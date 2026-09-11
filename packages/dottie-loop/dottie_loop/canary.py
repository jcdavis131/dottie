"""Canary runs that are limited and attributable (spec §25, §36 Runbook C 9–12, ML-13).

Every event names the exact artifact it came from (incumbent or challenger) or it is
rejected; thresholds are evaluated continuously with safety stricter than the primary
metric; the decision packet exists only at the PREDETERMINED stop, and the run cannot
be extended to chase a win. The packet is what :func:`evaluation.promotion_decision`
consumes as its ``canary`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dottie_loop.errors import (
    InvalidInputError,
    PolicyDeniedError,
    StaleEvidenceError,
    UnexecutableError,
)
from dottie_loop.evaluation import canary_plan_valid
from dottie_loop.hashing import age_seconds, new_id, now_iso

EVENT_FIELDS = ("artifact_id", "event_time", "ok", "latency_ms")


@dataclass
class CanaryRun:
    plan: dict[str, Any]
    incumbent_id: str
    challenger_id: str
    stop_after: int  # predetermined number of challenger events
    freshness_s: int = 3600
    safety_floor: float = 0.99  # challenger safety rate must not fall below this
    rollback_delta: float = 0.01  # challenger primary must not trail incumbent by more than this
    events: list[dict[str, Any]] = field(default_factory=list)
    stopped: dict[str, Any] | None = None
    canary_id: str = field(default_factory=lambda: new_id("canary_"))

    def __post_init__(self) -> None:
        v = canary_plan_valid(self.plan)
        if not v["ok"]:
            raise UnexecutableError(f"canary plan incomplete: {v['missing']}", "plan")
        if self.incumbent_id == self.challenger_id or not self.incumbent_id or not self.challenger_id:
            raise InvalidInputError("incumbent and challenger must be distinct, named artifacts", field="artifacts")
        if self.stop_after <= 0:
            raise InvalidInputError("stop_after must be a positive, predetermined count", field="stop_after")

    # -- ML-13: every event attributable --
    def observe(self, event: dict[str, Any]) -> dict[str, Any]:
        if self.stopped is not None:
            raise PolicyDeniedError("canary stopped; no further events are counted", field="canary")
        missing = [f for f in EVENT_FIELDS if f not in event]
        if missing:
            raise InvalidInputError(f"canary event missing {missing}", field="event")
        if event["artifact_id"] not in (self.incumbent_id, self.challenger_id):
            raise InvalidInputError("event names neither the incumbent nor the challenger", field="artifact_id")
        rec = {**event, "role": "challenger" if event["artifact_id"] == self.challenger_id else "incumbent", "safety_ok": bool(event.get("safety_ok", True))}
        self.events.append(rec)
        return rec

    # -- thresholds, safety stricter --
    def metrics(self) -> dict[str, Any]:
        def rate(role: str, key: str) -> float | None:
            xs = [e for e in self.events if e["role"] == role]
            return (sum(1 for e in xs if e[key]) / len(xs)) if xs else None

        return {
            "incumbent": {"n": sum(1 for e in self.events if e["role"] == "incumbent"), "primary": rate("incumbent", "ok"), "safety": rate("incumbent", "safety_ok")},
            "challenger": {"n": sum(1 for e in self.events if e["role"] == "challenger"), "primary": rate("challenger", "ok"), "safety": rate("challenger", "safety_ok")},
        }

    def thresholds(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        m = self.metrics()
        ch, inc = m["challenger"], m["incumbent"]
        latest = max((e["event_time"] for e in self.events), default=None)
        stale = latest is None or age_seconds(latest, now) > self.freshness_s
        breaches = []
        if ch["safety"] is not None and ch["safety"] < self.safety_floor:
            breaches.append("safety_floor")
        if ch["primary"] is not None and inc["primary"] is not None and ch["primary"] < inc["primary"] - self.rollback_delta:
            breaches.append("primary_below_incumbent")
        return {"breaches": breaches, "rollback_now": bool(breaches), "stale": stale, "latest_event": latest, "metrics": m, "at": now_iso()}

    # -- the predetermined stop --
    def reached_stop(self) -> bool:
        return self.metrics()["challenger"]["n"] >= self.stop_after

    def manual_stop(self, *, actor: str, reason: str) -> None:
        if not actor or not reason:
            raise InvalidInputError("a manual stop names its actor and reason", field="stop")
        self.stopped = {"kind": "manual", "actor": actor, "reason": reason, "at": now_iso()}

    def extend(self, *_a: Any, **_k: Any) -> None:
        raise PolicyDeniedError("a canary is not extended selectively to chase a win; start a new canary with a new predetermined stop", field="stop_after")

    def decision_packet(self, now: datetime | None = None) -> dict[str, Any]:
        """Only at the predetermined stop (or an explicit manual stop). Consumed by promotion_decision."""
        th = self.thresholds(now)
        if self.stopped is None and not self.reached_stop():
            raise UnexecutableError(f"canary has {self.metrics()['challenger']['n']} of {self.stop_after} challenger events; no packet before the predetermined stop", "stop_after")
        if th["stale"]:
            raise StaleEvidenceError("canary events are older than the freshness window", latest=th["latest_event"])
        if self.stopped is None:
            self.stopped = {"kind": "predetermined", "at": now_iso()}
        m = th["metrics"]
        return {
            "canary_id": self.canary_id,
            "status": "complete",
            "incumbent_id": self.incumbent_id,
            "challenger_id": self.challenger_id,
            "challenger_metric": m["challenger"]["primary"],
            "baseline_metric": m["incumbent"]["primary"],
            "challenger_safety": m["challenger"]["safety"],
            "n": {"incumbent": m["incumbent"]["n"], "challenger": m["challenger"]["n"]},
            "breaches": th["breaches"],
            "recommendation": "rollback" if th["breaches"] else "present_for_approval",
            "stop": self.stopped,
            "plan": {k: bool(self.plan.get(k)) for k in self.plan},
            "at": now_iso(),
        }
