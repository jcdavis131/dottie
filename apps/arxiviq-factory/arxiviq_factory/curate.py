"""Stage 5: curate the families into a training-ready pack.

  1. build every family from the committed source snapshots
  2. decontaminate (the dottie-os bench regex) and validate each record with
     the frozen jev-v0 validator; rejects are counted by reason, never repaired
  3. deduplicate identical (state, question, label); drop both sides of any
     identical state and question that carry different labels
  4. hold out >= 20% of PAPERS (every row of a held-out paper, so no paper and
     no Nimble pair straddles the split)
  5. write data/packs/<version>/{train,holdout}.jsonl (strict jev records),
     provenance.jsonl (family, paper, label source, pair_id, split per id) and
     MANIFEST.json; copy MANIFEST.json and a small per-family sample into the
     app so the pack's shape is reviewable without the gitignored data/.

Nothing here promotes anything or trains anything: consent.champion stays
false and the pack is a HELPER input, like the dottie-os packs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from typing import Any

from . import PACK_VERSION, SCHEMA_ID
from .common import APP_ROOT, DATA, SOURCES, read_jsonl, sha256_file, write_jsonl
from .families import Corpus, build

REPO = APP_ROOT.parent.parent
JEV_IO = REPO / "apps" / "jev-v0" / "decision_io.py"
HOLDOUT_FRAC = 0.20
CONSENT = {"capture_training": True, "public_sources": True, "champion": False}

# Same bench-contamination guard as apps/dottie-os (ultradata_curriculum._DECONTAM).
_DECONTAM = re.compile(r"(arxiviq|openjev|jevbench|nanojev|typesafe\s+teacher|jev-v0\s+champion)", re.I)


def load_validator() -> Any:
    spec = importlib.util.spec_from_file_location("jev_decision_io", JEV_IO)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the jev-v0 validator at {JEV_IO}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jev_decision_io"] = mod
    spec.loader.exec_module(mod)
    if mod.SCHEMA_ID != SCHEMA_ID:
        raise SystemExit(f"jev-v0 schema is {mod.SCHEMA_ID}, this factory writes {SCHEMA_ID}")
    return mod


def _key(rec: dict[str, Any], with_label: bool) -> str:
    body = {"state": rec["state"], "questions": rec["questions"]}
    if with_label:
        body["labels"] = rec["labels"]
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode(), usedforsecurity=False).hexdigest()


def split_by_paper(rows: list[dict[str, Any]], seed: int, frac: float = HOLDOUT_FRAC) -> set[str]:
    """Held-out paper ids: whole papers, until at least `frac` of the rows are held out."""
    by_paper: dict[str, int] = Counter(r["meta"]["arxiv_id"] for r in rows)
    papers = sorted(by_paper)
    random.Random(seed).shuffle(papers)
    target = math.ceil(len(rows) * frac)
    held, n = set(), 0
    for p in papers:
        if n >= target:
            break
        held.add(p)
        n += by_paper[p]
    return held


def label_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per family: row count, and the label distribution (choice counts, noul mean, score histogram)."""
    out: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[r["meta"]["family"]].append(r)
    for fam, rs in sorted(grouped.items()):
        lab = next(iter(rs[0]["record"]["labels"].values()))
        info: dict[str, Any] = {"rows": len(rs), "type": lab["type"]}
        vals = [next(iter(r["record"]["labels"].values())) for r in rs]
        if lab["type"] == "choice":
            info["choices"] = dict(Counter(v["choice"] for v in vals).most_common())
        elif lab["type"] == "noul":
            info["positive_rate"] = round(sum(v["noul"] for v in vals) / len(vals), 4)
        else:
            info["score_histogram"] = dict(sorted(Counter(v["score"] for v in vals).items()))
        info["label_sources"] = dict(Counter(r["meta"]["label_source"] for r in rs))
        info["nimble_pairs"] = len({r["meta"]["pair_id"] for r in rs if r["meta"]["pair_id"]})
        out[fam] = info
    return out


