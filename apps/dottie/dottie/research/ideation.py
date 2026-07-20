# Solo personal project, no connection to employer, built with public/free-tier only
"""Ideation worker (worker 1) — grounds the LLM in the real baseline and writes hypotheses.

Calls the real model (OllamaPolicy). If the model is unreachable it raises
``DottiePolicyUnavailable`` — it never invents a hypothesis. Dead ends (rejected / failed
experiments) are fed back into the prompt so the search does not repeat them.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dottie.research import prompts
from dottie.research.ledger import (
    Ledger, FAILED_TRAINING, FAILED_VALIDATION, REJECTED,
)

# A Policy turns a prompt into a completion (OllamaPolicy.__call__). Raises on unavailability.
Policy = Callable[[str], str]


def _name_key(name: str) -> tuple:
    """Lexical identity of a hypothesis name, ignoring acronyms and word order.

    Exact-match de-dup let "Orthogonalized Sparse Attention (OSA)" and "Orthogonalized
    Sparse Attention" both occupy slots in the 20 shown to the model (measured 2026-07-20:
    2 wasted slots of 20). Stripping the parenthetical and comparing word sets collapses
    them."""
    return tuple(sorted(re.findall(r"[a-z]+", re.sub(r"\(.*?\)", "", name.lower()))))


def dead_ends(ledger: Ledger, *, limit: int = 40) -> List[str]:
    """Names of hypotheses that were tried and failed — to steer ideation away from them.

    ``ledger.list`` orders by ``created_ts DESC``, so taking the head of this returns the
    model's OWN most recent ideas — maximally similar to whatever mode it is currently in.
    Interleaving across the three failure states and de-duplicating lexically keeps the
    sample broader; ``prompts._failed_block`` additionally names the overused vocabulary
    outright, because a list of near-identical names under a "do not repeat" heading reads
    as a 20-shot demonstration of exactly that vocabulary (TODOS §5.3.R24)."""
    per_state = [ledger.list(state=state, limit=limit)
                 for state in (REJECTED, FAILED_VALIDATION, FAILED_TRAINING)]
    seen: set = set()
    out: List[str] = []
    # Round-robin so one state cannot fill every visible slot with its newest entries.
    for i in range(max((len(x) for x in per_state), default=0)):
        for bucket in per_state:
            if i >= len(bucket):
                continue
            name = bucket[i].name
            key = _name_key(name)
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


def run_ideation(ledger: Ledger, policy: Policy, *, bottleneck: str, n_ideas: int = 1,
                 search_space: Optional[List[str]] = None,
                 ts: Optional[float] = None) -> Dict[str, Any]:
    """Generate ``n_ideas`` hypotheses grounded in the real baseline; write them to the ledger.

    Raises ``DottiePolicyUnavailable`` (model down) or ``ValueError`` (unparseable output) — both
    honest failures the caller surfaces; nothing is fabricated."""
    baseline = ledger.get_baseline()
    prompt = prompts.ideation_prompt(
        baseline, bottleneck=bottleneck, search_space=search_space,
        failed_hypotheses=dead_ends(ledger), n_ideas=n_ideas,
    )
    text = policy(prompt)                       # DottiePolicyUnavailable propagates
    retried = False
    while True:
        try:
            hyps = prompts.parse_hypotheses(text)   # ValueError on garbage propagates
            break
        except ValueError as e:
            dump = _dump_raw(text, ts)
            if retried:
                # One corrective re-ask is the budget; after that the failure is honest.
                raise ValueError(f"{e} (raw completion saved to {dump})") from e
            # Content-level failures dominate at temperature 0.9 (missing required
            # keys, observed live) — hand the model its exact error once, the same
            # discipline the implementation worker uses.
            retried = True
            text = policy(
                f"{prompt}\n\n# CORRECTION\nYour previous response could not be used: "
                f"{e}. Respond again with ONLY the JSON array of hypothesis objects — "
                "EVERY schema key present and non-empty.")
    created = [ledger.create(h, ts=ts) for h in hyps]
    return {"created": [e.id for e in created], "names": [e.name for e in created],
            "bottleneck": bottleneck, "retried": retried}


def _dump_raw(text: str, ts: Optional[float]) -> Path:
    """Save an unparseable completion so failures stay diagnosable (never vanish)."""
    import os
    import time as _t
    import uuid
    log_dir = Path(os.environ.get("DOTTIE_RESEARCH_LOG_DIR", "data/research/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    # uuid suffix: two failures in the same second must not clobber each other
    # (caught by the retry test — a real live-dump hazard too).
    dump = log_dir / f"ideation_raw_{int(ts or _t.time())}_{uuid.uuid4().hex[:6]}.txt"
    dump.write_text(text, encoding="utf-8")
    return dump
