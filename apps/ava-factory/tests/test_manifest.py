"""Manifest concurrency + state-machine tests.

The claim path is the one place where a subtle bug silently corrupts a training
run: a double claim means a shard is trained on twice, a lost shard means data
silently vanishes. These tests use real processes/threads against a real
on-disk SQLite file -- not mocks -- because the property under test is precisely
the cross-process locking behavior.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
from pathlib import Path

import pytest

from ava.pipeline.manifest import (
    CLAIMED_CURATE,
    CONSUMED,
    DELETED,
    FAILED,
    PACKED,
    RAW,
    Manifest,
    StateError,
    TokenizerMismatch,
    worker_id,
)

N_SHARDS = 1000
N_CLAIMERS = 12


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "manifest.db")


def _seed(db_path: str, n: int = N_SHARDS) -> None:
    with Manifest(db_path) as m:
        for i in range(n):
            m.add_shard(f"s{i:05d}", source="test", phase=i % 6, path=f"/raw/s{i:05d}.jsonl.zst",
                        bytes_=1000, docs=10)


# --------------------------------------------------------------------------
# The headline property: no double claims, no lost shards.

def _claim_loop(db_path: str, out: list) -> None:
    me = worker_id()
    got = []
    with Manifest(db_path, timeout=60.0) as m:
        while True:
            s = m.claim("curate", by=me)
            if s is None:
                break
            got.append(s.id)
    out.extend(got)


def test_concurrent_claims_no_double_no_loss(db_path):
    _seed(db_path)

    results: list[list[str]] = [[] for _ in range(N_CLAIMERS)]
    threads = [threading.Thread(target=_claim_loop, args=(db_path, results[i]))
               for i in range(N_CLAIMERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    claimed = [sid for r in results for sid in r]
    assert len(claimed) == len(set(claimed)), "a shard was claimed twice"
    assert len(claimed) == N_SHARDS, f"lost shards: got {len(claimed)}, want {N_SHARDS}"

    with Manifest(db_path) as m:
        assert m.counts_by_state() == {CLAIMED_CURATE: N_SHARDS}

    # work actually spread across claimers (not one thread winning every race)
    assert sum(1 for r in results if r) >= 2


def _proc_claim(db_path: str, q: mp.Queue) -> None:
    me = worker_id()
    got = []
    with Manifest(db_path, timeout=60.0) as m:
        while (s := m.claim("curate", by=me)) is not None:
            got.append(s.id)
    q.put(got)


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "spawn" and __name__ != "__main__",
                    reason="spawn re-imports; guarded below")
def test_cross_process_claims(db_path):
    """Same property across OS processes -- the real container topology."""
    _seed(db_path, n=200)
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    procs = [ctx.Process(target=_proc_claim, args=(db_path, q)) for _ in range(4)]
    for p in procs:
        p.start()
    claimed: list[str] = []
    for _ in procs:
        claimed.extend(q.get(timeout=120))
    for p in procs:
        p.join(timeout=30)

    assert len(claimed) == len(set(claimed)) == 200


# --------------------------------------------------------------------------
# Leases

def test_expired_lease_requeues(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path, lease_seconds=0) as m:
        s = m.claim("curate", by="dead-worker")
        assert s is not None and s.state == CLAIMED_CURATE
        assert m.claim("curate", by="other") is None  # still leased

        time.sleep(0.01)
        assert m.requeue_expired() == [s.id]

        again = m.claim("curate", by="live-worker")
        assert again is not None and again.id == s.id
        assert again.attempts == 2  # attempt counter survives the requeue


def test_completing_after_lease_stolen_raises(db_path):
    """A zombie worker must not clobber a shard someone else now owns."""
    _seed(db_path, n=1)
    with Manifest(db_path, lease_seconds=0) as m:
        s = m.claim("curate", by="zombie")
        m.requeue_expired()
        m.claim("curate", by="new-owner")

        with pytest.raises(StateError, match="lease held by"):
            m.complete(s.id, by="zombie", tokens=1)


def test_renew_extends_only_for_holder(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        s = m.claim("curate", by="me")
        assert m.renew(s.id, by="me") is True
        assert m.renew(s.id, by="someone-else") is False


# --------------------------------------------------------------------------
# State machine

def test_full_lifecycle(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        m.freeze_tokenizer("abc123", 8192)

        s = m.claim("curate", by="c1")
        m.complete(s.id, by="c1", path="/packed/s.bin", tokens=4096, tokenizer_sha="abc123")
        assert m.counts_by_state() == {PACKED: 1}
        assert m.tokens_ready(phase=0) == 4096

        t = m.claim("train", by="t1")
        assert t is not None and t.id == s.id
        m.complete(t.id, by="t1")
        assert m.counts_by_state() == {CONSUMED: 1}

        assert m.mark_deleted([s.id]) == 1
        assert m.counts_by_state() == {DELETED: 1}


def test_illegal_transition_rejected(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        # RAW shard cannot be claimed for training (must be PACKED first)
        assert m.claim("train", by="t1") is None


def test_failure_retries_then_parks(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path, max_attempts=2) as m:
        s = m.claim("curate", by="w")
        assert m.fail(s.id, by="w", error="boom") == RAW      # attempt 1 -> retry

        s = m.claim("curate", by="w")
        assert m.fail(s.id, by="w", error="boom") == FAILED   # attempt 2 -> parked

        assert m.claim("curate", by="w") is None              # poison shard not respun


# --------------------------------------------------------------------------
# Split protection: the trainer must never see val/test; janitor must not delete them.

def test_trainer_never_claims_val_or_test(db_path):
    with Manifest(db_path) as m:
        m.freeze_tokenizer("t", 8192)
        for split in ("train", "val", "test"):
            m.add_shard(f"s-{split}", source="x", phase=0, path=f"/p/{split}.bin",
                        split=split, state=PACKED)
            m.db.execute("UPDATE shards SET tokens=100 WHERE id=?", (f"s-{split}",))

        claimed = []
        while (s := m.claim("train", by="t")) is not None:
            claimed.append(s.split)
            m.complete(s.id, by="t")

        assert claimed == ["train"], f"trainer claimed protected splits: {claimed}"


def test_janitor_refuses_to_delete_protected_split(db_path):
    with Manifest(db_path) as m:
        m.add_shard("v1", source="x", phase=0, path="/p/v.bin", split="val", state=PACKED)
        m.db.execute("UPDATE shards SET state=? WHERE id='v1'", (CONSUMED,))
        with pytest.raises(StateError, match="protected split"):
            m.mark_deleted(["v1"])


def test_consumed_shards_excludes_protected(db_path):
    with Manifest(db_path) as m:
        for split in ("train", "val"):
            m.add_shard(f"c-{split}", source="x", phase=0, path="/p", split=split, state=PACKED)
            m.db.execute("UPDATE shards SET state=? WHERE id=?", (CONSUMED, f"c-{split}"))
        ids = [s.id for s in m.consumed_shards()]
        assert ids == ["c-train"]


# --------------------------------------------------------------------------
# Tokenizer freeze gate

def test_pack_with_wrong_tokenizer_rejected(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        m.freeze_tokenizer("frozen-sha", 8192)
        s = m.claim("curate", by="c")
        with pytest.raises(TokenizerMismatch, match="not hash-compatible"):
            m.complete(s.id, by="c", tokens=10, tokenizer_sha="different-sha")


def test_refreeze_with_different_sha_rejected(db_path):
    with Manifest(db_path) as m:
        m.freeze_tokenizer("sha-a", 8192)
        m.freeze_tokenizer("sha-a", 8192)  # idempotent
        with pytest.raises(TokenizerMismatch, match="refusing to re-freeze"):
            m.freeze_tokenizer("sha-b", 8192)


def test_complete_to_packed_resets_attempts(db_path):
    """Curator claim attempts must not exhaust the trainer's claim budget."""
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        m.freeze_tokenizer("sha", 8192)
        s = m.claim("curate", by="c")
        assert s.attempts == 1
        m.complete(s.id, by="c", tokens=100, path="/packed/a.bin",
                   tokenizer_sha="sha", split="train")
        row = m.db.execute("SELECT attempts, state FROM shards WHERE id=?", (s.id,)).fetchone()
        assert row["state"] == PACKED
        assert row["attempts"] == 0


