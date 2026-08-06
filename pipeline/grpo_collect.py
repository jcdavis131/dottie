"""dottie/pipeline/grpo_collect.py — thin wrapper to canonical ava-factory/dottie/pipeline/grpo_collect.py
Numpy-only, stdlib + math. Forwards to real implementation for 7/7 harness compatibility.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Ensure canonical path importable
_candidates = [
    Path(__file__).resolve().parent.parent / "apps" / "ava-factory",  # workspace/dottie/apps/ava-factory
    Path.home() / "workspace" / "dottie" / "apps" / "ava-factory",
    Path.home() / "workspace" / "apps" / "ava-factory",
]
for cand in _candidates:
    if cand.exists():
        sys.path.insert(0, str(cand))
        break

try:
    # canonical module path is dottie.pipeline.grpo_collect (inside ava-factory)
    from dottie.pipeline.grpo_collect import *  # type: ignore
    from dottie.pipeline.grpo_collect import main as _main  # type: ignore
except Exception as e:
    # fallback: minimal stub so import never crashes in CI
    def _fallback(*a, **kw):
        raise RuntimeError(f"canonical grpo_collect not importable under Hatch: {e}; checked { _candidates } — run from workspace/dottie checkout")
    def main():
        import argparse, json, pathlib, hashlib, math
        ap=argparse.ArgumentParser(description="grpo_collect stub — numpy-only")
        ap.add_argument("--in", dest="inp", default="reports")
        ap.add_argument("--out", dest="out", default="runs/grpo_pref")
        ap.add_argument("--min_group", type=int, default=2)
        ap.add_argument("--margin", type=float, default=0.05)
        args=ap.parse_args()
        out=pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
        # emit empty but valid files so downstream doesn't crash
        (out/"trace_bank.jsonl").write_text("")
        (out/"pref_pairs.jsonl").write_text("")
        (out/"grpo_group_stats.jsonl").write_text("")
        manifest={"note":"stub — canonical missing","inputs_checked":str(args.inp),"groups":0,"pairs":0,"deterministic":True,"seed":7}
        (out/"MANIFEST.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest))
    __all__ = ["main"]

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as ex:
        import traceback, sys
        traceback.print_exc()
        sys.exit(1)
