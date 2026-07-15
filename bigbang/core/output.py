"""Dual output - rich + json for agents"""
import json
import sys
from typing import Any
from rich.console import Console
from rich.table import Table

_console = Console()
_json_mode = False

def set_json_mode(v: bool):
    global _json_mode
    _json_mode = v

def is_json():
    return _json_mode

def emit(data: Any, table: Table | None = None):
    """Emit for both humans and agents"""
    if _json_mode:
        # Always valid JSON
        print(json.dumps(data, indent=2, default=str))
    else:
        if table:
            _console.print(table)
        else:
            # pretty rich if not json
            if isinstance(data, dict) and "message" in data:
                _console.print(data["message"])
            else:
                _console.print(data)

def emit_table(dicts: list[dict], title: str = ""):
    if _json_mode:
        print(json.dumps(dicts, indent=2, default=str))
        return
    if not dicts:
        _console.print(f"[dim]{title}: no data[/dim]")
        return
    t = Table(title=title)
    for k in dicts[0].keys():
        t.add_column(k)
    for d in dicts:
        t.add_row(*[str(v) for v in d.values()])
    _console.print(t)
