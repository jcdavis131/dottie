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


def test_herd_close_kill_actually_stops_a_running_process():
    """End-to-end, on whichever real platform runs this suite.

    Before this fix, `herd close --kill` against a still-running session
    crashed with AttributeError on Windows: os.killpg is not a module
    attribute there and signal.SIGKILL is not defined, so `close --kill`
    against a live session could not complete at all (reachable only since
    PR #67 made `alive()` correct on Windows). This does not fake the OS —
    it starts a real long-running child, kills it through the CLI, and checks
    the pid is actually gone, not merely that the ledger row was removed.
    """
    label = f"kill{int(time.time()) % 100000}"
    c = _run(["--json", "herd", "create", "--label", label, "--cwd", str(ROOT)])
    assert c.returncode == 0, c.stderr + c.stdout

    s = _run(
        ["--json", "herd", "start", label, "--cmd", "python3 -c \"import time; time.sleep(60)\""]
    )
    assert s.returncode == 0, s.stderr + s.stdout
    pid = json.loads(s.stdout)["started"]["pid"]

    w = _run(["--json", "herd", "wait", label, "--status", "working", "--timeout", "5"])
    assert json.loads(w.stdout)["matched"] is True, w.stdout + w.stderr

    k = _run(["--json", "herd", "close", label, "--kill", "--force"], timeout=15)
    assert k.returncode == 0, k.stderr + k.stdout  # a crash here is the bug
    assert json.loads(k.stdout)["ok"] is True

    from bigbang.plugins.herd import store as _store

    deadline = time.time() + 10
    while time.time() < deadline and _store._pid_alive(pid):
        time.sleep(0.2)
    assert not _store._pid_alive(pid), f"pid {pid} is still alive after --kill"


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


