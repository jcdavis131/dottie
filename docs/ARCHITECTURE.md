# Architecture

## Goal
BigBang CLI is the **single control plane** for Cameron's personal life OS.

Design goals:
- **Agent-native**: every command emits `--json` and is exposed via MCP server (`bb mcp serve`)
- **Local-first**: no work systems, no Vercel/Bluehen, free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM)
- **Continuously growing**: plugin discovery via `bigbang/plugins/*/cli.py`, `app.add_typer`
- **Context-aware**: reads MEMORY.md, Plaid snapshot cache, Gmail receipts (via Hatch), Drive personal doc IDs

## Plugin spec
Each plugin folder must contain `cli.py` with:

```python
import typer
app = typer.Typer(name="mything", ...)
@app.command("foo")
def foo(): ...
def register(root): root.add_typer(app, name="mything")
```

Auto-loaded by `bigbang/core/plugin_loader.py` scanning `bigbang/plugins/`.

## Growth mechanism

1. `bb system scaffold <name>` → creates folder + starter `cli.py` + test stub
2. Drop a markdown skill in `bigbang/skills/<name>.md` → becomes `bb skill run <name>`
3. Hatch Heartbeat + Ideation loops can propose new plugins from recurring patterns → promotes to `~/skills/` then to repo

## Output contract for agents

- Human: rich tables, color Okabe-Ito
- Agent: `bb <cmd> --json` → `{"ok": true, "data": ...}` valid JSON, no ANSI
- MCP: wraps same functions, JSON schema from Typer annotations

## Isolation

- HOME only — never reads `03_Meta_Work_ISOLATED`
- Every artifact footer: "Solo personal project, no connection to employer, built with public/free-tier only"
- Fidelity → manual Mon 9am CT, never Plaid pull (AGENTS.md rule)

## Roadmap for BigBang

- Phase 0: core + finance + system + doctor
- Phase 1: family brain integration (10 tables) + bills checker
- Phase 2: vector hoops/pitch full rebuild commands + verify_accuracy.py
- Phase 3: Ava factory docker orchestration + Ollama judge switcher
- Phase 4: tennis DINOv3 + ExecuTorch export, 2MB model
- Phase 5: passive lab SaaS turnover shield CLI hooks
