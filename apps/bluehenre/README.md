# BLUEHENRE — the org, playable

**One line:** bluehenre.com is a window into the org building
**dumbmodels.com** — MTNN-based vector games (gaming/prediction platforms) —
and **Dottie**, the assistant that helps it hill-climb better models for each
game and a **Universal MTNN** to connect them all.

**Why it matters:** the org works autonomously on this machine. The game is how
you watch it — and help it. Real training telemetry renders in-world; validated
play becomes real curriculum shards.

**The form:** a zero-dependency 3D browser game (three.js via import map, bare-
node server) set on the org's Austin, TX campus. You are the hired consultant.

## Run

```bash
node server.mjs                        # http://localhost:8321, NPCs offline-honest
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # NPCs answer via Dottie
```

- **Controls:** WASD move · Shift sprint (spends bandwidth) · E ability at the
  nearest NPC (advances quests, clears blockers) · Q memory router · V observe
  mode (aerial orbit — the org runs itself) · 1/2/3 hot-swap persona on a
  terminal · R reset after run-over. Phones get a touch joystick + buttons.

## The loop

- The org builds **DUMBMODEL-1** on its own: data → curate → train → eval → ship.
- **Real factory events** (trainer stale, data starved, red gates) stall it with
  `REAL:`-stamped blockers; seeded fictional blockers fill the gaps.
- You clear blockers as the right persona at the right department. Bandwidth 0
  ends the run: memory **actually wipes**, the transcript is extracted —
  **validated** (quest line done, majority of actions ok) or **discarded with
  the reason**.
- Validated workflows land in `data/workflows.jsonl` (factory doc shape,
  `source:"bluehenre/workflow"`). **The operator feeds them to the factory
  explicitly — nothing auto-ingests.**

## Honesty doctrine

- Every NPC line is tagged `[dottie]` (real engine) or `[offline]` (withheld,
  says so). No fabricated replies, ever.
- Twin boards render numbers **only** from `source:"local"` telemetry; stale
  feeds say "history, not telemetry". The hosted build reads the operator's own
  published gist — provenance intact, box unexposed.
- The router stamps `keyword-stub` on every result. Extraction refuses
  unvalidated runs loudly.

## Tests

```bash
for f in public/js/*.contract.test.mjs; do node "$f"; done   # 10 suites, bare node
```

Spec of record: [SPEC.md](./SPEC.md).
