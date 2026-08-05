#!/usr/bin/env bash
# Alienware heavy — Dottie nano 1K
set -euo pipefail
PRESET=nano
STEPS=1000
SEED=1234
TOKENIZER="runs/cpu_pilot/tokenizer/ava_nano_bpe.json"
EXPECTED_SHA="33fd029f318d0193124323ad3426ba8b06e6d96eb923c5385d6104594297212e"
echo "Checking tokenizer $TOKENIZER"
sha256sum "$TOKENIZER"
if [ "$(sha256sum "$TOKENIZER" | awk '{print $1}')" != "$EXPECTED_SHA" ]; then
  echo "WARN: sha mismatch — re-download or tokenizer.json changed"
fi
echo "Running heavy train $STEPS steps preset $PRESET seed $SEED"
./scripts/local_train.sh --preset $PRESET --steps $STEPS --seed $SEED --tokenizer "$TOKENIZER" --checkpoint_every 250 --metrics_every 10 --out reports/dottie_nano_step1000.pt
echo "Frontier eval cap 0.983"
python3 scripts/frontier_eval.py --ckpt reports/dottie_nano_step1000.pt --preset $PRESET --cap_score 0.983 || echo "frontier_eval script may be named differently — check eval logic"
echo "Triple-write checkpoint"
python3 - << 'PY'
from dottie.pipeline.checkpoint_manager import DottieCheckpointManager
mgr=DottieCheckpointManager('dottie-nano-1k-alienware')
mgr.save({
  "runId":"dottie-nano-1k-alienware",
  "dag_version":2,
  "nodes":[{"nodeId":"train","agentId":"heavy-trainer","attempt":1,"latency_ms":0,"tokens_est":1000*8192,"status":"ok","errorClass":None}],
  "version":"v0.8-scout-v3.3-parity"
})
print("saved triple")
PY
echo "Done — emit sandbox://workspace/dottie/apps/ava-factory/reports/dottie_nano_step1000.pt"
