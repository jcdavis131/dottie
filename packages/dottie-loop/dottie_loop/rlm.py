"""RLM execution and the REPL surface (spec §06 REPL row, §10 "RLM execution").

The Recursive Language Model environment treats long context as program
variables and permits bounded child calls through ``rlm(...)``. The parent stays
responsible for budget, scope and synthesis. A stuck detector fires after repeated
queries, repeated failures, or confidence below threshold, then allows exactly ONE
lateral reasoning lens rather than agent spam. Every child call is logged as a
timeline event; there are no unlogged ephemeral subagents. Missions resume from
the log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError, LoopError, PolicyDeniedError
from dottie_loop.hashing import digest, new_id, now_iso

if TYPE_CHECKING:
    from collections.abc import Callable

STUCK_REPEAT_QUERIES = 3
STUCK_REPEAT_FAILURES = 2
STUCK_CONFIDENCE = 0.4
LATERAL_LENSES = ("invert_the_question", "smallest_reproducer", "adjacent_domain_analogy", "constraint_relaxation")


@dataclass
class Budget:
    tokens: int
    child_calls: int
    depth: int
    wall_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class StuckDetector:
    queries: list[str] = field(default_factory=list)
    failures: int = 0
    low_confidence: int = 0
    lens_used: str | None = None

    def observe(self, query: str, *, failed: bool, confidence: float | None) -> str | None:
        """Returns the reason the session is stuck, or None."""
        self.queries.append(digest(query.strip().lower()))
        if failed:
            self.failures += 1
        if confidence is not None and confidence < STUCK_CONFIDENCE:
            self.low_confidence += 1
        if self.queries.count(self.queries[-1]) >= STUCK_REPEAT_QUERIES:
            return "repeated_query"
        if self.failures >= STUCK_REPEAT_FAILURES:
            return "repeated_failure"
        if self.low_confidence >= 2:
            return "low_confidence"
        return None

    def lens(self, preferred: str | None = None) -> str:
        """Exactly one lateral lens per stuck episode; a second request escalates."""
        if self.lens_used is not None:
            raise LoopError("one lateral lens already used; escalate to a human", code="stuck", status=409, error_class="unknown")
        chosen = preferred or LATERAL_LENSES[0]
        if chosen not in LATERAL_LENSES:
            raise InvalidInputError(f"unknown lens {chosen!r}", field="lens")
        self.lens_used = chosen
        self.failures = 0
        self.low_confidence = 0
        return chosen


class RLMSession:
    """A persistent mission: variables + an append-only mission log + a bounded ``rlm()``."""

    def __init__(self, mission_id: str, log_path: Path, budget: Budget, *, depth: int = 0, parent_call: str | None = None) -> None:
        self.mission_id = mission_id
        self.log_path = Path(log_path)
        self.budget = budget
        self.depth = depth
        self.parent_call = parent_call
        self.variables: dict[str, Any] = {}
        self.tokens_used = 0
        self.child_calls = 0
        self.stuck = StuckDetector()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # -- mission log --
    def _log(self, kind: str, **fields: Any) -> dict[str, Any]:
        rec = {"mission_id": self.mission_id, "kind": kind, "depth": self.depth, "at": now_iso(), **fields}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def set_var(self, name: str, value: Any, *, source: str) -> None:
        """Context lives in named variables with provenance, not in a hidden prompt."""
        if not name.isidentifier():
            raise InvalidInputError("variable names must be identifiers", field="name")
        self.variables[name] = value
        self._log("set_var", name=name, source=source, value_digest=digest(value))

    def visible_budget(self) -> dict[str, Any]:
        return {"tokens": {"limit": self.budget.tokens, "used": self.tokens_used}, "child_calls": {"limit": self.budget.child_calls, "used": self.child_calls}, "depth": {"limit": self.budget.depth, "current": self.depth}}

    # -- bounded child call --
    def rlm(self, query: str, worker: Callable[[RLMSession, str], dict[str, Any]], *, tokens: int, inputs: list[str] | None = None) -> dict[str, Any]:
        """One child call with its own budget slice; logged before and after; never unbounded."""
        if self.depth >= self.budget.depth:
            raise PolicyDeniedError(f"child depth {self.depth + 1} exceeds budget {self.budget.depth}", field="depth")
        if self.child_calls >= self.budget.child_calls:
            raise PolicyDeniedError("child call budget exhausted", field="child_calls")
        if self.tokens_used + tokens > self.budget.tokens:
            raise PolicyDeniedError("token budget would be exceeded", field="tokens")
        for name in inputs or []:
            if name not in self.variables:
                raise InvalidInputError(f"child input {name!r} is not a defined variable", field="inputs")
        call_id = new_id("rlm_")
        self.child_calls += 1
        self._log("rlm_call", call_id=call_id, query=query, tokens=tokens, inputs=sorted(inputs or []))
        child = RLMSession(self.mission_id, self.log_path, Budget(tokens=tokens, child_calls=max(0, self.budget.child_calls - self.child_calls), depth=self.budget.depth, wall_seconds=self.budget.wall_seconds), depth=self.depth + 1, parent_call=call_id)
        for name in inputs or []:
            child.variables[name] = self.variables[name]
        try:
            out = worker(child, query)
            failed = not out.get("ok", True)
        except LoopError as e:
            out = {"ok": False, "error": e.to_dict()}
            failed = True
        used = int(out.get("tokens_used", tokens))
        self.tokens_used += min(used, tokens) + child.tokens_used
        self._log("rlm_result", call_id=call_id, ok=not failed, tokens_used=used, confidence=out.get("confidence"))
        stuck = self.stuck.observe(query, failed=failed, confidence=out.get("confidence"))
        if stuck:
            self._log("stuck", call_id=call_id, reason=stuck, lens_available=self.stuck.lens_used is None)
            out = {**out, "stuck": stuck}
        return {"call_id": call_id, **out}

    def lateral_lens(self, preferred: str | None = None) -> str:
        lens = self.stuck.lens(preferred)
        self._log("lateral_lens", lens=lens)
        return lens

    # -- resume --
    @classmethod
    def resume(cls, mission_id: str, log_path: Path, budget: Budget) -> RLMSession:
        """Reconstruct variables' provenance and spent budget from the log; values are re-hydrated by the caller."""
        s = cls(mission_id, log_path, budget)
        if not s.log_path.exists():
            return s
        for line in s.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("mission_id") != mission_id or rec.get("depth", 0) != 0:
                continue
            if rec["kind"] == "set_var":
                s.variables.setdefault(rec["name"], {"__rehydrate__": rec["value_digest"], "source": rec["source"]})
            elif rec["kind"] == "rlm_call":
                s.child_calls += 1
            elif rec["kind"] == "rlm_result":
                s.tokens_used += int(rec.get("tokens_used", 0))
            elif rec["kind"] == "lateral_lens":
                s.stuck.lens_used = rec["lens"]
        s._log("resume", child_calls=s.child_calls, tokens_used=s.tokens_used)
        return s
