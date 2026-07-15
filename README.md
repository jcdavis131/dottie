# BigBang CLI — One CLI to Rule All Tools

> Agent-native, security-first, local-first control plane for *every* internet tool, API, and MCP server. Ava-brained. Now v0.5 with Authentic Generators + Passive Lab.

**Solo personal project, no connection to employer, built with public/free-tier only. No personal finance.**

## What's New in v0.5 — Authentic Generators + Passive Lab + Brain (Ava Co-Dev Plane)

- **Write Plugin v0.5 ✍️** — research-grounded AI slop detector (ai-slop-detect 70+, slop-radar 245 buzzwords, slop-cop 36 rules, CMU PNAS 2025 participial 2-5x, arXiv 2509.19163). `scan`/`check` BEFORE STRONG_AI 100 → AFTER HUMAN_LIKE 0 via deterministic fix (em-dash, buzzword strip, participial comma strip x2). `generate` always HUMAN_LIKE 0 with real citations, `batch` scans dir, `hook --install` adds pre-commit guard. Ollama fast path 0.8s + 6s chat (trust_env=False) — no 25s hang.
- **Lab Plugin 🧪** — Passive Lab top10 (Turnover Shield $79-$149/mo), `shield` MVP status, `mrr` logs to `projects/first-1k-mo-passive/files/mrr.jsonl` for First $1k/mo goal, `pitch` generates HUMAN_LIKE founder pitch scanned by write plugin.
- **Brain Plugin 🧠** — Hatch MEMORY.md + daily notes + goals bridge for Ava. `memory`, `goals`, `goal <slug>`, `sync` token-efficient snapshot for LLM-wiki ingestion, `daily` append.
- **Ava & Agent Routing Upgraded** — `ava route "check slop"` → write 0.93, `"mrr"` → lab 0.91, `"brain sync"` → brain 0.90. `agent run` builtin_hints includes write/lab/brain. Tests 14 passing.
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
bb mcp serve --port 8787 --transport sse
# Add to Claude Desktop as http://localhost:8787/sse => instant access to bb_*
```

## Security First — by Design

Every command audited. Every secret vaulted. Every plugin capability-declared.

| Layer | How |
|-------|-----|
| **Vault** | `bb secrets set GITHUB_TOKEN xxx` → OS keyring + `~/.local/share/bigbang/secrets.json` (0600) + audit without value. Env fallback `BB_SECRET_GITHUB_TOKEN` |
| **Policy** | Each plugin/tool has `manifest.yaml` with `capabilities.network.domains`, `filesystem.write`, `secrets.allow`. Default deny. Checked before exec |
| **Audit** | Every invocation → `~/.local/share/bigbang/audit.jsonl` (ts, command, args hash, duration) |
| **Isolation** | Tools run via registry with restricted env. Docker tools → container. Python tools → isolated venv. OpenAPI → httpx with domain allowlist |
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
bb mcp serve --port 8787
# In Claude Desktop config:
# { "mcpServers": { "bigbang": {"url": "http://localhost:8787/sse"}}}

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
- v0.5.0 ✅ Authentic Generators v0.5: write scan/humanize/generate HUMAN_LIKE 0 + batch + pre-commit hook, lab MRR tracking, brain goals/memory bridge, Ava routes write/lab/brain 0.9+, 14 tests passing
- v0.6.0 🔜 Docker isolation for tools, pipx venv isolation, age encryption for vault, Sigstore signing for plugins, Ava vector memory over audit.log
- v0.7.0 🔜 Tailscale tunnel to expose bb MCP to iOS/Android, background bus as Hatch heartbeat, bb lab auto-pitch via Frontier rubric

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Security first, local-first, free to host. MIT.
