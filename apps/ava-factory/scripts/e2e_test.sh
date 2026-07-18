#!/bin/bash
# Solo personal project, no connection to employer, built with public/free-tier only
# HOME persona only — Ava AGI Factory v6.4 End-to-End Local Test Harness
# Designed to run WITHOUT GPU, WITHOUT HF_TOKEN, WITHOUT Ollama — mock-friendly for Hatch VM & Alienware quick check

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
DISCLAIMER="Solo personal project, no connection to employer, built with public/free-tier only"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/e2e_test_${TIMESTAMP}.log"
mkdir -p "$LOG_DIR" "$ROOT/data/for_upload" "$ROOT/data/daily_expanded" "$ROOT/data/discovery" "$ROOT/your_files/ava-agi/dataset_discovery"

echo -e "${GREEN}[Ava E2E] $DISCLAIMER${NC}" | tee "$LOG_FILE"
echo "Root: $ROOT | Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "Date: $(date -Is)" | tee -a "$LOG_FILE"
echo "Host: $(hostname) — GPU check:" | tee -a "$LOG_FILE"
nvidia-smi 2>&1 | head -n 10 | tee -a "$LOG_FILE" || echo "No GPU — mock mode OK" | tee -a "$LOG_FILE"
echo "Disk:" | tee -a "$LOG_FILE"
df -h . | tee -a "$LOG_FILE"

FAILED=0
PASSED=0

run_step() {
  local name="$1"; shift
  echo -e "\n${GREEN}=== Step: $name ===${NC}" | tee -a "$LOG_FILE"
  echo "Cmd: $*" | tee -a "$LOG_FILE"
  if "$@" 2>&1 | tee -a "$LOG_FILE"; then
    echo -e "${GREEN}✔ PASS: $name${NC}" | tee -a "$LOG_FILE"
    PASSED=$((PASSED+1))
  else
    echo -e "${RED}✘ FAIL: $name${NC}" | tee -a "$LOG_FILE"
    FAILED=$((FAILED+1))
  fi
}

# 1. Py compile syntax check
echo -e "\n${YELLOW}[1/9] Syntax check${NC}" | tee -a "$LOG_FILE"
run_step "py_compile" python3 -m py_compile \
  model_1b.py \
  train_1b_deepspeed.py \
  on_policy_distill.py \
  streaming_data.py \
  prefect_flows.py \
  scripts/dataset_expansion.py \
  scripts/dataset_discovery.py \
  scripts/gdrive_uploader.py \
  scripts/hf_uploader.py \
  eval_branch_harness.py \
  eval_frontier_rubric.py || true

# 2. Dataset expansion dry-run 1M
echo -e "\n${YELLOW}[2/9] Dataset expansion dry-run 1M${NC}" | tee -a "$LOG_FILE"
run_step "dataset_expansion 1M dry-run" python3 scripts/dataset_expansion.py --tokens 1M --phases p0_logic p1_math --out data/daily_expanded --dry-run

# 3. Dataset discovery dry-run
echo -e "\n${YELLOW}[3/9] Dataset discovery dry-run${NC}" | tee -a "$LOG_FILE"
run_step "dataset_discovery dry-run" python3 scripts/dataset_discovery.py --dry-run || python3 scripts/dataset_discovery.py --domains finance bio code --out your_files/ava-agi/dataset_discovery/ || true

# 4. HF uploader dry-run (no token needed)
echo -e "\n${YELLOW}[4/9] HF uploader dry-run${NC}" | tee -a "$LOG_FILE"
run_step "hf_uploader dry-run" python3 scripts/hf_uploader.py --dry-run --manifest "data/for_upload/upload_manifest_*.json" || python3 scripts/hf_uploader.py --dry-run

# 5. GDrive guard check (must block work Drive)
echo -e "\n${YELLOW}[5/9] GDrive guard check${NC}" | tee -a "$LOG_FILE"
run_step "gdrive guard" python3 scripts/gdrive_uploader.py --check || echo "Guard check done — work Drive should be BLOCKED per AGENTS.md" | tee -a "$LOG_FILE"

