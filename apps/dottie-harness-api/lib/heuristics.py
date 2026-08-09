"""Self-contained port of the harness router heuristics — stdlib only.

Vendored from apps/scout-cli/bigbang/plugins/harness/cli.py so the serverless
package carries no cross-package imports. Source lines for each piece:

* ``INTENT_KEYWORDS`` + ``_score_intent`` — cli.py:37-52 (word hit +1, regex
  hit +2.5; four families agentic_loop / deep_research / complex_action /
  deterministic with their exact word and pattern lists).
* ``_complexity`` — cli.py:62-67 (words>60 or chain_signals>=3 -> "epic",
  words>18 -> "medium", else "simple"; chain_signals =
  len(re.findall(r"(->|then|after|next|→)", t)) + (1 if " and " in t and
  words>10 else 0)).
* ``_classify_moma`` — cli.py:54-60 (five tiers: deterministic, llm,
  deep_research, action_operator, agentic_epic).
* ``_routed_agents`` — cli.py:69-79 (deep_research 3 or 5 agents;
  complex_action 3; agentic_loop epic full 13 else capped [:5]; plain epic 8,
  medium 3, simple 2).
* ``plan_goal`` — minimal port of the graph-plan python fallback,
  cli.py:397-440 (tier hint, three DAG templates, llm_map of cli.py:430,
  sideEffect rule of cli.py:438).

Deliberate divergence (bug fix, not replicated from the source): the original
route command computes confidence via ``scores[intent]`` after forcing
``intent='llm'`` on zero-keyword goals, which raises KeyError because "llm" is
not an intent family (cli.py:99-103). This port computes confidence from
``max(scores.values())`` and never indexes ``scores`` by the forced intent.

Deliberate divergence (provenance honesty): the source plan command mines
per-role failure rates from the timeline store (g_history_stats,
cli.py:424-429). A serverless bundle has no timeline store, so ``plan_goal``
uses STATIC risk priors only (0.2, +0.15 for executor/builder) and labels the
response ``risk_provenance`` accordingly. Claiming mined history here would be
provenance-dishonest.
"""

from __future__ import annotations

import re
from typing import Any

MOMA_TIERS = (
    "deterministic",
    "llm",
    "deep_research",
    "action_operator",
    "agentic_epic",
)

# cli.py:37-42 — exact word/pattern lists.
INTENT_KEYWORDS: dict[str, dict[str, Any]] = {
    "agentic_loop": {
        "words": ["launch", "ship", "build", "end-to-end", "loop", "factory", "close the loop"],
        "patterns": [r"\b12 things at once\b", r"\bopaque goal\b", r"\bkeep track\b"],
        "weight": 1,
    },
    "deep_research": {
        "words": ["compare", "vs", "stripe", "lemon squeezy", "research", "sota", "paper", "benchmark", "triangulation", "sources"],
        "patterns": [r"\baug\s*2026\b", r"\b5-7 sources\b"],
        "weight": 1,
    },
    "complex_action": {
        "words": ["gmail", "calendar", "drive", "notion", "linear", "pay", "invoice", "book", "schedule"],
        "patterns": [r"\btool\s*chain\b"],
        "weight": 1,
    },
    "deterministic": {
        "words": ["heartbeat", "monitor", "cron", "tick"],
        "patterns": [],
        "weight": 1,
    },
}


def _score_intent(text: str, intent: str) -> float:
    """cli.py:44-52 — substring word hits +1, regex hits +2.5."""
    cfg = INTENT_KEYWORDS.get(intent, {})
    t = text.lower()
    score = 0.0
    for w in cfg.get("words", []):
        if w.lower() in t:
            score += 1
    for pat in cfg.get("patterns", []):
        if re.search(pat, t, re.I):
            score += 2.5
    return score


def _complexity(text: str) -> str:
    """cli.py:62-67."""
    words = len(text.split())
    chain_signals = len(re.findall(r"(->|then|after|next|→)", text.lower())) + (
        1 if " and " in text.lower() and words > 10 else 0
    )
    if words > 60 or chain_signals >= 3:
        return "epic"
    if words > 18:
        return "medium"
    return "simple"


def _classify_moma(text: str, intent: str, complexity: str) -> str:
    """cli.py:54-60."""
    t = text.lower()
    if any(k in t for k in ["heartbeat", "monitor", "tick", "cron health"]):
        return "deterministic"
    if intent == "deep_research" or any(k in t for k in ["stripe", "lemon", "triangulation", "paper", "sota", "sources"]):
        return "deep_research"
    if intent == "complex_action" or any(k in t for k in ["gmail", "calendar trick", "chain call"]):
        return "action_operator"
    if intent == "agentic_loop" or complexity == "epic":
        return "agentic_epic"
    return "llm"


