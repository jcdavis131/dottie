"""Phase 8 acceptance: ML-13 attributable canary with a predetermined stop, Runbook B 16
deletion canary before a release is usable, ML-07 reproducibility, §37D opaque cursors."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import canary, dataset, errors, evaluation, surfaces, training
from dottie_loop.intake import GoalStore

PLAN = dict.fromkeys(evaluation.CANARY_REQUIREMENTS, True)


def _t(minutes_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def test_canary_is_attributable_limited_and_stops_where_planned():
    with pytest.raises(errors.UnexecutableError):
        canary.CanaryRun(plan={**PLAN, "manual_stop_tested": False}, incumbent_id="inc", challenger_id="ch", stop_after=4)
    with pytest.raises(errors.InvalidInputError):
        canary.CanaryRun(plan=PLAN, incumbent_id="same", challenger_id="same", stop_after=4)
    c = canary.CanaryRun(plan=PLAN, incumbent_id="inc", challenger_id="ch", stop_after=4)
    with pytest.raises(errors.InvalidInputError):  # ML-13: no artifact id, no event
        c.observe({"event_time": _t(), "ok": True, "latency_ms": 5})
    with pytest.raises(errors.InvalidInputError):
        c.observe({"artifact_id": "someone-else", "event_time": _t(), "ok": True, "latency_ms": 5})
    for ok in (True, True, True, False):
        c.observe({"artifact_id": "inc", "event_time": _t(), "ok": ok, "latency_ms": 5})
    for _ in range(3):
        c.observe({"artifact_id": "ch", "event_time": _t(), "ok": True, "latency_ms": 4})
    with pytest.raises(errors.UnexecutableError):  # not at the predetermined stop
        c.decision_packet()
    with pytest.raises(errors.PolicyDeniedError):
        c.extend(stop_after=40)
    c.observe({"artifact_id": "ch", "event_time": _t(), "ok": True, "latency_ms": 4})
    packet = c.decision_packet()
    assert packet["status"] == "complete" and packet["n"] == {"incumbent": 4, "challenger": 4} and packet["challenger_metric"] == 1.0 and packet["baseline_metric"] == 0.75
    assert packet["recommendation"] == "present_for_approval" and packet["stop"]["kind"] == "predetermined"
    with pytest.raises(errors.PolicyDeniedError):  # nothing counts after the stop
        c.observe({"artifact_id": "ch", "event_time": _t(), "ok": True, "latency_ms": 4})
    gates = {"failed": [], "bundle_id": "b"}
    assert evaluation.promotion_decision(gates, canary=packet, approval_valid=True)["outcome"] == "promote"
    assert evaluation.promotion_decision(gates, canary=packet, approval_valid=False)["outcome"] == "block"

    # safety is stricter than the primary metric: one unsafe challenger event breaches
    s = canary.CanaryRun(plan=PLAN, incumbent_id="inc", challenger_id="ch", stop_after=2)
    s.observe({"artifact_id": "ch", "event_time": _t(), "ok": True, "latency_ms": 4, "safety_ok": False})
    assert s.thresholds()["breaches"] == ["safety_floor"] and s.thresholds()["rollback_now"]
    s.manual_stop(actor="cam", reason="safety breach")
    assert s.decision_packet()["recommendation"] == "rollback"
    # stale events never make a packet
    st = canary.CanaryRun(plan=PLAN, incumbent_id="inc", challenger_id="ch", stop_after=1, freshness_s=60)
    st.observe({"artifact_id": "ch", "event_time": _t(minutes_ago=5), "ok": True, "latency_ms": 4})
    with pytest.raises(errors.StaleEvidenceError):
        st.decision_packet()


def test_release_is_usable_only_after_a_passing_deletion_canary():
    ln = dataset.Lineage()
    ln.register_trace("trc_1", "del-u1")
    approved = {"dataset_id": "ds_1", "trace_ids": ["trc_1"], "status": "approved", "approved_by": "reviewer"}
    ln.register_manifest(approved)
    before = ln.to_dict()
    proof = dataset.canary_deletion_test(ln, approved)
    assert proof["ok"] and proof["promotion_blocked"] and proof["receipt_status"] == "complete"
    assert ln.to_dict() == before  # the real lineage is untouched by the probe
    usable = dataset.mark_release_usable(approved, proof)
    assert usable["usable"] and usable["deletion_proof"]["promotion_blocked"]
    with pytest.raises(errors.UnexecutableError):
        dataset.mark_release_usable({**approved, "status": "candidate"}, proof)
    with pytest.raises(errors.UnexecutableError):
        dataset.mark_release_usable({**approved, "dataset_id": "ds_other"}, proof)
    with pytest.raises(errors.UnexecutableError):
        dataset.mark_release_usable(approved, {**proof, "ok": False})


def _train_run(seed=1, lr=0.001):
    return training.TrainRun(objective="sft", parent_checkpoint="ckpt-0", dataset_manifest="ds-1", code_commit="abc1234", tokenizer_hash="tok", model={"architecture": "tiny", "parameters": 1, "context": 128}, optimizer={"name": "adamw", "lr": lr, "schedule": "cosine", "weight_decay": 0.1}, batch={"micro": 2, "grad_accum": 2, "global": 4, "packing": "concat"}, hardware={"runner": "box", "gpu": "x", "vram_gb": 8, "cuda": "12"}, budgets={"max_steps": 10, "max_hours": 1, "max_cost": 1}, seed=seed)


def test_reproducibility_needs_identical_inputs_and_compatible_metrics():
    a, b = _train_run(), _train_run()
    ok = training.reproducibility_check(a, b, {"loss": 1.00, "acc": 0.80}, {"loss": 1.005, "acc": 0.80})
    assert ok["ok"] and ok["deltas"] == {"loss": 0.005, "acc": 0.0} and ok["runs"] == [a.run_id, b.run_id]
    bad = training.reproducibility_check(a, b, {"loss": 1.0, "acc": 0.8}, {"loss": 1.5, "kl": 0.1})
    assert not bad["ok"] and bad["incompatible"] == ["loss"] and bad["metrics_on_one_side_only"] == ["acc", "kl"]
    assert not training.reproducibility_check(a, _train_run(seed=2), {"loss": 1.0}, {"loss": 1.0})["same_seed"]
    assert not training.reproducibility_check(a, _train_run(lr=0.01), {"loss": 1.0}, {"loss": 1.0})["same_inputs"]
    assert not training.reproducibility_check(a, b, {}, {})["ok"]  # no shared metric is no evidence
    with pytest.raises(errors.InvalidInputError):
        training.reproducibility_check(a, b, {}, {}, tolerance=-1)


def _http(url, *, bearer=None):
    req = urllib.request.Request(url)  # noqa: S310 - loopback test server
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback test server
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_goal_listing_uses_opaque_cursors_bound_to_scope(tmp_path):
    goals = GoalStore(tmp_path / "goals")
    for i in range(5):
        goals.submit({"idempotency_key": f"c{i}", "intent_text": f"goal {i}"}, authenticated_subject="cam", surface="api")
    goals.submit({"idempotency_key": "o1", "intent_text": "other"}, authenticated_subject="oli", surface="api")
    state = surfaces.ApiState(goals, principals={"tok-cam": "cam", "tok-oli": "oli"})
    api = surfaces.ApiServer(state)
    api.start()
    base = f"http://{api.address[0]}:{api.address[1]}"
    try:
        assert _http(base + "/api/goals")[0] == 401
        code, p1 = _http(base + "/api/goals?limit=2", bearer="tok-cam")
        assert code == 200 and len(p1["data"]["items"]) == 2 and p1["data"]["total"] == 5 and p1["data"]["items"][0]["status"] == "received"
        cur = p1["data"]["next_cursor"]
        assert cur and "cam" not in cur and "offset" not in cur  # opaque
        code, p2 = _http(base + f"/api/goals?limit=2&cursor={cur}", bearer="tok-cam")
        assert code == 200 and [g["goal_id"] for g in p2["data"]["items"]] != [g["goal_id"] for g in p1["data"]["items"]]
        code, p3 = _http(base + f"/api/goals?limit=2&cursor={p2['data']['next_cursor']}", bearer="tok-cam")
        assert code == 200 and len(p3["data"]["items"]) == 1 and p3["data"]["next_cursor"] is None
        assert _http(base + f"/api/goals?cursor={cur}", bearer="tok-oli")[0] == 403  # bound to scope
        assert _http(base + f"/api/goals?cursor={cur[:-3]}xyz", bearer="tok-cam")[0] == 400  # tampered
        assert _http(base + "/api/goals?limit=0", bearer="tok-cam")[0] == 400 and _http(base + "/api/goals?limit=many", bearer="tok-cam")[0] == 400
        code, oli = _http(base + "/api/goals", bearer="tok-oli")
        assert code == 200 and oli["data"]["total"] == 1
        assert _http(base + "/api/nope", bearer="tok-cam")[0] == 404
    finally:
        api.stop()
