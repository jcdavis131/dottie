"""DAG planning and budgets (spec §09, §37A PlanGraph).

A plan is a typed acyclic graph whose nodes can be authorized, scheduled, retried,
verified and resumed independently. :func:`validate_plan` runs every planner
validation in the spec and raises :class:`UnexecutableError` naming the first failing
check; :func:`plan_hash` covers normalized content and is what approval tokens
bind to. Once a run starts the plan is immutable: :func:`supersede` creates a new
version linked by ``supersedes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dottie_loop.errors import InvalidInputError, UnexecutableError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active

LLM_TIERS = ("T0", "T1", "T2", "T3", "T4")
RISK_CLASSES = ("read_only", "write_local", "external_send", "production_mutate")
ON_FAILURE = frozenset({"retry", "patch", "replan", "escalate", "stop"})
BUDGET_KEYS = ("tokens", "wall_seconds", "attempts", "api_calls", "bytes", "cost")
#: Risk classes whose steps MUST carry an approval edge (§09 "Every external effect
#: has an approval edge").
EFFECT_CLASSES = frozenset({"external_send", "production_mutate"})
DATA_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class PlanStep:
    id: str
    idx: int
    role: str
    depends_on: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    llm_tier: str = "T0"
    capabilities: list[str] = field(default_factory=list)
    risk: dict[str, Any] = field(
        default_factory=lambda: {
            "class": "read_only",
            "score": 0.0,
            "provenance": "static_priors",
            "approval_required": False,
        }
    )
    budget: dict[str, float] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    verifiers: dict[str, str] = field(default_factory=dict)
    on_failure: str = "escalate"
    mutates: list[str] = field(default_factory=list)
    data_class_in: str = "P1"
    data_class_out: str = "P1"
    final: bool = False
    blocked_on: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PlanGraph:
    goal_id: str
    steps: list[PlanStep]
    plan_id: str = field(default_factory=lambda: new_id("plan_"))
    version: int = 1
    planner: str = "dottie_loop.plan/0.1.0"
    created_at: str = field(default_factory=now_iso)
    policy_digest: str = ""
    budget_ceiling: dict[str, float] = field(default_factory=dict)
    goal_capabilities: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    supersedes: str | None = None
    schema: str = field(default_factory=lambda: active("plan-graph"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "version": self.version,
            "goal_id": self.goal_id,
            "planner": self.planner,
            "created_at": self.created_at,
            "policy_digest": self.policy_digest,
            "budget_ceiling": self.budget_ceiling,
            "goal_capabilities": self.goal_capabilities,
            "assumptions": self.assumptions,
            "supersedes": self.supersedes,
            "steps": [s.to_dict() for s in self.steps],
        }


def plan_hash(plan: PlanGraph) -> str:
    """Hash over NORMALIZED content: ids, edges, capabilities, risk, budgets, policy."""
    norm = {
        "goal_id": plan.goal_id,
        "policy_digest": plan.policy_digest,
        "steps": sorted(
            (
                {
                    "id": s.id,
                    "role": s.role,
                    "depends_on": sorted(s.depends_on),
                    "inputs": sorted(s.inputs),
                    "outputs": sorted(s.outputs),
                    "llm_tier": s.llm_tier,
                    "capabilities": sorted(s.capabilities),
                    "risk": s.risk,
                    "budget": s.budget,
                    "postconditions": sorted(s.postconditions),
                    "on_failure": s.on_failure,
                }
                for s in plan.steps
            ),
            key=lambda d: d["id"],
        ),
    }
    return digest(norm)


def topological_order(steps: list[PlanStep]) -> list[str]:
    """Kahn's algorithm; raises UnexecutableError on a cycle or a missing dependency."""
    ids = {s.id for s in steps}
    indeg = {s.id: 0 for s in steps}
    children: dict[str, list[str]] = {s.id: [] for s in steps}
    for s in steps:
        for d in s.depends_on:
            if d not in ids:
                raise UnexecutableError(f"step {s.id} depends on missing node {d}", "depends_on")
            if d == s.id:
                raise UnexecutableError(f"step {s.id} depends on itself", field="depends_on")
            indeg[s.id] += 1
            children[d].append(s.id)
    ready = sorted(i for i, n in indeg.items() if n == 0)
    order: list[str] = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for c in children[cur]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
                ready.sort()
    if len(order) != len(steps):
        raise UnexecutableError("plan graph contains a cycle", field="depends_on")
    return order


