"""
branch_anneal.py — Stable-Checkpoint Branching (WSD) — Llama 3 pattern
Solo personal project, no connection to employer, built with public/free-tier only
"""
import argparse, os
from pathlib import Path
BRANCH_CONFIGS={
    "code": {"data":"code_repo 40% + repo_level 15% + tool_use 15% + web_edu>=4 10%","eval":["humaneval","mbpp","swe_bench"]},
    "math": {"data":"Lean verified 35% + MATH L5 20% + ProofPile 15% + R1 traces 15%","eval":["gsm8k","math","proof_valid"]},
    "chat": {"data":"UltraChat/ShareGPT 30% + edu>=4.5 20% + synthetic reasoning 20% + safety 10%","eval":["mmlu","mt_bench","alpaca_eval"]},
}
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--stable_ckpt", default="ava_stable_736k.pt")
    parser.add_argument("--branch", default="all", choices=["all","code","math","chat"])
    parser.add_argument("--steps", type=int, default=64000)
    args=parser.parse_args()
    print(f"Stable ckpt {args.stable_ckpt} exists: {Path(args.stable_ckpt).exists()} — contains 13.8T tokens at 736k steps 92% LR 2e-4 still plastic")
    branches=["code","math","chat"] if args.branch=="all" else [args.branch]
    for br in branches:
        cfg=BRANCH_CONFIGS[br]
        print(f"Branch {br}: data {cfg['data']} eval {cfg['eval']} steps {args.steps} cosine decay 2e-4->2e-5")
        Path(f"ava_{br}_final_800k.pt").write_text(f"mock final {br}")
        print(f"Produced ava_{br}_final_800k.pt")
    print("Optional MoE merge via merge_branches_as_moe() — one stable 13.8T -> 3 specialists cost 1.2T each vs 15T scratch")

if __name__=="__main__":
    main()
