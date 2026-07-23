# Solo personal project, no connection to employer, built with public/free-tier only
"""Evaluator & hill-climber (worker 4) — the only place a new SOTA is declared.

Compares a finished experiment's REAL measured metric against the global baseline. Promotion is
strict and direction-aware (``Baseline.improves``) and additionally requires the run to be stable
— an unstable "win" is never promoted (rank-invariance / rigor discipline). A win whose only
spread is within-run must additionally survive the paired-seed A/B gate (``_multi_seed_gate``):
within-run SEM alone can never promote. On promotion it moves the baseline, marks the experiment
``sota``, and writes an automated write-up. On no improvement it marks the experiment
``rejected`` and the failure feeds back into ideation as a dead end.
Nothing is compared that was not really measured — a missing metric is an honest rejection.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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

#: Capacity gate (TODOS item 10, operator-activated 2026-07-21). A swap that DELETES more
#: than this fraction of the block it replaces can "win" a fixed-step comparison simply by
#: being easier to fit — the exact chain behind every artifact SOTA in this ledger (MLBR
#: removed 100%; `5a7232ffea24` removed 99.97%). Such a win must not ratchet the baseline.
#: 10% headroom keeps a genuinely leaner-but-better block eligible while refusing wins that
#: are mostly shrinkage; a gated candidate is REJECTED with the reason spelled out, and a
#: capacity-fair re-eval (same param budget) can always be run from its promotion bundle.
CAPACITY_DELETE_FRAC = 0.10

#: Metric series a trainer may record, in preference order. The first one present supplies
#: the spread; without any, significance is reported UNAVAILABLE, never assumed.
#:
#: ``per_seed`` is FIRST on purpose. It holds one final loss per training seed, so its spread
#: includes run-to-run variance; ``eval_ce_per_batch`` holds 20 batches from a SINGLE run and
#: cannot see that variance at all. The order used to be the other way round, which meant a
#: trainer recording both would have its stronger estimate silently ignored.
#:
#: This is not theoretical. TODOS §5.3.R93: the factory trainer records only
#: ``eval_ce_per_batch`` (SEM 0.0172), and on that basis `5a7232ffea24` was promoted as a
#: 4.4-SEM win. Paired seed testing then showed the same candidate is WORSE at all three
#: seeds — because the unmodified model's own score swings **0.343 across seeds**, 4.5× the
#: "effect". A bar built from within-run spread cannot measure the noise that decides the
#: comparison.
_SERIES_KEYS = ("per_seed", "eval_ce_per_batch", "eval_losses")

#: Series that come from ONE training run, so their spread is blind to run-to-run variance.
_WITHIN_RUN_SERIES = frozenset({"eval_ce_per_batch", "eval_losses"})

#: Wall-clock ceiling for an auto-run ab_nano.py: 2 models × 3 seeds × ~150 nano steps,
#: with CPU margin. Overridable via DOTTIE_AB_GATE_TIMEOUT_S. A timeout is MISSING
#: evidence (refusal), never a pass.
_AB_GATE_TIMEOUT_S_DEFAULT = 5400.0


def parse_ab_verdict(output: str) -> Optional[str]:
    """Classify an ab_nano.py run from its stdout: 'win' | 'loss' | 'within_noise' | None.

    Keys off the VERDICT line the ``promote._AB_TEMPLATE`` script prints (the LAST one,
    should reruns be concatenated). None means no verdict was printed — an aborted or
    foreign script — which callers must treat as missing evidence, never as a pass."""
    verdict: Optional[str] = None
    for line in output.splitlines():
        if "VERDICT:" not in line:
            continue
        if "BETTER beyond noise" in line:
            verdict = "win"
        elif "WORSE beyond noise" in line:
            verdict = "loss"
        elif "WITHIN NOISE" in line:
            verdict = "within_noise"
    return verdict


def subprocess_ab_runner(script_path: str | Path) -> Tuple[Optional[int], str]:
    """Run a promotion bundle's ab_nano.py in a FRESH interpreter; (returncode, output).

    A subprocess on purpose, not an import: the daemon never live-reloads, and ab_nano
    trains 2×len(SEEDS) real nano runs whose torch state must not accumulate inside the
    forever-daemon's memory. NOT the default for run_evaluation — only entry points that
    can actually pay for six training runs (__main__'s cmd_evaluate/cmd_loop/cmd_run)
    wire it in; every unwired caller refuses within-run-only promotions outright."""
    import subprocess
    script = Path(script_path)
    try:
        timeout_s = float(os.environ.get("DOTTIE_AB_GATE_TIMEOUT_S",
                                         _AB_GATE_TIMEOUT_S_DEFAULT))
    except ValueError:
        timeout_s = _AB_GATE_TIMEOUT_S_DEFAULT
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          cwd=str(script.parent), timeout=timeout_s)
    out = proc.stdout or ""
    if proc.stderr:
        out += "\n" + proc.stderr
    return proc.returncode, out


def _multi_seed_gate(ledger: Ledger, exp: Experiment, *,
                     ab_runner: Optional[Callable[..., Tuple[Optional[int], str]]],
                     promotions_root: Optional[str | Path] = None) -> Dict[str, Any]:
    """Demand paired-seed (ab_nano) evidence for a would-be promotion whose only spread
    is within-run. Returns a gate record; ONLY ``status == "win"`` permits promotion.

    Statuses: ``win`` (paired A/B better beyond noise), ``loss`` (worse beyond noise —
    the R93 shape), ``within_noise`` (indistinguishable), ``error`` (script ran but
    produced no clean verdict), ``unavailable`` (no runner wired, script unwritable, or
    the run itself failed — e.g. no torch/GPU on this box). Everything except ``win`` is
    an honest refusal: within-run SEM alone can never promote (§5.3.R93)."""
    gate: Dict[str, Any] = {"evidence": "ab_nano"}
    if ab_runner is None:
        gate.update(status="unavailable",
                    detail="no A/B runner wired into this evaluation (library callers "
                           "get the refusing default; __main__ wires the real one)")
        return gate
    from dottie.research import promote as _promote   # lazy: promote imports this module
    root = (Path(promotions_root) if promotions_root is not None
            else Path(ledger.path).parent / "promotions")
    try:
        script = _promote.write_ab_script(ledger, exp.id, out_root=root)
    except Exception as e:                            # never let the gate break evaluation
        gate.update(status="unavailable", detail=f"could not write ab_nano.py: {e!r}")
        return gate
    gate["script"] = str(script)
    try:
        rc, out = ab_runner(script)
    except Exception as e:
        gate.update(status="unavailable", detail=f"ab_nano.py did not run: {e!r}")
        return gate
    gate["output_tail"] = (out or "").strip()[-2000:]
    verdict = parse_ab_verdict(out or "")
    if rc not in (0, None):
        # A verdict printed by a script that then crashed is not evidence of anything.
        gate.update(status="error", detail=f"ab_nano.py exited {rc}")
    elif verdict is None:
        gate.update(status="error", detail="ab_nano.py printed no VERDICT line")
    elif verdict == "win":
        gate.update(status="win",
                    detail="paired-seed A/B: candidate BETTER than unmodified beyond noise")
    elif verdict == "loss":
        gate.update(status="loss",
                    detail="paired-seed A/B: candidate WORSE than unmodified beyond noise "
                           "— the within-run 'win' was noise (the R93 shape)")
    else:
        gate.update(status="within_noise",
                    detail="paired-seed A/B: WITHIN NOISE — the runs do not distinguish "
                           "the candidate from the unmodified model")
    return gate


def _baseline_provenance(baseline: Baseline) -> tuple:
    """(kind, caveat) — where the number we are comparing against actually came from.

    Measured 2026-07-20 (TODOS §5.3.R0): the loop's older "SOTA" beat **4.5**, the
    hand-seeded placeholder from the runbook example, on an explicitly-not-capability
    synthetic task — a meaningless promotion that no gate caught, because nothing
    recorded how the baseline was obtained. Recording only; not a gate."""
    if baseline.experiment_id:
        return "promoted", None          # ratcheted from a measured experiment — see
                                         # _baseline_contamination for whether that
                                         # experiment still passes today's gates
    if (baseline.notes or "").lower().startswith("measured baseline calibration"):
        return "calibrated", None
    return "hand_seeded", (
        "the baseline is a HAND-SEEDED placeholder (no calibration recorded) — this delta "
        "measures distance from an arbitrary number, not a real improvement. Run "
        "`python -m dottie.research calibrate-baseline` before trusting any promotion.")


def _baseline_contamination(ledger: Ledger, baseline: Baseline) -> Optional[str]:
    """Would the experiment that SET this baseline still survive today's validator?

    `_baseline_provenance` treats any baseline with an ``experiment_id`` as "promoted",
    the highest-trust category, with no caveat. That trust is retrospective and unchecked:
    a gate added *after* a promotion never re-examines the number that promotion left
    behind, so a candidate the loop would now reject can still be the standard every later
    candidate is measured against — and it reads as fully trustworthy while doing it.

    Measured 2026-07-20: the live baseline is ``factory_lm_loss 5.60506``, ratcheted by
    ``23bb41375804`` (MLBR), which the degeneracy gate now fails outright as a zero-
    parameter no-op. Every comparison since has been against a number set by a module
    that cannot learn anything.

    Re-validating the source experiment's stored code costs one dry run (seconds) and is
    the only way to notice. Returns a caveat string when the source is contaminated or
    cannot be checked, else None. This RECORDS; it deliberately does not block — whether a
    contaminated baseline should halt the loop or merely flag itself is a call for the
    operator, and is queued in TODOS."""
    if not baseline.experiment_id:
        return None
    try:
        src = ledger.get(baseline.experiment_id)
    except Exception:
        return (f"the experiment that set this baseline ({baseline.experiment_id}) is no "
                "longer in the ledger — its validity cannot be checked")
    impl = src.implementation or {}
    code = impl.get("code")
    if not code:
        return (f"the experiment that set this baseline ({baseline.experiment_id}) stored "
                "no code — its validity cannot be re-checked against current gates")
    dry = impl.get("dry_run") or {}
    try:
        from dottie.research import validate as _validate
        res = _validate.validate(code, class_name=dry.get("class_name"),
                                 init_kwargs=dry.get("init_kwargs") or {},
                                 input_shape=dry.get("input_shape") or [4, 16, 64])
    except Exception as e:                       # never let a check break an evaluation
        return (f"could not re-validate the baseline's source experiment "
                f"({baseline.experiment_id}): {e!r}")
    if res.ok:
        # "ok" is NOT the same as "checked". With torch missing — which is the normal state
        # in the server container, where this ledger is bind-mounted read-only — validate()
        # reports dry_run as *skipped* and still returns ok=True. Returning None there would
        # be a FALSE CLEAN: a contaminated baseline presented as verified, by the very check
        # written to catch that. Measured 2026-07-20 by stubbing _find_torch to None.
        skipped = [lvl for lvl, info in (res.per_level or {}).items()
                   if info.get("status") == "skipped"]
        if skipped:
            return (f"baseline validity UNVERIFIED — re-checking the experiment that set it "
                    f"({baseline.experiment_id}) needs stage(s) {sorted(skipped)}, which could "
                    "not run here (usually torch or ruff absent). This is NOT a clean bill of "
                    "health: it means the check did not happen.")
        return None
    return (f"CONTAMINATED BASELINE — the experiment that set it ({baseline.experiment_id}, "
            f"{src.name}) FAILS the current validator at '{res.level}': "
            f"{(res.detail or '').strip()[:200]}. This delta is measured against a number "
            "produced by a candidate the loop would now reject, so it is not evidence of "
            "an improvement. Re-seed the baseline before trusting any promotion.")


#: A swap is treated as capacity-confounded when it removed at least this fraction of the
#: block it replaced. Half is a deliberate, statable line: below it the swap is plausibly a
#: redesign, above it the model is simply smaller and a fixed-step win partly measures that.
_CAPACITY_REMOVAL_FRACTION = 0.5


def _baseline_capacity_caveat(ledger: Ledger, baseline: Baseline) -> Optional[str]:
    """Did the experiment that SET this baseline win by DELETING capacity?

    ``_baseline_contamination`` asks whether the source experiment still passes the
    validator. That catches degenerate no-ops (MLBR) and nothing else — a candidate can pass
    every gate cleanly and still have won for a reason unrelated to its idea.

    Measured 2026-07-20 (TODOS §5.3.R86/R90): the live baseline ``factory_lm_loss 5.54404``
    was set by ``5a7232ffea24``, which replaced a 787,072-parameter block with 256 parameters
    — it removed **99.97% of the block** — and passes the validator outright. So
    ``_baseline_contamination`` returns clean and the status snapshot reported
    ``caveat: null``: a bar set by deleting three quarters of a million parameters, presented
    to the operator as an ordinary promoted baseline.

    factory_trainer.py has recorded ``block_param_delta`` all along, and its own comment says
    a parameter-light candidate "can 'win' at fixed steps for that reason alone (MLBR did)".
    The number existed; nothing ever read it back at baseline level. This reads it.

    RECORDS, never blocks — same contract as ``_baseline_contamination``. Whether a
    capacity-confounded baseline should halt the loop is the operator's call. Stating the
    fact is not: the delta is real provenance whether or not the win turns out to be."""
    if not baseline.experiment_id:
        return None
    try:
        src = ledger.get(baseline.experiment_id)
        metrics = src.train_metrics or {}
    except Exception:
        return None                      # absence is reported by _baseline_contamination
    delta = metrics.get("block_param_delta")
    replaced = metrics.get("replaced_block_params")
    if not isinstance(delta, int) or not isinstance(replaced, int) or delta >= 0 or replaced <= 0:
        return None
    fraction = abs(delta) / replaced
    if fraction < _CAPACITY_REMOVAL_FRACTION:
        return None
    return (f"CAPACITY-CONFOUNDED BASELINE — the experiment that set it "
            f"({baseline.experiment_id}, {src.name}) REMOVED {abs(delta):,} of "
            # .2% not .1%: 786,816/787,072 rounds to "100.0%", which would state that the
            # block was removed ENTIRELY. It was not -- 256 parameters remain. A caveat about
            # overstated claims must not overstate.
            f"{replaced:,} parameters ({fraction:.2%} of the block it replaced). At a fixed "
            "step budget a smaller model CAN reach a lower loss for that reason alone, so "
            "this bar MAY partly measure capacity rather than the idea — only a capacity-"
            "matched control can tell, and it is cheap: rerun the swap with a zero-parameter "
            "pass-through and compare. Until then, treat deltas against this baseline as "
            "provisional.")


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
                   ts: Optional[float] = None,
                   ab_runner: Optional[Callable[..., Tuple[Optional[int], str]]] = None,
                   promotions_root: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    """Evaluate the oldest evaluation_pending experiment against the baseline; hill-climb if it
    really improved. Returns a summary, or None if nothing is pending.

    ``ab_runner``/``promotions_root`` feed the hard multi-seed gate: a would-be promotion
    whose only spread is within-run auto-runs its bundle's ab_nano.py through ``ab_runner``
    and promotes ONLY on a paired-seed win. The default (None) refuses such promotions
    outright — within-run SEM alone can never promote, wired or not."""
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
    # PAIRED test (TODOS item 11, operator-activated 2026-07-21): when the candidate and the
    # baseline both carry `per_seed` at the same n, the honest denominator is the SE of the
    # per-seed DIFFERENCES — a hard seed hurts both runs, so differencing cancels the shared
    # seed variance the unpaired test wrongly counts (§5.3.R93: the unmodified model alone
    # swings 0.343 across seeds). Falls back to the unpaired test whenever pairing is not
    # possible, which keeps every pre-per_seed baseline behaving exactly as before.
    paired_diffs: Optional[List[float]] = None
    cand_ps = metrics.get("per_seed")
    base_ps = getattr(baseline, "per_seed", None)
    if (isinstance(cand_ps, (list, tuple)) and isinstance(base_ps, (list, tuple))
            and len(cand_ps) == len(base_ps) and len(cand_ps) >= 2):
        try:
            diffs = [float(c) - float(b) for c, b in zip(cand_ps, base_ps)]
        except (TypeError, ValueError):
            diffs = None
        if diffs is not None and all(math.isfinite(x) for x in diffs):
            paired_diffs = diffs
    if sp is None:
        significant, sig_note = None, "no per-batch series recorded — significance unmeasurable"
    else:
        # Two-sample when the baseline recorded its own spread, one-sample when it did not.
        # Comparing a candidate's SEM against a POINT baseline silently assumes the
        # baseline was measured without error: the effective threshold is ~1.4 SE_diff
        # (~84%), not the 95% the word "significant" implies. When the baseline carries a
        # SEM, SE_diff = sqrt(sem_c² + sem_b²) is the honest denominator. The fallback is
        # kept — most baselines here predate this field — but it now says so out loud
        # instead of leaving the reader to assume the stronger test was applied.
        base_sem = baseline.metric_sem
        if paired_diffs is not None:
            n_p = len(paired_diffs)
            mean_d = sum(paired_diffs) / n_p
            var_d = sum((x - mean_d) ** 2 for x in paired_diffs) / (n_p - 1)
            se_diff = math.sqrt(var_d) / math.sqrt(n_p)
            basis = (f"PAIRED per-seed SE {se_diff:.5g} over n={n_p} shared seeds "
                     f"(candidate vs baseline differenced at the SAME seeds — shared "
                     f"seed variance cancels)")
        elif base_sem is not None and base_sem >= 0:
            se_diff = (sp["sem"] ** 2 + float(base_sem) ** 2) ** 0.5
            basis = (f"two-sample SE_diff {se_diff:.5g} "
                     f"(candidate SEM {sp['sem']:.5g}, baseline SEM {float(base_sem):.5g})")
        else:
            se_diff = sp["sem"]
            basis = (f"candidate-only SEM {sp['sem']:.5g} — the baseline records NO spread, "
                     f"so it is treated as an exact point and this test is weaker than "
                     f"{SIGNIFICANCE_SEM} SE of a real difference")
        # Say which spread this rests on. A within-run series measures batch-to-batch noise
        # inside ONE run and is blind to run-to-run variance — which is the variance that
        # actually decides these comparisons (TODOS §5.3.R93: a candidate cleared this bar at
        # 4.4 SEM and was then WORSE at all 3 seeds, because the unmodified model's own score
        # swings 0.343 across seeds). The basis string RECORDS it; the hard multi-seed gate
        # below (operator order B0) is what now REFUSES it: a would-be promotion on this
        # basis must survive its bundle's paired-seed ab_nano.py first.
        if sp["series"] in _WITHIN_RUN_SERIES:
            basis += (f" [spread from '{sp['series']}' — a SINGLE run's batch-to-batch "
                      f"noise, which CANNOT see run-to-run variance. Verify with "
                      f"promotions/<id>/ab_nano.py before trusting this]")
        significant = abs(delta) >= SIGNIFICANCE_SEM * se_diff
        # `significant` is direction-AGNOSTIC (it tests |delta| against noise), so a
        # candidate that is significantly WORSE also sets it true. Spell the direction out
        # here: this string is what lands in the write-up and the promotion bundle, where
        # a skimmer could otherwise read "significant: true" as good news.
        if significant:
            verdict_word = "BETTER than baseline" if improved else "WORSE than baseline"
        else:
            verdict_word = "within noise of baseline"
        sig_note = (f"{verdict_word}: |delta| {abs(delta):.5g} vs {SIGNIFICANCE_SEM}× "
                    f"{basis} = {SIGNIFICANCE_SEM * se_diff:.5g} "
                    f"(n={sp['n']}, std={sp['std']:.5g})")

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
    contamination = _baseline_contamination(ledger, baseline)
    if contamination:
        base_kind = "promoted_contaminated"
        base_caveat = "\n".join(x for x in (base_caveat, contamination) if x)
    capacity_confound = _baseline_capacity_caveat(ledger, baseline)
    if capacity_confound:
        # Distinct from `promoted_contaminated`, which means the source no longer VALIDATES.
        # This source validates cleanly and still won partly by shrinking the model.
        base_kind = "promoted_capacity_flagged" if base_kind == "promoted" else base_kind
        base_caveat = "\n".join(x for x in (base_caveat, capacity_confound) if x)
    # CAPACITY GATE (TODOS item 10, operator-activated): a candidate that deleted more than
    # CAPACITY_DELETE_FRAC of the block it replaced may not promote, however good its number —
    # at fixed steps that win is confounded with being easier to fit. Gates only on POSITIVE
    # knowledge of a large deletion: swaps that add capacity, and trainers that never record
    # the delta, are untouched (their absence of evidence is already surfaced as a caveat).
    replaced_params = metrics.get("replaced_block_params")
    capacity_gated = (
        isinstance(block_delta, int) and isinstance(replaced_params, int)
        and replaced_params > 0 and block_delta < 0
        and (-block_delta) / replaced_params > CAPACITY_DELETE_FRAC
    )
    # HARD MULTI-SEED GATE (operator order B0, 2026-07-23): within-run SEM alone can NEVER
    # promote. §5.3.R93 is the proof — a 4.4-SEM within-run "win" that was worse at every
    # seed; all 3 historical "sota" rows rest on this class of evidence. When the only
    # spread is within-run, the gate auto-runs the promotion bundle's ab_nano.py (paired
    # seeds — the fix the comments above have named all along) and refuses on a loss, on
    # noise, or on missing evidence. Checked AFTER the capacity gate on purpose: a
    # capacity-gated candidate must not spend six training runs on evidence that cannot
    # change its answer.
    multi_seed_evidence = sp is not None and sp["series"] not in _WITHIN_RUN_SERIES
    would_promote = (improved and (stable if require_stable else True) and bool(significant)
                     and not capacity_gated)
    seed_gate: Optional[Dict[str, Any]] = None
    seed_gated = False
    if would_promote and not multi_seed_evidence:
        seed_gate = _multi_seed_gate(ledger, exp, ab_runner=ab_runner,
                                     promotions_root=promotions_root)
        seed_gated = seed_gate.get("status") != "win"
    promote = would_promote and not seed_gated
    verdict = {
        "promote": promote, "improved": improved, "stable": bool(stable),
        "capacity_gated": capacity_gated,
        "multi_seed_evidence": multi_seed_evidence,
        "seed_gated": seed_gated, "seed_gate": seed_gate,
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
        # Carry this run's spread onto the baseline so the NEXT candidate gets a
        # two-sample test instead of inheriting the point-estimate weakness.
        # Carry the winner's per-seed values too, so the NEXT candidate is compared PAIRED
        # at the same seeds instead of falling back to the weaker unpaired test.
        ledger.promote_baseline(exp.id, value, notes=exp.name, ts=ts,
                                metric_sem=None if sp is None else sp["sem"],
                                metric_sem_n=None if sp is None else sp["n"],
                                per_seed=([float(v) for v in cand_ps]
                                          if isinstance(cand_ps, (list, tuple)) and cand_ps
                                          else None))
        return {"experiment": exp.id, "state": SOTA, "verdict": verdict}

    if not improved:
        reason = "did not beat baseline"
    elif not stable:
        reason = "improved but unstable — held (rank-invariance)"
    elif not significant:
        reason = (f"improvement within noise — held ({sig_note})" if significant is False
                  else f"improvement unverifiable — held ({sig_note})")
    elif capacity_gated:
        reason = (f"capacity-gated — the swap deleted {-block_delta:,} of the replaced "
                  f"block's {replaced_params:,} parameters "
                  f"({-block_delta / replaced_params:.1%} > {CAPACITY_DELETE_FRAC:.0%} "
                  f"threshold); a fixed-step win by shrinkage may not ratchet the baseline")
    elif seed_gated:
        reason = (f"multi-seed gate — significance rests on within-run spread only "
                  f"('{sp['series']}' cannot see run-to-run variance, §5.3.R93) and "
                  f"{(seed_gate or {}).get('detail', 'no paired-seed evidence')}. "
                  f"Run promotions/{exp.id}/ab_nano.py on a training-capable box, or "
                  f"re-train with --seeds so per_seed is recorded")
    else:
        reason = "held"
    writeup = _writeup(exp, baseline, value, promoted=False, reason=reason,
                       significance=sig_note,
                       capacity="\n".join(x for x in (capacity_note, base_caveat) if x))
    ledger.transition(exp.id, REJECTED, eval_verdict=verdict, writeup=writeup, ts=ts)
    return {"experiment": exp.id, "state": REJECTED, "verdict": verdict, "reason": reason}
