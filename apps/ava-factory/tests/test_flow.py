"""Backpressure predicate tests.

These guard the property that keeps the pipeline alive unattended: collectors
throttle before the disk fills, and the trainer reports starvation instead of
crashing on an empty queue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ava.pipeline import flow
from ava.pipeline.flow import DataState, FlowConfig, StarvationTracker
from ava.pipeline.manifest import PACKED, Manifest


@pytest.fixture()
def cfg() -> FlowConfig:
    return FlowConfig(
        low_water_gb=12, janitor_trigger_gb=18, critical_gb=6,
        raw_max_bytes=4_000_000_000, packed_ahead_max_tokens=3_000_000_000,
        packed_min_tokens=200_000_000, starved_poll_seconds=5, starved_warn_seconds=60,
        prefetch_phases=2, delete_consumed=True,
    )


@pytest.fixture()
def m(tmp_path: Path) -> Manifest:
    with Manifest(str(tmp_path / "m.db")) as mm:
        mm.freeze_tokenizer("sha", 8192)
        yield mm


def _packed(m: Manifest, sid: str, phase: int, tokens: int, split: str = "train") -> None:
    m.add_shard(sid, source="s", phase=phase, path=f"/p/{sid}", split=split, state=PACKED)
    m.db.execute("UPDATE shards SET tokens=? WHERE id=?", (tokens, sid))


def test_config_loads_from_repo_yaml():
    cfg = FlowConfig.load(Path(__file__).parent.parent / "configs" / "pipeline.yaml")
    assert cfg.low_water_gb == 12
    assert cfg.packed_min_tokens == 200_000_000
    assert cfg.critical_gb < cfg.low_water_gb < cfg.janitor_trigger_gb  # ordering sanity


def test_collector_pauses_on_low_disk(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 5.0)
    r = flow.collector_should_pause(m, cfg, phase=0)
    assert r and "disk" in r.reason


def test_collector_pauses_on_raw_backlog(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    # Phase must not be starved, or raw-backlog pause is intentionally skipped.
    _packed(m, "warm", phase=0, tokens=cfg.packed_min_tokens)
    m.add_shard("r1", source="s", phase=0, path="/r", bytes_=cfg.raw_max_bytes)
    r = flow.collector_should_pause(m, cfg, phase=0)
    assert r and "raw backlog" in r.reason


def test_collector_pauses_when_runway_deep(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    _packed(m, "p1", phase=0, tokens=cfg.packed_ahead_max_tokens)
    r = flow.collector_should_pause(m, cfg, phase=0)
    assert r and "runway" in r.reason


def test_collector_runs_when_all_clear(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    _packed(m, "p1", phase=0, tokens=1000)
    assert not flow.collector_should_pause(m, cfg, phase=0)


def test_runway_ignores_val_test_shards(m, cfg, monkeypatch):
    """A pile of val shards must not fool the collector into thinking it's ahead."""
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    _packed(m, "v1", phase=0, tokens=cfg.packed_ahead_max_tokens, split="val")
    assert not flow.collector_should_pause(m, cfg, phase=0)


