# Solo personal project, no connection to employer, built with public/free-tier only
"""memory-router: Route between S1/S2/Planner bias control + ShardMemo Tier A/B/C scope-before-routing
v2.1.0 — ShardMemo: Tier A safety scope, Tier B memory scope, Tier C domain scope
Design targets (+6.87 F1, reduced scan scope) are reported under the `targets` key,
never inside `measured`; the emitted KL is a true divergence computed per run.
"""

from __future__ import annotations
from typing import Any, Dict, List

def describe() -> Dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ava_skills_loader", here.parent / "loader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)

BRANCH_BIASES = {
    "code": [0.25,0.45,0.05,0.25],
    "math": [0.10,0.65,0.20,0.05],
    "chat": [0.15,0.25,0.35,0.25],
    "base": [0.20,0.40,0.15,0.25],
}

TIER_A_SAFETY_KEYWORDS = ["blackmail","leverage","threat","extort","expose","shutdown","regret","danger","harm","unsafe"]
TIER_B_MEMORY_SIGNALS = {
    "S1_fast_8": ["react","quick","fast","reflex","pattern","intuition"],
    "S2_slow_300": ["remember","reason","logic","explain","verbalize","report","fact","openwiki","wiki"],
    "Planner_150": ["plan","temporal","deadline","sequence","then","after","schedule","future"],
    "Critic_30": ["safety","check","risk","audit","critic"]
}
TIER_C_DOMAIN_KEYWORDS = {
    "code": ["code","python","function","def ","class ","import","exec","bench"],
    "math": ["math","prove","theorem","logic","axiom","syllogism","truth table","phi"],
    "chat": ["hello","hi ","how are you","chat","talk","joke"],
    "base": []
}

def _shardmemo_scope_before_routing(instruction: str) -> Dict[str,Any]:
    instr = (instruction or "").lower()
    tier_a_triggered = any(kw in instr for kw in TIER_A_SAFETY_KEYWORDS)
    tier_a_scope = "Critic" if tier_a_triggered else "none"
    tier_b_scores = {}
    for scope, kws in TIER_B_MEMORY_SIGNALS.items():
        tier_b_scores[scope] = sum(1 for kw in kws if kw in instr)
    tier_b_scope = max(tier_b_scores, key=tier_b_scores.get) if tier_b_scores else "S2_slow_300"
    if all(v==0 for v in tier_b_scores.values()):
        tier_b_scope = "Router_default"
    tier_c_scores = {}
    for domain, kws in TIER_C_DOMAIN_KEYWORDS.items():
        tier_c_scores[domain] = sum(1 for kw in kws if kw in instr) if kws else 0.1
    tier_c_scope = max(tier_c_scores, key=tier_c_scores.get) if tier_c_scores else "base"
    # Heuristic estimate of how much scoping narrows the vector scan — NOT a measurement.
    estimated_scope_reduction = 0.0
    if tier_a_triggered:
        estimated_scope_reduction = 1.0
    else:
        if tier_b_scores.get(tier_b_scope,0) > 0:
            estimated_scope_reduction += 0.5
        if tier_c_scores.get(tier_c_scope,0) > 0:
            estimated_scope_reduction += 0.15
        estimated_scope_reduction = min(0.65, estimated_scope_reduction)
    return {
        "tier_a": {"triggered": tier_a_triggered, "scope": tier_a_scope, "keywords": TIER_A_SAFETY_KEYWORDS[:3]},
        "tier_b": {"scope": tier_b_scope, "scores": tier_b_scores},
        "tier_c": {"scope": tier_c_scope, "scores": tier_c_scores},
        "estimated_scope_reduction": estimated_scope_reduction,
    }

