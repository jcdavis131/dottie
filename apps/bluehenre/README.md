# The Dottie Site

**One product, three faces** — the operator's window into and steering wheel for
the Agentic Org:

1. **GUIDE** — a Manus / OpenClaw / Hermes-style agentic personal assistant that
   helps the operator guide the org: converses grounded in live telemetry,
   renders the real Dottie engine's ReAct trace, gives a ranked "what to do next"
   digest, and shows the three autonomous agents (research loop, docker fleet,
   workflows) working.
2. **HUB** — a HuggingFace-style registry of the org's OWN datasets, models, and
   research reports, each stamped with its provenance classification
   (REAL / HONEST-SYNTHETIC / PLACEHOLDER) and an honest eval.
3. **MONITOR** — a Weights&Biases-style real-time monitor of the local
   development the org runs: training curves, research experiments/promotions,
   fleet stats, run comparison — all real-measured.

**The differentiator — provenance-honesty by construction.** Every number renders
only from a real source; every dataset/model carries its classification; the
assistant is `[dottie]`/`[offline]` and never fabricates; nothing auto-ingests
into training. This is the anti-fabrication HF+W&B+Manus for an autonomous org.

**Why it matters:** the org works autonomously on the operator's box (RTX 4080,
Windows + WSL2 Docker). The site is how the operator runs it end to end from
anywhere — the training run, the docker fleet, real alerts, the Dottie assistant,
the artifact registry, the global sites — all real telemetry, provenance-stamped.
Built **additively on the existing amber retro-terminal console** (crisp text,
warm browns/cream/gold, faint CRT scanlines); static-first so local == Vercel.

## Cards today (the substrate the three faces grow from)

RUN (mode, step/loss, run + phase bars, loss sparkline, flow gates, funnel, ETA)
· ALERTS//UNBLOCK (real factory events by owning team) · DOTTIE//ASSISTANT
(source-stamped chat → **Guide**) · FLEET//DOCKER (containers, live cpu/mem) ·
HUB//SUBSYSTEMS (model, skills, evals, research queue → **Hub + Monitor**) ·
SITES//GLOBAL (deployed fleet with latency).

## Run

```bash
node server.mjs                        # http://localhost:8321 — live docker + hub feeds
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # assistant answers via Dottie
```

Hosted (Vercel) reads the box's own published gist (10-min publisher, 30-min
freshness cap) — real numbers publicly, box unexposed.

## Honesty doctrine

- Numbers render **only** from `source:"local"` telemetry; stale feeds say
  "history, not telemetry"; unreachable blocks render as offline lines.
- Every dataset/model card carries REAL / HONEST-SYNTHETIC / PLACEHOLDER; a card
  with no traceable provenance does not render.
- Every assistant line is `[dottie]` or `[offline]` — withheld beats fabricated.
- Nothing auto-ingests: the operator feeds the factory explicitly.

## Tests

```bash
node public/js/twin.contract.test.mjs   # pure parsers, bare node (76 checks)
```

Spec of record: [SPEC.md](./SPEC.md). Phased build plan:
[../../tasks/dottie_site_plan.md](../../tasks/dottie_site_plan.md). Live board:
[../../tasks/todo.md](../../tasks/todo.md).
