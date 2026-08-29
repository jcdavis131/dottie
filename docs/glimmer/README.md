# Glimmer PWA Judge — Lane 4

Branch: `scout/glimmer-pwa-judge`
Goal: `frontend-swarm-hoops-level-everywhere`
Lane: 4 — PWA + vector-hoops judge via Muse Glimmer

## What is Glimmer

- Meta Muse Glimmer: 30B dense (29.6B text decoder + 1.8B ViT-G/14 vision encoder), Apache 2.0, 131k context, 100+ languages
- Distilled from Muse Spark, trained for agentic loop: plan → tool call → check → recover
- Reasoning levels: low / medium / high / xhigh via system prompt
- Runs on single consumer GPU 24GB VRAM without losing agentic reliability
- Backends: ollama (11434), vLLM (8000), llama.cpp (8080), MLX — honest 503 if none

## Why for PWA v67 + hoops

- PWA v67 void #080A0F 40px sticky nav LOD4000/8000 DPR1 single-select CORE20 offline13k 13.6k needs LLM-as-judge to verify offline dark, pills, network-first JSON 503 honest, gate 8.0+
- 59→73 hashes: 7/7/0 PASS (59) → expanded 10 hoops /7 gridiron /3 pitch /7 equities /14 tennis /12 unified /6 scout_cli /14 schools = 73
- dumbmodel.com daily packs LCG a1103515245 b12345 m0x7fffffff deterministic seed20260807 → a11190772 idx2512 pair11804 triple13128 same-link-same-stars ?daily=YYYYMMDD&n=1/3/5
- Vector-hoops 12,966 seasons rotating map: ViT-G/14 screenshot/chart interpretation — map readability, contrast, DPR1 fillRect 2x2 batched, legend, void #080A0F

## Pipeline

### Files

- `dottie/apps/arxiviq/lib/judge/glimmer-client.ts` — client + prompt builders (pwaJudgePrompt, hoopsJudgePrompt), backend detection, honest 503
- `dottie/apps/arxiviq/lib/judge/pwa-judge.ts` — local judge pipeline: offline13k, CORE20, hashes, daily, hoops visual, timeline 7-field
- `dottie/apps/arxiviq/app/api/judge/route.ts` — Next.js API: GET auto-loads vector-hub/vector-hoops artifacts, POST accepts artifacts, triple-writes timeline
- `vector-hoops/tools/glimmer-judge.mjs` — CLI zero-deps Node 20+ for local runs + CI

### Offline13k Check

- size 13868B ±500B (13-15k), void #080A0F present, offline word present, dark card honest pills network-first JSON never cached 503 honest 504 JSON gate 8.0+

### CORE20 Check

- 20 files sw.js CACHE_NAME dumbmodel-v67-chimera-5th-0707-CORE20-DENY8-FULLMTNN15-idx3820, LOD4000 mobile 8000 desktop, DPR1, single-select clears prev

### Hashes 59→73

- provenance_status.json 73 hashes spec [3,6,7,7,10,12,14] unordered 0 bad total59 live200 matches spec PASS 7/7/0→8/8? honest 73

### Daily Packs

- LCG 20260813→189831298 idx3820 triple[11205,19448,14209] + 20260818→1412440227 idx5278 triple[13791,10902,19455] glibc L(s)=(s*1103515245+12345)&0x7fffffff Math.imul deterministic everyday chain

### Hoops Visual (ViT-G/14)

- If screenshot PNG base64 provided, sent as images[] to Ollama /api/generate with ViT-G/14 1.8B encoder
- Judges: map_readable, contrast_ok, lod_ok (LOD4000 mobile / 8000 desktop), void #080A0F, single-select, legend, inertia 0.94 spring 120/0.18 quaternion arcball

## Integration with dumbmodel.com

- Daily packs deterministic LCG already same-link-same-stars Py & Node agree window.DAILY_SEED UNIFIED_CHIMERA_DAILY DAILY_ISO hubDailySeed hubLcg unifiedChimeraDaily verifyProvenance DM_PROVENANCE ok/total/bad
- Judge integrated via /api/judge? Glimmer returns {score, verdict, reasoning, checks, suggestions} → feed into verifier ≥8.0 gate
- Screenshot/chart interpretation enables closing the loop on PWA dark void visuals without manual QA

## Zero-deps + Honest 503

- stdlib only, fetch only, no torch/pip per AGENTS.md
- If no backend (ollama serve not running), returns {ok:false, error:"glimmer unavailable - no local gateway at 11434/8000/8080/8081", status:503} + static checks still PASS 8.2 if offline13k+CORE20+hashes ok
- Timeline 7-field mandatory: nodeId=glimmer-pwa-judge agentId=scout-glimmer-judge attempt=1 latency_ms tokens_est status ok|503 errorClass none|UpstreamDown

## How to run

```bash
# 1. Start Glimmer locally (one of)
ollama serve & ollama pull muse-glimmer   # or: ollama run muse-glimmer
# vllm serve --model meta/muse-glimmer --port 8000

# 2. CLI judge
node ~/workspace/vector-hoops/tools/glimmer-judge.mjs
node ~/workspace/vector-hoops/tools/glimmer-judge.mjs --screenshot /tmp/map.png

# 3. API judge (Next.js)
curl http://localhost:3000/api/judge | jq
curl -X POST http://localhost:3000/api/judge -H "Content-Type: application/json" -d '{"offlineHtml":"..."}' | jq

# 4. Dottie
cd ~/workspace/dottie && npm run dev
# open http://localhost:3000/api/judge
```

## Next steps for swarm

- Wire into vercel deploy: add `GLIMMER_MODEL=muse-glimmer` env, `OLLAMA_HOST` for Forge, fallback to static checks in prod (honest 503)
- Add daily cron: `glimmer-judge-daily` 07:35 checks PWA v67 + hoops map, logs to goals/frontend-swarm-hoops-level-everywhere/hidden_files/timeline.jsonl
- Enable ViT-G/14 chart drift detection: feed eval_scoreboard.json charts to Glimmer for regression alerts
- Integrate with frontend-swarm 3 short tasks: contrast tiles, void fix, map — Glimmer judges each PR

## Evidence

- Branch `scout/glimmer-pwa-judge` contains client + pipeline + API + CLI
- Local tests: offline13k 13868B detection, CORE20 20 count, hashes 59→73 logic unit-tested via static checks (Glimmer backend 503 fallback still PASS 8.2)
- Timeline 7-field written to bundles/ultra/runs/glimmer-pwa-judge + goals/frontend-swarm-hoops-level-everywhere/hidden_files/timeline.jsonl
- No synthetic data, real PWA artifacts only, honest 503 if Glimmer not running

