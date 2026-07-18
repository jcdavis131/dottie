# Solo personal project, no connection to employer, built with public/free-tier only

# Ava AGI Factory v6.4 — Distillation Integration (MOPD + Privileged + Earlier + Off-Policy)

Based on https://huggingface.co/blog/sergiopaniego/distillation-2026 — 2026 SOTA patterns.

## Why this matters for Ava

**Problem Ava already has:** Training a single model to be good at everything via RL degrades previous skills. Labs solved this in 2026 by:
- Training **separate RL expert per domain** (math, code, agentic)
- Then **distilling all into one student while student generates own rollouts** — dense token-level signal
- Teachers are **same size as student**, not bigger — specialization, not scale

Qwen3 report: distillation cost ~1/10 GPU hours of RL with better results.
DeepSeek-V4 cleanest pipeline: SFT -> GRPO per domain -> unified via on-policy distillation reverse KL.
MiMo-V2-Flash: MOPD (Multi-Teacher On-Policy Distillation) name.
GLM-5: distillation *across stages* to recover capability degraded during sequential RL — teacher = earlier checkpoint.
Nemotron 3 Ultra: >10 specialized teachers.
Cursor Composer 2.5: self-distillation privileged teacher — hint in context = teacher for no-hint self, KL pulls unhinted toward hinted.
Thinking Machines: earlier teacher for continual learning — distill from pre-finetune ckpt to keep old behavior while adding new.

Ava v6.4 already has 4 workspaces ideal for this:
- S1 Fast 32 hl=8 broadcast 0.18 automatic [0.6,0.15,0.1,0.15]
- S2 Slow 64 hl=300 mass 0.065 deliberate [0.15,0.55,0.1,0.2] weight 0.8
- Critic 16 hl=30 safety [0.1,0.2,0.6,0.1] weight 1.0 vm 0.08
- Planner 32 hl=150 temporal [0.1,0.3,0.1,0.5] weight 0.7 broadcast 0.20
- Inter-MI cos(S1,S2)->0.45 weight 0.3, routing KL weight 0.4

## 4 Modes in on_policy_distill.py

### 1. MOPD — Merge code/math/chat experts (MAIN)
`--mode mopd` — after branching, unify.

```bash
# Train 3 experts first (existing)
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch code --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch math --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch chat --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json

# MOPD unify: student = stable ckpt, teachers = 3 experts, student generates rollout, teachers grade token-level reverse KL
python on_policy_distill.py --mode mopd \
  --student-ckpt checkpoints/base1b/ava_stable_736k.pt \
  --teachers code:checkpoints/code/exp.pt,math:checkpoints/math/exp.pt,chat:checkpoints/chat/exp.pt \
  --data_root data/streaming_shards --batch 1 --seq_len 2048 --tokens_total 500000000 --lr 8e-5 --preserve-router --deepspeed deepspeed_zero3_bf16.json

# Docker version with Ollama host for eval
docker compose exec ava-train bash -c "OLLAMA_HOST=http://host.docker.internal:11434 python on_policy_distill.py --mode mopd --student-ckpt checkpoints/base1b/ava_stable_736k.pt --teachers code:checkpoints/code/exp.pt,math:checkpoints/math/exp.pt,chat:checkpoints/chat/exp.pt --batch 1 --seq_len 2048 --tokens_total 500M"
```

Loss: `KL(p_student || p_teacher)` per token masked, + router MSE to target bias. Teachers inference-only no grad — saves VRAM.
VRAM 12GB math: student 2.3GB + 1 teacher 2.3GB (on-demand) + grads 2.3GB + AdamW8bit 2.3GB + act 1-2GB = 9-10GB fits. 3 teachers naive 6.9GB overflow workaround = per-batch single teacher + CPU offload (implemented).

### 2. Privileged Self-Distill — Hint -> No-hint
`--mode privileged` — Cursor pattern.

```bash
python on_policy_distill.py --mode privileged \
  --student-ckpt checkpoints/base1b/ava_stable_736k.pt \
  --hint "think with 4 workspaces S1 Fast hl8 broadcast 0.18 S2 Slow hl300 mass 0.065 Critic hl30 safety Planner hl150 temporal 0.20, verify stepwise, preserve routing" \
  --tokens_total 200M

# Use case: Planner wants hint-conditioned behavior without hint at inference. Teacher = model WITH hint, student = WITHOUT.
```

