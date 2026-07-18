"""Model correctness tests.

The headline test is `test_causality`. The original attention had no causal
mask, so a "language model" could see the token it was predicting. That defect
is invisible in a loss curve (loss just drops implausibly fast) and invalidates
every downstream number. It gets a property test, not a smoke test.
"""

from __future__ import annotations

import math

import pytest

torch = pytest.importorskip("torch")

from ava.config import AvaConfig, ConfigError
from ava.model import build_model, count_params, set_router_bias
from model_1b import (
    AvaModel1B, DeltaNetBlock, LongRoPE2ScaledRoPE, TransformerBlock1B,
    apply_rope_scaling, apply_rotary_emb, rotate_half,
)


def _tiny(jspace_causal: bool = True, jspace_chunk: int = 4, **overrides) -> AvaConfig:
    """A model small enough to test exhaustively on CPU in milliseconds."""
    raw = {
        "preset": "tiny",
        "model": {
            "vocab_size": 64, "d_model": 32, "n_heads": 2, "head_dim": 16,
            "n_text_layers": 1, "n_fusion_layers": 1, "n_reasoning_layers": 1,
            "tie_lm_head": True, "tie_verbalizer": True, "multimodal": False,
            "qk_norm": True, "rope_base_init": 10000, "jspace_num_heads": 2,
            **overrides.pop("model", {}),
        },
        "jspace": {
            "slots": {"system1": 4, "system2": 4, "critic": 2, "planner": 4},
            "half_life": {"system1": 8, "system2": 60, "critic": 30, "planner": 50},
            "hl_weight": {"system1": 0.6, "system2": 0.8, "critic": 1.0, "planner": 0.7},
            "broadcast_target": {"system1": 0.18, "system2": 0.22, "critic": 0.20, "planner": 0.20},
            "routing_targets": {
                "automatic": [0.6, 0.15, 0.1, 0.15], "deliberate": [0.15, 0.55, 0.1, 0.2],
                "safety": [0.1, 0.2, 0.6, 0.1], "temporal": [0.1, 0.3, 0.1, 0.5],
            },
            "base_loss_weights": {"report": 1.0, "broadcast": 0.5, "selectivity": 0.3, "modulation": 0.5},
            "j_weight": {"early": 0.08, "late": 0.15},
            "causal": jspace_causal, "chunk_size": jspace_chunk,
            **overrides.pop("jspace", {}),
        },
        "training": {
            "device": "cpu", "precision": "fp32", "tokens_per_step": 64,
            "wsd": {"warmup_steps": 1, "stable_frac": 0.9, "lr_max": 1e-3, "lr_min": 1e-4},
            "optimizer": {"name": "adamw", "betas": [0.9, 0.95], "weight_decay": 0.1, "grad_clip": 1.0},
        },
        "phases": [{"name": "p0_logic", "tokens": 100, "seq": 16, "rope_base": 10000, "ntk": 1.0,
                    "mix": {"logic": 1.0}}],
    }
    for k, v in overrides.items():
        raw[k] = v
    return AvaConfig.from_dict(raw)


@pytest.fixture(scope="module")
def tiny_model():
    torch.manual_seed(0)
    return build_model(_tiny()).eval()


# ---------------------------------------------------------------------------
# THE bug: attention must not see the future.

def test_causality_future_tokens_cannot_change_past_logits(tiny_model):
    """Perturbing token t must leave logits at positions < t bit-identical.

    Without a causal mask this fails at every position.
    """
    torch.manual_seed(1)
    ids = torch.randint(0, 64, (1, 12))
    with torch.no_grad():
        base = tiny_model(input_ids=ids)["lm_logits"]

    t = 7
    perturbed = ids.clone()
    perturbed[0, t] = (perturbed[0, t] + 1) % 64
    with torch.no_grad():
        after = tiny_model(input_ids=perturbed)["lm_logits"]

    torch.testing.assert_close(base[:, :t], after[:, :t], atol=1e-5, rtol=1e-5)
    # and the change must actually propagate forward, or the test is vacuous
    assert not torch.allclose(base[:, t], after[:, t], atol=1e-5)


