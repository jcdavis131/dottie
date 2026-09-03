# Jarvis Harness Plan — from 27 repos to one hosted pair programmer

**Status:** Proposed 2026-09-03 · **Companion docs:** `ECOSYSTEM.md` (the map),
`PLATFORM_IMPROVEMENT_PLAN.md` (the research-loop plan this one sits beside),
`DOTTIE_V2_SPEC.md` (the colibri/openworker/qm/anydoc distillation)
**Evidence base:** a read of all 27 repositories in the `jcdavis131` account on
2026-09-03 (local clones at their default branches), GitHub Actions history for
`dottie`, open pull requests, and a local reproduction of the CI failures at
`dottie` HEAD `c7d1f54`. Live-site probes were not possible from the review
sandbox, so "deployed" below means "deploy config present and commit history
says it shipped", not "verified serving today".

## 1. The goal, stated plainly

Build a personal pair-programming agent ("Jarvis") that is:

1. **Always on and reachable** — one process with a stable URL, not a CLI you
   have to be sitting at.
2. **Shared across the tools you already use** — Claude Code, Cursor, OpenCode,
   and Slack all talk to the *same* Jarvis and see the *same* memory, goals, and
   claims.
3. **Built on the harness you already have** — `dottie` (routing, plugins,
   meta-MCP, timeline, memory, contacts), not a fresh codebase.
4. **Honest** — every number carries provenance; unreachable is reported as
   unreachable. This is already house doctrine; the plan keeps it.

Definition of done for Jarvis v1: a goal typed in Slack, a memory written from a
Claude Code session, and a claim made from Cursor are all visible to each other
within seconds, through one hosted endpoint, with CI green on `main`.

## 2. Portfolio triage — where the 27 repos land

The account has one center, a ring of building blocks, a ring of live products,
and a tail of things that are finished or superseded. The single most important
finding: **almost all recent effort went to the outer rings** (vector-equities
197 commits since June, vector-hub 96) while the center's CI has been red on
every push since at least 2026-08-18.

### Center — build Jarvis here

