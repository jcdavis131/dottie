"""Planes — judgment-plane differentiator surface."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLI = [sys.executable, "-m", "bigbang.cli"]
ROOT = Path(__file__).resolve().parents[1]


def _run(args, timeout=20):
    return subprocess.run(
        CLI + args, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT)
    )


def test_planes_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "planes" in list_plugin_names()
    assert (ROOT / "docs/DIFFERENTIATION.md").exists()


def test_planes_status_envelope():
    r = _run(["--json", "planes", "status"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    body = data["data"]
    assert "judgment plane" in body["thesis"].lower() or "Judgment" in body["thesis"]
    ids = [p["id"] for p in body["planes"]]
    assert ids == ["trust", "world", "herd", "judgment", "memory"]
    trust = body["planes"][0]
    assert trust["signals"]["product_telemetry"] is False
    assert trust["signals"]["phone_home"] is False
    assert trust["signals"]["local_audit"] is True


def test_planes_bare_defaults_to_status():
    r = _run(["--json", "planes"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert "planes" in data["data"]


def test_planes_compare_refuses_pty_trap():
    r = _run(["--json", "planes", "compare"])
    assert r.returncode == 0
    data = json.loads(r.stdout)["data"]
    assert any("PTY" in x or "multiplexer" in x.lower() or "TUI" in x for x in data["refuse"])
    # Scout should not claim persistent PTY wins
    pty_row = next(r for r in data["rows"] if "PTY" in r["capability"])
    assert pty_row["scout"] is False
    assert pty_row["herdr"] is True
    # Scout should win vault/policy
    trust_row = next(r for r in data["rows"] if "Vault" in r["capability"])
    assert trust_row["scout"] is True
    assert trust_row["herdr"] is False


def test_planes_loop_and_thesis():
    loop = _run(["--json", "planes", "loop"])
    assert loop.returncode == 0
    stages = [s["stage"] for s in json.loads(loop.stdout)["data"]["stages"]]
    assert "act" in stages and "audit" in stages and "rft" in stages

    th = _run(["--json", "planes", "thesis"])
    assert th.returncode == 0
    body = json.loads(th.stdout)["data"]
    assert "judgment plane" in body["thesis"].lower()
    assert body["teach"].startswith("scout skill")


def test_ava_routes_planes():
    from bigbang.plugins.ava.cli import _heuristic_route

    r = _heuristic_route("compare scout vs herdr differentiation")
    assert r["picked_tool"] == "planes"
    assert "compare" in r["picked_command"]
