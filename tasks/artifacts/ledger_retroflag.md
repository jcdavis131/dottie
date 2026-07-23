# Ledger retro-flag — promotions resting on within-run-SEM-only evidence

- generated: 2026-07-23 14:52:19Z  ·  report ONLY, no ledger was mutated
- source: ledger COPY `C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3` (pre-existing copy; NOT refreshed — delete it and rerun to re-snapshot)
- live db (never opened by this script): `C:\Users\jcdav\dottie\apps\dottie\data\research\ledger.sqlite3`

Criterion (operator order B0, applied retroactively): a promotion is flagged when
its significance rested on a single run's batch-to-batch spread (`eval_ce_per_batch`, `eval_losses`)
or on no spread series at all — evidence that is blind to run-to-run variance.
§5.3.R93 measured that variance at 0.343 across seeds for the unmodified model,
4.5× the best claimed 'effect'; a candidate cleared 4.4 within-run SEM and lost
at all three seeds. Flagged rows are NOT evidence of improvement until their
promotion bundle's `ab_nano.py` (paired seeds) says so.

## Flagged promotions (2)

| id | name | promoted (UTC) | metric | value | delta | evidence |
|---|---|---|---|---|---|---|
| `23bb41375804` | MoE Load-Balanced Regularization (MLBR) | 2026-07-20 03:05:04Z | factory_lm_loss | 5.60506 | -0.01476 | **within_run_only** — train_metrics.eval_ce_per_batch (n=20) and NO per_seed; verdict predates sem_series |
| `5a7232ffea24` | Dynamic Feature Re-Weighting with Positional Gates | 2026-07-20 15:15:16Z | factory_lm_loss | 5.54404 | -0.06102 | **within_run_only** — eval_verdict.sem_series='eval_ce_per_batch' (n=20) |

## Promotions with cross-seed evidence (1)

Not flagged by THIS criterion — which classifies evidence class only. A row
here can still be an artifact for other reasons (hand-seeded baseline it was
measured against, capacity confound); see the promotion bundle's caveat block.

- `bc3dbb74bead` Hierarchical Attention with Reduced Memory Overhead (2026-07-19 05:00:03Z) — train_metrics.per_seed (n=3; verdict predates sem_series)

## Current baseline

- `factory_lm_loss` = 5.73733  ·  set by: (no experiment — seeded/calibrated)
- notes: measured baseline calibration: steps=150 seq=256 batch=16 lr=0.0003 device=cuda seeds=[0, 1, 2] per_seed=[5.74331, 5.56278, 5.90589]
- calibrated baseline; cross-seed per_seed recorded ([5.74331, 5.56278, 5.90589])

Summary: 2 of 3 sota promotions flagged.
