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


def _status_note(base_caveat: Optional[str], task: Optional[str] = None) -> str:
    """The snapshot's own summary line, which must not overstate what the numbers mean.

    The standing note said a SOTA "is declared only on a real, direction-aware improvement
    over the baseline". True of the comparison, and actively misleading when the BASELINE is
    the problem — as it is right now (TODOS §5.3.R5: the live baseline was ratcheted by a
    module the validator would reject today). A snapshot that reports a contaminated
    baseline in the same voice as a clean one is the exact failure this loop keeps having.

    ``task`` is read from the LEDGER rather than hardcoded. The note used to assert every
    metric came "from the proxy micro-benchmark", which stopped being true when the daemon
    moved to ``--trainer factory``: measured 2026-07-20 (TODOS §5.3.R59), 27 of 28 recorded
    integrations are ``factory_nano_block_swap`` and 21 runs describe themselves as
    "held-out LM cross-entropy on the real packed pilot corpus". A hardcoded description of
    your own measurement drifts silently the moment the measurement changes — and an
    inaccurate honesty statement is worse than none."""
    measured = task or "the recorded trainer integration"
    note = (f"Every metric is a real measurement ({measured}); a new SOTA "
            "is declared only on a real, direction-aware improvement over the baseline.")
    if base_caveat:
        note += (" WARNING: the baseline itself carries a caveat (see baseline.caveat) — "
                 "improvements measured against it are NOT trustworthy until it is re-seeded.")
    return note


def _recent_task(ledger: Ledger) -> Optional[str]:
    """How the most recent measured run described its own task, or None if nothing has run.

    Derived, not asserted: whatever the trainer wrote into `train_metrics["task"]` is what
    the loop actually measured (TODOS §5.3.R59)."""
    for exp in ledger.list(limit=25):
        task = (exp.train_metrics or {}).get("task")
        if task:
            return str(task)
    return None


def build_status(ledger: Ledger, *, recent: int = 25) -> Dict[str, Any]:
    """The honest research snapshot: baseline, state counts, recent experiments, SOTA history."""
    baseline = ledger.get_baseline()
    # Provenance travels WITH the number. Reporting 5.60506 with no indication that a
    # rejected no-op set it is how the dashboard ends up more confident than the data.
    base_kind, base_caveat = (None, None)
    if baseline is not None:
        from dottie.research.evaluate import _baseline_contamination, _baseline_provenance
        base_kind, base_caveat = _baseline_provenance(baseline)
        contamination = _baseline_contamination(ledger, baseline)
        if contamination:
            base_kind = "promoted_contaminated" if base_kind == "promoted" else base_kind
            base_caveat = "\n".join(x for x in (base_caveat, contamination) if x)
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
    # metric regime-matches the CURRENT baseline metric (null for sota from a retired metric);
    # metric_name/baseline_value come from the verdict that promoted it, so the dashboard can
    # anchor a hill-climb series at the seed value each sota was actually measured against.
    sota = []
    for e in ledger.list(state=SOTA, limit=recent):
        v = e.eval_verdict or {}
        sota.append({
            "id": e.id, "name": e.name,
            "metric": (e.train_metrics or {}).get(baseline.metric_name if baseline else ""),
            "metric_name": v.get("metric"), "baseline_value": v.get("baseline_value"),
            "updated_ts": e.updated_ts,
        })
    return {
        "service": "dottie-research",
        "ts": time.time(),
        "baseline": (None if baseline is None else {
            "metric_name": baseline.metric_name, "metric_value": baseline.metric_value,
            "higher_is_better": baseline.higher_is_better, "architecture": baseline.architecture,
            "experiment_id": baseline.experiment_id, "updated_ts": baseline.updated_ts,
            "notes": baseline.notes,
            "metric_sem": baseline.metric_sem, "metric_sem_n": baseline.metric_sem_n,
            "provenance": base_kind, "caveat": base_caveat}),
        "counts": ledger.counts(),
        "experiments": experiments,
        "sota_history": sota,
        "note": _status_note(base_caveat, _recent_task(ledger)),
    }


def write_status(ledger: Ledger, *, data_dir: Optional[str | Path] = None) -> Path:
    sp = paths.status_path(data_dir)
    sp.write_text(json.dumps(build_status(ledger), indent=2), encoding="utf-8")
    return sp
