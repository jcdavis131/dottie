"""
prepare_longrope2.py — generate LongRoPE2 non-uniform per-dim factors
Solo personal project, no connection to employer, built with public/free-tier only

Generates factors for YaRN 10k->1M (scale 1..100) with critical_dim_shift 31->25
Usage:
  python scripts/prepare_longrope2.py --dim 128 --base 10000 --scales 1,2,4,8,16,32,100 --out data/rope_factors.json
  python scripts/prepare_longrope2.py --dim 64 --base 10000 --scales 100 --out data/rope_factors_64.json
"""
import argparse, json, math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from model_1b import longrope2_factors
import torch

def main():
    parser = argparse.ArgumentParser(description="Prepare LongRoPE2 factors")
    parser.add_argument("--dim", type=int, default=128, help="head_dim")
    parser.add_argument("--base", type=int, default=10000)
    parser.add_argument("--scales", type=str, default="1,2,4,8,16,32,100", help="comma scales")
    parser.add_argument("--critical_shift", type=int, default=6, help="31->25 shift")
    parser.add_argument("--sharpness", type=float, default=12.0)
    parser.add_argument("--out", type=str, default="data/rope_factors_longrope2.json")
    args = parser.parse_args()

    scales = [float(s) for s in args.scales.split(",")]
    print(f"Solo personal project, no connection to employer, built with public/free-tier only")
    print(f"Generating LongRoPE2 factors dim={args.dim} base={args.base} shift={args.critical_shift}")

    out = {
        "meta": {
            "dim": args.dim,
            "base": args.base,
            "critical_dim_shift": args.critical_shift,
            "sharpness": args.sharpness,
            "note": "LongRoPE2 non-uniform per-dim lambda_i = 1+(scale-1)*sigmoid_k(t-crit_t)^0.65 * resonance, YaRN 10x less tokens preserved via mscale",
            "citation": "LongRoPE2: Near-Lossless LLM Context Window Scaling, YaRN NTK"
        },
        "scales": {}
    }

    for scale in scales:
        inv, lam, crit, crit_t = longrope2_factors(args.dim, args.base, scale, args.critical_shift, args.sharpness)
        # mscale / attn_factor same as YaRN
        if scale <=1:
            attn_factor=1.0
            mscale=1.0
        else:
            attn_factor=0.1*math.log(scale)+1.0
            mscale=min(1.414, max(1.0, 0.1*math.log(scale)+1.0))
        out["scales"][str(scale)] = {
            "inv_freq": inv.tolist(),
            "lambda_factors": lam.tolist(),
            "critical": crit,
            "critical_t": crit_t,
            "attn_factor": attn_factor,
            "mscale": mscale,
            "lambda_stats": {
                "min": float(lam.min()),
                "max": float(lam.max()),
                "mean": float(lam.mean()),
                "first8": lam[:8].tolist(),
                "last8": lam[-8:].tolist()
            }
        }
        print(f"scale={scale:>6} crit={crit:5.2f} crit_t={crit_t:.3f} lam min {lam.min():.2f} max {lam.max():.2f} mean {lam.mean():.2f} attn {attn_factor:.3f} mscale {mscale:.3f}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {args.out} with {len(scales)} scales, {args.dim//2} pairs each")

    # also write small .pt for fast load
    pt_out = Path(args.out).with_suffix(".pt")
    torch.save({k: torch.tensor(v["inv_freq"]) for k,v in out["scales"].items()}, pt_out)
    print(f"Wrote {pt_out}")

if __name__ == "__main__":
    main()
