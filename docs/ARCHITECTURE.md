# Dottie architecture

**Status: normative** (2026-09-23). This page describes what runs today and
the rules it runs under. It replaces the aspirational parts of
`docs/ECOSYSTEM.md` (now a pointer and a history). When this page and the code
disagree, the code is right and this page has a bug; fix it here in the same
change.

Dottie is the `jcdavis131/dottie` monorepo: the harness, the router, the
decision model (System One), the dottie-os sidecar and the sites. Its goal is
that every decision it makes is **knowledgeable** (grounded in a bounded,
relevant context) and **fast** (warm, cached, measured), and that there is one
path that makes it.

## The four planes

1. **Surfaces (thin).** scout (`apps/scout-cli`), MCP clients (Claude Code,
   OpenCode, Cursor) over jarvisd `/mcp`, the console (`apps/arxiviq`, planned
   `os.jcamd.com`, through its server-side BFF), Slack (jarvisd
   `/api/slack/events`). Surfaces ask; they do not decide. scout asks jarvisd
   when it is reachable and falls back to the same code in-process when not.
2. **Decision plane: jarvisd** (`apps/jarvisd`), the one always-on process.
   One entry, `decide(goal, hints)`: context, then the router, then a decision
   record. Served as `POST /api/decide` and MCP `harness.decide`;
   `/api/route` and `harness.route` are compatible aliases. The code lives in
   `packages/dottie-loop` (`dottie_loop.decide`, `dottie_loop.context`,
   `dottie_loop.router`, `dottie_loop.backends`) so scout runs the identical
   path in-process.
3. **Knowledge plane.** One `ContextProvider` protocol
   (`dottie_loop/context.py`) with adapters. jarvisd's SQLite store is the
   canonical store for memories, goals and claims; scout's run timeline is the
   run-history store; personal-graphify is the code graph. No new stores.
4. **Learning plane.** Traces carry the same System One state the model is
   served (one builder, `dottie_loop.backends.system_one_state`) and a
   provenance tier, then `scout router probe` (benchmark labels) and real use
   (production labels) -> `scout router pack` -> train (MLP on CPU, System One
   on the GPU host) -> eval (quality gate) -> human spot-check and stamp ->
   serve. Nothing auto-promotes.

## Runtime topology

```
  shell / agents / console / Slack                       (surfaces)
      |            |               |            |
  scout CLI    MCP clients    arxiviq BFF    Slack events
      |   \        |               |            |
      |    \  POST /api/decide     |            |
      |     \      |  /mcp harness.decide       |
      |      v     v               v            v
      |   +---------------------------------------------+
      |   | jarvisd :8790  (decision plane, always on)  |
      |   |  decide(goal, hints)                        |
      |   |   1. context  -> jarvisd SQLite (memories   |
      |   |      FTS5, open goals, claims), run history,|
      |   |      graphify (opt-in); bounded, cached     |
      |   |   2. router   -> dottie_loop.router         |
      |   |      heuristic | learned MLP | System One --+----> dottie-os :8770
      |   |   3. record   -> timeline row + trace line  |      POST /decide
      |   +---------------------------------------------+      (jev-v0 serve_decide
      |                                                         dev server :8771)
      +--- jarvisd unreachable: same dottie_loop.decide in-process
           (run-history context; no jarvisd store)

  scout harness run (production) + scout router probe (benchmark-verified)
      --> ~/.dottie/traces/route-YYYYMMDD.jsonl --> scout router pack
      --> train (MLP: CPU; System One: GPU host) --> scout router eval
      --> scout router spotcheck + promote (human) --> served
```

## Services and ports

