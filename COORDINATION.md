# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |

| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT 2026-08-04 | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | exempt OOM 57h+ — do NOT prune per CLAIM_BOARD_PROMPT |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT 2026-08-04 | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | exempt OOM 57h+ — claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT 2026-08-04 | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | exempt OOM 57h+ — claimed |
| Scout-hillclimb-loop | vector-hub / daily chimera + provenance 7/7/0 + PWA v67 live | Sun 2026-08-09 16:07 CDT | Proactive hill 99→100% — verify 20,719×64-d LCG 70737614 dailySeed same-link-same-stars, provenance 10/7/3/7/14/12/6 59 hashes 7/7/0, PWA v67 sw 5322B CORE19, Vercel 200 74K HIT, side-effect tagged READ, trail 7-field | scout/hillclimb-vector-hub | done 16:16 CDT PASS 10.0/8.0 — chimera verified live 200 len74426 5 dailies Game01-05 chimera 20719×64-d LCG 70737614 idx2948 provenance 59 hashes 7/7/0 PWA v67 manifest 2238B theme #080A0F sw 5888B CORE20 DENY9 offline dark #080A0F — 7/7 swarm DONE — board 3 GPU exempt + 1 done cleared → 3 rows exempt only

## Free lanes right now
- dottie / distilled reasoning optimizer traces→nano GRPO
- hoops-dumbmodel.com alias fix — OWNER live 200 root 404 Vercel re-link pending — workaround via dumbmodel.com/models/hoops.html live
- (vector-hub claimed above — 1 left, 2 still free, refresh in 30m)

## How to use
1. Add your row before editing
2. Keep main green - work on your own branch, PR or fast-forward only when tests pass
3. New assets = candidate.json -> promote only when eval beats current + gate passes
4. Log even if no change ("checked, no-op") so others know you looked
5. Clear row when done — stale >4h auto-pruned except LOCAL-GPU OOM exempt

