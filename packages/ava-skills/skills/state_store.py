"""
state_store.py — J-Space persistence engine: skills library, session context, task logs.

One SQLite database (WAL) behind three stores:

  skills_library   what `scout forge new/edit` created — code, schema, capabilities —
                   so the router and future sessions can discover capabilities without
                   re-reading the filesystem (Hermes: every solved task leaves a tool)
  session_context  persistent variables / execution flags keyed by session + channel,
                   surviving process restarts (OpenClaw: deep state across loops)
  task_logs        execution traces, policy checks, eval outcomes — the raw feed the
                   MLOps telemetry pipeline (dottie_telemetry.jsonl) aggregates

Placement is deliberate: this is core infrastructure BESIDE loader.py, not a skill dir —
skills consume it. The database lives OUTSIDE the repo by default (~/.dottie-claw/) so no
generated state can ever be committed; DOTTIE_STATE_DB overrides for tests and containers.

Solo personal project, no connection to employer, built with public/free-tier only.
Stdlib only (sqlite3, json) — no new dependencies.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import time
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills_library (
    name        TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    schema_json TEXT,
    capabilities TEXT NOT NULL DEFAULT '',      -- e.g. 'network,filesystem'
    source      TEXT NOT NULL DEFAULT 'forge',  -- forge | manual | import
    version     INTEGER NOT NULL DEFAULT 1,
    created_ts  REAL NOT NULL,
    updated_ts  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_context (
    session_id  TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'default',
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    updated_ts  REAL NOT NULL,
    PRIMARY KEY (session_id, channel, key)
);
CREATE TABLE IF NOT EXISTS task_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    task        TEXT NOT NULL,
    outcome     TEXT NOT NULL,                  -- ok | failed | refused | skipped
    trace_json  TEXT,
    policy_ok   INTEGER,                        -- NULL = not checked (honest tri-state)
    eval_score  REAL,                           -- NULL = not evaluated; NEVER defaulted
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_logs_session ON task_logs (session_id, ts);
CREATE INDEX IF NOT EXISTS idx_task_logs_ts ON task_logs (ts);
"""


def default_db_path() -> pathlib.Path:
    env = os.environ.get("DOTTIE_STATE_DB")
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / ".dottie-claw" / "state" / "jspace_state.sqlite3"


