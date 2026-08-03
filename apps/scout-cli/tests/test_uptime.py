"""Uptime — openswap #2 (UptimeRobot/Pingdom -> stdlib probe loop + sqlite
incident ledger). Pure-logic core tests + capability-detection fallback + the
subprocess envelope. Offline and deterministic by construction: probes are
injected fakes, timestamps are explicit, and no test opens a socket."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, uptime

ROOT = Path(__file__).resolve().parents[1]

OK = {"http": 200, "latency_ms": 50.0, "error": None, "body_head": ""}
DOWN = {"http": None, "latency_ms": 0.0, "error": "TimeoutError: x", "body_head": ""}


def _mem():
    return uptime.open_ledger(":memory:")


def _scripted_probe(seq):
    """Probe fake that replays canned results in order (offline invariant)."""
    it = iter(seq)

    def probe(url, cfg):
        return next(it)

    return probe


# ---- classification ---------------------------------------------------------


def test_classify_matrix():
    assert uptime.classify(200, 120) == "up"
    assert uptime.classify(302, 120) == "up"  # redirect proves liveness
    assert uptime.classify(404, 120) == "down"
    assert uptime.classify(503, 120) == "down"
    assert uptime.classify(None, 0) == "down"  # DNS/TLS/timeout failures
    assert uptime.classify(200, 5000) == "degraded"  # default 3000ms budget
    assert uptime.classify(200, 5000, degraded_ms=6000) == "up"
    assert uptime.classify(200, 100, expect_ok=False) == "degraded"
    assert uptime.classify(200, 100, expect_ok=True) == "up"


# ---- flap damping -----------------------------------------------------------


def test_damping_requires_consecutive_confirmation():
    assert uptime.damped_state(None, ["down"], 2) == "down"  # first sighting
    assert uptime.damped_state("up", ["up", "down"], 2) == "up"  # lone blip
    assert uptime.damped_state("up", ["down", "down"], 2) == "down"
    assert uptime.damped_state("up", ["down", "up", "down"], 2) == "up"  # flapping
    assert uptime.damped_state("down", ["up", "up"], 2) == "up"
    assert uptime.damped_state("up", ["down"], 2) == "up"  # not enough history


# ---- ledger + incident lifecycle --------------------------------------------


def test_incident_opens_after_damping_and_closes_on_recovery():
    conn = _mem()
    targets = {"svc": {"url": "https://dumbmodel.com"}}
    probe = _scripted_probe([OK, DOWN, DOWN, DOWN, OK, OK])
    states = []
    for ts in range(1, 7):
        res = uptime.run_pass(conn, targets, probe, ts=float(ts))
        states.append(res["results"][0]["confirmed"])
    assert states == ["up", "up", "down", "down", "down", "up"]
    incidents = uptime.list_incidents(conn)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["state"] == "down"
    assert inc["opened_ts"] == 3.0 and inc["closed_ts"] == 6.0
    assert inc["duration_s"] == 3.0
    assert uptime.list_incidents(conn, open_only=True) == []


def test_expect_string_miss_is_degraded():
    conn = _mem()
    targets = {"api": {"url": "https://bluehenre-campus.vercel.app/x", "expect": '"sites"'}}
    bad = {"http": 200, "latency_ms": 40.0, "error": None, "body_head": "<html>err</html>"}
    good = {"http": 200, "latency_ms": 40.0, "error": None, "body_head": '{"sites": []}'}
    row = uptime.run_pass(conn, targets, _scripted_probe([bad]), ts=1.0)["results"][0]
    assert row["expect_ok"] is False and row["observed"] == "degraded"
    row2 = uptime.run_pass(conn, targets, _scripted_probe([good]), ts=2.0)["results"][0]
    assert row2["expect_ok"] is True and row2["observed"] == "up"


def test_board_reports_unknown_then_confirmed():
    conn = _mem()
    targets = {"svc": {"url": "https://dumbmodel.com"}}
    b0 = uptime.board(conn, targets)
    assert b0[0]["state"] == "unknown" and b0[0]["last_check"] is None
    uptime.run_pass(conn, targets, _scripted_probe([OK]), ts=1.0)
    b1 = uptime.board(conn, targets)
    assert b1[0]["state"] == "up"
    assert b1[0]["last_check"]["http"] == 200
    assert b1[0]["open_incident"] is None


def test_deploy_marker_events_on_timeline():
    conn = _mem()
    uptime.record_event(conn, kind="deploy", message="bhenre 4009c52", target="bhenre", ts=5.0)
    uptime.record_event(conn, kind="note", message="global note", ts=6.0)
    uptime.record_event(conn, kind="deploy", message="other", target="hub", ts=7.0)
    evs = uptime.recent_events(conn, target="bhenre")
    # global (NULL-target) events ride along; other targets' events do not
    assert [e["kind"] for e in evs] == ["note", "deploy"]
    assert [e["target"] for e in uptime.recent_events(conn)][:1] == ["hub"]


# ---- rollups ----------------------------------------------------------------


def test_rollup_percentiles_and_up_pct():
    conn = _mem()
    for i, ms in enumerate([100.0] * 98 + [900.0, 1000.0], 1):
        uptime.record_check(
            conn, target="svc", url="u", ts=float(i), state="up", http=200, latency_ms=ms
        )
    uptime.record_check(
        conn, target="svc", url="u", ts=101.0, state="down", error="boom"
    )
    roll = uptime.rollup(conn, "svc")
    assert roll["checks"] == 101
    assert roll["up_pct"] == round(100 * 100 / 101, 2)
    lat = roll["latency"]
    assert lat["p50"] == 100.0 and lat["p95"] == 100.0
    assert lat["p99"] == 900.0 and lat["max"] == 1000.0
    windowed = uptime.rollup(conn, "svc", since=101.0)
    assert windowed["checks"] == 1 and windowed["up_pct"] == 0.0


def test_latency_reports_the_sample_size_it_was_computed_over():
    """`checks` is not the latency sample size, and the gap is worst during an outage.

    A probe that times out records no latency, so failures leave the distribution
    entirely — latency looks BEST exactly when a target is most broken. Here 98 of
    100 probes time out and every percentile reads 12 ms off the 2 survivors.
    statuspage.services() publishes `checks` and `latency` side by side, so that row
    read "100 checks, p99 12 ms" for a service down 98% of the window.
    """
    conn = _mem()
    for i in range(98):
        uptime.record_check(
            conn, target="svc", url="u", ts=float(i), state="down", error="timeout"
        )
    for i in range(2):
        uptime.record_check(
            conn, target="svc", url="u", ts=float(100 + i), state="up",
            http=200, latency_ms=12.0,
        )
    roll = uptime.rollup(conn, "svc")
    assert roll["checks"] == 100
    assert roll["up_pct"] == 2.0
    lat = roll["latency"]
    assert lat["p99"] == 12.0, "survivor latency is still reported, correctly"
    assert lat["n"] == 2, "the payload must say how many samples that came from"
    assert lat["n"] != roll["checks"], (
        "n that merely echoes `checks` would hide exactly the case this catches"
    )


def test_latency_n_is_zero_when_nothing_answered():
    """No answered probe means no distribution — n must say 0, not go missing."""
    conn = _mem()
    for i in range(5):
        uptime.record_check(
            conn, target="svc", url="u", ts=float(i), state="down", error="timeout"
        )
    lat = uptime.rollup(conn, "svc")["latency"]
    assert lat["n"] == 0
    assert lat["p50"] is None and lat["avg"] is None and lat["max"] is None


def test_percentile_edges():
    assert uptime.percentile([], 50) is None
    assert uptime.percentile([42.0], 99) == 42.0
    assert uptime.percentile([2.0, 1.0], 50) == 1.0  # sorts before ranking


# ---- targets are policy-as-config -------------------------------------------


def test_load_targets_defaults_and_overlay(tmp_path):
    defaults = uptime.load_targets(None)
    assert len(defaults) == 10  # 8-site fleet + bluehenre API + ollama
    assert {"hub", "bhenre", "bluehenre-api", "ollama"} <= set(defaults)
    overlay = tmp_path / "targets.json"
    overlay.write_text(
        json.dumps(
            {
                "ollama": False,
                "hub": {"expect": "vector"},
                "myapi": {"url": "https://api.example.com/health", "degraded_ms": 500},
            }
        ),
        encoding="utf-8",
    )
    t = uptime.load_targets(str(overlay))
    assert "ollama" not in t
    assert t["hub"]["url"] == "https://dumbmodel.com"  # defaults kept
    assert t["hub"]["expect"] == "vector"
    assert t["myapi"]["degraded_ms"] == 500


def test_load_targets_rejects_bad_shapes(tmp_path):
    for bad in ("[1]", '{"x": {"note": "no url"}}', '{"x": {"url": "ftp://nope"}}'):
        f = tmp_path / "bad.json"
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            uptime.load_targets(str(f))


# ---- family schema + detection ----------------------------------------------


def test_results_normalize_into_family_diagnostics():
    conn = _mem()
    targets = {
        "good": {"url": "https://dumbmodel.com"},
        "bad": {"url": "https://www.bhenre.com"},
    }
    probe = _scripted_probe([OK, DOWN])
    res = uptime.run_pass(conn, targets, probe, ts=1.0)
    diags = uptime.to_diagnostics(res["results"])
    assert len(diags) == 1  # up targets emit nothing
    assert diags[0]["rule"] == "uptime:down"
    assert diags[0]["severity"] == "error"
    assert diags[0]["path"] == "https://www.bhenre.com"
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.uptime import cli as uptime_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = uptime_cli._capability()
    assert cap["adapter"] == "uptime"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "uptime-kuma"
    assert cap["extras"]["curl"]["found"] is False


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


def test_cli_uptime_hello_envelope():
    r = _cli(["uptime", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_uptime_targets_default_fleet():
    r = _cli(["uptime", "targets"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["count"] == 10
    assert "hub" in data["data"]["targets"] and "ollama" in data["data"]["targets"]


def test_cli_uptime_status_without_ledger_fails_actionably(tmp_path):
    r = _cli(["uptime", "status", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no uptime ledger" in data["error"]
    assert "example" in data
