# Architecture

## Goal
BigBang CLI is the control plane for agents, tools, and services — local-first, agent-native.

Design goals:
- **Agent-native**: every command emits `--json` and is exposed via MCP server (`bb mcp serve`)
- **Local-first**: free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM)
- **Continuously growing**: plugin discovery via `bigbang/plugins/*/cli.py`
- **Context-aware**: generic tool paths, Ollama local

## Plugin spec
Each plugin folder must contain `cli.py`:
```python
import typer
app = typer.Typer(name="mything", ...)
@app.command("foo")
def foo(): ...
def register(root): root.add_typer(app, name="mything")
```
Auto-loaded by `bigbang/core/plugin_loader.py`.

## Growth mechanism
1. `bb system scaffold <name>` → creates folder + starter cli
2. Drop markdown skill in `bigbang/skills/<name>.md`
3. Hatch heartbeat proposes new plugins from recurring patterns

## Output contract
- Human: rich tables
- Agent: `bb <cmd> --json` → valid JSON, no ANSI
- MCP: JSON schema from Typer annotations

## Isolation
- HOME only — never reads work isolated paths
- Strictly agents/tools/services — no personal data categories
- Every artifact: "Solo personal project, no connection to employer, built with public/free-tier only"
