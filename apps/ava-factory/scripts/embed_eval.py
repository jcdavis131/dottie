#!/usr/bin/env python3
"""Score a train_encoder.py checkpoint against the SAME golden sets and protocol
the FTS5 baseline was measured on, so the number is comparable, not just a number.

Solo personal project, no connection to employer, built with public/free-tier only

Reuses `scripts/retrieval_eval.py`'s NDCG@10 / MRR / recall@10 / leak-free-subset
definitions and `scripts/task_eval_slice.py`'s TODO-mined task-shaped slice (query-source
docs pruned, no walk-forward split — see that file's own docstring for why the task slice
is evaluation-only). Nothing here re-implements those metrics; re-deriving them here would
make the two numbers incomparable, which is the exact mistake the strategy review's
0.977-vs-0.846 finding warns about.

RECORDED BARS (leak-free): commit-shaped NDCG@10 0.622 (n=209), task-shaped NDCG@10 0.429
(n=87). The task-shaped number is the pre-registered target (tasks/artifacts/
embedding_train_plan_2026-07-31.md) — beat that one, not the easier commit-shaped one.

The encoder embeds documents and queries with the ``task`` domain adapter (the domain
train_encoder.py trained on file-level positives/negatives from the same golden set's
TRAIN half) — the ``code`` domain adapter answers a different question (docstring ->
single function) that this golden set was never built to measure.

Usage:
    python apps/ava-factory/scripts/embed_eval.py --checkpoint artifacts/encoder_v1
    python apps/ava-factory/scripts/embed_eval.py --checkpoint artifacts/encoder_v1 --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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


retrieval_eval = _load("_ee_retrieval_eval", _REPO_ROOT / "scripts" / "retrieval_eval.py")
task_eval_slice = _load("_ee_task_eval_slice", _REPO_ROOT / "scripts" / "task_eval_slice.py")

RECORDED = {"commit": {"ndcg": 0.622, "mrr": 0.619, "recall": 0.791},
            "task": {"ndcg": 0.429, "mrr": None, "recall": None}}
K = retrieval_eval.K


# ---------------------------------------------------------------------------
# Document set (same walk retrieval_eval.build_index does, texts kept not indexed)
# ---------------------------------------------------------------------------

def load_docs() -> dict:
    docs = {}
    for p in retrieval_eval.ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in retrieval_eval.INDEXABLE:
            continue
        if retrieval_eval.SKIP_PARTS & set(p.parts):
            continue
        rel = p.relative_to(retrieval_eval.ROOT).as_posix()
        try:
            docs[rel] = p.read_text(encoding="utf-8", errors="replace")[:retrieval_eval.MAX_DOC_CHARS]
        except OSError:
            continue
    return docs


# ---------------------------------------------------------------------------
# Encoder loading (mirrors train_encoder.DomainEncoder but LOADS trained adapters)
# ---------------------------------------------------------------------------

def _mean_pool_encode(torch, model, tokenizer, device, texts, max_len: int, batch_size: int = 64):
    if not texts:
        return torch.zeros((0, model.config.hidden_size))
    chunks = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            enc = tokenizer(batch, padding=True, truncation=True,
                             max_length=max_len, return_tensors="pt").to(device)
            out = model(**enc)
            mask = enc["attention_mask"].unsqueeze(-1).float()
            summed = (out.last_hidden_state * mask).sum(1)
            counts = mask.sum(1).clamp(min=1e-9)
            chunks.append((summed / counts).cpu())
    return torch.cat(chunks, dim=0)


class LoadedEncoder:
    def __init__(self, checkpoint_dir: Path, device: str):
        import torch
        from peft import PeftModel
        from transformers import AutoModel, AutoTokenizer

        manifest = json.loads((checkpoint_dir / "manifest.json").read_text(encoding="utf-8"))
        self.manifest = manifest
        self.torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(str(checkpoint_dir / "tokenizer"))
        base = AutoModel.from_pretrained(manifest["base_model"])

        domains = manifest["domains"]
        self.model = PeftModel.from_pretrained(base, str(checkpoint_dir / domains[0]),
                                                adapter_name=domains[0])
        for d in domains[1:]:
            self.model.load_adapter(str(checkpoint_dir / d), adapter_name=d)
        self.model.to(device).eval()

    def set_domain(self, domain: str):
        self.model.set_adapter(domain)

    def encode(self, texts, max_len: int, batch_size: int = 64):
        return _mean_pool_encode(self.torch, self.model, self.tokenizer, self.device,
                                  texts, max_len, batch_size)


class BaseOnlyEncoder:
    """The frozen base model, zero LoRA — the zero-shot floor a trained checkpoint
    must actually beat to justify its own existence. Same interface as LoadedEncoder
    (encode/set_domain/manifest) so main() doesn't need to branch."""

    def __init__(self, base_model: str, dims, device: str):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(base_model)
        self.model = AutoModel.from_pretrained(base_model).to(device).eval()
        self.manifest = {"base_model": base_model, "dims": dims, "domains": ["none"]}

    def set_domain(self, domain: str):
        pass

    def encode(self, texts, max_len: int, batch_size: int = 64):
        return _mean_pool_encode(self.torch, self.model, self.tokenizer, self.device,
                                  texts, max_len, batch_size)


# ---------------------------------------------------------------------------
# Cosine ranking + scoring, reusing retrieval_eval's metric definitions
# ---------------------------------------------------------------------------

