#!/usr/bin/env python3
"""Step 5 of the embedding sequence: ONE encoder, per-domain LoRA, Matryoshka.

Solo personal project, no connection to employer, built with public/free-tier only

Pre-registered plan: tasks/artifacts/embedding_train_plan_2026-07-31.md. Steps 1-4 of
that sequence (golden set, FTS5 baseline, the Option C decision, MinHash dedup) are
already done and are NOT reimplemented here — this module is purely the training loop
over data two existing, already-tested modules produce:

  ``ast_pairs.py`` + ``hard_negatives.py`` SOURCE A -> the ``code`` domain
  ``retrieval_eval.py`` (TRAIN split only) + ``hard_negatives.py`` SOURCE B -> the
  ``task`` domain

TWO DOMAINS, NOT N. One LoRA adapter per hard-negative source, sharing one frozen base
encoder (``sentence-transformers/all-MiniLM-L6-v2`` — already in the local HF cache from
vector-unified's cultural-text warm-start, zero new download). The base has no trainable
parameters shared between domains, so training the two adapters sequentially within an
epoch is exactly equivalent to interleaving them: there is no cross-domain gradient to
worry about forgetting.

MATRYOSHKA. Loss is summed over truncated+renormalised prefixes of the embedding
(``--dims``, default 384,256,128,64) so a smaller slice of the same vector stays usable —
the guide the strategy review cites already specifies this, and it is what lets a single
encoder serve latency-sensitive callers a shorter vector without a second training run.

HARD NEGATIVES + IN-BATCH. Per query: the mined hard negatives (already verified by
hard_negatives.py to never be a genuine positive for that query) plus every OTHER
positive in the batch as an in-batch negative. Standard multiple-negatives-ranking setup,
extended with the hard-negative columns.

TRAIN/EVAL SPLIT DISCIPLINE. The ``task`` domain trains ONLY on the walk-forward TRAIN
half of retrieval_eval.mine_pairs (same ``--split-frac`` retrieval_eval.py and
task_eval_slice.py use), so embed_eval.py's TEST-half numbers are not contaminated by
having been seen during training. This is the same walk-forward discipline the golden
set was built for in the first place (see the strategy review's note on the shipped
hoops embedding turning out to be transductive).

Usage:
    python apps/ava-factory/scripts/train_encoder.py --smoke
    python apps/ava-factory/scripts/train_encoder.py --out artifacts/encoder_v1
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
MAX_DOC_CHARS = 60_000


def _load(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


hard_negatives = _load("_te_hard_negatives", _HERE / "hard_negatives.py")
ast_pairs = hard_negatives.ast_pairs
retrieval_eval = hard_negatives.retrieval_eval

DOMAINS = ("code", "task")
DEFAULT_DIMS = (384, 256, 128, 64)


# ---------------------------------------------------------------------------
# Example construction
# ---------------------------------------------------------------------------

def code_examples(path: Path, n_neg: int):
    """(query, positive, negatives[]) triples from ast_pairs + sibling negatives.

    Text is already present on every record (`positive` and `negatives[].text`) — no
    file reads needed, unlike the task domain.
    """
    pairs = hard_negatives.pairs_from_tree(path)
    records = hard_negatives.mine_sibling_negatives(pairs, n=n_neg)
    out = []
    for r in records:
        negs = [n["text"] for n in r["negatives"][:n_neg]]
        if r["query"] and r["positive"]:
            out.append({"domain": "code", "query": r["query"], "positive": r["positive"],
                        "negatives": negs})
    return out


def _read_doc(rel_path: str, cache: dict) -> str | None:
    """Same truncation retrieval_eval.build_index uses, so training text matches eval text."""
    if rel_path in cache:
        return cache[rel_path]
    p = _REPO_ROOT / rel_path
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:MAX_DOC_CHARS]
    except OSError:
        text = None
    cache[rel_path] = text
    return text


def task_examples(max_commits: int, split_frac: float, window: int, n_neg: int):
    """(query, positive, negatives[]) triples from the golden set's TRAIN half only.

    Deliberately does NOT touch the TEST half — that half is what embed_eval.py scores
    against, and training on it would be the exact transductive mistake the strategy
    review flagged in the shipped hoops embedding.
    """
    pairs = retrieval_eval.mine_pairs(max_commits)
    pairs.sort(key=lambda p: p["date"])
    cut = int(len(pairs) * split_frac)
    train_pairs = pairs[:cut]

    records = hard_negatives.mine_adjacent_negatives(train_pairs, window=window, n=n_neg)
    cache: dict[str, str | None] = {}
    out = []
    for r in records:
        neg_texts = []
        for neg in r["negatives"][:n_neg]:
            text = _read_doc(neg["path"], cache)
            if text:
                neg_texts.append(text)
        for rel in r["relevant"]:
            pos_text = _read_doc(rel, cache)
            if not pos_text:
                continue
            out.append({"domain": "task", "query": r["query"], "positive": pos_text,
                        "negatives": neg_texts})
    return out


def build_examples(path: Path, max_commits: int, split_frac: float, window: int, n_neg: int):
    examples = {
        "code": code_examples(path, n_neg),
        "task": task_examples(max_commits, split_frac, window, n_neg),
    }
    return examples


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class DomainEncoder:
    """One frozen base + one LoRA adapter per domain. Adapters share zero trainable
    parameters, so which domain trained most recently cannot bias another domain's
    forward pass — only ``set_domain`` changes what's active."""

    def __init__(self, base_name: str, domains, r: int, alpha: int, dropout: float, device: str):
        import torch
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(base_name)
        base = AutoModel.from_pretrained(base_name)
        cfg = LoraConfig(
            r=r, lora_alpha=alpha, lora_dropout=dropout,
            target_modules=["query", "key", "value", "dense"],
            task_type=TaskType.FEATURE_EXTRACTION,
        )
        self.model = get_peft_model(base, cfg, adapter_name=domains[0])
        for d in domains[1:]:
            self.model.add_adapter(d, cfg)
        self.model.to(device)
        self.domains = domains

    def set_domain(self, domain: str):
        self.model.set_adapter(domain)

    def encode(self, texts, max_len: int):
        torch = self.torch
        if not texts:
            return torch.zeros((0, self.model.config.hidden_size), device=self.device)
        enc = self.tokenizer(
            list(texts), padding=True, truncation=True, max_length=max_len,
            return_tensors="pt",
        ).to(self.device)
        out = self.model(**enc)
        mask = enc["attention_mask"].unsqueeze(-1).float()
        summed = (out.last_hidden_state * mask).sum(1)
        counts = mask.sum(1).clamp(min=1e-9)
        return summed / counts

    def save(self, out_dir: Path):
        """peft's save_pretrained already nests by adapter name (save_directory/<adapter>/...)
        for any adapter not literally named "default" — passing out_dir/d here would double
        that nesting."""
        out_dir.mkdir(parents=True, exist_ok=True)
        for d in self.domains:
            self.set_domain(d)
            self.model.save_pretrained(str(out_dir), selected_adapters=[d])
        self.tokenizer.save_pretrained(str(out_dir / "tokenizer"))


