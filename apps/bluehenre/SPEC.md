# BLUEHENRE — spec of record

**The story:** **bluehenre.com is a window into the org** that is building
**dumbmodels.com** — vector games (MTNN-based gaming/prediction platforms:
vector-hoops, -gridiron, -pitch, …) — and building **Dottie**, the agentic
assistant that helps the org hill-climb better models for each game, plus a
**Universal MTNN** that connects them all. The org runs autonomously on the
operator's machine; the game is the public window and steering wheel.

Source: operator's design doc (`1EpAenKrYUgCi1xwbnz7fpKumXR6Om_NabPgoaUhitFU`);
org name is **bluehenre** ("Limbic" was a discarded working title). This file
supersedes the doc.

## What the game IS — the Dottie digital twin

- **World:** a low-grade digital twin of Earth; the playable slice is the org's
  HQ in **Austin, TX**. More Earth nodes are future rungs.
- **NPCs ARE the docker fleet** (operator 2026-07-22): every running container
  (trainer, collectors, curators, server, janitor, research daemon) walks the
  campus near its department, wearing a live nameplate with docker's own
  cpu%/mem, streamed via `/api/fleet` (local: docker CLI, 10s cache; hosted:
  the published gist's `hub.fleet` snapshot). Activity drives the body — busy
  containers pace, idle ones stand; stopped containers leave the campus. The
  per-dept expert minifigs remain visible ONLY where no live node exists.
  Chat brains = local Dottie when reachable (`DOTTIE_CHAT_URL`); otherwise
  they say so in-world. No fabricated expertise, ever.
- **The Dottie terminal:** ONE special NPC on the plaza. Interacting opens a
  modal: the full dottie:app console (iframe) when the hub is reachable from
  the build, else an honest source-stamped chat over `/api/npc-chat`.
- **Twin telemetry:** the real training run (step, loss, eval ppl) renders on
  the plaza console via `/api/twin-status`, source-stamped `local` or honestly
  offline.
- **The :8000 hub lives in-world:**
  - Plaza console = the training dashboard: mode badge, run/phase bars, lm-loss
    sparkline, five flow-gate LEDs, shard funnel. 15s poll.
  - Dept-sited mini-boards = the rest of the hub: NETWORK//ARCH (labs),
    SKILLS//ECOSYSTEM (design), EVAL//REPORT (proving), RESEARCH//LOOP (hall).
  - Source priority (`server.mjs`): live `/pipeline/status` → exported
    `dottie_live_status.json` → raw artifacts, each freshness-capped. The
    hosted site reads the operator's published gist (`via:"gist-feed"`, hourly
    publisher, 75-min cap) — real numbers publicly, box unexposed.
- **The closed loop:** telemetry IN → players clear blockers/quests →
  validated workflows OUT as curriculum shards → operator feeds the factory →
  better Dottie → better NPC brains → better play. Hill-climb.

### Department → subsystem map (ids/colors/order contract-frozen)

| dept id | in-world | real subsystem | expert |
|---|---|---|---|
| labs | Foundation Training Lab | `apps/ava-factory` trainer | foundation LLM training |
| servers | Collector Farm | collector fleet (docker) | data collection |
| archives | Data Curation & Archives | curator + datagen | data curation |
| proving | Eval Harness Proving Grounds | `evals/run_harness` + open-harness | evals |
| design | Skills Ecosystem Studio | `packages/ava-skills` + scout plugins | skills ecosystem |
| gardens | Memory & Router Gardens | memory-mint / router | memory architecture |
| finance | Compute & Fleet Ops | GPU, fleet, budgets | infra & compute |
| hall | The Great Hall | org commons | — social hub |

### Hill-climb ladder

1. ✅ Twin telemetry v1 (step/loss/ppl on the board).
2. ✅ NPC expert prompts v1 (chat carries subsystem focus).
3. ✅ REAL-event blockers: `twin.parseLiveEvents` maps genuine problems
   (trainer stale/error, data starved, disk water-marks, red gates; benign
   full-runway pauses excluded) → `pipeline.raiseLiveBlocker` stalls the org
   with a `REAL:` blocker. One block per distinct event per session.
4. ✅ Dashboard-on-the-board + dept hub panels (all of :8000 in-world).
5. ✅ Shard feedback counter (banked half): the board's twin line shows the
   LOCAL bank's real count (`workflows.jsonl` lines; absent file = honest 0;
   hosted build claims nothing). The fed-to-factory half needs a factory-side
   source marker — future.
