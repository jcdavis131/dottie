# LOCAL PICKUP — Alienware RTX 4090
Solo personal project, no connection to employer, built with public/free-tier only

> You can clone this repo on your Alienware and go from 0 → data loop → streaming train → MOPD distill → eval in one session.

## Prerequisites (Alienware)

- **Host:** Windows 11 WSL2 Ubuntu 22.04 + NVIDIA driver >=555.xx
- **Docker Desktop:** with WSL2 + nvidia-container-toolkit
  ```bash
  wsl --update
  docker --version
  nvidia-smi
  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
  ```
- **Ollama on host (for free judging):**
  ```bash
  ollama serve &
  ollama pull qwen3:32b          # primary judge ~19GB
  ollama pull deepseek-r1:32b    # optional reasoning
  curl http://localhost:11434/api/tags
  ```
- **HF token (personal, not work):**
  - Create at https://huggingface.co/settings/tokens → fine-grained → repo write to `jcdavis131/ava-textbook-v6`
  - `export HF_TOKEN=hf_...` and `export HUGGINGFACE_HUB_TOKEN=$HF_TOKEN`

## Clone + First Check

```bash
git clone https://github.com/jcdavis131/ava-agi-factory-v6-4.git
cd ava-agi-factory-v6-4

# quick e2e mock — no GPU, no token needed
chmod +x scripts/e2e_test.sh
./scripts/e2e_test.sh 2>&1 | tee logs/e2e_test_$(date +%Y%m%d).log
# expect: 10/10 PASS in mock mode, manifests in data/for_upload/
```

The e2e test does:
1. py_compile all modules
2. dataset_expansion 1M dry-run
3. dataset_discovery
4. hf_uploader dry-run
5. gdrive_uploader guard check (blocks work Drive camd@meta.com)
6. streaming_data import
7. eval_branch_harness mock + frontier mock
8. prefect_flows data/eval/vector mock
9. distill import

## 2-Loop Architecture

```
Loop 1 — Data (every 4h): [Gather Phi-B synthetic p0-p3] → [Curate dedup simhash + quality reward>0.8] → [Split 92/6/2] → [Parquet shards sha12] → PUSH HF Hub jcdavis131/ava-textbook-v6

Loop 2 — Model (weekly / on-demand): [Stream HF via datasets streaming=True] → [DeepSpeed Zero3 bf16 8-bit Adam + checkpointing] → [WSD 736k stable 2e-4→2e-5] → [Branches code/math/chat] → [Eval Ollama qwen3:32b] → [MOPD distill]

Both loops observable via Prefect UI localhost:4200 and logs/your_files/
```

### Why HF Hub vs GDrive?

- **GDrive:** Work Drive connected in Hatch VM is **camd@meta.com** with health.json → **BLOCKED** per AGENTS.md Home/Work absolute separation. `scripts/gdrive_uploader.py --check` aborts if work indicators. Personal Drive jcdavis131@gmail.com would work but HF is better for streaming.
- **HF:** private dataset, versioned, `load_dataset(..., streaming=True)`, parquet sharded, no local 100GB download, free-tier, public pip only.

## Loop 1 — Real Data Expansion (Alienware)

```bash
# Build & start container
./scripts/local_train.sh   # builds ava-agi-factory:2.4.0-cuda12.4 if first time (10-20min)

# Inside container or via wrapper — generate 10M tokens this run (~50k docs, 60M/day if 4h cron)
./scripts/local_train.sh python scripts/dataset_expansion.py \
  --tokens 10M \
  --phases p0_logic p1_math p2_foundation p3_code \
  --out data/daily_expanded \
  --upload-mode local

# Check output
ls -lh data/daily_expanded/ | tail
cat data/daily_expanded/manifest_*.jsonl | head
cat data/for_upload/upload_manifest_*.json | jq

# Optional R2 upload (free-tier, Home-safe)
# export CLOUDFLARE_R2_ACCESS_KEY=... R2_SECRET_KEY=... R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com R2_BUCKET=ava-datasets
# ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 10M --upload-mode r2
```

**Efficient downstream format:** `packed_{ts}_{idx}_{rand}.jsonl.gz` 50MB gzipped, content-addressable short sha12 = first 12 of sha256, append-only `manifest.jsonl` and global `data/manifest.jsonl` with tokens_est, phase, timestamp, version.

