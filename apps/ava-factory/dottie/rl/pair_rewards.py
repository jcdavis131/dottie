# Solo personal project, no connection to employer, built with public/free-tier only
"""Pair-programming reward signal for Dottie's closed-loop RL (feeds grpo_collect.py).

This is the RL reward that makes "best pair programming assistant" trainable. Every
component is computed from MEASURED data — test outcomes, user actions, wall-clock
time, independent verifier scores — never from the policy's own claims.

Components (all bounded, GPU-free, stdlib-only):
  R_task    — task's own tests pass (0/1 or graded 0..1). The primary signal.
  R_noreg   — multiplicative gate: 0 if pre-existing tests regressed, 1 otherwise.
              A solution that passes its tests but breaks the suite gets zero task credit.
  R_accept  — user acceptance: explicit accept / edit / reject / revert, or implicit
              (kept-after-session vs reverted). Positive terms count only when the task
              actually succeeded; a rejection always counts (the user is always right
              about hating it).
  R_time    — wall-clock time-to-done vs a measured baseline (previous median for the
              task family). Faster than baseline is good; slower is a bounded penalty.
              Only meaningful when the task succeeded.
  R_quality — independent verifier score (NORTH_STAR gate: verifier >= 8.0) mapped to
              [-1, 1] as a tiebreaker among correct solutions. The verifier is a separate
              pipeline, never the policy grading its own homework.
  R_tok     — difficulty-scaled token penalty carried from codeact r_len: easy families
              snap to terse, hard families get budget. Bounded [-1, 0], can never overturn
              the task term.

Task-dominance invariant: w_task = 1.0 and the sum of all other |weights| is kept
below 1.0, AND grpo_collect should rank by (task_ok, total) — a correct solution
always outranks any wrong one. See ReturnWeights docstring.

Contract note: packages/dottie-loop/dottie_loop/reward.py implements the same
formula and anti-hacking rules as the spec contract, but with different
component scalings ([0,1] with None-for-missing; quality=(score-1)/9). This
module's [-1,1] centered components (reject/revert=-1, quality centered on the
8.0 gate, difficulty-scaled token penalty) are pinned by
apps/ava-factory/tests/test_pair_rewards.py — do not "unify" them by
delegation without a deliberate, tested respec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


# ── trace record ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PairTrace:
    """One measured pair-programming episode. All fields are observed, not inferred.

    task_passed:      0..1 graded fraction of the task's own tests passing (1.0 = all).
    regression:       True if any pre-existing (non-task) test broke during the episode.
    user_signal:      "accept" | "edit" | "reject" | "revert" | "kept" | "none".
                      Explicit UI signals preferred; "kept" = code still present after the
                      session (implicit accept); "revert" = user reverted the change;
                      "none" = no signal observed (stays neutral).
    edit_ratio:       0..1 — fraction of emitted lines the user subsequently changed.
                      Large edits downgrade an "accept" (they had to fix it themselves).
    seconds:          measured wall-clock time to task completion (0 if not completed).
    baseline_seconds: measured median time for this task family (must be > 0 to count).
    verifier_score:   independent verifier score, 0..10 (NORTH_STAR: >= 8.0 passes).
    tokens:           total tokens emitted in the episode.
    family_pass_rate: historical pass rate of the task family, 0..1 (difficulty scale).
    """

    task_passed: float = 0.0
    regression: bool = False
    user_signal: str = "none"
    edit_ratio: float = 0.0
    seconds: float = 0.0
    baseline_seconds: float = 0.0
    verifier_score: float = 0.0
    tokens: int = 0
    family_pass_rate: float = 0.5


# ── components ───────────────────────────────────────────────────────────────

def r_task_ok(trace: PairTrace) -> float:
    """Task term with the no-regression gate: graded pass, zeroed if the suite broke.

    Multiplicative, not additive — this is the anti-hack core: you cannot trade a
    broken codebase for a passing demo."""
    passed = min(1.0, max(0.0, trace.task_passed))
    return 0.0 if trace.regression else passed


_ACCEPT_TABLE: Dict[str, float] = {
    "accept": 1.0,
    "kept": 0.5,     # implicit: still there afterwards, but no explicit thumbs-up
    "edit": 0.5,     # accepted with modifications — half credit before edit penalty
    "none": 0.0,     # silence is neutral: never punish a user for not rating
    "reject": -1.0,
    "revert": -1.0,  # strongest negative: the user undid the work
}


def r_accept(trace: PairTrace) -> float:
    """User acceptance in [-1, 1].

    Positive signals count only when the task actually succeeded (an accept of broken
    code is politeness, not quality). Rejections always count — disliking the output
    is informative even when the tests happened to pass. Heavy user edits after an
    "accept" are penalized: if they rewrote half of it, it wasn't really accepted."""
    base = _ACCEPT_TABLE.get(trace.user_signal, 0.0)
    if base > 0 and r_task_ok(trace) <= 0.0:
        return 0.0  # accepted-but-broken: no positive credit
    if trace.user_signal == "accept":
        edit = min(1.0, max(0.0, trace.edit_ratio))
        return max(0.0, 1.0 - edit)  # accept + 50% rewritten => 0.5
    return base