6. ✅ Earth-twin nodes (2026-07-22): the org's REAL deployed sites on the
   satellite board — dumbmodel.com hub, the four vector games, arcade,
   arxiviq, bhenre.com — publisher-probed (real http/latency), green/red
   nodes + legend. Visitable interiors: future.
7. Campus densification (operator 2026-07-22): keep the world tight, not
   sprawling — make the org campus itself hyper-detailed and life-like.
   Slice 1 ✅ (staff desk-routes, curbs/planters/conduit/doorways, tighter
   scatter); further slices open-ended.

## Core mechanic — The Project (`pipeline.mjs`)

The org ships **DUMBMODEL-1**: data → curate → train → eval → ship, each stage
owned by a department.

- **NPCs do the work.** A stage progresses only while its dept's NPC is at
  their post (ecosystem circuits: home → Great Hall → peer). No player input
  needed — observe mode (V) proves the org runs itself.
- **Blockers stall it** — seeded (deterministic per run seed) and REAL (rung 3).
  Each names the dept + consultant hat + action. Resolution pays a retainer
  (bandwidth refund).
- **Shipping = validated run** (counts as a completed quest line).
- Pure logic, seeded, bare-node contract-tested — like every module.

**Personas** (consultant hats; keys/abilities frozen): auditor = Discovery
Consultant (interview) · cipher = Systems Cipher (decode) · architect =
Delivery Architect (replan). Hot-swap on terminals only.

**Quest lines (optional briefs):** Archival Cipher (archives) · Performance
Division (finance) · Design Sabotage (design + hall) · Hardware Heist (servers).

**Bandwidth:** per-run action budget, slow regen, specialty at half cost, 0 =
run over → GTA-style reset (memory wipes; only validated workflows survive as
extracted signal).

## Presentation

- **Visual bar: CRISP-FIRST at golden hour** (operator 2026-07-22: "make
  everything much more crisp and clear — I cannot read much of it"). Full-
  resolution render, AA on, devicePixelRatio-aware; NO low-res upscale and NO
  vertex wobble (both made text illegible). Retro character lives in materials:
  flatShading facets, ordered dithering, indexed board palettes, fog, the
  dithered SNES sunset. Every board/sign canvas is 2x supersampled
  (`setTransform(2,0,0,2,…)` over the logical grid).
- **Boards are cyberpunk consoles** (32-color indexed palette, hard pixels,
  zero AA); the Earth board is a 90s weather-satellite map (natural palette,
  dithered oceans, comma clouds, HQ AUSTIN marker, 2Hz redraw).
- **Austin set dressing:** ring road, limestone plaza, Lady Bird Creek + bat
  bridge, live oaks, food trucks, Texas flag, ATX water tower, hazy skyline.
  Sims-style minifigs with plumbobs.
- **Render contract (frozen):** DEPARTMENTS order/ids; buildings r=40, NPC
  homes r=24, same angle formula; terminals [6,0] [-6,4] [0,-7]; `buildWorld`
  API (+ `animate(dt,t)`). `world.mjs` is render-only and deterministic
  (mulberry32).

## Input — mobile-first

Touch is the default (left-thumb joystick, right-thumb action buttons, persona
buttons appear on terminals; coarse-pointer gated); keyboard is the desktop
enhancement — both drive the same handlers. Joystick math is pure and
contract-tested (`touch.mjs`). Safe-area CSS, portrait-aware camera, shadow map
1024 on phones / 2048 desktop.

## Honesty doctrine (non-negotiable)

- NPC replies: `[dottie]` or `[offline]` — withheld beats fabricated.
- Twin numbers only from `source:"local"`; stale feeds are "history, not
  telemetry"; unreachable hub blocks render as offline lines.
- Router results stamped `keyword-stub` until a real vector store exists.
- Extraction refuses unvalidated runs loudly; discarded runs say why.

## Explicitly OUT of autonomous scope

Auto-pushing generated code to public repos, and any write-integration into
dumbmodels.com, are outward-facing automation: **not built** without the
operator's own design + sign-off. Shards never auto-ingest — the operator feeds
the factory explicitly. Deploying the game itself is in scope (established:
Vercel production, `vercel deploy --prod` from `apps/bluehenre`).
