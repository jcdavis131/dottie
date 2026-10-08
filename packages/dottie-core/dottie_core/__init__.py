# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""dottie-core: agent = model + harness, clean-room.

The model is a pure decision function: state in, scored answer out. The harness
owns lifecycle, policy, cost, HITL, verification, and recording — all in
deterministic code, never in prompts.
"""

from dottie_core.state import Belief, Constraints, StateRef, WorldState, empty_state
from dottie_core.model import Model, QueryKind, ScoredAnswer, ScoredValue, TypedQuery
from dottie_core.heuristic import HeuristicModel
from dottie_core.policy import Policy, default_policy
from dottie_core.harness import Goal, Harness, RunResult

__all__ = [
    "Belief", "Constraints", "StateRef", "WorldState", "empty_state",
    "Model", "QueryKind", "ScoredAnswer", "ScoredValue", "TypedQuery",
    "HeuristicModel", "Policy", "default_policy",
    "Goal", "Harness", "RunResult",
]
__version__ = "0.1.0"
