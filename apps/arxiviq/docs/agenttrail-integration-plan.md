# Agenttrail → Dottie site integration plan

Reverse-engineered from https://github.com/sodiumsun/agenttrail (MIT — see attribution note at the end).
Research only; no code written. Dottie site = Next.js app at `apps/arxiviq` in `jcdavis131/dottie`.

## What agenttrail actually is

Local observability for AI coding agents. Two independent views:

- **Map** (`npx agenttrail`, port 5330): one Node daemon file plus one HTML page (SVG + D3, no WebGL — lightweight). Reads a `PLAN.md` written in a strict convention: components as `## Plain name {#id}`, tasks as `- [ ] outcome {#id}` with `[~]` in-progress / `[x]` done / `[!]` blocked, plus `by:`, `tech:`, `needs:`, `links:`, and `files:` globs per component. Watches the repo filesystem and attributes every file write to a component via the `files:` globs — so "revising finished work" stays visible even when the checkbox says done. Optional Claude Code hooks stream live runs (session id, current tool, todo list, which component it's in). Serves JSON (`/model`, `/summary`, `/board-lite`) and pushes live updates over Server-Sent Events. Multi-repo aware (ports 5330+ discover each other). Detects plan staleness (code moving while PLAN.md sits untouched) and nudges the agent.
- **Kitchen** (`npx agenttrail-kitchen .`, port 4780): a 3D WebGL kitchen scene. Chefs = project responsibilities (not processes); tickets/dishes = the agent's native todo list; cooking = observed work; the delivery conveyor = completed todos. Three in-memory stores: sessions (lifecycle states like working/reading/writing/permission/error), orders (native todos become tickets with status history and contributors), and plates (artifact handoffs). The plate/receipt model is the sharpest idea: a handoff is only recorded when an integration *explicitly emits* produced/offered/received/failed events with artifact + revision + handoff ids — it is never inferred from two agents touching the same file. Roles attach to sessions by explicit binding first, then inference (task-title match, component context, file globs, tool category), always labeled explicit vs inferred. Allowlisted metadata only — no prompts, reasoning, or code bodies reach the browser. Evidence taxonomy throughout: reported / observed / inferred / unknown. Never fabricates progress.

## What Dottie already has

- Deployed Next.js site (Vercel, `dottie-os-console`). Pages: home, `/dottie` (jarvisd pairing), `/hive` (concept page), `/conductor` (sessions, todos, notes), `/mlops` (static program page).
- Live agent data flows through `/api/conductor/snapshot`, an authenticated proxy to the local `jarvisd` daemon: todos (id, timestamp, agent, mission, text, priority, status open/in_progress/completed), a shared scratchpad, feedback, guardrails. Requires a paired session; honest 503 when jarvisd is unreachable.
- The hive floor (`registry.json`, `board.md`, `tasks.json`, `log.jsonl`) is a design exposition on the hive page, not a live data directory in this repo.
- House philosophy matches agenttrail's: honest 503 over fake success, "not measured" states, no fabricated data.

## Feature mapping: take / skip / defer

**Take for the Dottie site:**
1. **Agent-activity trail timeline** — the core "trail" feature. Chronological feed of what agents did: todo status transitions, scratchpad notes, feedback. 2D, honest, live-updating.
2. **Task tickets view** — conductor todos grouped by agent/mission with open → in-progress → completed flow. Agenttrail's "orders/tables" without the kitchen metaphor.
3. **Receipt entries for handoffs** — Dottie's world already has *explicit* handoffs (subagent results delivered into context, forge job results). Show them as produced/received receipts instead of implying collaboration from timing.
4. **Evidence labels** — adopt reported / observed / inferred / unknown as a visible design principle; the site already does "not measured," this gives it a vocabulary.
5. **Component map (later)** — an SVG Map-style view of the dottie-os program itself (the 7-stage MLOps loop, or dottie-os components) with per-component activity. The Map frontend is plain SVG/D3 — portable.

**Skip or defer:**
- The full WebGL 3D kitchen — heavy, and the kitchen metaphor doesn't fit Cameron's aesthetic or the site's 2D design. Propose the 2D trail as the permanent view; 3D only as a possible later phase if he asks.
- Local filesystem watching and Codex/Claude log adapters — they need a daemon on the machine; Vercel can't do this. Needs a local companion (see bridge options).
- Multi-repo fleet view, plan-staleness nudges, autostart — local-ops features, not site features.
- PLAN.md convention tooling — Dottie's plans live in goals/briefs, not PLAN.md; don't force the convention.

## The architecture gap (important)

Agenttrail assumes a daemon on 127.0.0.1 with filesystem access. The Dottie site is a deployed Next.js app. Three ways to bridge it:

- **A. jarvisd proxy (works today).** Phase 1 feeds the trail from the existing `/api/conductor/snapshot` — todos, scratchpad, feedback. Authenticated, paired-session only, no new infrastructure. Limited to what jarvisd reports.
- **B. Sidecar-generated snapshots.** A script on Cameron's machine periodically writes trail JSON (from hive-style logs or the sidecar feed) that the site reads at build time or serves as a static JSON. Works unpaired, less live, new moving part.
- **C. Local companion daemon.** An agenttrail-style local service the site polls — richest (fs watching, hook events) but a whole new service to install and maintain.

Recommendation: Phase 1 uses A; Phase 2 adds B for history depth. C only if he wants live fs-level trails later.

## Phased scope

**Phase 1 — Trail page (smallest shippable, needs his nod).**
A new `/trail` route (or a section in `/conductor` — see open question 1): a chronological, auto-refreshing activity timeline from the conductor snapshot — todo transitions, scratchpad notes, feedback — grouped by agent/mission with status pills, plus a tickets board (open / in-progress / completed). 2D, SSE-style live refresh modeled on agenttrail's `/events` pattern, honest empty states. No new backend.

**Phase 2 — Map + receipts.**
An SVG component map of the dottie-os program with activity heat per component (Map-style, no WebGL), and explicit produced/received receipt entries for subagent and forge handoffs.

**Later (only on his word).**
3D kitchen-style scene; local companion daemon for filesystem-level watching; multi-session live-runs view.

## Open questions for Cameron

1. Where should the trail live — a new `/trail` route, or folded into the existing `/conductor` page?
2. Phase 1 data: jarvisd snapshot only (live, needs pairing), or also a sidecar-generated static snapshot so the trail shows something when unpaired? Both, with honest labels, is the recommendation.
3. Is the 3D kitchen visualization ever wanted, or is 2D the permanent aesthetic?

## MIT attribution

Agenttrail is MIT-licensed (sodiumsun). If we port any of its code (PLAN.md parser, SSE broadcast pattern, store shapes), we keep its copyright + license text in the repo (e.g. `apps/arxiviq/docs/attribution.md`) and credit it in the UI where the feature appears.
