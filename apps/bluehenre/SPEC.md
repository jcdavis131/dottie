# BLUEHENRE — synthetic AI-org campus game (distilled spec)

Source: operator's design doc (Google Doc `1EpAenKrYUgCi1xwbnz7fpKumXR6Om_NabPgoaUhitFU`,
re-distilled 2026-07-21 after the operator's correction: **the org is "bluehenre" — "Limbic"
was a discarded working name**). This file is the in-repo spec of record; the doc is the
narrative history behind it.

## Concept

A cel-shaded 3D browser game set on the campus of **bluehenre**, a fictional tech company
staffed by autonomous NPC instances (bluehenre also operates the public platform
dumbmodels.com in the fiction). The player probes, audits, and stress-tests the org.
Successful player workflows become training signal for Dottie — ephemeral play, persistent
signal ("Trojan horse" framing in the source doc).

## World — campus locations (from the doc)

Developer Labs · Design Studio & Marketing Plazas · Finance Towers · Legal Archives ·
Subterranean Server Farms · The Great Hall & Cafeteria · Botanical Gardens · Proving Grounds.
Ghibli-ish cel shading (MeshToonMaterial approximation). Terminals scattered through the
world: persona hot-swap points.

## Playable personas (hot-swap at terminals only)

| persona | role | flavor |
|---|---|---|
| auditor | The External Auditor — the primary lens | interviews NPCs, files findings |
| cipher | The Cipher (hacker) | decodes, exfiltrates, opens locked context |
| architect | The Spatial Architect (optimizer) | re-plans space/compute for efficiency wins |

## Gameplay pillars (quest lines)

1. **The Archival Cipher** — deep puzzle-solving / cryptography hunts (Legal Archives)
2. **The Performance Division** — workflow optimization + resource allocation (Finance Towers)
3. **The Design Sabotage** — social deduction + NPC persuasion (Design Studio)
4. **The Hardware Heist** — logic-based security bypass / adversarial testing (Server Farms)

## Core mechanics

- **Bandwidth**: per-run action budget; slow regen; 0 ends the run. Personas do their
  specialty at half cost.
- **GTA-style reset loop**: session memory wipes at run end; only *validated* workflows are
  extracted as training data.
- **Memory architecture** (target): global memory-router + per-NPC stores. The code ships an
  honest keyword-scoring router stub — no fabricated "vector DB".
- **NPC chat**: NPCs answer via the Dottie engine when reachable (`DOTTIE_CHAT_URL`);
  otherwise the NPC says so in-world. **No fabricated replies, ever.**

## Phases (doc phases, honestly scoped)

1. **P1 — engine + campus** (done): three.js blockout, WASD player, terminals + persona
   hot-swap, bandwidth HUD, honest NPC chat proxy, pure-logic modules under bare-node tests.
2. **P2 — closed-loop NPC ecosystem + persistence** (this build): NPC schedules and
   inter-NPC memo traffic feeding per-NPC memory buckets; run-end workflow extraction.
   (The doc's WebSocket multiplayer is future work — single-player persistence first.)
3. **P3 — gameplay pillars as quest lines** (this build): the 4 pillars above as ordered
   quest steps gated by persona + location; org identity surfaced in-world.
4. **P4 — training-signal extraction** (this build): validated run workflows → curriculum-
   shard JSONL (`{text, task_type, concept, phase, source:"bluehenre/workflow"}`) written
   LOCALLY for the operator to feed the factory. Nothing auto-ingests.

## Explicitly OUT of autonomous scope

The doc's **"Live Deployment: real GitHub integration pushing validated code to a public
bluehenre repository"** and any dumbmodels.com integration are outward-facing automation.
NOT built; needs the operator's own design + sign-off. Deploying the *game itself* to a
host is fine; a pipeline that pushes generated code anywhere public is not.
