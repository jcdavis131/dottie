"""`scout loop` — the dottie-loop contracts behind the single tool surface.

Every write lands under the plugin's ONE declared root (which conftest.py has
already redirected under a throwaway HOME), gated by enforce_or_raise before the
directory exists. Blocked states come back as exit code 2 with the typed error,
never as a mock success.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bigbang.core import output
from bigbang.plugins.loop import cli as loop_cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _json_mode():
    output.set_json_mode(True)
    yield
    output.set_json_mode(False)


def _invoke(*args: str):
    res = runner.invoke(loop_cli.app, list(args))
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    payload = json.loads("\n".join(lines)) if lines else {}
    return res.exit_code, payload


def test_store_root_is_under_home_and_gated():
    assert Path.home() in loop_cli.STORE_ROOT.parents
    assert loop_cli.STORE_ROOT == Path.home() / ".local" / "share" / "dottie" / "loop"
    assert loop_cli._store("goals").is_dir()


def test_status_reports_no_capability_claim():
    code, payload = _invoke("status")
    assert code == 0 and payload["ok"] and payload["data"]["capability_claim"] == "none"


def test_goal_submit_is_idempotent_and_only_received():
    code, a = _invoke("goal", "--intent", "summarize the README", "--key", "t-1")
    code2, b = _invoke("goal", "--intent", "summarize the README", "--key", "t-1")
    assert code == 0 and code2 == 0
    assert a["data"]["status"] == "received" and a["data"]["created"] is True
    assert b["data"]["goal_id"] == a["data"]["goal_id"] and b["data"]["replay"] is True
    assert (loop_cli.STORE_ROOT / "goals" / "goals.jsonl").read_text().count("\n") == 1


def test_run_executes_one_goal_end_to_end(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hello")
    spec = tmp_path / "run.json"
    spec.write_text(json.dumps({"intent_text": "check the file", "idempotency_key": "run-1", "steps": [{"id": "f", "kind": "file", "path": "hello.txt", "expect_substring": "hello"}]}))
    code, payload = _invoke("run", "--spec", str(spec), "--root", str(tmp_path))
    assert code == 0 and payload["data"]["status"] == "completed" and len(payload["data"]["checkpoints"]) == 1
    assert payload["data"]["trace_id"] is None  # capture off by default
    code, payload = _invoke("run", "--spec", str(tmp_path / "missing.json"), "--root", str(tmp_path))
    assert code == 1 and "spec not found" in payload["error"]


def test_feedback_binds_to_a_captured_run(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hello")
    spec = tmp_path / "run.json"
    spec.write_text(json.dumps({"intent_text": "check the file for feedback", "idempotency_key": "run-fb", "capture": True, "steps": [{"id": "f", "kind": "file", "path": "hello.txt", "expect_substring": "hello"}]}))
    code, payload = _invoke("run", "--spec", str(spec), "--root", str(tmp_path), "--capture")
    assert code == 0 and payload["data"]["trace_id"]
    code, fb = _invoke("feedback", "--run-id", payload["data"]["run_id"], "--signal", "accept")
    assert code == 0 and fb["data"]["feedback"]["surface"] == "cli" and fb["data"]["reward"]["components"]["accept"] == 1.0
    code, bad = _invoke("feedback", "--run-id", payload["data"]["run_id"], "--signal", "love_it")
    assert code == 3 and bad["error"]["code"] == "invalid_input"
    code, missing = _invoke("feedback", "--run-id", "run_nope", "--signal", "accept")
    assert code == 3 and "no trace" in missing["error"]["message"]


def test_evaluate_blocked_on_stale_metrics_exits_2(tmp_path: Path):
    stale = (datetime.now(UTC) - timedelta(days=21)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    src = tmp_path / "m.json"
    src.write_text(json.dumps({k: {"value": v, "event_time": stale, "provenance": "measured", "version": "v1"} for k, v in {"verifier": 7.0, "agent_ok": 0.8, "eval": 0.7, "traces": 600}.items()}))
    code, payload = _invoke("evaluate", "--sources", str(src), "--promote")
    assert code == 2 and payload["ok"] is False and payload["status"] == "blocked" and "stale" in payload["error"]["message"]
    assert (loop_cli.STORE_ROOT / "decisions" / "decisions.jsonl").exists()  # LoopDecision emitted even when blocked


def test_forge_runners_blocked_until_registered_and_bench_reconciles():
    code, payload = _invoke("forge-runners")
    assert code == 2 and payload["error"]["details"]["dependency"] == "forge_runner"
    code, payload = _invoke("bench")
    assert code == 0 and payload["data"]["accounting_ok"] and payload["data"]["capability_claim"] == "none"
