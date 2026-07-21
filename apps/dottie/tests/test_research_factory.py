# Solo personal project, no connection to employer, built with public/free-tier only
"""Factory-trainer tests — honest refusals everywhere, real integration when the box has it.

The integration test runs ONLY where the real factory checkout + packed pilot corpus exist
(the 4080 box); in CI it skips with the true reason. Nothing is mocked into "passing"."""

from __future__ import annotations

import json

import pytest

from dottie import resolve
from dottie.research import factory_trainer as ft
from dottie.research.ledger import Baseline, Ledger, READY_FOR_TRAINING
from tests.test_research import make_policy  # reuse the scripted-policy stand-in


def _factory_available() -> bool:
    try:
        root = resolve.factory_code_root()
    except resolve.DottieResolutionError:
        return False
    return any(d.is_dir() and any(d.glob("*.bin")) for d in ft._default_packed_dirs(root))


def test_factory_trainer_refuses_honestly_without_infrastructure(monkeypatch, tmp_path):
    monkeypatch.setenv("AVA_FACTORY_ROOT", str(tmp_path / "nowhere"))
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path / "nowhere-monorepo"))

    class _Exp:  # minimal duck-typed experiment
        workspace = str(tmp_path)
        implementation = {"module_name": "X"}

    r = ft.factory_nano_trainer(_Exp(), {})
    assert r.ok is False and r.stable is False
    assert "infrastructure missing" in r.detail


def test_resolve_seeds_parsing_and_dedup():
    """Seed-list resolution is pure and defensive: a list enables cross-seed measurement,
    absence falls back to the single configured seed (unchanged behaviour)."""
    assert ft._resolve_seeds({}, 1234) == [1234]              # no list -> single default
    assert ft._resolve_seeds({"seeds": []}, 1234) == [1234]   # empty list -> default
    assert ft._resolve_seeds({"seeds": [0, 1, 2]}, 1234) == [0, 1, 2]
    assert ft._resolve_seeds({"seeds": [0, 0, 1]}, 1234) == [0, 1]     # dedup, order kept
    assert ft._resolve_seeds({"seeds": ["2", "3"]}, 1234) == [2, 3]    # str coercion
    assert ft._resolve_seeds({"seeds": [1, "bad", 2]}, 1234) == [1, 2]  # skip unparseable


def test_make_candidate_forces_model_width():
    class Cand:
        def __init__(self, d_model=64, alpha=0.5):
            self.d_model = d_model
            self.alpha = alpha

    c = ft._make_candidate(Cand, {"d_model": 64, "alpha": 0.25, "bogus_kwarg": 1}, 256)
    assert c.d_model == 256          # dim-like kwarg overridden to the real model width
    assert c.alpha == 0.25           # declared non-dim kwargs preserved
    # bogus kwarg the constructor does not accept was dropped, not a crash


@pytest.mark.skipif(not _factory_available(),
                    reason="real factory checkout + packed pilot corpus not on this machine")
def test_factory_trainer_real_integration(tmp_path):
    """REAL end-to-end: candidate block into the real nano model, a few real steps on the
    real packed corpus, real held-out CE. Tiny config to stay test-fast."""
    led = Ledger(tmp_path / "ledger.sqlite3")
    led.seed_baseline(Baseline("factory_lm_loss", 9.9, False, "nano", None, 0.0))
    from dottie.research import ideation, implementation
    ideation.run_ideation(led, make_policy(), bottleneck="test", n_ideas=1)
    r = implementation.run_implementation(led, make_policy(), workspace_root=tmp_path / "ws")
    assert r["state"] == READY_FOR_TRAINING

    exp = led.get(r["experiment"])
    result = ft.factory_nano_trainer(exp, {
        "steps": 3, "seq_len": 32, "batch": 2, "eval_batches": 2, "device": "cpu",
    })
    assert result.ok, result.detail
    assert result.stable, result.detail
    m = result.metrics
    assert m["factory_lm_loss"] > 0 and m["integration"] == "factory_nano_block_swap"
    assert m["capability_claim"] == "none" and m["params"] > 1_000_000
    assert json.dumps(m)  # metrics are JSON-serializable for the ledger


@pytest.mark.skipif(not _factory_available(),
                    reason="real factory checkout + packed pilot corpus not on this machine")
def test_factory_trainer_multi_seed_records_per_seed(tmp_path):
    """SPEC #3: with a seeds list the candidate is trained once per seed and each seed's
    held-out CE is recorded in `per_seed`, so the evaluator's significance test uses
    CROSS-SEED spread (not within-run per-batch spread). The metric is the seed mean."""
    from dottie.research import ideation, implementation
    from dottie.research.evaluate import _spread

    led = Ledger(tmp_path / "ledger.sqlite3")
    led.seed_baseline(Baseline("factory_lm_loss", 9.9, False, "nano", None, 0.0))
    ideation.run_ideation(led, make_policy(), bottleneck="test", n_ideas=1)
    r = implementation.run_implementation(led, make_policy(), workspace_root=tmp_path / "ws")
    exp = led.get(r["experiment"])

    result = ft.factory_nano_trainer(exp, {
        "steps": 3, "seq_len": 32, "batch": 2, "eval_batches": 2, "device": "cpu",
        "seeds": [0, 1],
    })
    assert result.ok and result.stable, result.detail
    m = result.metrics
    assert m["seeds"] == [0, 1]
    assert isinstance(m["per_seed"], list) and len(m["per_seed"]) == 2
    assert all(v > 0 for v in m["per_seed"])
    # the metric is the cross-seed mean
    assert abs(m["factory_lm_loss"] - sum(m["per_seed"]) / 2) < 1e-3
    # and the evaluator now measures spread ACROSS SEEDS, not within one run
    sp = _spread(m)
    assert sp is not None and sp["series"] == "per_seed" and sp["n"] == 2
