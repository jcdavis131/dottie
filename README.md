# BigBang CLI — Your Personal Control Plane

> One CLI to run your whole life. Local-first, agent-native, continuously expanding.

Solo personal project, no connection to employer, built with public/free-tier only.

## Why this makes sense

You already have:
- **5 finance sources** (Betterment/Charmed? actually Betterment + Schwab + USAA + Chase + Capital One + Fidelity manual) → $2.5M net, $11k burn
- **Family OS** (Davis Family Brain, Life Admin Brain — 10 tables, bills, Roth tracker)
- **3 Vector MTNNs** (Hoops/Pitch/Gridiron — 12,966 seasons, dumbmodel.com)
- **Ava AGI Factory v6.4** (local CUDA Docker, Frontier rubric)
- **Tennis DINOv3** serve coach
- **10 boring B2B SaaS ideas** in Passive Lab

Each has its own scripts, spaces, and hacks. Agents can't reuse them efficiently because there's no unified tool layer. **BigBang CLI fixes that.**

```
bb finance snapshot --net
bb family bills --due-this-week
bb vector hoops sync --verify
bb ava train --smoke --offline
bb tennis serve analyze ./serve.mp4
bb agent run "cut tax drag on emergency fund"
```

One surface, infinite growth.

## Install

```bash
git clone https://github.com/jcdavis131/bigbang-cli
cd bigbang-cli
pip install -e ".[all]"

# or with uv
uv pip install -e ".[all]"

bb --help
bb doctor
```

## Core Principles

1. **Local-first, free-tier only** — ONNX WASM, Supabase/R2/Workers free, public pip, manual CSV bridge. No work IP.
2. **Agent-native** — every command → `bb <cmd> --json` structured output, MCP server auto-exposed.
3. **Continuously growing** — `bigbang/plugins/` auto-discovers; drop a folder, it becomes a command.
4. **Context-aware** — reads `~/memory/` + `MEMORY.md` + Plaid read-only + Gmail (receipts) + Drive personal.
5. **Sunni-ready polish** — Okabe-Ito, AAA contrast, 18px/1.65 for any UI it emits.

## Quickstart

```bash
bb doctor              # verify local env, tools, free tiers
bb finance snapshot    # vested $2.248M + RSU $273k, burn, EF 206%
bb family brain open   # opens Davis Family Brain
bb vector list         # hoops/pitch/gridiron status
bb ava status          # docker + ollama + wandb offline
bb skill list          # show all auto-discovered skills
bb mcp serve           # expose as MCP for Claude/Cursor
```

## Architecture

```
bb (typer)
├── core/
│   ├── context.py      # loads MEMORY.md, Plaid snapshot cache, config
│   ├── plugin_loader.py# discovers bigbang/plugins/*/*.py via entrypoints
│   ├── output.py       # rich + --json dual output
│   └── bus.py          # event bus for crons/hooks
├── plugins/
│   ├── finance/        # Betterment/Schwab/USAA/Chase/Fidelity manual
│   ├── family/         # bills, roth, insurance, cash_routes
│   ├── vector/         # hoops/pitch/gridiron sync + rebuild
│   ├── tennis/         # DINOv3 serve + line judge
│   ├── ava/            # data gather, train, eval, frontier rubric
│   └── system/         # doctor, update, shell completions
├── mcp/                # MCP server wrapping every command as tool
└── skills/             # MD files that become `bb skill run <name>`
```

Growth loop:
1. You (or agent) runs `bb new plugin <name>` → scaffolds folder + tests + docs
2. Adds YAML in `bigbang/skills/` → instantly `bb skill run x`
3. Nightly heartbeat can propose new skills from recurring workflows (skill_review loop)

## MCP — Use from any agent

```bash
bb mcp serve --port 8787
# In Claude Desktop / Cursor / Hatch:
# add MCP server http://localhost:8787
```

Every Typer command auto-becomes an MCP tool with JSON schema.

## Examples

```bash
# Finance
bb finance snapshot --json | jq .net_worth
bb finance roth room --year 2026
bb finance tax-loss --check-wash META

# Family
bb family bills check --duplicate
bb family brain sync

# Vector
bb vector hoops daily --date 2026-07-15 --mode guess
bb vector pitch rebuild --quick

# Ava
bb ava data gather --shard finance --size 10M
bb ava eval frontier --judge ollama:qwen3:32b

# System
bb doctor
bb update
bb skill new "emergency fund tax lift watcher"
```

## Roadmap

- [ ] v0.1 — core + finance + system + MCP
- [ ] v0.2 — family + vector + ava plugins
- [ ] v0.3 — tennis DINOv3 + ExecuTorch export
- [ ] v0.4 — auto skill curation from Hatch loops
- [ ] v0.5 — iOS/Android companion via bb mcp tunnel

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Free to build/host/serve. Fidelity manual screenshot Mon 9am CT only.

MIT License.
