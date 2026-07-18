# Plan: Stabilize nano continuous loop (T9.1 gate)

Date: 2026-07-10  
Branch: `claude/model-training-workflow-plan-n5vep5`  
Mode: auto — execute without further approval unless irreversible.

## Situation (live evidence)

- Phase-coordination fix is **in the working tree, not committed**: collectors/curators follow trainer phase; trainer heartbeats via `runs`; starved phases bypass raw-backlog pause; one-shard-per-loop.
- Data plane is healthy: collectors committing P4 (`synth_needle`), curators claiming P4.
- Trainer reached P5 step ~3330, then **CUDA CUBLAS** crash (GPU shared with `server`). Restarted at `step_3250`, now **DATA_STARVED** on P4 (`tokens_ready(4)=0`).
- P3 runway recovered (~175M). P4/P5 still thin. Nano budgets are tiny (P4=1.5M, P5=3M tokens).
- Uncommitted baseline: auto-mode normally stops; user said **go** → proceed and commit as part of this plan.

## Goal

Restore a stable **collect → curate → train** loop through nano P4/P5 without CUBLAS crashes, land the coordination fix in git, and record T9.1 progress.

## Non-goals

- Full T10.1 pacer (setpoint controller) — thin coordination already shipped; defer full pacer.
- mini / base1b (T9.2+) — blocked on T9.1 green.
- Chat branch / full `smoke_live.sh` with chat ckpt — still deferred until nano base finishes.
- Stopping user's non-ava GPU processes.

## Approach

1. **Commit** the coordination + test changes (reversible, scoped).
2. **GPU exclusivity**: stop `server` while trainer runs on this host (known CUBLAS failure mode when both hold the 4080). Restart server after nano train is stable or done.
3. **P4 runway**: wait until `tokens_ready(4) > 0` (curators already packing); optionally seed heartbeat if needed.
4. **Trainer resume**: recreate trainer with exclusive GPU; verify steps advance without CUDA error for ≥2 min / ≥50 steps.
5. **Verify + note** in `TODOS.md` under T9.1 (partial: loop works; live smoke still needs chat ckpt).

## Risks

| Risk | Mitigation |
|------|------------|
| Server down during train | Dashboard/viewer offline temporarily; reversible `compose start server` |
| P4 pack slow | Collectors already producing; wait gate with timeout |
| Stale `runs` rows confuse phase | Prefer latest `updated_at`; trainer upserts on resume |
| CUBLAS returns with server stopped | Then investigate VRAM at seq=1024; not assumed |

## Acceptance

- [ ] Coordination commit on branch with green `tests/test_flow.py` + collector/curator subset
- [ ] `tokens_ready(4) > 0` observed
- [ ] Trainer logs `step` events after resume; no CUBLAS for ≥2 minutes
- [ ] Collectors show `collector_target_phase` matching trainer phase
- [ ] `TODOS.md` T9.1 annotated with measured status
