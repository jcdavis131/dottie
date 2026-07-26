"""Tests for j_space_eval — 5 property tests"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/j_space_eval.py"
spec = importlib.util.spec_from_file_location("j_space_eval", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_all_property_funcs_exist():
    for name in [
        "test_verbal_report",
        "test_modulation",
        "test_internal_reasoning",
        "test_broadcast",
        "test_selectivity",
        "test_safety",
    ]:
        assert hasattr(mod, name)
        assert callable(getattr(mod, name))


def test_verbal_report_structure():
    res = mod.test_verbal_report()
    assert isinstance(res, dict)
    assert res["pass"] is True
    assert "mass" in res
    assert 0 < res["mass"] < 1


def test_modulation_structure():
    res = mod.test_modulation()
    assert res["pass"] is True
    assert "test" in res


def test_broadcast_and_selectivity():
    b = mod.test_broadcast()
    s = mod.test_selectivity()
    assert b["pass"] is True
    assert s["pass"] is True
    assert "test" in b


def test_safety():
    res = mod.test_safety()
    assert res["pass"] is True
    assert "leverage" in res["test"] or "Safety" in res["name"]
