# Dottie Org — spec of record

**Status: SPEC-ONLY. No code exists yet.** This file records the operator's objective and
the decisions it forces, so that whoever implements it does not have to re-derive them.
Sequenced *after* Dottie passes testing at bhenre.com — see root `SPEC.md`.

## Operator objective (2026-07-25, verbatim intent)

> Train individual multi-tower → multi-task deep neural networks for each domain
> (NBA / NFL / College Football / Baseball / Hockey / Soccer / Equities public+private) so we
> get embedding vectors for each domain, then train a downstream model using a similar
> architecture to ImageBind to generate the universal model binding the domain models
> together into a universal model.

Reference: <https://github.com/facebookresearch/imagebind>

Dottie Org is also named as the creator of **dumbmodel.com** and **vector games** — both
currently undefined here; they need their own one-liners before they can be built.

## Shape

```
per domain d ∈ {NBA, NFL, CFB, MLB, NHL, Soccer, Equities-public, Equities-private}:
    multi-tower encoder  →  shared trunk  →  multi-task heads
                                │
                                └─→  z_d  (domain embedding vector)

then:  {z_d}  →  ImageBind-style contrastive binder  →  universal embedding space
```

## The one architectural fact that decides everything

ImageBind does **not** train all-pairs. Each modality is trained contrastively against
**one anchor modality** (images), using only (anchor, modality) pairs; alignment between
modality pairs never trained together then appears *emergently*. That is the whole trick —
it turns an O(n²) data problem into O(n).

**So the binder needs an anchor, and the anchor choice is the central open decision.** Two
things make this harder here than in the paper, and they must not be glossed:

1. **These domains do not co-occur.** ImageBind's pairs are genuinely simultaneous
   observations of one event (the audio and the video of the same clip). An NBA game and an
   NFL game are not two views of one thing. There is no natural (NBA, NFL) pair to learn
   from, so the anchor cannot be another sport.
2. **Therefore the anchor must be something every domain independently pairs with.** The
   strongest candidate is **natural-language text** — every domain has dense independent
   textual coverage (game reports, box-score narratives, injury notes; filings, earnings
   calls, news). Each domain then trains as (text ↔ z_d), and cross-domain comparability
   emerges through text.

**That makes Dottie's own foundation LLM the anchor encoder, which is why the two halves of
the roadmap are one project rather than two.** The foundation model is not just a product —
it is the binder's shared coordinate system.

⚠ **Unverified:** the ImageBind mechanics above are stated from the paper's design as
understood, not from reading the linked repo — outbound HTTPS from the dev box is currently
failing (curl exit 35, urllib WinError 10054, WebFetch ECONNRESET on three separate
attempts). **Verify against the repo before building.** Specifically confirm: the loss
(InfoNCE with learnable temperature), whether the anchor encoder is frozen or co-trained,
and how modality-specific heads are dimensioned.

## Open decisions — operator's, not the implementer's

| # | Decision | Why it cannot be defaulted |
|---|---|---|
| 1 | **The anchor modality.** Text (recommended above) or a constructed entity-time key? | Determines the entire data-pairing effort. Getting it wrong is a full restart, not a tuning pass. |
| 2 | **What "multi-task" means per domain** — enumerate the heads (win probability? spread? totals? player-level props? return forecast? volatility?). | "Multi-task" currently names a shape with no tasks in it. Heads define the labels, and labels define the data collection. |
| 3 | **What the towers are** per domain (e.g. team / player / context / market). | Tower decomposition is domain modelling, not architecture. |
| 4 | **Whether the universal model has a task at all**, or is only a shared embedding space to be probed. | Changes whether success is measurable by a metric or only by downstream transfer. |
| 5 | **Equities-private scope.** | See the hard gate below — this one has legal consequences, not just technical ones. |

## Invariants — inherited from the platform, plus two this domain forces

Carried over from root `SPEC.md` (these are not optional):

- **Provenance travels with every number.** A metric renders only from a real source; an
  unreachable source is labelled, never faked. Stale is "history, not telemetry".
- **Nothing auto-ingests into training.** A discovered dataset is a candidate, not an input.
- **License gate is deny-by-default.** Any `-nd` component is denied outright (training is a
  derivative use); any `-nc` component is denied (revenue mission); unverified is not
  permissive. Enforced by `apps/ava-factory/scripts/dataset_discovery.py::gate_license`.
- **Shadow libraries are forbidden ingestion sources** regardless of licence field.

New, and specific to sports/finance modelling:

- **TEMPORAL SPLITS ONLY — no random splits, ever.** Walk-forward / strictly time-ordered
  evaluation. A random split leaks the future into training and is *the* reason
  sports and finance models look excellent offline and fail live. This is the single most
  likely way this project produces a fake win, and the platform already has a hard lesson
  about fake wins: all three recorded research `sota` rows to date were artifacts. Any
  eval harness for Dottie Org must make a random split impossible to express, not merely
  discouraged.
- **Entity resolution is a first-class component, not glue.** Cross-domain binding requires
  stable identity for teams, players, and tickers across sources and across time (trades,
  renames, relocations, ticker changes, corporate actions). Identity drift silently
  destroys a shared embedding space.

## Hard gate — Equities private data

**Do not ingest any non-public equities data until the operator has confirmed, in writing,
the source and the terms under which it may be used for model training.** Non-public data
routinely carries contractual redistribution and derived-work restrictions that a licence
tag cannot express, and material non-public information carries obligations beyond the
project's own rules. This is deliberately a stop, matching the existing doctrine that an
unverified licence is not a permissive one — the same reason the `stack-v3` ingestion is
still blocked rather than assumed.

Separately: if any downstream use involves wagering, the applicable rules vary by
jurisdiction. Flagging, not advising — that determination is the operator's.

## Reusable today

| Asset | Path | Use here |
|---|---|---|
| Trainer + data pipeline | `apps/ava-factory` | per-domain tower training |
| Eval-gate doctrine (anti-mock, provenance-honest) | `packages/ava-open-harness` | keeps a fake win from scoring |
| Licence gate (deny-by-default) | `apps/ava-factory/scripts/dataset_discovery.py` | every domain corpus passes it first |
| Agent CLI | `apps/scout-cli` | the assistant that builds this |
| Site / console | `apps/bluehenre` → bhenre.com | where results get shown, honestly |

## Definition of done (v0 — operator to confirm or redirect)

1. One domain end-to-end (recommend **NBA**: densest public play-by-play, cleanest entity
   resolution) — towers → heads → `z_d`, evaluated walk-forward.
2. A second domain reusing the same code with only config changes, proving the shape
   generalises before any binder work starts.
3. The binder trained on (text ↔ z_d) for those two domains, with a stated,
   pre-registered test of *emergent* cross-domain alignment — i.e. the metric is written
   down before it is measured, so a null result cannot be reinterpreted as a win.
