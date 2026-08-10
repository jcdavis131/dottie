---
generated_by: scripts/business/generators/research_brief.py
generated_at: "2026-08-10T02:28:02+00:00"
classification: REAL
method: >-
  Mechanical extraction (quote or count, no paraphrase) from the committed
  insights spec plus verbatim key/number listing of any orchestrator report
  JSON present at generation time.
measured: true
sources:
  - path: "docs/LONGCAT2_INSIGHTS_SPEC.md"
    sha256: "1dd25ca11150fe706a8e986ace9283e785e6d3cdc624c553447e1e2c811d4d31"
  - path: "apps/ava-factory/reports/orchestrator/champion_weights.json"
    sha256: "8d5442532482d7372921ec0465ff177b90aa87c8ded317e743ca89483fa5086e"
  - path: "apps/ava-factory/reports/orchestrator/eval_report.json"
    sha256: "b3186e17e8dbdb8e4fef3370034bb4ff4ecd4a15c3020cb0241e737f85e3e015"
  - path: "apps/ava-factory/reports/orchestrator/ladder_report.json"
    sha256: "6981baf6a8654a15e3ac5d947ac3761e8a4fcabc82f683aa269316daed402336"
---

# LONGCAT2_INSIGHTS_SPEC — mapping LongCat 2.0's efficiency doctrine onto Dottie

This brief indexes the committed specification titled “LONGCAT2_INSIGHTS_SPEC — mapping LongCat 2.0's efficiency doctrine onto Dottie”. The specification marks 1 item(s) BUILD-NOW and 1 item(s) SPECED-DEFERRED across 10 H2 section(s). The TL;DR below is reproduced verbatim from the source; counts are computed mechanically and no claim is paraphrased or added.

## Spec inventory

- BUILD-NOW markers: 1
- SPECED-DEFERRED markers: 1
- H2 headings (verbatim):
  - TL;DR
  - Context: LongCat 2.0 in one paragraph
  - 1. Streaming-aware indexing → a real timeline store for the harness
  - 2. Hierarchical (coarse-to-fine) retrieval → ShardStore fine ranking
  - 3. MOPD → distillation model-load fix and a gated multi-tier ladder
  - 4. Cross-layer reuse / compute-once in the harness route pipeline
  - 5. Engram embeddings → hashed n-gram table for DottieModel1B
  - 6. muP → width-invariant transfer across the nano/mini/base1b ladder
  - 7. True on-policy rollouts for the MOPD tier
  - Verification

### TL;DR (verbatim from source)

- LongCat 2.0 (1.6T params, trained on a non-Nvidia ASIC stack) contributes five transferable
  ideas: streaming-aware indexing, cross-layer index reuse, hierarchical (coarse-to-fine)
  retrieval, n-gram "engram" embedding tables, muP hyperparameter transfer, and multi-tier
  on-policy distillation (MOPD).
- Dottie's analog of LongCat's hardware co-design is free-tier co-design: CPU-only CI, a
  commodity 12GB-VRAM box, append-only JSONL stores. The cheap slice of each insight lands
  now; everything GPU-shaped or freeze-blocked is speced and deferred with a reversal trigger.
- Three items are BUILD-NOW, with non-overlapping file sets and pytest coverage:
  1. Streaming timeline store feeding `harness graph-plan` failure risk (scout-cli).
  2. Coarse-to-fine shard retrieval in the memory layer (ava-skills).
  3. Distillation model-load bugfix + gated multi-tier distillation ladder (ava-factory).

## Orchestrator evidence

- `champion_weights.json`
  - top-level keys: config, gate_passed, model_version, norms, provenance, schema_version, trained_at, weights
  - numeric fields (verbatim): schema_version=1
- `eval_report.json`
  - top-level keys: baselines, built_at, champion, corpus_source, gate, notes, schema_version, trainer
  - numeric fields (verbatim): schema_version=1
- `ladder_report.json`
  - top-level keys: built_at, corpus_counts, corpus_source, n_records_dropped_bad_label, schema_version, seed_offset, time_budget_s, trainer, variants
  - numeric fields (verbatim): n_records_dropped_bad_label=0, schema_version=1, seed_offset=0, time_budget_s=60.0

## Citations

- `docs/LONGCAT2_INSIGHTS_SPEC.md` — sha256 `1dd25ca11150fe706a8e986ace9283e785e6d3cdc624c553447e1e2c811d4d31`
- `apps/ava-factory/reports/orchestrator/champion_weights.json` — sha256 `8d5442532482d7372921ec0465ff177b90aa87c8ded317e743ca89483fa5086e`
- `apps/ava-factory/reports/orchestrator/eval_report.json` — sha256 `b3186e17e8dbdb8e4fef3370034bb4ff4ecd4a15c3020cb0241e737f85e3e015`
- `apps/ava-factory/reports/orchestrator/ladder_report.json` — sha256 `6981baf6a8654a15e3ac5d947ac3761e8a4fcabc82f683aa269316daed402336`
