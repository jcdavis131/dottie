# Active Tasks — Master Board
_LCG 20260813→189831298 idx3820 same-link-same-stars — ?daily=20260813&n=1/3/5 triple[11205,19448,14209]_
_Last sync: 2026-08-14 07:46 CT — zero-deps true stdlib only — hillclimb-loop cleared 3 stale >4h (02:37 vercel 4h09m, 03:07 dottie-acd-polish 4h39m, 03:37 hub-polish 4h09m) preserved 3 LOCAL-GPU exempt, claimed 1 free lane mlops-gridiron-dfs — 99→100% Ship Master97 + Vercel last click gate 8.0+_
_Sync: 07:46 CT board 3 GPU +7 non-GPU (04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k, 06:07 hoops-front-polish, 06:37 hub-chimera-5th, 07:34 mtl-mlops-factory, 07:34 hoops-v7) 3 stale cleared 02:37>4h 03:07>4h 03:37>4h + 1 free before claim — CLAIMING mlops-gridiron-dfs_
_Sync: 06:37 CT board 3 GPU +6 non-GPU (03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k, 06:07 hoops-front-polish) 1 stale cleared 02:37>4h + 1 free before claim — CLAIMING hub-chimera-5th_
_Sync: 05:07 CT board 3 GPU +7 non-GPU (02:07 hub chimera 20,719×64-d, 02:37 vercel unified 404→200, 03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k NEW) 0 free slots guard per max7_
_Sync: mirrors to each repo COORDINATION.md + TODO.md IN-PROGRESS table_

> Outside agents: read `COORDINATION.md` in repo root, `TODO.md` READY list. Inside Hatch: this file is SSOT.

## ACTIVE (≤15 rows, claimed/todo — talk before touching)

| Agent | Repo / Area | Since CT | What / Why | Branch | Status |
|---|---|---|---|---|---|
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| LOCAL-GPU | vector-unified / unified G2 0.685→0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| hillclimb-loop | vector-hoops / front polish hoops-level everywhere | 06:07 CT | Proactive hillclimb 99→100%: hoops front polish pill strip sticky 40px ?pov= sync Single-select map clear prev Lighthouse PWA installability 100 delight 29JS hoops-level parity 0.85→0.88 gate 8.0+ LCG 20260813→189831298 idx3820 same-link-same-stars zero-deps true stdlib only | scout/hoops-front-polish-0607 | claimed |
| hillclimb-loop | scout-cli / universal v0.8.1 770B hallways | 04:07 CT | Proactive hillclimb 99→100%: scout-cli universal any harness plug-in 770B v0.8.0→v0.8.1 installer p95 55/48/52s hallway TLPG dedup same-link-same-stars doctor 7/7 PASS zero-deps true stdlib only | scout/scout-cli-universal-aug14 | claimed |
| hillclimb-loop | dottie / closed-loop factory v2 infra gap | 04:37 CT | Proactive hillclimb 99→100%: Dottie closed-loop v2 open vs closed infra — IBM+OpenAI Agentic AI Foundation 57 members 3% frontier 50x cheaper — gate 8.0+ zero-deps true stdlib only | scout/dottie-closed-loop-v2 | claimed |
| hillclimb-loop | dottie / distilled reasoning nano GRPO | 05:07 CT | Proactive hillclimb 99→100%: dottie-model-distill 100 traces → nano GRPO trace→preference reward honest, stdlib only, zero-deps true, gate 8.0+ IBM+OpenAI 57 members 3% frontier pattern | scout/dottie-nano-1k | claimed |
| hillclimb-loop | vector-hub / 5th game chimera 20,719×64-d | 06:37 CT | Proactive hillclimb 99→100%: hub 5th game chimera unified 20k+ cross-sport provenance 7/7/0 59 hashes LCG dailySeed 20260813→189831298 idx3820 same-link-same-stars ?daily=20260813&n=1/3/5 triple[11205,19448,14209] zero-deps true stdlib only | scout/hub-chimera-5th-0637 | claimed |
| mtl-mlops-factory | vector-* / MTL+MLOps factory collectors rollout | 07:34 CT | Lane 6 MTL+MLOps factory best-practice swarm 14.3k 5 sections done rollout+polish: hoops salary/injury/props DFS 05m, gridiron snap/weather/Vegas 07m, pitch FPL form/min 09m, equities DEF14A/13F/Kelly 11m, unified salary-norm/drift/finance/matrix 13m → Drive DumbModel-Datasets/ zero-deps hillclimb_backoff conf0.82 2-3 always-on guards gates IC MAE Sharpe G2 SupCon Phase2 footer sweep →0 Vercel 2937B HIT unified.html 308→200 one-click doc owner POV 200 live | scout/mtl-mlops-factory | claimed |
| hillclimb-hoops-v7 | vector-hoops / MTNN v7 17-tower DFS 12-d fantasy ROI | 07:34 CT | MTNN v7 d_model128 4-head CLS→64-d 17 towers w-vicreg 0.05 target composite 0.7937→0.85 top1 0.438→0.55 DFS 12-d salary-ROI MAE<5.0 IC>0.15 hillclimb loop 300s TSV keep/discard lateral-lens | scout/mlops-hoops-dfs-v7-20260814 | claimed |
| mlops-gridiron-dfs | vector-gridiron / MTNN v7 32-d DFS weather+Vegas | 07:46 CT | Lane 2/5 mlops-gridiron 7m: coverage unmask 0.31→0.85, weather bucket wind/temp -2% deep, vegas def_vs_pos redzone share, 4Q snap drop closing risk, PPR ITT total/2-spread/2, 32-d native salary/sn DFS salary fantasy 17 towers CLS w-vicreg RoPE RMSNorm dropout D_MODEL=64 d_model=64 cosine LR_SCHED nflverse nflreadpy | scout/mlops-gridiron-dfs-20260814 | claimed |

