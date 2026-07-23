# Audit — gridiron_forecast_rows.jsonl

Corpus PROPOSAL only (data-flywheel L4). Nothing auto-ingests this file; it is
an audited artifact per the honesty doctrine. Generated 2026-07-23.
vector-gridiron was treated strictly READ-ONLY (three files read, zero written).

## Row counts

- **5,412 rows**: season 2025, weeks 2–18, positions QB/RB/WR/TE,
  `nan_actuals=0`, every row `in_scored_group=true`.
- Exporter output (verbatim):

```
input: eval_backtest.json sha256=687af17bfac3a0813b782f24c8b120dc0f3e74af4a3e9af0f481686a3248b824
input: feature_manifest.json sha256=67ed8d6054974ec3166994ff4d7aff4f9ba4f06244b016ead1e1f1a46a7b3448
input: train_matrix.npz sha256=4092d5e4ba30a24d1f92f42c86764ba18c6267b38ec45bb2a741905b9970bbe1
wrote C:\Users\jcdav\dottie\tasks\artifacts\corpus_proposals\gridiron_forecast_rows.jsonl: 5412 rows, season 2025, weeks 2-18, nan_actuals=0
cross-check (recomputed from exported rows vs published artifact):
   QB last4 0.3683 vs 0.3683 | std 0.3844 vs 0.3844 | n 583 vs artifact 583
   RB last4 0.7038 vs 0.7038 | std 0.7122 vs 0.7122 | n 1424 vs artifact 1424
   WR last4 0.6113 vs 0.6113 | std 0.6158 vs 0.6158 | n 2258 vs artifact 2258
   TE last4 0.5792 vs 0.5792 | std 0.5999 vs 0.5999 | n 1147 vs artifact 1147
  ALL last4 0.6539 vs 0.6539 | std 0.6611 vs 0.6611 | n 5412 vs artifact 5412
```

Integrity: the per-position and overall mean per-week Spearman of both baseline
forecasts, recomputed from the exported rows with build_backtest.py's exact
average-rank Spearman, matches the published `assets/eval_backtest.json` to all
4 decimals, and all 5 row counts match. These rows ARE the backtest's input
population, not a lookalike.

## Schema (one JSON object per line)

| field | type | meaning |
|---|---|---|
| season | int | 2025 (the backtest's held-out test season) |
| week | int | 2–18 (week 1 unscoreable: feature builder needs one prior in-season game) |
| gsis | str | NFL GSIS player id (join key) |
| name | str | player display name |
| pos | str | QB \| RB \| WR \| TE |
| team | str | team code at that week |
| forecast_last4_ppr | float | as-of forecast: last-4-game PPR average (feature `f_fpts_ppr`) |
| forecast_std_ppr | float | as-of forecast: season-to-date PPR average (feature `std_ppr`) |
| forecast_last4_present | int | mask bit — 0 means the feature was missing and its value is a masked 0 |
| forecast_std_present | int | mask bit, same semantics |
| actual_fpts_ppr | float\|null | actual PPR fantasy points that week (target `fpts_ppr`) |
| in_scored_group | bool | (week, pos) group had ≥ min_group=8 rows, build_backtest.py's scoring rule |

## Provenance

- Repo: `C:\Users\jcdav\vector-gridiron`, branch
  `claude/model-training-workflow-plan-n5vep5`, HEAD
  `39f71372ec725d1028d8cf831def2fec55c9cedb` ("Add walk-forward weekly rank
  backtest…"). Working tree DIRTY (modified assets/*.json); however the two
  pipeline inputs are untracked build artifacts, so provenance is
  sha256 + mtime, not a commit:
  `train_matrix.npz` and `feature_manifest.json` built 2026-07-21 10:04 by
  `pipeline/build_features.py`, unchanged since; `eval_backtest.json` computed
  2026-07-22 14:14 FROM that npz (artifact postdates its input; the exact
  cross-check above confirms consistency).
- Ultimate source of stats: public nflverse play-by-play/weekly data (public
  sports statistics; no PII beyond public player names/ids).
- Exporter: `C:\Users\jcdav\dottie\apps\dottie\scripts\export_gridiron_forecast_rows.py`
  (tests: `apps/dottie/tests/test_export_gridiron_forecast_rows.py`).

## Known contamination / limits

1. **No MTNN model predictions.** The rows carry only the two deterministic
   baseline forecasts the backtest scores. The MTNN's per-row predictions exist
   nowhere on disk — `build_backtest.py` recomputes them in memory from the
   torch checkpoint each run, and this session was static-analysis-only (no
   model loads). Their absence is stated, not imputed. If the flywheel needs
   them, run `pipeline/build_backtest.py` with a per-row dump flag in a session
   allowed to load the checkpoint.
2. **Forecast and actual share a data stream.** Both baselines are rolling
   aggregates of the same nflverse PPR series as the target. A model trained on
   these rows learns "predict PPR from recent PPR" — fine for calibration/
   forecast-shaped fine-tuning, useless as an information-advantage benchmark.
3. **Backtest-of-method caveat inherited.** No timestamped archive of published
   projections exists (eval_backtest.json caveat #1); these are as-of features
   rebuilt leakage-safe, not archived publications.
4. **Masked zeros.** Where a mask bit is 0 the raw feature value is a masked 0.0
   that build_backtest.py nevertheless ranked as-is. Kept identical here for
   fidelity; filter on the `*_present` bits before treating values as real.
5. **Population quirks.** K/DST excluded (separate season-rate models); each
   player's first game of the season excluded; `in_scored_group` is uniformly
   true in this vintage (every 2025 week×pos group cleared min_group=8) but the
   flag is emitted anyway for schema stability across vintages.
