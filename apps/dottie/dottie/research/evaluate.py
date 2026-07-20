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

import math
from typing import Any, Dict, List, Optional

from dottie.research.ledger import Ledger, Experiment, Baseline, EVALUATION_PENDING, REJECTED, SOTA

#: A win must clear this many standard errors of the candidate's own per-batch spread.
#: Measured 2026-07-20: the first "SOTA" (MLBR) beat the baseline by 1.1 SEM — i.e. noise —
#: because promotion used a bare `<`. Two SEM is the cheapest honest bar; it costs nothing
#: when an effect is real and blocks the ratchet from wandering on variance.
#:
#: HONEST LIMIT of this bar: the stored baseline carries no spread of its own, so this
#: tests the candidate's mean against a POINT baseline. A true two-sample test would use
#: SE_diff = √(SE_cand² + SE_base²) ≈ √2·SE for equal variances, making this bar ≈1.4
#: SE_diff (~84% confidence), not 95%. It is therefore a floor, not a proof — deliberately
#: chosen over 2·√2 to keep statistical power while the loop's conversion rate is low.
#: The real fix is paired-seed evaluation (same seeds both sides → test the per-seed
#: DIFFERENCES, which cancels shared variance); queued in TODOS §5.3.R.
SIGNIFICANCE_SEM = 2.0

#: Per-batch metric series a trainer may record, in preference order. The first one present
#: supplies the spread; without any, significance is reported UNAVAILABLE, never assumed.
_SERIES_KEYS = ("eval_ce_per_batch", "per_seed", "eval_losses")


def _baseline_provenance(baseline: Baseline) -> tuple:
    """(kind, caveat) — where the number we are comparing against actually came from.

    Measured 2026-07-20 (TODOS §5.3.R0): the loop's older "SOTA" beat **4.5**, the
    hand-seeded placeholder from the runbook example, on an explicitly-not-capability
    synthetic task — a meaningless promotion that no gate caught, because nothing
    recorded how the baseline was obtained. Recording only; not a gate."""
    if baseline.experiment_id:
        return "promoted", None          # ratcheted from a measured experiment
    if (baseline.notes or "").lower().startswith("measured baseline calibration"):
        return "calibrated", None
    return "hand_seeded", (
        "the baseline is a HAND-SEEDED placeholder (no calibration recorded) — this delta "
        "measures distance from an arbitrary number, not a real improvement. Run "
        "`python -m dottie.research calibrate-baseline` before trusting any promotion.")


