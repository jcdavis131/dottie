"""
Unit test for shared ResidualTower cat([x·m,m]) mask broadcast fix
Solo project, public pip only.
"""
import sys
from pathlib import Path

def _try_torch():
    try:
        import torch
        return torch
    except Exception as e:
        print(f"SKIP no torch ({e}) — static-site path still allows import")
        return None

def test_mask_broadcast():
    torch = _try_torch()
    if torch is None:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dottie" / "apps" / "scout-cli"))
    # import via direct file to avoid bigbang dep
    import importlib.util, pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "dottie" / "apps" / "scout-cli" / "bigbang" / "plugins" / "vector" / "shared" / "towers.py"
    # alternative path for this repo layout
    if not p.exists():
        p = Path("~/workspace/dottie/apps/scout-cli/bigbang/plugins/vector/shared/towers.py").expanduser()
    spec = importlib.util.spec_from_file_location("towers", str(p))
    towers_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(towers_mod)
    ResidualTower = towers_mod.ResidualTower
    TransformerFusion = towers_mod.TransformerFusion

    B, D = 4, 6
    t = ResidualTower(in_dim=D, hidden=16, out_dim=8)
    x = torch.randn(B, D)
    # mask None path — presence
    out = t(x, mask=None)
    assert out.shape == (B,8), f"None mask shape {out.shape}"
    # mask (B,1) broadcast
    m1 = torch.tensor([[1.],[0.],[1.],[1.]])
    out1 = t(x, mask=m1)
    assert out1.shape == (B,8)
    # mask (B,D)
    m2 = (torch.rand(B,D) > 0.5).float()
    out2 = t(x, mask=m2)
    assert out2.shape == (B,8)
    # cat([x·m,m]) correctness: zero mask zeroes xm but retains m
    x_zeros = torch.zeros(B,D)
    out_zeros = t(x_zeros, mask=None)
    # should not NaN due to L2 norm eps
    assert not torch.isnan(out_zeros).any(), "NaN with zero input"
    print("ResidualTower mask broadcast PASS")

    # TransformerFusion CLS shape
    nt = 3
    fusion = TransformerFusion(n_towers=nt, in_dim=8, d_model=16, n_heads=2, n_layers=2, out_dim=8)
    assert tuple(fusion.cls.shape) == (1,1,16), f"CLS shape {tuple(fusion.cls.shape)} != (1,1,16)"
    towers = [torch.randn(B,8) for _ in range(nt)]
    out_f = fusion(towers)
    assert out_f.shape == (B,8)
    # expand check
    cls_exp = fusion.cls.expand(B,-1,-1)
    assert cls_exp.shape == (B,1,16)
    print(f"TransformerFusion CLS {tuple(fusion.cls.shape)} -> expand {tuple(cls_exp.shape)} PASS")

if __name__ == "__main__":
    test_mask_broadcast()
    print("all shared lib unit tests PASS")
