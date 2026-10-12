# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Model contract: the pure decision function.

Clean-room principle: the model takes state, returns a scored answer. No I/O,
no side effects, no tool calls, no memory beyond what the state carries. If the
model is pure, the entire harness is testable without any model, models are
swappable without touching harness code, and every decision replays from
(state, query) pairs.

Queries are typed (CLASSIFY/SCORE/CHOOSE/EXTRACT/VERIFY) — never free text.
The model never generates prose the harness must parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from dottie_core.state import StateRef


class QueryKind:
    CLASSIFY = "classify"  # state -> label from a fixed set
    SCORE = "score"  # state -> float in [0, 1]
    CHOOSE = "choose"  # state -> best of N options
    EXTRACT = "extract"  # state -> typed struct per schema
    VERIFY = "verify"  # (state, claim) -> supported | refuted | unknown

    ALL = (CLASSIFY, SCORE, CHOOSE, EXTRACT, VERIFY)


@dataclass(frozen=True)
class TypedQuery:
    """Everything the model needs to answer, nothing it doesn't."""

    kind: str
    state_ref: StateRef
    schema: dict[str, Any] = field(default_factory=dict)  # expected output shape
    options: tuple[str, ...] = ()  # for CHOOSE: candidate labels
    claim: str = ""  # for VERIFY: the claim to check

    def __post_init__(self) -> None:
        if self.kind not in QueryKind.ALL:
            raise ValueError(f"unknown query kind {self.kind!r}")
        if self.kind == QueryKind.CHOOSE and not self.options:
            raise ValueError("CHOOSE requires options")


@dataclass(frozen=True)
class ScoredValue:
    """One candidate answer with its calibrated probability of being correct."""

    value: Any
    confidence: float  # calibrated P(correct), 0..1

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")


@dataclass(frozen=True)
class ScoredAnswer:
    """The model's full response: best guess plus ranked alternatives."""

    best: ScoredValue
    alternatives: tuple[ScoredValue, ...] = ()
    query_id: str = ""
    model_id: str = ""
    calibration: str = "uncalibrated"  # or a description of the calibration method


class Model(Protocol):
    """Pure decision function. Implementations: heuristic, LLM-adapter, state-model."""

    model_id: str
    calibration: str  # "uncalibrated" or a description; harness treats uncalibrated as 0.5

    def decide(self, state: "WorldState", query: TypedQuery) -> ScoredAnswer:  # noqa: F821
        """No I/O. No side effects. Deterministic given (state, query)."""
        ...


# --- Future plugin interface: native state-model (Jev-pattern) ---

class StateModel(Model):
    """Protocol for a native state-model adapter (implemented later as a plugin).

    A state-model takes a WorldState slice and returns typed answers with
    calibrated probabilities — never free text. This protocol defines the
    integration point; the heuristic adapter below is the default until a
    state-model plugin is registered.
    """

    model_id: str = "state-model"
    calibration: str = "vendor-calibrated"

    def decide(self, state, query):  # pragma: no cover - plugin interface
        raise NotImplementedError("register a state-model plugin to use this")