def _spread(metrics: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Sample std + standard error of the mean from a recorded per-batch/per-seed series."""
    for key in _SERIES_KEYS:
        raw = metrics.get(key)
        if not isinstance(raw, (list, tuple)):
            continue
        xs: List[float] = [float(v) for v in raw
                           if isinstance(v, (int, float)) and math.isfinite(float(v))]
        if len(xs) < 2:
            continue
        n = len(xs)
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / (n - 1)
        std = math.sqrt(var)
        return {"series": key, "n": n, "mean": mean, "std": std, "sem": std / math.sqrt(n)}
    return None


def _writeup(exp: Experiment, baseline: Baseline, value: Optional[float], *,
             promoted: bool, reason: str = "", significance: str = "",
             capacity: str = "") -> str:
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
    if significance:
        lines.append(f"**Significance:** {significance}")
    if capacity:
        lines.append(f"**Caveats:** {capacity}")
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
    # Metric-agnostic: a run is comparable when a real trainer integration recorded the
    # baseline's metric (run_training already diverts unstable runs to failed_training).
    stable = (metrics.get("integration") is not None
              and baseline.metric_name in metrics) if require_stable else True

    if value is None:
        verdict = {"promote": False, "metric": baseline.metric_name,
                   "reason": f"no '{baseline.metric_name}' in train_metrics — not comparable"}
        ledger.transition(exp.id, REJECTED, eval_verdict=verdict,
                          writeup=_writeup(exp, baseline, None, promoted=False,
                                           reason=verdict["reason"]), ts=ts)
        return {"experiment": exp.id, "state": REJECTED, "reason": "no comparable metric"}

    value = float(value)
    improved = baseline.improves(value)
    delta = value - baseline.metric_value

    # Significance: a direction-correct win must also clear SIGNIFICANCE_SEM standard
    # errors of the candidate's own measurement spread. No series recorded => reported
    # unavailable and NOT treated as passing (the ratchet only moves on evidence).
    sp = _spread(metrics)
    if sp is None:
        significant, sig_note = None, "no per-batch series recorded — significance unmeasurable"
    else:
        significant = abs(delta) >= SIGNIFICANCE_SEM * sp["sem"]
        # `significant` is direction-AGNOSTIC (it tests |delta| against noise), so a
        # candidate that is significantly WORSE also sets it true. Spell the direction out
        # here: this string is what lands in the write-up and the promotion bundle, where
        # a skimmer could otherwise read "significant: true" as good news.
        if significant:
            verdict_word = "BETTER than baseline" if improved else "WORSE than baseline"
        else:
            verdict_word = "within noise of baseline"
        sig_note = (f"{verdict_word}: |delta| {abs(delta):.5g} vs {SIGNIFICANCE_SEM}×SEM "
                    f"{SIGNIFICANCE_SEM * sp['sem']:.5g} (n={sp['n']}, std={sp['std']:.5g})")

    # Recorded, not gated on: a swap that DELETES parameters can "win" at fixed steps
    # simply by being easier to fit (MLBR did exactly this). The reviewer needs to see it.
    params = metrics.get("params")
    block_delta = metrics.get("block_param_delta")
    capacity_note = None
    if isinstance(block_delta, int) and block_delta != 0:
        direction = "REMOVED" if block_delta < 0 else "added"
        capacity_note = (
            f"the swapped block {direction} {abs(block_delta):,} parameters vs the block it "
            f"replaced ({metrics.get('replaced_block_params'):,} → "
            f"{metrics.get('candidate_block_params'):,}) — a fixed-step comparison partly "
            f"measures capacity, not just the idea")
    base_kind, base_caveat = _baseline_provenance(baseline)
    promote = improved and (stable if require_stable else True) and bool(significant)
    verdict = {
        "promote": promote, "improved": improved, "stable": bool(stable),
        "significant": significant, "significance": sig_note,
        "baseline_provenance": base_kind, "baseline_caveat": base_caveat,
        "sem": None if sp is None else round(sp["sem"], 6),
        "sem_series": None if sp is None else sp["series"],
        "sem_n": None if sp is None else sp["n"],
        "candidate_params": params,
        "block_param_delta": block_delta, "capacity_caveat": capacity_note,
        "metric": baseline.metric_name, "baseline_value": baseline.metric_value,
        "new_value": value, "delta": round(delta, 6),
        "higher_is_better": baseline.higher_is_better,
    }

    if promote:
        writeup = _writeup(exp, baseline, value, promoted=True, significance=sig_note,
                           capacity="\n".join(x for x in (capacity_note, base_caveat) if x))
        ledger.transition(exp.id, SOTA, eval_verdict=verdict, writeup=writeup, ts=ts)
        ledger.promote_baseline(exp.id, value, notes=exp.name, ts=ts)
        return {"experiment": exp.id, "state": SOTA, "verdict": verdict}

    if not improved:
        reason = "did not beat baseline"
    elif not stable:
        reason = "improved but unstable — held (rank-invariance)"
    elif not significant:
        reason = (f"improvement within noise — held ({sig_note})" if significant is False
                  else f"improvement unverifiable — held ({sig_note})")
    else:
        reason = "held"
    writeup = _writeup(exp, baseline, value, promoted=False, reason=reason,
                       significance=sig_note,
                       capacity="\n".join(x for x in (capacity_note, base_caveat) if x))
    ledger.transition(exp.id, REJECTED, eval_verdict=verdict, writeup=writeup, ts=ts)
    return {"experiment": exp.id, "state": REJECTED, "verdict": verdict, "reason": reason}
