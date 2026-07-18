#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only
"""Efficiency Gain (EG) — one currency for comparing R&D levers against a baseline scaling curve.

EG answers: "how much compute would the *baseline* recipe need to reach the loss this
candidate reached?" divided by what the candidate actually spent. EG 1.3 = baseline would
need 30% more compute to match. Source: MAI-Thinking-1 hill-climbing review
(docs/RL_INTEGRATION.md). Two flavors, same math, different x-axis:

  EG_FLOPs — x = estimated FLOPs (or tokens x params proxy): algorithmic efficiency,
             independent of kernels/hardware.
  EG_Time  — x = wall-clock seconds: what training actually costs today.

A candidate with EG_FLOPs > 1 but EG_Time < 1 is an un-optimized win (the report's
LatentMoE MFU-crash case; this repo's DeltaNet T11.2 state) — keep climbing, fix kernels,
judge on the trend. Decision gates (ORCHESTRATION.md) require the EG *trend across >= 2
ladder rungs*, never a single point (rank-invariance finding).

Baseline model: power law  loss = a * x^(-b)  (+ optional irreducible floor c, fixed by
caller, subtracted before the fit). Fit is ordinary least squares in log-log space —
stdlib only, no numpy, per repo convention.

CLI:
  python efficiency_gain.py --baseline runs/baseline.jsonl --candidate runs/cand.jsonl \
      --x-key flops --y-key loss
JSONL rows need the two keys; extra keys ignored; a "label" key names candidate rows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PowerLawFit:
    """loss = a * x^(-b), fitted on points with loss > floor; floor is subtracted pre-fit."""

    a: float
    b: float
    floor: float
    n_points: int
    min_loss_seen: float  # smallest (floor-adjusted) baseline loss — extrapolation boundary

    def loss_at(self, x: float) -> float:
        return self.a * x ** (-self.b) + self.floor

    def compute_to_reach(self, loss: float) -> float:
        """Baseline compute needed to reach `loss`. Raises if loss <= floor (unreachable)."""
        adj = loss - self.floor
        if adj <= 0.0:
            raise ValueError(
                f"loss {loss} is at/below the irreducible floor {self.floor}; "
                "baseline can never reach it (EG undefined)"
            )
        return (self.a / adj) ** (1.0 / self.b)


def fit_power_law(points: list[tuple[float, float]], floor: float = 0.0) -> PowerLawFit:
    """OLS in log-log space over (compute, loss) points. Needs >= 2 distinct x values, b > 0."""
    usable = [(x, y - floor) for x, y in points if x > 0.0 and (y - floor) > 0.0]
    if len(usable) < 2:
        raise ValueError(f"need >= 2 usable points above the floor, got {len(usable)}")
    lx = [math.log(x) for x, _ in usable]
    ly = [math.log(y) for _, y in usable]
    n = float(len(usable))
    mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((v - mx) ** 2 for v in lx)
    if sxx == 0.0:
        raise ValueError("all baseline points share one compute value; cannot fit a curve")
    sxy = sum((vx - mx) * (vy - my) for vx, vy in zip(lx, ly))
    slope = sxy / sxx  # = -b
    b = -slope
    if b <= 0.0:
        raise ValueError(
            f"fitted exponent b={b:.4g} <= 0 — baseline loss does not improve with compute; "
            "check the data before trusting any EG from it"
        )
    a = math.exp(my - slope * mx)
    return PowerLawFit(a=a, b=b, floor=floor, n_points=len(usable),
                       min_loss_seen=min(y for _, y in usable) + floor)


@dataclass(frozen=True)
class EGResult:
    label: str
    eg: float
    candidate_compute: float
    candidate_loss: float
    baseline_compute_equiv: float
    extrapolated: bool  # candidate loss below any baseline point — trust with care


def efficiency_gain(fit: PowerLawFit, candidate_compute: float, candidate_loss: float,
                    label: str = "candidate") -> EGResult:
    if candidate_compute <= 0.0:
        raise ValueError("candidate compute must be > 0")
    base_c = fit.compute_to_reach(candidate_loss)
    return EGResult(
        label=label,
        eg=base_c / candidate_compute,
        candidate_compute=candidate_compute,
        candidate_loss=candidate_loss,
        baseline_compute_equiv=base_c,
        extrapolated=candidate_loss < fit.min_loss_seen,
    )


def eg_trend(rung_results: list[tuple[str, EGResult]]) -> dict:
    """Ladder verdict over (rung_label, EGResult) pairs, smallest rung first.

    Promotion rule (rank-invariance): every rung EG > 1 AND the largest rung's EG is not
    the worst — a candidate that only wins small is exactly the trap the finding warns about.
    """
    if len(rung_results) < 2:
        return {"verdict": "insufficient", "reason": "need >= 2 ladder rungs", "rungs": len(rung_results)}
    egs = [r.eg for _, r in rung_results]
    all_positive = all(e > 1.0 for e in egs)
    largest_not_worst = egs[-1] >= min(egs[:-1])
    verdict = "promote" if (all_positive and largest_not_worst) else "hold"
    return {
        "verdict": verdict,
        "egs": {label: round(r.eg, 4) for label, r in rung_results},
        "all_rungs_gt_1": all_positive,
        "largest_rung_not_worst": largest_not_worst,
        "extrapolated_rungs": [label for label, r in rung_results if r.extrapolated],
    }


def _read_jsonl(path: str, x_key: str, y_key: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if x_key not in row or y_key not in row:
                raise KeyError(f"{path}:{i + 1} missing '{x_key}' or '{y_key}'")
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--baseline", required=True, help="JSONL of baseline runs (the scaling curve)")
    p.add_argument("--candidate", required=True, help="JSONL of candidate runs to score")
    p.add_argument("--x-key", default="flops", help="compute field: flops for EG_FLOPs, seconds for EG_Time")
    p.add_argument("--y-key", default="loss", help="quality field (lower is better), e.g. loss or val_bpb")
    p.add_argument("--floor", type=float, default=0.0, help="irreducible loss floor, subtracted before fit")
    args = p.parse_args(argv)

    base = _read_jsonl(args.baseline, args.x_key, args.y_key)
    cand = _read_jsonl(args.candidate, args.x_key, args.y_key)
    fit = fit_power_law([(r[args.x_key], r[args.y_key]) for r in base], floor=args.floor)
    results = [
        efficiency_gain(fit, r[args.x_key], r[args.y_key], label=str(r.get("label", f"row{i}")))
        for i, r in enumerate(cand)
    ]
    out = {
        "fit": {"a": fit.a, "b": fit.b, "floor": fit.floor, "n_points": fit.n_points},
        "x_key": args.x_key,
        "results": [r.__dict__ for r in results],
    }
    if len(results) >= 2:
        out["trend"] = eg_trend([(r.label, r) for r in results])
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
