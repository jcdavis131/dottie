# Spec 04 — Model Bug Fixes + Parameterization + GPU Preset Configs

- **Spec ID:** 04_model_and_configs
- **Worker tier:** OPUS
- **Dependencies:** 01_environment (AvaConfig, configs/nano.yaml, pytest scaffolding). Does NOT depend on 02/03 (no data or tokenizer needed — all tests use synthetic tensors).
- **Status when done:** `pytest tests/test_model.py` green in <60s on 4-core CPU; `python -m ava.config --preset nano --count-params` reports 13–16M.

## Purpose

Turn the blueprint model into a correct, trainable, config-driven implementation. The blueprint files
`model_1b.py` and `multi_jspace_module.py` contain real architecture but with showstopper bugs (no
causal mask, broken RoPE rotation, cross-step autograd crash, missing `top_concepts`). **Exception to
the spec-01 "blueprint untouched" rule:** this spec (and only this spec) is authorized to make surgical
in-place edits to exactly two blueprint files — `model_1b.py` and `multi_jspace_module.py`. All other
blueprint files (train_1b_deepspeed.py, eval_branch_harness.py, j_space_module.py, server.py, ...)
remain untouched. New glue code goes in `ava/`.

## Deliverable files (exact paths, repo-root-relative)

1. `model_1b.py` — in-place surgical fixes (items 1, 2, 3, 4a, 7, 8 below)
2. `multi_jspace_module.py` — in-place surgical fixes (items 4b, 5, 7 below)
3. `ava/model.py` — `build_model(cfg: AvaConfig) -> AvaModel1B` factory + `set_router_bias(model, probs)` helper
4. `ava/config.py` — extend AvaConfig (new fields below); update analytic param formula
5. `configs/nano.yaml`, `configs/nano_quick.yaml` — add new keys (values below)
6. `configs/mini.yaml`, `configs/base1b.yaml` — new GPU presets (values below; config-only, never instantiated on this container)
7. `tests/test_model.py`

## Detailed requirements — enumerated fixes (line numbers verified against current HEAD)

### Fix 1 — NO CAUSAL MASK (model_1b.py:134-136)
`TransformerBlock1B.forward` computes plain `torch.einsum('b h l d, b h m d -> b h l m', q, k)` +
`F.softmax` over ALL positions — every token attends to the future; the LM objective is degenerate.
Replace lines 133-136 with `F.scaled_dot_product_attention(q, k, v, is_causal=True,
scale=attn_factor / math.sqrt(self.head_dim))` (keeps the YaRN `attn_factor` temperature currently
built at line 133). No attention-mask argument plumbing needed (packed fixed-length training).
**Required test:** `test_causality` — random input `[2, 64]`, forward; perturb token at position t=40;
logits at positions < 40 unchanged (`torch.allclose(..., atol=1e-5)`), logits at ≥ 40 changed.

### Fix 2 — rotate_half layout mismatch (model_1b.py:91-94 vs model_1b.py:81)
`apply_rotary_emb`'s inner `rotate_half` uses the interleaved convention
(`x1 = x[..., ::2]; x2 = x[..., 1::2]; stack(...).flatten(-2)`), but `get_cos_sin` builds the
half-split layout `emb = torch.cat((freqs, freqs), dim=-1)` (line 81). The combination is NOT a valid
rotation — relative-position encoding is silently broken. Fix `rotate_half` to LLaMA-style half-split:
`torch.cat((-x[..., d//2:], x[..., :d//2]), dim=-1)` where `d = x.shape[-1]`. Leave `get_cos_sin` as-is.
**Required test:** `test_rotary_relative_property` — for random q,k and offsets, verify
`dot(rot(q,pos=m), rot(k,pos=n))` depends only on `m-n`: compare positions (5,3) vs (12,10),
`allclose(atol=1e-5)`. Also verify rotation preserves vector norm.

