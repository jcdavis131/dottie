#!/usr/bin/env python3
"""Count L3 actions / tiers / champion=false / holdout ≥20% for a pack_v2 staging dir.

Default staging is the nugatron registry path. Pass --staging for the repo-mirror
smoke or any other checkout. Does not kick FT or touch LIVE/champion.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_STAGING = Path(r"C:\Users\jcdav\workspace\dottie-os\registry\datasets\staging")


def smoke(staging: Path) -> dict:
    pack = staging / "curated_pack_v2.jsonl"
    hold = staging / "curated_pack_v2_holdout.jsonl"
    train = staging / "curated_pack_v2_train.jsonl"
    summary = staging / "curated_pack_v2_summary.json"
    print("exists", pack.exists(), hold.exists(), train.exists(), summary.exists())
    actions = Counter()
    tiers = Counter()
    sources = Counter()
    n = 0
    champ = 0
    multi = 0
    with pack.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            n += 1
            tiers[str(o.get("tier"))] += 1
            src = o.get("source")
            if isinstance(src, dict):
                sources[str(src.get("hf") or "?")] += 1
            if (o.get("consent") or {}).get("champion") is True:
                champ += 1
            if len(o.get("questions") or {}) >= 3:
                multi += 1
            lab = (o.get("labels") or {}).get("action") or {}
            if lab.get("choice"):
                actions[str(lab["choice"])] += 1
    hold_rows = 0
    if hold.exists():
        with hold.open(encoding="utf-8") as hf:
            hold_rows = sum(1 for _ in hf)
    train_rows = 0
    if train.exists():
        with train.open(encoding="utf-8") as tf:
            train_rows = sum(1 for _ in tf)
    report = {
        "total": n,
        "tiers": dict(tiers),
        "sources": dict(sources),
        "l3_actions": dict(actions),
        "multi_head": multi,
        "champion_true": champ,
        "holdout_rows": hold_rows,
        "train_rows": train_rows,
    }
    print(json.dumps(report, indent=2))
    assert champ == 0, "champion must stay false for this pack"
    assert hold.exists() and train.exists() and pack.exists()
    if n:
        assert (hold_rows / n) >= 0.20
    print("SMOKE_OK")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging",
        type=Path,
        default=DEFAULT_STAGING,
        help="Directory with curated_pack_v2{,_train,_holdout}.jsonl",
    )
    args = ap.parse_args(argv)
    smoke(args.staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
