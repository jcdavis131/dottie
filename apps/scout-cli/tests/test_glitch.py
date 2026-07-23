"""Glitch — openswap #8 (Sentry -> GlitchTip-lite: stdlib capture/fingerprint/
sqlite/static-HTML). Pure-logic core tests + capability-detection fallback +
the subprocess envelope. Offline and deterministic by construction: `ts`/`now`
are explicit everywhere, no test opens a socket, and the excepthook is
exercised by calling it directly — nothing actually crashes."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import glitch, openswap

ROOT = Path(__file__).resolve().parents[1]

CRASH_TEXT = """\
2026-07-22 03:14:07 INFO trainer step 1487 checkpoint banked
Traceback (most recent call last):
  File "/app/trainer/loop.py", line 88, in run
    step(batch)
  File "/app/trainer/loop.py", line 41, in step
    loss = model(batch)
RuntimeError: CUDA out of memory

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/app/trainer/main.py", line 12, in <module>
    run()
  File "/app/trainer/loop.py", line 92, in run
    raise TrainerCrash("fatal") from exc
trainer.errors.TrainerCrash: fatal
2026-07-22 03:14:09 INFO container exiting
"""


def _mem():
    return glitch.open_store(":memory:")


def _boom() -> BaseException:
    try:
        1 / 0
    except ZeroDivisionError as exc:
        return exc


# ---- fingerprinting (the grouping contract) ---------------------------------


def test_fingerprint_ignores_lines_messages_and_path_noise():
    frames = [{"file": "C:\\app\\pkg\\mod.py", "line": 10, "function": "run"}]
    a = {"kind": "ValueError", "message": "bad id 12", "frames": frames}
    moved = {
        "kind": "ValueError",
        "message": "bad id 99",  # varying interpolations must not shard issues
        "frames": [{"file": "/other/PKG/Mod.py", "line": 500, "function": "run"}],
    }
    assert glitch.fingerprint_of(a) == glitch.fingerprint_of(moved)
    other_fn = {
        "kind": "ValueError",
        "message": "bad id 12",
        "frames": [{"file": "C:\\app\\pkg\\mod.py", "line": 10, "function": "step"}],
    }
    assert glitch.fingerprint_of(a) != glitch.fingerprint_of(other_fn)
    assert glitch.fingerprint_of({**a, "kind": "KeyError"}) != glitch.fingerprint_of(a)


def test_template_grouping_for_stackless_events():
    a = glitch.log_event("step 12 failed", template="step N failed")
    b = glitch.log_event("step 99 failed", template="step N failed")
    assert a["fingerprint"] == b["fingerprint"]
    assert a["message"] != b["message"]
    c = glitch.log_event("step 12 failed", template="step N failed", logger="other")
    assert c["fingerprint"] != a["fingerprint"]  # logger is part of the key
    # no template at all: the message is all there is to group on
    assert (
        glitch.log_event("x")["fingerprint"] != glitch.log_event("y")["fingerprint"]
    )


# ---- normalization ----------------------------------------------------------


def test_normalize_exception_frames_culprit_and_kind():
    ev = glitch.normalize_exception(_boom())
    assert ev["kind"] == "ZeroDivisionError"  # builtins stay unqualified
    assert ev["message"] == "division by zero"
    assert ev["frames"] and ev["frames"][-1]["function"] == "_boom"
    assert ev["culprit"].endswith(":_boom") and ev["line"] > 0
    assert "ZeroDivisionError" in ev["traceback"]
    assert ev["file"] == ev["frames"][-1]["file"]


def test_exception_without_traceback_still_groups():
    # never-raised exception: no frames, no crash — message-based grouping
    ev = glitch.normalize_exception(ValueError("x"))
    assert ev["frames"] == [] and ev["culprit"] is None
    ev2 = glitch.normalize_exception(ValueError("x"))
    assert ev["fingerprint"] == ev2["fingerprint"]


def test_normalize_log_record_template_vs_exc_info():
    r1 = logging.LogRecord("worker", logging.ERROR, "x.py", 10, "step %s", (12,), None)
    r2 = logging.LogRecord("worker", logging.ERROR, "x.py", 99, "step %s", (99,), None)
    e1, e2 = glitch.normalize_log_record(r1), glitch.normalize_log_record(r2)
    assert e1["fingerprint"] == e2["fingerprint"]  # the unformatted-msg trick
    assert e1["message"] == "step 12" and e1["kind"] == "log.error"
    exc = _boom()
    r3 = logging.LogRecord(
        "worker", logging.CRITICAL, "x.py", 10, "boom", (), (type(exc), exc, None)
    )
    e3 = glitch.normalize_log_record(r3)
    assert e3["kind"] == "ZeroDivisionError" and e3["level"] == "fatal"
    assert e3["logger"] == "worker" and e3["fingerprint"] != e1["fingerprint"]


# ---- the issue store --------------------------------------------------------


def test_capture_upserts_and_out_of_order_ts_never_rewrites_history():
    conn = _mem()
    ev = glitch.log_event("boom", template="boom")
    r1 = glitch.capture(conn, ev, project="p", ts=100.0)
    assert r1["new"] is True and r1["count"] == 1 and r1["status"] == "open"
    # ingesting an OLDER log later: first_seen moves back, last_seen stays
    r2 = glitch.capture(conn, ev, project="p", ts=50.0, context={"step": 7})
    assert r2["new"] is False and r2["count"] == 2
    issue = glitch.get_issue(conn, r1["issue_id"])
    assert issue["first_seen"] == 50.0 and issue["last_seen"] == 100.0
    occ = glitch.occurrences_of(conn, r1["issue_id"])
    assert len(occ) == 2 and occ[0]["ts"] == 100.0  # newest first
    assert occ[1]["context"] == {"step": 7}  # JSON round-trips
    # same fingerprint in another project = a separate issue (per-project scope)
    r3 = glitch.capture(conn, ev, project="q", ts=1.0)
    assert r3["new"] is True and r3["issue_id"] != r1["issue_id"]


def test_regression_reopens_resolved_but_ignored_stays_ignored():
    conn = _mem()
    ev = glitch.log_event("flaky", template="flaky")
    iid = glitch.capture(conn, ev, project="p", ts=1.0)["issue_id"]
    assert glitch.set_status(conn, iid, "resolved")["status"] == "resolved"
    r = glitch.capture(conn, ev, project="p", ts=2.0)
    assert r["regressed"] is True and r["status"] == "open"  # Sentry's contract
    glitch.set_status(conn, iid, "ignored")
    r = glitch.capture(conn, ev, project="p", ts=3.0)
    assert r["regressed"] is False and r["status"] == "ignored"
    assert glitch.get_issue(conn, iid)["count"] == 3  # volume still visible
    with pytest.raises(ValueError):
        glitch.set_status(conn, iid, "wontfix")
    assert glitch.set_status(conn, 999, "open") is None


# ---- capture plumbing (the drop-ins) ----------------------------------------


def test_handler_captures_errors_groups_templates(tmp_path):
    db = tmp_path / "g.db"
    logger = logging.getLogger("glitch-test-worker")
    logger.propagate = False
    handler = glitch.Handler(db, project="worker")
    logger.addHandler(handler)
    try:
        logger.error("step %s failed", 12)
        logger.error("step %s failed", 99)  # same template -> same issue
        logger.warning("below handler level")  # ERROR default: not captured
        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception("crashed")  # exc_info -> frame grouping
    finally:
        logger.removeHandler(handler)
    conn = glitch.open_store(db)
    issues = {i["kind"]: i for i in glitch.list_issues(conn)}
    assert set(issues) == {"log.error", "ZeroDivisionError"}
    assert issues["log.error"]["count"] == 2
    assert issues["log.error"]["message"] == "step 99 failed"  # latest wins
    assert issues["ZeroDivisionError"]["project"] == "worker"


def test_excepthook_records_chains_and_skips_keyboardinterrupt(
    tmp_path, monkeypatch
):
    db = tmp_path / "g.db"
    calls = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: calls.append(a))
    hook = glitch.install_excepthook(db, project="daemon")
    assert sys.excepthook is hook and hook.previous is not None
    exc = _boom()
    hook(type(exc), exc, exc.__traceback__)
    assert len(calls) == 1  # the crash still reaches the previous hook
    hook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert len(calls) == 2  # Ctrl+C passes through...
    conn = glitch.open_store(db)
    issues = glitch.list_issues(conn)
    assert len(issues) == 1  # ...but is never recorded as a defect
    assert issues[0]["kind"] == "ZeroDivisionError"
    assert issues[0]["project"] == "daemon"


# ---- crash-log ingestion ----------------------------------------------------


def test_parse_traceback_text_takes_last_block():
    ev = glitch.parse_traceback_text(CRASH_TEXT)
    # last block = the outermost exception of the chain — what Sentry displays
    assert ev["kind"] == "trainer.errors.TrainerCrash" and ev["message"] == "fatal"
    assert [f["function"] for f in ev["frames"]] == ["<module>", "run"]
    assert ev["frames"][0]["code"] == "run()"  # source echo captured
    assert ev["culprit"] == "/app/trainer/loop.py:run" and ev["line"] == 92
    assert ev["traceback"].startswith("Traceback (most recent call last):")


def test_parse_traceback_text_rejects_junk_and_truncation():
    assert glitch.parse_traceback_text("just some log lines\nno crash here") is None
    # header word-dropped in prose, no frames
    assert glitch.parse_traceback_text("Traceback (most recent call last):") is None
    truncated = 'Traceback (most recent call last):\n  File "x.py", line 1, in m'
    assert glitch.parse_traceback_text(truncated) is None
    # a truncated LAST block falls back to the previous complete one
    both = CRASH_TEXT + "\nTraceback (most recent call last):\n"
    assert glitch.parse_traceback_text(both)["kind"] == "trainer.errors.TrainerCrash"


# ---- retention (policy-as-config) -------------------------------------------


def test_load_retention_defaults_overlay_and_rejects(tmp_path):
    assert glitch.load_retention(None)["*"] == {
        "max_age_s": 30 * 86400.0,
        "keep_last": 200,
    }
    overlay = tmp_path / "retention.json"
    overlay.write_text(
        json.dumps({"trainer": {"max_age_s": 86400}, "noisy": False}),
        encoding="utf-8",
    )
    r = glitch.load_retention(str(overlay))
    assert r["trainer"] == {"max_age_s": 86400} and r["noisy"] is False
    assert r["*"]["keep_last"] == 200  # defaults kept
    for bad in ("[1]", '{"x": 3}', '{"x": {"max_age_s": -1}}',
                '{"x": {"keep_last": true}}', '{"x": {"keep_last": -2}}'):
        overlay.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            glitch.load_retention(str(overlay))


def test_prune_ages_out_and_caps_but_counters_survive():
    conn = _mem()
    ev_a = glitch.log_event("a", template="a")
    for ts in (100.0, 200.0, 300.0, 400.0, 500.0):
        a_id = glitch.capture(conn, ev_a, project="p", ts=ts)["issue_id"]
    b_id = glitch.capture(conn, glitch.log_event("b"), project="p", ts=100.0)[
        "issue_id"
    ]
    glitch.set_status(conn, b_id, "resolved")
    # exempt project: nothing moves
    assert glitch.prune(conn, {"p": False, "*": {"max_age_s": 1.0}}, now=600.0) == {
        "occurrences_deleted": 0,
        "issues_deleted": 0,
    }
    res = glitch.prune(conn, {"*": {"max_age_s": 250.0}}, now=600.0)
    # a: ts<350 drops 3; b: drops its 1 AND the resolved aged issue itself
    assert res == {"occurrences_deleted": 4, "issues_deleted": 1}
    assert glitch.get_issue(conn, b_id) is None
    issue = glitch.get_issue(conn, a_id)
    assert issue is not None and issue["status"] == "open"  # open = still a bug
    assert issue["count"] == 5  # counters ALWAYS survive pruning
    assert glitch.prune(conn, {"*": {"keep_last": 1}}, now=600.0) == {
        "occurrences_deleted": 1,
        "issues_deleted": 0,
    }
    occ = glitch.occurrences_of(conn, a_id)
    assert [o["ts"] for o in occ] == [500.0]  # newest kept


# ---- family schema + the static browser -------------------------------------


def test_diagnostics_normalize_into_family_schema():
    conn = _mem()
    glitch.capture(conn, glitch.normalize_exception(_boom()), project="p", ts=1.0)
    w_id = glitch.capture(
        conn, glitch.log_event("meh", level="warning"), project="p", ts=2.0
    )["issue_id"]
    i_id = glitch.capture(conn, glitch.log_event("shh"), project="p", ts=3.0)[
        "issue_id"
    ]
    glitch.set_status(conn, w_id, "ignored")
    glitch.set_status(conn, i_id, "resolved")
    diags = glitch.to_diagnostics(glitch.list_issues(conn, status=None))
    assert len(diags) == 1  # resolved/ignored emit nothing — gate on live only
    assert diags[0]["rule"] == "glitch:ZeroDivisionError"
    assert diags[0]["severity"] == "error" and diags[0]["line"] > 0
    assert "(seen 1x)" in diags[0]["message"]
    assert openswap.summarize(diags)["by_severity"]["error"] == 1


def test_render_html_escapes_hostile_text(tmp_path):
    conn = _mem()
    assert "no issues recorded" in glitch.render_html(conn)
    ev = glitch.log_event("<script>alert(1)</script>", template="xss")
    ev["traceback"] = "raise <b>Boom</b>"
    glitch.capture(conn, ev, project="p", ts=1.0)
    page = glitch.render_html(conn)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert" not in page and "<b>Boom</b>" not in page
    assert "log.error" in page and "no issues recorded" not in page


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.glitch import cli as glitch_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = glitch_cli._capability()
    assert cap["adapter"] == "glitch"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "glitchtip"
    assert cap["extras"]["sentry-cli"]["found"] is False


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_glitch_hello_envelope():
    r = _cli(["glitch", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_capture_triage_gate_report_loop(tmp_path):
    db = str(tmp_path / "g.db")
    r = _cli(["glitch", "log", "backup failed", "--project", "cron", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["new"] is True
    crash = tmp_path / "crash.log"
    crash.write_text(CRASH_TEXT, encoding="utf-8")
    r = _cli(["glitch", "ingest", str(crash), "--project", "trainer", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["kind"] == "trainer.errors.TrainerCrash"
    r = _cli(["glitch", "issues", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert len(data["issues"]) == 2
    assert data["summary"]["by_severity"]["error"] == 2
    r = _cli(["glitch", "issues", "--db", db, "--fail-on", "error"])
    assert r.returncode == 1  # the gate fires on open errors
    for iid, verdict in (("1", "resolved"), ("2", "ignored")):
        r = _cli(["glitch", "mark", iid, verdict, "--db", db])
        assert r.returncode == 0, r.stderr + r.stdout
        assert json.loads(r.stdout)["data"]["issue"]["status"] == verdict
    r = _cli(["glitch", "issues", "--db", db, "--fail-on", "error"])
    assert r.returncode == 0, r.stderr + r.stdout  # triaged = gate passes
    out = tmp_path / "report.html"
    r = _cli(["glitch", "report", "--db", db, "--out", str(out)])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["open_issues"] == 0
    page = out.read_text(encoding="utf-8")
    assert "TrainerCrash" in page and "backup failed" in page


def test_cli_issues_without_store_fails_actionably(tmp_path):
    r = _cli(["glitch", "issues", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no issue store" in data["error"]
    assert "example" in data
