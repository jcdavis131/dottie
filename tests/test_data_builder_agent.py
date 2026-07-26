"""Tests for data_builder_agent — ShardWriter and phase handling"""

import gzip
import importlib.util
import json
import sys

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/data_builder_agent.py"
spec = importlib.util.spec_from_file_location("data_builder_agent", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_shard_writer_writes_and_rotates(tmp_path):
    out = tmp_path / "shards"
    writer = mod.ShardWriter(out, source="test_src", shard_mb=1)  # 1MB for test
    assert writer.out_dir.exists()
    writer.write({"text": "hello", "id": 1})
    writer.write({"text": "world", "id": 2})
    assert writer.total_written == 2
    writer.close()
    # files should exist
    files = list(out.glob("*.jsonl.gz"))
    assert len(files) >= 1
    # verify gzip content
    with gzip.open(files[0], "rt", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) >= 1
    obj = json.loads(lines[0])
    assert "text" in obj


def test_shard_writer_rotation_on_small_threshold(tmp_path):
    out = tmp_path / "rot"
    w = mod.ShardWriter(
        out, source="rot_src", shard_mb=0
    )  # rotate immediately after one write
    # patch tiny to force rotate: any write >0 triggers rotate
    w.shard_mb = 0
    w.current_bytes = 0
    w.write({"a": "b" * 1000})
    # after write current_bytes >0, should rotate -> shard_idx increased
    assert w.shard_idx >= 1
    w.close()


def test_dolma_config_path_exists_handling():
    # DOLMA_CONFIG is Path object
    assert hasattr(mod, "DOLMA_CONFIG")
    # load_dolma_phases should work even if missing
    phases = mod.load_dolma_phases()
    assert isinstance(phases, list)
    assert len(phases) >= 1
    # each phase tuple length 4
    for p in phases:
        assert len(p) == 4


def test_gen_phi_textbook():
    txt = mod.gen_phi_textbook("induction")
    assert "induction" in txt.lower() or "Definition" in txt
    assert len(txt) > 20


def test_shard_writer_total_written_count(tmp_path):
    out = tmp_path / "cnt"
    w = mod.ShardWriter(out, source="cnt_src", shard_mb=10)
    for i in range(5):
        w.write({"i": i})
    assert w.total_written == 5
    w.close()