## HF Upload + Streaming Train

```bash
# Push cleaned train/val/test to private HF dataset
HF_TOKEN=hf_... ./scripts/local_train.sh python scripts/hf_uploader.py \
  --repo jcdavis131/ava-textbook-v6 \
  --manifest "data/daily_expanded/manifest_*.jsonl" \
  --private --push

# Verify on HF: https://huggingface.co/datasets/jcdavis131/ava-textbook-v6

# Stream directly in training (no local download)
./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py \
  --preset mini \
  --data-source hf://jcdavis131/ava-textbook-v6 \
  --streaming \
  --tokens_total 2500000000 \
  --deepspeed deepspeed_zero3_bf16.json \
  --compile --resume-if-exists

# Nano smoke 14M for 2h test
./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset nano --tokens_total 500000000

# Monitor
tail -f logs/mini/train.log
cat checkpoints/mini/metrics.jsonl | tail -20
```

**Streaming code snippet (already in streaming_data.py fallback):**
```python
from datasets import load_dataset
ds = load_dataset("jcdavis131/ava-textbook-v6", streaming=True, split="train")
for ex in ds.shuffle(buffer_size=10_000):
    print(ex["text"][:200])
```

## Discovery — Additional Data Sources (fixes "only one data source")

```bash
# Reads frontier_eval_results.json weak domains → proposes HF datasets
python3 scripts/dataset_discovery.py --domains finance bio code math safety --out your_files/ava-agi/dataset_discovery/

cat data/discovery/needs.json
cat your_files/ava-agi/dataset_discovery/candidates_*.json | grep -A2 license_ok | head

# Download script for Alienware (does NOT auto-download TBs in Hatch VM)
bash your_files/ava-agi/dataset_discovery/download_candidates_*.sh

# Example candidates (58 in test): financial_phrasebank, convfinqa, finqa, pubmed_qa, medmcqa, the_stack, code_search_net, metamath-qa, gsm8k, open-web-math
# Filter license_ok:true = MIT/Apache2/CC0/CC-BY
```

## Loop 2 — Model + Eval + Distill MOPD

```bash
# Eval free SOTA judge
OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b \
./scripts/local_train.sh python eval_frontier_rubric.py --domain all --judge ollama --mode mock

./scripts/local_train.sh python eval_branch_harness.py --branch all --mode mock
# real with ckpt
./scripts/local_train.sh python eval_branch_harness.py --branch chat --ckpt checkpoints/mini/ava_stable_mini.pt --mode real

# Distillation — Multi-Teacher On-Policy Distillation (MOPD) per https://huggingface.co/blog/sergiopaniego/distillation-2026
# Train 3 experts then merge
./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch code --ckpt checkpoints/base1b/ava_stable_736k.pt
./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch math
# Then MOPD: student generates own rollouts, teachers grade every token reverse KL KL(p_student||p_teacher) ~1/10 GPU hours vs RL (Qwen3)
./scripts/distill.sh torchrun --nproc_per_node=1 on_policy_distill.py \
  --mode mopd \
  --teachers checkpoints/code_expert.pt checkpoints/math_expert.pt checkpoints/chat_expert.pt \
  --student-ckpt checkpoints/base1b/ava_stable_736k.pt \
  --tokens_total 100M --preserve-router

# Privileged hint self-distill (Cursor Composer 2.5 pattern)
./scripts/distill.sh python on_policy_distill.py --mode privileged --hint "think with 4 workspaces S1 Fast hl8 S2 Slow hl300 Critic hl30 Planner hl150"

# Earlier-teacher continual learning (Thinking Machines)
./scripts/distill.sh python on_policy_distill.py --mode earlier --earlier-ckpt checkpoints/base1b/ava_stable_736k.pt --student-ckpt checkpoints/math/math_final.pt
```

## Continuous Pipelines — Crontab for Alienware

