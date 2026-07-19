"""Muon: momentum-orthogonalized optimizer for the hidden matrices.

Jordan et al. 2024 (github.com/KellerJordan/Muon) with the Moonlight scaling
recipe (arXiv 2502.16982): SGD-momentum orthogonalized by a Newton-Schulz
iteration, updates rescaled by 0.2*sqrt(max(A, B)) so their RMS (~0.2)
matches AdamW's typical update RMS, plus decoupled weight decay. With that
RMS matching, Muon DIRECTLY REUSES the AdamW-tuned learning rate and weight
decay -- verified verbatim against the paper ("with this adjustment, Muon
can directly reuse the learning rate and weight decay tuned for AdamW"), so
the WSD schedule drives both optimizers at the same magnitude and there is
no second LR to tune.

Two properties matter at Ava's scale:

* **Half the optimizer memory of AdamW for matrices.** One momentum buffer
  per matrix instead of Adam's (m, v) pair -- on mini that is ~0.6GB back on
  a 12GB GPU that crash-looped at 97% VRAM.
* **Validated step-efficiency, honestly sized**: 1.35x token-efficiency at
  124M (NanoGPT speedrun record) and ~25% compute reduction at 1.5B. The
  circulated "~2x" figure is the vendor's own scaling-law fit and did not
  survive independent benchmarking -- do not plan around it.

Muon applies ONLY to 2D hidden weights. Embeddings, tied heads, norms,
biases, and the J-space decay logits keep AdamW (the split every source --
Jordan, Moonlight, Essential AI -- lands on independently). `build_hybrid`
wires the split behind a single optimizer-shaped object so ava/train.py's
checkpoint and LR plumbing does not care. Presets opt in with
optimizer.name: "muon".
"""

from __future__ import annotations

import torch

_NS_COEFFS = (3.4445, -4.7750, 2.0315)


