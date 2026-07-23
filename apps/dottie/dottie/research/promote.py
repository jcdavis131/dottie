# Solo personal project, no connection to employer, built with public/free-tier only
"""SOTA promotion bundles — the human-gated bridge from the research loop to the factory.

When an experiment reaches ``sota`` the loop has PROVEN (real training, real held-out
measurement) that its module beats the baseline at nano scale. This module turns that
proof into a reviewable promotion bundle under ``<data_dir>/research/promotions/<id>/``:

    candidate.py        the exact validated module that earned the metric
    PROMOTION.md        the evidence: hypothesis, measured metrics vs baseline, provenance
    ab_nano.py          a runnable A/B script (candidate vs unmodified) for re-verification

NOTHING is auto-applied to the factory model. A human reads PROMOTION.md, reruns
ab_nano.py if they wish, and only then wires the block into model_1b presets. The
bundle generator refuses honestly when the experiment is not sota or its workspace
module is missing — a promotion without its exact artifact would be provenance theater.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dottie.research.ledger import SOTA, Ledger, LedgerError

_AB_TEMPLATE = '''# Auto-generated A/B re-verification for research promotion {exp_id}.
#
# Runs the SAME factory nano recipe on the unmodified model and on the candidate, over
# several seeds, and applies the SAME noise standard the loop's own evaluation gate uses.
# Requires torch + AVA_FACTORY_ROOT + the packed corpus.
#
# Why seeds and not one run each: comparing two single numbers cannot tell a real
# difference from run-to-run noise. That is exactly the mistake that produced this loop's
# first false SOTA, and a re-verification script that repeats it is worse than none --
# it launders a coin flip as confirmation. Cost is len(SEEDS) x 2 training runs
# (~{steps} steps each); lower SEEDS only if you accept a weaker answer.
import statistics

from dottie.research.factory_trainer import run_baseline_calibration, factory_nano_trainer
from dottie.research.ledger import Ledger

STEPS = {steps}
SEEDS = [0, 1, 2]
LEDGER = r"{ledger_path}"
EXP_ID = "{exp_id}"

try:                                      # the trainer needs the Experiment, not a path
    exp = Ledger(LEDGER).get(EXP_ID)      # NB: get() RAISES for an unknown id, never None
except Exception as _e:
    raise SystemExit(f"experiment {{EXP_ID}} not found in {{LEDGER}}: {{_e}}")

base, cand = [], []
for seed in SEEDS:
    b = run_baseline_calibration({{"steps": STEPS, "seed": seed}})
    r = factory_nano_trainer(exp, {{"steps": STEPS, "seed": seed}})
    if not (r.ok and r.stable):
        raise SystemExit(f"candidate failed to train at seed {{seed}}: {{r.detail}}")
    bv, cv = b["factory_lm_loss"], r.metrics["factory_lm_loss"]
    base.append(bv)
    cand.append(cv)
    print(f"seed {{seed}}: unmodified {{bv:.5f}}  candidate {{cv:.5f}}  delta {{cv - bv:+.5f}}")

diffs = [c - b for c, b in zip(cand, base)]
mean_d = statistics.fmean(diffs)
# PAIRED differences: same seed both sides, so shared run-to-run variance cancels.
sem_d = (statistics.stdev(diffs) / len(diffs) ** 0.5) if len(diffs) > 1 else float("nan")
print()
print(f"unmodified mean {{statistics.fmean(base):.5f}}   candidate mean {{statistics.fmean(cand):.5f}}")
print(f"paired delta    {{mean_d:+.5f}}   SEM {{sem_d:.5f}}   (lower is better)")
if len(diffs) > 1 and abs(mean_d) >= 2.0 * sem_d:
    print("VERDICT:", "candidate is BETTER beyond noise" if mean_d < 0
          else "candidate is WORSE beyond noise")
else:
    print("VERDICT: WITHIN NOISE - this run does not distinguish the candidate from the "
          "unmodified model. Do not promote on it.")
'''



def write_ab_script(ledger: Ledger, exp_id: str, *, out_root: str | Path) -> Path:
    """Write JUST ab_nano.py for an experiment — deliberately WITHOUT the sota requirement.

    ``build_promotion`` refuses non-sota experiments by design, but the evaluator's hard
    multi-seed gate needs this script BEFORE any sota transition: since operator order B0
    the paired-seed A/B is what decides whether that transition happens at all. Same
    template, same ``<out_root>/<exp_id>/`` location, so a later full bundle build simply
    overwrites it in place."""
    try:
        exp = ledger.get(exp_id)
    except LedgerError as e:
        raise ValueError(f"unknown experiment {exp_id!r}") from e
    metrics = exp.train_metrics or {}
    steps = int((metrics.get("config") or {}).get("steps", 150)) if isinstance(
        metrics.get("config"), dict) else 150
    out = Path(out_root) / exp_id
    out.mkdir(parents=True, exist_ok=True)
    script = out / "ab_nano.py"
    script.write_text(
        # ledger_path, not module_path: factory_nano_trainer takes an Experiment (it reads
        # .implementation and .workspace off it). The old template passed the module path as
        # that argument, so every generated ab_nano.py raised AttributeError on its first
        # candidate call — the re-verification step had never actually run (§5.3.R32).
        _AB_TEMPLATE.format(exp_id=exp_id, steps=steps,
                            ledger_path=str(Path(ledger.path).resolve())),
        encoding="utf-8")
    return script


def _caveat_block(verdict: Dict[str, Any]) -> List[str]:
    """Everything qualifying this result, ABOVE the numbers rather than inside a JSON dump.

    The bundle is the artifact a human reads to decide whether to promote. It already
    contained the full `eval_verdict`, so the caveats were technically present — buried in a
    JSON blob under a header that said only "see eval_verdict below". A warning that the
    baseline is contaminated, or that the win is inside the noise, or that the block simply
    removed capacity, is not a footnote: it is the reason not to promote. Measured
    2026-07-20 (TODOS §5.3.R31): none of `baseline_provenance`, `baseline_caveat`,
    `significance` or `capacity_caveat` appeared anywhere in the rendered prose.

    Returns [] when a verdict is genuinely clean, so an honest result is not padded with
    reassurance it did not earn."""
    lines: List[str] = []
    prov = verdict.get("baseline_provenance")
    caveat = verdict.get("baseline_caveat")
    if caveat or (prov and prov != "promoted"):
        lines.append(f"> **BASELINE CAVEAT** (provenance: `{prov}`) — "
                     f"{(caveat or 'no detail recorded').strip()}")
    if verdict.get("significant") is None:
        lines.append("> **SIGNIFICANCE UNMEASURABLE** — no per-batch series was recorded, so "
                     "this delta was never tested against noise.")
    elif verdict.get("significant") is False:
        lines.append(f"> **WITHIN NOISE** — {verdict.get('significance', '')}")
    if verdict.get("capacity_caveat"):
        lines.append(f"> **CAPACITY CHANGE** — {verdict['capacity_caveat']}")
    sig = verdict.get("significance") or ""
    if "candidate-only SEM" in sig:
        lines.append("> **WEAK SIGNIFICANCE TEST** — the baseline records no spread, so it "
                     "was treated as an exact point; the real bar is higher than it looks.")
    # The R93 miss surfaced here, not just in the significance prose. A verdict whose spread
    # came from a SINGLE run's batches cannot see run-to-run variance — the variance that
    # actually decides these calls. Keyed off the structured field, not the prose, so a
    # reworded significance string can never silently drop this warning.
    from dottie.research.evaluate import _WITHIN_RUN_SERIES
    if verdict.get("sem_series") in _WITHIN_RUN_SERIES:
        lines.append("> **WITHIN-RUN SPREAD ONLY** — significance rests on one run's "
                     "batch-to-batch noise, which is BLIND to run-to-run variance (TODOS "
                     "§5.3.R93: a candidate cleared this bar at 4.4 SEM and was then worse at "
                     "every seed). Run `ab_nano.py` in this bundle before promoting.")
    if not lines:
        return []
    return ["> ### Read this before promoting", *lines, ""]


def build_promotion(ledger: Ledger, exp_id: str, *, out_root: str | Path,
                    ts: Optional[float] = None) -> Dict[str, Any]:
    """Write the bundle for a sota experiment. Raises ValueError on a non-sota
    experiment or a missing workspace module (honest refusals, not empty bundles)."""
    # Ledger.get() RAISES LedgerError for an unknown id — it never returns None, so the
    # old `if exp is None` was dead code and the caller got a LedgerError instead of this
    # module's honest refusal (TODOS 5.3.R54).
    try:
        exp = ledger.get(exp_id)
    except LedgerError as e:
        raise ValueError(f"unknown experiment {exp_id!r}") from e
    if exp.state != SOTA:
        raise ValueError(f"experiment {exp_id} is {exp.state!r}, not sota — only proven "
                         "winners get promotion bundles")
    impl = exp.implementation or {}
    code = impl.get("code")
    if not code:
        raise ValueError(f"experiment {exp_id} has no recorded implementation code")

    b = ledger.get_baseline()
    metrics = exp.train_metrics or {}

    out = Path(out_root) / exp_id
    out.mkdir(parents=True, exist_ok=True)
    module_path = out / "candidate.py"
    module_path.write_text(code, encoding="utf-8")

    hyp = exp.hypothesis or {}
    md = [
        f"# Research promotion — {hyp.get('hypothesis_name', exp_id)}",
        "",
        *_caveat_block(exp.eval_verdict or {}),
        f"- experiment: `{exp_id}`  |  state: **sota**  |  generated: "
        f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(ts or time.time()))}",
        f"- metric: `{b.metric_name}` — candidate **{metrics.get(b.metric_name)}** vs "
        f"baseline-at-evaluation (see eval_verdict below); lower is "
        f"{'worse' if b.higher_is_better else 'better'}",
        "",
        "## Hypothesis",
        str(hyp.get("theoretical_intuition", "(none recorded)")),
        "",
        "## Measured",
        "```json", json.dumps(metrics, indent=2, default=str), "```",
        "## Verdict",
        "```json", json.dumps(exp.eval_verdict or {}, indent=2, default=str), "```",
        "",
        "## Next steps (HUMAN-GATED — nothing here is auto-applied)",
        f"1. Re-verify: `python {out.name}/ab_nano.py` (factory checkout + packed corpus).",
        "2. If it reproduces, wire the block into the target preset the same way",
        "   `deltanet_layers` swaps a fusion block, behind a config gate.",
        "3. Gate the preset change through the eval harness before ANY promotion to serve.",
    ]
    (out / "PROMOTION.md").write_text("\n".join(md), encoding="utf-8")
    write_ab_script(ledger, exp_id, out_root=out_root)
    return {"experiment": exp_id, "bundle": str(out),
            "files": ["candidate.py", "PROMOTION.md", "ab_nano.py"]}


def build_pending_promotions(ledger: Ledger, *, out_root: str | Path,
                             rebuild: bool = False) -> Dict[str, Any]:
    """Bundle every sota experiment that has no bundle yet. Returns a summary.

    ``rebuild=True`` regenerates bundles that already exist. Without it, a bundle written
    once is frozen forever — so every later fix to the bundle format silently fails to
    reach the artifacts a human actually reads. Measured 2026-07-20 (§5.3.R33): both
    existing bundles predated the caveat block AND carried the broken `ab_nano.py`, and
    `promote` reported them as `already_bundled` rather than repairing them. The bundle is
    derived entirely from the ledger, so regenerating it loses nothing."""
    out_root = Path(out_root)
    built, skipped = [], []
    for exp in ledger.list(state=SOTA):
        if not rebuild and (out_root / exp.id / "PROMOTION.md").exists():
            skipped.append(exp.id)
            continue
        try:
            built.append(build_promotion(ledger, exp.id, out_root=out_root))
        except ValueError as e:
            skipped.append(f"{exp.id}: {e}")
    return {"built": built, "already_bundled": skipped}
