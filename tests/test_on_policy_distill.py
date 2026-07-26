"""Tests for on_policy_distill — configs and constants"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/on_policy_distill.py"
spec = importlib.util.spec_from_file_location("on_policy_distill", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_wsd_config_structure():
    assert hasattr(mod, "WSD_CONFIG")
    cfg = mod.WSD_CONFIG
    assert "warmup" in cfg and "stable_steps" in cfg
    assert cfg["warmup"] == 2000
    assert cfg["stable_steps"] == 736000


def test_rope_schedule_list():
    assert hasattr(mod, "ROPE_SCHEDULE")
    sched = mod.ROPE_SCHEDULE
    assert isinstance(sched, list)
    assert len(sched) >= 3
    assert all("base" in s and "ctx" in s for s in sched)


def test_branch_router_targets():
    assert hasattr(mod, "BRANCH_ROUTER_TARGETS")
    br = mod.BRANCH_ROUTER_TARGETS
    assert "code" in br and "math" in br and "chat" in br
    for k, v in br.items():
        assert isinstance(v, list) and len(v) == 4
        assert abs(sum(v) - 1.0) < 1e-6


def test_has_torch_flag():
    assert hasattr(mod, "HAS_TORCH")
    assert isinstance(mod.HAS_TORCH, bool)
