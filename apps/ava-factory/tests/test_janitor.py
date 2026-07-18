"""Janitor tests — watermarks, CONSUMED reclaim, ckpt rotation, val/test refuse.

Runs offline against a real on-disk SQLite manifest and temp directories. Disk
pressure is injected via ``free_gb`` monkeypatch so CI does not depend on host
free space.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ava.pipeline import flow, janitor
from ava.pipeline.janitor import (
    Janitor,
    RetentionConfig,
    delete_shard_files,
    reclaim_consumed,
    rotate_checkpoints,
)
from ava.pipeline.manifest import CONSUMED, DELETED, PACKED, Manifest, StateError

REPO = Path(__file__).resolve().parent.parent
PIPELINE_YAML = REPO / "configs" / "pipeline.yaml"


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "manifest.db")


def _write_packed(path: Path, payload: bytes = b"tok") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    idx = path.with_suffix(".idx.json")
    idx.write_text('{"tokens": 1, "docs": []}', encoding="utf-8")
    return path


def _seed_consumed(
    m: Manifest,
    *,
    shard_id: str,
    path: str,
    split: str = "train",
    phase: int = 0,
) -> None:
    m.add_shard(shard_id, source="x", phase=phase, path=path, split=split, state=PACKED)
    m.db.execute("UPDATE shards SET state=? WHERE id=?", (CONSUMED, shard_id))


# ---------------------------------------------------------------------------
# Config / retention


def test_retention_loads_from_pipeline_yaml():
    r = RetentionConfig.load(PIPELINE_YAML)
    assert r.delete_consumed is True
    assert r.keep_last_checkpoints == 1
    assert r.keep_stable_checkpoints is True


def test_janitor_reads_watermarks_from_config(tmp_path: Path):
    cfg = {
        "disk": {"low_water_gb": 12, "janitor_trigger_gb": 18, "critical_gb": 6},
        "backpressure": {
            "raw_max_bytes": 1,
            "packed_ahead_max_tokens": 1,
            "packed_min_tokens": 1,
            "starved_poll_seconds": 1,
            "starved_warn_seconds": 1,
        },
        "collector": {"prefetch_phases": 2},
        "retention": {
            "delete_consumed": True,
            "keep_last_checkpoints": 2,
            "keep_stable_checkpoints": True,
        },
    }
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    j = Janitor(config_path=str(p), db_path=str(tmp_path / "m.db"),
                packed_dir=str(tmp_path), ckpt_dir=str(tmp_path / "ckpt"))
    assert j.flow.janitor_trigger_gb == 18
    assert j.retention.keep_last_checkpoints == 2


# ---------------------------------------------------------------------------
# File delete helpers


def test_delete_shard_files_removes_bin_and_idx(tmp_path: Path):
    bin_path = _write_packed(tmp_path / "p0" / "train" / "s.bin")
    assert delete_shard_files(str(bin_path))
    assert not bin_path.exists()
    assert not bin_path.with_suffix(".idx.json").exists()


def test_delete_shard_files_missing_is_ok(tmp_path: Path):
    assert delete_shard_files(str(tmp_path / "gone.bin"))


# ---------------------------------------------------------------------------
# CONSUMED reclaim + val/test negative control


def test_reclaim_deletes_consumed_train_and_marks_deleted(db_path, tmp_path: Path):
    packed = tmp_path / "packed"
    bin_path = _write_packed(packed / "p0" / "train" / "t1.bin")
    with Manifest(db_path) as m:
        _seed_consumed(m, shard_id="t1", path=str(bin_path), split="train")
        stats = reclaim_consumed(m)
        assert stats["deleted"] == 1
        assert stats["refused_protected"] == 0
        assert m.counts_by_state() == {DELETED: 1}
    assert not bin_path.exists()
    assert not bin_path.with_suffix(".idx.json").exists()


def test_reclaim_never_deletes_val_or_test_negative_control(db_path, tmp_path: Path):
    """Negative control: even if val/test rows are forced into CONSUMED, refuse."""
    packed = tmp_path / "packed"
    paths = {}
    with Manifest(db_path) as m:
        for split in ("train", "val", "test"):
            p = _write_packed(packed / "p0" / split / f"{split}.bin")
            paths[split] = p
            # Force protected splits into CONSUMED (bypasses claim path) to prove
            # the janitor still refuses — structural + explicit refuse.
            _seed_consumed(m, shard_id=f"s-{split}", path=str(p), split=split)

        # Direct mark_deleted on protected must raise (manifest contract).
        with pytest.raises(StateError, match="protected split"):
            m.mark_deleted(["s-val"])

        stats = reclaim_consumed(m)
        assert stats["deleted"] == 1
        assert stats["refused_protected"] == 0  # consumed_shards already excludes them
        # Explicit refuse path: call delete path with a protected row that somehow
        # appears — simulate by checking files still present for val/test.
        assert paths["val"].exists()
        assert paths["test"].exists()
        assert not paths["train"].exists()

        # Manifest: train DELETED; val/test still CONSUMED (never deleted).
        rows = {
            r["id"]: r["state"]
            for r in m.db.execute("SELECT id, state FROM shards").fetchall()
        }
        assert rows["s-train"] == DELETED
        assert rows["s-val"] == CONSUMED
        assert rows["s-test"] == CONSUMED


def test_janitor_explicit_refuse_protected_split(db_path, tmp_path: Path, monkeypatch):
    """If a protected CONSUMED row leaks past consumed_shards, janitor still refuses."""
    packed = tmp_path / "packed"
    val_bin = _write_packed(packed / "p0" / "val" / "v.bin")
    with Manifest(db_path) as m:
        _seed_consumed(m, shard_id="v1", path=str(val_bin), split="val")

        # Bypass the SQL filter so reclaim_consumed sees the protected row.
        from ava.pipeline.manifest import Shard

        fake = Shard(
            id="v1", source="x", phase=0, split="val", state=CONSUMED,
            path=str(val_bin), bytes=1, tokens=1, docs=1, attempts=0,
        )
        monkeypatch.setattr(m, "consumed_shards", lambda limit=100: [fake])
        stats = reclaim_consumed(m)
        assert stats["refused_protected"] == 1
        assert stats["deleted"] == 0
        assert val_bin.exists()
        assert m.db.execute("SELECT state FROM shards WHERE id='v1'").fetchone()[0] == CONSUMED


def test_reclaim_skips_bad_shard_without_raising(db_path, tmp_path: Path, monkeypatch):
    packed = tmp_path / "packed"
    good = _write_packed(packed / "p0" / "train" / "good.bin")
    bad = _write_packed(packed / "p0" / "train" / "bad.bin")
    with Manifest(db_path) as m:
        _seed_consumed(m, shard_id="good", path=str(good))
        _seed_consumed(m, shard_id="bad", path=str(bad))

        _orig = janitor.delete_shard_files

        def selective(path):
            if path and Path(path).name == "bad.bin":
                raise OSError("simulated I/O failure")
            return _orig(path)

        monkeypatch.setattr(janitor, "delete_shard_files", selective)
        stats = reclaim_consumed(m)
        assert stats["deleted"] == 1
        assert stats["skipped_error"] == 1
        assert not good.exists()
        assert bad.exists()  # left alone after error


# ---------------------------------------------------------------------------
# Checkpoint rotation


def test_rotate_keeps_last_n_and_stables(tmp_path: Path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    for n in (100, 200, 300, 400):
        (ckpt / f"step_{n}.pt").write_bytes(b"x")
    (ckpt / "stable_p0.pt").write_bytes(b"s")
    (ckpt / "stable_p1.pt").write_bytes(b"s")
    (ckpt / "latest").write_text("step_400.pt", encoding="utf-8")
    (ckpt / "base_final.pt").write_bytes(b"f")

    removed = rotate_checkpoints(ckpt, keep_last=2, keep_stable=True)
    assert set(removed) == {"step_100.pt", "step_200.pt"}
    assert (ckpt / "step_300.pt").exists()
    assert (ckpt / "step_400.pt").exists()
    assert (ckpt / "stable_p0.pt").exists()
    assert (ckpt / "stable_p1.pt").exists()
    assert (ckpt / "latest").exists()
    assert (ckpt / "base_final.pt").exists()


def test_rotate_idempotent(tmp_path: Path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "step_1.pt").write_bytes(b"a")
    (ckpt / "step_2.pt").write_bytes(b"b")
    assert rotate_checkpoints(ckpt, keep_last=1, keep_stable=True) == ["step_1.pt"]
    assert rotate_checkpoints(ckpt, keep_last=1, keep_stable=True) == []
    assert (ckpt / "step_2.pt").exists()


# ---------------------------------------------------------------------------
# Service loop: watermark gate + --once


def test_run_once_only_reclaims_under_pressure(db_path, tmp_path: Path, monkeypatch):
    packed = tmp_path / "packed"
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "step_1.pt").write_bytes(b"a")
    (ckpt / "step_2.pt").write_bytes(b"b")
    bin_path = _write_packed(packed / "p0" / "train" / "t.bin")

    cfg = yaml.safe_load(PIPELINE_YAML.read_text())
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    with Manifest(db_path) as m:
        _seed_consumed(m, shard_id="t", path=str(bin_path))

    j = Janitor(
        config_path=str(cfg_path),
        db_path=db_path,
        packed_dir=str(packed),
        ckpt_dir=str(ckpt),
    )

    # Above trigger: no reclaim, but rotation still runs.
    monkeypatch.setattr(flow, "free_gb", lambda _p: 50.0)
    with Manifest(db_path) as m:
        out = j.run_once(m)
    assert out["pressure"] is False
    assert out["reclaimed"] is None
    assert bin_path.exists()
    assert out["ckpts_removed"] == ["step_1.pt"]  # keep_last=1

    # Under trigger: reclaim fires.
    monkeypatch.setattr(flow, "free_gb", lambda _p: 10.0)
    with Manifest(db_path) as m:
        out = j.run_once(m)
    assert out["pressure"] is True
    assert out["reclaimed"]["deleted"] == 1
    assert not bin_path.exists()


def test_cli_help_exits_zero():
    with pytest.raises(SystemExit) as ei:
        janitor.main(["--help"])
    assert ei.value.code == 0


def test_cli_once(tmp_path: Path, monkeypatch):
    cfg = yaml.safe_load(PIPELINE_YAML.read_text())
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    packed = tmp_path / "packed"
    ckpt = tmp_path / "ckpt"
    packed.mkdir()
    ckpt.mkdir()
    monkeypatch.setattr(flow, "free_gb", lambda _p: 50.0)
    # janitor binds free_gb at import; patch the local name too for disk_free_gb.
    monkeypatch.setattr(janitor, "free_gb", lambda _p: 50.0)
    rc = janitor.main([
        "--once",
        "--config", str(cfg_path),
        "--db", str(tmp_path / "m.db"),
        "--packed-dir", str(packed),
        "--ckpt-dir", str(ckpt),
    ])
    assert rc == 0
