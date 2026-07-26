# Solo personal project, no connection to employer, built with public/free-tier only
"""Retro-flag ledger promotions that rest on within-run-SEM-only evidence. REPORT ONLY.

    apps/dottie> .venv/Scripts/python.exe scripts/retro_flag_ledger.py

Operator order B0 made paired-seed (or equivalent multi-seed) evidence a HARD promotion
gate going forward. This script applies the same standard BACKWARD: every ``sota`` row
and the current baseline are classified by what their significance actually rested on,
and everything that cleared the bar on a single run's batch-to-batch spread alone —
the §5.3.R93 failure class, which produced all three historical "sota" artifacts — is
flagged in ``tasks/artifacts/ledger_retroflag.md``.

SAFETY CONTRACT (the reason this script exists at all):
  * The LIVE ledger is NEVER opened. The research daemon holds it and writes it; opening
    it from here — even read-only — negotiates WAL/locks with a live writer. This script
    reads only the file COPY at ``tasks/artifacts/ledger_copy.sqlite3``, creating it with
    a plain file copy (db + -wal/-shm siblings) only when it is absent.
  * Nothing is written back to ANY ledger: the copy is opened for SELECTs only. (SQLite
    may replay the copied WAL into the COPY on open — that touches only the artifact.)
  * A file copy of a database under a live writer is a best-effort snapshot, not a
    backup-API checkpoint; the report says which file it read and when.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]  # apps/dottie
REPO = APP.parents[1]  # the dottie repo root
LIVE_DB = APP / "data" / "research" / "ledger.sqlite3"  # NEVER opened, only file-copied
COPY_DB = REPO / "tasks" / "artifacts" / "ledger_copy.sqlite3"
OUT_MD = REPO / "tasks" / "artifacts" / "ledger_retroflag.md"

#: Mirrors evaluate._WITHIN_RUN_SERIES. Duplicated as a literal ON PURPOSE: this script
#: judges HISTORICAL rows, so its criteria must not drift when the live module's set
#: changes — a rerun of the same report over the same copy must say the same thing.
WITHIN_RUN_SERIES = ("eval_ce_per_batch", "eval_losses")


def ensure_copy(live: Path, copy: Path) -> bool:
    """Create the copy (db + WAL siblings) if absent. Returns True when copied now."""
    if copy.exists():
        return False
    if not live.exists():
        raise SystemExit(f"no copy at {copy} and no live ledger at {live} to copy from")
    copy.parent.mkdir(parents=True, exist_ok=True)
    # Siblings first, main file last: recent frames live in -wal, and sqlite replays it
    # against the main file on open — copying main-first could pair an older main file
    # with a newer WAL. Still best-effort under a live writer; stated in the report.
    for suffix in ("-wal", "-shm"):
        side = live.with_name(live.name + suffix)
        if side.exists():
            shutil.copyfile(side, copy.with_name(copy.name + suffix))
    shutil.copyfile(live, copy)
    return True


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def classify(verdict: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, str]:
    """(evidence_class, detail) for one experiment's promotion evidence.

    Classes: ``cross_seed`` (spread includes run-to-run variance — NOT flagged),
    ``within_run_only`` (the R93 class — FLAGGED), ``no_series`` (promoted with no
    spread at all, pre-significance-gate — FLAGGED, it is even weaker).

    Decomposed honestly: trust the verdict's structured ``sem_series`` when present;
    verdicts predating that field fall back to what the train_metrics actually recorded,
    which is the same series the evaluator of that era would have used."""
    series = verdict.get("sem_series")
    if series is not None:
        n = verdict.get("sem_n")
        if series in WITHIN_RUN_SERIES:
            return "within_run_only", f"eval_verdict.sem_series={series!r} (n={n})"
        return "cross_seed", f"eval_verdict.sem_series={series!r} (n={n})"
    ps = metrics.get("per_seed")
    if isinstance(ps, list) and len(ps) >= 2:
        return (
            "cross_seed",
            f"train_metrics.per_seed (n={len(ps)}; verdict predates sem_series)",
        )
    for key in WITHIN_RUN_SERIES:
        raw = metrics.get(key)
        if isinstance(raw, list) and len(raw) >= 2:
            return "within_run_only", (
                f"train_metrics.{key} (n={len(raw)}) and NO per_seed; "
                "verdict predates sem_series"
            )
    return (
        "no_series",
        "no spread series recorded anywhere — never tested against noise",
    )


def _utc(ts: float | None) -> str:
    if not isinstance(ts, (int, float)):
        return "n/a"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(ts))


def build_report(copy: Path, *, copied_now: bool) -> str:
    conn = sqlite3.connect(copy)  # the COPY — SELECTs only, see module doc
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, state, updated_ts, hypothesis, train_metrics, eval_verdict "
            "FROM experiments WHERE state = 'sota' ORDER BY updated_ts ASC"
        ).fetchall()
        b = conn.execute("SELECT * FROM baseline WHERE singleton = 1").fetchone()
    finally:
        conn.close()

    flagged, clean = [], []
    by_id: dict[str, tuple[str, str]] = {}
    for row in rows:
        verdict = _loads(row["eval_verdict"])
        metrics = _loads(row["train_metrics"])
        cls, detail = classify(verdict, metrics)
        by_id[row["id"]] = (cls, detail)
        item = {
            "id": row["id"],
            "name": str(_loads(row["hypothesis"]).get("hypothesis_name") or row["id"]),
            "updated": _utc(row["updated_ts"]),
            "metric": verdict.get("metric"),
            "value": verdict.get("new_value"),
            "delta": verdict.get("delta"),
            "class": cls,
            "detail": detail,
        }
        (clean if cls == "cross_seed" else flagged).append(item)

    lines = [
        "# Ledger retro-flag — promotions resting on within-run-SEM-only evidence",
        "",
        f"- generated: {_utc(time.time())}  ·  report ONLY, no ledger was mutated",
        f"- source: ledger COPY `{copy}`"
        + (
            " (copied from the live db this run)"
            if copied_now
            else " (pre-existing copy; NOT refreshed — delete it and rerun to re-snapshot)"
        ),
        f"- live db (never opened by this script): `{LIVE_DB}`",
        "",
        "Criterion (operator order B0, applied retroactively): a promotion is flagged when",
        "its significance rested on a single run's batch-to-batch spread"
        f" ({', '.join(f'`{s}`' for s in WITHIN_RUN_SERIES)})",
        "or on no spread series at all — evidence that is blind to run-to-run variance.",
        "§5.3.R93 measured that variance at 0.343 across seeds for the unmodified model,",
        "4.5× the best claimed 'effect'; a candidate cleared 4.4 within-run SEM and lost",
        "at all three seeds. Flagged rows are NOT evidence of improvement until their",
        "promotion bundle's `ab_nano.py` (paired seeds) says so.",
        "",
        f"## Flagged promotions ({len(flagged)})",
        "",
    ]
    if flagged:
        lines += [
            "| id | name | promoted (UTC) | metric | value | delta | evidence |",
            "|---|---|---|---|---|---|---|",
        ]
        for it in flagged:
            lines.append(
                f"| `{it['id']}` | {it['name']} | {it['updated']} | {it['metric'] or 'n/a'} "
                f"| {it['value'] if it['value'] is not None else 'n/a'} "
                f"| {it['delta'] if it['delta'] is not None else 'n/a'} "
                f"| **{it['class']}** — {it['detail']} |"
            )
    else:
        lines.append("(none — every sota row carries cross-seed evidence)")

    lines += [
        "",
        f"## Promotions with cross-seed evidence ({len(clean)})",
        "",
        "Not flagged by THIS criterion — which classifies evidence class only. A row",
        "here can still be an artifact for other reasons (hand-seeded baseline it was",
        "measured against, capacity confound); see the promotion bundle's caveat block.",
        "",
    ]
    if clean:
        for it in clean:
            lines.append(
                f"- `{it['id']}` {it['name']} ({it['updated']}) — {it['detail']}"
            )
    else:
        lines.append("(none)")

    lines += ["", "## Current baseline", ""]
    if b is None:
        lines.append("(no baseline row in this copy)")
    else:
        keys = b.keys()
        exp_id = b["experiment_id"]
        lines.append(
            f"- `{b['metric_name']}` = {b['metric_value']}  ·  set by: "
            f"{'`' + exp_id + '`' if exp_id else '(no experiment — seeded/calibrated)'}"
        )
        notes = (b["notes"] or "").strip()
        if notes:
            lines.append(f"- notes: {notes[:300]}")
        base_ps = b["per_seed"] if "per_seed" in keys else None
        if exp_id and exp_id in by_id:
            cls, detail = by_id[exp_id]
            mark = (
                "**FLAGGED — the current bar itself rests on within-run-SEM-only "
                "evidence**"
                if cls != "cross_seed"
                else "cross-seed evidence"
            )
            lines.append(f"- evidence of the run that set it: {mark} ({detail})")
        elif exp_id:
            lines.append(
                f"- **FLAGGED — set by `{exp_id}`, which is not a sota row in this "
                "copy; its evidence cannot be classified from here**"
            )
        elif notes.lower().startswith("measured baseline calibration"):
            lines.append(
                "- calibrated baseline"
                + (
                    f"; cross-seed per_seed recorded ({base_ps})"
                    if base_ps
                    else " — single-seed (no cross-seed spread recorded)"
                )
            )
        else:
            lines.append(
                "- hand-seeded placeholder — no measurement behind it at all "
                "(see `_baseline_provenance`)"
            )

    lines += [
        "",
        f"Summary: {len(flagged)} of {len(flagged) + len(clean)} sota promotions "
        "flagged.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument(
        "--copy",
        type=Path,
        default=COPY_DB,
        help="ledger COPY to read (created from --live only when absent)",
    )
    ap.add_argument(
        "--live",
        type=Path,
        default=LIVE_DB,
        help="live ledger to file-copy IF the copy is absent (never opened)",
    )
    ap.add_argument(
        "--out", type=Path, default=OUT_MD, help="markdown report destination"
    )
    args = ap.parse_args()

    copied_now = ensure_copy(args.live, args.copy)
    report = build_report(args.copy, copied_now=copied_now)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"{'copied live -> ' if copied_now else 'reused existing '}{args.copy}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