def curate(seed: int = 20260923, version: str = PACK_VERSION) -> dict[str, Any]:
    io = load_validator()
    corpus = Corpus(
        read_jsonl(SOURCES / "papers.jsonl.gz"),
        read_jsonl(SOURCES / "enrich.jsonl.gz"),
        read_jsonl(SOURCES / "ror.jsonl.gz"),
        read_jsonl(SOURCES / "teacher.jsonl.gz"),
    )
    built = build(corpus, seed)
    rejects: Counter = Counter()
    valid: list[dict[str, Any]] = []
    for r in built:
        text = json.dumps(r["record"]["state"]) + json.dumps(r["record"]["questions"])
        if _DECONTAM.search(text):
            rejects["decontam"] += 1
            continue
        try:
            r["record"] = io.validate_record(r["record"])
        except io.SchemaError as err:
            rejects[f"schema: {str(err)[:60]}"] += 1
            continue
        valid.append(r)

    # Conflicts: the same state and question with different labels teach nothing.
    by_q: dict[str, set[str]] = defaultdict(set)
    for r in valid:
        by_q[_key(r["record"], False)].add(_key(r["record"], True))
    conflicted = {k for k, labs in by_q.items() if len(labs) > 1}
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for r in valid:
        if _key(r["record"], False) in conflicted:
            rejects["conflicting labels"] += 1
            continue
        k = _key(r["record"], True)
        if k in seen:
            rejects["duplicate"] += 1
            continue
        seen.add(k)
        kept.append(r)

    # A Nimble pair missing a side after filtering is no longer contrastive: drop the orphan.
    sides = Counter(r["meta"]["pair_id"] for r in kept if r["meta"]["pair_id"])
    orphans = {p for p, n in sides.items() if n != 2}
    if orphans:
        rejects["nimble orphan"] += sum(1 for r in kept if r["meta"]["pair_id"] in orphans)
        kept = [r for r in kept if r["meta"]["pair_id"] not in orphans]

    held = split_by_paper(kept, seed)
    for r in kept:
        r["meta"]["split"] = "holdout" if r["meta"]["arxiv_id"] in held else "train"
    train = [r for r in kept if r["meta"]["split"] == "train"]
    hold = [r for r in kept if r["meta"]["split"] == "holdout"]

    out = DATA / "packs" / version
    write_jsonl(out / "train.jsonl", (r["record"] for r in train))
    write_jsonl(out / "holdout.jsonl", (r["record"] for r in hold))
    write_jsonl(out / "provenance.jsonl", ({**r["meta"], "consent": CONSENT} for r in kept))

    papers_in = {r["meta"]["arxiv_id"] for r in kept}
    manifest = {
        "pack": version,
        "schema": SCHEMA_ID,
        "seed": seed,
        "consent": CONSENT,
        "rows": {"total": len(kept), "train": len(train), "holdout": len(hold), "holdout_frac": round(len(hold) / max(1, len(kept)), 4)},
        "papers": {"harvested": len(corpus.papers), "in_pack": len(papers_in), "holdout": len(held & papers_in)},
        "types": dict(Counter(next(iter(r["record"]["labels"].values()))["type"] for r in kept)),
        "label_sources": dict(Counter(r["meta"]["label_source"].split(":")[0] for r in kept)),
        "families": label_summary(kept),
        "families_holdout": {f: v["rows"] for f, v in label_summary(hold).items()},
        "nimble_pairs": len({r["meta"]["pair_id"] for r in kept if r["meta"]["pair_id"]}),
        "rejected": dict(rejects),
        "files": {n: {"sha256": sha256_file(out / n), "bytes": (out / n).stat().st_size} for n in ("train.jsonl", "holdout.jsonl", "provenance.jsonl")},
        "sources": {p.name: sha256_file(p) for p in sorted(SOURCES.glob("*.jsonl.gz"))},
        "rules": [
            "states never contain their own answer; see arxiviq_factory/families.py for each family's state",
            "labels from published metadata or recorded outcomes, except label_source llm-teacher (teacher-written, named)",
            "Nimble pairs are mined from real positives and real same-topic hard negatives; no generated twins",
            "holdout is whole papers (>= 20% of rows); pairs never straddle it",
            "consent.champion=false: a HELPER pack, never auto-promoted",
        ],
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (APP_ROOT / "PACK_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Reviewable sample: two train rows per family (one per side for Nimble pairs).
    sample: list[dict[str, Any]] = []
    per: Counter = Counter()
    for r in train:
        f = r["meta"]["family"]
        if per[f] < 2:
            per[f] += 1
            sample.append({"record": r["record"], "provenance": r["meta"]})
    write_jsonl(APP_ROOT / "sample" / "pack_sample.jsonl", sample)
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--version", default=PACK_VERSION)
    args = ap.parse_args(argv)
    m = curate(args.seed, args.version)
    print(json.dumps({k: m[k] for k in ("rows", "papers", "types", "label_sources", "nimble_pairs", "rejected")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

