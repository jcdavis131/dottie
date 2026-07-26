# Dottie Org — spec of record

> **Corrected 2026-07-25.** The first version of this file, written earlier the same day,
> opened with "**Status: SPEC-ONLY. No code exists yet.**" That was **wrong**. It was written
> from the operator's objective without searching the machine for prior art. The objective is
> substantially built: four domain models with real commit histories, a detailed joint-embedding
> architecture document, and a binder trainer. What follows replaces it.

## What this file is now

The design of record for the joint embedding is **not here**. It is
`~/vector-unified/docs/UNIFIED_ARCHITECTURE.md` (dated 2026-07-10), which is more specific
and better grounded than anything this file proposed. This file's job is to (a) map the
estate, (b) record what alignment work was done, and (c) name what is genuinely missing —
not to re-design something already designed.

## The estate — measured 2026-07-25, not assumed

| project | domain | commits | remote | state |
|---|---|---|---|---|
| `~/vector-hoops` | NBA | **318** | `jcdavis131/vector-hoops` | **64-d** (was documented 48-d; corrected 2026-07-26), 17 ResidualMLP towers (160→32), concat 556→256→64, MTNN v5 |
| `~/vector-gridiron` | NFL | 20 | `jcdavis131/vector-gridiron` | 32-d, 13 ResidualTowers (→24), gated attention, MTNN v2, **temporal split** |
| `~/vector-pitch` | Soccer (WC) | 14 | `jcdavis131/vector-pitch` | 16-d z-scored, PCA(3), k-means(8) — **no neural net** |
| `~/vector-equities` | Equities | 12 | `jcdavis131/vector-equities` | published embedding space + sector-coherence eval; has CI, ruff, pre-commit |
| `~/vector-unified` | **the binder** | 1 | **private** (2026-07-26) | 28 py / 5,397 lines, `train_unified.py`, `eval_unified.py` |
| `~/vector-hub` | — | 3 | none | landing page for **dumbmodel.com** (not a model) |
| `~/vector-tennis`, `~/vector-golf` | — | 0 | none | empty scaffolds |

**Domains in the operator's objective with no project yet: College Football, Baseball,
Hockey.** Equities-private also has no project — see the hard gate below.

## Design of record — summarised, authority is the source doc

From `~/vector-unified/docs/UNIFIED_ARCHITECTURE.md`:

> Treat each **sport** as a **modality**, treat **abstract role archetypes** as the **shared
> semantics**, and learn a single **64-d L2-normalized** space in which a player's location
> encodes *what role they play* regardless of *which sport they play it in* — while every
> per-sport task the live games depend on keeps working at least as well as today.

Two properties of that design worth restating because they are easy to lose:

1. **It is additive.** The unified model must not regress any per-sport model. The live games
   depend on those.
2. **It already picked an anchor, and it is not the one this file previously proposed.** An
   earlier draft here argued for **text** as the ImageBind anchor, reasoning that the domains
   do not co-occur so the anchor cannot be another sport. The existing design instead uses
   **abstract role archetypes** as the shared semantics. Both solve the same problem —
   ImageBind needs one shared thing every modality pairs with — and **the existing choice is
   the one in force.** Role archetypes have the advantage of already existing in the per-sport
   models (8 archetype heads in hoops, k-means(8) in pitch). Text remains a plausible *second*
   bridge if role archetypes prove too coarse, and is the natural one if the Dottie foundation
   LLM is ever brought in as an encoder — but that is a future option, not the plan.

**Prior art that already exists and should not be rebuilt:** hoops already trains **InfoNCE
career pairs**, so contrastive learning is in the codebase, not a new capability. Gridiron
z-scores **on train only with a temporal split**, and its HEAD commit is literally "Add
walk-forward weekly rank backtest". Pitch is the outlier: PCA + k-means, no network.

### Verified against the code 2026-07-25 — three numbers in the design doc are stale

