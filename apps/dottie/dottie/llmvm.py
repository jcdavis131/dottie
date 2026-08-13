# Solo personal project, no connection to employer, built with public/free-tier only
"""
Dottie + llmvm — LLMVM-inspired interleaved execution adapter for Dottie.
v2 hardened: chunking + map-reduce + forge helper discovery + guard/JIT compile.

llmvm insight (9600dev/llmvm):
  Traditional tool-call API: User -> LLM picks function -> host runs -> return.
  llmvm: allow LLM to interleave natural language and code (<helpers> blocks),
  execute statement-by-statement in a persistent Python runtime, with helpers
  that let the LLM call itself recursively to overcome context limits.

This module ports the core ideas to Dottie without breaking zero_deps:

  * Continuation-passing execution: Query -> NL + <helpers> interleaved -> execute
    -> replace block with <helpers_result> -> ask LLM to continue -> final.
  * Helpers: llm_call, llm_list_bind, llm_bind, llm_var_bind, guard, result
    mapped to Dottie's existing rlm() + MissionLog.
  * Thread-to-program "compiler" — parameterizes successful traces,
    matching llmvm's `compile` command, feeding Dottie's flywheel.
  * CHUNKING (new): when context > 6k tokens, chunk 256 tok windows, keyword-rank,
    ask LLM if ALL required → map-reduce else top-N. Keeps context window intact.
  * FORGE DISCOVERY (new): scans apps/scout-cli/bigbang/plugins/*/cli.py +
    manifest.yaml, injects as discoverable tools into _globals.

It reuses Dottie's existing Policy interface (transcript -> next turn) so no
new network dep. Heavy llmvm deps (playwright, pdf, yfinance, etc.) remain
optional.

Usage:
    from dottie.llmvm import LLMVMRuntime, make_llmvm_environment
    rt = LLMVMRuntime(mission=mission_log, policy=policy)
    final = rt.run("go to https://ten13.vc/team and extract names", max_continuations=8)
"""

from __future__ import annotations

import ast
import json
import math
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dottie.policy import PolicyProvider

# ---------------------------------------------------------------------------
# Block parsing — supports both llmvm <helpers> and Dottie ```python fences
# ---------------------------------------------------------------------------

