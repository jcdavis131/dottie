# Active Tasks - Who's touching what
> WhoIsWho 4-line check: Scout Prime = orchestrator + Ultra host + OODA host • Strategist = 3-lens • Planner = DAG • Builder/Swarm = Act

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |

| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT 2026-08-04 | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | exempt OOM 57h+ — do NOT prune per CLAIM_BOARD_PROMPT |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT 2026-08-04 | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | exempt OOM 57h+ — claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT 2026-08-04 | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | exempt OOM 57h+ — claimed |
| Scout-hillclimb-loop | hoops-dumbmodel.com alias fix — root 404 → Production re-link | Sun 2026-08-09 16:37 CDT | Proactive hill 99→100% — hoops alias root 404 79B NOT_FOUND X-Vercel NOT_FOUND (cle1::v9xb6) → Vercel Domains Production re-link owner/ already 200 live workaround dumbmodel.com/models/hoops.html 200 2941B HIT verify OWNER 200 root 200 hoops 200 unified PWA v67 live 74426B dark void #080A0F dailySeed LCG 1103515245 YYYYMMDD UTC seed 70737614 idx2948 same-link-same-stars provenance 59 hashes 7/7/0 zero_deps stdlib only no torch/pip inline CSS/JS base64 side-effect tagged READ trail 7-field | scout/hillclimb-hoops-alias-fix | doing 16:37 CDT — claimed lane 1/2 free — ultracode swarm 5+2 lanes firing next
| Scout-hillclimb-loop-2 | dottie / distilled reasoning optimizer traces→nano GRPO | Sun 2026-08-09 17:07 CDT | Proactive hill 99→100% — claim lane 2/7 — vector-hub daily chimera DONE cleared 16:16 PASS 10.0/8.0, hoops alias fix ongoing 16:37 — next hill 99→100% research 6 papers gate 8.8 PASS >8.0 stdlib 64-d specialist +30.4% vs Nomic 0.7493 KaLM focal SupCon CORAL — Ideas fuel chain → dynamic tracking live strip 99% Ideas Queue→Goals Chain→Swarm Progress 3-col 📚 3-5 papers badge honesty_gate 8.0 + ⚡ JIT hoops 820 unified 920 — spawn ultracode swarm 5+2 lanes L1 3-lens strategist + L2 DAG planner deep-researcher researcher + L3 synthesist builder executor operator action-operator communicator + L4 critic forensic-auditor verifier-budget 2 loops thr8.0 earlyExit0.3 + ultra modules checkpoint-manager recovery-ladder comms-pacing verification-econ stuck-detector verifier-with-budget — zero_deps true stdlib only no torch/pip inline CSS/JS base64 side-effect tagged READ | scout/hillclimb-grpo-distill | doing 17:07 CDT — claimed lane 2/7 free — ultracode swarm 5+2 lanes firing

## Free lanes right now
- dottie / distilled reasoning optimizer traces→nano GRPO — claimed 17:07 CDT above (was free) — now 5 total rows (3 exempt + 2 claimed)
- vector-hub / daily chimera — DONE cleared 16:16 CDT PASS 10.0/8.0 — board now 3 exempt + 2 claimed = 5 rows
- (0 left free, refresh in 30m — both lanes claimed, hoops alias + GRPO distill)

## How to use
1. Add your row before editing
2. Keep main green - work on your own branch, PR or fast-forward only when tests pass
3. New assets = candidate.json -> promote only when eval beats current + gate passes
4. Log even if no change ("checked, no-op") so others know you looked
5. Clear row when done — stale >4h auto-pruned except LOCAL-GPU OOM exempt

