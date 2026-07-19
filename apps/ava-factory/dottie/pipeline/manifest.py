"""SQLite-backed manifest: the single source of truth for every shard.

Why SQLite and not Redis/Kafka: this is a single host. SQLite in WAL mode with
`BEGIN IMMEDIATE` gives us atomic claims across processes and containers (the
DB lives on a shared named volume) with no extra service to run or babysit.

Concurrency contract
--------------------
`claim()` is the only way to take ownership of a shard. It is atomic: N
concurrent claimers over M shards produce exactly M claims, never a double
claim and never a lost shard. This is enforced by doing the SELECT and the
UPDATE inside one `BEGIN IMMEDIATE` transaction, which takes the write lock
up front and so cannot interleave with another claimer's read.

Claims are *leased*, not permanent. A worker that dies mid-shard leaves the row
in a CLAIMED_* state with an expired `lease_expires_at`; `requeue_expired()`
returns it to the prior state so another worker picks it up. This is what makes
`docker kill` on a curator safe.

State machine (enforced by _LEGAL_TRANSITIONS; illegal moves raise):

    RAW ──claim(curate)──> CLAIMED_CURATE ──complete──> PACKED
     ▲                          │                         │
     └────requeue (lease)───────┘                    claim(train)
                                                          │
                                                          ▼
    DELETED <──janitor── CONSUMED <──complete── CLAIMED_TRAIN
                                                          │
     FAILED <──fail() from any CLAIMED_* after max_attempts┘

Splits: `val` and `test` shards are terminal at PACKED. They are never trained
on, never consumed, and the janitor must never delete them.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

# ---------------------------------------------------------------------------
# States

RAW = "RAW"
CLAIMED_CURATE = "CLAIMED_CURATE"
PACKED = "PACKED"
CLAIMED_TRAIN = "CLAIMED_TRAIN"
CONSUMED = "CONSUMED"
DELETED = "DELETED"
FAILED = "FAILED"

#: stage -> (claimable_from, claimed_state, completed_state)
STAGES = {
    "curate": (RAW, CLAIMED_CURATE, PACKED),
    "train": (PACKED, CLAIMED_TRAIN, CONSUMED),
}

_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    RAW: frozenset({CLAIMED_CURATE, FAILED, DELETED}),  # DELETED: T10.9 janitor eviction
    CLAIMED_CURATE: frozenset({PACKED, RAW, FAILED}),  # -> RAW on lease requeue
    PACKED: frozenset({CLAIMED_TRAIN, FAILED, DELETED}),
    CLAIMED_TRAIN: frozenset({CONSUMED, PACKED, FAILED}),  # -> PACKED on requeue
    CONSUMED: frozenset({DELETED}),
    DELETED: frozenset(),
    FAILED: frozenset({RAW}),  # manual retry
}

#: splits that must never be trained on or deleted
PROTECTED_SPLITS = frozenset({"val", "test"})

DEFAULT_LEASE_SECONDS = 900
DEFAULT_MAX_ATTEMPTS = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shards (
    id                TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    phase             INTEGER NOT NULL,
    split             TEXT NOT NULL DEFAULT 'train',
    state             TEXT NOT NULL,
    path              TEXT,
    bytes             INTEGER DEFAULT 0,
    tokens            INTEGER DEFAULT 0,
    docs              INTEGER DEFAULT 0,
    sha256            TEXT,
    tokenizer_sha     TEXT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    claimed_by        TEXT,
    lease_expires_at  REAL,
    error             TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);

-- The claim hot path: WHERE state=? AND phase IN (...) ORDER BY created_at.
CREATE INDEX IF NOT EXISTS idx_shards_claim ON shards (state, phase, created_at);
CREATE INDEX IF NOT EXISTS idx_shards_lease ON shards (state, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_shards_split ON shards (split, state);

-- Resumable per-source cursors so a killed collector doesn't re-emit docs.
CREATE TABLE IF NOT EXISTS cursors (
    source      TEXT PRIMARY KEY,
    position    TEXT NOT NULL,
    docs_seen   INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    preset      TEXT,
    started_at  REAL,
    step        INTEGER DEFAULT 0,
    phase       INTEGER DEFAULT 0,
    status      TEXT,
    updated_at  REAL
);

CREATE TABLE IF NOT EXISTS metrics (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts     REAL NOT NULL,
    key    TEXT NOT NULL,
    value  REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_run ON metrics (run_id, key, ts);

-- Single-row table guarding the frozen tokenizer (see Stage 5 freeze gate).
CREATE TABLE IF NOT EXISTS tokenizer (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    sha256      TEXT NOT NULL,
    vocab_size  INTEGER NOT NULL,
    frozen_at   REAL NOT NULL
);
"""


