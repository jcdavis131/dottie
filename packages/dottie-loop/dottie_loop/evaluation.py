"""Evaluation bundle and gate logic (spec §24), promotion, canary, rollback (§25),
ReleaseRecord and IncidentRecord (§37C).

A challenger must win by slice and remain safe. Every gate is wired into a decision
that can stop advancement (the "harness truth rule"): :func:`evaluate_gates`
returns the verdict :func:`promotion_decision` consumes, and a bundle that
self-declares ``mock`` or ``synthetic`` is ineligible no matter its numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dottie_loop.errors import ApprovalRequiredError, InvalidInputError
from dottie_loop.hashing import age_seconds, new_id, now_iso
from dottie_loop.schema import active

GATES = (
    "data_integrity",
    "task_win",
    "no_critical_regression",
    "slice_floor",
    "efficiency_bound",
    "freshness",
    "anti_mock",
)
DECISIONS = ("promote", "hold", "reject", "rollback", "block")
FRESHNESS_WINDOW_S = 48 * 3600


@dataclass
class EvalBundle:
    candidate: dict[str, str]  # {"id", "sha256"}
    incumbent: dict[str, str]
    benchmark_version: str
    hidden_set_snapshot: str
    primary_metric: str
    candidate_primary: float
    incumbent_primary: float
    ci_low: float  # paired bootstrap CI lower bound of (candidate - incumbent)
    ci_high: float
    n_items: int
    slice_results: dict[str, float]
    slice_floors: dict[str, float]
    regressions: dict[str, int]  # {"safety": 0, "authorization": 0, "protected_tests": 0}
    safety_findings: list[str]
    efficiency: dict[str, float]  # {"candidate_cost", "incumbent_cost", "approved_ratio"}
    overlap_report: dict[str, Any]
    synthetic: bool
    mock: bool
    evaluator_commit: str
    evaluated_at: str
    baseline_evaluated_at: str
    bundle_id: str = field(default_factory=lambda: new_id("eval_"))
    schema: str = field(default_factory=lambda: active("eval-bundle"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def evaluate_gates(b: EvalBundle, now: datetime | None = None) -> dict[str, Any]:
    """Every §24 gate with its pass condition; the verdict is the conjunction."""
    now = now or datetime.now(UTC)
    if b.n_items <= 0:
        raise InvalidInputError("n_items must be positive (denominator required)", "n_items")
    gates: dict[str, dict[str, Any]] = {}
    ov = b.overlap_report
    gates["data_integrity"] = {
        "pass": bool(ov.get("manifest_ok")) and bool(ov.get("split_ok")) and not ov.get("leakage") and not ov.get("privacy_unresolved"),
        "evidence": ov,
    }
    win = b.candidate_primary > b.incumbent_primary and b.ci_low > 0.0
    gates["task_win"] = {
        "pass": win,
        "evidence": {"metric": b.primary_metric, "candidate": b.candidate_primary, "incumbent": b.incumbent_primary, "ci": [b.ci_low, b.ci_high], "n": b.n_items},
    }
    crit = {k: v for k, v in b.regressions.items() if v}
    gates["no_critical_regression"] = {"pass": not crit and not b.safety_findings, "evidence": {"regressions": crit, "safety": b.safety_findings}}
    below = {s: (b.slice_results.get(s), fl) for s, fl in b.slice_floors.items() if b.slice_results.get(s) is None or b.slice_results[s] < fl}
    gates["slice_floor"] = {"pass": not below, "evidence": below}
    inc_cost = b.efficiency.get("incumbent_cost", 0.0) or 0.0
    ratio = (b.efficiency.get("candidate_cost", 0.0) / inc_cost) if inc_cost else float("inf")
    gates["efficiency_bound"] = {"pass": ratio <= b.efficiency.get("approved_ratio", 1.0), "evidence": {"ratio": ratio}}
    fresh = age_seconds(b.evaluated_at, now) <= FRESHNESS_WINDOW_S and age_seconds(b.baseline_evaluated_at, now) <= FRESHNESS_WINDOW_S
    gates["freshness"] = {"pass": fresh, "evidence": {"evaluated_at": b.evaluated_at, "baseline_evaluated_at": b.baseline_evaluated_at, "window_s": FRESHNESS_WINDOW_S}}
    gates["anti_mock"] = {"pass": not (b.synthetic or b.mock), "evidence": {"synthetic": b.synthetic, "mock": b.mock}}
    failed = [g for g in GATES if not gates[g]["pass"]]
    return {"bundle_id": b.bundle_id, "gates": gates, "failed": failed, "verdict": "pass" if not failed else "fail", "at": now_iso()}


def calibration(pairs: list[tuple[float, bool]], *, abstentions: int = 0, wrong_when_confident: int | None = None, bins: int = 10) -> dict[str, Any]:
    """Expected calibration error over (confidence, correct) pairs, plus abstention quality.

    Every float derives from the records given (harness truth rule); an empty input is
    reported as unmeasured, never as a plausible zero.
    """
    if not pairs:
        return {"ece": None, "n": 0, "abstentions": abstentions, "status": "unmeasured"}
    for c, _ in pairs:
        if not 0.0 <= c <= 1.0:
            raise InvalidInputError("confidence must be in [0, 1]", field="pairs")
    buckets: dict[int, list[tuple[float, bool]]] = {}
    for c, ok in pairs:
        buckets.setdefault(min(bins - 1, int(c * bins)), []).append((c, ok))
    ece = 0.0
    table = []
    for b, items in sorted(buckets.items()):
        conf = sum(c for c, _ in items) / len(items)
        acc = sum(1 for _, ok in items if ok) / len(items)
        ece += abs(conf - acc) * len(items) / len(pairs)
        table.append({"bin": b, "n": len(items), "confidence": round(conf, 4), "accuracy": round(acc, 4)})
    total = len(pairs) + abstentions
    return {"ece": round(ece, 4), "n": len(pairs), "bins": table, "abstentions": abstentions, "abstention_rate": round(abstentions / total, 4) if total else 0.0, "wrong_when_confident": wrong_when_confident, "status": "measured"}


# --- §25 promotion -----------------------------------------------------------------------


def promotion_decision(
    gate_result: dict[str, Any],
    *,
    canary: dict[str, Any] | None,
    approval_valid: bool,
    production_threshold_crossed: bool = False,
) -> dict[str, Any]:
    """Map gate + canary + approval state to one of the five outcomes."""
    failed = set(gate_result["failed"])
    if production_threshold_crossed:
        return _decision("rollback", "production threshold crossed", ["restore pinned incumbent", "open incident"])
    blockers = failed & {"freshness", "data_integrity", "anti_mock"}
    if blockers:
        return _decision("block", f"prerequisite invalid: {sorted(blockers)}", ["resolve prerequisite; do not reinterpret as hold"])
    if failed & {"task_win", "slice_floor", "no_critical_regression"}:
        return _decision("reject", f"primary gate or floor failed: {sorted(failed)}", ["archive evidence", "return to data/training"])
    if failed:
        return _decision("hold", f"non-critical gate failed: {sorted(failed)}", ["collect more data without expanding traffic"])
    if canary is None or canary.get("status") != "complete":
        return _decision("hold", "canary evidence insufficient", ["run canary to its predetermined stop"])
    if canary.get("challenger_metric", 0.0) < canary.get("baseline_metric", 0.0) - 0.01:
        return _decision("reject", "canary below baseline - 0.01 floor", ["archive evidence"])
    if not approval_valid:
        return _decision("block", "explicit approval missing", ["present decision packet for approval"])
    return _decision("promote", "all gates pass and approval is valid", ["deploy exact artifact", "verify served bytes/state"])


def _decision(outcome: str, reason: str, next_actions: list[str]) -> dict[str, Any]:
    if outcome not in DECISIONS:
        raise InvalidInputError(f"unknown decision {outcome!r}", field="outcome")
    return {"outcome": outcome, "reason": reason, "next_actions": next_actions, "at": now_iso()}


CANARY_REQUIREMENTS = (
    "pre_alias_smoke_verified",
    "traffic_limited",
    "logs_distinguish_incumbent_challenger",
    "rollback_thresholds_stricter_for_safety",
    "duration_covers_load_and_diversity",
    "manual_stop_tested",
)


def canary_plan_valid(plan: dict[str, Any]) -> dict[str, Any]:
    missing = [r for r in CANARY_REQUIREMENTS if not plan.get(r)]
    return {"ok": not missing, "missing": missing}


# --- release record + served verification + rollback -------------------------------------


def release_record(
    *,
    artifact: dict[str, str],
    source_commit: str,
    eval_bundle: str,
    canary_decision: str,
    approval_id: str | None,
    deployment_id: str,
    previous_release: str | None,
    rollback_target: str,
    served_observed_hash: str,
    environment: str = "production",
) -> dict[str, Any]:
    """Writing a record does not deploy; it records what an operator did after approval."""
    if not approval_id:
        raise ApprovalRequiredError("a release requires an explicit approval id")
    pass_served = served_observed_hash == artifact.get("sha256")
    return {
        "schema": active("release-record"),
        "release_id": new_id("rel_"),
        "artifact": artifact,
        "source_commit": source_commit,
        "eval_bundle": eval_bundle,
        "canary_decision": canary_decision,
        "approval_id": approval_id,
        "environment": environment,
        "deployment_id": deployment_id,
        "previous_release": previous_release,
        "rollback_target": rollback_target,
        "served_verification": {"at": now_iso(), "observed_hash": served_observed_hash, "pass": pass_served},
        "status": "active" if pass_served else "mismatch",
    }


def rollback(release: dict[str, Any], *, served_after_hash: str, reason: str) -> dict[str, Any]:
    """Switch to the pinned incumbent, verify, freeze the challenger, open an incident."""
    restored = served_after_hash == release["rollback_target"]
    incident = {
        "schema": active("incident-record"),
        "incident_id": new_id("inc_"),
        "severity": "SEV-1",
        "detected_at": now_iso(),
        "source": "rollback",
        "affected_releases": [release["release_id"]],
        "observed_impact": reason,
        "containment": ["serving pointer moved to rollback target", "challenger frozen", "incident-window traces quarantined"],
        "rollback_record": {"target": release["rollback_target"], "verified": restored},
        "suspected_cause": None,
        "confirmed_cause": None,
        "status": "contained" if restored else "open",
    }
    return {
        "release_id": release["release_id"],
        "status": "rolled_back" if restored else "rollback_failed",
        "challenger_frozen": release["artifact"]["id"],
        "quarantine_window_open": True,
        "incident": incident,
    }
