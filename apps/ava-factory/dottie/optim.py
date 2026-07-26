"""
Dottie — Unified optimizer factory: AdamW, Muon, SOAP/KL-SOAP, MOP/REKLS, layer-wise
Solo personal project, no connection to employer, built with public/free-tier only
HOME-only.

Paper: 2607.20548 SOAP, Muon, and Beyond (Khona et al)
Repo: NVIDIA-NeMo/Emerging-Optimizers (Apache-2.0) — implements KL-Shampoo, REKLS, etc.

Features per 2607.20548:
- Muon Newton-Schulz orthogonalization (5 steps default) with Moonlight RMS matching 0.2*sqrt(max)
- SOAP with per-step QR orth fix (precondition_freq=1) — eliminates loss spikes at large-batch (Sec 5.4)
- KL covariance option (KL-Shampoo Sec 5.4) — integrates KL-divergence correction
- update-RMS matching factor 0.2*sqrt((1-beta)/(1+beta)) for fair LR transfer (Sec 5.2)
- sqrt batch scaling eta' = eta sqrt(B'/B) (Sec 3)
- layer-wise distributed optimizer pattern (Sec 6, Megatron-Core compatible)
- CPU fallback, offline-first, free-tier friendly
"""

from __future__ import annotations

import math
from typing import Tuple

import torch

# Muon core — import from dottie.muon (full version with Hyperball etc)
try:
    from dottie.muon import (
        Muon,
        MuonVS,
        HybridOptimizer,
        Hyperball,
        build_hybrid as build_hybrid_muon,
        is_muon_param,
        newton_schulz_orthogonalize,
    )
except ImportError as e:
    # fallback minimal (if running as script)
    from muon import (  # type: ignore
        Muon,
        MuonVS,
        HybridOptimizer,
        Hyperball,
        build_hybrid as build_hybrid_muon,
        is_muon_param,
        newton_schulz_orthogonalize,
    )

# SOAP core
try:
    from dottie.soap import (
        SOAP,
        HybridSOAPAdamW,
        LayerWiseDistributedOptimizer,
        build_hybrid_soap,
        init_kronecker_factors,
        is_soap_param,
        precondition,
        sqrt_batch_scaled_lr,
        unprecondition,
        update_eigenbasis_and_exp_avgs,
        update_kronecker_factors,
        update_kronecker_factors_kl_shampoo,
        update_rms_match_factor,
    )
except ImportError:
    # if soap missing, create stubs so adamw/muon still works offline
    SOAP = None  # type: ignore
    HybridSOAPAdamW = None  # type: ignore
    LayerWiseDistributedOptimizer = None  # type: ignore
    build_hybrid_soap = None  # type: ignore
    init_kronecker_factors = None  # type: ignore
    is_soap_param = None  # type: ignore
    precondition = None  # type: ignore
    unprecondition = None  # type: ignore
    update_eigenbasis_and_exp_avgs = None  # type: ignore
    update_kronecker_factors = None  # type: ignore
    update_kronecker_factors_kl_shampoo = None  # type: ignore

    def update_rms_match_factor(beta: float = 0.9, base_scale: float = 0.2) -> float:
        if not (0 <= beta < 1):
            return base_scale
        return base_scale * math.sqrt((1.0 - beta) / (1.0 + beta))

    def sqrt_batch_scaled_lr(base_lr: float, base_batch_tokens: int, new_batch_tokens: int) -> float:
        if base_batch_tokens <= 0 or new_batch_tokens <= 0:
            return base_lr
        return base_lr * math.sqrt(new_batch_tokens / base_batch_tokens)


__all__ = [
    # Muon
    "Muon",
    "MuonVS",
    "HybridOptimizer",
    "Hyperball",
    "build_hybrid_muon",
    "is_muon_param",
    "newton_schulz_orthogonalize",
    # SOAP
    "SOAP",
    "HybridSOAPAdamW",
    "LayerWiseDistributedOptimizer",
    "build_hybrid_soap",
    "init_kronecker_factors",
    "is_soap_param",
    "precondition",
    "unprecondition",
    "update_kronecker_factors",
    "update_kronecker_factors_kl_shampoo",
    "update_eigenbasis_and_exp_avgs",
    # transfer / scaling
    "update_rms_match_factor",
    "sqrt_batch_scaled_lr",
    "build_optim",
    "build_hybrid",
]