def validate_plan(plan: PlanGraph) -> dict[str, Any]:
    """Every §09 planner validation, in order. Returns a report on success."""
    steps = plan.steps
    if not steps:
        raise UnexecutableError("plan has no steps", field="steps")
    ids = [s.id for s in steps]
    if len(set(ids)) != len(ids):
        raise UnexecutableError("step ids must be unique", field="id")
    for s in steps:
        if s.llm_tier not in LLM_TIERS:
            raise InvalidInputError(f"step {s.id}: unknown llm_tier {s.llm_tier!r}", "llm_tier")
        if s.risk.get("class") not in RISK_CLASSES:
            raise InvalidInputError(f"step {s.id}: unknown risk class", field="risk.class")
        if s.on_failure not in ON_FAILURE:
            raise InvalidInputError(f"step {s.id}: unknown on_failure policy", "on_failure")
        for k in s.budget:
            if k not in BUDGET_KEYS:
                raise InvalidInputError(f"step {s.id}: unknown budget key {k!r}", "budget")

    # 1. acyclic + connected to a terminal outcome
    order = topological_order(steps)
    by_id = {s.id: s for s in steps}
    dependents: dict[str, set[str]] = {i: set() for i in ids}
    for s in steps:
        for d in s.depends_on:
            dependents[d].add(s.id)
    terminals = {i for i in ids if not dependents[i]}
    if not any(by_id[t].final for t in terminals):
        raise UnexecutableError("no terminal step is marked final", field="final")
    # every node must reach a final terminal
    reaches_final: dict[str, bool] = {}
    for sid in reversed(order):
        st = by_id[sid]
        reaches_final[sid] = st.final or any(reaches_final[c] for c in dependents[sid])
    dangling = sorted(i for i in ids if not reaches_final[i])
    if dangling:
        raise UnexecutableError(
            f"steps not connected to a terminal outcome: {dangling}", field="depends_on"
        )

    # 2. every external effect has an approval edge
    for s in steps:
        if s.risk.get("class") in EFFECT_CLASSES and not s.risk.get("approval_required"):
            raise UnexecutableError(
                f"step {s.id} has an external effect without an approval edge",
                field="risk.approval_required",
            )

    # 3. every output is consumed or declared final
    consumed = {i for s in steps for i in s.inputs}
    for s in steps:
        for o in s.outputs:
            if o not in consumed and not s.final:
                raise UnexecutableError(f"output {o!r} of {s.id} is neither consumed nor final", "outputs")
    # inputs must come from an upstream output (no hidden prompt-only dependencies)
    produced_by: dict[str, str] = {o: s.id for s in steps for o in s.outputs}
    for s in steps:
        for i in s.inputs:
            src = produced_by.get(i)
            if src is None:
                raise UnexecutableError(f"input {i!r} of {s.id} is produced by no step", "inputs")
            if src not in _ancestors(s.id, by_id):
                raise UnexecutableError(
                    f"input {i!r} of {s.id} is produced by {src}, which is not upstream",
                    field="inputs",
                )

    # 4. no step requests capability beyond goal scope
    allowed = set(plan.goal_capabilities)
    for s in steps:
        extra = sorted(set(s.capabilities) - allowed)
        if extra:
            raise UnexecutableError(f"step {s.id} requests capabilities beyond goal scope: {extra}", "capabilities")

    # 5. budgets sum within goal ceiling
    totals: dict[str, float] = {}
    for s in steps:
        for k, v in s.budget.items():
            totals[k] = totals.get(k, 0.0) + float(v)
    for k, ceiling in plan.budget_ceiling.items():
        if totals.get(k, 0.0) > float(ceiling):
            raise UnexecutableError(
                f"budget {k} sums to {totals[k]} over ceiling {ceiling}", field="budget"
            )

    # 6. verifier exists for every claimed postcondition
    for s in steps:
        for pc in s.postconditions:
            if pc not in s.verifiers:
                raise UnexecutableError(f"step {s.id}: postcondition {pc!r} has no verifier", "verifiers")

    # 7. parallel steps do not mutate the same resource unsafely
    for a in steps:
        for b in steps:
            if a.id >= b.id or not a.mutates or not b.mutates:
                continue
            shared = set(a.mutates) & set(b.mutates)
            if not shared:
                continue
            ordered = a.id in _ancestors(b.id, by_id) or b.id in _ancestors(a.id, by_id)
            if not ordered:
                raise UnexecutableError(
                    f"steps {a.id} and {b.id} mutate {sorted(shared)} without ordering",
                    field="mutates",
                )

    # 8. data sensitivity does not increase across a transform
    for s in steps:
        if DATA_RANK.get(s.data_class_out, 99) > DATA_RANK.get(s.data_class_in, -1):
            raise UnexecutableError(f"step {s.id} raises data sensitivity {s.data_class_in}->{s.data_class_out}", "data_class_out")

    # 9. fallback paths preserve the same policy constraints — replan/patch cannot
    #    be requested by a step whose failure policy is 'retry' on an effect step
    for s in steps:
        if s.risk.get("class") in EFFECT_CLASSES and s.on_failure == "retry":
            raise UnexecutableError(f"step {s.id}: an external effect may not auto-retry", "on_failure")

    # 10. all blocked dependencies are named before run start
    blocked = sorted(s.id for s in steps if s.blocked_on)
    return {
        "ok": True,
        "order": order,
        "terminals": sorted(terminals),
        "budget_totals": totals,
        "blocked_steps": blocked,
        "plan_hash": plan_hash(plan),
    }


def _ancestors(step_id: str, by_id: dict[str, PlanStep]) -> set[str]:
    seen: set[str] = set()
    stack = list(by_id[step_id].depends_on)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(by_id[cur].depends_on)
    return seen


def supersede(old: PlanGraph, steps: list[PlanStep], reason: str) -> PlanGraph:
    """Replanning creates a NEW version linked by ``supersedes``; the old is untouched."""
    new = PlanGraph(
        goal_id=old.goal_id,
        steps=steps,
        version=old.version + 1,
        planner=old.planner,
        policy_digest=old.policy_digest,
        budget_ceiling=dict(old.budget_ceiling),
        goal_capabilities=list(old.goal_capabilities),
        assumptions=[*old.assumptions, f"replan: {reason}"],
        supersedes=old.plan_id,
    )
    validate_plan(new)
    return new


def receipt_reusable(
    old_step: PlanStep, new_step: PlanStep, old_policy_digest: str, new_policy_digest: str
) -> bool:
    """A completed node receipt may be reused only when inputs and policy still match."""
    return (
        sorted(old_step.inputs) == sorted(new_step.inputs)
        and old_step.role == new_step.role
        and sorted(old_step.capabilities) == sorted(new_step.capabilities)
        and old_policy_digest == new_policy_digest
    )
