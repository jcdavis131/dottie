# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| Scout-hillclimb-loop-122 | ship-ai / proactive-hillclimb 99→100% lane 2/7 | 14:07 CT | quick coordinator <60s L0 scout-prime pacing max3/4 tempo :13 OODA 4/4 DAG7 KISS forms-memory-v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers VICReg0.05 CORAL0.5 SupCon2.0 Bloom8192 everyday chain open drag-map→Jordan LCG 1233799701 idx3970 ?daily=20260812&n=1/3/5 same-link-same-stars one Vercel click left | main | claimed |
| Scout-hillclimb-loop-126 | ship-ai / proactive-hillclimb 99→100% lane 5/7 | 15:37 CT | quick coordinator <60s L0 scout-prime pacing max3/4 tempo :13 OODA 4/4 DAG7 KISS forms-memory-v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers VICReg0.05 CORAL0.5 SupCon2.0 Bloom8192 everyday chain open drag-map→Jordan LCG 1233799701 idx3970 ?daily=20260812&n=1/3/5 same-link-same-stars one Vercel click left — 5+2 swarm lite PASS 8.9 everyday chain deferred heavy Nomic/KaLM/MoMA to 16:07 CDT zero-deps true | main | done 15:38 CDT lane5/7 quick coord PASS 8.9 |
| Scout-hillclimb-loop-127 | ship-ai / proactive-hillclimb 99→100% lane 3/7 | 16:07 CT | quick coordinator <60s L0 scout-prime pacing max3/4 tempo :13 OODA 4/4 DAG7 KISS forms-memory-v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers VICReg0.05 CORAL0.5 SupCon2.0 Bloom8192 everyday chain open drag-map→Jordan LCG 1233799701 idx3970 ?daily=20260812&n=1/3/5 same-link-same-stars one Vercel click left — 5+2 swarm lite PASS 8.9 everyday chain deferred heavy Nomic/KaLM/MoMA to 16:37 CDT zero-deps true | main | claimed |

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
