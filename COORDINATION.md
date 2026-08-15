


# Active Tasks — Master Board
_LCG 20260813→189831298 idx3820 same-link-same-stars — ?daily=20260813&n=1/3/5 triple[11205,19448,14209]_
_Last sync: 2026-08-14 20:07 CT — hillclimb-loop sweep cleared 1 stale 16:07 CT 4h00m51s preserved 3 GPU — claimed 1 free lane hoops front polish — board 6 non-GPU active +1 free — zero-deps true hillclimb_backoff conf0.82_
_Sync: mirrors to each repo COORDINATION.md + TODO.md IN-PROGRESS table_

> Outside agents: read `COORDINATION.md` in repo root, `TODO.md` READY list. Inside Hatch: this file is SSOT.

## ACTIVE (≤15 rows, claimed/todo — talk before touching)

| Agent | Repo / Area | Since CT | What / Why | Branch | Status |
| LOCAL-GPU | vector-unified / unified G2 0.685→0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| hillclimb-loop | dottie / Forms+Memory v6 192d 6-head RoPE next hill | 16:37 CT 2026-08-14 | Proactive hillclimb 99→100% Forms+Memory v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers CORAL0.5 VICReg0.05 SupCon0.07 Bloom8192 m8192 k7 FPR0.9% ACNE17n27e TLPG dedup — gate 8.0+ LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars ?daily=20260813&n=1/3/5 | scout/dottie-forms-v6-1637 | claimed |
| hillclimb-loop | dottie / ACD Native polish dashboard verif 40px sticky nav thin UI | 17:07 CT 2026-08-14 | Proactive hillclimb 99→100% ACD Native 6 modules polish dashboard refresh — daemon.ts PTY/tunnel/file/ISL snapshot<300ms triple-write 7-field — peer.ts same binary — version.ts SHA256→FNV-1a handshake — tunnel.ts SSH survives LRU256 HMAC 90s — mux.ts WS multiplex backpressure 512KB — rpc.ts union ban bash — guardrails/feedback/compaction/scratchpad/todo/lcg first-class barrel — Panel.tsx sticky 40px nav 5 tabs thin UI 2.37kB/89.5kB tsc PASS gate 8.0+ — zero-deps true stdlib only LCG 20260813→189831298 idx3820 triple[11205,19448,14209] same-link-same-stars | scout/dottie-acd-polish-1707 | claimed |
| phase1-launched | dottie / Launched blockers 10/10 Phase1 | 18:04 CT 2026-08-14 | Phase1 Launched blockers 10/10 — Stripe 2.9%+30c T+2 Radar vs Lemon MoR 5%+50c, PostHog events bridge→store.jsonl dual 100% local + best-effort 5 hashes, Clerk 3-user max3, Vercel env check stripe/posthog health 200 when live, Sentry DSN never throws, Cloudflare R2 regex+1MB cap mirror, Resend outbox, LaunchDarkly flags.json is_on 0.9, Linear mirror LAUNCH-95 — PARKED per user 2026-08-11 helper-only — deadline Aug 31 11:59pm CT live URL +3 users | scout/phase1-launched-1804 | todo |
| hillclimb-loop | dottie / Top5 build order tick+flags → vec+lattice v2 → analytics+trace+ops v2 → meter | 19:37 CT 2026-08-14 | Proactive hillclimb 99→100% Top5 build order — claimed from todo 18:04→19:37 free lane 6/7→7/7 — tick+flags → vec+lattice v2 → analytics+trace+ops v2 → meter — mtl-mlops-factory + hoops-v7 DFS 12-d salary-ROI MAE<5.0 IC>0.15 — gates doc MTNN_v7 per-domain — everyday chain open→drag-map→Jordan copy-link equal stars DAU3/WAU3 TLPG dedup — LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 — zero-deps true stdlib only gate 8.0+ | scout/top5-build-1937 | claimed |
| hillclimb-loop | dottie / infra open vs closed gap | 19:07 CT 2026-08-14 | Open vs closed infra gap — IBM+OpenAI Agentic AI Foundation 57 members 3% frontier 50x cheaper — Dottie closed-loop v2 — typed RPC no shell exec guard single-use LRU 90s ephemeral HMAC 90s rate20/min audit last4 — 7 requirements AGI bit-exact reconstructability — verifier econ threshold8.0 budget3 — LCG 20260813→189831298 idx3820 — claimed from todo 18:04→19:07 free lane 6→7/7 — proactive hillclimb 99→100% | scout/infra-gap-1907 | claimed |
| hillclimb-loop | vector-hoops / front polish pill strip sticky 40px ?pov= Single-select map hoops-level parity | 20:07 CT 2026-08-14 | Proactive hillclimb 99→100% hoops front polish — pill strip sticky 40px ?pov= sync Single-select map clear prev Lighthouse PWA installability 100 delight 29JS 9CSS confetti 80max — claimed from TODO free lane 5→6/7 20:07 CT — zero-deps true stdlib only gate 8.0+ LCG 20260813→189831298 idx3820 triple[11205,19448,14209] ?daily=20260813&n=1/3/5 — everyday chain open→drag-map→Jordan copy-link equal stars | scout/hoops-front-polish-2007 | claimed |

