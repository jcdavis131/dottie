#!/usr/bin/env bash
# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Single-instance wrapper for one research-loop worker. flock -n makes cron a no-op if the same
# worker (or, for training, the GPU) is still busy from the previous tick — so an hourly cron
# never stacks a second 14-hour training run on top of a running one.
#
# Usage: research_worker.sh <ideate|implement|train|evaluate|loop|run> [extra args...]
set -euo pipefail

WORKER="${1:?usage: research_worker.sh <ideate|implement|train|evaluate|loop|run> [args...]}"
shift || true

REPO="${DOTTIE_ROOT:-$HOME/workspace/dottie}"
APP="$REPO/apps/dottie"
LOG_DIR="${DOTTIE_RESEARCH_LOG_DIR:-$APP/data/research/logs}"
LOCK="/tmp/dottie_research_${WORKER}.lock"

mkdir -p "$LOG_DIR"
cd "$APP"

# -n: fail immediately (skip this tick) if the lock is held. Training additionally shares the
# 'train' lock so only one run touches the GPU at a time.
exec flock -n "$LOCK" python3 -m dottie.research "$WORKER" "$@" \
    >>"$LOG_DIR/${WORKER}.log" 2>&1
