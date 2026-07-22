"""Agentability regression tests — cli-for-agents skill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "bigbang.cli"]


def _run(args, *, input_text=None, timeout=8, env=None):
    # --help is rendered by Typer/Rich. Under a color-forcing CI terminal (FORCE_COLOR,
    # which GitHub Actions sets) Rich wraps help into an ANSI panel, splitting literal
    # example substrings across lines so content assertions fail. Pin a plain, wide,
    # color-free render so these tests assert on content, not terminal layout.
    run_env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1", "COLUMNS": "200"}
    if env:
        run_env.update(env)
    return subprocess.run(
        CLI + args,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
        env=run_env,
    )


def test_root_help_has_examples():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "scout --json tools list" in r.stdout


def test_secrets_help_has_examples():
    r = _run(["secrets", "set", "--help"])
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "--stdin" in r.stdout
    assert "--value" in r.stdout


def test_secrets_set_via_stdin_and_get_json():
    key = f"AGENT_TEST_{int(time.time())}"
    r = _run(["secrets", "set", key, "--stdin"], input_text="super-secret-value\n")
    assert r.returncode == 0, r.stderr
    r2 = _run(["--json", "secrets", "get", key])
    assert r2.returncode == 0, r2.stderr + r2.stdout
    data = json.loads(r2.stdout)
    assert data["value"] == "super-secret-value"
    # cleanup
    _run(["secrets", "rm", key, "--force"])


def test_secrets_rm_dry_run_and_force():
    key = f"AGENT_RM_{int(time.time())}"
    _run(["secrets", "set", key, "--value", "tmp"])
    dry = _run(["--json", "secrets", "rm", key, "--dry-run"])
    assert dry.returncode == 0
    payload = json.loads(dry.stdout)
    assert payload["dry_run"] is True
    assert payload["exists"] is True
    # still present
    assert _run(["--json", "secrets", "get", key]).returncode == 0
    rm = _run(["--json", "secrets", "rm", key, "--force"])
    assert rm.returncode == 0
    assert json.loads(rm.stdout)["ok"] is True


def test_secrets_get_missing_exits_nonzero_with_example():
    r = _run(["--json", "secrets", "get", "definitely_missing_key_zz"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "error" in data
    assert "example" in data
    assert "scout secrets set" in data["example"]


def test_auth_set_token_noninteractive_fails_fast():
    """Must not hang waiting for a hidden prompt when stdin is not a TTY."""
    t0 = time.monotonic()
    r = _run(["--json", "auth", "set-token", "_agent_probe_no_token"], timeout=5)
    elapsed = time.monotonic() - t0
    assert elapsed < 4.0, f"hung for {elapsed:.1f}s — interactive prompt leaked"
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "error" in data
    assert "example" in data
    assert "--token" in data["example"] or "--stdin" in data["example"]


def test_auth_set_token_stdin():
    svc = f"agentprobe{int(time.time()) % 100000}"
    r = _run(["--json", "auth", "set-token", svc, "--stdin"], input_text="tok_abc\n")
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert (
        data.get("service") == svc or data.get("status") == "ok" or "vault_key" in data
    )
    # logout cleanup if available
    _run(["auth", "logout", svc, "--delete-vault"])


def test_tools_rm_requires_force():
    name = f"agent_tool_{int(time.time())}"
    add = _run(
        ["--json", "tools", "add", name, "--type", "cli", "--description", "tmp"]
    )
    assert add.returncode == 0, add.stderr
    denied = _run(["--json", "tools", "rm", name])
    assert denied.returncode == 1
    body = json.loads(denied.stdout)
    assert "--force" in body.get("example", "")
    dry = _run(["--json", "tools", "rm", name, "--dry-run"])
    assert json.loads(dry.stdout)["dry_run"] is True
    ok = _run(["--json", "tools", "rm", name, "--force"])
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["ok"] is True


def test_tools_get_missing_exits_nonzero():
    r = _run(["--json", "tools", "get", "__no_such_tool__"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "example" in data


def test_write_scan_help_has_examples():
    r = _run(["write", "scan", "--help"])
    assert r.returncode == 0
    assert "Examples:" in r.stdout