| Repo | Why it is the center | State |
|---|---|---|
| **dottie** | Harness (`apps/scout-cli`, 60+ plugins, forge, meta-MCP), agent OS (`apps/dottie`: RLM, sessions, continual harness, goals), hosted API (`apps/dottie-harness-api` → slasso.com), conductor UI (`apps/arxiviq`), scopes/channels/drivers from the v2 spec. Vendors ava-skills, ava-open-harness, personal-graphify. | 56 commits since June. **CI red on `main` every run 08-18 → 08-27** (558 runs total). 123 untriaged open TODO items. 4 open PRs from July never closed (#7, #8, #9, #10). |

### Building blocks — consumed by the center

| Repo | Role | Disposition |
|---|---|---|
| **acne** | People/entity memory graph; ships `acne mcp-serve` (stdio + streamable HTTP). Own CI + PyPI publish. | **Keep active.** It is the one standalone package that is not a mirror. Jarvis's contacts memory. |
| **scout-cli** | Origin of the `scout` CLI | **Stale mirror.** 47 paths differ from `dottie/apps/scout-cli`; dottie is newer (08-27 vs 08-13) and has plugins the mirror lacks (`comms`, `inbox`, `infer`, `pair`). 3 open PRs from July. |
| **ava-skills** | Skill registry | **Stale mirror.** 30 paths differ; dottie side has `anydoc`, `jspace-context-engine`. |
| **ava-open-harness** | Eval gate (anti-mock rubric) | **Stale mirror.** Its own README already says "treat the dottie copy as source of truth". |
| **personal-graphify** | Code/knowledge graph CLI | **Stale mirror.** 20 paths differ; dottie newer. |
| **ava-agi-factory-v6-4** | Foundation-model training track (J-Space, scale ladder) | **Park.** Needs the RTX box; P3 in the existing plan. Not on the Jarvis critical path. |
| **cursor-agent-skills**, **cursor-skills-personal** | Skill/prompt content packs | **Keep as content.** No code, no CI needed. Jarvis's agent-side instructions will live here. |

### Live products — maintain, do not expand until Phase 3 lands

| Repo | Surface | Note |
|---|---|---|
| vector-hub | dumbmodel.com hub | 2 open PRs (#13 draft, #15). 3 open TODO items. |
| vector-hoops, vector-equities, vector-gridiron, vector-pitch, vector-unified | the five daily games | vector-unified was meant to consolidate the others (its `GOAL_AND_SHIP.md` says "5-game hub"); the other four still receive direct commits. Each carries a `COORDINATION.md` claim board that duplicates dottie's `bundles/coordination`. |
| arxiviq | arxiviq.com | **Diverged.** The standalone repo is the older graph site (`site/app/page.tsx`, `starter/`). The conductor + pairing UI (`app/conductor`, `app/api/pair/*`, `app/acd/*`) exists only in `dottie/apps/arxiviq`. Decide which one deploys to arxiviq.com (§6, decision 4). |
| jcamd, who-e, vector-arcade, vector-fusion-demo, component-books, alamost-com | personal site, reader, arcade, demo, book, card shop | Single-commit or finished. Leave alone. |

### Superseded — close out

| Repo | Why | Action |
|---|---|---|
| **bluehen** | `DEPRECATED.md` dated 2026-08-09 says development moved to dottie. But a weekly `okf-refresh.yml` cron still commits (08-10, 08-17, 08-24, 08-31) and `config/fleet.json` still lists 9 sites as `active`, including retired bhenre.com surfaces. Its `CLAUDE.md` still describes an active fleet, which misleads any agent that boots there. | Disable the cron, mark fleet statuses, archive the repository on GitHub. The 2 security fixes from 08-12/13 (rate-limit XFF, SSRF TOCTOU) are worth porting if the same code exists in dottie; grep before archiving. |
| **agent-lasso** | LangGraph + FastAPI multi-LLM chat app on Vercel, 1 test, no CI. This was the first Jarvis-shaped attempt ("Daivis agent"). | Salvage ideas only (LangGraph loop, Vercel Python deploy pattern). Do not host it as Jarvis. |
| vector-schools, vector-realty | No deploy config, no CI, experiments | Freeze. |
| jcdavis131 | Profile README | Fine as is. |

## 3. What already exists for a Jarvis (honest inventory)

Read this before building anything; most of the pieces are there.

| Jarvis capability | Exists today in dottie | Gap |
|---|---|---|
| Route a goal to the cheapest tier, plan a DAG, execute with a bounded recovery ladder, record a measured timeline | `scout harness run` (`apps/scout-cli/bigbang/plugins/harness/`) | Local CLI only. |
| Tool surface an agent can call | 60+ plugins; `scout forge` writes new ones; `scout mcp serve --transport streamable-http` exposes plugins as MCP tools; `scout mcp ns …` aggregates downstream MCP servers | The MCP server is not hosted anywhere. |
| Memory | `personal-graphify` (code graph), `acne` (people), `apps/dottie/dottie/harness_continual.py` (versioned prompts/memories with rollback), MEMORY.md write-back | Three stores, no single "remember this" endpoint. |
| Agent-to-agent messaging | `comms` plugin and `apps/dottie/dottie/sessions.py` inbox | **File-based** under `~/workspace/.dottie/` — only works on one machine. |
| Claim board (who is working on what) | `bundles/coordination`, plus a `COORDINATION.md` copied into every vector repo | Synced by hand via "chore: sync claim board" commits (13 of them on 08-18 alone). |
| Local always-on server | `docker-compose.dottie.yml` runs a stdlib HTTP server on 127.0.0.1:8787 with bearer auth, HMAC ephemeral tokens, rate limits | The server is a **Python heredoc inside the compose file**, not a package; `scout api` referenced in the comment does not exist as a plugin. |
| Hosted API | `apps/dottie-harness-api` on Vercel (slasso.com): `/api/health`, `/api/route`, `/api/plan`, `/api/stats`, `/api/meter`, `/api/vector/*` | Stateless routing and dashboards only. No execution, no memory, no auth. |
| Pairing local ↔ cloud | `pair` plugin (6-char code, local queue) + `apps/arxiviq/app/api/pair/verify` | **Cloud side is a demo**: it accepts any well-formed code, stores it in lambda memory (lost on cold start), and the comment says "production should look up Supabase". No queue relay exists. |
| Slack / web identity | `channels/slack.json`, `channels/identity.json`, `scopes/person|room|org` | **Config only.** No Slack event handler code anywhere in `apps/` or `packages/`. |
| Model-agnostic driver seam | `scopes/drivers/wiring.py` — `HarnessDriver.run(scope, goal, tools)` for Pi / OpenCode / Codex / Claude Code | Interface exists; no driver talks to a network endpoint. |
| A brain | `apps/dottie` engine with `OllamaPolicy` (qwen3:32b) and a FastAPI `/tasks` API; `EchoPolicy` for CI; `AvaPolicy` (trainee, no capability) | Needs its own venv + `AVA_FACTORY_ROOT`; excluded from the uv workspace. Ollama cannot run on free-tier hosting. |
| Learning loop | `flywheel_cycle.py` nightly; promotion gate; champion served advisory | Working as designed (gate never passed, honestly). Not on the Jarvis critical path. |

## 4. The gaps, ranked by how much they block Jarvis

1. **No single always-on process.** Everything real runs as a CLI on one box; the only hosted thing is stateless routing.
2. **No network transport between agents.** Inboxes and claim boards are files. Two machines, or one machine and a cloud session, cannot see each other.
3. **No agent-facing endpoint for the tools you use.** The right seam exists (`scout mcp serve`), but nothing points Claude Code, Cursor, or OpenCode at it.
4. **Signal-to-noise in the repo itself.** CI red for two weeks, 123 open TODO items, four stale PRs, and doctrine docs (`NORTH_STAR.md`) written as token soup that no agent can act on. Any agent that boots into dottie today gets contradictory instructions.
5. **Two brains, no front door.** `apps/dottie` (FastAPI + Ollama) and `scout harness` (deterministic) are both "the agent". Jarvis needs one entry point that calls both.
6. **Mirror drift.** Four standalone packages and the arxiviq site have diverged from their dottie copies in both directions.

## 5. The plan

Four phases. Each has acceptance criteria you can run. Phases 0 and 1 are the
critical path; do them in order. Estimates assume solo evenings/weekends.

### Phase 0 — Stabilize the center (2–3 days)

The fixes are small; the discipline is the point. Nothing in Phases 1–3 is
trustworthy while `main` is red.

| # | Task | Evidence / how |
|---|---|---|
| 0.1 | **Make CI green on `main`.** Two failures at HEAD `c7d1f54`, both reproduced locally: (a) `Ruff lint — packages/ava-skills (HARD gate)` — 9 findings in `packages/ava-skills/skills/anydoc/skill.py` (7 auto-fixable with `ruff --fix`; the 2 `UP035` need `Dict/List` → `dict/list`). Because this is the first hard gate, **every later step has been skipped, so no test has run in CI since the gate went red.** (b) `codeact-sandbox` job — `apps/ava-factory/tests/test_minhash_dedup.py::test_the_real_key_collision_is_recovered_not_overwritten` asserts a hardcoded collision count of 3; the tree now has 4. Count from the tree or assert `>=`. **Two more gates fail on the clean tree and are currently hidden behind (a):** (c) `Documented counts` — README/Makefile/ci.yml still say "511 known ruff findings"; the fresh count is 1022, and the gate wants the number updated with a reason; (d) `HANDOFF freshness` — `HANDOFF.md` cites sha `18e3454`, which is not in the repo (history was rewritten), so the top block must be re-stamped against a real sha. Expect one more round after (a)+(b) before `main` is green. **Two failures outside `ci.yml`, also red on every `main` push:** (e) `.github/workflows/cml.yaml` — `iterative/setup-cml@v1` cannot install on the Node 22 runner (node-canvas prebuilt binary 404, source build fails); 7 of 7 runs since 08-20 die at that step, and the workflow body is a `print` plus a hardcoded report, so either pin Node 20 with `actions/setup-node@v4` first or delete the workflow. (f) **Vercel builds of both the `dottie` and `arxiviq` projects error on every deployment since at least 08-19, production included:** `cd apps/arxiviq && npm ci` refuses because `package-lock.json` lacks the optional `@next/swc-*@14.2.5` platform entries. `npm install` in `apps/arxiviq` regenerates it. Until this lands, nothing pushed to dottie reaches arxiviq.com or the conductor. | `uvx ruff@0.15.22 check packages/ava-skills` · `uv run python scripts/check_documented_counts.py --check` · `uv run python scripts/check_handoff_fresh.py --check` · `cd apps/arxiviq && npm ci` · rerun `ci.yml` |
| 0.2 | **Close or merge the four July PRs** in dottie (#7, #8 auto-generated test stubs; #9 `dev_loop` plugin; #10 lane claim) and the three in scout-cli (#4, #5, #10). Stale PRs are noise for every agent that reads the repo. | GitHub |
| 0.3 | **Archive the stale mirrors.** `scout-cli`, `ava-skills`, `ava-open-harness`, `personal-graphify` standalone repos → GitHub "archived" with a README banner pointing at the dottie path. If you want public standalone packages later, publish *from* dottie with a one-way sync script, never by hand. `acne` stays active. | GitHub settings |
| 0.4 | **Close out bluehen.** Disable `okf-refresh.yml`, set retired surfaces to `retired` in `config/fleet.json`, port the two August security fixes if dottie has the same code, archive. | see §2 |
| 0.5 | **Triage `TODO.md` 123 → ≤ 20.** Tag each survivor `jarvis`, `research`, or `parked`. Move the reasoning log to `docs/archive/`. Replace `NORTH_STAR.md` prose with a machine-readable `docs/STATE.json` (what is live, what is red, what is next) that the HANDOFF freshness gate already knows how to check. | one sitting |

**Acceptance:** `ci.yml` green on `main`; zero open PRs older than 14 days across the account; TODO.md ≤ 20 items.

### Phase 1 — One front door: the Jarvis daemon (≈2 weeks)

Promote the heredoc server in `docker-compose.dottie.yml` into a real package,
`apps/jarvisd` (name is yours; "daemon" is the role). It is **one long-running
process** that owns state and exposes two protocols:

- **MCP (streamable HTTP)** — the protocol Claude Code, Cursor, and OpenCode
  all speak natively. Reuse `scout mcp serve`; register a curated namespace
  rather than all 60 plugins. First tool set:
  `jarvis.context(repo)` (what am I working on, open claims, recent timeline),
  `jarvis.remember(text, scope)` / `jarvis.recall(query)` (graphify + acne +
  continual harness behind one call), `jarvis.claim(repo, area)` /
  `jarvis.release`, `jarvis.inbox(agent)` / `jarvis.send(to, msg)`,
  `harness.route(goal)`, `harness.run(goal)`, `contacts.resolve(phrase)` (acne).
- **HTTP JSON** — keep the existing `/api/health`, `/api/route`, `/api/plan`
  shape from `dottie-harness-api` so slasso.com can later proxy to it; add
  `/api/goals`, `/api/inbox`, `/api/claims`, `/api/timeline`.

State moves from files to **one SQLite database on a volume** (inbox, claims,
goals, sessions, timeline index). Keep the JSONL timeline as an export, not the
store. Auth is the design that already exists (bearer + 90 s HMAC per-agent
tokens + rate limits); implement it once in the package instead of inline.

**Where the brain lives is decision 1 in §6.** The recommendation for v1: the
client agent (Claude Code, Cursor) *is* the brain, and Jarvis is the shared
context + tools + routing server. That makes v1 free-tier-hostable and useful
on day one. `OllamaPolicy` remains available for the home box.

**Acceptance:** from a fresh machine,
`claude mcp add jarvis --transport http https://<host>/mcp` lists the tools;
a memory written in a Claude Code session is recalled from a Cursor session;
the ava-factory suite and scout-cli suite still pass; `docker compose up`
brings the daemon up with no heredoc.

### Phase 2 — Host it (≈1 week, mostly ops)

Constraints from your own docs: public/free-tier only; the capable models
(Ollama qwen3:32b, the RTX trainer) live on the home box; the daemon needs
persistent state and must stay up.

| Option | Fits the constraints? | Verdict |
|---|---|---|
| **Home box + Cloudflare Tunnel** | Free. Always on while the box is on. GPU and Ollama available. Public HTTPS on your domain. SQLite on local disk, nightly backup to R2 (you already use R2). | **Recommended v1.** |
| Fly.io machine with volume | Small always-on Python service fits the free-ish allowance; persistent volume; no GPU. | v2 fallback for "laptop closed" days. Clean container already implied by Phase 1. |
| Cloudflare Workers + D1 | Free, always on. But the daemon is stdlib Python; Workers need a JS/TS rewrite (Python Workers are beta). | Only if you decide to rewrite the daemon in TypeScript, which the `apps/arxiviq/app/acd/*` code hints you have started. Not for v1. |
| Vercel serverless (current) | Stateless, cold starts, no long-running process. | Keep for slasso.com dashboards; **not** the Jarvis host. |

**Acceptance:** `https://jarvis.<your-domain>/api/health` returns `ok` from a
phone; `claude mcp add` works from Claude Code on the web; state survives a
daemon restart; a nightly R2 backup exists.

### Phase 3 — Connect the agents (≈2 weeks)

| Client | What to add | Where |
|---|---|---|
| Claude Code | `.mcp.json` pointing at the daemon; a SessionStart hook that calls `jarvis.context(repo)` and injects the result; a `jarvis` skill that says when to `remember`/`claim`. | each active repo + `cursor-skills-personal` |
| Cursor | `.cursor/mcp.json` with the same server; a rule that mirrors the skill. | same repos |
| OpenCode | `opencode.json` `mcp` entry (the bluehen one shows the shape). | dottie root |
| Slack | Implement the handler behind `channels/slack.json`: Slack Events → `scopes/person|room` resolve → `harness.route` → reply. Stdlib or Bolt; runs inside the daemon. Consequential actions park in the existing `scout inbox` for approval. | `apps/jarvisd/channels/slack.py` |
| Agent ↔ agent | Point `comms` and `sessions.py` at the daemon's HTTP inbox; delete the file-inbox path. Replace the per-repo `COORDINATION.md` copies with `jarvis.claim`; one board, no sync commits. | scout-cli plugins |
| Pairing | Replace the demo `/api/pair/verify` with a call to the daemon (through the tunnel). The local daemon is the truth; the cloud conductor only asks it. | `dottie/apps/arxiviq` |

**Acceptance:** a goal typed in Slack appears in the next Claude Code session's
context; a claim from Cursor is visible in Claude Code within 5 s; zero "sync
claim board" commits for a week.

### Phase 4 — Let it learn (ongoing, already built)

Nothing new to build. Once the daemon is the source of traces, the nightly
`flywheel_cycle.py` gets real multi-agent, multi-machine traces and the
promotion gate keeps doing its job. Revisit P1 of `PLATFORM_IMPROVEMENT_PLAN.md`
(label ceiling) only after Phase 3.

## 6. Decisions only you can make

1. **Brain placement for v1.** (a) Client agent is the brain, Jarvis is the
   shared context/tools server — recommended, free-tier-hostable, useful
   immediately. (b) Jarvis has its own LLM (Ollama on the home box) and clients
   delegate to it — more "Jarvis", but ties uptime to the box and adds a second
   reasoning loop to debug.
2. **Hosting.** Home box + Cloudflare Tunnel (recommended) vs Fly.io vs a
   TypeScript rewrite for Workers.
3. **Archive the four mirror repos and bluehen.** Recommended yes. The
   alternative is a one-way sync script; hand-syncing has already failed.
4. **Which arxiviq deploys to arxiviq.com.** The standalone graph site or the
   conductor in `dottie/apps/arxiviq`. Recommended: the dottie one, and archive
   the standalone repo or reduce it to the data-build scripts.
5. **Feature freeze on the five game sites until Phase 3 lands.** They absorbed
   most of August. Recommended yes; bug fixes only.

## 7. First five things to do (in order)

```bash
# 0.1a — lint gate (7 auto-fixes, then fix the two UP035 by hand)
cd dottie && uvx ruff@0.15.22 check packages/ava-skills --fix
# 0.1b — the minhash count: change the hardcoded 3 to a tree-derived count
$EDITOR apps/ava-factory/tests/test_minhash_dedup.py   # line ~1444
# verify locally the way CI does
uv sync --all-groups --frozen && (cd apps/scout-cli && uv run pytest tests -q)
# 0.2 — close the July PRs (dottie #7 #8 #9 #10; scout-cli #4 #5 #10)
# 0.3 — archive scout-cli, ava-skills, ava-open-harness, personal-graphify (GitHub → Settings → Archive)
# 0.4 — bluehen: disable .github/workflows/okf-refresh.yml, then archive
# 0.5 — TODO.md triage, then start Phase 1 with apps/jarvisd from the compose heredoc
```

## 8. What this plan deliberately does not do

- It does not touch the training/flywheel track. That loop is honest and
  automated; Jarvis feeds it later.
- It does not propose a new UI. The conductor in `dottie/apps/arxiviq` and the
  slasso.com dashboard are enough surface for v1.
- It does not pick a model vendor. The driver seam in `scopes/drivers/wiring.py`
  is the right abstraction; keep it.
