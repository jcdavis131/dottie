"""
Dottie — Muon optimizer + hybrid Adam + weight-decay coupling + effort conditioning
Solo personal project, no connection to employer, built with public/free-tier only

Implements per Inkling architecture wins:
- Hybrid optimization: Muon for large matrix weights, Adam for others
- Weight decay coupled to square of LR: wd = base_wd * (lr / lr_max)^2 (Kosson 2023, Defazio 2025)
- Controllable thinking effort 0.2-0.99 via embedding + per-token cost (Inkling effort sweep)

Reference: https://github.com/KellerJordan/Muon (Newton-Schulz orthogonalization)
"""

from __future__ import annotations
import math
from typing import Iterable, Optional, List, Dict, Any
import torch
import torch.nn as nn


def zeropower_via_newtonschulz5(G: torch.Tensor, steps: int = 5) -> torch.Tensor:
    """
    Newton-Schulz iteration to approximate zeroth power / orthogonalization.
    G: 2D tensor
    Returns orthogonalized matrix approximating G * (G^T G)^-0.5
    Coefficients from Muon repo: a=3.4445, b=-4.7750, c=2.0315
    """
    assert G.ndim == 2, f"Newton-Schulz only for 2D, got {G.shape}"
    a, b, c = 3.4445, -4.7750, 2.0315
    # Normalize to avoid blowup
    X = G.to(torch.float32)
    # Scale by frobenius norm
    X = X / (X.norm() + 1e-7)

    # If more rows than cols, we operate on transposed for efficiency/stability
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True

    for _ in range(steps):
        A = X @ X.T
        # B = b*A + c*A@A
        B = b * A + c * (A @ A)
        X = a * X + B @ X

    if transposed:
        X = X.T
    return X.to(G.dtype)


class Muon(torch.optim.Optimizer):
    """
    Simplified Muon optimizer.
    - Momentum buffer
    - Newton-Schulz orthogonalization for 2D params
    - For 1D / other dims: SGD-momentum behavior
    - Supports weight decay coupling externally via get_coupled_weight_decay

    Usage:
        muon_params = [p for p in model if p.ndim==2]
        optimizer = Muon(muon_params, lr=0.02, momentum=0.95, weight_decay=0.01)
    """

    def __init__(self, params: Iterable[torch.nn.Parameter], lr: float = 0.02,
                 weight_decay: float = 0.01, momentum: float = 0.95,
                 nesterov: bool = True, ns_steps: int = 5,adam_wd: bool = True):
        defaults = dict(lr=lr, weight_decay=weight_decay, momentum=momentum,
                        nesterov=nesterov, ns_steps=ns_steps, adam_wd=adam_wd)
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            lr = group['lr']
            wd = group['weight_decay']
            momentum = group['momentum']
            nesterov = group['nesterov']
            ns_steps = group['ns_steps']

            for p in group['params']:
                if p.grad is None:
                    continue
                grad = p.grad
                if grad.is_sparse:
                    raise RuntimeError("Muon does not support sparse gradients")

                state = self.state[p]
                if 'momentum_buffer' not in state:
                    state['momentum_buffer'] = torch.zeros_like(p)

                buf = state['momentum_buffer']
                # momentum update: buf = momentum*buf + (1-momentum)*grad  OR classic
                # Use classic: buf = momentum*buf + grad (per original Muon)
                buf.mul_(momentum).add_(grad)

                # Orthogonalize if 2D
                if p.ndim == 2:
                    # Apply Newton-Schulz to buf
                    # For very small dims, skip orthogonalization to save compute
                    if buf.shape[0] >= 4 and buf.shape[1] >= 4:
                        try:
                            orth = zeropower_via_newtonschulz5(buf, steps=ns_steps)
                        except Exception:
                            orth = buf
                    else:
                        orth = buf
                    update = orth
                    if nesterov:
                        # Nesterov-ish: orth + momentum*buf orthogonalized?
                        # Simplified: use orth as update, as in Muon repo
                        pass
                else:
                    update = buf

                # Weight decay (AdamW style decoupled)
                if wd != 0:
                    p.mul_(1 - lr * wd)

                # Apply update
                p.add_(update, alpha=-lr)

        return loss


def get_coupled_weight_decay(base_wd: float, lr: float, lr_max: float) -> float:
    """
    Weight decay coupled to square of LR: wd = base_wd * (lr / lr_max)^2
    Keeps overall weight size stable across training horizons.
    Ref: Kosson et al. 2023, Defazio 2025 (cited in Inkling)
    """
    if lr_max <= 0:
        return base_wd
    ratio = lr / lr_max
    return base_wd * (ratio * ratio)


