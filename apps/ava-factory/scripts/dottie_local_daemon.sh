#!/usr/bin/env bash
# Solo personal project, no connection to employer, built with public/free-tier only
# Dottie Local Daemon — Alienware RTX 4080/4090 heavy loop
# 4h data 10M, daily train, logs to logs/dottie_local.log
# Usage: ./scripts/dottie_local_daemon.sh [start|stop|status|run-once]
set -euo pipefail

DISCLAIMER="Solo personal project, no connection to employer, built with public/free-tier only"
echo "[$DISCLAIMER] Dottie Local Daemon"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$REPO_DIR/logs/dottie_local.log"
PID_FILE="$REPO_DIR/logs/dottie_local_daemon.pid"
mkdir -p "$REPO_DIR/logs" "$REPO_DIR/reports" "$REPO_DIR/data/daily_expanded"

if [ -f "$REPO_DIR/.env" ]; then set -a; source "$REPO_DIR/.env"; set +a; fi

MODE="${1:-start}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

check_disk() {
  pct=$(df "$REPO_DIR" | awk 'NR==2 {print $5}' | tr -d '%')
  log "Disk usage: ${pct}%"
  if [ "$pct" -ge 85 ]; then
    log "WARN disk >=85% - rotating old shards"
    python3 "$REPO_DIR/scripts/dottie_continuous_loop.py" --mode ecosystem >> "$LOG_FILE" 2>&1 || true
  fi
}

run_once() {
  log "Run once started full=${DOTTIE_FULL:-1}"
  check_disk
  log "Data 10M expansion start"
  python3 "$REPO_DIR/scripts/dottie_continuous_loop.py" --mode data --tokens 10M --full >> "$LOG_FILE" 2>&1 || log "Data expansion failed"
  log "Ecosystem"
  python3 "$REPO_DIR/scripts/dottie_continuous_loop.py" --mode ecosystem >> "$LOG_FILE" 2>&1 || log "Ecosystem failed"
  if [ "${DOTTIE_TRAIN:-1}" = "1" ]; then
    log "Train mini"
    DOTTIE_TOKENS=10000000 python3 "$REPO_DIR/scripts/dottie_continuous_loop.py" --mode train --preset mini --steps 1000 --resume >> "$LOG_FILE" 2>&1 || log "Train failed"
  fi
  log "Eval"
  python3 "$REPO_DIR/scripts/dottie_continuous_loop.py" --mode eval --branch all --eval-mode real >> "$LOG_FILE" 2>&1 || log "Eval failed"
  log "Run once finished"
}

daemon_loop() {
  log "Daemon loop start PID $$"
  echo $$ > "$PID_FILE"
  while true; do
    run_once
    log "Sleeping 4h"
    sleep 14400
  done
}

case "$MODE" in
  start)
    if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
      log "Already running PID $(cat "$PID_FILE")"
      exit 0
    fi
    log "Starting daemon in background"
    nohup bash "$0" daemon >> "$LOG_FILE" 2>&1 &
    log "Started PID $! log $LOG_FILE"
    ;;
  daemon)
    daemon_loop
    ;;
  run-once)
    run_once
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      log "Stopping $PID"
      kill "$PID" || true
      rm -f "$PID_FILE"
    else
      log "Not running"
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
      log "Running PID $(cat "$PID_FILE")"
      tail -n 20 "$LOG_FILE"
    else
      log "Not running"
      tail -n 20 "$LOG_FILE" || true
    fi
    ;;
  *)
    echo "Usage: $0 [start|daemon|run-once|stop|status]"
    exit 1
    ;;
esac

echo ""
echo "Crontab for Alienware (crontab -e):"
echo "# Dottie 4h 10M data + ecosystem + train weekly"
echo "0 */4 * * * cd $REPO_DIR && DOTTIE_FULL=1 python3 scripts/dottie_continuous_loop.py --mode data --tokens 10M --full >> logs/dottie_local.log 2>&1"
echo "0 9 * * * cd $REPO_DIR && python3 scripts/dottie_continuous_loop.py --mode ecosystem >> logs/dottie_local.log 2>&1"
echo "0 3 * * 0 cd $REPO_DIR && python3 scripts/dottie_continuous_loop.py --mode train --preset mini --tokens-total 2500000000 --resume >> logs/dottie_local.log 2>&1"
echo "0 10 * * * cd $REPO_DIR && python3 scripts/dottie_continuous_loop.py --mode eval --branch all --eval-mode real >> logs/dottie_local.log 2>&1"
