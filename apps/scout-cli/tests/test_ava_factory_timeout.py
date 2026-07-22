# Solo personal project, no connection to employer, built with public/free-tier only
"""A hung factory job must not block the CLI forever.

`_run_in_factory` drives short factory scripts with subprocess.run(capture_output=True),
which buffers all stdout/stderr in memory until the child exits — so without a timeout a
wedged child hangs the CLI indefinitely while that buffer grows unbounded. The call now
passes FACTORY_SUBPROCESS_TIMEOUT and turns subprocess.TimeoutExpired into an honest
error envelope (exit 124) rather than an unbounded wait. This proves that path with a
mocked subprocess.run that raises TimeoutExpired — no real factory required.
"""

import json
import subprocess

import pytest
import typer

from bigbang.core import audit
from bigbang.core.output import set_json_mode
from bigbang.plugins.ava import cli as ava_cli


def test_run_in_factory_handles_timeout_gracefully(tmp_path, monkeypatch, capsys):
    set_json_mode(True)
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")
    # FACTORY must "exist" so we reach the subprocess call; tmp_path always does.
    monkeypatch.setattr(ava_cli, "FACTORY", tmp_path)

    argv = ["python", "scripts/hang.py"]

    def fake_run(*args, **kwargs):
        # The real call must pass the bounded timeout; the fake honours the
        # contract by raising TimeoutExpired the way a wedged child would.
        assert kwargs.get("timeout") == ava_cli.FACTORY_SUBPROCESS_TIMEOUT
        raise subprocess.TimeoutExpired(
            cmd=argv, timeout=kwargs["timeout"],
            output="partial-out", stderr="partial-err",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(typer.Exit) as excinfo:
        ava_cli._run_in_factory(
            argv, yes=True, command="ava test", description="hang test",
        )

    assert excinfo.value.exit_code == 124  # a clear non-zero, not a hang, not exit 0
    payload = json.loads(capsys.readouterr().out)
    assert "timed out" in payload["error"]
    assert payload["timeout_seconds"] == ava_cli.FACTORY_SUBPROCESS_TIMEOUT
    # the partial capture is preserved, not silently dropped
    assert payload["stdout"] == "partial-out"
    assert payload["stderr"] == "partial-err"


def test_factory_subprocess_timeout_is_env_overridable(monkeypatch):
    monkeypatch.setenv("FACTORY_SUBPROCESS_TIMEOUT", "12.5")
    assert ava_cli._env_float("FACTORY_SUBPROCESS_TIMEOUT", 900.0) == 12.5
    # 0 / negative / unparseable all fall back to the supplied default
    monkeypatch.setenv("FACTORY_SUBPROCESS_TIMEOUT", "0")
    assert ava_cli._env_float("FACTORY_SUBPROCESS_TIMEOUT", 900.0) == 900.0
    monkeypatch.setenv("FACTORY_SUBPROCESS_TIMEOUT", "not-a-number")
    assert ava_cli._env_float("FACTORY_SUBPROCESS_TIMEOUT", 900.0) == 900.0
