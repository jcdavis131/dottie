"""Phase 2 acceptance: tool plane (§12), end-to-end driver (§10/§36), surfaces (§06,
RT-16), memory (§15, RT-11), civilization (§30), observability (§32), incidents (§33),
retention (§17), and the Forge runner script (§27) against a real local git conveyor.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dottie_loop import (
    civilization,
    errors,
    incidents,
    memory,
    observability,
    retention,
    surfaces,
    tools,
)
from dottie_loop.approvals import ApprovalStore
from dottie_loop.driver import RunSpec, run_goal
from dottie_loop.intake import GoalStore

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- §12 tool plane ------------------------------------------------------------------------

MANIFEST = {"name": "example", "version": "1.2.0", "commands": ["search", "get", "send"], "capabilities": {"network": {"domains": ["official.example"], "methods": ["GET"]}, "filesystem": {"paths": ["workspace/example"], "mode": "read_write"}, "secrets": ["custom.example"]}, "side_effects": {"search": "none", "get": "none", "send": "external_send"}, "timeouts": {"default_seconds": 30}, "output_schema": "scout-result-1.0.0"}


def _envelope(**over):
    base = {"ok": True, "schema": "scout-result-1.0.0", "plugin": "example", "version": "1.2.0", "command": "search", "request_id": "x", "data": {}, "warnings": [], "metrics": {"latency_ms": 81}, "provenance": {"source": "provider", "retrieved_at": "2026-09-11T00:00:00Z"}}
    base.update(over)
    return base


def test_tool_plane_policy_invariants(tmp_path):
    (tmp_path / "workspace" / "example").mkdir(parents=True)
    broker = tools.SecretBroker({"custom.example": "SENTINEL-VALUE-XYZ"})
    plane = tools.ScoutToolPlane([MANIFEST], root=tmp_path, broker=broker)
    with pytest.raises(errors.PolicyDeniedError):
        plane.resolve("unknown", "search")  # unknown plugin denied
    with pytest.raises(errors.PolicyDeniedError):
        plane.resolve("example", "delete")  # unknown command denied
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", paths=["../outside"]))
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", paths=["workspace/other/x"]))
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", urls=["https://evil.example/"]))
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", urls=["https://official.example/"], method="POST"))
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", args=["--token", "SENTINEL-VALUE-XYZ"]))  # secret value in argv
    with pytest.raises(errors.PolicyDeniedError):
        plane.authorize(plane.resolve("example", "get"), tools.ToolCall("example", "get", secrets=["other.secret"]))  # undeclared secret
    auth = plane.authorize(plane.resolve("example", "send"), tools.ToolCall("example", "send"))
    assert auth["requires_approval"]
    with pytest.raises(errors.PolicyDeniedError):
        plane.call(tools.ToolCall("example", "send"), runner=lambda *_: {"stdout": json.dumps(_envelope(command="send")), "latency_ms": 1})
    dry = plane.call(tools.ToolCall("example", "send", dry_run=True))
    assert dry["data"]["dry_run"] and dry["provenance"]["source"] == "dry_run"  # dry-run performs no effect
    env = plane.call(tools.ToolCall("example", "search", args=["q"]), runner=lambda *_: {"stdout": json.dumps(_envelope(data={"hits": 1, "echo": "SENTINEL-VALUE-XYZ"})), "latency_ms": 5})
    assert env["data"]["echo"] == "[SECRET]"  # audit/envelope strip secret substrings
    with pytest.raises(errors.InvalidInputError):
        plane.call(tools.ToolCall("example", "search"), runner=lambda *_: {"stdout": "Searching...\n" + json.dumps(_envelope()), "latency_ms": 5})  # prose mixed into stdout
    with pytest.raises(errors.PolicyDeniedError):
        plane.call(tools.ToolCall("example", "search"), runner=lambda *_: {"stdout": json.dumps(_envelope(plugin="other")), "latency_ms": 5})  # cannot broaden itself

    def rate_limited(*_):
        raise errors.RateLimitedError()

    with pytest.raises(errors.RateLimitedError):
        plane.call(tools.ToolCall("example", "search"), runner=rate_limited)
    with pytest.raises(errors.RateLimitedError):
        plane.call(tools.ToolCall("example", "get"), runner=lambda *_: {"stdout": "{}", "latency_ms": 1})  # provider scope ended
    assert [a.denied_reason for a in plane.audit if a.denied_reason] == ["malformed_envelope", "rate_limited"]
    assert all("SENTINEL" not in a.args_digest for a in plane.audit)


def test_manifest_and_envelope_validation():
    with pytest.raises(errors.InvalidInputError):
        tools.validate_manifest({**MANIFEST, "side_effects": {"search": "none"}})
    with pytest.raises(errors.InvalidInputError):
        tools.validate_manifest({**MANIFEST, "output_schema": "scout-result-2.0.0"})
    with pytest.raises(errors.InvalidInputError):
        tools.validate_manifest({**MANIFEST, "capabilities": {**MANIFEST["capabilities"], "secrets": ["sk-VALUELIKE"]}})
    with pytest.raises(errors.InvalidInputError):
        tools.validate_result_envelope(_envelope(metrics={}))
    assert tools.validate_result_envelope(_envelope())["ok"]


# --- §10/§36 end-to-end driver ----------------------------------------------------------------


def _spec(**over):
    base = {"intent_text": "verify the sandbox file and echo", "steps": [{"id": "echo", "kind": "argv", "argv": [sys.executable, "-c", "print('ok-echo')"], "expect_substring": "ok-echo"}, {"id": "file", "kind": "file", "path": "hello.txt", "expect_substring": "hello"}]}
    base.update(over)
    return RunSpec.from_dict(base)


def test_driver_completes_verifies_checkpoints_and_captures_only_with_consent(tmp_path):
    (tmp_path / "hello.txt").write_text("hello world")
    r = run_goal(_spec(), store_root=tmp_path / "store", root=tmp_path, subject="cam")
    assert r["status"] == "completed" and len(r["checkpoints"]) == 2 and r["trace_id"] is None  # RT-12 default off
    goals = GoalStore(tmp_path / "store" / "goals")
    assert [t["to"] for t in goals.transitions(r["goal_id"])] == ["received", "validated", "planned", "running", "verified", "completed"]
    assert all(e["status"] == "completed" for e in json.loads((tmp_path / "store" / "runs" / r["run_id"] / "result.json").read_text())["timeline"]["nodes"].values())
    replay = run_goal(_spec(idempotency_key=r["goal_id"] and "same"), store_root=tmp_path / "store", root=tmp_path, subject="cam")
    replay2 = run_goal(_spec(idempotency_key="same"), store_root=tmp_path / "store", root=tmp_path, subject="cam")
    assert replay["status"] == "completed" and replay2["replay"] is True  # RT-02 through the driver
    # consent asserted but switch off -> no trace; both -> redacted trace + reward
    r2 = run_goal(_spec(idempotency_key="c1", capture=True), store_root=tmp_path / "store", root=tmp_path, subject="cam", capture_flag=False, env={})
    assert r2["trace_id"] is None
    r3 = run_goal(_spec(idempotency_key="c2", capture=True), store_root=tmp_path / "store", root=tmp_path, subject="cam@example.com", capture_flag=True)
    assert r3["trace_id"] and r3["reward"]["components"]["task_ok"] == 1.0
    disk = (tmp_path / "store" / "traces" / "pair.jsonl").read_text()
    assert "cam@example.com" not in disk and r3["trace_id"] in disk


def test_driver_failure_blocked_and_rejected_paths(tmp_path):
    bad = _spec(idempotency_key="f1", steps=[{"id": "x", "kind": "argv", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}])
    r = run_goal(bad, store_root=tmp_path / "store", root=tmp_path, subject="cam")
    assert r["status"] == "failed" and r["outcome"]["error_class"] == "verification_failed" and r["outcome"]["failed_step"] == "x"
    effect = _spec(idempotency_key="e1", intent_text="email the report to the team")
    r2 = run_goal(effect, store_root=tmp_path / "store", root=tmp_path, subject="cam")
    assert r2["status"] == "blocked" and r2["dependency"] == "approval"
    with pytest.raises(errors.LoopError):
        RunSpec.from_dict({"intent_text": "x", "steps": []})
    escape = _spec(idempotency_key="p1", steps=[{"id": "f", "kind": "file", "path": "../../etc/passwd"}])
    r3 = run_goal(escape, store_root=tmp_path / "store", root=tmp_path, subject="cam")
    assert r3["status"] == "blocked" and r3["outcome"]["error_class"] == "policy_denied"


# --- RT-16 Slack reports deduped and concise; §06 approval board -------------------------------------


def test_rt16_slack_reports_are_deduped_threaded_and_capped():
    rep = surfaces.SlackReporter(line_limit=4)
    assert rep.acknowledge("evt1", "C1", "g1")["text"] == "received goal g1"
    assert rep.acknowledge("evt1", "C1", "g1") is None  # replay
    m = rep.report(event_id="e2", channel_id="C1", run_id="r1", state="planned", verdict="plan v1", evidence=["a", "b", "c"], blocker=None, next_decision="approve send")
    assert m["lines"] == 4 and m["text"].endswith("lines in the run log)")
    assert rep.report(event_id="e3", channel_id="C1", run_id="r1", state="planned", verdict="again", evidence=[]) is None  # no state change
    assert rep.report(event_id="e4", channel_id="C1", run_id="r1", state="running", verdict="tick", evidence=[]) is None  # heartbeat noise
    m2 = rep.report(event_id="e5", channel_id="C1", run_id="r1", state="completed", verdict="done", evidence=["ckpt"])
    assert m2["thread_ts"] == m["thread_ts"] and len(rep.posted) == 3
    assert surfaces.SlackReporter.is_authorization("@dottie please deploy now") is False


def _http(url, *, method="GET", bearer=None, csrf=None, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)  # noqa: S310 - loopback test server
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    if csrf:
        req.add_header("X-CSRF-Token", csrf)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback test server
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_approval_board_is_server_authoritative(tmp_path):
    goals = GoalStore(tmp_path)
    gid = goals.submit({"idempotency_key": "k", "intent_text": "send the report"}, authenticated_subject="cam", surface="web")[0]["goal_id"]
    state = surfaces.BoardState(goals, ApprovalStore(), approvers={"tok-cam": "cam"})
    board = surfaces.ApprovalBoard(state)
    board.start()
    base = f"http://{board.address[0]}:{board.address[1]}"
    try:
        assert _http(base + "/api/state")[0] == 401
        code, st = _http(base + "/api/state", bearer="tok-cam")
        assert code == 200 and st["data"]["goals"][0]["goal_id"] == gid and st["data"]["decisions"] == []
        body = {"action_type": "send", "payload": {"text": "hi"}, "destination": "slack:#ops", "goal_id": gid}
        assert _http(base + "/api/approve", method="POST", bearer="tok-cam", body=body)[0] == 403  # no CSRF
        csrf = _http(base + "/api/csrf", bearer="tok-cam")[1]["data"]["csrf"]
        code, dec = _http(base + "/api/approve", method="POST", bearer="tok-cam", csrf=csrf, body=body)
        assert code == 201 and dec["data"]["kind"] == "approve" and dec["data"]["approval_id"].startswith("apr_")
        assert _http(base + "/api/approve", method="POST", bearer="tok-cam", csrf=csrf, body={**body, "goal_id": "nope"})[0] == 400
        code, _den = _http(base + "/api/deny", method="POST", bearer="tok-cam", csrf=csrf, body={"goal_id": gid, "reason": "not now"})
        assert code == 201 and [d["kind"] for d in state.snapshot()["decisions"]] == ["approve", "deny"]  # append-only history
        # the token issued through the board is a real one-time approval
        state.approvals.verify_and_consume(dec["data"]["approval_id"], action_type="send", payload={"text": "hi"}, destination="slack:#ops", goal_id=gid)
        with pytest.raises(errors.ApprovalRequiredError):
            state.approvals.verify_and_consume(dec["data"]["approval_id"], action_type="send", payload={"text": "hi"}, destination="slack:#ops", goal_id=gid)
    finally:
        board.stop()


# --- RT-11 memory writes are evidence-backed -------------------------------------------------------


def test_rt11_memory_provenance_confidence_contradiction(tmp_path):
    m = memory.MemoryStore(tmp_path / "mem")
    with pytest.raises(errors.InvalidInputError):
        m.remember("editor", "vim", evidence=[], provenance="user_stated", confidence=0.9)
    with pytest.raises(errors.InvalidInputError):
        m.remember("editor", "vim", evidence=["e1"], provenance="gossip", confidence=0.9)
    with pytest.raises(errors.PolicyDeniedError):
        m.remember("ssn", "123", evidence=["e"], provenance="document", confidence=1.0, sensitivity="P3")
    hint = m.remember("timezone", "UTC-5", evidence=["inferred from commit times"], provenance="inferred", confidence=0.3)
    assert hint.hint and not m.actionable(hint)
    a = m.remember("editor", "vim", evidence=["session 1"], provenance="user_stated", confidence=0.9)
    b = m.remember("editor", "emacs", evidence=["doc 7"], provenance="document", confidence=0.6)
    rec = m.recall("which editor")
    assert rec["resolution_required"] == ["editor"] and all(r["conflict"] for r in rec["results"] if r["key"] == "editor")
    assert rec["results"][0]["fact_id"] == a.fact_id  # user_stated authority outranks document
    assert all(r["evidence"] for r in rec["results"])
    fixed = m.correct(b.fact_id, "vim", evidence=["user said so"])
    assert m.facts[b.fact_id].superseded_by == fixed.fact_id and m.recall("editor")["resolution_required"] == []
    assert any(e.rel == "supersedes" for e in m.neighbors(fixed.fact_id, graph="history"))
    assert m.recall(a.fact_id)["results"][0]["fact_id"] == a.fact_id  # exact id first
    assert m.recall("editor", sensitivity_max="P0")["results"] == []
    assert (tmp_path / "mem" / "episodic.jsonl").read_text().count("\n") >= 4
    assert m.resolve_person("Sam", [{"id": "p1", "name": "Sam"}, {"id": "p2", "name": "Sam"}]) == {"resolved": None, "ask": True, "candidates": ["p1", "p2"]}
    m.confirm_person("Sam", "p2")
    assert m.resolve_person("sam", [])["resolved"] == "p2"


# --- §30 civilization --------------------------------------------------------------------------------


def test_civilization_machines_specialists_and_ladder():
    values = iter([0.95, 0.80, 0.80, 0.95, 0.70])
    mach = civilization.Machine("ok-rate", check=lambda: next(values), threshold=0.90, comparator="lt", specialist="reliability")
    assert mach.tick() is None
    wake = mach.tick()
    assert wake["wake"] == "reliability" and wake["tokens"] == 0
    assert mach.tick() is None  # same breach: deduped
    assert mach.tick() is None  # recovered: silent
    assert mach.tick()["incident_key"] == wake["incident_key"] and mach.wakeups == 2 and mach.avoided_wakeups == 3
    brief = civilization.WorkerBrief(objective="fix flaky test", scope=["tests/test_x.py"], excerpts=["..."], constraints=["no new deps"], allowed_actions=["edit", "run_tests"], success_tests=["pytest tests/test_x.py"], evidence_path="evidence/x.md")
    brief.validate()
    with pytest.raises(errors.PolicyDeniedError):
        civilization.WorkerBrief(objective="x", scope=["a"], excerpts=[], constraints=[], allowed_actions=["spawn"], success_tests=["t"], evidence_path="e").validate()
    good = civilization.validate_report("VERDICT: fixed\nevidence: evidence/x.md\n", brief)
    assert good["ok"]
    bad = civilization.validate_report("\n".join(["line"] * 12) + "\nALSO DID: refactored module", brief)
    assert not bad["ok"] and len(bad["problems"]) == 3
    assert civilization.decide(repeated_check=True, clear_threshold=True, single_step=False, reversible=False, fits_context=False, multi_step_self_contained=False)["choice"] == "machine"
    assert civilization.decide(repeated_check=False, clear_threshold=False, single_step=True, reversible=True, fits_context=True, multi_step_self_contained=False)["choice"] == "self"
    assert civilization.decide(repeated_check=False, clear_threshold=False, single_step=False, reversible=False, fits_context=False, multi_step_self_contained=True, tiny_jobs=5)["choice"] == "self"
    assert civilization.decide(repeated_check=False, clear_threshold=False, single_step=False, reversible=False, fits_context=False, multi_step_self_contained=True)["choice"] == "spawn_one"
    assert civilization.can_promote("T1", "T2") is False and civilization.can_promote("T2", "T0") is True
    ledger = civilization.TokenLedger()
    ledger.add("coordinator_in", 1200)
    ledger.add("specialist_context", 300)
    ledger.record_machine(mach)
    assert ledger.summary()["total"] == 1500 and ledger.summary()["avoided_wakeups"] == 3
    assert civilization.automation_cost_statement("ok-rate poller", 5000, 0)["justified"]


# --- §32 observability, §33 incidents, §17 retention ----------------------------------------------------


def test_observability_no_orphan_metrics_and_alert_dedupe():
    ev = {"goal_id": "g", "run_id": "r", "plan_version": 1, "node_id": "n", "attempt": 1, "request_id": "q", "actor": "svc", "at": _iso(NOW), "signal": "latency"}
    assert observability.correlate(ev) is ev
    with pytest.raises(errors.InvalidInputError):
        observability.correlate({k: v for k, v in ev.items() if k != "run_id"})
    with pytest.raises(errors.InvalidInputError):
        observability.metric_record(name="ok_rate", value=0.9, raw_source="", aggregation_version="v1", window="7d", denominator=100, freshness_at=_iso(NOW), owner="cam", decision="retrain-trigger")
    with pytest.raises(errors.InvalidInputError):
        observability.metric_record(name="ok_rate", value=0.9, raw_source="timeline.jsonl", aggregation_version="v1", window="7d", denominator=0, freshness_at=_iso(NOW), owner="cam", decision="retrain-trigger")
    rec = observability.metric_record(name="ok_rate", value=0.9, raw_source="timeline.jsonl", aggregation_version="v1", window="7d", denominator=100, freshness_at=_iso(NOW), owner="cam", decision="retrain-trigger")
    assert rec["denominator"] == 100 and rec["owner"] == "cam"
    slo = observability.SLO("goal-success", 0.9, "7d")
    out = slo.evaluate([{"good": True}] * 8 + [{"good": False, "cause": "system_block"}, {"good": False, "cause": "user_cancelled"}])
    assert out["denominator"] == 9 and out["status"] == "burning" and out["counts_system_blocks"]
    assert slo.evaluate([])["status"] == "unmeasured"
    d = observability.AlertDeduper()
    assert d.evaluate("safety_violation", "inc-1", "x")["action"] == "page"
    assert d.evaluate("safety_violation", "inc-1", "x again")["action"] == "suppressed"
    assert d.evaluate("informational_drift", "inc-2", "y")["action"] == "dashboard"


def test_incident_lifecycle_is_ordered_and_quarantines_window():
    inc = incidents.Incident(severity="SEV-1", source="canary", observed_impact="correctness regression on bugfix slice")
    with pytest.raises(errors.UnexecutableError):
        inc.close(True)  # cannot skip ahead
    inc.contain(["challenger disabled", "serving pointer pinned"])
    inc.preserve(["timeline.jsonl", "canary.jsonl"])
    inc.communicate("bugfix slice 0.62 vs floor 0.70; cause not yet known")
    with pytest.raises(errors.UnexecutableError):
        inc.restore({"target": "inc"}, verified=False)
    inc.restore({"target": "inc"}, verified=True)
    inc.investigate("mixture drift in anneal stage", "recipe_problem")
    assert inc.suspected_cause and inc.confirmed_cause is None
    inc.correct(owner="cam", test="tests/test_anneal.py", due_gate="phase-5", confirmed_cause="anneal mixture unversioned")
    with pytest.raises(errors.UnexecutableError):
        inc.close(recurrence_prevention_verified=False)
    assert inc.training_eligible(_iso(datetime.now(UTC))) is False  # inside the open window
    inc.close(recurrence_prevention_verified=True)
    assert inc.status == "close" and [t["step"] for t in inc.timeline] == list(incidents.LIFECYCLE)
    assert inc.training_eligible("2026-01-01T00:00:00Z") is True
    with pytest.raises(errors.InvalidInputError):
        incidents.Incident(severity="SEV-9", source="x", observed_impact="y")
    drill = incidents.dr_drill_checklist({"repository_checkout": True, "state_store_integrity": True})
    assert not drill["ok"] and "model_loading" in drill["failed"] and drill["recovery_order"][-1] == "training"


def test_retention_is_deterministic_idempotent_and_respects_holds():
    old = _iso(NOW - timedelta(days=400))
    recent = _iso(NOW - timedelta(days=1))
    recs = [{"record_id": "r1", "data_class": "raw_capture", "created_at": old, "deletion_key": "u1"}, {"record_id": "r2", "data_class": "raw_capture", "created_at": recent, "deletion_key": "u2"}, {"record_id": "r3", "data_class": "approval_release_evidence", "created_at": old}, {"record_id": "r4", "data_class": "curated_dataset", "created_at": old, "deletion_key": "held"}, {"record_id": "r5", "data_class": "sandbox_output", "created_at": recent, "deletion_key": "u9"}]
    out = retention.expire(recs, now=NOW, legal_holds={"held"}, deletion_requests={"u9"})
    assert out["tombstoned"] == ["r1", "r5"] and out["expedited_by_deletion_request"] == ["r5"] and out["held"] == ["r4"] and out["kept"] == ["r2", "r3"]
    again = retention.expire(recs, now=NOW, legal_holds={"held"}, deletion_requests={"u9"})
    assert again["tombstoned"] == [] and again["kept"] == ["r2", "r3"]  # idempotent
    with pytest.raises(errors.InvalidInputError):
        retention.expire([{"record_id": "x", "data_class": "mystery", "created_at": old}], now=NOW)


# --- §27 Forge runner script against a real local git conveyor ---------------------------------------------


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True, check=False).returncode != 0, reason="git required")
def test_forge_runner_once_completes_a_harmless_job(tmp_path):
    # a bare queue repo seeded with the layout + one pending job; a bare target repo with one commit
    bare_q = tmp_path / "queue.git"
    _git(["init", "--quiet", "--bare", "-b", "main", str(bare_q)], tmp_path)
    seed = tmp_path / "seed"
    _git(["clone", "--quiet", str(bare_q), str(seed)], tmp_path)
    target_src = tmp_path / "target_src"
    target_src.mkdir()
    _git(["init", "--quiet", "-b", "main"], target_src)
    (target_src / "train.py").write_text("print('FORGE_METRIC loss=0.25')\nopen('out.bin','wb').write(b'ok')\n")
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "add", "."], target_src)
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "init"], target_src)
    ref = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target_src, capture_output=True, text=True, check=True).stdout.strip()
    bare_t = tmp_path / "remotes" / "owner" / "repo"
    bare_t.parent.mkdir(parents=True)
    _git(["clone", "--quiet", "--bare", str(target_src), str(bare_t)], tmp_path)
    from dottie_loop.forge import ForgeQueue, JobSpec

    q = ForgeQueue(seed, repo_allowlist=["owner/repo"])
    job = JobSpec(repo="owner/repo", ref=ref, argv=[sys.executable, "train.py"], cwd=".", requirements={"cuda": False, "vram_gb": 0, "torch": False}, inputs=[{"path": "train.py", "sha256": __import__("hashlib").sha256((target_src / "train.py").read_bytes()).hexdigest()}], outputs=[{"path": "out.bin", "required": True}], timeout_seconds=60, submitted_by="test")
    q.submit(job)
    for d in ("runners", "jobs/pending", "jobs/claimed", "jobs/done", "results"):
        (seed / d / ".keep").touch()
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], seed)
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "seed"], seed)
    _git(["push", "--quiet"], seed)
    script = Path(__file__).resolve().parents[1] / "scripts" / "forge_runner.py"
    proc = subprocess.run([sys.executable, str(script), "--queue-repo", str(bare_q), "--workdir", str(tmp_path / "box"), "--allow", "owner/repo", "--remote-base", str(tmp_path / "remotes"), "--hostname", "testbox", "--once"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["claimed"] == job.job_id and out["result"]["status"] == "ok" and out["result"]["metrics"] == {"loss": 0.25}
    assert out["result"]["outputs"][0]["path"] == "out.bin"
    # results and the runner record travelled back through the conveyor
    _git(["pull", "--quiet", "--rebase"], seed)
    assert (seed / "runners" / "testbox.json").exists()
    assert json.loads((seed / "results" / job.job_id / "result.json").read_text())["status"] == "ok"
    assert (seed / "jobs" / "done" / f"{job.job_id}.json").exists() and not list((seed / "jobs" / "pending").glob("*.json"))