class MuonAdamHybrid:
    """
    Hybrid optimizer: Muon for large matrix weights, AdamW for others.
    Provides unified step()/zero_grad() interface for training loops.
    Offline deterministic, public pip only (torch).

    Selection heuristic for Muon params (large matrix weights):
      - ndim == 2
      - numel >= min_muon_params (default 128*128)
      - not in adam_exclude_names (embed, lm_head, norms etc can be forced to Adam)

    Others go to AdamW.
    """

    def __init__(self, model: nn.Module, lr_max: float = 2e-4, base_wd: float = 0.1,
                 muon_lr: float = 0.02, adam_lr: float = None,
                 momentum: float = 0.95, betas=(0.9, 0.95),
                 min_muon_params: int = 4096,
                 adam_exclude_names: Optional[List[str]] = None):
        self.lr_max = lr_max
        self.base_wd = base_wd
        self.muon_lr = muon_lr
        self.adam_lr = adam_lr if adam_lr is not None else lr_max

        adam_exclude_names = adam_exclude_names or ["embed", "lm_head", "norm", "bias", "router", "sink"]

        muon_params = []
        adam_params_decay = []
        adam_params_no_decay = []

        for n, p in model.named_parameters():
            if not p.requires_grad:
                continue
            is_2d_large = p.ndim == 2 and p.numel() >= min_muon_params
            excluded = any(k in n.lower() for k in adam_exclude_names)
            if is_2d_large and not excluded:
                # Large matrix weight -> Muon
                muon_params.append(p)
            else:
                # Adam group split by ndim for weight decay
                if p.ndim < 2 or "decay_logit" in n or "bias" in n.lower():
                    adam_params_no_decay.append(p)
                else:
                    adam_params_decay.append(p)

        self.muon_params = muon_params
        self.adam_decay = adam_params_decay
        self.adam_no_decay = adam_params_no_decay

        print(f"[MuonHybrid] Muon params: {len(muon_params)} tensors, {sum(p.numel() for p in muon_params)/1e6:.2f}M")
        print(f"[MuonHybrid] Adam decay: {len(adam_params_decay)} tensors, Adam no_decay: {len(adam_params_no_decay)}")

        self.muon_opt = None
        if len(muon_params) > 0:
            self.muon_opt = Muon(muon_params, lr=self.muon_lr,
                                 weight_decay=get_coupled_weight_decay(base_wd, self.muon_lr, lr_max),
                                 momentum=momentum)

        adam_groups = []
        if adam_params_decay:
            adam_groups.append({"params": adam_params_decay, "weight_decay": base_wd})
        if adam_params_no_decay:
            adam_groups.append({"params": adam_params_no_decay, "weight_decay": 0.0})

        self.adam_opt = None
        if adam_groups:
            self.adam_opt = torch.optim.AdamW(adam_groups, lr=self.adam_lr, betas=betas)

    def set_lr(self, lr: float, adam_lr: Optional[float] = None, muon_lr: Optional[float] = None):
        """
        Update LR and coupled weight decay for both optimizers.
        wd = base_wd * (lr / lr_max)^2
        """
        coupled_wd = get_coupled_weight_decay(self.base_wd, lr, self.lr_max)
        # Muon lr typically scaled differently; but we couple its wd too
        muon_lr_eff = muon_lr if muon_lr is not None else self.muon_lr
        adam_lr_eff = adam_lr if adam_lr is not None else lr

        if self.muon_opt:
            for g in self.muon_opt.param_groups:
                g['lr'] = muon_lr_eff
                g['weight_decay'] = get_coupled_weight_decay(self.base_wd, muon_lr_eff, self.lr_max)

        if self.adam_opt:
            for g in self.adam_opt.param_groups:
                g['lr'] = adam_lr_eff
                # Keep no_decay groups at 0, decay groups at coupled_wd
                if g['weight_decay'] != 0:
                    g['weight_decay'] = coupled_wd

    def zero_grad(self, set_to_none: bool = True):
        if self.muon_opt:
            self.muon_opt.zero_grad(set_to_none=set_to_none)
        if self.adam_opt:
            self.adam_opt.zero_grad(set_to_none=set_to_none)

    def step(self):
        if self.muon_opt:
            self.muon_opt.step()
        if self.adam_opt:
            self.adam_opt.step()

    def state_dict(self):
        return {
            "muon": self.muon_opt.state_dict() if self.muon_opt else None,
            "adam": self.adam_opt.state_dict() if self.adam_opt else None,
        }

    def load_state_dict(self, sd):
        if self.muon_opt and sd.get("muon"):
            self.muon_opt.load_state_dict(sd["muon"])
        if self.adam_opt and sd.get("adam"):
            self.adam_opt.load_state_dict(sd["adam"])


# ---------------------------------------------------------------------------
# Effort conditioning (Inkling controllable thinking effort 0.2-0.99)

