"""Shared state (spec §3): one SQLite file, WAL mode, FTS5 with a LIKE fallback.

Thread model: one connection opened with `check_same_thread=False`, every
public method holds `self._lock`. uvicorn's threadpool, FastMCP's tool runner
and the CLI `export` command all go through the same door.

Public surface (the brain worker codes against these names — keep them stable):

    remember(agent, scope, text, tags=None, source="")      -> dict
    recall(query, scope=None, limit=10)                       -> list[dict]
    claim(agent, repo, area, note="")                         -> dict  (raises ClaimConflictError)
    release(agent, repo, area, force=False)                   -> dict  (raises ClaimConflictError)
    claims(repo=None, include_released=False)                 -> list[dict]
    send(from_agent, to_agent, body)                          -> dict
    inbox(agent, mark_read=False, unread_only=True, limit=50) -> list[dict]
    unread_count(agent)                                       -> int
    add_goal(agent, repo, text)                               -> dict
    goals(repo=None, status="open", limit=100)                -> list[dict]
    goal_done(goal_id, result=None, status="done")            -> dict | None
    timeline_add(agent, repo, kind, payload=None)             -> dict
    timeline(repo=None, limit=10, kind=None)                  -> list[dict]
    touch_session(agent, repo)                                -> dict
    context(agent, repo)                                      -> dict
    counts()                                                  -> dict[str, int]
    export(table)                                             -> Iterator[dict]
    close()                                                   -> None
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

TABLES: tuple[str, ...] = (
    "memories",
    "claims",
    "messages",
    "goals",
    "timeline",
    "sessions",
)

GOAL_STATUSES: tuple[str, ...] = ("open", "done", "dropped")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    scope TEXT NOT NULL,
    text TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS memories_scope_ts ON memories(scope, ts);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    repo TEXT NOT NULL,
    area TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    released_ts TEXT
);
CREATE INDEX IF NOT EXISTS claims_active ON claims(repo, area, released_ts);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    body TEXT NOT NULL,
    read_ts TEXT
);
CREATE INDEX IF NOT EXISTS messages_to ON messages(to_agent, read_ts);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    repo TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    result TEXT
);
CREATE INDEX IF NOT EXISTS goals_repo_status ON goals(repo, status);

CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    repo TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS timeline_repo_ts ON timeline(repo, ts);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    repo TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(agent, repo)
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, content='memories', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-.]*")


class ClaimConflictError(RuntimeError):
    """Another agent holds the claim on this repo+area."""

    def __init__(self, holder: dict[str, Any]):
        self.holder = holder
        super().__init__(
            f"{holder['repo']}/{holder['area']} is claimed by {holder['agent']} "
            f"since {holder['ts']}"
        )


def now_iso() -> str:
    """UTC timestamp, second precision, `Z` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_scope(repo: str | None) -> str:
    """`repo:<name>` scope string, or `global` when no repo is given."""
    return f"repo:{repo}" if repo else "global"