| Service | Where | Port / transport | Role |
|---|---|---|---|
| jarvisd | `apps/jarvisd` (`uv run jarvisd serve`, `docker-compose.dottie.yml`) | `127.0.0.1:8790` HTTP: `/api/*`, `/mcp` (streamable HTTP), `/sse` (opt-in) | Decision plane; memories, claims, inbox, goals, timeline, pairing, conductor |
| dottie-os sidecar | your machine or tailnet | `:8770` `POST /decide`, `GET /health` | Serves System One (`jev-decision-schema-1.0.0`) |
| jev-v0 dev server | `apps/jev-v0/serve_decide.py` | `127.0.0.1:8771` (default) | Same contract; `mode=untrained` without `--checkpoint` |
| scout | `apps/scout-cli` (`scout`) | CLI; `scout mcp serve` is stdio MCP | Surface; decides via jarvisd or in-process |
| console | `apps/arxiviq` (Next.js) | `next dev` `:3000` locally; Vercel | Surface; BFF talks to jarvisd with `JARVIS_URL` |
| harness-api | `apps/dottie-harness-api` (Vercel) | Vercel function `/api/*` | Public deterministic routing + dashboard. Serves the vendored MoMA-lite heuristic, **not** a learned champion |
| Ollama | the home box | `OLLAMA_HOST` (default `127.0.0.1:11434`) | Optional brain for `jarvis.ask` and the `llm` executor tier (`DOTTIE_LLM_MODEL`, default `qwen2.5:7b-instruct`); not on the decision path |
| agent OS | `apps/dottie` | `:8100` (`python -m dottie serve`) | Separate agent runtime; not on the decision path (see Phase 2) |

## The decide contract

`POST /api/decide` (bearer auth like every jarvisd route; `X-Agent-Id`
names the caller):

```json
{"goal": "compare Stripe vs Lemon Squeezy", "repo": "dottie",
 "hints": {"learned": false, "system_one": null, "insufficiency": null,
           "policy_exclusions": [], "hard_constraint": null},
 "context": true, "cache": true}
```

The response is the router output (every existing key: `intent`,
`intent_scores`, `complexity`, `moma_tier`, `moma_cap`, `confidence`,
`routed_agents`, `spec_tier`, `authority`, `heuristic_tier`, `advisory`,
`trace`) plus `decision`, the record:

| Field | Meaning |
|---|---|
| `schema` | `dottie-decision-record-1` |
| `decision_id`, `trace_id` | ids; the trace line carries the same `decision_id` |
| `goal_sha256` | the goal's hash. The text is stored only under `DOTTIE_TRACE_TEXT=1` |
| `tier`, `spec_tier`, `authority`, `heuristic_tier` | the decision and who made it |
| `system_one` | System One's answers (`tier`, `action`, `safe`, `severity`, `shape_concentration`, `mode`, `signal`, `authoritative`) or null when off |
| `context` | digest, item ids and scores, per-source counts, per-provider `ok` / `latency_ms`, size; never texts |
| `latency_ms` | `context`, `route`, `backends` (per backend), `total` |
| `cache` | `hit`, `key` prefix, `enabled` |

Order inside `route` is unchanged: hard constraints -> MoMA-lite heuristic
(always runs, the authority by default) -> learned advice taken only when its
artifact is `gate_passed` AND human-stamped AND picks an equal-or-cheaper tier
-> one tier up only on a recorded insufficiency. See `docs/ROUTER.md`.

**Cache.** A per-daemon LRU (256 entries, 30 s TTL;
`DOTTIE_DECIDE_CACHE_SIZE` / `_TTL`) keyed by (goal sha256, context digest,
backend config, hints). New knowledge changes the digest, so it misses. A hit
is marked in the record and still writes its own trace line.

**Aliases.** `/api/route` and `harness.route` call `decide` and return the old
field set plus `decision`; `/api/plan` decides the same way before building the
plan. All three run in the threadpool, never on the event loop.

## Knowledge sources

