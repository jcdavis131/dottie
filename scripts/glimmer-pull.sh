#!/usr/bin/env bash
# glimmer-pull.sh — pull Muse Glimmer 30B weights for always-on local agent
# Zero-deps shell, stdlib only, honest 503 if blocked
# Branch: scout/glimmer-dottie-harness
# Goal: dottie-closed-loop-factory-v2

set -euo pipefail

MODEL="${GLIMMER_MODEL:-muse-glimmer-30b}"
HF_REPO="${GLIMMER_HF_REPO:-meta-llama/Muse-Glimmer-30B}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
LLAMA_CPP_URL="${LLAMA_CPP_URL:-http://localhost:8080}"
DEST_DIR="${1:-$HOME/workspace/dottie/models/glimmer}"

echo "=== Muse Glimmer 30B Pull ==="
echo "Model: $MODEL"
echo "HF Repo: $HF_REPO"
echo "Ollama: $OLLAMA_URL"
echo "Dest: $DEST_DIR"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# 1) Try Ollama pull (fastest for local agent)
echo "[1/3] Checking Ollama gateway at $OLLAMA_URL..."
if curl -sf "$OLLAMA_URL/" --max-time 3 | grep -qi "ollama is running" 2>/dev/null; then
  echo "Ollama is running — attempting ollama pull $MODEL"
  if command -v ollama >/dev/null 2>&1; then
    # ollama pull uses model name, not HF repo directly, but glimmer may be in library
    # Try direct pull, fallback to HF via ollama if supported
    if ollama pull "$MODEL" 2>&1 | tail -n 20; then
      echo "✓ Ollama pull succeeded for $MODEL"
      ollama list | grep -i glimmer || true
    else
      echo "Ollama pull $MODEL failed — trying $HF_REPO via ollama (if registry supports)..."
      if ollama pull "$HF_REPO" 2>&1 | tail -n 20; then
        echo "✓ Ollama pull succeeded for $HF_REPO"
      else
        echo "⚠ Ollama pull failed for both names — may need manual import from HF"
      fi
    fi
  else
    echo "⚠ ollama CLI not found in PATH — install from https://ollama.com or use HF path"
  fi
else
  echo "⚠ Ollama not reachable at $OLLAMA_URL — skipping Ollama pull (honest 503, not fatal)"
fi

echo ""
# 2) Try HF download via huggingface-cli (for llama.cpp GGUF or safetensors)
echo "[2/3] Checking HF weights via huggingface-cli..."
mkdir -p "$DEST_DIR"
if command -v huggingface-cli >/dev/null 2>&1; then
  echo "huggingface-cli found — downloading $HF_REPO to $DEST_DIR"
  # Try GGUF first if available, else safetensors
  # Use --local-dir for offline-ready cache
  if huggingface-cli download "$HF_REPO" --local-dir "$DEST_DIR" --local-dir-use-symlinks False 2>&1 | tail -n 30; then
    echo "✓ HF download succeeded to $DEST_DIR"
    ls -lh "$DEST_DIR" | head -n 20
  else
    echo "⚠ HF download failed — trying alt repos..."
    for alt in "meta/Muse-Glimmer" "meta-llama/muse-glimmer-30b" "musehq/glimmer-30b"; do
      echo "  trying $alt..."
      if huggingface-cli download "$alt" --local-dir "$DEST_DIR" --local-dir-use-symlinks False 2>&1 | tail -n 10; then
        echo "✓ HF download succeeded for alt $alt"
        break
      fi
    done
  fi
else
  echo "⚠ huggingface-cli not found — install via: pip install -U huggingface_hub (or skip if using Ollama only)"
  echo "  For zero-deps stdlib-only rule, Ollama pull is preferred on Hatch VM"
fi

echo ""
# 3) Verify offline readiness
echo "[3/3] Verifying offline readiness..."
echo "Checking Ollama models..."
if curl -sf "$OLLAMA_URL/api/tags" --max-time 3 2>/dev/null | head -c 500; then
  echo ""
  echo "Ollama tags reachable"
else
  echo "Ollama tags not reachable (honest 503)"
fi

echo ""
echo "Checking local cache dirs..."
for d in "$HOME/.ollama/models" "$HOME/.cache/huggingface/hub" "$DEST_DIR" "/tmp/glimmer-models"; do
  if [ -d "$d" ]; then
    sz=$(du -sh "$d" 2>/dev/null | cut -f1)
    cnt=$(ls -1 "$d" 2>/dev/null | wc -l)
    echo "  $d — $sz — $cnt entries"
  else
    echo "  $d — not found"
  fi
done

echo ""
echo "=== Pull Summary ==="
echo "Model: $MODEL"
echo "HF: $HF_REPO"
echo "Ollama: $OLLAMA_URL — $(curl -sf $OLLAMA_URL/ --max-time 2 | grep -qi "ollama" && echo "up" || echo "down (honest 503)")"
echo "Llama.cpp: $LLAMA_CPP_URL — $(curl -sf $LLAMA_CPP_URL/health --max-time 2 >/dev/null && echo "up" || echo "down")"
echo "Dest: $DEST_DIR"
echo "Offline ready: check dirs above for >5GB content"
echo ""
echo "Next: test via 'cd ~/workspace/dottie && node --loader ts-node/esm scripts/glimmer-test.ts' or 'curl http://localhost:3000/api/glimmer'"
echo "Or: 'OLLAMA_BASE_URL=$OLLAMA_URL node scripts/glimmer-test.mjs'"