def route_score(instruction: str) -> Dict[str,float]:
    instr = instruction.lower()
    scores = {"S1":0.2,"S2":0.2,"Critic":0.1,"Planner":0.2,"Router":0.3}
    if any(k in instr for k in ["code","python","function"]):
        scores = {"S1":0.25,"S2":0.45,"Critic":0.05,"Planner":0.25,"Router":0.0}
    elif any(k in instr for k in ["math","prove","logic"]):
        scores = {"S1":0.10,"S2":0.65,"Critic":0.20,"Planner":0.05,"Router":0.0}
    elif any(k in instr for k in ["safety","blackmail","threat"]):
        scores = {"S1":0.05,"S2":0.20,"Critic":0.60,"Planner":0.15,"Router":0.0}
    elif any(k in instr for k in ["plan","temporal","deadline"]):
        scores = {"S1":0.15,"S2":0.25,"Critic":0.10,"Planner":0.50,"Router":0.0}
    return scores

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", instruction: str = "", branch: str = "base", **kw):
    query = instruction or kw.get("query","") or kw.get("instruction","")
    shardmemo = _shardmemo_scope_before_routing(query)
    if shardmemo["tier_a"]["triggered"]:
        routed = {"S1":0.05,"S2":0.15,"Critic":0.70,"Planner":0.10,"Router":0.0}
        branch = "chat"
    else:
        tb_scope = shardmemo["tier_b"]["scope"]
        if tb_scope == "S1_fast_8":
            routed = {"S1":0.55,"S2":0.15,"Critic":0.05,"Planner":0.15,"Router":0.10}
        elif tb_scope == "S2_slow_300":
            routed = {"S1":0.10,"S2":0.65,"Critic":0.10,"Planner":0.10,"Router":0.05}
        elif tb_scope == "Planner_150":
            routed = {"S1":0.15,"S2":0.20,"Critic":0.10,"Planner":0.50,"Router":0.05}
        else:
            routed = route_score(query)
        tc_scope = shardmemo["tier_c"]["scope"]
        if tc_scope in BRANCH_BIASES:
            branch = tc_scope
    bias = BRANCH_BIASES.get(branch, BRANCH_BIASES["base"])
    import math
    routed_list = [routed["S1"], routed["S2"], routed["Critic"], routed["Planner"]]
    # Renormalize both distributions over the same 4-way support (routed also carries a
    # Router mass that bias vectors do not model) so this is a true KL divergence (>= 0).
    routed_sum = sum(routed_list) or 1.0
    bias_sum = sum(bias) or 1.0
    p = [r / routed_sum for r in routed_list]
    q = [b / bias_sum for b in bias]
    kl = sum(pi * math.log(pi / max(qi, 1e-9)) for pi, qi in zip(p, q) if pi > 0)
    measured={
        "routed": routed,
        "bias": bias,
        "branch": branch,
        "kl": kl,
        "shardmemo": shardmemo,
        "scope_before_routing": True,
        "estimated_scope_reduction": shardmemo["estimated_scope_reduction"],
    }
    recalled, recall_error = _recall_minted(query, limit=int(kw.get("memory_limit", 3)),
                                            store_dir=kw.get("memory_store_dir"))
    measured["recalled_memories"] = recalled
    if recall_error is not None:
        measured["memory_recall_error"] = recall_error
    # Design targets — aspirations, never measurements; kept OUTSIDE measured.
    targets = {"target_f1_improvement": 6.87, "target_kl_w": 0.4, "inter_mi_target": 0.45}
    passed = kl < 1.0
    return {"skill":"memory-router","mode":mode,"measured":measured,"targets":targets,
            "pass":passed,"bar":"kl<1.0 + ShardMemo Tier A/B/C","shardmemo":shardmemo}


def _recall_minted(instruction: str, limit: int = 3, store_dir=None) -> tuple[List[Dict[str, Any]], str | None]:
    """Retrieval half of the memory layer: read shards written by the memory-mint skill.

    Same Tier-B scoping in both directions (mint tags with our _shardmemo_scope_before_routing;
    query re-derives the scope from the instruction), so recall only touches one shard file.

    Returns (memories, error). mint-not-installed degrades silently to ([], None) —
    routing output is unchanged except for the additive key. Any OTHER failure
    (store corruption, permissions, schema drift) is surfaced as an error string so
    it is never silently swallowed.
    """
    import importlib.util
    import sys
    from pathlib import Path
    mint_path = Path(__file__).resolve().parent.parent / "memory-mint" / "skill.py"
    if not mint_path.exists():
        return [], None  # memory-mint not installed: silent, expected degradation
    try:
        name = "ava_memory_mint_skill"
        if name in sys.modules:
            mint = sys.modules[name]
        else:
            spec = importlib.util.spec_from_file_location(name, mint_path)
            if spec is None or spec.loader is None:
                return [], None
            mint = importlib.util.module_from_spec(spec)
            sys.modules[name] = mint  # required before exec: dataclasses resolve cls.__module__
            spec.loader.exec_module(mint)
        store = mint.ShardStore(Path(store_dir)) if store_dir else mint.ShardStore()
        return [
            {"instruction": r["instruction"], "outcome": r["outcome"],
             "branch": r["branch"], "tier_b_scope": r["tier_b_scope"]}
            for r in store.query(instruction=instruction, limit=limit)
        ], None
    except ImportError:
        return [], None  # mint present but unimportable in this env: treated as not installed
    except (OSError, KeyError) as e:
        return [], f"{type(e).__name__}: {e}"