| Source | Store | On the decision path | Notes |
|---|---|---|---|
| Memories (FTS5 recall, top-k) | jarvisd SQLite | **yes** (jarvisd) | private: text leaves only under `DOTTIE_TRACE_TEXT=1` |
| Open goals | jarvisd SQLite | **yes** (jarvisd) | ranked by term overlap with the goal; private |
| Active claims | jarvisd SQLite | **yes** (jarvisd) | repo/area/agent as data, note text private |
| Run history (per tier: runs, success, recovery, p50 latency; per role: fail rate, latency) | scout timeline `~/.cache/scout/checkpoints/*/timeline.jsonl` (`SCOUT_CHECKPOINT_BASE`) | **yes** (jarvisd and scout in-process) | `dottie_loop.run_history.HistoryIndex`: (size, mtime) + byte-offset incremental index, persisted next to the store |
| Code graph hits | personal-graphify `graph.json` | opt-in (`DOTTIE_CONTEXT_GRAPH=<graph.json>`) | off by default |
| Goal features | computed | **yes** | lexical features, hash; always |
| dottie_loop `MemoryStore`, scout brain `MEMORY.md`, ava-skills memory | their own files | **no** | not decision inputs; any future use comes through a `ContextProvider` adapter, not a new store |
| Place state (USGS gauge, Atlas construct stack, NWS flood warnings) | `apps/atlas-outcomes/sources/` snapshots | **no** | an `outcome-real` System One decision pack for place decisions; a future place `ContextProvider` would serve the same state |
| harness-api analytics / corpus files | `apps/dottie-harness-api/lib` | **no** | dashboard only |

Every provider runs under a per-provider timeout (default 250 ms) and fails
soft: a failed provider is recorded as `ok: false` with the reason and the
decision proceeds. The context is capped (5 items per provider, 12 items,
160 characters per text, 4 KB serialized) and deterministic (sorted by score,
source, id; the digest hashes exactly those items).

## The learning loop

1. **Trace.** Every decision appends a route line to
   `~/.dottie/traces/route-YYYYMMDD.jsonl` with the goal hash, features, every
   backend's answer, the context summary as System One was served it,
   `state_sha256` and a `provenance` tier. `scout harness run` appends an
   outcome line tagged `executor: stub|real` with measured backends, tokens,
   latency, cost and `verified`/`verifier`.
2. **Execute for real.** `scout harness run` runs each plan node's real
   executor (`apps/scout-cli/bigbang/plugins/harness/executors/`) when its
   backend is available: deterministic (AST-whitelisted local solvers and
   allowlisted read-only `scout` commands), llm (`bigbang.core.llm`: Ollama at
   `OLLAMA_HOST` first, then Anthropic or an OpenAI-compatible API only when a
   key AND a model are set), deep_research (arXiv, Semantic Scholar with a
   key, jarvisd recall; cited answers). action_operator runs only through the
   existing fail-closed MCP path; outside-world effects (`WRITE_DESTRUCTIVE`,
   `EXTERNAL_NOTIFY`) stay default-deny and are never auto-retried (the one
   ladder, `dottie_loop.execution.recovery_ladder`). **Default
   (`DOTTIE_EXECUTORS=auto`): real when the backend is up, else the node's
   deterministic stub, tagged `stub`**; `real` fails the node instead, `stub`
   never tries (the test suites). A run is `executor: real` only when every
   node was.
3. **Probe** (`scout router probe`). Curated goals
   (`packages/dottie-loop/dottie_loop/benchmarks/router_bench_v1.jsonl`, 221
   goals with verifier specs) run through the real executors cheapest tier
   first, one tier up at a time, until the goal's automatic verifier
   (`dottie_loop.verifiers`) passes. The label is that minimal sufficient
   tier. Never past `deep_research` (no side-effecting tier is probed). An
   unreachable backend stops the goal as `unavailable` (no label);
   `--past-unavailable` records upper bounds, which the pack refuses unless
   `--allow-upper-bound`. Rows are `benchmark-verified`.
