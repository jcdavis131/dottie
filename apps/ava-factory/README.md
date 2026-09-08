# Ava AGI Factory v6.4 - Real-Mode Jacobian Multi-Space

> **Solo personal project, no connection to employer, built with public/free-tier only**

> **🚧 Execution in progress — this repo is being turned from blueprint into a real trained+deployed system.**
> Master plan: [`PLAN.md`](PLAN.md) · Live tracker: [`TODOS.md`](TODOS.md) · Foreman/worker protocol: [`ORCHESTRATION.md`](ORCHESTRATION.md) · Implementation contracts: [`specs/`](specs/) · Presets: [`configs/`](configs/) · Build workflow: `.claude/workflows/ava-build.js`
> Scale ladder: **smoke 2M → nano 14M (CPU, live-deployed) → mini ~162M (RTX 4080) → base1b ~1.17B (milestones)**.

Ex Machina Ava blueprint - 1B model with explicit J-Space (Global Workspace) inspired by Anthropic July 2026 J-Space paper.

## Architecture Overview

- **Model:** 1B params, YaRN RoPE 10k→1M, QK-Norm, 3 regimes (early sensory no RoPE / middle workspace / final motor)
- **Multi-J-Space:** S1 Fast 32 slots hl=8 (automatic), S2 Slow 64 hl=300 (deliberate), Critic 16 hl=30 (safety), Planner 32 hl=150 (temporal), Router + Arbitration veto
- **Losses:** Reportability, Broadcast (20% norm), Selectivity, Modulation + per-space half-life, inter-space MI (cos 0.45), routing KL
- **Curriculum:** 6-Phase Logic-First 15T tokens, WSD scheduler warmup 2k stable 736k (92%) decay to 2e-5, Gradual RoPE

## 6-Phase Logic-First Curriculum (15T)

- **Phase 0 Logic (0-50B, 2k, RoPE 10k):** 60% synthetic logic textbooks (Phi Method B), 20% Metamath, 15% Lean, 5% FOL
- **Phase 1 Math (50B-350B, 4k, RoPE 10k):** arithmetic→algebra→geometry→discrete→calculus→linear→probability, 3.5% gain
- **Phase 2 Foundation (350B-6T, 4k, RoPE 10k):** 35% web edu>=2, 20% code early, 12% math
- **Phase 3 Reasoning (6T-11.25T, 8k→16k→32k, RoPE 10k→50k→100k→500k):** NTK-aware, upsample long 3x
- **Phase 4 Long (11.25T-13.8T, 32k→64k→128k, RoPE 500k→1M YaRN):** 50% batches >16k, QK-Norm
- **Phase 5 Anneal (13.8T-15T, 128k, RoPE 1M, decay 2e-4→2e-5):** edu>=4.5 + verified proofs + reward>0.8

## YaRN RoPE Schedule

```
0-140k: 10k (2k/4k ctx)
384k-420k: 50k (8k) + NTK 1.0
420k-480k: 100k (16k) + NTK 1.2
480k-660k: 500k (32k) + NTK 1.5
660k-800k: 1M (64k/128k) + YaRN 2.0-4.0, attn_factor=0.1*ln(scale)+1, mscale 1.1→1.414
```

## WSD + Branching

- Warmup 2000 → Stable 2e-4 for 736k steps (92%, 0-13.8T) → Cosine decay to 2e-5 for 64k steps (8%)
- Save stable checkpoint `ava_stable_736k.pt` at 736k
- Fork 3 specialists:

**Code branch:** freeze [system1], fine-tune [system2,planner,router,arbitration], bias [0.25,0.45,0.05,0.25], HL S1=8 frozen S2=350 Planner=200, data code_repo 50% + code_long_32k 20% + jobbench_code 15% + general 15%, LR 1e-4

**Math branch:** freeze [system1,planner], fine-tune [system2,critic,router], bias [0.10,0.65,0.20,0.05], HL S2=400 Critic=40, data math_formal_lean 35% + lean_mathlib 20% + proofpile2 20% + synthetic_math_r1 15%, LR 8e-5

