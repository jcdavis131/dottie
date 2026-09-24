"""Stage 3: curate the gauge-days into a training-ready pack.

  1. build every (gauge, day) row from the committed snapshots (features.py)
  2. time split: the holdout is the latest HOLDOUT_DAYS days of decision
     dates; the day before it is an embargo (its label window touches the
     holdout), everything earlier is train. No gauge-day is in both.
  3. downsample the easy negative mass in TRAIN only: a row with both noul
     labels false, flow below the 90th percentile for the date and of all
     days, and no warning over the gauge in the last 30 days is kept with
     probability EASY_KEEP (a seeded hash of site and date). Kept easy rows
     carry sample_weight 1 / EASY_KEEP in provenance.jsonl, so weighted counts
     recover the natural rates. The holdout keeps the natural distribution.
  4. render strict jev records, decontaminate with the dottie-os bench regex,
     validate with the frozen jev-v0 validator (rejects counted, never repaired),
     drop duplicates and both sides of any conflicting duplicate
  5. write data/packs/<version>/{train,holdout,provenance}.jsonl and MANIFEST.json
     (copied to PACK_MANIFEST.json here) and sample/pack_sample.jsonl.

Train rows are shuffled with the seed (the jev-v0 trainer walks its file in
order). Nothing here trains or promotes: consent.champion is false and the
labels are recorded futures (provenance tier outcome-real).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from . import PACK_VERSION, PROVENANCE_TIER, SCHEMA_ID
from .common import APP_ROOT, DATA, SOURCES, sha256_file, stable_unit, write_jsonl
from .features import CHANGE_LEVELS, ROW_START, Corpus, build_rows
from .records import to_record

REPO = APP_ROOT.parent.parent
JEV_IO = REPO / "apps" / "jev-v0" / "decision_io.py"
HOLDOUT_DAYS = 365
EMBARGO_DAYS = 1
EASY_KEEP = 0.10
# Easy: flow not 'much above normal' (under the 90th percentile for the date and of all days).
EASY_BELOW_PCT = 90
SEED = 20260923
CONSENT = {"capture_training": True, "public_sources": True, "champion": False}
LABEL_SOURCES = {"high_next": "usgs-nwis-dv", "warn_next": "iem-vtec-sbw", "flow_change": "usgs-nwis-dv"}

# Same bench-contamination guard as apps/dottie-os and apps/arxiviq-factory.
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


def split_dates(last_day: date, holdout_days: int = HOLDOUT_DAYS, embargo_days: int = EMBARGO_DAYS) -> tuple[date, date]:
    """(first holdout day, last train day)."""
    first_hold = last_day - timedelta(days=holdout_days - 1)
    return first_hold, first_hold - timedelta(days=embargo_days + 1)


def assign_split(d: str, first_hold: date, last_train: date) -> str | None:
    day = date.fromisoformat(d)
    if day >= first_hold:
        return "holdout"
    if day <= last_train:
        return "train"
    return None


def is_easy_negative(row: dict[str, Any]) -> bool:
    f, lab = row["features"], row["labels"]
    return (not lab["high_next"] and not lab["warn_next"] and f["pct_date"] < EASY_BELOW_PCT
            and (f["pct_all"] is None or f["pct_all"] < EASY_BELOW_PCT) and not f["warn_active"] and f["warn_gauge_30d"] == 0)


def _key(rec: dict[str, Any], with_label: bool) -> str:
    body = {"state": rec["state"], "questions": rec["questions"]}
    if with_label:
        body["labels"] = rec["labels"]
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode(), usedforsecurity=False).hexdigest()


def assemble(corpus: Corpus, seed: int = SEED, easy_keep: float = EASY_KEEP, *, row_start: date = ROW_START,
             holdout_days: int = HOLDOUT_DAYS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rows kept for the pack, each {"row", "record", "meta"}, plus curation counts."""
    io = load_validator()
    gauges = {g["site"]: g for g in corpus.gauges}
    rows = build_rows(corpus, row_start)
    last_day = date.fromisoformat(max(r["date"] for r in rows))
    first_hold, last_train = split_dates(last_day, holdout_days)
    rejects: Counter = Counter()
    info: dict[str, Any] = {"candidate_rows": len(rows), "first_holdout_day": first_hold.isoformat(),
                            "last_train_day": last_train.isoformat(), "last_day": last_day.isoformat(),
                            "easy_negatives": Counter()}
    valid: list[dict[str, Any]] = []
    for r in rows:
        split = assign_split(r["date"], first_hold, last_train)
        if split is None:
            rejects["embargo (label window touches the holdout)"] += 1
            continue
        easy = is_easy_negative(r)
        weight = 1.0
        if easy:
            info["easy_negatives"][split] += 1
            if split == "train":
                if stable_unit(str(seed), r["site"], r["date"]) >= easy_keep:
                    rejects["easy negative downsampled (train)"] += 1
                    continue
                weight = round(1.0 / easy_keep, 4)
        rec = to_record(gauges[r["site"]], r)
        if _DECONTAM.search(json.dumps(rec["state"]) + json.dumps(rec["questions"])):
            rejects["decontam"] += 1
            continue
        try:
            rec = io.validate_record(rec)
        except io.SchemaError as err:
            rejects[f"schema: {str(err)[:60]}"] += 1
            continue
        g = gauges[r["site"]]
        meta = {
            "id": rec["id"], "site": r["site"], "date": r["date"], "decision_utc": r["decision_utc"],
            "wfo": g["wfo"], "state": g["state"], "split": split, "easy_negative": easy, "sample_weight": weight,
            "provenance": PROVENANCE_TIER, "label_sources": LABEL_SOURCES,
        }
        valid.append({"row": r, "record": rec, "meta": meta})

    by_q: dict[str, set[str]] = defaultdict(set)
    for v in valid:
        by_q[_key(v["record"], False)].add(_key(v["record"], True))
    conflicted = {k for k, labs in by_q.items() if len(labs) > 1}
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for v in valid:
        if _key(v["record"], False) in conflicted:
            rejects["conflicting labels"] += 1
            continue
        k = _key(v["record"], True)
        if k in seen:
            rejects["duplicate"] += 1
            continue
        seen.add(k)
        kept.append(v)
    info["rejected"] = dict(rejects)
    info["easy_negatives"] = dict(info["easy_negatives"])
    return kept, info


