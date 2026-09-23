"""Routing tiers and the router output contract (spec §08).

Five execution tiers trade cost for uncertainty (T0 deterministic … T4 agentic
epic). Decision order, in the spec's order:

1. apply policy exclusions and hard constraints
2. choose deterministic execution when it can satisfy the goal
3. evaluate the heuristic route; it is always available
4. read a learned recommendation only if the artifact loaded, its schema validated
   and its provenance is exposed
5. prefer the safer / lower-cost tier when confidence is below threshold
6. escalate to a more capable tier only after a RECORDED insufficiency

The router must not use private attributes unrelated to the task. When a learned
model exists but its gate is false, the heuristic route stays authoritative
wherever they disagree; when no artifact is loaded, ``learned`` is null.

Two front doors, one policy:

* :func:`route` takes spec :class:`RoutingFeatures` (the RT-03 goldens).
* :func:`route_goal` takes a goal string. It is what scout (``scout route``,
  ``scout harness route``, ``scout harness run``) and jarvisd call. Its
  heuristic is MoMA-lite (:class:`dottie_loop.backends.HeuristicBackend`), its
  optional advisors are the orchestrator MLP and System One over ``/decide``,
  and it appends a trace line (:mod:`dottie_loop.traces`) for the training loop.

Both apply the same learned-advice rule (:func:`_take_learned`): a learned
answer moves the tier only when it is authoritative and equal-or-cheaper.
Authority for :func:`route_goal` additionally needs a human stamp
(:mod:`dottie_loop.router_artifacts`); nothing is stamped today, so every
learned answer is advisory, logged and displayed but never acted on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import now_iso

TIERS = ("T0", "T1", "T2", "T3", "T4")
TIER_NAMES = {"T0": "deterministic", "T1": "llm", "T2": "deep_research", "T3": "action_operator", "T4": "agentic_epic"}
#: harness-api / scout tier names -> spec tiers (adapter for apps/dottie-harness-api)
LEGACY_TIER = {"deterministic": "T0", "llm": "T1", "deep_research": "T2", "action_operator": "T3", "agentic_epic": "T4"}
CONFIDENCE_THRESHOLD = 0.6
TIER_BUDGETS: dict[str, dict[str, int]] = {
    "T0": {"tokens": 0, "wall_seconds": 60, "retries": 1},
    "T1": {"tokens": 2000, "wall_seconds": 120, "retries": 1},
    "T2": {"tokens": 9000, "wall_seconds": 1800, "retries": 1},
    "T3": {"tokens": 6000, "wall_seconds": 900, "retries": 0},
    "T4": {"tokens": 30000, "wall_seconds": 7200, "retries": 0},
}
TIER_AGENTS: dict[str, list[str]] = {
    "T0": ["machine"],
    "T1": ["assistant"],
    "T2": ["deep-researcher", "synthesist", "forensic-auditor"],
    "T3": ["planner", "action-operator", "critic"],
    "T4": ["scout-prime-coordinator", "strategist", "planner", "builder", "executor", "critic"],
}
#: Private attributes the router must never consult (§08 "Routing inputs").
FORBIDDEN_FEATURES = frozenset({"age", "gender", "religion", "ethnicity", "health", "politics", "sexuality"})

_DETERMINISTIC = re.compile(r"\b(heartbeat|monitor|tick|health ?check|lint|format|hash|checksum|rename|list files|count|validate schema|parse)\b", re.I)
_RESEARCH = re.compile(r"\b(research|compare|survey|evidence|sources|contradict|latest|fresh|investigate|literature)\b", re.I)
_ACTION = re.compile(r"\b(send|email|post|publish|deploy|merge|release|notify|webhook|book|purchase|pay|update .* in (jira|linear|notion|github))\b", re.I)
_EPIC = re.compile(r"\b(end to end|multi-?week|program|roadmap|migrate|overhaul|build .* platform|ship .* (app|product|service))\b", re.I)


@dataclass
class RoutingFeatures:
    """Only task-relevant inputs. Anything in FORBIDDEN_FEATURES is rejected at construction."""

    intent_text: str
    side_effect_class: str = "read_only"
    freshness_required: bool = False
    systems: int = 1
    ambiguity: float = 0.0  # 0..1
    expected_minutes: float = 1.0
    model_available: bool = True
    tool_available: bool = True
    cost_budget_tokens: int | None = None
    privacy_class: str = "P1"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        bad = sorted(set(self.extra) & FORBIDDEN_FEATURES)
        if bad:
            raise PolicyDeniedError(f"router must not use private attributes: {bad}", field="features")


def heuristic_route(f: RoutingFeatures) -> dict[str, Any]:
    """Step 2-3: deterministic when it can satisfy the goal, else the heuristic tier."""
    text = f.intent_text
    if _DETERMINISTIC.search(text) and f.side_effect_class in ("read_only", "write_local") and f.systems <= 1:
        return {"intent": "deterministic", "tier": "T0", "confidence": 0.9}
    if _EPIC.search(text) or f.expected_minutes > 240 or f.systems >= 4:
        return {"intent": "agentic_epic", "tier": "T4", "confidence": 0.7}
    if _ACTION.search(text) or f.side_effect_class in ("external_send", "production_mutate"):
        return {"intent": "action_operator", "tier": "T3", "confidence": 0.75}
    if _RESEARCH.search(text) or f.freshness_required or f.systems >= 2:
        return {"intent": "deep_research", "tier": "T2", "confidence": 0.75}
    return {"intent": "llm_assist", "tier": "T1", "confidence": 0.55 if f.ambiguity > 0.5 else 0.65}


def validate_learned(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    """Step 4: a learned recommendation counts only with artifact + schema + provenance."""
    if artifact is None:
        return None
    for k in ("model", "tier", "confidence", "provenance", "gate_passed"):
        if k not in artifact:
            return None  # schema invalid -> null, never a fabricated 'learned'
    if artifact["tier"] not in TIERS or not artifact["provenance"]:
        return None
    return {"model": str(artifact["model"]), "tier": artifact["tier"], "confidence": float(artifact["confidence"]), "gate_passed": bool(artifact["gate_passed"]), "provenance": str(artifact["provenance"])}


def _take_learned(tier: str, learned_tier: str, excluded: set[str]) -> tuple[str, bool]:
    """Step 4: an authoritative learned tier may only pick an equal-or-cheaper, non-excluded tier."""
    if learned_tier in TIERS and learned_tier not in excluded and TIERS.index(learned_tier) <= TIERS.index(tier):
        return learned_tier, True
    return tier, False


def _escalate(tier: str, insufficiency: dict[str, Any] | None) -> str:
    """Step 6: one tier up, and only after a RECORDED insufficiency."""
    if insufficiency is None:
        return tier
    if not insufficiency.get("recorded_at") or not insufficiency.get("error_class"):
        raise InvalidInputError("escalation requires a recorded insufficiency (recorded_at, error_class)", "insufficiency")
    return TIERS[min(TIERS.index(tier) + 1, len(TIERS) - 1)]


def route(f: RoutingFeatures, *, learned_artifact: dict[str, Any] | None = None, policy_exclusions: set[str] | None = None, insufficiency: dict[str, Any] | None = None) -> dict[str, Any]:
    """The §08 router output. ``insufficiency`` is a RECORDED prior failure that permits escalation."""
    excluded = policy_exclusions or set()
    # 1. hard constraints
    if not f.model_available and not f.tool_available:
        raise PolicyDeniedError("neither model nor tools available; nothing can run", field="availability")
    if f.privacy_class == "P3":
        raise PolicyDeniedError("P3 restricted goals are not routed automatically", field="privacy_class")
    h = heuristic_route(f)
    tier = h["tier"]
    if tier in excluded:
        raise PolicyDeniedError(f"tier {tier} excluded by policy", field="tier")
    if tier != "T0" and not f.model_available:
        tier = "T0"
        h = {**h, "downgraded": "model unavailable"}
    # 4. learned advice
    learned = validate_learned(learned_artifact)
    authority = "heuristic"
    if learned is not None and learned["gate_passed"]:
        tier, took = _take_learned(tier, learned["tier"], excluded)
        if took:
            authority = "learned"
    # 5. below-threshold confidence prefers the safer / cheaper tier
    if h["confidence"] < CONFIDENCE_THRESHOLD and TIERS.index(tier) > 0:
        tier = TIERS[TIERS.index(tier) - 1]
        h = {**h, "downgraded": "confidence below threshold"}
    # 6. escalate only after a recorded insufficiency
    tier = _escalate(tier, insufficiency)
    risk_score = {"read_only": 0.18, "write_local": 0.35, "external_send": 0.7, "production_mutate": 0.9}.get(f.side_effect_class, 0.9)
    budget = dict(TIER_BUDGETS[tier])
    if f.cost_budget_tokens is not None:
        budget["tokens"] = min(budget["tokens"], int(f.cost_budget_tokens))
    return {
        "intent": h["intent"],
        "tier": tier,
        "tier_name": TIER_NAMES[tier],
        "confidence": round(h["confidence"], 3),
        "agents": list(TIER_AGENTS[tier]),
        "risk": {"class": f.side_effect_class, "score": risk_score, "provenance": "static_priors"},
        "budget": budget,
        "learned": None if learned is None else {"model": learned["model"], "gate_passed": learned["gate_passed"], "tier": learned["tier"], "provenance": learned["provenance"]},
        "authority": authority,
        "heuristic": {"tier": h["tier"], "downgraded": h.get("downgraded")},
        "escalated_from_insufficiency": insufficiency is not None,
        "at": now_iso(),
    }


def from_production_routing(out: dict[str, Any]) -> dict[str, Any]:
    """Adapter: apps/dottie-harness-api ``route_goal`` output -> the spec's tier vocabulary."""
    tier = LEGACY_TIER.get(out.get("moma_tier", ""), None)
    if tier is None:
        raise InvalidInputError(f"unknown legacy tier {out.get('moma_tier')!r}", field="moma_tier")
    return {"intent": out.get("intent"), "tier": tier, "tier_name": TIER_NAMES[tier], "confidence": float(out.get("heuristic_score", 0.0)), "agents": list(out.get("recommended_agents", [])), "learned": None, "authority": "heuristic", "provenance": out.get("provenance", "request_derived_heuristic")}


