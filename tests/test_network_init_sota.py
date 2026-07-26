"""Tests for network_init_sota — AutoInit"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/network_init_sota.py"
spec = importlib.util.spec_from_file_location("network_init_sota", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_auto_init_model_exists():
    assert hasattr(mod, "auto_init_model")
    assert callable(mod.auto_init_model)


def test_auto_init_runs_on_simple_model():
    import torch
    import torch.nn as nn

    class Tiny(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(10, 8)
            self.lin = nn.Linear(8, 8)
            self.lin._layer_idx = 2
            self.norm = nn.LayerNorm(8)
            self.norm.weight = nn.Parameter(torch.ones(8))
            self.lm_head = nn.Linear(8, 10, bias=False)
            self.d_model = 8

        def forward(self, x):
            return x

    m = Tiny()
    # Capture old weight
    old_w = m.lin.weight.clone()
    mod.auto_init_model(m, std_base=0.02)
    # weight should have changed (normal init)
    assert not torch.equal(old_w, m.lin.weight)
    # norm weight should be 1
    assert torch.allclose(m.norm.weight, torch.ones(8))
    # lm_head scaled
    # Just ensure no crash and weight is finite
    assert torch.isfinite(m.lm_head.weight).all()


def test_auto_init_zero_bias():
    import torch
    import torch.nn as nn

    class M(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(4, 4)
            self.fc._layer_idx = 1
            self.d_model = 4

    model = M()
    model.fc.bias.data.fill_(5.0)
    mod.auto_init_model(model)
    assert torch.allclose(model.fc.bias, torch.zeros(4))
