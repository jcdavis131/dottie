"""Phase 6 acceptance: gap 02 (real feedback from every surface, §16) and the buildable part
of gap 06 (§17 expiry job, §33 restore drill) as CLI commands."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from dottie_loop import errors, feedback, surfaces
from dottie_loop.cli import EXIT_BLOCKED, EXIT_INVALID, EXIT_OK, main
from dottie_loop.intake import GoalStore


def _run(capsys, *argv):
    rc = main([str(a) for a in argv])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, json.loads(lines[-1])


def _captured_run(capsys, tmp_path, key="k1"):
    store = tmp_path / "store"
    (tmp_path / "hello.txt").write_text("hello")
    spec = tmp_path / f"spec-{key}.json"
    spec.write_text(json.dumps({"intent_text": f"check the hello file {key}", "idempotency_key": key, "capture": True, "steps": [{"id": "f", "kind": "file", "path": "hello.txt", "expect_substring": "hello"}]}))
    rc, env = _run(capsys, "loop", "run", "--spec", spec, "--store", store, "--root", tmp_path, "--subject", "cam", "--capture")
    assert rc == EXIT_OK and env["data"]["trace_id"]
    return store, env["data"]["run_id"], env["data"]["trace_id"]


def test_record_feedback_is_one_contract_for_every_surface(capsys, tmp_path):
    store, run_id, trace_id = _captured_run(capsys, tmp_path)
    with pytest.raises(errors.BlockedError):  # no captured traces: blocked, not invented
        feedback.record_feedback(tmp_path / "empty", run_id=run_id, signal="accept", surface="cli")
    for bad in ({"signal": "love_it"}, {"surface": "telepathy"}, {"edit_fraction": 1.5}, {"run_id": ""}):
        with pytest.raises(errors.InvalidInputError):
            feedback.record_feedback(store, **{"run_id": run_id, "signal": "edit", "surface": "cli", **bad})
    out = feedback.record_feedback(store, run_id=trace_id, signal="edit", surface="repl", edit_fraction=0.8, subject="h_cam")
    assert out["trace_id"] == trace_id and out["feedback"]["surface"] == "repl" and out["reward"]["components"]["accept"] == 0.25
    lines = (store / "traces" / "pair.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["supersedes_trace"] == trace_id and json.loads(lines[1])["feedback"][-1]["signal"] == "edit"  # append-only
    assert json.loads((store / "traces" / f"reward-{trace_id}.json").read_text())["evidence"][0] == "feedback:edit:repl"
    rc, env = _run(capsys, "feedback", "record", "--store", store, "--run-id", run_id, "--signal", "accept", "--subject", "h_cam")
    assert rc == EXIT_OK and env["data"]["feedback"]["surface"] == "cli" and env["data"]["feedback"]["subject"] == "h_cam"


def test_slack_reactions_and_replies_bind_to_the_run_thread():
    rep = surfaces.SlackReporter()
    m = rep.report(event_id="e1", channel_id="C1", run_id="run_1", state="completed", verdict="done", evidence=[])
    ts = m["thread_ts"]
    fb = rep.feedback_from_event({"type": "reaction_added", "event_id": "r1", "reaction": "white_check_mark", "item": {"ts": ts}, "user": "U1"})
    assert fb == {"run_id": "run_1", "signal": "accept", "surface": "slack", "event_id": "r1", "subject": "U1"}
    assert rep.feedback_from_event({"type": "reaction_added", "event_id": "r1", "reaction": "x", "item": {"ts": ts}}) is None  # replayed event id
    assert rep.feedback_from_event({"type": "reaction_added", "event_id": "r2", "reaction": "eyes", "item": {"ts": ts}}) is None  # not a signal
    assert rep.feedback_from_event({"type": "reaction_added", "event_id": "r3", "reaction": "x", "item": {"ts": "ts_other"}}) is None  # not a run thread
    assert rep.feedback_from_event({"type": "message", "event_id": "m1", "thread_ts": ts, "text": "Reject: wrong file"})["signal"] == "reject"
    assert rep.feedback_from_event({"type": "message", "event_id": "m2", "thread_ts": ts, "text": "please reject this"}) is None  # conversation, not a signal
    assert rep.feedback_from_event({"type": "app_mention", "event_id": "m3", "text": "accept"}) is None
    assert rep.feedback_from_event({"type": "message", "text": "accept"}) is None  # no event id, no dedupe, no bind
    assert feedback.signal_from_text("  APPLY!  ") == "apply" and feedback.signal_from_text("") is None


def _http(url, *, method="GET", bearer=None, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)  # noqa: S310 - loopback test server
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback test server
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_feedback_needs_a_principal_and_a_captured_run(capsys, tmp_path):
    store, run_id, _ = _captured_run(capsys, tmp_path)
    state = surfaces.ApiState(GoalStore(tmp_path / "goals"), principals={"tok-cam": "cam"}, run_store=store)
    api = surfaces.ApiServer(state)
    api.start()
    base = f"http://{api.address[0]}:{api.address[1]}"
    try:
        assert _http(base + "/api/feedback", method="POST", body={"run_id": run_id, "signal": "accept"})[0] == 401
        code, env = _http(base + "/api/feedback", method="POST", bearer="tok-cam", body={"run_id": run_id, "signal": "accept"})
        assert code == 201 and env["data"]["feedback"]["surface"] == "api" and env["data"]["feedback"]["subject"] == "cam"
        code, env = _http(base + "/api/feedback", method="POST", bearer="tok-cam", body={"run_id": run_id, "signal": "edit", "edit_fraction": "lots"})
        assert code == 400 and env["error"]["field"] == "edit_fraction"
        assert _http(base + "/api/feedback", method="POST", bearer="tok-cam", body={"run_id": "run_nope", "signal": "accept"})[0] == 400
        state.run_store = None
        code, env = _http(base + "/api/feedback", method="POST", bearer="tok-cam", body={"run_id": run_id, "signal": "accept"})
        assert code == 503 and env["error"]["code"] == "blocked"
    finally:
        api.stop()


def test_retention_expire_and_incident_drill_commands(capsys, tmp_path):
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat().replace("+00:00", "Z")
    fresh = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records = [
        {"record_id": "a", "data_class": "raw_capture", "created_at": old},
        {"record_id": "b", "data_class": "raw_capture", "created_at": fresh, "deletion_key": "del-b"},
        {"record_id": "c", "data_class": "raw_capture", "created_at": old, "deletion_key": "hold-c"},
        {"record_id": "d", "data_class": "approval_release_evidence", "created_at": old},
    ]
    src = tmp_path / "records.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in records))
    holds = tmp_path / "holds.json"
    holds.write_text(json.dumps(["hold-c"]))
    dels = tmp_path / "dels.json"
    dels.write_text(json.dumps(["del-b"]))
    rc, env = _run(capsys, "retention", "expire", "--records", src, "--holds", holds, "--deletions", dels, "--out", tmp_path / "out.jsonl")
    r = env["data"]["receipt"]
    assert rc == EXIT_OK and r["tombstoned"] == ["a", "b"] and r["expedited_by_deletion_request"] == ["b"] and r["held"] == ["c"] and r["kept"] == ["d"]
    assert (tmp_path / "out.jsonl.receipt.json").exists() and json.loads(src.read_text().splitlines()[0]).get("tombstoned") is None  # source untouched with --out
    rc, env2 = _run(capsys, "retention", "expire", "--records", tmp_path / "out.jsonl", "--holds", holds)  # idempotent, in place
    assert rc == EXIT_OK and env2["data"]["receipt"]["tombstoned"] == [] and env2["data"]["receipt"]["held"] == ["c"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"record_id": "z", "data_class": "mystery", "created_at": old}) + "\n")
    assert _run(capsys, "retention", "expire", "--records", bad)[0] == EXIT_INVALID

    results = tmp_path / "drill.json"
    results.write_text(json.dumps({"repository_checkout": True, "state_store_integrity": True, "checkpoint_hashes": True, "dataset_manifest_resolution": True, "model_loading": True}))
    rc, env = _run(capsys, "incident", "drill", "--results", results, "--out", tmp_path / "drill-out.json")
    assert rc == EXIT_BLOCKED and env["error"]["details"]["verdict"]["failed"] == ["rollback_deployment"]
    results.write_text(json.dumps({"repository_checkout": True, "state_store_integrity": True, "checkpoint_hashes": True, "dataset_manifest_resolution": True, "model_loading": True, "rollback_deployment": True}))
    rc, env = _run(capsys, "incident", "drill", "--results", results)
    assert rc == EXIT_OK and env["data"]["ok"] and env["data"]["recovery_order"]
    results.write_text("[]")
    assert _run(capsys, "incident", "drill", "--results", results)[0] == EXIT_INVALID