An independent read of `~/vector-hoops` (every claim `file:line`-checked) contradicts the
summary table above, which was itself copied from `UNIFIED_ARCHITECTURE.md`. **Cite these,
not the doc:**

| | `UNIFIED_ARCHITECTURE.md` / README say | the code and artifacts say |
|---|---|---|
| embedding dim | 48-d | **64-d** — `pipeline/data/mtnn_report.json → "dim": 64`; `assets/mtnn_embeddings.f32` is 3,319,296 B = 12,966 × 64 × 4 |
| features / families | 120 in 17 families | **130 in 18 families**; `injury` is dropped unconditionally (`train_mtnn.py:1349`) → **126 features across 17 towers** |
| fusion | concat 544+season → 48 | concat **556 → 256 → 64**, then L2-norm (`ConcatFusion`, `train_mtnn.py:338-370`); season is a learned `nn.Embedding(n_seasons, 12)`, concatenated not added |

**The shipped model is NOT held out.** `--phase final-refit` sets `fit_rows="all"`
(`train_mtnn.py:1478-1479`) and `train.sh:161` passes exactly that, so the published
embedding is trained transductively on all 12,966 rows while the reported metrics come from
an earlier selection run. `assets/manifest.json` says so outright:
`"mtnn_eval_protocol": "transductive (atlas) — trained on all rows; NOT held-out"`. So the
temporal-split discipline is real **in model selection** and absent **in the shipped
artifact** — do not read "walk-forward exists" as "the shipped numbers are held out".

**Two disagreeing splits, two different numbers, both published.** `train_mtnn.py:846-853`
splits temporally (train ≤2021 / val ≤2023 / test ≥2024) and reports **test recall@10 =
0.846**. `pipeline/leakfree.py:42-71` splits by **md5 hash of player name** and is the source
of the README's **0.977** — but that run carries only 5 loss terms (`ablate_v5.py:80-86`), not
the shipping trainer's 16 heads. `leakfree.py`'s own docstring says it "measures
generalization to an UNSEEN PLAYER, not temporal forecasting". A third boundary again in
`train_career_mtnn.py:36-42`. Any spec quoting a hoops number must say **which protocol**.

**Dead code, so nobody builds on it:** `train_towers.py` is the v2 ancestor — writes
`embedding_v2.npz`, nothing reads it. `train_mtnn_v6.py` is a 31-line stub that
`sys.exit()`s and tells you to use `train_mtnn.py --era-align/--robust-scaling`; two docs
still instruct you to run it. `train_mtnn.py` is the only real trainer.

### Why the binder is genuinely new work, not an extension

The contrastive machinery in hoops is **intra-modal**. Both InfoNCE views are rows of *the
same tabular matrix* — a feature-dropout augmentation and the same player's adjacent season
(`train_mtnn.py:1556-1562`). The 17 "towers" are **feature-group MLPs over one table, not
modality encoders**, and they are combined by flatten-concat through one linear layer, which
is structurally the opposite of a binding architecture. A repo-wide search for
`ImageBind|cross.?modal|cross.?domain|CLIP|multimodal` returns zero substantive hits
(`overflow-x: clip`, `np.clip`, `clip_grad_norm_`), and `pyproject.toml` declares only
`numpy` and `torch`.

**So: the contrastive *loss* is reusable; the cross-domain *architecture* has to be built.**
Anyone reading "hoops already does InfoNCE" as "the binder is nearly done" will be wrong.

⚠ **Provenance flag on the shipped hoops artifact.** `mtnn_report.json → promote` is
`{"ok": false, "reason": "CQS 78.11 < promote bar 82.62"}`, yet the 64-d artifact shipped
the same day. `composite_score.py:88-95` records that it was promoted "not by clearing the
CQS bar, which it does not", justified on a manual held-out top-5 comparison (0.363 → 0.757)
that **no artifact in the repo records**. A number that cleared no gate is exactly the shape
of the three research `sota` rows that turned out to be artifacts. Re-derive it or retract it
before it anchors anything.

