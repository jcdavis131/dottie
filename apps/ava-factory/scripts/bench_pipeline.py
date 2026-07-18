#!/usr/bin/env python3
"""Measure collector / curator / trainer throughput and gate curation ≥ 3× trainer.

Usage:
  python scripts/bench_pipeline.py --preset nano
  python scripts/bench_pipeline.py --preset nano --device cpu --skip-trainer-gpu

Writes reports/bench_pipeline.json with measured tok/s. Exit 0 always after a
successful measurement; prints GATE PASS / GATE FAIL for the 3× invariant.
Does not fake numbers — if the gate fails, it says so.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _log(msg: str) -> None:
    print(msg, flush=True)


def _resolve_tokenizer(preset: str) -> Path:
    cfg_path = _REPO / "configs" / f"{preset}.yaml"
    tok = _REPO / "data" / preset / "tokenizer" / f"ava_{preset}_bpe.json"
    if cfg_path.is_file():
        try:
            import yaml

            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            rel = (cfg.get("data") or {}).get("tokenizer_path")
            if rel:
                cand = _REPO / rel
                if cand.is_file():
                    return cand
        except Exception:
            pass
    if tok.is_file():
        return tok
    # common nano name
    alt = _REPO / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json"
    if alt.is_file():
        return alt
    raise FileNotFoundError(
        f"no frozen tokenizer for preset={preset}; expected {tok} "
        "(run Stage 5 bootstrap / scripts/build_eval_data.py first)"
    )


def bench_collector(workdir: Path, *, target_bytes: int, max_docs: int, seed: int) -> dict:
    """Synthetic collect → RAW .jsonl.zst; report docs/s and approx tok/s."""
    from ava.datagen.logic import LogicGenerator
    from ava.pipeline.collector import ShardWriter, doc_id_for
    from ava.pipeline.pack import load_tokenizer

    raw_dir = workdir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    writer = ShardWriter("bench_logic", raw_dir, target_bytes=target_bytes)
    gen = LogicGenerator(seed=seed)
    tok_path = os.environ.get("AVA_TOKENIZER")
    lt = load_tokenizer(tok_path) if tok_path else None

    docs_written = 0
    bytes_written = 0
    tokens_est = 0
    t0 = time.perf_counter()
    for doc in gen.generate(max(target_bytes * 2, 200_000)):
        text = doc["text"]
        rec = {
            "doc_id": doc_id_for("bench_logic", text),
            "text": text,
            "source": "bench_logic",
            "phase": doc.get("phase", "p0"),
            "task_type": doc.get("task_type", "automatic"),
            "concept": doc.get("concept", ""),
            "meta": {},
        }
        if lt is not None:
            tokens_est += len(lt.tokenizer.encode(text).ids) + 1  # +EOD
        rolled = writer.add(rec)
        docs_written += 1
        if rolled:
            info = writer.publish()
            bytes_written += info.bytes if info else 0
            writer.reset()
            break
        if docs_written >= max_docs:
            break
    if writer.docs > 0:
        info = writer.publish()
        bytes_written += info.bytes if info else 0
    elapsed = max(time.perf_counter() - t0, 1e-6)

    # If we couldn't tokenize during collect, estimate from chars (~3.3 chars/tok nano).
    if tokens_est <= 0:
        tokens_est = max(1, int(bytes_written / 3.3))

    return {
        "docs": docs_written,
        "raw_bytes": bytes_written,
        "tokens_est": tokens_est,
        "elapsed_s": round(elapsed, 4),
        "docs_per_s": round(docs_written / elapsed, 2),
        "tok_s": round(tokens_est / elapsed, 2),
        "note": "synthetic LogicGenerator → ShardWriter (no HF network)",
    }


def bench_curator(workdir: Path, *, n_docs: int, seed: int, pipeline_cfg: Path) -> dict:
    """Clean + dedup + decontam + pack on synthetic docs; measure packed tok/s."""
    from ava.datagen.logic import LogicGenerator
    from ava.pipeline import clean, decontaminate
    from ava.pipeline.dedup import MinHashDeduper
    from ava.pipeline.decontaminate import Decontaminator
    from ava.pipeline.pack import load_tokenizer, pack_docs, write_shard
    from ava.pipeline.split import assign_split
    import yaml

    cfg = yaml.safe_load(pipeline_cfg.read_text(encoding="utf-8"))
    cur = cfg["curator"]
    splits = {k: float(v) for k, v in cfg["splits"].items()}
    dedup_db = workdir / "dedup.db"
    packed_dir = workdir / "packed"
    packed_dir.mkdir(parents=True, exist_ok=True)

    gen = LogicGenerator(seed=seed)
    docs_in = []
    for doc in gen.generate(500_000):
        docs_in.append(doc)
        if len(docs_in) >= n_docs:
            break

    lt = load_tokenizer(os.environ["AVA_TOKENIZER"])
    deduper = MinHashDeduper(
        str(dedup_db),
        num_perm=int(cur.get("minhash_perm", 128)),
        threshold=float(cur.get("minhash_threshold", 0.8)),
    )
    decon = Decontaminator(ngram=int(cur.get("ngram_decontam", 13)))

    kept: list[dict] = []
    t0 = time.perf_counter()
    try:
        for i, doc in enumerate(docs_in):
            norm = clean.normalize(doc.get("text", ""))
            if not norm or not clean.is_english(norm):
                continue
            ok, _ = clean.gopher_quality(norm)
            if not ok:
                continue
            scrubbed = clean.scrub_pii(norm)
            doc_id = doc.get("doc_id") or f"bench:{i}"
            if not deduper.add_if_new(doc_id, scrubbed):
                continue
            contaminated, _ = decon.is_contaminated(scrubbed)
            if contaminated:
                continue
            split = assign_split(doc_id, splits)
            if split != "train":
                continue
            kept.append(
                {
                    "doc_id": doc_id,
                    "text": scrubbed,
                    "task_type": doc.get("task_type", "automatic"),
                    "concept": doc.get("concept", ""),
                    "phase": doc.get("phase", "p0"),
                }
            )
        arr, idx = pack_docs(kept, lt)
        out_bin = packed_dir / "bench_curate.bin"
        write_shard(arr, idx, out_bin)
    finally:
        deduper.close()
    elapsed = max(time.perf_counter() - t0, 1e-6)
    tokens = int(arr.size) if kept else 0

    return {
        "docs_in": len(docs_in),
        "docs_kept": len(kept),
        "tokens": tokens,
        "elapsed_s": round(elapsed, 4),
        "tok_s": round(tokens / elapsed, 2),
        "note": "clean→dedup→decontam→pack (train split only)",
    }


def bench_trainer(preset: str, *, device: str, warmup: int, steps: int, seq: int) -> dict:
    """Steady-state trainer tok/s via timed optimizer steps (random ids).

    Mirrors specs/05 bench_throughput spirit but scoped to the pipeline gate:
    we need trainer tok/s as the denominator for the curation ≥ 3× check.
    """
    import torch

    from ava.config import AvaConfig
    from ava.jlosses import JSpaceObjective
    from ava.model import build_model
    from ava.train import build_optimizer, micro_batch_for

    cfg = AvaConfig.load(preset)
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
        _log("WARN: CUDA requested but unavailable; falling back to cpu")

    model = build_model(cfg).to(device)
    opt = build_optimizer(model, cfg)
    obj = JSpaceObjective(cfg).to(device)
    model.train()

    mb, accum = micro_batch_for(seq, cfg.training.tokens_per_step)
    # Keep the microbench short: one micro-batch per step (accum=1) so wall time
    # stays bounded; tok/s still reflects forward+backward+opt on real geometry.
    accum = 1
    mb = max(1, min(mb, 4))
    V = cfg.model.vocab_size
    step_tokens = mb * seq

    def one_step() -> None:
        opt.zero_grad(set_to_none=True)
        ids = torch.randint(0, V, (mb, seq), device=device)
        cids = torch.full((mb,), -1, device=device, dtype=torch.long)
        use_bf16 = device == "cuda" and cfg.training.precision == "bf16"
        ctx = (
            torch.autocast("cuda", dtype=torch.bfloat16)
            if use_bf16
            else torch.autocast("cpu", enabled=False)
        )
        with ctx:
            out = model(input_ids=ids, task_type="automatic")
            parts = obj(model, out, ids, phase=0, task_type="automatic", concept_ids=cids)
        parts.total.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.training.optimizer.grad_clip)
        opt.step()

    # warmup
    for _ in range(warmup):
        one_step()
    if device == "cuda":
        torch.cuda.synchronize()

    t0 = time.perf_counter()
    for _ in range(steps):
        one_step()
    if device == "cuda":
        torch.cuda.synchronize()
    elapsed = max(time.perf_counter() - t0, 1e-6)
    tok_s = (step_tokens * steps) / elapsed

    return {
        "device": device,
        "seq": seq,
        "micro_batch": mb,
        "steps": steps,
        "warmup": warmup,
        "tokens_per_step": step_tokens,
        "elapsed_s": round(elapsed, 4),
        "tok_s": round(tok_s, 2),
        "params": sum(p.numel() for p in model.parameters()),
        "note": "random-id optimizer steps (no DATA_STARVED / no packed I/O)",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ava pipeline throughput bench + 3× gate")
    ap.add_argument("--preset", default=os.environ.get("AVA_PRESET", "nano"))
    ap.add_argument("--device", default=None, help="cpu|cuda (default: cuda if available)")
    ap.add_argument("--collector-docs", type=int, default=400)
    ap.add_argument("--curator-docs", type=int, default=300)
    ap.add_argument("--trainer-steps", type=int, default=20)
    ap.add_argument("--trainer-warmup", type=int, default=5)
    ap.add_argument("--seq", type=int, default=256)
    ap.add_argument("--skip-trainer", action="store_true")
    ap.add_argument("--out", default=None, help="JSON output path")
    args = ap.parse_args(argv)

    import torch

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    tok_path = _resolve_tokenizer(args.preset)
    os.environ["AVA_TOKENIZER"] = str(tok_path)
    pipeline_cfg = _REPO / "configs" / "pipeline.yaml"
    if not pipeline_cfg.is_file():
        pipeline_cfg = Path(os.environ.get("AVA_PIPELINE_CONFIG", "/app/configs/pipeline.yaml"))

    _log(f"bench_pipeline preset={args.preset} device={device} tokenizer={tok_path}")

    workdir = Path(tempfile.mkdtemp(prefix="ava_bench_"))
    result: dict = {
        "preset": args.preset,
        "device": device,
        "tokenizer": str(tok_path),
        "gate_ratio_required": 3.0,
    }
    try:
        _log("--- collector ---")
        # Small target so we don't write a 256MB shard during a bench.
        coll = bench_collector(
            workdir,
            target_bytes=256_000,
            max_docs=args.collector_docs,
            seed=1234,
        )
        result["collector"] = coll
        _log(json.dumps({"collector": coll}))

        _log("--- curator ---")
        cur = bench_curator(
            workdir,
            n_docs=args.curator_docs,
            seed=1234,
            pipeline_cfg=pipeline_cfg,
        )
        result["curator"] = cur
        _log(json.dumps({"curator": cur}))

        if args.skip_trainer:
            result["trainer"] = {"skipped": True, "tok_s": None}
            _log("trainer skipped")
        else:
            _log("--- trainer ---")
            tr = bench_trainer(
                args.preset,
                device=device,
                warmup=args.trainer_warmup,
                steps=args.trainer_steps,
                seq=args.seq,
            )
            result["trainer"] = tr
            _log(json.dumps({"trainer": tr}))

        c_tok = float(cur["tok_s"])
        t_tok = result["trainer"].get("tok_s")
        if t_tok is None:
            result["gate"] = {
                "pass": None,
                "reason": "trainer skipped — cannot evaluate 3× gate",
                "curation_tok_s": c_tok,
                "trainer_tok_s": None,
                "ratio": None,
            }
            _log("GATE DEFERRED (no trainer measurement)")
        else:
            t_tok = float(t_tok)
            ratio = c_tok / t_tok if t_tok > 0 else float("inf")
            ok = c_tok >= 3.0 * t_tok
            result["gate"] = {
                "pass": ok,
                "curation_tok_s": c_tok,
                "trainer_tok_s": t_tok,
                "collector_tok_s": float(coll["tok_s"]),
                "ratio": round(ratio, 3),
                "required": 3.0,
            }
            if ok:
                _log(
                    f"GATE PASS: curation {c_tok:.1f} tok/s >= 3x trainer {t_tok:.1f} tok/s "
                    f"(ratio={ratio:.2f})"
                )
            else:
                _log(
                    f"GATE FAIL: curation {c_tok:.1f} tok/s < 3x trainer {t_tok:.1f} tok/s "
                    f"(ratio={ratio:.2f}; need >= {3.0 * t_tok:.1f})"
                )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    out = Path(args.out) if args.out else _REPO / "reports" / "bench_pipeline.json"
    if not out.is_absolute():
        out = _REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
