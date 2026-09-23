"""Stage 6: sandboxed proposal-only HyperAgents lineage."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from dottie_loop import approvals, errors, experiment, hyperagents
from dottie_loop.cli import EXIT_ERROR, EXIT_OK, main
from dottie_loop.closed_loop import LeaseFile
from dottie_loop.schema import active

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _proposal(**over) -> hyperagents.Proposal:
    kw = {
        "proposer_id": "agent-meta",
        "action": "experiment",
        "destination": "sandbox",
        "payload": {"kind": "search", "split": "search"},
    }
    kw.update(over)
    return hyperagents.propose(**kw)


def test_propose_is_sandbox_only_and_never_production():
    p = _proposal()
    d = p.to_dict()
    assert d["schema"] == active("hyperagent-proposal")
    assert d["production_change"] is False
    assert d["sandbox"]["may_apply"] is False
    assert d["sandbox"]["may_promote"] is False
    with pytest.raises(errors.PolicyDeniedError, match="production_change"):
        hyperagents.Proposal(
            proposer_id="a",
            action="experiment",
            destination="sandbox",
            payload={},
            production_change=True,
        )
    with pytest.raises(errors.PolicyDeniedError, match="production"):
        _proposal(destination="production")
    with pytest.raises(errors.PolicyDeniedError, match="outside the sandbox"):
        _proposal(action="promote")


def test_proposals_cannot_self_apply_even_with_approval_and_approve_prod():
    p = _proposal()
    with pytest.raises(errors.PolicyDeniedError, match="cannot apply"):
        hyperagents.apply_proposal(p)
    with pytest.raises(errors.PolicyDeniedError, match="cannot apply"):
        hyperagents.apply_proposal(p, actor_id="human-op", approval_id="apr_x", approve_prod=True)
    promo = hyperagents.promotion_from_proposal(p, approve_prod=True, promote=True)
    assert promo["production_change"] is False
    assert promo["guard"]["production_change"] is False
    assert promo["approve_prod_ignored"] is True


def test_submit_from_proposal_allowed_gpu_claim_requires_operator(tmp_path):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60)
    q = experiment.ExperimentQueue(experiment.ResourceBroker(lf))
    p = _proposal()
    job = experiment.ExperimentJob("aira-1", "search", "gpu", {"kind": "eval"}, job_id="h1")
    submitted = hyperagents.submit_from_proposal(q, p, job)
    assert submitted.status == "pending"
    assert submitted.lineage["proposal_id"] == p.proposal_id
    assert submitted.lineage["production_change"] is False

    with pytest.raises(errors.PolicyDeniedError, match="proposing agent"):
        hyperagents.claim_from_proposal(q, p, "agent-meta", owner_kind="operator", resource="gpu", now=NOW)
    with pytest.raises(errors.PolicyDeniedError, match="named operator"):
        hyperagents.claim_from_proposal(q, p, "box-a", owner_kind="hyperagent", resource="gpu", now=NOW)

    claimed = hyperagents.claim_from_proposal(
        q, p, "box-a", owner_kind="operator", resource="gpu", now=NOW
    )
    assert claimed is not None and claimed.job_id == "h1"
    assert lf.read().owner == "box-a"
    q.start("h1", "box-a")
    q.complete("h1", "box-a", result={"ok": True})
    assert lf.read() is None


def test_proposer_cannot_issue_or_consume_own_approval():
    store = approvals.ApprovalStore()
    p = _proposal()
    with pytest.raises(errors.PolicyDeniedError, match="cannot issue"):
        hyperagents.issue_approval_for(
            store, p, approver_subject="agent-meta", approver_role="agent", goal_id="g1"
        )
    rec = hyperagents.issue_approval_for(
        store, p, approver_subject="cam", approver_role="operator", goal_id="g1"
    )
    assert rec.destination == "sandbox"
    with pytest.raises(errors.PolicyDeniedError, match="cannot consume"):
        hyperagents.consume_as_proposer(store, p, rec.approval_id, actor_id="agent-meta", goal_id="g1")
    hyperagents.consume_as_proposer(store, p, rec.approval_id, actor_id="cam", goal_id="g1")
    with pytest.raises(errors.PolicyDeniedError, match="promote"):
        hyperagents.issue_approval_for(
            store, p, approver_subject="cam", approver_role="operator", goal_id="g1", action_type="promote"
        )


def test_hyperagent_cli_apply_is_denied(tmp_path, capsys):
    payload = {
        "proposer_id": "agent-meta",
        "action": "experiment",
        "destination": "sandbox",
        "payload": {"kind": "search"},
    }
    p = tmp_path / "prop.json"
    p.write_text(json.dumps(payload))
    rc = main(["research", "hyperagent", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK
    assert out["data"]["production_change"] is False
    rc = main(["research", "hyperagent", "--file", str(p), "--apply", "--approve-prod"])
    err = capsys.readouterr()
    assert rc == EXIT_ERROR
    body = json.loads(err.out)
    assert body["ok"] is False
    assert body["error"]["code"] == "policy_denied"
