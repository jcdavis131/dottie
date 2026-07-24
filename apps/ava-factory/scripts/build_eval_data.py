"""Build tokenizer + heldout bins required by the real eval harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Running as `python scripts/...` puts scripts/ on sys.path, not the repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


from ava.config import AvaConfig
from ava.datagen.chat_safety import ChatSafetyGenerator
from ava.datagen.code_gen import CodeGenGenerator
from ava.datagen.encyclopedia import EncyclopediaGenerator
from ava.datagen.logic import LogicGenerator
from ava.datagen.math_gen import MathGenerator
from ava.pipeline.pack import load_tokenizer, pack_docs, write_shard
from ava.tokenizer import train as train_tokenizer
from evals.probe_items_gen import generate_probe_items

_REPO_ROOT = _REPO
SEED = 1234
# Held-out MUST be disjoint from training. The collector generates synthetic docs
# with seed `1234 + epoch` (collector.py:155 "same seed => same corpus"), all
# labeled split="train"; it never excludes a test split. So held-out docs built
# with SEED=1234 were BYTE-IDENTICAL to the collector's epoch-0 training docs and
# the perplexity "eval" was measuring memorization (provenance audit 2026-07-24).
# Generating held-out from a seed astronomically outside the epoch range (a run is
# thousands of steps, not ~1e9 epochs) yields fresh draws from the SAME generators
# and distribution that training provably never saw — a real held-out.
HELDOUT_SEED = SEED + 1_000_000_000


def _collect_docs(target_bytes: int = 500_000, seed: int = SEED) -> list[dict]:
    gens = [
        LogicGenerator(seed),
        MathGenerator(seed + 1),
        EncyclopediaGenerator(seed + 2),
        CodeGenGenerator(seed + 3),
        ChatSafetyGenerator(seed + 4),
    ]
    docs: list[dict] = []
    seen = 0
    for gen in gens:
        for doc in gen.generate(target_bytes // len(gens)):
            docs.append(doc)
            seen += len(doc["text"])
            if seen >= target_bytes:
                return docs
    return docs


def build(
    preset: str = "nano",
    force: bool = False,
    target_bytes: int = 500_000,
    rebuild_tokenizer: bool = False,
) -> None:
    cfg = AvaConfig.load(preset)
    data_root = _REPO_ROOT / "data" / preset
    tok_path = _REPO_ROOT / cfg.data.get(
        "tokenizer_path", f"data/{preset}/tokenizer/ava_nano_bpe.json"
    )
    corpus_dir = data_root / "eval_corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # An existing tokenizer may be the FROZEN pipeline artifact the training corpus
    # was packed with (mini's ava_bpe_32k.json is). Retraining it here from a small
    # eval corpus would silently invalidate every future eval, so --force no longer
    # touches it — only the explicit --rebuild-tokenizer flag does.
    if rebuild_tokenizer or not tok_path.exists():
        docs = _collect_docs(target_bytes)
        shard = corpus_dir / "corpus.jsonl"
        with open(shard, "w", encoding="utf-8") as f:
            for d in docs:
                f.write(json.dumps({"text": d["text"]}) + "\n")
        tok_path.parent.mkdir(parents=True, exist_ok=True)
        train_tokenizer(corpus_dir, tok_path, cfg.model.vocab_size, max_bytes=2_000_000)
        print(f"tokenizer -> {tok_path}")

    generate_probe_items()

    lt = load_tokenizer(tok_path)
    # Disjointness comes from HELDOUT_SEED (a generation training never runs), so
    # every doc here is valid held-out — no sub-bucket needed, and the old 2% hash
    # bucket (sha1%100<2) was uncorrelated with the training split anyway.
    docs = _collect_docs(target_bytes, seed=HELDOUT_SEED)
    heldout_budget = int(cfg.data.get("heldout_tokens_per_phase", 200_000))

    for phase_idx in range(len(cfg.phases)):
        phase_key = f"p{phase_idx}"
        held_docs = [d for d in docs if d["phase"].startswith(phase_key)]
        if not held_docs:
            # A phase with no held-out docs is a real gap — report it, never
            # backfill with non-held-out (training) docs (the old fallback did,
            # re-contaminating the bin; provenance audit 2026-07-24).
            print(f"heldout phase {phase_idx}: NO disjoint docs for {phase_key} "
                  f"— bin skipped (raise --target-bytes)")
            continue

        arr, idx = pack_docs(held_docs, lt)
        # Truncate to heldout budget
        if arr.size > heldout_budget:
            arr = arr[:heldout_budget]
            # trim idx docs beyond budget
            trimmed = []
            for doc in idx["docs"]:
                if doc["end"] <= heldout_budget:
                    trimmed.append(doc)
                elif doc["start"] < heldout_budget:
                    doc = dict(doc)
                    doc["end"] = heldout_budget
                    trimmed.append(doc)
                    break
            idx["docs"] = trimmed
            idx["tokens"] = int(arr.size)

        out = data_root / f"heldout_phase{phase_idx}.bin"
        if force or not out.exists():
            write_shard(arr, idx, out)
            print(
                f"heldout phase {phase_idx}: {arr.size} tokens, {len(idx['docs'])} docs -> {out}"
            )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--force", action="store_true", help="rewrite existing heldout bins")
    ap.add_argument(
        "--target-bytes", type=int, default=500_000,
        help="doc bytes to collect; raise so sparse phases (p3/p5) clear the eval's "
        "minimum-token floor (500k left mini p3 at 447 tokens -> 'too short')",
    )
    ap.add_argument(
        "--rebuild-tokenizer", action="store_true",
        help="retrain the tokenizer even if one exists — NEVER for a preset whose "
        "tokenizer is the frozen pipeline artifact (e.g. mini's ava_bpe_32k.json)",
    )
    args = ap.parse_args()
    build(
        args.preset,
        force=args.force,
        target_bytes=args.target_bytes,
        rebuild_tokenizer=args.rebuild_tokenizer,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
