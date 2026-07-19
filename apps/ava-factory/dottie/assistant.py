"""Dottie — the Hermes/OpenClaw-style server-side assistant (spec 15 §5).

A ReAct tool loop over ``ServeEngine.generate`` that is, by construction:

  * **grounded** — it calls read-only tools and answers from their Observations,
    the behavior the tool-use curriculum (spec 15 §4) trains;
  * **trust-gated** — every tool call passes ``ava.trust.ToolRegistry.check``
    *before* dispatch; an undeclared tool or a path escaping the sandbox is
    denied and the denial is fed back as an Observation (teaching the model the
    boundary at inference the same way L4 teaches it at train time);
  * **telemetered** — every step emits one ``ava.trust`` event, so the whole
    trajectory is reconstructable after the fact.

The loop is engine-agnostic: it takes a ``generate_fn(prompt, max_tokens,
temperature) -> str`` so tests can drive it with a scripted model and the server
can pass a real ``ServeEngine``. When the engine is absent
(``AVA_SKIP_ENGINE_BOOT=1``) the caller gets a clean structured refusal, never a
crash — same discipline as ``/chat``.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dottie.trust import ToolRegistry, default_registry, emit_event

USER = "<|user|>"
ASSISTANT = "<|assistant|>"

# Same turn-boundary specials the trainer/serve use; generation is truncated at
# the first one because the engine has no early stop.
_TURN_END_RE = re.compile(r"<\|eos\|>|<\|user\|>|<\|assistant\|>")
# Byte-identical to the production parser (AgenticOS/ava_bridge.py::_ACTION_RE).
_ACTION_RE = re.compile(r"Action:\s*([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)\s*$", re.M)

# The persona. No system special token exists (frozen tokenizer), so this rides
# in as leading <|user|> framing — consistent with how the model was trained.
PERSONA = (
    "You are Dottie, a careful tool-using assistant. You prefer to check with a "
    "tool over guessing, you answer from the tool's Observation rather than from "
    "memory, and when a tool returns nothing or errors you say so plainly instead "
    "of fabricating. To use a tool, write a line 'Action: tool_name(args)'. When "
    "you have the answer, give it directly with no Action line. Do not call "
    "destructive tools; decline and explain instead."
)


# ---------------------------------------------------------------------------
# Action-argument parsing (self-contained; mirrors ava_bridge but does not
# depend on the sibling repo being present at serve time).
# ---------------------------------------------------------------------------

def parse_action(text: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Return (tool, args) for the first Action line, or None if there is none."""
    m = _ACTION_RE.search(text)
    if not m:
        return None
    return m.group(1), _parse_args(m.group(2))


# Split a list body on commas that are NOT inside quotes, so "1,000" survives.
_LIST_ITEM = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^,]+')


