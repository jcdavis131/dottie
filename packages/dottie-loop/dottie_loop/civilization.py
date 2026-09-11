"""Token-efficient agent civilization (spec §30).

T0 machines poll at zero model tokens and stay silent on no change; T1
specialists get bounded context and one deliverable, never spawn, and return a
verdict-first report of at most ten lines; T2 is the sole context-rich
coordinator. None can self-promote into a more authoritative tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import new_id, now_iso

if TYPE_CHECKING:
    from collections.abc import Callable

TIERS = ("T0", "T1", "T2")
REPORT_MAX_LINES = 10


# --- T0 machines ---------------------------------------------------------------------------


@dataclass
class Machine:
    """A deterministic poller: check → compare to threshold → wake ONE specialist on breach."""

    name: str
    check: Callable[[], float]
    threshold: float
    comparator: str = "lt"  # breach when value < threshold ("lt") or > threshold ("gt")
    specialist: str = "specialist"
    last_breach_key: str | None = None
    ticks: int = 0
    wakeups: int = 0
    avoided_wakeups: int = 0

    def tick(self) -> dict[str, Any] | None:
        """Silent (None) on no change; a WakeRequest once per distinct breach."""
        self.ticks += 1
        value = float(self.check())
        breached = value < self.threshold if self.comparator == "lt" else value > self.threshold
        if not breached:
            self.last_breach_key = None
            self.avoided_wakeups += 1
            return None
        key = f"{self.name}:{self.comparator}:{self.threshold}"
        if self.last_breach_key == key:
            self.avoided_wakeups += 1
            return None  # already woke someone for this breach; dedupe by incident key
        self.last_breach_key = key
        self.wakeups += 1
        return {"wake": self.specialist, "machine": self.name, "value": value, "threshold": self.threshold, "incident_key": key, "tokens": 0, "at": now_iso()}


# --- T1 specialists ------------------------------------------------------------------------


@dataclass
class WorkerBrief:
    objective: str
    scope: list[str]
    excerpts: list[str]
    constraints: list[str]
    allowed_actions: list[str]
    success_tests: list[str]
    evidence_path: str
    return_format: str = "verdict-first, <= 10 lines"
    brief_id: str = field(default_factory=lambda: new_id("brief_"))

    def validate(self) -> None:
        if not self.objective or not self.scope or not self.success_tests:
            raise InvalidInputError("a brief needs objective, exact scope and success tests", "brief")
        if any(a in ("spawn", "fan_out") for a in self.allowed_actions):
            raise PolicyDeniedError("specialists never spawn", field="allowed_actions")


def validate_report(text: str, brief: WorkerBrief) -> dict[str, Any]:
    """Verdict-first, at most ten lines, and it cannot expand the assignment."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    problems: list[str] = []
    if not lines or not lines[0].upper().startswith("VERDICT:"):
        problems.append("first line must start with VERDICT:")
    if len(lines) > REPORT_MAX_LINES:
        problems.append(f"{len(lines)} lines > {REPORT_MAX_LINES}")
    if any("EXPAND SCOPE" in ln.upper() or "ALSO DID" in ln.upper() for ln in lines):
        problems.append("report attempts to expand the assignment; results are data for the coordinator")
    return {"ok": not problems, "problems": problems, "lines": len(lines), "brief_id": brief.brief_id}


# --- binding decision ladder ---------------------------------------------------------------------


def decide(*, repeated_check: bool, clear_threshold: bool, single_step: bool, reversible: bool, fits_context: bool, multi_step_self_contained: bool, tiny_jobs: int = 0) -> dict[str, str]:
    """Machine first, self second, spawn last; never fan out tiny jobs."""
    if repeated_check and clear_threshold:
        return {"choice": "machine", "why": "repeated check with a clear threshold → deterministic poller"}
    if single_step and reversible and fits_context:
        return {"choice": "self", "why": "single-step reversible op that fits current context → inline"}
    if tiny_jobs > 1:
        return {"choice": "self", "why": f"{tiny_jobs} tiny jobs would each re-inject full context → batch inline"}
    if multi_step_self_contained:
        return {"choice": "spawn_one", "why": "multi-step, self-contained → one large specialist"}
    return {"choice": "self", "why": "default: coordinator handles it without spawning"}


def can_promote(from_tier: str, to_tier: str) -> bool:
    """Safety property: no tier can self-promote into a more authoritative one."""
    if from_tier not in TIERS or to_tier not in TIERS:
        raise InvalidInputError("unknown tier", field="tier")
    return TIERS.index(to_tier) <= TIERS.index(from_tier)


# --- token accounting -------------------------------------------------------------------------------


@dataclass
class TokenLedger:
    coordinator_in: int = 0
    coordinator_out: int = 0
    specialist_context: int = 0
    tool_text: int = 0
    avoided_wakeups: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, tokens: int, note: str = "") -> None:
        if kind not in ("coordinator_in", "coordinator_out", "specialist_context", "tool_text"):
            raise InvalidInputError(f"unknown token kind {kind!r}", field="kind")
        setattr(self, kind, getattr(self, kind) + int(tokens))
        self.entries.append({"kind": kind, "tokens": int(tokens), "note": note, "at": now_iso()})

    def record_machine(self, m: Machine) -> None:
        self.avoided_wakeups += m.avoided_wakeups

    def summary(self) -> dict[str, int]:
        return {"coordinator_in": self.coordinator_in, "coordinator_out": self.coordinator_out, "specialist_context": self.specialist_context, "tool_text": self.tool_text, "avoided_wakeups": self.avoided_wakeups, "total": self.coordinator_in + self.coordinator_out + self.specialist_context + self.tool_text}


def automation_cost_statement(name: str, tokens_removed_per_day: int, tokens_added_per_day: int) -> dict[str, Any]:
    """Every new automation states the token cost it removes (§30 token accounting)."""
    return {"automation": name, "removes_per_day": tokens_removed_per_day, "adds_per_day": tokens_added_per_day, "net": tokens_removed_per_day - tokens_added_per_day, "justified": tokens_removed_per_day > tokens_added_per_day}
