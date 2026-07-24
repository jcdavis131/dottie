---
pretty_name: vector-gridiron MTNN (NFL fantasy PPR)
license: mit
language:
- en
tags:
- mtnn
- sports-prediction
- nfl
- fantasy-football
- vector-site
- dottie
model_info:
  base_preset: MTNN v2 (gated fusion)
  params_note: gated-fusion multi-task net; selection split (train ≤2023, early-stop on 2024); calibration = bias-shrink + per-position affine fit on 2024 val
  eval_metric: walk-forward weekly Spearman (rank corr, model vs actual PPR)
  eval_value: 0.6899
  eval_method: 17-week walk-forward backtest, 5,412 rows; per-week Spearman averaged; beats last-4-avg (0.654) and season-to-date (0.661) baselines
  eval_retracted: none — but this is a backtest of the projection METHOD, not archived published projections (see Considerations)
  provenance_classification: REAL
---

# vector-gridiron MTNN (NFL fantasy PPR)

## Model Summary

The MTNN behind **vector-gridiron** — predicts weekly NFL fantasy PPR scoring
order for QB/RB/WR/TE. This card surfaces the model's ONE
honest eval in the org Hub, per the provenance doctrine. It is the trained model
whose input population is the `gridiron_forecast_rows` dataset card.

## Architecture

MTNN v2 with **gated fusion** across feature families (`family_drop=0.0`).
Selection split: trained on seasons ≤2023, early-stopped on 2024. Predictions
calibrated by bias-shrink + a per-position affine fit on the 2024 validation
season. The checkpoint lives in the `vector-gridiron` repo (not this monorepo);
this card is its provenance record in the Hub.

## Evaluation — the honest number

**Walk-forward weekly Spearman: 0.6899 ± 0.040** (season 2025, 17 scored weeks,
5,412 player-weeks). For each scored week, Spearman rank correlation between the
model's projected PPR ordering and realized PPR, per position and overall, then
averaged across weeks.

| model | weekly Spearman |
|---|---|
| **MTNN v2 (this model)** | **0.6899** |
| last-4-game PPR average (baseline) | 0.6539 |
| season-to-date PPR average (baseline) | 0.6611 |

The MTNN beats both as-of baselines. Source: `vector-gridiron/assets/eval_backtest.json`
(computed 2026-07-22), the artifact the `gridiron_forecast_rows` dataset card
also sha-cites.

## Provenance classification

**REAL** — a real walk-forward backtest on real public NFL data (nflverse), the
model's ordering scored against realized outcomes. See `data_provenance_SOP.md`.

## Considerations

- **Backtest of the METHOD, not archived projections.** No timestamped archive of
  published projections exists (the site only ships the upcoming week), so the
  frozen pre-2025 checkpoint is scored on as-of (leakage-safe) features — it
  measures the method, not a track record of live calls.
- Two simple baselines only; the improvement over them (0.690 vs 0.654) is modest
  but real and cross-week stable (sd 0.040).

## Citation

vector-gridiron MTNN v2, eval `assets/eval_backtest.json` (2026-07-22, walk-forward
backtest). Regenerate via `vector-gridiron/pipeline/build_backtest.py`.
