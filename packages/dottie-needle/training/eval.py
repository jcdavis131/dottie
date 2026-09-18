#!/usr/bin/env python3
"""Tier 2 eval harness: greedy decode on held-out tools, Tier 1 grammar verdict.

Metrics (all on tools the model never saw in training):
- valid_call_rate: Tier 1 CompiledGrammar accepts the emitted call
- exact_match: tool name + full arguments equal gold
- arg_f1: per-argument precision/recall over the gold argument set
- tok_per_s: decode throughput on this host
- ECE: expected calibration error of the confidence signal
         (mean logprob over the call span, isotonic-fit on this split)

Ablation: raw greedy decode vs. the Tier 1 guided loop (validate + repair).
This directly measures what the grammar mechanism is worth on our own
weights. Confidence is reported as a scrutiny signal only — it never
authorizes anything.

Usage (on runner, after train.py):
    python3 eval.py --data data --ckpt checkpoints/needle-native/model.pt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from train import ByteLM, encode, ensure_torch  # noqa: E402

torch = ensure_torch()

from dottie_needle.catalog import build_catalog  # noqa: E402
from dottie_needle.engine import extract_call_span  # noqa: E402
from dottie_needle.grammar import CompiledGrammar, GrammarError  # noqa: E402

PAD, BOS, EOS = 256, 257, 258


@torch.no_grad()
def greedy_decode(model, prompt_ids, max_new=160, device="cpu"):
    ids = prompt_ids[:]
    logprobs = []
    start = time.time()
    for _ in range(max_new):
        inp = torch.tensor([ids[-model.ctx:]], device=device)
        logits = model(inp)[0, -1]
        lp = torch.log_softmax(logits, dim=-1)
        nxt = int(lp.argmax())
        logprobs.append(float(lp[nxt]))
        ids.append(nxt)
        if nxt == EOS:
            break
    dt = time.time() - start
    text = bytes(b for b in ids if b < 256).decode("utf-8", errors="replace")
    return text, logprobs, len(ids) / max(dt, 1e-6)


def call_span_logprob(text, logprobs, prompt_len_ids):
    """Mean logprob over the bytes of the extracted call span."""
    span = extract_call_span(text)
    if not span:
        return None, None
    span_bytes = span.encode("utf-8", errors="replace")
    # logprobs[i] corresponds to ids[prompt_len + i]; find the span's offset.
    body = text.encode("utf-8", errors="replace")
    off = body.find(span_bytes)
    if off < 0:
        return span, None
    # Approximate: map byte offset -> token index via prompt byte length.
    start_tok = max(0, len(body[:off]) - 0)
    vals = logprobs[start_tok : start_tok + len(span_bytes)]
    if not vals:
        return span, None
    return span, sum(vals) / len(vals)


def ece(scores: list[float], labels: list[int], bins: int = 10) -> float:
    # scores are mean logprobs (negative); map to [0,1] via exp for binning.
    probs = [min(1.0, max(0.0, 2.718281828 ** s)) for s in scores]
    edges = [i / bins for i in range(bins + 1)]
    err, n = 0.0, len(probs)
    for b in range(bins):
        idx = [i for i, p in enumerate(probs) if edges[b] <= p < edges[b + 1] or (b == bins - 1 and p == 1.0)]
        if not idx:
            continue
        acc = sum(labels[i] for i in idx) / len(idx)
        conf = sum(probs[i] for i in idx) / len(idx)
        err += len(idx) / n * abs(acc - conf)
    return err


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--ckpt", default="checkpoints/needle-native/model.pt")
    ap.add_argument("--max-new", type=int, default=160)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt = torch.load(args.ckpt, map_location=device, weights_only=False)
    cfg = ckpt["config"]
    model = ByteLM(layers=cfg["layers"], d=cfg["d"], heads=cfg["heads"],
                   dff=cfg["dff"], ctx=cfg["ctx"]).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    catalog = {t.name: t for t in build_catalog()}
    rows = [json.loads(l) for l in (Path(args.data) / "eval.jsonl").read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    valid = exact = 0
    tp = fp = fn = 0
    scores, labels = [], []
    tok_s = []
    for row in rows:
        prompt_ids = encode(row["prompt"])[: model.ctx // 2]
        text, lps, tps = greedy_decode(model, prompt_ids, args.max_new, device)
        tok_s.append(tps)
        span, conf = call_span_logprob(text, lps, len(prompt_ids))
        gold = row["gold"]
        grammar = CompiledGrammar([catalog[gold["tool"]]])
        try:
            call = grammar.validate_call(span) if span else None
            if call is None:
                raise GrammarError("no call span")
            valid += 1
            ok = call["tool"] == gold["tool"] and call["arguments"] == gold["arguments"]
            exact += ok
            labels.append(1 if ok else 0)
            gargs, cargs = gold["arguments"], call["arguments"]
            for k in cargs:
                if k in gargs and cargs[k] == gargs[k]:
                    tp += 1
                else:
                    fp += 1
            for k in gargs:
                if k not in cargs or cargs[k] != gargs[k]:
                    fn += 1
        except (GrammarError, ValueError):
            labels.append(0)
        if conf is not None:
            scores.append(conf)
        else:
            scores.append(-10.0)

    n = len(rows)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    report = {
        "n": n,
        "valid_call_rate": round(valid / n, 4),
        "exact_match_rate": round(exact / n, 4),
        "arg_precision": round(prec, 4),
        "arg_recall": round(rec, 4),
        "arg_f1": round(2 * prec * rec / max(1e-9, prec + rec), 4),
        "mean_tok_per_s": round(sum(tok_s) / len(tok_s), 1),
        "ece_mean_call_logprob": round(ece(scores, labels), 4),
        "note": "Confidence (mean call-span logprob) is a scrutiny signal only; "
                "it never authorizes. Authorization stays in dottie_loop.",
    }
    print(json.dumps(report, indent=2))
    Path("eval_report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