class JSpaceStateStore:
    """Thread-friendly facade over the three stores. One instance per process is fine;
    WAL mode lets concurrent processes (scout CLI + dottie engine) share the file."""

    def __init__(self, db_path: str | os.PathLike | None = None) -> None:
        self.path = pathlib.Path(db_path) if db_path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "JSpaceStateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- skills_library ------------------------------------------------------

    def register_skill(self, name: str, code: str, *, schema: Optional[Dict] = None,
                       capabilities: str = "", source: str = "forge") -> int:
        """Insert or version-bump a skill. Returns the stored version."""
        now = time.time()
        cur = self._conn.execute("SELECT version FROM skills_library WHERE name=?", (name,))
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO skills_library (name, code, schema_json, capabilities, source,"
                " version, created_ts, updated_ts) VALUES (?,?,?,?,?,1,?,?)",
                (name, code, json.dumps(schema) if schema else None, capabilities,
                 source, now, now))
            version = 1
        else:
            version = int(row["version"]) + 1
            self._conn.execute(
                "UPDATE skills_library SET code=?, schema_json=?, capabilities=?, source=?,"
                " version=?, updated_ts=? WHERE name=?",
                (code, json.dumps(schema) if schema else None, capabilities, source,
                 version, now, name))
        self._conn.commit()
        return version

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM skills_library WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["schema"] = json.loads(d.pop("schema_json")) if d.get("schema_json") else None
        return d

    def list_skills(self, *, source: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT name, capabilities, source, version, updated_ts FROM skills_library"
        args: tuple = ()
        if source:
            q += " WHERE source=?"
            args = (source,)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY name", args)]

    # -- session_context (OpenClaw) -----------------------------------------

    def set_context(self, session_id: str, key: str, value: Any,
                    *, channel: str = "default") -> None:
        self._conn.execute(
            "INSERT INTO session_context (session_id, channel, key, value_json, updated_ts)"
            " VALUES (?,?,?,?,?) ON CONFLICT (session_id, channel, key)"
            " DO UPDATE SET value_json=excluded.value_json, updated_ts=excluded.updated_ts",
            (session_id, channel, key, json.dumps(value), time.time()))
        self._conn.commit()

    def get_context(self, session_id: str, key: str, default: Any = None,
                    *, channel: str = "default") -> Any:
        row = self._conn.execute(
            "SELECT value_json FROM session_context WHERE session_id=? AND channel=?"
            " AND key=?", (session_id, channel, key)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def session_snapshot(self, session_id: str) -> Dict[str, Dict[str, Any]]:
        """All channels and keys for a session — the cross-channel state OpenClaw
        loops re-enter with."""
        out: Dict[str, Dict[str, Any]] = {}
        for r in self._conn.execute(
                "SELECT channel, key, value_json FROM session_context WHERE session_id=?",
                (session_id,)):
            out.setdefault(r["channel"], {})[r["key"]] = json.loads(r["value_json"])
        return out

    # -- task_logs -----------------------------------------------------------

    def log_task(self, session_id: str, task: str, outcome: str, *,
                 trace: Optional[Dict] = None, policy_ok: Optional[bool] = None,
                 eval_score: Optional[float] = None) -> int:
        """Record one execution. eval_score/policy_ok stay NULL unless a real check ran —
        the anti-mock guard asserts no defaulted scores ever enter this table."""
        cur = self._conn.execute(
            "INSERT INTO task_logs (session_id, task, outcome, trace_json, policy_ok,"
            " eval_score, ts) VALUES (?,?,?,?,?,?,?)",
            (session_id, task, outcome, json.dumps(trace) if trace else None,
             None if policy_ok is None else int(policy_ok), eval_score, time.time()))
        self._conn.commit()
        return int(cur.lastrowid)

    def recent_tasks(self, limit: int = 50,
                     session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM task_logs"
        args: tuple = ()
        if session_id:
            q += " WHERE session_id=?"
            args = (session_id,)
        q += " ORDER BY ts DESC LIMIT ?"
        rows = self._conn.execute(q, args + (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["trace"] = json.loads(d.pop("trace_json")) if d.get("trace_json") else None
            out.append(d)
        return out

    def task_stats(self) -> Dict[str, Any]:
        by_outcome = {r["outcome"]: r["n"] for r in self._conn.execute(
            "SELECT outcome, COUNT(*) AS n FROM task_logs GROUP BY outcome")}
        scored = self._conn.execute(
            "SELECT COUNT(*) AS n, AVG(eval_score) AS avg FROM task_logs"
            " WHERE eval_score IS NOT NULL").fetchone()
        return {"by_outcome": by_outcome, "total": sum(by_outcome.values()),
                "evaluated": int(scored["n"]),
                "avg_eval_score": scored["avg"]}      # None when nothing evaluated — honest

    # -- telemetry feed ------------------------------------------------------

    def export_telemetry(self, path: str | os.PathLike, *,
                         since_ts: float = 0.0) -> int:
        """Append task_logs newer than since_ts as JSONL records (the format
        reports/dottie_telemetry.jsonl aggregates). Returns records written."""
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with p.open("a", encoding="utf-8") as fh:
            for r in self._conn.execute(
                    "SELECT * FROM task_logs WHERE ts > ? ORDER BY ts", (since_ts,)):
                rec = {"ts": r["ts"], "event": "task", "service": "jspace-state",
                       "session": r["session_id"], "task": r["task"],
                       "outcome": r["outcome"], "policy_ok": r["policy_ok"],
                       "eval_score": r["eval_score"]}
                fh.write(json.dumps(rec) + "\n")
                n += 1
        return n
