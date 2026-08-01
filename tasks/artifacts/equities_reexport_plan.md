# Equities placeholder re-export — post-GPU-window plan (2026-07-23)

## ✅ SUPERSEDED 2026-07-31 — the problem below was solved, by a different fix

GPU/RAM window was open (Docker Desktop not running, checked directly), so this plan
was picked up to execute. Investigation before executing found the premise stale:

- **`export_v6_real_assets.py` (step 1's candidate) is the WRONG, abandoned script.**
  It exports from `model_career.py`/`dataset_career.py` (a sequence model, last real
  edit `23de1dc`, before this plan was even written) and would have produced a
  `equities_mtnn_v6_real_d64_towers...` artifact — but the actually-shipped
  `assets/real_data.json` carries `model: equities_mtnn_v_rebuild_d64_transformer`,
  which comes from `export_real_assets.py`, not the v6/career script. Running step 1
  as literally written would have re-exported from the wrong pipeline entirely.
- **The real fix already shipped, 2026-07-30, `ba50cda` + `15e2fd1`.** A full
  real-data-chain rebuild (`fetch_sec_summary.py` + `fetch_market_history.py` → real
  SEC/market data, replacing `expand_sp500.py`'s sector-centroid+noise fill
  entirely) → `build_real_from_summary.py` → `build_skills.py`/`build_archetypes.py`
  → `train_mtnn.py --dim 64 --fusion transformer --d-model 128` → `export_real_assets.py`.
  The shipped artifact's own provenance block now reads: *"Rebuilt 2026-07-30 end to
  end... No synthetic rows"* and classifies `embeddings`/`skills` as **REAL**, not
  MIXED. Row count is 4,831 (not 4,941 — the universe itself changed), and
  `eval_sector_coherence.json`'s placeholder-contamination language is now historical
  prose in its `provenance` field, not a live per-run flag (there is no
  `placeholder_contamination` top-level key in the current output).
- **What's genuinely still open, and it's a DIFFERENT task than this plan's.** This
  session's own `c6b5c2d` (coverage-aware fusion + DEF14A comp, 2026-07-31) touched
  `pipeline/model.py` — the same `train_mtnn.py` pipeline `export_real_assets.py`
  reads from — but `assets/real_data.json` is still the 2026-07-30 18:56 UTC build,
  from BEFORE `c6b5c2d`. A re-export to pick up that fix is real, standing work, but
  it is a fresh decision (re-export + re-run `eval_sector_coherence.py` + propose-
  first before any public deploy, standing order 6 — same gate this plan itself
  named), not a continuation of this now-obsolete plan. Not started here.

Original plan preserved below for the record.

---


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
