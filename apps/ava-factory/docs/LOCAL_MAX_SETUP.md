Solo personal project, no connection to employer, built with public/free-tier only

# Ava AGI Factory v6.4 — LOCAL MAX SETUP (RTX 4080/4090 + Docker + Ollama)

**Goal:** Reach maximum potential of Ava 1B on YOUR machine with Docker + NVIDIA + Ollama (free SOTA judging) + WSD stop-anytime checkpoints.

**Target:** RTX 4090 24GB (2-3x base1b throughput) OR RTX 4080 Laptop 12GB (reference). 100GB+ free disk, 32GB RAM recommended.

---

## 1. Prereqs

### Hardware check
```bash
nvidia-smi
# expect driver >= 555.xx, 12GB+ VRAM, CUDA 12.x

# VRAM size
nvidia-smi --query-gpu=name,memory.total --format=csv

# CPU RAM + disk
free -h
df -h  # need >=100GB free on native Linux ext4 or WSL2 ext4, NOT /mnt/c (5-10x slower IO)
```

### Software
- Docker Engine 24+ with `nvidia-container-toolkit`:
```bash
# Ubuntu / WSL2 Ubuntu 24.04
sudo apt update && sudo apt install -y docker.io docker-buildx-plugin
# NVIDIA toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

- Ollama installed on HOST (not container):
```bash
# Linux/WSL host
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull qwen3:32b              # balanced SOTA judge, 24GB Q4
ollama pull deepseek-r1:32b        # reasoning judge
ollama pull llama3.3:70b           # generalist (40GB Q4, needs 24GB+ VRAM+RAM)
ollama pull qwen2.5-coder:32b      # coding judge
ollama pull glm4:9b-chat           # small GLM that DOES fit Ollama vs 753B GLM-5.2 needing 241GB
ollama list
curl http://localhost:11434/api/tags | jq
```

- **GLM-5.2 753B reality check:**
  - MIT open weights, 1M context, but even 2-bit quantized = 241–280GB RAM+VRAM (per Unsloth docs). Cannot fit Ollama on consumer hardware.
  - Cheap paths: Z.ai API $1.40/M in $4.40/M out cached $0.26/M, or Coding Plan Lite $18/mo 400 prompts/week ~$12.60 annual. Use `Glm52Judge` if you buy that, else use local Ollama free.

### Repo clone
```bash
git clone <your-fork> ava-agi-factory-v6-4
cd ava-agi-factory-v6-4
ls configs/mini.yaml configs/base1b.yaml
pip install -r requirements.txt  # host only for quick eval_frontier_rubric mock
python eval_frontier_rubric.py --domain finance --judge mock --mode mock
```

---

## 2. Docker build — max throughput + Ollama host link

### Dockerfile (saved as `docker/Dockerfile`)

```dockerfile
# Solo personal project, no connection to employer, built with public/free-tier only
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV WANDB_MODE=offline
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
ENV OLLAMA_HOST=http://host.docker.internal:11434

RUN apt-get update && apt-get install -y --no-install-recommends \
    git git-lfs build-essential curl tmux htop nvtop \
    python3-dev libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt

# Core deps + SOTA local free stack
RUN pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cu124 && \
    pip install -r requirements.txt && \
    pip install bitsandbytes>=0.43.0 einops accelerate safetensors tiktoken chonkie \
    ninja packaging wheel && \
    # optional flash-attn (fragile, fallback to SDPA) — comment out on 4080 Laptop if build fails
    pip install flash-attn --no-build-isolation || echo "flash-attn build failed, will use torch SDPA"

# Copy repo (for layer caching, code changes not invalidating pip layer)
COPY . /workspace

