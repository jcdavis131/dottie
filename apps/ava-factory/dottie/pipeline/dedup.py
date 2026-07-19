"""Exact + near-duplicate detection, persistent across shards and replicas.

Dedup state must be **global and durable**: multiple curator replicas run
concurrently, and a doc seen in shard A must be recognized as a duplicate when
it reappears in shard B processed by a different container. So the index lives
in its own SQLite database (``/state/dedup.db``, WAL mode) — the same
shared-volume, single-writer-at-a-time discipline the manifest uses.

Why hand-rolled LSH banding instead of ``datasketch.MinHashLSH``
----------------------------------------------------------------
``MinHashLSH`` only persists to Redis/Cassandra; its default storage is an
in-process dict that evaporates between shards and is invisible to other
replicas. We keep ``datasketch.MinHash`` (for the signature) but persist the
banding ourselves in SQLite: a ``lsh`` table of ``(band, bucket, doc_id)`` gives
us the candidate lookup, and a ``sigs`` table lets us verify a candidate's true
estimated Jaccard before calling it a duplicate — which is what buys the high
precision the tests demand.

Concurrency contract
--------------------
``add_if_new`` runs its check-and-insert inside one ``BEGIN IMMEDIATE``
transaction. IMMEDIATE grabs the write lock up front, so two replicas racing to
add the same duplicate are serialized: the first inserts, the second sees it and
returns False. No pair of concurrent callers can both accept the same doc.

Reprocess safety
----------------
Keyed by ``doc_id``. If a ``doc_id`` is already in the index we return True
without re-inserting: that means this exact doc is being re-curated (e.g. a shard
whose lease expired and was requeued after a crash), and it must flow through
packing again rather than being dropped as a "duplicate of itself". Genuinely
duplicated *text* collides on ``doc_id`` too (``doc_id = source:sha1(text)``), so
this never lets a real duplicate through.
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import numpy as np
from datasketch import MinHash
from datasketch.lsh import _optimal_param

from dottie.pipeline.clean import normalize

SHINGLE_K = 5  # word-level 5-grams


def exact_hash(text: str) -> str:
    """sha256 of the *normalized* text — the cheap exact-duplicate key."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _shingles(text: str) -> list[bytes]:
    """5-gram word shingles (encoded). Falls back to the whole doc when short."""
    words = normalize(text).lower().split()
    if len(words) < SHINGLE_K:
        return [" ".join(words).encode("utf-8")] if words else [b""]
    return [" ".join(words[i : i + SHINGLE_K]).encode("utf-8") for i in range(len(words) - SHINGLE_K + 1)]


def _minhash(text: str, num_perm: int) -> MinHash:
    mh = MinHash(num_perm=num_perm)
    for sh in _shingles(text):
        mh.update(sh)
    return mh


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sigs (
    doc_id TEXT PRIMARY KEY,
    sig    BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS exact (
    hash   TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lsh (
    band   INTEGER NOT NULL,
    bucket TEXT NOT NULL,
    doc_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lsh_bucket ON lsh (band, bucket);
"""


class MinHashDeduper:
    """Persistent exact + MinHash-LSH near-duplicate filter.

    Parameters mirror the ``curator:`` config block: ``num_perm`` (128) and
    ``threshold`` (0.8 Jaccard). The number of bands/rows is chosen by
    datasketch's optimal-parameter search for that threshold.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        num_perm: int = 128,
        threshold: float = 0.8,
        timeout: float = 60.0,
    ) -> None:
        import sqlite3

        self.db_path = str(db_path or os.environ.get("AVA_DEDUP_DB", "/state/dedup.db"))
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.num_perm = num_perm
        self.threshold = threshold
        # Optimal (bands, rows) minimizing weighted false pos/neg at threshold.
        self.n_bands, self.n_rows = _optimal_param(threshold, num_perm, 0.5, 0.5)

        self.db = sqlite3.connect(self.db_path, timeout=timeout, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # busy_timeout first, so the WAL-mode switch below waits out a peer
        # replica that happens to be mid-transaction when we open concurrently
        # (a WAL journal_mode change can return SQLITE_BUSY without honoring the
        # connect timeout in some sqlite builds; retry it explicitly).
        self.db.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        self._set_wal(timeout)
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)

    def _set_wal(self, timeout: float) -> None:
        import sqlite3
        import time as _time

        deadline = _time.time() + max(timeout, 1.0)
        while True:
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
                return
            except sqlite3.OperationalError:
                if _time.time() >= deadline:
                    raise
                _time.sleep(0.05)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "MinHashDeduper":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- banding helpers ----------------------------------------------------

    def _buckets(self, sig: np.ndarray) -> list[str]:
        """One bucket key per band: sha1 over that band's slice of the sig."""
        out = []
        for b in range(self.n_bands):
            lo = b * self.n_rows
            band = sig[lo : lo + self.n_rows]
            out.append(hashlib.sha1(band.tobytes()).hexdigest()[:16])
        return out

    @staticmethod
    def _estimate_jaccard(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.count_nonzero(a == b)) / float(len(a))

    # -- public API ---------------------------------------------------------

    def add_if_new(self, doc_id: str, text: str) -> bool:
        """Return True if ``text`` is new (and record it); False if duplicate.

        Order of checks: (0) reprocess of a known doc_id -> True; (1) exact
        normalized-hash match -> False; (2) MinHash-LSH candidate whose verified
        estimated Jaccard >= threshold -> False; else insert and return True.
        The whole sequence is one IMMEDIATE transaction for cross-replica safety.
        """
        mh = _minhash(text, self.num_perm)
        sig = mh.hashvalues.astype(np.uint64)
        sig_blob = sig.tobytes()
        ehash = exact_hash(text)
        buckets = self._buckets(sig)

        self.db.execute("BEGIN IMMEDIATE")
        try:
            # (0) reprocess safety: same doc coming back around.
            row = self.db.execute("SELECT 1 FROM sigs WHERE doc_id=?", (doc_id,)).fetchone()
            if row is not None:
                self.db.execute("COMMIT")
                return True

            # (1) exact duplicate (cheap).
            row = self.db.execute("SELECT 1 FROM exact WHERE hash=?", (ehash,)).fetchone()
            if row is not None:
                self.db.execute("COMMIT")
                return False

            # (2) near-duplicate via LSH candidates + Jaccard verification.
            candidate_ids: set[str] = set()
            for band, bucket in enumerate(buckets):
                rows = self.db.execute(
                    "SELECT doc_id FROM lsh WHERE band=? AND bucket=?", (band, bucket)
                ).fetchall()
                for r in rows:
                    candidate_ids.add(r["doc_id"])

            for cid in candidate_ids:
                r = self.db.execute("SELECT sig FROM sigs WHERE doc_id=?", (cid,)).fetchone()
                if r is None:
                    continue
                other = np.frombuffer(r["sig"], dtype=np.uint64)
                if len(other) == len(sig) and self._estimate_jaccard(sig, other) >= self.threshold:
                    self.db.execute("COMMIT")
                    return False

            # New doc: persist signature, exact hash, and band buckets.
            self.db.execute("INSERT OR IGNORE INTO sigs (doc_id, sig) VALUES (?,?)", (doc_id, sig_blob))
            self.db.execute("INSERT OR IGNORE INTO exact (hash, doc_id) VALUES (?,?)", (ehash, doc_id))
            self.db.executemany(
                "INSERT INTO lsh (band, bucket, doc_id) VALUES (?,?,?)",
                [(band, bucket, doc_id) for band, bucket in enumerate(buckets)],
            )
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