def rank_all(torch, query_embs, doc_embs, doc_paths, dim: int, k: int = K):
    import torch.nn.functional as F
    qd = F.normalize(query_embs[:, :dim], dim=-1)
    dd = F.normalize(doc_embs[:, :dim], dim=-1)
    sims = qd @ dd.t()  # [Q, N]
    topk = torch.topk(sims, k=min(k, dd.shape[0]), dim=1).indices
    return [[doc_paths[j] for j in row.tolist()] for row in topk]


def score_pairs(pairs, ranked_lists, k: int = K):
    rows = []
    for p, ranked in zip(pairs, ranked_lists, strict=True):
        relevant = p["relevant"]
        rows.append({
            "ndcg": retrieval_eval.ndcg_at_k(ranked, relevant, k),
            "mrr": retrieval_eval.rr(ranked, relevant),
            "recall": retrieval_eval.recall_at_k(ranked, relevant, k),
            "leak": retrieval_eval.leaks_filename(p["query"], relevant),
            "hit": bool(set(ranked[:k]) & set(relevant)),
        })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--base-only", action="store_true",
                     help="skip the checkpoint, score the frozen base model with zero LoRA "
                          "(the floor a trained checkpoint must actually beat)")
    ap.add_argument("--base-model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--max-commits", type=int, default=4000)
    ap.add_argument("--split-frac", type=float, default=0.7)
    ap.add_argument("--continuation-lines", type=int, default=task_eval_slice.MAX_CONTINUATION_LINES)
    ap.add_argument("--dims", default=None, help="comma-separated dims to score; default: manifest's")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--device", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.base_only and not args.checkpoint:
        ap.error("--checkpoint is required unless --base-only is set")

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    if args.base_only:
        checkpoint_dir = None
        default_dims = [384, 256, 128, 64]
        encoder = BaseOnlyEncoder(args.base_model, default_dims, device)
    else:
        checkpoint_dir = Path(args.checkpoint)
        encoder = LoadedEncoder(checkpoint_dir, device)
        encoder.set_domain("task")
    dims = [int(d) for d in args.dims.split(",")] if args.dims else encoder.manifest["dims"]

    docs = load_docs()

    # --- commit-shaped TEST half, same split train_encoder.py used -------------
    commit_pairs = retrieval_eval.mine_pairs(args.max_commits)
    commit_pairs.sort(key=lambda p: p["date"])
    cut = int(len(commit_pairs) * args.split_frac)
    commit_test = commit_pairs[cut:]

    # --- task-shaped slice, query-source docs pruned like task_eval_slice.py ---
    pruned_paths = {p for p in task_eval_slice.QUERY_SOURCE_DOCS if p in docs}
    task_docs = {p: t for p, t in docs.items() if p not in pruned_paths}
    index = task_eval_slice.DocIndex(set(task_docs))
    todo_text = task_eval_slice.TODO_PATH.read_text(encoding="utf-8")
    task_pairs, task_stats = task_eval_slice.mine_todo_pairs(
        todo_text, index, continuation_lines=args.continuation_lines
    )

    # --- embed everything once ---------------------------------------------
    full_paths = sorted(docs)
    full_doc_embs = encoder.encode([docs[p] for p in full_paths], args.max_len)
    task_paths = sorted(task_docs)
    task_doc_embs = encoder.encode([task_docs[p] for p in task_paths], args.max_len)

    commit_q_embs = encoder.encode([p["query"] for p in commit_test], args.max_len)
    task_q_embs = encoder.encode([p["query"] for p in task_pairs], args.max_len)

    by_dim = {}
    for dim in dims:
        commit_ranked = rank_all(torch, commit_q_embs, full_doc_embs, full_paths, dim)
        commit_rows = score_pairs(commit_test, commit_ranked)
        commit_summary = retrieval_eval.summarise(commit_rows)

        if task_pairs:
            task_ranked = rank_all(torch, task_q_embs, task_doc_embs, task_paths, dim)
            task_rows = score_pairs(task_pairs, task_ranked)
            task_summary = retrieval_eval.summarise(task_rows)
        else:
            task_summary = None

        by_dim[dim] = {
            "commit": commit_summary,
            "task": task_summary,
            "beats_target": (
                task_summary["leak_free"]["ndcg"] > RECORDED["task"]["ndcg"]
                if task_summary else None
            ),
        }

    summary = {
        "checkpoint": str(checkpoint_dir) if checkpoint_dir else f"BASE ONLY ({args.base_model}, zero LoRA)",
        "device": device,
        "domain_used": "task" if checkpoint_dir else "n/a (base only)",
        "documents": {"full": len(full_paths), "task_pruned": len(task_docs),
                       "pruned_paths": sorted(pruned_paths)},
        "golden_set": {"commit_test_n": len(commit_test), "task_n": len(task_pairs),
                        "task_mined_stats": task_stats},
        "recorded_baseline_leak_free": RECORDED,
        "by_dim": by_dim,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"checkpoint={checkpoint_dir}  device={device}  domain=task")
        print(f"docs: full={len(full_paths)}  task-pruned={len(task_docs)} "
              f"(removed {sorted(pruned_paths)})")
        print(f"commit test queries: {len(commit_test)}   task queries: {len(task_pairs)}")
        print()
        print(f"{'dim':>5}  {'commit NDCG@10':>15}  {'task NDCG@10':>13}  {'beats 0.429':>11}")
        for dim in dims:
            r = by_dim[dim]
            c = r["commit"]["leak_free"]["ndcg"]
            t = r["task"]["leak_free"]["ndcg"] if r["task"] else float("nan")
            beats = r["beats_target"]
            print(f"{dim:>5}  {c:>15.3f}  {t:>13.3f}  {beats!s:>11}")
        print()
        print("recorded baselines (leak-free): commit 0.622, task 0.429 (the pre-registered target)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
