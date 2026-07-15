# Extending BigBang CLI

## Add a new plugin in 30 seconds

```bash
bb system scaffold mynewthing
# edits bigbang/plugins/mynewthing/cli.py
python3 -m bigbang.cli mynewthing hello
```

Structure:
```
bigbang/plugins/mynewthing/
  cli.py        -> typer app named "mynewthing"
  __init__.py
```

`cli.py` must expose:
```python
import typer
app = typer.Typer(name="mynewthing")
@app.command("foo")
def foo(): ...

def register(root):
    root.add_typer(app, name="mynewthing")
```

It auto-loads on next `bb --help`.

## Agent-friendly JSON

Every command should support dual output:

```python
from bigbang.core.output import emit
emit({"ok": True, "data": ...})
# user runs: bb mynewthing foo --json => valid JSON
```

## MCP

`bigbang/mcp/server.py` generates manifest:
```bash
python3 -m bigbang.mcp.server
bb mcp serve --port 8787  # (TODO: full MCP stdio impl)
```

Add to Claude/Cursor Hatch as MCP server.

## Skills

Drop markdown files into `bigbang/skills/` - they become `bb skill run <name>`.

Example `bigbang/skills/emergency-tax-lift.md`:
```yaml
---
name: emergency-tax-lift
description: Cut tax drag on emergency fund
---
Pull Plaid 7333, fetch treasury yields, build ladder
```

## Continuous Growth Loop

1. Daily pattern? `bb system scaffold`
2. Recurring Hatch IDEAs loop suggests new skills from workspace/projects/
3. File them into Life Admin Brain / Davis Family Brain

