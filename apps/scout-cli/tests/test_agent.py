"""Tests for agent run --execute, teach, and bus (findings #5/#6)."""

import importlib
import json
import sys

from bigbang.core import audit
from bigbang.plugins.agent import cli as agent_cli


class TestPolicyCheckStep:
    def test_valid_step(self):
        ok, reason, argv = agent_cli._policy_check_step("bb tools list")
        assert ok, reason
        assert argv[-3:] == ["--json", "tools", "list"]

    def test_shell_metacharacters_denied(self):
        ok, reason, _ = agent_cli._policy_check_step("bb tools list; rm -rf /")
        assert not ok
        assert "metacharacters" in reason

    def test_unknown_plugin_denied(self):
        ok, _reason, _ = agent_cli._policy_check_step("bb notaplugin go")
        assert not ok

    def test_non_bb_prefix_denied(self):
        ok, _, _ = agent_cli._policy_check_step("curl http://x")
        assert not ok


def test_execute_plan_harmless(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")
    results = agent_cli._execute_plan(["bb tools list", "bb evil; whoami"])
    assert results[0]["executed"] is True
    assert results[0]["exit_code"] == 0
    assert isinstance(results[0]["output"], dict)
    assert "tools" in results[0]["output"]
    assert results[1]["executed"] is False
    assert "denied" in results[1]["policy"]


def test_teach_writes_skill_file(tmp_path, monkeypatch, capsys):
    from bigbang.core.output import set_json_mode

    monkeypatch.setattr(agent_cli, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")
    set_json_mode(True)
    agent_cli.teach("Run scout rft export weekly to build the dataset")
    out = json.loads(capsys.readouterr().out)
    assert out["learned"] is True
    path = tmp_path / "skills" / f"{out['slug']}.md"
    assert path.exists()
    assert "scout rft export" in path.read_text().lower() or "rft" in path.read_text()


class TestBus:
    def test_bus_absent_audit_log_honest_empty(self, tmp_path, monkeypatch, capsys):
        from bigbang.core.output import set_json_mode

        missing = tmp_path / "nope" / "audit.jsonl"
        monkeypatch.setattr(audit, "AUDIT_FILE", missing)
        set_json_mode(True)
        agent_cli.bus(threshold=3)
        out = json.loads(capsys.readouterr().out)
        assert out["suggestions"] == []
        assert out["count"] == 0
        assert "not present" in out["note"]

    def test_bus_suggests_repeated_commands(self, tmp_path, monkeypatch, capsys):
        from bigbang.core.output import set_json_mode

        f = tmp_path / "audit.jsonl"
        entries = [{"command": "tools list", "args": {}}] * 4 + [
            {"command": "rare", "args": {}}
        ]
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        monkeypatch.setattr(audit, "AUDIT_FILE", f)
        set_json_mode(True)
        agent_cli.bus(threshold=3)
        out = json.loads(capsys.readouterr().out)
        cmds = [s["command"] for s in out["suggestions"]]
        assert "tools list" in cmds
        assert "rare" not in cmds
        # 4 from the file + the bus emit itself may append after read; count from file read
        assert out["suggestions"][0]["times_run"] >= 3


class _FakeAgentResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAgentClient:
    """Routes a request to the first payload whose key is a substring of the URL."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list = []

    def _match(self, url: str) -> _FakeAgentResp:
        for key, (status, payload) in self.routes.items():
            if key in url:
                return _FakeAgentResp(status, payload)
        return _FakeAgentResp(404, {})

    def get(self, url):
        self.calls.append(("GET", url))
        return self._match(url)

    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self._match(url)

    def close(self):
        pass


def test_fallback_ollama_chat_sends_the_cap(monkeypatch):
    """agent/cli.py duplicates ollama_chat + _num_predict_cap_fallback (PR #67/#68)
    ONLY inside the `except Exception:` around `from bigbang.core.llm import ...`,
    reachable only when that import has already failed (_HAS_LLM=False) — which
    does not happen in this repo's real environment (bigbang.core.llm always
    imports here; confirmed via `agent_cli._HAS_LLM is True` below). PR #68's
    review flagged this branch as shipped with zero coverage.

    Force the import failure to reach it: setting sys.modules["bigbang.core.llm"]
    = None makes the next `from bigbang.core.llm import ...` raise ImportError —
    the documented sys.modules sentinel behavior, not a monkeypatch of real
    module internals — then reload the plugin so its top-level try/except takes
    the fallback branch. Restored in `finally` so no other test in the suite
    (test_agent_bus_skips.py holds the same module reference) sees the fallback
    definitions after this one exits.
    """
    monkeypatch.delenv("DOTTIE_OLLAMA_NUM_PREDICT", raising=False)
    real_llm = sys.modules.get("bigbang.core.llm")
    sys.modules["bigbang.core.llm"] = None
    try:
        importlib.reload(agent_cli)
        assert agent_cli._HAS_LLM is False
        client = _FakeAgentClient({"/api/chat": (200, {"message": {"content": "hi"}})})
        monkeypatch.setattr(agent_cli, "_httpx_client_fallback", lambda timeout=2.0: client)

        agent_cli.ollama_chat(
            "qwen3:8b", [{"role": "user", "content": "hi"}], base="http://127.0.0.1:11434"
        )
        posts = [c for c in client.calls if c[0] == "POST"]
        assert posts[-1][2]["options"]["num_predict"] == 2048  # default cap

        monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "64")
        agent_cli.ollama_chat(
            "qwen3:8b", [{"role": "user", "content": "hi"}], base="http://127.0.0.1:11434"
        )
        posts = [c for c in client.calls if c[0] == "POST"]
        assert posts[-1][2]["options"]["num_predict"] == 64  # env override
    finally:
        if real_llm is not None:
            sys.modules["bigbang.core.llm"] = real_llm
        else:
            sys.modules.pop("bigbang.core.llm", None)
        importlib.reload(agent_cli)
        assert agent_cli._HAS_LLM is True