def _parse_args(argstr: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    # Extract ALL name=[...] list groups first (each may contain commas). Using
    # re.sub with a side-effecting replacer both records the list and removes it
    # from argstr so the scalar pass below doesn't re-parse its insides.
    def _take_list(m: "re.Match[str]") -> str:
        args[m.group(1)] = [_coerce(x.strip()) for x in _LIST_ITEM.findall(m.group(2)) if x.strip()]
        return ""

    argstr = re.sub(r"([a-zA-Z_]\w*)\s*=\s*\[([^\]]*)\]", _take_list, argstr)
    # Scalars. The number branch is anchored (lookahead for a comma or end) so a
    # value like 2024.01.05/log.txt isn't truncated to its numeric prefix.
    for m in re.finditer(
        r'([a-zA-Z_]\w*)\s*=\s*'
        r'("(?:[^"\\]|\\.)*"|\'[^\']*\'|-?\d+(?:\.\d+)?(?=\s*(?:,|$))|[^,]+)',
        argstr,
    ):
        key = m.group(1)
        if key in args:
            continue
        args[key] = _coerce(m.group(2).strip())
    return args


def _coerce(tok: str) -> Any:
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
        return tok[1:-1]
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        return tok


# ---------------------------------------------------------------------------
# Tool executor — read-only, sandboxed implementations. Names mirror the
# training distribution so inference matches what the model saw.
# ---------------------------------------------------------------------------


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, sandbox_root: Optional[Path] = None,
                 clock: Optional[Callable[[], str]] = None):
        self.registry = registry
        self.root = (sandbox_root or Path.cwd()).resolve()
        self._clock = clock

    def run(self, tool: str, args: dict[str, Any]) -> tuple[str, str]:
        """Return (observation, status). Never raises — a tool failure becomes
        an ``Error:`` Observation so the loop can teach/observe recovery."""
        fn = getattr(self, f"_t_{tool}", None)
        if fn is None:
            return f"Error: no executor for tool '{tool}'", "error"
        try:
            out = fn(args)
        except Exception as exc:  # tool errors are Observations, not crashes
            return f"Error: {type(exc).__name__}: {exc}", "error"
        return self.registry.clip(tool, out), "ok"

    # -- filesystem (sandboxed) --------------------------------------------
    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
        p.relative_to(self.root)  # raises ValueError on escape -> becomes Error obs
        return p

    def _t_repo_read_file(self, args) -> str:
        p = self._resolve(str(args.get("path", "")))
        if not p.is_file():
            return "(file not found)"
        return p.read_text(encoding="utf-8", errors="replace")

    def _t_repo_grep(self, args) -> str:
        pat = str(args.get("pattern", ""))
        p = self._resolve(str(args.get("path", "")))
        if not p.is_file():
            return "(file not found)"
        n = p.read_text(encoding="utf-8", errors="replace").count(pat)
        return f"{n} matches" if n else "(no matches)"

    def _t_list_dir(self, args) -> str:
        p = self._resolve(str(args.get("path", "")))
        if not p.is_dir():
            return "(directory not found)"
        entries = sorted(x.name for x in p.iterdir())
        return ", ".join(entries) if entries else "(empty)"

    # -- arithmetic --------------------------------------------------------
    def _t_add(self, args) -> str:
        return str(_num(args.get("a")) + _num(args.get("b")))

    def _t_subtract(self, args) -> str:
        return str(_num(args.get("a")) - _num(args.get("b")))

    def _t_multiply(self, args) -> str:
        return str(_num(args.get("a")) * _num(args.get("b")))

    def _t_sum(self, args) -> str:
        vals = args.get("values") or []
        return str(sum(_num(v) for v in vals))

    # -- introspection -----------------------------------------------------
    def _t_get_clock(self, args) -> str:
        if self._clock:
            return self._clock()
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _t_pipeline_status(self, args) -> str:
        try:
            from dottie.pipeline_status import collect_status
            s = collect_status(preset=None)
        except Exception as exc:
            return f"(pipeline status unavailable: {type(exc).__name__})"
        keys = ("trainer_phase", "target_phase", "paused", "data_starved", "tokens_ready")
        parts = [f"{k}={s.get(k)}" for k in keys if k in s]
        return "; ".join(parts) or "(no status fields)"

    def _t_ecosystem_status(self, args) -> str:
        try:
            from dottie.ecosystem_status import collect_ecosystem_status
            s = collect_ecosystem_status()
        except Exception as exc:
            return f"(ecosystem status unavailable: {type(exc).__name__})"
        return "; ".join(f"{k}={'present' if s.get(k) else 'absent'}"
                         for k in ("agenticos", "skills", "agent_eval"))

    def _t_skill_search(self, args) -> str:
        query = str(args.get("query", "")).lower()
        skills = ("commit", "commit-push-pr", "code-review", "dataviz", "schedule", "pdf")
        hit = next((s for s in skills if s in query or any(w in s for w in query.split())), None)
        return f'found skill "{hit}"' if hit else "(no matching skills)"


def _num(v: Any) -> float:
    if isinstance(v, bool):
        raise ValueError("boolean is not a number")
    if isinstance(v, (int, float)):
        return v
    return float(str(v))


# ---------------------------------------------------------------------------
# The loop.
# ---------------------------------------------------------------------------


@dataclass
class Step:
    thought: str
    action: Optional[str]
    args: dict[str, Any]
    observation: Optional[str]
    gate: str  # "ok" | "denied" | "n/a"
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "thought": self.thought, "action": self.action, "args": self.args,
            "observation": self.observation, "gate": self.gate, "status": self.status,
        }


@dataclass
class AssistantResult:
    content: str
    steps: list[Step] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    refused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "steps": [s.as_dict() for s in self.steps],
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "refused": self.refused,
        }


def _build_prompt(messages: list[dict[str, str]], registry: ToolRegistry) -> str:
    catalog = "\n".join(
        f"- {c['signature']} — {c['description']}" for c in registry.catalog()
    )
    preamble = f"{PERSONA}\n\nAvailable tools:\n{catalog}"
    parts = [f"{USER}\n{preamble}"]
    for m in messages:
        marker = USER if m.get("role") != "assistant" else ASSISTANT
        parts.append(f"{marker}\n{m.get('content', '')}")
    parts.append(ASSISTANT)  # cue the model to continue as the assistant
    return "\n".join(parts) + "\n"