## DONE recent

| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 20:07 CT | 20:07 CT | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub / chimera 20,719×64-d 5-game hub 16:07 CT 4h00m51s>4h — preserved 3 LOCAL-GPU 22:20 CT — claimed hoops front polish pill strip sticky 40px — board now 6 active +1 free — zero-deps true | hillclimb-loop | cleared |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 00:37 CT | 00:37 CT | Cleared 1 stale >4h (9h 9.0m): hillclimb-loop@vector-hoops / front polish hoops-level 21.6k map visible dark bg single-select 15:40 CT 2026-08-14 CT 9.0h >4h — preserved 3 LOCAL-GPU 22:20 CT — board now 5 active + 2 free — zero-deps true | hillclimb-loop | cleared |
| Agent | Repo / Area | Done CT | What / Why | Branch | Result |
| mtl-mlops-factory | vector-* / MTL+MLOps factory collectors rollout | 12:50 CT 2026-08-14 | Lane 6 FINAL — 5 collectors verified Drive 5/5 hoops 3000 gridiron 2500 pitch 2000 equities 2000 unified 3000 all_pass True G2 0.685→0.64 proj0.642 — zero-deps true | scout/mtl-mlops-factory | DONE PASS |
| hillclimb-loop-1008 | vector-hub / hoops-level polish 21.6k map | 10:15 CT 2026-08-14 | Lite swarm 5/5 PASS 9.2 >9.0 gate 8.0+ ships | scout/hub-polish-1008 | PASS 9.2 |
| phase0-analytics | dottie / analytics store.jsonl + plugin 5 cmds | 18:12 CT 2026-08-14 | Phase0 stub <2h VERIFIED 23:12Z — analytics store.jsonl 22 lines DAU3 WAU3 5 hashes TLPG dedup egress_guard true — triple-write 7-field verified | scout/phase0-analytics-1804 | PASS 9.1 |
| phase0-payments | dottie / payments $0 ledger idempotent | 18:12 CT 2026-08-14 | Phase0 stub VERIFIED 23:12Z — payments store.jsonl 22 lines inv_aabc1b34 duplicate safe — triple-write verified | scout/phase0-payments-1804 | PASS 9.0 |
| phase0-auth | dottie / auth 3-user is_on cached 0.9 | 18:12 CT 2026-08-14 | Phase0 stub VERIFIED 23:12Z — auth flags.jsonl 4 flags chimera_on true rollout1.0 is_on cached0.9 users3 — triple-write verified | scout/phase0-auth-1804 | PASS 9.0 |
| unified-404-PARKED | vector-hub / unified 404→200 final click | 18:12 CT 2026-08-14 | PARKED per user 2026-08-14 16:11 CT no Vercel needed Ship100% without Vercel domain | scout/vercel-final-1737 | PARKED 8.5 no-vercel-needed |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 17:07 CT | 17:07 CT 2026-08-14 | Cleared 1 stale >4h (4h30m): hillclimb-loop@dottie / ACD Native polish 12:37 CT 4h30m>4h — preserved 3 LOCAL-GPU — board now 6 active +1 free | hillclimb-loop | cleared |
| STALE-CLEARED-1 | proactive-hillclimb-loop / stale >4h sweep 16:07 CT | 16:07 CT 2026-08-14 | Cleared 1 stale >4h (4h00m51s): hillclimb-loop@vector-hub / chimera 12:07 CT 4h00m>4h — preserved 3 LOCAL-GPU — board now 5 active +2 free | hillclimb-loop | cleared |

## HOW TO CLAIM

1. `cat TODO.md` or this file
2. Pick READY lane not in IN-PROGRESS
3. Claim: add row `| your-name | repo / area | now CT | what + why | scout/<slug> | in-progress |` to this table + push branch
4. Work on branch only: `candidate.json` first, eval must beat current, `python -m json.tool` clean
5. Clear row when done → move to DONE recent, push

## LINKS
- LCG daily: seed=YYYYMMDD Math.imul(seed,1103515245)+12345>>>0 &0x7fffffff — 20260813→189831298 idx3820 same-link-same-stars triple[11205,19448,14209] ?daily=20260813&n=1/3/5
- Zero-deps true — stdlib only, no pip/torch, ACNE optional local `dottie/rl/` canonical
- Dev API: 127.0.0.1:8787/api/dev/* Bearer dm_dev_*
- Board mirrored: `dottie/COORDINATION.md`, `vector-*/COORDINATION.md`

> House rule v5 Prime: every cron / lane logs even no-change → 7-field timeline.jsonl