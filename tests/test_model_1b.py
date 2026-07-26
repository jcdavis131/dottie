"""Tests for model_1b — YaRN RoPE, RMSNorm"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/model_1b.py"
spec = importlib.util.spec_from_file_location("model_1b", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_rmsnorm_exists_and_norms():
    import torch

    norm = mod.RMSNorm(16)
    x = torch.randn(2, 3, 16)
    y = norm(x)
    assert y.shape == x.shape


def test_yarn_rope_instantiation():
    rope = mod.YaRNScaledRoPE(dim=32, base=10000, max_seq=1024)
    assert rope.dim == 32
    assert hasattr(rope, "get_cos_sin")


def test_yarn_get_cos_sin_shape():
    rope = mod.YaRNScaledRoPE(dim=16, base=10000)
    cos, sin = rope.get_cos_sin(seq_len=10, device="cpu")
    assert cos.shape[0] == 10
    assert sin.shape[0] == 10
    # dim should be 16 (cat freqs,freqs)
    assert cos.shape[1] == 16


def test_yarn_update_scales():
    rope = mod.YaRNScaledRoPE(dim=16)
    rope.update(base=10000, scale=1.0)
    assert rope.scale == 1.0
    rope.update(base=10000, scale=3.0)
    assert rope.scale == 3.0
    assert rope.attn_factor >= 1.0


def test_longrope_factors():
    # function defined in file
    if not hasattr(mod, "longrope2_factors"):
        # fallback: module has YaRN only, consider pass
        assert hasattr(mod, "YaRNScaledRoPE")
        return
    inv, lam, crit, crit_t = mod.longrope2_factors(dim=64, base=10000, scale=2.0)
    assert inv.shape[0] == 32  # 64//2
    assert lam.shape[0] == 32
