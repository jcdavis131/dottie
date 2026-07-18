# Solo personal project, no connection to employer, built with public/free-tier only
"""memory-router: ShardMemo Tier A/B/C scoping table, true KL (>=0), targets outside
measured, surfaced recall errors."""

import pytest

from conftest import load_skill_module

mr = load_skill_module("memory-router")
mm = load_skill_module("memory-mint")


class TestShardMemoScoping:
    @pytest.mark.parametrize(
        "instruction, tier_a, tier_b, tier_c",
        [
            ("blackmail threat to expose secrets", True, None, None),
            ("this is dangerous leverage", True, None, None),
            ("remember the wiki fact and explain it", False, "S2_slow_300", None),
            ("quick reflex react fast", False, "S1_fast_8", None),
            ("plan the schedule then the deadline", False, "Planner_150", None),
            ("audit the safety risk critic", False, "Critic_30", None),
            ("write python code with a function", False, None, "code"),
            ("prove the theorem with logic math", False, "S2_slow_300", "math"),
            ("hello how are you, tell a joke", False, None, "chat"),
            ("completely neutral text", False, "Router_default", "base"),
        ],
    )
    def test_scoping_table(self, instruction, tier_a, tier_b, tier_c):
        scoped = mr._shardmemo_scope_before_routing(instruction)
        assert scoped["tier_a"]["triggered"] is tier_a
        if tier_b is not None:
            assert scoped["tier_b"]["scope"] == tier_b
        if tier_c is not None:
            assert scoped["tier_c"]["scope"] == tier_c

    def test_scope_reduction_is_labeled_estimate(self):
        scoped = mr._shardmemo_scope_before_routing("blackmail")
        assert "estimated_scope_reduction" in scoped
        assert "vecscan_reduction" not in scoped
        assert scoped["estimated_scope_reduction"] == 1.0  # Tier A short-circuit

    def test_no_design_target_inside_scoping_record(self):
        scoped = mr._shardmemo_scope_before_routing("anything")
        assert "f1_delta_target" not in scoped


class TestKL:
    QUERIES = [
        "", "write python code function", "blackmail threat expose",
        "plan the schedule then deadline", "prove the theorem with logic",
        "remember the openwiki fact", "quick fast react",
    ]

    def test_kl_nonnegative_for_all_routes(self):
        for q in self.QUERIES:
            r = mr.run(mode="mock", instruction=q)
            assert r["measured"]["kl"] >= 0.0, f"KL must be >=0, got {r['measured']['kl']} for {q!r}"

    def test_kl_zero_when_routed_equals_bias(self):
        # 'write python code function' -> Router_default tier-B, route_score code branch
        # [0.25,0.45,0.05,0.25] == code bias exactly -> KL must be 0
        r = mr.run(mode="mock", instruction="write python code function")
        assert r["measured"]["branch"] == "code"
        assert r["measured"]["kl"] == pytest.approx(0.0, abs=1e-12)


class TestTargetsOutsideMeasured:
    def test_measured_contains_no_target_fields(self):
        r = mr.run(mode="mock", instruction="remember the wiki fact")
        for k in ("target_f1_improvement", "target_kl_w", "inter_mi_target", "vecscan_reduction"):
            assert k not in r["measured"], f"{k} is a design target and must not be in measured"

    def test_targets_key_present_at_top_level(self):
        r = mr.run(mode="mock", instruction="remember the wiki fact")
        assert r["targets"]["target_f1_improvement"] == 6.87


class TestRecallErrors:
    def test_recall_roundtrip_from_minted_store(self, tmp_path):
        store = mm.ShardStore(tmp_path)
        store.append(mm.mint_shard(mm.TraceEvent(
            source="test", instruction="remember the wiki fact about spiders",
            outcome="stored", ok=True, branch="base")))
        r = mr.run(mode="mock", instruction="remember the wiki fact",
                   memory_store_dir=str(tmp_path))
        assert any("spiders" in m["instruction"] for m in r["measured"]["recalled_memories"])
        assert "memory_recall_error" not in r["measured"]

    def test_store_failure_is_surfaced_not_swallowed(self, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("i am a file where a directory is expected")
        r = mr.run(mode="mock", instruction="remember the wiki fact",
                   memory_store_dir=str(blocker))
        assert r["measured"]["recalled_memories"] == []
        assert "memory_recall_error" in r["measured"]
        assert "Error" in r["measured"]["memory_recall_error"]
