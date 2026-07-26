
"""Tests for wandb_dashboard — chart definitions"""
import importlib.util
MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/wandb_dashboard.py"
spec = importlib.util.spec_from_file_location("wandb_dashboard", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_define_charts_returns_list():
    charts = mod.define_charts()
    assert isinstance(charts, list)
    assert len(charts) >= 5
    assert any("S1" in c for c in charts)

def test_charts_contain_expected_keys():
    charts = mod.define_charts()
    joined = " ".join(charts)
    assert "half_life" in joined
    assert "routing" in joined or "jspace" in joined
    assert "broadcast" in joined

def test_define_charts_prints(capsys):
    mod.define_charts()
    cap = capsys.readouterr()
    assert "W&B" in cap.out or "charts" in cap.out
