# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct → MOPD consolidation trace-pool prep (spec 13 T13C.5, GPU-free half).

After the agentic specialist climbs, its verified CodeAct trajectories join the MOPD trace pool
(`docs/DISTILLATION_INTEGRATION.md`) so the *unified* model retains code-as-action after the
code/math/chat merge. This module builds that pool as **data** — the GPU-free preparation step — so
the actual `on_policy_distill.py --mode mopd` run (GPU, gated) can consume a clean, balanced corpus.

Two rules distinguish this from spec-12's *recovery* sampling (which was uniform, to maximize prompt
diversity when rebuilding a collapsed checkpoint):

  • **Only verified trajectories are admitted.** A trace whose FINAL did not exec-verify to its gold
    answer is dropped — a code interpreter that merges *unverified* code-as-action would teach the
    unified model to trust code that doesn't run. `admit_trace` enforces this; the caller cannot
    bypass it.
  • **Stratified, not uniform.** Consolidation must *retain every capability* across the merge, so
    the pool is balanced across families/concepts: the rare grounding families (recover, tool-
    grounding — the "the output contradicted my assumption, re-plan" behavior) must not be washed
    out by the common compute family. `consolidate` dedupes by prompt, then stratifies to an even
    per-family target.

The safety obligation from the spec (a code interpreter is an attack surface — `safety_blackmail`
0/180 must hold post-consolidation) is a property of the *downstream trained model*, verified by the
existing safety eval after the gated MOPD run — not something this data-prep step can assert. What it
CAN do is carry a `refuse` label through so "refuse to run this" trajectories are representable in
the pool; the actual safety hold is checked by `evals` on the merged checkpoint.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ConsolidationTrace:
    """A verified CodeAct trajectory prepared for the MOPD pool.

    `verified` MUST be the real exec-verification outcome (final sandbox value == gold answer) — the
    caller computes it via `evals.codeact_eval.score_emission`, this module does not take it on
    faith beyond admitting it. `family` is the datagen concept (e.g. `codeact_recover`); `behavior`
    ∈ {'solve','refuse'} lets the rare 'refuse to run this' safety trajectories be counted and kept."""
    prompt: str
    rendered: str                 # the full transcript (turns + observations) to distill on
    answer: str
    family: str
    verified: bool
    behavior: str = "solve"       # 'solve' | 'refuse'
    step: int = 0


def admit_trace(trace: ConsolidationTrace) -> bool:
    """A trace may enter the pool iff it exec-verified. Unverified code-as-action is never merged
    (it would teach the unified model to trust code that doesn't run)."""
    return trace.verified


@dataclass(frozen=True)
class ConsolidationPool:
    """The prepared MOPD trace pool + a manifest of what it contains (for logging / provenance)."""
    traces: List[ConsolidationTrace]
    per_family: Dict[str, int]
    dropped_unverified: int
    dropped_duplicate: int

    def __len__(self) -> int:
        return len(self.traces)


def _dedupe_by_prompt(traces: Sequence[ConsolidationTrace]
                      ) -> Tuple[List[ConsolidationTrace], int]:
    """Keep the first trace per (prompt) — prompt diversity over per-prompt volume. Deterministic:
    preserves input order. Returns (deduped, n_dropped)."""
    seen = set()
    out: List[ConsolidationTrace] = []
    dropped = 0
    for t in traces:
        if t.prompt in seen:
            dropped += 1
            continue
        seen.add(t.prompt)
        out.append(t)
    return out, dropped


def consolidate(traces: Sequence[ConsolidationTrace], *,
                per_family_cap: Optional[int] = None,
                balance: bool = True) -> ConsolidationPool:
    """Build the MOPD pool: drop unverified, dedupe by prompt, then (optionally) stratify by family.

    Stratification (`balance=True`) caps every family at the same size so no capability dominates or
    vanishes. The cap is `per_family_cap` if given, else the size of the *smallest* non-empty family
    (an even split — the strictest anti-washout choice). `balance=False` keeps all verified, deduped
    traces (no cap) for callers that want the raw pool. Deterministic given input order.

    This is data prep only — the KL-distillation MOPD run that consumes the pool is GPU-gated
    (`on_policy_distill.py --mode mopd`); see `mopd_consolidation_run` below for the honest gate."""
    verified = [t for t in traces if admit_trace(t)]
    dropped_unverified = len(traces) - len(verified)

    deduped, dropped_duplicate = _dedupe_by_prompt(verified)

    by_family: Dict[str, List[ConsolidationTrace]] = defaultdict(list)
    for t in deduped:
        by_family[t.family].append(t)

    if balance and by_family:
        cap = per_family_cap if per_family_cap is not None else min(
            len(v) for v in by_family.values())
        selected: List[ConsolidationTrace] = []
        for family in sorted(by_family):
            selected.extend(by_family[family][:cap])
    elif per_family_cap is not None:
        selected = []
        for family in sorted(by_family):
            selected.extend(by_family[family][:per_family_cap])
    else:
        selected = deduped

    per_family = defaultdict(int)
    for t in selected:
        per_family[t.family] += 1
    return ConsolidationPool(traces=selected, per_family=dict(per_family),
                             dropped_unverified=dropped_unverified,
                             dropped_duplicate=dropped_duplicate)


class ConsolidationBlockedError(RuntimeError):
    """Raised when the real (GPU) MOPD distillation run is invoked from here."""


def mopd_consolidation_run(pool: ConsolidationPool, *args, **kwargs):
    """The MOPD distillation run that consumes the pool — INTENTIONALLY GATED. It is
    `on_policy_distill.py --mode mopd` (student generates rollouts, teachers grade token-level
    reverse-KL): a real multi-GB checkpoint + GPU job (BLOCKED_NO_GPU), and it needs the branch
    specialists (T9.3/T9.5) that do not exist. This function prepares nothing new — the pool is the
    deliverable — it exists to make the boundary explicit and refuse rather than fake a merge."""
    raise ConsolidationBlockedError(
        "MOPD consolidation run is gated: it is on_policy_distill.py --mode mopd (student rollouts + "
        "teacher token-level reverse-KL), needing branch specialist checkpoints (T9.3/T9.5, absent) "
        f"and a GPU (BLOCKED_NO_GPU). The trace pool ({len(pool)} traces) is prepared and ready; run "
        "the merge once checkpoints exist. safety_blackmail 0/180 is verified on the MERGED model by "
        "evals, not assertable at data-prep time."
    )
