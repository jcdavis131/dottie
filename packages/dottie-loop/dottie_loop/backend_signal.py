"""Naming and provenance discipline for an externally-sourced probability
(research learning, TypeSafe Jev).

TypeSafe's own worked example returns a ``confidence`` of 0.82 for a
distribution whose top probability is 0.85; TypeSafe's docs say only that
confidence is "derived from the shape of the distribution", with the
formula undisclosed, and TypeSafe's own SKILL.md says it "summarizes
distribution concentration, not overall workflow correctness or permission
to act". Independent traces (vinilana/jev-eval-agent, 208 live calls)
recorded high-confidence tool-selection errors, and a community
reproductions tracker's own summary is "confidence does not reliably flag
errors". No public reliability curve exists for it.

Meanwhile this repository already uses the word ``confidence`` for four
different, unrelated things: a preference-pair margin in ``reward.py``, a
writer-asserted fact strength in ``memory.py``, a worker-reported number in
``rlm.py``, and a hand-typed number in ``docs/LESSONS.md``. Importing a
field literally named ``confidence`` from any future backend would merge a
fifth, unmeasured meaning into that name and make every one of those
un-joinable against the others.

This module does not add a decision system, a router, or a backend
adapter — none of that survived adversarial review (see
``docs/JEV_COLIBRI_INSIGHTS_SPEC.md``, "Not adopted"). It is the one rule
from that review that did survive on its own: IF something in this
codebase ever wraps an external backend's probability, it must be wrapped
in ``BackendProbability`` — named ``backend_confidence``, never
``confidence`` — carrying who produced it, and reject_confidence_aliasing
refuses a record that tries to smuggle a bare ``confidence`` key in next to
it. No number here is compared to a threshold, banded, or fed to
``evaluation.calibration`` — that would require a measured reliability
record this module does not have and does not fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.schema import active

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Keys this module refuses to see beside a ``backend_confidence`` field,
#: because each already names one of Dottie's own, differently-derived
#: numbers and a bare ``confidence`` would be ambiguous with all of them.
FORBIDDEN_ALONGSIDE_BACKEND_CONFIDENCE = frozenset({"confidence", "score", "prob", "p"})


@dataclass(frozen=True)
class BackendProbability:
    """An external backend's reported scalar, held at arm's length.

    ``value`` is stored verbatim: never recomputed, never renamed to
    ``confidence``, never compared to a threshold by this module. A caller
    that wants to gate on it must first build a measured calibration
    record the ordinary way (``evaluation.calibration`` over real outcome
    pairs) — this type is not that record and does not pretend to be.
    """

    value: float
    backend: str
    provenance: str

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise InvalidInputError("value must be a number", field="value")
        if not 0.0 <= float(self.value) <= 1.0:
            raise InvalidInputError("value must be in [0, 1]", field="value")
        if not isinstance(self.backend, str) or not self.backend.strip():
            raise InvalidInputError("backend must name the source", field="backend")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise InvalidInputError("provenance must be a non-empty string", field="provenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": active("backend-probability"),
            "backend_confidence": float(self.value),
            "backend": self.backend,
            "provenance": self.provenance,
        }


def reject_confidence_aliasing(record: Mapping[str, Any]) -> None:
    """Refuse a record that carries ``backend_confidence`` next to a bare
    key this codebase already uses for one of its own confidence-shaped
    numbers. Walks one level (records are flat dicts here); raises
    ``PolicyDeniedError`` rather than silently dropping either key.
    """
    if "backend_confidence" not in record:
        return
    clashing = FORBIDDEN_ALONGSIDE_BACKEND_CONFIDENCE & set(record)
    if clashing:
        raise PolicyDeniedError(
            f"backend_confidence cannot share a record with {sorted(clashing)}; "
            "an unmeasured backend scalar must never alias one of Dottie's own "
            "confidence-shaped fields",
            field="backend_confidence",
        )
