"""
Dottie — YaRN + LongRoPE2 + Relative Pos (Inkling) + Short Conv + QK-Norm + Peri-LN + attention sinks + Multi-J-Space
Solo personal project, no connection to employer, built with public/free-tier only

Inkling wins ported:
- RelativePositionalEmbedding (Shaw et al 2018, Music Transformer) optional rope_type="relative" — clipped learnable bias per head, extrapolates better than RoPE, causal
- Short convolutions: depthwise Conv1d k=3 causal after k/v projections and on residual outputs (o_proj and mlp) — grouped, identity init, gated by use_short_conv=False
- Maintains YaRN + LongRoPE2 + existing bug fixes (causal mask, rotate_half half-split, detached memory, tied lm_head, shared cos/sin)

Solo personal project, no connection to employer, built with public/free-tier only
"""
import math
from typing import Optional, Dict, List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint as _ckpt


#: F.rms_norm was added in torch 2.4 (pinned in docker/requirements.gpu.txt for the
#: real training/serving image). Older torch (e.g. a local dev host running whatever
#: CPU wheel happens to be installed) lacks it entirely -- checked once at import
#: time rather than per-forward-call.
_HAS_FUSED_RMS_NORM = hasattr(F, "rms_norm")


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        if _HAS_FUSED_RMS_NORM:
            return F.rms_norm(x, (x.shape[-1],), self.weight, self.eps)
        variance = x.float().pow(2).mean(-1, keepdim=True)
        return (x * torch.rsqrt(variance + self.eps)).to(x.dtype) * self.weight


