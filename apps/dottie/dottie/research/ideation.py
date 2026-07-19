# Solo personal project, no connection to employer, built with public/free-tier only
"""Ideation worker (worker 1) — grounds the LLM in the real baseline and writes hypotheses.

Calls the real model (OllamaPolicy). If the model is unreachable it raises
``DottiePolicyUnavailable`` — it never invents a hypothesis. Dead ends (rejected / failed
experiments) are fed back into the prompt so the search does not repeat them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dottie.research import prompts
from dottie.research.ledger import (
    Ledger, FAILED_TRAINING, FAILED_VALIDATION, REJECTED,
)

# A Policy turns a prompt into a completion (OllamaPolicy.__call__). Raises on unavailability.
Policy = Callable[[str], str]


def dead_ends(ledger: Ledger, *, limit: int = 40) -> List[str]:
    """Names of hypotheses that were tried and failed — to steer ideation away from them."""
    names: List[str] = []
    for state in (REJECTED, FAILED_VALIDATION, FAILED_TRAINING):
        for exp in ledger.list(state=state, limit=limit):
            names.append(exp.name)
    # de-dup, keep order
    seen: set = set()
    out: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
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
    try:
        hyps = prompts.parse_hypotheses(text)   # ValueError on garbage propagates
    except ValueError as e:
        # Dump the raw completion so an unparseable shape is diagnosable tomorrow
        # instead of vanishing (two live failures were opaque before this).
        import os
        import time as _t
        log_dir = Path(os.environ.get("DOTTIE_RESEARCH_LOG_DIR", "data/research/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        dump = log_dir / f"ideation_raw_{int(ts or _t.time())}.txt"
        dump.write_text(text, encoding="utf-8")
        raise ValueError(f"{e} (raw completion saved to {dump})") from e
    created = [ledger.create(h, ts=ts) for h in hyps]
    return {"created": [e.id for e in created], "names": [e.name for e in created],
            "bottleneck": bottleneck}
