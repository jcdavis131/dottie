"""Locking tests: routing dispatches are fail-closed on unknown intent/complexity.

Regression lock for the gate-audit ratchet (fail-open-dispatch). An
unrecognised intent or complexity must raise, never silently fall through
to a default tier or agent list.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PACKAGE_ROOT / "lib" / "production_routing.py"
SPEC = importlib.util.spec_from_file_location("production_routing_guards", MODULE_PATH)
routing = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(routing)


def test_classify_tier_unknown_intent_raises():
    with pytest.raises(ValueError, match="unknown intent"):
        routing._classify_tier("ship it", "banana", "simple")


def test_classify_tier_unknown_complexity_raises():
    with pytest.raises(ValueError, match="unknown complexity"):
        routing._classify_tier("ship it", "agentic_loop", "gargantuan")


def test_recommended_agents_unknown_intent_raises():
    with pytest.raises(ValueError, match="unknown intent"):
        routing._recommended_agents("banana", "simple")


def test_recommended_agents_unknown_complexity_raises():
    with pytest.raises(ValueError, match="unknown complexity"):
        routing._recommended_agents("deep_research", "gargantuan")


def test_known_intents_still_route():
    assert routing._classify_tier("compare stripe vs lemon squeezy", "deep_research", "medium") == "deep_research"
    assert routing._classify_tier("pay the invoice", "complex_action", "simple") == "action_operator"
    assert routing._classify_tier("ship the whole harness", "agentic_loop", "epic") == "agentic_epic"
    assert routing._classify_tier("heartbeat tick", "deterministic", "simple") == "deterministic"
    assert routing._classify_tier("hello world", "llm", "simple") == "llm"


def test_known_combinations_still_recommend():
    agents = routing._recommended_agents("deep_research", "epic")
    assert agents[0] == "deep-researcher"
    assert routing._recommended_agents("complex_action", "simple")[0] == "action-operator"
    assert routing._recommended_agents("agentic_loop", "epic")[0] == "scout-prime-coordinator"
    assert routing._recommended_agents("llm", "simple") == ["operator", "scout-prime-coordinator"]


def test_route_goal_never_raises_on_plain_goals():
    for goal in ("monitor tick", "compare stripe vs lemon squeezy", "ship the harness end to end", "hello"):
        result = routing.route_goal(goal)
        assert result["moma_tier"] in {"deterministic", "deep_research", "action_operator", "agentic_epic", "llm"}
        assert result["recommended_agents"]
