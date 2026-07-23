"""Heartbeat — openswap #6 (Healthchecks.io/Cronitor -> stdlib dead-man's-switch
on the shared uptime ledger). Pure-logic core tests + capability-detection
fallback + the subprocess envelope. Offline and deterministic by construction:
`now`/`ts` are explicit everywhere, file beats use os.utime-pinned mtimes, and
no test opens a socket (route_request is exercised socket-free)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import heartbeat, openswap, uptime

ROOT = Path(__file__).resolve().parents[1]


def _mem():
    return heartbeat.open_registry(":memory:")


# ---- staleness verdicts -----------------------------------------------------


def test_status_of_matrix():
    assert heartbeat.status_of(100.0, None)["status"] == "never"
    assert heartbeat.status_of(100.0, 90.0, grace_s=60)["status"] == "ok"
    assert heartbeat.status_of(160.0, 100.0, grace_s=60)["status"] == "ok"  # boundary
    stale = heartbeat.status_of(161.0, 100.0, grace_s=60)
    assert stale["status"] == "stale"
    assert stale["age_s"] == 61.0 and stale["overdue_s"] == 1.0
    late = heartbeat.status_of(150.0, 100.0, grace_s=60, expected_interval_s=30)
    assert late["status"] == "late"  # early warning between cadence and grace
    # future timestamp (clock skew / touched-ahead file) reads as fresh
    assert heartbeat.status_of(100.0, 500.0, grace_s=60)["age_s"] == 0.0


# ---- the registry -----------------------------------------------------------


def test_beat_upserts_and_reports_gap():
    conn = _mem()
    b1 = heartbeat.beat(conn, "trainer", ts=100.0, note="step 1")
    assert b1["count"] == 1 and b1["prev_ts"] is None and b1["gap_s"] is None
    b2 = heartbeat.beat(conn, "trainer", ts=160.0)
    assert b2["count"] == 2 and b2["prev_ts"] == 100.0 and b2["gap_s"] == 60.0
    row = heartbeat.last_beat(conn, "trainer")
    assert row["first_ts"] == 100.0 and row["note"] == "step 1"  # note survives


def test_beat_rejects_invalid_names():
    conn = _mem()
    for bad in ("", "Bad!", "UPPER", "-lead", "x" * 65, 42):
        with pytest.raises(ValueError):
            heartbeat.beat(conn, bad, ts=1.0)


# ---- the watcher pass -------------------------------------------------------


def test_sweep_lifecycle_incident_and_alert_events():
    conn = _mem()
    daemons = {"worker": {"grace_s": 60.0}}
    heartbeat.beat(conn, "worker", ts=100.0)
    r1 = heartbeat.sweep(conn, daemons, now=110.0)["results"][0]
    assert r1["status"] == "ok" and r1["state"] == "up"
    assert heartbeat.sweep(conn, daemons, now=110.0)["alerts"] == []  # no day-one noise
    stale = heartbeat.sweep(conn, daemons, now=200.0)
    assert stale["results"][0]["status"] == "stale"
    assert stale["results"][0]["state"] == "down"
    assert stale["alerts"][0]["kind"] == "alert"
    # incidents live in the SHARED #2 table, namespaced — substrate reuse
    incs = uptime.list_incidents(conn, target="hb:worker", open_only=True)
    assert len(incs) == 1 and incs[0]["state"] == "down"
    # still stale next sweep: no repeat alert (transition-only, no spam)
    assert heartbeat.sweep(conn, daemons, now=205.0)["alerts"] == []
    heartbeat.beat(conn, "worker", ts=210.0)
    back = heartbeat.sweep(conn, daemons, now=215.0)
    assert back["results"][0]["status"] == "ok"
    assert back["alerts"][0]["kind"] == "recovery"
    assert back["results"][0]["incident"]["closed"] == incs[0]["id"]
    assert uptime.list_incidents(conn, target="hb:worker", open_only=True) == []
    kinds = [e["kind"] for e in uptime.recent_events(conn, target="hb:worker")]
    assert kinds == ["recovery", "alert"]  # the alert-router read contract


def test_late_is_early_warning_degraded():
    conn = _mem()
    daemons = {"loop": {"grace_s": 600.0, "expected_interval_s": 60.0}}
    heartbeat.beat(conn, "loop", ts=100.0)
    r = heartbeat.sweep(conn, daemons, now=300.0)["results"][0]
    assert r["status"] == "late" and r["state"] == "degraded"
    diags = heartbeat.to_diagnostics([r])
    assert diags[0]["severity"] == "warning"


def test_never_stays_out_of_state_machine():
    conn = _mem()
    daemons = {"ghost": {"grace_s": 60.0}}
    res = heartbeat.sweep(conn, daemons, now=100.0)
    assert res["results"][0]["status"] == "never"
    assert res["results"][0]["state"] == "unknown"
    assert res["alerts"] == []  # a daemon the registry never met can't "die"
    assert conn.execute("SELECT COUNT(*) AS n FROM state").fetchone()["n"] == 0
    b = heartbeat.board(conn, daemons, now=100.0)[0]
    assert b["status"] == "never" and b["state"] == "unknown" and b["beats"] is None


def test_file_heartbeats_use_mtime(tmp_path):
    f = tmp_path / "ckpt.log"
    f.write_text("x", encoding="utf-8")
    os.utime(f, (1000.0, 1000.0))
    daemons = {
        "ckpt": {"kind": "file", "path": str(f), "grace_s": 60.0},
        "gone": {"kind": "file", "path": str(tmp_path / "nope"), "grace_s": 60.0},
    }
    conn = _mem()
    by = {r["daemon"]: r for r in heartbeat.sweep(conn, daemons, now=1030.0)["results"]}
    assert by["ckpt"]["status"] == "ok" and by["ckpt"]["last_ts"] == 1000.0
    assert by["gone"]["status"] == "never"  # missing file = no beat, not a crash
    by2 = {
        r["daemon"]: r for r in heartbeat.sweep(conn, daemons, now=2000.0)["results"]
    }
    assert by2["ckpt"]["status"] == "stale" and by2["ckpt"]["state"] == "down"


def test_namespace_isolated_from_uptime_targets():
    conn = _mem()
    # an uptime target and a daemon share the name "ollama" in the same ledger
    uptime.record_check(conn, target="ollama", url="u", ts=1.0, state="up")
    uptime.apply_state(conn, "ollama", ts=1.0, damping=1)
    heartbeat.beat(conn, "ollama", ts=1.0)
    heartbeat.sweep(conn, {"ollama": {"grace_s": 60.0}}, now=1000.0)
    rows = {
        r["target"]: r["state"] for r in conn.execute("SELECT target, state FROM state")
    }
    assert rows == {"ollama": "up", "hb:ollama": "down"}  # no clobbering


# ---- daemons are policy-as-config -------------------------------------------


def test_load_daemons_defaults_and_overlay(tmp_path):
    defaults = heartbeat.load_daemons(None)
    assert set(defaults) == {
        "trainer",
        "research-loop",
        "factory-checkpointer",
        "watch-rearm",
    }
    assert all(cfg["kind"] == "beat" for cfg in defaults.values())
    overlay = tmp_path / "daemons.json"
    overlay.write_text(
        json.dumps(
            {
                "watch-rearm": False,
                "trainer": {"grace_s": 900, "expected_interval_s": 300},
                "ckpt": {"kind": "file", "path": "steps/ckpt.log", "grace_s": 1200},
            }
        ),
        encoding="utf-8",
    )
    d = heartbeat.load_daemons(str(overlay))
    assert "watch-rearm" not in d
    assert d["trainer"]["grace_s"] == 900  # scalar replaced
    assert d["trainer"]["note"] == "training step loop"  # defaults kept
    assert d["ckpt"]["kind"] == "file" and d["ckpt"]["path"] == "steps/ckpt.log"


def test_load_daemons_rejects_bad_shapes(tmp_path):
    bads = (
        "[1]",
        '{"x": {"kind": "file"}}',
        '{"x": {"kind": "weird"}}',
        '{"x": {"grace_s": -5}}',
        '{"x": {"grace_s": true}}',
        '{"Bad Name": {}}',
    )
    for bad in bads:
        f = tmp_path / "bad.json"
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            heartbeat.load_daemons(str(f))


# ---- family schema + detection ----------------------------------------------


def test_diagnostics_normalize_into_family_schema():
    conn = _mem()
    daemons = {
        "fresh": {"grace_s": 600.0},
        "dead": {"grace_s": 60.0},
        "ghost": {"grace_s": 60.0},
    }
    heartbeat.beat(conn, "fresh", ts=990.0)
    heartbeat.beat(conn, "dead", ts=100.0)
    diags = heartbeat.to_diagnostics(
        heartbeat.sweep(conn, daemons, now=1000.0)["results"]
    )
    assert [d["rule"] for d in diags] == ["heartbeat:stale", "heartbeat:never"]
    assert diags[0]["path"] == "heartbeat:dead" and diags[0]["severity"] == "error"
    assert diags[1]["severity"] == "info"  # never = visible, not an alarm
    summary = openswap.summarize(diags)
    assert summary["by_severity"] == {
        "error": 1,
        "warning": 0,
        "suggestion": 0,
        "info": 1,
    }


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.heartbeat import cli as heartbeat_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = heartbeat_cli._capability()
    assert cap["adapter"] == "heartbeat"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "healthchecks"
    assert cap["extras"]["runitor"]["found"] is False


# ---- HTTP check-in routing (socket-free) ------------------------------------


def test_parse_beat_path():
    assert heartbeat.parse_beat_path("/beat/trainer") == "trainer"
    assert heartbeat.parse_beat_path("/beat/trainer?x=1") == "trainer"
    assert heartbeat.parse_beat_path("/beat/Bad!") is None
    assert heartbeat.parse_beat_path("/beat/") is None
    assert heartbeat.parse_beat_path("/") is None


def test_route_request_records_and_rejects():
    conn = _mem()
    code, payload = heartbeat.route_request(conn, "/", now=1.0)
    assert (code, payload["daemons_seen"]) == (200, 0)
    code, payload = heartbeat.route_request(conn, "/beat/worker", now=5.0)
    assert code == 200 and payload["count"] == 1
    code, payload = heartbeat.route_request(conn, "/beat/worker?src=cron", now=6.0)
    assert code == 200 and payload["count"] == 2 and payload["gap_s"] == 1.0
    code, payload = heartbeat.route_request(conn, "/beat/Bad!", now=7.0)
    assert code == 400 and "example" in payload  # junk never pollutes the registry
    assert heartbeat.route_request(conn, "/nope", now=8.0)[0] == 404
    assert heartbeat.route_request(conn, "/", now=9.0)[1]["daemons_seen"] == 1


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


def test_cli_heartbeat_hello_envelope():
    r = _cli(["heartbeat", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_beat_then_sweep_then_status_loop(tmp_path):
    db = str(tmp_path / "hb.db")
    r = _cli(["heartbeat", "beat", "trainer", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["count"] == 1
    r = _cli(["heartbeat", "sweep", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    # trainer just beat; the other three org daemons have never checked in
    assert data["data"]["by_status"] == {"ok": 1, "never": 3}
    r = _cli(["heartbeat", "status", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    board = json.loads(r.stdout)["data"]["board"]
    assert {b["daemon"]: b["status"] for b in board}["trainer"] == "ok"


def test_cli_status_without_ledger_fails_actionably(tmp_path):
    r = _cli(["heartbeat", "status", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no monitoring ledger" in data["error"]
    assert "example" in data