def _loads(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class State:
    """The daemon's one SQLite store. Safe to share across threads."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self.fts_enabled = False
        self._migrate()

    # -- lifecycle ---------------------------------------------------------

    def _migrate(self) -> None:
        """Idempotent: safe to run on every boot against an existing file."""
        with self._lock:
            if str(self.path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            try:
                self._conn.executescript(_FTS_SCHEMA)
                self._conn.execute("SELECT count(*) FROM memories_fts")
                self.fts_enabled = True
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def close(self) -> None:
        """Close the connection. The object is unusable afterwards."""
        with self._lock:
            self._conn.close()

    # -- helpers -----------------------------------------------------------

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _memory(row: dict[str, Any]) -> dict[str, Any]:
        row["tags"] = _loads(row.get("tags"), [])
        return row

    @staticmethod
    def _goal(row: dict[str, Any]) -> dict[str, Any]:
        row["result"] = _loads(row.get("result"), None)
        return row

    @staticmethod
    def _event(row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = _loads(row.get("payload"), {})
        return row

    # -- memories ----------------------------------------------------------

    def remember(
        self,
        agent: str,
        scope: str,
        text: str,
        tags: list[str] | None = None,
        source: str = "",
    ) -> dict[str, Any]:
        """Insert one memory and return the stored row."""
        text = text.strip()
        if not text:
            raise ValueError("text is empty")
        scope = (scope or "global").strip()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO memories(ts, agent, scope, text, tags, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (now_iso(), agent, scope, text, json.dumps(list(tags or [])), source or ""),
            )
            row = self._row("SELECT * FROM memories WHERE id = ?", (cur.lastrowid,))
        assert row is not None
        return self._memory(row)

    def memories(self, scope: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Newest memories, optionally in one scope."""
        if scope:
            rows = self._rows(
                "SELECT * FROM memories WHERE scope = ? ORDER BY id DESC LIMIT ?",
                (scope, limit),
            )
        else:
            rows = self._rows("SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,))
        return [self._memory(r) for r in rows]

    def recall(
        self, query: str, scope: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Full-text search over memory text (FTS5 bm25, OR-of-terms).

        Falls back to a LIKE scan when FTS5 is unavailable. Returns newest
        first on the fallback path, best-match first on FTS.
        """
        terms = _TOKEN_RE.findall(query or "")
        if not terms:
            return self.memories(scope=scope, limit=limit)
        limit = max(1, int(limit))
        if self.fts_enabled:
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
            sql = (
                "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid "
                "WHERE memories_fts MATCH ?"
            )
            params: list[Any] = [match]
            if scope:
                sql += " AND m.scope = ?"
                params.append(scope)
            sql += " ORDER BY bm25(memories_fts), m.id DESC LIMIT ?"
            params.append(limit)
            try:
                return [self._memory(r) for r in self._rows(sql, tuple(params))]
            except sqlite3.OperationalError:
                pass  # malformed MATCH — fall through to LIKE
        clauses = " OR ".join("text LIKE ? ESCAPE '\\'" for _ in terms)
        params = [
            "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            for t in terms
        ]
        sql = f"SELECT * FROM memories WHERE ({clauses})"  # noqa: S608 — clauses are `?` placeholders
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [self._memory(r) for r in self._rows(sql, tuple(params))]

    # -- claims ------------------------------------------------------------

    def active_claim(self, repo: str, area: str) -> dict[str, Any] | None:
        """The live claim on repo+area, if any."""
        return self._row(
            "SELECT * FROM claims WHERE repo = ? AND area = ? AND released_ts IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (repo, area),
        )

    def claim(self, agent: str, repo: str, area: str, note: str = "") -> dict[str, Any]:
        """Claim repo+area for `agent`.

        Re-claiming your own area refreshes the note and is not a conflict.
        Raises `ClaimConflictError` when another agent holds it.
        """
        repo, area = repo.strip(), area.strip()
        if not repo or not area:
            raise ValueError("repo and area are required")
        with self._lock:
            held = self.active_claim(repo, area)
            if held is not None:
                if held["agent"] != agent:
                    raise ClaimConflictError(held)
                self._conn.execute(
                    "UPDATE claims SET note = ? WHERE id = ?", (note or held["note"], held["id"])
                )
                row = self._row("SELECT * FROM claims WHERE id = ?", (held["id"],))
                assert row is not None
                return row
            cur = self._conn.execute(
                "INSERT INTO claims(ts, agent, repo, area, note) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), agent, repo, area, note or ""),
            )
            row = self._row("SELECT * FROM claims WHERE id = ?", (cur.lastrowid,))
        assert row is not None
        return row

    def release(
        self, agent: str, repo: str, area: str, force: bool = False
    ) -> dict[str, Any]:
        """Release the live claim on repo+area.

        Only the holder may release unless `force=True`. Returns
        `{released: bool, claim: row | None}`.
        """
        with self._lock:
            held = self.active_claim(repo.strip(), area.strip())
            if held is None:
                return {"released": False, "claim": None}
            if held["agent"] != agent and not force:
                raise ClaimConflictError(held)
            self._conn.execute(
                "UPDATE claims SET released_ts = ? WHERE id = ?", (now_iso(), held["id"])
            )
            row = self._row("SELECT * FROM claims WHERE id = ?", (held["id"],))
        return {"released": True, "claim": row}

    def claims(
        self, repo: str | None = None, include_released: bool = False
    ) -> list[dict[str, Any]]:
        """Claim board: active claims (newest first), optionally for one repo."""
        sql = "SELECT * FROM claims"
        where: list[str] = []
        params: list[Any] = []
        if not include_released:
            where.append("released_ts IS NULL")
        if repo:
            where.append("repo = ?")
            params.append(repo)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC"
        return self._rows(sql, tuple(params))

    # -- messages ----------------------------------------------------------

    def send(self, from_agent: str, to_agent: str, body: str) -> dict[str, Any]:
        """Queue a message for `to_agent`."""
        to_agent = to_agent.strip()
        body = body.strip()
        if not to_agent or not body:
            raise ValueError("to and body are required")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(ts, from_agent, to_agent, body) VALUES (?, ?, ?, ?)",
                (now_iso(), from_agent, to_agent, body),
            )
            row = self._row("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,))
        assert row is not None
        return row

    def inbox(
        self,
        agent: str,
        mark_read: bool = False,
        unread_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Messages addressed to `agent`, oldest first; optionally mark them read."""
        sql = "SELECT * FROM messages WHERE to_agent = ?"
        params: list[Any] = [agent]
        if unread_only:
            sql += " AND read_ts IS NULL"
        sql += " ORDER BY id ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._rows(sql, tuple(params))
            if mark_read and rows:
                ts = now_iso()
                ids = [r["id"] for r in rows if r["read_ts"] is None]
                if ids:
                    marks = ",".join("?" for _ in ids)
                    self._conn.execute(
                        f"UPDATE messages SET read_ts = ? WHERE id IN ({marks})",  # noqa: S608
                        (ts, *ids),
                    )
                    for r in rows:
                        if r["id"] in ids:
                            r["read_ts"] = ts
        return rows

    def unread_count(self, agent: str) -> int:
        """Number of unread messages for `agent`."""
        row = self._row(
            "SELECT count(*) AS n FROM messages WHERE to_agent = ? AND read_ts IS NULL",
            (agent,),
        )
        return int(row["n"]) if row else 0

    # -- goals -------------------------------------------------------------

    def add_goal(self, agent: str, repo: str, text: str) -> dict[str, Any]:
        """Open a goal on `repo`."""
        text = text.strip()
        if not text:
            raise ValueError("text is empty")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO goals(ts, agent, repo, text, status) VALUES (?, ?, ?, ?, 'open')",
                (now_iso(), agent, repo or "", text),
            )
            row = self._row("SELECT * FROM goals WHERE id = ?", (cur.lastrowid,))
        assert row is not None
        return self._goal(row)

    def goals(
        self, repo: str | None = None, status: str | None = "open", limit: int = 100
    ) -> list[dict[str, Any]]:
        """Goals, newest first. `status=None` returns every status."""
        sql = "SELECT * FROM goals"
        where: list[str] = []
        params: list[Any] = []
        if repo:
            where.append("repo = ?")
            params.append(repo)
        if status:
            where.append("status = ?")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [self._goal(r) for r in self._rows(sql, tuple(params))]

    def goal_done(
        self, goal_id: int, result: Any = None, status: str = "done"
    ) -> dict[str, Any] | None:
        """Close a goal (`done` or `dropped`) with an optional JSON result."""
        if status not in GOAL_STATUSES:
            raise ValueError(f"status must be one of {GOAL_STATUSES}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE goals SET status = ?, result = ? WHERE id = ?",
                (status, json.dumps(result) if result is not None else None, int(goal_id)),
            )
            if cur.rowcount == 0:
                return None
            row = self._row("SELECT * FROM goals WHERE id = ?", (int(goal_id),))
        return self._goal(row) if row else None

    # -- timeline ----------------------------------------------------------

    def timeline_add(
        self, agent: str, repo: str, kind: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Append one event (harness run, route, brain turn, ...)."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO timeline(ts, agent, repo, kind, payload) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), agent, repo or "", kind, json.dumps(payload or {}, default=str)),
            )
            row = self._row("SELECT * FROM timeline WHERE id = ?", (cur.lastrowid,))
        assert row is not None
        return self._event(row)

    def timeline(
        self, repo: str | None = None, limit: int = 10, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Newest events, optionally filtered by repo and/or kind."""
        sql = "SELECT * FROM timeline"
        where: list[str] = []
        params: list[Any] = []
        if repo:
            where.append("repo = ?")
            params.append(repo)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [self._event(r) for r in self._rows(sql, tuple(params))]

    # -- sessions / context -----------------------------------------------

    def touch_session(self, agent: str, repo: str) -> dict[str, Any]:
        """Upsert the (agent, repo) session row and bump `last_seen`."""
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(ts, agent, repo, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(agent, repo) DO UPDATE SET last_seen = excluded.last_seen",
                (ts, agent, repo or "", ts),
            )
            row = self._row(
                "SELECT * FROM sessions WHERE agent = ? AND repo = ?", (agent, repo or "")
            )
        assert row is not None
        return row

    def context(self, agent: str, repo: str | None) -> dict[str, Any]:
        """What `agent` should know about `repo` right now (spec §4 `jarvis.context`)."""
        scope = repo_scope(repo)
        with self._lock:
            self.touch_session(agent, repo or "")
            return {
                "agent": agent,
                "repo": repo,
                "scope": scope,
                "claims": self.claims(repo=repo),
                "goals": self.goals(repo=repo, status="open", limit=50),
                "memories": self.memories(scope=scope, limit=10),
                "timeline": self.timeline(repo=repo, limit=10),
                "unread": self.unread_count(agent),
            }

    # -- export / stats ----------------------------------------------------

    def counts(self) -> dict[str, int]:
        """Row count per table."""
        out: dict[str, int] = {}
        for t in TABLES:
            row = self._row(f"SELECT count(*) AS n FROM {t}")  # noqa: S608
            out[t] = int(row["n"]) if row else 0
        return out

    def export(self, table: str) -> Iterator[dict[str, Any]]:
        """Iterate every row of `table` as a dict (the JSONL view of the store)."""
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}; one of {TABLES}")
        decode = {"memories": self._memory, "goals": self._goal, "timeline": self._event}.get(
            table, lambda r: r
        )
        for row in self._rows(f"SELECT * FROM {table} ORDER BY id ASC"):  # noqa: S608
            yield decode(row)


__all__ = [
    "GOAL_STATUSES",
    "TABLES",
    "ClaimConflictError",
    "State",
    "now_iso",
    "repo_scope",
]
