# Dottie Site — SPEC of record (2026-07-24)

The operator's goal: the Dottie site is **a Manus/OpenClaw/Hermes-style agentic
personal assistant for guiding the Agentic Org + a HuggingFace-style
datasets/models/research hub + a Weights&Biases-style real-time monitor of the
local development the org runs** — one product with three faces.

## The one principle (the differentiator)

Manus/HF/W&B are the *shapes*. The Dottie difference is **provenance-honesty by
construction**: every number renders only from a real source; every dataset and
model carries its classification (REAL | HONEST-SYNTHETIC | PLACEHOLDER) per
`tasks/artifacts/data_provenance_SOP.md`; the assistant is `[dottie]`/`[offline]`
honest and never fabricates; nothing auto-ingests into training. This is the
anti-fabrication HF+W&B+Manus for an autonomous org — and it is the payoff of the
2026-07-24 provenance work.

It is built **additively on the existing `apps/bluehenre` console** (amber
terminal PWA + org console), not a rewrite. Everything static-first so it works
identically on localhost and Vercel.

## Pillar 1 — GUIDE (Manus / OpenClaw / Hermes)

The agentic-assistant face. Grows the one-line `DOTTIE//ASSISTANT` card into a
real assistant that guides the org:
- **Converses grounded in live telemetry** — renders the real Dottie engine's
  ReAct trace (thought → action → observation → **trust-gate stamp incl.
  DENIED**), not a flattened reply string. Honestly-absent when the engine field
  is missing; `[dottie]`/`[offline]` stamped.
- **"What should I do next"** — a deterministic, engine-independent digest ranked
  from the REAL alert list (`parseLiveEvents`), research-queue counts, and fleet
  health, each next-action carrying its steer command (reusing the copy+open-gist
  bar).
- **Shows the three autonomous agents working** — research loop, docker fleet,
  workflow orchestration — from live telemetry.
- Write-path stays the steer channel (owner-only, GitHub-login auth).
- Data: `POST /api/npc-chat → DOTTIE_CHAT_URL` (factory hub `/assistant` ReAct
  trace, `/chat` fallback); `GET /api/twin-status` for grounding.
- Open question: does the engine expose ReAct `steps[]`, or only the flattened
  reply? If the latter, the trace surface waits on an engine field while the
  digest + agent tiles ship now.

## Pillar 2 — HUB (HuggingFace)

The honest artifacts face — a browsable registry of the org's OWN datasets,
models, and research, **each card stamped with its provenance classification and
an honest eval**. The substrate already exists: two HF-standard dataset cards
(`tasks/artifacts/corpus_proposals/{gridiron_forecast_rows REAL, repair_transcripts
HONEST-SYNTHETIC}`) with `provenance_classification` frontmatter + sha256-pinned
audit sidecars, the SOP's four-class taxonomy, and the live feed's model/eval
data. Today `grep PLACEHOLDER|HONEST-SYNTHETIC` across the app returns zero —
nothing renders provenance yet. That gap is the Hub.
- **Dataset cards** — from the corpus_proposals card frontmatter (+ future
  training corpora, vector-site data) with classification badge + row counts +
  integrity (sha256 cross-check).
- **Model cards** — checkpoints + vector-site MTNNs with **honest eval** (the
  real 2,268 ppl, never the retracted 275.95; the vector eval artifacts).
- **Research** — ledger experiments, the audit reports, the design notes.
- **Bidirectional with real HF** — publish org artifacts / browse open-source.
  DEPENDS ON the `HF_TOKEN` rotation (MASTER audit #6): ship the mirror dormant
  with an honest "awaiting rotation" until rotated, then wire push.
- Data: static `hub_registry.json` rebuilt by a read-only exporter from the
  card frontmatter + audit sidecars (Vercel-safe, no server dependency).

## Pillar 3 — MONITOR (Weights & Biases)

The real-time local-dev face. Live monitoring of what the org's agents are doing:
training curves, research-loop experiments/promotions, fleet stats, run
comparison — all real-measured.
- **Backend = the `runtrack` sqlite tracker** (scout-cli openswap W&B-lite) wired
  to the live trainer/research metrics + the ledger, plus the existing feed
  chain (pipeline curves, fleet stats, site probes).
- Everything real; stale = "history, not telemetry"; offline = offline.

## Architecture

All three pillars are cards/surfaces on the existing bluehenre console (amber
terminal `index.html`/`console.mjs` + org console `org.html`/`org.mjs`), fed by
the honest telemetry chain (`publish_live_status.py` → gist → hosted APIs) plus
three new static/additive read-side artifacts (`hub_registry.json`, runtrack
readouts, the assistant trace passthrough). Pure parsers in `twin.mjs` with
contract tests (`twin.contract.test.mjs`). Zero frozen-path edits; static-first
so local == Vercel.

## Honesty doctrine (non-negotiable, every pillar)

Numbers render only from `source:"local"` real feeds; stale = "history, not
telemetry"; unreachable = offline; datasets/models carry REAL/HONEST-SYNTHETIC/
PLACEHOLDER; the assistant is `[dottie]`/`[offline]`, never fabricated; nothing
auto-ingests into training. A card with no traceable provenance does not render.

## Build order — see tasks/plan.md
First slice: the HUB Artifact Registry (substrate is ready — the two cards
exist), fully additive, static, Vercel-safe. Then Guide digest+tiles, then
Monitor runtrack readout, then the engine-dependent + HF-push pieces.
