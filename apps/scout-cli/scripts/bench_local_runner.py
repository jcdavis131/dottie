#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only
"""Benchmark local LLM runners head-to-head: Ollama vs KoboldCpp.

Measures the REAL tokens/sec + VRAM delta on THIS box — it does not assume the
"7x" figure from the write-up (that number is LM Studio -> KoboldCpp, i.e. mostly
Electron overhead). Ollama and KoboldCpp share the same llama.cpp core, so the
honest question is how much ContextShift + FlashAttention defaults + lower idle
overhead actually buy you here. This script answers that with numbers.

This script NEVER downloads or launches a runner. It measures whatever is already
serving. Start the contenders yourself first:

  Ollama     :  ollama serve      (then `ollama run <model>` once to load it)
  KoboldCpp  :  koboldcpp.exe --model <file>.gguf --usecublas --flashattention \
                             --contextshift --port 5001
               Download ONLY from github.com/LostRuins/koboldcpp/releases/latest
               — the koboldcpp[.]com domain is a known phishing clone. Needs a
               GGUF file (not HF safetensors). Kobold Lite UI is AGPL v3.

Example:
  python scripts/bench_local_runner.py --model qwen3:8b --rounds 5 --max-tokens 256
  python scripts/bench_local_runner.py --ollama-base http://localhost:11434 \
         --kobold-base http://localhost:5001 --context-shift
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
from pathlib import Path

# Make `bigbang` importable when this file is run directly from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bigbang.core.llm import (
    chat_with_metrics,
    get_ollama_base,
    koboldcpp_available,
)

DEFAULT_PROMPT = (
    "Explain, step by step and in full detail, how a Merkle tree proves that a "
    "single leaf is a member of the set without revealing the other leaves. "
    "Cover hashing, the proof path, and how the verifier recomputes the root."
)


def gpu_mem_used_mb() -> int | None:
    """Peak GPU memory.used across all visible GPUs, in MiB (None if no nvidia-smi)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        vals = [int(x) for x in out.stdout.splitlines() if x.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:
        return None


def bench_backend(
    backend: str,
    base: str | None,
    model: str,
    prompt: str,
    max_tokens: int,
    rounds: int,
    warmup: int,
    context_shift: bool,
) -> dict | None:
    """Warm up, then time `rounds` generations. Returns stats, or None if the
    backend is not reachable (skipped, not failed)."""
    detected = base or (
        get_ollama_base() if backend == "ollama" else koboldcpp_available()
    )
    if not detected:
        print(
            f"  [{backend}] not reachable — skipped "
            f"(start it first; see this script's header)"
        )
        return None

    messages = [{"role": "user", "content": prompt}]
    print(f"  [{backend}] {detected}  model={model}  warmup={warmup} rounds={rounds}")

    for _ in range(max(0, warmup)):
        chat_with_metrics(
            backend,
            model,
            messages,
            base=detected,
            max_tokens=max_tokens,
            timeout=300.0,
        )

    wall_tps: list[float] = []
    server_tps: list[float] = []
    toks: list[int] = []
    peak_vram = gpu_mem_used_mb()
    for i in range(rounds):
        r = chat_with_metrics(
            backend,
            model,
            messages,
            base=detected,
            max_tokens=max_tokens,
            timeout=300.0,
            context_shift=context_shift,
        )
        v = gpu_mem_used_mb()
        if v is not None:
            peak_vram = v if peak_vram is None else max(peak_vram, v)
        if not r.get("ok"):
            print(f"    round {i + 1}: FAILED — {r.get('error')}")
            continue
        if r.get("tok_per_s"):
            wall_tps.append(r["tok_per_s"])
        if r.get("server_tok_per_s"):
            server_tps.append(r["server_tok_per_s"])
        if r.get("completion_tokens"):
            toks.append(r["completion_tokens"])
        print(
            f"    round {i + 1}: {r.get('completion_tokens')} tok  "
            f"wall={r.get('tok_per_s')} tok/s  server={r.get('server_tok_per_s')} tok/s"
        )

    if not wall_tps:
        print(f"  [{backend}] no successful rounds")
        return None
    return {
        "backend": backend,
        "base": detected,
        "model": model,
        "n": len(wall_tps),
        "wall_tok_per_s_median": round(statistics.median(wall_tps), 2),
        "wall_tok_per_s_stdev": round(statistics.stdev(wall_tps), 2)
        if len(wall_tps) > 1
        else 0.0,
        "server_tok_per_s_median": round(statistics.median(server_tps), 2)
        if server_tps
        else None,
        "tokens_median": int(statistics.median(toks)) if toks else None,
        "peak_vram_used_mb": peak_vram,
        "context_shift": context_shift,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ollama vs KoboldCpp local-runner benchmark"
    )
    ap.add_argument(
        "--model",
        default="qwen3:8b",
        help="model name (Ollama tag, or ignored by Kobold which serves its loaded GGUF)",
    )
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--ollama-base", default="")
    ap.add_argument("--kobold-base", default="")
    ap.add_argument(
        "--context-shift",
        action="store_true",
        help="record that Kobold was launched with --contextshift (telemetry label)",
    )
    ap.add_argument(
        "--only",
        choices=["ollama", "koboldcpp"],
        default="",
        help="benchmark just one backend",
    )
    args = ap.parse_args()

    baseline = gpu_mem_used_mb()
    print(
        f"baseline GPU memory.used: {baseline} MiB"
        if baseline is not None
        else "nvidia-smi not available — VRAM will be null"
    )

    todo = [
        ("ollama", args.ollama_base or None),
        ("koboldcpp", args.kobold_base or None),
    ]
    if args.only:
        todo = [t for t in todo if t[0] == args.only]

    results: dict[str, dict] = {}
    for backend, base in todo:
        r = bench_backend(
            backend,
            base,
            args.model,
            args.prompt,
            args.max_tokens,
            args.rounds,
            args.warmup,
            args.context_shift,
        )
        if r:
            results[backend] = r

    # --- report ---
    print("\n=== RESULT ===")
    hdr = f"{'backend':<11} {'n':>3} {'median tok/s':>13} {'stdev':>7} {'server tok/s':>13} {'peak VRAM MiB':>14}"
    print(hdr)
    print("-" * len(hdr))
    for backend, r in results.items():
        print(
            f"{backend:<11} {r['n']:>3} {r['wall_tok_per_s_median']:>13} "
            f"{r['wall_tok_per_s_stdev']:>7} "
            f"{r['server_tok_per_s_median']!s:>13} {r['peak_vram_used_mb']!s:>14}"
        )
    if baseline is not None:
        for backend, r in results.items():
            if r["peak_vram_used_mb"] is not None:
                print(
                    f"  {backend} VRAM over baseline: {r['peak_vram_used_mb'] - baseline} MiB"
                )
    if "ollama" in results and "koboldcpp" in results:
        o = results["ollama"]["wall_tok_per_s_median"]
        k = results["koboldcpp"]["wall_tok_per_s_median"]
        if o > 0:
            print(
                f"\n  KoboldCpp / Ollama speedup: {k / o:.2f}x "
                f"(measured on THIS box — not the write-up's 7x LM-Studio figure)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