```cron
# Ava expansion 10M every 4h (60M/day)
0 */4 * * * cd ~/ava-agi-factory-v6-4 && ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math p2_foundation p3_code --out data/daily_expanded --upload-mode local >> logs/cron-expansion.log 2>&1

# HF push hourly if new shards + token set
30 */4 * * * cd ~/ava-agi-factory-v6-4 && HF_TOKEN=hf_... python scripts/hf_uploader.py --repo jcdavis131/ava-textbook-v6 --manifest "data/daily_expanded/manifest_*.jsonl" --private --push >> logs/cron-hf.log 2>&1

# Discovery daily 9am Central
0 9 * * * cd ~/ava-agi-factory-v6-4 && python3 scripts/dataset_discovery.py --domains finance bio code math safety >> logs/cron-discovery.log 2>&1

# Train weekly Sun 3am, streaming from HF
0 3 * * 0 cd ~/ava-agi-factory-v6-4 && ./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --data-source hf://jcdavis131/ava-textbook-v6 --streaming --tokens_total 2500000000 --resume-if-exists >> logs/cron-train.log 2>&1

# Eval daily 3am
0 3 * * * cd ~/ava-agi-factory-v6-4 && OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b ./scripts/local_train.sh python eval_frontier_rubric.py --domain all --judge ollama >> logs/cron-eval.log 2>&1

# Vector dumb models daily 6am
0 6 * * * cd ~/ava-agi-factory-v6-4 && python3 prefect_flows.py --run vector --leagues all >> logs/cron-vector.log 2>&1
```

Hatch VM crons already created: `ava-data-gather-daily` interval@4h, `ava-dataset-discovery-daily` daily 10:00 UTC, `vector-dumb-models-daily` 12:00 UTC, `ava-eval-distill-daily` 09:00 UTC, `ava-training-weekly` Sun 03:00 UTC.

## Prefect UI (Free Self-Host)

```bash
pip install prefect==3.4.0
prefect server start --port 4200 &
# http://localhost:4200

python prefect_flows.py --run data --preset nano
python prefect_flows.py --run eval --domains all
python prefect_flows.py --run all --preset mini

# Deployments (optional alternative to cron)
prefect deployment build prefect_flows.py:ava_data_gen_flow -n daily --cron "0 6 * * *" --apply
prefect deployment build prefect_flows.py:ava_train_flow -n weekly --cron "0 3 * * 0" --apply
prefect agent start -q default
```

## Troubleshooting

- **Flash-attn build fail in Docker:** fallback to torch SDPA (Dockerfile has `|| echo fallback`) — ok for testing, slower 30%
- **Ollama not reachable from container:** check `extra_hosts: host.docker.internal:host-gateway` in docker-compose.yml, `export OLLAMA_HOST=http://host.docker.internal:11434`
- **Hatch VM no GPU:** expected — e2e_test.sh mock mode PASS is fine, real train only on Alienware
- **Work Drive guard blocks GDrive upload:** In Hatch VM, Drive is work camd@meta.com (detected via gchak_health.json) → blocked per AGENTS.md. Use personal Drive jcdavis131@gmail.com or R2 or HF. On Alienware, set `GOOGLE_DRIVE_PERSONAL_CONNECTED=1` after connecting personal.
- **HF push 403:** token needs `write` to dataset repo, make repo private first
- **Disk 100GB needed:** `df -h` — clean `data/daily/raw` old, keep `packed` + `manifest.jsonl`

## Repo Layout

- `scripts/dataset_expansion.py` — 10M incremental shards, dedup threshold 3, quality alpha>0.6, content-addressable sha12
- `scripts/dataset_discovery.py` — weak domain → HF candidates search
- `scripts/gdrive_uploader.py` — efficient GDrive with work guard
- `scripts/hf_uploader.py` — push_to_hub train/val/test + streaming example
- `scripts/e2e_test.sh` — end-to-end mock test
- `prefect_flows.py` — flows with `push_to_hf_task` + retries
- `on_policy_distill.py` — MOPD reverse KL + privileged + earlier
- `docker/Dockerfile` — pytorch:2.4.0-cuda12.4 + datasets[parquet], hf_transfer, prefect
- `docs/CONTINUOUS_PIPELINES.md` — full cron + deployment details
- `docs/LOCAL_PICKUP.md` — this file

## Solo Disclaimer

All pipelines: public pip only, free-tier R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, local Ollama qwen3:32b. No work data/code/systems. Footer on every artifact: "Solo personal project, no connection to employer, built with public/free-tier only"