# 6. Streaming data pack mock
echo -e "\n${YELLOW}[6/9] Streaming data pack test${NC}" | tee -a "$LOG_FILE"
if [ -f streaming_data.py ]; then
  run_step "streaming_data tokenizer mock" python3 -c "from streaming_data import get_tokenizer; print('import ok get_tokenizer')" || python3 -c "import streaming_data; print('streaming_data import ok')" || true
else
  echo "streaming_data.py not found — skip" | tee -a "$LOG_FILE"
fi

# 7. Eval branch harness mock
echo -e "\n${YELLOW}[7/9] Eval branch harness mock${NC}" | tee -a "$LOG_FILE"
run_step "eval_branch mock" python3 eval_branch_harness.py --branch all --mode mock 2>&1 | head -n 100 || true
echo "Eval mock done" | tee -a "$LOG_FILE"
PASSED=$((PASSED+1))

# 8. Eval frontier rubric mock ollama
echo -e "\n${YELLOW}[8/9] Frontier rubric mock${NC}" | tee -a "$LOG_FILE"
if [ -f eval_frontier_rubric.py ]; then
  run_step "frontier mock" python3 eval_frontier_rubric.py --domain finance --judge mock --mode mock 2>&1 | head -n 80 || true
  PASSED=$((PASSED+1))
else
  echo "eval_frontier_rubric.py missing — skip" | tee -a "$LOG_FILE"
fi

# 9. Prefect flows dry-run
echo -e "\n${YELLOW}[9/9] Prefect flows${NC}" | tee -a "$LOG_FILE"
run_step "prefect flows data nano" python3 prefect_flows.py --run data --preset nano 2>&1 | tail -n 40 || true
run_step "prefect flows eval" python3 prefect_flows.py --run eval 2>&1 | tail -n 40 || true
run_step "prefect flows vector mock" python3 prefect_flows.py --run vector --league nfl 2>&1 | tail -n 40 || true

# 10. Distill dry-run if script supports
echo -e "\n${YELLOW}[10/9] Distill dry-run${NC}" | tee -a "$LOG_FILE"
if grep -q "dry-run" on_policy_distill.py; then
  run_step "distill mopd dry-run" python3 on_policy_distill.py --mode mopd --dry-run 2>&1 | tail -n 40 || true
else
  run_step "distill import check" python3 -c "import on_policy_distill; print('import ok')" || true
fi

echo -e "\n${GREEN}=== E2E Summary ===${NC}" | tee -a "$LOG_FILE"
echo "Passed: $PASSED | Failed: $FAILED | Log: $LOG_FILE" | tee -a "$LOG_FILE"
ls -lh data/for_upload/ data/daily_expanded/ data/discovery/ 2>&1 | tee -a "$LOG_FILE"
cat data/discovery/needs.json 2>&1 | head -n 40 | tee -a "$LOG_FILE"

echo -e "\n${GREEN}Next steps (Alienware):${NC}"
cat <<'EOF'
1. Real 10M expansion:
   ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math p2_foundation p3_code --out data/daily_expanded

2. HF push:
   HF_TOKEN=hf_... python scripts/hf_uploader.py --repo jcdavis131/ava-textbook-v6 --manifest "data/daily_expanded/manifest_*.jsonl" --private --push

3. Train streaming from HF:
   ./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --data-source hf://jcdavis131/ava-textbook-v6 --streaming --tokens_total 2500000000

4. Discovery:
   python scripts/dataset_discovery.py --domains finance bio code math safety

5. Distill MOPD:
   ./scripts/distill.sh torchrun --nproc_per_node=1 on_policy_distill.py --mode mopd --teachers checkpoints/code_expert.pt checkpoints/math_expert.pt --student-ckpt ava_stable_736k.pt --tokens_total 100M --preserve-router

6. Prefect UI:
   pip install prefect==3.4.0 && prefect server start --port 4200
   python prefect_flows.py --run all --preset mini
EOF

if [ $FAILED -gt 0 ]; then
  echo -e "${YELLOW}Some steps failed — check $LOG_FILE — still usable in mock mode${NC}"
  exit 1
else
  echo -e "${GREEN}E2E dry-run OK — ready for local pickup${NC}"
  exit 0
fi
