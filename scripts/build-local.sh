#!/usr/bin/env bash
# build-local.sh — package Dottie Local as a single-file executable.
# Stdlib only: python3 -m zipapp. No pip, no build backend, no network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
PYZ="$DIST/dottie.pyz"

mkdir -p "$DIST"
python3 -m zipapp "$ROOT/worker" -o "$PYZ" -p "/usr/bin/env python3" -m "dottie:main" -c
chmod +x "$PYZ"

echo "built: $PYZ ($(du -h "$PYZ" | cut -f1))"
echo "run:   $PYZ status"
echo "try:   DOTTIE_JOBS_DIR=~/.dottie/jobs $PYZ submit --goal 'hello dottie'"