def balance(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Class balance per label: raw counts, and weighted rates (the natural distribution before downsampling)."""
    if not items:
        return {}
    w = [v["meta"]["sample_weight"] for v in items]
    tw = sum(w)
    out: dict[str, Any] = {"rows": len(items), "weighted_rows": round(tw, 1)}
    for lab in ("high_next", "warn_next"):
        pos = [v["row"]["labels"][lab] for v in items]
        out[lab] = {"positives": sum(pos), "positive_rate": round(sum(pos) / len(items), 4),
                    "natural_rate": round(sum(wi for wi, p in zip(w, pos, strict=True) if p) / tw, 4)}
    buckets = Counter(v["row"]["labels"]["change_bucket"] for v in items)
    out["flow_change"] = {CHANGE_LEVELS[k]: buckets.get(k, 0) for k in range(len(CHANGE_LEVELS))}
    return out


def curate(seed: int = SEED, version: str = PACK_VERSION) -> dict[str, Any]:
    corpus = Corpus.load()
    kept, info = assemble(corpus, seed)
    train = [v for v in kept if v["meta"]["split"] == "train"]
    hold = [v for v in kept if v["meta"]["split"] == "holdout"]
    random.Random(seed).shuffle(train)
    if not train or not hold:
        raise SystemExit("split left train or holdout empty")

    out = DATA / "packs" / version
    write_jsonl(out / "train.jsonl", (v["record"] for v in train))
    write_jsonl(out / "holdout.jsonl", (v["record"] for v in hold))
    write_jsonl(out / "provenance.jsonl", ({**v["meta"], "consent": CONSENT} for v in kept))
    stats = json.loads((SOURCES / "harvest_stats.json").read_text(encoding="utf-8"))
    manifest = {
        "pack": version,
        "schema": SCHEMA_ID,
        "seed": seed,
        "provenance": PROVENANCE_TIER,
        "consent": CONSENT,
        "rows": {"total": len(kept), "train": len(train), "holdout": len(hold),
                 "holdout_frac": round(len(hold) / len(kept), 4), "candidates": info["candidate_rows"]},
        "split": {"kind": "time", "train_days": [min(v["meta"]["date"] for v in train), info["last_train_day"]],
                  "embargo_days": EMBARGO_DAYS, "holdout_days": [info["first_holdout_day"], info["last_day"]]},
        "downsampling": {"easy_keep": EASY_KEEP, "applies_to": "train only", "easy_negatives_before": info["easy_negatives"],
                         "rule": f"both noul labels false, pct_date < {EASY_BELOW_PCT}, pct_all < {EASY_BELOW_PCT}, no warning over the gauge in 30 days"},
        "balance": {"train": balance(train), "holdout": balance(hold)},
        "gauges": {"in_pack": len({v["meta"]["site"] for v in kept}), "offices": sorted({v["meta"]["wfo"] for v in kept}),
                   "states": sorted({v["meta"]["state"] for v in kept}), "harvest_end": stats["end"]},
        "questions": {"high_next": "noul", "warn_next": "noul", "flow_change": "score (5 levels)"},
        "label_sources": LABEL_SOURCES,
        "rejected": info["rejected"],
        "files": {n: {"sha256": sha256_file(out / n), "bytes": (out / n).stat().st_size} for n in ("train.jsonl", "holdout.jsonl", "provenance.jsonl")},
        "sources": {p.name: sha256_file(p) for p in sorted(SOURCES.glob("*.jsonl.gz"))},
        "rules": [
            "labels are recorded futures (USGS daily values on t+1, IEM VTEC warning polygons issued after T): provenance tier outcome-real",
            "features use only data dated <= t and warnings issued <= T (end of local standard day t); percentiles from days strictly before t",
            "holdout is the latest 365 days; a one-day embargo keeps every train label window out of it",
            "easy negatives are downsampled in train only; sample_weight in provenance.jsonl restores natural rates",
            "may train candidates; eval on the time-split holdout; consent.champion=false: nothing auto-promotes",
        ],
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (APP_ROOT / "PACK_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Reviewable sample: one of each (split, high_next, warn_next) combination that exists, then a few easy rows.
    sample: list[dict[str, Any]] = []
    per: Counter = Counter()
    for v in sorted(kept, key=lambda v: (v["meta"]["date"], v["meta"]["site"])):
        lab = v["row"]["labels"]
        k = (v["meta"]["split"], lab["high_next"], lab["warn_next"])
        if per[k] < 2:
            per[k] += 1
            sample.append({"record": v["record"], "provenance": v["meta"]})
    write_jsonl(APP_ROOT / "sample" / "pack_sample.jsonl", sample)
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--version", default=PACK_VERSION)
    args = ap.parse_args(argv)
    m = curate(args.seed, args.version)
    print(json.dumps({k: m[k] for k in ("rows", "split", "balance", "rejected")}, indent=2))
    return 0
