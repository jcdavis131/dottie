#!/bin/bash
# Solo personal project, no connection to employer, built with public/free-tier only
# Hatch VM Always-On — lightweight data gather + discovery + eval + ecosystem update
# Designed to be called from Hatch crons every 4h, but can loop if needed
set -e
cd "$(dirname "$0")/.."
echo "[Dottie Hatch] $(date -Is) — lightweight loop"

python scripts/dataset_expansion.py --tokens 500K --phases p0_logic p1_math p2_foundation --out data/daily_expanded --upload-mode local || true
python scripts/dataset_discovery.py --eval-results frontier_eval_results.json branch_eval_results.json --out data/discovery/needs.json || true
python eval_branch_harness.py --branch all --mode mock || true
python eval_frontier_rubric.py --domain all --judge mock --mode mock || true

# Ecosystem update: run llmvm kernel audit cell + skillbook list
python -c "
from dottie.llmvm import ToolRegistry
try:
    from dottie.llmvm.tool_registry import create_dottie_registry
    reg = create_dottie_registry()
    print(f'Tools registered: {len(reg._metadata)}')
except Exception as e:
    print(f'LLMVM check failed: {e}')
" || true

# Update STATUS
python -c "
import json, datetime, pathlib
p=pathlib.Path('STATUS.json')
j=json.loads(p.read_text()) if p.exists() else {}
j['last_hatch_loop']=datetime.datetime.utcnow().isoformat()+'Z'
p.write_text(json.dumps(j, indent=2))
"

git add STATUS.json reports/ data/discovery/ data/manifest.jsonl 2>/dev/null || true
git commit -m "auto: hatch continuous $(date -Is) 500K expansion" || true
git push origin main || true
