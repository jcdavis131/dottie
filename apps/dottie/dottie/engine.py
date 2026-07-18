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
  * ``r_task`` is recorded as ``null``: open-ended assistant tasks have no automatic verifier,
    and Dottie never fabricates a task-success score. The components that ARE measurable from
    real execution logs (R_exec, R_codeuse, redundant_calls) are computed and recorded.
  * A policy that cannot run raises :class:`dottie.policy.DottiePolicyUnavailable` — the task
    fails honestly; no trace is invented.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from dottie import resolve
from dottie.policy import get_policy

TRACE_SCHEMA_VERSION = "1.0.0"

# Safe, deterministic, network-free tools bound into the sandbox via tool_sources (the
# sandbox additionally always binds get_clock()). Pure functions only — the sandbox itself
# enforces no-network / no-outside-writes regardless.
DEFAULT_TOOL_SOURCES: Dict[str, str] = {
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

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.traces_dir = self.data_dir / "traces"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.traces_path = self.traces_dir / "traces.jsonl"

    # -- prompt composition -------------------------------------------------------
    @staticmethod
    def compose_prompt(prompt: str) -> str:
        """The task prompt plus an honest statement of the sandbox contract and bound tools."""
        tool_names = ["get_clock()"] + [f"{n}(text)" for n in DEFAULT_TOOL_SOURCES]
        return (
            f"{prompt}\n\n"
            f"(Sandbox tools available: {', '.join(tool_names)}. Emit one ```python block per "
            "turn to act; a turn with no code block is your FINAL answer.)"
        )

    # -- core ---------------------------------------------------------------------
    def run_task(
        self,
        prompt: str,
        *,
        backend: str = "ollama",
        max_steps: int = 8,
        timeout_s: float = 5.0,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one task end-to-end; returns (and appends to the trace log) the trace record.

        Raises ``DottiePolicyUnavailable`` if the backend cannot run and ``ValueError`` for an
        unknown backend — both surfaced to the caller, never masked with a fake result."""
        if not prompt or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        resolve.ensure_factory_on_path()
        from ava.rl.codeact_loop import run_code_act
        from ava.rl.codeact_rewards import r_codeuse, r_exec, redundant_calls

        policy = get_policy(backend)
        task_id = task_id or uuid.uuid4().hex[:12]
        ts = time.time()
        t0 = time.monotonic()
        result = run_code_act(
            policy,
            self.compose_prompt(prompt),
            tool_sources=dict(DEFAULT_TOOL_SOURCES),
            max_steps=max_steps,
            timeout_s=timeout_s,
        )
        wall_s = time.monotonic() - t0

        obs = result.observations
        record: Dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "task_id": task_id,
            "ts": ts,
            "backend": policy.name,
            "plumbing_only": bool(policy.plumbing_only),
            "prompt": prompt,
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
            # Real reward components from the REAL observations (factory codeact_rewards).
            # r_task is null: no automatic verifier exists for open-ended assistant tasks and
            # Dottie never invents a success score (repo anti-fabrication rule).
            "reward_components": {
                "r_exec": r_exec(obs),
                "r_codeuse": r_codeuse(obs),
                "redundant_calls": redundant_calls(obs),
                "r_task": None,
                "r_task_note": "unscored: no automatic verifier for open-ended tasks",
            },
        }
        self._append_trace(record)
        return record

    # -- trace log ----------------------------------------------------------------
    def _append_trace(self, record: Dict[str, Any]) -> None:
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
