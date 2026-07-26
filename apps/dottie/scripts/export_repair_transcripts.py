# Solo personal project, no connection to employer, built with public/free-tier only
"""Export failure->hint->corrected-code repair transcripts from a research-ledger COPY.

Data-flywheel corpus PROPOSAL (L4): nothing auto-ingests this output; it is an
audited artifact. The honesty constraints are structural, not aspirational:

* Point --db at a COPY of the ledger, never the live file — the research daemon
  holds apps/dottie/data/research/ledger.sqlite3 open and must not be raced.
* Rows come ONLY from experiments whose validation history recovered (at least
  one failed attempt followed by an ok attempt). Those are the only experiments
  where the ledger contains code KNOWN to fix the recorded failure; the 70
  never-recovered experiments yield no pair and are deliberately absent.
* validate.py's history persists attempt/ok/level/status/detail but NOT the
  per-attempt candidate code, so `corrected_code` is the experiment's FINAL
  validated code — identical across all rows of one experiment (dedup on
  experiment_id) and marked corrected_code_role=final_validated_code. No
  per-attempt diff is fabricated.
* `repair_hint` is diagnose_failure() recomputed with TODAY'S validate.py. The
  hints shipped 2026-07-22, mined from this same ledger; history rows predating
  that never showed the corrector any hint. hint_source says so on every row.

Run (from apps/dottie):
    .venv/Scripts/python.exe scripts/export_repair_transcripts.py ^
        --db ..\\..\\tasks\\artifacts\\ledger_copy.sqlite3 ^
        --out ..\\..\\tasks\\artifacts\\corpus_proposals\\repair_transcripts.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_APP_ROOT = Path(__file__).resolve().parents[1]  # apps/dottie
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from dottie.research.validate import diagnose_failure
from dottie.trajectory_schema import from_repair_rows, to_sft_records

HINT_SOURCE = (
    "diagnose_failure recomputed at export time; hints shipped "
    "2026-07-22, so history rows from before that never showed the "
    "corrector any hint"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_rows(db_path: Path) -> list[dict[str, Any]]:
    """One row per failed validation attempt of every RECOVERED experiment."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        exps = con.execute(
            "SELECT id, state, hypothesis, implementation FROM experiments "
            "WHERE implementation IS NOT NULL ORDER BY created_ts, id"
        ).fetchall()
    finally:
        con.close()

    rows: list[dict[str, Any]] = []
    for exp in exps:
        impl = json.loads(exp["implementation"])
        hyp = json.loads(exp["hypothesis"]) if exp["hypothesis"] else {}
        hist = (impl.get("validation") or {}).get("history") or []
        fails = [h for h in hist if h.get("ok") is False and "detail" in h]
        oks = [h for h in hist if h.get("ok") is True]
        code = impl.get("code")
        if not (fails and oks and code):
            continue  # no recovery -> the ledger holds no code that fixes these failures
        validated_detail = oks[-1].get("detail") or ""
        for seq, h in enumerate(fails):
            detail = h.get("detail") or ""
            hint = diagnose_failure(h.get("level") or "", detail)
            rows.append(
                {
                    "experiment_id": exp["id"],
                    "experiment_state": exp["state"],
                    "hypothesis_name": hyp.get("hypothesis_name"),
                    "module_name": impl.get("module_name"),
                    "dry_run_contract": impl.get("dry_run"),
                    "attempt": h.get("attempt"),
                    "failure_seq": seq,
                    "n_failed_attempts": len(fails),
                    "level": h.get("level"),
                    "status": h.get("status"),
                    "failure_detail": detail,  # verbatim (trainer truncated at 2000)
                    "repair_hint": hint or None,
                    "hint_source": HINT_SOURCE,
                    "corrected_code": code,
                    "corrected_code_role": "final_validated_code",
                    "validated_detail": validated_detail,
                }
            )
    return rows


def sft_records_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Route the repair rows through the unified trajectory schema.

    Groups by experiment_id, maps each group to a Trajectory (from_repair_rows),
    and flattens with to_sft_records — the SAME learning consumer the codeact and
    validation sources use, so downstream training code reads one shape regardless
    of rollout. The rich native rows (--out) still carry the repair-specific
    provenance (hint_source, dry_run_contract) that the generic schema drops; this
    is the additional unified view, not a replacement.
    """
    by_exp: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        by_exp.setdefault(r["experiment_id"], []).append(r)
    out: list[dict[str, Any]] = []
    for exp_rows in by_exp.values():
        out.extend(to_sft_records(from_repair_rows(exp_rows)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--db", type=Path, required=True, help="ledger COPY (never the live daemon DB)"
    )
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="rich native repair rows (repair-specific provenance)",
    )
    ap.add_argument(
        "--sft-out",
        type=Path,
        default=None,
        help="ALSO emit unified trajectory-schema SFT records "
        "(dottie.trajectory_schema.to_sft_records) — the same "
        "shape codeact/validation sources produce",
    )
    args = ap.parse_args(argv)

    rows = extract_rows(args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    exps = sorted({r["experiment_id"] for r in rows})
    levels = Counter(r["level"] for r in rows)
    hinted = sum(1 for r in rows if r["repair_hint"])
    print(f"db: {args.db} sha256={_sha256(args.db)}")
    print(
        f"wrote {args.out}: {len(rows)} rows from {len(exps)} recovered "
        f"experiments {exps}"
    )
    print(
        f"levels: {dict(levels)} | rows with a (recomputed) hint: {hinted}/{len(rows)}"
    )

    if args.sft_out is not None:
        sft = sft_records_from_rows(rows)
        args.sft_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.sft_out, "w", encoding="utf-8", newline="\n") as f:
            for r in sft:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(
            f"wrote {args.sft_out}: {len(sft)} unified SFT records "
            f"(trajectory_schema.to_sft_records)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
