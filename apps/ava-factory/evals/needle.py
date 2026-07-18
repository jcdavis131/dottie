"""Needle-in-haystack pass-key retrieval at native and YaRN-scaled context."""

from __future__ import annotations

import random
from typing import Any

import torch

from evals.common import EVAL_SEED, greedy_decode, prep_eval
from model_1b import apply_rope_scaling


def _filler(rng: random.Random, n_tokens: int, tokenizer) -> str:
    words = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog", "and", "then"]
    parts = []
    while len(tokenizer.encode(" ".join(parts))) < n_tokens:
        parts.append(rng.choice(words))
    return " ".join(parts)


def run_needle(
    model,
    tokenizer,
    *,
    ctx_native: int = 1024,
    ctx_yarn: int = 2048,
    depths: list[float] | None = None,
    samples_per_depth: int = 10,
    device: str = "cpu",
) -> dict[str, Any]:
    """Pass-key retrieval accuracy per depth, native + YaRN contexts."""
    depths = depths or [round(x, 1) for x in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]]
    rng = random.Random(EVAL_SEED)
    results: dict[str, Any] = {"native": {}, "yarn": {}}

    def _eval_ctx(ctx_len: int, label: str, rope_scale: float | None) -> None:
        if rope_scale is not None:
            apply_rope_scaling(model, 32000, rope_scale)
        try:
            for depth in depths:
                correct = 0
                for _ in range(samples_per_depth):
                    prep_eval(model)
                    key = str(rng.randint(1000, 9999))
                    needle = f"The magic number is {key}."
                    pre_toks = int((ctx_len - len(tokenizer.encode(needle)) - 16) * depth)
                    pre_toks = max(pre_toks, 8)
                    filler = _filler(rng, pre_toks, tokenizer)
                    prompt = f"{filler} {needle} {_filler(rng, 32, tokenizer)} What is the magic number? Answer:"
                    pids = tokenizer.encode(prompt)
                    if len(pids) > ctx_len:
                        pids = pids[:ctx_len]
                    out_ids = greedy_decode(model, pids, max_new=8, device=device)
                    ans = tokenizer.decode(out_ids[len(pids) :]).strip()
                    if key in ans:
                        correct += 1
                results[label][str(depth)] = correct / samples_per_depth
        finally:
            if rope_scale is not None:
                apply_rope_scaling(model, 32000, 1.2)

    _eval_ctx(ctx_native, "native", None)
    _eval_ctx(ctx_yarn, "yarn", 2.4)
    return results


def main() -> int:
    import argparse
    import json

    from evals.common import load_model

    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="none")
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    model, tok, _ = load_model(args.ckpt, args.preset, args.device)
    out = run_needle(model, tok, device=args.device)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
