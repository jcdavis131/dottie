"""
ResidualTower — cat([x·m, m]) → 96h → 24d skip, L2-norm
Port of equities 17× ResidualTower, generalized to any sport.

Usage:
  tower = ResidualTower(in_dim=15, hidden=96, out_dim=24)
  z = tower(x, mask)  # x (B, in_dim), mask (B,1) optional, returns (B, out_dim) L2-normalized if requested
Fused: 4-layer transformer d_model 128 4 heads CLS → 64-d L2-norm

Equities pattern: cat([x·m, m]) doubles feature + keeps presence signal for sparse XBRL.
Hoops: 130 features in 18 families, 17 towers (injury → durability head, not input tower)
Pitch: 24-d WC per-90 tournament-z
Gridiron: nflverse usage/snaps/age/weather/Vegas lines
"""
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ResidualTower(nn.Module):
        def __init__(self, in_dim: int, hidden: int = 96, out_dim: int = 24, p_drop: float = 0.1):
            super().__init__()
            self.in_dim = in_dim
            self.fc1 = nn.Linear(in_dim*2, hidden)  # cat([x·m,m])
            self.fc2 = nn.Linear(hidden, out_dim)
            self.skip = nn.Linear(in_dim, out_dim) if in_dim != out_dim else nn.Identity()
            self.dropout = nn.Dropout(p_drop)
            self.ln = nn.LayerNorm(out_dim)

        def forward(self, x, mask=None, normalize=True):
            # x: (B, in_dim), mask: (B, in_dim) or (B,1)
            if mask is None:
                m = torch.ones_like(x[:, :1]) if x.dim()==2 else torch.ones_like(x)
                m = m.expand_as(x) if x.dim()==2 else m
                if x.size(1)==1:
                    m = m
                else:
                    # broadcast single col to full
                    if m.size(1)==1:
                        m = m.expand_as(x)
                # presence from non-zero (equities sparsity signal)
                presence = (x != 0).float() if self.in_dim>1 else torch.ones_like(x)
                # equities pattern: keep mask presence + value
                xm = x * presence
                cat = torch.cat([xm, presence], dim=1)
            else:
                if mask.size(1)==1:
                    m = mask.expand_as(x)
                else:
                    m = mask
                xm = x * m
                cat = torch.cat([xm, m], dim=1)
            h = F.gelu(self.fc1(cat))
            h = self.dropout(h)
            out = self.fc2(h)
            out = out + self.skip(x) if not isinstance(self.skip, nn.Identity) else out + x[:, :out.size(1)] if x.size(1)>=out.size(1) else out
            out = self.ln(out)
            if normalize:
                out = F.normalize(out, dim=1)
            return out

    class TransformerFusion(nn.Module):
        """4-layer transformer d_model 128 4 heads CLS → 64-d L2-norm (equities proven)."""
        def __init__(self, n_towers: int, in_dim: int = 24, d_model: int = 128, n_heads: int = 4, n_layers: int = 4, out_dim: int = 64):
            super().__init__()
            self.proj = nn.ModuleList([nn.Linear(in_dim, d_model) for _ in range(n_towers)])
            self.cls = nn.Parameter(torch.randn(1,1,d_model))
            layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=n_heads, dim_feedforward=d_model*2, batch_first=True)
            self.transformer = nn.TransformerEncoder(layer, num_layers=n_layers)
            self.head = nn.Linear(d_model, out_dim)

        def forward(self, towers):
            # towers: list of (B, in_dim) length n_towers
            B = towers[0].size(0)
            xs = []
            for i, t in enumerate(towers):
                xs.append(self.proj[i](t).unsqueeze(1))  # (B,1,d)
            x = torch.cat(xs, dim=1)  # (B, n_towers, d)
            cls = self.cls.expand(B, -1, -1)
            x = torch.cat([cls, x], dim=1)
            x = self.transformer(x)
            cls_out = x[:,0,:]
            out = self.head(cls_out)
            return F.normalize(out, dim=1)

except ImportError:
    # torch optional for static-site path — allow import without torch for eval/export commands
    class ResidualTower:  # type: ignore
        def __init__(self, *a, **kw): raise RuntimeError("torch required for training — install torch to run vector train")
    class TransformerFusion:
        def __init__(self, *a, **kw): raise RuntimeError("torch required")

except Exception as e:
    # fallback stub
    pass
