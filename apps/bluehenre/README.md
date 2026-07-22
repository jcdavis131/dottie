# BLUEHENRE — the org's command console

**One line:** bluehenre is the mobile command console for the org building
**dumbmodel.com** vector games (MTNN gaming/prediction platforms), **Dottie**
the agentic assistant that hill-climbs better models for each game, and a
**Universal MTNN** to connect them all.

**Why it matters:** the org works autonomously on the operator's machine. The
console is how you watch it and steer it from anywhere — the run, the docker
fleet, real alerts, Dottie chat — all real telemetry, provenance-stamped.
**Core focus: keep the hill-climb and data flywheel spinning.**

## Surfaces

- **`/` — the console (primary, mobile-first):** RUN (mode, step/loss, run +
  phase bars, loss sparkline, flow gates, shard funnel) · ALERTS//UNBLOCK
  (real factory events) · DOTTIE (source-stamped chat) · FLEET (containers,
  live cpu/mem) · HUB (subsystems) · SITES (the deployed global fleet).
  Retro-console look; crisp full-resolution text.
- **`/world.html` — the 3D campus (secondary):** the same data as a walkable
  Austin, TX digital twin. Fleet containers are the NPCs; validated play
  extracts curriculum shards (`data/workflows.jsonl`, operator-fed only).

## Run

```bash
node server.mjs                        # http://localhost:8321 — live docker + hub feeds
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # chat answers via Dottie
```

Hosted (Vercel) reads the box's own published gist — real numbers publicly,
box unexposed, freshness-capped.

## Honesty doctrine

- Numbers render **only** from `source:"local"` telemetry; stale feeds say
  "history, not telemetry"; unreachable blocks render as offline lines.
- Every chat line is `[dottie]` or `[offline]` — withheld beats fabricated.
- Nothing auto-ingests: the operator feeds shards to the factory explicitly.

## Tests

```bash
for f in public/js/*.contract.test.mjs; do node "$f"; done   # 10 suites, bare node
```

Spec of record: [SPEC.md](./SPEC.md).
