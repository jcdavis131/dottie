#!/usr/bin/env bash
# Idempotent developer / Cursor Cloud bootstrap for the dottie monorepo.
# Safe to re-run. Mirrors CI (.github/workflows/ci.yml): uv + Python 3.11 + sync.
set -euo pipefail

DOTTIE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DOTTIE_ROOT"

log() { printf '[dev-env] %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- uv ---
export PATH="${HOME}/.local/bin:${PATH}"
if ! have uv; then
  log "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi
log "uv $(uv --version)"

# --- Python 3.11 (CI pin; .python-version) ---
log "ensuring Python 3.11 via uv"
uv python install 3.11

# --- Workspace sync (light packages; factory/torch intentionally excluded) ---
log "uv sync (workspace members + dev group)"
if [[ -f uv.lock ]]; then
  uv sync --all-groups --frozen || uv sync --all-groups
else
  uv sync --all-groups
fi

# --- confirm lint toolchain on PATH via uv run ---
if ! uv run ruff --version >/dev/null 2>&1; then
  log "WARN: ruff not resolvable via uv run after sync"
fi

# --- scout on PATH via uv tool (editable monorepo member) ---
log "installing scout CLI tool (editable apps/scout-cli)"
uv tool install -e "./apps/scout-cli" --force >/dev/null 2>&1 \
  || uv pip install --python "$(uv python find 3.11)" -e "./apps/scout-cli"

# --- optional: personal-graphify CLI ---
if [[ -d packages/personal-graphify ]]; then
  log "installing pgraphify tool (editable packages/personal-graphify)"
  uv tool install -e "./packages/personal-graphify" --force >/dev/null 2>&1 || true
fi

# --- shell profile (marked block; idempotent) ---
BASHRC="${HOME}/.bashrc"
BLOCK_BEGIN="# >>> dottie-dev-env >>>"
BLOCK_END="# <<< dottie-dev-env <<<"
BLOCK_BODY=$(cat <<EOF
${BLOCK_BEGIN}
export PATH="\${HOME}/.local/bin:\${PATH}"
export DOTTIE_ROOT="${DOTTIE_ROOT}"
export AVA_FACTORY_ROOT="${DOTTIE_ROOT}/apps/ava-factory"
export SCOUT_CLI_ROOT="\${SCOUT_CLI_ROOT:-/agent/repos/scout-cli}"
# Prefer uv-managed Python 3.11 when available
if command -v uv >/dev/null 2>&1; then
  _dottie_py311="\$(uv python find 3.11 2>/dev/null || true)"
  if [[ -n "\${_dottie_py311}" ]]; then
    export UV_PYTHON="\${_dottie_py311}"
  fi
  unset _dottie_py311
fi
alias dottie-root='cd "\$DOTTIE_ROOT"'
alias scout-root='cd "\${SCOUT_CLI_ROOT:-/agent/repos/scout-cli}"'
alias dottie-sync='(cd "\$DOTTIE_ROOT" && uv sync --all-groups)'
alias dottie-test='(cd "\$DOTTIE_ROOT" && make test)'
alias dottie-doctor='(cd "\$DOTTIE_ROOT" && make doctor)'
${BLOCK_END}
EOF
)

if [[ -f "$BASHRC" ]] && grep -qF "$BLOCK_BEGIN" "$BASHRC"; then
  # Replace existing block
  tmp="$(mktemp)"
  awk -v begin="$BLOCK_BEGIN" -v end="$BLOCK_END" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$BASHRC" >"$tmp"
  printf '\n%s\n' "$BLOCK_BODY" >>"$tmp"
  mv "$tmp" "$BASHRC"
  log "refreshed dottie-dev-env block in ${BASHRC}"
else
  printf '\n%s\n' "$BLOCK_BODY" >>"$BASHRC"
  log "appended dottie-dev-env block to ${BASHRC}"
fi

# Export for current process
export DOTTIE_ROOT
export AVA_FACTORY_ROOT="${DOTTIE_ROOT}/apps/ava-factory"
export PATH="${HOME}/.local/bin:${PATH}"

# --- sibling scout-cli repo (multi-repo cloud env) ---
SIBLING_SCOUT="${SCOUT_CLI_ROOT:-/agent/repos/scout-cli}"
if [[ -d "$SIBLING_SCOUT" && -f "$SIBLING_SCOUT/pyproject.toml" ]]; then
  log "syncing sibling scout-cli at ${SIBLING_SCOUT}"
  (
    # Isolate from this monorepo's uv project discovery.
    unset UV_PROJECT UV_PROJECT_ENVIRONMENT VIRTUAL_ENV || true
    if [[ -x "${SIBLING_SCOUT}/scripts/dev-env-setup.sh" ]]; then
      bash "${SIBLING_SCOUT}/scripts/dev-env-setup.sh"
    else
      cd "$SIBLING_SCOUT"
      [[ -d .venv ]] || uv venv --python 3.11 .venv
      uv sync --all-extras --python "${SIBLING_SCOUT}/.venv/bin/python" \
        || uv pip install --python "${SIBLING_SCOUT}/.venv/bin/python" -e ".[dev]"
    fi
  ) || log "WARN: sibling scout-cli setup skipped (non-fatal)"
  # Re-sync monorepo workspace in case sibling tooling touched shared caches,
  # and prefer monorepo scout on PATH when developing inside dottie.
  log "re-syncing dottie workspace + re-pinning scout uv tool"
  uv sync --all-groups --frozen >/dev/null 2>&1 || uv sync --all-groups >/dev/null
  uv tool install -e "./apps/scout-cli" --force >/dev/null 2>&1 || true
fi

# --- status report ---
log "DOTTIE_ROOT=${DOTTIE_ROOT}"
log "AVA_FACTORY_ROOT=${AVA_FACTORY_ROOT}"
log "python: $(uv run python -c 'import sys; print(sys.version.split()[0])')"
if have scout; then
  log "scout: $(scout --version 2>/dev/null || scout --help 2>&1 | head -1)"
else
  log "scout: not on PATH yet — use: uv run --directory apps/scout-cli python -m bigbang.cli"
fi
if have docker; then
  log "docker: present"
else
  log "docker: absent (factory fleet / compose optional)"
fi
if have ollama; then
  log "ollama: present"
else
  log "ollama: absent (optional for local LLM paths)"
fi

log "done. Next: source ~/.bashrc && make forge && make doctor"
