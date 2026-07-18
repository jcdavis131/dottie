# Spec 05 — Real Training Loop + J-Losses + Packing Pipeline

- **Spec ID:** 05_training
- **Worker tier:** OPUS. The packing pipeline (`ava/data.py` + `scripts/build_dataset.py`) is a
  self-contained SONNET subtask — dispatch it first against the PhaseSampler interface below, in
  parallel with the loss/trainer work.
- **Dependencies:** 01_environment (AvaConfig), 02 (data gen: `data/raw/*.jsonl`), 03 (tokenizer:
  `ava.tokenizer`, vocab 8192 for nano), 04_model_and_configs (build_model, fixed model).
- **Status when done:** `bash scripts/smoke_e2e.sh` green in ~5 min; `pytest tests/test_train_smoke.py` green.

## Purpose

Replace the mock trainer (train_1b_deepspeed.py runs a 5-step demo with `loss=torch.tensor(1.0)` at
:121-139 and its "checkpoint load" at :116-118 never calls `load_state_dict`) with a real single-process,
device-agnostic training loop for the nano preset on 4-core CPU, plus the tokenize/pack pipeline that
feeds it. Same code must run unmodified with `--device cuda` later (RTX 4080 12GB / WSL2 — separate
spec). Zero network calls: no wandb, no HF hub; metrics go to local JSONL.

## Deliverable files (exact paths)

1. `ava/data.py` — memmap dataset + `PhaseSampler` (Sonnet subtask)
2. `scripts/build_dataset.py` — tokenize + pack per-phase bins (Sonnet subtask)
3. curriculum lives in the **committed `configs/nano.yaml`** (`phases:` / `training:` /
   `branch_chat:` sections) — no separate curriculum file; see below for how to consume it
4. `ava/jlosses.py` — combined loss
5. `ava/train.py` — trainer CLI (`python -m ava.train`)
6. `scripts/bench_throughput.py`
7. `scripts/smoke_e2e.sh`
8. `tests/test_train_smoke.py`

## Detailed requirements

### Curriculum — consumed from the committed `configs/nano.yaml`
The committed `configs/nano.yaml` (`phases:`/`training:`/`branch_chat:` sections) is authoritative
for token budgets, seq lengths, RoPE transitions, WSD numbers, and the chat-branch recipe. The
table below restates the derived step arithmetic the trainer must honor; where the yaml's
per-phase `mix:` keys don't match spec-02 source names, the trainer/build worker maps them
(preserving proportions) and records the mapping as comments in the yaml.
Six phases; `optimizer step = 8192 tokens` always (micro_batch × grad_accum × seq_len == 8192;
micro_batch chosen per seq_len: 8@256, 4@512, 2@1024, grad_accum computed = 8192/(mb*seq)).
```yaml
step_tokens: 8192
phases:
  - {id: 0, name: logic,      tokens: 5000000,  seq_len: 256,  j_weight: 0.08}
  - {id: 1, name: math,       tokens: 6000000,  seq_len: 256,  j_weight: 0.08}
  - {id: 2, name: foundation, tokens: 10000000, seq_len: 512,  j_weight: 0.08}
  - {id: 3, name: reasoning,  tokens: 4500000,  seq_len: 512,  j_weight: 0.15}
  - {id: 4, name: long,       tokens: 1500000,  seq_len: 1024, j_weight: 0.15, rope_base: 32000, rope_scale: 1.2}
  - {id: 5, name: anneal,     tokens: 3000000,  seq_len: 1024, j_weight: 0.15, rope_base: 32000, rope_scale: 1.2}
wsd: {warmup_steps: 110, lr_max: 1.0e-3, lr_min: 1.0e-4, stable_until_step: 3369, total_steps: 3662,
      stable_ckpt: runs/base/ava_nano_stable.pt}
optimizer: {betas: [0.9, 0.95], weight_decay: 0.1, grad_clip: 1.0}
branch_chat: {tokens: 3000000, lr: 2.5e-4, freeze: [system1, system2],
              router_bias: [0.15, 0.25, 0.35, 0.25],
              mix: {chat_alignment: 0.30, safety: 0.20, delegation: 0.25, temporal: 0.15, counterfactual: 0.10}}
```
Total 30M tokens = 3662 steps (nano_quick: trainer scales every phase's `tokens` by
`cfg.token_budget/30e6` and recomputes warmup/stable/total proportionally). WSD shape mirrors
train_1b_deepspeed.py:39-47 scaled down (blueprint: 2000/736k/800k @2e-4→2e-5). Per-phase mixture
weights (below) are the dolma_config.yaml:34-99 phase mixes scaled to spec-02 sources; keys MUST match
`source` values present in `data/raw/*.jsonl` — hard error at build time otherwise. Include in the yaml
a `mix:` per phase: P0 {logic: 0.60, math: 0.20, formal: 0.20}; P1 {math: 0.80, logic: 0.20};
P2 {web_edu: 0.35, code: 0.20, math: 0.12, general: 0.33}; P3 {reasoning: 0.55, long_docs: 0.20,
workflow: 0.15, general: 0.10}; P4 {long_docs: 0.50, workflow: 0.25, general: 0.25};
P5 {edu_high: 0.40, verified: 0.40, workflow: 0.20}. The Sonnet worker maps/renames these keys to the
actual spec-02 source names, preserving proportions, and records the mapping in the yaml as comments.