def build_optim(
    model: torch.nn.Module,
    *,
    name: str = "adamw",
    adamw_lr: float = 3e-4,
    betas: Tuple[float, float] = (0.9, 0.95),
    weight_decay: float = 0.01,
    shampoo_beta: float = 0.95,
    precondition_freq: int = 1,
    use_kl_shampoo: bool = False,
    use_eigh: bool = False,
    power_iter_steps: int = 1,
    momentum: float = 0.95,
    ns_steps: int = 5,
    layer_wise: bool = False,
    num_ranks: int = 1,
    # LR transfer / batch scaling (Sec 5.2 & Sec 3)
    update_rms_match: bool = False,
    rms_beta: float = 0.9,
    sqrt_batch_scaling: bool = False,
    base_batch_tokens: int = 1_048_576,
    new_batch_tokens: int = 1_048_576,
    base_lr_for_scaling: float | None = None,
    hyperball_radius: float | None = None,
) -> torch.optim.Optimizer | HybridOptimizer | HybridSOAPAdamW | LayerWiseDistributedOptimizer | Hyperball:
    """
    Unified factory called by dottie/train.py and train_1b_deepspeed.py.

    name choices:
      adamw       - vanilla AdamW
      muon        - Muon for matrices + AdamW rest (HybridOptimizer)
      muon_vs     - Variance-scaled Muon
      muonh       - Muon + Hyperball (Frobenius radius)
      soap        - SOAP with per-step QR fix (paper 2607.20548 Sec 5.4)
      kl_soap     - SOAP + KL-Shampoo covariance (paper Sec 5.4)
      mop         - Momentum Orthogonalized by Polar (MOP) — same as Muon but polar decomp alias
      rekls       - REKLS = SOAP + eigen basis per step + KL (advanced variant per NVIDIA blog)

    Returns an optimizer-like object with .param_groups, .step(), .zero_grad(), .state_dict().
    Offline-first, CPU fallback, free-tier.
    """
    n = name.lower()

    # handle LR scaling helpers before building
    effective_lr = adamw_lr
    if update_rms_match:
        factor = update_rms_match_factor(beta=rms_beta)
        # paper says factor ~0.2 sqrt((1-beta)/(1+beta)) for LR transfer
        effective_lr = effective_lr * factor
    if sqrt_batch_scaling and base_lr_for_scaling is not None:
        effective_lr = sqrt_batch_scaled_lr(base_lr_for_scaling, base_batch_tokens, new_batch_tokens)
    elif sqrt_batch_scaling:
        effective_lr = sqrt_batch_scaled_lr(adamw_lr, base_batch_tokens, new_batch_tokens)

    if n in ("adamw", "adamw8bit"):
        decay, no_decay = [], []
        for mod_n, p in model.named_parameters():
            if not p.requires_grad:
                continue
            (no_decay if p.ndim < 2 or "decay_logit" in mod_n else decay).append(p)
        if n == "adamw8bit":
            try:
                import bitsandbytes as bnb

                return bnb.optim.AdamW8bit(
                    [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}],
                    lr=effective_lr,
                    betas=betas,
                )
            except ImportError:
                pass
        return torch.optim.AdamW(
            [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}],
            lr=effective_lr,
            betas=betas,
        )

    if n in ("muon", "muon_vs", "muon-nsr", "muon_nsr", "muonh", "mop"):
        variant = "muon_vs" if n in ("muon_vs", "muon-nsr", "muon_nsr") else "muon"
        radius = hyperball_radius if hyperball_radius is not None else (1.0 if n == "muonh" else None)
        if n == "mop":
            variant = "muon"  # MOP alias = Muon with polar factor, same NS path
        return build_hybrid_muon(
            model,
            adamw_lr=effective_lr,
            betas=betas,
            weight_decay=weight_decay,
            momentum=momentum,
            ns_steps=ns_steps,
            variant=variant,
            hyperball_radius=radius,
        )

    if n in ("soap", "kl_soap", "rekls"):
        if build_hybrid_soap is None or SOAP is None:
            raise ImportError("dottie.soap module missing — cannot build SOAP; install or restore soap.py")
        use_kl = n in ("kl_soap", "rekls") or use_kl_shampoo
        use_eigh_flag = use_eigh or (n == "rekls")
        precond_freq = precondition_freq
        if n == "rekls":
            precond_freq = 1  # per-step required for stability Sec 5.4
        return build_hybrid_soap(
            model,
            adamw_lr=effective_lr,
            betas=betas,
            weight_decay=weight_decay,
            shampoo_beta=shampoo_beta,
            precondition_freq=precond_freq,
            use_kl_shampoo=use_kl,
            use_eigh=use_eigh_flag,
            power_iter_steps=power_iter_steps,
            num_ranks=num_ranks,
            layer_wise=layer_wise,
        )

    raise ValueError(f"Unknown optimizer name {name!r}; expected adamw|muon|muon_vs|soap|kl_soap|mop|rekls")


def build_hybrid(*args, **kwargs):
    return build_hybrid_muon(*args, **kwargs)
