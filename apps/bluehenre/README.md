# BLUEHENRE — synthetic AI-org campus game

Cel-shaded 3D browser game on the campus of **bluehenre**, a fictional tech company staffed
by NPC AIs (see [SPEC.md](./SPEC.md) — the in-repo spec distilled from the operator's design
doc; the org was renamed from the working title "Limbic"). Zero npm dependencies: three.js
loads via import map at runtime, the server is bare node.

Phases P1–P4 are built: campus + personas + bandwidth (P1), closed-loop NPC ecosystem with
memo traffic into per-NPC memory buckets (P2), the four doc pillars as quest lines +
org identity (P3), and validated-run → curriculum-shard extraction (P4).

## Run

```bash
node server.mjs                        # http://localhost:8321, NPCs offline-honest
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # NPCs answer via Dottie
```

Controls: **WASD** move · **Shift** sprint (spends bandwidth) · **E** persona ability at the
nearest NPC (advances quests) · **Q** query the memory router · **V** observe mode — a
RollerCoaster-Tycoon-style aerial orbit where you just watch the org at work ·
**1/2/3** hot-swap persona *on a terminal pad* · **R** reset after run-over.

## The loop

Complete quest steps as the right persona in the right location. When bandwidth hits 0 the
run ends: the session memory **actually wipes**, and the run transcript is extracted —
**validated** (a quest line completed, majority of actions succeeded) or **discarded with
the reason**. Validated workflows become curriculum shards appended to
`data/workflows.jsonl` (factory doc shape, `source:"bluehenre/workflow"`). **The operator
feeds those to the factory explicitly — nothing auto-ingests** (SPEC "OUT of autonomous
scope", same boundary as the doc's GitHub auto-PR pipeline, which is not built).

## Honesty doctrine

Same as the Dottie console webapp: every NPC line is tagged `[dottie]` (real engine reply)
or `[offline]` (no engine — the reply is withheld and says so). The memory router stamps
`keyword-stub` on every result — it never claims to be a vector store. Extraction refuses
unvalidated runs loudly. The hosted (Vercel) build says plainly that it cannot reach a
Dottie engine and cannot bank shards.

## Tests (bare node, like the webapp — 61 checks)

```bash
for f in public/js/*.contract.test.mjs; do node "$f"; done
```
