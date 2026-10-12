# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Minimal harness: observe -> policy -> route -> execute -> verify -> record.

Clean-room principle: each stage is a typed function in a middleware chain.
Policy, cost, and HITL are deterministic code between stages — the model never
negotiates its own budget and is never asked whether something is allowed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from dottie_core.heuristic import HeuristicModel
from dottie_core.model import Model, QueryKind, ScoredAnswer, TypedQuery
from dottie_core.policy import (
    Action, HITLRequiredError, Policy, PolicyDeniedError, confidence_ok, default_policy,
)
from dottie_core.state import Belief, Constraints, StateRef, WorldState, empty_state


@dataclass
class Goal:
    intent: str  # human-readable, for audit only
    state_seed: dict[str, Any] = field(default_factory=dict)
    constraints: Constraints = field(default_factory=Constraints)
    success_criteria: list[TypedQuery] = field(default_factory=list)


@dataclass
class CostRecord:
    model_units: float = 0.0
    tool_units: float = 0.0
    wall_seconds: float = 0.0
    by_stage: dict[str, float] = field(default_factory=dict)

    def total(self) -> float:
        return self.model_units + self.tool_units

    def exceeds(self, budget: float) -> bool:
        return self.total() > budget


@dataclass
class RunResult:
    goal_id: str
    status: str  # completed | failed | blocked | escalated
    final_state: WorldState
    decisions: list[ScoredAnswer] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    cost: CostRecord = field(default_factory=CostRecord)
    halt_reason: str = ""


@dataclass
class RunContext:
    goal: Goal
    state: WorldState
    policy: Policy
    model: Model
    tier: str | None = None
    routing_answer: ScoredAnswer | None = None
    verification: dict[str, Any] | None = None
    cost: CostRecord = field(default_factory=CostRecord)
    decisions: list[ScoredAnswer] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""


Middleware = Callable[[RunContext], RunContext]


def observe(ctx: RunContext) -> RunContext:
    """Goal -> WorldState v0. Seeds beliefs from goal.state_seed."""
    state = empty_state(ctx.goal.goal_id if hasattr(ctx.goal, "goal_id") else _new_id(),
                        ctx.goal.constraints)
    for i, (k, v) in enumerate(ctx.goal.state_seed.items()):
        state = state.update(Belief(
            belief_id=f"seed-{i}", key=k, value=v, confidence=1.0,
            source="prior", at_version=state.version,
        ), actor="harness")
    ctx.state = state
    return ctx


def policy_gate(ctx: RunContext) -> RunContext:
    """Check the goal's side-effect class against policy before anything runs."""
    action = Action(kind="run_goal", name=ctx.goal.intent[:64],
                    side_effect_class=ctx.state.constraints.side_effect_class)
    decision = ctx.policy.check(action, ctx.state)
    if not decision.allowed:
        ctx.halted, ctx.halt_reason = True, f"policy denied: {decision.reason}"
    elif decision.require_hitl:
        raise HITLRequiredError(action, decision, resume_token=_new_id())
    return ctx


def route(ctx: RunContext) -> RunContext:
    """One model call: which tier fits? Confidence-gated by policy floor."""
    if ctx.halted:
        return ctx
    query = TypedQuery(
        kind=QueryKind.CHOOSE,
        state_ref=StateRef(belief_keys=tuple(ctx.state.beliefs.keys())),
        options=("T0-deterministic", "T1-llm", "T2-deep-research"),
    )
    answer = ctx.model.decide(ctx.state, query)
    calibrated = ctx.model.calibration != "uncalibrated"
    ok, reason = confidence_ok(answer.best.confidence, ctx.policy, calibrated)
    if not ok:
        ctx.tier, ctx.halted = "T0-deterministic", False
        ctx.halt_reason = f"low confidence, fell back to T0: {reason}"
    else:
        ctx.tier = str(answer.best.value)
    ctx.routing_answer = answer
    ctx.decisions.append(answer)
    ctx.cost.model_units += 1.0
    return ctx


