"""Smoke — openswap #5 (Checkly -> JSON url->expected-string manifest polled
under a bounded retry/backoff budget). Pure-logic core tests + capability
detection fallback + the subprocess envelope. Offline and deterministic by
construction: fetches are injected fakes, sleep/clock are a fake timeline, and
no test opens a socket."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, smoke

ROOT = Path(__file__).resolve().parents[1]

CFG = {"url": "https://www.bhenre.com", "expect": "bhenre"}


def _r(http=200, ms=50.0, body="", error=None):
    return {"http": http, "latency_ms": ms, "error": error, "body_head": body}


HIT = _r(body="<title>bhenre</title>")
MISS = _r(body="<html>deploying...</html>")
DOWN = _r(http=None, ms=0.0, error="URLError: refused")


def _scripted_fetch(seq):
    """Fetch fake that replays canned results in order (offline invariant)."""
    it = iter(seq)

    def fetch(url, cfg):
        return next(it)

    return fetch


class _Timeline:
    """Fake clock + sleep: time only moves when the retry loop sleeps."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


# ---- manifest parsing -------------------------------------------------------


def test_load_checks_both_shapes(tmp_path):
    f = tmp_path / "smoke.json"
    f.write_text(
        json.dumps(
            {
                "https://www.bhenre.com": "bhenre",
                "home": {
                    "url": "https://dumbmodel.com",
                    "expect": "vector",
                    "max_ms": 1500,
                },
            }
        ),
        encoding="utf-8",
    )
    checks = smoke.load_checks(f)
    # minimal shape: the key IS the url, the value the expected string
    assert checks["https://www.bhenre.com"] == {
        "url": "https://www.bhenre.com",
        "expect": "bhenre",
    }
    assert checks["home"]["max_ms"] == 1500.0


def test_load_checks_tolerates_utf8_bom(tmp_path):
    # PS 5.1 (Set-Content -Encoding utf8) writes BOMs — reproduced live on the
    # first real invocation; per-site manifests will be written by PS wrappers
    f = tmp_path / "smoke.json"
    f.write_bytes(b'\xef\xbb\xbf{"https://www.bhenre.com": "bhenre"}')
    assert smoke.load_checks(f)["https://www.bhenre.com"]["expect"] == "bhenre"


def test_load_checks_rejects_bad_shapes(tmp_path):
    bads = (
        "[1]",
        "{}",
        '{"x": 3}',
        '{"x": {"expect": "no url"}}',
        '{"x": {"url": "ftp://nope", "expect": "y"}}',
        '{"x": {"url": "https://a.com", "expect": ""}}',
        '{"x": {"url": "https://a.com", "expect": "y", "max_ms": true}}',
        '{"x": {"url": "https://a.com", "expect": "y", "max_ms": -5}}',
    )
    for bad in bads:
        f = tmp_path / "bad.json"
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            smoke.load_checks(f)


# ---- backoff schedule -------------------------------------------------------


def test_backoff_delays_geometric_and_capped():
    assert smoke.backoff_delays(5) == [2.0, 4.0, 8.0, 16.0]  # defaults
    assert smoke.backoff_delays(1) == []  # single attempt never sleeps
    assert smoke.backoff_delays(5, initial=20, multiplier=3, max_delay=30) == [
        20.0,
        30.0,
        30.0,
        30.0,
    ]


# ---- attempt classification -------------------------------------------------


def test_classify_attempt_matrix():
    ok, rule, _ = smoke.classify_attempt(HIT, CFG)
    assert ok and rule is None
    assert smoke.classify_attempt(_r(http=201, body="bhenre"), CFG)[0]  # any 2xx
    assert smoke.classify_attempt(DOWN, CFG)[1] == "unreachable"
    assert smoke.classify_attempt(_r(http=404, body="bhenre"), CFG)[1] == "http"
    assert smoke.classify_attempt(_r(http=503), CFG)[1] == "http"
    assert smoke.classify_attempt(MISS, CFG)[1] == "expect-miss"
    slow_cfg = {**CFG, "max_ms": 100.0}
    assert smoke.classify_attempt(_r(ms=250.0, body="bhenre"), slow_cfg)[1] == "slow"
    assert smoke.classify_attempt(_r(ms=99.0, body="bhenre"), slow_cfg)[0]
    # wrong content is worse than late content: expect-miss outranks slow
    assert (
        smoke.classify_attempt(_r(ms=250.0, body="nope"), slow_cfg)[1] == "expect-miss"
    )


