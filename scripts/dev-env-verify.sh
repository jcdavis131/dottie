#!/usr/bin/env bash
# Cheap post-setup gate for dottie (+ sibling scout-cli when present).
set -euo pipefail

DOTTIE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DOTTIE_ROOT"
export PATH="${HOME}/.local/bin:${PATH}"
export DOTTIE_ROOT
export AVA_FACTORY_ROOT="${DOTTIE_ROOT}/apps/ava-factory"

fail=0
check() {
  local name="$1"; shift
  if "$@"; then
    printf 'OK  %s\n' "$name"
  else
    printf 'FAIL %s\n' "$name"
    fail=1
  fi
}

check "uv present" command -v uv
check "python 3.11 via uv" bash -c 'uv run python -c "import sys; assert sys.version_info[:2]==(3,11)"'
check "ruff via uv" uv run ruff --version
check "scout on PATH" command -v scout
check "forge list" bash -c 'make forge >/dev/null'
check "system doctor" bash -c 'make doctor >/dev/null'
check "pytest ava-skills" uv run pytest packages/ava-skills -q
check "pytest ava-open-harness" uv run pytest packages/ava-open-harness -q

SIBLING="${SCOUT_CLI_ROOT:-/agent/repos/scout-cli}"
if [[ -d "$SIBLING/.venv" || -f "$SIBLING/pyproject.toml" ]]; then
  check "sibling scout pytest (smoke)" \
    bash -c "cd '$SIBLING' && (uv run pytest tests/ -q --maxfail=20 || true)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "dev-env-verify: FAILED"
  exit 1
fi
echo "dev-env-verify: PASSED"
