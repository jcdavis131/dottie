# Solo personal project, no connection to employer, built with public/free-tier only
"""Replay diagnose_failure over every failed validation attempt in the ledger COPY.

    apps/dottie> .venv/Scripts/python.exe scripts/replay_hint_coverage.py

Every failed attempt in ``implementation.validation.history`` was a real
correction-pass prompt, so each one is a hint opportunity. This script replays
``dottie.research.validate.diagnose_failure`` as currently on disk over all of
them and prints coverage (fraction receiving a non-empty repair hint). Run it
before AND after editing ``_HINTS`` to measure what a change actually buys.
Mines history, not the ``failure`` column — that column truncates (~567 chars)
and usually cuts off before the terminal exception line.

SAFETY CONTRACT: the LIVE ledger is NEVER opened (the research daemon holds it
and writes it). This script reads only the file COPY at
``tasks/artifacts/ledger_copy.sqlite3``, opened read-only; it never creates or
refreshes the copy — that is retro_flag_ledger.py's job.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

APP = Path(__file__).resolve().parents[1]  # apps/dottie
REPO = APP.parents[1]  # the dottie repo root
COPY_DB = REPO / "tasks" / "artifacts" / "ledger_copy.sqlite3"

sys.path.insert(0, str(APP))  # importable when run from anywhere, venv install or not

from dottie.research.validate import diagnose_failure


def iter_failed_attempts(db: Path) -> Iterator[tuple[str, str, str]]:
    """Yield (experiment_id, level, detail) for every failed history attempt."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, implementation FROM experiments "
            "WHERE implementation IS NOT NULL ORDER BY created_ts"
        ).fetchall()
        for r in rows:
            impl = json.loads(r["implementation"])
            history = (impl.get("validation") or {}).get("history") or []
            for h in history:
                if h.get("ok") is False and "detail" in h:
                    yield (
                        r["id"],
                        str(h.get("level") or "?"),
                        str(h.get("detail") or ""),
                    )
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="hint coverage over the ledger copy's failed validation attempts"
    )
    ap.add_argument(
        "--db",
        type=Path,
        default=COPY_DB,
        help="ledger COPY to replay (never point this at the live db)",
    )
    args = ap.parse_args()
    if not args.db.exists():
        raise SystemExit(
            f"no ledger copy at {args.db} — create it with a plain file "
            "copy first (see scripts/retro_flag_ledger.py)"
        )
    total = 0
    hinted = 0
    per_level: Counter = Counter()
    per_level_hinted: Counter = Counter()
    per_hint: Counter = Counter()
    for _exp_id, level, detail in iter_failed_attempts(args.db):
        total += 1
        per_level[level] += 1
        hint = diagnose_failure(level, detail)
        if hint:
            hinted += 1
            per_level_hinted[level] += 1
            # Every hint text opens with an ALL-CAPS class label before ':' —
            # the distribution shows targeted vs generic, which coverage % hides.
            per_hint[hint.split(":", 1)[0]] += 1
    if not total:
        raise SystemExit("no failed attempts found — wrong or empty copy?")
    print(f"db: {args.db}")
    print(f"failed attempts: {total}")
    print(f"hinted: {hinted}")
    print(f"coverage: {100.0 * hinted / total:.1f}%")
    print("per level:")
    for lvl in sorted(per_level):
        n, h = per_level[lvl], per_level_hinted[lvl]
        print(f"  {lvl:20s} {h:4d}/{n:<4d} ({100.0 * h / n:.1f}%)")
    print("per hint class:")
    for label, n in per_hint.most_common():
        print(f"  {label:28s} {n:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
