"""
Tests for the harness MCP action executor (mcp_executor.py + runner wiring).

Pattern borrowed from tests/test_harness_runner.py:

- Session-wide HOME isolation via conftest.py is active; an autouse per-test
  HOME keeps stores (default-base timeline, runs dir) fresh per test.
- Unit tests monkeypatch meta / policy / mcp_client at their module refs —
  mcp_executor resolves them at call time, so no network is ever needed.
- Runner-level tests call run_goal in-process (monkeypatch cannot cross a
  subprocess boundary); the no-namespace CLI guard is exercised through a real
  CLI subprocess because that guard lives in the command body.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import mcp_client, policy
from bigbang.plugins.harness import mcp_executor, runner
from bigbang.plugins.mcp import meta


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Per-test HOME so each test sees a fresh checkpoint store and runs dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _read_jsonl(path: Path) -> list:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --- parse_mcp_goal -------------------------------------------------------------


def test_parse_non_mcp_goal_returns_none():
    assert mcp_executor.parse_mcp_goal("ship the harness end-to-end loop") is None


def test_parse_valid_goal_no_args():
    p = mcp_executor.parse_mcp_goal("mcp:srv__echo")
    assert p == {"ok": True, "server": "srv", "tool": "echo", "args": {}}


def test_parse_valid_goal_with_json_args():
    p = mcp_executor.parse_mcp_goal('mcp:srv__echo {"a": 1, "b": "x"}')
    assert p["ok"] is True
    assert (p["server"], p["tool"]) == ("srv", "echo")
    assert p["args"] == {"a": 1, "b": "x"}


def test_parse_tool_name_keeps_downstream_separators():
    # split on FIRST __ only — downstream tool names may contain __
    p = mcp_executor.parse_mcp_goal("mcp:srv__ns__tool")
    assert p["ok"] is True
    assert (p["server"], p["tool"]) == ("srv", "ns__tool")


@pytest.mark.parametrize("goal", [
    "mcp:",                       # empty
    "mcp:unqualified",            # no separator
    "mcp:__tool",                 # empty server
    "mcp:srv__",                  # empty tool
    "mcp:srv__echo not-json",     # unparseable args
    'mcp:srv__echo [1, 2]',       # args not a JSON object
])
def test_parse_malformed_goals_return_error_marker(goal):
    p = mcp_executor.parse_mcp_goal(goal)
    assert p is not None and p.get("ok") is False and p.get("error"), (goal, p)


# --- execute_mcp_action ---------------------------------------------------------


@pytest.fixture
def _wire(monkeypatch):
    """Registered server srv in namespace ns; records any network attempt."""
    calls: list = []
    monkeypatch.setattr(meta, "load_namespaces",
                        lambda: {"ns": {"servers": ["srv"], "disabled_tools": []}})
    monkeypatch.setattr(meta, "load_servers",
                        lambda: {"srv": {"url": "http://127.0.0.1:9/mcp"}})
    monkeypatch.setattr(policy, "check_user_url", lambda url: (True, "ok"))

    def _call(url, tool, args=None):
        calls.append((url, tool, args))
        return {"echoed": args}

    monkeypatch.setattr(mcp_client, "call_mcp_tool_sync", _call)
    return calls


def _assert_measured(res):
    assert res["latency_ms"] >= 0
    assert res["tokens_est"] == 0


def test_execute_success(_wire):
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {"a": 1})
    assert res["status"] == "ok"
    assert res["error_class"] is None
    assert res["payload"] == {"echoed": {"a": 1}}
    _assert_measured(res)
    assert _wire == [("http://127.0.0.1:9/mcp", "echo", {"a": 1})]


def test_execute_policy_denied_never_touches_network(_wire, monkeypatch):
    monkeypatch.setattr(policy, "check_user_url", lambda url: (False, "host denied"))
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {})
    assert res["status"] == "error"
    assert res["error_class"] == "policy_denied"
    assert "denied" in res["error"]
    _assert_measured(res)
    assert _wire == [], "policy-denied call reached the network"


def test_execute_disabled_tool_never_touches_network(_wire, monkeypatch):
    monkeypatch.setattr(meta, "load_namespaces",
                        lambda: {"ns": {"servers": ["srv"], "disabled_tools": ["srv__echo"]}})
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "disabled_tool")
    _assert_measured(res)
    assert _wire == [], "disabled tool reached the network"


def test_execute_unreachable(_wire, monkeypatch):
    def _boom(url, tool, args=None):
        raise ConnectionError("no route to host")

    monkeypatch.setattr(mcp_client, "call_mcp_tool_sync", _boom)
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "unreachable")
    assert "no route" in res["error"]
    _assert_measured(res)


def test_execute_downstream_error(_wire, monkeypatch):
    def _boom(url, tool, args=None):
        raise ValueError("tool exploded")

    monkeypatch.setattr(mcp_client, "call_mcp_tool_sync", _boom)
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "downstream_error")


def test_execute_downstream_iserror_is_a_failure(_wire, monkeypatch):
    # MCP reports tool-level failure in-band: transport succeeds, isError set.
    monkeypatch.setattr(
        mcp_client,
        "call_mcp_tool_sync",
        lambda url, tool, args=None: {"isError": True, "content": [{"text": "Unknown tool"}]},
    )
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "downstream_error")
    assert "isError" in res["error"]


def test_execute_namespace_missing(_wire):
    res = mcp_executor.execute_mcp_action("other-ns", "srv", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "namespace_missing")
    assert _wire == []


def test_execute_unknown_server(_wire):
    res = mcp_executor.execute_mcp_action("ns", "ghost", "echo", {})
    assert (res["status"], res["error_class"]) == ("error", "unknown_server")
    assert _wire == []


def test_execute_bad_args(_wire):
    res = mcp_executor.execute_mcp_action("ns", "srv", "echo", ["not", "a", "dict"])  # type: ignore[arg-type]
    assert (res["status"], res["error_class"]) == ("error", "bad_args")
    assert _wire == []


# --- runner wiring --------------------------------------------------------------


def test_runner_mcp_failure_flows_through_recovery_ladder(_wire, tmp_path, monkeypatch):
    def _boom(url, tool, args=None):
        raise ConnectionError("downstream down")

    monkeypatch.setattr(mcp_client, "call_mcp_tool_sync", _boom)
    d = runner.run_goal("mcp:srv__echo", mcp_namespace="ns",
                        runs_dir=tmp_path / "runs", run_id="mcp-fail")
    assert d["ok"] is True  # the RUN completed; the node failed
    assert d["tier"] == "action_operator"
    assert d["n_nodes"] == 1 and d["failed_nodes"] == 1
    node = d["nodes"][0]
    assert node["id"] == "mcp-call"
    assert node["status"] == "failed"
    assert node["attempts"] == 1          # EXTERNAL_NOTIFY: never auto-retried
    assert node["errorClass"] == "TOOL_FAILURE"
    assert node["recovery_action"] == "escalate"
    assert node["artifact_chars"] == 0
    rows = _read_jsonl(Path(d["timeline_path"]))
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["nodeId"] == "mcp-call"
    assert row["attempt"] == 1
    assert row["status"] == "fail"
    assert row["errorClass"] == "TOOL_FAILURE"
    assert row["latency_ms"] >= 0 and row["tokens_est"] == 0


def test_runner_mcp_success_checkpoint_provenance(_wire, tmp_path):
    d = runner.run_goal('mcp:srv__echo {"q": "ping"}', mcp_namespace="ns",
                        runs_dir=tmp_path / "runs", run_id="mcp-ok")
    assert d["ok"] is True
    assert d["intent"] == "complex_action"
    assert d["tier"] == "action_operator"
    assert d["ok_nodes"] == 1 and d["failed_nodes"] == 0
    node = d["nodes"][0]
    assert node["status"] == "ok" and node["attempts"] == 1
    assert node["errorClass"] is None
    assert node["artifact_chars"] > 0
    # downstream actually got the parsed args
    assert _wire == [("http://127.0.0.1:9/mcp", "echo", {"q": "ping"})]

    cp = json.loads(Path(d["checkpoint_path"]).read_text(encoding="utf-8"))
    prov = cp["provenance"]
    assert prov["tier"] == "action_operator"
    assert prov["intent"] == "complex_action"
    assert prov["goal"] == 'mcp:srv__echo {"q": "ping"}'
    assert prov["complexity"] == d["complexity"]

    rows = _read_jsonl(Path(d["timeline_path"]))
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok" and row["errorClass"] is None
    assert row["latency_ms"] >= 0
    assert row["tokens"] == 0 and row["tokens_est"] == 0


def test_runner_malformed_mcp_goal_writes_no_stores(tmp_path):
    d = runner.run_goal("mcp:unqualified", mcp_namespace="ns",
                        runs_dir=tmp_path / "runs", run_id="mcp-bad")
    assert d["ok"] is False and "qualified" in d["error"]
    assert not (tmp_path / "runs").exists()
    assert not (Path.home() / ".cache" / "scout" / "checkpoints").exists()


def test_runner_mcp_goal_without_namespace_errors_before_stores(tmp_path):
    d = runner.run_goal("mcp:srv__echo", runs_dir=tmp_path / "runs", run_id="mcp-nons")
    assert d["ok"] is False and "mcp-namespace" in d["error"]
    assert not (tmp_path / "runs").exists()


def test_cli_mcp_goal_without_namespace_fails_before_stores():
    cmd = [sys.executable, "-m", "bigbang.cli", "--json", "harness", "run", "mcp:srv__echo"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=12)
    assert r.returncode == 0, (r.stderr, r.stdout)
    payload = json.loads(r.stdout)
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    assert data.get("ok") is False
    assert "--mcp-namespace" in data.get("error", "")
    # clear error BEFORE any store write
    assert not (Path.home() / "workspace" / "bundles" / "ultra" / "runs").exists()
    assert not (Path.home() / ".cache" / "scout" / "checkpoints").exists()
