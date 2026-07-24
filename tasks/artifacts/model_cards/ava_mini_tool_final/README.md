---
pretty_name: ava-mini (tool_final @ step 2861)
license: mit
language:
- en
- code
tags:
- jspace
- small-language-model
- multi-timescale
- dottie
model_info:
  base_preset: mini
  params_note: ≈270M analytic (untied 4-workspace verbalizers); 171M nominal preset
  d_model: 768
  n_layers: 12
  jspace_split: 3T/6F/3R
  n_heads: 12
  mlp: swiglu
  vocab_size: 32000
  max_context: 4096
  eval_metric: weighted_heldout_ppl
  eval_value: 2268
  eval_tokens: 6360000
  eval_method: disjoint held-out bins (HELDOUT_SEED), tool_final@2861, all 6 phases
  eval_retracted: 275.95 / 4103 (contaminated + tiny bins — unreliable, do not cite)
  provenance_classification: REAL
---

# ava-mini (tool_final @ step 2861)

## Model Summary

The org's own small language model — a **J-Space multi-timescale transformer**
(four workspaces updated at different half-lives) trained by the AVA factory on
the six-phase curriculum. This card is the checkpoint `tool_final.pt` at step
2861 (2.4997B tokens, exit 0). Governance per
`tasks/artifacts/data_provenance_SOP.md`; the honesty doctrine applies to every
number below.

**Nothing here is a claim of frontier quality** — it is a small research model,
and the point of this card is to report its ONE trustworthy eval number honestly,
with the retracted numbers named so they are never re-cited.

## Architecture

| field | value |
|---|---|
| preset | mini |
| d_model | 768 |
| layers | 12 (3 text / 6 fusion / 3 reasoning) |
| heads | 12 |
| MLP | SwiGLU (ratio 4.0) |
| vocab | 32000 |
| max context | 4096 (YaRN/NTK extended in p4/p5) |
| J-Space workspaces | system1 / system2 / critic / planner, half-lives 8 / 300 / 30 / 150 steps |
| params | ≈270M analytic (each of the 4 workspaces owns a `[vocab, d_model]` verbalizer — untying costs 4×32000×768 ≈ 98M; the "mini" nominal label is ~171M) |

Source: `apps/ava-factory/configs/mini.yaml` (committed).

## Evaluation — the honest number

**Weighted held-out perplexity: 2,268** over **6.36M tokens** (token-weighted
geometric mean across all six phases).

| phase | p0 | p1 | p2 | p3 | p4 | p5 |
|---|---|---|---|---|---|---|
| ppl | 3506 | 997 | 22440 | 2134 | 335 | 4.9 |

- **Method:** the held-out bins were rebuilt disjoint from training via
  `HELDOUT_SEED = SEED + 1e9` (the eval-integrity fix), then `tool_final@2861`
  scored on all six phases. This is the **first reliable perplexity number** for
  this model.
- **⚠ RETRACTED — do not cite:** the earlier **275.95 / 2341 / 4103** A/B figures
  are unreliable. The held-out bins they used were built with the SAME seed as
  the collector's epoch-0 training docs (contaminated) AND were tiny (~30k
  tokens). The honest number came out *higher* than the contaminated 275.95 and
  *lower* than the contaminated 4,103 — the delta is confounded (contamination +
  sample size together), so it is not a clean memorization measurement. A real
  baseline A/B requires re-running step-1487 on the honest bins.

Source: `tasks/artifacts/provenance_audit_MASTER.md` (committed), eval-fix commit
`6ba0ac5`.

## Provenance classification

**REAL** — measured from a real forward pass of the real checkpoint on
decontaminated held-out data. The retracted numbers are named so they cannot be
laundered back into a metric. See `data_provenance_SOP.md`.

## Training

Six-phase curriculum (p0 logic → p1 math → p2 foundation → p3 reasoning → p4
long-context → p5 anneal), 2.4997B tokens, bf16 on a single RTX 4080, run exit 0
at step 2861. Curriculum + sources: `apps/ava-factory/configs/mini.yaml` and
`sources.yaml` (all sources REAL/HONEST-SYNTHETIC; see the Hub dataset cards).

## Considerations

- A small research model on modest compute — perplexity is high in absolute terms
  (esp. p2 foundation); this card exists to report it *honestly*, not to impress.
- The checkpoint binary (`tool_final.pt`) lives on the training box, not in this
  repo; this card + the committed config + audit are its provenance record.
- p5's ppl 4.9 reflects the anneal-phase template fit on a narrow mix, not general
  capability — read per-phase numbers with the curriculum mix in mind.

## Citation

ava-mini `tool_final.pt` @ step 2861, honest held-out eval 2026-07-24. Reproduce
the eval bins: `python apps/ava-factory/scripts/build_eval_data.py --force`
(uses `HELDOUT_SEED`), then re-run the harness on `tool_final`.