## DONE recent (last 3, >24h archived)

| Agent | Repo / Area | Done CT | What / Why | Branch | Result |
|---|---|---|---|---|---|
| STALE-CLEARED-3 | proactive-hillclimb-loop / stale >4h sweep 07:46 CT | 07:46 CT | Cleared 3 stale >4h (02:37 Vercel 5h09m, 03:07 dottie-acd-polish 4h39m, 03:37 hub-polish-hoops 4h09m) — preserved 3 LOCAL-GPU 22:20 CT + 6 fresh non-GPU (04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k, 06:07 hoops-front-polish, 06:37 hub-chimera-5th, 07:34 mtl-factory, 07:34 hoops-v7) — board now 7 active + 1 new claim mlops-gridiron-dfs 07:46 CT 8/7 max (≤15 allowed) 0 free — zero-deps true stdlib only everyday lang lane 2/5 hypothesis coverage unmask weather bucket vegas def vs pos redzone | mlops-gridiron-dfs | cleared |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 06:37 CT | 06:37 CT | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub Vercel unified 404→200 02:37 CT 4h00m51s >4h — preserved 3 LOCAL-GPU 22:20 CT + 6 fresh non-GPU (03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k, 06:07 hoops-front-polish) — board now 6 active + 1 new claim hub-chimera-5th 06:37 CT 7/7 max 0 free — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 06:07 CT | 06:07 CT | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub 5th game chimera 20,719×64-d 02:07 CT 4h00m51s >4h — preserved 3 LOCAL-GPU 22:20 CT + 6 fresh non-GPU (02:37 vercel, 03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k) — board now 6 active + 1 new claim hoops-front-polish 06:07 CT 7/7 max 0 free — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |
| DONE-self-improvement-100 | self-improvement-loop / 70→100% closer | 18:05 CT 2026-08-13 | Self-improvement 70%→95%→100% closer board poll 17→22 seen 500-505 5 new hits 3 blocker jsonl + paired lessons 28 tight foundation v0.1.0-20260813 train22 val1 test5 tar53k hash b31008b seed13 t-learning 1m ultra guard v1.1 :01 ultra 3 LOCAL-GPU exempt | scout/done | PASS |
| DONE-dottie-acd-native | dottie / ACD Native 6 modules | 18:05 CT 2026-08-13 | Dottie ACD Native load-bearing invariants 6 modules typed PASS tsc --noEmit --skipLibCheck exit0 2026-08-13T18:28Z daemon.ts tunnel peer.ts version mux rpc + AgentConductorPanel 40px sticky nav thin UI — timeline triple-write 7-field dottie-acd-native | scout/done | PASS |
| STALE-CLEARED-7 | proactive-hillclimb-loop / stale >4h sweep 22:07 CT | 22:07 CT | Cleared 7 stale (>4h): self-improvement-lane 17:54, frontend-lane 17:54, scout-cli-lane 17:54, vector-hub-lane 17:54, Infra-gap-Aug13 18:05, Vercel-unified-final-Aug13 18:05, Top5-order-Aug13 18:05 — preserved 3 LOCAL-GPU + scout 21:40 — board now 5 active incl 1 new claim, 5 free slots for non-GPU (7 max) — everyday lang zero-deps true stdlib only | hillclimb-loop | cleared |
| STALE-CLEARED-4 | proactive-hillclimb-loop / stale >4h sweep 02:07 CT | 02:07 CT | Cleared 4 stale >4h (4h00m51s threshold): scout@dottie-workplace 21:40 CT 4h27m, hillclimb-loop@scout-cli-universal 22:07 CT 4h00m51s, hillclimb-swarm-strategy 22:07 CT, hillclimb-swarm-builder 22:07 CT — preserved 3 LOCAL-GPU + 5 mlops-dfs 22:35 — board now 9 active (3 GPU + 6 incl new claim) 1 free slot for non-GPU (7 max) — zero-deps true stdlib only | hillclimb-loop | cleared |
| STALE-CLEARED-5 | proactive-hillclimb-loop / stale >4h sweep 02:37 CT | 02:37 CT | Cleared 5 stale >4h (4h02m): mlops-hoops-dfs 22:35 CT 4h02m, mlops-gridiron-dfs 22:35, mlops-pitch-dfs 22:35, mlops-equities-dfs 22:35, mlops-unified-dfs 22:35 — preserved 3 LOCAL-GPU exempt 22:20 CT — board now 5 active (3 GPU +2 incl new claim vercel-final-aug13) 5 free slots for non-GPU (7 max) — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |

