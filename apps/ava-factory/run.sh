#!/usr/bin/env bash
# run.sh - build & run the Stage 8 self-host serve image (specs/07).
#
# Usage:
#   ./run.sh              # CPU image, port 8000
#   ./run.sh gpu          # CUDA wheels build-arg + --gpus all
#   AVA_CKPT=/path/to.pt ./run.sh
#
# Compose (docker-compose.yml) remains the primary multi-service path;
# this script is the single-container Alienware package.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="${1:-cpu}"
IMAGE="${AVA_SERVE_IMAGE:-ava-serve}"
PORT="${AVA_SERVE_PORT:-8000}"
CKPT_ENV="${AVA_CKPT:-}"

BUILD_ARGS=()
RUN_GPUS=()
case "$MODE" in
  cpu|"")
    BUILD_ARGS+=(--build-arg "TORCH_INDEX=https://download.pytorch.org/whl/cpu")
    ;;
  gpu)
    BUILD_ARGS+=(--build-arg "TORCH_INDEX=https://download.pytorch.org/whl/cu124")
    RUN_GPUS+=(--gpus all)
    ;;
  *)
    echo "usage: $0 [cpu|gpu]" >&2
    exit 2
    ;;
esac

echo "building $IMAGE ($MODE)..."
docker build -t "$IMAGE" "${BUILD_ARGS[@]}" .

RUN_ENV=()
if [[ -n "$CKPT_ENV" ]]; then
  RUN_ENV+=(-e "AVA_CKPT=$CKPT_ENV")
fi

echo "running $IMAGE on :$PORT (mounting ./runs -> /app/runs)..."
exec docker run --rm -p "${PORT}:8000" \
  -v "${ROOT}/runs:/app/runs" \
  -v "${ROOT}/reports:/app/reports" \
  "${RUN_ENV[@]}" \
  "${RUN_GPUS[@]}" \
  "$IMAGE"
