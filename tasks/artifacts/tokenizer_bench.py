#!/usr/bin/env python3
"""Honest micro-benchmark for the shard-packing tokenize path (STAGED, NOT RUN).

Written 2026-07-23 while a GPU training run was live. DO NOT run until the
trainer is idle: the guard flag --trainer-idle is required, because CPU
contention would corrupt both this measurement and the live run.

What it measures, on the SAME real raw-shard documents:
  A  current path  — per-doc ``tok.encode(text).ids`` loop, exactly as
                     dottie/pipeline/pack.py:pack_docs does today.
  B  encode_batch  — one ``tok.encode_batch(texts)`` call (GIL released,
                     rayon-parallel inside the HF tokenizers Rust core).
  C  py-word-cache — the REJECTED pure-Python pretoken LRU (whitespace-word
                     dict cache above the FFI boundary), included behind
                     --include-pyword-cache to validate the rejection with a
                     number instead of an assertion. NOTE: C is NOT
                     id-equivalent to A/B (word-boundary encoding differs);
                     it is a throughput probe only, never a packing path.

Methodology (disclosed, gigatoken-style — see tokenizer_learnings.md §1):
  * doc-level encode of discrete jsonl records; the presplit-vs-unsplit
    question from the Gigatoken README does not arise for our data shape.
  * variants run interleaved A,B[,C] x --repeats on identical docs so
    thermal/clock drift cannot systematically favor a later variant;
    best-of-N reported per variant.
  * intra-process repeats still share allocator/cache warmth: for the real
    number, run this script 3x in fresh processes and take the best.
  * A-vs-B id-equality is asserted BEFORE any speedup is reported, because
    Patch A in tokenizer_learnings.md is only valid if output is identical.

Usage (after the freeze lifts, trainer idle):
  python tasks/artifacts/tokenizer_bench.py --trainer-idle \
      [--factory-root C:/Users/jcdav/dottie/apps/ava-factory] \
      [--preset mini] [--tokenizer PATH] [--shard PATH.jsonl[.zst]] \
      [--max-docs 2000] [--repeats 3] [--include-pyword-cache] [--out PATH]

Reads only; writes only its JSON report (default: next to this script).
No torch, no docker, no model loads, no manifest access.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_FACTORY_ROOT = Path(r"C:\Users\jcdav\dottie\apps\ava-factory")


def _resolve_tokenizer(root: Path, preset: str, explicit: str | None) -> Path:
    """Mirror scripts/bench_pipeline.py:_resolve_tokenizer (host-side copies)."""
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(f"--tokenizer {p} does not exist")
    env = os.environ.get("AVA_TOKENIZER")
    if env and Path(env).is_file():
        return Path(env)
    cfg_path = root / "configs" / f"{preset}.yaml"
    if cfg_path.is_file():
        try:
            import yaml

            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            rel = (cfg.get("data") or {}).get("tokenizer_path")
            if rel:
                cand = root / rel
                if cand.is_file():
                    return cand
        except Exception:
            pass
    for cand in (
        root / "data" / preset / "tokenizer" / f"ava_{preset}_bpe.json",
        root / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json",
    ):
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        f"no frozen tokenizer found for preset={preset}; pass --tokenizer or "
        f"set AVA_TOKENIZER (canonical copy lives on the ava_state volume at "
        f"/state/tokenizer.json; host copies under data/<preset>/tokenizer/)"
    )


def _iter_docs(shard: Path):
    """Yield 'text' fields from a .jsonl or .jsonl.zst raw shard."""
    if shard.suffix == ".zst":
        import zstandard as zstd

        fh = zstd.ZstdDecompressor().stream_reader(open(shard, "rb"))
        stream = io.TextIOWrapper(fh, encoding="utf-8")
    else:
        stream = open(shard, encoding="utf-8")
    with stream as f:
        for line in f:
            try:
                text = json.loads(line).get("text")
            except json.JSONDecodeError:
                continue
            if text:
                yield text


def _find_shard(root: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(f"--shard {p} does not exist")
    raw_dir = Path(os.environ.get("AVA_RAW_DIR", root / "data" / "raw"))
    candidates: list[Path] = []
    if raw_dir.is_dir():
        candidates = sorted(raw_dir.rglob("*.jsonl*"))
    if not candidates:
        candidates = (
            sorted((root / "data").rglob("*.jsonl*"))
            if (root / "data").is_dir()
            else []
        )
    candidates = [c for c in candidates if c.suffix in (".jsonl", ".zst")]
    if not candidates:
        raise FileNotFoundError(
            f"no .jsonl/.jsonl.zst shard under {raw_dir} or {root / 'data'}; pass --shard"
        )
    # Pick the largest so the sample is not a stub shard.
    return max(candidates, key=lambda p: p.stat().st_size)


# --- variants ---------------------------------------------------------------


def variant_a_current(tok, eod_id: int, texts: list[str]) -> list[int]:
    """Exactly pack_docs' shape: per-doc encode loop + stream extend + eod."""
    stream: list[int] = []
    for t in texts:
        stream.extend(tok.encode(t).ids)
        stream.append(eod_id)
    return stream


def variant_b_batch(tok, eod_id: int, texts: list[str]) -> list[int]:
    """Patch A shape: one encode_batch call, same stream layout."""
    stream: list[int] = []
    for enc in tok.encode_batch(texts):
        stream.extend(enc.ids)
        stream.append(eod_id)
    return stream


