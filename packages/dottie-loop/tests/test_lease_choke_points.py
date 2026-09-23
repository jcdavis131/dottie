"""Lease choke points (research stage 6 hardening).

An ``agent:`` subject may propose; it never holds the retraining lease, a
broker resource, a queued job or an approval. Ownership and outcome lineage
come only from claim / complete / fail; an outcome needs a job that actually
holds its lease and gives that lease back before anything is recorded; labels
never ride in a result. A non-bool ``task_ok`` earns no credit anywhere.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import (
    approvals,
    errors,
    experiment,
    hyperagents,
    opt_lane,
    reward,
    rubric,
)
from dottie_loop.closed_loop import LeaseFile
from dottie_loop.schema import active

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
NOW_ISO = "2026-09-17T12:00:00Z"
AGENT_SPELLINGS = (
    "agent:hyper-1",
    "Agent:hyper-1",
    "agent :hyper-1",
    " agent:hyper-1",
    "AGENT:other",
)
NOT_AGENTS = ("human:cam", "runner:alienware", "agent_x", "agent", "svc:agent:x", "")
NON_BOOL_TASK_OK = (1, 0, 1.0, "yes", "true", [True])


def _queue(tmp_path, with_lease: bool = True):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60) if with_lease else None
    return experiment.ExperimentQueue(experiment.ResourceBroker(lf)), lf


def _job(job_id: str, resource: str = "gpu", **kw) -> experiment.ExperimentJob:
    return experiment.ExperimentJob(
        "aira-1", "search", resource, {"cmd": "x"}, job_id=job_id, **kw
    )


def _proposal(proposer_id: str = "agent-meta") -> hyperagents.Proposal:
    return hyperagents.propose(
        proposer_id=proposer_id,
        action="experiment",
        destination="sandbox",
        payload={"kind": "search", "split": "search"},
    )


def _record(approval_id: str, approver: dict[str, str], **over) -> dict:
    base = {
        "approval_id": approval_id,
        "approver": approver,
        "action": "promote",
        "digest": approvals.action_digest("promote", {"artifact": "x"}, "production"),
        "destination": "production",
        "scope": {"goal_id": "g", "limits": {}},
        "issued_at": "2026-09-17T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    base.update(over)
    return approvals.ApprovalRecord(**base).to_dict()


def _consume(store: approvals.ApprovalStore, approval_id: str) -> approvals.ApprovalRecord:
    return store.verify_and_consume(
        approval_id,
        action_type="promote",
        payload={"artifact": "x"},
        destination="production",
        goal_id="g",
        now=NOW,
    )


def _sandbox() -> opt_lane.SandboxProvenance:
    return opt_lane.SandboxProvenance("recorded", "3.11", "linux", "abcd1234", [])


def _rubric_eval(task_ok) -> dict:
    rub = rubric.Rubric(
        "r", "1.0.0", "n", [rubric.RubricCriterion("c", "instruction_follow", "follow", 1.0)]
    )
    return rubric.evaluate_rubric(
        rub,
        rubric.Transcript(turns=[{"role": "user", "text": "hi"}]),
        rubric.ScriptedVerifier({"c": 1.0}),
        task_ok=task_ok,
        trace_id="t1",
    )


# --- is_agent_subject -------------------------------------------------------------


def test_is_agent_subject_recognises_every_spelling_of_an_agent_principal():
    assert approvals.AGENT_SUBJECT_PREFIX == "agent:"
    assert "is_agent_subject" in approvals.__all__
    assert "AGENT_SUBJECT_PREFIX" in approvals.__all__
    for spelling in AGENT_SPELLINGS:
        assert approvals.is_agent_subject(spelling), spelling
    for other in NOT_AGENTS:
        assert not approvals.is_agent_subject(other), other
    # only strings are subjects; anything else is not an agent (and not a crash)
    for not_a_string in (None, 1, b"agent:x", ["agent:x"], {"subject_id": "agent:x"}):
        assert not approvals.is_agent_subject(not_a_string)


# --- (a) LeaseFile.acquire ----------------------------------------------------------


def test_leasefile_refuses_agent_subjects_and_accepts_a_named_operator(tmp_path):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60)
    for spelling in AGENT_SPELLINGS:
        with pytest.raises(errors.PolicyDeniedError, match="agent subject cannot hold") as ei:
            lf.acquire(spelling, now=NOW)
        assert ei.value.field == "owner" and ei.value.code == "policy_denied"
        assert ei.value.status == 403 and ei.value.retryable is False
    # refused before the lock sidecar or the lease is even touched
    assert lf.read() is None and list(tmp_path.iterdir()) == []

    lease = lf.acquire("human:cam", now=NOW)
    assert lease.owner == "human:cam" and lf.read().owner == "human:cam"
    # while an operator holds it, an agent is still refused by policy, not by the lease
    with pytest.raises(errors.PolicyDeniedError, match="agent subject cannot hold"):
        lf.acquire("agent:hyper-1", now=NOW + timedelta(seconds=10))
    # heartbeat / release from a non-owner are the unchanged lease rules
    with pytest.raises(errors.BlockedError, match="non-owner"):
        lf.heartbeat("agent:hyper-1", now=NOW)
    with pytest.raises(errors.BlockedError, match="non-owner"):
        lf.release("agent:hyper-1")
    assert lf.read().owner == "human:cam"
    # a crashed lease is reclaimable after expiry by an operator, never by an agent
    later = NOW + timedelta(seconds=120)
    with pytest.raises(errors.PolicyDeniedError, match="agent subject cannot hold"):
        lf.acquire("agent:hyper-1", now=later)
    assert lf.read().owner == "human:cam"
    reclaimed = lf.acquire("runner:alienware", now=later, live_runners=set())
    assert reclaimed.owner == "runner:alienware" and lf.read().owner == "runner:alienware"


# --- (b) ResourceBroker.acquire -------------------------------------------------------


def test_resource_broker_refuses_agent_owners_for_every_resource(tmp_path):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60)
    broker = experiment.ResourceBroker(lf)
    for resource in experiment.RESOURCES:
        with pytest.raises(errors.PolicyDeniedError, match="agent cannot hold") as ei:
            broker.acquire(resource, "agent:hyper-1", now=NOW)
        assert ei.value.field == "owner"
    for spelling in AGENT_SPELLINGS:
        with pytest.raises(errors.PolicyDeniedError, match="agent cannot hold"):
            broker.acquire("gpu", spelling, now=NOW)
    # nothing was held: the lease file is empty and every resource is still free
    assert lf.read() is None
    assert broker.acquire("cpu", "w1")["owner"] == "w1"
    assert broker.acquire("disk", "w1")["owner"] == "w1"
    assert broker.acquire("gpu", "human:cam", now=NOW)["owner"] == "human:cam"
    assert lf.read().owner == "human:cam"
    # an unknown resource is still the first refusal (typed input error, not policy)
    with pytest.raises(errors.InvalidInputError, match="unknown resource") as ei2:
        broker.acquire("tpu", "agent:hyper-1")
    assert ei2.value.field == "resource"

    # without a lease file the agent is refused by policy BEFORE the missing-file block
    bare = experiment.ResourceBroker(None)
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot hold"):
        bare.acquire("gpu", "agent:hyper-1")
    with pytest.raises(errors.BlockedError, match="not bypassed"):
        bare.acquire("gpu", "human:cam")
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot hold"):
        bare.acquire("cpu", "Agent:hyper-1")
    assert bare.acquire("cpu", "w1")["owner"] == "w1"


# --- (c) ExperimentQueue.claim --------------------------------------------------------


def test_queue_claim_refuses_agents_before_any_job_is_touched(tmp_path):
    q, lf = _queue(tmp_path)
    # an empty queue does not return None for an agent: the refusal precedes the scan
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        q.claim("agent:hyper-1", resource="gpu", now=NOW)
    job = q.submit(_job("direct"))
    for spelling in AGENT_SPELLINGS:
        with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim") as ei:
            q.claim(spelling, resource="gpu", now=NOW)
        assert ei.value.field == "owner"
        with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
            q.claim(spelling, now=NOW)
    assert lf.read() is None
    assert job.status == "pending" and job.owner is None
    assert "leased_at" not in job.lineage and "lease_owner" not in job.lineage
    # main's operator wrapper cannot launder an agent subject with owner_kind="operator"
    p = _proposal()
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        hyperagents.claim_from_proposal(
            q, p, "agent:hyper-2", owner_kind="operator", resource="gpu", now=NOW
        )
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        hyperagents.claim_from_proposal(q, p, "Agent:hyper-2", owner_kind="human", now=NOW)
    assert lf.read() is None and job.status == "pending"
    # a named operator claims, and the claim IS the closed-loop lease file
    claimed = q.claim("human:cam", resource="gpu", now=NOW)
    assert claimed is job and job.status == "leased" and job.owner == "human:cam"
    assert lf.read().owner == "human:cam" and job.lineage["lease_owner"] == "human:cam"


def test_queue_claim_refuses_the_recorded_proposer_even_when_lineage_is_edited(tmp_path):
    q, lf = _queue(tmp_path)
    job = q.submit(_job("prop", lineage={"proposer": "agent:hyper-1", "proposed_by": "agent"}))
    assert job.lineage["proposer"] == "agent:hyper-1"  # submit keeps proposal lineage
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        q.claim("agent:hyper-1", resource="gpu", now=NOW)
    # editing the lineage the proposer wrote does not help the agent
    job.lineage["proposed_by"] = "operator"
    job.lineage.pop("proposer")
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        q.claim("agent:hyper-1", resource="gpu", now=NOW)
    # a hand-written lineage naming a non-agent proposer still cannot self-claim
    job.lineage["proposer"] = "runner:alienware"
    for spelling in ("runner:alienware", "Runner:Alienware", " runner:alienware "):
        with pytest.raises(errors.PolicyDeniedError, match="never claimed by its proposer") as ei:
            q.claim(spelling, resource="gpu", now=NOW)
        assert ei.value.field == "owner"
    with pytest.raises(errors.PolicyDeniedError, match="never claimed by its proposer"):
        q.claim("runner:alienware", now=NOW)
    assert lf.read() is None and job.status == "pending" and job.owner is None
    # the refusal is bound to the job that names the proposer, not to the subject
    other = q.submit(_job("plain", resource="cpu"))
    taken = q.claim("runner:alienware", resource="cpu")
    assert taken is other and other.owner == "runner:alienware"
    assert job.status == "pending" and job.owner is None
    # a different operator claims the proposed job
    claimed = q.claim("human:cam", resource="gpu", now=NOW)
    assert claimed is job and job.owner == "human:cam" and lf.read().owner == "human:cam"
    assert job.lineage["proposer"] == "runner:alienware"


def test_agent_proposer_lineage_from_main_wrapper_never_claims(tmp_path):
    q, lf = _queue(tmp_path)
    p = _proposal(proposer_id="agent:hyper-9")
    job = hyperagents.submit_from_proposal(q, p, _job("h9"))
    assert job.status == "pending" and job.owner is None
    assert job.lineage["proposer_id"] == "agent:hyper-9"
    assert job.lineage["production_change"] is False
    # the wrapper refuses its proposer; the primitive refuses the agent regardless
    with pytest.raises(errors.PolicyDeniedError, match="proposing agent"):
        hyperagents.claim_from_proposal(q, p, "agent:hyper-9", owner_kind="operator", now=NOW)
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        q.claim("agent:hyper-9", resource="gpu", now=NOW)
    job.lineage["proposer"] = "agent:hyper-9"
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot claim"):
        q.claim("agent:hyper-9", resource="gpu", now=NOW)
    assert lf.read() is None and job.status == "pending"
    claimed = hyperagents.claim_from_proposal(
        q, p, "human:cam", owner_kind="operator", resource="gpu", now=NOW
    )
    assert claimed is job and lf.read().owner == "human:cam"
    q.start("h9", "human:cam")
    q.complete("h9", "human:cam", result={"ok": True})
    assert lf.read() is None and job.status == "succeeded"


# --- (d) submit ----------------------------------------------------------------------


def test_submit_drops_caller_set_owner_status_and_outcome_lineage(tmp_path):
    assert experiment.OUTCOME_LINEAGE_KEYS == (
        "leased_at",
        "lease_owner",
        "started_at",
        "completed_at",
        "failed_at",
        "result",
        "hidden_eval",
        "debug",
    )
    assert "OUTCOME_LINEAGE_KEYS" in experiment.__all__
    q, lf = _queue(tmp_path)
    forged = {k: f"forged-{k}" for k in experiment.OUTCOME_LINEAGE_KEYS}
    forged["result"] = {"ok": True}
    forged["hidden_eval"] = {"mean": 1.0}
    pre = _job(
        "pre",
        owner="agent:hyper-1",
        status="succeeded",
        lineage={**forged, "proposer": "agent:hyper-1", "rubric_eval_id": "rubric_x"},
    )
    out = q.submit(pre)
    assert out is pre and pre.status == "pending" and pre.owner is None
    assert pre.to_dict()["owner"] is None and pre.to_dict()["status"] == "pending"
    for stale in experiment.OUTCOME_LINEAGE_KEYS:
        assert stale not in pre.lineage, stale
    # non-outcome lineage survives; submitted_at is stamped
    assert pre.lineage["proposer"] == "agent:hyper-1"
    assert pre.lineage["rubric_eval_id"] == "rubric_x"
    assert set(pre.lineage) == {"proposer", "rubric_eval_id", "submitted_at"}
    assert lf.read() is None
    # a bare job carries only submitted_at
    bare = q.submit(_job("bare", owner="human:cam", lineage={"lease_owner": "human:cam"}))
    assert bare.owner is None and set(bare.lineage) == {"submitted_at"}
    # through main's proposal wrapper the same scrub applies
    p = _proposal()
    via = hyperagents.submit_from_proposal(
        q, p, _job("viaprop", owner="agent-meta", lineage={"result": {"ok": True}})
    )
    assert via.owner is None and "result" not in via.lineage
    assert via.lineage["proposal_id"] == p.proposal_id
    assert via.lineage["production_change"] is False


# --- (e) complete / fail need a held lease ---------------------------------------------


def test_outcome_needs_a_job_that_holds_its_lease(tmp_path):
    q, lf = _queue(tmp_path)
    pre = q.submit(_job("pre"))
    debug = experiment.DebugResult(job_id="pre", traceback="boom")
    # never leased and unowned: not owned by anyone, so no outcome
    with pytest.raises(errors.BlockedError, match="not owned"):
        q.complete("pre", "agent:hyper-1", result={"ok": True})
    with pytest.raises(errors.BlockedError, match="not owned"):
        q.fail("pre", "agent:hyper-1", debug)
    # a stale in-memory owner without a claim still cannot record an outcome
    pre.owner = "human:cam"
    with pytest.raises(errors.BlockedError, match="leased or running") as ei:
        q.complete("pre", "human:cam", result={"ok": True})
    assert ei.value.details["dependency"] == "lease"
    with pytest.raises(errors.BlockedError, match="leased or running") as ei2:
        q.fail("pre", "human:cam", debug)
    assert ei2.value.details["dependency"] == "lease"
    assert pre.status == "pending" and lf.read() is None
    for key in ("result", "completed_at", "failed_at", "debug"):
        assert key not in pre.lineage, key

    # the honest path: claim -> start -> complete releases the lease and records
    pre.owner = None
    job = q.claim("human:cam", resource="gpu", now=NOW)
    assert job is pre and lf.read().owner == "human:cam"
    q.start("pre", "human:cam")
    q.complete("pre", "human:cam", result={"ok": True})
    assert pre.status == "succeeded" and lf.read() is None
    assert pre.lineage["result"] == {"ok": True} and "completed_at" in pre.lineage
    first_completed_at = pre.lineage["completed_at"]
    # a finished job holds no lease, so it can record no second outcome
    with pytest.raises(errors.BlockedError, match="leased or running"):
        q.complete("pre", "human:cam", result={"ok": False})
    with pytest.raises(errors.BlockedError, match="leased or running"):
        q.fail("pre", "human:cam", debug)
    assert pre.status == "succeeded" and pre.lineage["completed_at"] == first_completed_at
    assert pre.lineage["result"] == {"ok": True} and "debug" not in pre.lineage

    # leased (not yet started) is enough to fail; the resource is given back
    d1 = q.submit(_job("d1", resource="cpu"))
    q.claim("dbg", resource="cpu")
    q.fail("d1", "dbg", experiment.DebugResult(job_id="d1", traceback="TypeError: boom"))
    assert d1.status == "debug" and "failed_at" in d1.lineage
    assert q.broker.acquire("cpu", "w2")["owner"] == "w2"


def test_complete_and_fail_give_the_lease_back_before_recording(tmp_path, monkeypatch):
    q, lf = _queue(tmp_path)
    q.submit(_job("g1"))
    job = q.claim("human:cam", resource="gpu", now=NOW)
    q.start("g1", "human:cam")
    debug = experiment.DebugResult(job_id="g1", traceback="boom")
    # the lease went away underneath the running job: a lost lease records no success
    lf.release("human:cam")
    with pytest.raises(errors.BlockedError, match="non-owner"):
        q.complete("g1", "human:cam", result={"ok": True})
    with pytest.raises(errors.BlockedError, match="non-owner"):
        q.fail("g1", "human:cam", debug)
    assert job.status == "running"
    for key in ("result", "completed_at", "failed_at", "debug"):
        assert key not in job.lineage, key
    # someone else holding the GPU does not change that
    lf.acquire("runner:alienware", now=NOW)
    with pytest.raises(errors.BlockedError, match="non-owner"):
        q.complete("g1", "human:cam", result={"ok": True})
    assert job.status == "running" and "result" not in job.lineage
    assert lf.read().owner == "runner:alienware"
    lf.release("runner:alienware")

    # ordering: release happens while the job is still unfinished and unrecorded
    seen: list[dict] = []
    real_release = q.broker.release

    def spy(resource: str, owner: str, **kw):
        target = q.jobs[current["job_id"]]
        seen.append({"status": target.status, "lineage": dict(target.lineage), "resource": resource, "owner": owner})
        return real_release(resource, owner, **kw)

    monkeypatch.setattr(q.broker, "release", spy)
    current = {"job_id": "g2"}
    g2 = q.submit(_job("g2"))
    q.claim("human:cam", resource="gpu", now=NOW)
    q.start("g2", "human:cam")
    q.complete("g2", "human:cam", result={"ok": True})
    assert g2.status == "succeeded" and lf.read() is None
    assert seen[-1]["status"] == "running" and seen[-1]["resource"] == "gpu"
    assert "completed_at" not in seen[-1]["lineage"] and "result" not in seen[-1]["lineage"]
    current = {"job_id": "g3"}
    g3 = q.submit(_job("g3", resource="cpu"))
    q.claim("human:cam", resource="cpu")
    q.fail("g3", "human:cam", experiment.DebugResult(job_id="g3", traceback="boom"))
    assert g3.status == "debug"
    assert seen[-1]["status"] == "leased" and seen[-1]["resource"] == "cpu"
    assert "failed_at" not in seen[-1]["lineage"] and "debug" not in seen[-1]["lineage"]


def test_result_and_hidden_eval_are_checked_for_leaks_before_the_lease_moves(tmp_path):
    q, lf = _queue(tmp_path)
    q.submit(_job("g1"))
    job = q.claim("human:cam", resource="gpu", now=NOW)
    q.start("g1", "human:cam")
    leaky_results = (
        {"gold": {"q1": "42"}},
        {"ok": True, "rows": [{"answer": 1}]},
        {"cases": ({"label": 1},)},
        {"a": {"b": {"c": {"target": 0}}}},
    )
    for bad in leaky_results:
        with pytest.raises(errors.InvalidInputError, match="hidden eval leak"):
            q.complete("g1", "human:cam", result=bad)
    with pytest.raises(errors.InvalidInputError, match="hidden eval leak") as ei:
        q.complete("g1", "human:cam", result={"gold": 1})
    assert ei.value.field == "gold"
    with pytest.raises(errors.InvalidInputError, match="hidden eval leak"):
        q.complete(
            "g1",
            "human:cam",
            hidden_eval={
                "pack_id": "pk",
                "mean": 1.0,
                "n": 1,
                "scorer_version": "s",
                "rows": [{"item_id": "q1", "score": 1.0, "expected": "A"}],
            },
        )
    # refused before the lease moved: the job still runs and still holds the GPU
    assert job.status == "running" and lf.read().owner == "human:cam"
    assert "result" not in job.lineage and "hidden_eval" not in job.lineage
    assert "completed_at" not in job.lineage
    # the honest result lands, the lease is gone, and hidden eval is reduced to its summary
    q.complete(
        "g1",
        "human:cam",
        result={"ok": True, "log": "x" * 10},
        hidden_eval={
            "pack_id": "pk",
            "mean": 0.5,
            "n": 2,
            "scorer_version": "s",
            "rows": [{"item_id": "q1", "score": 1.0}],
        },
    )
    assert job.status == "succeeded" and lf.read() is None
    assert job.lineage["result"] == {"ok": True, "log": "x" * 10}
    assert job.lineage["hidden_eval"] == {"pack_id": "pk", "mean": 0.5, "n": 2, "scorer_version": "s"}
    experiment.assert_no_leak(job.to_dict())


def test_assert_no_leak_is_public_and_walks_every_container():
    assert "assert_no_leak" in experiment.__all__
    assert not hasattr(experiment, "_assert_no_leak")
    for clean in (
        {},
        [],
        (),
        set(),
        frozenset(),
        None,
        "gold",
        {"x": "gold", "golden": 1, "labelled": 2},
        {"a": [({"b": (1, 2)},)]},
        (frozenset({("x",)}), [{"ok": True}]),
    ):
        experiment.assert_no_leak(clean)
    for key in experiment.HIDDEN_LEAK_KEYS:
        with pytest.raises(errors.InvalidInputError, match="hidden eval leak") as ei:
            experiment.assert_no_leak({key: 1})
        assert ei.value.field == key
    for leaky in (
        [{"label": 1}],
        ({"labels": []},),
        {"a": [({"answer": 1},)]},
        {"a": {"b": {"c": {"target": 0}}}},
        [[[{"score_detail": {}}]]],
    ):
        with pytest.raises(errors.InvalidInputError, match="hidden eval leak"):
            experiment.assert_no_leak(leaky)


# --- (f) ApprovalStore ----------------------------------------------------------------


def test_approval_store_refuses_agent_approvers_at_issue():
    st = approvals.ApprovalStore()
    for subject, role in (
        ("agent:hyper-1", "agent"),
        ("agent :hyper-1", "operator"),
        ("Agent:hyper-1", "human"),
        ("cam", "Agent"),
        ("cam", " agent "),
    ):
        with pytest.raises(errors.PolicyDeniedError, match="agent cannot approve") as ei:
            st.issue(
                approver_subject=subject,
                approver_role=role,
                action_type="promote",
                payload={"artifact": "x"},
                destination="production",
                goal_id="g",
                now=NOW,
            )
        assert ei.value.field == "approver"
    assert st.history == []  # nothing was issued or recorded
    rec = st.issue(
        approver_subject="human:cam",
        approver_role="operator",
        action_type="promote",
        payload={"artifact": "x"},
        destination="production",
        goal_id="g",
        now=NOW,
    )
    assert rec.approver == {"subject_id": "human:cam", "role": "operator"}
    assert _consume(st, rec.approval_id).consumed_at == NOW_ISO
    # main's proposal wrapper: a non-proposer agent subject is still refused by the store
    p = _proposal()
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot approve"):
        hyperagents.issue_approval_for(
            st, p, approver_subject="agent:reviewer", approver_role="operator", goal_id="g1"
        )
    with pytest.raises(errors.PolicyDeniedError, match="agent cannot approve"):
        hyperagents.issue_approval_for(
            st, p, approver_subject="cam", approver_role="agent", goal_id="g1"
        )
    assert hyperagents.issue_approval_for(
        st, p, approver_subject="cam", approver_role="operator", goal_id="g1"
    ).approver["subject_id"] == "cam"


def test_verify_and_consume_rejects_a_stored_record_whose_approver_is_an_agent(tmp_path):
    path = tmp_path / "approvals.json"
    records = [
        _record("apr_agent", {"subject_id": "agent:hyper-1", "role": "agent"}),
        _record("apr_role", {"subject_id": "cam", "role": "Agent"}),
        _record("apr_spaced", {"subject_id": " Agent :hyper-1", "role": "operator"}),
        _record(
            "apr_expired_agent",
            {"subject_id": "agent:hyper-1", "role": "agent"},
            expires_at="2000-01-01T00:00:00Z",
        ),
        _record("apr_human", {"subject_id": "human:cam", "role": "operator"}),
    ]
    path.write_text(
        json.dumps({"records": records, "history": [], "replay_attempts": 0}), encoding="utf-8"
    )
    st = approvals.ApprovalStore.load(path)
    assert st.history == [] and st.replay_attempts == 0
    for approval_id in ("apr_agent", "apr_role", "apr_spaced", "apr_expired_agent"):
        for _attempt in range(2):
            with pytest.raises(errors.PolicyDeniedError, match="issued by an agent") as ei:
                _consume(st, approval_id)
            assert ei.value.field == "approver"
            assert st.history[-1] == {
                "event": "agent_approver_rejected",
                "at": NOW_ISO,
                "approval_id": approval_id,
            }
    # never consumed, never counted as a replay, and the expiry check never got a say
    assert st.replay_attempts == 0
    assert [h["event"] for h in st.history] == ["agent_approver_rejected"] * 8
    # the human record from the same file consumes normally
    human = _consume(st, "apr_human")
    assert human.consumed_at == NOW_ISO and st.history[-1]["event"] == "consumed"
    with pytest.raises(errors.ApprovalRequiredError, match="replay"):
        _consume(st, "apr_human")
    assert st.replay_attempts == 1
    # the rejections persist and the agent record is still refused after a reload
    st.save(path)
    again = approvals.ApprovalStore.load(path)
    assert [h["event"] for h in again.history].count("agent_approver_rejected") == 8
    with pytest.raises(errors.PolicyDeniedError, match="issued by an agent"):
        _consume(again, "apr_agent")
    saved = json.loads(path.read_text(encoding="utf-8"))
    by_id = {r["approval_id"]: r for r in saved["records"]}
    assert by_id["apr_agent"]["consumed_at"] is None
    assert by_id["apr_human"]["consumed_at"] == NOW_ISO
    assert by_id["apr_agent"]["schema"] == active("approval-record")


# --- (g) non-bool task_ok -------------------------------------------------------------


def test_reward_refuses_non_bool_task_ok_and_keeps_none_as_unknown():
    for bad in NON_BOOL_TASK_OK:
        with pytest.raises(errors.InvalidInputError, match="task_ok") as ei:
            reward.compute_reward(reward.RewardInputs(trace_id="t1", task_ok=bad))
        assert ei.value.field == "task_ok"
        with pytest.raises(errors.InvalidInputError, match="task_ok"):
            reward.compute_reward_with_rubric(
                reward.RewardInputs(trace_id="t1", task_ok=bad), _rubric_eval(True)
            )
    unknown = reward.compute_reward(reward.RewardInputs(trace_id="t1", task_ok=None))
    assert unknown["components"]["task_ok"] is None and "task_ok" in unknown["components_missing"]
    assert "task_ok:unknown(no valid verifier)" in unknown["evidence"]
    assert reward.compute_reward(reward.RewardInputs(trace_id="t1", task_ok=True))["components"]["task_ok"] == 1.0
    assert reward.compute_reward(reward.RewardInputs(trace_id="t1", task_ok=False))["components"]["task_ok"] == 0.0


def test_rubric_refuses_non_bool_task_ok_and_keeps_none_as_unknown():
    for bad in NON_BOOL_TASK_OK:
        with pytest.raises(errors.InvalidInputError, match="task_ok") as ei:
            _rubric_eval(bad)
        assert ei.value.field == "task_ok"
    unknown = _rubric_eval(None)
    assert unknown["task_ok"] is None and unknown["gate"] == "unknown"
    assert unknown["gated_score"] is None and unknown["task_success"] is False
    assert _rubric_eval(True)["gate"] == "open" and _rubric_eval(False)["gate"] == "task_failed"


def test_opt_lane_refuses_non_bool_task_ok_including_none():
    timing = opt_lane.calibrate_timing([0.4, 0.5, 0.6], warmup_n=1)
    for bad in (*NON_BOOL_TASK_OK, None):
        with pytest.raises(errors.InvalidInputError, match="task_ok") as ei:
            opt_lane.build_report(task_ok=bad, timing=timing, sandbox=_sandbox(), baseline_s=[1.0, 0.9])
        assert ei.value.field == "task_ok"
    # task_ok is checked before the timing is: a truthy int gets no further than the gate
    with pytest.raises(errors.InvalidInputError, match="task_ok") as ei2:
        opt_lane.build_report(task_ok=1, timing={}, sandbox=_sandbox())
    assert ei2.value.field == "task_ok"
    ok = opt_lane.build_report(task_ok=True, timing=timing, sandbox=_sandbox(), baseline_s=[1.0, 0.9])
    bad_run = opt_lane.build_report(task_ok=False, timing=timing, sandbox=_sandbox(), baseline_s=[1.0, 0.9])
    assert ok["task_ok"] is True and ok["correctness"] == 1.0
    assert bad_run["task_ok"] is False and bad_run["speed_credit"] == 0.0


def test_claim_refuses_the_proposer_id_main_wrapper_records_without_a_proposer_key(tmp_path):
    """main's submit_from_proposal records ``proposer_id`` (not ``proposer``); the primitive
    must refuse that subject too, including casefold/strip spellings, with nothing held."""
    q, lf = _queue(tmp_path)
    p = _proposal(proposer_id="runner:alienware")
    job = hyperagents.submit_from_proposal(q, p, _job("r1"))
    assert "proposer" not in job.lineage and job.lineage["proposer_id"] == "runner:alienware"
    for spelling in ("runner:alienware", "Runner:Alienware", " runner:alienware "):
        with pytest.raises(errors.PolicyDeniedError, match="never claimed by its proposer"):
            q.claim(spelling, resource="gpu", now=NOW)
        assert lf.read() is None and job.status == "pending" and job.owner is None
    claimed = q.claim("human:cam", resource="gpu", now=NOW)
    assert claimed is job and lf.read().owner == "human:cam"


def test_cli_opt_lane_does_not_coerce_task_ok_before_the_typed_guard(tmp_path, capsys):
    """``research opt-lane`` used to do ``bool(raw["task_ok"])``, so a JSON ``1`` became
    ``True`` and the typed guard in build_report was unreachable from the CLI."""
    from dottie_loop import opt_lane
    from dottie_loop.cli import EXIT_INVALID, EXIT_OK, main

    def payload(task_ok):
        return {
            "task_ok": task_ok,
            "warmup_n": opt_lane.MIN_WARMUP,
            "samples_s": [0.2] * (opt_lane.MIN_WARMUP + 8),
            "sandbox": {
                "kind": "local",
                "python": "3.11.0",
                "platform": "linux",
                "hostname_hash": "a" * 64,
            },
        }

    for bad in (1, "yes", 0, None):
        f = tmp_path / "opt.json"
        f.write_text(json.dumps(payload(bad)))
        rc = main(["research", "opt-lane", "--file", str(f)])
        out = capsys.readouterr().out.strip().splitlines()
        env = json.loads(out[-1])
        assert rc == EXIT_INVALID, (bad, env)
        assert "task_ok" in json.dumps(env), (bad, env)
    f = tmp_path / "ok.json"
    f.write_text(json.dumps(payload(True)))
    rc = main(["research", "opt-lane", "--file", str(f)])
    env = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == EXIT_OK, env
