"""Herd plugin — Herdr-inspired session control surface."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

CLI = [sys.executable, "-m", "bigbang.cli"]
ROOT = Path(__file__).resolve().parents[1]


def _run(args, *, timeout=30):
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
    )


def test_herd_plugin_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "herd" in list_plugin_names()
    assert (Path("bigbang/plugins/herd/manifest.yaml")).exists()


def test_ava_routes_herd():
    from bigbang.plugins.ava.cli import _heuristic_route

    route = _heuristic_route("show my herd agent status")
    assert route["picked_tool"] == "herd"
    assert route["confidence"] >= 0.9


def test_herd_status_json():
    r = _run(["--json", "herd", "status"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "by_status" in data
    assert "herdr" in data
    assert "installed" in data["herdr"]


def test_herd_create_start_wait_read_close():
    label = f"t{int(time.time()) % 100000}"
    c = _run(["--json", "herd", "create", "--label", label, "--cwd", str(ROOT)])
    assert c.returncode == 0, c.stderr + c.stdout
    created = json.loads(c.stdout)["created"]
    assert created["status"] == "idle"

    s = _run(
        ["--json", "herd", "start", label, "--cmd", "python3 -c \"print('herd-ok')\""]
    )
    assert s.returncode == 0, s.stderr + s.stdout
    started = json.loads(s.stdout)["started"]
    assert started["pid"]

    w = _run(
        ["--json", "herd", "wait", label, "--status", "done", "--timeout", "15"],
        timeout=20,
    )
    assert w.returncode == 0, w.stderr + w.stdout
    waited = json.loads(w.stdout)
    assert waited["matched"] is True
    assert waited["session"]["status"] == "done"

    rd = _run(["--json", "herd", "read", label, "--lines", "20"])
    assert rd.returncode == 0
    body = json.loads(rd.stdout)
    assert any("herd-ok" in line for line in body["lines"])

    rep = _run(
        ["--json", "herd", "report", label, "--status", "blocked", "--note", "test"]
    )
    # process already done — report still sets manual status
    assert rep.returncode == 0, rep.stderr + rep.stdout

    dry = _run(["--json", "herd", "close", label, "--dry-run"])
    assert json.loads(dry.stdout)["dry_run"] is True

    cl = _run(["--json", "herd", "close", label, "--force"])
    assert cl.returncode == 0, cl.stderr + cl.stdout


def test_herd_wait_timeout_exit_2():
    label = f"w{int(time.time()) % 100000}"
    _run(["--json", "herd", "create", "--label", label])
    # never started → waiting for done should timeout
    r = _run(
        ["--json", "herd", "wait", label, "--status", "done", "--timeout", "1"],
        timeout=10,
    )
    assert r.returncode == 2
    data = json.loads(r.stdout)
    assert data["matched"] is False
    _run(["--json", "herd", "close", label, "--force"])


def test_herd_help_has_examples():
    r = _run(["herd", "--help"])
    assert r.returncode == 0
    assert "Examples:" in r.stdout


def test_herd_skill_file_exists():
    assert Path("bigbang/skills/scout-herd.md").exists()
