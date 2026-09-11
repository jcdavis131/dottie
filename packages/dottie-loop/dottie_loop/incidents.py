"""Incident handling and disaster recovery (spec §33, §37C IncidentRecord).

Recovery restores known-good state before diagnosis finishes. The lifecycle is
ordered and enforced; close happens only after recurrence prevention is verified;
suspected and confirmed causes are kept separate; incident-window data is
quarantined from training until reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dottie_loop.errors import InvalidInputError, UnexecutableError
from dottie_loop.hashing import new_id, now_iso
from dottie_loop.schema import active

SEVERITY: dict[str, dict[str, str]] = {
    "SEV-0": {"examples": "credential exposure, unauthorized external effect, cross-tenant access", "action": "stop affected services, revoke credentials, preserve evidence, notify owner"},
    "SEV-1": {"examples": "production model safety/correctness regression, corrupted release", "action": "rollback, disable challenger, quarantine affected traces"},
    "SEV-2": {"examples": "major workflow unavailable, queue stuck, stale critical metrics", "action": "fail closed, shift to safe fallback, restore dependency"},
    "SEV-3": {"examples": "non-critical degradation, isolated skill failure", "action": "disable component or route around; schedule fix"},
}
LIFECYCLE = ("detect", "contain", "preserve", "communicate", "restore", "investigate", "correct", "close")
RECOVERY_ORDER = ("identity_and_policy", "immutable_artifacts", "goal_run_state", "tool_registry", "routing_planning", "execution", "telemetry", "training")
ATTRIBUTION = ("recipe_problem", "knowledge_gap", "ambiguity")


@dataclass
class Incident:
    severity: str
    source: str
    observed_impact: str
    affected: dict[str, list[str]] = field(default_factory=lambda: {"goals": [], "releases": [], "data": []})
    incident_id: str = field(default_factory=lambda: new_id("inc_"))
    detected_at: str = field(default_factory=now_iso)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    containment: list[str] = field(default_factory=list)
    rollback_record: dict[str, Any] | None = None
    suspected_cause: str | None = None
    confirmed_cause: str | None = None
    attribution: str | None = None
    corrective_actions: list[dict[str, Any]] = field(default_factory=list)
    quarantine_window: dict[str, str | None] = field(default_factory=dict)
    status: str = "detect"
    schema: str = field(default_factory=lambda: active("incident-record"))

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY:
            raise InvalidInputError(f"unknown severity {self.severity!r}", field="severity")
        self.timeline.append({"step": "detect", "at": self.detected_at, "note": self.source})
        self.quarantine_window = {"from": self.detected_at, "to": None}

    def _advance(self, step: str, note: str) -> None:
        idx = LIFECYCLE.index(step)
        cur = LIFECYCLE.index(self.status)
        if idx != cur + 1:
            raise UnexecutableError(f"incident step {step} out of order after {self.status}", "status")
        self.status = step
        self.timeline.append({"step": step, "at": now_iso(), "note": note})

    def contain(self, actions: list[str]) -> None:
        if not actions:
            raise InvalidInputError("containment must name at least one authority-limiting action", "actions")
        self.containment.extend(actions)
        self._advance("contain", "; ".join(actions))

    def preserve(self, evidence_refs: list[str]) -> None:
        self._advance("preserve", f"{len(evidence_refs)} evidence refs preserved (append-only)")

    def communicate(self, verified_impact: str) -> None:
        # do not speculate on cause here: only the verified impact goes out
        self._advance("communicate", verified_impact)

    def restore(self, rollback_record: dict[str, Any], verified: bool) -> None:
        if not verified:
            raise UnexecutableError("restore requires end-to-end verification", "verified")
        self.rollback_record = rollback_record
        self._advance("restore", "known-good artifact restored and verified")

    def investigate(self, suspected: str, attribution: str) -> None:
        if attribution not in ATTRIBUTION:
            raise InvalidInputError("attribution must be recipe_problem|knowledge_gap|ambiguity", "attribution")
        self.suspected_cause = suspected
        self.attribution = attribution
        self._advance("investigate", f"suspected: {suspected} ({attribution})")

    def correct(self, owner: str, test: str, due_gate: str, confirmed_cause: str | None = None) -> None:
        self.corrective_actions.append({"owner": owner, "test": test, "due_gate": due_gate, "verified": False})
        if confirmed_cause:
            self.confirmed_cause = confirmed_cause
        self._advance("correct", f"corrective action owned by {owner}")

    def close(self, recurrence_prevention_verified: bool) -> None:
        if not recurrence_prevention_verified or not self.corrective_actions:
            raise UnexecutableError("close only after recurrence prevention is deployed and verified", "close")
        for a in self.corrective_actions:
            a["verified"] = True
        self.quarantine_window["to"] = now_iso()
        self._advance("close", "recurrence prevention verified")

    def training_eligible(self, at: str) -> bool:
        """Traces from the incident window are NOT automatically eligible for training."""
        start = self.quarantine_window["from"]
        end = self.quarantine_window["to"]
        inside = at >= start and (end is None or at <= end)
        return not inside

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def dr_drill_checklist(results: dict[str, bool]) -> dict[str, Any]:
    """Restore drills must prove every item; a missing item is a failed drill."""
    required = ("repository_checkout", "state_store_integrity", "checkpoint_hashes", "dataset_manifest_resolution", "model_loading", "rollback_deployment")
    failed = [k for k in required if not results.get(k)]
    return {"ok": not failed, "failed": failed, "recovery_order": list(RECOVERY_ORDER), "at": now_iso()}
