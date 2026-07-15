"""Dual output — rich for humans, valid JSON for agents, audited"""
import json
import sys
import time
from typing import Any
from rich.console import Console

_console = Console()
_json_mode = False
_start_ts = time.time()

def set_json_mode(enabled: bool):
    global _json_mode, _start_ts
    _json_mode = enabled
    _start_ts = time.time()

def is_json() -> bool:
    return _json_mode

def emit(data: Any, command: str = "unknown"):
    if _json_mode:
        try:
            json.dump(data, sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
        except Exception:
            print(json.dumps({"data": str(data)}))
    else:
        if isinstance(data, dict):
            _console.print_json(data=data)
        else:
            _console.print(data)
    # audit async
    try:
        from bigbang.core.audit import log_event
        dur = int((time.time() - _start_ts)*1000)
        # don't log secret values
        safe = {k: v for k, v in (data.items() if isinstance(data, dict) else {}).items() if "secret" not in k.lower() and "key" not in k.lower()}
        log_event(command, safe, status="ok", duration_ms=dur)
    except Exception:
        pass
