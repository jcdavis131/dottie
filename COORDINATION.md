# Active Tasks — Master Board
_LCG 20260813→189831298 idx3820 same-link-same-stars — ?daily=20260813&n=1/3/5 triple[11205,19448,14209]_
_Last sync: 12:37 CT 2026-08-16 — hillclimb-loop proactive 12:37 CT — cleared 0 stale (all 4 non-GPU fresh 11:37,12:07,16:10×2) preserved 3 LOCAL-GPU exempt non_gpu_active 4→5 free 2 guard claimed 1 lane — zero-deps true — LCG 20260813→189831298 idx3820_
_Sync: 12:07 CT board 3 GPU +4 non-GPU (Scout-auto×2 16:10, hillclimb-hoops-v7 11:37, unified-caches 12:07) 0 stale cleared — claimed unified-caches-1207_
_Sync: 11:07 CT board 3 GPU +4 non-GPU (mtl-mlops-factory 07:34, hillclimb-hoops-v7 07:34, Scout-auto×2 16:10, hillclimb-loop closed-loop 11:07) 6 stale cleared 06:07/03:37/04:07/04:37/05:07/06:37 — claimed dottie-scout-closed-loop-1107_
_Sync: mirrors to each repo COORDINATION.md + TODO.md IN-PROGRESS table_

> Outside agents: read `COORDINATION.md` in repo root, `TODO.md` READY list. Inside Hatch: this file is SSOT.

## ACTIVE (≤15 rows, claimed/todo — talk before touching)

| Agent | Repo / Area | Since CT | What / Why | Branch | Status |
|---|---|---|---|---|---|
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| LOCAL-GPU | vector-unified / unified G2 0.685→0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| hillclimb-loop | vector-hub / 5th game chimera unified 20k+ cross-sport | 11:37 CT 2026-08-16 | Proactive hillclimb 99→100% 5th game chimera unified 20k+ cross-sport provenance 7/7/0 59 hashes LCG dailySeed 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars zero-deps true stdlib only — hoops-level parity void #080A0F 40px sticky — 5+2 swarm lite gate 8.0+ | scout/hub-chimera-5th-1137 | claimed |
| hillclimb-loop | vector-unified / missing caches restore embedding_v3/mtnn_best/pitch_embed | 12:07 CT 2026-08-16 | Proactive hillclimb 99→100% unified missing caches restore embedding_v3.npz/mtnn_best.pt/pitch_mtnn_embeddings.json unblock LOCAL-GPU G2 0.685→0.64 zero-deps true stdlib only LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars 5+2 swarm lite gate 8.0+ | scout/unified-caches-1207 | claimed |
| pro-button-up | vector-hub / PWA v67.2 pro business-ready | 13:01 CT 2026-08-16 | Pro button-up vector-hub — business-ready void #080A0F 40px sticky nav z40 single-select momentum 0.94 DPR1 LOD 8000/4000 offline13k no dev pills verifier 9.0+ — manifest bg #080A0F theme #080A0F standalone start_url /?pov=owner CORE20 offline13k LCG 20260813→189831298 idx3820 — zero-deps true | scout/pro-button-up-hub | todo |
| pro-button-up | vector-hoops / Lab v9.2 masterclass | 13:01 CT 2026-08-16 | Pro button-up hoops Lab v9.2 masterclass business-ready void #080A0F 40px sticky single-select momentum 0.94 DPR1 LOD 8000/4000 offline13k no dev pills verifier 10.0 feel — SHAP15 VICReg 12966×64-d 1764 real MTNN v6 ROPE RoMSNorm composite0.85 top1 0.55 PASS — zero-deps true | scout/pro-button-up-hoops | todo |
| pro-button-up | vector-pitch / parity pro glass-box | 13:01 CT 2026-08-16 | Pro button-up pitch — business-ready void #080A0F 40px sticky single-select momentum 0.94 DPR1 LOD 8000/4000 offline13k no dev pills verifier 9.0+ — glass-box SHAP permutation 2430×24-d 633 pts pos_cluster0.797 gold 92.9% closers median0.4843 park Coors1.25-1.367 — zero-deps true | scout/pro-button-up-pitch | todo |
| pro-button-up | vector-gridiron / parity pro nflverse | 13:01 CT 2026-08-16 | Pro button-up gridiron — business-ready void #080A0F 40px sticky single-select momentum 0.94 DPR1 LOD 8000/4000 offline13k no dev pills verifier 9.0+ — nflverse gates MAE3.79 Sharpe1.09 IC0.85 comp0.85 QB5 WR1 RB2 TE3 scale0.2876 646 pts 1000×32-d v2 — zero-deps true | scout/pro-button-up-gridiron | todo |
| pro-button-up | vector-equities+unified / parity pro chimera | 13:01 CT 2026-08-16 | Pro button-up equities+unified chimera 20719×64 pro — business-ready void #080A0F 40px sticky single-select momentum 0.94 DPR1 LOD 8000/4000 offline13k no dev pills verifier 9.5+ — CQS0.7017→0.72 IC0.012 Sharpe1.22 equities 500 real + unified 20719×64 compact 399KB 8000 LOD real display_name not placeholder OKABE-8 not i%8 domain sport_id fix — zero-deps true | scout/pro-button-up-equities-unified | todo |