### Fix 3 — Vision-fusion ternary precedence bug (model_1b.py:210)
`x = x + v.mean(dim=1, keepdim=False).unsqueeze(1) if v.dim()==3 else x` — the ternary binds the ENTIRE
expression, so when `v.dim()!=3` the addition is discarded silently, and the intent is ambiguous.
Parenthesize: `x = x + (v.mean(dim=1).unsqueeze(1) if v.dim() == 3 else v)`. Additionally gate the whole
multimodal path behind `cfg.multimodal` (new constructor arg, item 7): when `multimodal=False`
(nano/mini/base1b are text-only), `VisionEncoder`/`AudioEncoder` are NOT constructed (`None`) so their
params (`nn.Linear(1024, d)` at model_1b.py:145, `nn.Linear(512, d)` at :154) don't pollute param count
or optimizer state; passing `images`/`audio` then raises `ValueError`.
**Required test:** `test_text_only_no_vision_params` — nano-config model has no parameter whose name
contains `vision_enc` or `audio_enc`; forward with `input_ids` only succeeds.

### Fix 4 — cross-step workspace persistence crashes (model_1b.py:197,222-223; multi_jspace_module.py:54-60)
(a) `self._prev_workspaces = jspace_out.get("workspaces")` (model_1b.py:223) stores live graph tensors;
the second training step backprops through the freed graph of step 1 → RuntimeError. (b) In
`SingleWorkspace.forward` (multi_jspace_module.py:57-60), `prev_ws` from a batch of size B1 is added to
`slots` expanded to the new B2 → shape-mismatch crash whenever B changes (train→eval, last partial batch).
Fix: add `use_memory: bool = False` constructor flag on `AvaModel1B`; when False (training default),
`_prev_workspaces` is never stored and stays None. When True (eval persistence tests), store
`{k: v.detach() for ...}` and inside `AvaModel1B.forward` reset `_prev_workspaces = None` if the stored
batch size differs from the incoming B. Add `model.reset_memory()` that sets it to None.
**Required test:** `test_two_steps_varying_batch` — nano model + AdamW: forward(B=2,L=32) → loss.backward()
→ step → zero_grad → forward(B=3,L=32) → backward → step, no exception, both with `use_memory=False`
(default) and `use_memory=True`.

### Fix 5 — JacobianLens.top_concepts MISSING; verbalizer untied (multi_jspace_module.py:16-25, 39-41, 69)
`JacobianLens` in multi_jspace_module.py defines only `concept_vec`; the guard
`if hasattr(self.jlens,'top_concepts')` at line 69 is ALWAYS false, so `verbalizable_mass` is the
constant `torch.tensor(0.06)` — the reportability metric is fake. Also each `SingleWorkspace` allocates
its own V×D verbalizer (lines 39-41 construct TWO JacobianLens instances per workspace) — 4 untied V×D
matrices (8.4M wasted params at nano scale). Fix: (i) implement `top_concepts(self, ws, k=8)` — logits =
`self.verbalizer(ws.mean(dim=1))`, probs = softmax, `vals, idx = probs.topk(k)`, mass =
`vals.sum(dim=-1).mean()`; return `(idx, vals, mass)` (reference impl exists at j_space_module.py:19-25;
do NOT import from there). (ii) `JacobianLens.__init__` and `SingleWorkspace.__init__` accept an optional
`shared_verbalizer_weight: nn.Parameter`; when given, `self.verbalizer.weight = shared_weight` (tied, no
new allocation). `MultiJSpace.__init__` accepts and forwards it; `AvaModel1B` passes `self.lm_head.weight`.
Remove the duplicate-JacobianLens construction at lines 39-41 (keep one `self.jlens`). Drop the sha256
`concept_vec` path or leave it unused — eval (spec 06) uses real tokenizer ids only.
**Required test:** `test_top_concepts_real` — nano forward on two different random inputs; for each space
metric dict: `top_idx` is an int tensor with values in `[0, vocab)`, `verbalizable_mass` a scalar strictly
in `(0, 1)`, not equal to 0.06 exactly, and mass/idx differ between the two inputs. Also
`model.multi_jspace.system1.jlens.verbalizer.weight.data_ptr() == model.lm_head.weight.data_ptr()`.

