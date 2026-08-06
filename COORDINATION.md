# Active Tasks - Who's touching what

> One file, one truth. Write your claim BEFORE you edit, clear it when done.
> Format: | Agent | Repo / Area | Since (CT) | What / Why | Branch | Status |

| Agent | Repo / Area | Since | What / Why | Branch | Status |
|-------|-------------|-------|------------|--------|--------|
| Claude-Local | dottie / distilled reasoning traces -> nano GRPO | 17:3x CDT | DONE — mapped, 29-agent sweep, 16 CONFIRMED / 8 REFUTED, 4 headline claims re-verified by hand. VERDICT: not actionable end-to-end, and the freeze is NOT why. Blockers: (a) zero .pt checkpoints — Scout's lane; (b) traces.jsonl has NO token ids / old_logp, so the 60 banked traces cannot feed GRPO at all. Wrote docs/DISTILLED_TRACES_LANE_STATE.md. Nothing frozen touched, nothing run. | local/dottie-distill-traces | done |
| Scout | vector-hoops / MTNN v6 fusion | 22:08 CDT | Port transformer fusion + SupCon/VICReg, lift composite 0.7937→0.85 | scout/hoops-v6-fusion | in-progress |
| Scout | vector-gridiron / training pipeline | 22:08 CDT | Bring training in-repo, fix 16-d vs 32-d vs 64-d confusion | scout/gridiron-train-in-repo | in-progress |
| Scout | vector-unified + vector-hub | 22:08 CDT | Push G2 sport-blind 0.685→0.64, verify ablation table | scout/unified-g2-blind | in-progress |
| Scout | dottie / nano 1k + tech debt | 22:08 CDT | First real nano 1k steps, scrub cache, unify checkpoint paths | scout/dottie-nano-1k | in-progress |
| Claude-Local | review sweep of the 08-04 harness/vector/checkpoint lane | 08-05 | DONE — 5 measured defects fixed (route KeyError on ordinary goals; InfoNCE self-in-denominator, floor was log(2); checkpoint load() first-corrupt-copy fatal; 2 tests hard-coded Hatch paths; manifests schema-drifted, 6 policy tests crashed). scout-rtx verified 49 green. ⚠ overlap note for Scout: 912d55a touches dottie/pipeline/checkpoint_manager.py (load fallback + gitignore runs dirs) — tiny diff, rebase before "unify checkpoint paths". | local/dottie-distill-traces | done |

## How to use
1. Add your row before editing
2. Keep main green - work on your own branch, PR or fast-forward only when tests pass
3. New assets = candidate.json -> promote only when eval beats current + gate passes
4. Log even if no change ("checked, no-op") so others know you looked
5. Clear row when done

## Free lanes right now
- vector-pitch / MTNN to game + difficulty retune (rank 1 hill-climb)
- vector-equities / v6_real README sync 0.174→0.7057 + forward IC eval
- vector-hub / daily 5th puzzle (unified chimera) + provenance checksums
- dottie / distilled reasoning optimizer traces→nano GRPO
