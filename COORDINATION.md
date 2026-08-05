# Mirrored from bundles/coordination/active-tasks.md 2026-08-05T03:49Z
# Active Tasks - Who's touching what

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |

| Agent | Repo / Area | Since | What / Why | Branch | Status |
|-------|-------------|-------|------------|--------|--------|
| Scout | vector-hoops / MTNN v6 fusion | 22:08 CDT | Port transformer fusion + SupCon/VICReg, lift composite 0.7937→0.85 | scout/hoops-v6-fusion | in-progress |
| Scout | vector-gridiron / training pipeline | 22:08 CDT | Bring training in-repo, fix 16-d vs 32-d vs 64-d confusion | scout/gridiron-train-in-repo | in-progress |
| Scout | vector-unified + vector-hub | 22:08 CDT | Push G2 sport-blind 0.685→0.64, verify ablation table | scout/unified-g2-blind | in-progress |
| Scout | dottie / nano 1k + tech debt | 22:08 CDT | First real nano 1k steps, scrub cache, unify checkpoint paths | scout/dottie-nano-1k | in-progress |
| Scout-lane2 | dottie + scout-cli v0.8 polish | 22:43 CDT | Night shift lane 2 verify triple-write + nano smoke deterministic + 1k spec + scaffold | scout/dottie-cli-night2 | done 03:45 CT — triple verified 7-field, 15-dirs scrub 0 left, gitignored pipeline/runs, manifest v0.8.0 fs true net false, 1K spec written |

## How to use
1. Add your row before editing
2. Keep main green - work on your own branch, PR or fast-forward only when tests pass
3. New assets = candidate.json -> promote only when eval beats current + gate passes
4. Log even if no change ("checked, no-op") so others know you looked
5. Clear row when done

| Scout-lane1 | vector-* all 4 / honesty pass | 22:43 CDT | equities 4831×500 0.7057 lift6.32 verified fixed d80a716, hoops v6 17 towers d128 4L 4H CLS→64-d leak-free test top1 0.438→0.55 target recall@10 0.977 verified, pitch 588/633 92.9% WC-only 633 2430×11ctx verified, gridiron 32-d native 16-d compat wrapper gate NO promote MAE 8.41 synthetic vs claimed 4.268, branch scout/vector-honesty-night1 4 repos, tests 8p+13p PASS, timeline.jsonl ok | scout/vector-honesty-night1 | done 03:46 CT |

## Free lanes right now
- vector-hub / daily 5th puzzle (unified chimera) + provenance checksums
- dottie / distilled reasoning optimizer traces→nano GRPO
- LOCAL GPU heavy trains (OOM in Hatch) — see handoff table above, do NOT pip torch

## 2026-08-04 22:20 CT — HANDOFF to local GPU agent
| LOCAL-GPU | vector-unified / unified G2 0.685->0.64 | 22:20 CT | FULL TRAIN: GRL λ0.3→0.5 + CORAL centroid, missing caches embedding_v3.npz / mtnn_best.pt / pitch_mtnn_embeddings.json, torch OOM workaround → run train_stage2.py --smoke -> train_unified.py 60ep -> eval_unified.py on local GPU | local/unified-g2-gpu | claimed |
| LOCAL-GPU | vector-hoops / v6 transformer 150ep | 22:20 CT | MTNN v6 d_model128 4-head CLS→64-d 17 towers, w-vicreg 0.05, target composite 0.7937→0.85 test top1 0.438→0.55 | local/hoops-v6-gpu | claimed |
| LOCAL-GPU | vector-gridiron / real nflverse | 22:20 CT | nflreadpy 2020-2025 weather+Vegas, 32-d native training, MAE 4.268→3.8 | local/gridiron-real | claimed |
