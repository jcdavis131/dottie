#!/bin/bash
set -e
# Monorepo-first: Dottie is source of truth, fallback to legacy standalone
DOTTIE_ROOT="${DOTTIE_ROOT:-$HOME/workspace/dottie}"
FACTORY_ROOT="$DOTTIE_ROOT/apps/ava-factory"
RESEARCH_ROOT="$FACTORY_ROOT/research-engine"

# Prefer monorepo research-engine, fallback to standalone
if [ -d "$RESEARCH_ROOT" ]; then
  cd "$RESEARCH_ROOT"
elif [ -d "$HOME/workspace/ava-research-engine" ]; then
  cd "$HOME/workspace/ava-research-engine"
else
  cd "$FACTORY_ROOT"
fi

echo "[Autoresearch] DOTTIE_ROOT=$DOTTIE_ROOT FACTORY=$FACTORY_ROOT PWD=$(pwd) Starting 5-min smoke loop"
# Ensure results dir exists in monorepo location too
mkdir -p ~/workspace/your_files/ava-agi/runs
python3 scripts/autoresearch_runner.py 2>&1 | tee -a ~/workspace/your_files/ava-agi/runs/autoresearch-$(date -Is).log || echo "runner failed"
echo "Done"