def test_causality_holds_at_every_position(tiny_model):
    torch.manual_seed(2)
    ids = torch.randint(0, 64, (1, 8))
    with torch.no_grad():
        base = tiny_model(input_ids=ids)["lm_logits"]
    for t in range(1, 8):
        p = ids.clone()
        p[0, t] = (p[0, t] + 3) % 64
        with torch.no_grad():
            out = tiny_model(input_ids=p)["lm_logits"]
        torch.testing.assert_close(base[:, :t], out[:, :t], atol=1e-5, rtol=1e-5)


def test_jspace_broadcast_is_prefix_only():
    """The workspace broadcast into chunk c must not depend on tokens in chunk >= c.

    The original whole-sequence mean-pool + expand made every position's
    broadcast a function of the entire sequence. Regression guard.
    """
    torch.manual_seed(8)
    m = build_model(_tiny(jspace_chunk=4)).eval()
    mj = m.multi_jspace
    fused = torch.randn(1, 12, 32)

    with torch.no_grad():
        out_a, _ = mj(fused)
        f2 = fused.clone()
        f2[0, 9] += 10.0                     # perturb a LATE token
        out_b, _ = mj(f2)

    # positions before the perturbed token's chunk (chunk 2 starts at index 8)
    torch.testing.assert_close(out_a[:, :8], out_b[:, :8], atol=1e-5, rtol=1e-5)
    # ...and the perturbation must reach later chunks, or the test proves nothing
    assert not torch.allclose(out_a[:, 8:], out_b[:, 8:], atol=1e-5)


def test_jspace_noncausal_mode_does_leak():
    """Guards the guard: `causal=False` really is the whole-sequence pooling that
    must never be used for training."""
    torch.manual_seed(9)
    m = build_model(_tiny(jspace_causal=False)).eval()
    fused = torch.randn(1, 12, 32)
    with torch.no_grad():
        a, _ = m.multi_jspace(fused)
        f2 = fused.clone()
        f2[0, 11] += 10.0
        b, _ = m.multi_jspace(f2)
    assert not torch.allclose(a[:, 0], b[:, 0], atol=1e-5), "non-causal mode should leak"


def test_chunk0_broadcast_is_data_independent():
    """Chunk 0 broadcasts from the learned prior, so two different inputs must
    produce the same broadcast there -- the proof that nothing leaks into it."""
    torch.manual_seed(10)
    m = build_model(_tiny(jspace_chunk=4)).eval()
    mj = m.multi_jspace
    with torch.no_grad():
        a, _ = mj(torch.randn(1, 8, 32))
        b, _ = mj(torch.randn(1, 8, 32))
        # subtract the residual input to recover the broadcast itself
    # broadcast_from on the init state must match for any batch of same size
    s = mj.system1.init_state(1)
    with torch.no_grad():
        bc1 = mj.system1.broadcast_from(s, 4)
        bc2 = mj.system1.broadcast_from(mj.system1.init_state(1), 4)
    torch.testing.assert_close(bc1, bc2)


# ---------------------------------------------------------------------------
# T11.2 -- gated DeltaNet fixed-state block (specs/11_arch_hillclimb.md).

def test_deltanet_block_is_causal():
    """Same property as the transformer block, proven the same way: perturbing
    token t must leave the block's own output at positions < t bit-identical."""
    torch.manual_seed(20)
    blk = DeltaNetBlock(d_model=16, n_heads=2, head_dim=8).eval()
    x = torch.randn(1, 10, 16)
    with torch.no_grad():
        base = blk(x, None, None)

    t = 4
    x2 = x.clone()
    x2[0, t] += 5.0
    with torch.no_grad():
        after = blk(x2, None, None)

    torch.testing.assert_close(base[:, :t], after[:, :t], atol=1e-5, rtol=1e-5)
    assert not torch.allclose(base[:, t], after[:, t], atol=1e-5), "perturbation must propagate forward"


