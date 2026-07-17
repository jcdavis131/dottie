"""
Ava — YaRN + LongRoPE2 RoPE 10k→1M + QK-Norm + Peri-LN + attention sinks +
Multi-J-Space support
Solo personal project, no connection to employer, built with public/free-tier only

Fixed per specs/04_model_and_configs.md. The bugs that were here mattered:

  1. Attention had NO causal mask -- every position attended to the future, so
     the "language model" could trivially read the token it was predicting.
     Nothing trained on it could have worked. Now F.scaled_dot_product_attention
     with is_causal=True (also faster: flash/mem-efficient kernels).
  2. rotate_half() used interleaved pairing (x[..., ::2] / x[..., 1::2]) while
     get_cos_sin() builds cos/sin as cat((freqs, freqs)) -- the half-split
     (LLaMA) layout. The two disagreed, so RoPE applied a garbage rotation.
  3. _prev_workspaces was cached across forward passes without .detach(), so the
     second backward pass walked into a freed graph. Training could not reach
     step 2. Cross-step persistence is now opt-in (`use_memory`) and detached.
  4. lm_head was never tied to embed; heads/head_dim/layer counts were hardcoded
     at 16x128 regardless of d_model.
  5. cos/sin were recomputed inside every block despite all blocks sharing an
     identical RoPE. Computed once per forward now.

Also adds, config-gated, what base1b needs to fit in 12GB: grouped-query
attention (n_kv_heads) and SwiGLU, plus gradient checkpointing.

LongRoPE2 / Peri-LN / attention sinks (config-gated, default off -- see
tasks/plan-longrope2-port.md): ported from an independent line of work that
built these on top of the *original*, unfixed rotate_half()/get_cos_sin(),
so its own rotation had the same bug as (2) above. They're re-plumbed here
through the fixed rotate_half()/apply_rotary_emb() instead of bringing that
bug back, and attention sinks now compose with GQA (sinks live per KV-head
group, repeated the same way regular K/V are for grouped-query attention).
rope_type="longrope2" swaps in non-uniform per-dim RoPE factors (near-lossless
long-context scaling); use_peri_ln adds QK-L2-norm's counterpart output-LN
after attention and after the FFN; n_sinks>0 adds that many learnable,
always-attended KV pairs (Xiao et al. 2023) alongside the causal mask.
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
        # Fallback for torch<2.4: numerically identical to F.rms_norm --
        # x / sqrt(mean(x**2, dim=-1) + eps) * weight -- just not the fused kernel.
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
        emb = torch.cat((freqs, freqs), dim=-1)          # half-split layout
        cos = emb.cos() * self.mscale
        sin = emb.sin() * self.mscale
        if dtype is not None:
            cos, sin = cos.to(dtype), sin.to(dtype)
        return cos, sin


def longrope2_factors(
    dim: int, base: int, scale: float, critical_dim_shift: int = 6, sharpness: float = 12.0,
) -> Tuple[torch.Tensor, torch.Tensor, float, float]:
    """LongRoPE2 non-uniform per-dim RoPE factors + resonance mitigation.

    dim: head_dim (e.g. 64 -> 32 pairs, 128 -> 64 pairs).
    base: RoPE base (e.g. 10000).
    scale: extension factor (1 = original context, 100 = 100x, e.g. 10k->1M).
    critical_dim_shift: how far the "critical dimension" (the pair index past
        which interpolation dominates) moves as scale goes 1->100 -- 31->25
        for a 32-pair (head_dim=64) reference.

    Returns (inv_freq [n_pairs], lambda_factors [n_pairs], critical, critical_t).
    Per-dim lambda_i = 1 + (scale-1) * sigmoid_k(t - crit_t)^0.65 * resonance,
    interpolating low frequencies earlier than a linear ramp would (mimics the
    non-uniform schedule LongRoPE2's evolutionary search finds) while leaving
    high frequencies (small j, local position info) untouched.
    """
    n_pairs = dim // 2
    j = torch.arange(n_pairs).float()
    exponent = (2 * j) / dim
    inv_base = 1.0 / (base ** exponent)

    if scale <= 1.0:
        lam = torch.ones(n_pairs)
        return inv_base, lam, 31.0, 31.0 / 32.0

    # critical 31 -> 25 shift in log space: for scale=1 keep 31, for scale=100 -> 25
    critical_start = 31.0
    critical_end = 31.0 - float(critical_dim_shift)  # 25
    log_ratio = math.log(scale) / math.log(100.0)
    log_ratio = min(1.0, max(0.0, log_ratio))
    critical = critical_start - (critical_start - critical_end) * log_ratio
    critical_t = critical / 32.0  # ratio reference for 32 pairs; same proportion for other dims

    t = j / float(n_pairs)  # 0..~1
    # sigmoid sharpness k=12 gives a LongRoPE2-like steep-but-not-step ramp;
    # power 0.65 mimics evolutionary search pushing mid dims earlier than linear.
    sig = 1.0 / (1.0 + torch.exp(-sharpness * (t - critical_t)))
    lam = 1.0 + (scale - 1.0) * (sig ** 0.65)

    # Resonance mitigation: dimensions whose wavelength ~ seq_len cause attention
    # spikes. A small sinusoidal jitter (phase tied to log(scale)) avoids landing
    # on exact multiples.
    resonance = 1.0 + 0.015 * torch.sin(j * 2.7 + math.log(scale + 1.0) * 1.3)
    lam = lam * resonance

    lam = torch.clamp(lam, min=1.0, max=scale * 1.02)  # avoid overshoot

    inv_final = inv_base / lam
    return inv_final, lam, critical, critical_t


class LongRoPE2ScaledRoPE(nn.Module):
    """Near-lossless long-context RoPE via non-uniform per-dim factors.

    Same external interface as YaRNScaledRoPE (`.update()`, `.get_cos_sin()`,
    `.attn_factor`, `.mscale`) so callers (TransformerBlock1B, AvaModel1B,
    apply_rope_scaling) don't need to know which one they hold. Uses the same
    half-split cos/sin layout as YaRNScaledRoPE -- callers rotate with the
    module-level `rotate_half`/`apply_rotary_emb`, not a bespoke one, so this
    can't drift out of sync with them the way the pre-port version did.

    Ref: "LongRoPE2: Near-Lossless LLM Context Window Scaling" (arXiv 2412...).
    """

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
            # Same YaRN "10x less tokens to reach a given ctx" scaling as
            # YaRNScaledRoPE, so the two stay comparable at the same `scale`.
            self.attn_factor = 0.1 * math.log(scale) + 1.0
            self.mscale = min(1.414, max(1.0, 0.1 * math.log(scale) + 1.0))

    def get_cos_sin(self, seq_len: int, device=None, dtype=None):
        dev = device or self.inv_freq.device
        t = torch.arange(seq_len, device=dev, dtype=self.inv_freq.dtype)
        freqs = torch.einsum("i,j->ij", t, self.inv_freq.to(dev))
        emb = torch.cat((freqs, freqs), dim=-1)          # half-split layout
        cos = emb.cos() * self.mscale
        sin = emb.sin() * self.mscale
        if dtype is not None:
            cos, sin = cos.to(dtype), sin.to(dtype)
        return cos, sin


def _make_rope(rope_type: str, dim: int, base: int):
    if rope_type == "longrope2":
        return LongRoPE2ScaledRoPE(dim=dim, base=base)
    if rope_type == "yarn":
        return YaRNScaledRoPE(dim=dim, base=base)
    raise ValueError(f"rope_type must be 'yarn' or 'longrope2', got {rope_type!r}")


def rotate_half(x):
    """Half-split rotation, matching get_cos_sin's cat((freqs, freqs)) layout.

    The old interleaved version (x[..., ::2] / x[..., 1::2]) paired dimension i
    with i+1, but cos/sin pair dimension i with i + dim/2. Mixing the two
    conventions rotates by an arbitrary angle per dimension.
    """
    d = x.shape[-1] // 2
    x1, x2 = x[..., :d], x[..., d:]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_emb(q, k, cos, sin):
    # q,k: [B, H, L, D]; cos,sin: [L, D] -> broadcast over batch and heads
    cos_q = cos[: q.shape[-2]].unsqueeze(0).unsqueeze(0).to(q.dtype)
    sin_q = sin[: q.shape[-2]].unsqueeze(0).unsqueeze(0).to(q.dtype)
    cos_k = cos[: k.shape[-2]].unsqueeze(0).unsqueeze(0).to(k.dtype)
    sin_k = sin[: k.shape[-2]].unsqueeze(0).unsqueeze(0).to(k.dtype)
    return (q * cos_q) + (rotate_half(q) * sin_q), (k * cos_k) + (rotate_half(k) * sin_k)


class SwiGLU(nn.Module):
    """Gated MLP. base1b uses this at mlp_ratio=1.0 to land at ~1.17B params;
    the blueprint's dense 4x GELU at d2048x48 layers alone is 2.4B and will not
    fit 12GB with optimizer state."""

    def __init__(self, d_model: int, hidden: int):
        super().__init__()
        self.gate = nn.Linear(d_model, hidden, bias=False)
        self.up = nn.Linear(d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, d_model, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class TransformerBlock1B(nn.Module):
    def __init__(self, d_model=2048, n_heads=16, head_dim=128, use_qk_norm=True,
                 n_kv_heads: Optional[int] = None, mlp: str = "gelu",
                 mlp_mult: int = 4, mlp_ratio: Optional[float] = None,
                 rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = head_dim
        self.n_kv_heads = n_kv_heads or n_heads
        self.n_rep = n_heads // self.n_kv_heads
        self.n_sinks = n_sinks

        self.q_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(d_model, self.n_kv_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(d_model, self.n_kv_heads * head_dim, bias=False)
        self.o_proj = nn.Linear(n_heads * head_dim, d_model, bias=False)
        self.qk_norm_q = RMSNorm(head_dim) if use_qk_norm else nn.Identity()
        self.qk_norm_k = RMSNorm(head_dim) if use_qk_norm else nn.Identity()
        self.norm1 = RMSNorm(d_model)
        self.norm2 = RMSNorm(d_model)
        # Peri-LN: an output-LN after attention and after the FFN, on top of the
        # pre-LN (norm1/norm2) this block already had. QK-norm + output-LN
        # together improve loss/stability at 400M-1B (Peri-LN paper). Identity
        # (a pure no-op, not just "small") when off, so this can't perturb the
        # default path at all, floating point included.
        self.peri_norm_attn = RMSNorm(d_model) if use_peri_ln else nn.Identity()
        self.peri_norm_mlp = RMSNorm(d_model) if use_peri_ln else nn.Identity()

        if mlp == "swiglu":
            self.mlp = SwiGLU(d_model, int((mlp_ratio or 4.0) * d_model))
        else:
            self.mlp = nn.Sequential(
                nn.Linear(d_model, d_model * mlp_mult, bias=False),
                nn.GELU(),
                nn.Linear(d_model * mlp_mult, d_model, bias=False),
            )
        # Kept for backward compat with apply_rope_scaling(); the model computes
        # cos/sin once per forward from its own rope and passes them in.
        self.rope = _make_rope(rope_type, head_dim, 10000)

        # n_sinks learnable KV pairs (Xiao et al. 2023, StreamingLLM), always
        # attended regardless of position -- absorb the softmax mass early
        # tokens otherwise soak up as attention sinks by accident. One pair
        # per KV-head group (not per query head), so they compose with GQA
        # the same way regular K/V do: concatenate at the KV-head count, then
        # repeat_interleave up to n_heads.
        if n_sinks > 0:
            self.sink_k = nn.Parameter(torch.randn(self.n_kv_heads, n_sinks, head_dim) * 0.02)
            self.sink_v = nn.Parameter(torch.randn(self.n_kv_heads, n_sinks, head_dim) * 0.02)
        else:
            self.sink_k = None
            self.sink_v = None

    def forward(self, x, cos, sin, attn_factor=1.0):
        B, L, _ = x.shape
        h = self.norm1(x)
        q = self.q_proj(h).view(B, L, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(h).view(B, L, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(h).view(B, L, self.n_kv_heads, self.head_dim).transpose(1, 2)

        # QK-Norm prevents logit explosion and entropy collapse at 128k
        q = self.qk_norm_q(q)
        k = self.qk_norm_k(k)
        q, k = apply_rotary_emb(q, k, cos, sin)

        if self.sink_k is not None:
            # Concat sinks onto K/V *before* the GQA repeat, at the KV-head
            # count -- a sink pair is then shared across a query-head group
            # exactly like a regular key/value would be.
            sink_k = self.sink_k.unsqueeze(0).expand(B, -1, -1, -1).to(k.dtype)
            sink_v = self.sink_v.unsqueeze(0).expand(B, -1, -1, -1).to(v.dtype)
            k = torch.cat([sink_k, k], dim=2)  # [B, n_kv_heads, n_sinks+L, D]
            v = torch.cat([sink_v, v], dim=2)

        if self.n_rep > 1:  # grouped-query attention
            k = k.repeat_interleave(self.n_rep, dim=1)
            v = v.repeat_interleave(self.n_rep, dim=1)

        # CAUSAL. Was an unmasked full-softmax einsum: the model saw the future.
        # SDPA's `scale=` kwarg needs torch>=2.1; pre-scaling q gets the identical
        # (q@k^T) * (attn_factor/sqrt(head_dim)) softmax argument via SDPA's own
        # default scale (1/sqrt(head_dim)) instead, so this works on torch>=2.0
        # without a version check and without changing the math.
        if self.sink_k is not None:
            # SDPA's fused is_causal path can't express "always attend to the
            # sinks, causal otherwise" -- build that mask explicitly instead.
            # True = attend. Recomputed every call (cheap: L x (n_sinks+L)
            # bools) rather than cached, since L varies across curriculum phases.
            q_idx = torch.arange(L, device=x.device).unsqueeze(1)       # [L, 1]
            k_idx = torch.arange(L, device=x.device).unsqueeze(0)       # [1, L]
            causal = k_idx <= q_idx                                     # [L, L]
            sinks_always = torch.ones(L, self.n_sinks, device=x.device, dtype=torch.bool)
            mask = torch.cat([sinks_always, causal], dim=1)             # [L, n_sinks+L]
            out = F.scaled_dot_product_attention(q * attn_factor, k, v, attn_mask=mask)
        else:
            out = F.scaled_dot_product_attention(q * attn_factor, k, v, is_causal=True)
        out = out.transpose(1, 2).reshape(B, L, -1)
        out = self.o_proj(out)
        out = self.peri_norm_attn(out)
        x = x + out
        x = x + self.peri_norm_mlp(self.mlp(self.norm2(x)))
        return x


class DeltaNetBlock(nn.Module):
    """Gated DeltaNet: linear attention with a fixed-size recurrent state.

    T11.2 (specs/11_arch_hillclimb.md), candidate answer to open risk #1 (base1b
    VRAM): swappable for TransformerBlock1B at a config-gated subset of layers
    (AvaModel1B's `deltanet_layers`). Per-layer state is [B, H, Dh, Dh] --
    independent of sequence length, unlike a KV-cache that grows with context.

    Delta rule (Yang et al. 2024, "Parallelizing Linear Transformers with the
    Delta Rule over Sequence Length"): S_t = S_{t-1}(I - beta_t k_t k_t^T) +
    beta_t v_t k_t^T, beta_t a learned data-dependent gate in (0, 1) -- writes
    v_t at address k_t, erasing whatever the old state predicted at that
    address first. Output reads the state with the query: o_t = S_t q_t.

    This is a straight sequential scan (O(L) python loop), not the paper's
    chunked-parallel form. Causal by construction -- S_t is built only from
    tokens <= t, so there is no way for it to see the future, no mask to get
    wrong. Deliberately correctness-first to clear the causality suite (T6.1)
    before any throughput work; the chunked-parallel form is a follow-up once
    this lands, same relationship as J-Space's chunk-recurrent MultiJSpace vs.
    a hypothetical fully-parallel version.
    """

    def __init__(self, d_model=2048, n_heads=16, head_dim=128, mlp: str = "gelu",
                 mlp_mult: int = 4, mlp_ratio: Optional[float] = None):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = head_dim

        self.q_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(d_model, n_heads * head_dim, bias=False)
        self.beta_proj = nn.Linear(d_model, n_heads)  # data-dependent write gate
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

    def state_bytes(self, batch_size: int = 1, elem_bytes: int = 4) -> int:
        """Per-forward state size -- constant in L, the whole point of T11.2."""
        return batch_size * self.n_heads * self.head_dim * self.head_dim * elem_bytes

    def forward(self, x, cos, sin, attn_factor=1.0):
        # cos/sin/attn_factor accepted only to keep the TransformerBlock1B call
        # signature (RoPE has no meaning for a state-space recurrence -- the
        # delta rule already encodes order through the scan itself).
        B, L, _ = x.shape
        h = self.norm1(x)
        q = h @ self.q_proj.weight.T
        k = h @ self.k_proj.weight.T
        v = h @ self.v_proj.weight.T
        q = q.view(B, L, self.n_heads, self.head_dim)
        k = F.normalize(k.view(B, L, self.n_heads, self.head_dim), dim=-1)
        v = v.view(B, L, self.n_heads, self.head_dim)
        beta = torch.sigmoid(self.beta_proj(h))  # [B, L, H]

        S = x.new_zeros(B, self.n_heads, self.head_dim, self.head_dim)
        outs = []
        for t in range(L):
            k_t, v_t, q_t = k[:, t], v[:, t], q[:, t]           # [B, H, Dh]
            beta_t = beta[:, t].unsqueeze(-1)                    # [B, H, 1]
            pred = torch.einsum("bhij,bhj->bhi", S, k_t)         # what S already predicts at k_t
            delta = beta_t * (v_t - pred)
            S = S + torch.einsum("bhi,bhj->bhij", delta, k_t)    # write (erase old + insert new)
            outs.append(torch.einsum("bhij,bhj->bhi", S, q_t))   # read with the query

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


class AvaModel1B(nn.Module):
    """
    Three regimes explicit:
    - early sensory: Vision/Audio encoders (no RoPE)
    - middle workspace: Fusion + Multi-J-Space -> broadcast
    - final motor: Reasoning + LM head collapse to next token
    + Text encoder for RoPE long context
    """

    def __init__(self, vocab_size=128000, d_model=2048, n_text=12, n_fusion=28, n_reason=8,
                 multi_jspace_enabled=True, n_heads=16, head_dim=128, use_qk_norm=True,
                 n_kv_heads=None, mlp="gelu", mlp_mult=4, mlp_ratio=None,
                 tie_lm_head=False, tie_verbalizer=False, multimodal=True,
                 use_memory=False, jspace_slots=None, jspace_half_life=None,
                 jspace_num_heads=4, rope_base=10000, gradient_checkpointing=False,
                 jspace_causal=True, jspace_chunk_size=128, deltanet_layers=None,
                 rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False):
        super().__init__()
        self.d_model = d_model
        self.vocab_size = vocab_size
        self.multi_jspace_enabled = multi_jspace_enabled
        self.multimodal = multimodal
        # Cross-step workspace persistence. OFF during training: it would carry a
        # graph (and a batch dimension) across steps. ON for eval persistence tests.
        self.use_memory = use_memory
        self.gradient_checkpointing = gradient_checkpointing
        self.rope_type = rope_type
        self.n_sinks = n_sinks
        self.use_peri_ln = use_peri_ln

        self.embed = nn.Embedding(vocab_size, d_model)

        def _block():
            return TransformerBlock1B(d_model, n_heads=n_heads, head_dim=head_dim,
                                      use_qk_norm=use_qk_norm, n_kv_heads=n_kv_heads,
                                      mlp=mlp, mlp_mult=mlp_mult, mlp_ratio=mlp_ratio,
                                      rope_type=rope_type, n_sinks=n_sinks, use_peri_ln=use_peri_ln)

        # T11.2: fusion-layer indices that run DeltaNetBlock instead of full
        # attention. Default None/empty = every layer is TransformerBlock1B,
        # i.e. byte-identical to before this param existed.
        self._deltanet_layers = set(deltanet_layers or ())

        def _fusion_block(i):
            if i in self._deltanet_layers:
                return DeltaNetBlock(d_model, n_heads=n_heads, head_dim=head_dim,
                                     mlp=mlp, mlp_mult=mlp_mult, mlp_ratio=mlp_ratio)
            return _block()

        self.text_layers = nn.ModuleList([_block() for _ in range(n_text)])
        self.fusion_layers = nn.ModuleList([_fusion_block(i) for i in range(n_fusion)])
        self.reasoning_layers = nn.ModuleList([_block() for _ in range(n_reason)])

        self.vision_enc = VisionEncoder(d_model) if multimodal else None
        self.audio_enc = AudioEncoder(d_model) if multimodal else None
        self.fusion_norm = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        if tie_lm_head:
            self.lm_head.weight = self.embed.weight

        # One RoPE for the whole model: every block's schedule is identical, so
        # computing cos/sin per block was pure waste.
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

    # -- initialization ------------------------------------------------------

    def init_weights(self, std: float = 0.02) -> None:
        """GPT-2/LLaMA-style scaled init.

        Torch's default nn.Embedding init is N(0,1). With lm_head tied to embed
        that puts initial logits at O(sqrt(d)) and cross-entropy at ~196 for a
        vocab of 8192, where ln(8192)=9.01 is the correct value for a uniform
        predictor. Training from there wastes thousands of steps just shrinking
        the output layer, if it doesn't diverge first.

        Residual output projections are additionally scaled by 1/sqrt(2*n_layers)
        so the residual stream variance does not grow with depth.

        (The blueprint's docs/blueprint/network_init_sota.py multiplies lm_head by 1/sqrt(d);
        with tied weights that silently rescales the embedding table too.)
        """
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
                # in_proj_weight is a raw Parameter, not an nn.Linear
                if getattr(mod, "in_proj_weight", None) is not None:
                    nn.init.normal_(mod.in_proj_weight, mean=0.0, std=std)
                if getattr(mod, "in_proj_bias", None) is not None:
                    nn.init.zeros_(mod.in_proj_bias)
            elif isinstance(mod, RMSNorm):
                nn.init.ones_(mod.weight)

        # residual-path projections: shrink with depth
        for blk in list(self.text_layers) + list(self.fusion_layers) + list(self.reasoning_layers):
            nn.init.normal_(blk.o_proj.weight, mean=0.0, std=resid_std)
            down = blk.mlp.down if isinstance(blk.mlp, SwiGLU) else blk.mlp[2]
            nn.init.normal_(down.weight, mean=0.0, std=resid_std)

        # RMSNorm gains are set last: the loop above may have hit them as Linear-free
        for mod in self.modules():
            if isinstance(mod, RMSNorm):
                nn.init.ones_(mod.weight)

        # lm_head: when tied, it IS embed -- rescaling here would corrupt the
        # embedding table. Only initialize it separately when untied.
        if self.lm_head.weight is not self.embed.weight:
            nn.init.normal_(self.lm_head.weight, mean=0.0, std=std)

    @property
    def n_layers(self) -> int:
        return len(self.text_layers) + len(self.fusion_layers) + len(self.reasoning_layers)

    # -- workspace memory ----------------------------------------------------

    def reset_memory(self) -> None:
        self._prev_workspaces = None

    def _memory_for(self, batch_size: int):
        """Detached previous workspaces, or None if unusable.

        Two ways this used to explode: (a) the tensors carried a graph into the
        next step's backward, (b) a batch-size change made the slot broadcast
        shapes disagree. Both are now non-events.
        """
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

    def forward(self, images=None, audio=None, input_ids=None, task_type="deliberate"):
        if input_ids is None:
            raise ValueError("input_ids required")
        B, L = input_ids.shape
        x = self.embed(input_ids)

        # early sensory — no RoPE for vision/audio
        if self.multimodal and images is not None and self.vision_enc is not None:
            v = self.vision_enc(images)
            if v is not None and v.dim() == 3:
                x = x + v.mean(dim=1, keepdim=True)
        if self.multimodal and audio is not None and self.audio_enc is not None:
            a = self.audio_enc(audio)
            if a is not None and a.dim() == 3:
                x = x + a.mean(dim=1, keepdim=True)

        cos, sin = self.rope.get_cos_sin(L, device=x.device)
        af = self.rope.attn_factor

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

    # -- branch surgery ------------------------------------------------------

    def freeze_spaces(self, freeze_list: List[str]):
        """freeze_spaces(["system1"]) sets requires_grad=False.
        Supports system1, system2, critic, planner, router, arbitration."""
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


def apply_rope_scaling(model: AvaModel1B, base: int, scale: float):
    model.rope_base = base
    model.rope_scale = scale
    model.rope.update(base, scale)
    # keep per-block ropes in sync for anything still reading them
    for blk in list(model.text_layers) + list(model.fusion_layers) + list(model.reasoning_layers):
        blk.rope.update(base, scale)


def get_model(vocab_size=128000, d_model=2048, multi_jspace_enabled=True,
              rope_type: str = "yarn", n_sinks: int = 0, use_peri_ln: bool = False):
    """Blueprint-compatible factory. New code should use ava.model.build_model(cfg)."""
    return AvaModel1B(vocab_size=vocab_size, d_model=d_model,
                      multi_jspace_enabled=multi_jspace_enabled,
                      rope_type=rope_type, n_sinks=n_sinks, use_peri_ln=use_peri_ln)
