"""Runtrack — openswap #10 (Weights & Biases -> stdlib sqlite run/metric store).
Pure-logic core tests + compare/summary edge cases + capability-detection
fallback + the subprocess envelope. Offline and deterministic by construction:
`ts` is explicit everywhere, the store is :memory: or a tmp file, and this
adapter has no network surface at all so the CLI roundtrip runs fully offline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, runtrack

ROOT = Path(__file__).resolve().parents[1]


def _mem():
    return runtrack.open_store(":memory:")


# ---- runs -------------------------------------------------------------------


def test_start_run_config_roundtrip_and_duplicate_names():
    conn = _mem()
    r = runtrack.start_run(conn, "trainer", config={"lr": 3e-4, "bf16": True}, ts=100.0)
    assert r["id"] == 1 and r["status"] == "running" and r["created_ts"] == 100.0
    assert r["config"] == {"lr": 3e-4, "bf16": True}  # JSON round-trips
    assert runtrack.get_run(conn, 1)["config"]["lr"] == 3e-4
    # duplicate names are allowed and get distinct ids
    r2 = runtrack.start_run(conn, "trainer", ts=101.0)
    assert r2["id"] == 2 and r2["config"] is None


def test_start_run_rejects_bad_input():
    conn = _mem()
    for bad_name in ("", "   ", 42):
        with pytest.raises(ValueError):
            runtrack.start_run(conn, bad_name)
    with pytest.raises(ValueError):
        runtrack.start_run(conn, "ok", config=[1, 2])  # non-dict config
    with pytest.raises(ValueError):
        runtrack.start_run(conn, "ok", status="finished")  # not a start status


def test_finish_run_sets_terminal_state():
    conn = _mem()
    runtrack.start_run(conn, "r", ts=1.0)
    done = runtrack.finish_run(conn, 1, status="finished", ts=9.0)
    assert done["status"] == "finished" and done["finished_ts"] == 9.0
    assert runtrack.finish_run(conn, 999, status="failed") is None  # no such run
    with pytest.raises(ValueError):
        runtrack.finish_run(conn, 1, status="running")  # not a terminal status


def test_list_runs_filters():
    conn = _mem()
    runtrack.start_run(conn, "a", ts=1.0)
    runtrack.start_run(conn, "b", ts=2.0)
    runtrack.finish_run(conn, 2, status="failed", ts=3.0)
    assert [r["name"] for r in runtrack.list_runs(conn)] == ["b", "a"]  # newest first
    assert [r["id"] for r in runtrack.list_runs(conn, status="failed")] == [2]
    assert [r["id"] for r in runtrack.list_runs(conn, name="a")] == [1]


# ---- metrics ----------------------------------------------------------------


def test_log_metrics_autostep_and_history_order():
    conn = _mem()
    runtrack.start_run(conn, "r", ts=1.0)
    r1 = runtrack.log_metrics(conn, 1, {"loss": 0.9, "acc": 0.5}, ts=2.0)
    assert r1["step"] == 0 and r1["logged"] == 2 and r1["keys"] == ["acc", "loss"]
    assert runtrack.log_metrics(conn, 1, {"loss": 0.7}, ts=3.0)["step"] == 1
    assert runtrack.log_metrics(conn, 1, {"loss": 0.5}, ts=4.0)["step"] == 2
    # explicit step is honored, not auto-incremented
    assert runtrack.log_metrics(conn, 1, {"loss": 0.4}, step=100, ts=5.0)["step"] == 100
    hist = runtrack.run_history(conn, 1, key="loss")
    assert [h["step"] for h in hist] == [0, 1, 2, 100]  # ascending, plot-ready
    assert [h["value"] for h in hist] == [0.9, 0.7, 0.5, 0.4]
    # a limit returns the most-recent points, still ascending
    tail = runtrack.run_history(conn, 1, key="loss", limit=2)
    assert [h["step"] for h in tail] == [2, 100]


def test_log_metrics_validation_is_all_or_nothing():
    conn = _mem()
    runtrack.start_run(conn, "r", ts=1.0)
    with pytest.raises(ValueError):
        runtrack.log_metrics(conn, 999, {"loss": 0.1})  # unknown run
    with pytest.raises(ValueError):
        runtrack.log_metrics(conn, 1, {})  # empty
    for bad in ({"loss": "high"}, {"loss": True}, {"loss": float("nan")},
                {"loss": float("inf")}):
        with pytest.raises(ValueError):
            runtrack.log_metrics(conn, 1, bad)
    # a call that raised on a bad value wrote nothing (validate before insert)
    with pytest.raises(ValueError):
        runtrack.log_metrics(conn, 1, {"good": 1.0, "bad": "x"})
    assert runtrack.run_history(conn, 1) == []


def test_run_summary_first_last_min_max():
    conn = _mem()
    runtrack.start_run(conn, "r", ts=1.0)
    for step, loss in enumerate([0.9, 0.4, 0.6, 0.3]):
        runtrack.log_metrics(conn, 1, {"loss": loss}, step=step, ts=float(step))
    s = runtrack.run_summary(conn, 1)["loss"]
    assert s["count"] == 4 and s["first"] == 0.9 and s["last"] == 0.3
    assert s["min"] == 0.3 and s["max"] == 0.9 and s["last_step"] == 3


# ---- comparison -------------------------------------------------------------


def test_compare_runs_deltas_and_missing_metric():
    conn = _mem()
    runtrack.start_run(conn, "base", ts=1.0)
    runtrack.start_run(conn, "cand", ts=2.0)
    runtrack.log_metrics(conn, 1, {"loss": 0.50, "acc": 0.80}, step=0, ts=1.0)
    runtrack.log_metrics(conn, 1, {"loss": 0.40}, step=1, ts=2.0)
    runtrack.log_metrics(conn, 2, {"loss": 0.30}, step=0, ts=3.0)  # no 'acc' logged
    cmp = runtrack.compare_runs(conn, [1, 2], metric="min")
    assert cmp["baseline"] == 1
    loss = cmp["keys"]["loss"]
    assert loss["last"] == {1: 0.40, 2: 0.30}
    assert loss["min"] == {1: 0.40, 2: 0.30}
    assert loss["baseline_last"] == 0.40
    assert loss["delta_last"] == {1: 0.0, 2: pytest.approx(-0.10)}
    assert loss["chosen"] == {1: 0.40, 2: 0.30}  # metric=min picked
    # a run that never logged 'acc' shows None, not a crash or a zero
    acc = cmp["keys"]["acc"]
    assert acc["last"] == {1: 0.80, 2: None}
    assert acc["delta_last"] == {1: 0.0, 2: None}


def test_compare_runs_rejects_bad_args():
    conn = _mem()
    runtrack.start_run(conn, "r", ts=1.0)
    with pytest.raises(ValueError):
        runtrack.compare_runs(conn, [])  # empty
    with pytest.raises(ValueError):
        runtrack.compare_runs(conn, [1], metric="median")  # unknown metric
    with pytest.raises(ValueError):
        runtrack.compare_runs(conn, [1, 999])  # missing run


# ---- family schema + detection ----------------------------------------------


def test_to_diagnostics_maps_failed_runs_to_warnings():
    conn = _mem()
    runtrack.start_run(conn, "ok-run", ts=1.0)
    runtrack.start_run(conn, "boom", ts=2.0)
    runtrack.finish_run(conn, 1, status="finished", ts=3.0)
    runtrack.finish_run(conn, 2, status="failed", ts=4.0)
    diags = runtrack.to_diagnostics(runtrack.list_runs(conn))
    assert len(diags) == 1  # only the failed run emits
    assert diags[0]["rule"] == "runtrack:failed"
    assert diags[0]["severity"] == "warning"
    assert "boom" in diags[0]["message"]
    assert openswap.summarize(diags)["by_severity"]["warning"] == 1


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.runtrack import cli as runtrack_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = runtrack_cli._capability()
    assert cap["adapter"] == "runtrack"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "mlflow"
    assert cap["extras"]["wandb"]["found"] is False  # SaaS client, never executed


# ---- adversarial ------------------------------------------------------------


def test_unicode_names_and_negative_steps_survive():
    conn = _mem()
    runtrack.start_run(conn, "実験-α", config={"note": "ünïcode ✓"}, ts=1.0)
    runtrack.log_metrics(conn, 1, {"loss": 1.0}, step=-5, ts=1.0)
    runtrack.log_metrics(conn, 1, {"loss": 0.5}, step=0, ts=2.0)
    hist = runtrack.run_history(conn, 1, key="loss")
    assert [h["step"] for h in hist] == [-5, 0]  # negative step sorts first
    assert runtrack.get_run(conn, 1)["name"] == "実験-α"


# ---- the real CLI in a subprocess (fully offline — no network surface) -------


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


def test_cli_runtrack_hello_envelope():
    r = _cli(["runtrack", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_runtrack_start_log_finish_compare_loop(tmp_path):
    db = str(tmp_path / "rt.db")
    r = _cli(["runtrack", "start", "trainer", "--config", '{"lr": 0.0003}', "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["run"]["id"] == 1
    for loss, acc in (("0.5", "0.7"), ("0.3", "0.9")):
        r = _cli(["runtrack", "log", "1", "--metric", f"loss={loss}",
                  "--metric", f"acc={acc}", "--db", db])
        assert r.returncode == 0, r.stderr + r.stdout
    r = _cli(["runtrack", "finish", "1", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["run"]["status"] == "finished"
    # a second, failed run
    r = _cli(["runtrack", "start", "trainer-b", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    _cli(["runtrack", "log", "2", "--metrics", '{"loss": 0.4}', "--db", db])
    r = _cli(["runtrack", "finish", "2", "--status", "failed", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    # show run 1: summary reflects the two logged steps
    r = _cli(["runtrack", "show", "1", "--db", db])
    data = json.loads(r.stdout)["data"]
    assert data["summary"]["loss"]["last"] == 0.3 and data["summary"]["loss"]["min"] == 0.3
    # compare the two runs
    r = _cli(["runtrack", "compare", "1", "2", "--metric", "min", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    keys = json.loads(r.stdout)["data"]["keys"]
    assert keys["loss"]["last"]["1"] == 0.3 and keys["loss"]["last"]["2"] == 0.4
    # list gates on the failed run
    r = _cli(["runtrack", "list", "--db", db])
    assert len(json.loads(r.stdout)["data"]["runs"]) == 2
    r = _cli(["runtrack", "list", "--db", db, "--fail-on", "warning"])
    assert r.returncode == 1  # run 2 failed -> the CI gate fires


def test_cli_runtrack_list_without_store_fails_actionably(tmp_path):
    r = _cli(["runtrack", "list", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no run store" in data["error"]
    assert "example" in data
