# The Dottie Site — spec of record

**Operator vision (2026-07-24):** the Dottie site is **a Manus / OpenClaw /
Hermes-style agentic personal assistant for guiding the Agentic Org + a
HuggingFace-style datasets/models/research hub + a Weights&Biases-style
real-time monitor of the local development the org runs** — one product with
three faces, linked to the operator's real local development being run by the
Agentic Org.

It is built **additively on the existing `apps/bluehenre` console** (a
mobile-first amber-phosphor retro terminal PWA + org console), not a rewrite.
Everything is static-first so it works identically on localhost and Vercel.

## The one principle (the differentiator)

Manus, HuggingFace, and Weights&Biases are the *shapes*. The Dottie difference
is **provenance-honesty by construction**: every number renders only from a real
source; every dataset and model carries its classification
(REAL | HONEST-SYNTHETIC | PLACEHOLDER) per
`tasks/artifacts/data_provenance_SOP.md`; the assistant is `[dottie]`/`[offline]`
honest and never fabricates; nothing auto-ingests into training. This is the
anti-fabrication HF+W&B+Manus for an autonomous org.

## Mission it serves

Build SOTA models faster by researching every piece of the stack → generate
insights with those models → turn insights into revenue. The org runs
autonomously on the operator's box (RTX 4080, Windows + WSL2 Docker); the site
is how the operator guides it, browses what it produces, and watches it work —
from anywhere.

---

## Pillar 1 — GUIDE (Manus / OpenClaw / Hermes)

The agentic-assistant face. Grows the one-line `DOTTIE//ASSISTANT` card into a
real assistant that helps the operator guide the org:

- **Converses grounded in live telemetry** — renders the real Dottie engine's
  ReAct trace (thought → action → observation → **trust-gate stamp incl.
  DENIED**), not a flattened reply string. Honestly-absent when the engine field
  is missing; `[dottie]`/`[offline]` stamped.
- **"What should I do next"** — a deterministic, engine-independent digest ranked
  from the REAL alert list (`parseLiveEvents`), research-queue counts, and fleet
  health, each next-action carrying its steer command (reusing the copy+open
  steer bar).
- **Shows the three autonomous agents working** — research loop, docker fleet,
  workflow orchestration — from live telemetry.
- Write-path stays the steer channel (owner-only, GitHub-login auth; see below).
- Data: `POST /api/assistant-chat → DOTTIE_CHAT_URL` (factory hub `/assistant`
  ReAct trace, `/chat` fallback); `GET /api/twin-status` for grounding.
- Open question: does the engine expose ReAct `steps[]`, or only the flattened
  reply? If the latter, the trace surface waits on an engine field while the
  digest + agent tiles ship now.

## Pillar 2 — HUB (HuggingFace)

The honest artifacts face — a browsable registry of the org's OWN datasets,
models, and research reports, **each card stamped with its provenance
classification and an honest eval**. The substrate already exists: two
HF-standard dataset cards
(`tasks/artifacts/corpus_proposals/{gridiron_forecast_rows REAL,
repair_transcripts HONEST-SYNTHETIC}`) with `provenance_classification`
frontmatter + sha256-pinned audit sidecars, the SOP's four-class taxonomy, and
the live feed's model/eval data.

- **Dataset cards** — from the corpus_proposals card frontmatter (+ future
  training corpora, vector-site data) with classification badge + row counts +
  integrity (sha256 cross-check).
- **Model cards** — checkpoints + vector-site MTNNs with **honest eval** (the
  real 2,268 held-out ppl, never the retracted 275.95; the vector eval
  artifacts).
- **Research reports** — ledger experiments, the audit reports, the design notes.
- **Bidirectional with real HuggingFace** — publish org artifacts / browse
  open-source. DEPENDS ON the `HF_TOKEN` rotation (provenance audit #6): ship the
  mirror dormant with an honest "awaiting rotation" until rotated, then wire push.
- Data: static `hub_registry.json` rebuilt by a read-only exporter from the card
  frontmatter + audit sidecars (Vercel-safe, no server dependency).

## Pillar 3 — MONITOR (Weights & Biases)

The real-time local-dev face. Live monitoring of what the org's agents are
doing: training curves, research-loop experiments/promotions, fleet stats, run
comparison — all real-measured.

- **Backend = the `runtrack` sqlite tracker** (scout-cli openswap W&B-lite) wired
  to the live trainer/research metrics + the ledger, plus the existing feed chain
  (pipeline curves, fleet stats, site probes).
- Everything real; stale = "history, not telemetry"; offline = offline.

---

## The console today (the substrate we build on)

`/` — mobile-first, cozy amber-phosphor retro terminal; crisp full-resolution
text; warm browns/cream/gold; faint CRT scanlines. Existing cards:

- **RUN//AVA-MINI** — the training run: mode badge, step · loss, held-out ppl,
  throughput + ETA, checkpoint age, RUN and PHASE progress bars, flow-gate LEDs
  (D1–D5), shard funnel, lm-loss sparkline. 15s poll.
- **ALERTS//UNBLOCK** — REAL factory events (trainer stale/error, data starved,
  disk water-marks, red gates; benign full-runway pauses excluded), each naming
  the owning team + the feed's own words. Empty = "org unblocked".
