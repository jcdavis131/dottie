"""Build-time artifact copier — run manually before deploy.

Vendors the orchestrator model artifacts produced elsewhere in the repo into
this package so the serverless bundle is fully self-contained:

* apps/ava-factory/reports/orchestrator/champion_weights.json
    -> lib/weights/champion_weights.json (verbatim)
* apps/ava-factory/reports/orchestrator/eval_report.json
    -> lib/meta/eval_summary.json (champion + gate sections only; per-decile
       risk-calibration detail is dropped to keep the bundle lean)
* apps/ava-factory/data/orchestration/corpus_meta.json
    -> lib/meta/corpus_meta.json (verbatim)

A missing source is not an error: parallel lanes produce these artifacts, and
the package legitimately ships without them (the API then serves
model_loaded:false with heuristic-only responses).

Usage, from this package root:

    python lib/copy_artifacts.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

_LIB = Path(__file__).resolve().parent
# lib -> parents[0]=lib, parents[1]=apps/dottie-harness-api, parents[2]=apps
_AVA = Path(__file__).resolve().parents[2] / "ava-factory"

_MISSING_NOTE = "artifact not present — package will serve model_loaded:false"


def _copy_weights() -> bool:
    src = _AVA / "reports" / "orchestrator" / "champion_weights.json"
    dst = _LIB / "weights" / "champion_weights.json"
    if not src.exists():
        print(f"[copy_artifacts] {src}: {_MISSING_NOTE}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"[copy_artifacts] vendored {src} -> {dst} ({dst.stat().st_size} bytes)")
    return True


def _copy_eval_summary() -> bool:
    src = _AVA / "reports" / "orchestrator" / "eval_report.json"
    dst = _LIB / "meta" / "eval_summary.json"
    if not src.exists():
        print(f"[copy_artifacts] {src}: {_MISSING_NOTE}")
        return False
    doc = json.loads(src.read_text(encoding="utf-8"))
    champion = dict(doc.get("champion") or {})
    # Drop the per-decile risk-calibration detail; the summary keeps only the
    # headline champion metrics and the gate verdict.
    if "risk_calibration" in champion:
        champion.pop("risk_calibration")
        champion["risk_calibration_note"] = (
            "per-decile detail dropped at vendor time; see the full "
            "eval_report.json in apps/ava-factory/reports/orchestrator/"
        )
    summary = {
        "schema_version": doc.get("schema_version"),
        "built_at": doc.get("built_at"),
        "corpus_source": doc.get("corpus_source"),
        "trainer": doc.get("trainer"),
        "champion": champion,
        "gate": doc.get("gate"),
        "notes": doc.get("notes"),
        "vendored_from": "apps/ava-factory/reports/orchestrator/eval_report.json",
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[copy_artifacts] vendored eval summary {src} -> {dst}")
    return True


def _copy_corpus_meta() -> bool:
    src = _AVA / "data" / "orchestration" / "corpus_meta.json"
    dst = _LIB / "meta" / "corpus_meta.json"
    if not src.exists():
        print(f"[copy_artifacts] {src}: {_MISSING_NOTE}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"[copy_artifacts] vendored {src} -> {dst}")
    return True


def main() -> int:
    copied = [_copy_weights(), _copy_eval_summary(), _copy_corpus_meta()]
    n = sum(copied)
    print(f"[copy_artifacts] {n}/3 artifacts vendored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
