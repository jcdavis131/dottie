"""Sandboxed, proposal-only HyperAgents lineage (research sequence stage 6).

A meta-agent may propose an experiment, opt-lane job, or train run. It may
not apply the change, acquire the GPU lease, consume a promote approval, or
write a release. Approval and promotion gates stay closed by default.
``production_change`` is always false on every record this module emits.

Safety invariants (tests pin these):

1. ``apply_proposal`` always fails — proposals cannot self-apply, even when
   the actor is not the proposer and even when ``approve_prod`` is set.
2. ``ExperimentQueue.submit`` from a proposal is allowed; ``claim`` of a
   GPU job requires a named operator, not the proposing agent id.
3. ``promote_guard`` / ``evaluation.promotion_decision`` remain the only
   promotion paths. This module never sets ``production_change: true``.
4. Sandbox destinations only. Production / release / promote destinations
   are refused at propose time.
5. A proposer cannot consume an approval issued against its own proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dottie_loop.approvals import ACTION_TYPES, ApprovalStore
from dottie_loop.closed_loop import promote_guard
from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active

if TYPE_CHECKING:
    from dottie_loop.experiment import ExperimentJob, ExperimentQueue

PROPOSABLE_ACTIONS = frozenset({"experiment", "opt_lane", "train"})
FORBIDDEN_ACTIONS = frozenset({"promote", "release", "deploy", "merge"})
SANDBOX_DESTINATIONS = frozenset({"sandbox", "experiment-queue", "opt-lane", "local"})
PRODUCTION_DESTINATIONS = frozenset({"production", "prod", "release", "promote"})
OPERATOR_KINDS = frozenset({"operator", "human", "runner"})
PROPOSER_KINDS = frozenset({"hyperagent", "agent"})


@dataclass
class Proposal:
    """Digest-bound, destination-bound, proposal-only record."""

    proposer_id: str
    action: str
    destination: str
    payload: dict[str, Any]
    proposer_kind: str = "hyperagent"
    proposal_id: str = field(default_factory=lambda: new_id("prop_"))
    production_change: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.production_change:
            raise PolicyDeniedError(
                "a proposal cannot set production_change", field="production_change"
            )
        if self.proposer_kind not in PROPOSER_KINDS:
            raise InvalidInputError(
                f"proposer_kind must be one of {sorted(PROPOSER_KINDS)}",
                field="proposer_kind",
            )
        if not self.proposer_id.strip():
            raise InvalidInputError("proposer_id is required", field="proposer_id")
        if self.action in FORBIDDEN_ACTIONS or self.action in {"promote", "release", "deploy"}:
            raise PolicyDeniedError(
                f"action {self.action!r} is outside the sandbox (proposal-only)",
                field="action",
            )
        if self.action not in PROPOSABLE_ACTIONS:
            raise InvalidInputError(
                f"action must be one of {sorted(PROPOSABLE_ACTIONS)}", field="action"
            )
        if self.destination in PRODUCTION_DESTINATIONS:
            raise PolicyDeniedError(
                "proposal destination cannot be production", field="destination"
            )
        if self.destination not in SANDBOX_DESTINATIONS:
            raise InvalidInputError(
                f"destination must be one of {sorted(SANDBOX_DESTINATIONS)}",
                field="destination",
            )
    def digest(self) -> str:
        return digest(
            {
                "proposer_id": self.proposer_id,
                "action": self.action,
                "destination": self.destination,
                "payload": self.payload,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("hyperagent-proposal"),
            "proposal_id": self.proposal_id,
            "proposer_id": self.proposer_id,
            "proposer_kind": self.proposer_kind,
            "action": self.action,
            "destination": self.destination,
            "payload": dict(self.payload),
            "digest": self.digest(),
            "production_change": False,
            "notes": self.notes,
            "sandbox": sandbox_bounds(),
            "proposed_at": now_iso(),
        }


def sandbox_bounds() -> dict[str, Any]:
    return {
        "destinations": sorted(SANDBOX_DESTINATIONS),
        "proposable": sorted(PROPOSABLE_ACTIONS),
        "forbidden": sorted(FORBIDDEN_ACTIONS),
        "may_apply": False,
        "may_claim_gpu": False,
        "may_promote": False,
        "production_change": False,
    }


def propose(
    *,
    proposer_id: str,
    action: str,
    destination: str,
    payload: dict[str, Any],
    proposer_kind: str = "hyperagent",
    notes: str = "",
) -> Proposal:
    """Create a sandbox proposal. Does not apply, claim, or promote."""
    return Proposal(
        proposer_id=proposer_id,
        action=action,
        destination=destination,
        payload=dict(payload),
        proposer_kind=proposer_kind,
        notes=notes,
        production_change=False,
    )


def apply_proposal(
    proposal: Proposal,
    *,
    actor_id: str | None = None,
    approval_id: str | None = None,
    approve_prod: bool = False,
    **_ignored: Any,
) -> dict[str, Any]:
    """Always denied. Proposals cannot self-apply or apply at all.

    Approval, a different actor, and ``approve_prod`` are ignored on purpose:
    the only sandbox effect is :func:`submit_from_proposal`.
    """
    raise PolicyDeniedError(
        "hyperagent proposals cannot apply themselves; submit is the only sandbox effect",
        field="apply",
        actor_id=actor_id,
        approval_id=approval_id,
        approve_prod=approve_prod,
        proposal_id=proposal.proposal_id,
    )


def submit_from_proposal(queue: ExperimentQueue, proposal: Proposal, job: ExperimentJob) -> ExperimentJob:
    """Queue an experiment from a proposal. Does not claim resources or promote."""
    if proposal.action != "experiment":
        raise InvalidInputError(
            "only an experiment proposal may submit to ExperimentQueue", field="action"
        )
    job.lineage.setdefault("proposal_id", proposal.proposal_id)
    job.lineage.setdefault("proposal_digest", proposal.digest())
    job.lineage.setdefault("proposer_id", proposal.proposer_id)
    job.lineage["production_change"] = False
    return queue.submit(job)


def claim_from_proposal(
    queue: ExperimentQueue,
    proposal: Proposal,
    owner: str,
    *,
    owner_kind: str,
    resource: str | None = None,
    **lease_kw: Any,
) -> ExperimentJob | None:
    """Claim a queued job. GPU (and any claim) requires a named operator.

    The proposing agent id is never an acceptable owner.
    """
    if owner == proposal.proposer_id:
        raise PolicyDeniedError(
            "proposing agent cannot claim its own job (including gpu)",
            field="owner",
        )
    if owner_kind not in OPERATOR_KINDS:
        raise PolicyDeniedError(
            "job claim requires a named operator, not the proposing agent",
            field="owner_kind",
        )
    if resource == "gpu" or (resource is None and any(
        j.resource == "gpu" and j.status == "pending" for j in queue.jobs.values()
    )):
        if owner_kind not in OPERATOR_KINDS:
            raise PolicyDeniedError("gpu claim requires a named operator", field="owner_kind")
    return queue.claim(owner, resource=resource, **lease_kw)


def issue_approval_for(
    store: ApprovalStore,
    proposal: Proposal,
    *,
    approver_subject: str,
    approver_role: str,
    goal_id: str,
    action_type: str = "experiment",
    ttl_seconds: int = 900,
) -> Any:
    """A human issues an approval bound to the proposal digest.

    The proposing agent cannot be the approver. Production actions stay denied.
    ``experiment`` is accepted as the bound action even though it is not a
    production mutate — it still cannot be consumed by the proposer.
    """
    if approver_subject == proposal.proposer_id:
        raise PolicyDeniedError("proposer cannot issue an approval for its own proposal", field="approver")
    if action_type in FORBIDDEN_ACTIONS:
        raise PolicyDeniedError(
            "hyperagent approvals cannot bind promote/release/deploy", field="action"
        )
    if action_type not in ACTION_TYPES:
        raise InvalidInputError(f"unknown action type {action_type!r}", field="action")
    if action_type != proposal.action and action_type != "experiment":
        raise InvalidInputError("approval action must match the proposal", field="action")
    return store.issue(
        approver_subject=approver_subject,
        approver_role=approver_role,
        action_type=action_type,
        payload={"proposal_digest": proposal.digest(), "proposal_id": proposal.proposal_id},
        destination=proposal.destination,
        goal_id=goal_id,
        ttl_seconds=ttl_seconds,
    )


def consume_as_proposer(
    store: ApprovalStore,
    proposal: Proposal,
    approval_id: str,
    *,
    actor_id: str,
    goal_id: str,
) -> None:
    """The proposing agent may not consume an approval issued against the proposal."""
    if actor_id == proposal.proposer_id:
        raise PolicyDeniedError(
            "proposer cannot consume an approval for its own proposal", field="actor"
        )
    store.verify_and_consume(
        approval_id,
        action_type="experiment",
        payload={"proposal_digest": proposal.digest(), "proposal_id": proposal.proposal_id},
        destination=proposal.destination,
        goal_id=goal_id,
    )


def promotion_from_proposal(
    proposal: Proposal,
    *,
    approve_prod: bool = False,
    promote: bool = True,
) -> dict[str, Any]:
    """Promotion stays closed. ``approve_prod`` is ignored; production does not change."""
    decision = {
        "decision": "no_change",
        "decision_id": new_id("loop_"),
        "proposal_id": proposal.proposal_id,
    }
    guard = promote_guard(promote=promote, approve_prod=approve_prod, decision=decision)
    # Belt and braces: even if a caller spoofs a trigger decision, this path
    # still reports no production change.
    return {
        "production_change": False,
        "proposal_id": proposal.proposal_id,
        "proposal_digest": proposal.digest(),
        "approve_prod_ignored": bool(approve_prod),
        "guard": {**guard, "production_change": False},
        "reason": "hyperagent proposals cannot promote; use promote_guard / promotion_decision",
    }


__all__ = [
    "FORBIDDEN_ACTIONS",
    "OPERATOR_KINDS",
    "PRODUCTION_DESTINATIONS",
    "PROPOSABLE_ACTIONS",
    "Proposal",
    "apply_proposal",
    "claim_from_proposal",
    "consume_as_proposer",
    "issue_approval_for",
    "promotion_from_proposal",
    "propose",
    "sandbox_bounds",
    "submit_from_proposal",
]