HELPERS_RE = re.compile(r"<helpers>(.*?)</helpers>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
STOP_TOKENS = ("</complete>", "FINAL:", "<|complete|>")

# ---------------------------------------------------------------------------
# Token estimation + chunking (zero_deps, no tiktoken)
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: max(words, chars//4). Good enough for chunk decisions."""
    if not text:
        return 0
    words = len(text.split())
    chars = len(text) // 4
    return max(words, chars, 1)

def _chunk_text(text: str, chunk_tokens: int = 256, overlap_tokens: int = 32) -> List[str]:
    """
    Simple sentence-aware chunking ~256 tokens, ~32 overlap, zero_deps.
    Roughly 950-1100 chars per chunk.
    """
    if not text:
        return []
    # Approximate char budget
    char_per_token = 4
    char_budget = chunk_tokens * char_per_token
    overlap_chars = overlap_tokens * char_per_token

    # Split on sentence boundaries for coherence
    sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', text)
    chunks: List[str] = []
    cur = ""
    for sent in sentences:
        if not sent.strip():
            continue
        if len(cur) + len(sent) + 1 <= char_budget:
            cur = (cur + " " + sent).strip() if cur else sent.strip()
        else:
            if cur:
                chunks.append(cur)
            # If single sentence > budget, hard-split
            if len(sent) > char_budget:
                # hard split with overlap sliding
                start = 0
                while start < len(sent):
                    end = start + char_budget
                    chunks.append(sent[start:end])
                    if end >= len(sent):
                        break
                    start = end - overlap_chars
                cur = ""
            else:
                cur = sent.strip()
    if cur:
        chunks.append(cur)

    # If text was not sentence-splittable (e.g., code), fallback sliding window
    if not chunks and len(text) > char_budget:
        chunks = []
        start = 0
        while start < len(text):
            end = start + char_budget
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap_chars

    if not chunks:
        chunks = [text]

    return chunks

def _keyword_rank(query: str, instruction: str, chunks: List[str]) -> List[Tuple[int, float, str]]:
    """
    Simple keyword overlap ranking mimicking llmvm's faiss rank stage.
    Returns list of (idx, score, chunk) sorted desc score.
    """
    q_tokens = set((query + " " + instruction).lower().split())
    q_tokens = set(t.strip(".,;:!?()[]\"'") for t in q_tokens if len(t) > 2)
    q_tokens = {t for t in q_tokens if t}

    scored = []
    for i, ch in enumerate(chunks):
        ch_tokens = set(ch.lower().split())
        ch_tokens = {t.strip(".,;:!?()[]\"'") for t in ch_tokens if len(t) > 2}
        if not q_tokens:
            score = 0.0
        else:
            inter = len(q_tokens & ch_tokens)
            union = len(q_tokens | ch_tokens) or 1
            jacc = inter / union
            # Bonus for rare token overlap (tf-ish)
            inter_ratio = inter / (len(q_tokens) or 1)
            score = 0.6 * inter_ratio + 0.4 * jacc
            # Small random jitter to avoid pathological ties (llmvm random sample analog)
            score += random.random() * 0.02
        scored.append((i, score, ch))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored

def _needs_all_chunks_heuristic(policy: Optional[PolicyProvider], original_query: str, instruction: str, sample_chunks: List[str]) -> bool:
    """
    Ask LLM if ALL content required — llmvm second stage.
    If policy unavailable, heuristic: if query contains words like compare, contrast, summarize all, aggregate, total → YES.
    """
    if not policy:
        triggers = {"all", "every", "compare", "contrast", "aggregate", "summarize", "total", "map-reduce", "across"}
        combined = (original_query + " " + instruction).lower()
        return any(w in combined for w in triggers)

    # Build small sample prompt (random 2-3 chunks as llmvm does)
    sample_txt = "\n\n---\n\n".join(c[:600] for c in sample_chunks[:3])
    prompt = (
        f"Original task: {original_query[:800]}\n"
        f"Instruction: {instruction[:600]}\n\n"
        f"Sample of document chunks ({len(sample_chunks)} total available):\n{sample_txt}\n\n"
        f"Question: Does achieving the instruction require seeing ALL chunks, or can it be done from just a few top chunks?\n"
        f"Answer with single word: YES if you need ALL chunks to be correct, NO if a few chunks suffice."
    )
    try:
        resp = policy(f"<|user|>\n{prompt}\n<|assistant|>\n").strip().upper()
        # Extract YES/NO
        if "YES" in resp.split()[:3] or resp.startswith("YES"):
            return True
        if "NO" in resp:
            return False
        # Fallback: if ambiguous, interpret conservatively
        return len(sample_chunks) > 8  # many chunks → need all?
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Forge helper discovery (zero_deps)
# ---------------------------------------------------------------------------

def _discover_forge_plugins() -> List[Dict[str, Any]]:
    """
    Scan apps/scout-cli/bigbang/plugins/*/cli.py + manifest.yaml
    Returns list of {name, cli_path, manifest, description, commands (if parseable)}
    Zero_deps: pure FS scan, no import.
    """
    # Resolve from this file's location
    here = Path(__file__).resolve()
    # Typical layout: apps/dottie/dottie/llmvm.py -> parents[2] = apps/
    candidates = [
        here.parents[1] / "scout-cli" / "bigbang" / "plugins",  # apps/dottie/dottie -> apps/dottie/scout-cli/...
        here.parents[2] / "scout-cli" / "bigbang" / "plugins",   # apps/dottie/.. -> apps/scout-cli/...
        Path.home() / "workspace" / "dottie" / "apps" / "scout-cli" / "bigbang" / "plugins",
        Path.home() / "workspace" / "dottie" / "apps" / "scout-cli" / "bigbang" / "plugins",
    ]
    plugins_root: Optional[Path] = None
    for cand in candidates:
        if cand.exists() and cand.is_dir():
            plugins_root = cand
            break
    if not plugins_root:
        return []

    discovered: List[Dict[str, Any]] = []
    for child in plugins_root.iterdir():
        if not child.is_dir():
            continue
        cli_path = child / "cli.py"
        if not cli_path.exists():
            continue
        manifest_path = child / "manifest.yaml"
        desc = ""
        if manifest_path.exists():
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                # quick parse without yaml dep: look for description: lines
                m = re.search(r'description\s*:\s*["\']?(.*?)["\']?\s*\n', text, re.IGNORECASE)
                if m:
                    desc = m.group(1).strip()[:300]
                else:
                    # first non-empty line after name
                    for line in text.splitlines():
                        if "description" in line.lower():
                            desc = line.split(":",1)[-1].strip().strip('"\'')[:300]
                            break
            except Exception:
                desc = ""
        # Try extract typer commands from cli.py shallow parse
        commands: List[str] = []
        try:
            src = cli_path.read_text(encoding="utf-8", errors="ignore")
            # find @app.command patterns
            cmds = re.findall(r'@app\.command.*?def\s+([a-z_][a-z0-9_]+)', src, re.DOTALL)
            commands = cmds[:12]
            if not commands:
                # fallback: def <name>( pattern near top level
                cmds2 = re.findall(r'def\s+([a-z_][a-z0-9_]+)\s*\(', src)
                commands = [c for c in cmds2 if not c.startswith("_")][:12]
        except Exception:
            commands = []

        discovered.append({
            "name": child.name,
            "cli_path": str(cli_path),
            "description": desc or f"{child.name} plugin (forge)",
            "commands": commands,
            "manifest_exists": manifest_path.exists(),
        })
    return sorted(discovered, key=lambda d: d["name"])

# Cache at import time (light)
_FORGE_PLUGINS_CACHE: List[Dict[str, Any]] = _discover_forge_plugins()

def list_forge_plugins() -> List[Dict[str, Any]]:
    return list(_FORGE_PLUGINS_CACHE)

# ---------------------------------------------------------------------------
# Core runtime
# ---------------------------------------------------------------------------

@dataclass
class ContinuationState:
    query: str
    turn_count: int = 0
    answers: List[Any] = field(default_factory=list)
    locals: Dict[str, Any] = field(default_factory=dict)
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    history: List[str] = field(default_factory=list)
    # chunking / token stats
    total_tokens_estimated: int = 0
    chunks_used: List[int] = field(default_factory=list)

class LLMVMRuntime:
    """
    Lightweight llmvm-style runtime for Dottie — v2 hardened.

    - Pluggable on top of any Dottie PolicyProvider (ollama/ava/echo)
    - Persistent locals dict (like IPython REPL) — variables survive across blocks
    - Helpers wired to Dottie's rlm() / MissionLog + forge plugin discovery
    - Chunking + map-reduce when context > 6k tokens
    """

    def __init__(
        self,
        policy: PolicyProvider,
        mission: Any | None = None,
        helpers: List[Callable] | None = None,
        enable_map_reduce: bool = True,
        max_context_tokens: int = 6000,
        chunk_tokens: int = 256,
    ):
        self.policy = policy
        self.mission = mission
        self.helpers = helpers or []
        self.enable_map_reduce = enable_map_reduce
        self.max_context_tokens = max_context_tokens
        self.chunk_tokens = chunk_tokens
        self.state = ContinuationState(query="")
        self._globals: Dict[str, Any] = {}
        self._forge_plugins = list_forge_plugins()

    # -- helpers exposed to LLM ------------------------------------------------
    def llm_call(self, expr_list: List[Any], instruction: str, original_query: Optional[str] = None) -> str:
        """
        llm_call(expression_list, instruction) -> str
        Packages exprs into LLM messages, performs instruction via sub-agent.
        Implements chunking fallback when token count > max_context_tokens.

        Maps to Dottie's rlm().
        """
        original_query = original_query or self.state.query or instruction[:400]
        # Flatten exprs to strings
        ctx_parts = [str(x) for x in expr_list if x is not None]
        full_ctx = "\n\n---\n\n".join(ctx_parts)
        total_tokens = _estimate_tokens(full_ctx) + _estimate_tokens(instruction) + _estimate_tokens(original_query)

        # If we have mission -> log subagent spawn (Dottie RLM pattern)
        sub_id = f"llmcall-{uuid.uuid4().hex[:6]}"
        if self.mission:
            try:
                from dottie.rlm import MissionEvent
                self.mission.append(MissionEvent(
                    ts=time.time(),
                    type="subagent_spawn",
                    agent_id=sub_id,
                    payload={
                        "prompt": instruction[:400],
                        "tier": "llm_medium",
                        "helper": "llm_call",
                        "tokens_est": total_tokens,
                        "chunked": total_tokens > self.max_context_tokens,
                    },
                ))
            except Exception:
                pass

        # Normal path — fits context
        if total_tokens <= self.max_context_tokens:
            prompt = f"Context:\n{full_ctx[:12000]}\n\nInstruction: {instruction}\n\nOriginal task: {original_query[:600]}"
            transcript = f"<|user|>\n{prompt}\n<|assistant|>\n"
            try:
                result = self.policy(transcript)
            except Exception as e:
                return f"[llm_call error: {e}]"
            result = result.strip()
            if result.startswith("FINAL:"):
                result = result[len("FINAL:"):].strip()
            return result

        # Chunking path — >6k tokens
        chunks = _chunk_text(full_ctx, chunk_tokens=self.chunk_tokens, overlap_tokens=32)
        ranked = _keyword_rank(original_query, instruction, chunks)

        # Decide if ALL needed (llmvm second stage)
        sample_chunks = [c for _,_,c in ranked[:5]] or chunks[:3]
        needs_all = _needs_all_chunks_heuristic(self.policy, original_query, instruction, sample_chunks)

        if not needs_all:
            # Take top N chunks fitting context
            budget = self.max_context_tokens - _estimate_tokens(instruction) - _estimate_tokens(original_query) - 400
            taken: List[str] = []
            used_tokens = 0
            used_idx: List[int] = []
            for idx, score, ch in ranked:
                tok = _estimate_tokens(ch)
                if used_tokens + tok > budget:
                    if taken:
                        break
                    # at least one chunk if none taken
                taken.append(ch)
                used_tokens += tok
                used_idx.append(idx)
                if used_tokens >= budget:
                    break
            self.state.chunks_used = used_idx[:20]
            prompt = (
                f"Context (top {len(taken)}/{len(chunks)} chunks, ranked by relevance to task):\n"
                + "\n\n---\n\n".join(taken)
                + f"\n\nInstruction: {instruction}\n\nOriginal task: {original_query[:600]}"
            )
            transcript = f"<|user|>\n{prompt}\n<|assistant|>\n"
            try:
                result = self.policy(transcript)
            except Exception as e:
                return f"[llm_call chunked error: {e}]"
            return result.strip().removeprefix("FINAL:").strip()

        # Map-Reduce path — all chunks needed
        if not self.enable_map_reduce:
            # Fallback to top-N even if says need all, if disabled
            top = [c for _,_,c in ranked[:8]]
            prompt = f"Context (first 8/{len(chunks)} chunks, map-reduce disabled):\n" + "\n\n---\n\n".join(top) + f"\n\nInstruction: {instruction}\n\nOriginal task: {original_query[:600]}"
            try:
                return self.policy(f"<|user|>\n{prompt}\n<|assistant|>\n").strip()
            except Exception as e:
                return f"[llm_call map-reduce disabled error: {e}]"

        # Map step
        map_results: List[str] = []
        for i, ch in enumerate(chunks):
            map_prompt = (
                f"Original task: {original_query[:500]}\n"
                f"Instruction: {instruction[:500]}\n\n"
                f"Chunk {i+1}/{len(chunks)} to process:\n{ch[:4000]}\n\n"
                f"Task: Perform the instruction on ONLY this chunk. Extract any partial results relevant to main task."
            )
            try:
                part = self.policy(f"<|user|>\n{map_prompt}\n<|assistant|>\n").strip()
                map_results.append(part[:1500])
            except Exception as e:
                map_results.append(f"[chunk {i} error: {e}]")
                continue

        # Reduce step
        combined = "\n\n====\n\n".join(f"Chunk {i+1} result: {r}" for i, r in enumerate(map_results))
        reduce_prompt = (
            f"Original task: {original_query[:600]}\n"
            f"Instruction: {instruction[:600]}\n\n"
            f"Map step produced {len(map_results)} partial results from chunked processing:\n{combined[:12000]}\n\n"
            f"Now reduce/combine into final answer for instruction. Be comprehensive, de-duplicate, synthesize."
        )
        try:
            final = self.policy(f"<|user|>\n{reduce_prompt}\n<|assistant|>\n").strip()
        except Exception as e:
            final = f"[reduce error: {e}] Fallback combine:\n" + combined[:4000]

        self.state.chunks_used = list(range(len(chunks)))
        return final

    def llm_list_bind(self, expression: Any, instruction: str) -> List[str]:
        raw = self.llm_call([expression], instruction + " Return ONLY as a JSON list or numbered list.")
        try:
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                lst = json.loads(m.group(0))
                if isinstance(lst, list):
                    return [str(x).strip() for x in lst]
        except Exception:
            pass
        items: List[str] = []
        for line in raw.splitlines():
            line = re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip()
            line = line.strip("-•* ").strip()
            if line:
                line = re.sub(r"^\W+", "", line).strip()
                if len(line) > 1:
                    items.append(line)
        seen = set()
        uniq = []
        for it in items:
            if it.lower() not in seen:
                seen.add(it.lower())
                uniq.append(it)
        return uniq[:80]

    def llm_bind(self, expression: Any, func_def_str: str) -> str:
        prompt = (
            f"Given value: {str(expression)[:1200]}\n"
            f"Target function signature: {func_def_str}\n"
            f"Bind arguments. If any arg cannot be bound, use None and append "
            f"# Question: what is needed to bind it?\n"
            f"Output ONLY the call, e.g. WebHelpers.search(\"Jane\",\"Doe\",\"Acme\")"
        )
        bound = self.llm_call([prompt], "bind arguments")
        return bound.splitlines()[0].strip()[:600]

    def llm_var_bind(self, expression: Any, var_name: str) -> str:
        return self.llm_bind(expression, f"{var_name}(value)")

    def guard(self, condition: str, expected_type: str = "") -> bool:
        try:
            val = eval(condition, {}, self.state.locals) if condition in self.state.locals else None
            if expected_type and not isinstance(str(type(val)), str):
                pass
            self.state.history.append(f"guard {condition} -> {val}")
            return True
        except Exception:
            self.state.history.append(f"guard {condition} failed -> recompile needed")
            return False

    def result(self, answer: Any) -> None:
        self.state.answers.append(answer)
        self.state.locals["_last_result"] = answer

    def coerce(self, value: Any, target_type: type) -> Any:
        try:
            return target_type(value)
        except Exception:
            return value

    # -- forge helper introspection ------------------------------------------
    def list_forge_tools(self) -> List[Dict[str, Any]]:
        """Return discovered forge plugins for LLM context."""
        return self._forge_plugins

    def _make_scout_stub(self):
        """Create a minimal scout() stub that lists available tools and simulates json calls."""
        plugins = self._forge_plugins

        def scout(*args, **kwargs) -> str:
            # Called as scout("search", ...) or scout("--json", "search", ...)
            if not args:
                return f"Available forge plugins ({len(plugins)}): " + ", ".join(p["name"] for p in plugins[:20])
            # Strip --json etc
            cmd = " ".join(str(a) for a in args)
            # Find matching plugin
            for p in plugins:
                if p["name"] in cmd:
                    return f"[scout stub] plugin={p['name']}, desc={p['description']}, commands={p['commands']}, cmd={cmd[:300]} — forge would exec this via bigbang"
            return f"[scout stub] Unknown plugin in '{cmd[:300]}'. Known: {', '.join(pp['name'] for pp in plugins[:12])}"
        scout._plugins = plugins  # type: ignore
        return scout

    # -- core execution helpers ------------------------------------------------
    @staticmethod
    def extract_helpers_blocks(llm_output: str) -> List[str]:
        blocks = HELPERS_RE.findall(llm_output)
        if blocks:
            return [b.strip() for b in blocks if b.strip()]
        fences = FENCE_RE.findall(llm_output)
        return [f.strip() for f in fences if f.strip()]

    @staticmethod
    def contains_result(output: str) -> bool:
        return "result(" in output.lower()

    @staticmethod
    def is_final(output: str, has_code: bool) -> bool:
        if has_code:
            return False
        out = output.strip()
        if any(tok.lower() in out.lower() for tok in STOP_TOKENS):
            return True
        return len(out) > 30

    def _make_helper_namespace(self) -> Dict[str, Any]:
        ns: Dict[str, Any] = {
            "__builtins__": __import__("builtins"),
            "llm_call": self.llm_call,
            "llm_list_bind": self.llm_list_bind,
            "llm_bind": self.llm_bind,
            "llm_var_bind": self.llm_var_bind,
            "guard": self.guard,
            "result": self.result,
            "coerce": self.coerce,
            # forge introspection
            "list_forge_plugins": self.list_forge_tools,
            "scout": self._make_scout_stub(),
            "forge_plugins": self._forge_plugins,
            # Dottie compat
            "download": lambda url: f"[download stub: no network in sandbox, url={url}]",
            "write_memory": lambda k,v: self.state.locals.update({f"mem_{k}": v}),
            "read_memory": lambda k: self.state.locals.get(f"mem_{k}"),
            "read_memory_keys": lambda: [k for k in self.state.locals if k.startswith("mem_")],
            "count_tokens": lambda texts: sum(_estimate_tokens(str(t)) for t in ([texts] if isinstance(texts, str) else texts)),
            "get_clock": lambda: __import__("time").time(),
            "word_count": lambda text: len(str(text).split()),
            "char_count": lambda text: len(str(text)),
            "reverse_text": lambda text: str(text)[::-1],
            "print": lambda *a, **kw: None,
            "_estimate_tokens": _estimate_tokens,
            "_chunk_text": _chunk_text,
        }
        # Inject persistent locals (but don't override helpers)
        for k, v in self.state.locals.items():
            if k not in ns:
                ns[k] = v
        # Inject user-provided helpers
        for h in self.helpers:
            try:
                if hasattr(h, "__name__") and h.__name__ not in ns:
                    ns[h.__name__] = h
            except AttributeError:
                pass
        self._globals = ns
        return ns

    def _exec_block(self, code: str) -> tuple[bool, str, Any]:
        ns = self._make_helper_namespace()
        try:
            tree = ast.parse(code)
            exec(compile(tree, "<helpers>", "exec"), ns)
            for k, v in ns.items():
                if k in ("__builtins__",):
                    continue
                if k.startswith("_") and k not in ("_last_result",):
                    continue
                if callable(v) and k in ("llm_call","llm_list_bind","llm_bind","guard","result","scout","list_forge_plugins"):
                    continue
                # Don't persist internal helpers but keep user vars
                if k in ("_estimate_tokens","_chunk_text","forge_plugins"):
                    continue
                self.state.locals[k] = v
            last_val = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                try:
                    last_val = ns.get("_", None)
                except Exception:
                    pass
            return True, "", last_val
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-1400:]
            return False, f"{type(e).__name__}: {e}\n{tb}", None

    def run(
        self,
        query: str,
        max_continuations: int = 10,
        enable_error_correction: bool = True,
    ) -> Dict[str, Any]:
        self.state = ContinuationState(query=query)
        self.state.locals.clear()

        transcript = f"<|user|>\n{query}\n<|assistant|>\n"
        final_answer = None
        turns = []

        for step in range(max_continuations):
            self.state.turn_count = step
            try:
                llm_output = self.policy(transcript)
            except Exception as e:
                turns.append({"step": step, "type": "policy_error", "error": str(e)})
                break

            self.state.history.append(llm_output[:4000])
            if self.mission:
                try:
                    from dottie.rlm import MissionEvent
                    self.mission.append(MissionEvent(
                        ts=time.time(),
                        type="turn",
                        agent_id="llmvm-rt",
                        payload={
                            "step": step,
                            "output": llm_output[:2000],
                            "tokens_est": _estimate_tokens(llm_output),
                            "forge_plugins": len(self._forge_plugins),
                        },
                    ))
                except Exception:
                    pass

            blocks = self.extract_helpers_blocks(llm_output)

            if not blocks:
                if self.contains_result(llm_output) or self.is_final(llm_output, has_code=False):
                    final_answer = llm_output
                    turns.append({"step": step, "type": "final", "text": llm_output})
                    break
                else:
                    transcript += llm_output + "\n<|user|>\nContinue. If you have executable steps, put them in <helpers>...</helpers>. When done call result(answer). Available forge tools: " + ", ".join(p["name"] for p in self._forge_plugins[:10]) + "\n<|assistant|>\n"
                    turns.append({"step": step, "type": "narrative_continue", "text": llm_output})
                    continue

            block_results = []
            had_error = False
            for b_idx, block in enumerate(blocks):
                ok, err, val = self._exec_block(block)
                if not ok:
                    had_error = True
                    block_results.append({"block": b_idx, "ok": False, "error": err, "code": block[:900]})
                    if self.mission:
                        try:
                            from dottie.rlm import MissionEvent
                            self.mission.append(MissionEvent(
                                ts=time.time(),
                                type="tool_call",
                                agent_id=f"llmvm-block-{step}-{b_idx}",
                                payload={"error": err[:500], "code": block[:500]},
                            ))
                        except Exception:
                            pass
                    if enable_error_correction:
                        fix_prompt = (
                            f"The previous <helpers> block failed:\n```python\n{block[:1300]}\n```\n"
                            f"Error:\n{err[:900]}\n"
                            f"Locals now: {list(self.state.locals.keys())[:18]}\n"
                            f"Forge plugins available: {[p['name'] for p in self._forge_plugins[:8]]}\n"
                            f"Fix the block. Output ONLY corrected <helpers> block."
                        )
                        transcript += (
                            llm_output + f"\n<|user|>\n<helpers_result>Error: {err[:600]}</helpers_result>\n"
                            f"{fix_prompt}\n<|assistant|>\n"
                        )
                        turns.append({"step": step, "type": "error_correct", "error": err, "block_idx": b_idx})
                    break
                else:
                    block_results.append({"block": b_idx, "ok": True, "code": block[:900], "val": str(val)[:500] if val is not None else None})

            if had_error and enable_error_correction:
                continue

            if self.state.answers:
                final_answer = self.state.answers[-1]
                turns.append({"step": step, "type": "result", "answers": self.state.answers, "blocks": block_results, "text": llm_output})
                if len(self.state.answers) == 1:
                    transcript += (
                        llm_output + "\n<|user|>\n<highlights>\n"
                        f"Result captured. Summarize final answer using the result value. End with FINAL.\n"
                        f"</highlights>\n<|assistant|>\n"
                    )
                    try:
                        summary = self.policy(transcript)
                        if summary.strip():
                            final_answer = summary if not self.state.answers else final_answer
                            turns.append({"step": step+1, "type": "summary", "text": summary})
                    except Exception:
                        pass
                break

            injected = "\n".join(
                f"<helpers_result>Block {i} ok: {r.get('val') or 'executed'}</helpers_result>"
                for i, r in enumerate(block_results)
            )
            transcript += llm_output + f"\n{injected}\n<|assistant|>\n"
            turns.append({"step": step, "type": "continuation", "blocks": block_results, "text": llm_output})

            if step >= max_continuations - 1:
                final_answer = final_answer or llm_output
                break

        return {
            "query": query,
            "final": str(final_answer)[:9000] if final_answer is not None else None,
            "answers": self.state.answers,
            "locals": {k: str(v)[:1400] for k, v in self.state.locals.items() if not k.startswith("mem_")},
            "turns": turns,
            "thread_id": self.state.thread_id,
            "n_steps": len(turns),
            "chunks_used": self.state.chunks_used,
            "forge_plugins_discovered": len(self._forge_plugins),
            "mission_id": getattr(self.mission, "mission_id", None),
        }

# ---------------------------------------------------------------------------
# Thread-to-program compiler (llmvm `compile` command)
# ---------------------------------------------------------------------------

def compile_thread_to_program(
    thread_history: List[Dict[str, Any]],
    policy: PolicyProvider,
    program_name: str = "compiled_program",
) -> str:
    thread_str = "\n\n".join(
        f"Step {i}: {str(t)[:1200]}" for i, t in enumerate(thread_history[-10:])
    )
    prompt = (
        f"You are llmvm compiler. Convert this message thread into a reusable Python program.\n"
        f"Name: {program_name}\n\n"
        f"Thread:\n{thread_str}\n\nRequirements:\n"
        f"- Parameterize specific values (symbols, tickers, names) into function args\n"
        f"- Split into small functions (download, extract, summarize, etc.)\n"
        f"- Lift out calls to llm_call if pure code can do it\n"
        f"- Add guard(var_name, expected_type) checks at top of each specialized function\n"
        f"- If guard fails, return {{'recompile_needed': True, 'reason': ...}}\n"
        f"- Output ONLY python code with def {program_name}(...):\n"
    )
    try:
        out = policy(f"<|user|>\n{prompt}\n<|assistant|>\n")
        m = FENCE_RE.search(out)
        if m:
            return m.group(1).strip()
        return out.strip()[:7000]
    except Exception as e:
        return f"# compile failed: {e}\n\ndef {program_name}(*args, **kwargs):\n    return {{'error': 'compile failed'}}"

# ---------------------------------------------------------------------------
# Factory helper — makes llmvm helpers available inside Dottie REPL
# ---------------------------------------------------------------------------

def make_llmvm_environment(mission=None, policy=None) -> Dict[str, Any]:
    rt = LLMVMRuntime(policy=policy, mission=mission) if policy else None

    def rlm_llmvm(prompt: str, **kw) -> Any:
        if rt:
            return rt.llm_call([prompt], kw.get("instruction", prompt))
        return f"[llmvm rlm stub] {prompt}"

    env: Dict[str, Any] = {
        "llmvm": rt,
        "llm_call": rt.llm_call if rt else lambda *a, **kw: "[no policy]",
        "llm_list_bind": rt.llm_list_bind if rt else lambda *a, **kw: [],
        "llm_bind": rt.llm_bind if rt else lambda *a, **kw: "",
        "guard": rt.guard if rt else lambda *a, **kw: True,
        "result": rt.result if rt else lambda *a, **kw: None,
        "compile_thread": lambda hist, name="prog": compile_thread_to_program(hist, policy, name) if policy else "",
        "MissionLog": mission.__class__ if mission else None,
        "list_forge_plugins": rt.list_forge_tools if rt else lambda: [],
        "forge_plugins": rt._forge_plugins if rt else [],
        "_estimate_tokens": _estimate_tokens,
        "_chunk_text": _chunk_text,
    }
    return env

# ---------------------------------------------------------------------------
# Pause/Resume helper for MissionLog
# ---------------------------------------------------------------------------

def resume_mission_log(mission_id: str, base_dir: Optional[Path] = None) -> Tuple[Any, List[Dict[str, Any]]]:
    """
    Resume a mission days later from timeline.jsonl — Scout v5 Prime contract.

    Returns (MissionLog, list_of_events) — MissionLog is already opened at existing path.
    Usage:
        mission, events = resume_mission_log("dottie-20260807T103003Z")
        # continue loop using same mission_dir, events intact
    """
    from dottie.rlm import MissionLog
    mission = MissionLog(mission_id=mission_id, base_dir=base_dir)
    events: List[Dict[str, Any]] = []
    # Count existing + parse
    for ev in mission.iter_events():
        events.append(ev)
    return mission, events

def latest_mission_state(mission_id: str, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Lightweight resume snapshot — last N events + locals if stored."""
    mission, events = resume_mission_log(mission_id, base_dir=base_dir)
    last = events[-1] if events else {}
    return {
        "mission_id": mission.mission_id,
        "mission_dir": str(mission.mission_dir),
        "timeline_path": str(mission.timeline_path),
        "event_count": len(events),
        "last_event_ts": last.get("ts"),
        "last_event_type": last.get("type") if isinstance(last, dict) else last.get("payload",{}).get("type") if isinstance(last, dict) else None,
    }

