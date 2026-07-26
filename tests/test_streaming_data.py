"""Tests for streaming_data — PHASE_TOKENS, PHASE_MIX, BRANCH_MIX"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/streaming_data.py"
spec = importlib.util.spec_from_file_location("streaming_data", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_phase_tokens_structure():
    assert hasattr(mod, "PHASE_TOKENS")
    pts = mod.PHASE_TOKENS
    assert isinstance(pts, list)
    assert len(pts) == 6
    # each tuple len 5: name,start,end,seq_len,rope_base?
    for tup in pts:
        assert len(tup) == 5
        assert isinstance(tup[0], str)
        assert tup[1] < tup[2]


def test_phase_mix_weights_sum_to_one():
    assert hasattr(mod, "PHASE_MIX")
    for phase, mix in mod.PHASE_MIX.items():
        s = sum(mix.values())
        assert abs(s - 1.0) < 1e-6 or 0.9 < s < 1.1, f"{phase} sum {s}"


def test_branch_mix_contains_expected():
    assert hasattr(mod, "BRANCH_MIX")
    assert "code" in mod.BRANCH_MIX
    assert "math" in mod.BRANCH_MIX
    assert "chat" in mod.BRANCH_MIX


def test_source_to_task_mapping():
    assert hasattr(mod, "SOURCE_TO_TASK")
    assert "dclm" in mod.SOURCE_TO_TASK
    assert mod.SOURCE_TO_TASK["dclm"] == "automatic"
