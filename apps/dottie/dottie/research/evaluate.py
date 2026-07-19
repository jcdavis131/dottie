# Solo personal project, no connection to employer, built with public/free-tier only
"""Evaluator & hill-climber (worker 4) — the only place a new SOTA is declared.

Compares a finished experiment's REAL measured metric against the global baseline. Promotion is
strict and direction-aware (``Baseline.improves``) and additionally requires the run to be stable
— an unstable "win" is never promoted (rank-invariance / rigor discipline). On promotion it moves
the baseline, marks the experiment ``sota``, and writes an automated write-up. On no improvement
it marks the experiment ``rejected`` and the failure feeds back into ideation as a dead end.
Nothing is compared that was not really measured — a missing metric is an honest rejection.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from dottie.research.ledger import Ledger, Experiment, Baseline, EVALUATION_PENDING, REJECTED, SOTA


def _writeup(exp: Experiment, baseline: Baseline, value: Optional[float], *,
             promoted: bool, reason: str = "") -> str:
    h = exp.hypothesis or {}
    m = exp.train_metrics or {}
    lines = [
        f"# Experiment {exp.id} — {exp.name}",
        "",
        f"**Verdict:** {'PROMOTED — new SOTA' if promoted else 'rejected'}",
        f"**Metric:** {baseline.metric_name} "
        f"({'higher is better' if baseline.higher_is_better else 'lower is better'})",
        f"**Baseline:** {baseline.metric_value:.6g}  ·  "
        f"**This run:** {value if value is None else f'{value:.6g}'}",
    ]
    if value is not None:
        delta = value - baseline.metric_value
        lines.append(f"**Delta:** {delta:+.6g}"
                     + (f"  ·  std {m.get('proxy_loss_std')}" if m.get("proxy_loss_std") is not None else ""))
    if reason:
        lines.append(f"**Reason:** {reason}")
    lines += [
        "",
        "## Hypothesis",
        h.get("theoretical_intuition", "(none)"),
        "",
        f"- Formulation: {h.get('mathematical_formulation', '(none)')}",
        f"- Expected outcome: {h.get('expected_outcome', '(none)')}",
        f"- Measured on: {m.get('task', 'n/a')} "
        f"({m.get('integration', 'n/a')}; params={m.get('params', 'n/a')}, "
        f"seeds={m.get('seeds', 'n/a')})",
    ]
    return "\n".join(lines)


def run_evaluation(ledger: Ledger, *, require_stable: bool = True,
                   ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Evaluate the oldest evaluation_pending experiment against the baseline; hill-climb if it
    really improved. Returns a summary, or None if nothing is pending."""
    exp = ledger.next_in_state(EVALUATION_PENDING)
    if exp is None:
        return None
    baseline = ledger.get_baseline()
    if baseline is None:
        # Cannot hill-climb without a baseline — reject honestly rather than invent one.
        verdict = {"promote": False, "reason": "no baseline seeded"}
        ledger.transition(exp.id, REJECTED, eval_verdict=verdict,
                          writeup="rejected: no baseline to compare against", ts=ts)
        return {"experiment": exp.id, "state": REJECTED, "reason": "no baseline"}

    metrics = exp.train_metrics or {}
    value = metrics.get(baseline.metric_name)
    stable = metrics.get("integration") is not None and "proxy_loss" in metrics if require_stable else True

    if value is None:
        verdict = {"promote": False, "metric": baseline.metric_name,
                   "reason": f"no '{baseline.metric_name}' in train_metrics — not comparable"}
        ledger.transition(exp.id, REJECTED, eval_verdict=verdict,
                          writeup=_writeup(exp, baseline, None, promoted=False,
                                           reason=verdict["reason"]), ts=ts)
        return {"experiment": exp.id, "state": REJECTED, "reason": "no comparable metric"}

    value = float(value)
    improved = baseline.improves(value)
    promote = improved and (stable if require_stable else True)
    verdict = {
        "promote": promote, "improved": improved, "stable": bool(stable),
        "metric": baseline.metric_name, "baseline_value": baseline.metric_value,
        "new_value": value, "delta": round(value - baseline.metric_value, 6),
        "higher_is_better": baseline.higher_is_better,
    }

    if promote:
        writeup = _writeup(exp, baseline, value, promoted=True)
        ledger.transition(exp.id, SOTA, eval_verdict=verdict, writeup=writeup, ts=ts)
        ledger.promote_baseline(exp.id, value, notes=exp.name, ts=ts)
        return {"experiment": exp.id, "state": SOTA, "verdict": verdict}

    reason = ("did not beat baseline" if not improved
              else "improved but unstable — held (rank-invariance)")
    writeup = _writeup(exp, baseline, value, promoted=False, reason=reason)
    ledger.transition(exp.id, REJECTED, eval_verdict=verdict, writeup=writeup, ts=ts)
    return {"experiment": exp.id, "state": REJECTED, "verdict": verdict, "reason": reason}
