# BigBang CLI — Agent & Tools Control Plane

> One CLI to orchestrate all your agents, tools, and services. Local-first, agent-native, continuously growing.

Solo personal project, no connection to employer, built with public/free-tier only.

## Why this exists

You have Family Brain, Life Admin Brain, 3 Vector MTNNs (12,966 Hoops), Ava AGI Factory v6.4, Tennis DINOv3, Passive Lab, plus growing tools. Agents kept rewriting glue. No unified surface for tools/services.

BigBang fixes it — strictly for agents/tools/services (no personal finance):

```bash
bb doctor
bb family brain
bb vector list
bb vector hoops --daily --leakfree
bb ava status
bb tennis serve --video serve.mp4
bb agent run "rebuild vector hoops with leakfree split"
bb mcp manifest
bb --json vector list | jq .
```

## Install

```bash
git clone https://github.com/jcdavis131/bigbang-cli
cd bigbang-cli
pip install -e ".[all]" --break-system-packages
# or: uv pip install -e .
bb --help
bb doctor
```

## Plugins (auto-discovered)

- `family` — Davis Family Brain shareable + Life Admin Brain (10 tables: tasks, docs, bills, etc)
- `vector` — Hoops/Pitch/Gridiron MTNN control, dumbmodel.com — leakfree rebuilds, Guess The Player mode
- `tennis` — DINOv3 serve coach, ExecuTorch ConvNeXt-Tiny 2MB ONNX WASM
- `ava` — Ava Factory v6.4 Docker CUDA, Frontier rubric 11 cats, Ollama judges qwen3:32b
- `system` — doctor, scaffold, update — `bb system scaffold <name>` creates new tool instantly
- `agent` — natural language -> bb tool selection + event bus for recurring workflows
- `mcp` — expose every command as MCP tool for Claude/Cursor/Hatch agents

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
bb --json vector list
bb --json ava status
bb --json family bills
```

MCP server:

```bash
bb mcp manifest  # list tools as JSON
bb mcp serve --port 8787
# add to Claude Desktop / Cursor / Hatch as MCP server http://localhost:8787
```

## Architecture

```
bb (Typer)
 ├── core/
 │   ├── context.py      # generic settings, MEMORY.md existence check
 │   ├── plugin_loader.py# auto-discovers bigbang/plugins/*/cli.py
 │   └── output.py       # dual rich + --json contract (no ANSI in --json)
 ├── plugins/
 │   ├── family/         # family brain + life admin
 │   ├── vector/         # MTNN control
 │   ├── tennis/         # DINOv3 serve coach
 │   ├── ava/            # AGI factory
 │   ├── system/         # doctor + scaffold
 │   ├── agent/          # NL -> tools
 │   └── mcp/            # manifest + serve
 ├── skills/             # markdown skills -> bb skill run <name>
 └── config/default.yaml # local-first paths, no finance
```

Growth loop:
1. You or agent notices repeated workflow
2. `bb system scaffold <name>` → scaffold folder + test
3. Implement with public/free-tier only
4. Nightly Hatch heartbeat proposes new skills from recurring patterns

## Production touches

- `pyproject.toml` setuptools, `bb` + `bigbang` entrypoints, `tools` manifest auto-discovery
- `.github/workflows/ci.yml` ruff + pytest
- `.gitignore` venv/build/cache
- `docs/ARCHITECTURE.md` + `docs/EXTENDING.md`
- `examples/quickstart.sh`
- Tests `tests/test_cli.py`
- Dual output: rich for humans, valid JSON for agents (--json only JSON)
- Isolation: HOME only, never touches 03_Meta_Work_ISOLATED, disclaimer footer

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. Strictly agents/tools/services — no personal finance. Free to build/host/serve.

MIT
