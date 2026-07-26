"""Tests for j_space_module — JacobianLens and GlobalWorkspace"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/j_space_module.py"
spec = importlib.util.spec_from_file_location("j_space_module", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
try:
    spec.loader.exec_module(mod)
except Exception:
    # If torch missing, module failed earlier but torch is present per env
    raise


def test_jacobian_lens_instantiation():
    lens = mod.JacobianLens(d_model=32, vocab_size=100)
    assert lens.d_model == 32
    assert lens.vocab_size == 100


def test_concept_vector_deterministic_norm():
    lens = mod.JacobianLens(d_model=16, vocab_size=200)
    vec1, tid1 = lens.concept_vector("spider")
    vec2, tid2 = lens.concept_vector("spider")
    assert tid1 == tid2
    # normalized vector norm ~1
    assert abs(float(vec1.norm()) - 1.0) < 1e-3


def test_global_workspace_forward():
    import torch

    ws = mod.GlobalWorkspace(d_model=32, slots=4, vocab_size=100)
    B, L, D = 2, 5, 32
    fused = torch.randn(B, L, D)
    out, metrics = ws.forward(fused)
    assert out.shape == (B, L, D)
    assert "verbalizable_mass" in metrics
    assert "broadcast_strength" in metrics
    assert "half_life" in metrics


def test_half_life_property():
    ws = mod.GlobalWorkspace(d_model=16, slots=2, vocab_size=50)
    hl = ws.half_life
    assert isinstance(hl, float)
    assert hl > 0