### ava/data.py + scripts/build_dataset.py (Sonnet subtask)
- `scripts/build_dataset.py --preset nano [--phases 0-5]`: reads `data/raw/*.jsonl` (lines:
  `{"text": str, "task_type": "automatic"|"deliberate"|"safety"|"temporal", "concept": str|null,
  "source": str}`), tokenizes with the spec-03 tokenizer, writes per phase:
  - `data/nano/phase{N}.bin` — uint16 little-endian memmap of token ids, docs separated by EOS;
  - `data/nano/phase{N}.idx.json` — `{"doc_offsets": [int,...], "doc_task_type": [str,...],
    "doc_concept_id": [int|null,...]}` where `doc_concept_id` = tokenizer id of the doc's concept word
    (single token; drop concept if multi-token, log count);
  - `data/nano/heldout_phase{N}.bin` + sidecar — first 200_000 tokens per phase drawn from held-out docs
    NEVER in the train bin (split by doc hash, deterministic seed 1234).
  - vocab_size ≤ 65535 asserted (uint16). Idempotent; `--force` to rebuild. Prints per-phase token
    counts; each train bin must contain ≥ the phase's `tokens` budget (oversample sources by repetition
    with a warning if raw data is short).
- `ava/data.py` — `class PhaseSampler:`
  `PhaseSampler(phase: int, seq_len: int, batch_tokens: int, data_dir: str, seed: int, mix: dict)`;
  `sample() -> (input_ids [B,T] int64, targets [B,T] int64, task_type: str, concept_ids [B] int64)`
  with `B = batch_tokens // seq_len`, targets = inputs shifted by 1 (next-token; last target = EOS or
  next doc token — windows are contiguous memmap slices respecting nothing else; doc boundaries only
  matter for task_type/concept attribution: a window's task_type/concept comes from the doc owning its
  first token). Each `sample()` call is SINGLE-task_type; task_types rotate round-robin weighted by the
  phase mix (deterministic given seed). `concept_ids[b] = -1` when absent.
  `state_dict()/load_state_dict()` expose cursor + RNG state for bit-exact resume. Memory: memmap only,
  never load a full bin into RAM.

### ava/jlosses.py
`compute_losses(out: dict, targets, task_type: str, concept_ids, model, j_weight: float, cfg) ->
(total: Tensor, parts: dict[str, float])`. Reuse `MultiJSpaceLosses` (multi_jspace_module.py:159-195)
methods wherever they exist; implement only glue. Exact composition:
```
lm       = F.cross_entropy(logits.view(-1,V), targets.view(-1))
base4    = report*1.0 + broadcast*0.5 + selectivity*0.3 + modulation*0.5      # weights per dolma_config.yaml:106-112
hl       = 0.6*HL(S1) + 0.8*HL(S2) + 1.0*HL(Critic) + 0.7*HL(Planner)        # HL = MultiJSpaceLosses.half_life_loss
                                                                              #   targets from cfg.jspace_half_life (nano: 8/60/30/50)
inter_mi = MultiJSpaceLosses.inter_space_mi_regularizer(ws1, ws2, 0.45)      # :166-171
route_kl = MultiJSpaceLosses.routing_loss(route_probs, task_type)            # :172-181, targets automatic [0.6,0.15,0.1,0.15]
                                                                              #   deliberate [0.15,0.55,0.1,0.2] safety [0.1,0.2,0.6,0.1]
                                                                              #   temporal [0.1,0.3,0.1,0.5] — already in the module
total    = lm + base4*j_weight + hl + inter_mi*0.3 + route_kl*0.4
```
- `report` = `reportability_loss` (:182-185) on the task_type's primary space (automatic→S1,
  deliberate→S2, safety→Critic, temporal→Planner) with `target_concepts=concept_ids`; masked to rows
  where `concept_ids >= 0`, contributes 0.0 (not NaN) if none.