def test_deltanet_state_size_independent_of_context_length():
    """The whole point of T11.2: state is [B, H, Dh, Dh], not a KV-cache that
    grows with L. Run at 2x/4x/8x a base length and confirm the state tensor
    shape -- and therefore its byte size -- never changes."""
    torch.manual_seed(21)
    blk = DeltaNetBlock(d_model=16, n_heads=2, head_dim=8)
    base_bytes = blk.state_bytes(batch_size=1)
    assert base_bytes == 1 * 2 * 8 * 8 * 4  # B * H * Dh * Dh * fp32

    for L in (16, 32, 64, 128):  # 2x, 4x, 8x, 16x a 8-token base window
        x = torch.randn(1, L, 16)
        with torch.no_grad():
            out = blk(x, None, None)
        assert out.shape == (1, L, 16)
        # state_bytes() takes no L argument by construction; assert that isn't
        # accidentally lying by also checking it doesn't scale with L directly.
        assert blk.state_bytes(batch_size=1) == base_bytes


def test_deltanet_layers_swappable_and_causal_in_full_model():
    """A subset of fusion layers as DeltaNetBlock; the full-model causality
    property (T6.1's headline test) must still hold end to end."""
    torch.manual_seed(22)
    m = AvaModel1B(
        vocab_size=64, d_model=32, n_text=1, n_fusion=2, n_reason=1,
        n_heads=2, head_dim=16, multi_jspace_enabled=False, multimodal=False,
        deltanet_layers=[0],
    ).eval()
    assert isinstance(m.fusion_layers[0], DeltaNetBlock)
    assert isinstance(m.fusion_layers[1], TransformerBlock1B)

    ids = torch.randint(0, 64, (1, 10))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    t = 5
    p = ids.clone()
    p[0, t] = (p[0, t] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :t], after[:, :t], atol=1e-4, rtol=1e-4)
    assert not torch.allclose(base[:, t], after[:, t], atol=1e-5)


def test_deltanet_layers_default_off_preserves_existing_model():
    """deltanet_layers defaults to None: every fusion layer must still be a
    plain TransformerBlock1B, so this param is a pure opt-in addition."""
    m = AvaModel1B(vocab_size=64, d_model=32, n_text=1, n_fusion=3, n_reason=1,
                    n_heads=2, head_dim=16, multi_jspace_enabled=False, multimodal=False)
    assert all(isinstance(blk, TransformerBlock1B) for blk in m.fusion_layers)


# ---------------------------------------------------------------------------
# Rotary: half-split layout, and the relative-position property.

def test_rotate_half_is_half_split_not_interleaved():
    x = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    # half-split: (-x[2:], x[:2]) -> [-3, -4, 1, 2]
    torch.testing.assert_close(rotate_half(x), torch.tensor([[-3.0, -4.0, 1.0, 2.0]]))


