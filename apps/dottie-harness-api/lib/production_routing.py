"""Deterministic production routing with no artifact or synthetic-data access.

The classifier is the router's MoMA-lite heuristic (dottie_loop.backends),
vendored verbatim into lib/moma_lite.py by scripts/vendor_router.py because
Vercel deploys this app without the monorepo. This module adds only the API's
fail-closed guards (RoutingRejected) and response shape;
tests/test_production_routing_parity.py holds it to the router's goldens.
Phase 2 replaces the copy with a proxy to jarvisd /api/decide.
"""

from __future__ import annotations

from typing import Any

try:  # package import (api/index.py, tests)
    from lib import moma_lite
except ImportError:  # loaded by file path (tests/test_production_routing_guards.py)
    import importlib.util as _ilu
    from pathlib import Path as _Path

    _spec = _ilu.spec_from_file_location("moma_lite", _Path(__file__).with_name("moma_lite.py"))
    moma_lite = _ilu.module_from_spec(_spec)
    assert _spec.loader is not None
    _spec.loader.exec_module(moma_lite)

INTENT_KEYWORDS = moma_lite.INTENT_KEYWORDS

RISK_PROVENANCE = "static priors — no mined run history in serverless"
# Fail-closed membership sets. Every value dispatched on by _classify_tier and
# _recommended_agents must be in these; anything else raises instead of silently
# falling through to a default tier. The gate audit (scripts/gate_audit.py)
# treats a membership guard as a cleared fail-open dispatch, and the raise is
# the honest terminator the audit's own docstring recommends.
KNOWN_INTENTS = frozenset({"agentic_loop", "deep_research", "complex_action", "deterministic", "llm"})
KNOWN_COMPLEXITIES = frozenset({"epic", "medium", "simple"})


class RoutingRejected(ValueError):
    """Fail-closed routing rejection: intent/complexity outside the membership sets.

    Subclasses ValueError so existing `except ValueError` guards — including the
    gate-audit ratchet tests — keep working. The HTTP boundary catches this
    specific type to answer 400 (with quarantine + alert) instead of 500.
    """

    def __init__(self, field: str, value: object, expected: frozenset[str]) -> None:
        self.field = field
        self.value = value
        self.expected = sorted(expected)
        super().__init__(f"unknown {field} {value!r}; expected one of {self.expected}")
LLM_MAP = {
    "planner": "llm",
    "deep-researcher": "deep_research",
    "builder": "action_operator",
    "operator": "deterministic",
    "critic": "llm",
    "synthesist": "llm",
    "researcher": "deep_research",
}


def _score_intent(text: str, intent: str) -> float:
    return moma_lite.score_intent(text, intent)


def _complexity(text: str) -> str:
    return moma_lite.complexity(text)


def _guard(intent: str, complexity: str) -> None:
    if intent not in KNOWN_INTENTS:
        raise RoutingRejected("intent", intent, KNOWN_INTENTS)
    if complexity not in KNOWN_COMPLEXITIES:
        raise RoutingRejected("complexity", complexity, KNOWN_COMPLEXITIES)


def _classify_tier(text: str, intent: str, complexity: str) -> str:
    _guard(intent, complexity)
    return moma_lite.classify_moma(text, intent, complexity)


def _recommended_agents(intent: str, complexity: str) -> list[str]:
    _guard(intent, complexity)
    return moma_lite.routed_agents(intent, complexity)


def route_goal(goal: str) -> dict[str, Any]:
    scores = {intent: _score_intent(goal, intent) for intent in INTENT_KEYWORDS}
    best = max(scores.values())
    intent = max(scores, key=scores.__getitem__) if best > 0 else "llm"
    complexity = _complexity(goal)
    recommended_agents = _recommended_agents(intent, complexity)
    return {
        "goal": goal,
        "intent": intent,
        "intent_scores": scores,
        "complexity": complexity,
        "moma_tier": _classify_tier(goal, intent, complexity),
        "heuristic_score": min(0.96, best / 4.0) if best > 0 else 0.4,
        "recommended_agents": recommended_agents,
        "recommended_agent_count": len(recommended_agents),
        "provenance": "request_derived_heuristic",
    }


def _plan_template(goal: str) -> tuple[str, list[dict[str, str]]]:
    lowered = goal.lower()
    tier_hint = "agentic_epic" if ("ship" in lowered or "harness" in lowered) else "llm"
    if "compare stripe" in lowered or "stripe vs" in lowered:
        nodes = [
            {"id": "observe-facts", "role": "deep-researcher", "desc": "wide source sweep"},
            {"id": "orient-memory", "role": "strategist", "desc": "compare evidence"},
            {"id": "decide-triangulate", "role": "synthesist", "desc": "resolve conflicts"},
            {"id": "act-deliver", "role": "builder", "desc": "produce verified brief"},
        ]
    elif "heartbeat" in lowered or "monitor" in lowered:
        nodes = [
            {"id": "observe-tick", "role": "operator", "desc": "observe current tick"},
            {"id": "orient-filter", "role": "strategist", "desc": "filter relevant state"},
            {"id": "act-noop", "role": "operator", "desc": "record no-op when unchanged"},
        ]
    else:
        nodes = [
            {"id": "intent-decompose", "role": "strategist", "desc": "decompose the goal"},
            {"id": "dag-architect", "role": "planner", "desc": "build a deterministic DAG"},
            {"id": "layer-exec", "role": "executor", "desc": "execute DAG nodes"},
            {"id": "build", "role": "builder", "desc": "produce the deliverable"},
            {"id": "verify-budget", "role": "critic", "desc": "verify within budget"},
        ]
    return tier_hint, nodes


def plan_goal(goal: str) -> dict[str, Any]:
    tier_hint, nodes = _plan_template(goal)
    steps: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        role = node["role"]
        risk = 0.35 if role in {"executor", "builder"} else 0.2
        llm_tier = LLM_MAP.get(role, tier_hint)
        if role == "strategist":
            llm_tier = tier_hint
        elif role == "executor":
            llm_tier = "agentic_epic"
        steps.append(
            {
                "id": node["id"],
                "idx": index,
                "role": role,
                "llmTier": llm_tier,
                "failureRisk": risk,
                "sideEffect": (
                    "WRITE_DESTRUCTIVE"
                    if role in {"builder", "executor"}
                    else "READ"
                    if role == "operator" or index == 0
                    else "WRITE_IDEMPOTENT"
                ),
                "desc": node["desc"],
            }
        )
    return {
        "goal": goal,
        "tierHint": tier_hint,
        "steps": steps,
        "risk_provenance": RISK_PROVENANCE,
        "version": "deterministic production routing v1",
        "provenance": "request_derived_heuristic",
    }
