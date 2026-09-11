"""CLI contract (spec §06 CLI row): stable exit codes, JSON-only stdout, dry-run."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dottie_loop.cli import EXIT_BLOCKED, EXIT_INVALID, EXIT_OK, main


def _run(capsys, *argv):
    rc = main(list(argv))
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, out  # JSON mode never mixes prose into stdout
    return rc, json.loads(lines[0])


def test_spec_status_and_capture_default(capsys):
    rc, env = _run(capsys, "spec", "status")
    assert rc == EXIT_OK and env["ok"] and env["data"]["capability_claim"] == "none"
    rc, env = _run(capsys, "capture", "status")
    assert env["data"]["enabled"] is False and env["data"]["default"] == "off"


def test_goal_submit_status_and_invalid(capsys, tmp_path):
    payload = json.dumps({"idempotency_key": "k1", "intent_text": "summarize"})
    rc, env = _run(capsys, "goal", "submit", "--store", str(tmp_path), "--subject", "u", "--json", payload)
    assert rc == EXIT_OK and env["data"]["status"] == "received" and env["data"]["created"]
    rc, env2 = _run(capsys, "goal", "status", "--store", str(tmp_path), "--goal-id", env["data"]["goal_id"])
    assert rc == EXIT_OK and env2["data"]["status"] == "received"
    rc, env3 = _run(capsys, "goal", "submit", "--store", str(tmp_path), "--subject", "u", "--json", json.dumps({"idempotency_key": "k2"}))
    assert rc == EXIT_INVALID and env3["ok"] is False and env3["error"]["field"] == "intent_text"


def test_loop_evaluate_blocked_exit_code(capsys, tmp_path):
    stale = (datetime.now(UTC) - timedelta(days=21)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    src = {k: {"value": v, "event_time": stale, "provenance": "measured", "version": "v1"} for k, v in {"verifier": 7.0, "agent_ok": 0.8, "eval": 0.7, "traces": 600}.items()}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(src))
    rc, env = _run(capsys, "loop", "evaluate", "--sources", str(p), "--promote", "--out", str(tmp_path / "d.jsonl"))
    assert rc == EXIT_BLOCKED and env["status"] == "blocked" and "stale" in env["error"]["message"]
    assert (tmp_path / "d.jsonl").exists()


def test_forge_runners_blocked_and_submit_dry_run(capsys, tmp_path):
    rc, env = _run(capsys, "forge", "runners", "--root", str(tmp_path / "f"))
    assert rc == EXIT_BLOCKED and env["error"]["details"]["dependency"] == "forge_runner"
    spec = {"repo": "jcdavis131/dottie", "ref": "abc1234", "argv": ["python3", "-c", "pass"], "cwd": ".", "requirements": {"cuda": True, "vram_gb": 6, "torch": True}, "inputs": [], "outputs": [], "timeout_seconds": 10, "submitted_by": "t"}
    sp = tmp_path / "job.json"
    sp.write_text(json.dumps(spec))
    rc, env = _run(capsys, "forge", "submit", "--root", str(tmp_path / "f"), "--file", str(sp), "--allow", "jcdavis131/dottie", "--dry-run")
    assert rc == EXIT_OK and env["data"]["dry_run"] and not list((tmp_path / "f" / "jobs" / "pending").glob("*.json"))
    rc, env = _run(capsys, "forge", "submit", "--root", str(tmp_path / "f"), "--file", str(sp), "--allow", "jcdavis131/dottie")
    assert rc == EXIT_OK and env["data"]["status"] == "accepted" and "not executed" in env["data"]["note"]


def test_bench_smoke_and_reward_via_module_entry(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "dottie_loop", "bench", "smoke"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], check=False)
    assert proc.returncode == 0
    rep = json.loads(proc.stdout)["data"]
    assert rep["accounting_ok"] and rep["workflows"]["ok"] == 2 and rep["capability_claim"] == "none"
    inp = tmp_path / "r.json"
    inp.write_text(json.dumps({"trace_id": "t", "task_ok": True, "feedback": "accept"}))
    proc = subprocess.run([sys.executable, "-m", "dottie_loop", "reward", "compute", "--file", str(inp)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0 and json.loads(proc.stdout)["data"]["total"] == 1.25
