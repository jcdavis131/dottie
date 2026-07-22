# Solo personal project, no connection to employer, built with public/free-tier only
"""The two operator-activated promotion gates (TODOS items 10+11, shipped together).

Item 10 — capacity gate: a swap that deleted >CAPACITY_DELETE_FRAC of the block it
replaced may not promote, however good its number (fixed-step wins by shrinkage are the
documented contamination chain). Item 11 — paired-seed significance: when candidate and
baseline both carry `per_seed` at the same n, significance uses the SE of the per-seed
DIFFERENCES (shared seed variance cancels); anything else falls back to the old tests.
They ship together because paired significance lowers the bar ~7x, which is only safe
once shrinkage wins are refused. Pure math + sqlite — no torch."""

from __future__ import annotations

import json

import pytest

from dottie.research import evaluate
from dottie.research.ledger import (
    EVALUATION_PENDING,
    READY_FOR_TRAINING,
    REJECTED,
    SOTA,
    Baseline,
    Ledger,
)
from tests.test_research import GOOD_CODE, HYP


def _eval_with(tmp_path, name, *, train_metrics, baseline_kwargs=None):
    """One evaluation run against a fresh ledger; returns run_evaluation's dict."""
    led = Ledger(tmp_path / f"{name}.sqlite3")
    led.seed_baseline(Baseline("proxy_loss", 4.6, higher_is_better=False,
                               architecture="ava-nano", experiment_id=None,
                               updated_ts=0.0, **(baseline_kwargs or {})))
    e = led.create(HYP)
    led.transition(e.id, READY_FOR_TRAINING,
                   implementation={"code": GOOD_CODE}, workspace="/w")
    base = {"integration": "proxy_micro_benchmark", "params": 1000}
    led.transition(e.id, EVALUATION_PENDING, train_metrics={**base, **train_metrics})
    return led, evaluate.run_evaluation(led)


# --------------------------------------------------------------------------- item 11


def test_paired_significance_cancels_shared_seed_variance(tmp_path):
    """Candidate/baseline per_seed at the same n → PAIRED SE of differences.

    The numbers are the R93 failure shape: both series swing ~0.3 across seeds (shared),
    but the candidate is a consistent ~0.10 better at EVERY seed. Unpaired SE_diff
    (~sqrt(.087²+.087²)≈0.12 → 2σ≈0.25) calls delta 0.1 noise; paired sd(diffs)=0.01 →
    SE≈0.0058 → 2σ≈0.012 correctly resolves it."""
    base_ps = [4.45, 4.75, 4.60]                      # mean 4.60, spread is seed variance
    cand_ps = [4.36, 4.65, 4.49]                      # 0.09/0.10/0.11 better per seed
    mean_c = round(sum(cand_ps) / 3, 5)
    led, r = _eval_with(
        tmp_path, "paired",
        train_metrics={"proxy_loss": mean_c, "per_seed": cand_ps, "seeds": [0, 1, 2]},
        baseline_kwargs={"metric_sem": 0.087, "metric_sem_n": 3, "per_seed": base_ps},
    )
    v = r["verdict"]
    assert v["significant"] is True
    assert "PAIRED per-seed SE" in v["significance"]
    assert "shared" in v["significance"]              # prose says what cancelled and why
    assert r["state"] == SOTA
    # the winner's per_seed landed on the NEW baseline so the next test pairs too
    nb = led.get_baseline()
    assert nb.per_seed == pytest.approx(cand_ps)


def test_unpaired_fallback_when_lengths_differ_or_absent(tmp_path):
    """Pairing must be conservative: n-mismatch or absent baseline per_seed → the old
    unpaired two-sample test, word 'PAIRED' absent — pre-per_seed baselines unchanged."""
    cand_ps = [4.36, 4.65, 4.49]
    # (a) baseline carries NO per_seed
    _, r = _eval_with(
        tmp_path, "nops",
        train_metrics={"proxy_loss": 4.5, "per_seed": cand_ps},
        baseline_kwargs={"metric_sem": 0.087, "metric_sem_n": 3},
    )
    assert "PAIRED" not in r["verdict"]["significance"]
    assert "two-sample SE_diff" in r["verdict"]["significance"]
    # (b) length mismatch (baseline measured at 2 seeds, candidate at 3)
    _, r2 = _eval_with(
        tmp_path, "mismatch",
        train_metrics={"proxy_loss": 4.5, "per_seed": cand_ps},
        baseline_kwargs={"metric_sem": 0.087, "metric_sem_n": 2, "per_seed": [4.45, 4.75]},
    )
    assert "PAIRED" not in r2["verdict"]["significance"]


