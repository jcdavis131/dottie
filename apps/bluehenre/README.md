# BLUEHENRE — the org's command console

**The mission:** build SOTA models faster by researching every piece of the
stack → generate insights with those models → turn insights into revenue.

**One line:** bluehenre is the mobile command console for the org executing
that mission — **dumbmodel.com** vector games and prediction platforms (the
insight/revenue surfaces), **Dottie** the agentic assistant that hill-climbs
better models for each, and a **Universal MTNN** to connect them all.

**Why it matters:** the org works autonomously on the operator's machine. The
console is how you run it end to end from anywhere — the training run, the
docker fleet, real alerts, Dottie chat, the global sites — all real telemetry,
provenance-stamped. **Core focus: keep the hill-climb and data flywheel
spinning.** (The former 3D world was removed 2026-07-22 — the console is the
product.)

## Cards

RUN (mode, step/loss, run + phase bars, loss sparkline, flow gates, funnel,
ETA) · ALERTS//UNBLOCK (real factory events by owning team) · DOTTIE
(source-stamped chat) · FLEET (containers, live cpu/mem) · HUB (model, skills,
evals, research queue) · SITES (deployed fleet with latency). Cozy amber
retro-terminal look; crisp text.

## Run

```bash
node server.mjs                        # http://localhost:8321 — live docker + hub feeds
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # chat answers via Dottie
```

Hosted (Vercel) reads the box's own published gist (10-min publisher, 30-min
freshness cap) — real numbers publicly, box unexposed.

## Honesty doctrine

- Numbers render **only** from `source:"local"` telemetry; stale feeds say
  "history, not telemetry"; unreachable blocks render as offline lines.
- Every chat line is `[dottie]` or `[offline]` — withheld beats fabricated.
- Nothing auto-ingests: the operator feeds the factory explicitly.

## Tests

```bash
node public/js/twin.contract.test.mjs   # pure parsers, bare node
```

Spec of record: [SPEC.md](./SPEC.md).
