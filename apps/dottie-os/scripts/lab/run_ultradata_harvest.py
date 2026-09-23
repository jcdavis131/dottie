"""Lean jcd-pc UltraData harvest. Memory-conscious caps.

Repo-mirror layout: this file lives at apps/dottie-os/scripts/lab/.
Sidecar imports resolve from apps/dottie-os. Staging/outbox stay under the
app tree (gitignored). Does not kick FT or touch LIVE/champion.
"""
from __future__ import annotations

import gc
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CANDIDATES = (
    _HERE.parents[1],  # apps/dottie-os (repo mirror)
    _HERE / "factory",  # original jcd-pc layout if the script is copied there
    _HERE,
)
APP_ROOT = next(
    (p for p in _CANDIDATES if (p / "sidecar" / "curation" / "ultradata_curriculum.py").is_file()),
    _HERE.parents[1],
)
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Path insert is required: sidecar is a namespace under APP_ROOT, not this file.
from sidecar.curation.ultradata_curriculum import (  # noqa: E402
    curate_ultradata_agent,
    curate_ultradata_code,
    curate_ultradata_math,
    holdout_split,
    summarize,
    write_jsonl,
)


def main() -> int:
    staging = APP_ROOT / "staging"
    outbox = APP_ROOT / "hop" / "outbox"
    staging.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)

    agent_n, code_n, math_n = 40, 40, 30
    print(f"lean harvest start agent={agent_n} code={code_n} math={math_n}", flush=True)

    rows = []
    print("P1 agent...", flush=True)
    rows.extend(curate_ultradata_agent(agent_n))
    gc.collect()
    print(f"  agent rows so far={len(rows)}", flush=True)

    print("P2 code...", flush=True)
    before = len(rows)
    rows.extend(curate_ultradata_code(code_n))
    gc.collect()
    print(f"  code +={len(rows) - before}", flush=True)

    print("P3 math...", flush=True)
    before = len(rows)
    rows.extend(curate_ultradata_math(math_n))
    gc.collect()
    print(f"  math +={len(rows) - before} total={len(rows)}", flush=True)

    train, holdout = holdout_split(rows, frac=0.20, seed=20260921)
    write_jsonl(staging / "curated_pack_v2.jsonl", rows)
    write_jsonl(staging / "curated_pack_v2_train.jsonl", train)
    write_jsonl(staging / "curated_pack_v2_holdout.jsonl", holdout)
    summary = {
        "counts": summarize(rows),
        "train_counts": summarize(train),
        "holdout_counts": summarize(holdout),
        "holdout_frac": len(holdout) / max(len(rows), 1),
        "caps": {"agent": agent_n, "code": code_n, "math": math_n, "v1_carried": 0},
        "notes": ["lean jcd-pc harvest", "champion/LIVE untouched", "no FT"],
    }
    (staging / "curated_pack_v2_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = outbox / f"ultradata_harvest_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "curated_pack_v2.jsonl",
        "curated_pack_v2_train.jsonl",
        "curated_pack_v2_holdout.jsonl",
        "curated_pack_v2_summary.json",
    ):
        src = staging / name
        if src.exists():
            dest.joinpath(name).write_bytes(src.read_bytes())
    print(f"wrote {dest} total={len(rows)}", flush=True)
    print(json.dumps({"ok": True, "dest": str(dest), "rows": len(rows)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