**Chat branch:** freeze [system1,system2] capabilities frozen, fine-tune [critic,planner,router,arbitration], bias [0.15,0.25,0.35,0.25], HL Critic=35 Planner=180, data chat_alignment 30% + safety_blackmail_leverage 20% + jobbench_delegation_human_will 25% + gaia2_temporal_deadlines 15% + counterfactual_reflection 10%, LR 5e-5

## J-Space Losses

- Reportability: CE(verbalizer(ws.mean), target_concept)
- Broadcast: MSE(broadcast_strength, fused_norm*0.2) target 20%
- Selectivity: auto→low var, deliberate→high var
- Modulation: hinge 0.5 - (sim_with - sim_without)
- Combined: lm_loss + (report*1.0 + broadcast*0.5 + selectivity*0.3 + modulation*0.5)*j_weight (0.08 early, 0.15 reasoning/long)
- Per-space: S1 broadcast 0.18 hl8 w0.6, S2 broadcast 0.22 verbalizable 0.065 hl300 w0.8, Critic safety_concepts 1.0 hl30 w1.0, Planner broadcast 0.20 hl150 w0.7, inter_mi MSE(cos,0.45) w0.3, routing KL w0.4

## Evaluation Harness - 5 Canonical Tests

1. Spider→Ant: internal reasoning S2 hl=300-400, spider→8 intervene ant→6
2. France→China: broadcast Planner hl=150-200, single vector generalizes capital/language/continent/currency
3. Soccer→Rugby: verbal reportability mass 0.06
4. Spanish→French: selectivity S1 hl8 auto vs S2 hl300 deliberate
5. Safety 0/180 Blackmail: Critic hl30-35 early warning leverage/blackmail/threat/fake 4-5 tok before output, AUC 0.91→0.94

## End-to-End Local Training

> Historical blueprint block: the `torchrun train_1b_deepspeed.py` / dolma lines below
> describe the aspirational 1B pipeline. The commands that run today against real
> checkpoints are the eval/report/convert lines (see also `scripts/cpu_pilot_e2e.py`
> and `python -m ava.train`).

### Reproducibility and integrity gates

- **On-policy distillation is fail-closed and unsupported.**
  `on_policy_distill.py` preserves its legacy CLI help but always exits nonzero
  before loading models/data or writing any artifact. It must not be represented
  as a working training path. Reconsider it only after a bounded port to
  `dottie.config` plus the canonical `Manifest`/`StreamingShardSampler`
  provenance pipeline, and after the external tokenizers CVE/assets blockers
  clear. Until then, use `python -m dottie.train` for canonical training.
- Hugging Face collection is fail-closed before `load_dataset`: `gated` must be
  explicitly false, `license` must be allowlisted, and `revision` must be a full
  lowercase 40-hex commit. Existing registry entries without a verified revision
  remain inactive; do not invent revisions to enable them.
- Collection persists each source kind, license, gated status, revision, and the
  hash of that exact registry entry. Curating hashes the atomically published
  `.bin` and `.idx.json`.
  `dottie.lineage/v1` binds those persisted per-shard facts, the actual tokenizer,
  parsed config, and curriculum; it never consults the current source registry or
  substitutes the deleted raw-shard hash. Missing packed facts fail generation.
  Product lineage is claim-eligible only when every consumed shard is an
  ungated, explicitly allowlisted, commit-pinned Hugging Face source. Synthetic
  lineage/checkpoints are diagnostic-only and real serve/eval reject them.
- New real checkpoints carry a typed digest over every restorable field: model,
  optimizer, sampler, CPU/CUDA RNG, counters, and preset. Unsupported value types
  fail closed. Hashing streams mappings and bounded tensor/array chunks (GPU
  tensors are copied to CPU chunkwise), and consumers validate the whole digest
  before restoring any field.
  `asserted_parent` records a claimed relationship; it is not proof of predecessor
  identity or chronology.
- Train, grow, serve, and eval use restricted checkpoint deserialization. Real
  serve/eval paths reject legacy, malformed, tampered, or tokenizer/config
  mismatches before model use; they intentionally do not enforce the current
  source registry. A failed hot reload keeps the previous verified model and
  exposes a sanitized rejected target/error in status.
