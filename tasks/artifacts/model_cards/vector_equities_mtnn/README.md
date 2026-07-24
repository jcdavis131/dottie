---
pretty_name: vector-equities MTNN (S&P sector embeddings)
license: mit
language:
- en
tags:
- mtnn
- equities
- sector-embeddings
- vector-site
- dottie
model_info:
  base_preset: MTNN sector-embedding trunk (dim 64)
  params_note: 64-dim company embedding over the S&P 500; evaluated by kNN GICS-sector purity
  eval_metric: kNN sector purity @10 (cosine)
  eval_value: 0.1742
  eval_method: fraction of each row's 10 nearest neighbors sharing its GICS sector, averaged; vs random-assignment baseline 0.111. 4,941 rows / 501 companies / 11 sectors
  eval_retracted: CONTAMINATED — 2,200 of 4,941 rows (45%) are PLACEHOLDER embeddings (sector-centroid + Gaussian noise, expand_sp500.py @7d93c0b), which bias the purity UPWARD. The 0.1742 is NOT a clean model number.
  provenance_classification: PLACEHOLDER
---

# vector-equities MTNN (S&P sector embeddings)

## Model Summary

The MTNN behind **vector-equities** — a 64-dim company embedding over the S&P
500, evaluated by how well nearest-neighbors share a GICS sector. This card
exists to surface the eval **and its contamination** honestly, not to claim a
clean score.

## Evaluation — measured, but CONTAMINATED

**kNN sector purity @10: 0.1742** (vs random-assignment baseline 0.111), over
4,941 rows / 501 companies / 11 sectors.

**⚠ This number is contaminated and must not be cited as a model result.**
`vector-equities/assets/eval_sector_coherence.json` carries a
`placeholder_contamination` block: **2,200 of 4,941 rows (45%) are placeholder
embeddings** — sector-centroid + Gaussian noise, introduced by
`pipeline/expand_sp500.py @7d93c0b` (the 2026-07-20 S&P 500 expansion). Because a
placeholder is literally its sector's centroid plus noise, its neighbors trivially
share its sector — so the placeholder rows bias purity **UPWARD**. Only the 2,741
real rows would give an honest score, which this artifact does not isolate.

## Provenance classification

**PLACEHOLDER** — the published metric contains placeholder-derived rows with a
stated upward bias, so per `data_provenance_SOP.md` it is not a REAL model number.
It renders in the Hub with the PLACEHOLDER badge and this contamination note so it
can never be laundered into a clean claim.

## Considerations / remediation

- To get a REAL number: re-run the eval on the **2,741 real rows only**, or
  re-embed the placeholder 2,200 with real description text and recompute.
  Re-export plan: `tasks/artifacts/equities_reexport_plan.md`.
- The contamination block is the reference pattern for the SOP's PLACEHOLDER class.

## Citation

vector-equities MTNN, eval `assets/eval_sector_coherence.json` (2026-07-22, sector
coherence). Regenerate via `vector-equities/pipeline/eval_sector_coherence.py`.
