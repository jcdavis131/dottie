"""
harness runner — end-to-end run loop for `scout harness run`.

Pipeline: route -> plan -> execute -> checkpoint/timeline -> critic.

Everything in this module is deterministic and local: the executors are pure
python functions over the goal text and prior artifacts — no network (the plugin
manifest pins capabilities network:false), no external model calls, no subprocess.
Latencies in the timeline are MEASURED with time.perf_counter(); token counts are
MEASURED as 0 — deterministic executors consume no external-model tokens, and
artifact size is retained separately as artifact_chars per node. Provenance is
labeled on every record.

Import order contract: this module imports routing helpers from
bigbang.plugins.harness.cli at module level. That is safe (no cycle) because the
CLI only imports this module LAZILY inside the `run` command body, so cli is
always fully loaded before runner.
"""
from __future__ import annotations

import hashlib
import importlib.util
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

from bigbang.plugins.harness.cli import (
    INTENT_KEYWORDS,
    _classify_moma,
    _complexity,
    _routed_agents,
    _score_intent,
)
from bigbang.plugins.harness.timeline import append_event, g_history_stats

_REPO_ROOT = Path(__file__).resolve().parents[5]  # .../apps/scout-cli/bigbang/plugins/harness/runner.py -> repo root


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --- recovery ladder -----------------------------------------------------------
# Prefer the repo-root ladder (pipeline/recovery_ladder.py) via file-path import;
# in installed layouts where that file is absent, fall back to an inline replica
# of pipeline/recovery_ladder.py:17-31 with identical decisions.

_FAILURE_TAXONOMY = ["INPUT_CORRUPTION", "CONTEXT_STARVATION", "TOOL_FAILURE", "REASONING_COLLAPSE", "OUTPUT_CORRUPTION"]
_SIDE_EFFECT_CLASSES = ("READ", "WRITE_IDEMPOTENT", "WRITE_DESTRUCTIVE", "EXTERNAL_NOTIFY")


def _inline_recovery_ladder(error_class: str, side_effect: str, attempt: int) -> dict:
    """Inline replica of pipeline/recovery_ladder.py recovery_ladder (lines 17-31)."""
    if error_class not in _FAILURE_TAXONOMY:
        error_class = "TOOL_FAILURE"
    if side_effect not in _SIDE_EFFECT_CLASSES:
        side_effect = "READ"
    # hard gate
    if side_effect in ("WRITE_DESTRUCTIVE", "EXTERNAL_NOTIFY"):
        return {"action": "escalate", "reason": f"{side_effect} never auto — needs human gate", "attempt": attempt, "errorClass": error_class, "sideEffect": side_effect, "bounded": True, "bio_map": "Remodeling — human gate, parallel true"}
    if attempt == 1:
        return {"action": "retry1", "attempt": 1, "errorClass": error_class, "sideEffect": side_effect, "safe": side_effect in ("READ", "WRITE_IDEMPOTENT"), "bio": "Hemostasis — stop bleeding, retry exact", "next_if_fail": "patch"}
    if attempt == 2:
        return {"action": "patch", "attempt": 2, "errorClass": error_class, "sideEffect": side_effect, "fix": "single-resp patch — fix concrete file:line evidence, no reformat ocean", "bio": "Inflammation — narrow scope, one file, one resp", "next_if_fail": "replan"}
    if attempt == 3:
        return {"action": "replan", "attempt": 3, "errorClass": error_class, "sideEffect": side_effect, "dag_version_inc": True, "bounded": True, "bio": "Proliferation — pure-function DAG re-plan, version++ never mutate in place", "next_if_fail": "escalate"}
    return {"action": "escalate", "attempt": attempt, "errorClass": error_class, "sideEffect": side_effect, "bounded": True, "bio": "Remodeling — human gate, visible abandonment", "reason": "3 attempts exhausted — escalate with evidence packet"}


def _load_recovery_ladder() -> Callable[[str, str, int], dict]:
    path = _REPO_ROOT / "pipeline" / "recovery_ladder.py"
    try:
        if path.exists():
            spec = importlib.util.spec_from_file_location("scout_recovery_ladder", str(path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod.recovery_ladder
    except Exception:
        pass
    return _inline_recovery_ladder


_recovery_ladder = _load_recovery_ladder()


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


EXECUTORS: dict[str, Callable[[dict], str]] = {
    "strategist": _exec_strategist,
    "planner": _exec_planner,
    "deep-researcher": _exec_deep_researcher,
    "synthesist": _exec_synthesist,
    "executor": _exec_executor,
    "builder": _exec_builder,
    "critic": _exec_critic,
    "operator": _exec_operator,
}


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
                 status: str, error_class: str | None, runs_dir: Path) -> None:
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


def _running_score(nodes: list[dict]) -> float:
    if not nodes:
        return 0.0
    total = len(nodes)
    ok_ratio = sum(1 for n in nodes if n["status"] == "ok") / total
    artifact_ratio = sum(1 for n in nodes if n["artifact_chars"] > 0) / total
    return round(10 * (0.7 * ok_ratio + 0.3 * artifact_ratio), 2)


# --- run loop ------------------------------------------------------------------


def run_goal(goal: str, *, max_nodes: int = 0, seed: int = 0, run_id: str = "",
             runs_dir: Path | None = None) -> dict:
    """Route -> plan -> execute -> checkpoint/timeline -> critic. Deterministic, local."""
    # runs_dir default is HOME-relative (workspace canonical), never CWD-relative:
    # this environment resets CWD between shells and tests redirect HOME.
    runs_dir = Path(runs_dir) if runs_dir else Path.home() / "workspace" / "bundles" / "ultra" / "runs"
    rid = run_id or f"harness-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    created = _now_iso()
    run_dir = runs_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. ROUTE — deterministic, in-process. Note: confidence deliberately avoids
    # route_cmd's scores['llm'] KeyError path (cli.py:99-103) on zero-keyword goals.
    scores = {k: _score_intent(goal, k) for k in INTENT_KEYWORDS}
    best = max(scores.values())
    intent = max(scores, key=lambda k: scores[k]) if best > 0 else "llm"
    complexity = _complexity(goal)
    tier = _classify_moma(goal, intent, complexity)
    agents = _routed_agents(intent, complexity)
    confidence = round(min(0.96, best / 4.0), 2) if best > 0 else 0.4

    # 2. PLAN
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
        _log_attempt(rid, step, 1, lat1, art1, "ok" if ok1 else "fail", None if ok1 else "TOOL_FAILURE", runs_dir)
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
                _log_attempt(rid, step, 2, lat2, art2, "ok" if ok2 else "fail", None if ok2 else "TOOL_FAILURE", runs_dir)
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
                                 "complexity": complexity})

    # 6. CRITIC + verification economics (constants mirror verify_cmd cli.py:458-482)
    total = len(node_summaries)
    ok_nodes = sum(1 for n in node_summaries if n["status"] == "ok")
    failed_nodes = sum(1 for n in node_summaries if n["status"] == "failed")
    critic_score = _running_score(node_summaries)
    passed = critic_score >= 8.0
    score_before_last = score_history[-2] if len(score_history) >= 2 else 0.0
    # informational only — execution is never truncated by early_exit
    early_exit = abs(critic_score - score_before_last) < 0.3

    return {
        "runId": rid,
        "goal": goal,
        "intent": intent,
        "complexity": complexity,
        "tier": tier,
        "confidence": confidence,
        "routed_agents": agents,
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
        "provenance": {"latency": "measured", "tokens": "estimated"},
        "ok": True,
        "command": "harness run",
    }
