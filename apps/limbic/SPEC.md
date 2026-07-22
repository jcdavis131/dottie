# LIMBIC — Dottie campus game (distilled spec)

Source: operator's design doc (Google Doc `1EpAenKrYUgCi1xwbnz7fpKumXR6Om_NabPgoaUhitFU`,
distilled 2026-07-21). This file is the in-repo spec of record; the doc is the narrative
history behind it.

## Concept

A cel-shaded 3D browser game set on the campus of **Limbic**, a fictional AI company staffed
by autonomous NPC instances. The player probes, audits, and stress-tests the organization.
Successful player workflows become training signal for Dottie — the game is a front-end for
RLHF data collection ("Trojan horse" framing in the source doc).

## World

- Silicon-Valley campus, Ghibli-ish cel shading (MeshToonMaterial approximation in the slice).
- **7 departments**, each a building + AI staff: Archive, Performance, Design, Hardware,
  Research, Safety, Operations.
- Terminals scattered through the world: persona hot-swap points.

## Playable personas (hot-swap at terminals only)

| persona | role | flavor |
|---|---|---|
| auditor | External Auditor — the primary lens | interviews NPCs, files findings |
| cipher | hacker — Archival Cipher pillar | decodes, exfiltrates, opens locked context |
| architect | Spatial Architect | re-plans space/compute for efficiency wins |

## Core mechanics

- **Bandwidth**: every action spends a per-run bandwidth budget; regen is slow; at 0 the
  run ends. Costs differ per persona (specialists do their specialty cheaper).
- **GTA-style reset loop**: session memory wipes at run end; only *validated* workflows are
  extracted as training data. Ephemeral play, persistent signal.
- **Memory architecture** (target): global memory-router + per-NPC vector stores. The slice
  ships an honest keyword-scoring router stub — no fabricated "vector DB".
- **NPC chat**: NPCs answer via the Dottie engine when one is reachable
  (`DOTTIE_CHAT_URL`); when not, the NPC says so in-world. **No fabricated replies, ever**
  — same provenance-honesty doctrine as the Dottie console webapp.

## Phases

1. **P1 — vertical slice (THIS scaffold)**: campus blockout, WASD player, 7 departments,
   wandering NPCs, terminals + persona hot-swap, bandwidth HUD, honest NPC chat proxy,
   pure-logic modules under bare-node contract tests.
2. P2 — closed-loop NPC ecosystem (schedules, inter-NPC traffic), per-NPC memory buckets
   behind the router, run-end extraction of workflow transcripts.
3. P3 — gameplay pillars as quest lines (Archival Cipher, Performance Division, Design
   Sabotage, Hardware Heist) + Limbic org identity (mission/vision/values surfaced in-world).
4. P4 — RLHF extraction pipeline: validated workflows → curriculum shards for the factory.

## Explicitly OUT of autonomous scope

The source doc's **gameplay→GitHub auto-PR pipeline** ("real code commits happen
automatically", dumbmodels.com integration) is outward-facing automation. It is NOT built
and must not be built autonomously — it needs the operator's own design + sign-off on any
system that pushes generated code anywhere public.
