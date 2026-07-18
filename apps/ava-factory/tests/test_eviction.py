"""T10.9 curriculum-aware high-water eviction tests.

Property: under disk pressure the janitor sheds oversupplied / behind-phase
RAW and PACKED train shards without dropping any phase below the lead floor
and without ever touching val/test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ava.pipeline import flow, janitor
from ava.pipeline.eviction import (
    StorageConfig,
    evict_oversupplied,
    rank_eviction_candidates,
    should_evict,
)
from ava.pipeline.flow import FlowConfig
from ava.pipeline.janitor import Janitor
from ava.pipeline.manifest import DELETED, PACKED, RAW, Manifest

REPO = Path(__file__).resolve().parent.parent
PIPELINE_YAML = REPO / "configs" / "pipeline.yaml"


@pytest.fixture()
def fcfg() -> FlowConfig:
    return FlowConfig(
        low_water_gb=12,
        janitor_trigger_gb=18,
        critical_gb=6,
        raw_max_bytes=4_000_000_000,
        packed_ahead_max_tokens=3_000_000_000,
        packed_min_tokens=200_000_000,
        starved_poll_seconds=5,
        starved_warn_seconds=60,
        prefetch_phases=2,
        delete_consumed=True,
    )


@pytest.fixture()
def storage() -> StorageConfig:
    return StorageConfig(evict_high_water_gb=15.0, evict_batch_limit=10)


def _write_raw(path: Path, payload: bytes = b"raw") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _write_packed(path: Path, payload: bytes = b"tok") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.with_suffix(".idx.json").write_text('{"tokens": 1, "docs": []}', encoding="utf-8")
    return path


def _add_raw(m: Manifest, sid: str, phase: int, path: str, *, bytes_: int = 100) -> None:
    m.add_shard(sid, source="s", phase=phase, path=path, split="train",
                state=RAW, bytes_=bytes_)


def _add_packed(m: Manifest, sid: str, phase: int, path: str, tokens: int) -> None:
    m.add_shard(sid, source="s", phase=phase, path=path, split="train", state=PACKED)
    m.db.execute("UPDATE shards SET tokens=? WHERE id=?", (tokens, sid))


def test_storage_loads_from_pipeline_yaml():
    s = StorageConfig.load(PIPELINE_YAML)
    assert s.evict_high_water_gb == 15.0
    assert s.evict_batch_limit >= 1


def test_should_evict_when_free_below_high_water(storage):
    assert should_evict(14.0, storage) is True
    assert should_evict(15.0, storage) is False
    assert should_evict(20.0, storage) is False


def test_rank_prefers_behind_phase_raw_over_current(fcfg, tmp_path: Path):
    """P0 RAW behind trainer phase 3 ranks ahead of P3 RAW."""
    with Manifest(str(tmp_path / "m.db")) as m:
        _add_raw(m, "old", phase=0, path="/r/old")
        _add_raw(m, "cur", phase=3, path="/r/cur")
        m.db.execute("UPDATE shards SET updated_at=? WHERE id='old'", (100.0,))
        m.db.execute("UPDATE shards SET updated_at=? WHERE id='cur'", (200.0,))
        ranked = rank_eviction_candidates(m, fcfg, current_phase=3)
        assert [c.id for c in ranked[:2]] == ["old", "cur"]


def test_rank_never_includes_protected_splits(fcfg, tmp_path: Path):
    with Manifest(str(tmp_path / "m.db")) as m:
        _add_raw(m, "train", phase=0, path="/r/t")
        m.add_shard("val", source="s", phase=0, path="/r/v", split="val", state=RAW)
        ranked = rank_eviction_candidates(m, fcfg, current_phase=3)
        assert [c.id for c in ranked] == ["train"]


def test_rank_protects_packed_at_or_below_lead(fcfg, tmp_path: Path):
    """PACKED on a phase at the lead floor must not be a candidate."""
    with Manifest(str(tmp_path / "m.db")) as m:
        _add_packed(m, "p3", phase=3, path="/p/p3.bin", tokens=fcfg.packed_min_tokens)
        # Two P0 shards: removing the fat one still leaves lead on the floor.
        _add_packed(m, "p0_fat", phase=0, path="/p/p0a.bin", tokens=fcfg.packed_ahead_max_tokens)
        _add_packed(m, "p0_keep", phase=0, path="/p/p0b.bin", tokens=fcfg.packed_min_tokens)
        ranked = rank_eviction_candidates(m, fcfg, current_phase=3)
        ids = [c.id for c in ranked]
        assert "p3" not in ids
        assert "p0_fat" in ids
        assert "p0_keep" not in ids  # removing it would drop P0 below lead


def test_evict_deletes_oversupplied_raw_under_pressure(fcfg, storage, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(flow, "free_gb", lambda _p: 10.0)  # below high-water 15
    raw_dir = tmp_path / "raw"
    old = _write_raw(raw_dir / "p0" / "old.jsonl.zst")
    with Manifest(str(tmp_path / "m.db")) as m:
        m.upsert_run("r", preset="nano", step=1, phase=3, status="running")
        _add_raw(m, "old", phase=0, path=str(old), bytes_=10_000_000)
        stats = evict_oversupplied(m, fcfg, storage, current_phase=3)
        assert stats["deleted"] == 1
        assert not old.exists()
        assert m.db.execute("SELECT state FROM shards WHERE id='old'").fetchone()[0] == DELETED


def test_evict_refuses_val_negative_control(fcfg, storage, tmp_path: Path):
    val = _write_raw(tmp_path / "val.jsonl.zst")
    with Manifest(str(tmp_path / "m.db")) as m:
        m.add_shard("v", source="s", phase=0, path=str(val), split="val", state=RAW)
        # Force into candidate list by calling delete path with protected id —
        # rank must exclude it; evict must delete nothing.
        ranked = rank_eviction_candidates(m, fcfg, current_phase=3)
        assert ranked == []
        stats = evict_oversupplied(m, fcfg, storage, current_phase=3)
        assert stats["deleted"] == 0
        assert val.exists()


def test_janitor_run_once_evicts_when_disk_low(tmp_path: Path, monkeypatch):
    cfg = {
        "disk": {"low_water_gb": 12, "janitor_trigger_gb": 18, "critical_gb": 6},
        "backpressure": {
            "raw_max_bytes": 4_000_000_000,
            "packed_ahead_max_tokens": 3_000_000_000,
            "packed_min_tokens": 200_000_000,
            "starved_poll_seconds": 1,
            "starved_warn_seconds": 1,
        },
        "collector": {"prefetch_phases": 2},
        "retention": {
            "delete_consumed": True,
            "keep_last_checkpoints": 1,
            "keep_stable_checkpoints": True,
        },
        "storage": {"evict_high_water_gb": 15, "evict_batch_limit": 5},
    }
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(flow, "free_gb", lambda _p: 10.0)
    monkeypatch.setattr(janitor, "free_gb", lambda _p: 10.0)

    db = str(tmp_path / "m.db")
    raw = _write_raw(tmp_path / "raw" / "dead.jsonl.zst")
    with Manifest(db) as m:
        m.freeze_tokenizer("sha", 8)
        m.upsert_run("r", preset="nano", step=1, phase=3, status="running")
        _add_raw(m, "dead", phase=0, path=str(raw), bytes_=5_000_000)

    j = Janitor(
        config_path=str(p),
        db_path=db,
        packed_dir=str(tmp_path / "packed"),
        ckpt_dir=str(tmp_path / "ckpt"),
    )
    (tmp_path / "packed").mkdir()
    (tmp_path / "ckpt").mkdir()
    with Manifest(db) as m:
        result = j.run_once(m)
        assert result["evicted"] is not None
        assert result["evicted"]["deleted"] == 1
        assert not raw.exists()
