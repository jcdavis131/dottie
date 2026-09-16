#!/usr/bin/env bash
# install-local.sh — install Dottie Local (single-file, stdlib only).
# Builds dist/dottie.pyz and links it as ~/.local/bin/dottie.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/scripts/build-local.sh" >/dev/null

BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$ROOT/dist/dottie.pyz" "$BIN_DIR/dottie"

# Default queue + timeline next to the user on first run.
mkdir -p "${DOTTIE_JOBS_DIR:-$HOME/.dottie/jobs}"/{pending,claimed,done,failed}

echo "installed: $BIN_DIR/dottie"
echo "queue:     ${DOTTIE_JOBS_DIR:-$HOME/.dottie/jobs}"
echo ""
echo "Add to your shell profile so the queue follows you everywhere:"
echo "  export DOTTIE_JOBS_DIR=\"\$HOME/.dottie/jobs\""
echo ""
echo "Try it: dottie submit --goal \"first job\" && dottie list"
