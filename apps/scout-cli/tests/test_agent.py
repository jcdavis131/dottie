"""Tests for agent run --execute, teach, and bus (findings #5/#6)."""

import json

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
