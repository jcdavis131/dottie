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
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

HERD_DIR = Path.home() / ".local" / "share" / "bigbang" / "herd"
HERD_FILE = HERD_DIR / "sessions.json"
LOG_DIR = HERD_DIR / "logs"

STATUSES = ("idle", "working", "blocked", "done", "failed", "unknown")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    HERD_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, Any]:
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


def _save(data: Dict[str, Any]) -> None:
    _ensure_dirs()
    tmp = HERD_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(HERD_FILE)


def _pid_alive(pid: Optional[int]) -> bool:
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


def refresh_session(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Update status from process reality unless manually authoritative."""
    authority = sess.get("status_authority")  # "process" | "manual"
    pid = sess.get("pid")
    alive = _pid_alive(pid) if pid else False
    sess["alive"] = alive

    if authority == "manual" and sess.get("status") in ("blocked", "idle"):
        # Keep human/agent-reported blocked/idle while process may still run.
        if not alive and sess.get("status") not in ("done", "failed"):
            # Process ended while marked blocked → failed unless exit 0.
            code = sess.get("exit_code")
            if code is None and pid:
                sess["exit_code"] = _reap_exit_code(pid)
                code = sess.get("exit_code")
            sess["status"] = "done" if code == 0 else "failed"
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
            sess["exit_code"] = _reap_exit_code(pid)
        code = sess.get("exit_code")
        if sess.get("status") not in ("done", "failed"):
            sess["status"] = "done" if code == 0 else ("failed" if code not in (None, 0) else "done")
            sess["status_authority"] = "process"
            sess["updated_at"] = _now()
        return sess

    # No pid yet
    if sess.get("status") is None:
        sess["status"] = "idle"
    return sess


def _reap_exit_code(pid: int) -> Optional[int]:
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


def list_sessions(*, refresh: bool = True) -> List[Dict[str, Any]]:
    data = _load()
    out: List[Dict[str, Any]] = []
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
    out.sort(key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
    return out


def get_session(key: str, *, refresh: bool = True) -> Optional[Dict[str, Any]]:
    data = _load()
    sess = data["sessions"].get(key)
    if not sess:
        # resolve by label (exact, then unique prefix)
        matches = [
            s for s in data["sessions"].values() if s.get("label") == key or s.get("id") == key
        ]
        if not matches:
            matches = [
                s
                for s in data["sessions"].values()
                if str(s.get("label", "")).startswith(key) or str(s.get("id", "")).startswith(key)
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
    cwd: Optional[str] = None,
    note: str = "",
    kind: str = "process",
) -> Dict[str, Any]:
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
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if not argv:
        raise ValueError("argv required")
    data = _load()
    sess = get_session(key, refresh=True)
    if not sess:
        raise KeyError(f"session not found: {key}")
    if sess.get("error"):
        raise ValueError(f"ambiguous session: {sess.get('matches')}")
    if sess.get("alive"):
        raise RuntimeError(f"session {sess['id']} already running (pid {sess.get('pid')})")

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

    proc = subprocess.Popen(
        list(argv),
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

    sess["cmd"] = list(argv)
    sess["cwd"] = work
    sess["pid"] = proc.pid
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
    note: Optional[str] = None,
) -> Dict[str, Any]:
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


def read_log(key: str, *, lines: int = 40) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    deadline = time.time() + max(0.1, timeout_s)
    last: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        last = get_session(key, refresh=True)
        if not last or last.get("error"):
            raise KeyError(f"session not found: {key}")
        if last.get("status") == status:
            return {"matched": True, "session": last, "waited_for": status}
        # Convenience: waiting for "done" also accepts "failed" as terminal? No —
        # Herdr keeps them distinct. Callers pick explicitly.
        time.sleep(poll_s)
    return {"matched": False, "session": last, "waited_for": status, "timeout_s": timeout_s}


def close_session(key: str, *, force: bool = False, kill: bool = False) -> Dict[str, Any]:
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


def summary() -> Dict[str, Any]:
    sessions = list_sessions(refresh=True)
    counts = {s: 0 for s in STATUSES}
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


def herdr_available() -> Dict[str, Any]:
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