def _routed_agents(intent: str, complexity: str) -> list[str]:
    """cli.py:69-79."""
    # Membership guards: unknown values normalize to the minimal-roster path
    # (identical outcome to the bare fall-through, made explicit).
    if intent not in ("deep_research", "complex_action", "agentic_loop"):
        intent = "chat"
    if complexity not in ("simple", "medium", "epic"):
        complexity = "simple"
    if intent == "deep_research":
        return (
            ["deep-researcher", "synthesist", "forensic-auditor"]
            if complexity != "epic"
            else ["deep-researcher", "synthesist", "researcher", "forensic-auditor", "critic"]
        )
    if intent == "complex_action":
        return ["action-operator", "operator", "critic"]
    if intent == "agentic_loop":
        if complexity == "epic":
            return [
                "scout-prime-coordinator", "strategist", "planner", "deep-researcher",
                "synthesist", "builder", "operator", "action-operator", "executor",
                "critic", "forensic-auditor", "researcher", "communicator",
            ]
        return [
            "scout-prime-coordinator", "strategist", "planner", "builder",
            "executor", "critic", "operator", "action-operator", "synthesist",
        ][:5]
    if complexity == "epic":
        return [
            "scout-prime-coordinator", "strategist", "planner", "deep-researcher",
            "synthesist", "builder", "executor", "critic",
        ]
    if complexity == "medium":
        return ["scout-prime-coordinator", "strategist", "builder"]
    return ["operator", "scout-prime-coordinator"]


def route_goal(goal: str) -> dict[str, Any]:
    """Classify a goal: intent, complexity, MoMA tier, confidence, agent roster.

    Confidence uses the fixed expression (see module docstring): when no
    keyword family scores above zero the goal falls back to intent "llm" with
    confidence 0.4 instead of crashing on ``scores['llm']``.
    """
    scores = {k: _score_intent(goal, k) for k in INTENT_KEYWORDS}
    best = max(scores.values())
    intent = max(scores, key=lambda k: scores[k]) if best > 0 else "llm"
    complexity = _complexity(goal)
    moma_tier = _classify_moma(goal, intent, complexity)
    confidence = min(0.96, best / 4.0) if best > 0 else 0.4
    routed = _routed_agents(intent, complexity)
    return {
        "goal": goal,
        "intent": intent,
        "intent_scores": scores,
        "complexity": complexity,
        "moma_tier": moma_tier,
        "confidence": confidence,
        "routed_agents": routed,
        "routed_count": len(routed),
    }


RISK_PROVENANCE = "static priors — no mined run history in serverless"

# cli.py:430 — role -> tier mapping; strategist/executor entries resolved per step.
_LLM_MAP_STATIC = {
    "planner": "llm",
    "deep-researcher": "deep_research",
    "builder": "action_operator",
    "operator": "deterministic",
    "critic": "llm",
    "synthesist": "llm",
    "researcher": "deep_research",
}


def plan_goal(goal: str) -> dict[str, Any]:
    """Deterministic DAG plan — port of the graph-plan python fallback (cli.py:397-440).

    Risks are static priors only: 0.2 base, +0.15 for executor/builder. The
    source mines per-role failure rates from run history (cli.py:424-429); a
    serverless bundle has no timeline store, so this port does not, and says so
    in ``risk_provenance``.
    """
    lower = goal.lower()
    # cli.py:397
    tier_hint = "agentic_epic" if ("ship" in lower or "harness" in lower) else "llm"

    # cli.py:400-421 — three DAG templates.
    if "compare stripe" in lower or "stripe vs" in lower:
        dag = [
            {"id": "observe-facts", "role": "deep-researcher", "desc": "wide sweep 5-7 sources"},
            {"id": "orient-memory", "role": "strategist", "desc": "3-lens + memory lattice"},
            {"id": "decide-triangulate", "role": "synthesist", "desc": "Collect→Cluster→Conflict→Crystallize"},
            {"id": "act-deliver", "role": "builder", "desc": "polished brief artifact"},
        ]
    elif "heartbeat" in lower or "monitor" in lower:
        dag = [
            {"id": "observe-tick", "role": "operator", "desc": "Observe real-time tick :13"},
            {"id": "orient-filter", "role": "strategist", "desc": "Orient filter culture/experience"},
            {"id": "act-noop", "role": "operator", "desc": "Act artifact heartbeat log even no-change"},
        ]
    else:
        dag = [
            {"id": "intent-decompose", "role": "strategist", "desc": "L1 opaque goal deconstruction"},
            {"id": "dag-architect", "role": "planner", "desc": "L2 DAG deterministic 3-7 nodes"},
            {"id": "layer-exec", "role": "executor", "desc": "L3 elite node runner OODA inner"},
            {"id": "build", "role": "builder", "desc": "Act polished deliverable"},
            {"id": "verify-budget", "role": "critic", "desc": "L4 verification econ budget3"},
        ]

    steps = []
    for i, node in enumerate(dag):
        role = node["role"]
        # Static priors — the source's mined fail_rate branch (cli.py:429) is
        # deliberately absent here.
        risk = 0.2 + (0.15 if role in ("executor", "builder") else 0.0)
        llm_map = dict(_LLM_MAP_STATIC)
        llm_map["strategist"] = tier_hint if tier_hint != "llm" else "llm"
        llm_map["executor"] = "agentic_epic" if risk > 0.3 else "action_operator"
        steps.append({
            "id": node["id"],
            "idx": i,
            "role": role,
            "llmTier": llm_map.get(role, tier_hint),
            "failureRisk": round(risk, 2),
            # cli.py:438 rule.
            "sideEffect": (
                "WRITE_DESTRUCTIVE" if role in ("builder", "executor")
                else "READ" if role == "operator"
                else "READ" if i == 0
                else "WRITE_IDEMPOTENT"
            ),
            "desc": node["desc"],
        })

    return {
        "goal": goal,
        "tierHint": tier_hint,
        "steps": steps,
        "risk_provenance": RISK_PROVENANCE,
        "version": "vendored port of harness graph-plan python fallback",
    }
