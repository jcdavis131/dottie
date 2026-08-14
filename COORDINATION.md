# Active Tasks — Master Board
_LCG 20260813→189831298 idx3820 same-link-same-stars — ?daily=20260813&n=1/3/5 triple[11205,19448,14209]_
_Last sync: 2026-08-13 21:12 CT — zero-deps true stdlib only_
_Sync: mirrors to each repo COORDINATION.md + TODO.md IN-PROGRESS table_

> Outside agents: read `COORDINATION.md` in repo root, `TODO.md` READY list. Inside Hatch: this file is SSOT.

## ACTIVE (≤15 rows, claimed/todo — talk before touching)

| Agent | Repo / Area | Since CT | What / Why | Branch | Status |
|---|---|---|---|---|---|
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| LOCAL-GPU | vector-unified / unified G2 0.685→0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| self-improvement-lane | self-improvement-loop | 2026-08-13 17:54 CDT | board poll diff 17→22 t-learning sweep SIGTERM OOMGuard 167s comp0.809 MAE 0.2313 vs 0.2085 → guard v1.1 :01 ultra 3 LOCAL-GPU exempt — auto-spawn after swarm DONE via ship-notes-after-swarm 127.0.0.1:8787 dm_dev_* ephemeral 90s | scout/ship-notes-auto-43665 | todo |
| frontend-lane | frontend-swarm-hoops-level-everywhere | 2026-08-13 17:54 CDT | Pill strip sticky 40px ?pov= sync Single-select map clear prev Lighthouse PWA installability 100 delight 29JS 9CSS confetti 80max — auto-spawn after swarm DONE via ship-notes-after-swarm 127.0.0.1:8787 dm_dev_* ephemeral 90s | scout/ship-notes-auto-43665 | todo |
| scout-cli-lane | scout-cli-universal-cli-any-harness-can-plug-in | 2026-08-13 17:54 CDT | bundles/cli.sh 770B v0.8.0 installer p95 55/48/52s hallway TLPG dedup same-link-same-stars doctor 7/7 PASS — auto-spawn after swarm DONE via ship-notes-after-swarm 127.0.0.1:8787 dm_dev_* ephemeral 90s | scout/ship-notes-auto-43665 | todo |
| vector-hub-lane | vector-models-5-game-hub-at-hoops-level-parity | 2026-08-13 17:54 CDT | 12966×64-d hoops 5323 gridiron real nflverse 2430 pitch 4831 equities 20719 unified 7/7/0 Proven 59 hashes LCG dailySeed — auto-spawn after swarm DONE via ship-notes-after-swarm 127.0.0.1:8787 dm_dev_* ephemeral 90s | scout/ship-notes-auto-43665 | todo |
| Infra-gap-Aug13 | dottie-closed-loop-factory-v2 / open vs closed infra Aug13 | 18:05 CT | Infra gap Aug13 evening-wrap: IBM+OpenAI enterprise AI consult+cyber 57 Agentic AI Foundation members + Skan AI $63M + Argonne CoLa efficient pretrain rhymes LCG bloom dedup + Reproducibility is New Copyleft 7 req bit-exact — open weight 3% behind frontier 50x cheaper 79% devs use open 51% ship open vs 63% closed — infra bottleneck pattern clear | scout/infra-gap-aug13 | claimed |
| Vercel-unified-final-Aug13 | vector-hub / unified 404→200 Aug13 | 18:05 CT | Vercel final Aug13 evening-wrap: hoops 200 LIVE 49243B HIT PWA v67 offline 13.6k CORE20 DENY9 unified still 404 needs one-click Production Domains link — last click to 100% Ship — everyday chain open link drag-map→Jordan copy-link same-stars | scout/vercel-final-aug13 | claimed |
| Top5-order-Aug13 | ship-ai-product-suite-live-launched-by-aug-31 / Top5 build order Aug13 | 18:05 CT | Top5 build order Aug13 evening-wrap tick+flags → vec+lattice v2 → analytics+trace+ops v2 → meter — hoops v6 150ep d_model128 4-head CLS64-d 17 towers target composite 0.7937→0.85 top1 0.438→0.55 / gridiron real nflverse 2020-2025 32-d MAE 4.268→3.8 / unified G2 20719x64-d LCG 189831298 idx3820 triple[11205,19448,14209] sport blind GRL0.3→0.5 CORAL centroid missing caches 3 restore → smoke 2ep → 60ep train → eval measured .642 experimental | scout/top5-aug13 | claimed |

## DONE recent (last 3, >24h archived)

| Agent | Repo / Area | Done CT | What / Why | Branch | Result |
|---|---|---|---|---|---|
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
