"""Audit trail — every invocation logged, security first"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone

AUDIT_DIR = Path.home() / ".local" / "share" / "bigbang"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

def log_event(command: str, args: dict, status: str = "ok", duration_ms: int = 0):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "args": args,
        "status": status,
        "duration_ms": duration_ms,
    }
    try:
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def tail_events(n: int = 20):
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text().strip().split("\n")[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out