class EffortConditioning(nn.Module):
    """
    Controllable thinking effort 0.2-0.99 via system message + per-token cost.
    - Effort embedding added to input (like system prompt token)
    - Per-token cost multiplier on loss teaches model to use fewer tokens at low effort

    Usage in model forward:
        effort: float tensor [B] in [0.2, 0.99] or scalar
        x = embed(input_ids) + effort_cond.effort_embedding(effort)

    Training: loss = lm_loss * effort_cost_factor + aux
        where effort_cost_factor = 1 + alpha * (0.99 - effort) encourages brevity at low effort
    """

    def __init__(self, d_model: int, hidden_mult: float = 2.0):
        super().__init__()
        self.d_model = d_model
        hidden = int(d_model * hidden_mult)
        self.net = nn.Sequential(
            nn.Linear(1, hidden, bias=False),
            nn.SiLU(),
            nn.Linear(hidden, d_model, bias=False)
        )
        # Learnable per-token cost scaling
        self.cost_predictor = nn.Sequential(
            nn.Linear(1, hidden // 2),
            nn.SiLU(),
            nn.Linear(hidden // 2, 1)
        )
        # Initialize small
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def effort_embedding(self, effort: torch.Tensor | float, device=None, dtype=None) -> torch.Tensor:
        """
        effort: scalar float or [B] tensor or [B,1]
        Returns: [B,1,D] or [1,D] embedding to add to token embeddings
        """
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

        emb = self.net(e)  # [B, D] or [1,D]
        return emb

    def forward(self, x: torch.Tensor, effort: torch.Tensor | float | None) -> torch.Tensor:
        """
        x: [B,L,D]
        effort: optional
        Returns x with effort embedding added
        """
        if effort is None:
            return x
        emb = self.effort_embedding(effort, device=x.device, dtype=x.dtype)  # [B,D] or [B,1]
        if emb.shape[0] == 1 and x.shape[0] > 1:
            emb = emb.expand(x.shape[0], -1)
        # [B,D] -> [B,1,D] broadcast over L
        return x + emb.unsqueeze(1)

    def per_token_cost_multiplier(self, effort: torch.Tensor | float, base_alpha: float = 0.5) -> torch.Tensor:
        """
        Computes cost multiplier for loss that teaches fewer tokens at low effort.
        Inkling: per-token cost adjusted + system message controls effort.
        Low effort (0.2) => higher cost per token => model learns brevity.
        High effort (0.99) => lower cost => model can think longer.

        Returns multiplier scalar: >1 for low effort, ~1 for high effort
        """
        if isinstance(effort, float):
            e_val = effort
        elif isinstance(effort, torch.Tensor):
            e_val = effort.mean().item() if effort.numel() > 0 else 0.6
        else:
            e_val = 0.6

        # Linear scaling: cost = 1 + α * (0.99 - effort)
        # At effort=0.2: cost=1+0.5*0.79=1.395, at 0.99: ~1.0
        mult = 1.0 + base_alpha * (0.99 - e_val)
        # Clamp
        return torch.tensor(max(0.5, min(2.0, mult)))

    @staticmethod
    def sample_effort(batch_size: int, device=None, low: float = 0.2, high: float = 0.99) -> torch.Tensor:
        """Sample random effort levels for training, as Inkling does via system message variation."""
        e = torch.rand(batch_size, 1, device=device) * (high - low) + low
        return e


def compute_effort_scaled_loss(lm_loss: torch.Tensor, effort: torch.Tensor | float | None,
                               alpha: float = 0.5, token_count: int | None = None) -> torch.Tensor:
    """
    Apply per-token cost multiplier.
    If effort low, penalize more for token count (if provided).
    """
    if effort is None:
        return lm_loss

    if isinstance(effort, torch.Tensor):
        e_mean = effort.mean()
    else:
        e_mean = torch.tensor(float(effort), device=lm_loss.device)

    # Base multiplier
    mult = 1.0 + alpha * (0.99 - e_mean.clamp(0.2, 0.99))

    # Optional token-count penalty: at low effort, extra penalty proportional to seq_len
    # This teaches model to be brief when effort low
    if token_count is not None:
        # token penalty scales as (0.99 - effort) * log(token_count)
        tok_penalty = (0.99 - e_mean.clamp(0.2, 0.99)) * 0.01 * math.log(max(1, token_count))
        return lm_loss * mult + tok_penalty
    return lm_loss * mult


__all__ = ["Muon", "MuonAdamHybrid", "zeropower_via_newtonschulz5",
           "get_coupled_weight_decay", "EffortConditioning", "compute_effort_scaled_loss"]

# Solo personal project, no connection to employer, built with public/free-tier only
