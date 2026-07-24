---
pretty_name: Dottie Repair Transcripts
license: mit
task_categories:
- text-generation
language:
- code
- en
tags:
- code
- self-correction
- code-repair
- agentic
- dottie
size_categories:
- n<1K
configs:
- config_name: default
  data_files:
  - split: train
    path: repair_transcripts.jsonl
dataset_info:
  features:
  - name: experiment_id
    dtype: string
  - name: experiment_state
    dtype: string
  - name: hypothesis_name
    dtype: string
  - name: module_name
    dtype: string
  - name: dry_run_contract
    dtype: string
  - name: attempt
    dtype: int64
  - name: failure_seq
    dtype: int64
  - name: n_failed_attempts
    dtype: int64
  - name: level
    dtype: string
  - name: status
    dtype: string
  - name: failure_detail
    dtype: string
  - name: repair_hint
    dtype: string
  - name: hint_source
    dtype: string
  - name: corrected_code
    dtype: string
  - name: corrected_code_role
    dtype: string
  - name: validated_detail
    dtype: string
  splits:
  - name: train
    num_examples: 12
  provenance_classification: HONEST-SYNTHETIC
---

# Dottie Repair Transcripts

## Dataset Summary

Failure → hint → corrected-code repair pairs mined from the Dottie research
loop's validation ledger. Each row records a candidate neural-block that failed
the 6-stage validator, the diagnostic hint for that failure class, and the final
validated code that recovered from it — training data for **self-correction**.
Structure modelled on [The Stack v3](https://huggingface.co/datasets/HuggingFaceCode/stack-v3-train);
governance follows this repo's `tasks/artifacts/data_provenance_SOP.md`.

**Nothing auto-ingests this file** — it is an audited proposal artifact per the
honesty doctrine.

## Data Structure / Fields

One JSON object per line (JSONL). Row = one failed validation attempt of a
recovered experiment.

| field | type | meaning |
|---|---|---|
| experiment_id | string | ledger `experiments.id` (join key) |
| experiment_state | string | final ledger state (rejected / failed_training) |
| hypothesis_name | string\|null | hypothesis JSON `hypothesis_name` |
| module_name | string | candidate module class name |
| dry_run_contract | object | `{class_name, init_kwargs, input_shape}` the validator instantiates with |
| attempt | int64 | validate.py history `attempt` index |
| failure_seq | int64 | 0-based index among this experiment's failed attempts |
| n_failed_attempts | int64 | failed attempts in this experiment's history |
| level | string | syntax \| static \| contract \| dry_run |
| status | string | validator status string |
| failure_detail | string | verbatim history detail (validate.py truncates to 2000 chars at write) |
| repair_hint | string\|null | `diagnose_failure(level, detail)` recomputed at export time |
| hint_source | string | constant disclaimer (see Considerations #2) |
| corrected_code | string | the experiment's final validated code |
| corrected_code_role | string | constant `final_validated_code` (see Considerations #1) |
| validated_detail | string | detail of the passing attempt (e.g. `forward ok on input [4, 16, 64] -> (4, 16, 64)`) |

## Splits

| split | rows | source experiments |
|---|---|---|
| train | 12 | 7 recovered (of 100 in the ledger copy; 70 failed and never recovered → 0 rows by design) |

## Dataset Creation

### Source data
- **Source:** a COPY of the research daemon's `apps/dottie/data/research/ledger.sqlite3`
  (`ledger_copy.sqlite3`, sha256 `5150bdf0…b489c4`, 983,040 bytes). The live DB
  was never opened.
- **Exporter:** `apps/dottie/scripts/export_repair_transcripts.py`
  (tests: `apps/dottie/tests/test_export_repair_transcripts.py`). Reproducible +
  deterministic from the ledger copy, except `repair_hint` (recomputed against
  the working-tree `diagnose_failure`).
- **Language producers:** failure text + corrected code were produced by the
  local research loop's LLM (qwen-family via Ollama) against the AVA factory
  harness — synthetic code, no third-party licensing or PII.

### Provenance classification
**HONEST-SYNTHETIC** — algorithmically produced by the org's own loop and
labelled as such. Not real-world code; not fabricated (every field is derived
from the ledger). See `data_provenance_SOP.md`.

### Personal and sensitive information
None. Synthetic neural-network code generated locally; no PII, no third-party
source.

## Considerations for Using the Data

1. **`corrected_code` is not the attempt+1 diff.** History persists
   attempt/ok/level/status/detail but not per-attempt source, so every row of one
   experiment carries the same final validated code. Dedup on `experiment_id`
   before per-pair loss weighting.
2. **Hints are recomputed, not historical.** `repair_hint` comes from today's
   `diagnose_failure` (shipped 2026-07-22, mined from this same ledger). The
   corrector that produced the recoveries saw raw tracebacks only — 0/12 rows had
   a hint at run time. Training on failure→hint then evaluating hint quality on
   this ledger is circular.
3. **`failure_detail` is pre-truncated** at 2000 chars.
4. **Small, survivor-biased.** 7 of 77 fail-touched experiments recovered;
   over-represents easy failure classes (F821, einsum, syntax), nothing for the
   hardest classes.

## Licensing
MIT (the exporter + the synthetic corpus). Solo personal project, no connection
to employer, built with public/free-tier only.

## Citation
Dottie research loop, `export_repair_transcripts.py`, 2026-07. Regenerate:
`python apps/dottie/scripts/export_repair_transcripts.py --db <ledger_copy> --out repair_transcripts.jsonl`