# Expose training + serving
EXPOSE 8000
CMD ["/bin/bash"]
```

### docker-compose.yml (repo root)

```yaml
# Solo personal project, no connection to employer, built with public/free-tier only
version: "3.8"
services:
  ava-train:
    build:
      context: .
      dockerfile: docker/Dockerfile
    image: ava-agi-factory:2.4.0-cuda12.4
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - WANDB_MODE=offline
      - PYTHONUNBUFFERED=1
      - OLLAMA_HOST=http://host.docker.internal:11434
      - OLLAMA_MODEL=qwen3:32b
      - GLM_MODEL=glm-5.2[1m]
      - HF_HUB_OFFLINE=0
      - TOKENIZERS_PARALLELISM=false
    volumes:
      - .:/workspace
      - ./checkpoints:/workspace/checkpoints
      - ./data:/workspace/data
      - ./logs:/workspace/logs
      - ./wandb:/workspace/wandb
    ports:
      - "8000:8000"
    stdin_open: true
    tty: true
    extra_hosts:
      - "host.docker.internal:host-gateway"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    command: bash -c "sleep infinity"

  # optional: if you want ollama inside compose instead of host (user already has host ollama, so this is alternative)
  # ollama:
  #   image: ollama/ollama:latest
  #   runtime: nvidia
  #   ports:
  #     - "11434:11434"
  #   volumes:
  #     - ollama:/root/.ollama
  # volumes:
  #   ollama:
```

### Host Ollama from Docker trick

Inside container, `host.docker.internal:11434` points to your host Ollama.

```bash
# inside ava-train container
curl http://host.docker.internal:11434/api/tags
OLLAMA_HOST=http://host.docker.internal:11434 ollama list || curl trick above for host
```

Build:

```bash
docker compose build --progress=plain
docker compose up -d
docker exec -it ava-agi-factory-ava-train-1 bash
# inside:
nvidia-smi
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# expect True + RTX 4080/4090
```

### WSL2 quirks (if on Alienware m16 WSL2)

1. `nvidia-smi` inside WSL reports Windows driver view; trust `torch.cuda.memory_allocated()`.
2. libcuda lives at `/usr/lib/wsl/lib`; never `apt install nvidia-driver-*` inside WSL.
3. If OOM near 12GB or stutter: disable Win11 Hardware-accelerated GPU scheduling, close Chrome, set `~/.wslconfig`:
```
[wsl2]
memory=24GB
swap=16GB
processors=12
```
4. Docker volumes in WSL ext4 not `/mnt/c` — IO 5-10x difference.
5. Thermal throttling check: `nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm --format=csv -l 5` and `nvidia-smi -q -d PERFORMANCE` — if SW Thermal Slowdown, `sudo nvidia-smi -pl 120` (100-140W range) costs 10-20% tok/s but stable.

---

## 3. Data generation — from smoke to 15T

All inside docker container `ava-train`:

```bash
# tokenizer (shared mini/base1b)
python -c "from streaming_data import build_tokenizer; build_tokenizer('data/mini/tokenizer/ava_bpe_32k.json')"
ls data/mini/tokenizer/ava_bpe_32k.json

# Phase 0-1 synthetic logic + math (Phi Method B)
python logic_textbook_pipeline.py --phases p0_logic p1_math --out data/mini/raw --tokens 500M --seed 1234

# Pack to streaming shards (webdataset + packed)
python -m streaming_data pack --in data/mini/raw --out data/mini/packed --seq 1024 --tokenizer data/mini/tokenizer/ava_bpe_32k.json

# For base1b scale:
python logic_textbook_pipeline.py --phases p0_logic p1_math p2_foundation --out data/base1b/raw --tokens 2B --seq 2048
python -m streaming_data pack --in data/base1b/raw --out data/base1b/packed --seq 2048

# Dolma + Nemo Curator pipeline (edu>=2 filter)
dolma -c dolma_config.yaml  # outputs to data/base1b/raw/dolma
python nemo_curator_pipeline.yaml || python -m nemo_curator_pipeline --config nemo_curator_pipeline.yaml

