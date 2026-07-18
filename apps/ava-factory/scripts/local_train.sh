#!/bin/bash
# Solo personal project, no connection to employer, built with public/free-tier only
# Local max-potential wrapper for Ava AGI Factory v6.4 on consumer RTX 4080/4090 + Docker + Ollama host

set -e

# === config ===
COMPOSE_FILE="docker-compose.yml"
OLLAMA_HOST_DEFAULT="http://host.docker.internal:11434"
OLLAMA_MODEL_DEFAULT="qwen3:32b"
PRESET_DEFAULT="mini"

# Colors for UX
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}[Ava] Local Max Setup — Solo personal project, public/free-tier only${NC}"
echo "Prereqs: Docker + nvidia-container-toolkit + Ollama on host (ollama serve) + 100GB disk"

# 1. Check nvidia-smi on host
echo ">> Checking nvidia-smi..."
if ! command -v nvidia-smi &> /dev/null; then
  echo "nvidia-smi not found — install NVIDIA driver >=555.xx"
  exit 1
fi
nvidia-smi || true

# 2. Check docker + nvidia runtime
echo ">> Checking docker + nvidia runtime..."
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi || {
  echo "Docker NVIDIA runtime missing — install nvidia-container-toolkit and restart docker"
  exit 1
}

# 3. Check ollama host
echo ">> Checking host Ollama..."
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
  echo -e "${YELLOW}Ollama not reachable at localhost:11434 — start 'ollama serve &' on host${NC}"
  echo "Pull SOTA free judges: ollama pull qwen3:32b; ollama pull deepseek-r1:32b; ollama pull llama3.3:70b"
else
  echo "Ollama host OK"
  curl -s http://localhost:11434/api/tags | head -c 300 || true
fi

# 4. Build & up
echo ">> Building docker image ava-agi-factory:2.4.0-cuda12.4 (may take 10-20min with flash-attn)..."
docker compose -f $COMPOSE_FILE build --progress=plain

echo ">> Starting ava-train container detached..."
docker compose -f $COMPOSE_FILE up -d
sleep 2
docker compose -f $COMPOSE_FILE ps

# 5. Smoke inside container
echo ">> Inside-container CUDA check..."
docker compose -f $COMPOSE_FILE exec ava-train bash -c "nvidia-smi && python -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))'"

echo ">> Checking Ollama from inside container..."
docker compose -f $COMPOSE_FILE exec ava-train bash -c "echo OLLAMA_HOST=\$OLLAMA_HOST && curl -s http://host.docker.internal:11434/api/tags | head -c 200 || echo 'host Ollama not reachable from container — check extra_hosts host-gateway'"

# 6. Default action: if args given, exec them; else interactive instructions
if [ $# -eq 0 ]; then
  echo -e "${GREEN}Container ready. Next steps (run inside container):${NC}"
  cat <<'EOF'
docker compose exec ava-train bash
# inside:
export OLLAMA_HOST=http://host.docker.internal:11434
export OLLAMA_MODEL=qwen3:32b

# tokenizer + data
python -c "from streaming_data import build_tokenizer; build_tokenizer('data/mini/tokenizer/ava_bpe_32k.json')"
python logic_textbook_pipeline.py --phases p0_logic p1_math --out data/mini/raw --tokens 500M
python -m streaming_data pack --in data/mini/raw --out data/mini/packed --seq 1024

# mini — 162M — 2.5B tokens — 3-5 days 12GB, 1.5-2 days 4090
tmux new -s ava
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --deepspeed deepspeed_zero3_bf16.json --compile
# detach: Ctrl+b d

# monitor
tail -f logs/mini/train.log
cat checkpoints/mini/metrics.jsonl | tail -20

# eval free SOTA
python eval_branch_harness.py --branch all --mode mock
OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock

# base1b M1 2B — honest arithmetic: 1.17B = 65.5M embed + 23.1M*48 + slots, FLOPs/token 6P*3 ≈1.8e10, VRAM 9-10GB fits 12GB with 8bit adam + checkpointing, 1.0-1.5k tok/s ≈100M/day
torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --deepspeed deepspeed_zero3_bf16.json --tokens_total 2000000000 --compile

# branch after M1 stable
torchrun --nproc_per_node=1 train_1b_deepspeed.py --branch code --ckpt checkpoints/base1b/ava_stable_736k.pt --deepspeed deepspeed_zero3_bf16.json --preset base1b

# serve
uvicorn server:app --host 0.0.0.0 --port 8000 &
# open http://localhost:8000/jspace/viewer?mode=audit

# convert to hf
python convert_to_hf.py --ckpt checkpoints/base1b/ava_stable_736k.pt --out hf_model/base1b
EOF
  exit 0
fi

# 7. Exec custom command inside container
echo ">> Executing inside container: $@"
docker compose -f $COMPOSE_FILE exec ava-train bash -c "export OLLAMA_HOST=http://host.docker.internal:11434; export OLLAMA_MODEL=${OLLAMA_MODEL_DEFAULT}; $*"