# ---- retry loop -------------------------------------------------------------


def test_run_check_retries_until_match():
    tl = _Timeline()
    r = smoke.run_check(
        "site",
        CFG,
        _scripted_fetch([MISS, MISS, HIT]),
        attempts=5,
        delays=[2.0, 4.0, 8.0, 16.0],
        budget_s=120.0,
        sleep=tl.sleep,
        clock=tl.clock,
    )
    assert r["ok"] is True and r["rule"] is None and r["detail"] is None
    assert r["attempts_used"] == 3
    assert tl.slept == [2.0, 4.0]  # backoff between failed attempts only
    assert [a["rule"] for a in r["trail"]] == ["expect-miss", "expect-miss", None]
    assert r["elapsed_s"] == 6.0


def test_run_check_exhaustion_reports_final_reason():
    tl = _Timeline()
    r = smoke.run_check(
        "site",
        CFG,
        _scripted_fetch([DOWN, DOWN, MISS]),
        attempts=3,
        delays=[1.0, 1.0],
        sleep=tl.sleep,
        clock=tl.clock,
    )
    assert r["ok"] is False
    assert r["rule"] == "expect-miss"  # the LAST attempt's verdict
    assert r["attempts_used"] == 3 and r["budget_exhausted"] is False


def test_run_check_budget_never_starts_an_overrunning_sleep():
    tl = _Timeline()
    r = smoke.run_check(
        "site",
        CFG,
        _scripted_fetch([MISS, MISS, HIT]),
        attempts=3,
        delays=[10.0, 10.0],
        budget_s=15.0,
        sleep=tl.sleep,
        clock=tl.clock,
    )
    # attempt 1 fails, sleep 10; attempt 2 fails, next sleep would hit 20 > 15
    assert r["ok"] is False and r["budget_exhausted"] is True
    assert r["attempts_used"] == 2 and tl.slept == [10.0]
    assert "budget exhausted" in r["detail"]


# ---- suite + family schema --------------------------------------------------


def test_run_suite_mixed_normalizes_into_family_diagnostics():
    tl = _Timeline()
    checks = {
        "good": dict(CFG),
        "bad": {"url": "https://dumbmodel.com", "expect": "vector"},
        "slow": {"url": "https://arxiviq.com", "expect": "arxiv", "max_ms": 100.0},
    }
    fetch = _scripted_fetch([HIT, _r(http=502), _r(ms=900.0, body="arxiv")])
    res = smoke.run_suite(checks, fetch, attempts=1, sleep=tl.sleep, clock=tl.clock)
    assert res["ok"] is False
    assert (res["passed"], res["failed"], res["total"]) == (1, 2, 3)
    diags = smoke.to_diagnostics(res["results"])
    assert len(diags) == 2  # passing checks emit nothing
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["smoke:http"]["severity"] == "error"
    assert by_rule["smoke:slow"]["severity"] == "warning"
    assert by_rule["smoke:http"]["path"] == "https://dumbmodel.com"
    summary = openswap.summarize(diags)
    assert summary["by_severity"] == {
        "error": 1,
        "warning": 1,
        "suggestion": 0,
        "info": 0,
    }


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.smoke import cli as smoke_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = smoke_cli._capability()
    assert cap["adapter"] == "smoke"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert "never executed" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "hurl"
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


def test_cli_smoke_hello_envelope():
    r = _cli(["smoke", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_smoke_plan_resolves_manifest_offline(tmp_path):
    f = tmp_path / "smoke.json"
    f.write_text(json.dumps({"https://www.bhenre.com": "bhenre"}), encoding="utf-8")
    r = _cli(["smoke", "plan", "--manifest", str(f), "--attempts", "3"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["count"] == 1
    assert data["data"]["retry"]["delays"] == [2.0, 4.0]


def test_cli_smoke_run_without_manifest_fails_actionably(tmp_path):
    r = _cli(["smoke", "run", "--manifest", str(tmp_path / "none.json")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no smoke manifest" in data["error"]
    assert "example" in data
