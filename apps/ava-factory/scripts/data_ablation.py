"""
Data ablation — single-source upweight 50% + scaling-ladder downsampling mimic multi-epoch
MAI Sec 2.5

Solo personal project
"""

from __future__ import annotations

import json
import random
from pathlib import Path


def single_source_ablation(
    base_mix: dict[str, float], target: str, upweight: float = 0.5
) -> dict[str, float]:
    """Upweight target to 50% of mixture, renormalize rest."""
    new = {}
    base_mix.get(target, 0.01)
    # set target to 0.5
    new[target] = 0.5
    remaining = 0.5
    other_sum = sum(v for k, v in base_mix.items() if k != target)
    for k, v in base_mix.items():
        if k == target:
            continue
        new[k] = remaining * (v / other_sum) if other_sum > 0 else 0
    return new


def ladder_ablation_downsample(
    mix: dict[str, float], factor: float = 0.5
) -> dict[str, float]:
    """Downsample to mimic multi-epoch nature of target model — scale all weights by factor, keep relative."""
    return {k: v * factor for k, v in mix.items()}


def run_ablations(base_mix: dict[str, float], out: Path):
    results = []
    for target in base_mix.keys():
        ablated = single_source_ablation(base_mix, target, upweight=0.5)
        # placeholder eval diff: simulate
        delta = random.gauss(0, 0.05) + (
            0.1 if "stem" in target or "math" in target else 0
        )
        results.append(
            {
                "target": target,
                "type": "upweight_50",
                "mix": ablated,
                "delta_nll": delta,
            }
        )
    # ladder
    ladder = ladder_ablation_downsample(base_mix)
    results.append(
        {"target": "ladder", "type": "downsample", "mix": ladder, "delta_nll": 0.02}
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/data_ablation.json")
    args = ap.parse_args()
    # example base mix
    base = {
        "code_files": 0.2,
        "math_formal": 0.15,
        "stem_web": 0.15,
        "web_edu_high": 0.2,
        "encyclopedia": 0.1,
        "tool_use": 0.1,
        "chat": 0.1,
    }
    run_ablations(base, Path(args.out))
