"""Dual output - rich for humans, valid JSON for agents"""
import json
import sys
from typing import Any
from rich.console import Console

_console = Console()
_json_mode = False

def set_json_mode(enabled: bool):
    global _json_mode
    _json_mode = enabled

def is_json() -> bool:
    return _json_mode

def emit(data: Any):
    """Emit data - if --json, print only JSON (valid), else rich"""
    if _json_mode:
        # Only JSON, no other prints
        # Ensure serializable
        try:
            json.dump(data, sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
        except Exception:
            # fallback
            print(json.dumps({"data": str(data)}))
    else:
        # Human path - rich
        if isinstance(data, dict):
            # pretty but concise
            _console.print_json(data=data)
        else:
            _console.print(data)

def emit_table(title: str, rows: list, columns: list = None):
    from rich.table import Table
    if _json_mode:
        emit({"title": title, "rows": rows})
        return
    table = Table(title=title)
    if columns:
        for c in columns:
            table.add_column(c)
    else:
        if rows and isinstance(rows[0], dict):
            for k in rows[0].keys():
                table.add_column(str(k))
    for r in rows:
        if isinstance(r, dict):
            table.add_row(*[str(v) for v in r.values()])
        else:
            table.add_row(str(r))
    _console.print(table)
