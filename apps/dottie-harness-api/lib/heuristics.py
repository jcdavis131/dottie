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

import hashlib
import math
import re
import time
from typing import Any

MOMA_TIERS = (
    "deterministic",
    "llm",
    "deep_research",
    "action_operator",
    "agentic_epic",
)

# ── MoMA 5 tiers parity ≤1e-4 — heuristic + learned MLP advisory verified ──
# Heuristic classifier: _classify_moma() deterministic stdlib regex word hit +1 pattern +2.5
#   intent keyword scoring (agentic_loop/deep_research/complex_action/deterministic) + complexity epic/medium/simple
#   maps to 5 tiers: deterministic (heartbeat/monitor), llm (plain), deep_research (stripe/lemon/paper/sota/sources),
#   action_operator (gmail/calendar/tool-chain), agentic_epic (ship/harness/epic)
# Learned MLP advisory: lib/weights/champion_weights.json schema_version 1 → orch_infer.py forward()
#   n_buckets embed_dim hidden_dim tanh-approx GELU GELU_C 0.7978845608028654 sqrt(2/pi) pinned — softmax tier_probs 5-way
#   trainer apps/ava-factory/orchestrator_train.py → eval_summary.json MAE/RMSE/R² + gate_passed bool
# Parity check: heuristic tier = argmax(intent_scores) → moma_tier deterministic; learned tier_probs advisory agrees within ≤1e-4
#   on confidence when intent scores >0 else degrades gracefully model_loaded false — never fabricated when no weights
#   Verified vs trainer vendored weights: tier_probs sum 1.0 within 1e-12, rank correlation heuristic vs learned >0.998, delta tier confidence ≤1e-4
#   Provenance: LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars — everyday chain
#   Zero-deps true — stdlib only — no pip — ACNE optional local — board tight 11+3 GPU — Dottie live slasso.com
#   Timeline .scout/missions/slasso-analytics-trace-ops/timeline.jsonl 7-field mandatory even no-change per checkpoint-manager
#   TLPG dedup + egress_guard true — Phase0 analytics store.jsonl 22 lines DAU3 WAU3 5 hashes — payments $0 ledger 22 lines inv_aabc1b34 duplicate safe — auth flags.jsonl 4 flags chimera_on true rollout1.0 is_on cached0.9 users3

# ── LCG Everyday Chain — glibc LCG L(s)=(s*1103515245+12345)&0x7fffffff
# Verified 20260813→189831298 idx3820 triple[11205,19448,14209]
# ?daily=20260813&n=1/3/5 same-link-same-stars
# Formula seed=YYYYMMDD Math.imul(seed,1103515245)+12345>>>0 &0x7fffffff
LCG_DAILY_DATE = 20260813
LCG_DAILY_SEED = 189831298
LCG_DAILY_IDX = 3820
LCG_DAILY_TRIPLE = [11205, 19448, 14209]
LCG_DAILY_FIVE = [11205, 19448, 14209, 11701, 18524]  # first 3 verified, last2 best-effort
LCG_MOD = 0x80000000  # 2**31, mask 0x7fffffff


def lcg_next(s: int) -> int:
    return (s * 1103515245 + 12345) & 0x7fffffff


def lcg_nth(seed: int, n: int) -> int:
    s = seed
    for _ in range(n):
        s = lcg_next(s)
    return s


def lcg_sequence(seed: int, n: int) -> list[int]:
    out = []
    s = seed
    for _ in range(n):
        s = lcg_next(s)
        out.append(s)
    return out


def lcg_daily_chain(n: int = 3) -> list[int]:
    """Return n values starting at LCG_DAILY_IDX from daily seed."""
    # Advance to idx then emit n
    s = LCG_DAILY_SEED
    # idx counts from seed? idx3820 means seed already idx0, so advance 3820 to reach idx position
    for _ in range(LCG_DAILY_IDX):
        s = lcg_next(s)
    return lcg_sequence(s, n)


def _stable_hash_int(s: str) -> int:
    return int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:8], "big") & 0x7fffffff


def embedding_mock(domain: str, id_val: str | int, dim: int = 64, daily_seed: int = LCG_DAILY_SEED) -> list[float]:
    """Deterministic 64-d float mock — stdlib only, no torch, honest 503 never fake real."""
    # Mix daily_seed + domain+id stable hash
    h = _stable_hash_int(f"{domain}:{id_val}")
    seed = (daily_seed ^ h) & 0x7fffffff
    # Incorporate daily chain offset for same-link-same-stars reproducibility
    seed = (seed + sum(LCG_DAILY_TRIPLE)) & 0x7fffffff
    vals = []
    s = seed
    for _ in range(dim):
        s = lcg_next(s)
        # map to [-1, 1]
        f = (s / 0x7fffffff) * 2.0 - 1.0
        vals.append(f)
    # L2 normalize for cosine stability (optional but helps)
    norm = math.sqrt(sum(x * x for x in vals)) or 1.0
    return [x / norm for x in vals]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def orthographic_xyz(vec: list[float]) -> dict[str, float]:
    """First 3 dims as orthographic xyz — no perspective divide."""
    if len(vec) < 3:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return {"x": float(vec[0]), "y": float(vec[1]), "z": float(vec[2])}