4. **Pack** (`scout router pack`). Rebuilds each record's state with the same
   `system_one_state`, refuses a drifted `state_sha256`, refuses any outcome
   not observed by real executors, applies the data policy below, and writes
   `train.jsonl`, `holdout.jsonl` (production), `holdout_benchmark.jsonl`,
   `provenance.jsonl` (with each row's weight) and `MANIFEST.json`.
5. **Train.** The orchestrator MLP router on CPU
   (`scout router train --mlp`, `dottie_loop.mlp_train`, numpy; the frozen
   schema_version-1 weights `dottie_loop.mlp_infer` serves). System One on
   the GPU host (`apps/jev-v0/train_pointer_lora.py --go`).
6. **Eval** (`scout router eval`): the gate below; `gate_passed` and
   `refusals` in `eval_summary.json`.
7. **Spot-check and stamp.** `scout router spotcheck` samples 20 labels into
   `<artifact>.spotcheck.json`; a human marks each ok/bad (at most 10% bad).
   `scout router promote --i-have-reviewed --by <name>` refuses without it:
   the only way a learned answer becomes authoritative.
8. **Serve.** The MLP via `SCOUT_ORCH_MODEL` / `hints.learned`; System One
   from dottie-os `/decide`, whose `/health` identity hash is what the stamp
   is checked against.

The host runbook is `docs/ROUTER_LABELS_RUNBOOK.md`.

## Data policy (provenance tiers)

Owner-approved 2026-09-23. Every trace line and pack row carries
`provenance` (`dottie_loop.provenance`):

| Tier | What | Weight | May |
|---|---|---|---|
| `production` | real use, real executors | 1.0 | train; the **primary** gate holdout |
| `benchmark-verified` | curated goals through real executors, outcome checked by an automatic verifier (`scout router probe`) | 0.7 | train candidates; only a disjoint, deduped benchmark holdout in eval |
| `outcome-real` | recorded futures (the separate Atlas track) | - | recognised; never a router label |
| `teacher`, `synthetic` | model- or template-made | - | never train a champion, never in gate eval |

- **Dedupe and decontamination** key on the normalised goal hash
  (`goal_norm_sha256`: NFKC, case, whitespace and punctuation folded). One row
  per (provenance, goal); a goal whose labels contradict drops. No goal that
  sits in the production holdout, the benchmark holdout or an external eval
  set (`--eval-set`) trains. The benchmark's builder refuses any goal whose
  normalised hash appears in this repo's eval sets.
- **The gate** (`dottie_loop.router_training.evaluate`) passes only when the
  pack holds at least `MIN_PRODUCTION_ROWS` production rows (50;
  `--min-production-rows`), the candidate beats the heuristic on the
  production holdout (the §24 gates), and it does not trail the heuristic on
  the benchmark holdout. Otherwise `refusals` says which failed.
- **Promotion** additionally needs the human spot-check and the stamp.

**Today (measured in the build container, 2026-09-23):** no Ollama and no LLM API key are
reachable in that container, and arXiv's API there answers only single-id
lookups (search queries get HTTP 406; `/abs` pages serve as the id fallback).
`scout router probe` over all 221 goals:

| | strict (default) | `--past-unavailable` |
|---|---|---|
| labeled (verifier passed, every cheaper tier ran) | 86, all `deterministic` | 86, all `deterministic` |
| upper-bound labels (`llm` unknown) | - | 44 `deep_research` (arXiv id lookups) |
| unavailable / no label | 135 (llm tier unreachable) | 91 (llm unreachable, then arXiv search 406) |
| heuristic tier vs label | dearer on all 86 (it routes them to `llm`) | same, plus agrees on the 44 |
| tokens / cost | 0 / $0 (no model ran) | 0 / $0 |

Pack (upper-bound run, `--allow-upper-bound`): 130 benchmark-verified rows,
0 production; 104 train, 26 in the benchmark holdout. MLP on CPU: 300
epochs, under 1 s wall. Eval: benchmark holdout tier accuracy 0.962 vs the
heuristic's 0.423 (n=26), and the gate **refused**: 0 < 50 production rows,
empty production holdout. That is the expected state; the numbers do not show
the MLP is better on real use, and upper-bound labels are only a pipeline
exercise. No `llm`-tier outcome was fabricated: those goals are recorded
unavailable.

**Place decisions (`apps/atlas-outcomes`).** A second source of real labels,
outside the router: System One records about a place on the eye.jcamd.com
Atlas (a USGS gauge, its construct stack and the NWS warnings over it) at the
end of day t, labelled by what happened next (flow on t+1 above the gauge's
p90, an NWS flood-type warning polygon over it within 24 h, the next-day
change level). Provenance tier `outcome-real`: the rows may train System One
candidates and are scored on a time-split holdout (the latest 365 days)
against the persistence and climatology baselines in
`apps/atlas-outcomes/BASELINE.json`; the same stamp rule applies. The same
state shape is what a future place `ContextProvider` would hand the decision
plane; none is wired today.

## Speed budget (measured)

Budget (warm, jarvisd): p50 decide <= 10 ms without System One, <= 150 ms with
System One on a local GPU; scout cold `route` <= 250 ms.

Measured with `dottie-loop bench decide --n 100 --cold-n 20` (also
`scout router bench`) on a 4-CPU Linux container, Python 3.11.15. Before is
the branch point of this change (`fa04d85`); after is this change. The System One rows use a
local **untrained** `serve_decide` (HTTP path only; no model runs on this box,
so the <= 150 ms GPU budget is not measured here).

| Scenario | Before p50 / p95 ms | After p50 / p95 ms |
|---|---|---|
| scout cold `route` (fresh interpreter, in-process decide) | 826.2 / 892.9 | 136.0 / 150.2 |
| `scout --help` (fresh interpreter; range of 5 runs before, 3 after) | 765-1266 | 176-208 |
| in-process `route_goal` (heuristic only) | 0.018 / 0.028 | 0.014 / 0.020 |
| in-process `decide` + run-history context | n/a | 0.612 / 0.935 |
| jarvisd warm `/api/route` (keep-alive) | 1.483 / 1.977 (no context) | 3.805 / 4.817 (now with context) |
| jarvisd warm `/api/decide`, `context: false` | n/a | 2.132 / 2.678 |
| jarvisd warm `/api/decide`, with context | n/a | 3.833 / 4.888 |
| jarvisd warm `/api/decide` + context + System One (untrained sidecar) | n/a | 5.175 / 8.311 |
| System One backend round trip (untrained sidecar) | 2.184 / 2.693 | 0.509 / 0.941 |
| run-history stats, 400 runs x 5 events, warm | 5.521 / 11.827 | 2.151 / 2.732 |

What moved the numbers: scout registers plugin commands from an entry table
and imports a plugin only when it is invoked, and `bigbang.core.mcp_client`
imports the MCP SDK on first use (`python -X importtime` put
`bigbang.core.mcp_client` at 706 ms cumulative on the old cold path, almost all
of it the `mcp` package); the System One backend caches `/health` per URL, keeps one
connection alive per thread, disables Nagle, and sends one `/decide` per route
with all four questions (the dev server speaks HTTP/1.1 and disables Nagle
too); run history is an incremental index instead of a merge over every event.
`jev-v0` scores every question of a request from one encoding of the shared
state prefix (`pointer_infer.SharedPrefixScorer`, torch-free orchestration,
tested with a fake model); its GPU latency is not measured here.

## Rules (non-negotiable)

- Nothing auto-promotes. A checkpoint is authoritative only if its artifact
  says `gate_passed: true` and a human stamped its exact bytes. Today nothing
  is stamped: the heuristic is the authority and every learned or System One
  answer is advisory, logged and displayed.
- Synthetic, teacher, test or stub-executor rows never train a champion.
  Benchmark-verified rows train candidates but never stand in for real use:
  the gate needs production rows and a production-holdout win.
  Rows whose labels are recorded futures (provenance `outcome-real`) may
  train candidates; they are evaluated on a time-split holdout.
- No new "confidence" in code or copy. System One reports
  `shape_concentration`; external probabilities are `backend_confidence`. The
  router's existing `confidence` key (a keyword-score ratio) keeps its name.
  Nothing is called "calibrated".
- The goal text leaves the process only under `DOTTIE_TRACE_TEXT=1`; the same
  switch governs private context texts.
- Tests never write the real `~/.dottie`, the real jarvisd DB or the real
  scout checkpoint store (`DOTTIE_TRACE_DIR`, `SCOUT_CHECKPOINT_BASE`,
  `SCOUT_DECIDE_REMOTE=0` in the suites' conftests).

## One copy of each thing

| Thing | The one copy | What happened to the others |
|---|---|---|
| MoMA-lite heuristic | `dottie_loop.backends` | scout's names are aliases; harness-api serves `lib/moma_lite.py`, vendored verbatim by `scripts/vendor_router.py` with a `--check` and golden parity test (Vercel packages the app alone). `lib/heuristics.py` and `lib/vector_router.py` (dormant) deleted. `dottie_loop.router.heuristic_route` is the spec's RT-03 feature router, a separate contract kept for its goldens |
| Recovery ladder | `dottie_loop.execution.recovery_ladder` | `pipeline/recovery_ladder.py` and `pipeline/checkpoint_manager.py` re-export it; scout's inline replica and `bundles/ultra/recovery-ladder.js` removed. Remaining copies: the frozen `apps/ava-factory/dottie/**` mirror (edited only through its review process) and `apps/dottie-harness-api/lib/analytics.py` (goes with the Phase 2 proxy) |
| Run-history mining | `dottie_loop.run_history` | scout's `g_history_stats` delegates to it |
| Ollama endpoint variable | `OLLAMA_HOST` (`dottie_loop.env`) | `OLLAMA_BASE`, `OLLAMA_URL`, `DOTTIE_OLLAMA_URL` accepted as deprecated aliases with a warning in scout and jarvisd. `apps/dottie` still reads `DOTTIE_OLLAMA_URL` (Phase 2 fold) |
| Agent handoff | jarvisd messages (`jarvis.send` / `jarvis.inbox`) or `scout comms` | the `HandoffEnvelope` cited in docs never existed in code; references removed |
| `harness` package name | `packages/ava-open-harness` | the unimported `src/harness` tree (a name collision) deleted |
| ACD daemon simulation | none | `apps/arxiviq/app/acd` (imported by nothing) deleted |

## Retirement and integration (owner decision, 2026-09-23)

Nothing below is deleted in Phase 1.

| Tree | Decision |
|---|---|
| `apps/bluehenre` | **Retire.** Archive out of the monorepo in Phase 2, history kept; its `bluehenre-checks` CI job goes with it |
| `apps/dottie-rlm` | **Keep and integrate.** Converge the three RLM implementations (`apps/dottie-rlm/dottie_rlm/rlm.py`, `apps/dottie/dottie/rlm.py`, `packages/dottie-loop/dottie_loop/rlm.py`) onto one |
| `apps/dottie` (agent OS) | **Keep and integrate.** Fold its useful parts (missions, research loop) into the decision plane / jarvisd; resolve the `dottie` package-name collision with `apps/ava-factory/dottie` |
| `apps/dottie-harness-api` | **Keep.** Becomes a thin proxy to jarvisd `/api/decide`, which retires its vendored heuristic and its remaining ladder copy |
| `apps/ava-factory` | Kept as is: the frozen trainer mirror (not a retirement candidate) |

## Phase 2 (in `docs/project_dag.json`)

- `decision-plane-real-executors` (**in progress**): real executors, the tier
  probe, the benchmark, provenance tiers, the production-gated eval, the
  spot-check and the CPU MLP trainer are built and tested. Open: production
  traces with every node real on the owner's host (Ollama up), then a gate
  run with 50+ production rows.
- `harness-api-jarvisd-proxy`: harness-api forwards to jarvisd `/api/decide`.
- `retire-bluehenre`: archive `apps/bluehenre` and its CI job.
- `rlm-converge`: one RLM implementation.
- `agent-os-fold`: fold `apps/dottie` missions / research loop into the
  decision plane; resolve the `dottie` package collision.
