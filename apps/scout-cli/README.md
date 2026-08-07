# Scout CLI 🐾 — One CLI to Rule All Tools (ex-BigBang) v0.8.0

> Agent-native, security-first, local-first control plane for *every* internet tool, API, and MCP server. Ava-brained + RTX offload. Now v0.7 with **herd** — a [Herdr](https://herdr.dev/)-inspired session control surface (wait/read/report) that pairs with real PTY multiplexers.

**Solo personal project, no connection to employer, built with public/free-tier only.**

Primary command: `scout` (aliases: `bb`, `bigbang`, `dv`, `kitty` for compat) — `scout --help` / `scout --json rtx status`

## What's New in v0.8.0 — Universal Harness + Vector Unification (v5 Prime SOTA)

**Thesis:** One CLI = all three worlds — Scout v3.3 harness (13 agents / 11 packs / MoMA-lite 5 tiers / GARNet G_workflow+G_history / Checkpoint 7-field / Recovery Ladder 5+4 / Pacing :13 / Verification Econ budget3 threshold8.0) + Dottie factory (closed-loop LLM one tool = scout) + dumbmodel.com vector games (4 daily + unified trunk).

- **Harness plugin** (fs true, net false, zero_deps true, no torch): `scout --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"` → intent deep_research 5-7 sources A/B/C, stickiness_guard Launched=live URL+3 users+payments/analytics Aug31 locked, routed_agents [deep-researcher,synthesist,forensic], graph_memory G_workflow+G_history GARNet MDP, tempo :13, max_concurrent_safe 4. Also `harness agents list/health/relevant`, `harness checkpoint list/show/pause/resume`, `harness memory <q> --k 5`, `harness graph-plan <goal>`, `harness ops health/dashboard`, `harness verify --score 8.2 --prev 8.0` → early_exit True delta<0.3 threshold 8.0.
- **Vector plugin** (fs true, net false): `scout --json vector train hoops --preset nano`, `scout --json vector eval hoops --gate leak-free` → Recall@10 0.977 Purity@20 0.6717 composite 0.7937 player-split not season-split (season-split Recall 1.0 mem bug fixed), `scout --json vector export`, `scout --json vector ship hub`, `scout --json vector unified ablation --configs full,no_supcon,no_coral,no_grl,no_vicreg,task_only` → G1 per-sport recall, G2 sport-invariance, G3 silhouette, G4 hit-rate random baseline, house rule does each loss earn keep.
- **Shared lib** (torch optional stub for static-site): `ResidualTower cat([x·m,m])→96h→24d skip L2-norm` 18 families hoops / 17 towers equities / 8 towers pitch / 10 families gridiron 160 feats, `TransformerFusion d_model128 4 heads 4L CLS→64-d L2-norm` (equities proven 0.7057), `normalize` era-honest per-season zscore / per-90 tournament-z / per-ticker FY, losses InfoNCE/SupCon→G3/CORAL→G3/GRL λ0.3 warmup10ep/VICReg var25 cov1 anti-collapse task w=2.0 anchor G1.
- **Security**: every plugin manifest.yaml capabilities network false filesystem true secrets false (harness/vector), audit.jsonl, vault 0600, policy.yaml default-deny, no network egress, no secrets in repo.
- **Determinism**: 1k spec, `--json` envelope ok:true, no pip installs, stdlib + optional local src/acne, tests green `pytest tests/test_harness_vector.py -v`.
- **v5 Prime honesty**: early_exit after 2, fallback visibleAbandonments, noFake7of7, zero_deps true, no torch for static-site path, provenance-honest eval_scoreboard.json 7/7/0, candidate.json honest.

## What's New in v0.7.0 — Judgment plane (above Herdr, not beside it)

**Thesis:** Most agent managers are multiplexers. **Scout is a judgment plane.**

[Herdr](https://herdr.dev/) owns panes / SSH attach / responsive TUI. Scout refuses that trap and owns what multiplexers cannot: **trust · world tools · judgment · memory · learning**.

```bash
# Differentiator cockpit
scout --json planes thesis
scout --json planes compare      # honest matrix vs herdr/tmux/apps
scout --json planes status       # Trust · World · Herd · Judgment · Memory
scout --json planes loop         # act → audit → rft → ava flywheel

# Teach Dottie-claw
scout skill teach --target dottie
scout skill show scout

# Herd ledger (not a PTY multiplexer)
scout herd start api --cmd "pytest -q"
scout --json herd wait api --status done --timeout 120

# MCP — scout_<plugin> tools
scout mcp serve
```

Read: `docs/DIFFERENTIATION.md` · `docs/FOUNDATION.md` · `bigbang/skills/scout/SKILL.md`

## What's New in v0.6.0 — Scout rename 🐾 + RTX Releases Auto-Read

- **Scout rename:** `name = "scout-cli" v0.6.0` — binary `scout` primary, `bb`/`bigbang`/`kitty`/`dv` kept as aliases. `pyproject.toml` scripts + `bigbang/cli.py` app name `scout` with invoked detection. `scout --help` shows Scout CLI personal control plane. Full pytest suite green (`pytest tests/` for the current count).
- **RTX Offload v0.6.0 wired to GitHub Releases:** new plugin commands `scout rtx releases list` (fetches `https://api.github.com/repos/jcdavis131/scout-rtx/releases`) and `scout rtx releases sync --tag v0.6.0-demo-0715` (downloads `results.tsv/jsonl` assets to local `autoresearch-rtx-custom/`). 
- **Dashboard auto-read:** `rtx-offload-dashboard` space now has `githubReleases` table + migration `0003_add_github_releases.sql`, server actions `listGithubReleases` (GH API), `syncReleaseResults` (TSV/JSONL parse + dedup by commit_sha), `getReleaseCache`, and client `releasesQuery` with `refetchInterval: 60_000`. UI section GITHUB RELEASES with SYNC GH + asset links + IMPORT → LOG button. Demo release `v0.6.0-demo-0715` published with best bpb 0.9935 (4 rows) → dashboard DB verified: 4 results, best 0.9935.
- **Hourly server cron:** `rtx-releases-hourly-sync` interval@1h—auto-fetches latest release, runs `scout rtx releases sync`, inserts missing rows into dashboard `app.db` `experiment_results`, logs to `your_files/rtx-sync-log.jsonl`. So even when browser closed, local `scout rtx results --best` stays fresh.
- **Alienware auto-publish:** `scripts/run-autonomous.ps1` now auto-publishes every 5 exps via `publish-release.ps1 -Program <prog> -Tag v0.6.0-<prog>-<MMdd-HHmm>` + final publish at loop end. Dashboard picks up in <60s. `scripts/publish-release.{ps1,sh}` creates GH release with `results.tsv` + `results.jsonl` assets.
- **Repos:** `github.com/jcdavis131/scout-cli` (this) + `github.com/jcdavis131/scout-rtx` custom fork — cross-linked via `INTEGRATION.md`. Monorepo home: `github.com/jcdavis131/dottie` (this repo at `apps/scout-cli`, scout-rtx at `apps/scout-rtx`, plus `apps/ava-factory` and `packages/personal-graphify`); standalone clones keep working.
- **Ava routing:** `ava route "offload to my RTX"` → rtx 0.95, `dashboard` command notes auto-read every 60s.

### Personal Graphify (baked in)

```bash
# Requires: uv tool install -e ~/personal-graphify
scout graphify status
scout graphify query "how does Scout connect to Ava?"
scout graphify path "Scout CLI" "Ava AGI Factory v6.4"
scout graphify task "wire Scout to Ava J-space"
scout graphify ecosystem                  # multi-root personal brain rebuild
```

See `docs/llm-wiki/graphify-integration.md`.

### v0.6.0 Flow (end-to-end)

```bash
# Cloud → Local offload (Hatch)
scout rtx status                          # queue_pending, best 0.9935, 4 programs
scout rtx queue add --task "optimize Ava router entropy 0.7" --program programs/program-ava.md
scout rtx queue list

# On Alienware Windows
.\scripts\setup-win.ps1 -Program programs\program-ava.md -Tag scout-ava
.\scripts\run-autonomous.ps1 -Program programs\program-ava.md -Tag scout-ava -MaxExperiments 20
# every 5 exps: auto gh release create v0.6.0-ava-MMdd-HHmm results.tsv + results.jsonl
# final: publish-release.ps1

# Back in Hatch / anywhere
scout --json rtx releases list             # shows v0.6.0-demo-0715 with download URLs
scout --json rtx releases sync --tag v0.6.0-demo-0715  # downloads to autoresearch-rtx-custom/
scout --json rtx results --best           # best 0.9935

# Dashboard
scout rtx dashboard                       # opens rtx-offload-dashboard
# In dashboard: GITHUB RELEASES section SYNC GH -> IMPORT → LOG -> bestOverall updates to 0.9935
# Hourly cron rtx-releases-hourly-sync keeps DB fresh even when UI closed
```



> Agent-native, security-first, local-first control plane for *every* internet tool, API, and MCP server. Ava-brained. Now v0.5 with Authentic Generators + Passive Lab.

**Solo personal project, no connection to employer, built with public/free-tier only. No personal finance.**

## What's New in v0.5 — Authentic Generators + Passive Lab + Brain (Ava Co-Dev Plane)

- **Write Plugin v0.5 ✍️** — research-grounded AI slop detector (ai-slop-detect 70+, slop-radar 245 buzzwords, slop-cop 36 rules, CMU PNAS 2025 participial 2-5x, arXiv 2509.19163). `scan`/`check` BEFORE STRONG_AI 100 → AFTER HUMAN_LIKE 0 via deterministic fix (em-dash, buzzword strip, participial comma strip x2). `generate` always HUMAN_LIKE 0 with real citations, `batch` scans dir, `hook --install` adds pre-commit guard. Ollama fast path 0.8s + 6s chat (trust_env=False) — no 25s hang.
- **Lab Plugin 🧪** — Passive Lab top10 (Turnover Shield $79-$149/mo), `shield` MVP status, `mrr` logs to `projects/first-1k-mo-passive/files/mrr.jsonl` for First $1k/mo goal, `pitch` generates HUMAN_LIKE founder pitch scanned by write plugin.
- **Brain Plugin 🧠** — Hatch MEMORY.md + daily notes + goals bridge for Ava. `memory`, `goals`, `goal <slug>`, `sync` token-efficient snapshot for LLM-wiki ingestion, `daily` append.
- **Ava & Agent Routing Upgraded** — `ava route "check slop"` → write 0.93, `"mrr"` → lab 0.91, `"brain sync"` → brain 0.90. `agent run` builtin_hints includes write/lab/brain.
- **Tests**: write scan/humanize 0, generate HUMAN_LIKE, lab ideas, ava routes, manifest existence for write/lab/brain.

## Vision: Why One CLI?

You have 100+ tools across the internet: GitHub, Notion, Linear, Stripe, Vector MTNNs (12,966 Hoops), Ava Factory v6.4, Tennis DINOv3, Family Brain, etc.

Every agent rewrites the same glue: auth, secrets, parsing, retries. MCP helps but you still need a router.

**BigBang fixes it — bb becomes the universal router:**

```
Any Internet Tool → bb adapter → standardized `bb <tool> <action> --json` + MCP tool
                                                        ↕
                                              Ava (local brain, router)
```

```bash
# Add any tool in 5 seconds
bb tools add github --type openapi --url https://api.github.com/openapi.json
bb tools add notion --type mcp --url https://mcp.notion.com/sse
bb auth login github                              # vaulted, never in repo
bb tools list                                     # universal registry

# Use them — human or agent
bb github list-prs --repo jcdavis131/bigbang-cli
bb notion search "Vector Hoops roadmap"

# Agent-native
bb --json tools list | jq .
bb agent run "summarize my GitHub PRs and check Vector Hoops build"
# → Ava plans: [bb github list-prs, bb vector list, bb vector verify] with policy checks

# MCP — expose BigBang itself as one MCP server to Claude/Cursor/Hatch
bb mcp manifest
bb mcp serve                 # real MCP server over stdio (default) — one bb_<plugin> tool per plugin
bb mcp serve --sse --port 8787   # or SSE/HTTP at http://localhost:8787/sse
# Claude Desktop (stdio config):
# {"mcpServers": {"scout": {"command": "scout", "args": ["mcp", "serve"]}}}
```

## Security First — by Design

Every command audited. Every secret vaulted. Every plugin capability-declared.

| Layer | How |
|-------|-----|
| **Vault** | `bb secrets set GITHUB_TOKEN xxx` → file store `~/.local/share/bigbang/secrets.json` (0600); reads also check OS keyring (read-fallback, no keyring writes) and env `BB_SECRET_GITHUB_TOKEN`. Audited without value |
| **Policy** | Each plugin/tool has `manifest.yaml` with `capabilities.network.domains`, `filesystem.write`, `secrets.allow`. Default deny. Checked before exec |
| **Audit** | Every invocation → `~/.local/share/bigbang/audit.jsonl` (ts, command, args hash, duration) |
| **Isolation** | OpenAPI/MCP calls → httpx with domain allowlist + persisted user allowlist (`~/.config/bigbang/policy.yaml`, default-deny). Docker-container and isolated-venv execution are Roadmap (v0.6.0), not current |
| **Supply** | pinned deps, egg-info scrubbed, no secrets in repo, `git secrets` ready |

```bash
bb system doctor       # checks vault 0600, audit log, registry, ollama, etc
bb system audit        # tail last 20 audited events
bb system policy       # show all manifests + caps
bb secrets list        # keys only, values never listed
```

## Architecture: Sovereign Control Plane

```
bb (Typer root — --json global, dual rich+json)
 ├── core/
 │   ├── security.py   Vault: keyring + file 0600 + env fallback
 │   ├── policy.py     Capability engine: manifest.yaml → allow/deny
 │   ├── audit.py      JSONL audit trail
 │   ├── registry.py   Universal tool registry ~/.local/share/bigbang/registry.json
 │   ├── discovery.py  OpenAPI fetch, MCP discovery
 │   ├── plugin_loader.py  Scans plugins/*/manifest.yaml + cli.py
 │   └── output.py     emits valid JSON when --json, else rich, always audited
 ├── plugins/ (auto-discovered, each is an MCP tool)
 │   ├── secrets/ 🔐 set/get/list/rm (vault)
 │   ├── auth/ 🔑 login/list/set-token (unified OAuth/API key)
 │   ├── tools/ 🧰 Universal registry: add/list/get/rm/search/call/import-openapi
 │   ├── mcp/ 🌐 Client for any MCP server (add/list/list-tools/call) + serve bb as MCP
 │   ├── agent/ 🤖 Ava-native planner: NL → plan → tool calls with policy checks (now write/lab/brain hints)
 │   ├── ava/ 🧠 Factory: status/train/eval/route — brain of BigBang (v0.5 routes write/lab/brain 0.9+)
 │   ├── write/ ✍️ Authentic writing: scan/humanize/generate/sources/check/batch/hook — HUMAN_LIKE 0
 │   ├── lab/ 🧪 Passive Lab — Turnover Shield $79-$149/mo, MRR tracking, pitch
 │   ├── brain/ 🧠 Hatch brain — goals, MEMORY.md, daily notes for Ava co-dev
 │   ├── system/ 🖥️ doctor/audit/policy/scaffold (with manifest.yaml)
 │   ├── family/  Family Brain generic
 │   ├── vector/  MTNN control (12,966 Hoops)
 │   ├── tennis/  DINOv3 serve coach
 └── config/default.yaml  Local-first paths, no finance
```

Growth loop (continuous):
1. You do something 3x → audit log shows pattern
2. `bb agent bus` proposes: `bb system scaffold <name>` with manifest.yaml caps
3. Ava judges if safe/useful via Frontier rubric (11 cats)
4. Drop folder = new `bb <name>` command = instantly new `bb_<name>` MCP tool — no restart

## Install

```bash
git clone https://github.com/jcdavis131/bigbang-cli
cd bigbang-cli
pip install -e ".[all]" --break-system-packages
bb --help
bb system doctor
```

## Quickstart — Rule The Internet

```bash
# 1. Secure your secrets (never in repo)
bb secrets set GITHUB_TOKEN ghp_xxx
bb secrets set OPENAI_API_KEY sk-xxx
bb secrets list

# 2. Register any tool
bb tools add stripe --type openapi --url https://api.stripe.com/openapi.json --tags api,payments
bb tools add my-mcp --type mcp --url http://localhost:3000/sse
bb mcp add notion https://mcp.notion.com/sse

# 3. Discover & use
bb tools list
bb tools search github
bb mcp manifest | jq .tools

# 4. Agent does the work (Ava-routed)
bb agent run "check Vector Hoops build status and list open GitHub PRs"
bb --json agent run "summarize Family Brain" | jq .plan

# 5. Serve yourself as MCP to Claude/Cursor
bb mcp serve                       # stdio (default, Claude Desktop-ready)
bb mcp serve --sse --port 8787     # or SSE at http://localhost:8787/sse
# Claude Desktop config (stdio):
# {"mcpServers": {"scout": {"command": "scout", "args": ["mcp", "serve"]}}}

# 6. Audit & policy
bb system audit --n 20
bb system policy
```

## Ava Ecosystem Expansion

Ava is the brain:

- **Router**: `bb ava route "translate README"` → picks best tool from registry, confidence scored
- **Judge**: When `bb agent bus` proposes new automation, Ava evaluates via Frontier rubric (Financial Accuracy → Tool Accuracy, etc, 11 cats, 22k rubrics inspiration)
- **Trainer**: `bb ava train --smoke` → Docker CUDA YaRN 10k→1M, WSD, Ollama qwen3:32b judges
- **Memory**: Future — vector store of all `audit.jsonl` + tool uses for lifelong learning

```bash
bb ava status
bb ava train --smoke --steps 1000
bb ava eval --frontier
bb ava route "rebuild vector hoops leakfree"
```

## Adding a New Plugin (30 sec)

```bash
bb system scaffold mytool
# creates bigbang/plugins/mytool/{cli.py, manifest.yaml}
# edit manifest.yaml to declare caps:
# capabilities:
#   network: {enabled: true, domains: [api.mytool.com]}
#   filesystem: {write: false}
#   secrets: {allow: [MYTOOL_TOKEN]}

# edit cli.py
bb mytool hello --json
# → instantly in `bb --help` and `bb mcp manifest` as bb_mytool
```

## Roadmap

- v0.2.0 ✅ Remove finance, generic tools only
- v0.3.0 ✅ Security foundation: vault 0600+keyring, policy caps via manifest.yaml, audit jsonl, universal tool registry, MCP client+server, Ava router stub
- v0.4.0 ✅ Real MCP SDK client (mcp Python), OpenAPI codegen, Google Tasks wired, LLM-wiki + graphify, Ollama qwen3:32b routing
- v0.5.0 ✅ Authentic Generators v0.5: write scan/humanize/generate HUMAN_LIKE 0 + batch + pre-commit hook, lab MRR tracking, brain goals/memory bridge, Ava routes write/lab/brain 0.9+
- v0.6.0 🔜 Docker isolation for tools, pipx venv isolation, age encryption for vault, Sigstore signing for plugins, Ava vector memory over audit.log
- v0.7.0 🔜 Tailscale tunnel to expose bb MCP to iOS/Android, background bus as Hatch heartbeat, bb lab auto-pitch via Frontier rubric

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Security first, local-first, free to host. MIT.

## What's New in v0.8 — Harness as a CLI surface (Scout v3.3 → scout-cli)

**Thesis:** Until now Scout's harness lived only in `workspace/bundles/`. Dottie, vector-hub, and any other harness each rewrote the same router / checkpoint / verification. **scout-cli v0.8 collapses 12 entrypoints into one.**

```bash
# Single-source CLI — any harness can call it
~/workspace/bundles/cli.sh --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"
# → MoMA-lite 5 tiers deterministic cheap / llm medium / deep_research heavy 9K /
#    action_operator medium-verify / agentic_epic 13-swarm checkpointed
# → intent deep_research 0.96, routed 3 agents, graph_memory G_workflow+G_history+GARNet, stickiness PASS

~/workspace/bundles/cli.sh --json vector eval hoops
# → Recall@10 0.977 Purity@20 0.6717 composite 0.7937 leak-free player-split

~/workspace/bundles/cli.sh --json vector unified ablation
# → house rule Δ G1/G2/G3/G4 — does each loss earn keep?

# Direct python (same entry)
python3 -m bigbang.cli --json harness route "heartbeat tick"
python3 -m bigbang.cli --json vector train --game equities --preset nano
```

### Scout v3.3 Integration

- **MoMA-lite 5 tiers** — `bundles/router/router.ultra.js` ported to `bigbang/plugins/harness/cli.py`:
  `deterministic` (heartbeat/monitor cheap no LLM), `llm` (medium), `deep_research` (heavy 9K 5-7 sources A/B/C), `action_operator` (medium-verify tool-chain), `agentic_epic` (checkpointed 13-swarm). Cost-performance optimal before full LLM call.

- **GARNet-style Graph Memory** — `G_workflow` current DAG live in checkpoint + `G_history` past runs timeline.jsonl patterns/failures → `garnet` picks (role,LLM) per MDP MoMA profiles caps. `graph_memory` in every route output.

- **Stickiness Guard** — Stripe vs Lemon Squeezy Aug 2026 must recall `Launched = live URL + 3 users + payments/analytics by Aug31 11:59pm CT` without re-asking, sources min5 graded A/B/C freshness Aug2026, forbidden re-asking Launched def. `must_recall` PASS enforced in `intent_scores`/`stickiness_guard.passed`.

- **Checkpoint Manager** — `bundles/ultra/checkpoint-manager.js` LangGraph pause/resume days later `bundles/ultra/runs/<runId>/checkpoint.json` required fields `nodeId/agentId/attempt/latency/tokens/status/errorClass`. 60-epoch unified job can pause days and resume. Verified via `checkpoint list/show`.

- **Bounded Recovery Ladder** — `bundles/ultra/recovery-ladder.js` FailureTaxonomy 5 `INPUT_CORRUPTION/CONTEXT_STARVATION/TOOL_FAILURE/REASONING_COLLAPSE/OUTPUT_CORRUPTION` + SideEffect 4 `READ/WRITE_IDEMPOTENT/WRITE_DESTRUCTIVE/EXTERNAL_NOTIFY` + ladder `retry1→patch→replan→escalate`. Cannot skip levels. 28→315 features via enriched schedule binary gate rather than shipping coin-flip map.

- **Pacing Filter** — `bundles/ultra/communication-pacing.js` HandoffEnvelope 7 required + ScoutCommsBus sub-swarm + `max3 parallel / max4 concurrent safe`, `tempo :13 Never :00` timing over speed, sub-swarm 3-5 medium 13 only epic. CrewAI >5-6 noisy needs filtering.

- **Verification Economics** — `bundles/ultra/verification-economics.js` CriticEconomics `budget3 threshold8.0 earlyExit delta<0.3` + EvalHooks6 `correctness/reliability/coherence/tool_failures/hallucination/comms_quality` + SuggestibilityGuard best vs worst critique + PECHamsterWheelGuard `Memory is difference iteration→improvement` episodic/semantic/working 1500 chars immediate lattice write BLOCKED. Stops `pos_drop 0.0` mask-as-index bug via shuffled null 0.5493.

- **Dumbmodel.com Vector Hub** — `vector train/eval/export/ship/difficulty/unified` commands unify 6 models 4 daily games 20,719 player-seasons x64-d joint trunk ablation 30ep warmup5 Stage1 v0 frozen encoders non-destructive, G1 per-sport pos non-inf pos_drop/pos_baseline, G2 sport-invariance target ≤0.7258 (0.6258+0.10) majority baseline, G3 archetype silhouette 0.683 within-arch x-sport 0.746 >> between -0.121 sep 0.867, G4 cross-sport NN 0.9828 random 0.1712 +0.8116 lift curated 40 triples top-10 0.000 mean rank 2114 vs random 2067 ratio 0.978. All in `assets/data/scout_cli.json` provenance-honest.

- **Dashboard** — single slug `scout-ops-always-on-2` client-only no secrets DOM, coffee steam + wave hover, sparkle on 8/8 core lit (OODA 4/4 agentic 6/6 MoMA 5 tiers Graph 2 pacing :13 checkpoint).

### Test surface

```bash
pytest tests/test_harness_vector.py -q   # 9 tests — harness route stickiness, verify econ, agents, vector eval/train/ship/unified, shared lib, cli.sh wrapper
```

`bundles/cli.sh` ensures any hatch harness can call `scout` as single source without knowing pip/virtualenv details — it sets `PYTHONPATH` to `~/workspace/dottie/apps/scout-cli` and execs `python -m bigbang.cli`.

