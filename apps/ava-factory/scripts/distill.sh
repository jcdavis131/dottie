#!/bin/bash
# Solo personal project, no connection to employer, built with public/free-tier only
# Distillation wrapper for Ava AGI Factory v6.4 — MOPD / privileged / earlier / offpolicy
# Usage: ./scripts/distill.sh [mopd|privileged|earlier|offpolicy] [extra args...]
# Runs inside docker compose ava-train with OLLAMA_HOST=host.docker.internal:11434 for free SOTA judging
# Honest VRAM: student 2.3GB + teacher 2.3GB + grads 2.3GB + adam8bit 2.3GB + act 1-2GB = 9-10GB fits 12GB

set -e

MODE=${1:-mopd}
shift || true

COMPOSE_FILE="docker-compose.yml"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}[Ava Distill] mode=$MODE — Solo personal project, public/free-tier only${NC}"

# Check docker nvidia
if ! docker ps | grep -q ava-train; then
  echo -e "${YELLOW}ava-train not running — starting via docker compose up -d${NC}"
  docker compose -f $COMPOSE_FILE up -d
  sleep 2
fi

# Check ollama host from inside container
echo ">> Checking Ollama from container (for eval frontier rubric)..."
docker compose -f $COMPOSE_FILE exec ava-train bash -c "curl -s http://host.docker.internal:11434/api/tags | head -c 200 || echo 'Ollama host not reachable — start ollama serve on host'"

# Build command per mode
case $MODE in
  mopd)
    CMD="python on_policy_distill.py --mode mopd --student-ckpt checkpoints/base1b/ava_stable_736k.pt --teachers code:checkpoints/code/exp.pt,math:checkpoints/math/exp.pt,chat:checkpoints/chat/exp.pt --data_root data/streaming_shards --batch 1 --seq_len 2048 --tokens_total 500000000 --lr 8e-5 --preserve-router --deepspeed deepspeed_zero3_bf16.json $@"
    ;;
  privileged)
    CMD="python on_policy_distill.py --mode privileged --student-ckpt checkpoints/base1b/ava_stable_736k.pt --hint \"think with 4 workspaces S1 Fast hl8 S2 Slow hl300 Critic hl30 Planner hl150, verify stepwise, preserve routing\" --batch 1 --seq_len 2048 --tokens_total 200000000 --lr 5e-5 $@"
    ;;
  earlier)
    CMD="python on_policy_distill.py --mode earlier --student-ckpt checkpoints/chat/finetuned.pt --teachers earlier:checkpoints/base1b/ava_stable_736k.pt --data_root data/streaming_shards/synthetic_reward_gt0.8 --batch 1 --seq_len 2048 --tokens_total 200000000 --lr 5e-5 --earlier-kl-weight 0.7 --earlier-ce-weight 0.3 $@"
    ;;
  offpolicy)
    CMD="python on_policy_distill.py --mode offpolicy --student-ckpt None --student-config configs/mini.yaml --teachers teacher:checkpoints/base1b/ava_stable_736k.pt --teacher-config configs/base1b.yaml --data_root data/mini/packed --batch 2 --seq_len 1024 --tokens_total 500000000 --lr 6e-4 --offpolicy-alpha 0.5 $@"
    ;;
  *)
    # Custom mode passed through
    CMD="python on_policy_distill.py --mode $MODE $@"
    ;;
esac

echo ">> Executing inside ava-train: $CMD"
docker compose -f $COMPOSE_FILE exec ava-train bash -c "export OLLAMA_HOST=http://host.docker.internal:11434; export OLLAMA_MODEL=qwen3:32b; $CMD"

# Post-run eval hint
echo -e "${GREEN}[Ava Distill] Done mode=$MODE. Next:${NC}"
echo "  python eval_branch_harness.py --branch all --mode mock"
echo "  OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock"
echo "  Logs: logs/distill.log + logs/metrics.jsonl, CKPT: checkpoints/distill/"