- `broadcast` = `broadcast_loss(b_strength, target)` (:186-187) on the primary space's
  `broadcast_strength`, per-space targets S1 0.18 / S2 0.22 / Critic 0.08(vm-style) / Planner 0.20
  (dolma_config.yaml:114-117; for Critic use MSE(verbalizable_mass, 0.08) instead of broadcast).
- `selectivity` = `selectivity_loss(ws_var, task_type)` (:188-193) with `ws_var =` variance of the
  primary space's workspace slots; `modulation` = `modulation_loss` (:194-195) with sim_with/sim_without
  = cosine(fused_out_row, fused_row) computed with and without broadcast added (cheap second stats pass,
  no second forward: use `out["fused"]` vs `out["fused"] + jspace["broadcast"]`).
- `parts` returns every term as a python float (keys: lm, report, broadcast, selectivity, modulation,
  hl_s1, hl_s2, hl_critic, hl_planner, inter_mi, route_kl, total).

### ava/train.py — CLI `python -m ava.train --preset nano [--device cpu|cuda] [--max-steps N] [--resume] [--branch chat --init CKPT]`
- Single process. `torch.set_num_threads(4)` on cpu. AdamW betas (0.9, 0.95), wd 0.1, grad-clip 1.0
  (`clip_grad_norm_` after accumulation, before step). Grad-accum so each optimizer step consumes
  exactly `step_tokens=8192`. bf16 `torch.autocast` on cuda only; pure fp32 on cpu. NO wandb/network.
- WSD per curriculum yaml: linear warmup 110 steps → 1e-3 flat through 3369 → cosine to 1e-4 at 3662.
  At step 3369 save `runs/base/ava_nano_stable.pt` (same full-checkpoint format as below).
- Phase manager: advances when the phase token budget is consumed; on boundary switches PhaseSampler
  (new seq_len, mix, j_weight) and, entering P4, calls `apply_rope_scaling(model, 32000, 1.2)`
  (model_1b.py:260-264).
- Checkpoint every 250 steps AND at phase boundaries to `runs/<preset>/ckpt_step{N}.pt`:
  `{model, optimizer, step, phase, tokens_seen, rng: {torch, python, numpy}, sampler: sampler.state_dict(),
  cfg_hash}`. `--resume` loads latest, restores ALL of it; resumed run is bit-exact (same losses) vs
  uninterrupted. Keep last 3 rolling + the stable ckpt.
- Metrics: append one JSON line to `runs/<preset>/metrics.jsonl` every 10 steps:
  `{step, phase, lr, lm_loss, j_losses: {<all parts keys>}, route_probs: [4 floats, batch-mean],
  hl_est: {S1,S2,Critic,Planner}, broadcast_strength, verbalizable_mass, tok_s, rss_mb}`
  (hl_est via SingleWorkspace.hl_est(), multi_jspace_module.py:50-52; rss via
  `resource.getrusage(...).ru_maxrss/1024`).
- `--branch chat --init runs/base/ava_nano_stable.pt`: ACTUALLY `model.load_state_dict(ckpt["model"])`
  (fixing the train_1b_deepspeed.py:116-118 no-op; BRANCH_CONFIGS["chat"] pattern at :36), then
  `model.freeze_spaces(["system1","system2"])`, `set_router_bias(model, [0.15,0.25,0.35,0.25])` (spec 04),
  fresh AdamW over `requires_grad` params at lr 2.5e-4 constant (110-step warmup), 3M tokens (366 steps)
  on the branch_chat mix, output `runs/chat/`.

### scripts/bench_throughput.py
`--preset nano --device cpu`: for seq_len in (256, 512, 1024): build model, run 20 warmup + 30 timed
full optimizer steps (real data if built, else random ids), record steady-state tok/s. Write
`runs/bench.json`: `{"tok_s": {"256": x, "512": y, "1024": z}, "weighted_tok_s": w, "budget_tokens": b,
"preset_recommendation": r}` where `w` weights by phase token share, `b = clamp(w*6*3600, 15_000_000,
40_000_000)`, and `r = "nano"` if `b >= 30_000_000` else `"nano_quick"`.

