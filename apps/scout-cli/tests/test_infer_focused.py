"""Focused regression tests for infer lane — six families, honest null VRAM, IO_MISSING, cache, pinning, 503."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from bigbang.plugins.infer.cli import (
    SUPPORTED_FAMILIES,
    TieredCache,
    cmd_hello,
    cmd_list,
    cmd_run,
    cmd_status,
)


def test_six_families_count():
    assert len(SUPPORTED_FAMILIES) == 6
    expected = {"glm52", "inkling", "kimi_k3", "deepseek_v4", "qwen3", "olmoe"}
    assert set(SUPPORTED_FAMILIES) == expected


def test_hello_ok():
    res = cmd_hello()
    assert res["ok"] is True
    assert res["data"]["ready"] is True


def test_list_has_six():
    res = cmd_list()
    assert res["ok"] is True
    data = res.get("data") or res
    # ok fallback returns data inside payload
    models = data.get("models") if "models" in data else data.get("data", {}).get("models", [])
    # when using real ok, it's in data.models
    if "data" in res and "models" in res["data"]:
        models = res["data"]["models"]
    assert len(models) == 6
    # each has params
    for m in models:
        assert "params" in m


def test_status_honest_null_vram():
    res = cmd_status()
    assert res["ok"] is True
    payload = res.get("data") or res
    placement = payload.get("placement") if "placement" in payload else payload.get("data", {}).get("placement")
    if "data" in res:
        placement = res["data"]["placement"]
    # On Hatch CPU box, vram_free_mb must be None (honest), never faked
    assert placement["vram_free_mb"] is None
    assert placement["ram_free_mb"] is None or isinstance(placement["ram_free_mb"], int)


def test_run_missing_dense_returns_io_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        res = cmd_run(model="glm52", prompt="hi", disk_root_str=str(root))
        assert res["ok"] is False
        assert res["errorClass"] == "IO_MISSING"
        assert "dense" in res["error"].lower()


def test_tiered_cache_mmap_and_hit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "glm52" / "experts"
        root.mkdir(parents=True)
        # write a fake expert
        expert_path = root / "expert_00000.int4"
        expert_path.write_bytes(b"\x00\x01\x02\x03" * 16)
        disk_root = Path(tmp)
        cache = TieredCache(disk_root, lru_slots=2)
        data = cache.get("expert_00000", "glm52")
        assert data is not None
        assert len(data) == 64
        assert cache.hits == 0
        assert cache.misses == 1
        # second get should be hit
        data2 = cache.get("expert_00000", "glm52")
        assert data2 == data
        assert cache.hits == 1


def test_tiered_cache_eviction_and_pinning():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "glm52" / "experts"
        root.mkdir(parents=True)
        for i in range(3):
            (root / f"expert_{i:05d}.int4").write_bytes(b"x" * 10)
        disk_root = Path(tmp)
        cache = TieredCache(disk_root, lru_slots=2, pinned=["glm52/expert_00000"])
        cache.get("expert_00000", "glm52")
        cache.get("expert_00001", "glm52")
        assert len(cache._lru) == 2
        # adding third should evict non-pinned, keep pinned
        cache.get("expert_00002", "glm52")
        assert len(cache._lru) == 2
        assert "glm52/expert_00000" in cache._lru  # pinned survives
        assert "glm52/expert_00001" not in cache._lru or "glm52/expert_00002" in cache._lru


def test_run_with_dense_but_no_forward_is_not_implemented():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        model_dir = root / "glm52"
        model_dir.mkdir(parents=True)
        (model_dir / "dense.int4").write_bytes(b"\x00" * 100)
        experts_dir = model_dir / "experts"
        experts_dir.mkdir()
        (experts_dir / "expert_00000.int4").write_bytes(b"\x01" * 10)
        res = cmd_run(model="glm52", prompt="hi", disk_root_str=str(root))
        assert res["ok"] is False
        assert res["errorClass"] == "NOT_IMPLEMENTED"
        assert "honest 503" in res["error"]


def test_unknown_model_bad_args():
    with tempfile.TemporaryDirectory() as tmp:
        res = cmd_run(model="unknown_xyz", prompt="hi", disk_root_str=tmp)
        assert res["ok"] is False
        assert res["errorClass"] == "BAD_ARGS"
