# Data Provenance SOP — real, verified, credible data for every model

Operator directive (2026-07-24): "ALWAYS use real and verified data sources and
follow a strict SOP for building our own so we can maintain credibility and
provenance." Garbage in, garbage out. This SOP is the standing rule for any data
that trains, evaluates, or is publicly attributed to a model. It extends the
repo-wide honesty doctrine ("every number renders from a real source") to the
data layer.

## The one rule

**No value enters a training set, an eval set, or a public surface unless its
provenance is recorded and it is either (a) real measured data, or (b) synthetic
data explicitly labeled synthetic.** A fabricated, random, placeholder, or
hardcoded value presented as real is a defect of the same class as a lying
metric — it destroys credibility and, in training/eval, silently corrupts the
model or its scoreboard.

## Classification every data source must carry

Tag each dataset/asset with one of:
- **REAL** — measured from a real source (a public dataset, a real model's
  forward pass, a real run). Record the source + method.
- **HONEST-SYNTHETIC** — algorithmically generated and *labeled as such*
  (e.g. a math-problem generator, a templated tool-use trace). Valid for
  training/eval WHEN the label travels with it and the task is genuinely learned
  from the synthesis. Never dress synthetic as real.
- **PLACEHOLDER** — a stand-in awaiting real data. MUST carry a machine-readable
  contamination marker (see below) and MUST NOT be counted in any published
  metric or fed to training as if real. The equities
  `placeholder_contamination` block is the reference pattern.
- **FORBIDDEN** — `np.random`/`random` values used as features or labels,
  hardcoded metric literals, copy-pasted numbers from another repo, `i % len`
  fake assignments, or any value invented to look like signal. These never ship.

## Required provenance metadata (on every dataset/asset)

Every generated dataset or shipped asset carries a sidecar (or inline block):
```
{ "source": <where the data came from>,
  "method": <script:commit that produced it>,
  "computed_at": <ISO timestamp>,
  "classification": REAL | HONEST-SYNTHETIC | PLACEHOLDER,
  "row_counts": {...},
  "contamination": <null, or {rows, mechanism, metric_bias, remediation}> }
```
A published metric computed over a set that contains any PLACEHOLDER rows MUST
either exclude them or carry the contamination block stating the bias direction.

## Build SOP (the strict sequence for building our own data)

1. **Name the real source first.** Before writing a generator, state where the
   ground truth comes from (public dataset, real model output, real run). If
   there is no real source, the output is HONEST-SYNTHETIC and must say so.
2. **Separate generation from labeling.** The value and its label come from the
   same real computation, or the label is derived by a verifiable rule — never a
   random or hardcoded stand-in.
3. **Decontaminate.** Eval/held-out sets are built disjoint from training data,
   with a real leakage check (fixed-stem/decon discipline). Never evaluate on
   data the model trained on.
4. **Verify a sample.** Before a dataset is used, audit N random rows by hand:
   does each value trace to its stated source? Wrong gold answers, random
   features, and placeholder metrics are caught here.
5. **Stamp provenance.** Write the metadata block. No block → the data does not
   ship.
6. **Gate.** A dataset used for training or a published metric passes a
   provenance check (the block is present, classification is REAL or
   HONEST-SYNTHETIC, no PLACEHOLDER rows in published metrics) before use.

## Anti-patterns (from real findings this session)

- Shipping `np.random.rand(12)` as "skills" in a public asset (vector-equities).
- Hardcoded metric literals (`cqs 0.6347`, `val_recall 0.882`) in a shipped
  asset with no computation behind them (vector-equities).
- A dashboard displaying a model stack that does not exist, numbers copy-pasted
  from a sibling repo (vector-pitch).
- Placeholder embeddings (sector-centroid + Gaussian noise) counted in a
  published coherence metric without a contamination flag (vector-equities S&P
  rows — since annotated).
- A scoreboard tabulating an HTTP-500 errored run as a real datum (agent-eval).
- A baseline seeded to a hand-picked placeholder value, then "beaten"
  (research-loop MLBR / the 4.5 placeholder).

## Enforcement

- The three provenance audit reports (`provenance_audit_{training,vectorsites,
  evals}.md`) are the current-state assessment; findings become fix tickets.
- New generators land with a provenance block + a sample audit (per the
  adding-a-curriculum-generator discipline).
- Public metrics get a provenance line in review; a number with no traceable
  computation is a blocker.

## Dataset card structure (HF-standard) — every custom dataset we build

Model the structure on The Stack v3
(https://huggingface.co/datasets/HuggingFaceCode/stack-v3-train). Each dataset
we build ships as its own directory: `README.md` (the card) + the data file(s),
co-located and HF-loadable. The card is:

1. **YAML frontmatter** — machine-readable metadata: `pretty_name`, `license`,
   `task_categories`, `language`, `tags`, `size_categories`, `configs`
   (`config_name` + `data_files` with split→path), and `dataset_info` with typed
   `features` (name + dtype for every column) and `splits` (name + num_examples).
   ADD `provenance_classification: REAL | HONEST-SYNTHETIC | PLACEHOLDER` under
   `dataset_info` — the SOP field on the card itself.
2. **Sections**, in order: Dataset Summary → Data Structure/Fields (typed schema
   table) → Splits (row counts) → Dataset Creation (Source data, Integrity or
   reproducibility, **Provenance classification**, Personal/sensitive info) →
   Considerations for Using the Data (the honest limitations/contamination) →
   Licensing → Citation (with the exact regenerate command).

Reference exemplars in this repo:
`tasks/artifacts/corpus_proposals/repair_transcripts/README.md` (HONEST-SYNTHETIC)
and `.../gridiron_forecast_rows/README.md` (REAL). A dataset without this card
does not ship — the card IS the provenance metadata block for datasets.

*This SOP is the standing rule; the audit findings below drive the remediation.*
