"""Herd plugin — Herdr-inspired session control surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "bigbang.cli"]
ROOT = Path(__file__).resolve().parents[1]

# One throwaway herd state dir for every subprocess in this module. A module-level
# tempdir rather than the `tmp_path` fixture because `_run` is called from plain
# functions as well as fixtured tests, and every one of them must be pointed away
# from the real ledger — an unisolated caller is what caused the damage this exists
# to prevent.
_SESSION_HERD_TMP = tempfile.TemporaryDirectory(prefix="scout-herd-tests-")
_SESSION_HERD_DIR = Path(_SESSION_HERD_TMP.name)


def _run(args, *, timeout=30, herd_dir=None):
    """Spawn the real CLI with the herd state dir pointed AWAY from the developer's.

    Without SCOUT_HERD_DIR these subprocess tests read and rewrote the real
    ~/.local/share/bigbang/herd/sessions.json — a child process cannot see the
    monkeypatch the in-process tests use. That made the suite mutate user state and,
    worse, made results depend on whatever sessions were lying around: green on a
    fresh CI runner, red on a dev box. Four tests here and in test_planes.py looked
    like a permanent Windows-only failure for exactly that reason.
    """
    env = {**os.environ, "SCOUT_HERD_DIR": str(herd_dir or _SESSION_HERD_DIR)}
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


def test_a_failing_command_is_not_reported_as_done(tmp_path):
    """THE BUG: a command that exited 3 reported status 'done'.

    `_reap_exit_code` returns None on Windows always, and on POSIX for any process
    that is not a child of the CURRENT interpreter — and every `scout` invocation is
    a fresh interpreter, so the spawner is always gone by the time anything asks. The
    old mapping sent that None to "done", so `herd wait --status done` — the flow in
    this plugin's own epilog — exited 0 and told the agent a failed command had
    succeeded. Measured before the fix: status='done', exit_code=None, wait exit 0.
    """
    failer = tmp_path / "failer.py"
    failer.write_text("import sys\nprint('about to fail')\nsys.exit(3)\n", encoding="utf-8")
    label = "failjob"
    assert _run(["--json", "herd", "create", "--label", label], herd_dir=tmp_path).returncode == 0
    # posix-style paths on purpose: herd start --cmd runs shlex.split() in POSIX mode,
    # which eats backslashes, so a native Windows path arrives mangled. as_posix() is
    # the portable spelling; the `-- argv` form avoids the split entirely.
    s = _run(["--json", "herd", "start", label, "--cmd",
              f"{Path(sys.executable).as_posix()} {failer.as_posix()}"],
             herd_dir=tmp_path)
    assert s.returncode == 0, s.stderr + s.stdout

    deadline = time.time() + 30
    sess = None
    while time.time() < deadline:
        out = _run(["--json", "herd", "get", label], herd_dir=tmp_path)
        sess = json.loads(out.stdout)["session"]
        if not sess.get("alive"):
            break
        time.sleep(0.3)

    assert sess is not None and sess["alive"] is False, "command never finished"
    assert sess["exit_code"] == 3, f"real exit code lost: {sess.get('exit_code')!r}"
    assert sess["status"] == "failed", f"a failure reported as {sess['status']!r}"

    # and the agent-facing contract: waiting for 'done' must NOT succeed
    w = _run(["--json", "herd", "wait", label, "--status", "done", "--timeout", "3"],
             timeout=20, herd_dir=tmp_path)
    assert w.returncode == 2, "wait --status done still claims a failed command succeeded"
    assert json.loads(w.stdout)["matched"] is False

    # stdout still reaches the log — the supervisor must be transparent to capture
    rd = _run(["--json", "herd", "read", label, "--lines", "20"], herd_dir=tmp_path)
    assert any("about to fail" in line for line in json.loads(rd.stdout)["lines"])


def test_unknown_exit_code_is_unknown_not_success():
    """The mapping in isolation. An absent exit code is not evidence of success.

    Pinned separately from the end-to-end test because this is the exact expression
    that was wrong, and it is the one a future edit is most likely to 'simplify'
    back into `else "done"`.
    """
    from bigbang.plugins.herd import store

    assert store._status_from_code(0) == "done"
    assert store._status_from_code(3) == "failed"
    assert store._status_from_code(1) == "failed"
    assert store._status_from_code(None) == "unknown"


def test_a_stale_exit_sentinel_is_not_read_as_this_runs_result(tmp_path):
    """Restarting a session must clear the previous run's recorded exit code."""
    from bigbang.plugins.herd import store

    log = tmp_path / "s.log"
    sentinel = Path(f"{log}.exit")
    sentinel.write_text("3", encoding="utf-8")
    sess = {"log_path": str(log), "exit_path": str(sentinel)}
    assert store._read_exit_sentinel(sess) == 3

    sentinel.unlink()
    assert store._read_exit_sentinel(sess) is None, (
        "a missing sentinel must read as unknown, never as 0"
    )
    sentinel.write_text("not-a-number", encoding="utf-8")
    assert store._read_exit_sentinel(sess) is None


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