class TestPidAlive:
    """The liveness probe behind every refresh, wait and close.

    It used to be `os.kill(pid, 0)` on every platform. On Windows signal 0 is
    CTRL_C_EVENT: measured on the dev box 2026-09-27, probing a running
    herd-style child (start_new_session=True, sleeping 4 s, same console) raised
    nothing, so the probe said "alive", and the child then exited 0xC000013A
    (STATUS_CONTROL_C_EXIT) without printing. The check killed what it checked.
    (A dead pid raised OSError there, so dead did read as dead.)

    Both branches are tested with fakes so each runs on BOTH platforms. CI is
    ubuntu-only, so a win32 test gated on sys.platform would pass there by
    checking nothing.
    """

    class FakeKernel32:
        """OpenProcess / GetExitCodeProcess / CloseHandle, as ctypes calls them."""

        def __init__(self, *, handle=77, exit_code=259, query_ok=True):
            self.handle, self.exit_code, self.query_ok = handle, exit_code, query_ok
            self.opened, self.closed = [], []

        def OpenProcess(self, access, inherit, pid):  # noqa: N802 (the Win32 name)
            self.opened.append((access, inherit, pid))
            return self.handle

        def GetExitCodeProcess(self, handle, code_ptr):  # noqa: N802
            assert handle == self.handle
            if not self.query_ok:
                return 0
            code_ptr.contents.value = self.exit_code
            return 1

        def CloseHandle(self, handle):  # noqa: N802
            self.closed.append(handle)
            return 1

    @pytest.fixture()
    def store(self):
        from bigbang.plugins.herd import store

        return store

    @staticmethod
    def _no_signals(monkeypatch, store):
        def refuse(*a):
            raise AssertionError(f"the win32 probe sent a signal: os.kill{a}")

        monkeypatch.setattr(store.os, "kill", refuse)

    # --- win32 branch -------------------------------------------------------------

    def test_win32_a_running_process_is_alive_and_the_handle_is_closed(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        k = self.FakeKernel32(exit_code=259)
        assert store._pid_alive_win32(4242, kernel32=k, get_last_error=lambda: 0) is True
        assert k.opened == [(0x1000, False, 4242)]  # query-limited: works on others' processes
        assert k.closed == [77]

    def test_win32_an_exited_process_is_dead_even_while_its_handle_is_open(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        for code in (0, 1, 3):
            k = self.FakeKernel32(exit_code=code)
            assert store._pid_alive_win32(4242, kernel32=k, get_last_error=lambda: 0) is False, code
            assert k.closed == [77]

    def test_win32_open_refusals_split_on_the_error_code(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        denied = self.FakeKernel32(handle=None)
        # ERROR_ACCESS_DENIED: exists, not ours to query (POSIX PermissionError)
        assert store._pid_alive_win32(4, kernel32=denied, get_last_error=lambda: 5) is True
        gone = self.FakeKernel32(handle=None)
        # ERROR_INVALID_PARAMETER: no process holds that pid
        assert store._pid_alive_win32(4242, kernel32=gone, get_last_error=lambda: 87) is False
        assert denied.closed == [] and gone.closed == []  # nothing opened, nothing to close

    def test_win32_an_unreadable_exit_code_is_not_called_alive(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        k = self.FakeKernel32(query_ok=False)
        assert store._pid_alive_win32(4242, kernel32=k, get_last_error=lambda: 0) is False
        assert k.closed == [77]

    def test_on_win32_the_dispatcher_never_signals(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        asked = []
        monkeypatch.setattr(store.sys, "platform", "win32")
        monkeypatch.setattr(store, "_pid_alive_win32", lambda pid: asked.append(pid) or True)
        assert store._pid_alive(4242) is True
        assert asked == [4242]

    # --- POSIX branch -------------------------------------------------------------

    def test_posix_keeps_the_signal_zero_probe(self, store, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(store.sys, "platform", "linux")
        monkeypatch.setattr(store, "_PROC_ROOT", tmp_path)  # no /proc entry: trust the signal
        monkeypatch.setattr(store.os, "kill", lambda pid, sig: sent.append((pid, sig)))
        monkeypatch.setattr(store, "_pid_alive_win32", lambda pid: pytest.fail("win32 probe on POSIX"))
        assert store._pid_alive(4242) is True
        assert sent == [(4242, 0)]

    @pytest.mark.parametrize(("exc", "alive"), [
        (ProcessLookupError(3, "No such process"), False),
        (PermissionError(1, "Operation not permitted"), True),  # exists, owned by someone else
        (OSError(22, "Invalid argument"), False),
    ])
    def test_posix_signal_errors(self, store, monkeypatch, tmp_path, exc, alive):
        def kill(pid, sig):
            raise exc

        monkeypatch.setattr(store.os, "kill", kill)
        monkeypatch.setattr(store, "_PROC_ROOT", tmp_path)
        assert store._pid_alive_posix(4242) is alive

    def test_posix_a_zombie_is_dead(self, store, monkeypatch, tmp_path):
        monkeypatch.setattr(store.os, "kill", lambda pid, sig: None)  # zombies accept signal 0
        monkeypatch.setattr(store, "_PROC_ROOT", tmp_path)
        (tmp_path / "4242").mkdir()
        (tmp_path / "4242" / "status").write_text("Name:\tpython\nState:\tZ (zombie)\n", encoding="utf-8")
        assert store._pid_alive_posix(4242) is False
        (tmp_path / "4242" / "status").write_text("Name:\tpython\nState:\tS (sleeping)\n", encoding="utf-8")
        assert store._pid_alive_posix(4242) is True

    def test_no_pid_is_never_alive(self, store, monkeypatch):
        self._no_signals(monkeypatch, store)
        monkeypatch.setattr(store, "_pid_alive_win32", lambda pid: pytest.fail("probed a non-pid"))
        for pid in (None, 0, -1):
            assert store._pid_alive(pid) is False

    # --- the real OS, whichever this is -------------------------------------------

    def test_real_processes_on_this_platform(self, store):
        """Unfaked: real ctypes on Windows, real signal 0 on POSIX."""
        assert store._pid_alive(os.getpid()) is True
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            assert store._pid_alive(child.pid) is True
            # A console Ctrl+C lands asynchronously, so give it a moment to land:
            # the old probe's victim exited within this window.
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=1.0)
        finally:
            child.kill()
            child.wait(timeout=10)
        assert store._pid_alive(child.pid) is False


class TestCloseSessionKill:
    """`herd close --kill`'s kill path (close_session, `--kill`).

    Before this, the POSIX-only body used `os.killpg`/`signal.SIGKILL` directly
    with no platform branch. Neither exists on Windows — `os.killpg` is not a
    module attribute there at all, and `signal.SIGKILL` is not defined — so the
    very first line raised AttributeError, caught by nothing (only
    ProcessLookupError was caught). PR #67 made `_pid_alive` correct on
    Windows, which made this path reachable there for the first time, so the
    crash became real rather than latent.

    Both branches are tested with fakes so each runs on BOTH platforms — the
    same reasoning as TestPidAlive above: CI is ubuntu-only, so a win32 test
    gated on `sys.platform` would pass there by checking nothing.
    """

    @pytest.fixture()
    def store(self):
        from bigbang.plugins.herd import store

        return store

    # --- POSIX: byte-identical to the pre-Windows-support behavior ----------
    #
    # os.killpg does not exist on Windows AT ALL (not even for SIGTERM), and
    # signal.SIGKILL is not defined there either — both patched with
    # raising=False so these tests exercise the POSIX branch's logic on
    # whichever platform runs the suite (this dev box is Windows; CI is
    # ubuntu, where both attributes are real and the patch just overwrites
    # them for the test, same as always).

    @staticmethod
    def _fake_sigkill(monkeypatch, store):
        """A stand-in int for signal.SIGKILL, which does not exist on Windows."""
        monkeypatch.setattr(store.signal, "SIGKILL", -9, raising=False)
        return -9

    def test_posix_term_then_kill_when_still_alive(self, store, monkeypatch):
        sigkill = self._fake_sigkill(monkeypatch, store)
        calls = []
        monkeypatch.setattr(store.os, "killpg", lambda pid, sig: calls.append(sig), raising=False)
        monkeypatch.setattr(store.time, "sleep", lambda s: None)
        monkeypatch.setattr(store, "_pid_alive", lambda pid: True)  # still running after TERM
        store._kill_session_posix(4242)
        assert calls == [store.signal.SIGTERM, sigkill]

    def test_posix_no_kill_needed_once_term_worked(self, store, monkeypatch):
        calls = []
        monkeypatch.setattr(store.os, "killpg", lambda pid, sig: calls.append(sig), raising=False)
        monkeypatch.setattr(store.time, "sleep", lambda s: None)
        monkeypatch.setattr(store, "_pid_alive", lambda pid: False)  # TERM was enough
        store._kill_session_posix(4242)
        assert calls == [store.signal.SIGTERM]  # no SIGKILL needed — never evaluated

    def test_posix_falls_through_to_kill_when_the_group_is_already_gone(self, store, monkeypatch):
        """killpg's ProcessLookupError (no such GROUP) falls through to a plain
        os.kill on the pid itself, on both the TERM and the KILL leg."""
        sigkill = self._fake_sigkill(monkeypatch, store)
        killpg_calls, kill_calls = [], []

        def killpg(pid, sig):
            killpg_calls.append(sig)
            raise ProcessLookupError

        def kill(pid, sig):
            kill_calls.append(sig)

        monkeypatch.setattr(store.os, "killpg", killpg, raising=False)
        monkeypatch.setattr(store.os, "kill", kill)
        monkeypatch.setattr(store.time, "sleep", lambda s: None)
        monkeypatch.setattr(store, "_pid_alive", lambda pid: True)
        store._kill_session_posix(4242)
        assert killpg_calls == [store.signal.SIGTERM, sigkill]
        assert kill_calls == [store.signal.SIGTERM, sigkill]

    def test_posix_a_pid_that_died_mid_sequence_does_not_raise(self, store, monkeypatch):
        """The original code's `except Exception: try os.kill(...) except Exception:
        pass` on the KILL leg — a pid that died between the alive recheck and the
        signal must not raise out of close_session."""
        sigkill = self._fake_sigkill(monkeypatch, store)

        def killpg(pid, sig):
            if sig == sigkill:
                raise ProcessLookupError
            return None

        def kill(pid, sig):
            raise ProcessLookupError

        monkeypatch.setattr(store.os, "killpg", killpg, raising=False)
        monkeypatch.setattr(store.os, "kill", kill)
        monkeypatch.setattr(store.time, "sleep", lambda s: None)
        monkeypatch.setattr(store, "_pid_alive", lambda pid: True)
        store._kill_session_posix(4242)  # must not raise

    # --- Windows: taskkill /T /F, no signals sent at all ---------------------

    def test_win32_sends_taskkill_with_an_argument_list(self, store, monkeypatch):
        """/T (tree) and /F (force) are load-bearing, not decoration: the pid on
        record is the supervisor, not the real command; and a console process
        has no SIGTERM analogue for taskkill without /F to fall back to."""
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))

        store._kill_session_win32(4242, run=fake_run)
        assert calls == [
            (["taskkill", "/PID", "4242", "/T", "/F"], {"capture_output": True, "check": False})
        ]

    def test_win32_never_signals(self, store, monkeypatch):
        """No SIGTERM-then-SIGKILL staging on Windows — one forceful taskkill
        pass, never os.kill/os.killpg (which do not exist there anyway)."""
        monkeypatch.setattr(
            store.os, "killpg", lambda *a: pytest.fail(f"sent a signal: {a}"), raising=False
        )
        monkeypatch.setattr(
            store.os, "kill", lambda *a: pytest.fail(f"sent a signal: {a}"), raising=False
        )
        store._kill_session_win32(4242, run=lambda *a, **k: None)

    def test_win32_swallows_a_failed_taskkill_invocation(self, store):
        def raises(*a, **k):
            raise OSError("taskkill not found")

        store._kill_session_win32(4242, run=raises)  # must not raise

    def test_win32_a_nonzero_exit_does_not_raise(self, store):
        """taskkill exits nonzero for 'already gone' / 'access denied' — the
        caller's own _pid_alive recheck is the source of truth, not this exit
        code, so a nonzero return must not become an exception here."""
        recorded = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            return type("R", (), {"returncode": 128})()

        store._kill_session_win32(4242, run=fake_run)  # must not raise
        assert recorded["argv"] == ["taskkill", "/PID", "4242", "/T", "/F"]

    # --- dispatcher: close_session picks the helper by sys.platform ---------

    @pytest.fixture()
    def isolated(self, tmp_path, monkeypatch, store):
        monkeypatch.setattr(store, "HERD_DIR", tmp_path)
        monkeypatch.setattr(store, "HERD_FILE", tmp_path / "sessions.json")
        monkeypatch.setattr(store, "LOG_DIR", tmp_path / "logs")
        return store

    @staticmethod
    def _seed_running_session(store, pid, label):
        sess = store.create_session(label=label)
        data = store._load()
        data["sessions"][sess["id"]].update(pid=pid, alive=True, status="working")
        store._save(data)
        return sess["id"]

    def test_close_kill_dispatches_to_win32_on_win32(self, isolated, monkeypatch):
        monkeypatch.setattr(isolated.sys, "platform", "win32")
        called = []
        monkeypatch.setattr(isolated, "_kill_session_win32", lambda pid: called.append(pid))
        monkeypatch.setattr(
            isolated, "_kill_session_posix", lambda pid: pytest.fail("POSIX path taken on win32")
        )
        monkeypatch.setattr(isolated, "_pid_alive", lambda pid: True)  # "still running": kill fires
        sid = self._seed_running_session(isolated, 4242, "k-win32")
        isolated.close_session(sid, kill=True)
        assert called == [4242]

    def test_close_kill_dispatches_to_posix_off_win32(self, isolated, monkeypatch):
        monkeypatch.setattr(isolated.sys, "platform", "linux")
        called = []
        monkeypatch.setattr(isolated, "_kill_session_posix", lambda pid: called.append(pid))
        monkeypatch.setattr(
            isolated, "_kill_session_win32", lambda pid: pytest.fail("win32 path taken off win32")
        )
        monkeypatch.setattr(isolated, "_pid_alive", lambda pid: True)
        sid = self._seed_running_session(isolated, 4243, "k-posix")
        isolated.close_session(sid, kill=True)
        assert called == [4243]
