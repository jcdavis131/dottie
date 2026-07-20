# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie research loop — the continuous, hill-climbing automated research system.

Four workers form a closed loop over an experiment ledger (a real SQLite state machine):

    ideation      -> writes hypotheses            (state: pending)
    implementation-> code + 4-level validation     (pending      -> ready_for_training)
    train         -> real factory training run     (ready_for_training -> evaluation_pending)
    evaluate      -> paired hill-climb vs baseline  (evaluation_pending -> sota | rejected)

Anti-fabrication contract (repo-wide): every metric in the ledger is a REAL measurement or is
absent. The ideation/implementation workers call the real Ollama model and refuse honestly
(``DottiePolicyUnavailable``) when it is unreachable — they never invent a hypothesis or code.
The train worker wraps the factory's real training subprocess and refuses without a checkpoint
tree. The evaluator reuses the factory's rank-invariance gate (``dottie.climb``) and only
declares a new SOTA on a real, paired improvement. Failures are recorded honestly and fed back
to ideation so the search does not repeat a dead end.
"""

from dottie.research.ledger import (
    STATES,
    TERMINAL_STATES,
    Baseline,
    Experiment,
    IllegalTransition,
    Ledger,
    LedgerError,
)

__all__ = [
    "STATES",
    "TERMINAL_STATES",
    "Baseline",
    "Experiment",
    "IllegalTransition",
    "Ledger",
    "LedgerError",
]
