# LongRoPE2 / Peri-LN / attention sinks: ported onto the fixed model_1b.py

**Status: done.** This file originally tracked the port as deferred work after
the `master` <- `claude/model-training-workflow-plan-n5vep5` merge; the port
has since landed. Kept as a record of what changed and why, since the
reasoning (the RoPE bug in particular) matters for anyone touching this code.

## Why this file exists

`master` and `claude/model-training-workflow-plan-n5vep5` diverged at `f508569`
and both rewrote `model_1b.py` / `multi_jspace_module.py` independently. The
merge kept the **branch's** `model_1b.py` (bug-fixed but without master's
architecture additions) rather than master's, because master's version still
had the exact RoPE bug the branch's version fixed — see below. This file is
the record of what was kept, what was dropped, and (now) how it was ported
back on top of the fixed base rather than reverting to the broken one.

## The bug that decided which base to port onto

Master's `TransformerBlock1B.forward` paired dimensions via
`x[..., ::2]`/`x[..., 1::2]` (`apply_rotary_emb`'s local `rotate_half`) while
its own `get_cos_sin()` built cos/sin via `cat((freqs, freqs))` (half-split
layout). Those two disagree — pairing dim `i` with `i+1` when cos/sin pairs
dim `i` with `i+dim/2` rotates by an inconsistent angle per dimension. Any
hill-climb numbers measured against master's `model_1b.py` (`GWTB v2
d_gw=256 k=8 selective 0.3514 phi 4.55x cap 0.82 collapse 1.0`, see
`tasks/hillclimb-log.md` commit `5a8c2f6`) were computed on top of that
broken rotation and should be treated as unverified.

The port re-plumbs LongRoPE2 through the *fixed* base's module-level
`rotate_half()`/`apply_rotary_emb()` (half-split, matching `get_cos_sin()`)
instead of bringing back a bespoke, bug-prone copy. A regression test
(`test_longrope2_rotary_preserves_norm_and_relative_position`) guards this
specifically: it checks the rotation is norm-preserving up to the intentional
`mscale` factor and that `<R_i q, R_j k>` depends only on `i-j`, which is
exactly the property the interleaved/half-split mismatch destroys.

## What's in model_1b.py now, config-gated, default off

- `rope_type: "yarn" | "longrope2"` on `TransformerBlock1B`/`AvaModel1B`.
  `longrope2_factors()` + `LongRoPE2ScaledRoPE` give non-uniform per-dim RoPE
  factors (critical-dim shift 31->25 as scale 1->100, resonance-jitter
  mitigation) for near-lossless long-context scaling, same `.update()`/
  `.get_cos_sin()` interface as `YaRNScaledRoPE` so `apply_rope_scaling()`
  and the rest of the model don't need to know which one they hold.
- `use_peri_ln: bool` adds an output-LN (RMSNorm) after attention and after
  the FFN, on top of the existing pre-LN. `nn.Identity()` when off — a true
  no-op, not just "small effect."
- `n_sinks: int` adds that many learnable, always-attended KV pairs (Xiao et
  al. 2023) per block. Unlike master's version, sinks are shaped per KV-head
  group (`self.n_kv_heads`, not `n_heads`) so they compose correctly with
  grouped-query attention — concatenated onto K/V before the GQA
  `repeat_interleave`, exactly like a regular key/value would be. When
  `n_sinks>0`, the attention call switches from SDPA's fused `is_causal=True`
  path to an explicit boolean `attn_mask` (`True` = attend: sinks always,
  original tokens causal) since SDPA's fast path can't express that shape.
- Defaults (`rope_type="yarn"`, `n_sinks=0`, `use_peri_ln=False`) reproduce
  the pre-port model exactly — `tests/test_model.py`'s existing 32 tests pass
  unchanged, byte-identical default forward path.

## Config plumbing

`ava/config.py`'s `ModelConfig` gained `rope_type`/`n_sinks`/`use_peri_ln`
(same defaults, validated in `__post_init__`); `ava/model.py`'s
`build_model()` passes them through. No preset (`nano`/`mini`/`base1b.yaml`)
opts in yet — that's a training-behavior decision for whoever wants to spend
a run on it, not implied by porting the code. To try it, add e.g.
`rope_type: longrope2`, `use_peri_ln: true`, `n_sinks: 4` under a preset's
`model:` section.

`scripts/prepare_longrope2.py` (imports `longrope2_factors`) is restored and
runs against the ported function unchanged.

## Left undone, deliberately out of scope for this port

- **Re-running master's hill-climb numbers** against the corrected rotation.
  That needs a real training run, not a code change — do it before trusting
  those numbers for anything.
- **Wiring OroJaR into `ava/jlosses.py`'s objective.** `multi_jspace_module.py`
  already has `estimate_jacobian_fro_norm`/`orojar_orthogonal_loss`/
  `orojar_comprehensive_loss` from the earlier merge (that conflict was
  purely additive, no port needed) but nothing calls them yet.
- **`docs/LOCAL_LLMS_2026_SOTA.md`** claims are accurate again now that the
  features are back in the tree (its note pointing here has been updated) —
  but it still describes the *master* implementation's numbers/behavior in
  places, which may not match this port's version (different sink shape,
  different attention path). Treat descriptions there as directional, not
  exact, until someone reconciles the prose with this implementation.
- A **pre-existing, unrelated latent bug** noticed while reading this code,
  not introduced or worsened by the port: `apply_rope_scaling()` iterates
  `model.fusion_layers` and calls `blk.rope.update(...)` unconditionally, but
  `DeltaNetBlock` (used when `deltanet_layers` is non-empty) has no `.rope`
  attribute at all — calling `apply_rope_scaling` on a model with any
  DeltaNet fusion layers will raise `AttributeError`. Not currently exercised
  by any test or config combination.
