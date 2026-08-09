"""
Tests for the harness timeline store — append-only timeline.jsonl + offset index
feeding graph-plan's mined failureRisk.

Pattern borrowed from tests/test_harness_vector.py:

- HOME isolation via conftest.py (throwaway HOME) already active, inherited by
  subprocesses — everything written under Path.home() here is isolated.
- subprocess `python -m bigbang.cli --json ...` to exercise real CLI discovery.
- stats and graph-plan run in separate subprocesses, so the module cache is cold
  each time — the store on disk is the source of truth; that is the point.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import time
from pathlib import Path

import pytest


# The pinned wrapper test (test_harness_vector.test_cli_sh_wrapper_single_source)
# expects the single-source shim documented in docs/HARNESS_POLISH_2026-08-05.md at
# ~/workspace/bundles/cli.sh. The conftest throwaway HOME starts empty, so materialize
# the shim there at import time (this module is collected before test_harness_vector).
_WRAPPER = Path.home() / "workspace" / "bundles" / "cli.sh"
if not _WRAPPER.exists():
    _WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    _WRAPPER.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nexec python3 -m bigbang.cli \"$@\"\n",
        encoding="utf-8",
    )
    _WRAPPER.chmod(0o755)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Per-test HOME so each test sees a fresh checkpoint store.

    conftest.py's redirect is session-wide, so timeline events appended by one test
    would otherwise leak into the next test's mined stats. Env vars are inherited by
    the CLI subprocesses, and Path.home() re-reads HOME on every call.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _run_cli(*args) -> dict:
    """Run `python -m bigbang.cli <args>` and return parsed JSON (envelope or raw)."""
    cmd = [sys.executable, "-m", "bigbang.cli", *args]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
    )
    assert r.returncode == 0, f"cli failed {' '.join(cmd)} exit {r.returncode} stderr {r.stderr} stdout {r.stdout[:2000]}"
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout not json for {' '.join(cmd)}: {e} stdout={r.stdout[:2000]}")
    # tennis-style: payload.get("data") or payload
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict) else payload
    # envelope also may have ok at top level; preserve both for assertions
    return {"raw": payload, "data": data, "stdout": r.stdout}


def _append(run_id: str, agent_id: str, node_id: str = "n1", status: str = "ok", error_class: str = "none") -> dict:
    return _run_cli(
        "--json", "harness", "timeline", "append",
        "--run-id", run_id, "--agent-id", agent_id, "--node-id", node_id,
        "--status", status, "--error-class", error_class,
    )


def _checkpoint_base() -> Path:
    return Path.home() / ".cache" / "scout" / "checkpoints"


def test_timeline_append_creates_store_and_index():
    for run_id, agent in [("run-a", "builder"), ("run-a", "executor"), ("run-a2", "builder")]:
        out = _append(run_id, agent)
        assert out["data"].get("ok") is True, out["data"]
    tl = _checkpoint_base() / "run-a" / "timeline.jsonl"
    idx = _checkpoint_base() / "run-a" / "timeline.idx.jsonl"
    assert tl.exists()
    assert idx.exists()
    tl_lines = [l for l in tl.read_text(encoding="utf-8").splitlines() if l.strip()]
    idx_lines = [l for l in idx.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(tl_lines) == len(idx_lines) == 2


def test_timeline_stats_fail_rate():
    _append("run-b", "builder", status="ok")
    _append("run-b", "builder", status="fail", error_class="ToolError")
    out = _run_cli("--json", "harness", "timeline", "stats")
    d = out["data"]
    builder = d.get("per_role", {}).get("builder")
    assert builder is not None, d
    assert builder["runs"] == 2
    assert builder["fail_rate"] == 0.5
    assert "ToolError" in builder.get("error_classes", {})
    assert d.get("per_run", {}).get("run-b", {}).get("failures") == 1


def test_graph_plan_uses_mined_history():
    _append("run-c", "builder", status="ok")
    _append("run-c", "builder", status="fail", error_class="ToolError")
    out = _run_cli("--json", "harness", "graph-plan", "ship Dottie SOTA")
    d = out["data"]
    steps = d.get("steps", [])
    builder_steps = [s for s in steps if s.get("role") == "builder"]
    assert builder_steps, f"no builder step in {steps}"
    assert builder_steps[0]["failureRisk"] == 0.5, builder_steps[0]
    g_history = d.get("graph_memory", {}).get("G_history", "")
    assert "no timeline.jsonl parsed" not in g_history, g_history
    assert "mined" in g_history


def test_checkpoint_list_newest_first():
    _append("run-old", "operator")
    _append("run-new", "operator")
    old_dir = _checkpoint_base() / "run-old"
    past = time.time() - 3600
    os.utime(old_dir, (past, past))
    out = _run_cli("--json", "harness", "checkpoint", "list")
    d = out["data"]
    cps = d.get("checkpoints", [])
    assert "run-old" in cps and "run-new" in cps, cps
    assert cps.index("run-new") < cps.index("run-old"), cps
    assert cps[0] != "run-old"


def test_append_missing_run_id_rejected():
    out = _run_cli("--json", "harness", "timeline", "append", "--agent-id", "x")
    d = out["data"]
    assert d.get("ok") is False
    assert "run-id" in d.get("error", "")


def test_append_event_missing_field_rejected_inprocess():
    from bigbang.plugins.harness.timeline import append_event
    res = append_event("run-x", {"nodeId": "n1", "agentId": "a", "attempt": 1, "latency": 1.0, "status": "ok", "errorClass": "none"})
    assert res["ok"] is False
    assert "tokens" in res["error"]


def test_route_regression_unchanged():
    """Guard that route output was not touched by the timeline wiring."""
    out = _run_cli("--json", "harness", "route", "compare Stripe vs Lemon Squeezy Aug 2026")
    d = out["data"]
    sg = d.get("stickiness_guard")
    assert sg is not None and sg.get("passed") is True
    assert "G_history" in d.get("graph_memory", {})
