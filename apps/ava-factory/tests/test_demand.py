"""Unit tests for train→data demand channel."""

from __future__ import annotations

from ava.pipeline.demand import (
    apply_demand_weights,
    compute_demand,
    read_demand,
    write_demand,
)
from ava.pipeline.flow import FlowConfig


def _cfg(**over) -> FlowConfig:
    base = dict(
        low_water_gb=12,
        janitor_trigger_gb=20,
        critical_gb=5,
        raw_max_bytes=4_000_000_000,
        packed_ahead_max_tokens=3_000_000_000,
        packed_min_tokens=200_000_000,
        starved_poll_seconds=5,
        starved_warn_seconds=60,
        prefetch_phases=2,
        delete_consumed=True,
    )
    base.update(over)
    return FlowConfig(**base)


def test_compute_demand_expand_when_runway_thin():
    snap = compute_demand(
        tokens_ready_by_phase={0: 50_000_000, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        cfg=_cfg(),
        trainer_phase=0,
        step=10,
        preset="mini",
        now=1.0,
    )
    p0 = next(p for p in snap.phases if p.phase == 0)
    assert p0.deficit == 150_000_000
    assert "expand" in p0.actions
    assert p0.effort > 0
    assert any("expand" in r for r in snap.reasons)


def test_compute_demand_examples_on_rising_lm():
    snap = compute_demand(
        tokens_ready_by_phase={0: 500_000_000, 1: 300_000_000, 2: 0, 3: 0, 4: 0, 5: 0},
        cfg=_cfg(),
        trainer_phase=0,
        lm_trend=0.05,
        now=1.0,
    )
    assert snap.boost_task_types.get("deliberate") == 1.5
    p0 = next(p for p in snap.phases if p.phase == 0)
    assert "examples" in p0.actions


def test_compute_demand_curate_on_fail_frac():
    snap = compute_demand(
        tokens_ready_by_phase={0: 500_000_000, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        cfg=_cfg(),
        trainer_phase=0,
        failed_shards=20,
        active_shards=100,
        now=1.0,
    )
    assert snap.curate_stricter is True
    p0 = next(p for p in snap.phases if p.phase == 0)
    assert "curate" in p0.actions


def test_write_read_roundtrip(tmp_path):
    snap = compute_demand(
        tokens_ready_by_phase={0: 10, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        cfg=_cfg(packed_min_tokens=100),
        trainer_phase=0,
        step=3,
        preset="nano",
        now=42.0,
    )
    path = tmp_path / "demand.json"
    write_demand(snap, path)
    got = read_demand(path)
    assert got is not None
    assert got.step == 3
    assert got.phases[0].deficit == 90


def test_apply_demand_weights_boosts_examples():
    snap = compute_demand(
        tokens_ready_by_phase={0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        cfg=_cfg(packed_min_tokens=100),
        trainer_phase=0,
        lm_trend=0.1,
        now=1.0,
    )
    base = [("synth_logic", 1.0), ("other", 1.0)]
    types = {"synth_logic": "deliberate", "other": "safety"}
    out = dict(apply_demand_weights(base, source_task_types=types, demand=snap, phase=0))
    assert out["synth_logic"] > out["other"]


def test_apply_demand_weights_noop_without_demand():
    base = [("a", 0.5), ("b", 0.5)]
    assert apply_demand_weights(base, source_task_types={}, demand=None, phase=0) == [
        ("a", 0.5), ("b", 0.5),
    ]