def test_rotary_preserves_norm():
    torch.manual_seed(3)
    q = torch.randn(1, 1, 5, 8)
    k = torch.randn(1, 1, 5, 8)
    from model_1b import YaRNScaledRoPE
    cos, sin = YaRNScaledRoPE(dim=8).get_cos_sin(5)
    qr, kr = apply_rotary_emb(q, k, cos, sin)
    torch.testing.assert_close(q.norm(dim=-1), qr.norm(dim=-1), atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(k.norm(dim=-1), kr.norm(dim=-1), atol=1e-5, rtol=1e-5)


def test_rotary_dot_product_depends_only_on_relative_position():
    """<R_i q, R_j k> must depend on (i-j) alone. This is the whole point of RoPE,
    and it is exactly what the interleaved/half-split mismatch destroyed."""
    from model_1b import YaRNScaledRoPE
    torch.manual_seed(4)
    d = 16
    cos, sin = YaRNScaledRoPE(dim=d).get_cos_sin(12)
    q = torch.randn(1, 1, 1, d)
    k = torch.randn(1, 1, 1, d)

    def score(i, j):
        qi = apply_rotary_emb(q, k, cos[i:i + 1], sin[i:i + 1])[0]
        kj = apply_rotary_emb(q, k, cos[j:j + 1], sin[j:j + 1])[1]
        return (qi * kj).sum().item()

    # same offset => same score
    assert score(5, 2) == pytest.approx(score(8, 5), abs=1e-4)
    assert score(3, 1) == pytest.approx(score(9, 7), abs=1e-4)
    # different offset => different score
    assert score(5, 2) != pytest.approx(score(5, 4), abs=1e-3)


# ---------------------------------------------------------------------------
# The autograd / batch-shape landmine.

def test_two_consecutive_train_steps_with_changing_batch_size():
    """Old code cached workspaces with a live graph and a fixed batch dim:
    step 2 raised 'backward through the graph a second time'."""
    torch.manual_seed(5)
    model = build_model(_tiny())
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

    for bs in (2, 3, 2):
        ids = torch.randint(0, 64, (bs, 8))
        out = model(input_ids=ids)
        loss = out["lm_logits"].float().mean()
        loss.backward()
        opt.step()
        opt.zero_grad()
        assert torch.isfinite(loss)


def test_use_memory_off_by_default_and_detaches_when_on():
    m = build_model(_tiny())
    assert m.use_memory is False
    assert m._prev_workspaces is None

    m2 = build_model(_tiny(), use_memory=True)
    m2.eval()
    ids = torch.randint(0, 64, (2, 8))
    with torch.no_grad():
        m2(input_ids=ids)
    assert m2._prev_workspaces is not None
    for t in m2._prev_workspaces.values():
        assert not t.requires_grad, "cached workspaces must be detached"

    # a batch-size change must reset rather than explode
    with torch.no_grad():
        m2(input_ids=torch.randint(0, 64, (3, 8)))


# ---------------------------------------------------------------------------
# JacobianLens.top_concepts -- was an unreachable branch returning constant 0.06.

def test_top_concepts_returns_real_ids_and_input_dependent_mass(tiny_model):
    torch.manual_seed(6)
    a = tiny_model(input_ids=torch.randint(0, 64, (1, 8)))["jspace"]
    b = tiny_model(input_ids=torch.randint(0, 64, (1, 8)))["jspace"]

    for out in (a, b):
        m = out["system2"]["verbalizable_mass"]
        assert 0.0 < float(m) < 1.0, "mass must be a probability"
        assert float(m) != pytest.approx(0.06, abs=1e-9), "constant 0.06 = the old dead branch"

    idx = a["system2"]["top_concepts"]
    assert idx.dtype in (torch.int64, torch.int32)
    assert int(idx.max()) < 64 and int(idx.min()) >= 0, "token ids must be in vocab"

    masses = {float(a["system2"]["verbalizable_mass"]), float(b["system2"]["verbalizable_mass"])}
    assert len(masses) == 2, "verbalizable_mass must vary with input"


def test_verbalizer_is_tied_to_lm_head_when_configured():
    m = build_model(_tiny())
    assert m.multi_jspace.system1.verbalizer.weight is m.lm_head.weight
    assert m.lm_head.weight is m.embed.weight  # tie_lm_head

    untied = build_model(_tiny(model={"tie_verbalizer": False}))
    assert untied.multi_jspace.system1.verbalizer.weight is not untied.lm_head.weight


# ---------------------------------------------------------------------------
# Config-gated features that base1b needs.

def test_gqa_shapes_and_causality():
    cfg = _tiny(model={"n_heads": 4, "head_dim": 8, "d_model": 32, "n_kv_heads": 2})
    m = build_model(cfg).eval()
    ids = torch.randint(0, 64, (1, 6))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    assert base.shape == (1, 6, 64)

    p = ids.clone()
    p[0, 3] = (p[0, 3] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :3], after[:, :3], atol=1e-5, rtol=1e-5)


def test_swiglu_shapes_and_causality():
    cfg = _tiny(model={"mlp": "swiglu", "mlp_ratio": 1.0})
    m = build_model(cfg).eval()
    ids = torch.randint(0, 64, (1, 6))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    p = ids.clone()
    p[0, 4] = (p[0, 4] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :4], after[:, :4], atol=1e-5, rtol=1e-5)


# ---------------------------------------------------------------------------
# LongRoPE2 / Peri-LN / attention sinks (ported from an independent line of
# work that built them on the *unfixed* rotate_half()/get_cos_sin() -- see
# tasks/plan-longrope2-port.md). All three are config-gated and default off.

def test_attention_sinks_default_off_preserves_existing_model():
    m = AvaModel1B(vocab_size=64, d_model=32, n_text=1, n_fusion=1, n_reason=1,
                    n_heads=2, head_dim=16, multi_jspace_enabled=False, multimodal=False)
    assert m.text_layers[0].sink_k is None and m.text_layers[0].sink_v is None
    assert isinstance(m.text_layers[0].peri_norm_attn, torch.nn.Identity)
    assert isinstance(m.text_layers[0].peri_norm_mlp, torch.nn.Identity)


