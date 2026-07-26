
"""Tests for trainer_agent — load_phases and wait_for_ready logic"""
import importlib.util, pathlib, json, time
MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/trainer_agent.py"
spec = importlib.util.spec_from_file_location("trainer_agent", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_load_phases_fallback():
    # without dolma_config.yaml in /tmp
    phases = mod.load_phases()
    assert isinstance(phases, list)
    assert len(phases) >=1
    assert isinstance(phases[0], tuple)

def test_wait_for_ready_finds_shards(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    # create 2 shards
    (data_root / "shard_00000.jsonl.gz").write_text("dummy")
    (data_root / "shard_00001.jsonl.gz").write_text("dummy")
    # should quickly return True
    res = mod.wait_for_ready(data_root, "phase0_logic", poll_interval=1, timeout=2)
    assert res is True

def test_wait_for_ready_timeout_when_empty(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    start = time.time()
    res = mod.wait_for_ready(empty, "phaseX", poll_interval=1, timeout=1)
    elapsed = time.time() - start
    assert res is False
    assert elapsed >=1 and elapsed <3
