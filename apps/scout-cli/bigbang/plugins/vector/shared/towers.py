"""
ResidualTower — cat([x·m, m]) → 96h → 24d skip, L2-norm
Port of equities 17× ResidualTower, generalized to any sport.

Fixes vs v0.7.1 audit:
- Mask broadcast now correct: mask (B,1) or (B,in_dim) or None (presence = x!=0) unified handling
- Skip connection shape-safe: Identity only when in_dim==out_dim else Linear
- No silent shadowing of m variable; single codepath for xm = x * mask

Usage:
  tower = ResidualTower(in_dim=15, hidden=96, out_dim=24)
  z = tower(x, mask)  # x (B, in_dim), mask (B,1) or (B,in_dim) optional, returns (B, out_dim) L2-normed

Fused: 4-layer transformer d_model 128 4 heads CLS → 64-d L2-norm

Equities pattern: cat([x·m, m]) doubles feature + keeps presence signal for sparse XBRL.
Hoops: 130 features in 18 families, 17 towers (injury → durability head, not input tower)
Pitch: 24-d WC per-90 tournament-z
Gridiron: nflverse usage/snaps/age/weather/Vegas lines

Provenance-honest link: dumbmodel Hub reads same towers via shared lib, same as Dottie Hub.
"""
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ResidualTower(nn.Module):
        def __init__(self, in_dim: int, hidden: int = 96, out_dim: int = 24, p_drop: float = 0.1):
            super().__init__()
            self.in_dim = in_dim
            self.out_dim = out_dim
            self.fc1 = nn.Linear(in_dim * 2, hidden)  # cat([x·m,m]) => 2*in_dim -> hidden
            self.fc2 = nn.Linear(hidden, out_dim)
            # Skip only when shapes match; otherwise linear projection
            if in_dim != out_dim:
                self.skip = nn.Linear(in_dim, out_dim)
            else:
                self.skip = nn.Identity()
            self.dropout = nn.Dropout(p_drop)
            self.ln = nn.LayerNorm(out_dim)

        def _make_mask(self, x: torch.Tensor, mask: torch.Tensor | None) -> torch.Tensor:
            # x: (B, in_dim)
            B, D = x.shape
            assert D == self.in_dim, f"in_dim mismatch {D} != {self.in_dim}"
            if mask is None:
                # equity sparsity signal: presence from non-zero; keeps dense case as all-ones
                # For multi-dim, presence per-feature; for single dim treat as ones if x non-zero
                presence = (x != 0).float()
                # If all zeros (degenerate batch) presence would be 0 -> cat would be zeros; fallback to ones to avoid NaN norm
                # Keep presence as-is; xm will be zeros correctly representing missing
                return presence
            else:
                # mask provided: (B,1) broadcast to (B,D) or (B,D) as-is
                if mask.dim() == 2 and mask.size(0) == B:
                    if mask.size(1) == 1:
                        return mask.expand(-1, D).to(x.dtype)
                    elif mask.size(1) == D:
                        return mask.to(x.dtype)
                    else:
                        raise ValueError(f"mask dim 1 {mask.size(1)} must be 1 or {D}")
                else:
                    raise ValueError(f"mask shape {tuple(mask.shape)} expected (B,1) or (B,{D})")

        def forward(self, x, mask=None, normalize=True):
            # x: (B, in_dim), mask: (B, in_dim) or (B,1) or None
            m = self._make_mask(x, mask)  # (B, in_dim)
            xm = x * m
            cat = torch.cat([xm, m], dim=1)  # (B, 2*in_dim) — provenance: equities cat([x·m,m])
            h = F.gelu(self.fc1(cat))
            h = self.dropout(h)
            out = self.fc2(h)  # (B, out_dim)
            # Residual: projected x -> out_dim
            residual = self.skip(x) if not isinstance(self.skip, nn.Identity) else x
            # If Identity but in_dim==out_dim, shape matches; else we already projected
            # Handle edge where in_dim==out_dim but x contains NaN mask -> still add
            out = out + residual
            out = self.ln(out)
            if normalize:
                out = F.normalize(out, dim=1, eps=1e-6)
            return out

    class TransformerFusion(nn.Module):
        """4-layer transformer d_model 128 4 heads CLS → 64-d L2-norm (equities proven).

        CLS param shape: (1,1,d_model) — verified expand(B,-1,-1) => (B,1,d_model) for cat over towers.
        Keeps same as Dottie checkpoint parity: bundles/ultra runs timeline shows CLS as learnable.
        """
        def __init__(self, n_towers: int, in_dim: int = 24, d_model: int = 128, n_heads: int = 4, n_layers: int = 4, out_dim: int = 64):
            super().__init__()
            self.n_towers = n_towers
            self.proj = nn.ModuleList([nn.Linear(in_dim, d_model) for _ in range(n_towers)])
            # CLS token — shape (1,1,d_model) as used in ViT / equities MTNN v6 96-d proven
            self.cls = nn.Parameter(torch.randn(1, 1, d_model) * 0.02)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 2,
                batch_first=True, dropout=0.1, activation='gelu'
            )
            self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self.head = nn.Linear(d_model, out_dim)

        def forward(self, towers):
            # towers: list of (B, in_dim) length n_towers
            assert len(towers) == self.n_towers, f"expected {self.n_towers} towers got {len(towers)}"
            B = towers[0].size(0)
            for t in towers:
                assert t.size(0) == B, "batch mismatch"
            xs = []
            for i, t in enumerate(towers):
                xs.append(self.proj[i](t).unsqueeze(1))  # (B,1,d_model)
            x = torch.cat(xs, dim=1)  # (B, n_towers, d_model)
            cls = self.cls.expand(B, -1, -1)  # (B,1,d_model) — shape verified
            x = torch.cat([cls, x], dim=1)  # (B, 1+n_towers, d_model)
            x = self.transformer(x)
            cls_out = x[:, 0, :]  # (B, d_model)
            out = self.head(cls_out)  # (B, out_dim)
            return F.normalize(out, dim=1, eps=1e-6)

except ImportError:
    # torch optional for static-site path — allow import without torch for eval/export commands
    class ResidualTower:  # type: ignore
        def __init__(self, *a, **kw): raise RuntimeError("torch required for training — install torch to run vector train")
    class TransformerFusion:
        def __init__(self, *a, **kw): raise RuntimeError("torch required")

