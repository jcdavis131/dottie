"""Stage 3: AIRA2-inspired experiment architecture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import errors, experiment, research, reward, rubric
from dottie_loop.closed_loop import LeaseFile
from dottie_loop.schema import active

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _split() -> experiment.ExperimentSplit:
    return experiment.ExperimentSplit(
        experiment_id="aira-1",
        train=["tr1", "tr2"],
        search=["se1"],
        validation=["va1", "va2"],
    )


def _pack() -> experiment.HiddenEvalPack:
    return experiment.HiddenEvalPack(
        pack_id="hid-1",
        scorer_version="scripted-1",
        items=[
            experiment.HiddenItem("va1", "solve a", gold="A", split="validation"),
            experiment.HiddenItem("va2", "solve b", gold="B", split="validation", constraints=["no peek"]),
        ],
    )


def test_fixed_split_isolation_and_digest():
    sp = _split()
    d = sp.to_dict()
    assert d["schema"] == active("experiment-split")
    assert d["counts"] == {"train": 2, "search": 1, "validation": 2}
    assert sp.assign("se1") == "search"
    assert sp.digest() == _split().digest()
    with pytest.raises(errors.InvalidInputError, match="isolation"):
        experiment.ExperimentSplit("x", train=["a"], search=["a"], validation=["b"])
    with pytest.raises(errors.InvalidInputError, match="non-empty"):
        experiment.ExperimentSplit("x", train=["a"], search=["b"], validation=[])
    with pytest.raises(errors.InvalidInputError):
        sp.assign("nope")


def test_hidden_eval_hides_labels_and_uses_external_scorer():
    pack = _pack()
    view = pack.agent_view()
    blob = str(view)
    assert "gold" not in blob and "A" not in blob and "B" not in blob
    assert {row["item_id"] for row in view} == {"va1", "va2"}
    assert all("prompt" in row and "gold" not in row for row in view)

    scorer = experiment.ScriptedScorer("scripted-1")
    scored = pack.score({"va1": "A", "va2": "wrong"}, scorer, split="validation")
    assert scored["schema"] == active("hidden-eval")
    assert scored["mean"] == 0.5 and scored["n"] == 2
    assert "gold" not in str(scored) and "label" not in str(scored)

    with pytest.raises(errors.InvalidInputError, match="scorer version"):
        pack.score({"va1": "A", "va2": "B"}, experiment.ScriptedScorer("other"))
    with pytest.raises(errors.InvalidInputError, match="missing"):
        pack.score({"va1": "A"}, scorer)
    with pytest.raises(errors.InvalidInputError, match="label"):
        experiment.HiddenEvalPack(
            "p",
            [experiment.HiddenItem("i", "q", gold=1, split="train", meta={"label": "x"})],
            "v",
        )


def test_gpu_lease_is_the_closed_loop_leasefile(tmp_path):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60)
    broker = experiment.ResourceBroker(lf)
    first = broker.acquire("gpu", "box-a", now=NOW)
    assert first["owner"] == "box-a"
    assert lf.read().owner == "box-a"
    with pytest.raises(errors.BlockedError, match="held by box-a"):
        broker.acquire("gpu", "box-b", now=NOW + timedelta(seconds=10))
    with pytest.raises(errors.BlockedError):
        broker.heartbeat("gpu", "box-b", now=NOW)
    broker.heartbeat("gpu", "box-a", now=NOW + timedelta(seconds=10))
    out = broker.release("gpu", "box-a", terminal_at="2026-09-15T13:00:00Z")
    assert out["terminal_at"] == "2026-09-15T13:00:00Z" and lf.read() is None

    bare = experiment.ResourceBroker(None)
    with pytest.raises(errors.BlockedError, match="not bypassed"):
        bare.acquire("gpu", "sneaky")
    cpu = bare.acquire("cpu", "w1")
    assert cpu["owner"] == "w1"
    with pytest.raises(errors.BlockedError, match="cpu"):
        bare.acquire("cpu", "w2")
    bare.release("cpu", "w1")


def test_queue_lineage_hidden_eval_and_debug(tmp_path):
    lf = LeaseFile(tmp_path / "lease.json", ttl_seconds=60)
    q = experiment.ExperimentQueue(experiment.ResourceBroker(lf))
    parent = q.submit(
        experiment.ExperimentJob("aira-1", "search", "cpu", {"kind": "search"}, job_id="p1")
    )
    child = q.submit(
        experiment.attach_lineage(
            experiment.ExperimentJob("aira-1", "validation", "gpu", {"kind": "eval"}, job_id="c1"),
            rubric_eval_id="rubric_x",
            opt_report_id="opt_x",
            split_digest=_split().digest(),
            parent_job_id=parent.job_id,
        )
    )
    assert child.parent_job_id == "p1"
    assert child.lineage["rubric_eval_id"] == "rubric_x"

    claimed_cpu = q.claim("worker-cpu", resource="cpu")
    assert claimed_cpu is not None and claimed_cpu.job_id == "p1"
    q.start("p1", "worker-cpu")
    q.complete("p1", "worker-cpu", result={"ok": True})
    assert q.jobs["p1"].status == "succeeded"

    claimed_gpu = q.claim("box-a", resource="gpu", now=NOW)
    assert claimed_gpu is not None and claimed_gpu.resource == "gpu"
    assert lf.read().owner == "box-a"
    q.start("c1", "box-a")
    scored = _pack().score({"va1": "A", "va2": "B"}, experiment.ScriptedScorer("scripted-1"))
    q.complete("c1", "box-a", hidden_eval=scored)
    assert lf.read() is None
    assert q.jobs["c1"].lineage["hidden_eval"]["mean"] == 1.0
    assert "gold" not in q.jobs["c1"].lineage["hidden_eval"]

    fail_job = q.submit(experiment.ExperimentJob("aira-1", "train", "cpu", {}, job_id="d1"))
    q.claim("dbg", resource="cpu")
    debug = experiment.DebugResult(
        job_id=fail_job.job_id,
        traceback="TypeError: boom",
        hypothesis="off-by-one in the reducer",
        fix_attempt="clamp the index",
        status="fix_attempted",
    )
    q.fail("d1", "dbg", debug)
    rec = q.jobs["d1"].lineage["debug"]
    assert rec["schema"] == active("debug-result")
    assert rec["traceback"] == "TypeError: boom"
    assert rec["hypothesis"] and rec["fix_attempt"]
    assert q.jobs["d1"].status == "debug"


def test_compose_with_split_does_not_weaken_task_gate():
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
    bundle = research.compose_bundle(
        reward_inputs=reward.RewardInputs(trace_id="t9", task_ok=False),
        rubric_eval=ev,
        split=_split().to_dict(),
        hidden_eval={"pack_id": "hid-1", "mean": 1.0, "n": 2, "scorer_version": "scripted-1"},
    )
    assert bundle["reward"]["components"]["quality"] == 0.0
    assert bundle["split"]["digest"] == _split().digest()
    assert bundle["hidden_eval"]["mean"] == 1.0
    assert bundle["promotion"] == "manual"