def test_clear_tokenizer_for_retrain_allows_new_freeze(db_path):
    _seed(db_path, n=2)
    with Manifest(db_path) as m:
        m.freeze_tokenizer("sha-a", 8192)
        s = m.claim("curate", by="c")
        m.complete(s.id, by="c", tokens=100, path="/packed/a.bin",
                   tokenizer_sha="sha-a", split="train")
        s2 = m.claim("train", by="t")
        with pytest.raises(StateError, match="CLAIMED_"):
            m.clear_tokenizer_for_retrain()
        released = m.abandon_claims()
        assert s2.id in released
        stats = m.clear_tokenizer_for_retrain()
        assert stats["deleted_tokenized"] >= 1
        assert m.tokenizer_sha() is None
        m.freeze_tokenizer("sha-b", 32000)
        assert m.tokenizer_sha() == "sha-b"


def test_pack_before_tokenizer_frozen_rejected(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        s = m.claim("curate", by="c")
        with pytest.raises(TokenizerMismatch, match="no tokenizer frozen"):
            m.complete(s.id, by="c", tokens=10, tokenizer_sha="whatever")


# --------------------------------------------------------------------------
# Cursors (collector resume)

def test_cursor_roundtrip_and_idempotent_add(db_path):
    with Manifest(db_path) as m:
        assert m.get_cursor("fineweb") == (None, 0)
        m.set_cursor("fineweb", "offset:1000", 1000)
        assert m.get_cursor("fineweb") == ("offset:1000", 1000)
        m.set_cursor("fineweb", "offset:2000", 2000)
        assert m.get_cursor("fineweb") == ("offset:2000", 2000)

        assert m.add_shard("dup", source="s", phase=0, path="/p") is True
        assert m.add_shard("dup", source="s", phase=0, path="/p") is False  # no duplicate


# --------------------------------------------------------------------------
# release_claim: a clean handback is not a failure

def test_release_claim_does_not_burn_attempts(db_path):
    """A trainer restarting mid-shard hands the shard back. Doing that through
    fail() would park a perfectly good shard in FAILED after three restarts."""
    _seed(db_path, n=1)
    with Manifest(db_path, max_attempts=3) as m:
        for _ in range(5):
            s = m.claim("curate", by="w")
            assert s is not None, "shard was parked as FAILED by repeated releases"
            assert m.release_claim(s.id, by="w") == RAW

        assert m.counts_by_state() == {RAW: 1}


def test_release_claim_rejects_non_holder(db_path):
    _seed(db_path, n=1)
    with Manifest(db_path) as m:
        s = m.claim("curate", by="owner")
        with pytest.raises(StateError, match="not held by"):
            m.release_claim(s.id, by="someone-else")


def test_release_claim_returns_train_shard_to_packed(db_path):
    with Manifest(db_path) as m:
        m.freeze_tokenizer("t", 8192)
        m.add_shard("p", source="x", phase=0, path="/p/p.bin", state=PACKED)
        m.db.execute("UPDATE shards SET tokens=100 WHERE id='p'")
        s = m.claim("train", by="trainer-1")
        assert m.tokens_ready(0) == 0                 # locked while claimed
        assert m.release_claim(s.id, by="trainer-1") == PACKED
        assert m.tokens_ready(0) == 100              # available again