def matryoshka_info_nce(torch, F, q, pos, negs, neg_mask, dims, temperature):
    """Sum of InfoNCE at each truncated+renormalised prefix. ``negs``: [B, n_neg, D]."""
    B = q.shape[0]
    labels = torch.arange(B, device=q.device)
    total = q.new_zeros(())
    for d in dims:
        qd = F.normalize(q[:, :d], dim=-1)
        pd = F.normalize(pos[:, :d], dim=-1)
        pos_logits = qd @ pd.t() / temperature  # [B, B]; diagonal is the true positive
        if negs.shape[1] > 0:
            nd = F.normalize(negs[..., :d], dim=-1)
            neg_logits = torch.einsum("bd,bkd->bk", qd, nd) / temperature  # [B, n_neg]
            neg_logits = neg_logits.masked_fill(~neg_mask, float("-inf"))
            logits = torch.cat([pos_logits, neg_logits], dim=1)
        else:
            logits = pos_logits
        total = total + F.cross_entropy(logits, labels)
    return total / len(dims)


def train_domain(encoder, examples, domain: str, *, dims, n_neg, epochs, batch_size,
                  lr, temperature, max_len, seed):
    torch = encoder.torch
    import torch.nn.functional as F

    encoder.set_domain(domain)
    params = [p for p in encoder.model.parameters() if p.requires_grad]
    if not params:
        return {"domain": domain, "steps": 0, "final_loss": None, "note": "no trainable params"}
    opt = torch.optim.AdamW(params, lr=lr)

    rng = random.Random(seed)
    losses = []
    steps = 0
    for _epoch in range(epochs):
        order = list(range(len(examples)))
        rng.shuffle(order)
        for start in range(0, len(order), batch_size):
            batch_idx = order[start:start + batch_size]
            if len(batch_idx) < 2:
                continue  # in-batch negatives need >=2 examples
            batch = [examples[i] for i in batch_idx]
            queries = [b["query"] for b in batch]
            positives = [b["positive"] for b in batch]
            neg_flat, neg_mask_flat = [], []
            for b in batch:
                negs = b["negatives"][:n_neg]
                for t in negs:
                    neg_flat.append(t)
                pad = n_neg - len(negs)
                neg_mask_flat.extend([True] * len(negs) + [False] * pad)
                neg_flat.extend([""] * pad)

            q_emb = encoder.encode(queries, max_len)
            p_emb = encoder.encode(positives, max_len)
            neg_emb = encoder.encode(neg_flat, max_len) if neg_flat else q_emb.new_zeros((0, q_emb.shape[-1]))
            B = len(batch)
            neg_emb = neg_emb.view(B, n_neg, -1) if neg_flat else neg_emb.view(B, 0, q_emb.shape[-1])
            neg_mask = torch.tensor(neg_mask_flat, device=encoder.device).view(B, n_neg) if neg_flat else torch.zeros((B, 0), dtype=torch.bool, device=encoder.device)

            loss = matryoshka_info_nce(torch, F, q_emb, p_emb, neg_emb, neg_mask, dims, temperature)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(loss.item())
            steps += 1

    return {
        "domain": domain,
        "steps": steps,
        "final_loss": losses[-1] if losses else None,
        "mean_loss": sum(losses) / len(losses) if losses else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default=str(_REPO_ROOT), help="tree to mine for the code domain")
    ap.add_argument("--max-commits", type=int, default=1500)
    ap.add_argument("--split-frac", type=float, default=0.7)
    ap.add_argument("--window", type=int, default=hard_negatives.DEFAULT_WINDOW)
    ap.add_argument("--n-neg", type=int, default=4)
    ap.add_argument("--base-model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--dims", default=",".join(str(d) for d in DEFAULT_DIMS))
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--temperature", type=float, default=0.05)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--device", default=None, help="default: cuda if available else cpu")
    ap.add_argument("--out", default=str(_HERE.parent / "artifacts" / "encoder_v1"))
    ap.add_argument("--smoke", action="store_true",
                     help="cap each domain to 32 examples, 1 epoch, batch 8 — must finish in well under a minute")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dims = tuple(int(d) for d in args.dims.split(","))
    epochs, batch_size = args.epochs, args.batch_size
    if args.smoke:
        epochs, batch_size = 1, 8

    t0 = time.time()
    examples = build_examples(Path(args.path), args.max_commits, args.split_frac, args.window, args.n_neg)
    coverage = {d: len(ex) for d, ex in examples.items()}
    if args.smoke:
        examples = {d: ex[:32] for d, ex in examples.items()}

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")  # auto: GPU on personal local (CUDA avail), CPU in Hatch VM

    encoder = DomainEncoder(args.base_model, DOMAINS, args.lora_r, args.lora_alpha,
                             args.lora_dropout, device)

    results = []
    for domain in DOMAINS:
        ex = examples.get(domain, [])
        if len(ex) < 2:
            results.append({"domain": domain, "steps": 0, "final_loss": None,
                             "note": f"only {len(ex)} example(s), need >=2"})
            continue
        results.append(train_domain(
            encoder, ex, domain, dims=dims, n_neg=args.n_neg, epochs=epochs,
            batch_size=batch_size, lr=args.lr, temperature=args.temperature,
            max_len=args.max_len, seed=args.seed,
        ))

    out_dir = Path(args.out)
    if not args.smoke:
        encoder.save(out_dir)
        manifest = {
            "base_model": args.base_model, "dims": list(dims), "domains": list(DOMAINS),
            "lora_r": args.lora_r, "lora_alpha": args.lora_alpha,
            "n_neg": args.n_neg, "epochs": epochs, "batch_size": batch_size,
            "lr": args.lr, "temperature": args.temperature, "max_len": args.max_len,
            "seed": args.seed, "coverage": coverage,
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summary = {
        "smoke": args.smoke, "device": device, "elapsed_s": round(time.time() - t0, 1),
        "example_coverage": coverage, "training": results,
        "out_dir": None if args.smoke else str(out_dir),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"device={device}  elapsed={summary['elapsed_s']}s  smoke={args.smoke}")
        print(f"example coverage: {coverage}")
        for r in results:
            print(f"  [{r['domain']}] steps={r['steps']} final_loss={r['final_loss']} "
                  f"{r.get('note', '')}")
        if summary["out_dir"]:
            print(f"saved -> {summary['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