### Fix 6 — stable-checkpoint load is a no-op (train_1b_deepspeed.py:116-118) — NOTE ONLY
The blueprint prints "Loading stable checkpoint ava_stable_736k.pt" then only calls `freeze_spaces`,
never `load_state_dict`. Do NOT edit train_1b_deepspeed.py — the real load lands in `ava/train.py`
(spec 05, `--branch chat --init <ckpt>`). Record this as a comment in ava/model.py near `build_model`.

### Fix 7 — Parameterize hardcoded sizes (model_1b.py:102,115-119,169,175-177,181; multi_jspace_module.py:35-36,103-106,109-112)
Current hardcodes: `TransformerBlock1B(d_model=2048, n_heads=16, head_dim=128)` (:102) but blocks are
constructed with `TransformerBlock1B(d_model)` only (:175-177) so 16×128 heads always; MLP fixed 4×
(:115-119); `AvaModel1B(vocab_size=128000, d_model=2048, n_text=12, n_fusion=28, n_reason=8)` (:169);
`lm_head` never tied to `embed` (:181 vs :174); `MultiJSpace` slots fixed 32/64/16/32 and hl 8/300/30/150
(:103-106), workspace MHA `num_heads=8` (:35-36), cross-attn `num_heads=4` (:109-112). Fix:
- `AvaModel1B.__init__` accepts `vocab_size, d_model, n_heads, head_dim, mlp_mult, n_text, n_fusion,
  n_reason, tie_lm_head, multimodal, use_memory, jspace_slots: dict, jspace_half_life: dict,
  jspace_num_heads, rope_base`. Blocks constructed with all attn/MLP args. `tie_lm_head=True` sets
  `self.lm_head.weight = self.embed.weight`.
- `MultiJSpace.__init__(d_model, vocab_size, slots: dict, half_life: dict, num_heads,
  shared_verbalizer_weight)` — dict keys are `system1,system2,critic,planner` everywhere
  (the canonical naming used by `freeze_spaces()`/`BRANCH_CONFIGS` and the committed configs).
- All existing defaults preserved so `get_model()` (:266) still works.
- `Router` gains `set_branch_bias(probs: list[float] | None)` storing a log-prior buffer added to
  logits in `Router.forward` (multi_jspace_module.py:77-89) after the task_type bias; `None` clears it.
  `ava/model.py:set_router_bias(model, probs)` wraps it (consumed by spec 05 chat branch).
- Delete the no-op `logits = logits / 1.0` (model_1b.py:237).
- `ava/model.py:build_model(cfg)` maps AvaConfig fields → constructor.
  **The committed `configs/nano.yaml` / `mini.yaml` / `base1b.yaml` are the authoritative schema
  (nested `model:`/`jspace:`/`training:`/`phases:` sections; space keys `system1..planner`) — do
  not rewrite them; extend `AvaConfig` to expose whatever this spec needs from them.** Relevant
  committed values: nano d256 heads 4×64 layers 2/6/2 vocab 8192 tie_lm_head multimodal:false;
  mini d768 heads 12×64 layers 3/6/3 vocab 32000 bf16; base1b d2048 heads 16×128 **GQA
  n_kv_heads 4, SwiGLU mlp_ratio 1.0** layers 12/28/8 vocab 32000 tied (~1.17B — see
  specs/08 arithmetic), `optimizer: adamw8bit`, `gradient_checkpointing: true`.
- **Additional config-gated features required for base1b** (defaults preserve blueprint
  behavior for nano/mini): `n_kv_heads` (grouped-query attention — repeat_interleave KV heads
  or SDPA enable_gqa; default = n_heads i.e. MHA) and `mlp: swiglu` + `mlp_ratio` (SwiGLU gate
  hidden = ratio·d_model·? per specs/08; default `mlp: gelu`, `mlp_mult: 4`). Both must be
  covered by the causality + shape tests at a tiny GQA/SwiGLU config.
