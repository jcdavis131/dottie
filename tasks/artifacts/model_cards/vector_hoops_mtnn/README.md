---
pretty_name: vector-hoops MTNN (NBA player embeddings)
license: mit
language:
- en
tags:
- mtnn
- sports-prediction
- nba
- player-embeddings
- retrieval
- vector-site
- dottie
model_info:
  base_preset: MTNN player-embedding trunk
  params_note: multi-task NBA player-season embedding model; evaluated by adjacent-season nearest-neighbor retrieval with train/val/test splits
  eval_metric: held-out adjacent-season retrieval (test split top-5)
  eval_value: 0.3633
  eval_method: test split n=790 — top1 0.1633, top5 0.3633 (overall n=10104 top1 0.266/top5 0.524; val top5 0.516); held-out by split
  eval_retracted: none
  provenance_classification: REAL
---

# vector-hoops MTNN (NBA player embeddings)

## Model Summary

The MTNN behind **vector-hoops** — learns NBA player-season embeddings whose
geometry supports adjacent-season retrieval (a player's near-neighbors are their
own adjacent seasons + similar players). This card surfaces the model's honest
held-out eval in the Hub.

## Evaluation — the honest number

**Held-out adjacent-season retrieval.** On the held-out **test split (n=790)**:
top-1 **0.1633**, top-5 **0.3633**. Reported with train/val/test splits so the
generalizing number (test) is not confused with the fitted one:

| split | n | top-1 | top-5 |
|---|---|---|---|
| **test (held-out)** | 790 | **0.1633** | **0.3633** |
| val | 761 | 0.2510 | 0.5164 |
| train | 8,553 | 0.2770 | 0.5399 |
| overall | 10,104 | 0.2661 | 0.5243 |

The honest generalization number is the **test** split (0.3633 top-5) — the train
number (0.54) is fitted and higher, as expected; showing both is the point.
Source: `vector-hoops/assets/eval_scoreboard.json` (2026-07-22).

## Provenance classification

**REAL** — a real retrieval eval over real NBA player-season data, with a proper
held-out test split. See `data_provenance_SOP.md`.

## Considerations

- The train↔test gap (0.54 → 0.36 top-5) is real generalization loss; cite the
  test number, not the overall/train.
- Retrieval quality is a proxy for embedding structure, not a downstream
  prediction accuracy.

## Citation

vector-hoops MTNN, eval `assets/eval_scoreboard.json` (2026-07-22, adjacent-season
retrieval). Regenerate via `vector-hoops/pipeline/build_eval_scoreboard.py`.
