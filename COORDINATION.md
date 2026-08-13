# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |
| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
| Scout-hillclimb-147 | proactive-hillclimb / 99→100% 5+2 ultracode | 00:07 CT | Thu 00:07 CDT 99→100% lane 6/7 free_before 2 — Goals 99% Ship Master97 hub20719 PWA v67 74426B HIT void #080A0F Auth15/15 3 users, Ideas gate 8.93 PASS 7 papers thr8.0 min8.6 Forms8.8 Zep9.1 CLS8.9 VICReg9.2 CORAL8.6 SupCon9.0 KaLM9.3 LCG 20260813→1233799701 idx3970 same-link-same-stars, swarm lite 5+2 L1 3-lens L2 DAG7 L3 Forms+Memory v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers CORAL0.5 VICReg0.05 SupCon0.07 Bloom8192 ACNE17n27e zero-deps stdlib only no torch/pip | scout/hill-147-proactive | claimed |
| Scout-hillclimb-148 | proactive-hillclimb / 99→100% 5+2 ultracode | 00:37 CT | Thu 00:37 CDT 99→100% lane 3/7 free_before 5 — Goals 99% Ship Master97 hub20719 PWA v67 74426B HIT void #080A0F Auth15/15 3 users, Ideas gate 8.93 PASS 7 papers thr8.0 min8.6 Forms8.8 Zep9.1 CLS8.9 VICReg9.2 CORAL8.6 SupCon9.0 KaLM9.3 LCG 20260813→1233799701 idx3970 same-link-same-stars, swarm lite 5+2 L1 3-lens L2 DAG7 L3 Forms+Memory v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers CORAL0.5 VICReg0.05 SupCon0.07 Bloom8192 ACNE17n27e zero-deps stdlib only no torch/pip | scout/hill-148-proactive | claimed |
| Scout-hillclimb-149 | proactive-hillclimb / 99→100% 5+2 ultracode | 01:07 CT | Thu 01:07 CDT 99→100% lane 3/7 free_before 5 cleared 1 stale 20:48 CT 4h19m >4h preserved 3 LOCAL-GPU exempt 22:20 CT 2h47m <4h — Goals 99% Ship Master97 hub20719 PWA v67 74426B HIT void #080A0F Auth15/15 3 users, Ideas gate 8.93 PASS 7 papers thr8.0 min8.6 Forms8.8 Zep9.1 CLS8.9 VICReg9.2 CORAL8.6 SupCon9.0 KaLM9.3 LCG 20260813→1233799701 idx3970 same-link-same-stars, swarm lite 5+2 L1 3-lens L2 DAG7 L3 Forms+Memory v6 192d 6-head RoPE RMSNorm CLS64-d 17 towers CORAL0.5 VICReg0.05 SupCon0.07 Bloom8192 ACNE17n27e zero-deps stdlib only no torch/pip researching→building L3 Forms+Memory v6 lite | scout/hill-149-proactive | building |

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
- brief-auto-exec evening-wrap-aug-12 2026-08-12 18:03 CDT — cleared 11 stale >4h (5 DONE + 6 OPEN inc Top5 build order) 22:07 CDT hillclimb-loop
- hillclimb-loop 00:37 CDT: cleared 9 stale >4h (Scout-factory-140 20:27,141 20:27,142 20:27,143 20:27, Scout-hillclimb-next-130-134 19:47 x5) — preserved 3 LOCAL-GPU exempt 22:20 CT unified/hoops/gridiron 57h+ OOM guard — 2 non-GPU remaining (145 20:48 3h49,147 00:07 30m) → free 5/7 claimed lane 3/7 00:37 CDT gate 8.93 PASS


<!-- merged from outside edits 2026-08-13T06:30Z -->
| Scout-factory-140 | autonomous-factory / core dashboard | 20:27 CT | FACTORY autonomous 5th puzzle factory core dashboard 12K inline LCG 1233799701 idx3970 | scout/factory-140-core | claimed |
| Scout-factory-141 | autonomous-factory / next-hills research | 20:27 CT | FACTORY research 7-paper gate 8.93 PASS beyond paper tracking | scout/factory-141-research | claimed |
| Scout-factory-142 | autonomous-factory / cron harness 1m ultra | 20:27 CT | FACTORY crons 1m ultra pacing-1 tempo-1 swarm-more-faster | scout/factory-142-crons | claimed |
| Scout-factory-143 | autonomous-factory / orchestrator v33 | 20:27 CT | FACTORY orchestrator v33 10 phases L0-L4 Scout Prime always-on | scout/factory-143-orchestrator | claimed |
| Scout-hill-145 | bundles/ultra / coordination layer ScoutCommsBus max3/4 :13→:01 | 20:48 CT | HILL 145 Build ScoutCommsBus relevantAgents filter max3/4 pacing :13→:01 + HandoffEnvelope 7-req mandatory + Claude Code swarm 3 instances + timeline triple-write 7-field even no-change PWA v67 #080A0F CORE20 LCG 1233799701 idx3970 | scout/hill-145-comms | claimed |
| Scout-hillclimb-next-130 | forms-memory-v6 / 192d 6-head | 19:47 CT | NEXT HILL Forms+Memory 10.5 Impact0.65Ease0.35 chain_readable 19tok 192/6=32 RoPE RMSNorm | scout/next-hill-130-forms | claimed |
| Scout-hillclimb-next-131 | vector-hoops / v6 192d gated full 130 | 19:47 CT | NEXT HILL Vector v6 8.7 hoops820 MAE0.2313→0.2085 130 feats 18 fams 150ep SupCon τ0.07 VICReg0.05 CORAL0.5 BLOOM8192 | scout/next-hill-131-hoops | claimed |
| Scout-hillclimb-next-132 | vector-unified / G2 0.685→0.64 | 19:47 CT | NEXT HILL unified 920 Δ-0.0851 p0.0251 CORAL centroid0.5 GRL0.3→0.5 60ep stage2 unfrozen | scout/next-hill-132-unified | claimed |
| Scout-hillclimb-next-133 | vector-equities / v6 money 0.7017→0.72 | 19:47 CT | NEXT HILL equities money CQS 0.7017→0.72 IC0.007→0.03 transformer 60ep 14.4k resume OneCycle 10% warmup | scout/next-hill-133-equities | claimed |
| Scout-hillclimb-next-134 | vector-hub / PWA v67 → v68 | 19:47 CT | NEXT HILL PWA 13k→ polished inline CSS/JS base64 LCG same-link-same-stars 1 Vercel click unified 404→200 | scout/next-hill-134-hub | claimed |