**Required test:** `test_param_count_nano` — `build_model(AvaConfig.load("nano"))` total params in
`[13_000_000, 16_000_000]`; and `python -m ava.config --preset nano --count-params` (subprocess) exits 0
printing a count in that range. `count_params` must now build via `ava.model.build_model` (analytic
fallback stays for missing-torch only).

### Fix 8 — RoPE cos/sin recomputed per block per forward (model_1b.py:120,213,217,234)
Every block owns a `YaRNScaledRoPE` (:120) and `AvaModel1B.forward` calls `blk.rope.get_cos_sin(L)`
once per block per forward (:213, :217, :234) — 10 identical computations at nano. Fix: compute
`cos, sin` ONCE per forward from a single model-level rope (`self.rope = YaRNScaledRoPE(dim=head_dim,
base=rope_base)`) and pass to every block; keep per-block `blk.rope` attribute pointing at the shared
module so `apply_rope_scaling` (:260-264) still works (dedupe: update the shared module once).
**Required test:** covered by `test_causality`/`test_rotary_relative_property` plus
`test_rope_shared` — `apply_rope_scaling(model, 32000, 1.2)` changes `attn_factor` visible from every
block and `get_cos_sin` is invoked exactly once per forward (assert via monkeypatched counter).

### Fix 9 — torch>=2.4 floor
`RMSNorm.forward` uses `F.rms_norm` (model_1b.py:17), added in torch 2.4. Add a top-of-module guard in
`ava/model.py`: raise `ImportError("torch>=2.4 required (F.rms_norm)")` if version lower. (setup_env.sh
from spec 01 already installs >=2.4; this is defense.)

## Interfaces (frozen contract for specs 05/06)

- `from ava.model import build_model, set_router_bias`; `build_model(cfg) -> AvaModel1B` on CPU, fp32,
  `use_memory=False`.
- `model(input_ids=ids, task_type=t)` returns `{"lm_logits": [B,L,V], "jspace": {...}, "fused": [B,L,D]}`;
  `jspace` dict keys per multi_jspace_module.py:149-155 (`system1/system2/critic/planner` sub-dicts each
  with `broadcast_strength`, `verbalizable_mass`, `workspace`, `hl_est`, plus new `top_idx`, `top_vals`;
  `route_probs [B,4]`, `route_logits`, `veto`, `broadcast`, `broadcast_strength`, `workspaces`).
- `model.freeze_spaces([...])` (model_1b.py:241-255) and `apply_rope_scaling(model, base, scale)`
  (:260-264) keep their signatures.
- `SingleWorkspace.decay_factor()/hl_est()` and all of `MultiJSpaceLosses` (multi_jspace_module.py:159-195)
  keep their signatures — spec 05 reuses them.

## Acceptance criteria (foreman runs, repo root)

1. `pytest tests/test_model.py -q` → all pass, wall time < 60s on 4-core CPU.
2. `python -m ava.config --preset nano --count-params` → exit 0, count in [13e6, 16e6].
3. `python -c "from ava.config import AvaConfig; AvaConfig.load('mini'); AvaConfig.load('base1b'); print('ok')"` → ok (configs parse; models NOT built).
4. `python - <<'EOF'` two fwd+bwd+opt steps at B=2 then B=3 on nano (inline script mirroring
   `test_two_steps_varying_batch`) → exit 0. `EOF`
5. `git diff --stat` touches ONLY model_1b.py and multi_jspace_module.py among pre-existing files;
   `git status --porcelain` shows new files only under ava/, configs/, tests/, specs/.

## Out of scope

- Training loop, losses composition, data, checkpointing (spec 05). Eval/interventions (spec 06).
  server.py (separate spec). GPU execution, bf16, 8-bit optimizer runtime (configs only here).
- Editing train_1b_deepspeed.py, eval_branch_harness.py, j_space_module.py, server.py, dolma_config.yaml.
- KV-cache / incremental decoding; attention masks for padded batches.
- Committing to git.
