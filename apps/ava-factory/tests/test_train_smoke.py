"""Trainer schedule + batching unit tests.

The end-to-end training run is exercised by `make smoke` against real shards;
these cover the pure functions that a smoke run would only catch by drifting.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from ava.config import AvaConfig
from ava.train import micro_batch_for, phase_for_step, wsd_lr


@pytest.fixture(scope="module")
def cfg() -> AvaConfig:
    return AvaConfig.load("nano")


def test_wsd_warms_up_then_plateaus_then_decays(cfg):
    total = 1000
    w = cfg.training.wsd

    assert wsd_lr(0, total, cfg) < w.lr_max                       # warming
    assert wsd_lr(w.warmup_steps, total, cfg) == pytest.approx(w.lr_max)

    stable_until = int(total * w.stable_frac)
    mid = (w.warmup_steps + stable_until) // 2
    assert wsd_lr(mid, total, cfg) == pytest.approx(w.lr_max)     # plateau

    assert wsd_lr(total - 1, total, cfg) < w.lr_max               # decaying
    assert wsd_lr(total - 1, total, cfg) >= w.lr_min


def test_wsd_is_monotone_within_each_leg(cfg):
    total = 1000
    w = cfg.training.wsd
    warm = [wsd_lr(s, total, cfg) for s in range(w.warmup_steps)]
    assert warm == sorted(warm)

    stable_until = int(total * w.stable_frac)
    decay = [wsd_lr(s, total, cfg) for s in range(stable_until, total)]
    assert decay == sorted(decay, reverse=True)


def test_stable_plateau_is_what_makes_checkpoints_usable(cfg):
    """Any checkpoint taken during the plateau is a usable model -- the whole
    basis of the stop-anytime milestone schedule."""
    total = 1000
    w = cfg.training.wsd
    lrs = {wsd_lr(s, total, cfg) for s in range(w.warmup_steps, int(total * w.stable_frac))}
    assert lrs == {w.lr_max}


def test_micro_batch_always_hits_tokens_per_step():
    for seq in (256, 512, 1024):
        mb, accum = micro_batch_for(seq, 8192)
        assert mb * seq * accum == 8192, f"seq={seq} desyncs the WSD schedule"
        assert mb >= 1 and accum >= 1


def test_micro_batch_is_capped():
    mb, _ = micro_batch_for(64, 8192)
    assert mb <= 8                                   # MAX_MICRO_BATCH


def test_phase_advances_with_the_token_budget(cfg):
    assert phase_for_step(cfg, 0) == 0
    first = cfg.phases[0].tokens
    assert phase_for_step(cfg, first - 1) == 0
    assert phase_for_step(cfg, first) == 1
    assert phase_for_step(cfg, 10**12) == len(cfg.phases) - 1     # clamps, never IndexError


def test_every_phase_is_reachable(cfg):
    seen = {phase_for_step(cfg, t) for t in range(0, cfg.training.tokens_total, 250_000)}
    assert seen == set(range(len(cfg.phases)))
