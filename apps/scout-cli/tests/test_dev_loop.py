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


def _git(args, cwd):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _throwaway_repo(tmp_path: Path) -> Path:
    """A real git repo that is NOT this one.

    This exists because the previous version of the ship test ran against ROOT --
    the actual scout-cli checkout -- with `--yes` and without `--no-add-all`, so
    every run performed a real `git add -A` + `git commit` and swallowed whatever
    happened to be uncommitted at the time. It was named "dry_run" and was not one;
    `--no-push` was the only reason the damage stayed local. A test must not commit
    to the tree it lives in.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    # a fresh repo inherits no identity, and commit fails without one
    _git(["config", "user.email", "test@example.invalid"], repo)
    _git(["config", "user.name", "dev_loop test"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "seed"], repo)
    return repo


def test_dev_loop_ship_commits_in_an_isolated_repo(tmp_path):
    """ship stages, commits, and honors --no-push -- proven, not assumed.

    The old assertion was `ok is True` with the comment "may succeed or say nothing
    to commit, both ok", which passes even when ship does nothing at all.
    """
    repo = _throwaway_repo(tmp_path)
    (repo / "change.txt").write_text("new work\n", encoding="utf-8")
    before = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    r = _run(
        [
            "--json",
            "dev_loop",
            "ship",
            "--path",
            str(repo),
            "--message",
            "test: isolated ship",
            "--yes",
            "--no-push",
            "--no-tests",
        ],
        timeout=60,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data.get("ok") is True
    inner = data.get("data") or {}

    # a REAL commit, not the "Nothing to commit" branch -- the old test took either
    assert inner.get("committed") is True
    assert inner.get("pushed") is False  # --no-push honored
    assert inner.get("message") == "test: isolated ship"

    after = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    assert after != before  # HEAD actually advanced
    assert inner.get("sha") and after.startswith(inner["sha"])
    assert (
        _git(["log", "-1", "--pretty=%s"], repo).stdout.strip() == "test: isolated ship"
    )
    # add -A swept the untracked file in, so nothing is left behind
    assert _git(["status", "--porcelain"], repo).stdout.strip() == ""


def test_dev_loop_ship_reports_nothing_to_commit_on_a_clean_tree(tmp_path):
    """The clean-tree branch must be distinguishable from a successful commit.

    These two outcomes were indistinguishable to the old test, which is what let a
    do-nothing ship read as a pass.
    """
    repo = _throwaway_repo(tmp_path)  # seeded and clean
    r = _run(
        [
            "--json",
            "dev_loop",
            "ship",
            "--path",
            str(repo),
            "--message",
            "test: should not commit",
            "--yes",
            "--no-push",
            "--no-tests",
        ],
        timeout=60,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    inner = (json.loads(r.stdout).get("data")) or {}
    assert "committed" not in inner  # no commit was made
    assert "Nothing to commit" in (inner.get("message") or "")
    assert _git(["log", "-1", "--pretty=%s"], repo).stdout.strip() == "seed"
