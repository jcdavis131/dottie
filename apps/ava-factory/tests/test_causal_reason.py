"""Offline tests for CausalReasonGenerator — computed CFA + confounder drills."""

from __future__ import annotations

import random

from dottie.datagen.base import validate_doc
from dottie.datagen.causal_reason import (
    CausalReasonGenerator,
    _confounder_doc,
    _intervention_doc,
)


def test_generator_emits_valid_docs_and_hits_phases():
    gen = CausalReasonGenerator(seed=7)
    docs = list(gen.generate(target_bytes=8_000))
    assert docs
    phases = {d["phase"] for d in docs}
    assert phases <= {"p2", "p3", "p5"}
    assert {"p2", "p3"} & phases  # should see at least foundation + reasoning soon
    for d in docs:
        validate_doc(d, allowed_phases=gen.phases)
        assert d["source"] == "causal_reason"
        assert (
            "Causal" in d["text"]
            or "Causal drill" in d["text"]
            or "Structural" in d["text"]
        )


def test_confounder_numbers_recompute():
    rng = random.Random(11)
    text, task, concept, meta = _confounder_doc(rng)
    assert task == "deliberate"
    assert concept == "confounding_adjustment"
    cells = meta["cells"]

    # recompute crude RD
    def risk(t: int) -> float:
        ys = sum(cells[f"{z}|{t}"][1] for z in ("low_sleep", "high_sleep"))
        ns = sum(cells[f"{z}|{t}"][0] for z in ("low_sleep", "high_sleep"))
        return ys / ns

    crude = risk(1) - risk(0)
    assert abs(crude - meta["crude_rd"]) < 1e-9
    assert "Crude risk difference" in text


def test_intervention_delta_matches_structural_coeff():
    rng = random.Random(99)
    text, _task, _concept, meta = _intervention_doc(rng)
    expected = meta["a"] * (meta["x_do"] - meta["x_obs"])
    assert meta["y_do"] - meta["y_obs"] == expected
    assert "do(X=" in text


def test_deterministic_across_runs():
    a = [d["doc_id"] for d in CausalReasonGenerator(seed=3).generate(4000)]
    b = [d["doc_id"] for d in CausalReasonGenerator(seed=3).generate(4000)]
    assert a == b