### scripts/smoke_e2e.sh (~5 min wall, `set -euo pipefail`, trap-based teardown)
1. tiny data: `python scripts/gen_all_data.py --seed 1234 --tiny` (or spec-02's documented tiny flag);
2. `python scripts/build_dataset.py --preset nano_quick`; 3. `python -m ava.train --preset nano_quick
--max-steps 200 --device cpu`; 4. mini-eval: `python evals/perplexity.py --ckpt <latest> --phases 0`
if `evals/perplexity.py` exists else echo "SKIP eval (spec 06 pending)"; 5. if `ava/serve_engine.py`
exists (spec 07): `AVA_CKPT=<latest> uvicorn server:app --port 8000 &`, poll,
`curl -sf localhost:8000/health`, else SKIP; 6. teardown
kills the server, prints `SMOKE OK`.

### tests/test_train_smoke.py (uses a 100k-token pre-built slice in tmp dir; build in a session fixture)
- `test_loss_decreases`: 50 steps nano_quick-geometry on the slice; 10-step-window mean lm_loss strictly
  decreasing across all 5 windows (w1>w2>w3>w4>w5); every j_losses part finite and nonzero (report may
  be 0.0 only if the fixture has no concept ids — fixture MUST include concept-tagged docs so it isn't).
- `test_resume_bit_exact`: run to step 30 (checkpoint interval forced to 10 via `--ckpt-every` hidden
  flag or env `AVA_CKPT_EVERY=10`), kill (simulate: stop loop), restart with `--resume`, continue to 50;
  step-50 lm_loss equals the uninterrupted run's within ±1e-4 (same seed).
- `test_metrics_schema`: after any 20-step run, every metrics.jsonl line parses and contains ALL keys
  listed above (recursively for j_losses and hl_est).

## Interfaces
- Consumes: `ava.config.AvaConfig`, `ava.model.build_model/set_router_bias`, `ava.tokenizer` (spec 03),
  `apply_rope_scaling`, `MultiJSpaceLosses`. Produces for spec 06: heldout bins
  `data/nano/heldout_phase{N}.bin(+.idx.json)`, checkpoints `runs/base/ava_nano_stable.pt` /
  `runs/chat/ckpt_step*.pt` (format above), `runs/*/metrics.jsonl`.
- `PhaseSampler` signature above is frozen; spec 06 reuses it for heldout PPL.

## Acceptance criteria (foreman runs, repo root; assumes specs 01-04 + 02/03 done)
1. `python scripts/build_dataset.py --preset nano_quick` → exit 0; `ls data/nano/phase0.bin
   data/nano/heldout_phase0.bin data/nano/phase0.idx.json` all exist; bins are uint16 (size == 2×tokens).
2. `pytest tests/test_train_smoke.py -q` → all pass, < 8 min CPU.
3. `python -m ava.train --preset nano_quick --max-steps 30 --device cpu` → exit 0, creates
   `runs/nano_quick/metrics.jsonl` (≥3 lines) and a `ckpt_step*.pt`; rerun with `--resume --max-steps 40`
   → continues from step 30 (log line states resumed step).
4. `python scripts/bench_throughput.py --preset nano --device cpu` → exit 0, `runs/bench.json` has all
   four top-level keys and 15e6 ≤ budget_tokens ≤ 40e6.
5. `bash scripts/smoke_e2e.sh` → prints `SMOKE OK`, exit 0, ≤ ~6 min.
6. `python -m ava.train --preset nano --branch chat --init runs/base/ava_nano_stable.pt --max-steps 5`
   (after a stable ckpt exists; for acceptance, any full checkpoint renamed into place is fine) → exit 0,
   log confirms `loaded state_dict (N tensors)`, `frozen: system1,system2`, router bias set.
7. `grep -rn "wandb\|huggingface\|requests\." ava/train.py ava/data.py ava/jlosses.py` → no matches.

## Out of scope
- Real eval harness/probes/interventions (spec 06). server.py replacement (separate spec).
- GPU/bf16 execution validation, 8-bit AdamW, grad checkpointing runtime (base1b config only; code paths
  may exist behind flags but are not exercised here). DDP/deepspeed. Editing any blueprint file.
- Full 3662-step nano run (foreman schedules it after acceptance). Committing to git.
