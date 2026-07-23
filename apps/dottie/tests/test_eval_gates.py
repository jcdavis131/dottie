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
from pathlib import Path

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


def _eval_with(tmp_path, name, *, train_metrics, baseline_kwargs=None, **eval_kwargs):
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
    return led, evaluate.run_evaluation(led, **eval_kwargs)


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
    """A candidate that would promote on its number alone, with a given param delta.

    Carries `per_seed` (cross-seed evidence) so the B0 multi-seed gate is never what
    refuses these candidates — CAPACITY is the gate under test here."""
    return {"proxy_loss": value, "eval_ce_per_batch": [value + 0.01, value - 0.01, value],
            "per_seed": [value + 0.01, value - 0.01, value], "seeds": [0, 1, 2],
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
                                     "eval_ce_per_batch": [4.41, 4.39, 4.40],
                                     "per_seed": [4.41, 4.39, 4.40], "seeds": [0, 1, 2]})
    assert r["verdict"]["capacity_gated"] is False
    assert r["state"] == SOTA


# --------------------------------------------------------------------------- B0: hard multi-seed gate


def _ab_runner(stdout, *, rc=0, calls=None):
    """A scripted stand-in for evaluate.subprocess_ab_runner — real training never runs
    in tests. Records the script path it was handed when `calls` is a list."""
    def run(script):
        if calls is not None:
            calls.append(str(script))
        return rc, stdout
    return run


#: The R93 evidence shape: 20 batches from ONE run. Alternating ±0.075 around 4.524 gives
#: sample SEM 0.075/√19 ≈ 0.0172 — the measured within-run SEM that let `5a7232ffea24`
#: clear the 2-SEM bar at ~4.4 SEM (delta 0.076 vs the 4.6 baseline).
_R93_BATCHES = [round(4.524 + (0.075 if i % 2 == 0 else -0.075), 5) for i in range(20)]


def test_r93_shape_within_run_win_that_loses_across_seeds_is_not_promoted(tmp_path):
    """The §5.3.R93 regression, both halves of it.

    A candidate clears the significance bar at ~4.4 SEM — but every one of those SEMs is
    within-run batch noise, blind to the run-to-run variance that decides the comparison.
    (a) With no A/B runner wired, that evidence alone must REFUSE promotion (missing
    multi-seed evidence, never a pass). (b) With the auto-run ab_nano reporting the
    cross-seed LOSS — R93's candidate was worse at all 3 seeds — the 'win' is refused as
    the noise it was. The bar must not move in either case."""
    metrics = {"proxy_loss": 4.524, "eval_ce_per_batch": _R93_BATCHES}

    # (a) no runner wired -> evidence missing -> held
    led, r = _eval_with(tmp_path, "r93_missing", train_metrics=metrics)
    v = r["verdict"]
    assert v["improved"] is True and v["significant"] is True     # the OLD bar did pass
    assert v["sem"] == pytest.approx(0.0172, abs=0.0005)          # ...on R93's numbers
    assert v["multi_seed_evidence"] is False
    assert v["seed_gated"] is True and v["promote"] is False
    assert v["seed_gate"]["status"] == "unavailable"
    assert r["state"] == REJECTED
    assert "within-run" in r["reason"] and "ab_nano" in r["reason"]
    assert led.get_baseline().metric_value == 4.6                 # bar did NOT ratchet

    # (b) the A/B ran and the candidate LOST across seeds -> refused as noise
    calls = []
    led2, r2 = _eval_with(
        tmp_path, "r93_loss", train_metrics=metrics,
        ab_runner=_ab_runner("seed 0: unmodified 5.56278  candidate 5.61000  delta +0.04722\n"
                             "VERDICT: candidate is WORSE beyond noise", calls=calls))
    assert r2["state"] == REJECTED
    assert r2["verdict"]["seed_gate"]["status"] == "loss"
    assert led2.get_baseline().metric_value == 4.6
    # the gate really generated and ran the bundle's ab_nano.py, pre-sota
    assert calls and calls[0].endswith("ab_nano.py")
    script = Path(calls[0])
    assert script.exists() and r2["experiment"] in str(script)
    assert "factory_nano_trainer" in script.read_text(encoding="utf-8")


def test_multi_seed_gate_promotes_on_a_paired_ab_win(tmp_path):
    """The passing case: same within-run evidence, but the auto-run A/B confirms the win
    across paired seeds -> promotion proceeds and the verdict records that evidence."""
    led, r = _eval_with(
        tmp_path, "abwin", train_metrics={"proxy_loss": 4.524,
                                          "eval_ce_per_batch": _R93_BATCHES},
        ab_runner=_ab_runner("paired delta    -0.08000   SEM 0.00500   (lower is better)\n"
                             "VERDICT: candidate is BETTER beyond noise"))
    v = r["verdict"]
    assert v["seed_gated"] is False and v["promote"] is True
    assert v["seed_gate"]["status"] == "win"
    assert r["state"] == SOTA
    b = led.get_baseline()
    assert b.metric_value == 4.524                # ratcheted, on real paired evidence
    assert b.metric_sem is not None and b.metric_sem > 0


