"""Trainer schedule + batching unit tests.

The end-to-end training run is exercised by `make smoke` against real shards;
these cover the pure functions that a smoke run would only catch by drifting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from ava.config import AvaConfig
from ava.pipeline.manifest import PACKED, Manifest
from ava.train import micro_batch_for, phase_for_step, save_ckpt, wsd_lr

from dottie.provenance import validate_checkpoint


@pytest.fixture(scope="module")
def cfg() -> AvaConfig:
    return AvaConfig.load("nano")


def test_wsd_warms_up_then_plateaus_then_decays(cfg):
    total = 1000
    w = cfg.training.wsd

    assert wsd_lr(0, total, cfg) < w.lr_max  # warming
    assert wsd_lr(w.warmup_steps, total, cfg) == pytest.approx(w.lr_max)

    stable_until = int(total * w.stable_frac)
    mid = (w.warmup_steps + stable_until) // 2
    assert wsd_lr(mid, total, cfg) == pytest.approx(w.lr_max)  # plateau

    assert wsd_lr(total - 1, total, cfg) < w.lr_max  # decaying
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
    lrs = {
        wsd_lr(s, total, cfg) for s in range(w.warmup_steps, int(total * w.stable_frac))
    }
    assert lrs == {w.lr_max}


def test_micro_batch_always_hits_tokens_per_step():
    for seq in (256, 512, 1024):
        mb, accum = micro_batch_for(seq, 8192)
        assert mb * seq * accum == 8192, f"seq={seq} desyncs the WSD schedule"
        assert mb >= 1 and accum >= 1


def test_micro_batch_is_capped():
    mb, _ = micro_batch_for(64, 8192)
    assert mb <= 8  # MAX_MICRO_BATCH


def test_phase_advances_with_the_token_budget(cfg):
    assert phase_for_step(cfg, 0) == 0
    first = cfg.phases[0].tokens
    assert phase_for_step(cfg, first - 1) == 0
    assert phase_for_step(cfg, first) == 1
    assert (
        phase_for_step(cfg, 10**12) == len(cfg.phases) - 1
    )  # clamps, never IndexError


def test_every_phase_is_reachable(cfg):
    seen = {
        phase_for_step(cfg, t) for t in range(0, cfg.training.tokens_total, 250_000)
    }
    assert seen == set(range(len(cfg.phases)))


def test_checkpoint_write_includes_valid_lineage_digest_and_parent(cfg, tmp_path):
    shard_id = "observed-shard"
    with Manifest(tmp_path / "manifest.db") as manifest:
        manifest.freeze_tokenizer("b" * 64, cfg.model.vocab_size)
        manifest.add_shard(
            shard_id,
            source="test",
            phase=0,
            path="test.bin",
            sha256="a" * 64,
            source_kind="hf",
            source_license="mit",
            source_gated=False,
            source_revision="a" * 40,
            source_entry_sha256="b" * 64,
            packed_bin_sha256="c" * 64,
            packed_idx_sha256="d" * 64,
            state=PACKED,
        )
        sampler = SimpleNamespace(
            m=manifest,
            state_dict=lambda: {"observed_shard_ids": [shard_id]},
            observed_shard_ids=lambda: [shard_id],
        )
        model = SimpleNamespace(state_dict=lambda: {"weight": torch.tensor([1.0])})
        opt = SimpleNamespace(state_dict=lambda: {"step": 1})
        path = tmp_path / "step_1.pt"
        digest = save_ckpt(
            path,
            model=model,
            opt=opt,
            step=1,
            phase=0,
            tokens_done=1024,
            cfg=cfg,
            sampler=sampler,
            asserted_parent={"checkpoint_digest": "e" * 64},
        )
    blob = torch.load(path, map_location="cpu", weights_only=True)
    assert blob["asserted_parent"] == {"checkpoint_digest": "e" * 64}
    assert digest == blob["digest"]
    assert validate_checkpoint(blob, expected_config=cfg) == digest