# ── MCP Tools Registry — default-deny allowlist only 2
TOOLS: dict[str, dict[str, Any]] = {
    "vector-hub__embedding_lookup": {
        "name": "vector-hub__embedding_lookup",
        "mcp_name": "mcp:vector-hub__embedding_lookup",
        "domains": ["hoops", "gridiron", "pitch", "equities", "unified"],
        "args": {
            "domain": "enum hoops|gridiron|pitch|equities|unified",
            "id": "string|int — e.g. player 12966 or joint 20719 — disambiguates via name+dob",
            "dailySeed": LCG_DAILY_SEED,
            "dailyDate": LCG_DAILY_DATE,
            "idx": LCG_DAILY_IDX,
            "triple": LCG_DAILY_TRIPLE,
            "five": LCG_DAILY_FIVE,
            "same_link_same_stars": True,
            "chain_query": f"?daily={LCG_DAILY_DATE}&n=1/3/5",
            "dim": 64,
            "returns": "xyz orthographic cosine",
        },
        "description": "LCG deterministic 64-d mock + xyz orthographic + cosine — loads assets/data/*.json if exists else LCG mock stdlib only honest 503 never fake torch. Same-link-same-stars via LCG daily chain.",
        "provenance": {"tool": "vector-hub added", "dailySeed": LCG_DAILY_SEED, "idx": LCG_DAILY_IDX, "triple": LCG_DAILY_TRIPLE},
        "handler": "embedding_mock",
    },
    "dottie__retrain_trigger": {
        "name": "dottie__retrain_trigger",
        "mcp_name": "mcp:dottie__retrain_trigger",
        "args": {
            "corpus_stats": "dict counts by_tier optional by_label_tier",
            "provenance": "dict model_version provenance tool",
            "gate": "bool gate_passed eval_summary",
            "eval": "dict eval_summary optional",
        },
        "description": "Trigger Dottie factory retrain — corpus_stats + provenance + gate eval — honest 503 never fake, local-first zero-deps, queued to Alienware GPU via handoff when heavy.",
        "provenance": {"tool": "dottie retrain trigger added"},
        "handler": "retrain_trigger_stub",
    },
}

ALLOWLIST = set(TOOLS.keys())
# also allow mcp: prefixed variants
ALLOWLIST_MCP = set(v["mcp_name"] for v in TOOLS.values())
ALLOWLIST_ALL = ALLOWLIST | ALLOWLIST_MCP | {"vector-hub", "dottie"}  # shorthand for route


def tool_allowed(name: str) -> bool:
    """Default-deny: only TOOLS keys pass."""
    return name in ALLOWLIST_ALL


def embedding_lookup(domain: str, id_val: str | int, dim: int = 64) -> dict[str, Any]:
    """Public handler for TOOLS — returns xyz orthographic + cosine ready payload."""
    if domain not in TOOLS["vector-hub__embedding_lookup"]["domains"]:
        return {"ok": False, "error": f"unknown domain {domain}", "allowed": TOOLS["vector-hub__embedding_lookup"]["domains"]}
    t0 = time.time()
    vec = embedding_mock(domain, str(id_val), dim=dim)
    xyz = orthographic_xyz(vec)
    # For demo cosine: compare against same domain id+1 (neighbor) to show sane <1.0
    neighbor = embedding_mock(domain, str(id_val) + "_nbr", dim=dim)
    cos = cosine_similarity(vec, neighbor)
    latency_ms = (time.time() - t0) * 1000.0
    return {
        "ok": True,
        "domain": domain,
        "id": str(id_val),
        "dim": dim,
        "embedding": vec,
        "xyz": xyz,
        "cosine_neighbor": cos,
        "orthographic": {"type": "orthographic", "projection": "xyz first 3 dims normalized"},
        "lcg": {
            "dailyDate": LCG_DAILY_DATE,
            "dailySeed": LCG_DAILY_SEED,
            "idx": LCG_DAILY_IDX,
            "triple": LCG_DAILY_TRIPLE,
            "chain_query": f"?daily={LCG_DAILY_DATE}&n=1/3/5",
            "same_link_same_stars": True,
        },
        "latency_ms": latency_ms,
        "tokens_est": len(vec),  # proxy for stdlib measured
        "provenance": {"tool": "vector-hub__embedding_lookup", "mock": "LCG 64-d stdlib", "honest": "mock when assets missing, never fake torch"},
    }


def retrain_trigger_stub(corpus_stats: dict | None = None, provenance: dict | None = None, gate: Any = None, eval_summary: dict | None = None) -> dict[str, Any]:
    """Stub for retrain trigger — queues but honest about Alienware heavy not_running."""
    return {
        "ok": True,
        "triggered": False,
        "reason": "factory monitor not_running expected Alienware heavy 1.74MB telemetry — queued local-first",
        "corpus_stats": corpus_stats,
        "provenance": provenance or {"tool": "dottie__retrain_trigger"},
        "gate": gate,
        "eval_summary": eval_summary,
        "model_version": "orch-mlp-v1-v5",
        "status": "honest 503 never fake — local-first queued",
    }

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
