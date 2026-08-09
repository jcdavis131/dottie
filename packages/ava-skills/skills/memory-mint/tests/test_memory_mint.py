# Solo personal project, no connection to employer, built with public/free-tier only
"""memory-mint pipeline: capture semantics, async minting, scoping symmetry, store integrity."""

import importlib.util
import sys
import time
from pathlib import Path

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
        shard = mm.mint_shard(
            make_event(instruction="blackmail threat to expose the operator")
        )
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
        pipe = mm.MemoryMintPipeline(
            store=mm.ShardStore(tmp_path),
            max_queue=8,
            batch_size=1024,
            idle_flush_s=10.0,
        )
        # worker is idle-waiting; saturate the queue synchronously
        for i in range(50):
            pipe.capture(make_event(i))
        assert pipe.stats["captured"] == 50
        assert pipe.stats["dropped"] >= 40  # bounded queue shed the oldest
        pipe.close(timeout=15.0)

    def test_mixed_scopes_land_in_right_files(self, tmp_path):
        with mm.MemoryMintPipeline(store=mm.ShardStore(tmp_path)) as pipe:
            pipe.capture(
                make_event(instruction="remember the fact and explain the wiki entry")
            )
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


class TestFineRanking:
    ON_TOPIC = "remember the fact about python dedupe logic"
    OFF_TOPIC = "remember to explain the report format"
    QUERY = "remember the python dedupe logic fact"

    def test_on_topic_outranks_newer_off_topic(self, tmp_path):
        # Sanity: both instructions land in the same Tier-B scope, so recency alone
        # would put the off-topic shard first — overlap ranking must beat it.
        scope_a = mm.scope_before_routing(self.ON_TOPIC)["tier_b"]["scope"]
        scope_b = mm.scope_before_routing(self.OFF_TOPIC)["tier_b"]["scope"]
        assert scope_a == scope_b == "S2_slow_300"
        store = mm.ShardStore(tmp_path)
        assert store.append(mm.mint_shard(make_event(1, instruction=self.ON_TOPIC)))
        time.sleep(0.01)
        assert store.append(mm.mint_shard(make_event(2, instruction=self.OFF_TOPIC)))
        rows = store.query(instruction=self.QUERY, limit=5)
        assert len(rows) == 2
        assert "dedupe" in rows[0]["instruction"]

    def test_empty_instruction_is_recency_only(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        instructions = [
            "remember the first fact",
            "remember the second fact",
            "remember the third fact",
        ]
        scope = mm.scope_before_routing(instructions[0])["tier_b"]["scope"]
        for i, instr in enumerate(instructions):
            assert store.append(mm.mint_shard(make_event(i, instruction=instr)))
            time.sleep(0.01)
        rows = store.query(instruction="", tier_b_scope=scope, limit=10)
        expected = sorted(rows, key=lambda r: r["minted_ts"], reverse=True)
        assert rows == expected
        assert [r["instruction"] for r in rows] == list(reversed(instructions))

    def test_append_then_query_sees_new_shard_without_reopen(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        assert store.append(mm.mint_shard(make_event(1, instruction=self.OFF_TOPIC)))
        # First query builds the scope's index lazily.
        store.query(instruction=self.QUERY, limit=5)
        time.sleep(0.01)
        # Same store object: the incremental index update path must pick this up.
        assert store.append(mm.mint_shard(make_event(2, instruction=self.ON_TOPIC)))
        rows = store.query(instruction=self.QUERY, limit=5)
        assert len(rows) == 2
        assert "dedupe" in rows[0]["instruction"]

    def test_result_count_parity(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        scope = mm.scope_before_routing("remember a fact")["tier_b"]["scope"]
        for i in range(4):
            assert store.append(
                mm.mint_shard(make_event(i, instruction=f"remember fact number {i}"))
            )
        rows = store.query(
            instruction="completely unrelated zebra quantum",
            tier_b_scope=scope,
            limit=10,
        )
        # Recall floor: zero token overlap must never shrink the result set.
        assert len(rows) == 4
