"""Naming/provenance discipline for an external backend's probability
(research learning, TypeSafe Jev)."""

from __future__ import annotations

import pytest

from dottie_loop import errors
from dottie_loop.backend_signal import (
    FORBIDDEN_ALONGSIDE_BACKEND_CONFIDENCE,
    BackendProbability,
    reject_confidence_aliasing,
)


def test_value_must_be_a_number_in_zero_one():
    with pytest.raises(errors.InvalidInputError, match="value"):
        BackendProbability(value=True, backend="jev-latest", provenance="p")  # bool rejected
    with pytest.raises(errors.InvalidInputError, match="value"):
        BackendProbability(value="0.5", backend="jev-latest", provenance="p")
    with pytest.raises(errors.InvalidInputError, match="value"):
        BackendProbability(value=1.5, backend="jev-latest", provenance="p")
    with pytest.raises(errors.InvalidInputError, match="value"):
        BackendProbability(value=-0.1, backend="jev-latest", provenance="p")
    BackendProbability(value=0.0, backend="jev-latest", provenance="p")
    BackendProbability(value=1.0, backend="jev-latest", provenance="p")


def test_backend_and_provenance_must_be_named():
    with pytest.raises(errors.InvalidInputError, match="backend"):
        BackendProbability(value=0.5, backend="", provenance="p")
    with pytest.raises(errors.InvalidInputError, match="backend"):
        BackendProbability(value=0.5, backend="   ", provenance="p")
    with pytest.raises(errors.InvalidInputError, match="provenance"):
        BackendProbability(value=0.5, backend="jev-latest", provenance="")


def test_to_dict_names_the_field_backend_confidence_never_confidence():
    d = BackendProbability(value=0.82, backend="jev-latest", provenance="typesafe_systemone_api").to_dict()
    assert d["backend_confidence"] == 0.82
    assert "confidence" not in d
    assert d["schema"] == "backend-probability-1.0.0"
    assert d["backend"] == "jev-latest"
    assert d["provenance"] == "typesafe_systemone_api"


def test_value_is_stored_verbatim_never_recomputed():
    # the record has no distribution/options to recompute max(p) from at all —
    # value is the only number, and it round-trips exactly.
    bp = BackendProbability(value=0.123456, backend="x", provenance="y")
    assert bp.to_dict()["backend_confidence"] == 0.123456


def test_reject_confidence_aliasing_is_a_noop_without_backend_confidence():
    reject_confidence_aliasing({})
    reject_confidence_aliasing({"confidence": 0.9})  # no backend_confidence key present at all


@pytest.mark.parametrize("clashing_key", sorted(FORBIDDEN_ALONGSIDE_BACKEND_CONFIDENCE))
def test_reject_confidence_aliasing_refuses_every_forbidden_alias(clashing_key):
    with pytest.raises(errors.PolicyDeniedError, match="backend_confidence"):
        reject_confidence_aliasing({"backend_confidence": 0.8, clashing_key: 0.9})


def test_reject_confidence_aliasing_allows_backend_confidence_alone():
    reject_confidence_aliasing({"backend_confidence": 0.8, "backend": "x", "provenance": "y"})