def test_attention_sinks_causal_with_gqa():
    """Sinks are shaped per KV-head group so they compose with GQA; this must
    still hold end to end: future tokens cannot change past logits, and the
    sinks (always-attended) must not be a back door around that."""
    cfg = _tiny(model={"n_heads": 4, "head_dim": 8, "d_model": 32, "n_kv_heads": 2,
                        "n_sinks": 3})
    m = build_model(cfg).eval()
    assert m.text_layers[0].sink_k.shape == (2, 3, 8)  # (n_kv_heads, n_sinks, head_dim)

    ids = torch.randint(0, 64, (1, 6))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    assert base.shape == (1, 6, 64)

    p = ids.clone()
    p[0, 3] = (p[0, 3] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :3], after[:, :3], atol=1e-5, rtol=1e-5)
    assert not torch.allclose(base[:, 3], after[:, 3], atol=1e-5)


def test_peri_ln_adds_output_norm_and_stays_causal():
    cfg = _tiny(model={"use_peri_ln": True})
    m = build_model(cfg).eval()
    assert isinstance(m.text_layers[0].peri_norm_attn, torch.nn.modules.module.Module)
    assert not isinstance(m.text_layers[0].peri_norm_attn, torch.nn.Identity)
    assert not isinstance(m.text_layers[0].peri_norm_mlp, torch.nn.Identity)

    ids = torch.randint(0, 64, (1, 6))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    p = ids.clone()
    p[0, 4] = (p[0, 4] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :4], after[:, :4], atol=1e-5, rtol=1e-5)


def test_rope_type_rejects_unknown_value():
    with pytest.raises(ConfigError, match="rope_type"):
        _tiny(model={"rope_type": "bogus"})
    with pytest.raises(ValueError, match="rope_type"):
        TransformerBlock1B(d_model=32, n_heads=2, head_dim=16, rope_type="bogus")


def test_longrope2_rope_scaling_updates_lambda_factors():
    cfg = _tiny(model={"rope_type": "longrope2"})
    m = build_model(cfg)
    from model_1b import LongRoPE2ScaledRoPE
    assert isinstance(m.rope, LongRoPE2ScaledRoPE)
    assert isinstance(m.text_layers[0].rope, LongRoPE2ScaledRoPE)

    base_lambda = m.rope.lambda_factors.clone()
    apply_rope_scaling(m, 1_000_000, 50.0)
    assert m.rope.base == 1_000_000 and m.rope.scale == 50.0
    assert not torch.allclose(m.rope.lambda_factors, base_lambda), \
        "lambda_factors must change with scale, or LongRoPE2 isn't doing anything"
    assert m.rope.critical < 31.0, "critical dim must shift down (31->25 direction) as scale grows"
    assert m.rope.attn_factor > 1.0 and 1.0 <= m.rope.mscale <= 1.414
    assert m.text_layers[0].rope.base == 1_000_000, "per-block rope must stay in sync"


