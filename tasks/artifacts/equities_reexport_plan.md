# Equities placeholder re-export — post-GPU-window plan (2026-07-23)

Why: 2,200 of 4,941 rows in vector-equities' published embedding matrix are
sector-centroid + Gaussian-noise placeholders (expand_sp500.py @7d93c0b), and
the sector-coherence eval (1.56x chance) is biased UPWARD for them — centroid
placeholders are sector-coherent by construction. The artifact now carries a
machine-readable `placeholder_contamination` block; this plan removes the
contamination instead of just labeling it.

Blocked on: GPU/RAM window (model load banned while the trainer runs). The
embedding model is `equities_mtnn_v6_real_d64_towers20_ic0.5490...` (from the
artifact's embedding_model field) — a torch multi-task NN producing d=64 rows.

Steps (run after trainer `done` + eval A/B complete):
1. Locate the export entry point in vector-equities/pipeline (the script that
   produced assets/real_data.json's 2,741 real rows; S3 scout traced it to the
   mtnn export path).
2. Run it restricted to the 2,200 placeholder tickers (ticker list = rows
   whose provenance is the expand_sp500 fill; identifiable from
   pipeline/expand_sp500.py's ticker set).
3. Regenerate assets/real_data.json with the real rows merged; keep a backup.
4. Re-run the sector-coherence eval; update eval_sector_coherence.json —
   remove `placeholder_contamination` only when placeholder_rows reaches 0.
5. Repo suite green; commit; propose-first before any public deploy
   (standing order 6).

Success: a public insight number measured only on model outputs.