class StateError(RuntimeError):
    """An illegal state transition was attempted."""


class TokenizerMismatch(RuntimeError):
    """Packing attempted against a tokenizer other than the frozen one."""


@dataclass(frozen=True)
class Shard:
    id: str
    source: str
    phase: int
    split: str
    state: str
    path: str | None
    bytes: int
    tokens: int
    docs: int
    attempts: int

    @classmethod
    def _from_row(cls, r: sqlite3.Row) -> "Shard":
        return cls(
            id=r["id"], source=r["source"], phase=r["phase"], split=r["split"],
            state=r["state"], path=r["path"], bytes=r["bytes"],
            tokens=r["tokens"], docs=r["docs"], attempts=r["attempts"],
        )


def worker_id() -> str:
    """Stable-per-process identity: container hostname + pid + random suffix."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class Manifest:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        timeout: float = 30.0,
    ) -> None:
        self.db_path = str(db_path or os.environ.get("AVA_STATE_DB", "/state/manifest.db"))
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # isolation_level=None -> we drive transactions explicitly. Without this,
        # sqlite3 opens an implicit DEFERRED transaction and BEGIN IMMEDIATE
        # inside claim() would raise "cannot start a transaction within a
        # transaction".
        self.db = sqlite3.connect(self.db_path, timeout=timeout, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        # Wait rather than immediately raising SQLITE_BUSY under contention.
        self.db.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- transactions -------------------------------------------------------

    @contextlib.contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        """Take the write lock up front, so read-then-write cannot interleave."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    # -- registration -------------------------------------------------------

    def add_shard(
        self,
        shard_id: str,
        *,
        source: str,
        phase: int,
        path: str,
        split: str = "train",
        bytes_: int = 0,
        docs: int = 0,
        sha256: str | None = None,
        state: str = RAW,
    ) -> bool:
        """Register a shard. Returns False if it already exists (idempotent).

        Idempotency is what makes collector restarts safe: a shard written but
        not registered before a crash is re-registered; one already registered
        is a no-op rather than a duplicate.
        """
        now = time.time()
        with self._immediate() as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO shards
                   (id, source, phase, split, state, path, bytes, docs, sha256,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (shard_id, source, phase, split, state, path, bytes_, docs, sha256, now, now),
            )
            return cur.rowcount > 0

    # -- claiming -----------------------------------------------------------

    def claim(
        self,
        stage: str,
        *,
        by: str,
        phases: Sequence[int] | None = None,
        splits: Sequence[str] | None = None,
    ) -> Shard | None:
        """Atomically claim one shard for `stage`, or return None if none ready.

        The SELECT and UPDATE run inside one BEGIN IMMEDIATE, so two concurrent
        claimers cannot both see the same row as unclaimed.
        """
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected {sorted(STAGES)}")
        from_state, claimed_state, _ = STAGES[stage]

        # The trainer must never consume val/test.
        if stage == "train" and splits is None:
            splits = ("train",)

        where = ["state = ?"]
        params: list[object] = [from_state]
        if phases:
            where.append(f"phase IN ({','.join('?' * len(phases))})")
            params.extend(phases)
        if splits:
            where.append(f"split IN ({','.join('?' * len(splits))})")
            params.extend(splits)
        where.append("attempts < ?")
        params.append(self.max_attempts)

        now = time.time()
        with self._immediate() as db:
            row = db.execute(
                f"SELECT * FROM shards WHERE {' AND '.join(where)} "
                f"ORDER BY phase ASC, created_at ASC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None

            self._assert_legal(row["state"], claimed_state)
            db.execute(
                """UPDATE shards
                      SET state=?, claimed_by=?, lease_expires_at=?,
                          attempts=attempts+1, updated_at=?
                    WHERE id=?""",
                (claimed_state, by, now + self.lease_seconds, now, row["id"]),
            )
            updated = db.execute("SELECT * FROM shards WHERE id=?", (row["id"],)).fetchone()
            return Shard._from_row(updated)

    def renew(self, shard_id: str, *, by: str) -> bool:
        """Extend a lease on a long-running shard. False if we no longer own it."""
        with self._immediate() as db:
            cur = db.execute(
                "UPDATE shards SET lease_expires_at=?, updated_at=? "
                "WHERE id=? AND claimed_by=?",
                (time.time() + self.lease_seconds, time.time(), shard_id, by),
            )
            return cur.rowcount > 0

    def complete(
        self,
        shard_id: str,
        *,
        by: str,
        path: str | None = None,
        tokens: int = 0,
        docs: int = 0,
        split: str | None = None,
        tokenizer_sha: str | None = None,
        bytes_: int | None = None,
    ) -> None:
        """Advance a claimed shard to its stage's completed state.

        Only the lease holder may complete. A worker whose lease expired and was
        requeued will find `claimed_by` changed and raise, rather than silently
        clobbering the shard another worker is now processing.
        """
        with self._immediate() as db:
            row = db.execute("SELECT * FROM shards WHERE id=?", (shard_id,)).fetchone()
            if row is None:
                raise KeyError(shard_id)
            if row["claimed_by"] != by:
                raise StateError(
                    f"{shard_id}: lease held by {row['claimed_by']!r}, not {by!r} "
                    "(lease likely expired and was requeued)"
                )

            target = {CLAIMED_CURATE: PACKED, CLAIMED_TRAIN: CONSUMED}.get(row["state"])
            if target is None:
                raise StateError(f"{shard_id}: cannot complete from {row['state']}")
            self._assert_legal(row["state"], target)

            if tokenizer_sha is not None:
                self._assert_tokenizer(db, tokenizer_sha)

            db.execute(
                """UPDATE shards
                      SET state=?, claimed_by=NULL, lease_expires_at=NULL,
                          path=COALESCE(?, path), tokens=COALESCE(NULLIF(?,0), tokens),
                          docs=COALESCE(NULLIF(?,0), docs), split=COALESCE(?, split),
                          tokenizer_sha=COALESCE(?, tokenizer_sha),
                          bytes=COALESCE(?, bytes), error=NULL, updated_at=?,
                          attempts=CASE WHEN ?=? THEN 0 ELSE attempts END
                    WHERE id=?""",
                (target, path, tokens, docs, split, tokenizer_sha, bytes_, time.time(),
                 target, PACKED, shard_id),
            )

    def fail(self, shard_id: str, *, by: str, error: str) -> str:
        """Record a failure. Returns the resulting state.

        Below max_attempts the shard goes back to its origin state for retry;
        at the limit it is parked in FAILED so a poison shard cannot spin
        forever.
        """
        with self._immediate() as db:
            row = db.execute("SELECT * FROM shards WHERE id=?", (shard_id,)).fetchone()
            if row is None:
                raise KeyError(shard_id)

            origin = {CLAIMED_CURATE: RAW, CLAIMED_TRAIN: PACKED}.get(row["state"], row["state"])
            target = FAILED if row["attempts"] >= self.max_attempts else origin
            self._assert_legal(row["state"], target)
            db.execute(
                """UPDATE shards SET state=?, claimed_by=NULL, lease_expires_at=NULL,
                          error=?, updated_at=? WHERE id=?""",
                (target, error[:2000], time.time(), shard_id),
            )
            return target

    def release_claim(self, shard_id: str, *, by: str, note: str = "") -> str:
        """Hand a claimed shard back, unprocessed. NOT a failure.

        Distinct from `fail()`: releasing does not increment `attempts`, because
        a clean handback (a trainer shutting down mid-shard) is not evidence the
        shard is poison. Using fail() here would park a perfectly good shard in
        FAILED after three ordinary restarts.
        """
        with self._immediate() as db:
            row = db.execute("SELECT * FROM shards WHERE id=?", (shard_id,)).fetchone()
            if row is None:
                raise KeyError(shard_id)
            if row["claimed_by"] != by:
                raise StateError(f"{shard_id}: not held by {by!r}")
            origin = {CLAIMED_CURATE: RAW, CLAIMED_TRAIN: PACKED}.get(row["state"])
            if origin is None:
                raise StateError(f"{shard_id}: cannot release from {row['state']}")
            self._assert_legal(row["state"], origin)
            db.execute(
                """UPDATE shards SET state=?, claimed_by=NULL, lease_expires_at=NULL,
                          attempts=MAX(0, attempts-1), error=?, updated_at=? WHERE id=?""",
                (origin, note or None, time.time(), shard_id),
            )
            return origin

    def requeue_expired(self) -> list[str]:
        """Return shards whose lease lapsed to their origin state. Returns ids."""
        now = time.time()
        with self._immediate() as db:
            rows = db.execute(
                "SELECT id, state FROM shards "
                "WHERE state IN (?,?) AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
                (CLAIMED_CURATE, CLAIMED_TRAIN, now),
            ).fetchall()
            ids = []
            for r in rows:
                origin = RAW if r["state"] == CLAIMED_CURATE else PACKED
                db.execute(
                    """UPDATE shards SET state=?, claimed_by=NULL, lease_expires_at=NULL,
                              error='lease expired', updated_at=? WHERE id=?""",
                    (origin, now, r["id"]),
                )
                ids.append(r["id"])
            return ids

    def mark_deleted(self, shard_ids: Sequence[str]) -> int:
        """Janitor: RAW|PACKED|CONSUMED -> DELETED. Refuses protected splits."""
        if not shard_ids:
            return 0
        with self._immediate() as db:
            placeholders = ",".join("?" * len(shard_ids))
            rows = db.execute(
                f"SELECT id, state, split FROM shards WHERE id IN ({placeholders})",
                list(shard_ids),
            ).fetchall()
            n = 0
            for r in rows:
                if r["split"] in PROTECTED_SPLITS:
                    raise StateError(f"{r['id']}: refusing to delete protected split {r['split']!r}")
                self._assert_legal(r["state"], DELETED)
                db.execute(
                    "UPDATE shards SET state=?, path=NULL, updated_at=? WHERE id=?",
                    (DELETED, time.time(), r["id"]),
                )
                n += 1
            return n

    # -- queries used by flow control ---------------------------------------

    def counts_by_state(self) -> dict[str, int]:
        rows = self.db.execute("SELECT state, COUNT(*) c FROM shards GROUP BY state").fetchall()
        return {r["state"]: r["c"] for r in rows}

    def tokens_ready(self, phase: int, *, split: str = "train") -> int:
        """Packed-but-unconsumed tokens for a phase: the trainer's runway."""
        r = self.db.execute(
            "SELECT COALESCE(SUM(tokens),0) t FROM shards "
            "WHERE state=? AND phase=? AND split=?",
            (PACKED, phase, split),
        ).fetchone()
        return int(r["t"])

    def raw_bytes(self) -> int:
        r = self.db.execute(
            "SELECT COALESCE(SUM(bytes),0) b FROM shards WHERE state IN (?,?)",
            (RAW, CLAIMED_CURATE),
        ).fetchone()
        return int(r["b"])

    def consumed_shards(self, limit: int = 100) -> list[Shard]:
        rows = self.db.execute(
            "SELECT * FROM shards WHERE state=? AND split NOT IN (?,?) "
            "ORDER BY updated_at ASC LIMIT ?",
            (CONSUMED, *sorted(PROTECTED_SPLITS), limit),
        ).fetchall()
        return [Shard._from_row(r) for r in rows]

    # -- cursors ------------------------------------------------------------

    def get_cursor(self, source: str) -> tuple[str | None, int]:
        r = self.db.execute("SELECT position, docs_seen FROM cursors WHERE source=?", (source,)).fetchone()
        return (r["position"], r["docs_seen"]) if r else (None, 0)

    def set_cursor(self, source: str, position: str, docs_seen: int) -> None:
        with self._immediate() as db:
            db.execute(
                """INSERT INTO cursors (source, position, docs_seen, updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(source) DO UPDATE SET
                     position=excluded.position, docs_seen=excluded.docs_seen,
                     updated_at=excluded.updated_at""",
                (source, position, docs_seen, time.time()),
            )

    # -- tokenizer freeze gate ----------------------------------------------

    def freeze_tokenizer(self, sha256: str, vocab_size: int) -> None:
        with self._immediate() as db:
            existing = db.execute("SELECT sha256 FROM tokenizer WHERE id=1").fetchone()
            if existing and existing["sha256"] != sha256:
                raise TokenizerMismatch(
                    f"tokenizer already frozen at {existing['sha256'][:12]}; "
                    f"refusing to re-freeze at {sha256[:12]}. Packed shards would be invalid."
                )
            db.execute(
                "INSERT OR REPLACE INTO tokenizer (id, sha256, vocab_size, frozen_at) VALUES (1,?,?,?)",
                (sha256, vocab_size, time.time()),
            )

    def abandon_claims(self) -> list[str]:
        """Maintenance: release all live claims (workers must be stopped).

        CLAIMED_CURATE → RAW, CLAIMED_TRAIN → PACKED. Returns released ids.
        """
        now = time.time()
        with self._immediate() as db:
            rows = db.execute(
                "SELECT id, state FROM shards WHERE state IN (?,?)",
                (CLAIMED_CURATE, CLAIMED_TRAIN),
            ).fetchall()
            ids: list[str] = []
            for r in rows:
                origin = RAW if r["state"] == CLAIMED_CURATE else PACKED
                db.execute(
                    """UPDATE shards SET state=?, claimed_by=NULL, lease_expires_at=NULL,
                              error='abandoned for tokenizer cutover', updated_at=? WHERE id=?""",
                    (origin, now, r["id"]),
                )
                ids.append(r["id"])
            return ids

    def clear_tokenizer_for_retrain(self) -> dict[str, int]:
        """Drop the freeze after invalidating every tokenized shard.

        Marks PACKED + CONSUMED → DELETED (including val/test — old token ids
        are not hash-compatible with a new vocab). RAW is kept. Raises if any
        CLAIMED_* rows remain (call ``abandon_claims`` first). Caller must
        delete packed files on disk before ``freeze_tokenizer`` of a new sha.
        """
        with self._immediate() as db:
            claimed = db.execute(
                "SELECT COUNT(*) c FROM shards WHERE state IN (?,?)",
                (CLAIMED_CURATE, CLAIMED_TRAIN),
            ).fetchone()["c"]
            if claimed:
                raise StateError(
                    f"{claimed} CLAIMED_* shard(s) still live; stop workers and "
                    f"call abandon_claims() before clear_tokenizer_for_retrain()"
                )
            rows = db.execute(
                "SELECT id FROM shards WHERE state IN (?,?)",
                (PACKED, CONSUMED),
            ).fetchall()
            now = time.time()
            for r in rows:
                db.execute(
                    "UPDATE shards SET state=?, path=NULL, updated_at=? WHERE id=?",
                    (DELETED, now, r["id"]),
                )
            db.execute("DELETE FROM tokenizer")
            return {"deleted_tokenized": len(rows), "tokenizer_cleared": 1}

    def tokenizer_sha(self) -> str | None:
        r = self.db.execute("SELECT sha256 FROM tokenizer WHERE id=1").fetchone()
        return r["sha256"] if r else None

    @staticmethod
    def _assert_tokenizer(db: sqlite3.Connection, sha: str) -> None:
        r = db.execute("SELECT sha256 FROM tokenizer WHERE id=1").fetchone()
        if r is None:
            raise TokenizerMismatch("no tokenizer frozen; run `python -m dottie.tokenizer train` first")
        if r["sha256"] != sha:
            raise TokenizerMismatch(
                f"shard packed with tokenizer {sha[:12]} but frozen tokenizer is "
                f"{r['sha256'][:12]}. Packed data is not hash-compatible."
            )

    # -- run / metrics bookkeeping ------------------------------------------

    def upsert_run(self, run_id: str, *, preset: str, step: int, phase: int, status: str) -> None:
        with self._immediate() as db:
            db.execute(
                """INSERT INTO runs (run_id, preset, started_at, step, phase, status, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET
                     step=excluded.step, phase=excluded.phase,
                     status=excluded.status, updated_at=excluded.updated_at""",
                (run_id, preset, time.time(), step, phase, status, time.time()),
            )

    def log_metric(self, run_id: str, key: str, value: float) -> None:
        with self._immediate() as db:
            db.execute(
                "INSERT INTO metrics (run_id, ts, key, value) VALUES (?,?,?,?)",
                (run_id, time.time(), key, float(value)),
            )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _assert_legal(src: str, dst: str) -> None:
        if dst not in _LEGAL_TRANSITIONS.get(src, frozenset()):
            raise StateError(f"illegal transition {src} -> {dst}")


def _summary(db_path: str | None) -> int:
    with Manifest(db_path) as m:
        counts = m.counts_by_state()
        total = sum(counts.values())
        print(json.dumps({
            "db": m.db_path,
            "total_shards": total,
            "by_state": counts,
            "raw_bytes": m.raw_bytes(),
            "tokenizer_sha": (m.tokenizer_sha() or "")[:12] or None,
            "tokens_ready_by_phase": {p: m.tokens_ready(p) for p in range(6)},
        }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Dottie shard manifest")
    ap.add_argument("--db", default=None)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--requeue-expired", action="store_true")
    args = ap.parse_args()

    if args.requeue_expired:
        with Manifest(args.db) as m:
            ids = m.requeue_expired()
            print(f"requeued {len(ids)} expired lease(s)")
        return 0
    return _summary(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
