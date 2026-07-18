# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct EG-gated rollout (spec 13 T13C.6) — a thin adapter over `efficiency_gain.eg_trend`.

Like every lever in this repo (spec 12 T12R.4), CodeAct only advances if it beats the *non-CodeAct
agentic baseline* on Efficiency Gain across two ladder rungs (nano, mini) — a single-rung win is the
rank-invariance trap the MAI finding warns about, so `eg_trend`'s promotion rule (every rung EG > 1
AND the largest rung is not the worst) is reused unchanged.

The one adaptation CodeAct needs: `efficiency_gain.py` is loss-based (loss = a·compute^−b, lower is
better), but CodeAct's quality metric is the T13C.3 **exec-verified success rate** (higher is
better). We map it to an *error rate* `1 − success_rate` (lower is better, with an irreducible
floor), which is the quantity that behaves like a loss and has a well-defined EG. Everything else —
the power-law fit, the compute-equivalence, the ladder verdict — is the existing, tested machinery.

Honesty boundary: the *math* here is real and tested on synthetic ladders. Producing a **real
verdict** needs numbers that do not exist — the CodeAct success rates (T13C.3 `run_codeact_eval`
currently fails honestly, gated on a checkpoint + GPU) and the baseline agentic-mode curve (its own
gated runs). `codeact_eg_gate_from_eval` refuses when handed the honest-fail eval records rather
than inventing a rate, so the gate can never emit a promote/hold verdict off fabricated capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from efficiency_gain import EGResult, efficiency_gain, eg_trend, fit_power_law


@dataclass(frozen=True)
class RungLadder:
    """One ladder rung's CodeAct-vs-baseline comparison, in *success-rate* space (higher better).

    `baseline_points` is the non-CodeAct agentic mode's (compute, success_rate) curve at this rung
    — the scaling reference CodeAct is measured against. `codeact_*` is the CodeAct candidate at the
    same rung. All success rates ∈ [0, 1]; compute in any consistent unit (FLOPs / tokens / GPU-h)."""
    rung: str
    baseline_points: List[Tuple[float, float]]      # [(compute, success_rate), ...]
    codeact_compute: float
    codeact_success_rate: float


def success_to_error(success_rate: float, *, error_floor: float = 0.0) -> float:
    """Map success rate (higher better) → error rate (lower better), clamped to [error_floor, 1].

    `error_floor` is the irreducible error (tasks unsolvable in the frozen set) — the EG floor below
    which no amount of compute reaches, exactly as `PowerLawFit.floor` models it. A perfect rate
    (error at/below the floor) is not a valid EG candidate (compute-to-reach is undefined there);
    the underlying `efficiency_gain` raises an informative error, which we let surface rather than
    swallow."""
    err = 1.0 - success_rate
    return err if err > error_floor else error_floor


def codeact_eg_gate(ladders: Sequence[RungLadder], *, error_floor: float = 0.0) -> Dict:
    """Compose per-rung EG (CodeAct vs baseline) into the ladder verdict via `eg_trend`.

    For each rung: fit the baseline error-vs-compute power law, then compute the CodeAct candidate's
    EG = (baseline compute to reach CodeAct's error) / (CodeAct's compute). `eg_trend` then applies
    the rank-invariance promotion rule across rungs. Pure over its inputs — the numbers may be
    synthetic (tests) or real (a future climb); this function does not care where they came from,
    which is exactly why it must never be fed fabricated rates (see `codeact_eg_gate_from_eval`)."""
    rung_results: List[Tuple[str, EGResult]] = []
    for lad in ladders:
        pts = [(c, success_to_error(sr, error_floor=error_floor)) for c, sr in lad.baseline_points]
        fit = fit_power_law(pts, floor=error_floor)
        eg = efficiency_gain(
            fit, lad.codeact_compute,
            success_to_error(lad.codeact_success_rate, error_floor=error_floor),
            label=lad.rung,
        )
        rung_results.append((lad.rung, eg))
    verdict = eg_trend(rung_results)
    verdict["mode"] = "codeact_vs_agentic_baseline"
    return verdict


class CodeActEGGateBlockedError(RuntimeError):
    """Raised when the EG gate is asked for a real verdict but the capability numbers don't exist."""


def codeact_eg_gate_from_eval(eval_records: Dict[str, Dict], *args, **kwargs):
    """Build the real EG verdict from per-rung `run_codeact_eval` records — or refuse if they are
    the honest-fail records (measured is None), which they are today.

    `eval_records` maps rung → a `run_codeact_eval` output. Because `run_codeact_eval` is gated on a
    branch fine-tune checkpoint (T9.3/T9.5) + GPU (BLOCKED_NO_GPU), every record's `measured` is
    None, so this refuses. It also needs the baseline agentic-mode curve (its own gated runs), which
    is why even non-None CodeAct rates alone would be insufficient. This is the honest terminal
    state of the T13C.6 wiring: the adapter is built and tested; the verdict waits on real runs."""
    missing = [rung for rung, rec in eval_records.items() if rec.get("measured") is None]
    if missing:
        raise CodeActEGGateBlockedError(
            "CodeAct EG gate cannot produce a real verdict: the CodeAct success rates are gated "
            f"(rungs {missing} returned measured=None — run_codeact_eval is BLOCKED_NO_GPU / needs a "
            "branch checkpoint T9.3/T9.5), and the non-CodeAct agentic baseline curve needs its own "
            "gated runs. The adapter (codeact_eg_gate) is built and tested on synthetic ladders; the "
            "verdict waits on the real climb — do not fabricate rates to force a promote/hold."
        )
    raise CodeActEGGateBlockedError(
        "CodeAct EG gate: CodeAct rates present, but the non-CodeAct agentic baseline scaling curve "
        "is still required (its own gated runs). Assemble RungLadder objects with real baseline "
        "points and call codeact_eg_gate() directly once both sides exist."
    )
