---
pretty_name: "(not recorded)"
license: "(not recorded)"
tags:
- dottie
- orchestration
- dataset-card
provenance_classification: REAL
generated_by: scripts/business/generators/dataset_card.py
generated_at: "2026-08-10T02:28:03+00:00"
classification: REAL
method: >-
  Per-source table rendered from the committed corpus metadata JSON;
  absent keys render as '(not recorded)' and no value is invented.
measured: true
sources:
  - path: "apps/ava-factory/data/orchestration/corpus_meta.json"
    sha256: "5ef0fc331ed3e0a0e9afe1f61bab540704b34c7ddea3a4dee581ed4ac3e7cd6e"
---

# (not recorded)

## Dataset Summary

The metadata file declares 3 source record(s). 0 of 3 record a license, 3 of 3 record a row count, and 0 of 3 record a checksum. All values below are rendered verbatim from the metadata file; absent keys are shown as “(not recorded)”.

## Source provenance

| Source | Path | License | Rows | Checksum | Classification |
| --- | --- | --- | --- | --- | --- |
| ultra_timeline | bundles/ultra/runs | (not recorded) | 749 | (not recorded) | (not recorded) |
| workflow_journal | wf_e370f3be-001 | (not recorded) | 14 | (not recorded) | (not recorded) |
| synthetic_battery | (not recorded) | (not recorded) | 800 | (not recorded) | (not recorded) |

## Recorded counts

Copied verbatim from the metadata file's `counts` block; nothing is recomputed.

- by_label_tier — measured-behavior: 726, measured-outcome: 8, simulated: 829
- by_provenance — measured: 729, simulated: 834
- by_source — synthetic_battery: 800, ultra_timeline: 749, workflow_journal: 14
- by_split — test: 61, train: 1359, val: 143
- by_tier — action_operator: 284, agentic_epic: 460, deep_research: 453, deterministic: 251, llm: 115
- measured_holdout_by_label_tier — measured-behavior: 114, measured-outcome: 2, simulated: 2
- total: 1563

## Audit

- generated_at: 2026-08-10T02:28:03+00:00
- source file: `apps/ava-factory/data/orchestration/corpus_meta.json`
- source_sha256: `5ef0fc331ed3e0a0e9afe1f61bab540704b34c7ddea3a4dee581ed4ac3e7cd6e`
