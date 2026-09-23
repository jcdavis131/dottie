"""
harness runner — end-to-end run loop for `scout harness run`.

Pipeline: route -> plan -> execute -> checkpoint/timeline -> critic.

Everything in this module is deterministic and local: the executors are pure
python functions over the goal text and prior artifacts — no external model
calls, no subprocess, and no network with ONE declared exception: the
mcp-operator executor (mcp: goals only) makes a downstream MCP tool call after
the fail-closed gates in mcp_executor.py, including the default-deny user URL
allowlist. The plugin manifest declares that network axis.
Latencies in the timeline are MEASURED with time.perf_counter(); token counts are
MEASURED as 0 — deterministic executors consume no external-model tokens, and
artifact size is retained separately as artifact_chars per node. Provenance is
labeled on every record.

Routing (step 1) is dottie_loop.decide.decide (bounded context, then
dottie_loop.router.route_goal), the same decision plane as `scout route` and
jarvisd: MoMA-lite decides unless a learned backend is gate_passed AND
human-stamped. The route appends a trace line, and the run's
observed outcome (success/failure, recovery rung, escalation) is appended to
the same trace so `scout router pack` can label it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from dottie_loop import traces as router_traces
from dottie_loop.backends import complexity as complexity_of
from dottie_loop.backends import routed_agents
from dottie_loop.context import RunHistoryProvider
from dottie_loop.decide import decide
from dottie_loop.execution import recovery_ladder

from bigbang.plugins.harness import mcp_executor
from bigbang.plugins.harness.timeline import append_event, g_history_stats


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --- recovery ladder -----------------------------------------------------------
# The one ladder: dottie_loop.execution.recovery_ladder (pipeline/recovery_ladder.py
# re-exports it). scout depends on dottie-loop, so every layout has it; the
# file-path import of pipeline/ and the inline replica it needed are gone.

_recovery_ladder = recovery_ladder


# --- plan ---------------------------------------------------------------------
# Pure-python mirror of the graph_plan_cmd fallback DAG templates (cli.py:399-440).
# Deliberate non-action: no subprocess and no node planner — the js planner
# (~/workspace/bundles/ultra/graph_planner_garnet.js) is absent in this
# environment and run behavior must not depend on it.

_DAG_RESEARCH = [
    {"id": "observe-facts", "role": "deep-researcher", "desc": "wide sweep 5-7 sources"},
    {"id": "orient-memory", "role": "strategist", "desc": "3-lens + memory lattice"},
    {"id": "decide-triangulate", "role": "synthesist", "desc": "Collect→Cluster→Conflict→Crystallize"},
    {"id": "act-deliver", "role": "builder", "desc": "polished brief artifact"},
]
_DAG_HEARTBEAT = [
    {"id": "observe-tick", "role": "operator", "desc": "Observe real-time tick :13"},
    {"id": "orient-filter", "role": "strategist", "desc": "Orient filter culture/experience"},
    {"id": "act-noop", "role": "operator", "desc": "Act artifact heartbeat log even no-change"},
]
_DAG_EPIC = [
    {"id": "intent-decompose", "role": "strategist", "desc": "L1 opaque goal deconstruction"},
    {"id": "dag-architect", "role": "planner", "desc": "L2 DAG deterministic 3-7 nodes"},
    {"id": "layer-exec", "role": "executor", "desc": "L3 elite node runner OODA inner"},
    {"id": "build", "role": "builder", "desc": "Act polished deliverable"},
    {"id": "verify-budget", "role": "critic", "desc": "L4 verification econ budget3"},
]


def build_plan(goal: str, tier: str) -> list[dict]:
    """DAG template selection + per-step risk/side-effect, mirroring cli.py:399-440."""
    lower = goal.lower()
    if "compare stripe" in lower or "stripe vs" in lower:
        dag = _DAG_RESEARCH
    elif "heartbeat" in lower or "monitor" in lower:
        dag = _DAG_HEARTBEAT
    else:
        dag = _DAG_EPIC

    hist = g_history_stats()
    role_stats = hist.get("per_role", {})
    steps = []
    for i, node in enumerate(dag):
        role = node["role"]
        mined = role_stats.get(role, {})
        # failureRisk exactly as cli.py:429 — mined fail_rate when history exists, static prior otherwise
        risk = min(0.9, max(0.05, mined["fail_rate"])) if mined.get("runs", 0) > 0 else 0.2 + (0.15 if role in ("executor", "builder") else 0)
        llm_map = {
            "strategist": tier if tier != "llm" else "llm",
            "planner": "llm",
            "deep-researcher": "deep_research",
            "builder": "action_operator",
            "executor": "agentic_epic" if risk > 0.3 else "action_operator",
            "operator": "deterministic",
            "critic": "llm",
            "synthesist": "llm",
            "researcher": "deep_research",
        }
        steps.append({
            "id": node["id"],
            "idx": i,
            "role": role,
            "llmTier": llm_map.get(role, tier),
            "rationale": f"{node['desc']} — deterministic run driver GARNet {tier}, risk {risk:.2f}",
            "failureRisk": round(risk, 2),
            # sideEffect exactly as cli.py:438
            "sideEffect": "WRITE_DESTRUCTIVE" if role in ("builder", "executor") else "READ" if role == "operator" else "READ" if i == 0 else "WRITE_IDEMPOTENT",
            "desc": node["desc"],
        })
    return steps


# --- deterministic executors ---------------------------------------------------
# ctx = {'goal': str, 'node': step_dict, 'prior': dict[node_id -> artifact_str],
#        'seed': int, 'plan': [step_dict, ...]}
# All executors are pure functions of ctx: no network, no external model, no clock
# in the ARTIFACT text (so output is seed/goal-deterministic).

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CHAIN_SPLIT_RE = re.compile(r"(?:->|then|after|next|→)")  # chain signals from cli.py:64


def _exec_strategist(ctx: dict) -> str:
    clauses = [c.strip() for c in _CHAIN_SPLIT_RE.split(ctx["goal"].lower()) if c.strip()]
    lines = [f"decomposition: {len(clauses)} clause(s)"]
    lines.extend(f"- {c}" for c in clauses)
    return "\n".join(lines)


def _exec_planner(ctx: dict) -> str:
    node = ctx["node"]
    remaining = [s["id"] for s in ctx.get("plan", []) if s["idx"] > node["idx"]]
    if not remaining:
        return "remaining steps: none"
    return "\n".join(f"{i + 1}. {sid}" for i, sid in enumerate(remaining))


def _exec_deep_researcher(ctx: dict) -> str:
    tokens = _TOKEN_RE.findall(ctx["goal"].lower())
    top = Counter(tokens).most_common(5)
    lines = ["top goal tokens (local frequency count, no external sources):"]
    lines.extend(f"- {tok}: {n}" for tok, n in top)
    return "\n".join(lines)


def _exec_synthesist(ctx: dict) -> str:
    parts = [f"## {nid}\n{art}" for nid, art in ctx["prior"].items() if art]
    return "\n\n".join(parts) if parts else "no prior artifacts to synthesize"


def _exec_executor(ctx: dict) -> str:
    latest_id, latest = "goal", ctx["goal"]
    for nid, art in ctx["prior"].items():
        if art:
            latest_id, latest = nid, art
    digest = hashlib.sha256(latest.encode("utf-8")).hexdigest()[:16]
    return f"transform[{latest_id}]: words={len(latest.split())} sha256={digest}"


def _exec_builder(ctx: dict) -> str:
    lines = [f"# artifact — goal: {ctx['goal']}", ""]
    for nid, art in ctx["prior"].items():
        lines.append(f"## {nid}")
        lines.append(art if art else "(empty — node failed)")
        lines.append("")
    return "\n".join(lines)


def _exec_critic(ctx: dict) -> str:
    prior = ctx["prior"]
    non_empty = [nid for nid, art in prior.items() if art]
    builder_art = ""
    for nid, art in prior.items():
        if ("build" in nid or "deliver" in nid) and art:
            builder_art = art
    goal_tokens = sorted(set(_TOKEN_RE.findall(ctx["goal"].lower())))
    covered = [t for t in goal_tokens if t in builder_art.lower()] if builder_art else []
    lines = [
        f"non-empty artifacts: {len(non_empty)}/{len(prior)} ({', '.join(non_empty) if non_empty else 'none'})",
        f"goal tokens present in builder artifact: {len(covered)}/{len(goal_tokens)}",
    ]
    return "\n".join(lines)


def _exec_operator(ctx: dict) -> str:
    # no timestamp in the artifact — timestamps live in the timeline rows only
    return f"heartbeat {ctx['node']['id']} ok"


def _exec_mcp_operator(ctx: dict) -> str:
    """Proxied downstream MCP call. Failure signal is an exception (raise), so an
    MCP failure flows through the SAME recovery-ladder path as every other
    executor — no parallel failure handling."""
    spec = ctx["mcp"]
    res = mcp_executor.execute_mcp_action(spec["namespace"], spec["server"], spec["tool"], spec["args"])
    if res["status"] != "ok":
        raise RuntimeError(f"mcp {res['error_class']}: {res.get('error')}")
    # artifact keeps the full measured result (latency_ms/tokens_est/payload)
    return json.dumps(res, default=str, sort_keys=True)


EXECUTORS: dict[str, Callable[[dict], str]] = {
    "mcp-operator": _exec_mcp_operator,
    "strategist": _exec_strategist,
    "planner": _exec_planner,
    "deep-researcher": _exec_deep_researcher,
    "synthesist": _exec_synthesist,
    "executor": _exec_executor,
    "builder": _exec_builder,
    "critic": _exec_critic,
    "operator": _exec_operator,
}

#: Executors that do real work. Every other executor is a deterministic stub (a
#: pure function of the goal text), so its outcome says nothing about whether
#: the routed tier was sufficient. Outcomes are tagged `executor: stub|real`.
REAL_EXECUTORS = frozenset({"mcp-operator"})


def executor_kind(role: str) -> str:
    """real | stub for the executor that serves ``role``."""
    return "real" if role in REAL_EXECUTORS else "stub"


def _dispatch(step: dict, ctx: dict) -> str:
    # TEST-ONLY HOOK: SCOUT_RUN_FAIL_NODES is a comma-separated list of node ids.
    # A listed node raises here, BEFORE its executor runs, producing a genuine
    # measured failure event (not a fabricated row) for recovery-ladder tests.
    fail_nodes = {s.strip() for s in os.environ.get("SCOUT_RUN_FAIL_NODES", "").split(",") if s.strip()}
    if step["id"] in fail_nodes:
        raise RuntimeError("injected failure")
    fn = EXECUTORS.get(step["role"])
    if fn is None:
        raise RuntimeError(f"no deterministic executor registered for role {step['role']!r}")
    return fn(ctx)


# --- timeline / checkpoint -----------------------------------------------------


def _log_attempt(run_id: str, step: dict, attempt: int, latency_ms: float, artifact: str,
                 status: str, error_class: str | None, runs_dir: Path, tier: str = "") -> None:
    # MEASURED true cost: deterministic executors make no external model calls,
    # so the run consumed exactly 0 model tokens. len(artifact)//4 was an
    # estimate of a cost that does not exist here; artifact size stays available
    # as artifact_chars in the node summaries.
    tok = 0
    # Both spellings on purpose: the harness timeline store requires latency/tokens
    # (timeline.py:26) while the repo-root checkpoint contract requires
    # latency_ms/tokens_est (pipeline/checkpoint_manager.py:63).
    row = {
        "nodeId": step["id"],
        "agentId": step["role"],
        "attempt": attempt,
        "latency": latency_ms,
        "latency_ms": latency_ms,
        "tokens": tok,
        "tokens_est": tok,
        "status": status,
        "errorClass": error_class,
        "ts": _now_iso(),
        "runId": run_id,
        # extra fields (not in REQUIRED_FIELDS): the run-history index aggregates
        # success / recovery / latency per routed tier, and per executor kind.
        "tier": tier,
        "executor": executor_kind(step["role"]),
    }
    # Twice on purpose: default base feeds g_history_stats mining
    # (graph-plan / timeline stats); runs_dir base keeps the run self-contained.
    for base in (None, runs_dir):
        res = append_event(run_id, row, base=base)
        if not res.get("ok"):
            # append_event never raises; ok:False means the row itself is malformed,
            # which is a programming error here — surface it loudly.
            raise RuntimeError(f"timeline append rejected: {res.get('error')}")


def _write_checkpoint(run_dir: Path, run_id: str, nodes: list[dict], created: str,
                      route: dict | None = None) -> Path:
    # Deliberate non-action: DottieCheckpointManager's triple-write is NOT used
    # here — its _RUNS/_DOTTIE_RUNS constants (pipeline/checkpoint_manager.py:24-30)
    # resolve to HOME-independent absolute paths that would escape the test suite's
    # throwaway-HOME isolation and pollute the repo. One canonical write under
    # runs_dir satisfies self-containment.
    checkpoint = {
        "runId": run_id,
        "dag_version": 1,  # never mutated in place; a replan would write version 2
        "nodes": nodes,
        "created": created,
        "saved_at": _now_iso(),
        "version": "harness-run/0.1",
        "provenance": {
            "driver": "harness run",
            "executors": "deterministic local, no network, no external model calls",
            "latency": "measured perf_counter",
            "tokens": "measured 0 — no external-model tokens consumed; artifact size in artifact_chars",
            "store": "single canonical write under runs_dir",
            # Routing actually executed for this run — consumed by the
            # orchestration corpus miner (goal text + behavior labels).
            **(route or {}),
        },
    }
    path = run_dir / "checkpoint.json"
    path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    return path


# recovery ladder rungs, mildest first (pipeline/recovery_ladder.py)
_RUNGS = ["retry1", "patch", "replan", "escalate"]


def _running_score(nodes: list[dict]) -> float:
    if not nodes:
        return 0.0
    total = len(nodes)
    ok_ratio = sum(1 for n in nodes if n["status"] == "ok") / total
    artifact_ratio = sum(1 for n in nodes if n["artifact_chars"] > 0) / total
    return round(10 * (0.7 * ok_ratio + 0.3 * artifact_ratio), 2)


# --- run loop ------------------------------------------------------------------


def run_goal(goal: str, *, max_nodes: int = 0, seed: int = 0, run_id: str = "",
             runs_dir: Path | None = None, mcp_namespace: str = "",
             context_providers: list | None = None) -> dict:
    """Route -> plan -> execute -> checkpoint/timeline -> critic. Deterministic, local."""
    # mcp: goals are validated BEFORE any store write (mkdir/timeline/checkpoint)
    # so a misconfigured goal leaves no run artifacts and touches no network.
    mcp_action: dict | None = None
    if goal.startswith(mcp_executor.MCP_GOAL_PREFIX):
        if not mcp_namespace:
            return {"ok": False, "goal": goal, "command": "harness run",
                    "error": "mcp: goal requires an --mcp-namespace (default disabled) — no network or store write attempted"}
        parsed = mcp_executor.parse_mcp_goal(goal)
        if parsed is None or not parsed.get("ok"):
            return {"ok": False, "goal": goal, "command": "harness run",
                    "error": (parsed or {}).get("error", "unparseable mcp goal")}
        mcp_action = parsed

    # runs_dir default is HOME-relative (workspace canonical), never CWD-relative:
    # this environment resets CWD between shells and tests redirect HOME.
    runs_dir = Path(runs_dir) if runs_dir else Path.home() / "workspace" / "bundles" / "ultra" / "runs"
    rid = run_id or f"harness-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    created = _now_iso()
    run_dir = runs_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. ROUTE — dottie_loop.router, in-process. An mcp: goal is a hard
    # constraint (an exact protocol-prefix match, not a keyword score), so the
    # router records it as such and skips the advisory backends.
    hard = None
    if mcp_action is not None:
        hard = {"tier": "action_operator", "intent": "complex_action", "confidence": 1.0,
                "routed_agents": routed_agents("complex_action", complexity_of(goal)),
                "reason": "mcp: protocol prefix"}
    # decide() = bounded context (run history here; jarvisd adds its store via
    # context_providers) -> route_goal. The trace line carries the context
    # summary and the served state's hash, so this run's outcome labels a
    # record whose state matches what System One is served.
    providers = context_providers if context_providers is not None else [RunHistoryProvider()]
    routed = decide(goal, hints={"hard_constraint": hard} if hard else {}, providers=providers,
                    surface="scout.harness.run", cache=None)
    complexity = routed["complexity"]
    intent = routed["intent"]
    tier = routed["moma_tier"]
    agents = routed["routed_agents"]
    confidence = routed["confidence"]
    trace_id = routed["trace"]["trace_id"]

    # 2. PLAN
    if mcp_action is not None:
        # Single-node plan. EXTERNAL_NOTIFY on purpose: a downstream MCP call is
        # an external side effect scout cannot prove idempotent, so the recovery
        # ladder never auto-retries it — one attempt, then escalate.
        steps = [{
            "id": "mcp-call",
            "idx": 0,
            "role": "mcp-operator",
            "llmTier": "action_operator",
            "rationale": f"proxied MCP call {mcp_action['server']}__{mcp_action['tool']} via namespace {mcp_namespace}",
            "failureRisk": 0.35,  # static prior — downstream availability is unknown
            "sideEffect": "EXTERNAL_NOTIFY",
            "desc": f"call {mcp_action['server']}__{mcp_action['tool']}",
        }]
    else:
        steps = build_plan(goal, tier)
    if max_nodes > 0:
        steps = steps[:max_nodes]

    # 3-5. EXECUTE with recovery ladder + per-attempt timeline + per-node checkpoint
    prior: dict[str, str] = {}
    node_summaries: list[dict] = []
    score_history: list[float] = []
    checkpoint_path = run_dir / "checkpoint.json"

    for step in steps:
        ctx = {"goal": goal, "node": step, "prior": dict(prior), "seed": seed, "plan": steps}
        if mcp_action is not None:
            ctx["mcp"] = {"namespace": mcp_namespace, "server": mcp_action["server"],
                          "tool": mcp_action["tool"], "args": mcp_action["args"]}

        def _attempt(n: int, step: dict = step, ctx: dict = ctx) -> tuple:
            t0 = time.perf_counter()
            try:
                art = _dispatch(step, ctx)
                return True, art, (time.perf_counter() - t0) * 1000.0
            except Exception:
                return False, "", (time.perf_counter() - t0) * 1000.0

        artifact = ""
        status = "ok"
        error_class: str | None = None
        recovery_action: str | None = None
        attempts = 1

        ok1, art1, lat1 = _attempt(1)
        total_latency = lat1
        _log_attempt(rid, step, 1, lat1, art1, "ok" if ok1 else "fail", None if ok1 else "TOOL_FAILURE", runs_dir, tier)
        if ok1:
            artifact = art1
        else:
            error_class = "TOOL_FAILURE"
            decision = _recovery_ladder(error_class, step["sideEffect"], 1)
            recovery_action = decision["action"]
            if decision["action"] == "retry1":
                attempts = 2
                ok2, art2, lat2 = _attempt(2)
                total_latency += lat2
                _log_attempt(rid, step, 2, lat2, art2, "ok" if ok2 else "fail", None if ok2 else "TOOL_FAILURE", runs_dir, tier)
                if ok2:
                    artifact, status, error_class = art2, "ok", None
                else:
                    status = "failed"
                    # patch/replan are recorded for provenance, never executed here
                    recovery_action = _recovery_ladder(error_class, step["sideEffect"], 2)["action"]
            else:
                # destructive/notify side effects are never auto-retried
                status = "failed"

        prior[step["id"]] = artifact  # failed node contributes an empty artifact
        node_summaries.append({
            "id": step["id"],
            "role": step["role"],
            "status": status,
            "attempts": attempts,
            "latency_ms": round(total_latency, 3),
            "errorClass": error_class,
            "artifact_chars": len(artifact),
            "recovery_action": recovery_action,
        })
        score_history.append(_running_score(node_summaries))
        _write_checkpoint(run_dir, rid, node_summaries, created,
                          route={"goal": goal, "tier": tier, "intent": intent,
                                 "complexity": complexity,
                                 "authority": routed["authority"],
                                 "trace_id": trace_id})

    # 6. CRITIC + verification economics (constants mirror verify_cmd cli.py:458-482)
    total = len(node_summaries)
    ok_nodes = sum(1 for n in node_summaries if n["status"] == "ok")
    failed_nodes = sum(1 for n in node_summaries if n["status"] == "failed")
    critic_score = _running_score(node_summaries)
    passed = critic_score >= 8.0
    score_before_last = score_history[-2] if len(score_history) >= 2 else 0.0
    # informational only — execution is never truncated by early_exit
    early_exit = abs(critic_score - score_before_last) < 0.3

    # 7. OUTCOME -> router trace (what `scout router pack` labels from)
    actions = [n["recovery_action"] for n in node_summaries if n["recovery_action"]]
    kinds = Counter(executor_kind(n["role"]) for n in node_summaries)
    router_traces.record_outcome(trace_id, {
        # stub unless every executed node did real work: `scout router pack`
        # never labels from a stub outcome (synthetic rows never train).
        "executor": "real" if node_summaries and set(kinds) == {"real"} else "stub",
        "executors": dict(kinds),
        "run_id": rid,
        "ok": True,
        "tier": tier,
        "passed": passed,
        "critic_score": critic_score,
        "n_nodes": total,
        "ok_nodes": ok_nodes,
        "failed_nodes": failed_nodes,
        "recovery_actions": actions,
        "recovery_rung": max(actions, key=lambda a: _RUNGS.index(a) if a in _RUNGS else -1) if actions else None,
        "escalated": "escalate" in actions,
        "truncated": max_nodes > 0,
        "injected_failure": bool(os.environ.get("SCOUT_RUN_FAIL_NODES", "").strip()),
    }, surface="scout.harness.run")

    return {
        "runId": rid,
        "goal": goal,
        "intent": intent,
        "complexity": complexity,
        "tier": tier,
        "confidence": confidence,
        "routed_agents": agents,
        "authority": routed["authority"],
        "spec_tier": routed["spec_tier"],
        "advisory": routed["advisory"],
        "trace_id": trace_id,
        "seed": seed,
        "max_nodes": max_nodes,
        "nodes": node_summaries,
        "n_nodes": total,
        "ok_nodes": ok_nodes,
        "failed_nodes": failed_nodes,
        "critic_score": critic_score,
        "passed": passed,
        "early_exit": early_exit,
        "threshold_pass": 8.0,
        "timeline_path": str(run_dir / "timeline.jsonl"),
        "checkpoint_path": str(checkpoint_path),
        "runs_dir": str(runs_dir),
        "provenance": {"latency": "measured", "tokens": "measured 0"},
        "ok": True,
        "command": "harness run",
    }
