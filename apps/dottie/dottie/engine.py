# Solo personal project, no connection to employer, built with public/free-tier only
"""DottieEngine — runs one task through the factory's REAL CodeAct loop and captures the trace.

The loop (``run_code_act``), sandbox, and reward components are imported from
``apps/ava-factory`` via the dottie-aware resolution in :mod:`dottie.resolve` (the same style
ava-open-harness uses for ``factory_root``); nothing is re-implemented here.

Every completed task appends one JSONL trace record to ``<data_dir>/traces/traces.jsonl``:
task id, timestamp, policy backend, prompt, sanitized FINAL, per-step trace (code + real
observation), termination reason, wall time, and reward components computed by the factory's
``codeact_rewards`` from the REAL observations.

Honesty notes:
  * Free-form prompts: ``r_task`` is recorded as ``null`` — open-ended assistant tasks have no
    automatic verifier, and Dottie never fabricates a task-success score. The components that
    ARE measurable from real execution logs (R_exec, R_codeuse, redundant_calls) are computed
    and recorded.
  * Verified tasks (``family``/``seed`` via :mod:`dottie.tasks`): ``r_task`` is computed by the
    task's deterministic verifier from the REAL final text and REAL observations, and the
    blended ``rl_return`` scalar is computed with the factory's ``codeact_return``. The length
    term is omitted (weight 0) because no historical family pass-rate stats exist yet — noted
    in the record rather than invented.
  * Skills (``use_skills=True``): memory recall is a REAL parent-side memory-router run whose
    output is injected as a labeled context block; bridged sandbox tools are extracted from
    the live skills and parity-checked (:mod:`dottie.skill_tools`). Unavailable skills raise —
    never a silent fake.
  * A policy that cannot run raises :class:`dottie.policy.DottiePolicyUnavailable` — the task
    fails honestly; no trace is invented.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dottie import resolve
from dottie.policy import get_policy
from dottie.tasks import VerifiedTask, VerifiedTaskProvider

TRACE_SCHEMA_VERSION = "1.0.0"

# Safe, deterministic, network-free tools bound into the sandbox via tool_sources (the
# sandbox additionally always binds get_clock()). Pure functions only — the sandbox itself
# enforces no-network / no-outside-writes regardless.
DEFAULT_TOOL_SOURCES: dict[str, str] = {
    "word_count": "def word_count(text):\n    return len(str(text).split())\n",
    "char_count": "def char_count(text):\n    return len(str(text))\n",
    "reverse_text": "def reverse_text(text):\n    return str(text)[::-1]\n",
}

_STDOUT_EXCERPT = 1000
_ERROR_EXCERPT = 500


def default_data_dir() -> Path:
    """``DOTTIE_DATA_DIR`` env, else ``apps/dottie/data`` (gitignored)."""
    env = os.environ.get("DOTTIE_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


class DottieEngine:
    """Task runner + trace capture over the factory's real CodeAct machinery."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.traces_dir = self.data_dir / "traces"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.traces_path = self.traces_dir / "traces.jsonl"

    # -- prompt composition -------------------------------------------------------
    @staticmethod
    def compose_prompt(
        prompt: str,
        extra_tool_names: list[str] | None = None,
        context: str | None = None,
    ) -> str:
        """The task prompt plus an honest statement of the sandbox contract and bound tools.

        ``extra_tool_names`` are display signatures for task/skill tools bound beyond the
        defaults; ``context`` is a clearly labeled pre-task block (e.g. real memory recall)."""
        tool_names = ["get_clock()"] + [f"{n}(text)" for n in DEFAULT_TOOL_SOURCES]
        tool_names += list(extra_tool_names or [])
        parts = []
        if context:
            parts.append(context)
        parts.append(prompt)
        parts.append(
            f"(Sandbox tools available: {', '.join(tool_names)}. Emit one ```python block per "
            "turn to act; a turn with no code block is your FINAL answer.)"
        )
        return "\n\n".join(parts)

    # -- core ---------------------------------------------------------------------
    def run_task(
        self,
        prompt: str | None = None,
        *,
        backend: str | None = None,  # None -> DOTTIE_POLICY env, else "ollama"
        max_steps: int = 8,
        timeout_s: float = 5.0,
        task_id: str | None = None,
        family: str | None = None,
        seed: int = 0,
        use_skills: bool = False,
    ) -> dict[str, Any]:
        """Run one task end-to-end; returns (and appends to the trace log) the trace record.

        Exactly one of ``prompt`` (free-form; ``r_task`` stays null with an honest note) or
        ``family`` (+ ``seed``: a :mod:`dottie.tasks` verified task; ``r_task`` computed by its
        deterministic verifier from the real final/observations) must be given.

        Raises ``DottiePolicyUnavailable`` if the backend cannot run, ``ValueError`` for an
        unknown backend/family or bad arguments, and ``DottieSkillsUnavailable`` if
        ``use_skills=True`` but ava-skills cannot really run — all surfaced to the caller,
        never masked with a fake result."""
        task: VerifiedTask | None = None
        if family is not None:
            if prompt is not None:
                raise ValueError("pass either prompt or family, not both")
            task = VerifiedTaskProvider().build(family, seed)
            base_prompt = task.prompt
        else:
            if not prompt or not prompt.strip():
                raise ValueError("prompt must be a non-empty string")
            base_prompt = prompt
        if backend is None:
            backend = os.environ.get("DOTTIE_POLICY", "ollama")
        resolve.ensure_factory_on_path()
        # --- TECH DEBT FIX: ava.rl was package-shim that broke submodule imports
        # Try canonical ava path, then dottie local mirror, then honest error
        try:
            from ava.rl.codeact_loop import run_code_act
            from ava.rl.codeact_rewards import (
            ReturnWeights,
            codeact_return,
            r_codeuse,
            r_exec,
            redundant_calls,
            )
        except (ModuleNotFoundError, ImportError):
            try:
                # local factory mirror (apps/ava-factory/dottie/rl) is on sys.path via resolve
                from dottie.rl.codeact_loop import run_code_act  # type: ignore
                from dottie.rl.codeact_rewards import ReturnWeights, codeact_return, r_codeuse, r_exec, redundant_calls  # type: ignore
            except (ModuleNotFoundError, ImportError):
                # final fallback: try ava-factory path directly via package dottie.rl.* shim we provide
                from ava.rl.codeact_loop import run_code_act  # will raise honest
                from ava.rl.codeact_rewards import ReturnWeights, codeact_return, r_codeuse, r_exec, redundant_calls

        tool_sources: dict[str, str] = dict(DEFAULT_TOOL_SOURCES)
        extra_tool_names: list[str] = []
        if task is not None:
            for name in task.tool_sources:
                if name in tool_sources:
                    raise ValueError(f"task tool {name!r} collides with a default tool")
            tool_sources.update(task.tool_sources)
            extra_tool_names += list(task.tool_names)

        skills_info: dict[str, Any] | None = None
        context: str | None = None
        if use_skills:
            from dottie import skill_tools

            recall = skill_tools.memory_recall(
                base_prompt, store_dir=self.data_dir / "memory_shards"
            )
            context = skill_tools.render_recall_context(recall)
            bridged = skill_tools.sandbox_skill_tool_sources()
            bridged["recalled_memories"] = skill_tools.recall_snapshot_source(
                recall["recalled"]
            )
            for name in bridged:
                if name in tool_sources:
                    raise ValueError(
                        f"bridged skill tool {name!r} collides with a bound tool"
                    )
            tool_sources.update(bridged)
            extra_tool_names += [
                skill_tools.BRIDGED_TOOL_SIGNATURES[n]
                for n in skill_tools.BRIDGED_TOOL_SIGNATURES
            ] + ["recalled_memories()"]
            skills_info = {
                "memory_recall": recall,
                "bridged_tools": sorted(bridged),
                "note": (
                    "memory recall ran parent-side (real memory-router); bridged tools "
                    "are source-extracted from live skills and parity-checked; "
                    "recalled_memories() is a labeled snapshot of the real recall"
                ),
            }

        policy = get_policy(backend)
        task_id = task_id or uuid.uuid4().hex[:12]
        ts = time.time()
        t0 = time.monotonic()
        result = run_code_act(
            policy,
            self.compose_prompt(base_prompt, extra_tool_names, context),
            tool_sources=tool_sources,
            max_steps=max_steps,
            timeout_s=timeout_s,
        )
        wall_s = time.monotonic() - t0

        obs = result.observations

        # Reward components: measurable-from-execution values always; r_task only when a real
        # verifier exists (verified tasks), else null with the honest note (never invented).
        components: dict[str, Any] = {
            "r_exec": r_exec(obs),
            "r_codeuse": r_codeuse(obs),
            "redundant_calls": redundant_calls(obs),
        }
        if task is not None:
            if result.reached_final:
                r_task = task.verify(result.final, obs)
                r_task_note = (
                    f"verified: family={task.family_id} seed={task.seed} "
                    f"deterministic verifier ({task.grading})"
                )
            else:
                r_task = 0.0
                r_task_note = (
                    f"verified failure: no FINAL emitted "
                    f"(terminated={result.terminated})"
                )
            components["r_task"] = r_task
            components["r_task_note"] = r_task_note
            # Blended scalar via the factory's real codeact_return. w_len=0: no historical
            # family pass-rate stats exist yet, so the length term is omitted, not invented.
            components["rl_return"] = codeact_return(
                r_task,
                obs,
                token_count=0,
                family_pass_rate=1.0,
                weights=ReturnWeights(w_task=1.0, w_exec=0.2, w_codeuse=0.2, w_len=0.0),
            )
            components["rl_return_note"] = (
                "w_task=1.0 w_exec=0.2 w_codeuse=0.2; "
                "r_len omitted (no family pass-rate history)"
            )
        else:
            components["r_task"] = None
            components["r_task_note"] = (
                "unscored: no automatic verifier for open-ended tasks"
            )

        record: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "task_id": task_id,
            "ts": ts,
            "backend": policy.name,
            "plumbing_only": bool(policy.plumbing_only),
            "prompt": base_prompt,
            "final": result.final,
            "terminated": result.terminated,
            "reached_final": result.reached_final,
            "n_steps": len(result.steps),
            "wall_s": round(wall_s, 3),
            "steps": [
                {
                    "code": s.code,
                    "ok": s.observation.ok,
                    "stdout": s.observation.stdout[:_STDOUT_EXCERPT],
                    "value": s.observation.value,
                    "error": (s.observation.error or "")[:_ERROR_EXCERPT] or None,
                    "wall_ms": s.observation.wall_ms,
                    "tool_calls": s.observation.tool_calls,
                }
                for s in result.steps
            ],
            # Real reward components from the REAL observations (factory codeact_rewards);
            # r_task per the verified/free-form contract documented above.
            "reward_components": components,
        }
        if task is not None:
            record["verified_task"] = task.verifier_detail()
        if skills_info is not None:
            record["skills"] = skills_info
        # Cross-surface persistence: the same J-Space store scout's profiles use
        # (channel "engine"); unavailable => recorded honestly, never a dependency.
        import os as _os

        from dottie import jspace_state

        outcome = "ok" if record.get("final") is not None else "failed"
        record["jspace_state"] = jspace_state.record_task(
            _os.environ.get("DOTTIE_SESSION", "engine"),
            (base_prompt or "")[:200],
            outcome,
            trace={"task_id": record.get("task_id"), "backend": backend},
        )
        self._append_trace(record)
        return record

    # -- trace log ----------------------------------------------------------------
    def _append_trace(self, record: dict[str, Any]) -> None:
        with self.traces_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def iter_traces(self):
        """Yield every recorded trace (skipping any partially-written line)."""
        if not self.traces_path.exists():
            return
        with self.traces_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def trace_count(self) -> int:
        return sum(1 for _ in self.iter_traces())
