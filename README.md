# Dottie — self-improving orchestration platform

![CI](https://github.com/jcdavis131/dottie/actions/workflows/ci.yml/badge.svg)
![Ruff Lint](https://github.com/jcdavis131/dottie/actions/workflows/lint.yml/badge.svg)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![uv](https://img.shields.io/badge/uv-workspace-black)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Solo Project](https://img.shields.io/badge/solo-personal%20project%20%E2%80%94%20no%20employer%20tie-lightgrey)

Dottie is a self-improving orchestration platform built around one closed loop:
goals go in; a harness routes each goal to the cheapest of five execution tiers
that can do the work; execution — including real external tool calls through a
meta-MCP layer — leaves a **measured** trace; traces are mined into training
labels; a router model retrains nightly against the accumulated corpus; a
fail-closed promotion gate decides honestly whether the new champion ships; and
the deployed router serves the same harness that generated the traces.

> Solo personal project, no connection to employer, built with public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip). See `apps/dottie/DOTTIE_PRIME_SOTA.md` for prime → Dottie comparison.

The normative map of the ecosystem — the loop diagram, repo roles, provenance
doctrine, and honest status — is [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md). When
that document and the code disagree, the code is right.

## The loop

1. **Route** — MoMA-lite heuristic classifier plus a learned MLP router
   (advisory) choose among five tiers: `deterministic`, `llm`,
   `deep_research`, `action_operator`, `agentic_epic`.
2. **Execute** — `scout harness run` drives route → DAG plan → deterministic
   executors → bounded recovery ladder (retry → patch → replan → escalate,
   fail-closed) → critic. Goals of the form `mcp:<server>__<tool> {json}`
   execute real external tool calls through the meta-MCP layer under a
   default-deny URL allowlist.
3. **Record** — every run writes a timeline and checkpoints with measured
   latency, measured status, and measured token cost (executors that make no
   model calls record 0 as a measured fact).
4. **Mine** — traces become labels from three sources: `measured-behavior`
   (the tier that executed), `measured-outcome` (the recovery ladder's
   escalation target when the routed tier failed), and `operator-corrected`
   (`apps/ava-factory/data/orchestration/label_corrections.jsonl`).
5. **Retrain** — a nightly Routine at 09:00 UTC rebuilds the corpus and
   hill-climbs the router.
6. **Gate** — promotion requires the new champion to strictly beat both a
   frequency prior and the routing heuristic on measured hold-out data. The
   gate has never passed; see [Status](#status-2026-08-09) for why that is the
   system working, not failing.
7. **Serve** — the current champion is deployed to slasso.com and answers
   `/api/route` with zero-torch numpy inference (parity ≤1e-4 against the
   trainer).

## Monorepo layout

| Path | What it is |
|---|---|
| `apps/scout-cli` | The `scout` CLI — 60+ capability-declared plugins (harness, mcp, forge, vector, …) behind one entry point |
| `apps/ava-factory` | Training factory: data pipeline, trainer, corpus mining, hill-climb, scale ladder (smoke → nano → mini → base1b); excluded from the uv workspace (requirements/Docker-driven) |
| `apps/dottie-harness-api` | The slasso.com surface: serverless harness API (`/api/health`, `/api/stats`, `/api/route`, `/api/plan`) + Validation Lab dashboard; numpy-only inference over vendored champion weights |
| `apps/dottie` | Agent OS layer: RLM engine, flywheel, missions, research orchestration (see its README); excluded from the uv workspace (own `.venv` + `AVA_FACTORY_ROOT` needed, entangles with the `dottie.rl` namespace collision) |
| `apps/scout-rtx` | Windows RTX hill-climb runner (torch cu128 hard-pin); excluded from the uv workspace |
| `apps/arxiviq` | Next.js app (arxiviq) |
| `apps/bluehenre` | **Deprecated** bhenre.com org console — retired as a deployed surface 2026-08-09; see `apps/bluehenre/DEPRECATED.md` and `docs/CONSOLIDATION.md` |
| `apps/dottie-org` | Org spec of record (`SPEC.md`) |
| `packages/ava-skills` | Skill system (memory-router, memory-mint, code-bench, safety-scanner, …); ruff hard gate at 0 |
| `packages/ava-open-harness` | Eval gate: J-Space tests, 11-category rubric, anti-mock guard |
| `packages/personal-graphify` | Code knowledge-graph CLI/library |
| `playbooks/` | Business playbooks (`monitor`, `ops`, `research`, `validation`), parsed by `scripts/business/playbook.py` |
| `docs/` | Doctrine and specs (see [Doctrine docs](#doctrine-docs)) |
| `scripts/` | CI gates, ratchets, and their self-tests |

Root `pyproject.toml` is a virtual uv workspace over the four light packages
(`packages/ava-skills`, `packages/ava-open-harness`,
`packages/personal-graphify`, `apps/scout-cli`); `apps/scout-rtx` and
`apps/ava-factory` are deliberately excluded (heavy, pinned deps), and so is
`apps/dottie` (own `.venv` + `AVA_FACTORY_ROOT`, entangled with the
`dottie.rl` namespace collision — see `HANDOFF.md`'s open-decisions list).

## Quickstart

```bash
git clone https://github.com/jcdavis131/dottie.git && cd dottie

uv sync --all-groups --frozen        # install workspace members editable; lockfile must be current

uv run scout --help
uv run pytest packages/ava-skills -q

# route a goal (heuristic; --learned augments with the champion when weights are present)
uv run scout --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"
uv run scout harness route "heartbeat check" --learned --json

# execute end-to-end: route -> DAG plan -> deterministic executors -> measured timeline
uv run scout harness run "ship the harness loop" --json

# local mirror of CI (lint + gates + tests + forge smoke + doctor)
make ci
```

The scout-cli test suite uses CWD-relative fixtures and must run from its own
directory, exactly as CI does:

```bash
cd apps/scout-cli && uv run pytest tests -q
```

## Single-CLI doctrine

The harness gets exactly one tool: `scout`. Every capability is a plugin behind
`scout --json ...`, each declaring capabilities (`network` / `filesystem` /
`secrets`, default deny) in a manifest. The agent adds capabilities itself
through the forge engine:

```bash
scout --json forge new github --description "GitHub API wrapper" --domains api.github.com --network
scout --json forge cat github            # read the generated cli.py
scout --json forge edit github --code '<implementation>'
scout --json forge test github           # smoke test
scout forge rm github --force

# or generate from a spec
scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json
scout --json forge from-mcp --name notion --url https://mcp.notion.com/sse
```

Forge engine: `apps/scout-cli/bigbang/plugins/forge/cli.py` (shipped in
`4528f85`; self-evolution loop verified end-to-end: `new demo_tool → hello →
test pass → rm`).

## Meta-MCP layer

The mcp plugin registers downstream MCP servers, groups them into namespaces
with per-tool disables, and re-serves a namespace as a single MCP endpoint.
This is what turns the `action_operator` tier outward: real external tool
calls, real failures, measured latency.

```bash
scout mcp add <server> <sse-url>              # register (default-deny URL allowlist)
scout mcp ns create ops                       # create a namespace
scout mcp ns add-server ops <server>
scout mcp ns tools ops                        # aggregate tools with enabled flags
scout mcp ns disable-tool ops <server>__<tool>
scout mcp ns call ops <server>__<tool> --args '{}'
scout mcp serve --namespace ops               # expose the namespace over MCP

# harness goals can call namespaced tools directly
scout harness run 'mcp:<server>__<tool> {"arg": "value"}' --mcp-namespace ops
```

Failures are real failures — policy denials, unreachable servers, downstream
errors — and they exercise the same bounded recovery ladder as everything
else, producing exactly the non-behavior labels the promotion gate needs.

## Live surface

- **https://www.slasso.com** — Validation Lab: training-progress dashboard,
  read-only and provenance-honest (every number derives from committed
  sources; unmeasured renders as UNMEASURED, never a plausible zero).
- **`GET /api/health`** — service health plus which artifacts are vendored.
- **`POST /api/route`** — heuristic routing always; learned routing
  (`orch-mlp-v1-v4`) when champion weights are vendored, degrading to
  heuristic-only otherwise.

```bash
curl -s https://www.slasso.com/api/health
curl -s -X POST https://www.slasso.com/api/route \
  -H 'Content-Type: application/json' \
  -d '{"goal": "compare stripe vs lemon squeezy pricing"}'
```

Implementation: `apps/dottie-harness-api` — a single stdlib
`http.server` handler, sole dependency numpy, fully self-contained.

## Training and the eval gate

The factory (`apps/ava-factory`) owns the corpus build and hill-climb; the
foundation-model track (J-Space architecture, phase curriculum) is a design
target with progress published to the live console — training telemetry is
generated locally, gitignored, and never committed.

Checkpoints are only promoted to serving if they pass `ava-open-harness`:
J-Space behavioral tests, the 11-category weighted rubric, safety evals, and
`test_no_mock.py` — a guard that exists because an earlier version of this
project fabricated eval scores, and every number must now come from a live
forward pass or fail with a structured error.

```bash
uv run pytest packages/ava-open-harness -q   # non-blocking in CI today (package name collision, documented in ci.yml)
```

## Status (2026-08-09)

- **Champion deployed:** `orch-mlp-v1-v4` — 97.2% validation accuracy, 87.7%
  on the 57-record measured hold-out — serves `/api/route` in an advisory
  role. Corpus: 1,556 records, 722 measured
  (`apps/ava-factory/data/orchestration/corpus_meta.json`; champion metrics in
  `apps/ava-factory/reports/orchestrator/eval_report.json`).
- **Promotion gate: not passed — by design.** The gate requires strictly
  beating both a frequency prior and the heuristic router on the measured
  hold-out; on the latest cycle the champion's 87.7% fell short of the
  heuristic's 89.3%. Behavior labels are the heuristic's own outputs — it
  scores 1.0 on them by construction — so the gate stays locked until the
  hold-out carries enough non-behavior labels: real meta-MCP action failures
  and operator corrections, the current P1 in
  [`docs/PLATFORM_IMPROVEMENT_PLAN.md`](docs/PLATFORM_IMPROVEMENT_PLAN.md).
  The dashboard reports the gate status as-is.
- **CI:** full pipeline green on GitHub runners as of `c151ab2`.
- **Consolidation:** dottie is the primary monorepo; the bluehen fleet
  monorepo and all bhenre.com surfaces are deprecated
  (`docs/CONSOLIDATION.md`); standalone GitHub repos (`scout-cli`,
  `ava-skills`, `ava-open-harness`, `ava-agi-factory-v6-4`) are vendored
  mirrors — changes originate here and are pushed outward, never the reverse.

## Doctrine docs

| Doc | What it holds |
|---|---|
| [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) | The normative map: loop, repos, tiers, label ceiling, provenance doctrine, honest status |
| [`docs/CONSOLIDATION.md`](docs/CONSOLIDATION.md) | One monorepo, fewer surfaces: what is deprecated, what stays live, salvage manifest |
| [`docs/PLATFORM_IMPROVEMENT_PLAN.md`](docs/PLATFORM_IMPROVEMENT_PLAN.md) | The plan: P0 CI-to-green, P1 break the label ceiling, P2 harness capability |
| [`docs/JARVIS_HARNESS_PLAN.md`](docs/JARVIS_HARNESS_PLAN.md) | Portfolio triage of all 27 repos and the phased path to a hosted, agent-connected pair programmer built on this harness |
| [`docs/PROJECT_DAG.md`](docs/PROJECT_DAG.md) | The unified project DAG: every piece of product and infra work as a node with dependencies; `scripts/dag_next.py` prints what is ready now |
| [`docs/LONGCAT2_INSIGHTS_SPEC.md`](docs/LONGCAT2_INSIGHTS_SPEC.md) | Architecture doctrine |
| [`docs/DOTTIE_HARNESS_DEEP_SPEC.md`](docs/DOTTIE_HARNESS_DEEP_SPEC.md) | Harness deep spec (tiers, checkpointing, recovery ladder, verification economics) |
| [`docs/TRAINING_CURRICULUM_SIZING.md`](docs/TRAINING_CURRICULUM_SIZING.md) | Curriculum sizing |
| [`docs/GRPO_PIPELINE.md`](docs/GRPO_PIPELINE.md) | GRPO pipeline |
| [`docs/LESSONS.md`](docs/LESSONS.md) | Recorded lessons |

## Repo hygiene and CI

- Generated telemetry and status files are gitignored; `make ci` fails if any
  are tracked.
- CI (`.github/workflows/ci.yml`): frozen uv sync, ruff hard gate on
  `packages/ava-skills` (at 0) with the remaining lint debt run non-blocking
  and counted, gate-audit and declared-capability ratchets (new fail-open
  patterns only), scripts self-tests, secret scans over the working tree and
  full history, hard-gate pytest for scout-cli / ava-skills /
  personal-graphify, non-blocking ava-open-harness, and a forge smoke test.
- Lint (`.github/workflows/lint.yml`): ruff pinned to the same version as
  ci.yml so local findings predict CI.
- `make ci` mirrors the workflow deliberately; if a gate is added to ci.yml it
  must be added there too.

## Dottie as open-source Hatch — local+Docker+website tandem you own

> Dottie is the open-source Hatch you build and run from your local machine + docker and link to your website then it can work and function like a hatch agent and work in tandem with my hatch agent to build together.

**One-command boot (pip/uv + Docker both work):**

```bash
git clone https://github.com/jcdavis131/dottie ~/workspace/dottie && cd dottie
bash install.sh   # bundles/cli.sh 770 zero_deps true + uv sync --frozen + docker-compose.dottie.yml up -d
# or: curl -fsSL https://arxiviq.com/starter/install.sh | sh
```

**What install does (production-grade extensible, not demo):**

- `apps/scout-cli/install.sh` → `bundles/cli.sh` 770, `bundles/zero_deps.json` `{"zero_deps":true,"allow":"acne:./src"}`, `bundles/manifest.json` v5 Prime 13 agents/11 packs/6 ultra modules MoMA-lite 5 tiers GARNet checker 7-field
- Docker `docker-compose.dottie.yml` services:
  - `dottie-api` `127.0.0.1:8787` localhost-only Bearer `dm_dev_*` timingSafeEqual + 90s HMAC ephemeral 256 LRU rate20/agent 60/key 1k/IP, audit prefix-only last4, CORS dev-only no-store nosniff DENY frame, honest 503 never fake
  - `dottie-harness` thin single daemon owns PTY/tunnel/file/ISL snapshot() every 2s → `/ws/.dottie/daemon_snapshot.json`
  - `dottie-redis` `redis:7-alpine` optional queue (filesystem fallback `/ws/.dottie/queue`)

**Link once via pairing code `scout pair create` → paste on arxiviq:**

```bash
# 1) local 6-char code (10m expiry, stored 0600 at ~/.config/dottie/pair.json):
uv run scout pair create
curl -X POST http://127.0.0.1:8787/api/dev/pair/create -H "Authorization: Bearer $DOTTIE_DEV_BEARER" | jq .code

# 2) Open arxiviq.com/dottie and paste code → Verify
# Production path: POST https://arxiviq.com/api/pair/verify {code} → Supabase pairings PK code exp idx + R2 pair_<code>.json
# Demo path: in-memory ephemeral LRU 256 honests in Next lambda warm

# 3) Tandem queue — cloud drops task, local picks up + streams back:
curl -X POST http://127.0.0.1:8787/api/dev/queue/push -H "Authorization: Bearer $DOTTIE_DEV_BEARER" -d '{"task":"build PWA offsite","from":"cloud Scout"}'
uv run scout pair status   # paired? local_api + queue_count
uv run scout queue list

# 4) Conductor shows triple green:
# arxiviq.com/conductor?tandem=1  → Local Healthy ● + Cloud Healthy ● + Paired ✓  + 127.0.0.1:8787 dev API
```

**Composition:**

- `apps/arxiviq/app/dottie/page.tsx` polished #080A0F CORE20 PWA — Generate + Copy + Verify tandem + Push/Claim/Clear queue, confetti same as conductor
- `your_files/dottie-tandem-bridge/index.html` standalone 19kB self-contained #080A0F CORE20 PWA fallback for local dev (no Vercel needed)
- `apps/arxiviq/app/conductor/page.tsx?type=...` reads `?tandem=1` and renders tandem bar, probes `127.0.0.1:8787/api/dev/health` + `.../pair/status` every 6s
- `apps/arxiviq/app/api/pair/verify/route.ts` + `.../status/route.ts` Next serverless pairing — in-mem LRU honest limit, upgrade to Supabase `pairings` table in <30 lines
- `apps/scout-cli/bigbang/plugins/pair/cli.py` `scout pair create|verify|status` + `scout queue push|poll|list` — stdlib only, pip/uv both, filesystem fallback + API fallback dual, timingSafeEqual Bearer

Extensible: replace filesystem queue with `XADD dottie:queue * task A` or Supabase realtime `INSERT queue` — task schema unchanged `{id,ts,task,from,to,status}`. Bridge guarantees at-least-once idempotent consumer, Paired receipt 7-field timeline triple-write `bundles/ultra/runs/dottie-tandem/timeline.jsonl + .scout/missions/dottie-tandem/timeline.jsonl + hidden`.

Only name is Dottie model + harness with Scout CLI tool — never hatch 2.0.

## Connect an agent

Claude Code, Cursor and OpenCode connect to the shared `jarvisd` daemon
(`docs/JARVISD_SPEC.md`) over MCP for context, memory, claims and handoffs.
Export `JARVIS_URL` (default `http://127.0.0.1:8790`) and `JARVIS_BEARER`, then:

| Client | Config | Verify |
|---|---|---|
| Claude Code | `.mcp.json` + SessionStart hook in `.claude/settings.json` + `.claude/skills/jarvis` | `claude mcp list` |
| Cursor | `.cursor/mcp.json` + `.cursor/rules/jarvis.mdc` | Settings → MCP shows `jarvis` |
| OpenCode | `opencode.json` `mcp.jarvis` | `opencode mcp list` |

Details, the two-client acceptance test, and how to copy this into other repos:
`docs/JARVIS_CONNECT.md`.

## License

MIT — Solo personal project, no connection to employer, built with public/free-tier only. See `LICENSE` and per-package READMEs.
