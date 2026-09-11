"""Observability (spec §32): correlation model, four-plus signals, SLOs, alert design,
and the "no orphan metrics" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import age_seconds, now_iso

CORRELATION_FIELDS = ("goal_id", "run_id", "plan_version", "node_id", "attempt", "request_id", "actor", "at")
SIGNALS = ("traffic", "errors", "latency", "saturation", "quality", "safety")
PAGE_WORTHY = frozenset({"safety_violation", "production_correctness_regression", "runner_dead_with_pending_work", "release_mismatch", "data_qa_failure", "sustained_objective_burn"})


def correlate(event: dict[str, Any]) -> dict[str, Any]:
    """Every event carries the correlation fields; adapters preserve, never invent, them."""
    missing = [f for f in CORRELATION_FIELDS if f not in event]
    if missing:
        raise InvalidInputError(f"event missing correlation fields {missing}", field="event")
    if "signal" in event and event["signal"] not in SIGNALS:
        raise InvalidInputError(f"unknown signal {event['signal']!r}", field="signal")
    return event


def metric_record(*, name: str, value: float, raw_source: str, aggregation_version: str, window: str, denominator: int, freshness_at: str, owner: str, decision: str) -> dict[str, Any]:
    """No orphan metrics: source, aggregation code version, window, denominator, freshness, owner, decision."""
    for k, v in (("raw_source", raw_source), ("aggregation_version", aggregation_version), ("window", window), ("owner", owner), ("decision", decision)):
        if not v:
            raise InvalidInputError(f"metric {name} has no {k}; a number with no decision or owner is not a gate", k)
    if denominator <= 0:
        raise InvalidInputError(f"metric {name} has no denominator", field="denominator")
    return {"name": name, "value": value, "raw_source": raw_source, "aggregation_version": aggregation_version, "window": window, "denominator": denominator, "freshness_at": freshness_at, "freshness_age_s": round(age_seconds(freshness_at), 1), "owner": owner, "decision": decision, "recorded_at": now_iso()}


@dataclass
class SLO:
    """Outcome-based objective: a timely ack is not a successful goal."""

    name: str
    target: float  # e.g. 0.95 success ratio
    window: str

    def evaluate(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        considered = [o for o in outcomes if o.get("cause") != "user_cancelled"]
        if not considered:
            return {"slo": self.name, "measured": None, "target": self.target, "denominator": 0, "status": "unmeasured"}
        good = sum(1 for o in considered if o.get("good"))
        ratio = good / len(considered)
        budget_total = (1 - self.target) * len(considered)
        budget_used = len(considered) - good
        return {"slo": self.name, "measured": round(ratio, 4), "target": self.target, "denominator": len(considered), "error_budget_remaining": round(budget_total - budget_used, 2), "status": "ok" if ratio >= self.target else "burning", "counts_system_blocks": True}


@dataclass
class AlertDeduper:
    seen: dict[str, str] = field(default_factory=dict)
    paged: list[dict[str, Any]] = field(default_factory=list)
    dashboard: list[dict[str, Any]] = field(default_factory=list)

    def evaluate(self, breach_class: str, incident_key: str, detail: str) -> dict[str, Any]:
        """Page only on actionable breaches; dedupe by incident key; drift goes to dashboards."""
        if incident_key in self.seen:
            return {"action": "suppressed", "incident_key": incident_key, "first_seen": self.seen[incident_key]}
        self.seen[incident_key] = now_iso()
        rec = {"class": breach_class, "incident_key": incident_key, "detail": detail, "at": self.seen[incident_key]}
        if breach_class in PAGE_WORTHY:
            self.paged.append(rec)
            return {"action": "page", **rec}
        self.dashboard.append(rec)
        return {"action": "dashboard", **rec}
