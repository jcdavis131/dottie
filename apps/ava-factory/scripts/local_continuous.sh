#!/bin/bash
# Solo personal project, no connection to employer, built with public/free-tier only
# Dottie Continuous Factory — Local Alienware RTX 4080/4090 Always-On Loop
# Usage: tmux new -s dottie-local -d ./scripts/local_continuous.sh
# Loop: pull → expand 10M → train mini/base1b → eval → push STATUS + reports → sleep 1h
set -e
cd "$(dirname "$0")/.."
echo "[Dottie Local] Starting $(date -Is) pwd=$(pwd)"

# Ensure Ollama is reachable
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "[Dottie Local] WARNING: Ollama not reachable at http://localhost:11434 — evals will use mock judge"
else
  echo "[Dottie Local] Ollama OK"
fi

# Check GPU
nvidia-smi || echo "nvidia-smi not found — running CPU mode?"

while true; do
  echo "===== LOOP $(date -Is) ====="
  # Pull latest (don't fail if merge conflict — stash?)
  git pull origin main || echo "git pull failed, continuing"

  # 1) Data expansion 10M tokens (heavy)
  echo "[1] Expanding 10M tokens..."
  python scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math p2_foundation --out data/daily_expanded --upload-mode local || echo "expansion failed"

  # 2) Pack if needed
  echo "[2] Packing..."
  python -m dottie.data pack --in data/daily_expanded --out data/packed --seq 1024 --tokenizer data/mini/tokenizer/dottie_bpe_32k.json || true

  # 3) Training — mini gate first, then base1b resume (WSD stop-anytime)
  if [ -f "configs/mini.yaml" ]; then
    echo "[3a] Mini 2.5B check (may be already done)..."
    torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --tokens_total 2500000000 --deepspeed deepspeed_zero3_bf16.json --compile || echo "mini train step done/failed"
  fi

  echo "[3b] Base1b 2B M1 resume..."
  torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --resume --deepspeed deepspeed_zero3_bf16.json --tokens_total 2000000000 --compile || echo "base1b step done"

  # 4) Evals
  echo "[4] Evals..."
  python eval_branch_harness.py --branch all --mode mock || true
  OLLAMA_HOST=http://localhost:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock || python eval_frontier_rubric.py --domain all --judge mock --mode mock || true

  # 5) Reports
  echo "[5] Reports..."
  python scripts/make_report.py --out reports/ || true

  # Update STATUS.json timestamp
  python -c "
import json, datetime, pathlib
p=pathlib.Path('STATUS.json')
j=json.loads(p.read_text()) if p.exists() else {}
j['last_local_loop']=datetime.datetime.utcnow().isoformat()+'Z'
p.write_text(json.dumps(j, indent=2))
print('STATUS updated')
" || true

  # 6) Push
  echo "[6] Git push..."
  git add STATUS.json reports/ BRANCH_EVAL_REPORT.md FRONTIER_EVAL_REPORT.md data/manifest.jsonl 2>/dev/null || true
  git commit -m "auto: local continuous $(date -Is) tokens=$(python -c 'import json; print(json.load(open(\"STATUS.json\")).get(\"total_tokens\",\"?\"))' 2>/dev/null || echo ?)" || echo "nothing to commit"
  git push origin main || echo "push failed"

  echo "[Sleep] 1h..."
  sleep 3600
done
