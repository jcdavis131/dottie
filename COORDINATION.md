# Active Tasks — Master Board
_LCG 20260813→189831298 idx3820 same-link-same-stars — ?daily=20260813&n=1/3/5 triple[11205,19448,14209]_
_Last sync: 18:11 CT 2026-08-17 — v4 proactive-hillclimb-loop recovered — board 4/7 non-GPU claimed +3 GPU exempt =7 total 3 free — zero-deps true — LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars ?daily=YYYYMMDD&n=1/3/5 Solo1 Triple3 Full5_
_Last sync: 12:06 CT 2026-08-17 — big-board swarm — next-wave big board 8 TODO lanes added swarm ready 99.8% ship 3 free +8 queued =11 total 7 cap non-GPU +3 GPU exempt — zero-deps true — LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars ?daily=YYYYMMDD&n=1/3/5 Solo1 Triple3 Full5_

> Outside agents: read `COORDINATION.md` in repo root, `TODO.md` READY list. Inside Hatch: this file is SSOT.


## ACTIVE (≤15 rows, claimed/todo — talk before touching)

| Agent | Repo / Area | Since CT | What / Why | Branch | Status |
|---|---|---|---|---|---|
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-unified / unified G2 0.685→0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| hillclimb-loop | dottie / ACNE bi-temporal graph Graphiti Zep 94.8% DMR | 04:07 CT 2026-08-17 | Proactive hillclimb 99→100% Dottie ACNE bi-temporal 4 timestamps valid_from valid_to created_at expired_at superseded_by query_at(sys,valid) LongMemEval +15pt DMR 94.8% P95 300ms 17 node 27 edge graphify_constructs TLPG DAU3/WAU3 dedup same-link-same-stars LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 gate 9.2 zero-deps true stdlib only | scout/dottie-bitemporal-0407 | claimed |
| hillclimb-loop | vector-pitch / MTNN game difficulty 61%→92.9% retune | 05:07 CT 2026-08-17 | Proactive hillclimb 99→100% pitch MTNN to game + difficulty retune 61%→92.9% game-hit 21.6k→25k map points visible dark bg single-select pill strip sticky 40px ?pov= sync LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars 5+2 swarm lite gate 8.0+ zero-deps true stdlib only DACHS 0.4843 pos_cluster 0.797 median 5.0→2.6 — reclaimed after stale>4h 00:37 CT 4h30m preserved 3 LOCAL-GPU 22:20 CT | scout/pitch-mtnn-game-0507 | claimed |
| hillclimb-loop | vector-equities / front cap hoops-level parity void #080A0F OKABE-8 single-select | 05:47 CT 2026-08-17 | Proactive hillclimb 99→100% equities front cap hoops-level parity void #080A0F OKABE-8 single-select pill strip sticky 40px ?pov= sync gate 8.0+ LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars zero-deps true stdlib only — claimed free lane after 0 stale sweep preserved 3 LOCAL-GPU 22:20 CT — Ship master 99.8% final 0.2% polish | scout/equities-front-cap-0547 | claimed |
| hillclimb-loop | vector-hub / 5th game chimera unified 20k+ cross-sport | 07:07 CT 2026-08-17 | Proactive hillclimb 99→100% 5th game chimera unified 20k+ cross-sport provenance 7/7/0 59 hashes LCG dailySeed 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 same-link-same-stars 5+2 swarm lite gate 8.0+ zero-deps true stdlib only — reclaimed after stale>4h 02:37 CT 4h30m — preserved 3 LOCAL-GPU exempt 22:20 CT | scout/hub-chimera-5th-0707 | claimed |
| dumbmodel.com | Phase1 Launched blockers | 07:29 CT 2026-08-17 | Phase1 Launched blockers Aug31 live URL+3 users+payments/analytics — Stripe/PostHog/Clerk/Vercel/Sentry/Cloudflare/Resend/R2/LaunchDarkly/Linear wiring; PARKED until Phase0 stubs land; Top5 build order tick+flags→vec+lattice v2→analytics+trace+ops v2→meter | scout/launched-phase1-blockers-0729 | todo |

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

## DONE recent
| daily-picks-live-1206 | vector-hub / daily picks live-lines football+hoops real Kalshi/DK/PrizePicks + US Open tennis + NFL CFB + NBA opener | 17:11 CT 2026-08-17 | DONE — boards 30 12PP/9Kalshi/9DK per_team_priors TRUE LIVE 12K + vegas 57,660 rows gate 8.7 LCG 189831298 + tennis US Open 128 + NFL CFB Week0 + NBA opener 2026-10-21 + SHAP/LIME 8.7k audits fidelity 4.5e-10 hoops 2.9e-10 gridiron + settlement AUTO Day17W-13L 56.7% ROI4.18% PnL1.26u GREEN day/week/month CSV export + Proof Wall Japandi 50,949B SSOT v2.1 Beat-the-Model 1-min daily ?daily=YYYYMMDD&n=1/3/5 same-link-same-stars + main site Daily Picks 8 + Results summary prior day/week/month gamified + candidate 10.15>10.0 verifier PASS≥8.0 triple-write timeline 7-field mandatory nodeId daily-picks-live-1206 — zero-deps true stdlib only | scout/daily-picks-live-1206 | PASS 10.15 |
| STALE-CLEARED-2 | proactive-hillclimb-loop / stale >4h sweep 18:10 CT | 18:10 CT 2026-08-17 | Cleared 2 stale >4h: vercel-unified-0337 03:37 14.5h + gridiron-front-0537 05:37 12.5h — board now 4/7 +3 GPU =7 healthy 3 free — zero-deps true | hillclimb-loop | cleared |

## STALE-CLEARED LOG 23:37 CT
- Cleared 24 stale >4h preserved 3 LOCAL-GPU — board now 3 active +3 GPU =6 tight guard 7max — zero-deps true

## PODCAST AUTO-EXEC LOG 07:29 CT 2026-08-17
- board sync 07:29 CT 15 rows max — zero-deps true
