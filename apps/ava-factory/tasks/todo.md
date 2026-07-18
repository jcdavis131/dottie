# Todo: Stabilize nano continuous loop

- [x] T1 Commit phase-coordination fix (collector/curator/train/compose/tests) — `22530a9`
- [x] T2 Stop server for exclusive GPU during train
- [x] T3 Confirm P4 packed runway > 0 — ~143M tokens
- [x] T4 Recreate trainer --resume; verify stepping without CUDA crash (≥2 min) — P5 ~11k tok/s, restarts=0
- [x] T5 Annotate TODOS.md T9.1 with measured loop status
- [x] T6 Verify gate: collect+curate+train healthy; readiness one-liner
