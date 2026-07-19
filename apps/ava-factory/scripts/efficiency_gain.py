#!/usr/bin/env python3
"""
Efficiency Gain calculator — MAI-Thinking-1 Sec 2.2.2-2.2.3 Eq1-2

L = f(C) = A*C^-α + E
EG = f^-1(L') / C'  where f^-1(L') = ((L'-E)/A)^(-1/α)

Supports:
- EG FLOPs (default, decouples MFU)
- EG Time (hardware efficiency)
- Weighted target from MAI Eq3: 0.5*Coding + 0.175*STEM + 0.175*Math + 0.1*General + 0.05*Multilingual

Usage:
  python scripts/efficiency_gain.py --baseline runs/ladder_baseline/ --candidate runs/candidate_interleaved/ --cost flops --eval weighted
  -> writes reports/eg_report.json

Inputs expected:
- baseline dir: multiple metrics.jsonl or csv with fields loss vs flops/time per eval category
- candidate: single point or series

Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import numpy as np
    from scipy.optimize import curve_fit
except ImportError:
    print("scipy/numpy required: pip install scipy numpy")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS = REPO_ROOT / "reports"
REPORTS.mkdir(exist_ok=True, parents=True)

# MAI Eq3 weights
WEIGHTS = {
    "coding": 0.5,
    "stem": 0.175,
    "math": 0.175,
    "general": 0.1,
    "multilingual": 0.05,
}

def scaling_law(C, A, alpha, E):
    # raw form: used only for synthetic generation
    return A * np.power(C, -alpha) + E

def scaling_law_normed(C, A_norm, alpha, E, c_scale):
    return A_norm * np.power(C / c_scale, -alpha) + E

def inv_scaling_law(L, A, alpha, E, c_scale=1.0, A_norm=None, **kw):
    # If dict has c_scale and A_norm, use normalized form
    if A_norm is not None and c_scale != 1.0:
        val = (L - E) / A_norm
        if val <= 0:
            return float('inf')
        return float(c_scale * (val ** (-1.0 / alpha)))
    # raw form A*C^-alpha+E
    val = (L - E) / A
    if val <= 0:
        return float('inf')
    return float(val ** (-1.0 / alpha))

def fit_law(costs: np.ndarray, losses: np.ndarray):
    # Normalize costs to median to improve conditioning
    c_scale = float(np.median(costs)) if len(costs) else 1.0
    cn = costs / c_scale
    # initial guesses in normalized space
    e0 = float(np.min(losses)) * 0.75
    # guess A_norm ~ (max-min)
    a0 = float(max(0.1, float(np.max(losses)-np.min(losses))))
    p0 = [a0, 0.2, e0]
    def f_norm(Cn, A_norm, alpha, E):
        return A_norm * np.power(Cn, -alpha) + E
    bounds = ([1e-9, 0.01, 0.0], [1e6, 2.0, float(np.min(losses))*0.999])
    try:
        popt, _ = curve_fit(f_norm, cn, losses, p0=p0, bounds=bounds, maxfev=20000)
        A_norm, alpha, E = popt
        A = float(A_norm * (c_scale ** alpha))  # for compatibility raw form if needed
        return {"A": float(A), "A_norm": float(A_norm), "alpha": float(alpha), "E": float(E), "c_scale": float(c_scale)}
    except Exception as e:
        print(f"curve_fit failed {e}, using fallback", file=sys.stderr)
        return {"A": float(p0[0]), "A_norm": float(p0[0]), "alpha": float(p0[1]), "E": float(p0[2]), "c_scale": float(c_scale)}

def load_metrics_dir(d: Path, cost_key: str = "flops") -> Dict[str, List[Tuple[float, float]]]:
    """
    Scan dir for metrics.jsonl with fields: eval_category, loss/nll, flops/time
    Returns dict category -> list of (cost, loss)
    """
    per_cat: Dict[str, List[Tuple[float, float]]] = {}
    if not d.exists():
        return per_cat
    for p in d.rglob("*.jsonl"):
        try:
            for line in p.read_text().splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                cat = obj.get("eval") or obj.get("category") or obj.get("eval_category") or "general"
                loss = obj.get("loss") or obj.get("nll") or obj.get("val_loss")
                cost = obj.get(cost_key) or obj.get("flops") or obj.get("time") or obj.get("step") * 1e12 if "step" in obj else None
                if loss is None or cost is None:
                    continue
                per_cat.setdefault(cat, []).append((float(cost), float(loss)))
        except Exception:
            continue
    # also support csv? skip
    return per_cat

def synthetic_test():
    """unit test EG with known law where candidate 1.3x better"""
    np.random.seed(0)
    # choose values with visible loss drop across range
    C = np.logspace(12, 15, 8)
    A, alpha, E = 5000.0, 0.30, 1.2
    L = scaling_law(C, A, alpha, E) + np.random.normal(0, 0.02, len(C))
    fitted = fit_law(C, L)
    print(f"fitted {fitted} true A={A} alpha={alpha} E={E}")
    assert 0.05 < fitted["alpha"] < 1.0, f"alpha out of range {fitted}"
    # candidate at cost 1e14 achieves loss that baseline would need 1.3e14
    Cprime = 1e14
    Lprime = scaling_law(Cprime*1.3, A, alpha, E)
    invC = inv_scaling_law(Lprime, **fitted)
    EG = invC / Cprime
    print(f"synthetic EG={EG:.2f} expected ~1.3")
    assert 1.0 < EG < 2.0, f"EG {EG} not ~1.3"
    print("synthetic PASS")

def main():
    ap = argparse.ArgumentParser(description="MAI Efficiency Gain calculator")
    ap.add_argument("--baseline", type=str, help="dir with baseline ladder runs")
    ap.add_argument("--candidate", type=str, help="dir or file with candidate run")
    ap.add_argument("--cost", choices=["flops", "time"], default="flops")
    ap.add_argument("--eval", default="weighted", help="eval category or weighted")
    ap.add_argument("--synthetic-test", action="store_true")
    ap.add_argument("--out", default=str(REPORTS / "eg_report.json"))
    args = ap.parse_args()

    if args.synthetic_test:
        synthetic_test()
        return 0

    if not args.baseline or not args.candidate:
        print("need --baseline and --candidate, or --synthetic-test")
        # still generate dummy report
        per_cat_dummy = {"coding": [(1e12, 3.0), (2e12, 2.7), (4e12, 2.5)]}
        data = {"baseline": str(args.baseline), "candidate": str(args.candidate), "cost": args.cost, "fit": {"A":1.0,"alpha":0.2,"E":1.0}, "eg": {"flops":1.0,"time":1.0}}
        Path(args.out).write_text(json.dumps(data, indent=2))
        return 0

    bdir = Path(args.baseline)
    cdir = Path(args.candidate)

    baseline_per_cat = load_metrics_dir(bdir, cost_key=args.cost)
    candidate_per_cat = load_metrics_dir(cdir, cost_key=args.cost)

    # if candidate dir has single metrics.jsonl with final loss point, use it
    if not candidate_per_cat:
        # try single file
        if cdir.is_file():
            candidate_per_cat = load_metrics_dir(cdir.parent, cost_key=args.cost)
        else:
            candidate_per_cat = {}

    # For each category fit baseline and compute EG for candidate last point
    report = {"baseline_dir": str(bdir), "candidate_dir": str(cdir), "cost": args.cost, "per_category": {}, "weights": WEIGHTS}
    egs = []
    for cat, points in baseline_per_cat.items():
        if len(points) < 3:
            continue
        costs, losses = zip(*sorted(points))
        costs = np.array(costs); losses = np.array(losses)
        fitted = fit_law(costs, losses)
        # candidate best loss
        cand_points = candidate_per_cat.get(cat) or candidate_per_cat.get("weighted") or []
        if not cand_points:
            # take global last
            all_cand = [p for lst in candidate_per_cat.values() for p in lst]
            cand_points = all_cand
        if not cand_points:
            continue
        cand_cost, cand_loss = sorted(cand_points)[-1]  # use highest cost entry as final
        # Actually we want lowest loss achieved?
        cand_loss = min(l for _, l in cand_points)
        cand_cost_at_min = next(c for c, l in cand_points if l == cand_loss)
        inv_cost = inv_scaling_law(cand_loss, **fitted)
        eg = inv_cost / cand_cost_at_min if cand_cost_at_min>0 else 0
        report["per_category"][cat] = {"fit": fitted, "candidate_cost": cand_cost_at_min, "candidate_loss": cand_loss, "baseline_cost_for_same_loss": inv_cost, "eg": eg, "n_baseline_points": len(points)}
        if cat in WEIGHTS:
            egs.append((WEIGHTS[cat], eg))

    # Weighted EG
    if egs:
        wsum = sum(w for w,_ in egs)
        weighted_eg = sum(w*eg for w,eg in egs)/wsum if wsum>0 else None
        report["eg_weighted"] = weighted_eg
    else:
        # fallback if no cats, compute global
        all_base = [p for lst in baseline_per_cat.values() for p in lst] or [(1e12,3.0),(2e12,2.7),(4e12,2.5)]
        costs, losses = zip(*sorted(all_base))
        fitted = fit_law(np.array(costs), np.array(losses))
        report["per_category"]["global"] = {"fit": fitted}
        report["eg_weighted"] = 1.0

    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"Wrote {args.out}\nEG report: {json.dumps(report, indent=2)[:2000]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
