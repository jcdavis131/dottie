"""Persistent herd session registry (Herdr-inspired control surface).

Scout is not a PTY multiplexer — Herdr owns that. This module tracks named
agent/process sessions with semantic status so agents and humans can
list / wait / read / report over a CLI + JSON API.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# Ledger-write retry budget. ~0.55s worst case (0.01+0.02+...+0.1), which is short
# next to wait_status's 0.4s poll interval and long enough to outlast a concurrent
# reader's open()/close() of sessions.json.
_SAVE_RETRIES = 10
_SAVE_BACKOFF_S = 0.01

# Runs the command and records its exit code where a LATER `scout` process can
# read it. argv[1] is the sentinel path, argv[2:] the real command. It re-exits
# with the command's own code so the supervisor is transparent to liveness.
_SUPERVISOR = (
    "import subprocess,sys,pathlib\n"
    "rc=subprocess.call(sys.argv[2:])\n"
    "try:\n"
    "    pathlib.Path(sys.argv[1]).write_text(str(rc),encoding='utf-8')\n"
    "except OSError:\n"
    "    pass\n"
    "sys.exit(rc)\n"
)

def _default_herd_dir() -> Path:
    """State dir, overridable by SCOUT_HERD_DIR.

    The override exists because the SUBPROCESS tests could not be isolated without
    it. In-process tests monkeypatch HERD_DIR/HERD_FILE/LOG_DIR (see the `isolated`
    fixture in tests/test_herd.py), but `_run(["--json", "herd", "status"])` spawns a
    real CLI, and a child process cannot see a monkeypatch — so those tests read and
    REWROTE the developer's actual ~/.local/share/bigbang/herd/sessions.json.

    Two consequences, both observed rather than theorised:
      * running the suite MUTATED real user state;
      * the tests were data-dependent — green on a fresh CI runner with no ledger,
        red on a dev box with accumulated sessions. That is how four of them looked
        like a permanent Windows-only failure for so long: the platform was never
        the variable, the leftover ledger was.

    Matches the store-path convention this codebase already uses elsewhere
    (SCOUT_SEO_DB in core/seo.py, SCOUT_LINKS_DB in the links plugin).
    """
    override = os.environ.get("SCOUT_HERD_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "bigbang" / "herd"


HERD_DIR = _default_herd_dir()
HERD_FILE = HERD_DIR / "sessions.json"
LOG_DIR = HERD_DIR / "logs"

STATUSES = ("idle", "working", "blocked", "done", "failed", "unknown")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_dirs() -> None:
    HERD_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict[str, Any]:
    _ensure_dirs()
    if not HERD_FILE.exists():
        return {"version": "1", "sessions": {}}
    try:
        data = json.loads(HERD_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": "1", "sessions": {}}
        data.setdefault("version", "1")
        data.setdefault("sessions", {})
        return data
    except Exception:
        return {"version": "1", "sessions": {}}


def _save(data: dict[str, Any]) -> None:
    """Write the ledger atomically, and survive concurrent writers.

    The temp name is PER-PROCESS. It used to be a fixed
    `HERD_FILE.with_suffix(".tmp")`, i.e. one `sessions.tmp` shared by every
    process on the box, so two `scout herd` invocations wrote the same file and
    one replaced it out from under the other. Measured before this change: 4
    processes polling `get_session(refresh=True)` for 6 seconds produced **3334**
    PermissionErrors --

        [Errno 13] Permission denied: ...sessions.tmp
        [WinError 32] ...sessions.tmp -> sessions.json

    -- which surfaced through `herd wait` as an OSError and red the suite at
    random. `os.getpid()` is enough: two live processes cannot share a pid.

    The replace is retried because it is the OTHER half of the race. `os.replace`
    is atomic, but on Windows it fails with WinError 32 when the TARGET is open,
    and `_load` opens `sessions.json` on every read. POSIX rename has no such
    failure, so the retry is a no-op there rather than a platform branch.
    """
    _ensure_dirs()
    tmp = HERD_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for attempt in range(_SAVE_RETRIES):
        try:
            tmp.replace(HERD_FILE)
            return
        except PermissionError:
            if attempt == _SAVE_RETRIES - 1:
                # Do not leave a per-pid temp behind on the final failure, or a
                # crashed writer litters the directory with one file per run.
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_SAVE_BACKOFF_S * (attempt + 1))


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # On Linux, zombies still accept signal 0 — check /proc status when possible.
    proc = Path(f"/proc/{pid}")
    if proc.exists():
        try:
            status = (proc / "status").read_text(encoding="utf-8", errors="ignore")
            for line in status.splitlines():
                if line.startswith("State:"):
                    # Z = zombie
                    return "Z" not in line.split()[1]
        except OSError:
            pass
    return True


def _new_id() -> str:
    return f"hs_{uuid.uuid4().hex[:10]}"


def refresh_session(sess: dict[str, Any]) -> dict[str, Any]:
    """Update status from process reality unless manually authoritative."""
    authority = sess.get("status_authority")  # "process" | "manual"
    pid = sess.get("pid")
    alive = _pid_alive(pid) if pid else False
    sess["alive"] = alive

    if authority == "manual" and sess.get("status") in ("blocked", "idle"):
        # Keep human/agent-reported blocked/idle while process may still run.
        if not alive and sess.get("status") not in ("done", "failed"):
            # Process ended while marked blocked → status follows the exit code.
            code = sess.get("exit_code")
            if code is None and pid:
                sess["exit_code"] = _read_exit_sentinel(sess)
                if sess["exit_code"] is None:
                    sess["exit_code"] = _reap_exit_code(pid)
                code = sess.get("exit_code")
            sess["status"] = _status_from_code(code)
            sess["status_authority"] = "process"
            sess["updated_at"] = _now()
        return sess

    if pid and alive:
        if sess.get("status") not in ("working", "blocked", "idle"):
            sess["status"] = "working"
            sess["updated_at"] = _now()
        elif authority != "manual":
            sess["status"] = "working"
        return sess

    if pid and not alive:
        if sess.get("exit_code") is None:
            # Sentinel first: it is the only source that survives the interpreter
            # that spawned the process. _reap_exit_code stays as the fallback for
            # sessions started before the supervisor existed.
            sess["exit_code"] = _read_exit_sentinel(sess)
            if sess["exit_code"] is None:
                sess["exit_code"] = _reap_exit_code(pid)
        code = sess.get("exit_code")
        if sess.get("status") not in ("done", "failed"):
            sess["status"] = _status_from_code(code)
            sess["status_authority"] = "process"
            sess["updated_at"] = _now()
        return sess

    # No pid yet
    if sess.get("status") is None:
        sess["status"] = "idle"
    return sess


def _exit_sentinel_path(sess: dict[str, Any]) -> Path | None:
    """Where the supervisor records the real exit code (see start_session)."""
    p = sess.get("exit_path")
    if p:
        return Path(p)
    log = sess.get("log_path")
    return Path(f"{log}.exit") if log else None


def _read_exit_sentinel(sess: dict[str, Any]) -> int | None:
    """The exit code the supervisor wrote, or None if it never got to write one.

    None is the honest answer for a killed supervisor or a session started before
    this mechanism existed — and None must NOT be read as success, which is the
    bug this exists to fix.
    """
    path = _exit_sentinel_path(sess)
    if not path:
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _status_from_code(code: int | None) -> str:
    """Exit code -> status, with UNKNOWN kept distinct from success.

    The bug: this used to be
        "done" if code == 0 else ("failed" if code not in (None, 0) else "done")
    which sends an UNKNOWN exit code to "done". `_reap_exit_code` returns None on
    Windows always, and on POSIX for any process that is not a child of the
    CURRENT interpreter — and every `scout` invocation is a fresh interpreter, so
    the process that spawned the session is always gone by the time anything asks.
    Measured: a command exiting 3 reported status 'done', exit_code None, and
    `herd wait --status done` exited 0. An agent following the plugin's own
    documented flow was told a failed command had succeeded.
    """
    if code is None:
        return "unknown"
    return "done" if code == 0 else "failed"


def _reap_exit_code(pid: int) -> int | None:
    """Best-effort exit code; usually None for unreaped foreign PIDs."""
    if not hasattr(os, "WNOHANG"):
        # Windows: no POSIX reaping — liveness probing is the status authority.
        return None
    try:
        # Non-blocking wait only works for our children.
        finished_pid, status = os.waitpid(pid, os.WNOHANG)
        if finished_pid == pid:
            if os.WIFEXITED(status):
                return int(os.WEXITSTATUS(status))
            if os.WIFSIGNALED(status):
                return int(128 + os.WTERMSIG(status))
    except ChildProcessError:
        pass
    except OSError:
        pass
    return None


def list_sessions(*, refresh: bool = True) -> list[dict[str, Any]]:
    data = _load()
    out: list[dict[str, Any]] = []
    dirty = False
    for sid, sess in list(data["sessions"].items()):
        if refresh:
            before = json.dumps(sess, sort_keys=True, default=str)
            sess = refresh_session(dict(sess))
            data["sessions"][sid] = sess
            if json.dumps(sess, sort_keys=True, default=str) != before:
                dirty = True
        out.append(sess)
    if dirty:
        _save(data)
    out.sort(
        key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True
    )
    return out


def get_session(key: str, *, refresh: bool = True) -> dict[str, Any] | None:
    data = _load()
    sess = data["sessions"].get(key)
    if not sess:
        # resolve by label (exact, then unique prefix)
        matches = [
            s
            for s in data["sessions"].values()
            if s.get("label") == key or s.get("id") == key
        ]
        if not matches:
            matches = [
                s
                for s in data["sessions"].values()
                if str(s.get("label", "")).startswith(key)
                or str(s.get("id", "")).startswith(key)
            ]
        if len(matches) == 1:
            sess = matches[0]
        elif len(matches) > 1:
            return {"error": "ambiguous", "matches": [m.get("id") for m in matches]}
        else:
            return None
    if refresh and "error" not in sess:
        sess = refresh_session(dict(sess))
        data["sessions"][sess["id"]] = sess
        _save(data)
    return sess


def create_session(
    *,
    label: str,
    cwd: str | None = None,
    note: str = "",
    kind: str = "process",
) -> dict[str, Any]:
    data = _load()
    sid = _new_id()
    work = str(Path(cwd or os.getcwd()).expanduser().resolve())
    sess = {
        "id": sid,
        "label": label,
        "cwd": work,
        "status": "idle",
        "status_authority": "process",
        "cmd": [],
        "pid": None,
        "exit_code": None,
        "log_path": str(LOG_DIR / f"{sid}.log"),
        "created_at": _now(),
        "updated_at": _now(),
        "note": note,
        "kind": kind,
        "alive": False,
        "herdr_pane": None,
    }
    data["sessions"][sid] = sess
    _save(data)
    return sess


def start_session(
    key: str,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not argv:
        raise ValueError("argv required")
    data = _load()
    sess = get_session(key, refresh=True)
    if not sess:
        raise KeyError(f"session not found: {key}")
    if sess.get("error"):
        raise ValueError(f"ambiguous session: {sess.get('matches')}")
    if sess.get("alive"):
        raise RuntimeError(
            f"session {sess['id']} already running (pid {sess.get('pid')})"
        )

    work = str(Path(cwd or sess.get("cwd") or os.getcwd()).expanduser().resolve())
    log_path = Path(sess["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(log_path, "a", encoding="utf-8")
    log_f.write(f"\n--- scout herd start {_now()} ---\n")
    log_f.write(f"$ {' '.join(argv)}\n")
    log_f.flush()

    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    child_env["SCOUT_HERD_ID"] = sess["id"]
    child_env["SCOUT_HERD_LABEL"] = sess.get("label") or sess["id"]

    # A stale sentinel from a previous run of this session would be read as this
    # run's result, so clear it before anything can observe the two together.
    exit_path = Path(f"{log_path}.exit")
    try:
        exit_path.unlink()
    except OSError:
        pass

    # Run under a supervisor that writes the REAL exit code where a later `scout`
    # invocation can read it. Without this the exit status is simply unknowable:
    # os.waitpid only works for children of the current interpreter, and the
    # interpreter that spawned the session has exited by the time anyone asks.
    # The supervisor inherits the log fd and passes it to the command, so output
    # capture is unchanged; it exits with the command's own code, so liveness and
    # `close --kill` (which killpg's the new session group) behave as before.
    proc = subprocess.Popen(
        [sys.executable, "-c", _SUPERVISOR, str(exit_path), *argv],
        cwd=work,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=child_env,
        start_new_session=True,
    )
    # Parent keeps log handle — child inherited fd; close our copy after spawn.
    try:
        log_f.close()
    except Exception:
        pass

    sess["cmd"] = list(argv)  # what the user asked for, not the supervisor wrapper
    sess["cwd"] = work
    sess["pid"] = proc.pid
    sess["exit_path"] = str(exit_path)
    sess["exit_code"] = None
    sess["status"] = "working"
    sess["status_authority"] = "process"
    sess["alive"] = True
    sess["updated_at"] = _now()
    data = _load()
    data["sessions"][sess["id"]] = sess
    _save(data)
    return sess


def report_status(
    key: str,
    status: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    data = _load()
    sess = get_session(key, refresh=False)
    if not sess or sess.get("error"):
        raise KeyError(f"session not found: {key}")
    sess = refresh_session(dict(sess))
    sess["status"] = status
    sess["status_authority"] = "manual"
    if note is not None:
        sess["note"] = note
    sess["updated_at"] = _now()
    data["sessions"][sess["id"]] = sess
    _save(data)
    return sess


def read_log(key: str, *, lines: int = 40) -> dict[str, Any]:
    sess = get_session(key, refresh=True)
    if not sess or sess.get("error"):
        raise KeyError(f"session not found: {key}")
    path = Path(sess["log_path"])
    if not path.exists():
        return {"session": sess, "lines": [], "log_path": str(path), "missing": True}
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = content[-max(1, lines) :]
    return {"session": sess, "lines": tail, "log_path": str(path), "missing": False}


def wait_status(
    key: str,
    status: str,
    *,
    timeout_s: float = 60.0,
    poll_s: float = 0.4,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    deadline = time.time() + max(0.1, timeout_s)
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_session(key, refresh=True)
        if not last or last.get("error"):
            raise KeyError(f"session not found: {key}")
        if last.get("status") == status:
            return {"matched": True, "session": last, "waited_for": status}
        # Convenience: waiting for "done" also accepts "failed" as terminal? No —
        # Herdr keeps them distinct. Callers pick explicitly.
        time.sleep(poll_s)
    return {
        "matched": False,
        "session": last,
        "waited_for": status,
        "timeout_s": timeout_s,
    }


def close_session(
    key: str, *, force: bool = False, kill: bool = False
) -> dict[str, Any]:
    sess = get_session(key, refresh=True)
    if not sess or sess.get("error"):
        raise KeyError(f"session not found: {key}")
    if sess.get("alive") and not kill:
        raise RuntimeError(
            f"session {sess['id']} still running (pid {sess.get('pid')}); pass --kill or wait"
        )
    if sess.get("alive") and kill and sess.get("pid"):
        try:
            os.killpg(sess["pid"], signal.SIGTERM)
        except ProcessLookupError:
            try:
                os.kill(sess["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(0.2)
        if _pid_alive(sess["pid"]):
            try:
                os.killpg(sess["pid"], signal.SIGKILL)
            except Exception:
                try:
                    os.kill(sess["pid"], signal.SIGKILL)
                except Exception:
                    pass
    data = _load()
    removed = data["sessions"].pop(sess["id"], None)
    if removed is None and not force:
        raise KeyError(f"session not found: {key}")
    _save(data)
    return {"removed": sess["id"], "ok": removed is not None, "session": sess}


def summary() -> dict[str, Any]:
    sessions = list_sessions(refresh=True)
    counts = dict.fromkeys(STATUSES, 0)
    for sess in sessions:
        st = sess.get("status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
    return {
        "count": len(sessions),
        "by_status": counts,
        "sessions": [
            {
                "id": s["id"],
                "label": s.get("label"),
                "status": s.get("status"),
                "pid": s.get("pid"),
                "alive": s.get("alive"),
                "cwd": s.get("cwd"),
            }
            for s in sessions
        ],
    }


def herdr_available() -> dict[str, Any]:
    from shutil import which

    path = which("herdr")
    return {
        "installed": path is not None,
        "path": path,
        "docs": "https://herdr.dev/docs/",
        "note": (
            "Herdr is the PTY multiplexer; Scout herd is the JSON control-plane registry. "
            "Use them together: Herdr for panes, Scout for tools/MCP/Ava + session ledger."
        ),
    }
