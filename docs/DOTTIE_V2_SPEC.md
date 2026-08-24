# Dottie v2 — Spec (2026-08-23) — colibri / openworker / qm / anydoc distillation

> Solo personal project, no employer tie, public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip). Zero-deps true, honest 503 never fake, English/code only.

## Problem
Dottie v1 closes the loop (route→execute→record→mine→retrain→gate→serve) but is single-user, single-machine, scattered ingestion, no tiered inference, no approval for consequential actions, no multiplayer scopes. The 4 repos that went viral in July 2026 each solve one of those gaps with a clean primitive. v2 distills their principles (not copies their code) into Dottie.

## Module Touch Quiz
- Engine: Y — vector-hoops MTNN v9.2 20719×128-d canonical 18.8M vs 12966×64-d 5.1M fallback, TCA 7 heads 70% sparse L46-L48 + TAA k8 30% L51-L54 fusion 0.7/0.3, LCG triple[11205,19448,14209] same-link-same-stars
- Frontend: Y — paper #FAFAF8 / void #080A0F / 40px sticky z40 / map #0A0C10 / PWA v67 offline13k CORE20 / verifier≥8
- Factory: Y — ingest→clean→featurize→train→eval→bundle, Alienware GPU via ALIENWARE_HANDOFFS, anydoc upgrades ingest to unified Document IR + single GFM serializer
- Orchestrator: Y — 1 main +1 churn aligner c86e297d + N swarms never archive, timeline 7-field mandatory, qm adds scoped memory/files/keychain/crons/web apps per person/room + skill grants + admin tighten-only
- Creds: Y — dm_dev_* chmod600, openworker adds local secret store 0600 + per-launch sidecar token + X-OpenWorker-Token timingSafeEqual + inbox

## Distilled Principles

### 1. colibri — Tiny engine, immense model
- Treat VRAM/RAM/disk as one managed hierarchy, no SLA on speed, hard guarantee on semantics: never silently change precision/router
- One file per arch, same `coli chat/serve/web` front, experiments earn place via reproducible measurement
- Dottie: `scout infer` stdlib-only, TieredCache LRU 128 + pinned 512 + prefetch + mmap, placement probe /proc/meminfo + statvfs + nvidia-smi, fail-closed IO_MISSING

### 2. openworker — Local-first worker
- BYO model via aisuite (14 providers), curated verified tool-calling list, local secret store 0600, per-launch token sidecar-*.token + X-OpenWorker-Token, only small OAuth broker leaves machine
- Outcome-oriented: tell outcome, breaks into steps, checks before consequential (send message, calendar, run command), delivers finished deliverable, unattended parks in inbox
- Dottie: `scout secrets` 0600 vault + audit redaction, `scout models` curated list, `scout inbox` atomic 0600 park/list/approve/deny, approval gate CONSEQUENTIAL

### 3. qm — Multiplayer harness
- Personal and shared scopes: each person and room has scoped memory/files/keychain view/permissions/crons/web apps/durable sandbox
- Same identity across Slack/web, admin control org-level config + security posture + which harnesses/models available tighten-only
- Web apps spin up custom internal apps publish to right people, shared skills scope-owned shareable by grant + admin-gated promotion + packs imported from git, background crons/watches/webhooks, model-agnostic Pi/OpenCode/Codex/Claude
- Dottie: scopes/person/<handle>/ and scopes/room/<slug>/ contract, keychain views, permissions graph, skill grants registry.json + grants/<skill>.json + packs/ git import, admin org/config.json, drivers/wiring.py run(scope,goal,tools), channels/slack.json + identity.json, web apps manifest

