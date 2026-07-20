# Solo personal project, no connection to employer, built with public/free-tier only
"""Skills-bridge tests — real memory-router recall (against a really-minted shard store),
bridged tools parity-checked and executed in the REAL sandbox subprocess, engine injection."""

from __future__ import annotations

import ast

import pytest

from dottie import resolve, skill_tools


def _mint_module():
    loader = skill_tools.get_loader()
    return (
        loader.skills["memory-mint"]._module
        or loader.skills["memory-mint"].load_module()
    )


def test_bridge_probe_available_in_this_checkout():
    p = skill_tools.probe()
    assert p["available"] is True
    assert set(p["bridged_tools"]) == {
        "logic_truth_table",
        "route_query",
        "safety_scan",
    }
    assert "memory-router" in p["skills_found"]


def test_memory_recall_reads_really_minted_shards(tmp_path):
    """End-to-end recall: mint a shard with the REAL memory-mint skill, then recall it via
    the REAL memory-router run — no fixture fakery in between."""
    mint = _mint_module()
    store = mint.ShardStore(tmp_path / "shards")
    shard = mint.mint_shard(
        mint.TraceEvent(
            source="test",
            instruction="remember the fact about the report format",
            outcome="report format is CSV with a trailing newline",
            ok=True,
        )
    )
    assert store.append(shard) is True
    recall = skill_tools.memory_recall(
        "remember the report format fact", store_dir=tmp_path / "shards"
    )
    assert recall["skill"] == "memory-router"
    assert any("report format is CSV" in m["outcome"] for m in recall["recalled"])
    assert "recall_error" not in recall
    ctx = skill_tools.render_recall_context(recall)
    assert ctx.startswith("[memory recall")
    assert "report format is CSV" in ctx


def test_memory_recall_empty_store_is_honest(tmp_path):
    recall = skill_tools.memory_recall(
        "remember something", store_dir=tmp_path / "none"
    )
    assert recall["recalled"] == []
    assert (
        "(no minted memories matched this task)"
        in skill_tools.render_recall_context(recall)
    )


def test_recall_snapshot_source_is_pure_literal():
    src = skill_tools.recall_snapshot_source(
        [{"instruction": "i", "outcome": "o", "branch": "code"}]
    )
    ns = {}
    exec(src, ns)  # noqa: S102 - executing the source we just generated
    data = ns["recalled_memories"]()
    assert data == [{"instruction": "i", "outcome": "o", "branch": "code"}]
    # The embedded payload is a plain literal (nothing executable can be smuggled in).
    literal = src.split("return ", 1)[1]
    assert ast.literal_eval(literal.strip()) == data


def test_bridged_tools_parity_with_live_skills():
    """The composed sources compute EXACTLY what the live skill functions compute."""
    srcs = skill_tools.sandbox_skill_tool_sources()  # raises on any parity mismatch
    router = skill_tools._skill_module("memory-router")
    scanner = skill_tools._skill_module("safety-scanner")
    ns: dict = {}
    exec(srcs["route_query"], ns)  # noqa: S102
    assert ns["route_query"](
        "plan the deadline"
    ) == router._shardmemo_scope_before_routing("plan the deadline")
    ns2: dict = {}
    exec(srcs["safety_scan"], ns2)  # noqa: S102
    assert ns2["safety_scan"]("blackmail threat") == scanner._regex_safety_score(
        "blackmail threat"
    )


def test_bridged_tools_run_in_the_real_sandbox():
    """The tools genuinely execute inside the sandbox subprocess (python -S, no site-packages)
    and their real outputs match the live parent-side skills."""
    resolve.ensure_factory_on_path()
    from ava.rl.codeact_sandbox import Sandbox

    srcs = skill_tools.sandbox_skill_tool_sources()
    srcs["recalled_memories"] = skill_tools.recall_snapshot_source(
        [{"instruction": "past", "outcome": "solved", "branch": "code"}]
    )
    with Sandbox(tool_sources=srcs) as vm:
        o1 = vm.step(
            "route_query('plan the deadline then schedule')['tier_b']['scope']"
        )
        o2 = vm.step("safety_scan('blackmail threat if you do not pay I will expose')")
        o3 = vm.step("t = logic_truth_table('IMPLIES'); (t['expr'], t['valid'])")
        o4 = vm.step("recalled_memories()[0]['outcome']")
    assert o1.ok and o1.value == "'Planner_150'"
    router = skill_tools._skill_module("memory-router")
    assert (
        o1.value.strip("'")
        == router._shardmemo_scope_before_routing("plan the deadline then schedule")[
            "tier_b"
        ]["scope"]
    )
    scanner = skill_tools._skill_module("safety-scanner")
    assert o2.ok and float(o2.value) == scanner._regex_safety_score(
        "blackmail threat if you do not pay I will expose"
    )
    assert o3.ok and o3.value == "('P IMPLIES Q', True)"
    assert o4.ok and o4.value == "'solved'"
    # Real recorded tool calls, one per step.
    assert [c["tool"] for c in o1.tool_calls] == ["route_query"]
    assert [c["tool"] for c in o3.tool_calls] == ["logic_truth_table"]


def test_engine_use_skills_injects_real_recall_and_binds_tools(engine):
    """use_skills=True: the recall context block genuinely reaches the policy transcript
    (EchoPolicy's FINAL echoes the first prompt line, which is the recall label), the skills
    section is recorded, and the bridged tools are bound for the episode."""
    rec = engine.run_task("skills plumbing run", backend="echo", use_skills=True)
    assert rec["terminated"] == "final"
    skills = rec["skills"]
    assert set(skills["bridged_tools"]) == {
        "logic_truth_table",
        "recalled_memories",
        "route_query",
        "safety_scan",
    }
    assert skills["memory_recall"]["skill"] == "memory-router"
    assert isinstance(skills["memory_recall"]["recalled"], list)
    # Proof of injection: the first transcript line the policy saw is the recall label.
    assert "[memory recall" in rec["final"]
    # The free-form honesty contract is unchanged by skills: still unscored.
    assert rec["reward_components"]["r_task"] is None


def test_skills_unavailable_raises_honestly(engine, monkeypatch):
    """A missing skills checkout must raise, never degrade into fabricated skill output."""
    monkeypatch.setattr(skill_tools, "_LOADER", None)
    monkeypatch.setenv("DOTTIE_ROOT", "/nonexistent/dottie")
    with pytest.raises(skill_tools.DottieSkillsUnavailable):
        skill_tools.get_loader()
    monkeypatch.setattr(skill_tools, "_LOADER", None)  # do not leak the poisoned cache
