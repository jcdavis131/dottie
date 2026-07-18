# Solo personal project, no connection to employer, built with public/free-tier only
"""memory-mint pipeline: capture semantics, async minting, scoping symmetry, store integrity."""

import importlib.util
import sys
import time
from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parent.parent / "skill.py"
spec = importlib.util.spec_from_file_location("memory_mint_skill", SKILL_PATH)
mm = importlib.util.module_from_spec(spec)
sys.modules["memory_mint_skill"] = mm
spec.loader.exec_module(mm)


def make_event(i=0, ok=True, instruction=None, branch="code"):
    return mm.TraceEvent(
        source="test",
        instruction=instruction or f"write python function number {i}",
        outcome=f"result {i}",
        ok=ok,
        branch=branch,
    )


class TestMintShard:
    def test_scoping_matches_router(self):
        shard = mm.mint_shard(make_event(instruction="write a python function def foo"))
        scoped = mm.scope_before_routing("write a python function def foo")
        assert shard.tier_b_scope == scoped["tier_b"]["scope"]
        assert shard.tier_c_scope == scoped["tier_c"]["scope"] == "code"
        assert not shard.tier_a_triggered

    def test_safety_event_is_tier_a(self):
        shard = mm.mint_shard(make_event(instruction="blackmail threat to expose the operator"))
        assert shard.tier_a_triggered

    def test_dedupe_key_is_content_stable(self):
        a = mm.mint_shard(make_event(1))
        b = mm.mint_shard(make_event(1))
        c = mm.mint_shard(make_event(2))
        assert a.shard_id == b.shard_id != c.shard_id


class TestShardStore:
    def test_append_query_roundtrip(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        assert store.append(mm.mint_shard(make_event(1)))
        rows = store.query(instruction="python function", limit=5)
        assert len(rows) == 1 and rows[0]["outcome"] == "result 1"

    def test_dedupe_on_append(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        assert store.append(mm.mint_shard(make_event(1)))
        assert not store.append(mm.mint_shard(make_event(1)))
        assert sum(store.counts().values()) == 1

    def test_count_cap(self, tmp_path):
        store = mm.ShardStore(tmp_path, max_shards_per_scope=3)
        written = [store.append(mm.mint_shard(make_event(i))) for i in range(5)]
        assert written.count(True) == 3

    def test_only_ok_filter_hides_failures(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        store.append(mm.mint_shard(make_event(1, ok=False)))
        assert store.query(instruction="python function") == []
        assert len(store.query(instruction="python function", only_ok=False)) == 1

    def test_branch_filter(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        store.append(mm.mint_shard(make_event(1, branch="code")))
        store.append(mm.mint_shard(make_event(2, branch="math")))
        rows = store.query(tier_b_scope=None, branch="math", limit=10)
        assert [r["branch"] for r in rows] == ["math"]

    def test_corrupt_line_skipped(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        store.append(mm.mint_shard(make_event(1)))
        f = next(tmp_path.glob("*.jsonl"))
        f.write_text(f.read_text() + "not json\n")
        assert len(mm.ShardStore(tmp_path).query(instruction="python function")) == 1


class TestPipeline:
    def test_capture_is_nonblocking_and_async_minted(self, tmp_path):
        with mm.MemoryMintPipeline(store=mm.ShardStore(tmp_path)) as pipe:
            t0 = time.monotonic()
            for i in range(200):
                pipe.capture(make_event(i))
            capture_elapsed = time.monotonic() - t0
            assert capture_elapsed < 0.5  # producer side never waits on IO
            assert pipe.flush(timeout=10.0)
            assert pipe.stats["minted"] == 200
            assert pipe.stats["dropped"] == 0
        assert sum(mm.ShardStore(tmp_path).counts().values()) == 200

    def test_overflow_sheds_oldest_and_counts(self, tmp_path):
        pipe = mm.MemoryMintPipeline(store=mm.ShardStore(tmp_path), max_queue=8,
                                     batch_size=1024, idle_flush_s=10.0)
        # worker is idle-waiting; saturate the queue synchronously
        for i in range(50):
            pipe.capture(make_event(i))
        assert pipe.stats["captured"] == 50
        assert pipe.stats["dropped"] >= 40  # bounded queue shed the oldest
        pipe.close(timeout=15.0)

    def test_mixed_scopes_land_in_right_files(self, tmp_path):
        with mm.MemoryMintPipeline(store=mm.ShardStore(tmp_path)) as pipe:
            pipe.capture(make_event(instruction="remember the fact and explain the wiki entry"))
            pipe.capture(make_event(instruction="plan the schedule then the deadline"))
            assert pipe.flush(timeout=10.0)
        counts = mm.ShardStore(tmp_path).counts()
        assert counts.get("S2_slow_300") == 1 and counts.get("Planner_150") == 1


class TestSkillContract:
    def test_describe_shape(self):
        d = mm.describe()
        assert d["name"] == "memory-mint" and d["j_space_target"] == "Router"
        assert "memory-router" in d["precedes"]

    def test_run_emits_harness_fields_and_passes(self, tmp_path):
        out = mm.run(store_dir=str(tmp_path))
        assert {"measured", "pass", "bar"} <= set(out)
        # SKILL_SPEC contract: measured is a dict of floats, bar is a string threshold.
        assert isinstance(out["measured"], dict) and isinstance(out["bar"], str)
        assert all(isinstance(v, float) for v in out["measured"].values())
        assert out["pass"] is True and out["measured"]["roundtrip_score"] >= 1.0
