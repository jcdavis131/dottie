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

`bigbang/plugins/mcp/cli.py` generates manifest:
```bash
bb mcp manifest
bb mcp serve --port 8787
```

Add to Claude/Cursor/Hatch as MCP server http://localhost:8787.

## Skills

Drop markdown files into `bigbang/skills/` - they become `bb skill run <name>`.

Example `bigbang/skills/vector-daily.md`:
```yaml
---
name: vector-daily
description: Rebuild vector hoops daily guess mode
---
Run pipeline/rebuild_all.py --quick --leakfree
```

## Continuous Growth Loop

1. Daily pattern? `bb system scaffold`
2. Recurring Hatch IDEAS loop suggests new skills from workspace/projects/
3. File them into Life Admin Brain / tools registry