def variant_c_pyword_cache(
    tok, eod_id: int, texts: list[str], cache: dict
) -> list[int]:
    """REJECTED design, measured to validate the rejection (see module doc).

    Whitespace-word dict cache above the FFI boundary. NOT id-equivalent to
    A/B (word-local encoding loses cross-boundary merges and space prefixes);
    throughput probe only.
    """
    stream: list[int] = []
    for t in texts:
        for w in t.split(" "):
            ids = cache.get(w)
            if ids is None:
                ids = tok.encode(" " + w).ids
                if len(cache) < 200_000:
                    cache[w] = ids
            stream.extend(ids)
        stream.append(eod_id)
    return stream


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--trainer-idle",
        action="store_true",
        help="REQUIRED. You are asserting no GPU training run is live; this "
        "bench saturates CPU cores and would skew a live run (and be skewed by it).",
    )
    ap.add_argument("--factory-root", default=str(DEFAULT_FACTORY_ROOT))
    ap.add_argument("--preset", default=os.environ.get("AVA_PRESET", "mini"))
    ap.add_argument("--tokenizer", default=None)
    ap.add_argument("--shard", default=None, help="raw .jsonl[.zst] to sample")
    ap.add_argument("--max-docs", type=int, default=2000)
    ap.add_argument(
        "--repeats", type=int, default=3, help="interleaved repeats; best-of-N"
    )
    ap.add_argument("--include-pyword-cache", action="store_true")
    ap.add_argument("--out", default=None, help="JSON report path")
    args = ap.parse_args(argv)

    if not args.trainer_idle:
        print(
            "REFUSING TO RUN: pass --trainer-idle only when no GPU training run "
            "is live (this bench is CPU-heavy and both measurements would lie).",
            file=sys.stderr,
        )
        return 2

    root = Path(args.factory_root)
    if not (root / "dottie" / "pipeline" / "pack.py").is_file():
        print(f"--factory-root {root} does not look like ava-factory", file=sys.stderr)
        return 2
    sys.path.insert(0, str(root))

    from dottie.pipeline.pack import load_tokenizer

    tok_path = _resolve_tokenizer(root, args.preset, args.tokenizer)
    lt = load_tokenizer(tok_path)
    tok, eod_id = lt.tokenizer, lt.eod_id

    shard = _find_shard(root, args.shard)
    texts: list[str] = []
    for t in _iter_docs(shard):
        texts.append(t)
        if len(texts) >= args.max_docs:
            break
    if not texts:
        print(f"no docs read from {shard}", file=sys.stderr)
        return 2
    total_bytes = sum(len(t.encode("utf-8")) for t in texts)

    # Correctness gate BEFORE any timing is reported: Patch A is only valid
    # if encode_batch ids are identical to the per-doc loop's.
    ids_a = variant_a_current(tok, eod_id, texts)
    ids_b = variant_b_batch(tok, eod_id, texts)
    equivalent = ids_a == ids_b
    n_tokens = len(ids_a)

    variants: dict[str, dict] = {
        "A_current_perdoc_loop": {"fn": lambda: variant_a_current(tok, eod_id, texts)},
        "B_encode_batch": {"fn": lambda: variant_b_batch(tok, eod_id, texts)},
    }
    if args.include_pyword_cache:
        c_cache: dict = {}
        variants["C_pyword_cache_REJECTED"] = {
            "fn": lambda: variant_c_pyword_cache(tok, eod_id, texts, c_cache)
        }

    # Interleaved best-of-N: A,B[,C], A,B[,C], ...
    for name in variants:
        variants[name]["times"] = []
    for _ in range(max(1, args.repeats)):
        for name, v in variants.items():
            t0 = time.perf_counter()
            v["fn"]()
            v["times"].append(time.perf_counter() - t0)

    report = {
        "written_utc": "2026-07-23 (staged during live-run freeze; run later)",
        "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "methodology": (
            "doc-level encode of discrete jsonl records; variants interleaved "
            "on identical docs; best-of-%d intra-process — run the script 3x "
            "in fresh processes and take the best per variant; A/B id-equality "
            "asserted before speedups; C is a throughput probe only (not "
            "id-equivalent, rejected design)." % max(1, args.repeats)
        ),
        "host": {
            "cpu_count": os.cpu_count(),
            "platform": sys.platform,
            "tokenizers_parallelism_env": os.environ.get("TOKENIZERS_PARALLELISM"),
            "rayon_num_threads_env": os.environ.get("RAYON_NUM_THREADS"),
        },
        "tokenizer": {
            "path": str(tok_path),
            "sha256": lt.sha256,
            "vocab": lt.vocab_size,
        },
        "sample": {
            "shard": str(shard),
            "docs": len(texts),
            "bytes": total_bytes,
            "tokens_current_path": n_tokens,
        },
        "a_b_ids_identical": equivalent,
        "results": {},
    }
    best_a = None
    for name, v in variants.items():
        best = min(v["times"])
        row = {
            "times_s": [round(t, 4) for t in v["times"]],
            "best_s": round(best, 4),
            "mb_per_s": round(total_bytes / best / 1e6, 2),
            "mtok_per_s": round(n_tokens / best / 1e6, 3),
        }
        if name.startswith("A_"):
            best_a = best
        elif best_a:
            row["speedup_vs_A"] = round(best_a / best, 2)
        report["results"][name] = row

    if not equivalent:
        report["WARNING"] = (
            "encode_batch ids differ from per-doc loop ids — Patch A is NOT "
            "safe to apply; investigate before quoting any speedup."
        )

    out = (
        Path(args.out)
        if args.out
        else Path(__file__).with_name("tokenizer_bench_results.json")
    )
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["results"], indent=2))
    print(f"a_b_ids_identical={equivalent}")
    print(f"wrote {out}")
    return 0 if equivalent else 1


if __name__ == "__main__":
    raise SystemExit(main())