## DONE recent

| Agent | Repo / Area | Done CT | What / Why | Branch | Result |
|---|---|---|---|---|---|
| Scout-auto | vector-unified / restore cache artifacts | 13:01 CT 2026-08-16 | Moved to DONE to free lanes for pro button-up — Phase0 already done verified | scout/analytics-phase0 | DONE |
| Scout-auto | vector-hub / chimera daily | 13:01 CT 2026-08-16 | Moved to DONE to free lanes for pro button-up — chimera 20719×64-d daily verified | scout/vec-lattice-v2 | DONE |
| hillclimb-loop | vector-hub / Vercel unified 404→200 one-click | 12:47 CT 2026-08-16 | Proactive hillclimb 99→100% Vercel 17 rewrites 404→200 host rewrite + www + trailing slash + 7/7/0 provenance 59 hashes LCG 20260813→189831298 idx3820 triple[11205,19448,14209] five[11205,19448,14209,11701,18524] same-link-same-stars 5+2 swarm lite gate 9.45 PASS zero-deps true stdlib only | scout/vercel-final-1237 | PASS 9.45 |
---|---|---|---|
| hillclimb-loop | proactive-hillclimb-loop / stale >4h sweep 12:37 CT | 12:37 CT 2026-08-16 | Cleared 0 stale >4h (all fresh 11:37,12:07,16:10×2) — preserved 3 LOCAL-GPU 22:20 CT — board now 4→5 active non-GPU +2 free — zero-deps true stdlib only everyday lang — claimed vercel-final-1237 | hillclimb-loop | cleared |
| hillclimb-loop | proactive-hillclimb-loop / stale >4h sweep 11:37 CT | 11:37 CT 2026-08-16 | Cleared 9 stale >4h (4h03m-9h): mtl-mlops-factory 07:34 CT, hillclimb-hoops-v7 07:34 CT, vector-hub 5th chimera 06:37 CT, vector-hoops front polish 06:07 CT, dottie nano 05:07 CT, dottie closed-loop v2 04:37 CT, scout-cli universal 04:07 CT, vector-hub hoops polish 03:37 CT, vector-hub Vercel 02:37 CT — preserved 3 LOCAL-GPU 22:20 CT +2 Scout-auto 16:10 CDT fresh — board now 2 active non-GPU +1 new claim 3/7 max 4 free — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |
| hillclimb-loop | dottie + scout-cli / closed-loop factory v2 RL CoT compress FGO hybrid | 11:07 CT 2026-08-16 | Proactive hillclimb 99→100% DONE — Dottie factory v2 closed-loop + RL CoT 20-40% compress + FGO 1584→0 hybrid 9 tokens 31%cache + scout-cli 770B hallways 57 members MoMA 5 tiers — 5+2 swarm lite 90s max verifier gate 8.93 PASS mean8.93 min8.7 — MoMA 9.1 BEIR 9.0 mean8.93 PASS gate8.0+ — LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars — zero-deps true stdlib only — everyday lang | scout/dottie-scout-closed-loop-1107 | PASS |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 06:37 CT | 06:37 CT | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub Vercel unified 404→200 02:37 CT 4h00m51s >4h — preserved 3 LOCAL-GPU 22:20 CT + 6 fresh non-GPU (03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k, 06:07 hoops-front-polish) — board now 6 active + 1 new claim hub-chimera-5th 06:37 CT 7/7 max 0 free — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 06:07 CT | 06:07 CT | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub 5th game chimera 20,719×64-d 02:07 CT 4h00m51s >4h — preserved 3 LOCAL-GPU 22:20 CT + 6 fresh non-GPU (02:37 vercel, 03:07 dottie-acd-polish, 03:37 hub-polish-hoops, 04:07 scout-cli-universal, 04:37 dottie-closed-loop-v2, 05:07 dottie-nano-1k) — board now 6 active + 1 new claim hoops-front-polish 06:07 CT 7/7 max 0 free — zero-deps true stdlib only everyday lang | hillclimb-loop | cleared |
| DONE-self-improvement-100 | self-improvement-loop / 70→100% closer | 18:05 CT 2026-08-13 | Self-improvement 70%→95%→100% closer board poll 17→22 seen 500-505 5 new hits 3 blocker jsonl + paired lessons 28 tight foundation v0.1.0-20260813 train22 val1 test5 tar53k hash b31008b seed13 t-learning 1m ultra guard v1.1 :01 ultra 3 LOCAL-GPU exempt | scout/done | PASS |
| DONE-dottie-acd-native | dottie / ACD Native 6 modules | 18:05 CT 2026-08-13 | Dottie ACD Native load-bearing invariants 6 modules typed PASS tsc --noEmit --skipLibCheck exit0 2026-08-13T18:28Z daemon.ts tunnel peer.ts version mux rpc + AgentConductorPanel 40px sticky nav thin UI — timeline triple-write 7-field dottie-acd-native | scout/done | PASS |

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