# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Jev-pattern state-model plugin interface.

"Jev-pattern" names the paradigm — state in, typed answers out, calibrated
probabilities — not any vendor's product. This is our clean-room take on that
paradigm: `dottie_core/homegrown.py` implements it end to end with our own
code (feature encoder, logistic scorer, ledger calibration). No vendor API,
no vendor code, no external service.

This module defines the CONTRACT a state-model honors. `JevModel` is the
protocol; `HomegrownModel` (in `dottie_core.homegrown`) is the working
implementation. `JevStub` remains as documentation-as-code for anyone wiring a
different backend to the same contract.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dottie_core.model import Model, ScoredAnswer, TypedQuery
from dottie_core.state import WorldState


@runtime_checkable
class JevModel(Model, Protocol):
    """A `Model` with Jev-pattern guarantees: calibrated, schema-declared, floored.

    Extends the base `Model` protocol (pure `decide(state, query)` function)
    with the three things a state-model must expose for the harness to trust
    it with autonomous decisions:

    - `state_schema`: which belief keys / domain fields the adapter can read,
      so the harness can reject queries that reach outside the adapter's
      competence instead of letting it hallucinate over unknown state.
    - `confidence_floor`: the adapter's own declared minimum usable confidence.
      Below this, the harness escalates regardless of what the score says.
    - `calibrate()`: (re)fit the adapter's confidence mapping on labeled
      (state, query, correct_answer) triples; returns a calibration report.
      The harness requires a documented calibration method before trusting
      scores for high-stakes tiers.
    """

    @property
    def state_schema(self) -> dict[str, Any]:
        """JSON-schema-ish declaration of readable state. Keys the adapter handles."""
        ...

    @property
    def confidence_floor(self) -> float:
        """Minimum confidence the adapter will vouch for. Harness escalates below it."""
        ...

    def calibrate(
        self,
        validation: list[tuple[WorldState, TypedQuery, Any]],
    ) -> dict[str, float]:
        """Refit confidence mapping on labeled examples.

        Each triple is (state, query, correct_answer). Returns a report such as
        {"n": 200, "ece_before": 0.31, "ece_after": 0.07, "method": "isotonic"}.
        Expected calibration error (ECE) should drop; if it doesn't, the adapter
        must say so honestly and the harness keeps treating it as uncalibrated.
        """
        ...


class JevStub(JevModel):
    """Documentation-as-code for the JevModel contract. NOT a working model.

    Kept for import compatibility and as a reference implementation of the
    wire shape. For a working model, use `dottie_core.homegrown.HomegrownModel`
    — our implementation of this same contract.

    Wire shape this stub documents (what an adapter must speak):

    REQUEST (state in):
        {
          "model": "jev-system-one",
          "state": {
            "version": 3,
            "beliefs": {
              "risk_level": {"value": "high", "confidence": 0.82, "source": "tool:scanner"}
            },
            "constraints": {"side_effect_class": "write_local"}
          },
          "queries": [
            {
              "id": "q1",
              "kind": "choose",                       # classify|score|choose|extract|verify
              "state_ref": {"belief_keys": ["risk_level"]},
              "options": ["proceed", "escalate", "abort"],
              "schema": {}
            }
          ]
        }

    RESPONSE (typed answers out — never free text):
        {
          "answers": [
            {
              "query_id": "q1",
              "best": {"value": "escalate", "confidence": 0.91},
              "alternatives": [
                {"value": "proceed", "confidence": 0.06},
                {"value": "abort", "confidence": 0.03}
              ],
              "calibration": "vendor-calibrated v2026-09"
            }
          ]
        }

    Every method raises: instantiate this only to inspect the contract, never
    to decide. `HomegrownModel` implements `decide()` with our own code —
    no other harness code changes to swap backends.
    """

    model_id = "jev-stub"
    calibration = "unimplemented"

    @property
    def state_schema(self) -> dict[str, Any]:
        return {"beliefs": "any", "constraints": "any", "domain": "any"}

    @property
    def confidence_floor(self) -> float:
        return 0.6

    def calibrate(
        self,
        validation: list[tuple[WorldState, TypedQuery, Any]],
    ) -> dict[str, float]:
        raise NotImplementedError(
            "JevStub is documentation, not a model. "
            "Implement JevModel.decide() against the real API."
        )

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        raise NotImplementedError(
            "JevStub is documentation, not a model. "
            "Implement JevModel.decide() against the real API."
        )