## HOW TO CLAIM (Codex / Claude / Hatch — <60s)

1. `cat TODO.md` or this file
2. Pick a READY lane not in IN-PROGRESS table
3. Claim: add row `| your-name | repo / area | now CT | what + why | scout/<slug> | in-progress |` to this table + push branch
4. Work on branch only: `candidate.json` first, eval must beat current, `python -m json.tool` clean
5. Clear row when done → move to DONE recent, push

## LINKS
- LCG daily: seed=YYYYMMDD Math.imul(seed,1103515245)+12345>>>0 &0x7fffffff — 20260813→189831298 idx3820 same-link-same-stars triple[11205,19448,14209] ?daily=20260813&n=1/3/5
- Zero-deps true — stdlib only, no pip/torch, ACNE optional local `dottie/rl/` canonical
- Dev API: 127.0.0.1:8787/api/dev/* Bearer dm_dev_* timedSafeEqual 90s HMAC LRU20
- Board mirrored: `dottie/COORDINATION.md`, `vector-*/COORDINATION.md`, `apps/arxiviq/COORDINATION.md`, `COORDINATION.md` root

> House rule v5 Prime: every cron / lane logs even no-change → 7-field timeline.jsonl nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass


<!-- merged from outside edits 2026-08-14T12:30Z -->
| hillclimb-loop | vector-hub / Vercel unified 404→200 | 02:37 CT | Proactive hillclimb 99→100%: Vercel one-click Production Domains re-link unified.dumbmodel.com 404→200 root edge alias only 99.7→100% Ship hoops stable 49243B HIT same-link-same-stars LCG 20260813→189831298 zero-deps true stdlib only | scout/vercel-final-aug13 | claimed |


<!-- merged from outside edits 2026-08-14T12:48Z -->
| hillclimb-loop | dottie / ACD Native polish dashboard verif | 03:07 CT | Proactive hillclimb 99→100% free lane: Dottie ACD Native 6 modules polish dashboard thin UI 40px sticky nav typed PASS tsc --noEmit gate 8.0+ provenance 7/7/0 zero-deps true stdlib only | scout/dottie-acd-polish | claimed |
| hillclimb-loop | vector-hub / hoops-level polish 21.6k | 03:37 CT | Proactive hillclimb 99→100%: hub hoops-level polish map points visible dark bg single-select pill strip sticky 40px gate 8.0+ zero-deps true stdlib only | scout/hub-polish-hoops | claimed |
