"""Phase 5 acceptance: RLM/REPL (§10), session recorder (§16), calibration (§24),
fail-closed API surface (§28, RT-17) and the §39 traceability graph."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from dottie_loop import capture, errors, evaluation, rlm, surfaces, traceability
from dottie_loop.cli import EXIT_BLOCKED, EXIT_OK, main
from dottie_loop.hashing import digest
from dottie_loop.intake import GoalStore

# --- §10 RLM execution --------------------------------------------------------------------


def test_rlm_child_calls_are_bounded_and_logged(tmp_path):
    log = tmp_path / "mission.jsonl"
    s = rlm.RLMSession("m1", log, rlm.Budget(tokens=100, child_calls=2, depth=1, wall_seconds=10))
    s.set_var("corpus", "a" * 5000, source="upload:doc.txt")
    with pytest.raises(errors.InvalidInputError):
        s.set_var("not an identifier", 1, source="x")
    with pytest.raises(errors.InvalidInputError):
        s.rlm("q", lambda c, q: {"ok": True}, tokens=10, inputs=["missing"])

    def worker(child: rlm.RLMSession, query: str) -> dict:
        assert child.depth == 1 and "corpus" in child.variables
        with pytest.raises(errors.PolicyDeniedError):  # depth budget: a grandchild is refused
            child.rlm("deeper", lambda c, q: {"ok": True}, tokens=1)
        return {"ok": True, "tokens_used": 30, "confidence": 0.9}

    out = s.rlm("summarize corpus", worker, tokens=40, inputs=["corpus"])
    assert out["ok"] and out["call_id"].startswith("rlm_") and "stuck" not in out
    assert s.visible_budget()["tokens"]["used"] == 30 and s.visible_budget()["child_calls"]["used"] == 1
    with pytest.raises(errors.PolicyDeniedError):  # token budget would be exceeded
        s.rlm("big", worker, tokens=80)
    s.rlm("second", lambda c, q: {"ok": True, "tokens_used": 5}, tokens=10)
    with pytest.raises(errors.PolicyDeniedError):  # child-call budget exhausted
        s.rlm("third", lambda c, q: {"ok": True}, tokens=1)
    kinds = [json.loads(ln)["kind"] for ln in log.read_text().splitlines()]
    assert kinds == ["set_var", "rlm_call", "rlm_result", "rlm_call", "rlm_result"]  # no unlogged subagents
    assert "a" * 100 not in log.read_text()  # variable VALUES never leak into the log, only digests


def test_stuck_detector_allows_exactly_one_lateral_lens(tmp_path):
    s = rlm.RLMSession("m2", tmp_path / "log.jsonl", rlm.Budget(tokens=1000, child_calls=10, depth=2, wall_seconds=10))
    failing = lambda c, q: {"ok": False, "error": "no"}  # noqa: E731
    assert "stuck" not in s.rlm("try", failing, tokens=1)
    assert s.rlm("try again", failing, tokens=1)["stuck"] == "repeated_failure"
    lens = s.lateral_lens("smallest_reproducer")
    assert lens == "smallest_reproducer"
    with pytest.raises(errors.LoopError) as ei:  # a second lens is escalation, not agent spam
        s.lateral_lens()
    assert ei.value.code == "stuck"
    with pytest.raises(errors.InvalidInputError):
        rlm.StuckDetector().lens("brainstorm_harder")
    d = rlm.StuckDetector()
    assert d.observe("Same Q", failed=False, confidence=None) is None
    assert d.observe("same q", failed=False, confidence=None) is None
    assert d.observe(" same q ", failed=False, confidence=None) == "repeated_query"
    d2 = rlm.StuckDetector()
    d2.observe("a", failed=False, confidence=0.1)
    assert d2.observe("b", failed=False, confidence=0.2) == "low_confidence"


def test_mission_resumes_from_its_log(tmp_path):
    log = tmp_path / "log.jsonl"
    budget = rlm.Budget(tokens=100, child_calls=3, depth=1, wall_seconds=10)
    s = rlm.RLMSession("m3", log, budget)
    s.set_var("doc", {"pages": 3}, source="upload")
    s.rlm("q", lambda c, q: {"ok": True, "tokens_used": 12}, tokens=20)
    s.lateral_lens()
    r = rlm.RLMSession.resume("m3", log, budget)
    assert r.child_calls == 1 and r.tokens_used == 12 and r.stuck.lens_used == "invert_the_question"
    assert r.variables["doc"] == {"__rehydrate__": digest({"pages": 3}), "source": "upload"}  # provenance, re-hydrated by the caller
    assert json.loads(log.read_text().splitlines()[-1])["kind"] == "resume"
    assert rlm.RLMSession.resume("never", tmp_path / "none.jsonl", budget).child_calls == 0


# --- §16 session recorder -----------------------------------------------------------------


def test_session_recorder_finalizes_only_through_capture_writer(tmp_path):
    w = capture.CaptureWriter(tmp_path / "traces.jsonl", enabled=True, salt="s")
    rec = capture.SessionRecorder(session_id="sess-1", hashed_user_id=w.hash_identity("cam@example.com"), surface="cli", agent_id="dottie", goal={"intent_text": "fix the bug"}, consent_version="consent-1", deletion_key="del-1")
    with pytest.raises(errors.InvalidInputError):
        capture.SessionRecorder(session_id="s", hashed_user_id="h", surface="telepathy", agent_id="a", goal={}, consent_version="c", deletion_key="d")
    t1 = rec.turn("user", "my token is sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 please fix")
    rec.tool_call("grep", args_digest="d1", observation_digest="d2", ok=True, latency_ms=3)
    t2 = rec.turn("agent", "patched")
    rec.correction("no, the other file")
    rec.feedback("reject", turn=t2)
    rec.feedback("edit", magnitude=0.5)
    with pytest.raises(errors.InvalidInputError):
        rec.feedback("accept", turn=99)
    with pytest.raises(errors.InvalidInputError):
        rec.feedback("love_it")
    rec.checkpoint({"nodeId": "n1", "agentId": "dottie", "attempt": 1, "latency_ms": 5, "tokens_est": 10, "status": "completed", "errorClass": None, "extra": "ignored"})
    assert not (tmp_path / "traces.jsonl").exists()  # nothing persisted before finalize
    out = rec.finalize(w, outcome={"status": "success"}, resources={"tokens": 10})
    assert out is not None and out["feedback"][0]["turn"] == t2 and out["feedback"][1]["turn"] == t2 and t1 == 1
    stored = json.loads((tmp_path / "traces.jsonl").read_text())
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in json.dumps(stored) and "@" not in stored["hashed_user_id"]
    assert stored["checkpoints"][0] == {"nodeId": "n1", "agentId": "dottie", "attempt": 1, "latency_ms": 5, "tokens_est": 10, "status": "completed", "errorClass": None}
    assert stored["lineage"]["deletion_key"] == "del-1" and len(stored["tool_calls"]) == 1 and len(stored["observations"]) == 1
    off = capture.CaptureWriter(tmp_path / "never.jsonl", enabled=False, salt="s")
    assert rec.finalize(off, outcome={}, resources={}) is None and not (tmp_path / "never.jsonl").exists()


# --- §24 calibration ----------------------------------------------------------------------


def test_calibration_is_measured_from_records_or_reported_unmeasured():
    assert evaluation.calibration([]) == {"ece": None, "n": 0, "abstentions": 0, "status": "unmeasured"}
    perfect = evaluation.calibration([(1.0, True)] * 5 + [(0.0, False)] * 5, abstentions=10)
    assert perfect["ece"] == 0.0 and perfect["n"] == 10 and perfect["abstention_rate"] == 0.5 and perfect["status"] == "measured"
    over = evaluation.calibration([(0.95, False)] * 4, wrong_when_confident=4)
    assert over["ece"] == 0.95 and over["bins"] == [{"bin": 9, "n": 4, "confidence": 0.95, "accuracy": 0.0}] and over["wrong_when_confident"] == 4
    with pytest.raises(errors.InvalidInputError):
        evaluation.calibration([(1.5, True)])


# --- §28 fail-closed API ------------------------------------------------------------------


def _http(url, *, method="GET", bearer=None, headers=None, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, method=method, data=data)  # noqa: S310 - loopback test server
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback test server
            return resp.status, json.loads(resp.read()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), dict(e.headers)


def test_api_surface_fails_closed(tmp_path):
    goals = GoalStore(tmp_path / "goals")
    state = surfaces.ApiState(goals, principals={"tok-cam": "cam"}, quarantine_path=tmp_path / "q" / "routing.jsonl")
    api = surfaces.ApiServer(state)
    api.start()
    base = f"http://{api.address[0]}:{api.address[1]}"
    try:
        code, health, hdrs = _http(base + "/api/health")
        assert code == 200 and health["data"]["learned_loaded"] is False and hdrs["Cache-Control"] == "no-store"
        assert _http(base + "/api/nope")[0] == 404
        goal = {"intent_text": "summarize the report"}
        assert _http(base + "/api/goal", method="POST", body=goal)[0] == 401  # no bearer
        code, env, _ = _http(base + "/api/goal", method="POST", bearer="tok-cam", body=goal)
        assert code == 400 and env["error"]["field"] == "idempotency_key"  # missing Idempotency-Key
        code, first, _ = _http(base + "/api/goal", method="POST", bearer="tok-cam", headers={"Idempotency-Key": "k1"}, body=goal)
        assert code == 202 and first["status"] == "accepted" and first["data"]["status"] == "received"
        code, again, _ = _http(base + "/api/goal", method="POST", bearer="tok-cam", headers={"Idempotency-Key": "k1"}, body=goal)
        assert code == 200 and again["status"] == "replayed" and again["data"]["goal_id"] == first["data"]["goal_id"]
        code, conflict, _ = _http(base + "/api/goal", method="POST", bearer="tok-cam", headers={"Idempotency-Key": "k1"}, body={"intent_text": "something else"})
        assert code == 409 and conflict["error"]["code"] == "idempotency_conflict"
        assert _http(base + "/api/goal", method="POST", bearer="tok-cam", headers={"Idempotency-Key": "k2"}, raw=b"not json")[0] == 400
        # learned output is null (503) until weights are loaded; heuristic route still answers
        code, env, _ = _http(base + "/api/learned", method="POST", bearer="tok-cam", body={})
        assert code == 503 and env["error"]["code"] == "backend_unavailable"
        code, routed, _ = _http(base + "/api/route", method="POST", bearer="tok-cam", body={"goal": "list files", "side_effect_class": "read_only"})
        assert code == 200 and routed["data"]["tier"]
        # a bad routing input is a typed rejection AND a quarantine + alert, never acceptance
        code, env, _ = _http(base + "/api/route", method="POST", bearer="tok-cam", body={"goal": ""})
        assert code == 400 and env["error"]["field"] == "goal"
        code, env, _ = _http(base + "/api/route", method="POST", bearer="tok-cam", body={"goal": "x", "gender": "f"})
        assert code == 403 and env["error"]["code"] == "policy_denied"
        q = [json.loads(ln) for ln in (tmp_path / "q" / "routing.jsonl").read_text().splitlines()]
        assert [e["code"] for e in q] == ["invalid_input", "policy_denied"] and q[1]["value_class"] == "NoneType" and "\"f\"" not in json.dumps(q)
        assert [a["kind"] for a in state.alerts] == ["routing_rejected", "routing_rejected"]
        state.learned_artifact = {"id": "router-v1", "sha256": "0" * 64}
        assert _http(base + "/api/learned", method="POST", bearer="tok-cam", body={})[0] == 200
    finally:
        api.stop()


# --- §39 traceability graph ---------------------------------------------------------------


def _chain_records(tmp_path, *, with_rollback: bool = True, approver: str | None = "cam"):
    d = tmp_path / "chain"
    d.mkdir()
    files = {
        "session.json": {"session_id": "sess-1"},
        "trace.json": {"trace_id": "trc_1", "session_id": "sess-1"},
        "reward.json": {"trace_id": "trc_1", "reward": 1.0},
        "qa_report.json": {"id": "qa_1", "trace_id": "trc_1"},
        "manifest.json": {"dataset_id": "ds_1", "approved_by": approver},
        "train.json": {"run_id": "run_1", "dataset_id": "ds_1"},
        "checkpoint.json": {"checkpoint": "ckpt_1", "run_id": "run_1"},
        "bundle.json": {"bundle_id": "eval_1"},
        "canary.json": {"id": "canary_1", "approver": {"subject_id": approver} if approver else None},
        "approval.json": {"approval_id": "apr_1", "approver": approver},
        "release.json": {"release_id": "rel_1", "approved_by": approver},
        "served.json": {"id": "served_1", "pass": True},
        "monitoring.json": {"id": "mon_1"},
    }
    if with_rollback:
        files["rollback.json"] = {"id": "rel_0", "approved_by": approver}
    for name, rec in files.items():
        (d / name).write_text(json.dumps(rec), encoding="utf-8")
    return d


def test_traceability_graph_resolves_every_arrow(tmp_path, capsys):
    d = _chain_records(tmp_path)
    graph = traceability.from_directory(d)
    assert set(graph["nodes"]) == set(traceability.NODE_TYPES) and len(graph["edges"]) == len(traceability.EDGES)
    assert graph["nodes"]["dataset"]["id"] == "ds_1" and graph["nodes"]["canary"]["authority"] == "cam"
    v = traceability.validate_graph(graph)
    assert v["complete"] and v["unresolved_edges"] == [] and v["edges_missing_human_authority"] == []
    rc = main(["spec", "traceability", "--dir", str(d), "--out", str(tmp_path / "graph.json")])
    env = json.loads(capsys.readouterr().out.strip())
    assert rc == EXIT_OK and env["data"]["verdict"]["complete"] and (tmp_path / "graph.json").exists()

    # a missing rollback drill leaves one arrow unresolved unless the operator waives it
    (d / "rollback.json").unlink()
    v = traceability.validate_graph(traceability.from_directory(d))
    assert not v["complete"] and v["unresolved_edges"] == ["rolled_back_to"]
    assert traceability.validate_graph(traceability.from_directory(d), require_rollback=False)["complete"]
    rc = main(["spec", "traceability", "--dir", str(d)])
    env = json.loads(capsys.readouterr().out.strip())
    assert rc == EXIT_BLOCKED and env["status"] == "blocked" and "rolled_back_to" in env["error"]["message"]
    assert main(["spec", "traceability", "--dir", str(d), "--no-rollback"]) == EXIT_OK
    capsys.readouterr()

    # a consequential edge with no named human authority is not complete
    (tmp_path / "noauth").mkdir()
    d2 = _chain_records(tmp_path / "noauth", approver=None)
    v = traceability.validate_graph(traceability.from_directory(d2))
    assert not v["complete"] and set(v["edges_missing_human_authority"]) == {"released_in", "canaried_by", "approved_by", "released_as", "rolled_back_to"}
    # an empty directory resolves nothing
    v = traceability.validate_graph(traceability.from_directory(tmp_path / "empty"))
    assert len(v["unresolved_edges"]) == len(traceability.EDGES)


def test_spec_schemas_lists_one_active_version_per_record_type(capsys):
    rc = main(["spec", "schemas"])
    env = json.loads(capsys.readouterr().out.strip())
    assert rc == EXIT_OK and env["data"]["active"]["pair-session"] == "pair-session-1.0.0" and "release-record" in env["data"]["active"]
