#!/usr/bin/env bash
# scripts/smoke_live.sh - live serving smoke (Stage 8 / T8.5)
#
# Checks: /health, POST /generate, /jspace/inspect (input-dependent),
# intervene 403 without ENABLE_JSPACE_WRITE, optional intervene with gate open,
# /jspace/eval_branch, /report (or reports/index.html).
#
# Env:
#   AVA_CKPT              checkpoint path (default: runs/chat/ava_nano_chat.pt)
#   AVA_BASE_URL          if set, hit an already-running server (do not boot)
#   AVA_SMOKE_DRY_RUN=1   TestClient + fake engine - no ckpt/GPU (HTTP contract only)
#   AVA_SMOKE_INTERVENE=1 also boot a write-enabled server on AVA_SMOKE_WRITE_PORT
#   AVA_SMOKE_PORT        main server port when we boot (default 8000)
#   AVA_SMOKE_WRITE_PORT  write-enabled server port (default 8001)
#   AVA_SMOKE_PYTHON      python binary (default: python3, then python)
#
# Wall budget <=120s when a real ckpt is present (health poll <=60s + checks).
#
# Full live pass against nano weights is deferred to T9.1 until
# runs/chat/ava_nano_chat.pt exists. Without a ckpt / base URL this script
# exits non-zero with a clear message (never a silent pass). Use
# AVA_SMOKE_DRY_RUN=1 to prove the HTTP assertions offline.
#
# Usage:
#   bash scripts/smoke_live.sh
#   AVA_CKPT=runs/chat/ava_nano_chat.pt bash scripts/smoke_live.sh
#   AVA_BASE_URL=http://127.0.0.1:8000 bash scripts/smoke_live.sh
#   AVA_SMOKE_DRY_RUN=1 bash scripts/smoke_live.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AVA_CKPT="${AVA_CKPT:-runs/chat/ava_nano_chat.pt}"
AVA_BASE_URL="${AVA_BASE_URL:-}"
AVA_SMOKE_DRY_RUN="${AVA_SMOKE_DRY_RUN:-0}"
AVA_SMOKE_INTERVENE="${AVA_SMOKE_INTERVENE:-0}"
AVA_SMOKE_PORT="${AVA_SMOKE_PORT:-8000}"
AVA_SMOKE_WRITE_PORT="${AVA_SMOKE_WRITE_PORT:-8001}"
WALL_BUDGET_S="${AVA_SMOKE_WALL_S:-120}"

SERVER_PID=""
WRITE_PID=""
STARTED_AT="$(date +%s)"

die() {
  echo "SMOKE FAIL $*" >&2
  exit 1
}

pick_python() {
  if [[ -n "${AVA_SMOKE_PYTHON:-}" ]]; then
    echo "$AVA_SMOKE_PYTHON"
    return
  fi
  # Prefer an active venv / common local venvs that have fastapi.
  local candidates=()
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    candidates+=("${VIRTUAL_ENV}/Scripts/python.exe" "${VIRTUAL_ENV}/bin/python")
  fi
  candidates+=(
    "$ROOT/.venv/Scripts/python.exe"
    "$ROOT/.venv/bin/python"
    "$ROOT/venv/Scripts/python.exe"
    "$ROOT/venv/bin/python"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]] || [[ -f "$c" ]]; then
      echo "$c"
      return
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  die "python: neither python3 nor python found on PATH"
}

PYTHON="$(pick_python)"

cleanup() {
  local ec=$?
  if [[ -n "$WRITE_PID" ]] && kill -0 "$WRITE_PID" 2>/dev/null; then
    kill "$WRITE_PID" 2>/dev/null || true
    wait "$WRITE_PID" 2>/dev/null || true
  fi
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  local now elapsed
  now="$(date +%s)"
  elapsed=$((now - STARTED_AT))
  if [[ $ec -eq 0 && $elapsed -gt $WALL_BUDGET_S ]]; then
    echo "SMOKE FAIL wall: completed in ${elapsed}s > budget ${WALL_BUDGET_S}s" >&2
    exit 1
  fi
  exit "$ec"
}
trap cleanup EXIT INT TERM

