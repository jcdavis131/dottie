---
pretty_name: Gridiron Forecast/Actual Rows (NFL 2025 backtest)
license: mit
task_categories:
- tabular-regression
- time-series-forecasting
language:
- en
tags:
- nfl
- fantasy-football
- forecasting
- calibration
- dottie
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files:
  - split: train
    path: gridiron_forecast_rows.jsonl
dataset_info:
  features:
  - name: season
    dtype: int64
  - name: week
    dtype: int64
  - name: gsis
    dtype: string
  - name: name
    dtype: string
  - name: pos
    dtype: string
  - name: team
    dtype: string
  - name: forecast_last4_ppr
    dtype: float64
  - name: forecast_std_ppr
    dtype: float64
  - name: forecast_last4_present
    dtype: int64
  - name: forecast_std_present
    dtype: int64
  - name: actual_fpts_ppr
    dtype: float64
  - name: in_scored_group
    dtype: bool
  splits:
  - name: train
    num_examples: 5412
  provenance_classification: REAL
---

# Gridiron Forecast/Actual Rows (NFL 2025 backtest)

## Dataset Summary

As-of forecasts vs. realized outcomes for NFL fantasy scoring — the exact input
population of vector-gridiron's walk-forward backtest (season 2025, weeks 2–18,
positions QB/RB/WR/TE). Each row pairs two as-of baseline forecasts with the
realized PPR points and the scoring mask, for **prediction/calibration** training
and evaluation. Structure modelled on
[The Stack v3](https://huggingface.co/datasets/HuggingFaceCode/stack-v3-train);
governance per `tasks/artifacts/data_provenance_SOP.md`.

**Nothing auto-ingests this file** — audited proposal artifact.

## Data Structure / Fields

One JSON object per line (JSONL). Row = one (player, week) observation.

| field | type | meaning |
|---|---|---|
| season | int64 | 2025 (the backtest's held-out test season) |
| week | int64 | 2–18 (week 1 unscoreable: feature builder needs one prior in-season game) |
| gsis | string | NFL GSIS player id (join key) |
| name | string | player display name |
| pos | string | QB \| RB \| WR \| TE |
| team | string | team code at that week |
| forecast_last4_ppr | float64 | as-of forecast: last-4-game PPR average (feature `f_fpts_ppr`) |
| forecast_std_ppr | float64 | as-of forecast: season-to-date PPR average (feature `std_ppr`) |
| forecast_last4_present | int64 | mask bit — 0 = feature missing, value is a masked 0 |
| forecast_std_present | int64 | mask bit, same semantics |
| actual_fpts_ppr | float64\|null | realized PPR fantasy points that week (target `fpts_ppr`) |
| in_scored_group | bool | (week, pos) group had ≥ 8 rows (build_backtest.py scoring rule) |

## Splits

| split | rows | coverage |
|---|---|---|
| train | 5412 | season 2025, weeks 2–18, QB/RB/WR/TE; nan_actuals=0; all rows in_scored_group |

## Dataset Creation

### Source data
Real NFL data via **nflverse** (player_stats, play-by-play), assembled by
vector-gridiron's feature/backtest pipeline. Exported READ-ONLY from three
published artifacts (sha256-pinned): `eval_backtest.json` (`687af17b…`),
`feature_manifest.json` (`67ed8d60…`), `train_matrix.npz` (`4092d5e4…`).

### Integrity
Per-position and overall mean per-week Spearman of both baseline forecasts,
recomputed from the exported rows with build_backtest.py's exact average-rank
Spearman, matches the published `assets/eval_backtest.json` to 4 decimals, and
all 5 row counts match (QB 583 / RB 1424 / WR 2258 / TE 1147 / ALL 5412). **These
rows ARE the backtest's input population, not a lookalike.**

### Provenance classification
**REAL** — measured from real public NFL data (nflverse), forecasts computed by
the real feature pipeline, actuals are realized outcomes. See `data_provenance_SOP.md`.

### Personal and sensitive information
Public NFL player performance data only (names/ids are public sports records).

## Considerations for Using the Data
- Forecasts are **as-of** (no lookahead): computed from data available before
  each week. `*_present` mask bits flag imputed-zero features — respect them.
- `actual_fpts_ppr` may be null for a rostered player who did not record a
  scored line; `in_scored_group` gates the backtest's scored population.
- Two simple baselines only (last-4 avg, season-to-date avg) — this is the
  backtest INPUT, not model predictions.

## Licensing
MIT (the exporter + the derived table). Underlying nflverse data is public.
Solo personal project, no connection to employer, public/free-tier only.

## Citation
vector-gridiron backtest, exported 2026-07 (read-only). Regenerate from the
sha256-pinned artifacts via the gridiron export script.