# --- route_goal: the goal-string front door (scout, jarvisd) ---------------------------------

#: spec tiers -> MoMA-lite names, the inverse of LEGACY_TIER
MOMA_OF = {v: k for k, v in LEGACY_TIER.items()}
ADVISORY_ORDER = ("learned_mlp", "system_one")


def default_backends(*, learned: bool = False, system_one: bool | None = None) -> list[Any]:
    """Advisory backends for a route. The heuristic is implicit and always runs.

    ``learned`` turns on the orchestrator MLP (scout's ``--learned``). System One
    runs when ``DOTTIE_OS_URL`` is set, unless ``system_one`` says otherwise.
    """
    from dottie_loop.backends import LearnedMLPBackend, SystemOneBackend

    out: list[Any] = []
    if learned:
        out.append(LearnedMLPBackend())
    s1 = SystemOneBackend()
    if system_one if system_one is not None else s1.enabled:
        out.append(s1)
    return out


def route_goal(
    goal: str,
    *,
    backends: list[Any] | None = None,
    policy_exclusions: set[str] | None = None,
    insufficiency: dict[str, Any] | None = None,
    hard_constraint: dict[str, Any] | None = None,
    surface: str = "dottie_loop",
    trace: bool = True,
) -> dict[str, Any]:
    """Route a goal string. Default behaviour is exactly MoMA-lite's decision.

    Order (spec §08): 1. hard constraints (``hard_constraint``: an exact rule
    such as scout's ``mcp:`` prefix, and ``policy_exclusions``); 3. the MoMA-lite
    heuristic, always; 4. each advisory backend, whose tier is taken only when
    it is authoritative (``gate_passed`` AND human-stamped) and equal-or-cheaper;
    6. one tier up after a recorded ``insufficiency``. Step 5 (below-threshold
    downgrade) is NOT applied: MoMA-lite's ``confidence`` is a keyword-score
    ratio, not a probability, and thresholding it would change today's routes.

    The output keeps MoMA-lite's keys (``intent``, ``complexity``, ``moma_tier``,
    ``confidence``, ``routed_agents``, ...) with ``moma_tier`` = the final
    decision, and adds ``spec_tier``, ``authority``, ``heuristic_tier``,
    ``advisory`` (each backend's answer and whether it was authoritative) and
    ``trace`` (where the trace line went).
    """
    from dottie_loop import traces
    from dottie_loop.backends import MOMA_TIERS, HeuristicBackend, goal_features
    from dottie_loop.router_artifacts import is_authoritative

    excluded = policy_exclusions or set()
    heur = HeuristicBackend().answer(goal)
    detail = dict(heur["detail"])
    if hard_constraint is not None:
        forced = hard_constraint.get("tier")
        if forced not in MOMA_TIERS:
            raise InvalidInputError(f"hard constraint tier {forced!r} is not a MoMA-lite tier", field="hard_constraint")
        detail["intent"] = hard_constraint.get("intent", detail["intent"])
        detail["moma_tier"] = forced
        detail["moma_cap"] = MOMA_TIERS[forced]["cap"]
        detail["confidence"] = hard_constraint.get("confidence", detail["confidence"])
        detail["routed_agents"] = hard_constraint.get("routed_agents", detail["routed_agents"])
        heur = {**heur, "tier": forced, "reason": f"hard constraint: {hard_constraint.get('reason', 'exact rule')}"}
    heuristic_tier = heur["tier"]
    tier = LEGACY_TIER[heuristic_tier]
    if tier in excluded:
        raise PolicyDeniedError(f"tier {tier} excluded by policy", field="tier")

    advisory: dict[str, dict[str, Any]] = {"heuristic": {**{k: v for k, v in heur.items() if k != "detail"}, "authoritative": True}}
    for name in ADVISORY_ORDER:
        advisory[name] = {"backend": name, "enabled": False, "available": False, "tier": None, "authoritative": False,
                          "reason": "not enabled for this route"}
    authority = "heuristic"
    if hard_constraint is None:
        for b in backends if backends is not None else default_backends():
            ans = dict(b.answer(goal))
            ans["stamped"] = False
            authoritative = False
            if is_authoritative(ans):
                ans["stamped"] = True
                learned_tier = LEGACY_TIER.get(ans["tier"])
                if learned_tier is not None:
                    tier, authoritative = _take_learned(tier, learned_tier, excluded)
            ans["authoritative"] = authoritative
            if authoritative:
                authority = ans.get("backend", "learned")
                advisory["heuristic"]["authoritative"] = False
            advisory[ans.get("backend", getattr(b, "name", "backend"))] = ans
    tier = _escalate(tier, insufficiency)
    decided = MOMA_OF[tier]
    out: dict[str, Any] = {
        **detail,
        "moma_tier": decided,
        "moma_cap": MOMA_TIERS[decided]["cap"],
        "spec_tier": tier,
        "tier_name": TIER_NAMES[tier],
        "heuristic_tier": heuristic_tier,
        "authority": authority,
        "advisory": advisory,
        "escalated_from_insufficiency": insufficiency is not None,
        "policy": "dottie_loop.router.route_goal",
    }
    out["trace"] = (
        traces.record_route(out, surface=surface, goal=goal, features=goal_features(goal))
        if trace
        else {"trace_id": None, "path": None}
    )
    return out
