# BLUEHENRE — spec of record

**The org's primary goal & motivation (operator, 2026-07-22):** build SOTA
models FASTER by researching every piece of the stack — data, curriculum,
architecture, training, evals, harness, skills, memory — then **generate
insights** leveraging those models, and **turn the insights into revenue**.

**The story:** **bluehenre is the org's command console** — the window into
(and steering wheel for) the org executing that goal: **dumbmodel.com**
vector games and prediction platforms (hoops, gridiron, pitch, equities —
the insight/revenue surfaces), **Dottie** the agentic assistant that
hill-climbs better models for each, and a **Universal MTNN** connecting them
all. The org runs autonomously on the operator's machine; the console runs
the org end to end.

**Core focus: the hill-climb and the data flywheel** — the mechanism behind
"faster". Train → eval → publish telemetry → operator sees truth fast
(anywhere) → blockers cleared quickly → curriculum and research promotions
feed back → better model → better Dottie → better games/predictions → more
insight → revenue that funds the next climb. Everything in this app serves
that loop.

Simplification 2026-07-22 (operator): the 3D world is REMOVED. The console is
the product. Org name is **bluehenre** ("Limbic" was a discarded working
title); design doc `1EpAenKrYUgCi1xwbnz7fpKumXR6Om_NabPgoaUhitFU` is history,
this file supersedes it.

## The console (`/` — mobile-first, cozy amber-phosphor retro terminal)

Crisp full-resolution text; warm browns/cream/gold; faint CRT scanlines.
Cards, in order:

- **RUN//AVA-MINI** — the training run: mode badge, step · loss, held-out ppl,
  throughput + ETA, checkpoint age, RUN and PHASE progress bars, flow-gate
  LEDs (D1–D5), shard funnel, lm-loss sparkline. 15s poll.
- **ALERTS//UNBLOCK** — REAL factory events (trainer stale/error, data
  starved, disk water-marks, red gates; benign full-runway pauses excluded),
  each naming the owning team + the feed's own words. Empty = "org unblocked".
- **DOTTIE//ASSISTANT** — chat with the org's assistant. Source-stamped
  `[dottie]` / `[offline]`; withheld beats fabricated.
- **FLEET//DOCKER** — every running container (docker's own cpu%/mem), sorted
  by activity, 10s poll locally.
- **HUB//SUBSYSTEMS** — model card (params/layers/split), skills ecosystem,
  eval verdicts, research baseline ±SEM + queue counts.
- **SITES//GLOBAL** — the org's deployed sites (dumbmodel.com hub, the four
  vector games, arcade, arxiviq, bhenre.com) probed for liveness + latency.

## Data spine (shared, provenance-honest)

- Local server (`node server.mjs`, zero-dep): `/api/twin-status` (live
  `:8000/pipeline/status` → exported `dottie_live_status.json` → raw
  artifacts, freshness-capped), `/api/fleet` (docker CLI, 10s cache),
  `/api/npc-chat` (Dottie engine via `DOTTIE_CHAT_URL` or honest offline).
- Hosted (Vercel prod, `vercel deploy --prod`): the same endpoints read the
  box's OWN published gist (publisher task runs every 10 min; 30-min
  freshness cap; `via:"gist-feed"`, ageS included). Real numbers publicly,
  box unexposed.
- Publisher (`apps/ava-factory/scripts/publish_live_status.py`, scheduled):
  pipeline + research + the full :8000 hub (network/ecosystem/agent-eval/
  eval report+catalog) + docker fleet snapshot + site probes.
- Pure parsers + contract tests live in `public/js/twin.mjs` (bare-node
  `twin.contract.test.mjs`) — the only test suite now.

## Honesty doctrine (non-negotiable)

- Numbers render ONLY from `source:"local"` telemetry; stale feeds are
  "history, not telemetry"; unreachable blocks render as offline lines.
- Chat replies are `[dottie]` or `[offline]` — never fabricated.
- Nothing auto-ingests into training; the operator feeds the factory
  explicitly.

## Next core item — the write path

Unblock/steer from the phone needs a channel back to the box: an operator-run
tunnel (+ `DOTTIE_CHAT_URL`/`TWIN_STATUS_URL` on Vercel) or a directive-queue
the box polls. Operator decision pending; the hosted console is truthfully
read-only until then and says so.

## Explicitly OUT of autonomous scope

Auto-pushing generated code to public repos and any write-integration into
dumbmodel.com properties. Buying domains / entering credentials is the
operator's own action. Deploying the console is in scope (established).
