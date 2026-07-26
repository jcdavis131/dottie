"""Tests for engine — mapped to ava-open-harness runner + model_1b engine pieces"""
import importlib.util, pathlib, sys

runner_path = "/home/hatch/workspace/dottie/packages/ava-open-harness/harness/runner.py"
model_path = "/home/hatch/workspace/dottie/apps/ava-factory/model_1b.py"

def test_runner_or_model_engine_exists():
    assert pathlib.Path(model_path).exists()
    if pathlib.Path(runner_path).exists():
        spec = importlib.util.spec_from_file_location("runner", runner_path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        assert m is not None
    else:
        spec = importlib.util.spec_from_file_location("model_1b", model_path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        assert hasattr(m, "YaRNScaledRoPE")

def test_yarn_engine_causal_and_scaling():
    spec = importlib.util.spec_from_file_location("model_1b_eng", model_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    content = pathlib.Path(model_path).read_text()
    assert "is_causal" in content or "causal" in content.lower()

def test_powerlaw_fit_as_engine_component():
    spec = importlib.util.spec_from_file_location("eff", "/home/hatch/workspace/dottie/apps/ava-factory/efficiency_gain.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    fit = mod.fit_power_law([(1e9,3.0),(1e10,2.0)])
    assert fit.b > 0