def _split_thought_action(text: str) -> tuple[str, str]:
    """Return (visible_text_without_action_line, action_line_or_empty)."""
    m = _ACTION_RE.search(text)
    if not m:
        return text.strip(), ""
    return (text[: m.start()].strip(), m.group(0).strip())


def run_assistant(
    messages: list[dict[str, str]],
    generate_fn: Callable[[str, int, float], str],
    *,
    registry: Optional[ToolRegistry] = None,
    executor: Optional[ToolExecutor] = None,
    sandbox_root: Optional[Path] = None,
    max_steps: int = 4,
    max_tokens: int = 160,
    temperature: float = 0.7,
    actor: str = "anon",
    audit_path: Optional[Path] = None,
) -> AssistantResult:
    """Drive the ReAct tool loop to a final answer, a step budget, or a refusal."""
    registry = registry or default_registry(sandbox_root)
    executor = executor or ToolExecutor(registry, sandbox_root)
    t0 = time.time()
    transcript = _build_prompt(messages, registry)
    result = AssistantResult(content="")
    emit_event("loop_start", target="assistant", actor=actor,
               args={"messages": len(messages), "max_steps": max_steps},
               audit_path=audit_path)

    for _ in range(max_steps):
        raw = generate_fn(transcript, max_tokens, temperature)
        gen = _TURN_END_RE.split(raw, maxsplit=1)[0].strip()
        result.tokens += len(gen.split())
        thought, action_line = _split_thought_action(gen)

        parsed = parse_action(gen)
        if parsed is None:
            # No tool call -> this is the final answer (or a refusal).
            result.content = gen
            result.refused = _looks_like_refusal(gen)
            result.steps.append(Step(thought=thought, action=None, args={},
                                     observation=None, gate="n/a",
                                     status="refused" if result.refused else "final"))
            emit_event("final", target="assistant", actor=actor,
                       args={"refused": result.refused}, status="ok",
                       audit_path=audit_path)
            break

        tool, args = parsed
        allowed, reason = registry.check(tool, args)
        if not allowed:
            observation = f"Error: {reason}"
            result.steps.append(Step(thought=thought, action=action_line, args=args,
                                     observation=observation, gate="denied", status="denied"))
            emit_event("gate_denied", target=tool, actor=actor, args=args,
                       status="denied", meta={"reason": reason}, audit_path=audit_path)
        else:
            observation, status = executor.run(tool, args)
            result.steps.append(Step(thought=thought, action=action_line, args=args,
                                     observation=observation, gate="ok", status=status))
            emit_event("tool_call", target=tool, actor=actor, args=args,
                       status=status, meta={"observation_len": len(observation)},
                       audit_path=audit_path)
        # Feed the Observation back as a user turn and continue.
        transcript += f"{gen}\n{USER}\nObservation: {observation}\n{ASSISTANT}\n"
    else:
        # Ran out of steps without a final answer.
        result.content = (result.steps[-1].observation if result.steps
                          else "I couldn't complete this within the step budget.")
        emit_event("budget_exhausted", target="assistant", actor=actor,
                   args={"max_steps": max_steps}, status="error", audit_path=audit_path)

    result.latency_ms = int((time.time() - t0) * 1000)
    return result


# First-person refusal phrases only. Deliberately excludes observation-describing
# strings like "doesn't exist"/"no matching" — those appear in legitimate
# grounded negative answers ("No, foo.py doesn't exist in the repo.") and must
# NOT flip the turn to refused=True (which would corrupt refusal-gated telemetry).
_REFUSAL_MARKERS = ("i won't", "i won’t", "i will not", "i can't", "i cannot",
                    "i'm not going to", "i decline", "won't run", "won't invent",
                    "not something i should")


def _looks_like_refusal(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _REFUSAL_MARKERS)


def engine_generate_fn(engine: Any) -> Callable[[str, int, float], str]:
    """Adapt a ``ServeEngine`` to the loop's ``generate_fn`` signature."""
    def _fn(prompt: str, max_tokens: int, temperature: float) -> str:
        out = engine.generate(prompt, max_tokens=max_tokens, temperature=temperature,
                              task_type="chat")
        return out.get("text", "") if isinstance(out, dict) else str(out)
    return _fn
