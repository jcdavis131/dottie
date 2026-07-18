# Continuous Pipelines — Ava + Dumb Models
Solo personal project, no connection to employer, built with public/free-tier only

## Architecture

```
[Gather] -> [Curate/Clean] -> [Tokenize/Pack] -> [Train] -> [Distill MOPD] -> [Eval] -> [Deploy]
   ^                           ^                  ^           ^            ^         ^
   | cron 08:00 UTC            | cron daily       | weekly Sun 03:00 | daily 09:00 | vector daily 12:00 UTC
   | Prefect retry 3x          | streaming_data   | deepspeed      | Ollama judge | Vercel webhook
```

### Prefect Server (Free Self-Hosted)
- `pip install prefect==3.4.0`
- `prefect server start --port 4200`  # UI at http://localhost:4200
- All flows use `OLAMA_HOST=http://host.docker.internal:11434` to talk to host Ollama (qwen3:32b)
- No YAML, no DSL — just @flow/@task decorators, retries, version tracking

### Hatch Cron Jobs (Created)

| ID | Schedule | What | Tokens / Note |
|---|---|---|---|
| `ava-data-gather-daily` | daily 08:00 UTC | logic_textbook_pipeline p0-p3 100M tokens, tokenizer build, pack shards | 100M legacy, use expansion now |
| `ava-data-gather-4h` | interval 4h (00,04,08,12,16,20 UTC) | **dataset_expansion.py** incremental shards simhash dedup threshold 3, quality alpha>0.6 reward>0.8, content-addressable sha12, 50MB gzipped | **500K per run in Hatch VM** (35s ~5k docs, 150KB gz), 10M on Alienware = 60M/day 1.8B/month |
| `dataset-discovery-daily` | daily 14:00 UTC | **dataset_discovery.py** reads branch_eval_results weak domains -> HF candidates search public API, license filter MIT/Apache2/CC0 | No download in VM, writes candidates json + download sh for Alienware |
| `ava-eval-distill-daily` | daily 09:00 UTC | branch harness + frontier rubric via Ollama + distill dry-run | Ollama qwen3:32b fallback mock |
| `vector-dumb-models-daily` | daily 12:00 UTC (06:00 CDT) | nflverse/StatsBomb/ESPN ingest -> per-100 z-score -> PCA embeddings -> Vercel deploy | + deploy hook |
| `ava-training-weekly` | weekly Sun 03:00 UTC | torchrun nano/mini/base1b incremental WSD 736k stable 92% | Deepspeed Zero3 bf16 |

Live tested 2026-07-11: 500K tokens run succeeded in 35s, 5048 docs, 13.5k dup filtered, 10.8k qual filtered, 150KB gzipped shard + 1.7M manifest. Guard correctly blocked work Drive @meta.com (gchak_health.json, lockedunn_health.json owners).

Plus existing: cash-drag-watcher 02:00, fidelity screenshot Mon 09:00 CT, hatch-backup-daily 02:00

### For your Alienware (RTX 4090 24GB + Docker + Ollama)

Local crontab to add (`crontab -e`):

```cron
# Ava data - 2am Central daily legacy
0 2 * * * cd ~/ava-agi-factory-v6-4 && ./scripts/local_train.sh python logic_textbook_pipeline.py --phases all --out data/daily/raw --tokens 100M >> logs/cron-data.log 2>&1

# Ava expansion - every 4h 10M tokens (10M = ~50k docs, use 10M on 4090, 500K in Hatch VM)
0 */4 * * * cd ~/ava-agi-factory-v6-4 && python3 scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math p2_foundation p3_code --out data/daily_expanded --upload-mode local >> logs/cron-expansion.log 2>&1
# Optional R2 upload if creds set: --upload-mode r2
# Optional GDrive check: && python3 scripts/gdrive_uploader.py --check

# Dataset discovery - daily 2pm UTC / 9am Central - read eval weak domains -> HF candidates
0 9 * * * cd ~/ava-agi-factory-v6-4 && python3 scripts/dataset_discovery.py --domains finance bio code math safety --out your_files/ava-agi/dataset_discovery/ >> logs/cron-discovery.log 2>&1
# Then manual review: cat your_files/ava-agi/dataset_discovery/candidates_*.json | grep license_ok true
# Download on Alienware: bash your_files/ava-agi/dataset_discovery/download_candidates_*.sh

# Ava train - Sun 3am Central weekly incremental
0 3 * * 0 cd ~/ava-agi-factory-v6-4 && ./scripts/local_train.sh torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset mini --tokens_total 2500000000 --resume-if-exists >> logs/cron-train.log 2>&1

# Eva eval - 3am Central daily
0 3 * * * cd ~/ava-agi-factory-v6-4 && OLLAMA_HOST=http://host.docker.internal:11434 OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama >> logs/cron-eval.log 2>&1

# Vector models - 6am Central daily
0 6 * * * cd ~/ava-agi-factory-v6-4 && python prefect_flows.py --run vector --leagues all >> logs/cron-vector.log 2>&1
```

