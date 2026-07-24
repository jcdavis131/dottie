# Dottie Site — phased build plan (2026-07-24)

Spec: `apps/bluehenre/SPEC.md`. Everything ADDITIVE to the existing
bluehenre console, static-first (local == Vercel), zero frozen-path edits, every
surface provenance-honest. Each phase ships a verifiable slice; I stay in the
loop between phases (operator reviews, points at the next).

## Phase 1 — HUB Artifact Registry  ← FIRST SLICE (recommended)
Why first: the substrate is already built (the two HF-standard dataset cards
committed 2026-07-24), it's the most self-contained, fully static (Vercel-safe,
no server change), and it's where the provenance work becomes *visible*.
1. `apps/bluehenre/scripts/build_hub_registry.mjs` — read-only exporter: reads
   `tasks/artifacts/corpus_proposals/*/README.md` YAML frontmatter + the
   audit-sidecar summary/sha lines, emits `apps/bluehenre/public/hub_registry.json`
   `[{name, type, classification, counts, tags, cardPath, integrity, built_at,
   source_sha}]`. Deterministic, no network.
2. `parseHubRegistry(json)` pure fn in `public/js/twin.mjs` + a contract-test row
   in `twin.contract.test.mjs` (badge-from-frontmatter, unclassified fallback,
   link guard).
3. `renderHubRegistry()` card in `org.html`/`org.mjs` — one badge() helper
   (REAL green / HONEST-SYNTHETIC amber / PLACEHOLDER red), reusing existing
   line/table/chip/led/offline. Client fetches the static `/hub_registry.json`.
Gate: `node public/js/twin.contract.test.mjs` green (+ the new rows); the card
renders both real cards with correct badges local + on deploy. Then deploy +
re-alias per the runbook.

## Phase 2 — GUIDE digest + agent tiles
Additive to the DOTTIE//ASSISTANT card. Ships the parts that DON'T depend on the
engine exposing ReAct steps:
1. `nextActions(status)` in `twin.mjs` — rank `parseLiveEvents` alerts + research
   counts + fleet health into `[{label, team, steerCmd?}]`; contract-tested.
2. `renderGuide()` in `console.mjs` — the ranked next-action list (each row
   reusing the copy+open-gist steer bar) + three "autonomous agent" activity
   tiles (research loop / fleet / workflows) from live telemetry.
Gate: contract tests green; tiles render from real feed. The full ReAct chat
trace is Phase 4 (engine-dependent).

## Phase 3 — MONITOR runtrack readout
1. Wire the `runtrack` sqlite tracker (scout-cli openswap) to ingest the live
   trainer/research metrics (a small read-only bridge; runtrack is pure-sqlite).
2. A Monitor card: live training curve(s), research experiments/promotions from
   the ledger, fleet stats, run comparison. All real-measured; stale/offline
   honest.
Gate: contract tests + the card renders real runs.

## Phase 4 — gated / dependency-blocked pieces
- **HF publish** (Hub bidirectional mirror) — BLOCKED on the `HF_TOKEN`
  rotation (MASTER audit #6). Until rotated, the Hub shows an honest "mirror:
  awaiting token rotation". After: an `hf_uploader` push path (operator runs the
  authed step; I can't handle the token).
- **Engine ReAct trace** (Guide chat) — needs the factory hub `/assistant` to
  expose a stable `steps[]` (thought/action/observation/trust-gate). Verify the
  engine field first; pass it through `server.mjs` `/api/npc-chat` verbatim.
- **Model cards** — checkpoints (honest 2,268 eval) + vector MTNNs as Hub model
  cards (extends Phase 1's registry to models).

## Dependencies / operator calls
- `HF_TOKEN` rotation gates the Hub's HF-publish path (and is a live security
  item regardless).
- Each public deploy: `vercel deploy --prod --yes` then re-alias www.bhenre.com;
  update `apps/bluehenre/data/last_good_deployment.txt` (the alias-guard pin).
- Propose-first for anything touching the revenue-adjacent apex; the console
  deploys are the operator's already-blessed surface.

## Recommendation
Build **Phase 1 (Hub Artifact Registry)** first — additive, static, substrate
ready, and it makes the provenance work visible. On the operator's go, it's a
~single-slice build + contract test + deploy.
