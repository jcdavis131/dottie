"""Herd plugin — Herdr-inspired session control surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "bigbang.cli"]
ROOT = Path(__file__).resolve().parents[1]


def _run(args, *, timeout=30):
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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


# ---------------------------------------------------------------------------
# Concurrent ledger writes — the cause of the intermittent `herd wait` OSError
# ---------------------------------------------------------------------------
class TestLedgerWritesSurviveConcurrency:
    """`_save` used a FIXED temp name, so every process shared one sessions.tmp.

    Two `scout herd` invocations wrote the same file and one replaced it out from
    under the other. Measured before the fix: 4 processes polling
    `get_session(refresh=True)` for 6s produced 3334 PermissionErrors
    ([Errno 13] on the temp, [WinError 32] on the replace), which surfaced through
    `herd wait` as an OSError and red the suite at random. After: 0.

    These are in-process and fast. The multi-process reproduction is recorded in
    TODO.md; running it in the suite would add seconds and a second flake source.
    """

    @pytest.fixture()
    def isolated(self, tmp_path, monkeypatch):
        from bigbang.plugins.herd import store

        monkeypatch.setattr(store, "HERD_DIR", tmp_path)
        monkeypatch.setattr(store, "HERD_FILE", tmp_path / "sessions.json")
        monkeypatch.setattr(store, "LOG_DIR", tmp_path / "logs")
        return store

    def test_the_temp_name_is_unique_per_process(self, isolated, monkeypatch):
        """The whole fix. A shared temp name is the race; the pid makes it unique.

        Asserts on the file actually created, not on the expression -- a test that
        re-derived `with_suffix(f".{os.getpid()}.tmp")` would pass against the old
        code too if someone reverted only the write.
        """
        seen = []
        real_replace = Path.replace

        def spy(self, target):
            seen.append(Path(self).name)
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", spy)
        isolated._save({"version": "1", "sessions": {}})

        assert seen, "nothing was replaced — _save did not write atomically"
        assert seen[0] != "sessions.tmp", (
            "the temp name is shared by every process again; this is the race"
        )
        assert str(os.getpid()) in seen[0], f"temp name carries no pid: {seen[0]}"

    def test_a_transient_permission_error_is_retried(self, isolated, monkeypatch):
        """WinError 32 fires when a concurrent reader has sessions.json open. That
        is transient by nature, so the write must retry rather than propagate."""
        calls = {"n": 0}
        real_replace = Path.replace

        def flaky(self, target):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(32, "being used by another process")
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", flaky)
        isolated._save({"version": "1", "sessions": {"x": {"id": "x"}}})
        assert calls["n"] == 3, f"expected 2 retries then success, got {calls['n']}"
        assert isolated.HERD_FILE.exists()

    def test_a_permanent_failure_still_raises_and_leaves_no_temp(
        self, isolated, monkeypatch, tmp_path
    ):
        """Anti-vacuity in both directions. If the retry swallowed the error the
        ledger would silently stop persisting; if it did not clean up, every failed
        run would leave a per-pid temp behind and the directory would fill."""
        def always(self, target):
            raise PermissionError(13, "permission denied")

        monkeypatch.setattr(Path, "replace", always)
        with pytest.raises(PermissionError):
            isolated._save({"version": "1", "sessions": {}})
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == [], f"temp files left behind: {leftovers}"
