#!/usr/bin/env python3
"""Does FUSING lexical and dense retrieval beat either alone on the task slice?

Solo personal project, no connection to employer, built with public/free-tier only

WHY THIS EXISTS. Step 5 measured dense retrieval against the FTS5 lexical baseline,
found dense losing by ~1.77x, and concluded "the verdict stays lexical" (HANDOFF,
`5f5878f`, `3492360`). That comparison was always dense-OR-lexical. Nobody ran
dense-AND-lexical, and hybrid retrieval routinely beats both inputs because the two
systems fail on DIFFERENT queries — BM25 misses paraphrase, embeddings miss rare
literals like an identifier or a sha. If the errors are decorrelated here, fusion is
free accuracy on top of a baseline this repo already trusts.

Prompted by Token-Saver (MIT, github.com/Marktechpost/Token-Saver), which serves large
PDFs to a model with BM25 + embeddings fused at a fixed 40/60 and reports 92-98% fewer
tokens. The ARCHITECTURE is worth borrowing. Its WEIGHTS are not: 60% on the dense side
is the opposite of what was measured on this corpus, where dense scores roughly half of
lexical. Borrowing their constant would import a tuning decision made on someone else's
documents.

So this uses Reciprocal Rank Fusion, which has no weight to borrow or to fiddle:

    score(d) = sum over systems of  1 / (RRF_K + rank_of_d_in_that_system)

RRF_K=60 is the value from the original paper, fixed here before any result was seen.
Rank-based fusion also sidesteps the score-normalisation problem — BM25 scores and
cosine similarities are not on comparable scales, and any normalisation would be
another free parameter pointing at the answer I want.

PRE-REGISTERED DECISION RULE, written before the first run:

  1. Fusion is an improvement only if leak-free NDCG@10 beats LEXICAL ALONE, measured
     in the same run on the same slice. Beating dense alone proves nothing — dense
     already loses.
  2. The margin must survive a paired bootstrap over queries (10k resamples, 95% CI on
     the per-query difference excluding 0). n is ~90 and a 0.02 point-estimate gap is
     inside the noise at that size, which is exactly how the base-model bake-off
     misled me earlier today.
  3. Per-query wins/losses/ties are reported alongside the mean, because a mean can be
     carried by two queries out of ninety.
  4. If it fails, that is the result. This is not a weight search; there is no knob to
     turn until it passes.

Everything is scored with retrieval_eval's OWN ndcg_at_k / rr / recall_at_k /
leaks_filename over task_eval_slice's pairs, so these numbers are directly comparable
to the recorded bars rather than a re-derivation. Absolute values still drift as
commits land, so lexical, dense and hybrid are all measured in THIS run and only
compared to each other.

    python apps/ava-factory/scripts/hybrid_eval.py --json
    python apps/ava-factory/scripts/hybrid_eval.py --base-model BAAI/bge-small-en-v1.5
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]


def _load(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


retrieval_eval = _load("_he_retrieval_eval", _REPO_ROOT / "scripts" / "retrieval_eval.py")
task_eval_slice = _load("_he_task_eval_slice", _REPO_ROOT / "scripts" / "task_eval_slice.py")
embed_eval = _load("_he_embed_eval", _HERE / "embed_eval.py")

K = retrieval_eval.K
RRF_K = 60          # original RRF paper; fixed before any result was seen
BOOTSTRAP = 10_000
SEED = 12345        # fixed so the CI is reproducible, not resampled until it agrees


def rrf_fuse(*ranked_lists: list[str], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion. Rank-based, so BM25 and cosine never need a common scale."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, path in enumerate(ranked):
            scores[path] = scores.get(path, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda p: (-scores[p], p))


def score_one(ranked, pair):
    return {
        "ndcg": retrieval_eval.ndcg_at_k(ranked, pair["relevant"], K),
        "mrr": retrieval_eval.rr(ranked, pair["relevant"]),
        "recall": retrieval_eval.recall_at_k(ranked, pair["relevant"], K),
        "leak": retrieval_eval.leaks_filename(pair["query"], pair["relevant"]),
        "hit": bool(set(ranked[:K]) & set(pair["relevant"])),
    }


def paired_bootstrap(diffs: list[float], resamples: int = BOOTSTRAP, seed: int = SEED):
    """95% CI on the mean per-query difference. Excludes 0 -> the gap is real at this n."""
    if not diffs:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(resamples):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return {
        "mean": sum(diffs) / n,
        "lo": means[int(0.025 * resamples)],
        "hi": means[int(0.975 * resamples)],
        "n": n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-model", default="BAAI/bge-small-en-v1.5",
                    help="dense encoder; the best base measured on this slice so far")
    ap.add_argument("--dim", type=int, default=None, help="embedding dim (default: native)")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--device", default=None)
    ap.add_argument("--lexical-pool", type=int, default=50,
                    help="FTS rows to pull before restricting to the task doc set")
    ap.add_argument("--continuation-lines", type=int,
                    default=task_eval_slice.MAX_CONTINUATION_LINES)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")  # auto: GPU on personal local (CUDA avail), CPU in Hatch VM

    docs = embed_eval.load_docs()
    # Same pruning the task slice uses: documents the queries were mined FROM cannot
    # be candidates, or the query contains its own answer.
    pruned = {p for p in task_eval_slice.QUERY_SOURCE_DOCS if p in docs}
    task_docs = {p: t for p, t in docs.items() if p not in pruned}
    index = task_eval_slice.DocIndex(set(task_docs))
    todo_text = task_eval_slice.TODO_PATH.read_text(encoding="utf-8")
    pairs, _stats = task_eval_slice.mine_todo_pairs(
        todo_text, index, continuation_lines=args.continuation_lines
    )
    if not pairs:
        print("no task pairs mined - cannot compare anything.")
        return 2

    # --- lexical, over the SAME candidate set the dense side sees -----------------
    con = sqlite3.connect(":memory:")
    retrieval_eval.build_index(con)
    allowed = set(task_docs)
    lex_ranked = []
    for p in pairs:
        pool = retrieval_eval.fts_query(con, p["query"], args.lexical_pool)
        lex_ranked.append([d for d in pool if d in allowed][:K])

    # --- dense --------------------------------------------------------------------
    encoder = embed_eval.BaseOnlyEncoder(args.base_model, [args.dim or 0], device)
    paths = sorted(task_docs)
    doc_embs = encoder.encode([task_docs[p] for p in paths], args.max_len)
    q_embs = encoder.encode([p["query"] for p in pairs], args.max_len)
    dim = args.dim or doc_embs.shape[1]
    dense_ranked = embed_eval.rank_all(torch, q_embs, doc_embs, paths, dim, k=K)

    # --- fuse ---------------------------------------------------------------------
    hyb_ranked = [rrf_fuse(lx, dn)[:K] for lx, dn in zip(lex_ranked, dense_ranked, strict=True)]

    systems = {"lexical": lex_ranked, "dense": dense_ranked, "hybrid_rrf": hyb_ranked}
    rows = {name: [score_one(r, p) for r, p in zip(rk, pairs, strict=True)]
            for name, rk in systems.items()}
    summaries = {name: retrieval_eval.summarise(rs) for name, rs in rows.items()}

    # --- the pre-registered comparison: hybrid vs LEXICAL, paired, leak-free ------
    lf = [i for i, r in enumerate(rows["lexical"]) if not r["leak"]]
    diffs = [rows["hybrid_rrf"][i]["ndcg"] - rows["lexical"][i]["ndcg"] for i in lf]
    boot = paired_bootstrap(diffs)
    wins = sum(1 for d in diffs if d > 1e-9)
    losses = sum(1 for d in diffs if d < -1e-9)
    ties = len(diffs) - wins - losses
    beats = boot["lo"] > 0

    out = {
        "base_model": args.base_model,
        "dim": dim,
        "device": device,
        "rrf_k": RRF_K,
        "golden_set": {"task_n": len(pairs), "leak_free_n": len(lf),
                       "docs": len(task_docs), "pruned": sorted(pruned)},
        "summaries": summaries,
        "hybrid_vs_lexical_leak_free": {
            "mean_ndcg_delta": round(boot["mean"], 4),
            "ci95": [round(boot["lo"], 4), round(boot["hi"], 4)],
            "wins": wins, "losses": losses, "ties": ties,
            "verdict": ("hybrid beats lexical" if beats else
                        "no improvement that survives the CI"),
        },
        "decision_rule": "leak-free NDCG@10 above lexical AND paired-bootstrap 95% CI excluding 0",
        "beats_lexical": beats,
    }

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"task pairs: {len(pairs)}   leak-free: {len(lf)}   docs: {len(task_docs)}")
    print(f"dense base: {args.base_model} @ dim {dim} on {device}\n")
    print(f"{'system':14} {'ndcg(all)':>10} {'ndcg(LF)':>10} {'mrr(LF)':>9} {'recall(LF)':>11}")
    for name in ("lexical", "dense", "hybrid_rrf"):
        s = summaries[name]
        print(f"{name:14} {s['all']['ndcg']:>10} {s['leak_free']['ndcg']:>10} "
              f"{s['leak_free']['mrr']:>9} {s['leak_free']['recall']:>11}")
    print(f"\nhybrid - lexical, leak-free, paired over {len(diffs)} queries:")
    print(f"  mean NDCG@10 delta : {boot['mean']:+.4f}")
    print(f"  95% CI             : [{boot['lo']:+.4f}, {boot['hi']:+.4f}]  "
          f"({BOOTSTRAP} resamples, seed {SEED})")
    print(f"  wins/losses/ties   : {wins}/{losses}/{ties}")
    print(f"\nVERDICT: {out['hybrid_vs_lexical_leak_free']['verdict']}")
    if not beats:
        print("  The rule was fixed before the run and there is no weight to tune.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
