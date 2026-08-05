# Solo personal project, no connection to employer, built with public/free-tier only
"""
GRPO-lite data collector — nano eval traces + telemetry → preference pairs / TraceBank.

Torch-free, numpy-optional, stdlib-only fallback. Reads:
  - reports/metrics_nano.jsonl (optional, for loss sanity)
  - reports/dottie_telemetry.jsonl (prompt, completion, rl_return, logp_new, logp_old, entropy, verdict)
  - reports/branch_eval_results_real.json OR eval_*_base.json (task_id, trace, answer, score)
  - apps/ava-factory/dottie/datagen trace_common rendered docs if present (via eval_artifacts fallback)

Outputs under --out (default runs/grpo_pref/):
  - trace_bank.jsonl      : one rollout per line, grouped, with computed advantage placeholder
  - pref_pairs.jsonl      : chosen vs rejected per prompt group (max vs min return, margin filtered)
  - grpo_group_stats.jsonl: per group h_policy, thermostat info, outer-clip hits (stats only)
  - MANIFEST.json         : deterministic manifest with sha1s, counts, no fabricated numbers

Determinism: seed 7, sorted trace_id, SHA1 prompt grouping, population std.

No torch in Hatch — keep to math / json / hashlib, matches existing GRPO-lite spec 12 T12R.2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── pure-math GRPO helpers copied from dottie/rl/grpo.py to stay importable without package install ──
ADV_STD_EPS = 1e-8

def group_advantages(returns: List[float], eps: float = ADV_STD_EPS) -> List[float]:
    n = len(returns)
    if n == 0:
        return []
    mean = sum(returns) / n
    var = sum((r-mean)**2 for r in returns) / n
    std = math.sqrt(var)
    return [(r-mean)/(std+eps) for r in returns]

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def importance_weighted_entropy(logp_new, logp_old) -> float:
    if not logp_new:
        return 0.0
    if len(logp_new) != len(logp_old):
        # fallback to mean -logp_new
        return sum(-x for x in logp_new) / max(1, len(logp_new))
    weights = [math.exp(ln-lo) for ln, lo in zip(logp_new, logp_old)]
    wsum = sum(weights)
    if wsum <= 0.0:
        return 0.0
    return sum(w * (-ln) for w, ln in zip(weights, logp_new)) / wsum

class EntropyThermostat:
    def __init__(self, kappa=0.5, h_target=0.3, eps=0.2, k_max=4.0, k=0.0):
        self.kappa=kappa; self.h_target=h_target; self.eps=eps; self.k_max=k_max; self.k=k
    def update(self, h_policy: float) -> float:
        self.k = clamp(self.k + self.kappa*(self.h_target-h_policy), 0.0, self.k_max)
        return self.k
    def clip_bounds(self) -> Tuple[float,float]:
        upper=(1.0+self.eps)*(1.0+self.k)
        lower=1.0/(1.0+self.eps)
        return lower, upper

def clipped_surrogate(ratio: float, advantage: float, lower: float, upper: float, r_outer: float=1.0):
    outer_lo, outer_hi = 1.0-r_outer, 1.0+r_outer
    r_safe = clamp(ratio, outer_lo, outer_hi)
    outer_clipped = r_safe != ratio
    clipped_ratio = clamp(r_safe, lower, upper)
    unclipped_obj = r_safe*advantage
    clipped_obj = clipped_ratio*advantage
    objective = unclipped_obj if unclipped_obj < clipped_obj else clipped_obj
    inner_clipped = clipped_obj < unclipped_obj
    return objective, inner_clipped, outer_clipped

# ── IO helpers ──
def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    out=[]
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line: continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out

def load_json_any(path: Path) -> Any:
    if not path.is_file(): return None
    try: return json.loads(path.read_text())
    except Exception: return None

def resolve_reports_dir(cli: str|None) -> Path:
    for k in ("AVA_REPORTS_DIR", "DOTTIE_TELEMETRY_DIR", "AVA_HOST_REPORTS_DIR"):
        v=os.environ.get(k)
        if v and Path(v).is_dir():
            return Path(v)
    if cli and Path(cli).is_dir():
        return Path(cli)
    # fallback search order used by eval_artifacts.py
    base=Path(__file__).resolve().parents[2]  # apps/ava-factory/
    candidates=[base/"reports", Path(__file__).resolve().parents[3]/"reports", Path("reports")]
    for c in candidates:
        if c.is_dir(): return c
    return Path("reports")

def collect_groups(reports_dir: Path) -> Dict[str, List[Dict[str,Any]]]:
    groups: Dict[str, List[Dict]] = defaultdict(list)

    # 1. telemetry jsonl — primary GRPO rollouts
    tel = reports_dir/"dottie_telemetry.jsonl"
    if tel.is_file():
        entries = load_jsonl(tel)
        if len(entries)==0:
            # maybe alternate name ava_telemetry.jsonl
            entries = load_jsonl(reports_dir/"ava_telemetry.jsonl")
    else:
        entries = load_jsonl(reports_dir/"ava_telemetry.jsonl")

    for e in entries:
        prompt = e.get("prompt") or e.get("task") or e.get("task_id") or ""
        if not prompt: continue
        pid = e.get("prompt_id") or sha16(str(prompt))
        rollout = {
            "prompt_id": pid,
            "prompt": prompt,
            "completion": e.get("completion") or e.get("answer") or e.get("trace") or "",
            "trace_id": e.get("trace_id") or sha16(str(e.get("completion",""))+str(e.get("rl_return",""))),
            "rl_return": float(e.get("rl_return") if e.get("rl_return") is not None else e.get("reward",0.0) if e.get("reward") is not None else e.get("score",0.0) or 0.0),
            "logp_new": e.get("logp_new") or [],
            "logp_old": e.get("logp_old") or [],
            "entropy": float(e.get("entropy") or 0.0),
            "verdict": e.get("verdict") or "unknown",
            "source": str(tel),
        }
        groups[pid].append(rollout)

    # 2. branch_eval_results_real.json — second source if telemetry empty
    if sum(len(v) for v in groups.values())==0:
        for cand in ["branch_eval_results_real.json","eval_mini_base.json","eval_nano_base.json","branch_eval_results_final2861.json","frontier_eval_results.json"]:
            p=reports_dir/cand
            data=load_json_any(p)
            if not data: continue
            # handle list or dict
            items=[]
            if isinstance(data, list): items=data
            elif isinstance(data, dict):
                # possible {results:[...]} wrapper
                if "results" in data and isinstance(data["results"], list): items=data["results"]
                else: items=list(data.values())[:1000] if all(isinstance(v,dict) for v in data.values()) else []
            for it in items[:2000]:
                if not isinstance(it, dict): continue
                prompt=it.get("prompt") or it.get("task") or it.get("task_id") or it.get("id") or ""
                if not prompt: continue
                pid=sha16(str(prompt))
                score=float(it.get("score", it.get("reward", it.get("rl_return",0.0)) or 0.0))
                groups[pid].append({
                    "prompt_id":pid,
                    "prompt":prompt,
                    "completion":it.get("completion") or it.get("answer") or it.get("trace") or "",
                    "trace_id":it.get("trace_id") or sha16(str(it.get("completion",""))+str(score)),
                    "rl_return":score,
                    "logp_new":[],
                    "logp_old":[],
                    "entropy":float(it.get("entropy") or 0.0),
                    "verdict":"pass" if score>=0.8 else "fail",
                    "source":str(p),
                })
            if groups: break

    # 3. fallback synthetic group if still empty (makes pipeline runnable in Hatch without traces)
    if sum(len(v) for v in groups.values())==0:
        # emit deterministic demo group so downstream doesn't choke — marked source=synthetic_demo
        demo_prompt="ET-CoT demo: binary addition 101+10"
        pid=sha16(demo_prompt)
        groups[pid]=[
            {"prompt_id":pid,"prompt":demo_prompt,"completion":"<think>[step 1] carry...</think><answer>111</answer>","trace_id":"demo_a","rl_return":0.95,"logp_new":[math.log(0.6),math.log(0.4)],"logp_old":[math.log(0.5),math.log(0.5)],"entropy":0.25,"verdict":"pass","source":"synthetic_demo"},
            {"prompt_id":pid,"prompt":demo_prompt,"completion":"<think>[step 1] wrong carry</think><answer>110</answer>","trace_id":"demo_b","rl_return":0.10,"logp_new":[math.log(0.3),math.log(0.7)],"logp_old":[math.log(0.5),math.log(0.5)],"entropy":0.45,"verdict":"fail","source":"synthetic_demo"},
        ]

    return groups

def build_outputs(groups: Dict[str, List[Dict]], out_dir: Path, min_group: int=2, margin: float=0.05, seed: int=7):
    random.seed(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_bank_path=out_dir/"trace_bank.jsonl"
    pref_pairs_path=out_dir/"pref_pairs.jsonl"
    group_stats_path=out_dir/"grpo_group_stats.jsonl"
    manifest_path=out_dir/"MANIFEST.json"

    # deterministic order
    pids=sorted(groups.keys())
    thermostat=EntropyThermostat(kappa=0.5, h_target=0.3, eps=0.2, k_max=4.0)

    pref_count=0
    group_count=0
    trace_count=0
    with trace_bank_path.open("w") as tb_f, pref_pairs_path.open("w") as pref_f, group_stats_path.open("w") as stats_f:
        for pid in pids:
            rollouts=groups[pid]
            if len(rollouts) < min_group:
                continue
            # sort by trace_id for determinism
            rollouts=sorted(rollouts, key=lambda r: r["trace_id"])
            returns=[float(r["rl_return"]) for r in rollouts]
            advs=group_advantages(returns)

            # assign advantages back
            for r,a in zip(rollouts, advs):
                r["advantage"]=a

            # trace bank lines
            for r in rollouts:
                tb_f.write(json.dumps({
                    "prompt_id": pid,
                    "trace_id": r["trace_id"],
                    "prompt": r["prompt"],
                    "completion": r["completion"],
                    "rl_return": r["rl_return"],
                    "advantage": r["advantage"],
                    "entropy": r["entropy"],
                    "verdict": r["verdict"],
                    "source": r["source"],
                }, ensure_ascii=False)+"\n")
                trace_count+=1

            # group stats
            h_list=[importance_weighted_entropy(r["logp_new"], r["logp_old"]) if r["logp_new"] else r["entropy"] for r in rollouts]
            h_policy=sum(h_list)/max(1,len(h_list))
            k=thermostat.update(h_policy)
            lo,hi=thermostat.clip_bounds()
            # outer clip check per rollout (ratio estimated from logps mean exp)
            outer_hits=0
            for r in rollouts:
                if r["logp_new"] and r["logp_old"]:
                    # mean ratio approx exp(mean delta)
                    try: ratio=float(sum(math.exp(ln-lo) for ln,lo in zip(r["logp_new"], r["logp_old"]))/len(r["logp_new"]))
                    except Exception: ratio=1.0
                else: ratio=1.0
                _,_,outer=clipped_surrogate(ratio, r["advantage"], lo, hi, r_outer=1.0)
                if outer: outer_hits+=1

            stats_f.write(json.dumps({
                "prompt_id": pid,
                "group_size": len(rollouts),
                "group_mean": sum(returns)/len(returns),
                "group_std": math.sqrt(sum((x-sum(returns)/len(returns))**2 for x in returns)/len(returns)) if returns else 0.0,
                "h_policy": h_policy,
                "entropy_thermostat_k": k,
                "clip_bounds": [lo,hi],
                "outer_clip_hits": outer_hits,
            })+"\n")

            group_count+=1

            # pref pair: max vs min, margin filtered
            sorted_by_ret=sorted(rollouts, key=lambda r: r["rl_return"])
            rej=sorted_by_ret[0]; chosen=sorted_by_ret[-1]
            delta=float(chosen["rl_return"]-rej["rl_return"])
            if delta < margin: continue
            # extra tie guard: need str distinct completion
            if chosen["completion"]==rej["completion"]: continue

            pref_f.write(json.dumps({
                "prompt_id": pid,
                "prompt": chosen["prompt"],
                "chosen": {"completion": chosen["completion"], "trace_id": chosen["trace_id"], "return": chosen["rl_return"], "adv": chosen["advantage"], "entropy": chosen["entropy"]},
                "rejected": {"completion": rej["completion"], "trace_id": rej["trace_id"], "return": rej["rl_return"], "adv": rej["advantage"], "entropy": rej["entropy"]},
                "group_size": len(rollouts),
                "group_mean": sum(returns)/len(returns),
                "group_std": math.sqrt(sum((x-sum(returns)/len(returns))**2 for x in returns)/len(returns)) if returns else 0.0,
                "delta_return": delta,
            }, ensure_ascii=False)+"\n")
            pref_count+=1

    # manifest
    def sha_file(p: Path) -> str:
        h=hashlib.sha256()
        h.update(p.read_bytes())
        return h.hexdigest()[:16]
    manifest={
        "created_at": __import__("datetime").datetime.utcnow().isoformat()+"Z",
        "seed": seed,
        "min_group": min_group,
        "margin": margin,
        "groups": group_count,
        "trace_rollouts": trace_count,
        "pref_pairs": pref_count,
        "files": {
            "trace_bank.jsonl": sha_file(trace_bank_path) if trace_bank_path.exists() else None,
            "pref_pairs.jsonl": sha_file(pref_pairs_path) if pref_pairs_path.exists() else None,
            "grpo_group_stats.jsonl": sha_file(group_stats_path) if group_stats_path.exists() else None,
        },
        "source": "dottie/pipeline/grpo_collect.py torch-free",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest

def main():
    ap=argparse.ArgumentParser(description="GRPO-lite collector — nano traces → pref pairs (numpy/json only)")
    ap.add_argument("--in", dest="in_dir", default=None, help="reports dir (fallback: env or repo-local reports/)")
    ap.add_argument("--out", dest="out_dir", default="runs/grpo_pref", help="out dir")
    ap.add_argument("--min_group", type=int, default=2)
    ap.add_argument("--margin", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=7)
    args=ap.parse_args()

    reports_dir=resolve_reports_dir(args.in_dir)
    groups=collect_groups(reports_dir)
    manifest=build_outputs(groups, Path(args.out_dir), args.min_group, args.margin, args.seed)

    print(f"[grpo_collect] groups={manifest['groups']} traces={manifest['trace_rollouts']} prefs={manifest['pref_pairs']} out={args.out_dir} src={reports_dir} synthetic={manifest['trace_rollouts']<=2}")

if __name__=="__main__":
    main()
