"""Dual output — rich for humans, valid JSON for agents, audited"""

import json
import re
import sys
import time
from typing import Any

from rich.console import Console

_console = Console()
_json_mode = False
_start_ts = time.time()

# Keys whose values must never reach audit.jsonl. Covers `secrets get` ("value"),
# `auth get-token --reveal` ("token"), and the usual credential key names.
_AUDIT_DENY_KEY_RE = re.compile(
    r"(secret|key|value|token|password|passwd|credential|auth|bearer|cookie)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


def _redact_for_audit(data: Any, _key: str = "") -> Any:
    """Recursively redact secret-bearing keys and secret-shaped substrings."""
    # Reuse the battle-tested substring patterns from the rft ETL so raw
    # credentials embedded in longer strings are caught too.
    from bigbang.plugins.rft.etl import _SECRET_SUBSTR_RE

    if isinstance(data, dict):
        return {k: _redact_for_audit(v, _key=str(k)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact_for_audit(v, _key=_key) for v in data]
    if isinstance(data, str):
        if _AUDIT_DENY_KEY_RE.search(_key):
            return _REDACTED
        return _SECRET_SUBSTR_RE.sub(_REDACTED, data)
    if _AUDIT_DENY_KEY_RE.search(_key):
        return _REDACTED
    return data


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
    # audit trail — redacted; only I/O failures are tolerated, anything else is a bug
    from bigbang.core.audit import log_event

    dur = int((time.time() - _start_ts) * 1000)
    safe = _redact_for_audit(data) if isinstance(data, dict) else {}
    try:
        log_event(command, safe, status="ok", duration_ms=dur)
    except OSError:
        pass
