# Solo personal project, no connection to employer, built with public/free-tier only
"""Build the knowledge graph from the real local substrate. Read-only ingest.

Usage (from apps/dottie, its venv):

    python -m dottie.kg.build                # defaults: everything below
    python -m dottie.kg.build --out data/kg/graph.sqlite3

Defaults (all read-only; every one absent-tolerant):
    ledger        tasks/artifacts/ledger_copy.sqlite3      (the SAFE COPY)
    metrics       apps/ava-factory/runs/cpu_pilot/reports/{base,agentic}/metrics_nano.jsonl
    live status   apps/ava-factory/reports/dottie_live_status.json
    steer audit   apps/bluehenre/data/steer_audit.jsonl
    incidents     dottie/kg/data/incidents_seed.json (+ doc anchor re-verification)

SAFETY: the LIVE research ledger (apps/dottie/data/research/ledger.sqlite3)
is REFUSED by path identity before any file is opened — a research daemon
owns that file and even a read-only open can interfere with its WAL. Point
--ledger at a copy, never at the live file.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dottie.kg import ingest
from dottie.kg.store import GraphStore

_APP_ROOT = Path(__file__).resolve().parents[2]        # .../apps/dottie
_REPO_ROOT = Path(__file__).resolve().parents[4]       # monorepo root
LIVE_LEDGER = _APP_ROOT / "data" / "research" / "ledger.sqlite3"

DEFAULT_OUT = _APP_ROOT / "data" / "kg" / "graph.sqlite3"
DEFAULT_LEDGER = _REPO_ROOT / "tasks" / "artifacts" / "ledger_copy.sqlite3"
DEFAULT_METRICS = [
    _REPO_ROOT / "apps" / "ava-factory" / "runs" / "cpu_pilot" / "reports"
    / "base" / "metrics_nano.jsonl",
    _REPO_ROOT / "apps" / "ava-factory" / "runs" / "cpu_pilot" / "reports"
    / "agentic" / "metrics_nano.jsonl",
]
DEFAULT_LIVE_STATUS = (_REPO_ROOT / "apps" / "ava-factory" / "reports"
                       / "dottie_live_status.json")
DEFAULT_STEER = _REPO_ROOT / "apps" / "bluehenre" / "data" / "steer_audit.jsonl"
DEFAULT_SEED = Path(__file__).resolve().parent / "data" / "incidents_seed.json"


def refuse_live_ledger(path: str | Path) -> None:
    """Raise if ``path`` is the live research ledger. Never opens the file."""
    try:
        candidate = Path(path).resolve()
    except OSError:  # unresolvable path cannot be the live ledger
        return
    if candidate == LIVE_LEDGER.resolve():
        raise ValueError(
            f"REFUSED: {path} is the LIVE research ledger. The research daemon "
            "owns it; ingest only ever reads a copy "
            "(e.g. tasks/artifacts/ledger_copy.sqlite3).")


def build_graph(out: str | Path,
                ledger: Optional[str | Path] = None,
                metrics: Optional[List[str | Path]] = None,
                live_status: Optional[str | Path] = None,
                steer: Optional[str | Path] = None,
                incidents_seed: Optional[str | Path] = None,
                docs_root: Optional[str | Path] = None) -> Dict[str, Any]:
    """Run every ingester; return per-source counts + graph totals."""
    ledger = ledger if ledger is not None else DEFAULT_LEDGER
    refuse_live_ledger(ledger)
    metrics = metrics if metrics is not None else list(DEFAULT_METRICS)
    live_status = live_status if live_status is not None else DEFAULT_LIVE_STATUS
    steer = steer if steer is not None else DEFAULT_STEER
    incidents_seed = (incidents_seed if incidents_seed is not None
                      else DEFAULT_SEED)
    docs_root = docs_root if docs_root is not None else _REPO_ROOT

    store = GraphStore(out)
    report: Dict[str, Any] = {"sources": {}}
    for mp in metrics:
        key = f"trainer_metrics:{Path(mp).parent.name}"
        report["sources"][key] = ingest.ingest_trainer_metrics(store, mp)
    report["sources"]["live_status"] = ingest.ingest_live_status(store, live_status)
    report["sources"]["ledger"] = ingest.ingest_ledger(store, ledger)
    report["sources"]["steer"] = ingest.ingest_steer(store, steer)
    report["sources"]["incidents"] = ingest.ingest_incidents(
        store, incidents_seed, docs_root)
    store.set_meta("built_at", str(time.time()))
    store.set_meta("sources", json.dumps({
        "ledger": str(ledger), "metrics": [str(m) for m in metrics],
        "live_status": str(live_status), "steer": str(steer),
        "incidents_seed": str(incidents_seed)}))
    store.commit()
    report["graph"] = store.counts()
    report["out"] = str(Path(out).resolve())
    store.close()
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dottie.kg.build",
        description="Build the org knowledge graph from local substrate "
                    "(read-only ingest, stdlib only).")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                    help="research ledger COPY (the live ledger is refused)")
    ap.add_argument("--metrics", action="append", default=None,
                    help="trainer metrics JSONL (repeatable)")
    ap.add_argument("--live-status", default=str(DEFAULT_LIVE_STATUS))
    ap.add_argument("--steer", default=str(DEFAULT_STEER))
    ap.add_argument("--incidents-seed", default=str(DEFAULT_SEED))
    ap.add_argument("--docs-root", default=str(_REPO_ROOT))
    args = ap.parse_args(argv)
    report = build_graph(
        out=args.out, ledger=args.ledger,
        metrics=args.metrics if args.metrics else None,
        live_status=args.live_status, steer=args.steer,
        incidents_seed=args.incidents_seed, docs_root=args.docs_root)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
