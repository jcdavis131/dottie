"""Deterministic production routing with no artifact or synthetic-data access."""

from __future__ import annotations

import re
from typing import Any

INTENT_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "agentic_loop": {
        "words": ["launch", "ship", "build", "end-to-end", "loop", "factory", "close the loop"],
        "patterns": [r"\b12 things at once\b", r"\bopaque goal\b", r"\bkeep track\b"],
    },
    "deep_research": {
        "words": [
            "compare",
            "vs",
            "stripe",
            "lemon squeezy",
            "research",
            "sota",
            "paper",
            "benchmark",
            "triangulation",
            "sources",
        ],
        "patterns": [r"\baug\s*2026\b", r"\b5-7 sources\b"],
    },
    "complex_action": {
        "words": ["gmail", "calendar", "drive", "notion", "linear", "pay", "invoice", "book", "schedule"],
        "patterns": [r"\btool\s*chain\b"],
    },
    "deterministic": {
        "words": ["heartbeat", "monitor", "cron", "tick"],
        "patterns": [],
    },
}
RISK_PROVENANCE = "static priors — no mined run history in serverless"
# Fail-closed membership sets. Every value dispatched on by _classify_tier and
# _recommended_agents must be in these; anything else raises instead of silently
# falling through to a default tier. The gate audit (scripts/gate_audit.py)
# treats a membership guard as a cleared fail-open dispatch, and the raise is
# the honest terminator the audit's own docstring recommends.
KNOWN_INTENTS = frozenset({"agentic_loop", "deep_research", "complex_action", "deterministic", "llm"})
KNOWN_COMPLEXITIES = frozenset({"epic", "medium", "simple"})
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
    config = INTENT_KEYWORDS[intent]
    lowered = text.lower()
    word_score = sum(1.0 for word in config["words"] if word in lowered)
    pattern_score = sum(2.5 for pattern in config["patterns"] if re.search(pattern, lowered, re.I))
    return word_score + pattern_score


def _complexity(text: str) -> str:
    words = len(text.split())
    lowered = text.lower()
    chain_signals = len(re.findall(r"(->|then|after|next|→)", lowered))
    chain_signals += int(" and " in lowered and words > 10)
    if words > 60 or chain_signals >= 3:
        return "epic"
    if words > 18:
        return "medium"
    return "simple"


def _classify_tier(text: str, intent: str, complexity: str) -> str:
    lowered = text.lower()
    if intent not in KNOWN_INTENTS:
        raise ValueError(f"unknown intent {intent!r}; expected one of {sorted(KNOWN_INTENTS)}")
    if complexity not in KNOWN_COMPLEXITIES:
        raise ValueError(f"unknown complexity {complexity!r}; expected one of {sorted(KNOWN_COMPLEXITIES)}")
    if any(keyword in lowered for keyword in ("heartbeat", "monitor", "tick", "cron health")):
        return "deterministic"
    if intent == "deep_research":
        return "deep_research"
    if intent == "complex_action":
        return "action_operator"
    if intent == "agentic_loop" or complexity == "epic":
        return "agentic_epic"
    return "llm"


def _recommended_agents(intent: str, complexity: str) -> list[str]:
    if intent not in KNOWN_INTENTS:
        raise ValueError(f"unknown intent {intent!r}; expected one of {sorted(KNOWN_INTENTS)}")
    if complexity not in KNOWN_COMPLEXITIES:
        raise ValueError(f"unknown complexity {complexity!r}; expected one of {sorted(KNOWN_COMPLEXITIES)}")
    if intent == "deep_research":
        if complexity == "epic":
            return ["deep-researcher", "synthesist", "researcher", "forensic-auditor", "critic"]
        return ["deep-researcher", "synthesist", "forensic-auditor"]
    if intent == "complex_action":
        return ["action-operator", "operator", "critic"]
    if intent == "agentic_loop":
        if complexity == "epic":
            return [
                "scout-prime-coordinator",
                "strategist",
                "planner",
                "deep-researcher",
                "synthesist",
                "builder",
                "operator",
                "action-operator",
                "executor",
                "critic",
                "forensic-auditor",
                "researcher",
                "communicator",
            ]
        return ["scout-prime-coordinator", "strategist", "planner", "builder", "executor"]
    if complexity == "epic":
        return [
            "scout-prime-coordinator",
            "strategist",
            "planner",
            "deep-researcher",
            "synthesist",
            "builder",
            "executor",
            "critic",
        ]
    if complexity == "medium":
        return ["scout-prime-coordinator", "strategist", "builder"]
    return ["operator", "scout-prime-coordinator"]


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
