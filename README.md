# Dottie — self-improving orchestration platform

![CI](https://github.com/jcdavis131/dottie/actions/workflows/ci.yml/badge.svg)
![Ruff Lint](https://github.com/jcdavis131/dottie/actions/workflows/lint.yml/badge.svg)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![uv](https://img.shields.io/badge/uv-workspace-black)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Solo Project](https://img.shields.io/badge/solo-personal%20project%20%E2%80%94%20no%20employer%20tie-lightgrey)

Dottie is an orchestration platform built around a measured improvement loop:
goals go in; a harness routes each goal to the cheapest of five execution tiers
that can do the work; execution — including real external tool calls through a
meta-MCP layer — leaves a **measured** trace; and traces can support offline
router research. The production HTTP boundary currently uses deterministic,
request-derived routing only. No learned router is deployed, and learned or
artifact-backed output remains fail-closed until production provenance and
promotion requirements are satisfied.

> Solo personal project, no connection to employer, built with public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip). See `apps/dottie/DOTTIE_PRIME_SOTA.md` for prime → Dottie comparison.

The normative description of Dottie — the four planes (surfaces, the jarvisd
decision plane, knowledge, learning), every service and port, the `decide`
contract, which knowledge reaches decisions, the measured speed budget, the
rules and the retirement decisions — is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
When that document and the code disagree, the code is right.
(`docs/ECOSYSTEM.md` is now a pointer and a history.)

## The loop

1. **Decide** — `decide(goal, hints)` (jarvisd `POST /api/decide`, MCP
   `harness.decide`; `scout route` asks jarvisd and falls back to the same code
   in-process) builds a bounded context (jarvisd memories, open goals, claims,
   run history) and routes through the one router: the MoMA-lite heuristic
   chooses among five tiers (`deterministic`, `llm`, `deep_research`,
   `action_operator`, `agentic_epic`); the learned MLP and System One advise
   until a gated, human-stamped artifact exists.
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
5. **Retrain** — offline research can rebuild the corpus and hill-climb the
   router; no retrain output is exposed by the production HTTP boundary.
6. **Gate** — promotion requires a production-derived, non-synthetic artifact
   bundle with signed provenance and verified checksums. No current artifact
   satisfies that serving contract.
7. **Serve** — the harness API currently serves authenticated,
   request-derived deterministic routing and planning only. Learned outputs
   and artifact-backed routes fail closed as unavailable.

## Monorepo layout

| Path | What it is |
|---|---|
| `apps/scout-cli` | scout, Dottie's CLI: 60+ capability-declared plugins (harness, router, mcp, forge, vector, …) behind one `scout` entry point. `scout route` goes through the router |
| `packages/dottie-loop` | The spec's contracts as stdlib code, including **the router** (`dottie_loop.router`: one routing policy for scout and jarvisd, MoMA-lite heuristic + advisory learned/System One backends, traces and the training loop). See [`docs/ROUTER.md`](docs/ROUTER.md) |
| `apps/ava-factory` | Training factory: data pipeline, trainer, corpus mining, hill-climb, scale ladder (smoke → nano → mini → base1b); excluded from the uv workspace (requirements/Docker-driven) |
| `apps/dottie-harness-api` | Fail-closed authenticated harness API: request-derived deterministic `/api/route` and `/api/plan` from the router's MoMA-lite heuristic (vendored by `scripts/vendor_router.py`, parity-tested); learned and artifact-backed routes remain unavailable. Phase 2: a thin proxy to jarvisd `/api/decide` |
| `apps/jarvisd` | The decision plane: the always-on daemon (`:8790`) serving `/api/decide`, MCP at `/mcp`, and one SQLite store of memories, claims, goals, inbox and timeline |
| `apps/dottie` | Agent OS layer: RLM engine, flywheel, missions, research orchestration (see its README); excluded from the uv workspace (own `.venv` + `AVA_FACTORY_ROOT` needed, entangles with the `dottie.rl` namespace collision) |
| `apps/scout-rtx` | Windows RTX hill-climb runner (torch cu128 hard-pin); excluded from the uv workspace |
| `apps/jev-v0` | System One spike: small+LoRA+pointer heads, frozen `jev-decision-schema-1.0.0`, typed `/decide` dev server on 8771 (`--checkpoint` serves a trained pointer-LoRA). **NOT `train_1b`**, **NOT TypeSafe parity**. Excluded from the uv workspace (`--dry-run` is stdlib; `--go` is optional HF+peft) |
| `apps/dottie-os` | Curation mirror of dottie-os (the local sidecar that serves System One `/decide` on `:8770`, which is not in this tree): the UltraData curriculum factory + harvest/hop lab scripts, emitting strict `jev-decision-schema-1.0.0` records + a provenance sidecar. LIVE / FT out of scope. Excluded from the uv workspace (stdlib smoke; optional HF `datasets` on the host) |
| `apps/arxiviq` | Next.js app (arxiviq) |
| `apps/bluehenre` | **Deprecated** bhenre.com org console — retired as a deployed surface 2026-08-09; see `apps/bluehenre/DEPRECATED.md` and `docs/CONSOLIDATION.md`. Owner decision 2026-09-23: archived out of the monorepo in Phase 2 |
| `apps/dottie-org` | Org spec of record (`SPEC.md`) |
| `packages/ava-skills` | Skill system (memory-router, memory-mint, code-bench, safety-scanner, …); ruff hard gate at 0 |
| `packages/ava-open-harness` | Eval gate: J-Space tests, 11-category rubric, anti-mock guard |
| `packages/personal-graphify` | Code knowledge-graph CLI/library |
| `playbooks/` | Business playbooks (`monitor`, `ops`, `research`, `validation`), parsed by `scripts/business/playbook.py` |
| `docs/` | Doctrine and specs (see [Doctrine docs](#doctrine-docs)) |
| `scripts/` | CI gates, ratchets, and their self-tests |

Root `pyproject.toml` is a virtual uv workspace over five light packages
(`packages/ava-skills`, `packages/ava-open-harness`,
`packages/personal-graphify`, `apps/scout-cli`, `apps/jarvisd`); `apps/scout-rtx` and
`apps/ava-factory` are deliberately excluded (heavy, pinned deps), and so is
`apps/dottie` (own `.venv` + `AVA_FACTORY_ROOT`, entangled with the
`dottie.rl` namespace collision — see `HANDOFF.md`'s open-decisions list)
and `apps/jev-v0` (optional HF+peft on `--go`; `--dry-run` is stdlib-only)
and `apps/dottie-os` (UltraData factory/harvest/hop mirror; stdlib smoke only).

## Quickstart

```bash
git clone https://github.com/jcdavis131/dottie.git && cd dottie

uv sync --all-groups --frozen        # install workspace members editable; lockfile must be current

uv run scout --help
uv run pytest packages/ava-skills -q

# route a goal with the deterministic heuristic
uv run scout --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"

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

- **Public deployment: BLOCKED.** The repository does not claim a verified
  production host until a named owner, real distributed edge-rate policy,
  bearer rotation procedure, and canonical HTTPS smoke are independently
  confirmed.
- **`GET /api/health`** — returns only service identity, API version, and
  readiness; incomplete deployment policy fails closed.
- **`POST /api/route`** — authenticated, request-derived deterministic
  heuristic output. Learned fields remain unavailable.
- **`POST /api/plan`** — authenticated deterministic static-prior planning.
- **Artifact routes** — stats, analytics, corpus, meter, retrain, and vector
  routes return `503 artifact_unavailable`.

Implementation and exact local/public configuration requirements:
`apps/dottie-harness-api/README.md`.

## Training and the eval gate

The factory (`apps/ava-factory`) owns offline corpus and model research. The
foundation-model track is not a live product surface, and local training
telemetry is not published as production status.

`ava-open-harness` is one necessary checkpoint gate: J-Space behavioral tests,
the 11-category weighted rubric, safety evals, and `test_no_mock.py`. Passing it
is not sufficient for serving. A production artifact must also have
claim-eligible licensed sources, signed lineage, verified content checksums,
matching tokenizer/config identity, and an owner-approved loader with no
fallback. No current learned artifact meets that full contract.

```bash
uv run pytest packages/ava-open-harness -q   # non-blocking in CI today (package name collision, documented in ci.yml)
```

## Historical training status (2026-08-09)

- **Offline candidate only:** `orch-mlp-v1-v4` recorded 97.2% validation
  accuracy and 87.7% on a 57-record measured hold-out. Those repository
  artifacts are historical research evidence, not a deployed champion and not
  served by `/api/route`. Corpus: 1,556 records, 722 measured
  (`apps/ava-factory/data/orchestration/corpus_meta.json`; candidate metrics in
  `apps/ava-factory/reports/orchestrator/eval_report.json`).
- **Research gate not passed.** The candidate's 87.7% fell short of the
  heuristic's 89.3% on that historical hold-out. Independently, it lacks the
  complete production artifact provenance and deployment ownership required
  above, so it is not eligible to serve.
- **CI:** full pipeline green on GitHub runners as of `c151ab2`.
- **Consolidation:** dottie is the primary monorepo; the bluehen fleet
  monorepo and all bhenre.com surfaces are deprecated
  (`docs/CONSOLIDATION.md`); standalone GitHub repos (`scout-cli`,
  `ava-skills`, `ava-open-harness`, `ava-agi-factory-v6-4`) are vendored
  mirrors — changes originate here and are pushed outward, never the reverse.

## Doctrine docs

| Doc | What it holds |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **Normative.** The four planes, runtime topology, services and ports, the decide contract, knowledge sources, the learning loop, the measured speed budget, the rules, retirement decisions |
| [`docs/ROUTER.md`](docs/ROUTER.md) | The one router: decision order, backends, authority (gate + human stamp), traces, the training loop |
| [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) | Pointer + history: the 2026-08 map, label ceiling, provenance doctrine, honest status as of then |
| [`docs/CONSOLIDATION.md`](docs/CONSOLIDATION.md) | One monorepo, fewer surfaces: what is deprecated, what stays live, salvage manifest |
| [`docs/PLATFORM_IMPROVEMENT_PLAN.md`](docs/PLATFORM_IMPROVEMENT_PLAN.md) | The plan: P0 CI-to-green, P1 break the label ceiling, P2 harness capability |
| [`docs/JARVIS_HARNESS_PLAN.md`](docs/JARVIS_HARNESS_PLAN.md) | Portfolio triage of all 27 repos and the phased path to a hosted, agent-connected pair programmer built on this harness |
| [`docs/PROJECT_DAG.md`](docs/PROJECT_DAG.md) | The unified project DAG: every piece of product and infra work as a node with dependencies; `scripts/dag_next.py` prints what is ready now |
| [`docs/FACTORY.md`](docs/FACTORY.md) | The factory: how DAG nodes get executed. `python -m factory` runs the software line (repo validate gates, start/done), the MLOps line (the box's one training queue with gates) and the data line (dataset presence, freshness, restore) |
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

## Local Dottie control plane

```bash
git clone https://github.com/jcdavis131/dottie ~/workspace/dottie && cd dottie
uv sync --all-groups --frozen
export JARVIS_BEARER="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose -f docker-compose.dottie.yml up -d --build
```

The compose file runs the canonical jarvisd image on host-loopback port 8790,
with SQLite state in `jarvis-data`. It does not simulate a queue, local daemon,
model, or harness. The brain defaults off. Ollama is opt-in with
`JARVIS_BRAIN=ollama` and defaults to `qwen3:8b`; otherwise the brain reports
unavailable.

```bash
# Create a real 10-minute code in jarvisd.
export JARVIS_URL=http://127.0.0.1:8790
uv run scout pair create
```

The arxiviq `/dottie` page verifies codes only through a configured jarvisd
BFF. There is no in-memory or accept-any fallback; unset/unreachable jarvisd
returns 503 and disallowed targets return 403. A successful same-origin verify
sets a signed, HttpOnly `__Host-arxiviq_session` cookie for at most ten minutes;
claims/goals reads then use the fixed `ARXIVIQ_JARVIS_REPO`. Newly paired sessions
also expose the same fixed repo through an authenticated conductor BFF: measured
snapshot reads and only feedback, scratchpad, and todo writes. Production also
requires `ARXIVIQ_PUBLIC_ORIGIN`, a distinct base64url
`ARXIVIQ_SESSION_SECRET` decoding to at least 32 bytes, and an exact HTTPS
`JARVIS_ALLOWED_ORIGINS` entry for a remote `JARVIS_URL`. Command, PTY, tunnel,
machine/session control, guardrail mutation, compaction, and scout execution remain
unavailable through this UI.

`ARXIVIQ_PUBLIC_ORIGIN` must be an exact HTTPS origin in production. Exact
HTTP origins are accepted only for `localhost`, `127.0.0.1`, or `[::1]`
development; credentials, paths, queries, and fragments are rejected.
On Vercel (`VERCEL=1`), pair rate identity uses only
`x-vercel-forwarded-for`. Other public deployments must set
`ARXIVIQ_TRUSTED_CLIENT_IP_HEADER` to a platform-overwritten header containing
one IP address. Exact loopback HTTP operation uses a fixed local identity.
The IP is HMAC-pseudonymized with `JARVIS_BEARER` before any bucket or Jarvis
agent ID is constructed; missing or invalid trusted metadata fails closed.

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
