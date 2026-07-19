# Solo personal project, no connection to employer, built with public/free-tier only
"""arxiviq metric logger + research status snapshot.

``log_metric(key, value)`` is the standard pattern the generated code and workers use to route
auxiliary losses / routing distributions / run metrics into a single append-only JSONL that the
arxiviq dashboard reads. ``build_status`` / ``write_status`` distil the ledger into the honest
JSON the Research tab renders — every field comes from a real ledger row; nothing is invented.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dottie.research import paths
from dottie.research.ledger import Ledger, SOTA


def log_metric(key: str, value: Any, *, data_dir: Optional[str | Path] = None,
               experiment_id: Optional[str] = None, ts: Optional[float] = None,
               **tags: Any) -> None:
    """Append one measured metric to the research metrics JSONL (the arxiviq_logger pattern)."""
    rec = {"ts": ts if ts is not None else time.time(), "key": key, "value": value}
    if experiment_id is not None:
        rec["experiment_id"] = experiment_id
    rec.update(tags)
    mp = paths.metrics_path(data_dir)
    with mp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def build_status(ledger: Ledger, *, recent: int = 25) -> Dict[str, Any]:
    """The honest research snapshot: baseline, state counts, recent experiments, SOTA history."""
    baseline = ledger.get_baseline()
    experiments: List[Dict[str, Any]] = []
    for exp in ledger.list(limit=recent):
        m = exp.train_metrics or {}
        v = exp.eval_verdict or {}
        experiments.append({
            "id": exp.id, "name": exp.name, "state": exp.state,
            "created_ts": exp.created_ts, "updated_ts": exp.updated_ts,
            "metric": (m.get(baseline.metric_name) if baseline else None),
            "delta": v.get("delta"), "promote": v.get("promote"),
            "search_domain": (exp.hypothesis or {}).get("search_domain"),
            "attempts": exp.attempts,
        })
    sota = [{"id": e.id, "name": e.name, "metric": (e.train_metrics or {}).get(
        baseline.metric_name if baseline else ""), "updated_ts": e.updated_ts}
        for e in ledger.list(state=SOTA, limit=recent)]
    return {
        "service": "dottie-research",
        "ts": time.time(),
        "baseline": (None if baseline is None else {
            "metric_name": baseline.metric_name, "metric_value": baseline.metric_value,
            "higher_is_better": baseline.higher_is_better, "architecture": baseline.architecture,
            "experiment_id": baseline.experiment_id, "updated_ts": baseline.updated_ts,
            "notes": baseline.notes}),
        "counts": ledger.counts(),
        "experiments": experiments,
        "sota_history": sota,
        "note": ("Every metric is a real measurement from the proxy micro-benchmark; a new SOTA "
                 "is declared only on a real, direction-aware improvement over the baseline."),
    }


def write_status(ledger: Ledger, *, data_dir: Optional[str | Path] = None) -> Path:
    sp = paths.status_path(data_dir)
    sp.write_text(json.dumps(build_status(ledger), indent=2), encoding="utf-8")
    return sp