def execute(ctx: RunContext) -> RunContext:
    """Run the tier's work. Budget enforced BEFORE model calls, not after."""
    if ctx.halted:
        return ctx
    if ctx.cost.exceeds(ctx.policy.max_cost_units):
        ctx.halted, ctx.halt_reason = True, "budget exceeded before execute"
        return ctx
    # Slice MVP: the "work" is one CLASSIFY query against seeded state.
    # Real tools plug in here via the Tool protocol (future).
    query = TypedQuery(
        kind=QueryKind.CLASSIFY,
        state_ref=StateRef(belief_keys=tuple(ctx.state.beliefs.keys())),
        options=("code", "docs", "data"),
    )
    answer = ctx.model.decide(ctx.state, query)
    ctx.decisions.append(answer)
    ctx.cost.model_units += 1.0
    ctx.state = ctx.state.update(Belief(
        belief_id=_new_id(), key="classification",
        value=answer.best.value, confidence=answer.best.confidence,
        source=f"model:{ctx.model.model_id}", at_version=ctx.state.version,
    ), actor="harness")
    return ctx


def verify(ctx: RunContext) -> RunContext:
    """Check success criteria. Harness-owned verdict, not model opinion."""
    if ctx.halted:
        return ctx
    results = {}
    for crit in ctx.goal.success_criteria:
        answer = ctx.model.decide(ctx.state, crit)
        ctx.decisions.append(answer)
        results[crit.claim or crit.kind] = {
            "verdict": answer.best.value, "confidence": answer.best.confidence,
        }
    # MVP verdict: classification belief exists with confidence >= floor-ish.
    belief = ctx.state.beliefs.get("classification")
    passed = belief is not None and belief.confidence >= 0.2
    ctx.verification = {"passed": passed, "criteria": results}
    return ctx


def record(ctx: RunContext) -> RunContext:
    """Persist timeline + cost. Pure bookkeeping, never calls the model."""
    return ctx  # timeline lives on RunResult; persistence is the caller's job


DEFAULT_CHAIN: tuple[Middleware, ...] = (observe, policy_gate, route, execute, verify, record)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Harness:
    """Runs goals through the middleware chain. Owns lifecycle, policy, cost."""

    def __init__(self, model: Model | None = None, policy: Policy | None = None,
                 chain: tuple[Middleware, ...] = DEFAULT_CHAIN):
        self.model = model or HeuristicModel()
        self.policy = policy or default_policy()
        self.chain = chain

    def run(self, goal: Goal) -> RunResult:
        t0 = time.time()
        goal_id = _new_id()
        ctx = RunContext(goal=goal, state=empty_state(goal_id, goal.constraints),
                         policy=self.policy, model=self.model)
        timeline: list[dict[str, Any]] = []
        try:
            for stage in self.chain:
                s0 = time.time()
                ctx = stage(ctx)
                timeline.append({
                    "nodeId": stage.__name__, "agentId": "dottie-core", "attempt": 1,
                    "latency_ms": int((time.time() - s0) * 1000), "tokens_est": 0,
                    "status": "halted" if ctx.halted else "ok", "errorClass": "none",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                if ctx.halted and stage.__name__ != "route":
                    break
        except (PolicyDeniedError, HITLRequiredError) as e:
            return RunResult(goal_id=goal_id, status="blocked", final_state=ctx.state,
                             decisions=ctx.decisions, timeline=timeline,
                             cost=ctx.cost, halt_reason=str(e))
        except Exception as e:  # fail-closed: unexpected errors never silently pass
            return RunResult(goal_id=goal_id, status="failed", final_state=ctx.state,
                             decisions=ctx.decisions, timeline=timeline,
                             cost=ctx.cost, halt_reason=f"{type(e).__name__}: {e}")

        status = "completed"
        if ctx.halted:
            status = "blocked"
        elif ctx.verification and not ctx.verification.get("passed"):
            status = "failed"
        ctx.cost.wall_seconds = time.time() - t0
        return RunResult(goal_id=goal_id, status=status, final_state=ctx.state,
                         decisions=ctx.decisions, timeline=timeline,
                         cost=ctx.cost, halt_reason=ctx.halt_reason)