def test_cross_seed_per_seed_evidence_needs_no_ab_run(tmp_path):
    """A candidate whose spread already comes from `per_seed` (run-to-run variance) IS
    the multi-seed evidence — the gate must not spend 6 training runs re-proving it."""
    calls = []
    _, r = _eval_with(
        tmp_path, "ps", train_metrics={"proxy_loss": 4.4,
                                       "per_seed": [4.41, 4.39, 4.40], "seeds": [0, 1, 2]},
        ab_runner=_ab_runner("VERDICT: candidate is WORSE beyond noise", calls=calls))
    assert r["state"] == SOTA
    assert r["verdict"]["multi_seed_evidence"] is True
    assert r["verdict"]["seed_gate"] is None
    assert calls == []                            # runner never invoked


def test_ab_gate_refuses_on_noise_no_verdict_bad_exit_and_crash(tmp_path):
    """Anything short of a clean cross-seed WIN refuses: WITHIN NOISE, a script that
    prints no verdict, a 'win' from a non-zero exit, and a runner that raises are all
    non-evidence — the gate must never promote on them."""
    metrics = {"proxy_loss": 4.524, "eval_ce_per_batch": _R93_BATCHES}

    _, noise = _eval_with(tmp_path, "noise", train_metrics=metrics,
                          ab_runner=_ab_runner("VERDICT: WITHIN NOISE - this run does not "
                                               "distinguish the candidate"))
    assert noise["state"] == REJECTED
    assert noise["verdict"]["seed_gate"]["status"] == "within_noise"

    _, silent = _eval_with(tmp_path, "silent", train_metrics=metrics,
                           ab_runner=_ab_runner("no verdict line printed at all"))
    assert silent["state"] == REJECTED
    assert silent["verdict"]["seed_gate"]["status"] == "error"

    _, bad_rc = _eval_with(tmp_path, "badrc", train_metrics=metrics,
                           ab_runner=_ab_runner("VERDICT: candidate is BETTER beyond noise",
                                                rc=1))
    assert bad_rc["state"] == REJECTED, "a 'win' from a crashed script is not evidence"
    assert bad_rc["verdict"]["seed_gate"]["status"] == "error"

    def boom(script):
        raise OSError("torch not installed")
    _, crash = _eval_with(tmp_path, "crash", train_metrics=metrics, ab_runner=boom)
    assert crash["state"] == REJECTED
    assert crash["verdict"]["seed_gate"]["status"] == "unavailable"
    assert "torch not installed" in crash["verdict"]["seed_gate"]["detail"]


def test_capacity_gate_outranks_the_seed_gate_and_skips_the_ab_run(tmp_path):
    """A capacity-gated candidate refuses for THAT stated reason without spending six
    training runs on A/B evidence that cannot change the answer."""
    calls = []
    _, r = _eval_with(
        tmp_path, "capfirst",
        train_metrics={"proxy_loss": 4.4, "eval_ce_per_batch": [4.41, 4.39, 4.40],
                       "block_param_delta": -786_816, "replaced_block_params": 787_072,
                       "candidate_block_params": 256},
        ab_runner=_ab_runner("VERDICT: candidate is BETTER beyond noise", calls=calls))
    assert r["state"] == REJECTED and "capacity-gated" in r["reason"]
    assert r["verdict"]["seed_gate"] is None and calls == []


def test_daemon_wires_the_real_ab_runner_into_evaluation(tmp_path, monkeypatch):
    """cmd_evaluate/cmd_run must hand run_evaluation the subprocess runner + promotions
    root: an unwired caller gets the refusing default and can never promote, so this
    wiring IS the gate's production path. (The daemon evaluates IN-PROCESS at
    __main__.cmd_run and never live-reloads — edits land at its next restart.)"""
    import argparse

    from dottie.research import __main__ as m
    from dottie.research import paths

    seen = {}

    def spy(led, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(m.evaluate, "run_evaluation", spy)

    assert m.cmd_evaluate(argparse.Namespace(data_dir=str(tmp_path))) == 0
    assert seen["ab_runner"] is m.evaluate.subprocess_ab_runner
    assert str(seen["promotions_root"]).endswith("promotions")

    # the DAEMON path (cmd_run) — the invocation the operator-ordered restart activates
    seen.clear()
    monkeypatch.setenv("DOTTIE_RESEARCH_MIN_FREE_MB", "0")   # memory guard is not under test
    led = Ledger(paths.ledger_path(str(tmp_path)))
    led.seed_baseline(Baseline("proxy_loss", 4.6, higher_is_better=False,
                               architecture="ava-nano", experiment_id=None, updated_ts=0.0))
    e = led.create(HYP)
    led.transition(e.id, READY_FOR_TRAINING, implementation={"code": GOOD_CODE},
                   workspace="/w")
    led.transition(e.id, EVALUATION_PENDING, train_metrics={"proxy_loss": 4.5})
    args = argparse.Namespace(data_dir=str(tmp_path), steps=5, trainer="proxy", device=None,
                              seeds="", max_retries=1, bottleneck="b", n=1,
                              idle_seconds=0.0, ideate_cooldown=1e9, max_actions=1)
    assert m.cmd_run(args) == 0
    assert seen["ab_runner"] is m.evaluate.subprocess_ab_runner
    assert str(seen["promotions_root"]).endswith("promotions")
