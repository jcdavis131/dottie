"""Skill plugin — teach Dottie-claw / agents to drive Scout."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLI = [sys.executable, "-m", "bigbang.cli"]
ROOT = Path(__file__).resolve().parents[1]


def _run(args, *, env=None, timeout=20):
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=env,
    )


def test_skill_plugin_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "skill" in list_plugin_names()
    assert (ROOT / "bigbang/skills/scout/SKILL.md").exists()


def test_skill_list_and_show():
    r = _run(["--json", "skill", "list"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["ok"] is True
    names = {s["name"] for s in data["data"]["skills"]}
    assert "scout" in names
    assert "scout-herd" in names

    show = _run(["--json", "skill", "show", "scout"])
    assert show.returncode == 0
    body = json.loads(show.stdout)
    assert body["ok"] is True
    assert "Dottie" in body["data"]["skill"]["preview"] or "dottie" in body["data"]["skill"]["preview"].lower()


def test_skill_install_dottie_dry_run_and_real(tmp_path, monkeypatch):
    # Point dottie target at tmp via monkeypatch on module TARGETS
    from bigbang.plugins.skill import cli as skill_cli

    dottie_root = tmp_path / "dottie-skills"
    monkeypatch.setitem(skill_cli.TARGETS, "dottie", dottie_root)

    dry = _run(["--json", "skill", "install", "scout", "--target", "dottie", "--dry-run"])
    # dry-run uses TARGETS at runtime inside process — subprocess won't see monkeypatch.
    # Test install helpers in-process instead for the real write.
    assert dry.returncode == 0

    skill = skill_cli._resolve_skill("scout")
    assert skill
    result = skill_cli._install_one(skill, dottie_root, force=False)
    assert result["ok"] is True
    assert (dottie_root / "scout" / "SKILL.md").exists()
    text = (dottie_root / "scout" / "SKILL.md").read_text(encoding="utf-8")
    assert "Herd orchestration" in text or "scout herd" in text

    # idempotent skip
    again = skill_cli._install_one(skill, dottie_root, force=False)
    assert again["skipped"] is True


def test_skill_teach_inprocess(tmp_path, monkeypatch):
    from bigbang.plugins.skill import cli as skill_cli

    root = tmp_path / "skills"
    monkeypatch.setitem(skill_cli.TARGETS, "dottie", root)
    # Call install_cmd directly (same as teach)
    skill_cli.install_cmd(name=None, target="dottie", all_skills=True, force=True, dry_run=False)
    assert (root / "scout" / "SKILL.md").exists()
    assert (root / "scout-herd" / "SKILL.md").exists()


def test_ava_routes_dottie_to_skill():
    from bigbang.plugins.ava.cli import _heuristic_route

    route = _heuristic_route("teach dottie-claw how to use scout")
    assert route["picked_tool"] == "skill"
    assert "teach" in route["picked_command"]


def test_contract_ok_err():
    from bigbang.core.contract import err, make_plugin_app, ok

    payload = ok({"x": 1}, command="t", example="scout t")
    assert payload["ok"] is True
    assert payload["data"]["x"] == 1
    e = err("nope", command="t", example="scout t")
    assert e["ok"] is False
    app = make_plugin_app("demo", "demo", examples=["scout demo"])
    assert app.info.name == "demo"
