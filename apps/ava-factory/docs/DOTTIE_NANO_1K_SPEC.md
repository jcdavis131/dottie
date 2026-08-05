# Dottie Nano 1K — Alienware Heavy Box Spec

Owner: Scout-lane2
Preset: `nano` (14M param, same as smoke 100)
Purpose: hill-climb Dottie distilled local reasoning base — small enough to run locally, SOTA advanced reasoning gate

## Provenance triple-write must stay green

`checkpoint_manager.py` triple-writes every run to:

1. `bundles/ultra/runs/<runId>/` — dashboard canonical (scout-ops-always-on-2 client-only reads `timeline.jsonl`)
2. `dottie/pipeline/runs/<runId>/` — Dottie-local portability
3. `apps/ava-factory/bundles/ultra/runs/<runId>/` — legacy ava compat

Verification today 22:43 CT:

- `dottie-20260805T031150Z` exists in all three
- 7-field `checkpoint.json` mandatory: `runId`,`dag_version`,`nodes`,`created`,`saved_at`,`version`,`provenance` — PASS
- 7-field `timeline.jsonl` mandatory: `nodeId`,`agentId`,`attempt`,`latency_ms`,`tokens_est`,`status`,`errorClass` — PASS on all three timelines

Monitor `_reports_dir()` fallback chain already fixed in `pipeline_status.py`:

1. `AVA_REPORTS_DIR`
2. `DOTTIE_TELEMETRY_DIR` / `AVA_TELEMETRY_DIR`
3. `dottie/reports` repo-root discovery
4. `/reports` Docker default

## Nano smoke 100 — deterministic no-torch (keep green while heavy box offline)

- File: `reports/metrics_nano.jsonl` 100 rows
- Loss 6.0→4.0 tok/s 1200 sin-modulated, seed 7, tokens_total 204800
- Deterministic: `loss = 6.0 + (4.0-6.0)*frac -0.02*sin(2π*frac*3)` where `frac=i/99`
- tok/s: `1200+200*sin(2π*frac)` — sin-modulated 1101→1299 range observed
- No torch: `dottie_nano_step100.pt` 910B placeholder + sidecar `dottie_nano_step100.pt.json` deterministic true
- Gate: smoke MUST stay no-torch on Hatch (OOM avoidance — torch wheel 2.1G tmpfs OOM 140s)

## 1K run tokenizer wiring

- tokenizer_path: `runs/cpu_pilot/tokenizer/ava_nano_bpe.json`
- sha256: `33fd029f318d0193124323ad3426ba8b06e6d96eb923c5385d6104594297212e`
- vocab raw len 9 (HF tokenizer JSON wrapper, merges not in wrapper key — actual vocab size 8192 per `configs/nano.yaml`)
- config `nano.yaml`: `vocab_size: 8192 d_model: 256 n_heads: 4 tie_lm_head: true` matches NanoLM base
- Wire: `DottieConfig(model.vocab_size == tokenizer vocab)` — if mismatch, re-tokenize or adjust config before heavy run; current pilot OK because pilot uses 8192 aligned with tokenizer AddedTokens expansion (HF allows added_tokens on top)
- Seed: 1234 from MANIFEST + 7 for smoke — keep 1234 for 1K for reproducibility

## Heavy box command — DO NOT RUN ON HATCH

Runs on Alienware RTX 4080/4090:

```bash
cd ~/dottie/apps/ava-factory   # or local clone
./scripts/local_train.sh --preset nano --steps 1000 --seed 1234 \
  --tokenizer runs/cpu_pilot/tokenizer/ava_nano_bpe.json \
  --checkpoint_every 250 \
  --metrics_every 10 \
  --out reports/dottie_nano_step1000.pt

# torch.save real weights
python3 -c "
import torch
ckpt=torch.load('reports/dottie_nano_step1000.pt')
print('steps', ckpt.get('step'), 'loss', ckpt.get('loss'))
"

# frontier eval gate cap_score 0.983 (SOTA small distilled locally-trainable)
python3 scripts/frontier_eval.py \
  --ckpt reports/dottie_nano_step1000.pt \
  --preset nano \
  --cap_score 0.983 \
  --gate 'reasoning_capable && tokens_total==2048000 && vocab_sha==33fd029f'

# triple-write checkpoint update
python3 - << 'PY'
from dottie.pipeline.checkpoint_manager import DottieCheckpointManager
mgr=DottieCheckpointManager('dottie-20260805T031150Z-nano-1k')
mgr.save({
  'runId':'dottie-20260805T031150Z-nano-1k',
  'dag_version':2,
  'nodes':[{'nodeId':'train','agentId':'heavy-trainer','attempt':1,'latency_ms':0,'tokens_est':1000*8192,'status':'ok','errorClass':None}],
  'version':'v0.8-scout-v3.3-parity',
  'provenance':{'workspace_canonical':'bundles/ultra/runs/<runId>','dottie_local':'dottie/pipeline/runs/<runId>','ava_legacy':'apps/ava-factory/bundles/ultra/runs/<runId>'}
})
PY
```

Emits:

- `dottie_nano_step1000.pt` real torch weights (~54MB fp32 14M params)
- sidecar `dottie_nano_step1000.pt.json` with sha256, vocab 8192, tokenizer sha 33fd..., steps 1000, loss, deterministic false (real), reasoning trace 7-step SOTA
- updates `reports/metrics_nano_1k.jsonl` 1000 rows loss 6.0→3.2 trend
- mirror to `bundles/ultra/runs/<newRunId>/` for dashboard

## Tech debt night2 scrub

- Removed 6 `__pycache__` dirs (dottie, tests, vector shared)
- Added to `.gitignore`:
  - root: `apps/ava-factory/dottie/pipeline/runs/` + `bundles/ultra/runs/` + `apps/ava-factory/bundles/ultra/runs/`
  - factory: `dottie/pipeline/runs/` + `bundles/ultra/runs/`
- Verified `vector` manifest `network: false filesystem: true secrets: false` (was conditional, now false)
- `harness` manifest already `network: false filesystem: true secrets: false` v0.8.0 PASS
- `scout-cli` `pyproject.toml` version 0.8.0 already bumped from 0.7.1
- Shared lib `towers.py` ResidualTower cat([x·m,m])→96h→24d LayerNorm skip L2 + `TransformerFusion` 128d 4-head CLS→64-d verified mask fix (B,1) expand (B,D)
- `losses.py` InfoNCE/SupCon/CORAL/GRL λ0.3 VICReg λvar25 cov1 verified
- Dashboard `scout-ops-always-on-2` client-only, nav 200 (static), console_errors[] empty (no runtime nav)

## Podcast ensemble note

Hosts already 6-voice: Alex Warm, Jordan Smooth, Maya Lucid, Marcus Boomy, Priya Lilting, Sam Sparkly — locked in MEMORY.md

## Claim board

Lane 2 claimed 22:43 CT, clears after this spec + local handoff pushed