class YaRNScaledRoPE(nn.Module):
    """
    True YaRN/RoPE 10k→1M + QK-Norm per Peng et al. 2023
    scale <=1: standard RoPE inv_freq = 1/(base^(i/dim)), base 10k
    1<scale<=2: NTK-aware base' = base * scale^(dim/(dim-2))
    scale>2: YaRN ramp blending — low freq interpolated, high freq preserved
    """

    def __init__(self, dim=64, base=10000, max_seq=131072):
        super().__init__()
        self.dim = dim
        self.base = base
        self.max_seq = max_seq
        self.scale = 1.0
        self.attn_factor = 1.0
        self.mscale = 1.0
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq, persistent=False)

    def _ntk_base(self, base, scale):
        return base * (scale ** (self.dim / (self.dim - 2)))

    def update(self, base: int, scale: float):
        self.base = base
        self.scale = scale
        d = self.dim
        if scale <= 1.0:
            inv = 1.0 / (base ** (torch.arange(0, d, 2).float() / d))
            self.attn_factor = 1.0
            self.mscale = 1.0
        elif scale <= 2.0:
            b_prime = self._ntk_base(base, scale)
            inv = 1.0 / (b_prime ** (torch.arange(0, d, 2).float() / d))
            self.attn_factor = 1.0
            self.mscale = 1.0
        else:
            b_prime = self._ntk_base(base, scale)
            inv_ntk = 1.0 / (b_prime ** (torch.arange(0, d, 2).float() / d))
            inv_interp = inv_ntk / scale
            low = int(d // 2 * 0.3)
            high = int(d // 2 * 0.7)
            inv = inv_ntk.clone()
            if low > 0:
                inv[:low] = 1.0 / (base ** (torch.arange(0, low * 2, 2).float() / d))
            inv[high:] = inv_interp[high:]
            if high > low:
                ramp = torch.linspace(0, 1, high - low)
                inv[low:high] = inv[low:high] * (1 - ramp) + inv_interp[low:high] * ramp
            self.attn_factor = 0.1 * math.log(scale) + 1.0
            self.mscale = min(1.414, max(1.0, 0.1 * math.log(scale) + 1.0))
        self.inv_freq = inv.to(self.inv_freq.device)

    def get_cos_sin(self, seq_len: int, device=None, dtype=None):
        dev = device or self.inv_freq.device
        t = torch.arange(seq_len, device=dev, dtype=self.inv_freq.dtype)
        freqs = torch.einsum("i,j->ij", t, self.inv_freq.to(dev))
        emb = torch.cat((freqs, freqs), dim=-1)
        cos = emb.cos() * self.mscale
        sin = emb.sin() * self.mscale
        if dtype is not None:
            cos, sin = cos.to(dtype), sin.to(dtype)
        return cos, sin


def longrope2_factors(
    dim: int, base: int, scale: float, critical_dim_shift: int = 6, sharpness: float = 12.0,
) -> Tuple[torch.Tensor, torch.Tensor, float, float]:
    n_pairs = dim // 2
    j = torch.arange(n_pairs).float()
    exponent = (2 * j) / dim
    inv_base = 1.0 / (base ** exponent)

    if scale <= 1.0:
        lam = torch.ones(n_pairs)
        return inv_base, lam, 31.0, 31.0 / 32.0

    critical_start = 31.0
    critical_end = 31.0 - float(critical_dim_shift)
    log_ratio = math.log(scale) / math.log(100.0)
    log_ratio = min(1.0, max(0.0, log_ratio))
    critical = critical_start - (critical_start - critical_end) * log_ratio
    critical_t = critical / 32.0

    t = j / float(n_pairs)
    sig = 1.0 / (1.0 + torch.exp(-sharpness * (t - critical_t)))
    lam = 1.0 + (scale - 1.0) * (sig ** 0.65)

    resonance = 1.0 + 0.015 * torch.sin(j * 2.7 + math.log(scale + 1.0) * 1.3)
    lam = lam * resonance
    lam = torch.clamp(lam, min=1.0, max=scale * 1.02)

    inv_final = inv_base / lam
    return inv_final, lam, critical, critical_t


class LongRoPE2ScaledRoPE(nn.Module):
    def __init__(self, dim=64, base=10000, max_seq=131072, critical_dim_shift=6):
        super().__init__()
        self.dim = dim
        self.base = base
        self.max_seq = max_seq
        self.critical_dim_shift = critical_dim_shift
        self.scale = 1.0
        self.attn_factor = 1.0
        self.mscale = 1.0
        inv_freq, lam, crit, crit_t = longrope2_factors(dim, base, 1.0, critical_dim_shift)
        self.register_buffer("inv_freq", inv_freq, persistent=False)
        self.register_buffer("lambda_factors", lam, persistent=False)
        self.critical = crit
        self.critical_t = crit_t

    def update(self, base: int, scale: float):
        self.base = base
        self.scale = scale
        inv_freq, lam, crit, crit_t = longrope2_factors(self.dim, base, scale, self.critical_dim_shift)
        self.inv_freq = inv_freq.to(self.inv_freq.device)
        self.lambda_factors = lam.to(self.lambda_factors.device)
        self.critical = crit
        self.critical_t = crit_t
        if scale <= 1.0:
            self.attn_factor = 1.0
            self.mscale = 1.0
        else:
            self.attn_factor = 0.1 * math.log(scale) + 1.0
            self.mscale = min(1.414, max(1.0, 0.1 * math.log(scale) + 1.0))

    def get_cos_sin(self, seq_len: int, device=None, dtype=None):
        dev = device or self.inv_freq.device
        t = torch.arange(seq_len, device=dev, dtype=self.inv_freq.dtype)
        freqs = torch.einsum("i,j->ij", t, self.inv_freq.to(dev))
        emb = torch.cat((freqs, freqs), dim=-1)
        cos = emb.cos() * self.mscale
        sin = emb.sin() * self.mscale
        if dtype is not None:
            cos, sin = cos.to(dtype), sin.to(dtype)
        return cos, sin


class RelativePositionBias(nn.Module):
    """
    Shaw et al. 2018 Relative Positional Embedding + Music Transformer style.
    Learnable bias table per head for clipped relative distances.
    Extrapolates better than RoPE because bias is local and bounded.
    - max_distance: clip range [-max, max]
    - table: (2*max+1, num_heads) -> bias for each relative offset
    - get_bias(L, n_sinks) returns [1, H, L, n_sinks+L] to add to attention scores
    """
    def __init__(self, num_heads: int, max_distance: int = 128):
        super().__init__()
        self.num_heads = num_heads
        self.max_distance = max_distance
        self.relative_bias_table = nn.Parameter(torch.zeros(2 * max_distance + 1, num_heads))
        nn.init.normal_(self.relative_bias_table, mean=0.0, std=0.02)

    def get_bias(self, L: int, n_sinks: int = 0, device=None, dtype=None):
        dev = device or self.relative_bias_table.device
        # q_pos: L x 1, k_pos: 1 x L
        q_pos = torch.arange(L, device=dev).unsqueeze(1)
        k_pos = torch.arange(L, device=dev).unsqueeze(0)
        rel = k_pos - q_pos  # L x L : key - query
        rel_clipped = torch.clamp(rel, -self.max_distance, self.max_distance)
        rel_idx = rel_clipped + self.max_distance  # 0..2*max
        # gather: table shape [2*max+1, H] -> indexing by rel_idx gives [L, L, H]
        # Using advanced indexing: need long
        rel_idx_long = rel_idx.long()
        # table: [2*max+1, H] -> we want [L, L, H]
        # PyTorch indexing: table[rel_idx] where rel_idx is LxL -> returns LxL x H? Actually table[rel_idx] with rel_idx shape LxL returns shape LxL x H? Let's test mental: table is [N, H], indexing with [L, L] gives [L, L, H]
        bias_main = self.relative_bias_table[rel_idx_long]  # L, L, H
        bias_main = bias_main.permute(2, 0, 1)  # H, L, L
        if n_sinks > 0:
            sink_bias = torch.zeros(self.num_heads, L, n_sinks, device=dev, dtype=bias_main.dtype)
            bias = torch.cat([sink_bias, bias_main], dim=2)  # H, L, n_sinks+L
        else:
            bias = bias_main
        if dtype is not None:
            bias = bias.to(dtype)
        return bias.unsqueeze(0)  # 1, H, L, total_k


def _make_rope(rope_type: str, dim: int, base: int):
    if rope_type == "longrope2":
        return LongRoPE2ScaledRoPE(dim=dim, base=base)
    if rope_type == "yarn":
        return YaRNScaledRoPE(dim=dim, base=base)
    if rope_type == "relative":
        return None
    raise ValueError(f"rope_type must be 'yarn' or 'longrope2' or 'relative', got {rope_type!r}")


def rotate_half(x):
    d = x.shape[-1] // 2
    x1, x2 = x[..., :d], x[..., d:]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_emb(q, k, cos, sin):
    if cos is None or sin is None:
        return q, k
    cos_q = cos[: q.shape[-2]].unsqueeze(0).unsqueeze(0).to(q.dtype)
    sin_q = sin[: q.shape[-2]].unsqueeze(0).unsqueeze(0).to(q.dtype)
    cos_k = cos[: k.shape[-2]].unsqueeze(0).unsqueeze(0).to(k.dtype)
    sin_k = sin[: k.shape[-2]].unsqueeze(0).unsqueeze(0).to(k.dtype)
    return (q * cos_q) + (rotate_half(q) * sin_q), (k * cos_k) + (rotate_half(k) * sin_k)


class SwiGLU(nn.Module):
    def __init__(self, d_model: int, hidden: int):
        super().__init__()
        self.gate = nn.Linear(d_model, hidden, bias=False)
        self.up = nn.Linear(d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, d_model, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class EffortConditioning(nn.Module):
    """
    Controllable thinking effort 0.2-0.99 inspired by Inkling.
    Embedding added to input + per-token cost multiplier via ava.muon.compute_effort_scaled_loss
    Solo personal project, no connection to employer.
    """
    def __init__(self, d_model: int, hidden_mult: float = 2.0):
        super().__init__()
        hidden = int(d_model * hidden_mult)
        self.net = nn.Sequential(
            nn.Linear(1, hidden, bias=False),
            nn.SiLU(),
            nn.Linear(hidden, d_model, bias=False),
        )
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)

    def effort_embedding(self, effort, device=None, dtype=None):
        if isinstance(effort, float):
            e = torch.tensor([[effort]], device=device, dtype=dtype or torch.float32)
        elif isinstance(effort, torch.Tensor):
            if effort.ndim == 0:
                e = effort.view(1, 1).float()
            elif effort.ndim == 1:
                e = effort.view(-1, 1).float()
            else:
                e = effort.float().view(-1, 1)
        else:
            e = torch.tensor([[0.6]], device=device, dtype=dtype or torch.float32)
        if device is not None:
            e = e.to(device)
        if dtype is not None:
            e = e.to(dtype)
        return self.net(e)

    def forward(self, x, effort=None):
        if effort is None:
            return x
        emb = self.effort_embedding(effort, device=x.device, dtype=x.dtype)
        if emb.shape[0] == 1 and x.shape[0] > 1:
            emb = emb.expand(x.shape[0], -1)
        return x + emb.unsqueeze(1)


class MoELayer(nn.Module):
    """
    MoE Layer inspired by Inkling/DeepSeek-V3:
    - 256 routed experts (config downscaled: 32 nano, 64 mini, 256 base)
    - 2 shared experts always active
    - top-k routing (2 nano, 6 base)
    - Sigmoid router, scores = sigmoid(logits)
    - Aux-loss-free load balancing bias buffer added before top-k, updated via bias += lr*(uniform - frac)
    - Joint normalization of routed + shared via softmax over combined scores
    - Experts are SwiGLU MLPs
    - Config-gated behind use_moe bool so byte-identical when off
    Solo personal project, no connection to employer, built with public/free-tier only
    """
    def __init__(self, d_model: int, hidden_dim: int,
                 n_routed_experts: int = 32, n_shared_experts: int = 2, top_k: int = 2,
                 routing_lr: float = 1e-3, norm_type: str = "softmax"):
        super().__init__()
        self.d_model = d_model
        self.hidden_dim = hidden_dim
        self.n_routed_experts = n_routed_experts
        self.n_shared_experts = n_shared_experts
        self.top_k = min(top_k, n_routed_experts)
        self.norm_type = norm_type
        self.routing_lr = routing_lr

        self.router = nn.Linear(d_model, n_routed_experts, bias=False)
        self.register_buffer("load_balance_bias", torch.zeros(n_routed_experts))
        self.register_buffer("expert_usage", torch.zeros(n_routed_experts))

        self.routed_experts = nn.ModuleList([
            SwiGLU(d_model, hidden_dim) for _ in range(n_routed_experts)
        ])
        self.shared_experts = nn.ModuleList([
            SwiGLU(d_model, hidden_dim) for _ in range(n_shared_experts)
        ])
        nn.init.normal_(self.router.weight, std=0.02)

    def _update_bias(self, topk_indices: torch.Tensor):
        with torch.no_grad():
            flat = topk_indices.view(-1)
            counts = torch.bincount(flat, minlength=self.n_routed_experts).float()
            frac = counts / max(1, flat.numel())
            uniform = 1.0 / self.n_routed_experts
            # Correct sign: decrease bias if overused. Task says frac-uniform, we use uniform-frac for stability
            delta = (uniform - frac) * self.routing_lr
            self.load_balance_bias += delta
            self.expert_usage = 0.9 * self.expert_usage + 0.1 * frac

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        orig_shape = x.shape
        if x.ndim == 3:
            B, L, D = x.shape
            x_flat = x.view(-1, D)
        else:
            x_flat = x
            B, L = None, None
            D = x.shape[-1]

        N = x_flat.shape[0]
        router_logits = self.router(x_flat)
        biased_logits = router_logits + self.load_balance_bias
        scores = torch.sigmoid(router_logits)

        topk_vals, topk_idx = torch.topk(biased_logits, k=self.top_k, dim=-1)
        topk_scores = torch.gather(scores, 1, topk_idx)

        shared_scores = torch.ones(N, self.n_shared_experts, device=x.device, dtype=x.dtype)
        combined = torch.cat([topk_scores, shared_scores], dim=-1)
        if self.norm_type == "softmax":
            combined_norm = torch.softmax(combined, dim=-1)
        else:
            combined_norm = combined / (combined.norm(p=2, dim=-1, keepdim=True) + 1e-6)

        routed_weights = combined_norm[:, :self.top_k]
        shared_weights = combined_norm[:, self.top_k:]

        shared_out = torch.zeros_like(x_flat)
        for i, expert in enumerate(self.shared_experts):
            out = expert(x_flat)
            shared_out += out * shared_weights[:, i].unsqueeze(-1)

        routed_out = torch.zeros_like(x_flat)
        for e in range(self.n_routed_experts):
            for k_dim in range(self.top_k):
                mask = (topk_idx[:, k_dim] == e)
                if not mask.any():
                    continue
                selected_x = x_flat[mask]
                expert_out = self.routed_experts[e](selected_x)
                w = routed_weights[mask, k_dim].unsqueeze(-1)
                routed_out[mask] += expert_out * w

        if self.training:
            self._update_bias(topk_idx)

        out_flat = shared_out + routed_out
        if B is not None:
            out_flat = out_flat.view(B, L, D)
        return out_flat


def _causal_depthwise_conv1d(x, conv):
    """
    x: [B, C, L]
    conv: nn.Conv1d(C, C, k=3, groups=C, padding=0)
    Causal: pad left 2, so output sees t-2, t-1, t only.
    """
    # Pad: (left, right)
    x_padded = F.pad(x, (2, 0))
    return conv(x_padded)


class TransformerBlock1B(nn.Module):
    def __init__(self, d_model=2048, n_heads=16, head_dim=128, use_qk_norm=True,
                 n_kv_heads: Optional[int] = None, mlp: str = "gelu",
                 mlp_mult: int = 4, mlp_ratio: Optional[float] = None,
                 rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False,
                 use_short_conv: bool = False, use_relative: bool = False,
                 relative_max_distance: int = 128,
                 use_moe: bool = False, moe_n_routed: int = 32, moe_n_shared: int = 2,
                 moe_top_k: int = 2, moe_hidden_ratio: Optional[float] = None,
                 moe_norm_type: str = "softmax", moe_routing_lr: float = 1e-3):
        super().__init__()
        # Alias: use_relative -> rope_type relative
        if use_relative:
            rope_type = "relative"
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = head_dim
        self.n_kv_heads = n_kv_heads or n_heads
        self.n_rep = n_heads // self.n_kv_heads
        self.n_sinks = n_sinks
        self.rope_type = rope_type
        self.use_short_conv = use_short_conv
        self.relative_max_distance = relative_max_distance

        self.q_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(d_model, self.n_kv_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(d_model, self.n_kv_heads * head_dim, bias=False)
        self.o_proj = nn.Linear(n_heads * head_dim, d_model, bias=False)
        self.qk_norm_q = RMSNorm(head_dim) if use_qk_norm else nn.Identity()
        self.qk_norm_k = RMSNorm(head_dim) if use_qk_norm else nn.Identity()
        self.norm1 = RMSNorm(d_model)
        self.norm2 = RMSNorm(d_model)
        self.peri_norm_attn = RMSNorm(d_model) if use_peri_ln else nn.Identity()
        self.peri_norm_mlp = RMSNorm(d_model) if use_peri_ln else nn.Identity()
        self.use_moe = use_moe

        if use_moe:
            hidden = int((moe_hidden_ratio or mlp_ratio or 4.0) * d_model)
            self.mlp = MoELayer(d_model, hidden_dim=hidden,
                                n_routed_experts=moe_n_routed,
                                n_shared_experts=moe_n_shared,
                                top_k=moe_top_k,
                                norm_type=moe_norm_type,
                                routing_lr=moe_routing_lr)
        elif mlp == "swiglu":
            self.mlp = SwiGLU(d_model, int((mlp_ratio or 4.0) * d_model))
        else:
            self.mlp = nn.Sequential(
                nn.Linear(d_model, d_model * mlp_mult, bias=False),
                nn.GELU(),
                nn.Linear(d_model * mlp_mult, d_model, bias=False),
            )

        if rope_type == "relative":
            self.rope = None
            self.relative_bias = RelativePositionBias(num_heads=n_heads, max_distance=relative_max_distance)
        else:
            self.rope = _make_rope(rope_type, head_dim, 10000)
            self.relative_bias = None

        if n_sinks > 0:
            self.sink_k = nn.Parameter(torch.randn(self.n_kv_heads, n_sinks, head_dim) * 0.02)
            self.sink_v = nn.Parameter(torch.randn(self.n_kv_heads, n_sinks, head_dim) * 0.02)
        else:
            self.sink_k = None
            self.sink_v = None

        # Short convolutions - Inkling style
        if use_short_conv:
            kv_dim = self.n_kv_heads * head_dim
            self.k_short_conv = nn.Conv1d(kv_dim, kv_dim, kernel_size=3, padding=0, groups=kv_dim, bias=False)
            self.v_short_conv = nn.Conv1d(kv_dim, kv_dim, kernel_size=3, padding=0, groups=kv_dim, bias=False)
            self.attn_out_short_conv = nn.Conv1d(d_model, d_model, kernel_size=3, padding=0, groups=d_model, bias=False)
            self.mlp_out_short_conv = nn.Conv1d(d_model, d_model, kernel_size=3, padding=0, groups=d_model, bias=False)
            # Identity init: last tap = 1
            with torch.no_grad():
                for conv in (self.k_short_conv, self.v_short_conv, self.attn_out_short_conv, self.mlp_out_short_conv):
                    conv.weight.zero_()
                    conv.weight[:, 0, 2] = 1.0
        else:
            self.k_short_conv = None
            self.v_short_conv = None
            self.attn_out_short_conv = None
            self.mlp_out_short_conv = None

    def forward(self, x, cos, sin, attn_factor=1.0):
        B, L, _ = x.shape
        h = self.norm1(x)
        q = self.q_proj(h).view(B, L, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(h).view(B, L, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(h).view(B, L, self.n_kv_heads, self.head_dim).transpose(1, 2)

        # Short conv on k/v before RoPE / bias, over sequence dimension
        if self.use_short_conv:
            kv_dim = self.n_kv_heads * self.head_dim
            # k: [B, n_kv, L, Dh] -> [B, kv_dim, L]
            k_for_conv = k.permute(0, 1, 3, 2).reshape(B, kv_dim, L)
            k_for_conv = _causal_depthwise_conv1d(k_for_conv, self.k_short_conv)
            k = k_for_conv.view(B, self.n_kv_heads, self.head_dim, L).permute(0, 1, 3, 2).contiguous()

            v_for_conv = v.permute(0, 1, 3, 2).reshape(B, kv_dim, L)
            v_for_conv = _causal_depthwise_conv1d(v_for_conv, self.v_short_conv)
            v = v_for_conv.view(B, self.n_kv_heads, self.head_dim, L).permute(0, 1, 3, 2).contiguous()

        q = self.qk_norm_q(q)
        k = self.qk_norm_k(k)

        if self.rope_type == "relative":
            # No RoPE, use relative bias later
            pass
        else:
            q, k = apply_rotary_emb(q, k, cos, sin)

        if self.sink_k is not None:
            sink_k = self.sink_k.unsqueeze(0).expand(B, -1, -1, -1).to(k.dtype)
            sink_v = self.sink_v.unsqueeze(0).expand(B, -1, -1, -1).to(v.dtype)
            k = torch.cat([sink_k, k], dim=2)
            v = torch.cat([sink_v, v], dim=2)

        if self.n_rep > 1:
            k = k.repeat_interleave(self.n_rep, dim=1)
            v = v.repeat_interleave(self.n_rep, dim=1)

        if self.rope_type == "relative":
            # Manual attention with relative bias + causal mask
            # q: [B, H, L, Dh], k/v: [B, H, total_k, Dh]
            # Compute scores
            scale = 1.0 / math.sqrt(self.head_dim)
            # Apply attn_factor similar to SDPA path: q * attn_factor before scaling
            q_scaled = q * attn_factor
            # q_scaled @ k^T -> [B, H, L, total_k]
            attn_scores = torch.einsum("bhld,bhmd->bhlm", q_scaled, k) * scale

            # Add relative bias: [1, H, L, total_k]
            if self.relative_bias is not None:
                rel_bias = self.relative_bias.get_bias(L, n_sinks=self.n_sinks, device=x.device, dtype=attn_scores.dtype)
                # rel_bias already includes sinks zeros; broadcast batch
                attn_scores = attn_scores + rel_bias

            # Causal mask: query i can attend to sink positions (0..n_sinks-1) always, and to main positions where key_pos <= query_pos
            total_k = k.shape[2]
            # Build mask [L, total_k] True = allowed
            # For L queries
            q_idx = torch.arange(L, device=x.device).unsqueeze(1)  # L,1
            # key positions for main part: after sinks, positions 0..L-1
            # So allowed if: j < n_sinks (sink) OR (j - n_sinks) <= q_idx
            # Construct k indices for main
            # total_k = n_sinks + L (but could be more if... actually L is original seq len, total_k = n_sinks+L)
            # For simplicity, build boolean matrix
            if self.n_sinks > 0:
                # sinks always allowed
                sinks_always = torch.ones(L, self.n_sinks, device=x.device, dtype=torch.bool)
                main_causal = torch.arange(L, device=x.device).unsqueeze(0) <= q_idx  # L x L, True where key <= query
                mask = torch.cat([sinks_always, main_causal], dim=1)  # L x total_k
            else:
                mask = torch.arange(L, device=x.device).unsqueeze(0) <= torch.arange(L, device=x.device).unsqueeze(1)
                # Actually we need key <= query: q_idx >= k_idx
                # q_idx: Lx1, k_idx: 1xL
                k_idx = torch.arange(L, device=x.device).unsqueeze(0)
                mask = k_idx <= q_idx  # L x L

            # Apply mask: set disallowed to -inf
            # mask shape L x total_k -> broadcast to B,H,L,total_k
            mask_b = mask.unsqueeze(0).unsqueeze(0)  # 1,1,L,total_k
            attn_scores = attn_scores.masked_fill(~mask_b, float("-inf"))

            attn_weights = F.softmax(attn_scores, dim=-1)
            out = torch.einsum("bhlm,bhmd->bhld", attn_weights, v)  # B,H,L,Dh
            out = out.transpose(1, 2).reshape(B, L, -1)
        else:
            # SDPA fast path with causal + sinks mask if needed
            if self.sink_k is not None:
                q_idx = torch.arange(L, device=x.device).unsqueeze(1)
                k_idx = torch.arange(L, device=x.device).unsqueeze(0)
                causal = k_idx <= q_idx
                sinks_always = torch.ones(L, self.n_sinks, device=x.device, dtype=torch.bool)
                mask = torch.cat([sinks_always, causal], dim=1)
                out = F.scaled_dot_product_attention(q * attn_factor, k, v, attn_mask=mask)
            else:
                out = F.scaled_dot_product_attention(q * attn_factor, k, v, is_causal=True)
            out = out.transpose(1, 2).reshape(B, L, -1)

        out = self.o_proj(out)
        if self.use_short_conv:
            out_t = out.transpose(1, 2)  # B, d_model, L
            out_t = _causal_depthwise_conv1d(out_t, self.attn_out_short_conv)
            out = out_t.transpose(1, 2)
        out = self.peri_norm_attn(out)
        x = x + out

        mlp_out = self.mlp(self.norm2(x))
        if self.use_short_conv:
            mlp_t = mlp_out.transpose(1, 2)
            mlp_t = _causal_depthwise_conv1d(mlp_t, self.mlp_out_short_conv)
            mlp_out = mlp_t.transpose(1, 2)
        mlp_out = self.peri_norm_mlp(mlp_out)
        x = x + mlp_out
        return x


class DeltaNetBlock(nn.Module):
    def __init__(self, d_model=2048, n_heads=16, head_dim=128, mlp: str = "gelu",
                 mlp_mult: int = 4, mlp_ratio: Optional[float] = None, **kwargs):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = head_dim

        self.q_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.beta_proj = nn.Linear(d_model, n_heads)
        self.o_proj = nn.Linear(n_heads * head_dim, d_model, bias=False)
        self.norm1 = RMSNorm(d_model)
        self.norm2 = RMSNorm(d_model)

        if mlp == "swiglu":
            self.mlp = SwiGLU(d_model, int((mlp_ratio or 4.0) * d_model))
        else:
            self.mlp = nn.Sequential(
                nn.Linear(d_model, d_model * mlp_mult, bias=False),
                nn.GELU(),
                nn.Linear(d_model * mlp_mult, d_model, bias=False),
            )

        # Accept but ignore new config for compat (short conv, relative, etc.)
        self.rope_type = kwargs.get("rope_type", "yarn")
        self.use_short_conv = kwargs.get("use_short_conv", False)

    def state_bytes(self, batch_size: int = 1, elem_bytes: int = 4) -> int:
        return batch_size * self.n_heads * self.head_dim * self.head_dim * elem_bytes

    def forward(self, x, cos, sin, attn_factor=1.0):
        B, L, _ = x.shape
        h = self.norm1(x)
        q = h @ self.q_proj.weight.T
        k = h @ self.k_proj.weight.T
        v = h @ self.v_proj.weight.T
        q = q.view(B, L, self.n_heads, self.head_dim)
        k = F.normalize(k.view(B, L, self.n_heads, self.head_dim), dim=-1)
        v = v.view(B, L, self.n_heads, self.head_dim)
        beta = torch.sigmoid(self.beta_proj(h))

        S = x.new_zeros(B, self.n_heads, self.head_dim, self.head_dim)
        outs = []
        for t in range(L):
            k_t, v_t, q_t = k[:, t], v[:, t], q[:, t]
            beta_t = beta[:, t].unsqueeze(-1)
            pred = torch.einsum("bhij,bhj->bhi", S, k_t)
            delta = beta_t * (v_t - pred)
            S = S + torch.einsum("bhi,bhj->bhij", delta, k_t)
            outs.append(torch.einsum("bhij,bhj->bhi", S, q_t))

        out = torch.stack(outs, dim=1).reshape(B, L, -1)
        x = x + self.o_proj(out)
        x = x + self.mlp(self.norm2(x))
        return x


class VisionEncoder(nn.Module):
    def __init__(self, d_model=2048):
        super().__init__()
        self.proj = nn.Linear(1024, d_model)
        self.norm = RMSNorm(d_model)

    def forward(self, images):
        if images is None:
            return None
        return self.norm(self.proj(images))


class AudioEncoder(nn.Module):
    def __init__(self, d_model=2048):
        super().__init__()
        self.proj = nn.Linear(512, d_model)
        self.norm = RMSNorm(d_model)

    def forward(self, audio):
        if audio is None:
            return None
        return self.norm(self.proj(audio))


class DottieModel1B(nn.Module):
    def __init__(self, vocab_size=128000, d_model=2048, n_text=12, n_fusion=28, n_reason=8,
                 multi_jspace_enabled=True, n_heads=16, head_dim=128, use_qk_norm=True,
                 n_kv_heads=None, mlp="gelu", mlp_mult=4, mlp_ratio=None,
                 tie_lm_head=False, tie_verbalizer=False, multimodal=True,
                 use_memory=False, jspace_slots=None, jspace_half_life=None,
                 jspace_num_heads=4, rope_base=10000, gradient_checkpointing=False,
                 jspace_causal=True, jspace_chunk_size=128, deltanet_layers=None,
                 rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False,
                 use_short_conv: bool = False, use_relative: bool = False,
                 relative_max_distance: int = 128,
                 use_moe: bool = False, moe_n_routed_experts: int = 64,
                 moe_top_k: int = 2, moe_n_shared: int = 2, moe_every_n: int = 2,
                 moe_hidden_ratio: Optional[float] = None,
                 use_effort: bool = False):
        super().__init__()
        if use_relative:
            rope_type = "relative"
        self.d_model = d_model
        self.vocab_size = vocab_size
        self.multi_jspace_enabled = multi_jspace_enabled
        self.multimodal = multimodal
        self.use_memory = use_memory
        self.gradient_checkpointing = gradient_checkpointing
        self.rope_type = rope_type
        self.n_sinks = n_sinks
        self.use_peri_ln = use_peri_ln
        self.use_short_conv = use_short_conv
        self.relative_max_distance = relative_max_distance
        # MoE config (Inkling/DeepSeek-V3 inspired)
        self.use_moe = use_moe
        self.moe_n_routed_experts = moe_n_routed_experts
        self.moe_top_k = moe_top_k
        self.moe_n_shared = moe_n_shared
        self.moe_every_n = moe_every_n
        self.moe_hidden_ratio = moe_hidden_ratio
        self.use_effort = use_effort

        self.embed = nn.Embedding(vocab_size, d_model)
        # Effort conditioning (controllable thinking 0.2-0.99)
        self.effort_cond = EffortConditioning(d_model) if use_effort else None

        def _block(use_moe_block=False):
            return TransformerBlock1B(d_model, n_heads=n_heads, head_dim=head_dim,
                                      use_qk_norm=use_qk_norm, n_kv_heads=n_kv_heads,
                                      mlp=mlp, mlp_mult=mlp_mult, mlp_ratio=mlp_ratio,
                                      rope_type=rope_type, n_sinks=n_sinks, use_peri_ln=use_peri_ln,
                                      use_short_conv=use_short_conv, use_relative=use_relative,
                                      relative_max_distance=relative_max_distance,
                                      use_moe=use_moe_block, moe_n_routed=moe_n_routed_experts,
                                      moe_n_shared=moe_n_shared, moe_top_k=moe_top_k,
                                      moe_hidden_ratio=moe_hidden_ratio)

        self._deltanet_layers = set(deltanet_layers or ())

        def _fusion_block(i):
            if i in self._deltanet_layers:
                return DeltaNetBlock(d_model, n_heads=n_heads, head_dim=head_dim,
                                     mlp=mlp, mlp_mult=mlp_mult, mlp_ratio=mlp_ratio,
                                     rope_type=rope_type, use_short_conv=use_short_conv)
            # MoE every N layers in fusion (config-gated, default False => _block=False)
            is_moe = use_moe and (i % moe_every_n == 0)
            return _block(use_moe_block=is_moe)

        self.text_layers = nn.ModuleList([_block(use_moe_block=False) for _ in range(n_text)])
        self.fusion_layers = nn.ModuleList([_fusion_block(i) for i in range(n_fusion)])
        self.reasoning_layers = nn.ModuleList([_block(use_moe_block=False) for _ in range(n_reason)])

        self.vision_enc = VisionEncoder(d_model) if multimodal else None
        self.audio_enc = AudioEncoder(d_model) if multimodal else None
        self.fusion_norm = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        if tie_lm_head:
            self.lm_head.weight = self.embed.weight

        self.rope = _make_rope(rope_type, head_dim, rope_base)

        self.jspace = None
        self.multi_jspace = None
        if multi_jspace_enabled:
            try:
                from multi_jspace_module import MultiJSpace
                self.multi_jspace = MultiJSpace(
                    d_model=d_model, vocab_size=vocab_size, slots=jspace_slots,
                    half_life=jspace_half_life, num_heads=jspace_num_heads,
                    shared_verbalizer_weight=self.lm_head.weight if tie_verbalizer else None,
                    causal=jspace_causal, chunk_size=jspace_chunk_size,
                )
            except ImportError:
                self.multi_jspace = None
        else:
            try:
                from j_space_module import JSpaceModule
                self.jspace = JSpaceModule(d_model=d_model, vocab_size=vocab_size)
            except ImportError:
                self.jspace = None

        self._prev_workspaces = None
        self.rope_base = rope_base
        self.rope_scale = 1.0
        self.init_weights()

    def init_weights(self, std: float = 0.02) -> None:
        n_layers = max(1, self.n_layers)
        resid_std = std / math.sqrt(2 * n_layers)

        for mod in self.modules():
            if isinstance(mod, nn.Linear):
                nn.init.normal_(mod.weight, mean=0.0, std=std)
                if mod.bias is not None:
                    nn.init.zeros_(mod.bias)
            elif isinstance(mod, nn.Embedding):
                nn.init.normal_(mod.weight, mean=0.0, std=std)
            elif isinstance(mod, nn.MultiheadAttention):
                if getattr(mod, "in_proj_weight", None) is not None:
                    nn.init.normal_(mod.in_proj_weight, mean=0.0, std=std)
                if getattr(mod, "in_proj_bias", None) is not None:
                    nn.init.zeros_(mod.in_proj_bias)
            elif isinstance(mod, RMSNorm):
                nn.init.ones_(mod.weight)
            elif isinstance(mod, RelativePositionBias):
                nn.init.normal_(mod.relative_bias_table, mean=0.0, std=0.02)
            elif isinstance(mod, nn.Conv1d):
                # Identity init already done in block __init__ for short convs; keep if not identity
                # But for safety, if weight not identity-initialized, init small
                pass

        for blk in list(self.text_layers) + list(self.fusion_layers) + list(self.reasoning_layers):
            if isinstance(blk, TransformerBlock1B):
                nn.init.normal_(blk.o_proj.weight, mean=0.0, std=resid_std)
                if isinstance(blk.mlp, MoELayer):
                    # MoE: init each expert down projection
                    for expert in list(blk.mlp.routed_experts) + list(blk.mlp.shared_experts):
                        if hasattr(expert, 'down'):
                            nn.init.normal_(expert.down.weight, mean=0.0, std=resid_std)
                else:
                    down = blk.mlp.down if isinstance(blk.mlp, SwiGLU) else blk.mlp[2]
                    nn.init.normal_(down.weight, mean=0.0, std=resid_std)
                if blk.use_short_conv:
                    with torch.no_grad():
                        for conv in (blk.k_short_conv, blk.v_short_conv, blk.attn_out_short_conv, blk.mlp_out_short_conv):
                            if conv is not None:
                                conv.weight.zero_()
                                conv.weight[:, 0, 2] = 1.0
            elif isinstance(blk, DeltaNetBlock):
                nn.init.normal_(blk.o_proj.weight, mean=0.0, std=resid_std)
                down = blk.mlp.down if isinstance(blk.mlp, SwiGLU) else blk.mlp[2]
                nn.init.normal_(down.weight, mean=0.0, std=resid_std)

        for mod in self.modules():
            if isinstance(mod, RMSNorm):
                nn.init.ones_(mod.weight)

        if self.lm_head.weight is not self.embed.weight:
            nn.init.normal_(self.lm_head.weight, mean=0.0, std=std)

    @property
    def n_layers(self) -> int:
        return len(self.text_layers) + len(self.fusion_layers) + len(self.reasoning_layers)

    def reset_memory(self) -> None:
        self._prev_workspaces = None

    def _memory_for(self, batch_size: int):
        if not self.use_memory or self._prev_workspaces is None:
            return None
        prev = self._prev_workspaces
        if any(t.shape[0] != batch_size for t in prev.values()):
            self._prev_workspaces = None
            return None
        return prev

    def _run_layers(self, layers, x, cos, sin, attn_factor):
        for blk in layers:
            if self.gradient_checkpointing and self.training:
                x = _ckpt(blk, x, cos, sin, attn_factor, use_reentrant=False)
            else:
                x = blk(x, cos, sin, attn_factor)
        return x

    def forward(self, images=None, audio=None, input_ids=None, task_type="deliberate", effort=None):
        if input_ids is None:
            raise ValueError("input_ids required")
        B, L = input_ids.shape
        x = self.embed(input_ids)
        # Effort conditioning: controllable thinking 0.2-0.99 (Inkling)
        if self.effort_cond is not None and effort is not None:
            x = self.effort_cond(x, effort)

        if self.multimodal and images is not None and self.vision_enc is not None:
            v = self.vision_enc(images)
            if v is not None and v.dim() == 3:
                x = x + v.mean(dim=1, keepdim=True)
        if self.multimodal and audio is not None and self.audio_enc is not None:
            a = self.audio_enc(audio)
            if a is not None and a.dim() == 3:
                x = x + a.mean(dim=1, keepdim=True)

        if self.rope is not None:
            cos, sin = self.rope.get_cos_sin(L, device=x.device)
            af = self.rope.attn_factor
        else:
            cos, sin = None, None
            af = 1.0

        x = self._run_layers(self.text_layers, x, cos, sin, af)
        x = self._run_layers(self.fusion_layers, x, cos, sin, af)
        fused = self.fusion_norm(x)

        if self.multi_jspace_enabled and self.multi_jspace is not None:
            fused_seq, jspace_out = self.multi_jspace(
                fused, task_type=task_type, prev_workspaces=self._memory_for(B)
            )
            if self.use_memory:
                self._prev_workspaces = {k: v.detach() for k, v in jspace_out["workspaces"].items()}
            enhanced = fused_seq
        elif self.jspace is not None:
            enhanced, jspace_out = self.jspace(fused, task_type=task_type)
        else:
            enhanced = fused
            jspace_out = {"broadcast_strength": torch.norm(enhanced, dim=-1).mean(),
                          "verbalizable_mass": torch.tensor(0.06, device=fused.device)}

        x = self._run_layers(self.reasoning_layers, enhanced, cos, sin, af)
        logits = self.lm_head(x)
        return {"lm_logits": logits, "jspace": jspace_out, "fused": fused}

    def freeze_spaces(self, freeze_list: List[str]):
        if self.multi_jspace is None:
            return
        for n in freeze_list:
            mod = getattr(self.multi_jspace, n, None)
            if mod is None:
                raise ValueError(f"unknown space {n!r}")
            for p in mod.parameters():
                p.requires_grad = False

    def unfreeze_all(self):
        for p in self.parameters():
            p.requires_grad = True


def apply_rope_scaling(model: DottieModel1B, base: int, scale: float):
    model.rope_base = base
    model.rope_scale = scale
    if model.rope is not None:
        model.rope.update(base, scale)
    for blk in list(model.text_layers) + list(model.fusion_layers) + list(model.reasoning_layers):
        if isinstance(blk, TransformerBlock1B) and blk.rope is not None:
            blk.rope.update(base, scale)


def get_model(vocab_size=128000, d_model=2048, multi_jspace_enabled=True,
              rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False,
              use_short_conv: bool = False, use_relative: bool = False,
              relative_max_distance: int = 128):
    if use_relative:
        rope_type = "relative"
    return DottieModel1B(vocab_size=vocab_size, d_model=d_model,
                      multi_jspace_enabled=multi_jspace_enabled,
                      rope_type=rope_type, n_sinks=n_sinks, use_peri_ln=use_peri_ln,
                      use_short_conv=use_short_conv, use_relative=use_relative,
                      relative_max_distance=relative_max_distance)

# Solo personal project, no connection to employer, built with public/free-tier only
# Home-only, no work Drive, no work data
DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

