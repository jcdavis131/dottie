---
pretty_name: "(not recorded)"
license: "(not recorded)"
tags:
- dottie
- orchestration
- dataset-card
provenance_classification: REAL
generated_by: scripts/business/generators/dataset_card.py
generated_at: "2026-08-09T03:12:23+00:00"
classification: REAL
method: >-
  Per-source table rendered from the committed corpus metadata JSON;
  absent keys render as '(not recorded)' and no value is invented.
measured: true
sources:
  - path: "apps/ava-factory/data/orchestration/corpus_meta.json"
    sha256: "cf88c2cfb9a4bb5a95ed66e2782b7a31aa097c0f1f1a66622e3d406ee2cac861"
---

# (not recorded)

## Dataset Summary

The metadata file declares 3 source record(s). 0 of 3 record a license, 3 of 3 record a row count, and 0 of 3 record a checksum. All values below are rendered verbatim from the metadata file; absent keys are shown as “(not recorded)”.

## Source provenance

| Source | Path | License | Rows | Checksum | Classification |
| --- | --- | --- | --- | --- | --- |
| ultra_timeline | bundles/ultra/runs | (not recorded) | 15 | (not recorded) | (not recorded) |
| workflow_journal | wf_e370f3be-001 | (not recorded) | 14 | (not recorded) | (not recorded) |
| synthetic_battery | (not recorded) | (not recorded) | 800 | (not recorded) | (not recorded) |

## Recorded counts

Copied verbatim from the metadata file's `counts` block; nothing is recomputed.

- by_provenance — measured: 14, simulated: 815
- by_source — synthetic_battery: 800, ultra_timeline: 15, workflow_journal: 14
- by_split — test: 5, train: 741, val: 83
- by_tier — action_operator: 147, agentic_epic: 297, deep_research: 263, deterministic: 111, llm: 11
- total: 829

## Audit

- generated_at: 2026-08-09T03:12:23+00:00
- source file: `apps/ava-factory/data/orchestration/corpus_meta.json`
- source_sha256: `cf88c2cfb9a4bb5a95ed66e2782b7a31aa097c0f1f1a66622e3d406ee2cac861`