**Drive upload (efficient downstream, HOME/Work guard):**
- Current Hatch VM Drive is **WORK** `camd@meta.com` detected via `gchak_health.json` owner `gchak@meta.com` + `lockedunn_health.json` → **BLOCKED** correctly per AGENTS.md absolute separation
- Guard: `python scripts/gdrive_uploader.py --check` → aborts if work indicators
- To enable: connect personal Drive `jcdavis131@gmail.com` in Hatch (not work) OR set R2 env `CLOUDFLARE_R2_ACCESS_KEY/SECRET/ENDPOINT/BUCKET=ava-datasets`
- Then: `python scripts/gdrive_uploader.py --upload data/daily_expanded/ --folder Ava-Datasets-Expansion --dry-run` then real
- Efficient: content-addressable filename = sha12, incremental manifest.jsonl append-only, 50MB gzipped shards, batch 2 workers retry 3x
- Fallback local: `data/for_upload/upload_manifest_*.json` copy via `rsync -avz data/daily_expanded/ alienware:~/ava-agi-factory-v6-4/data/daily_expanded/`

**Discovery → Ingestion Loop (new):**
- Run on Alienware (not Hatch VM disk-limited): `python scripts/dataset_discovery.py --domains finance bio code`
- Review `your_files/ava-agi/dataset_discovery/candidates_*.json` for `license_ok:true` (MIT/Apache2/CC0/CC-BY)
- Candidates include: financial_phrasebank, convfinqa, finqa, pubmed_qa, medmcqa, the_stack, code_search_net, metamath-qa, gsm8k, open-web-math
- Download script `download_candidates_*.sh` has `datasets.load_dataset` commands for offline inspection
- Ingest: `./scripts/local_train.sh python streaming_data.py --use_raw data/raw/finance/ --pack --seq 2048`
- Tested 2026-07-11: forced domains finance,bio,code,math,safety → 58 candidates, download sh generated

### Prefect Deployment Commands (Alternative to cron)

```bash
# Inside Docker
prefect deployment build prefect_flows.py:ava_full_pipeline -n ava-daily --cron "0 8 * * *" --pool default-agent-pool -q ava-queue
prefect deployment build prefect_flows.py:daily_vector_flow -n vector-daily --cron "0 12 * * *" --pool default-agent-pool -q vector-queue
prefect agent start -q ava-queue
prefect agent start -q vector-queue
```

### Distillation Pipeline (New - MOPD from HF blog)

Implements https://huggingface.co/blog/sergiopaniego/distillation-2026 :

1. Train 3 separate RL experts (same size 1.17B) per domain: code, math, agentic/chat - each YaRN 1M RoPE
2. Student (unified) generates own rollouts (on-policy)
3. For each token, teachers grade: reverse KL KL(p_student || p_teacher) dense signal
4. Cost ~1/10 GPU hours vs RL (Qwen3 claim)
5. Optional privileged hint (Cursor Composer 2.5) and earlier-teacher continual learning (Thinking Machines)

Run:
```
./scripts/distill.sh torchrun --nproc_per_node=1 on_policy_distill.py --mode mopd --teachers ckpts/code_expert.pt ckpts/math_expert.pt ckpts/chat_expert.pt --student-ckpt ava_stable_736k.pt --tokens_total 100M --preserve-router
```

### Dumb Models Details

**Vector Hoops** (12,392 player-seasons 1996-2026):
- Daily ingest nflverse/basketball-ref via @task retries 5x60s on 500
- Compute per-100 z-scored within season, PCA(3) 8 archetypes
- Build flow SVG truthful topology

**Vector Gridiron** (fantasy MAE 4.268 R2 0.39):
- nflverse no tracking, usage/snaps/weather/Vegas
- Next-game task daily

**Vector Pitch** (633 WC tournaments):
- StatsBomb per-90 tournament z-scored

All deploy via Vercel webhook if VERCEL_DEPLOY_HOOK_URL set.

### Observability

- Hatch: activity feed /spaces_actions
- Prefect: http://localhost:4200 dashboard - flow runs, retries, logs, version
- Logs: your_files/ava-agi/runs/, logs/builder.log, your_files/vector-daily/

### E2E Test (New)

- `./scripts/e2e_test.sh` — runs all steps mock-friendly without GPU/HF_TOKEN/Ollama:
  1. py_compile
  2. dataset_expansion 1M dry-run
  3. dataset_discovery
  4. hf_uploader dry-run
  5. gdrive guard check (blocks work Drive)
  6. streaming_data import
  7. eval_branch mock
  8. frontier mock
  9. prefect flows data/eval/vector
  10. distill import
  Logs to `logs/e2e_test_TIMESTAMP.log` + manifests in `data/for_upload/`

- For real pickup: see `docs/LOCAL_PICKUP.md`

### 2-Loop HF Hub Architecture (New)

- **Loop 1 Data (4h):** dataset_expansion.py 10M shards simhash dedup 50MB gzipped content-addressable sha12 → manifest.jsonl → hf_uploader.py push_to_hub train/val/test 92/6/2 parquet → private repo jcdavis131/ava-textbook-v6
- **Loop 2 Model (weekly / on-demand):** streaming_data.py loads via `load_dataset(..., streaming=True)` → torchrun deepspeed Zero3 bf16 per-rank shard streaming WSD 736k stable → eval Ollama → MOPD distill reverse KL
- **Efficient downstream:** manifest includes HF URLs + sha + local paths, usable on Alienware via scp/rclone, no work Drive upload (guard blocks camd@meta.com)
- **Command:** `HF_TOKEN=... python scripts/hf_uploader.py --repo jcdavis131/ava-textbook-v6 --manifest "data/daily_expanded/manifest_*.jsonl" --private --push`

### Solo Disclaimer
All pipelines: public pip only (torch, transformers, prefect), free-tier R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, local Ollama qwen3:32b. No work data/code/systems. Footer: "Solo personal project, no connection to employer, built with public/free-tier only"
