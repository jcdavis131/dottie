"""
Tests for `scout harness run` — the end-to-end run loop (route -> plan ->
deterministic executors -> checkpoint/timeline -> critic).

Pattern borrowed from tests/test_harness_timeline.py:

- Session-wide HOME isolation via conftest.py (throwaway HOME, set at import
  time) is already active and inherited by subprocesses.
- An autouse per-test HOME keeps timeline events from one test out of the next
  test's mined stats — env vars are inherited by CLI subprocesses and
  Path.home() re-reads HOME on every call.
- subprocess `python -m bigbang.cli --json ...` exercises real CLI discovery;
  stats run in a separate subprocess so the timeline module cache is cold and
  the on-disk store is the source of truth.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Per-test HOME so each test sees a fresh checkpoint store and runs dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _run_cli(*args, env: dict | None = None) -> dict:
    """Run `python -m bigbang.cli <args>` and return parsed JSON (envelope or raw)."""
    cmd = [sys.executable, "-m", "bigbang.cli", *args]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        env=env,
    )
    assert r.returncode == 0, f"cli failed {' '.join(cmd)} exit {r.returncode} stderr {r.stderr} stdout {r.stdout[:2000]}"
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout not json for {' '.join(cmd)}: {e} stdout={r.stdout[:2000]}")
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict) else payload
    return {"raw": payload, "data": data, "stdout": r.stdout}


def _run_goal(goal: str, *extra, env: dict | None = None) -> dict:
    return _run_cli("--json", "harness", "run", goal, *extra, env=env)["data"]


_EPIC_GOAL = "ship the harness end-to-end loop"

_TIMELINE_ROW_FIELDS = [
    "nodeId", "agentId", "attempt",
    "latency", "latency_ms", "tokens", "tokens_est",
    "status", "errorClass",
]


def _read_jsonl(path: Path) -> list:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_run_happy_path_epic_dag():
    d = _run_goal(_EPIC_GOAL)
    assert d.get("ok") is True, d
    assert d["tier"] == "agentic_epic"
    assert d["n_nodes"] == 5
    assert d["ok_nodes"] == 5
    assert d["failed_nodes"] == 0
    assert d["passed"] is True
    assert d["critic_score"] == 10.0

    cp_path = Path(d["checkpoint_path"])
    assert cp_path.exists(), d
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    for field in ["runId", "dag_version", "nodes", "created", "saved_at", "version", "provenance"]:
        assert field in cp, f"checkpoint missing {field}: {sorted(cp)}"
    assert len(cp["nodes"]) == 5

    tl_path = Path(d["timeline_path"])
    assert tl_path.exists(), d
    rows = _read_jsonl(tl_path)
    assert rows, "timeline empty"
    for row in rows:
        for field in _TIMELINE_ROW_FIELDS:
            assert field in row, f"timeline row missing {field}: {row}"
        assert row["latency_ms"] >= 0


def test_run_self_contained_under_home():
    d = _run_goal(_EPIC_GOAL)
    expected = str(Path.home() / "workspace" / "bundles" / "ultra" / "runs")
    assert d["checkpoint_path"].startswith(expected), (d["checkpoint_path"], expected)


def test_run_feeds_timeline_stats_mining():
    d = _run_goal(_EPIC_GOAL)
    executed_roles = {n["role"] for n in d["nodes"]}
    # Separate subprocess = cold module cache; the on-disk default-base store is
    # the source of truth for mining.
    stats = _run_cli("--json", "harness", "timeline", "stats")["data"]
    assert stats.get("events", 0) > 0, stats
    per_role = stats.get("per_role", {})
    for role in executed_roles:
        assert role in per_role, (role, sorted(per_role))


def test_run_max_nodes_truncates_plan():
    d = _run_goal(_EPIC_GOAL, "--max-nodes", "2")
    assert d["n_nodes"] == 2
    cp = json.loads(Path(d["checkpoint_path"]).read_text(encoding="utf-8"))
    assert len(cp["nodes"]) == 2


def test_run_deterministic_across_runs():
    d1 = _run_goal(_EPIC_GOAL, "--seed", "7", "--run-id", "det-run-a")
    d2 = _run_goal(_EPIC_GOAL, "--seed", "7", "--run-id", "det-run-b")
    def key(n):
        return (n["id"], n["role"], n["status"], n["artifact_chars"])
    assert [key(n) for n in d1["nodes"]] == [key(n) for n in d2["nodes"]]


def test_recovery_ladder_retries_read_node_once():
    env = {**os.environ, "SCOUT_RUN_FAIL_NODES": "intent-decompose"}
    d = _run_goal(_EPIC_GOAL, env=env)
    node = next(n for n in d["nodes"] if n["id"] == "intent-decompose")
    assert node["attempts"] == 2, node          # retry1 fired for READ side effect
    assert node["status"] == "failed", node
    assert node["errorClass"] == "TOOL_FAILURE", node
    # run continues past the failed node
    remaining = [n for n in d["nodes"] if n["id"] != "intent-decompose"]
    assert remaining and all(n["status"] == "ok" for n in remaining), d["nodes"]
    rows = _read_jsonl(Path(d["timeline_path"]))
    assert sum(1 for r in rows if r["nodeId"] == "intent-decompose") == 2, rows


def test_recovery_ladder_never_retries_destructive_node():
    env = {**os.environ, "SCOUT_RUN_FAIL_NODES": "build"}
    d = _run_goal(_EPIC_GOAL, env=env)
    node = next(n for n in d["nodes"] if n["id"] == "build")
    assert node["attempts"] == 1, node          # WRITE_DESTRUCTIVE: no auto-retry
    assert node["status"] == "failed", node
    assert node["recovery_action"] == "escalate", node


def test_route_regression_unchanged():
    """Guard that route output was not touched by the run-command wiring."""
    d = _run_cli("--json", "harness", "route", "compare Stripe vs Lemon Squeezy Aug 2026")["data"]
    sg = d.get("stickiness_guard")
    assert sg is not None and sg.get("passed") is True
    assert "G_history" in d.get("graph_memory", {})
