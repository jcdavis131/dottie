# Spec 0008 — Eval Harness & Deploy Gates (salvaged)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source path: `specs/0008-eval-harness-and-gates.md`
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: retired-method (ASN) implementation pointers and worker/serving plumbing notes
>   annotated or removed; gate definitions, thresholds, and fail-closed doctrine carried
>   verbatim. Monorepo paths left in place refer to the deprecated repo, not to dottie.

**Why salvaged:** this file defines the exact gates the slasso.com certification dashboard
must render, and its fail-closed philosophy matches dottie's provenance doctrine. The
executable form (`packages/eval-harness/` in the source repo) is salvage-later; this
document is the normative gate definition.

---

## Problem (original framing)

Product claims about model quality must be **falsifiable in CI**, not asserted in marketing
copy (source repo `SCIENCE_REVIEW.md` §5).

## Goals

- Reusable metrics: effective rank, nDCG@10, deploy gates.
- Worker and `/v1/eval/*` share the same harness.
- Gates recorded on `model_versions.meta` for operator review.

## Design

### Package (source repo `packages/eval-harness` — salvage-later)

| Module | Purpose |
|---|---|
| `metrics.ndcg_at_k` | nDCG from relevance list |
| `metrics.retrieval_scores` | Cosine rank query vs docs |
| `gates.compute_gates` | rankAboveBaseline, ndcgNonRegression, mrlWithinTolerance |
| `runner.evaluate_checkpoint` | Load checkpoint, pairwise nDCG, effective rank, gates |

### Gate thresholds (v0.3) — normative

- `rankAboveBaseline`: effective rank > 8.0
- `ndcgNonRegression`: nDCG@10 >= 0.35 (pairwise eval on real collection pairs)
- `mrlWithinTolerance`: fails closed when Matryoshka retrieval is unmeasured (no stub `True`)
- `sufficientEvalPairs`: >= 8 real collection pairs required (REV-905). Below the floor the
  gate fails closed — the eval service returns `allPassed=False` with
  `metrics.skipped="insufficient_real_pairs"` and does **not** substitute demo pairs. The
  hard-coded demo pairs survive only behind an explicit `allow_demo=True` opt-in for manual
  smoke; no production caller sets it. Train minimum stays 10.

### API (as implemented in the source repo)

- `POST /v1/eval/run` — run harness, persist `ndcg10`, `effective_rank`, gates on model row.
- `GET /v1/eval/{model_version}/gates` — read or lazy-run gates.

## Evaluation gate (this spec)

| Metric | Dataset | Rule |
|---|---|---|
| Effective rank | Contrastive pairs from collection | > baseline 8.0 |
| nDCG@10 | Pairwise anchor vs pos/neg (k=2) | >= 0.35 |
| sufficientEvalPairs | Real collection pairs | >= 8 (fail closed, no demo fallback — REV-905) |
| Combined | `allPassed = all(gates.values())` | Recorded; promotion policy per Spec 0012 charters |

## Doctrine carried forward (the load-bearing part)

1. **Fail closed.** An unmeasured gate is a failed gate. No stub passes, no demo-data
   substitution on the production path.
2. **Gates are recorded, not asserted.** Results persist on the model record for operator
   review; claims in copy trace back to a recorded gate result.
3. **Honest retraction.** The source repo's acceptance record notes the rank gate was
   *not met* on early ablations and that ~62 prior deploy reports were **retracted** after a
   measurement bug. Retractions are stated next to the numbers they replace — the dashboard
   inherits this rule.

## Known limits (from the original risks section)

- Demo pairwise nDCG is not a full retrieval benchmark; the slasso.com exam engine is the
  surface-level test.