- **DOTTIE//ASSISTANT** — chat with the org's assistant. Source-stamped
  `[dottie]` / `[offline]`; withheld beats fabricated. → grows into Pillar 1.
- **FLEET//DOCKER** — every running container (docker's own cpu%/mem), sorted by
  activity, 10s poll locally.
- **HUB//SUBSYSTEMS** — model card (params/layers/split), skills ecosystem, eval
  verdicts, research baseline ±SEM + queue counts. → grows into Pillars 2 & 3.
- **SITES//GLOBAL** — the org's deployed sites (the hub + the four vector
  prediction sites, arxiviq, bhenre.com) probed for liveness + latency.

## Data spine (shared, provenance-honest)

- Local server (`node server.mjs`, zero-dep): `/api/twin-status` (live
  `:8000/pipeline/status` → exported `dottie_live_status.json` → raw artifacts,
  freshness-capped), `/api/fleet` (docker CLI, 10s cache), `/api/assistant-chat`
  (Dottie engine via `DOTTIE_CHAT_URL` or honest offline).
- Hosted (Vercel prod, `vercel deploy --prod`): the same endpoints read the
  box's OWN published gist (publisher task runs every 10 min; 30-min freshness
  cap; `via:"gist-feed"`, ageS included). Real numbers publicly, box unexposed.
- Publisher (`apps/ava-factory/scripts/publish_live_status.py`, scheduled):
  pipeline + research + the full :8000 hub (network/ecosystem/agent-eval/eval
  report+catalog) + docker fleet snapshot + site probes.
- Three new static/additive read-side artifacts land as the pillars build:
  `hub_registry.json` (Pillar 2), the runtrack readouts (Pillar 3), the assistant
  trace passthrough (Pillar 1).
- Pure parsers + contract tests live in `public/js/twin.mjs` (bare-node
  `twin.contract.test.mjs`) — the only test suite.

## Honesty doctrine (non-negotiable, every pillar)

- Numbers render ONLY from `source:"local"` telemetry; stale feeds are "history,
  not telemetry"; unreachable blocks render as offline lines.
- Datasets/models carry REAL / HONEST-SYNTHETIC / PLACEHOLDER; a card with no
  traceable provenance does not render.
- Chat replies are `[dottie]` or `[offline]` — never fabricated.
- Nothing auto-ingests into training; the operator feeds the factory explicitly.

## The write path — the steer channel (CONNECTED)

**Steer channel = comments on the steer gist**
(`gist.github.com/jcdavis131/c899ef776dcb81e99319239efa0f92ba`; STEER links in
both console footers). Zero new secrets, zero tunnel, zero box exposure: writes
are GitHub-authenticated from the operator's phone; the box's loop polls every
~3 min via `scripts/steer_poll.py` and acts.

Protocol (stateless, auditable): owner comments not starting 🤖 = DIRECTIVES; the
box replies `🤖 ack <comment-id>: <status>` after acting — an existing ack marks
it done. Comments from any other account are NEVER acted on (untrusted input;
surfaced only). Verified round-trip: post → poll → act → ack → empty.

### Fleet control (operator: "tweak the compute fleet … behind a login … only I should have access")

- **The login IS GitHub.** Mutating actions ride the steer channel, so they are
  gated by the operator's GitHub session — enforced by GitHub, not by anything
  hand-rolled on a static site. Visitors get read-only surfaces plus a locked
  STEER gate; the box never holds new secrets and is never directly exposed.
- **Grammar:** `fleet: <verb> <container>` — verbs start/stop/restart only;
  targets must match the closed allowlist (dottie-factory-{collector,curator,
  janitor,server,trainer}-N or dottie-dottie-1; short names accepted).
  `steer_poll.parse_fleet` validates; anything outside the allowlist is refused in
  the ack, never guessed at (path traversal, foreign containers, and destructive
  verbs tested-refused).

## Build order

See `tasks/dottie_site_plan.md` (phased plan) and `tasks/todo.md` (the live
board). **First slice: the HUB Artifact Registry** — the substrate is ready (the
two dataset cards exist), it is fully additive, static, and Vercel-safe. Then the
Guide digest + agent tiles, then the Monitor runtrack readout, then the
engine-dependent (ReAct trace) and HF-push pieces.

## Explicitly OUT of autonomous scope

Auto-pushing generated code to public repos; any write-integration into the
external revenue-surface properties; buying domains / entering credentials (the
operator's own action). Deploying the console IS in scope (established); each
public deploy re-aliases www.bhenre.com and updates the alias-guard pin.
