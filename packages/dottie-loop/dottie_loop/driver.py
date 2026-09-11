"""End-to-end loop driver (spec §01 primary sequence, §36 Runbook A).

Takes one goal from intake to a verified, checkpointed result, and — only with
capture consent — to a redacted pair-session trace and a decomposed reward::

    GoalEnvelope → PlanGraph → Kernel (admit/hydrate/execute/observe/verify/commit)
      → RunStore checkpoints + timeline → [opt-in] PairSessionTrace → RewardRecord

Executors are deterministic (argv, file check, python callable); a model client
may be registered as a callable but nothing here requires one. Every failure
becomes a typed goal state (``blocked`` or ``failed``), never a fabricated success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.capture import CaptureWriter, PairSessionTrace, capture_enabled
from dottie_loop.errors import (
    AUTO_RETRYABLE,
    ApprovalRequiredError,
    LoopError,
    PolicyDeniedError,
    classify_error,
)
from dottie_loop.execution import (
    Kernel,
    canonical_in_root,
    next_recovery_action,
    run_argv,
)
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.intake import GoalStore
from dottie_loop.plan import PlanGraph, PlanStep, plan_hash, validate_plan
from dottie_loop.reward import RewardInputs, compute_reward
from dottie_loop.timeline import RunStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from dottie_loop.approvals import ApprovalStore


@dataclass
class StepBinding:
    execute: Callable[[dict[str, Any]], bytes]
    verifier: Callable[[bytes], dict[str, Any]]
    tokens_est: int = 0
    token_method: str = "measured_zero"  # noqa: S105 - spec field, not a secret


def argv_binding(argv: list[str], root: Path, *, expect_exit: int = 0, expect_substring: str | None = None, timeout_s: float = 60.0) -> StepBinding:
    """Deterministic executor: run an argument array inside ``root``; verify exit + output."""

    def execute(_ctx: dict[str, Any]) -> bytes:
        res = run_argv(argv, cwd=root, timeout_s=timeout_s)
        return json.dumps({"exit_code": res["exit_code"], "stdout": res["stdout"], "stderr": res["stderr"]}).encode("utf-8")

    def verify(out: bytes) -> dict[str, Any]:
        obj = json.loads(out.decode("utf-8"))
        checks = {"exit_code": obj["exit_code"] == expect_exit}
        if expect_substring is not None:
            checks["substring"] = expect_substring in obj["stdout"]
        return {"pass": all(checks.values()), "checks": checks, "score": 10.0 if all(checks.values()) else 1.0}

    return execute, verify  # type: ignore[return-value]


def file_binding(path: str, root: Path, *, expect_substring: str | None = None) -> StepBinding:
    """Postcondition rule (§11): the FILE must exist and, if asked, contain the text."""

    def execute(_ctx: dict[str, Any]) -> bytes:
        p = canonical_in_root(path, root)
        return p.read_bytes() if p.exists() else b""

    def verify(out: bytes) -> dict[str, Any]:
        p = canonical_in_root(path, root)
        exists = p.exists()
        ok = exists and (expect_substring is None or expect_substring in out.decode("utf-8", errors="replace"))
        return {"pass": ok, "checks": {"exists": exists, "content": ok}, "score": 10.0 if ok else 1.0}

    return execute, verify  # type: ignore[return-value]


def make_binding(pair: Any, **kw: Any) -> StepBinding:
    execute, verify = pair
    return StepBinding(execute=execute, verifier=verify, **kw)


@dataclass
class RunSpec:
    """Serializable description of one end-to-end run (what ``loop run --spec`` reads)."""

    intent_text: str
    steps: list[dict[str, Any]]
    idempotency_key: str = field(default_factory=lambda: new_id("cli-"))
    capture: bool = False
    consent_version: str = "c1"
    capabilities: list[str] = field(default_factory=lambda: ["fs:read", "fs:write", "proc:argv"])
    budget_ceiling: dict[str, float] = field(default_factory=lambda: {"tokens": 0, "attempts": 10})

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunSpec:
        if not d.get("steps"):
            raise LoopError("spec has no steps", code="invalid_input", status=400, error_class="invalid_input")
        return cls(intent_text=d["intent_text"], steps=list(d["steps"]), idempotency_key=d.get("idempotency_key") or new_id("cli-"), capture=bool(d.get("capture", False)), consent_version=d.get("consent_version", "c1"), capabilities=list(d.get("capabilities") or ["fs:read", "fs:write", "proc:argv"]), budget_ceiling=dict(d.get("budget_ceiling") or {"tokens": 0, "attempts": 10}))


def build_plan(spec: RunSpec, goal_id: str, root: Path) -> tuple[PlanGraph, dict[str, StepBinding]]:
    """Turn spec steps into a validated PlanGraph plus executor bindings."""
    steps: list[PlanStep] = []
    bindings: dict[str, StepBinding] = {}
    kinds = {"argv": _bind_argv, "file": _bind_file}
    last = len(spec.steps) - 1
    for i, s in enumerate(spec.steps):
        kind = s.get("kind")
        binder = kinds.get(kind)
        if binder is None:
            raise LoopError(f"unknown step kind {kind!r} (argv|file)", code="invalid_input", status=400, error_class="invalid_input")
        sid = s.get("id") or f"step-{i + 1}"
        caps = ["proc:argv"] if kind == "argv" else ["fs:read"]
        steps.append(PlanStep(id=sid, idx=i, role=kind, depends_on=list(s.get("depends_on") or ([steps[-1].id] if steps else [])), capabilities=caps, budget={"attempts": 2}, postconditions=["verifier"], verifiers={"verifier": kind}, on_failure="retry" if kind == "argv" else "escalate", final=i == last))
        bindings[sid] = binder(s, root)
    plan = PlanGraph(goal_id=goal_id, steps=steps, goal_capabilities=spec.capabilities, budget_ceiling=spec.budget_ceiling, policy_digest=digest(spec.capabilities))
    validate_plan(plan)
    return plan, bindings


def _bind_argv(s: dict[str, Any], root: Path) -> StepBinding:
    return make_binding(argv_binding(list(s["argv"]), root, expect_exit=int(s.get("expect_exit", 0)), expect_substring=s.get("expect_substring"), timeout_s=float(s.get("timeout_s", 60))))


def _bind_file(s: dict[str, Any], root: Path) -> StepBinding:
    return make_binding(file_binding(str(s["path"]), root, expect_substring=s.get("expect_substring")))


def run_goal(spec: RunSpec, *, store_root: Path, root: Path, subject: str, surface: str = "cli", approvals: ApprovalStore | None = None, capture_flag: bool = False, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Runbook A, steps 1-16, for one goal. Returns the result record (also written to disk)."""
    store_root = Path(store_root)
    goals = GoalStore(store_root / "goals")
    payload = {"idempotency_key": spec.idempotency_key, "intent_text": spec.intent_text, "consent": {"execute": True, "capture_training": bool(spec.capture)}}
    ack, created = goals.submit(payload, authenticated_subject=subject, surface=surface)
    goal_id = ack["goal_id"]
    if not created:
        return {"goal_id": goal_id, "status": goals.status(goal_id), "replay": True}
    goal = goals.get(goal_id) or {}
    goals.transition(goal_id, "validated", reason="envelope validated")
    if goal.get("side_effect_class") in ("external_send", "production_mutate"):
        goals.transition(goal_id, "blocked", reason="external effect requires approval", dependency="approval")
        return {"goal_id": goal_id, "status": "blocked", "dependency": "approval", "side_effect_class": goal["side_effect_class"]}
    try:
        plan, bindings = build_plan(spec, goal_id, root)
    except LoopError as e:
        goals.transition(goal_id, "rejected", reason=e.message)
        return {"goal_id": goal_id, "status": "rejected", "error": e.to_dict()}
    goals.transition(goal_id, "planned", reason=f"plan {plan.plan_id} v{plan.version} {plan_hash(plan)[:12]}")
    run_id = new_id("run_")
    run_store = RunStore(store_root / "runs", run_id)
    kernel = Kernel(store=run_store, goal_id=goal_id, budget_tokens=int(spec.budget_ceiling.get("tokens") or 0) or None)
    goals.transition(goal_id, "running", reason=run_id)
    completed: set[str] = set()
    hashes: dict[str, str] = {}
    outcome: dict[str, Any] = {"task_ok": None, "verifier": None, "error_class": None}
    status = "verified"
    for sid in validate_plan(plan)["order"]:
        step = next(s for s in plan.steps if s.id == sid)
        b = bindings[sid]
        upstream = {d: hashes[d] for d in step.depends_on}
        attempt = 0
        while True:
            attempt += 1
            try:
                ck = kernel.run_step(step, completed=completed, upstream_hashes=upstream, execute=b.execute, verifier=b.verifier, attempt=attempt, plan_version=plan.version, capability_digest=plan.policy_digest, tokens_est=b.tokens_est, token_method=b.token_method)
                completed.add(sid)
                hashes[sid] = ck["output_hash"]
                break
            except (ApprovalRequiredError, PolicyDeniedError) as e:
                status = "blocked"
                outcome.update(task_ok=False, error_class=e.error_class, blocked_step=sid)
                break
            except LoopError as e:
                cls = classify_error(e.error_class)
                action = next_recovery_action(cls, attempt, max_retries=int(step.budget.get("attempts", 1)) - 1)
                if action == "retry" and cls in AUTO_RETRYABLE:
                    continue
                status = "failed"
                outcome.update(task_ok=False, error_class=cls, failed_step=sid, recovery=action)
                break
        if status != "verified":
            break
    if status == "verified":
        outcome.update(task_ok=True, verifier="pass")
        goals.transition(goal_id, "verified", reason="all postconditions verified")
        goals.transition(goal_id, "completed", reason="checkpoints durable")
        final_status = "completed"
    elif status == "blocked":
        goals.transition(goal_id, "blocked", reason=str(outcome.get("error_class")), dependency="approval" if outcome.get("error_class") == "approval_required" else "policy")
        final_status = "blocked"
    else:
        goals.transition(goal_id, "failed", reason=str(outcome.get("error_class")))
        final_status = "failed"
    summary = run_store.summary()
    result: dict[str, Any] = {"goal_id": goal_id, "run_id": run_id, "plan_id": plan.plan_id, "plan_hash": plan_hash(plan), "status": final_status, "outcome": outcome, "timeline": summary, "checkpoints": [c["checkpoint_id"] for c in run_store.checkpoints()], "trace_id": None, "reward": None, "at": now_iso()}
    # step 15: capture ONLY when consent is active AND the switch is on
    if goal.get("consent", {}).get("capture_training") and capture_enabled(capture_flag, env):
        writer = CaptureWriter(store_root / "traces" / "pair.jsonl", enabled=True, salt=subject)
        trace = PairSessionTrace(session_id=run_id, hashed_user_id=writer.hash_identity(subject), surface=surface, agent_id="dottie", goal={"intent": spec.intent_text, "task_family": "cli-run"}, turns=[{"role": "user", "text": spec.intent_text}], actions=[{"step": s.id, "role": s.role} for s in plan.steps], outcome=outcome, resources={"latency_ms": summary["latency_ms"], "tokens_est": summary["tokens_est"]}, checkpoints=[{k: e[k] for k in ("nodeId", "agentId", "attempt", "latency_ms", "tokens_est", "status", "errorClass")} for e in run_store.events()], lineage={"deletion_key": writer.hash_identity(subject), "source_hashes": sorted(hashes.values()), "goal_id": goal_id}, consent_version=spec.consent_version)
        written = writer.write(trace)
        result["trace_id"] = written["trace_id"] if written else None
        result["reward"] = compute_reward(RewardInputs(trace_id=result["trace_id"] or run_id, task_ok=outcome["task_ok"], evidence=[f"run:{run_id}"]))
    (run_store.dir / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result