def test_trainer_starved_on_empty_queue(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    state, msg = flow.trainer_data_state(m, cfg, phase=0)
    assert state is DataState.STARVED and "no packed tokens" in msg


def test_trainer_ready_with_data(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    _packed(m, "p1", phase=2, tokens=500_000_000)
    state, _ = flow.trainer_data_state(m, cfg, phase=2)
    assert state is DataState.READY


def test_trainer_critical_disk_beats_readiness(m, cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 1.0)
    _packed(m, "p1", phase=0, tokens=10**9)
    state, _ = flow.trainer_data_state(m, cfg, phase=0)
    assert state is DataState.CRITICAL_DISK


def test_prefetch_lookahead_clamped_at_last_phase(cfg):
    assert flow.prefetch_phases(0, cfg) == [0, 1]
    assert flow.prefetch_phases(5, cfg) == [5]


def test_starved_phase_picks_earliest_hungry(m, cfg):
    _packed(m, "a", phase=0, tokens=cfg.packed_min_tokens + 1)
    _packed(m, "b", phase=1, tokens=10)  # hungry
    assert flow.starved_phase(m, cfg, [0, 1, 2]) == 1


def test_collector_skips_raw_pause_when_trainer_starved(m, cfg, monkeypatch):
    """Wrong-phase RAW backlog must not block collecting when the GPU is starved."""
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    m.add_shard("r1", source="s", phase=0, path="/r", bytes_=cfg.raw_max_bytes)
    # Trainer defaults to phase 0 with no packed -> starved -> raw pause skipped
    # even when collecting a later empty phase.
    assert not flow.collector_should_pause(m, cfg, phase=3)
    # Once the trainer's phase has lead, raw backlog pauses again.
    _packed(m, "p0", phase=0, tokens=cfg.packed_min_tokens)
    assert flow.collector_should_pause(m, cfg, phase=0)


def test_prefetch_respects_raw_cap_when_trainer_has_lead(m, cfg, monkeypatch):
    """Empty next-phase prefetch must not bypass raw_max while current has lead."""
    monkeypatch.setattr(flow, "free_gb", lambda _p: 100.0)
    m.upsert_run("r1", preset="mini", step=100, phase=0, status="running")
    _packed(m, "p0", phase=0, tokens=cfg.packed_min_tokens + 1)
    m.add_shard("r1", source="s", phase=0, path="/r", bytes_=cfg.raw_max_bytes)
    # Targeting starved phase 1 (prefetch) with trainer fed on phase 0 -> pause.
    r = flow.collector_should_pause(m, cfg, phase=1)
    assert r and "raw backlog" in r.reason


def test_free_gb_prefers_host_disk_probe(tmp_path, monkeypatch):
    host = tmp_path / "host_disk"
    host.mkdir()
    calls: list[str] = []

    def fake_usage(p: str):
        calls.append(str(p))
        free = 5 * 10**9 if str(host) in str(p) else 900 * 10**9
        return type("U", (), {"total": 1000 * 10**9, "used": 0, "free": free})()

    monkeypatch.setenv("AVA_DISK_PROBE", str(host))
    monkeypatch.setattr(flow.shutil, "disk_usage", fake_usage)
    assert flow.free_gb("/raw") == 5.0
    assert calls and str(host) in calls[0]


def test_pick_target_follows_runs_heartbeat(m, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("AVA_REPORTS_DIR", str(tmp_path))
    m.upsert_run("r1", preset="nano", step=100, phase=3, status="running")
    # P3 empty -> starved wins inside prefetch [3,4]
    assert flow.pick_target_phase(m, cfg) == 3


def test_pick_target_falls_back_to_metrics(m, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("AVA_REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("AVA_PRESET", "nano")
    metrics = tmp_path / "metrics_nano.jsonl"
    metrics.write_text(
        json.dumps({"event": "step", "step": 3000, "phase": 3, "lm_loss": 0.1}) + "\n",
        encoding="utf-8",
    )
    assert flow.current_training_phase(m) == 3
    assert flow.pick_target_phase(m, cfg) == 3


def test_curator_claim_phases_prefers_starved_window(m, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("AVA_REPORTS_DIR", str(tmp_path))
    m.upsert_run("r1", preset="nano", step=1, phase=3, status="running")
    _packed(m, "p3", phase=3, tokens=0)  # still starved (0 < min)
    assert flow.curator_claim_phases(m, cfg) == [3, 4]
    # older phases must not appear
    assert 0 not in flow.curator_claim_phases(m, cfg)


def test_starvation_tracker_warns_only_after_threshold(cfg, monkeypatch):
    t = StarvationTracker(cfg)
    clock = {"v": 1000.0}
    monkeypatch.setattr(flow.time, "monotonic", lambda: clock["v"])

    assert t.record(True) is None            # just started
    clock["v"] += 59
    assert t.record(True) is None            # under warn threshold
    clock["v"] += 2
    assert "DATA_STARVED for" in t.record(True)

    assert t.record(False) is None           # recovery resets
    assert t.starved_seconds == 0.0


def test_janitor_triggers_under_pressure(cfg, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 10.0)
    assert flow.janitor_should_collect(cfg)
    monkeypatch.setattr(flow, "free_gb", lambda _p: 50.0)
    assert not flow.janitor_should_collect(cfg)