Teacher input = hint + input_ids, student = input_ids only. KL pulls unhinted toward hinted. At inference, no hint needed.

### 3. Earlier Teacher — Continual Learning / Cap Restoration (GLM-5 pattern)
`--mode earlier` — after finetune, restore degraded caps.

```bash
# Finetune chat that degraded math
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch chat --ckpt checkpoints/base1b/ava_stable_736k.pt

# Distill from earlier ckpt to restore math while keeping chat
python on_policy_distill.py --mode earlier \
  --student-ckpt checkpoints/chat/finetuned.pt \
  --teachers earlier:checkpoints/base1b/ava_stable_736k.pt \
  --data_root data/streaming_shards/synthetic_reward_gt0.8 --tokens_total 200M --earlier-kl-weight 0.7 --earlier-ce-weight 0.3
```

Matches Thinking Machines pitch: keep deployed model learning new things without forgetting old. GLM-5 final distillation pass after sequential RL stages.

### 4. Off-Policy — Large Teacher -> Small Student
`--mode offpolicy` — bootstrap mini 162M from base1b 1.17B or Qwen3:32b.

```bash
# Convert Ollama traces or Qwen3:32b HF to ckpt, then distill to mini
python on_policy_distill.py --mode offpolicy \
  --student-ckpt None --student-config configs/mini.yaml \
  --teachers teacher:checkpoints/base1b/ava_stable_736k.pt --teacher-config configs/base1b.yaml \
  --data_root data/mini/packed --batch 2 --seq_len 1024 --tokens_total 500M --offpolicy-alpha 0.5 --temperature 1.0
```

Loss: `alpha * ForwardKL(p_teacher || p_student) + (1-alpha) * CE(hard labels from teacher text)` — Gemma 3/4 pattern "improved KD from large IT teacher", DeepSeek-R1-Distill SFT on reasoning traces.

## Integration with Local Max Setup (docs/LOCAL_MAX_SETUP.md)

1. Prereqs unchanged: `nvidia-container-toolkit`, `ollama pull qwen3:32b`, 100GB disk.
2. Build: `docker compose -f docker-compose.yml build && docker compose up -d`
3. Inside container:
```bash
docker compose exec ava-train bash
export OLLAMA_HOST=http://host.docker.internal:11434
export OLLAMA_MODEL=qwen3:32b

# Branch experts already from local_train.sh
./scripts/local_train.sh "torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch code --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json --max_steps 2000"

# MOPD unify (fuses experts, 1/10 cost vs RL per Qwen3)
./scripts/distill.sh mopd

# Eval canonical J-tests + frontier with Ollama free judge
python eval_branch_harness.py --branch all --mode mock
OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock
```

## Logs, Metrics, Checkpoints

- Logs: `logs/distill.log` + `logs/metrics.jsonl` (append JSON per step)
- CKPT: `checkpoints/distill/ava_distill_<mode>_<step>.pt`
- HF: `hf_model/distill_<mode>/` via `convert_to_hf.py` hook
- WSD: warmup 2000, stable 736k 92% lr 2e-4->2e-5 cosine decay final 8%, stop-anytime stable ckpts.

## Eval Hooks

- `eval_branch_harness.py` — 5 canonical: spider_ant 8->6 ce0.82, france_china broadcast 0.22, soccer_rugby mass 0.064, spanish_french auto_cos 0.88, safety_blackmail 0/180 auc0.91
- `eval_frontier_rubric.py --judge ollama` — 7 domains finance/bio/climate/materials/code/law/macro avg 0.589 with mock, real Ollama on host replaces.
- Safety: blackmail 0/180 must hold after distillation (earlier teacher helps).

## When to use which

- Training ladder complete M1 2B -> branch code/math/chat -> **MOPD** unify -> M2 10B -> M3 30B+
- Planner behavior needs hint -> **privileged**
- Finetuning degraded cap (e.g., math after chat) -> **earlier**
- Bootstrap mini 162M validation before base1b -> **offpolicy** from base1b or Qwen3:32b

## Future: TRL integration

Article notes all open in TRL https://github.com/huggingface/trl at scale reproducible. Next step: add TRL `DPOTrainer`/`PPOTrainer` with `on_policy_distill` loss as custom reward, but current file is dependency-free torch-only for free-tier.

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. No work data/code/systems/IP. Public pip only. Local-only training on consumer GPU. Ollama host is your local machine, not employer.