# Holdout
ls data/*/packed/*.tar | head
# minimal smoke 2B tokens for M1, full 15T is multi-week crawl + NeMo filter — WSD lets you stop anytime
```

**Progression:**
- Smoke: 50M tokens nano (CPU)
- Mini 2.5B (3-5 days)
- M1 2B (logic+math) ~3 weeks on 12GB, ~1 week on 4090 24GB
- M2 10B (foundation) ~2 months 12GB / 3-4 weeks 24GB
- M3 30B+ (reasoning/long/anneal) incremental.

---

## 4. Training ladder to max potential

### Formulae (honest arithmetic)

- Params `P ≈ V·d (tied embed) + L·(attn + mlp) + verbalizer + Σslots·d`
- FLOPs/token `≈ 6P × 3` (×3 covers attention ctx≥512 + Multi-JSpace aux losses + recompute)
- Time `= token_budget / tok_s`

**mini — 162M — 2.5B tokens — GO/NO-GO gate:**

- Embed 32000×768=24.6M; per-layer 4d² attn + 12d² SwiGLU 4x ≈ 9.4M ×12=113M; untied verbalizer 24.6M; slots 144×768≈0.1M → P≈162M
- FLOPs/token ≈ 6×1.6e8×3 ≈ 2.9e9
- 25-40 TFLOPS effective bf16 on 4080/4090 → 6-10k tok/s → 2.5B / 8k ≈ 312k sec ≈ 3.6 days (3-5d range)
- VRAM ~5-7GB @ctx512 mb16 — fits 12GB no checkpointing

```bash
# mini full
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --deepspeed deepspeed_zero3_bf16.json --tokens_total 2500000000
# resume
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --resume --deepspeed deepspeed_zero3_bf16.json
```

Gate mini:
```bash
python eval_branch_harness.py --branch all --mode mock
python eval_frontier_rubric.py --domain all --judge ollama --mode mock
# OLLAMA_HOST must be host.docker.internal:11434 inside container
OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain finance --judge ollama
```

**base1b — 1.17B — honest:**

- Embed 32000×2048=65.5M tied; per-layer GQA attn (q 4.19M + k,v 2×1.05M + o 4.19M =10.5M) + SwiGLU h=2048 (3×2048²=12.6M) =23.1M ×48=1.109B; verbalizer tied; slots ~0.3M → P≈1.17B (band 1.0-1.25B)
- FLOPs/token ≈ 6×1e9×3 ≈ 1.8e10
- 25 TFLOPS / 1.8e10 ≈ 1388 tok/s minus recompute → 1.0-1.5k tok/s @12GB (with grad checkpoint + 8bit Adam) → 100M tokens/day
- 4090 24GB: no offload, micro_batch 2-4, ~2.5-3.5k tok/s → 250M/day → 2-3x faster. 2B M1 ≈ 20 days → 8 days on 4090.
- VRAM: bf16 weights 2.3GB + grads 2.3GB + 8bit AdamW ~2.3GB + acts checkpointed 1-2GB + CUDA ctx 1GB → 9-10GB fits 12GB

```bash
# base1b M1 — 2B tokens logic+math (stop-anytime via WSD stable ckpt)
tmux new -s ava
torchrun --nproc_per_node=1 train_1b_deepspeed.py \
  --preset base1b \
  --deepspeed deepspeed_zero3_bf16.json \
  --tokens_total 2000000000 \
  --compile

# Detach tmux: Ctrl+b d, resume: tmux attach -t ava

# Monitor
tail -f logs/base1b/train.log
cat checkpoints/base1b/metrics.jsonl | tail -20
python -c "import torch; print(torch.cuda.memory_allocated()/1e9)"

# Resume after reboot/laptop sleep
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --resume --deepspeed deepspeed_zero3_bf16.json

# M2 — 10B foundation (reuse same preset, milestone gate)
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --resume --deepspeed deepspeed_zero3_bf16.json --tokens_total 10000000000

# M3 — 30B+ reasoning/long/anneal (ctx 8192-16384, rope_base 50k→1M YaRN)
# 12GB reality: ctx>16k at 1B needs mb 1 + grad checkpoint aggressive; 64k-128k blueprint ctx out of reach on this GPU — YaRN eval-time extension covers probe
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --resume --deepspeed deepspeed_zero3_bf16.json --tokens_total 30000000000

# Stable ckpt example: ava_stable_736k.pt (WSD 736k steps stable)
ls -lh checkpoints/base1b/
# checkpoint ~6GB (bf16 2.3 + 8bit optim 2.3 + master + meta), keep-last-3 rotation + 1 stable per phase boundary => 100GB budget
```

**DeepSpeed zero3 bf16 config** (`deepspeed_zero3_bf16.json` already in repo):
- bf16 enabled, stage3 overlap_comm true, offload none (fits)
- For 4090 24GB keep same; for 12GB if OOM add `"offload_optimizer":{"device":"cpu"}` as fallback (slower).

**Compile + SDPA:**
```bash
# compile on mini first
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --compile
# if graph breaks in J-space routing, fallback:
TORCHDYNAMO_DISABLE=1 torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --no-compile
# Attention MUST go through F.scaled_dot_product_attention so flash backend engages automatically
# Do NOT require flash-attn pip package; use torch.backends.cuda.sdp_kernel for debug
```

---

## 5. Ollama integration for free SOTA judging

Host Ollama (you already have):

```bash
ollama serve &
ollama pull qwen3:32b
ollama pull deepseek-r1:32b
curl http://localhost:11434/api/tags
```

Inside Docker:

```bash
# env already set via compose: OLLAMA_HOST=http://host.docker.internal:11434
export OLLAMA_HOST=http://host.docker.internal:11434
export OLLAMA_MODEL=qwen3:32b

# test ollama from container
curl $OLLAMA_HOST/api/tags
python -c "import os, urllib.request, json; print(urllib.request.urlopen(os.environ['OLLAMA_HOST']+'/api/tags', timeout=3).read()[:200])"

# Frontier eval with free judge
python eval_frontier_rubric.py --domain finance --judge ollama --mode mock
python eval_frontier_rubric.py --domain all --judge ollama --mode mock

# Also eval branch harness (J-space 5 tests per branch)
python eval_branch_harness.py --branch all --mode mock
OLLAMA_MODEL=qwen3:32b python eval_branch_harness.py --branch chat --mode real --use-ollama-judge  # if you wire ollama into harness
```

**Model choice:**

| Ollama model | RAM/VRAM Q4 | Best for |
|---|---|---|
| qwen3:32b | 24GB | balanced Frontier judge (code+reasoning) |
| qwen2.5-coder:32b | 24GB | repo-level QA |
| deepseek-r1:32b | 22GB | numerical accuracy + risk disclosure |
| llama3.3:70b | 40GB | instruction following + chat safety |
| glm4:9b-chat | 8GB | GLM family small that fits |

GLM-5.2 753B (40B active) MIT but 241-280GB 2-bit -> not Ollama feasible; use `Glm52Judge` with `ZAI_API_KEY` if you buy Lite $18/mo, else stay ollama free.

```bash
# optional GLM-5.2 API path
export ZAI_API_KEY=personal_from_z.ai
export ZAI_BASE_URL=https://api.z.ai/api/anthropic
export GLM_MODEL=glm-5.2[1m]
python eval_frontier_rubric.py --domain all --judge glm --mode mock
```

---

## 6. Branching for max — code / math / chat from stable ckpt

From any WSD stable checkpoint (`ava_stable_736k.pt` or `checkpoints/base1b/stable/`):

**Arith**: Branch LR lower (1e-4 code, 8e-5 math, 5e-5 chat), freeze sets, router bias, HL targets.

```bash
# code branch — freeze system1, fine-tune system2/planner/router/arbitration, bias [0.25,0.45,0.05,0.25], HL S2 350 Planner200
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch code --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json --preset base1b

# math — freeze system1,planner, fine-tune system2,critic,router bias [0.10,0.65,0.20,0.05] HL S2 400 Critic40
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch math --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json --preset base1b

# chat — freeze system1,system2 capabilities frozen, fine-tune critic,planner,router,arbitration bias [0.15,0.25,0.35,0.25] HL Critic35 Planner180
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch chat --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json --preset base1b

ls checkpoints/ | grep branch
# each branch ~6GB ckpt
```

Router targets: automatic [0.6,0.15,0.1,0.15] deliberate [0.15,0.55,0.1,0.2] safety [0.1,0.2,0.6,0.1] temporal [0.1,0.3,0.1,0.5] per `configs/base1b.yaml`.

---

## 7. Eval loop — mock then real, J-space viewer, frontier, safety

```bash
# branch harness 5 canonical tests per branch
python eval_branch_harness.py --branch all --mode mock
# real with ckpt
python eval_branch_harness.py --branch chat --ckpt checkpoints/branch_chat_step800000.pt --mode real --device cuda

# frontier criteria eval (11 cats: Financial Accuracy, Transparency & Auditability, Risk & Ethical Disclosure, etc)
python eval_frontier_rubric.py --domain finance --judge mock --mode mock
OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock
# optional paid judges:
# META_API_KEY=... python eval_frontier_rubric.py --domain all --judge meta --mode mock  # Muse Spark $1.25/$4.25
# ZAI_API_KEY=... python eval_frontier_rubric.py --domain all --judge glm --mode mock   # GLM-5.2 $1.40/$4.40 cached $0.26

# safety blackmail 0/180 — early warning 4.5 tok base →5.2 tok chat AUC 0.91→0.94 per blueprint
python -m evals.run_harness  # real harness (root eval_harness.py stub was deleted; needle eval lives in evals/needle.py)

# J-space viewer (read-only audit)
uvicorn server:app --host 0.0.0.0 --port 8000 --reload &
# open http://localhost:8000/jspace/viewer?mode=audit (read-only) vs ?mode=research+ENABLE_JSPACE_WRITE=1 (intervene logged)
# frontier integration: add --frontier flag to eval_branch_harness if wired
```

---

## 8. Serving — uvicorn + HF conversion

```bash
# convert deepspeed ckpt to HF
python convert_to_hf.py --ckpt checkpoints/base1b/ava_stable_736k.pt --out hf_model/base1b
python convert_to_hf.py --ckpt checkpoints/branch_chat_step800000.pt --out hf_model/chat

# serve
uvicorn server:app --host 0.0.0.0 --port 8000 &
curl http://localhost:8000/health || curl http://localhost:8000/jspace/eval_branch?branch=all&mode=real

# Docker already exposes 8000:8000 via compose, so host can curl http://localhost:8000
docker compose ps
docker logs ava-agi-factory-ava-train-1 -f
```

---

## 9. Ops — tmux, resume, metrics, thermal, disk rotation

```bash
# long runs under tmux
tmux new -s ava
# inside: torchrun ...
# detach Ctrl+b d, attach tmux attach -t ava, list tmux ls

# metrics.jsonl render
python scripts/make_report.py --runs runs --out reports/index.html  # (wandb_dashboard.py moved to docs/blueprint/, unwired) || python specs/07_serving_deployment.md  # fallback
cat checkpoints/base1b/metrics.jsonl | tail -n 20
cat logs/base1b/train.log | tail -n 50

# wandb offline → sync later
export WANDB_MODE=offline
# after run:
wandb sync wandb/latest-run

# thermal
nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm --format=csv -l 5
nvidia-smi -q -d PERFORMANCE | grep -A5 Thermal
sudo nvidia-smi -pl 120  # try 100-140W, 10-20% tok/s haircut normal, already in time est

# disk rotation — checkpoint ~6GB
du -sh checkpoints/*/*
ls -lh checkpoints/base1b/ | grep stable
# keep-last-3 + 1 stable per phase boundary, auto-rotation script:
# cron: 0 * * * * ls -t checkpoints/base1b/*.pt | tail -n +4 | xargs rm -f