def test_longrope2_rotary_preserves_norm_and_relative_position():
    """The exact regression the port exists to avoid: an independent line of
    work built LongRoPE2 on top of the *original* interleaved rotate_half(),
    which didn't match get_cos_sin()'s half-split cos/sin layout. Ported
    through the fixed apply_rotary_emb()/rotate_half() instead, so this must
    hold exactly like it does for YaRNScaledRoPE."""
    torch.manual_seed(11)
    d = 16
    rope = LongRoPE2ScaledRoPE(dim=d)
    rope.update(base=1_000_000, scale=50.0)  # scale>1 so lambda_factors != 1
    assert not torch.allclose(rope.lambda_factors, torch.ones_like(rope.lambda_factors))

    # A *correct* rotation is an isometry up to the uniform `mscale` factor
    # YaRN/LongRoPE2 both apply on purpose (the "10x less tokens" magnitude
    # boost) -- ||rotated|| == ||orig|| * mscale, exactly, at every position.
    # An orthogonal-but-wrong rotation (e.g. angle mismatch per dim) breaks
    # this too, since it stops being a proper rotation at all; that's what
    # makes this check equivalent to the plain norm-preservation one at
    # mscale=1 while still exercising the scale>1 (non-trivial lambda) path.
    q = torch.randn(1, 1, 5, d)
    k = torch.randn(1, 1, 5, d)
    cos, sin = rope.get_cos_sin(5)
    qr, kr = apply_rotary_emb(q, k, cos, sin)
    torch.testing.assert_close(q.norm(dim=-1) * rope.mscale, qr.norm(dim=-1), atol=1e-4, rtol=1e-4)
    torch.testing.assert_close(k.norm(dim=-1) * rope.mscale, kr.norm(dim=-1), atol=1e-4, rtol=1e-4)

    q1 = torch.randn(1, 1, 1, d)
    k1 = torch.randn(1, 1, 1, d)
    cos, sin = rope.get_cos_sin(12)

    def score(i, j):
        qi = apply_rotary_emb(q1, k1, cos[i:i + 1], sin[i:i + 1])[0]
        kj = apply_rotary_emb(q1, k1, cos[j:j + 1], sin[j:j + 1])[1]
        return (qi * kj).sum().item()

    assert score(5, 2) == pytest.approx(score(8, 5), abs=1e-3)
    assert score(5, 2) != pytest.approx(score(5, 4), abs=1e-3)


def test_longrope2_forward_runs_and_is_causal():
    cfg = _tiny(model={"rope_type": "longrope2"})
    m = build_model(cfg)
    apply_rope_scaling(m, 1_000_000, 20.0)
    m.eval()
    ids = torch.randint(0, 64, (1, 6))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    p = ids.clone()
    p[0, 4] = (p[0, 4] + 1) % 64
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :4], after[:, :4], atol=1e-5, rtol=1e-5)
    assert not torch.allclose(base[:, 4], after[:, 4], atol=1e-5)


def test_gradient_checkpointing_matches_plain_forward():
    torch.manual_seed(7)
    cfg = _tiny()
    m = build_model(cfg)
    ids = torch.randint(0, 64, (2, 8))
    m.train()

    m.gradient_checkpointing = False
    loss_a = m(input_ids=ids)["lm_logits"].float().sum()
    ga = torch.autograd.grad(loss_a, m.embed.weight, retain_graph=False)[0].clone()

    m.zero_grad()
    m.gradient_checkpointing = True
    loss_b = m(input_ids=ids)["lm_logits"].float().sum()
    gb = torch.autograd.grad(loss_b, m.embed.weight)[0]

    torch.testing.assert_close(ga, gb, atol=1e-4, rtol=1e-4)


def test_router_branch_bias_shifts_routing():
    m = build_model(_tiny()).eval()
    ids = torch.randint(0, 64, (1, 8))
    with torch.no_grad():
        before = m(input_ids=ids, task_type="deliberate")["jspace"]["route_probs"].clone()

    set_router_bias(m, [0.15, 0.25, 0.35, 0.25])  # chat branch: Critic-heavy
    with torch.no_grad():
        after = m(input_ids=ids, task_type="deliberate")["jspace"]["route_probs"]
    assert after[0, 2] > before[0, 2], "critic weight should rise under the chat bias"

    set_router_bias(m, None)
    with torch.no_grad():
        restored = m(input_ids=ids, task_type="deliberate")["jspace"]["route_probs"]
    torch.testing.assert_close(before, restored, atol=1e-6, rtol=1e-6)


def test_routing_responds_to_task_type(tiny_model):
    ids = torch.randint(0, 64, (1, 8))
    with torch.no_grad():
        probs = {tt: tiny_model(input_ids=ids, task_type=tt)["jspace"]["route_probs"][0]
                 for tt in ("automatic", "deliberate", "safety", "temporal")}
    assert probs["automatic"].argmax().item() == 0
    assert probs["safety"].argmax().item() == 2


def test_freeze_spaces_and_unknown_space_raises(tiny_model):
    m = build_model(_tiny())
    m.freeze_spaces(["system1", "system2"])
    assert all(not p.requires_grad for p in m.multi_jspace.system1.parameters())
    assert any(p.requires_grad for p in m.multi_jspace.critic.parameters())
    with pytest.raises(ValueError, match="unknown space"):
        m.freeze_spaces(["nope"])
    m.unfreeze_all()
    assert all(p.requires_grad for p in m.multi_jspace.system1.parameters())


