# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct return terms (spec 13 T13C.4) — pure reward-component functions over execution logs.

These consume the `Observation`s that the T13C.1 `Sandbox` produces for a trajectory and compute
the CodeAct-specific components that extend spec 12's `rl_return`:

  R_exec    — fraction of emitted code blocks that executed without an uncaught error. Penalizes
              "narrated"/hallucinated code that doesn't run. MUST be secondary to R_task (guarded by
              the weight and by the bounded blend below).
  R_codeuse — rewards distinct tool calls, penalizes DUPLICATED calls (same tool+args seen more
              than once across the trajectory, error-free retries excepted) — the MAI tool-use
              finding. Bounded to [-1, 1].
  R_len     — difficulty-scaled length penalty carried from spec 12: easy families (high historical
              pass rate) get a severe penalty (snap to a terse program), hard families a relaxed one.
              Bounded below so it can never overturn R_task (the blend keeps |w_len·R_len| < w_task).

These are GPU-free and fully testable. The GRPO loop that *consumes* them (T13C.4 wiring into
`ava/rl/grpo.py`) stays blocked on branch fine-tunes (T9.3/T9.5); this module is the reusable,
verified building block it will call. Naming per the spec-12 guard: `rl_return`/`R_*`, metrics
namespaced `rl.codeact.*`; `reward` remains the data-quality filter score elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from ava.rl.codeact_sandbox import Observation


def r_exec(observations: Sequence[Observation]) -> float:
    """Fraction of blocks that executed cleanly, in [0, 1]. Empty → 0.0 (nothing ran)."""
    if not observations:
        return 0.0
    return sum(1 for o in observations if o.ok) / len(observations)


def _flatten_calls(observations: Sequence[Observation]) -> List[Tuple]:
    """Tool calls flattened to hashable (tool, args, kwargs) tuples, in execution order.

    A call made on a step that ERRORED is skipped: re-issuing an identical call after a transient
    failure is a legitimate retry, not redundancy, so it should not be penalized."""
    calls: List[Tuple] = []
    for o in observations:
        if not o.ok:
            continue
        for c in o.tool_calls:
            args = tuple(c.get("args", []) or [])
            kwargs = tuple(sorted((c.get("kwargs") or {}).items()))
            calls.append((c.get("tool"), args, kwargs))
    return calls


def redundant_calls(observations: Sequence[Observation]) -> int:
    """Number of DUPLICATE tool calls — every occurrence of a (tool, args, kwargs) beyond its first.

    Counts over the whole trajectory (a multiset), not just adjacent pairs, so interleaved
    repetition (A,B,A,B) is caught, not just consecutive (A,A)."""
    calls = _flatten_calls(observations)
    return len(calls) - len(set(calls))


def r_codeuse(observations: Sequence[Observation]) -> float:
    """Tool-use quality in [-1, 1]. No successful tool use → 0.0 (neutral). All-distinct → 1.0;
    fully-duplicated → −1.0. A single distinct call is dampened toward neutral (one call can't
    demonstrate 'independent tool use'); distinct calls are rewarded by not being penalized."""
    calls = _flatten_calls(observations)
    if not calls:
        return 0.0
    if len(calls) == 1:
        return 0.5   # one call: mildly positive, but not the full 'independent tool use' reward
    dup = len(calls) - len(set(calls))           # duplicates beyond the first occurrence
    # Normalize by the max possible duplicates (len-1) so all-distinct → 1.0 and fully-duplicated
    # → exactly -1.0 (the floor is reachable, and n=2 identical is a real -1.0, not a toothless 0).
    return max(-1.0, 1.0 - 2.0 * dup / (len(calls) - 1))


def r_len(token_count: int, family_pass_rate: float, *, scale: float = 512.0) -> float:
    """Difficulty-scaled length penalty (≤ 0), carried from spec 12.

    The penalty *weight* is proportional to the family's historical pass rate: an easy family
    (pass_rate → 1) is penalized severely for length (snap to a terse program); a hard family
    (pass_rate → 0) is barely penalized (budget for a deep derivation). `scale` is the token count
    at which an easy family incurs a unit penalty — a training knob, not a measured constant.
    """
    pass_rate = min(1.0, max(0.0, family_pass_rate))
    # Bounded below at -1.0 (mirrors r_codeuse): with w_len < w_task the length term can never
    # overturn a correct answer, so the task-dominance invariant holds for arbitrarily long code.
    return max(-1.0, -pass_rate * (max(0, token_count) / scale))


@dataclass(frozen=True)
class ReturnWeights:
    """Blend weights. Task-dominance is now a real invariant, not just an intent: every non-task
    term is bounded to [-1, 1], and w_exec + w_codeuse (+ the length term's reach) is set below
    w_task, so a correct answer always outranks any wrong one regardless of code length.

    With the defaults: min(correct) = w_task·1 + w_exec·0 + w_codeuse·(-1) + w_len·(-1) = 0.7,
    max(wrong) = w_task·0 + w_exec·1 + w_codeuse·1 + w_len·0 = 0.4, so 0.7 > 0.4 always. Keep
    w_exec + w_codeuse + w_len < w_task if you retune (else the guarantee breaks)."""

    w_task: float = 1.0
    w_exec: float = 0.2
    w_codeuse: float = 0.2
    w_len: float = 0.1


def codeact_return(
    r_task: float,
    observations: Sequence[Observation],
    token_count: int,
    family_pass_rate: float,
    weights: ReturnWeights = ReturnWeights(),
) -> float:
    """Blend the CodeAct components into a scalar `rl_return` contribution.

    r_task is the verified-answer signal (0/1 or graded) owned by T12R.1 and passed in here.
    R_exec is deliberately weighted below R_task so a correct terse solution outranks lots of
    trivially-valid statements that don't solve the task.
    """
    return (
        weights.w_task * r_task
        + weights.w_exec * r_exec(observations)
        + weights.w_codeuse * r_codeuse(observations)
        + weights.w_len * r_len(token_count, family_pass_rate)
    )
