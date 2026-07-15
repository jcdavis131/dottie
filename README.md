# BigBang CLI — Your Personal Control Plane

> One CLI to run your whole life. Local-first, agent-native, continuously expanding.

Solo personal project, no connection to employer, built with public/free-tier only.

## Why this exists

You have 5 finance sources, Family Brain, Life Admin Brain (10 tables), 3 Vector MTNNs (12,966 Hoops seasons), Ava AGI Factory v6.4, Tennis DINOv3, Passive Lab SaaS. No unified tool layer. Agents rewrite same glue.

BigBang fixes it:

```bash
bb finance snapshot --net
bb family bills --due-this-week
bb vector hoops --daily
bb ava status
bb agent run "cut tax drag on emergency fund"
bb --json finance snapshot | jq .net_after_cc
```

## Install

```bash
git clone https://github.com/jcdavis131/bigbang-cli
cd bigbang-cli
pip install -e ".[all]" --break-system-packages
# or uv pip install -e .
bb --help
bb doctor
```

## Plugins (auto-discovered)

- `finance` — Betterment $371k / USAA $66k / Schwab $536k / Fidelity $1.27M manual Mon 9am CT only / burn $11k / EF $136.5k
- `family` — Davis Family Brain shareable + Life Admin Brain (10 tables: roth, bills, insurance, RSU 444 @ $615)
- `vector` — Hoops/Pitch/Gridiron MTNN control, Guess The Player pivot, dumbmodel.com
- `tennis` — DINOv3 serve coach, ExecuTorch ConvNeXt-Tiny 2MB ONNX WASM
- `ava` — Ava Factory v6.4 Docker CUDA, Frontier rubric 11 cats, Ollama judges
- `system` — doctor, scaffold, update
- `agent` — natural language -> bb tool selection
- `mcp` — expose every command as MCP tool

Add a new one:
```bash
bb system scaffold shopping
# edit bigbang/plugins/shopping/cli.py
bb shopping hello
# instantly appears, instantly an MCP tool
```

## Agent-native

Every command supports `--json`:

```bash
bb --json finance snapshot
bb --json vector list
bb --json ava status
```

MCP server:

```bash
bb mcp manifest  # list tools
bb mcp serve --port 8787
# add to Claude Desktop / Cursor / Hatch as MCP server http://localhost:8787
```

Agents call structured tools without parsing rich tables.

## Architecture

```
bb (Typer)
 ├── core/
 │   ├── context.py      # MEMORY.md, settings (burn $11k, EF target $66k, fed 37%)
 │   ├── plugin_loader.py# auto-discovers bigbang/plugins/*/cli.py
 │   └── output.py       # dual rich + --json
 ├── plugins/
 │   ├── finance/        # snapshot, emergency-tax-lift (your PDF)
 │   ├── family/
 │   ├── vector/
 │   ├── tennis/
 │   ├── ava/
 │   ├── system/
 │   ├── agent/
 │   └── mcp/
 ├── skills/             # markdown -> bb skill run <name>
 └── config/default.yaml # local-first paths
```

Growth loop:
1. You or agent notices repeated workflow
2. `bb system scaffold <name>` → scaffold folder + test
3. Implement with public/free-tier only
4. Nightly Hatch heartbeat proposes new skills from recurring patterns

## Production-grade touches

- `pyproject.toml` setuptools, `bb` + `bigbang` entrypoints
- `.github/workflows/ci.yml` ruff + pytest
- `.gitignore` venv/build/cache
- `docs/ARCHITECTURE.md` + `docs/EXTENDING.md`
- `examples/quickstart.sh`
- Tests `tests/test_cli.py`
- Dual output contract (rich for humans, JSON for agents)
- Isolation: HOME only, never touches 03_Meta_Work_ISOLATED, every artifact footer disclaimer

## Roadmap

- v0.1 ✅ core + finance + family + vector + tennis + ava + system + agent + mcp
- v0.2 Family Brain sync + bills duplicate detector (Rocket Money 550 alerts replacement)
- v0.3 Vector verify_accuracy.py + league rebuild CLI
- v0.4 Ava docker-compose wrapper + smoke->nano->base gate
- v0.5 Tennis DINOv3 WASM export + on-device inference
- v0.6 Tunnel MCP to iOS/Android via Tailscale

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Fidelity manual screenshot Mon 9am CT, never Plaid. Free to build/host/serve.

MIT
