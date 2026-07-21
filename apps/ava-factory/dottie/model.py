"""Build an DottieModel1B from an DottieConfig.

Thin adapter: the architecture lives in the root `model_1b.py` (real code, now
fixed), and this maps config fields onto its constructor so nano/mini/base1b
differ only by YAML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from model_1b import DottieModel1B, apply_rope_scaling

from dottie.config import SPACES, DottieConfig

if TYPE_CHECKING:
    import torch


def build_model(cfg: DottieConfig, *, use_memory: bool = False) -> DottieModel1B:
    m = cfg.model
    model = DottieModel1B(
        vocab_size=m.vocab_size,
        d_model=m.d_model,
        n_text=m.n_text_layers,
        n_fusion=m.n_fusion_layers,
        n_reason=m.n_reasoning_layers,
        n_heads=m.n_heads,
        head_dim=m.head_dim,
        n_kv_heads=m.n_kv_heads,
        mlp=m.mlp,
        mlp_mult=m.mlp_mult,
        mlp_ratio=m.mlp_ratio,
        use_qk_norm=m.qk_norm,
        tie_lm_head=m.tie_lm_head,
        tie_verbalizer=m.tie_verbalizer,
        multimodal=m.multimodal,
        use_memory=use_memory,
        jspace_slots=dict(cfg.jspace.slots),
        jspace_half_life=dict(cfg.jspace.half_life),
        jspace_num_heads=m.jspace_num_heads,
        jspace_causal=cfg.jspace.causal,
        jspace_chunk_size=cfg.jspace.chunk_size,
        rope_base=m.rope_base_init,
        gradient_checkpointing=cfg.training.gradient_checkpointing,
        multi_jspace_enabled=True,
        rope_type=m.rope_type,
        n_sinks=m.n_sinks,
        use_peri_ln=m.use_peri_ln,
    )
    phase0 = cfg.phases[0]
    apply_rope_scaling(model, phase0.rope_base, phase0.ntk)
    return model


def set_router_bias(model: DottieModel1B, probs: list[float] | None) -> None:
    """Apply a branch's router prior (BRANCH_CONFIGS router_bias)."""
    if model.multi_jspace is None:
        raise RuntimeError("model has no Multi-J-Space; cannot set router bias")
    model.multi_jspace.router.set_branch_bias(probs)


def count_params(model: torch.nn.Module, *, trainable_only: bool = False) -> int:
    ps = model.parameters()
    if trainable_only:
        ps = (p for p in ps if p.requires_grad)
    # Tied weights are the same object; count each storage once.
    seen: dict[int, int] = {}
    for p in ps:
        seen[id(p)] = p.numel()
    return sum(seen.values())


__all__ = ["SPACES", "build_model", "count_params", "set_router_bias"]

# Legacy alias (Ava was the placeholder name; submodule-level import compat)
AvaModel1B = DottieModel1B
__all__ += ["AvaModel1B", "DottieModel1B"]