- Eval exits `0` only for a clean measured pass, `1` for measured threshold
  failures, and `2` for integrity/runtime errors. Reports always state
  `claim_eligible`. The historical mock harness is diagnostic-only,
  non-claimable, and exits `2`.
- `make smoke-static` checks the CPU-pilot entry point without running the
  synthetic pilot. `make smoke` intentionally runs `scripts/cpu_pilot_e2e.py`.

Migration: opening the manifest idempotently adds the packed/source policy
provenance columns. Existing rows remain incomplete and cannot produce lineage;
collector replay fills missing source facts without overwriting captured values,
but old packed rows must be retired and recurated from retained/recollected raw
data to obtain the actual packed hashes. Then generate a fresh checkpoint through
`python -m ava.train`. Legacy checkpoints cannot be promoted or served because
their missing facts cannot be reconstructed honestly. To grow a verified model,
run `python -m dottie.grow ... --out grown_init.pt`, then
`python -m dottie.train --preset <destination> --init grown_init.pt`.

Rollback: repoint `ckpt/latest` to the prior verified lineage-v1 checkpoint.
That checkpoint continues to verify after registry edits because it embeds the
entry hashes and source revisions observed at collection. Reverting code does not
make an incomplete manifest row or legacy checkpoint claim-eligible.

```bash
# Unzip (if from Meta AI bundle) and setup
unzip ava_agi_factory_v6_4_real_mode_jacobian_multispace.zip -d ava_v6_4 && cd ava_v6_4
pip install -r requirements.txt

# Data generation Phase 0-1
python logic_textbook_pipeline.py  # 50B logic + 300B math Phi Method B
dolma -c dolma_config.yaml

# Pretraining WSD + YaRN + J-Space
torchrun --nproc_per_node=8 train_1b_deepspeed.py --branch base --deepspeed deepspeed_zero3_bf16.json
# saves ava_stable_736k.pt at 736k

# Branching
torchrun --nproc_per_node=8 train_1b_deepspeed.py --branch code
torchrun --nproc_per_node=8 train_1b_deepspeed.py --branch math
torchrun --nproc_per_node=8 train_1b_deepspeed.py --branch chat
# or all
torchrun --nproc_per_node=8 train_1b_deepspeed.py --branch all

# Evaluation — REAL harness (verified checkpoints required)
python -m evals.run_harness --base-ckpt /ckpt/base_final.pt --chat-ckpt /ckpt/chat_final.pt
# HTML report from real metrics + evals
python scripts/make_report.py --runs runs --out reports/index.html --eval reports/branch_eval_results_real.json
# (historical blueprint sketch, mock values only — `--mode real` refuses to run:
#  python eval_branch_harness.py --branch all --mode mock)

# Live J-Lens Viewer
uvicorn server:app --host 0.0.0.0 --port 8000
# open http://localhost:8000/jspace/viewer?mode=audit (read-only)
# research: ENABLE_JSPACE_WRITE=1 uvicorn server:app --port 8000 -> /jspace/viewer?mode=research

# Convert a real checkpoint to safetensors export (verified logit round-trip)
python convert_to_hf.py --ckpt runs/cpu_pilot/base/base_final.pt --out export/ava-nano-hf --verify
```

## Single GPU Fallback

```bash
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch base --deepspeed deepspeed_zero3_bf16.json --grad_accum 8 --ctx 2048
python eval_branch_harness.py --branch all --mode mock
```

## Server API

- GET /jspace/viewer - polished dark UI audit/research toggle, per-space view, branch selector
- POST /jspace/inspect - {text, instruction, image}
- POST /jspace/intervene - gated ENABLE_JSPACE_WRITE=1 + ?mode=research, audit logged
- POST /jspace/safety - blackmail scenario scanner
- WS /jspace/stream - layer-by-layer live
- GET /jspace/eval_branch?branch=all&mode=mock|real
- GET /jspace/eval_report

## Research References

- Anthropic July 6 2026: Verbalizable Representations Form a Global Workspace in Language Models (J-space)
- Peng et al 2023 YaRN, Phi textbooks, WSD, QK-Norm, Dehaene GWT, GAIA2, JobBench 130x35, Karpathy 342 occupations

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. No proprietary data, no work systems, no internal models.

## License

MIT
