"""dottie.grow — function-preserving width growth, depth stretch, honest refusals.

The headline test is `test_integer_width_growth_is_function_preserving`: a model grown
2x in width must produce the SAME logits as its source, to float tolerance, before any
training. That is the property that makes a warm start a warm start and not a prayer.
Approximate paths (depth stretch, non-integer width) get behavioural tests: finite
forward, better-than-fresh loss, honest manifest.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from typing import TYPE_CHECKING

from ava.model import build_model
from test_model import _tiny

from dottie.grow import grow_state_dict, validate_growth

if TYPE_CHECKING:
    from ava.config import AvaConfig


def _widened(cfg: AvaConfig, k: int) -> AvaConfig:
    """The same tiny preset, k× wider (d_model and n_heads; head_dim fixed)."""
    import dataclasses

    model = dataclasses.replace(
        cfg.model, d_model=cfg.model.d_model * k, n_heads=cfg.model.n_heads * k
    )
    return dataclasses.replace(cfg, model=model)


def _deepened(cfg: AvaConfig, n_text: int) -> AvaConfig:
    import dataclasses

    model = dataclasses.replace(cfg.model, n_text_layers=n_text)
    return dataclasses.replace(cfg, model=model)


def test_integer_width_growth_is_function_preserving():
    torch.manual_seed(7)
    src_cfg = _tiny()
    dst_cfg = _widened(src_cfg, 2)
    src = build_model(src_cfg)
    dst = build_model(dst_cfg)

    grown, manifest = grow_state_dict(
        src.state_dict(), dst, src_cfg=src_cfg, dst_cfg=dst_cfg
    )
    dst.load_state_dict(grown)
    assert not manifest["dst_only"], f"unmapped tensors: {manifest['dst_only']}"

    ids = torch.randint(
        0, src_cfg.model.vocab_size, (2, 16), generator=torch.Generator().manual_seed(0)
    )
    src.eval()
    dst.eval()
    with torch.no_grad():
        ls = src(input_ids=ids, task_type="automatic")["lm_logits"]
        ld = dst(input_ids=ids, task_type="automatic")["lm_logits"]
    # Exact modulo RMSNorm's eps: the widened norm averages the padded zeros, so the
    # rsqrt sees mean(x^2)/k + eps instead of (mean(x^2) + eps)/k — a bounded relative
    # error of ~eps/mean(x^2) per norm (eps=1e-5; observed ~5e-4/block at tiny scale).
    # Real growth bugs measured 0.6-0.8 here; the tolerance separates the two regimes.
    assert torch.allclose(ls, ld, atol=2e-2, rtol=1e-2), (
        f"max logit delta {(ls - ld).abs().max().item():.3e} — growth is not preserving"
    )


def test_depth_stretch_runs_and_warm_start_beats_fresh():
    torch.manual_seed(11)
    src_cfg = _tiny()
    dst_cfg = _deepened(_widened(src_cfg, 2), n_text=2)  # wider AND deeper
    src = build_model(src_cfg)
    dst = build_model(dst_cfg)
    grown, _manifest = grow_state_dict(
        src.state_dict(), dst, src_cfg=src_cfg, dst_cfg=dst_cfg
    )
    dst.load_state_dict(grown)

    fresh = build_model(dst_cfg)
    v = validate_growth(
        src, dst, fresh, vocab=src_cfg.model.vocab_size, seq=32, batch=2
    )
    assert all(x == x for x in v.values())  # no NaN sneaks through rounding
    # Depth stretch is approximate — but a warm start that loses to random init on the
    # source model's own function is broken. (Both see the same fixed batch.)
    assert v["grown_loss"] < v["fresh_dst_loss"], v


def test_vocab_mismatch_is_refused_without_allow_partial():
    src_cfg = _tiny()
    import dataclasses

    dst_cfg = dataclasses.replace(
        src_cfg, model=dataclasses.replace(src_cfg.model, vocab_size=128)
    )
    src = build_model(src_cfg)
    dst = build_model(dst_cfg)
    with pytest.raises(SystemExit, match="vocab mismatch"):
        grow_state_dict(src.state_dict(), dst, src_cfg=src_cfg, dst_cfg=dst_cfg)
    # with allow_partial the embedding-shaped tensors keep fresh init, honestly listed
    grown, manifest = grow_state_dict(
        src.state_dict(), dst, src_cfg=src_cfg, dst_cfg=dst_cfg, allow_partial=True
    )
    assert manifest["vocab_fresh"], "vocab-shaped tensors must be flagged"
    dst.load_state_dict(grown)


def test_grown_checkpoint_manifest_is_complete():
    # Every destination tensor lands in exactly one manifest bucket — no silent tensors.
    src_cfg = _tiny()
    dst_cfg = _widened(src_cfg, 3)
    src = build_model(src_cfg)
    dst = build_model(dst_cfg)
    grown, manifest = grow_state_dict(
        src.state_dict(), dst, src_cfg=src_cfg, dst_cfg=dst_cfg
    )
    core = ("copied", "grafted_exact", "grafted", "dst_only", "vocab_fresh")
    n = sum(len(manifest[b]) for b in core)
    assert n == len(dst.state_dict()) == len(grown)