@torch.no_grad()
def newton_schulz_orthogonalize(g: torch.Tensor, steps: int = 5) -> torch.Tensor:
    """Approximate UV^T (the orthogonal factor of g's SVD) via the quintic
    Newton-Schulz iteration of the Muon reference implementation. Runs in
    bf16 on CUDA for speed; exact orthogonality is not required -- the
    iteration only has to crush the spread of singular values."""
    assert g.ndim == 2
    a, b, c = _NS_COEFFS
    x = g.to(torch.bfloat16 if g.is_cuda else torch.float32)
    transposed = x.shape[0] > x.shape[1]
    if transposed:
        x = x.mT
    x = x / (x.norm() + 1e-7)
    for _ in range(steps):
        s = x @ x.mT
        x = a * x + (b * s + c * (s @ s)) @ x
    if transposed:
        x = x.mT
    return x.to(g.dtype)


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr: float = 0.02, momentum: float = 0.95,
                 nesterov: bool = True, ns_steps: int = 5,
                 weight_decay: float = 0.0):
        defaults = dict(lr=lr, momentum=momentum, nesterov=nesterov,
                        ns_steps=ns_steps, weight_decay=weight_decay,
                        lr_scale=1.0)
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure=None):
        loss = closure() if closure is not None else None
        for group in self.param_groups:
            # group["lr"] is the FINAL lr: when the train loop drives the WSD
            # schedule it already folds lr_scale in (train.py); standalone use
            # just takes the constructor lr. lr_scale is metadata, not a
            # factor here -- multiplying twice was the first bug this file had.
            lr = group["lr"]
            mom, nesterov = group["momentum"], group["nesterov"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                state = self.state[p]
                if "momentum_buffer" not in state:
                    state["momentum_buffer"] = torch.zeros_like(g)
                buf = state["momentum_buffer"]
                buf.mul_(mom).add_(g)
                upd = g.add(buf, alpha=mom) if nesterov else buf
                flat = upd.reshape(upd.shape[0], -1)
                ortho = newton_schulz_orthogonalize(flat, group["ns_steps"])
                # Moonlight RMS matching (arXiv 2502.16982 eq. 1): an
                # orthogonalized [m, n] update has RMS ~= 1/sqrt(max(m, n));
                # scaling by 0.2*sqrt(max(m, n)) puts update RMS at ~0.2,
                # AdamW's empirical range -- which is exactly what lets Muon
                # ride the SAME learning rate the WSD schedule computes.
                scale = 0.2 * max(flat.shape) ** 0.5
                if group["weight_decay"]:
                    p.mul_(1.0 - lr * group["weight_decay"])
                p.add_(ortho.view_as(p), alpha=-lr * scale)
        return loss


class HybridOptimizer:
    """Muon for hidden matrices + AdamW for everything else, presented as one
    optimizer: the interface subset ava/train.py actually uses."""

    def __init__(self, muon: Muon, adamw: torch.optim.AdamW):
        self.muon = muon
        self.adamw = adamw

    @property
    def param_groups(self):
        return list(self.muon.param_groups) + list(self.adamw.param_groups)

    def step(self):
        self.muon.step()
        self.adamw.step()

    def zero_grad(self, set_to_none: bool = True):
        self.muon.zero_grad(set_to_none=set_to_none)
        self.adamw.zero_grad(set_to_none=set_to_none)

    def state_dict(self):
        return {"muon": self.muon.state_dict(), "adamw": self.adamw.state_dict()}

    def load_state_dict(self, sd):
        self.muon.load_state_dict(sd["muon"])
        self.adamw.load_state_dict(sd["adamw"])


_ADAMW_NAME_MARKERS = ("embed", "lm_head", "verbalizer", "decay_logit")


def is_muon_param(name: str, p: torch.nn.Parameter) -> bool:
    """Hidden matrices only: 2D+, not embeddings/heads/logits/norms."""
    if p.ndim < 2:
        return False
    return not any(m in name for m in _ADAMW_NAME_MARKERS)


class MuonVS(Muon):
    """Variance-Scaled Muon (Muon-VS lite): attenuate momentum when grad RMS is high.

    Research Muon-VS applies NSR modulation before Newton-Schulz. This lite path
    scales the buffered momentum by ``1 / (1 + grad_rms)`` so high-variance
    steps shrink before orthogonalization. Opt-in via ``optimizer.name: muon_vs``.
    """

    @torch.no_grad()
    def step(self, closure=None):
        loss = closure() if closure is not None else None
        for group in self.param_groups:
            lr = group["lr"]
            mom, nesterov = group["momentum"], group["nesterov"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                state = self.state[p]
                if "momentum_buffer" not in state:
                    state["momentum_buffer"] = torch.zeros_like(g)
                buf = state["momentum_buffer"]
                buf.mul_(mom).add_(g)
                upd = g.add(buf, alpha=mom) if nesterov else buf
                grad_rms = g.pow(2).mean().sqrt().clamp_min(1e-8)
                upd = upd / (1.0 + grad_rms)
                flat = upd.reshape(upd.shape[0], -1)
                ortho = newton_schulz_orthogonalize(flat, group["ns_steps"])
                scale = 0.2 * max(flat.shape) ** 0.5
                if group["weight_decay"]:
                    p.mul_(1.0 - lr * group["weight_decay"])
                p.add_(ortho.view_as(p), alpha=-lr * scale)
        return loss


class Hyperball:
    """Frobenius-norm constraint wrapper (Hyperball lite).

    After each wrapped step, rescale selected 2D matrices so
    ``||W||_F == radius``. Prefer ``matrix_params`` (Muon matrices only).
    """

    def __init__(self, inner, *, radius: float = 1.0,
                 matrix_params: list[torch.nn.Parameter] | None = None):
        self.inner = inner
        self.radius = float(radius)
        self.matrix_params = list(matrix_params) if matrix_params is not None else None

    @property
    def param_groups(self):
        return self.inner.param_groups

    def zero_grad(self, set_to_none: bool = True):
        return self.inner.zero_grad(set_to_none=set_to_none)

    def state_dict(self):
        return {"inner": self.inner.state_dict(), "radius": self.radius}

    def load_state_dict(self, sd):
        self.inner.load_state_dict(sd["inner"])
        self.radius = float(sd.get("radius", self.radius))

    @torch.no_grad()
    def step(self, closure=None):
        if closure is not None:
            loss = self.inner.step(closure)
        else:
            loss = self.inner.step()
        targets = self.matrix_params
        if targets is None:
            targets = [p for g in self.param_groups for p in g["params"] if p.ndim >= 2]
        for p in targets:
            if p.ndim < 2:
                continue
            n = p.norm()
            if float(n) > 1e-8:
                p.mul_(self.radius / n)
        return loss


def build_hybrid(model: torch.nn.Module, *, adamw_lr: float,
                 betas: tuple[float, float], weight_decay: float,
                 momentum: float = 0.95, ns_steps: int = 5,
                 variant: str = "muon",
                 hyperball_radius: float | None = None) -> HybridOptimizer | Hyperball:
    muon_params, decay, no_decay = [], [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        if is_muon_param(n, p):
            muon_params.append(p)
        elif p.ndim < 2 or "decay_logit" in n:
            no_decay.append(p)
        else:
            decay.append(p)
    muon_cls = MuonVS if variant in ("muon_vs", "muon-nsr", "muon_nsr") else Muon
    muon = muon_cls(muon_params, lr=adamw_lr, momentum=momentum,
                    ns_steps=ns_steps, weight_decay=weight_decay)
    adamw = torch.optim.AdamW(
        [{"params": decay, "weight_decay": weight_decay},
         {"params": no_decay, "weight_decay": 0.0}],
        lr=adamw_lr, betas=betas)
    hybrid = HybridOptimizer(muon, adamw)
    if hyperball_radius is not None:
        return Hyperball(hybrid, radius=hyperball_radius, matrix_params=muon_params)
    return hybrid
