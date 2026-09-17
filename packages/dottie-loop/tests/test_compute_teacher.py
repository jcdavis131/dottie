"""Stage 4: Compute-as-Teacher offline synthesis — contracts and fail-closed cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import (
    capture,
    closed_loop,
    compute_teacher,
    errors,
    opt_lane,
    research,
    reward,
    rubric,
)
from dottie_loop.cli import EXIT_INVALID, EXIT_OK, main
from dottie_loop.schema import active

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source(trace_id: str = "trc_cat_1", user: str = "u1") -> dict:
    rec = capture.PairSessionTrace(
        session_id="s-cat",
        hashed_user_id=user,
        surface="cli",
        agent_id="dottie",
        goal={"intent": "search then prove", "task_family": "bugfix"},
        turns=[{"role": "user", "text": "please search then prove the fix"}],
        outcome={"task_ok": True, "verifier": "pass"},
        consent_version="c1",
        lineage={"deletion_key": f"del-{user}", "source_hashes": []},
        captured_at=_iso(NOW + timedelta(minutes=1)),
        checkpoints=[
            {
                "nodeId": "n",
                "agentId": "dottie",
                "attempt": 1,
                "latency_ms": 5,
                "tokens_est": 0,
                "status": "completed",
                "errorClass": None,
            }
        ],
        trace_id=trace_id,
    ).to_dict()
    return rec


def _trace(trace_id: str = "trc_cat_1") -> compute_teacher.ComputeTrace:
    return compute_teacher.ComputeTrace(
        trace_id=trace_id,
        steps=[
            compute_teacher.ComputeStep("s1", "search", "pass", detail="expand"),
            compute_teacher.ComputeStep("s2", "proof", "pass", parent_id="s1"),
            compute_teacher.ComputeStep("s3", "test", "pass", parent_id="s1"),
        ],
        verifier_outcomes=[{"check": "unit", "ok": True}],
    )


def _artifact(trace_id: str = "trc_cat_1") -> dict:
    return compute_teacher.TeacherRecord(
        teacher_id="teach_1",
        compute_trace_id=trace_id,
        artifact_kind="search_tree",
        artifact_digest="abc123",
        task_ok=True,
    ).to_dict()


LEDGER = {"u1": {"capture_training": True, "version": "c1"}}


def test_compute_trace_digest_and_empty_fails():
    t = _trace()
    assert t.to_dict()["schema"] == active("compute-trace")
    assert t.digest() == _trace().digest()
    assert t.branching()["n_branch_nodes"] == 1
    with pytest.raises(errors.InvalidInputError, match="no steps"):
        compute_teacher.ComputeTrace("x", steps=[])
    with pytest.raises(errors.InvalidInputError, match="parent_id"):
        compute_teacher.ComputeTrace(
            "x",
            [compute_teacher.ComputeStep("a", "search", "pass", parent_id="missing")],
        )


def test_synthesize_offline_happy_path_no_training_claim():
    pack = compute_teacher.synthesize_offline(
        [_trace()],
        artifacts=[_artifact()],
        consent_ledger=LEDGER,
        source_records=[_source()],
    )
    assert pack["schema"] == active("teacher-pack")
    assert pack["training"] is False
    assert pack["factory"]["live_teacher"] is False
    assert pack["factory"]["ready"] is True
    assert pack["factory"]["n_traces"] == 1
    assert pack["shards"][0]["compute_trace_id"] == _trace().digest()
    assert compute_teacher.factory_ready(pack)["outcome"] == "pass"


def test_missing_artifacts_empty_traces_schema_mismatch_fail_closed(tmp_path):
    with pytest.raises(errors.InvalidInputError, match="no traces"):
        compute_teacher.synthesize_offline(
            [],
            artifacts=[_artifact()],
            consent_ledger=LEDGER,
            source_records=[_source()],
        )
    with pytest.raises(errors.InvalidInputError, match="artifacts"):
        compute_teacher.synthesize_offline(
            [_trace()],
            artifacts=None,
            consent_ledger=LEDGER,
            source_records=[_source()],
        )
    with pytest.raises(errors.InvalidInputError, match="no teacher artifact"):
        compute_teacher.synthesize_offline(
            [_trace()],
            artifacts=[_artifact("other")],
            consent_ledger=LEDGER,
            source_records=[_source()],
        )
    with pytest.raises(errors.InvalidInputError, match="schema"):
        compute_teacher.parse_trace({"schema": "compute-trace-2.0.0", "trace_id": "x", "steps": []})
    missing = tmp_path / "nope.json"
    with pytest.raises(errors.UnexecutableError, match="missing"):
        compute_teacher.load_teacher_artifacts(missing)
    empty = tmp_path / "empty.json"
    empty.write_text("")
    with pytest.raises(errors.InvalidInputError, match="empty"):
        compute_teacher.load_teacher_artifacts(empty)
    gate = compute_teacher.factory_ready({"schema": "opt-lane-report-1.0.0"})
    assert gate["outcome"] == "no_metric"


def test_consent_refusal_and_no_quality_on_failed_task():
    with pytest.raises(errors.InvalidInputError, match="survived"):
        compute_teacher.synthesize_offline(
            [_trace()],
            artifacts=[_artifact()],
            consent_ledger={},
            source_records=[_source()],
        )
    rub = rubric.Rubric(
        "r",
        "1.0.0",
        "n",
        [rubric.RubricCriterion("c", "instruction_follow", "follow", 1.0)],
    )
    ev = rubric.evaluate_rubric(
        rub,
        rubric.Transcript(turns=[{"role": "user", "text": "hi"}]),
        rubric.ScriptedVerifier({"c": 1.0}),
        task_ok=False,
        trace_id="t9",
    )
    with pytest.raises(errors.InvalidInputError, match="task_ok"):
        compute_teacher.attach_teacher(ev, _artifact())
    ok_ev = dict(ev, task_ok=True)
    attached = compute_teacher.attach_teacher(ok_ev, _artifact())
    assert attached["quality_from_compute"] is False
    timing = opt_lane.calibrate_timing([0.4, 0.5, 0.6], warmup_n=1)
    report = opt_lane.build_report(
        task_ok=False,
        timing=timing,
        sandbox=opt_lane.SandboxProvenance("recorded", "3", "linux", "h" * 16, []),
    )
    with pytest.raises(errors.InvalidInputError, match="task_ok"):
        compute_teacher.attach_teacher(report, _artifact())


def test_closed_loop_accepts_offline_pack_without_training():
    pack = compute_teacher.synthesize_offline(
        [_trace()],
        artifacts=[_artifact()],
        consent_ledger=LEDGER,
        source_records=[_source()],
    )
    acc = closed_loop.accept_teacher_pack(pack)
    assert acc["accepted"] is True
    assert acc["live_teacher"] is False
    assert acc["training"] is False
    assert acc["production_change"] is False
    denied = closed_loop.accept_teacher_pack({})
    assert denied["accepted"] is False


def test_live_teacher_flag_denied_and_compose_does_not_claim_training():
    with pytest.raises(errors.PolicyDeniedError, match="live teacher"):
        compute_teacher.synthesize_offline(
            [_trace()],
            artifacts=[_artifact()],
            consent_ledger=LEDGER,
            source_records=[_source()],
            config=compute_teacher.TeacherConfig(allow_live_teacher=True),
        )
    pack = compute_teacher.synthesize_offline(
        [_trace()],
        artifacts=[_artifact()],
        consent_ledger=LEDGER,
        source_records=[_source()],
    )
    rub = rubric.Rubric(
        "r",
        "1.0.0",
        "n",
        [rubric.RubricCriterion("c", "instruction_follow", "follow", 1.0)],
    )
    ev = rubric.evaluate_rubric(
        rub,
        rubric.Transcript(turns=[{"role": "user", "text": "hi"}]),
        rubric.ScriptedVerifier({"c": 1.0}),
        task_ok=True,
        trace_id="t1",
    )
    bundle = research.compose_bundle(
        reward_inputs=reward.RewardInputs(trace_id="t1", task_ok=True),
        rubric_eval=ev,
        teacher_pack=pack,
    )
    assert 4 in bundle["stages"]
    assert bundle["compute_teacher"]["training"] is False
    assert bundle["promotion"] == "manual"


def test_compute_teacher_cli(tmp_path, capsys):
    payload = {
        "traces": [_trace().to_dict()],
        "artifacts": [_artifact()],
        "consent_ledger": LEDGER,
        "source_records": [_source()],
    }
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(payload))
    rc = main(["research", "compute-teacher", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK
    assert out["data"]["factory"]["ready"] is True
    assert out["data"]["training"] is False
    p.write_text(json.dumps({**payload, "traces": []}))
    rc = main(["research", "compute-teacher", "--file", str(p)])
    assert rc == EXIT_INVALID
