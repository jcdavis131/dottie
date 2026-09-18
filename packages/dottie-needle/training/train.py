#!/usr/bin/env python3
"""Tier 2 trainer: byte-level function-calling LM. Runs on the Forge runner.

Bootstraps torch if absent (the runner is Cameron's Alienware; the "full
send" approval covers this program's own dependencies — torch is declared
here, in the job notes, and nowhere else).

Model: 8-layer decoder-only transformer, d_model 256, vocab 259
(bytes + pad/bos/eos). ~6.5M params ≈ 26 MB fp32. Cross-entropy on
completion bytes only; prompt bytes are masked.

Usage (on runner):
    python3 train.py --data data --epochs 5 --out checkpoints/needle-native
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def ensure_torch():
    try:
        import torch  # noqa: F401
    except ImportError:
        print("torch not found — installing (CUDA build) for this training job...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "torch", "--index-url", "https://download.pytorch.org/whl/cu126"],
            check=True,
        )
    import torch

    return torch


torch = ensure_torch()
import torch.nn as nn  # noqa: E402
from torch.utils.data import Dataset, DataLoader  # noqa: E402

PAD, BOS, EOS = 256, 257, 258
VOCAB = 259


def encode(s: str) -> list[int]:
    return [BOS] + list(s.encode("utf-8", errors="replace")) + [EOS]


class PairDataset(Dataset):
    def __init__(self, path: Path, ctx: int):
        self.items = []
        for line in path.read_text().splitlines():
            if line.strip():
                self.items.append(json.loads(line))
        self.ctx = ctx

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p = self.items[i]
        prompt_b = encode(p["prompt"])[: self.ctx // 2]
        comp_b = encode(p["completion"])[: self.ctx - len(prompt_b)]
        ids = (prompt_b + comp_b)[: self.ctx]
        # Labels: -100 over the prompt (masked), byte ids over the completion.
        labels = [-100] * len(prompt_b) + comp_b[1:] + [-100]
        labels = labels[: self.ctx]
        ids += [PAD] * (self.ctx - len(ids))
        labels += [-100] * (self.ctx - len(labels))
        return torch.tensor(ids), torch.tensor(labels)


class RMSNorm(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + 1e-6) * self.w


class Block(nn.Module):
    def __init__(self, d, heads, dff, dropout):
        super().__init__()
        self.heads = heads
        self.hd = d // heads
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.out = nn.Linear(d, d, bias=False)
        self.n1 = RMSNorm(d)
        self.n2 = RMSNorm(d)
        self.ff1 = nn.Linear(d, 2 * dff, bias=False)
        self.ff2 = nn.Linear(dff, d, bias=False)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, freqs):
        B, T, D = x.shape
        h = self.n1(x)
        q, k, v = self.qkv(h).split(D, dim=-1)
        q = q.view(B, T, self.heads, self.hd).transpose(1, 2)
        k = k.view(B, T, self.heads, self.hd).transpose(1, 2)
        v = v.view(B, T, self.heads, self.hd).transpose(1, 2)
        q, k = apply_rope(q, k, freqs)
        y = nn.functional.scaled_dot_product_attention(
            q, k, v, is_causal=True, dropout_p=self.drop.p if self.training else 0.0
        )
        y = y.transpose(1, 2).reshape(B, T, D)
        x = x + self.drop(self.out(y))
        h = self.n2(x)
        a, b = self.ff1(h).chunk(2, dim=-1)
        x = x + self.drop(self.ff2(nn.functional.silu(a) * b))
        return x


def apply_rope(q, k, freqs):
    # freqs: (T, hd//2) complex rotations; simplified interleaved RoPE.
    T = q.shape[2]
    fr = freqs[:T].to(q.device)
    q_ = q.float().reshape(*q.shape[:-1], -1, 2)
    k_ = k.float().reshape(*k.shape[:-1], -1, 2)
    qc = torch.view_as_complex(q_)
    kc = torch.view_as_complex(k_)
    return (qc * fr).real.type_as(q).reshape(q.shape), (kc * fr).real.type_as(k).reshape(k.shape)


class ByteLM(nn.Module):
    def __init__(self, layers=8, d=256, heads=8, dff=1024, ctx=512, dropout=0.1):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(VOCAB, d)
        self.blocks = nn.ModuleList([Block(d, heads, dff, dropout) for _ in range(layers)])
        self.norm = RMSNorm(d)
        self.head = nn.Linear(d, VOCAB, bias=False)
        # Precompute RoPE freqs for hd = d // heads.
        hd = d // heads
        inv = 1.0 / (10000 ** (torch.arange(0, hd, 2).float() / hd))
        t = torch.arange(ctx).float()
        ang = torch.outer(t, inv)
        self.register_buffer("freqs", torch.polar(torch.ones_like(ang), ang), persistent=False)

    def forward(self, ids):
        x = self.tok(ids)
        for blk in self.blocks:
            x = blk(x, self.freqs)
        return self.head(self.norm(x))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--ctx", type=int, default=512)
    ap.add_argument("--out", default="checkpoints/needle-native")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")
    ds = PairDataset(Path(args.data) / "train.jsonl", args.ctx)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True)
    model = ByteLM(ctx=args.ctx).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"params: {n_params/1e6:.2f}M  (~{n_params*4/1e6:.1f} MB fp32)")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs * len(dl))
    loss_fn = nn.CrossEntropyLoss(ignore_index=-100)

    model.train()
    for ep in range(args.epochs):
        total, n = 0.0, 0
        for ids, labels in dl:
            ids, labels = ids.to(device), labels.to(device)
            opt.zero_grad()
            logits = model(ids[:, :-1])
            loss = loss_fn(logits.reshape(-1, VOCAB), labels[:, 1:].reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            total += loss.item()
            n += 1
        ppl = math.exp(total / n)
        print(f"epoch {ep+1}/{args.epochs}  loss={total/n:.4f}  ppl={ppl:.2f}", flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(),
                "config": {"layers": 8, "d": 256, "heads": 8, "dff": 1024, "ctx": args.ctx}},
               out / "model.pt")
    # int8 artifact for the size headline.
    torch.save({"model": {k: v.to(torch.int8) if v.dtype == torch.float32 else v
                          for k, v in model.state_dict().items()}},
               out / "model.int8.pt")
    (out / "metrics.json").write_text(json.dumps({
        "params": n_params, "fp32_mb": round(n_params * 4 / 1e6, 1),
        "epochs": args.epochs, "final_loss": round(total / n, 4),
    }, indent=2) + "\n")
    print(f"saved to {out}/")


if __name__ == "__main__":
    main()
