# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Train the calibrator net. Runnable as a Forge job.

    python3 dottie_core/training/train.py --n 10000 --epochs 20 --out training/out

Loss = BCE on correctness + batch calibration penalty:
    L = BCE(p, y) + lambda * |mean(p) - mean(y)|
The penalty term directly optimizes what ECE measures, so the net learns
calibrated probabilities, not just ranking.

Early stopping on validation ECE (not loss) — we care about calibration.
Streaming batches keep RAM flat regardless of n.

Outputs (in --out):
    weights.json  plain-python weights (torch-free to load)
    metrics.json  train/val loss, ECE per epoch, best-epoch record
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

# Allow `python3 dottie_core/training/train.py` from packages/dottie-core.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dottie_core.training.data import stream_examples  # noqa: E402
from dottie_core.training.model import (  # noqa: E402
    CalibratorNet,
    count_params,
    export_weights,
    torch_available,
)

if not torch_available():
    raise SystemExit("train.py requires torch (nugatron has torch 2.11+cu128)")

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402


def _ece_torch(probs: torch.Tensor, labels: torch.Tensor, n_bins: int = 10) -> float:
    """Expected calibration error on a batch."""
    ece = 0.0
    n = probs.numel()
    if n == 0:
        return 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = (probs >= lo) & (probs < hi if b < n_bins - 1 else probs <= hi)
        m = int(mask.sum())
        if m == 0:
            continue
        acc = labels[mask].float().mean().item()
        conf = probs[mask].mean().item()
        ece += abs(acc - conf) * (m / n)
    return ece


def _batch_iter(n: int, seed: int, batch_size: int, device: torch.device):
    """Streaming batches: materialize one batch at a time, O(batch) RAM."""
    xs_b, ys_b = [], []
    for feats, _kidx, correct in stream_examples(n, seed):
        # kind is already one-hot inside feats (13-dim); drop the idx
        xs_b.append(feats)
        ys_b.append(correct)
        if len(xs_b) >= batch_size:
            yield (torch.tensor(xs_b, dtype=torch.float32, device=device),
                   torch.tensor(ys_b, dtype=torch.float32, device=device))
            xs_b, ys_b = [], []
    if xs_b:
        yield (torch.tensor(xs_b, dtype=torch.float32, device=device),
               torch.tensor(ys_b, dtype=torch.float32, device=device))


def train(n: int = 10000, epochs: int = 20, batch_size: int = 256,
          lr: float = 3e-3, calib_lambda: float = 0.5, seed: int = 0,
          patience: int = 5, out_dir: str = "training/out",
          device: str = "auto") -> dict:
    t0 = time.time()
    dev = torch.device(
        "cuda" if (device == "auto" and torch.cuda.is_available())
        else device if device != "auto" else "cpu"
    )
    print(f"device={dev} n={n} epochs={epochs} batch={batch_size}", flush=True)

    # 90/10 split by seed offset (deterministic, no shuffling of stored data)
    n_train = int(n * 0.9)

    model = CalibratorNet().to(dev)
    print(f"params={count_params(model)}", flush=True)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    bce = nn.BCELoss()

    best_ece = math.inf
    best_state = None
    stale = 0
    history = []

    for epoch in range(epochs):
        # --- train ---
        model.train()
        train_loss, nb = 0.0, 0
        for xb, yb in _batch_iter(n_train, seed + epoch * 1000, batch_size, dev):
            opt.zero_grad()
            p = model(xb)
            loss_bce = bce(p, yb)
            loss_cal = torch.abs(p.mean() - yb.mean())
            loss = loss_bce + calib_lambda * loss_cal
            loss.backward()
            opt.step()
            train_loss += loss.item()
            nb += 1
        train_loss /= max(nb, 1)

        # --- validate (fresh seed offset => unseen examples) ---
        model.eval()
        all_p, all_y = [], []
        val_loss, nvb = 0.0, 0
        with torch.no_grad():
            for xb, yb in _batch_iter(n - n_train, seed + 999999, batch_size, dev):
                p = model(xb)
                val_loss += bce(p, yb).item()
                nvb += 1
                all_p.append(p.cpu())
                all_y.append(yb.cpu())
        val_loss /= max(nvb, 1)
        probs = torch.cat(all_p) if all_p else torch.tensor([])
        labels = torch.cat(all_y) if all_y else torch.tensor([])
        val_ece = _ece_torch(probs, labels)

        rec = {"epoch": epoch, "train_loss": round(train_loss, 4),
               "val_loss": round(val_loss, 4), "val_ece": round(val_ece, 4)}
        history.append(rec)
        print(json.dumps(rec), flush=True)

        if val_ece < best_ece - 1e-4:
            best_ece = val_ece
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                print(f"early stopping at epoch {epoch} (val_ece={val_ece:.4f})", flush=True)
                break

    # restore best and export
    if best_state is not None:
        model.load_state_dict(best_state)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    weights = export_weights(model)
    (out / "weights.json").write_text(json.dumps(weights))
    metrics = {
        "n": n, "epochs_done": len(history), "best_val_ece": round(best_ece, 4),
        "params": count_params(model),
        "weights_bytes": (out / "weights.json").stat().st_size,
        "seconds": round(time.time() - t0, 1),
        "device": str(dev),
        "history": history,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps({"done": True, **{k: v for k, v in metrics.items() if k != "history"}}),
          flush=True)
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the calibrator net")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--calib-lambda", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--out", default="training/out")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()
    train(n=args.n, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
          calib_lambda=args.calib_lambda, seed=args.seed, patience=args.patience,
          out_dir=args.out, device=args.device)


if __name__ == "__main__":
    main()