## Alignment performed 2026-07-25

**Three `vector-hoops` checkouts existed at three different commits**, all sharing the same
remote — the same hazard class as the stale `__editable__.scout_cli-0.7.0.pth` that shadowed
`bigbang` and produced eight phantom failures.

| checkout | commits | last commit | dirty | verdict |
|---|---|---|---|---|
| `~/vector-hoops` | 318 | 2026-07-25 09:56 | 0 | **CANONICAL** — 0 ahead / 0 behind origin |
| `~/workspace/vector-hoops` | 171 | 2026-07-16 | 72 untracked | stale clone |
| `~/Documents/projects/vector-hoops` | 8 | 2026-07-05 | 0 | stale clone |

Nothing is stranded: canonical is fully synced with origin, and the 72 dirty files in the
stale copy are all **untracked** debug artifacts (`arena-*.png`, `_bump_cache.py`,
`assets/arena_topo/`). Neither stale copy was deleted — that is the operator's call, and
deleting a checkout to tidy up is how genuinely unpushed work disappears.

⚠ A claim in the previous turn's report — that `~/Documents/projects/vector-hoops` was "the
only one with `train_towers.py`" — was **wrong**, caused by a `head -5` truncating an
alphabetical listing before it reached that filename. All three have it.

**`~/vector-unified` had no version control at all** and now does (`e44774c`, 37 files, 7,053
lines). Excluded deliberately: generated artifacts (`assets/unified.json`, 16.7 MB), acquired
`data/` (27 MB), and `pipeline/cache/` (~30 MB of scraped HTML). That last one was caught by
inspecting `git diff --cached` *before* committing — staging had initially ballooned to
581,566 lines. **The commit is local only**; a remote is the operator's call.

## What is genuinely missing

1. ~~A remote for `vector-unified`~~ — **DONE 2026-07-26**: private remote created and pushed, so it is no longer the one repo in the estate without off-disk protection.
2. **Three domains with no project**: College Football, Baseball, Hockey.
3. **Pitch has no neural encoder** — PCA + k-means. Binding a 16-d PCA space to two learned
   spaces is not the same problem as binding two learned spaces, and the architecture doc
   should say which it intends.
4. **A pre-registered test of emergent cross-domain alignment.** The ImageBind claim is that
   alignment appears between pairs never trained together. That is a *falsifiable* claim and
   it needs its metric written down **before** it is measured, or a null result gets
   reinterpreted as a win. The platform's history makes this non-optional: all three recorded
   research `sota` rows to date were artifacts.
5. **Entity resolution across domains** — stable identity for players and tickers across
   trades, renames, relocations and ticker changes. Identity drift silently degrades a shared
   space.

## Hard gates — unchanged

- **Equities private data: do not ingest** until the operator confirms in writing the source
  and the terms permitting training use. Non-public data carries contractual redistribution
  and derived-work limits that no licence tag expresses.
- **Licence gate is deny-by-default** (`apps/ava-factory/scripts/dataset_discovery.py`): any
  `-nd` denied outright (training is a derivative use), any `-nc` denied, unverified is not
  permissive, and every asserted licence on a record must pass.
- **Model-output provenance is a second dimension** a licence cannot express — a dataset can
  be MIT-tagged while its content was generated under terms forbidding competitor training.
- **Shadow libraries are forbidden** ingestion sources regardless of licence field.
- If any downstream use involves wagering, jurisdiction rules apply. Flagging, not advising.

## Relationship to Dottie

Dottie (`apps/ava-factory`) trains a **nano language model** — `factory_lm_loss = 5.73733`.
It is not training an embedding model and, as of 2026-07-25, is not training at all
(`pipeline: TimeoutError`). The vector estate is a **separate, more advanced** line of work.
The two meet only if the foundation LLM is later used as a text encoder for the anchor — an
option, per the design-of-record note above, not the plan.