# checkpoint size ~6GB breakdown: bf16 2.3GB weights + 8-bit optim 2.3GB + fp32 master + metadata
```

---

## 10. Max potential checklist — Week 1-4 on consumer hardware

**Week 1: Validate + Mini gate**
- [ ] Day1: `nvidia-smi`, Docker + nvidia-ctk, `docker compose build`, `ollama pull qwen3:32b`, `ollama serve` host, curl `host.docker.internal:11434` from container works
- [ ] Day1-2: Build tokenizer, pack 500M mini, run nano smoke CPU 10M tokens
- [ ] Day2-5: Launch mini 2.5B `torchrun --preset mini`, tmux, monitor metrics.jsonl, 6-10k tok/s → expect ~3-5 days on 12GB, 1.5-2 days on 4090
- [ ] EOD Week1: `eval_branch_harness.py --branch all --mode mock` green + `eval_frontier_rubric.py --judge ollama` >0.6 overall, no NaNs, verbalizable_mass 0.05-0.08, broadcast 0.18-0.24, hl within 30% targets

**Week 2: M1 2B logic+math — first stop-anytime stable ckpt**
- [ ] Day8: `torchrun --preset base1b --tokens_total 2B --compile`, 1.0-1.5k tok/s 12GB → 100M/day, 2-3.5k tok/s 4090 24GB → 250M/day
- [ ] Mid: thermal check, power cap 120W if throttling, `WANDB_MODE=offline`
- [ ] Gate M1: eval probes arithmetic/logic clearly above mini, 5 J-tests trending, save `ava_stable_736k.pt` style ckpt

**Week 3: M2 10B foundation + branching prep**
- [ ] Resume `--resume --tokens_total 10B`, phases p2_foundation frac 0.47 seq 2048 rope 10k mix 35% encyclopedia 25% code etc per base1b.yaml
- [ ] Parallel: pack more data dolma + streaming, keep 100GB free, rotate checkpoints keep-last-3 + stable
- [ ] End Week3: heldout PPL down-trend + canonical J-tests, fork code/math/chat branches from stable ckpt as test of branching code

**Week 4: M3 30B+ reasoning/long/anneal + serving**
- [ ] Resume to 30B seq 8192-16384 rope 50k→1M YaRN, mix proofs_verified 30% math_reasoning 25% chat 25% safety 20%
- [ ] Eval loop: `eval_frontier_rubric.py --judge ollama` (free) daily, safety 0/180 blackmail, J-space viewer http://localhost:8000/jspace/viewer?mode=audit
- [ ] Serve: `convert_to_hf.py` → `hf_model/`, `uvicorn server:app --host 0.0.0.0 --port 8000`, expose via docker 8000
- [ ] Max potential reached on consumer: if heldout + J-tests + frontier >0.65 stable across domains, push branches to HF Hub + document `BRANCH_EVAL_REPORT.md`

**Rerunnable commands cheatsheet:**
```bash
docker compose up -d
docker exec -it ava-agi-factory-ava-train-1 bash -c "
  export OLLAMA_HOST=http://host.docker.internal:11434
  export OLLAMA_MODEL=qwen3:32b
  nvidia-smi && python -c \"import torch; print(torch.cuda.get_device_name(0))\"
  torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --deepspeed deepspeed_zero3_bf16.json
  python eval_branch_harness.py --branch all --mode mock
  python eval_frontier_rubric.py --domain all --judge ollama --mode mock
  uvicorn server:app --host 0.0.0.0 --port 8000
"
```

---

**Disclaimer repeated:** This setup uses only public PyTorch + Docker + Ollama + open MIT weights. No employer systems, no internal models. Build args are free-tier public. If you use Z.ai GLM-5.2 or Meta Muse Spark API, use your personal account key, public endpoint only, and keep offline mock fallback for CI.

End of max setup.