def test_baseline_per_seed_ledger_round_trip(tmp_path):
    """per_seed survives seed→get→promote→get, and the migration is additive: a ledger
    created without the column reads back rows written by the pre-migration INSERT."""
    led = Ledger(tmp_path / "rt.sqlite3")
    led.seed_baseline(Baseline("m", 5.0, higher_is_better=False, architecture="nano",
                               experiment_id=None, updated_ts=0.0,
                               per_seed=[5.1, 4.9, 5.0]))
    got = led.get_baseline()
    assert got.per_seed == [5.1, 4.9, 5.0]
    led.promote_baseline("exp42", 4.8, per_seed=[4.9, 4.7, 4.8])
    got = led.get_baseline()
    assert got.experiment_id == "exp42" and got.per_seed == [4.9, 4.7, 4.8]
    # promote WITHOUT per_seed clears it (a point baseline must not pair against stale seeds)
    led.promote_baseline("exp43", 4.7)
    assert led.get_baseline().per_seed is None
    # pre-migration write survives (column list without per_seed)
    import sqlite3
    c = sqlite3.connect(tmp_path / "rt.sqlite3")
    c.execute(
        "INSERT INTO baseline (singleton, metric_name, metric_value, higher_is_better, "
        "architecture, experiment_id, updated_ts, notes) VALUES (1,?,?,?,?,?,?,?) "
        "ON CONFLICT(singleton) DO UPDATE SET metric_value=excluded.metric_value",
        ("m", 4.6, 0, "nano", "old", 1.0, ""))
    c.commit(); c.close()
    assert led.get_baseline().metric_value == 4.6


# --------------------------------------------------------------------------- item 10


def _capacity_metrics(delta, replaced=787_072, value=4.4):
    """A candidate that would promote on its number alone, with a given param delta."""
    return {"proxy_loss": value, "eval_ce_per_batch": [value + 0.01, value - 0.01, value],
            "block_param_delta": delta, "replaced_block_params": replaced,
            "candidate_block_params": replaced + delta}


def test_capacity_gate_refuses_wins_by_large_deletion(tmp_path):
    """The 5a7232ffea24 shape: wins the metric while removing 99.97% of the block →
    REJECTED with the shrinkage spelled out, and the baseline does NOT move."""
    led, r = _eval_with(tmp_path, "gate",
                        train_metrics=_capacity_metrics(-786_816))
    v = r["verdict"]
    assert v["improved"] is True and v["significant"] is True   # the number DID win
    assert v["capacity_gated"] is True and v["promote"] is False
    assert r["state"] == REJECTED
    assert "capacity-gated" in r["reason"] and "shrinkage" in r["reason"]
    assert led.get_baseline().metric_value == 4.6               # bar did not ratchet


def test_capacity_gate_spares_small_deletions_and_additions(tmp_path):
    """<=10% deletion and any addition stay promotable — a genuinely leaner-but-better
    block must not be collateral damage."""
    _, small = _eval_with(tmp_path, "small",
                          train_metrics=_capacity_metrics(-50_000))   # 6.4% < 10%
    assert small["verdict"]["capacity_gated"] is False
    assert small["state"] == SOTA
    _, grew = _eval_with(tmp_path, "grew",
                         train_metrics=_capacity_metrics(+120_000))
    assert grew["verdict"]["capacity_gated"] is False
    assert grew["state"] == SOTA


def test_capacity_gate_needs_positive_evidence(tmp_path):
    """No recorded delta (non-swap trainer) → cannot gate; behaviour unchanged."""
    _, r = _eval_with(tmp_path, "nodelta",
                      train_metrics={"proxy_loss": 4.4,
                                     "eval_ce_per_batch": [4.41, 4.39, 4.40]})
    assert r["verdict"]["capacity_gated"] is False
    assert r["state"] == SOTA
