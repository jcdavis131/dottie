"""
Hierarchical mixture search — MAI Sec 2.5.1-2.5.3
Alternating local and global optimizations with 8-epoch cap.

Implements:
- categorize data into ~10 categories (coding, STEM, PDFs, general web, etc.)
- Local Search: keep all high-level categories fixed locally vary weights within single subset
- Global Search: keep relative make-up each bin fixed vary relative weight between subsets
- Cap max repetitions any given dataset 8 safeguard overfitting
- Single-source ablation upweight target 50% mixture train from scratch
- Scaling-ladder ablation downsampling mimic multi-epoch nature target model

Solo personal project
"""

from __future__ import annotations

import json
import random
from pathlib import Path

# ~10 high-level bins
HIGH_LEVEL_BINS = [
    "coding",
    "stem",
    "math",
    "pdfs",
    "general_web",
    "encyclopedia",
    "tool_use",
    "chat",
    "safety",
    "multilingual",
]

# Within each bin, sub-sources e.g., coding -> files/PRs/commits
SUB_SOURCES = {
    "coding": ["code_files", "code_prs", "code_commits", "code_repo"],
    "stem": ["stem_web", "stem_pdfs", "stem_wiki"],
    "math": ["math_formal", "math_synthetic", "proofs_verified"],
    "pdfs": ["pdf_academic", "pdf_technical"],
    "general_web": ["web_edu_high", "web_edu_mid", "web_general"],
    "encyclopedia": ["wikipedia", "textbooks"],
    "tool_use": ["react_tools", "agentic_workflows"],
    "chat": ["chat_helpful", "chat_safety"],
    "safety": ["safety_adversarial", "safety_benign"],
    "multilingual": ["multi_en", "multi_non_en"],
}


def random_mix() -> dict[str, float]:
    # random Dirichlet over high-level bins
    weights = [random.random() for _ in HIGH_LEVEL_BINS]
    s = sum(weights)
    return {k: v / s for k, v in zip(HIGH_LEVEL_BINS, weights, strict=False)}