### 4. anydoc — One output for every format
- Shared document model + single Markdown serializer so escaping/tables/heading anchors/footnotes behave identically whether .doc 2003 or .pptx yesterday
- Full structure: headings with anchors, bold/italic/strike, inline code/blocks, links/cross-refs, lists with source numbering, tables merged cells header rows, block quotes, footnotes/endnotes, speaker notes, equations as LaTeX $...$ / $$ $$, embedded assets as alt text raw bytes tagged media type
- Content-based detection from bytes (PDF header, RTF open group, OLE stream names, ZIP mimetype), fast pure Rust median <5ms, bindings stay out of event loop (libuv/GIL release), PDF built-in via pdf-inspector no OCR
- Dottie: unified Document {meta,blocks,assets} IR, single GFM serializer, content-based detection, Python stdlib impl median <50ms target, non-blocking ThreadPoolExecutor, honest 503 for scanned/encrypted/OLE, ships as `scout extract` + ava-skill `anydoc`

## Architecture
User goal → Route (MoMA-lite heuristic + learned MLP advisory, 5 tiers) → Scope resolve (person/room/org) → Plan DAG → Execute (deterministic stdlib, inference tier colibri, ingest tier anydoc, secrets tier openworker, consequential check inbox) → Record (timeline triple-write 7-field + checkpoint_manager pause/resume) → Mine (measured-behavior/outcome/operator-corrected) → Retrain (nightly) → Gate (freq prior + heuristic) → Serve (numpy-only /api/route parity ≤1e-4) → Tandem (local Docker 127.0.0.1:8787 + cloud arxiviq.com/conductor?tandem=1 queue, Bearer dm_dev_* timingSafeEqual + 90s HMAC ephemeral 256 LRU)

## User Stories
1. As a player, I want same-link-same-stars `?daily=20260813&n=1/3/5` LCG 20260813→189831298 triple[11205,19448,14209]
2. As a lab explorer, I want embedding map 72vh sticky 58/42 single-select clears prev inertial LOD4000/8000 DPR1 fusion 0.60*tca+0.25*taa+0.15*news
3. As Scout Prime, I want timeline triple-write even no-change 7-field
4. As org admin, I want scopes/org/config.json tighten-only + drivers/wiring.py to swap Pi/OpenCode/Codex/Claude
5. As developer, I want scout infer run --model glm52 --prompt "hi" to stream from disk on 16GB RAM with honest semantics guard
6. As writer, I want any Word/PPT/Excel/PDF dropped into scout extract read to give same clean GFM
7. As user away, I want consequential actions parked in scout inbox not executed

## Seams
- apps/scout-cli/bigbang/plugins/ — highest, existing forge pattern, stdlib-only, manifest.yaml, make_plugin_app + ok + emit + enforce_or_raise
- packages/ava-skills/skills/ — skillbook 13 agents/11 packs/6 ultra modules
- apps/arxiviq/app/dottie/ — frontend conductor + tandem bridge, #080A0F CORE20 PWA

## Acceptance
- scout infer hello → ok true, list → 6 families, status → vram null honest, run missing → IO_MISSING fail-closed
- scout inbox list → pending/approved/denied/expired correct, park→approve→clear lifecycle, 0600 perms
- scout secrets list → redacted human, full JSON for agents, 0600 vault
- scout extract detect → tier stdlib anydoc-py v1.0.0 scope unified ingestion 12 formats + ole + html, read docx → # Hello preserved, batch order preserved diffable
- scopes/person/<handle>/ + scopes/room/<slug>/ each with memory/files/keychain.json/permissions.json/crons/web_apps/sandbox/, skill grants registry.json + grants/, admin tighten-only, Slack+web same identity
- PWA v67 headers immutable 31536000 verifier≥8 offline-ready 40px sticky nav mono/sans only
- Timeline triple-write 7-field mandatory even no-change
- Live surface arxiviq.com/dottie + arxiviq.com/conductor?tandem=1 triple green Local/Cloud/Paired + queue

## Wayfinder
Destination: Dottie v2 live — all 4 distillations shipped, PWA v67, daily boards LCG 20260813 chain, Launched 99.9→100% free PWA offline13k, 3 real daily users

Out of scope: finance/payments PARKED 100/100 local-first gate until YES, analytics Phase0 stub store.jsonl only, auth Phase0 stub 3-user cached only
