"""Capability probes — exact-match greedy decode on generated item sets."""

from __future__ import annotations

import json
from pathlib import Path

from evals.common import EVAL_SEED, greedy_decode, prep_eval
from evals.probe_items_gen import generate_probe_items, load_items, norm_answer

_PROBE_DIR = Path(__file__).resolve().parent / "probe_items"


def score_probes(
    model,
    tokenizer,
    *,
    n_per_set: int | None = 200,
    device: str = "cpu",
) -> dict[str, dict[str, float]]:
    """Exact-match greedy decode accuracy per probe set."""
    prep_eval(model)
    dev = device
    results: dict[str, dict[str, float]] = {}

    for name in ("arithmetic", "modus_ponens", "facts", "code_out",
                 "db_mechanics", "compression"):
        items = load_items(name)
        if n_per_set is not None:
            items = items[:n_per_set]
        correct = 0
        for item in items:
            prompt_ids = tokenizer.encode(item["prompt"])
            ans_ids = tokenizer.encode(item["answer"])
            out_ids = greedy_decode(model, prompt_ids, max_new=max(len(ans_ids) + 2, 4), device=dev)
            pred = tokenizer.decode(out_ids[len(prompt_ids) : len(prompt_ids) + len(ans_ids)])
            if norm_answer(pred) == norm_answer(item["answer"]):
                correct += 1
        acc = correct / max(len(items), 1)
        results[name] = {"accuracy": acc, "correct": correct, "total": len(items)}
    return results


def main() -> int:
    import argparse

    from evals.common import load_model

    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--probe-n", type=int, default=200)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--generate-only", action="store_true")
    args = ap.parse_args()

    if args.generate_only:
        generate_probe_items(n_per_set=args.probe_n)
        return 0

    model, tok, _ = load_model(args.ckpt, args.preset, args.device)
    out = score_probes(model, tok, n_per_set=args.probe_n, device=args.device)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