ensure_report() {
  if [[ ! -f reports/index.html ]] || [[ "$(wc -c < reports/index.html | tr -d ' ')" -le 10240 ]]; then
    echo "... reports/index.html missing/small - running scripts/make_report.py" >&2
    "$PYTHON" scripts/make_report.py
  fi
}

wait_health() {
  local url="$1"
  local max_s="${2:-60}"
  local i=0
  echo "... polling $url/health (max ${max_s}s)" >&2
  while (( i < max_s )); do
    if curl -fsS "$url/health" >/dev/null 2>&1; then
      echo "... healthy after ${i}s" >&2
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  die "health: server at $url not healthy within ${max_s}s"
}

run_checks() {
  local base="$1"
  local intervene_url="${2:-}"
  local args=(scripts/smoke_live_checks.py --base-url "$base")
  if [[ -n "$intervene_url" ]]; then
    args+=(--intervene-base-url "$intervene_url")
  fi
  "$PYTHON" "${args[@]}"
}

# --- dry-run path (no ckpt / no long-lived server) ---
if [[ "$AVA_SMOKE_DRY_RUN" == "1" ]]; then
  echo "smoke_live: DRY-RUN (AVA_SMOKE_DRY_RUN=1) - HTTP contract via ASGI fake engine" >&2
  echo "NOTE: full live pass with real weights deferred to T9.1 nano smoke" >&2
  ensure_report
  "$PYTHON" scripts/smoke_live_checks.py --dry
  exit 0
fi

# --- already-running server ---
if [[ -n "$AVA_BASE_URL" ]]; then
  echo "smoke_live: using AVA_BASE_URL=$AVA_BASE_URL (no boot)" >&2
  ensure_report
  INTERVENE_URL=""
  if [[ "$AVA_SMOKE_INTERVENE" == "1" ]]; then
    # Caller must point a write-enabled server at AVA_SMOKE_INTERVENE_URL,
    # or we boot one only when we also own a ckpt (below). Against an external
    # base URL we require AVA_SMOKE_INTERVENE_URL explicitly.
    INTERVENE_URL="${AVA_SMOKE_INTERVENE_URL:-}"
    if [[ -z "$INTERVENE_URL" ]]; then
      die "intervene: AVA_SMOKE_INTERVENE=1 with AVA_BASE_URL requires AVA_SMOKE_INTERVENE_URL (write-enabled server)"
    fi
  fi
  run_checks "$AVA_BASE_URL" "$INTERVENE_URL"
  exit 0
fi

# --- need a checkpoint to boot uvicorn ---
if [[ ! -f "$AVA_CKPT" ]]; then
  cat >&2 <<EOF
SMOKE FAIL ckpt: checkpoint not found: $AVA_CKPT

  Set AVA_CKPT to a real .pt, or AVA_BASE_URL to a running server.
  For offline HTTP-contract checks (no GPU): AVA_SMOKE_DRY_RUN=1 bash scripts/smoke_live.sh

  Full live pass against nano weights is deferred to T9.1
  (runs/chat/ava_nano_chat.pt not present yet).
EOF
  exit 1
fi

ensure_report

# Boot main server WITHOUT write gate (so intervene-403 is meaningful).
export AVA_CKPT
unset ENABLE_JSPACE_WRITE || true
echo "smoke_live: booting uvicorn on :$AVA_SMOKE_PORT (AVA_CKPT=$AVA_CKPT)" >&2
"$PYTHON" -m uvicorn server:app --host 127.0.0.1 --port "$AVA_SMOKE_PORT" &
SERVER_PID=$!
BASE="http://127.0.0.1:${AVA_SMOKE_PORT}"
wait_health "$BASE" 60

INTERVENE_URL=""
if [[ "$AVA_SMOKE_INTERVENE" == "1" ]]; then
  echo "smoke_live: booting write-enabled uvicorn on :$AVA_SMOKE_WRITE_PORT" >&2
  ENABLE_JSPACE_WRITE=1 "$PYTHON" -m uvicorn server:app --host 127.0.0.1 --port "$AVA_SMOKE_WRITE_PORT" &
  WRITE_PID=$!
  INTERVENE_URL="http://127.0.0.1:${AVA_SMOKE_WRITE_PORT}"
  wait_health "$INTERVENE_URL" 60
fi

run_checks "$BASE" "$INTERVENE_URL"
# trap cleanup prints wall budget / kills servers
exit 0