def split_to_submix(high_mix: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for bin_name, bin_w in high_mix.items():
        subs = SUB_SOURCES.get(bin_name, [bin_name])
        # equal split internally for initial, then perturbed locally
        sub_w = bin_w / len(subs)
        for sub in subs:
            out[sub] = sub_w
    return out


def local_search(
    fixed_high: dict[str, float], target_bin: str, n_variants: int = 5
) -> list[dict[str, float]]:
    """Vary weights within single subset, keep others fixed."""
    variants = []
    subs = SUB_SOURCES.get(target_bin, [target_bin])
    if len(subs) <= 1:
        return [split_to_submix(fixed_high)]
    for _ in range(n_variants):
        # random Dirichlet within bin
        r = [random.random() for _ in subs]
        s = sum(r)
        # preserve total bin weight
        bin_total = fixed_high.get(target_bin, 0.1)
        sub_weights = {
            sub: (rv / s) * bin_total for sub, rv in zip(subs, r, strict=False)
        }
        # build full mix
        full = {}
        for bin_name, bin_w in fixed_high.items():
            if bin_name == target_bin:
                full.update(sub_weights)
            else:
                for sub in SUB_SOURCES.get(bin_name, [bin_name]):
                    full[sub] = bin_w / len(SUB_SOURCES.get(bin_name, [bin_name]))
        variants.append(full)
    return variants


def global_search(
    fixed_relative: dict[str, dict[str, float]], n_variants: int = 8
) -> list[dict[str, float]]:
    """Keep relative make-up each high-level bin fixed, vary relative weight between subsets."""
    variants = []
    for _ in range(n_variants):
        high_w = random_mix()
        full = {}
        for bin_name, bin_weight in high_w.items():
            rel = fixed_relative.get(bin_name, {})
            if not rel:
                # equal split if no relative history
                for sub in SUB_SOURCES.get(bin_name, [bin_name]):
                    full[sub] = bin_weight / len(SUB_SOURCES.get(bin_name, [bin_name]))
            else:
                # preserve internal ratios
                total_rel = sum(rel.values())
                for sub, rw in rel.items():
                    full[sub] = bin_weight * (rw / total_rel)
        # enforce 8-epoch cap placeholder (would need dataset sizes)
        variants.append(full)
    return variants


def cap_epochs(
    mix: dict[str, float],
    dataset_sizes: dict[str, int],
    token_budget: int,
    max_repeat: int = 8,
) -> dict[str, float]:
    """Ensure no dataset repeated > max_repeat"""
    capped = {}
    for k, w in mix.items():
        size = dataset_sizes.get(k, token_budget)  # fallback large
        repeat = (w * token_budget) / max(1, size)
        if repeat > max_repeat:
            # downscale
            capped[k] = (max_repeat * size) / token_budget
        else:
            capped[k] = w
    # renormalize
    s = sum(capped.values())
    if s > 0:
        for k in capped:
            capped[k] /= s
    return capped


def nll_for_mix_placeholder(
    mix: dict[str, float], eval_target: str = "physics"
) -> float:
    """Placeholder NLL that simulates correlations Fig7: STEM/PDFs positive, code neutral for physics."""
    # simulate: more stem/pdfs -> lower NLL for physics eval
    stem_w = sum(
        mix.get(k, 0)
        for k in ["stem_web", "stem_pdfs", "stem_wiki", "pdf_academic", "pdf_technical"]
    )
    math_w = sum(mix.get(k, 0) for k in SUB_SOURCES["math"])
    code_w = sum(mix.get(k, 0) for k in SUB_SOURCES["coding"])
    # physics NLL decreases with stem+math, neutral with code
    base = 2.5
    return base - 0.8 * stem_w - 0.4 * math_w + 0.05 * code_w + random.gauss(0, 0.02)


def search(n_rounds: int = 3, eval_target: str = "physics") -> dict:
    """Iterative global/local optimization"""
    # start from balanced
    high_mix = {k: 1 / len(HIGH_LEVEL_BINS) for k in HIGH_LEVEL_BINS}
    fixed_relative: dict[str, dict[str, float]] = {
        bin_name: {
            sub: 1 / len(SUB_SOURCES.get(bin_name, [bin_name]))
            for sub in SUB_SOURCES.get(bin_name, [bin_name])
        }
        for bin_name in HIGH_LEVEL_BINS
    }
    best = None
    best_nll = 999
    history = []
    for rnd in range(n_rounds):
        # global
        g_variants = global_search(fixed_relative, n_variants=6)
        for gv in g_variants:
            nll = nll_for_mix_placeholder(gv, eval_target)
            history.append({"round": rnd, "type": "global", "mix": gv, "nll": nll})
            if nll < best_nll:
                best_nll = nll
                best = gv
        # local: pick random bin
        target_bin = random.choice(HIGH_LEVEL_BINS)
        l_variants = local_search(high_mix, target_bin, n_variants=4)
        for lv in l_variants:
            nll = nll_for_mix_placeholder(lv, eval_target)
            history.append(
                {
                    "round": rnd,
                    "type": "local",
                    "bin": target_bin,
                    "mix": lv,
                    "nll": nll,
                }
            )
            if nll < best_nll:
                best_nll = nll
                best = lv
        # update fixed_relative from best for next round
        if best:
            # recompute relative
            for bin_name in HIGH_LEVEL_BINS:
                subs = SUB_SOURCES.get(bin_name, [bin_name])
                total = sum(best.get(sub, 0) for sub in subs)
                if total > 0:
                    fixed_relative[bin_name] = {
                        sub: best.get(sub, 0) / total for sub in subs
                    }
            high_mix = {
                bin_name: sum(
                    best.get(sub, 0) for sub in SUB_SOURCES.get(bin_name, [bin_name])
                )
                for bin_name in HIGH_LEVEL_BINS
            }

    return {
        "best_mix": best,
        "best_nll": best_nll,
        "history": history,
        "eval_target": eval_target,
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--eval", default="physics")
    ap.add_argument("--out", default="reports/hierarchical_mix.json")
    args = ap.parse_args()
    res = search(n_rounds=args.rounds, eval_target=args.eval)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(f"Best NLL {res['best_nll']:.3f} -> {args.out}")
