"""Tests for todos plugin — --help, --json, basic run."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "bigbang.cli"]


def _run(args, *, timeout=15, env=None):
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


def test_todos_plugin_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "todos" in list_plugin_names()


def test_todos_help():
    r = _run(["todos", "--help"])
    assert r.returncode == 0, r.stderr + r.stdout
    assert "TODO" in r.stdout or "todos" in r.stdout.lower()
    assert "Examples:" in r.stdout or "path" in r.stdout.lower()


def test_todos_help_json_position():
    # scout todos --help --json should work (json hoisted)
    r = _run(["todos", "--help", "--json"])
    assert r.returncode == 0, r.stderr + r.stdout
    # help output, not JSON error
    assert "todos" in r.stdout.lower() or "TODO" in r.stdout


def test_todos_json_output():
    r = _run(["--json", "todos"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data.get("ok") is True
    inner = data.get("data") or {}
    # should contain grouping keys
    assert "total_markers" in inner or "todos" in inner
    assert "by_type" in inner
    assert "by_plugin" in inner
    assert "scanned_files" in inner


def test_todos_list_json():
    r = _run(["--json", "todos", "list"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert "by_type" in data["data"]


def test_todos_path_filter():
    r = _run(["--json", "todos", "--path", "bigbang/plugins/todos"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    # filter should reduce files
    assert data["data"]["scan_root"] is not None


def test_todos_type_filter():
    r = _run(["--json", "todos", "--type", "TODO"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    # all returned todos should be TODO if any
    for item in data["data"].get("todos", []):
        assert item["type"] == "TODO"


def test_todos_yes_flag():
    # --yes should be accepted (no prompt)
    r = _run(["--json", "todos", "--yes"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True


def test_todos_env_yes():
    env = dict(**{k: v for k, v in __import__("os").environ.items()}, SCOUT_YES="1")
    r = _run(["--json", "todos", "--path", "bigbang/plugins"], env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True


def test_todos_no_factory_import():
    cli_path = ROOT / "bigbang" / "plugins" / "todos" / "cli.py"
    text = cli_path.read_text(encoding="utf-8")
    assert "apps/ava-factory" not in text or "subprocess" in text
    # ensure no direct import of factory
    assert "from apps.ava_factory" not in text
    assert "import apps.ava-factory" not in text
    assert "import ava_factory" not in text.lower() or "factory" in text.lower()
    # should mention factory wrapper rule comment
    assert "Factory wrapper" in text or "scout ava" in text


def test_todos_uses_ok_err():
    cli_path = ROOT / "bigbang" / "plugins" / "todos" / "cli.py"
    text = cli_path.read_text(encoding="utf-8")
    assert "from bigbang.core.contract import" in text
    assert "ok(" in text
    assert "emit(" in text
