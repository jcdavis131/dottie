"""Per-phase heldout perplexity on memmapped uint16 bins."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from ava.config import AvaConfig
from evals.common import EVAL_SEED, heldout_path, prep_eval


def _read_heldout(bin_path: Path) -> tuple[np.memmap, dict]:
    arr = np.memmap(str(bin_path), dtype=np.uint16, mode="r")
    idx_path = bin_path.with_suffix(".idx.json")
    if not idx_path.exists():
        idx_path = Path(str(bin_path) + ".idx.json")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    return arr, idx


def compute_ppl(
    model,
    preset: str,
    phases: list[int] | None = None,
    device: str = "cpu",
) -> dict[int, dict[str, float]]:
    """Per-phase PPL: exp(mean NLL) on non-overlapping windows at training seq_len."""
    cfg = AvaConfig.load(preset)
    phases = phases if phases is not None else list(range(len(cfg.phases)))
    dev = torch.device(device)
    prep_eval(model, EVAL_SEED)

    results: dict[int, dict[str, float]] = {}
    for ph in phases:
        path = heldout_path(preset, ph)
        if not path.exists():
            results[ph] = {"ppl": float("nan"), "tokens": 0, "error": f"missing {path}"}
            continue

        arr, _ = _read_heldout(path)
        seq_len = cfg.phases[ph].seq
        n_tokens = int(arr.size)
        if n_tokens < seq_len + 1:
            results[ph] = {"ppl": float("nan"), "tokens": n_tokens, "error": "too short"}
            continue

        nll_sum = 0.0
        n_preds = 0
        model.eval()
        with torch.no_grad():
            for start in range(0, n_tokens - seq_len, seq_len):
                window = arr[start : start + seq_len + 1].astype(np.int64)
                x = torch.tensor(window[:-1], device=dev).unsqueeze(0)
                y = torch.tensor(window[1:], device=dev)
                logits = model(input_ids=x)["lm_logits"][0]
                lp = F.log_softmax(logits.float(), dim=-1)
                nll = -lp[torch.arange(seq_len, device=dev), y]
                nll_sum += float(nll.sum().item())
                n_preds += seq_len

        mean_nll = nll_sum / max(n_preds, 1)
        results[ph] = {"ppl": float(math.exp(mean_nll)), "tokens": n_preds}
    return results


def main() -> int:
    import argparse

    from evals.common import load_model

    ap = argparse.ArgumentParser(description="Heldout perplexity")
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--phases", default="0-5")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if "-" in args.phases:
        lo, hi = args.phases.split("-", 1)
        phase_list = list(range(int(lo), int(hi) + 1))
    else:
        phase_list = [int(x) for x in args.phases.split(",")]

    model, _, _ = load_model(args.ckpt, args.preset, args.device)
    out = compute_ppl(model, args.preset, phase_list, args.device)
    text = json.dumps({str(k): v for k, v in out.items()}, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
