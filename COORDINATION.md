


# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| Scout-hillclimb-loop-129 | goals-ideas → ship-ai-product-suite-live-launched-by-aug-31 | 17:37 CDT | SOTA idea_sota_005 Payments+analytics UNLOCKS 11.6 Stripe 2.9%+30c T+2 Radar vs MoR 5%+50c PostHog vs Mixpanel $0 ledger sha(email|plan) + 5-cmd plugin daily shard 2026-08-07.jsonl chain drag-map→Jordan LCG 1233799701 idx3970 | scout/goals-ideas-sota-005 | researching 11.6 |
| Scout-brief-auto-DONE | dumbmodel / 5 games chimera | 18:03 CDT 2026-08-12 | DONE: dumbmodel 5 games chimera live 20719×64-d daily LCG 1233799701 idx3970 same-link-same-stars, PWA v67 74426B HIT void #080A0F, provenance 7/7/0 59 hashes — via evening-wrap-aug-12 | scout/chimera-done | done |
| Scout-brief-auto-DONE | vector-* / honesty pass | 18:03 CDT 2026-08-12 | DONE: vectors honesty pass — hoops 12966 native, gridiron 5323, pitch 633 WC, equities 4831 facts 500 tickers no leak, unified glue 98% — verified in manifest | scout/vectors-honesty-pass | done |
| Scout-brief-auto-DONE | dottie / triple-write 5/5 | 18:03 CDT 2026-08-12 | DONE: Dottie triple-write 5/5 healthy, deterministic triple-write in manifest, nano GRPO 29 tests green | scout/dottie-triple | done |
| Scout-brief-auto-DONE | scout-cli / 0.8 polish | 18:03 CDT 2026-08-12 | DONE: scout-cli 0.8 polish pushed, compressed packs 87% smaller, universal cli, token-cache 80% save | scout/cli-0.8 | done |
| Scout-brief-auto-DONE | ACNE / 30 contacts 57 triggers | 18:03 CDT 2026-08-12 | DONE: ACNE 30 contacts 57 triggers → now 54 contacts 17n27e, rebrand done, tool-first resolver | scout/acne-30c | done |
| Scout-brief-auto-OPEN | infra-gap / open-vs-closed | 18:03 CDT 2026-08-12 | OPEN: infra gap — Mozilla open vs closed gap 3%, 50× cheaper over 3y, 79% use open but only 51% prod vs 63% closed — infra is blocker, Dottie + vector-hub fix | scout/infra-gap | claimed |
| Scout-brief-auto-OPEN | bundles/analytics / Phase0 stub | 18:03 CDT 2026-08-12 | OPEN: Phase0 analytics store.jsonl + plugin — verify events/2026-08-12.jsonl exists, L1 checksum dedup, daily shards len//4, TS_TX bitemporal, no egress | scout/analytics-phase0 | in-progress |
| Scout-brief-auto-OPEN | bundles/payments / Phase0 stub | 18:03 CDT 2026-08-12 | OPEN: Phase0 payments idempotent 3-user $0 ledger — store.jsonl idempotent sha(email|plan), duplicate returns existing, no Stripe live until explicit go | scout/payments-phase0 | in-progress |
| Scout-brief-auto-OPEN | bundles/auth / Phase0 3-user | 18:03 CDT 2026-08-12 | OPEN: Phase0 auth 3-user allowlist — users.jsonl 3 active u_cameron/u_alex_demo/u_jordan_demo, flags.jsonl is_on cached 0.9, git-tracked | scout/auth-phase0 | in-progress |
| Scout-brief-auto-OPEN | Phase1 / Launched blockers | 18:03 CDT 2026-08-12 | OPEN: Phase1 Launched blockers — Stripe 2.9%+30c, PostHog 200 events, Clerk 3-user shim, Vercel env, Sentry trace, Cloudflare R2 1M cap regex bucket, Resend outbox, LaunchDarkly flags.json, Linear mirror — all PARKED local-first per 07:04 CDT, no live keys until Cameron yes | scout/launched-phase1-blockers | claimed |
| Scout-brief-auto-OPEN | Top5 / build order | 18:03 CDT 2026-08-12 | OPEN: Top5 build order tick+flags → vec+lattice v2 → analytics+trace+ops v2 → meter — ultracode 5+2 swarm lite <90s, gate 8.93 PASS thr8.0, LCG 1233799701 idx3970 same-link-same-stars ?daily=20260812&n=1/3/5 | scout/top5-build-order | claimed |

## How to use
1. Add your row before editing
2. Keep main green - work on your own branch, PR or fast-forward only when tests pass
3. New assets = candidate.json -> promote only when eval beats current + gate passes
4. Log even if no change ("checked, no-op") so others know you looked
5. Clear row when done

## Free lanes right now
- vector-hub / daily 5th puzzle (unified chimera) + provenance checksums
- dottie / distilled reasoning optimizer traces→nano GRPO
- LOCAL GPU heavy trains (OOM in Hatch) — see handoff table above, do NOT pip torch
- ship-ai / T5 epic 3-lens strategist DONE 16:50 CT PASS 8.93 3 difficulty
- ship-ai / T5 deep-researcher-planner DONE 16:48 CT gate 8.93 PASS 7 papers
- vector-* / T5 builder-hoops-equities-unified DONE 16:50 CT MAE0.2313 honest no promo epoch0 0.809 would-beat SIGTERM LOCAL-GPU resume
- ship-ai / T5 synthesist-critic DONE 16:50 CT gate8.0 PASS 8.93 everyday chain drag-map→Jordan
- brief-auto-exec evening-wrap-aug-12 2026-08-12 18:03 CDT — DONE 5 closed, OPEN 6 claimed/in-progress — triple-write verified