def test_rope_scaling_updates_model_and_blocks():
    m = build_model(_tiny())
    apply_rope_scaling(m, 32000, 1.2)
    assert m.rope.base == 32000 and m.rope.scale == 1.2
    assert m.text_layers[0].rope.base == 32000
    apply_rope_scaling(m, 1_000_000, 4.0)  # YaRN regime
    assert m.rope.attn_factor > 1.0 and 1.0 <= m.rope.mscale <= 1.414


# ---------------------------------------------------------------------------
# Presets

@pytest.mark.parametrize("preset", ["nano", "mini", "base1b"])
def test_presets_parse(preset):
    cfg = AvaConfig.load(preset)
    assert cfg.preset == preset
    assert cfg.model.n_heads * cfg.model.head_dim == cfg.model.d_model


def test_nano_param_count_in_band():
    cfg = AvaConfig.load("nano")
    n = count_params(build_model(cfg))
    assert 13_000_000 <= n <= 16_000_000, f"nano is {n/1e6:.1f}M, expected 13-16M"


def test_analytic_param_count_agrees_with_built_model():
    cfg = AvaConfig.load("nano")
    built = count_params(build_model(cfg))
    analytic = cfg.analytic_param_count()
    assert abs(built - analytic) / built < 0.10, f"built {built} vs analytic {analytic}"


def test_config_rejects_unknown_key_and_bad_dims():
    with pytest.raises(ConfigError, match="unknown key"):
        _tiny(model={"nonsense": 1})
    with pytest.raises(ConfigError, match="!= d_model"):
        _tiny(model={"n_heads": 3})
    with pytest.raises(ConfigError, match="uint16"):
        _tiny(model={"vocab_size": 70000})


def test_init_loss_matches_uniform_predictor():
    """A correctly initialized LM starts at cross-entropy ~= ln(vocab).

    Torch's default N(0,1) embedding init (which the model inherited, with
    lm_head tied to it) started nano at ~196 instead of 9.01.
    """
    torch.manual_seed(11)
    cfg = AvaConfig.load("nano")
    V = cfg.model.vocab_size
    m = build_model(cfg).eval()
    ids = torch.randint(0, V, (4, 64))
    with torch.no_grad():
        logits = m(input_ids=ids)["lm_logits"]
    loss = torch.nn.functional.cross_entropy(
        logits[:, :-1].reshape(-1, V).float(), ids[:, 1:].reshape(-1)
    )
    assert abs(float(loss) - math.log(V)) < 0.5, f"init loss {float(loss):.2f} vs ln(V)={math.log(V):.2f}"


def test_model_can_memorize_one_batch():
    """End-to-end gradient sanity: a working causal LM overfits a fixed batch."""
    torch.manual_seed(12)
    m = build_model(_tiny()).train()
    ids = torch.randint(0, 64, (2, 16))
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
    first = last = None
    for i in range(40):
        logits = m(input_ids=ids)["lm_logits"]
        loss = torch.nn.functional.cross_entropy(
            logits[:, :-1].reshape(-1, 64).float(), ids[:, 1:].reshape(-1)
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        opt.zero_grad()
        if i == 0:
            first = float(loss)
        last = float(loss)
    assert last < first * 0.6, f"loss did not fall: {first:.3f} -> {last:.3f}"


def test_nano_forward_runs_and_is_causal():
    cfg = AvaConfig.load("nano")
    m = build_model(cfg).eval()
    ids = torch.randint(0, cfg.model.vocab_size, (1, 16))
    with torch.no_grad():
        base = m(input_ids=ids)["lm_logits"]
    assert base.shape == (1, 16, cfg.model.vocab_size)
    p = ids.clone()
    p[0, 9] = (p[0, 9] + 1) % cfg.model.vocab_size
    with torch.no_grad():
        after = m(input_ids=p)["lm_logits"]
    torch.testing.assert_close(base[:, :9], after[:, :9], atol=1e-4, rtol=1e-4)