def r_time(trace: PairTrace) -> float:
    """Time-to-done vs measured baseline, in [-1, 1].

    2x faster than baseline => +0.5; at baseline => 0; 2x slower => -0.5, floored at -1.
    Only meaningful on success (fast failure is not a virtue) and only when a real
    baseline exists (baseline_seconds > 0) — never divide by a missing number."""
    if r_task_ok(trace) <= 0.0 or trace.seconds <= 0 or trace.baseline_seconds <= 0:
        return 0.0
    ratio = trace.seconds / trace.baseline_seconds
    return min(1.0, max(-1.0, 1.0 - ratio))


def r_quality(trace: PairTrace) -> float:
    """Independent verifier score mapped to [-1, 1], centered on the 8.0 gate.

    Only separates correct solutions (tiebreaker); a wrong solution gets no quality
    credit no matter how pretty. The verifier is a separate pipeline — the policy
    never grades its own homework."""
    if r_task_ok(trace) <= 0.0:
        return 0.0
    score = min(10.0, max(0.0, trace.verifier_score))
    return min(1.0, max(-1.0, (score - 8.0) / 2.0))


def r_tok(trace: PairTrace) -> float:
    """Difficulty-scaled token penalty in [-1, 0], carried from codeact r_len.

    Easy families (high historical pass rate) are penalized for verbosity; hard
    families get budget for deep derivations. Bounded so it can never overturn
    the task term."""
    rate = min(1.0, max(0.0, trace.family_pass_rate))
    return max(-1.0, -rate * (max(0, trace.tokens) / 512.0))


# ── blend ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PairWeights:
    """Blend weights. Task-dominance invariant: every non-task term is bounded to
    [-1, 1] and w_accept + w_time + w_quality + w_tok < w_task, so a correct
    solution always outranks a wrong one on the task term alone:

      min(correct) = 1.0 - (0.25+0.15+0.15+0.10) = 0.35
      max(wrong)   = 0.0 + (0.25+0.15+0.15+0.00) = 0.55  -- exceeds 0.35!

    The arithmetic alone does NOT guarantee dominance because wrong solutions can
    earn positive secondary terms (e.g. fast failure). So grpo_collect MUST rank
    pref pairs by (task_ok, total) — the tuple key in rank_key() — not by total
    alone. Keep w_accept + w_time + w_quality + w_tok < w_task when retuning."""

    w_task: float = 1.0
    w_accept: float = 0.25
    w_time: float = 0.15
    w_quality: float = 0.15
    w_tok: float = 0.10


def pair_return(trace: PairTrace, weights: PairWeights = PairWeights()) -> Dict[str, float]:
    """Blend components into a scalar reward. Returns the full breakdown plus total.

    Keys: r_task, r_accept, r_time, r_quality, r_tok, total. All in documented bounds."""
    comps = {
        "r_task": r_task_ok(trace),
        "r_accept": r_accept(trace),
        "r_time": r_time(trace),
        "r_quality": r_quality(trace),
        "r_tok": r_tok(trace),
    }
    total = (
        weights.w_task * comps["r_task"]
        + weights.w_accept * comps["r_accept"]
        + weights.w_time * comps["r_time"]
        + weights.w_quality * comps["r_quality"]
        + weights.w_tok * comps["r_tok"]
    )
    comps["total"] = total
    return comps


def task_ok(trace: PairTrace) -> int:
    """Binary task success for ranking: 1 if graded pass and no regression, else 0."""
    return 1 if r_task_ok(trace) > 0.0 else 0


def rank_key(trace: PairTrace, weights: PairWeights = PairWeights()) -> Tuple[int, float]:
    """Ranking key for grpo_collect pref-pair selection: (task_ok, total).

    Task success dominates; the blended total only orders within the same tier.
    This is what makes the dominance invariant real instead of aspirational."""
    return (task_ok(trace), pair_return(trace, weights)["total"])


def to_telemetry(trace: PairTrace, weights: PairWeights = PairWeights(),
                 extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Emit a grpo_collect-compatible telemetry row for one episode.

    grpo_collect reads rl_return (falls back to reward/score); we also ship the
    component breakdown so MANIFESTs and reports stay auditable."""
    comps = pair_return(trace, weights)
    row: Dict[str, Any] = {
        "rl_return": comps["total"],
        "verdict": "pass" if task_ok(trace) else "fail",
        "reward_components": {k: round(v, 4) for k, v in comps.items()},
        "task_ok": task_ok(trace),
        "user_signal": trace.user_signal,
        "regression": trace.regression,
    }
    if extra:
        row.update(extra)
    return row
