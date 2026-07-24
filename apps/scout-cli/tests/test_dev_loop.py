"""Tests for dev_loop plugin — toil automation from shell history."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "bigbang.cli"]

def _run(args, *, timeout=60, env=None):
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
        env=env,
    )

def test_dev_loop_plugin_discovered():
    from bigbang.core.plugin_loader import list_plugin_names
    names = list_plugin_names()
    assert "dev_loop" in names, f"dev_loop not in {names}"

def test_dev_loop_help():
    r = _run(["dev_loop", "--help"])
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout.lower()
    assert "dev_loop" in out or "dev loop" in out
    assert "status" in out or "ship" in out

def test_dev_loop_status_json():
    r = _run(["--json", "dev_loop", "status", "--path", str(ROOT)], timeout=20)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data.get("ok") is True
    inner = data.get("data") or {}
    assert "repo" in inner

def test_dev_loop_uses_ok_err_and_no_secrets():
    cli_path = ROOT / "bigbang" / "plugins" / "dev_loop" / "cli.py"
    text = cli_path.read_text(encoding="utf-8")
    assert "from bigbang.core.contract import" in text
    assert "ok(" in text
    assert "emit(" in text
    assert "ghp_" not in text
    assert "sk-" not in text
    assert "make_plugin_app" in text

def test_dev_loop_ship_dry_run_no_push():
    # dry run: should work with --yes and --no-push and --no-tests to avoid recursion
    r = _run(["--json", "dev_loop", "ship", "--path", str(ROOT), "--message", "test: dry-run check", "--yes", "--no-push", "--no-tests"], timeout=20)
    # may succeed or say nothing to commit, both ok
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data.get("ok") is True
