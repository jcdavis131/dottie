# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |

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
