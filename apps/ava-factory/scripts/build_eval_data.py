"""Build tokenizer + heldout bins required by the real eval harness."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# Running as `python scripts/...` puts scripts/ on sys.path, not the repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np

from ava.config import AvaConfig
from ava.datagen.chat_safety import ChatSafetyGenerator
from ava.datagen.code_gen import CodeGenGenerator
from ava.datagen.encyclopedia import EncyclopediaGenerator
from ava.datagen.logic import LogicGenerator
from ava.datagen.math_gen import MathGenerator
from ava.pipeline.pack import LoadedTokenizer, load_tokenizer, pack_docs, write_shard
from ava.tokenizer import train as train_tokenizer
from evals.probe_items_gen import generate_probe_items

_REPO_ROOT = _REPO
SEED = 1234


def _bucket(doc_id: str) -> int:
    return int(hashlib.sha1(doc_id.encode()).hexdigest(), 16) % 100


def _collect_docs(target_bytes: int = 500_000) -> list[dict]:
    gens = [
        LogicGenerator(SEED),
        MathGenerator(SEED + 1),
        EncyclopediaGenerator(SEED + 2),
        CodeGenGenerator(SEED + 3),
        ChatSafetyGenerator(SEED + 4),
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


def build(preset: str = "nano", force: bool = False) -> None:
    cfg = AvaConfig.load(preset)
    data_root = _REPO_ROOT / "data" / preset
    tok_path = _REPO_ROOT / cfg.data.get("tokenizer_path", f"data/{preset}/tokenizer/ava_nano_bpe.json")
    corpus_dir = data_root / "eval_corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if force or not tok_path.exists():
        docs = _collect_docs()
        shard = corpus_dir / "corpus.jsonl"
        with open(shard, "w", encoding="utf-8") as f:
            for d in docs:
                f.write(json.dumps({"text": d["text"]}) + "\n")
        tok_path.parent.mkdir(parents=True, exist_ok=True)
        train_tokenizer(corpus_dir, tok_path, cfg.model.vocab_size, max_bytes=2_000_000)
        print(f"tokenizer -> {tok_path}")

    generate_probe_items()

    lt = load_tokenizer(tok_path)
    docs = _collect_docs()
    phase_map = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5}
    heldout_budget = int(cfg.data.get("heldout_tokens_per_phase", 200_000))

    for phase_idx in range(len(cfg.phases)):
        phase_key = f"p{phase_idx}"
        held_docs = []
        for d in docs:
            if not d["phase"].startswith(phase_key):
                continue
            if _bucket(d["doc_id"]) >= 2:  # ~2% heldout (test bucket)
                continue
            held_docs.append(d)
        if not held_docs:
            # fallback: any concept-tagged docs for soccer_rugby test
            held_docs = [d for d in docs if d.get("concept")][:50]

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
            print(f"heldout phase {phase_idx}: {arr.size} tokens, {len(idx['docs'])} docs -> {out}")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    build(args.preset, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
