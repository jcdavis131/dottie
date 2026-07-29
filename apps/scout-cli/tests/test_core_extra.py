"""Extra coverage: security vault round-trip, auth pure helpers, tasks CRUD (stubbed)."""

import json
import os

import pytest

from bigbang.core import security


class TestSecurityVaultTmpHome:
    @pytest.fixture(autouse=True)
    def _tmp_vault(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        # keep keyring/env layers out of the way
        monkeypatch.delenv("BB_SECRET_RT_KEY", raising=False)

    def test_set_get_roundtrip_and_perms(self):
        security.set_secret("RT_KEY", "round-trip-value")
        assert security.get_secret("RT_KEY") == "round-trip-value"
        if os.name == "posix":  # Windows chmod cannot express 0o600
            mode = security.VAULT_FILE.stat().st_mode & 0o777
            assert mode == 0o600
        assert "RT_KEY" in security.list_secrets()
        assert security.delete_secret("RT_KEY") is True
        assert security.get_secret("RT_KEY") is None

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BB_SECRET_ENVONLY", "from-env")
        assert security.get_secret("ENVONLY") == "from-env"


class TestAuthHelpers:
    def test_get_token_vault_key_priority(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        from bigbang.plugins.auth import cli as auth_cli

        security.set_secret("GITHUB_TOKEN", "gh-vaulted")
        assert auth_cli.get_token("github") == "gh-vaulted"

    def test_get_token_env_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        from bigbang.plugins.auth import cli as auth_cli

        monkeypatch.setenv("MYSVC_TOKEN", "env-tok")
        assert auth_cli.get_token("mysvc") == "env-tok"

    def test_get_token_missing_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        from bigbang.plugins.auth import cli as auth_cli

        for var in ("NOSVC_TOKEN", "NOSVC_API_KEY", "NOSVC_PAT"):
            monkeypatch.delenv(var, raising=False)
        assert auth_cli.get_token("nosvc") is None
        assert auth_cli.get_token("") is None

    def test_resolve_client_id_explicit_wins(self, monkeypatch):
        from bigbang.plugins.auth import cli as auth_cli

        cfg = auth_cli.SERVICE_CONFIGS["github"]
        assert auth_cli._resolve_client_id("github", cfg, explicit=" abc ") == "abc"

    def test_resolve_client_id_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "VAULT_FILE", tmp_path / "secrets.json")
        from bigbang.plugins.auth import cli as auth_cli

        cfg = auth_cli.SERVICE_CONFIGS["github"]
        monkeypatch.setenv("GITHUB_CLIENT_ID", "cid-env")
        assert auth_cli._resolve_client_id("github", cfg) == "cid-env"

    def test_load_save_auth_roundtrip(self, tmp_path, monkeypatch):
        """Relocates HOME, not just REG.

        `_save_auth` now enforces the manifest allowlist, which declares
        `~/.local/share/bigbang/auth.json`. The old fixture pointed REG at
        `tmp_path/auth.json` -- a path no expansion of `~` can produce -- so the
        gate correctly denied it and this test went red. Moving HOME moves BOTH
        sides: `_norm_path` expanduser()s the declared entry against the same fake
        home, so the real relationship (auth.json lives under the user's data dir)
        is preserved instead of bypassed. USERPROFILE is what expanduser reads on
        Windows, HOME on POSIX -- set both so the fixture is not platform-specific.
        """
        from bigbang.plugins.auth import cli as auth_cli

        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        reg = tmp_path / ".local" / "share" / "bigbang" / "auth.json"
        monkeypatch.setattr(auth_cli, "REG", reg)
        auth_cli._save_auth({"github": {"method": "token"}})
        assert auth_cli._load_auth() == {"github": {"method": "token"}}
        if os.name == "posix":  # Windows chmod cannot express 0o600
            assert reg.stat().st_mode & 0o777 == 0o600

    def test_save_auth_refuses_a_path_outside_the_allowlist(self, tmp_path, monkeypatch):
        """The gate must be load-bearing, not decorative.

        Without this, the roundtrip above could keep passing with the enforcement
        deleted and nothing would notice -- the exact "a gate whose verdict nothing
        consumes" shape this repo keeps finding. Here REG is deliberately somewhere
        no expansion of `~` reaches, which is what a compromised or buggy caller
        would do, and the write must not happen.
        """
        import typer

        from bigbang.plugins.auth import cli as auth_cli

        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        stray = tmp_path / "elsewhere" / "auth.json"
        monkeypatch.setattr(auth_cli, "REG", stray)
        with pytest.raises(typer.Exit):
            auth_cli._save_auth({"github": {"method": "token"}})
        assert not stray.exists(), "denied write still created the file"


class TestTasksCrudStubbed:
    @pytest.fixture()
    def gws_calls(self, monkeypatch, tmp_path):
        """Stub subprocess.run inside the tasks plugin; record hatch_gws_cli argv."""
        from bigbang.core import audit
        from bigbang.plugins.tasks import cli as tasks_cli

        monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")
        calls = []

        class FakeProc:
            returncode = 0
            stderr = ""

            def __init__(self, out):
                self.stdout = out

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[2] == "insert" or (len(cmd) > 3 and cmd[3] == "insert"):
                return FakeProc(json.dumps({"id": "task-1", "title": "stub"}))
            return FakeProc(json.dumps({"items": [{"id": "task-1", "title": "stub"}]}))

        monkeypatch.setattr(tasks_cli.subprocess, "run", fake_run)
        return calls

    def _out(self, capsys):
        return json.loads(capsys.readouterr().out)

    def test_add_list_complete_delete(self, gws_calls, capsys):
        from bigbang.core.output import set_json_mode
        from bigbang.plugins.tasks import cli as tasks_cli

        set_json_mode(True)

        tasks_cli.add_task("Test task", notes="n", due=None, tasklist="@default")
        out = self._out(capsys)
        assert out["created"]["id"] == "task-1"
        assert gws_calls[-1][:3] == ["hatch_gws_cli", "tasks", "tasks"]

        tasks_cli.list_tasks(
            tasklist="@default",
            show_completed=False,
            max_results=10,
            due_min=None,
            due_max=None,
        )
        out = self._out(capsys)
        assert out["count"] == 1

        tasks_cli.complete_task("task-1", tasklist="@default")
        out = self._out(capsys)
        assert out["task_id"] == "task-1"

        tasks_cli.delete_task("task-1", tasklist="@default", force=True)
        out = self._out(capsys)
        assert out["deleted"] == "task-1"

    def test_export_writes_to_repo_docs(self, gws_calls, capsys, monkeypatch, tmp_path):
        from bigbang.core.output import set_json_mode
        from bigbang.plugins.tasks import cli as tasks_cli

        set_json_mode(True)
        # redirect repo root to tmp so the test never touches real docs/
        monkeypatch.setattr(tasks_cli, "_repo_root", lambda: tmp_path)
        tasks_cli.export_tasks(tasklist="@default")
        out = self._out(capsys)
        exported = tmp_path / "docs" / "llm-wiki" / "tasks-@default.json"
        assert out["exported"] == str(exported)
        assert exported.exists()
        assert json.loads(exported.read_text())["items"][0]["id"] == "task-1"
