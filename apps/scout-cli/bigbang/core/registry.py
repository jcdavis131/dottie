"""Universal tool registry — the heart of 'one CLI to rule them all'"""

import time
from pathlib import Path

from bigbang.core import atomic_json

REG_DIR = Path.home() / ".local" / "share" / "bigbang"
REG_FILE = REG_DIR / "registry.json"
REG_DIR.mkdir(parents=True, exist_ok=True)


def _load():
    """Registry contents, or a fresh one when none exists.

    A CORRUPT registry raises rather than reading as empty -- same read-modify-write
    trap as the vault: silently returning a fresh registry would make the next
    register_tool() drop every previously registered tool. See atomic_json.
    """
    return atomic_json.read_json(REG_FILE, {"version": "0.3.0", "tools": {}})


def _save(data):
    atomic_json.write_json(REG_FILE, data)


def register_tool(name: str, manifest: dict):
    db = _load()
    manifest["registered_at"] = int(time.time())
    db["tools"][name] = manifest
    _save(db)


def get_tool(name: str) -> dict | None:
    db = _load()
    return db["tools"].get(name)


def list_tools() -> dict[str, dict]:
    db = _load()
    return db["tools"]


def unregister_tool(name: str) -> bool:
    db = _load()
    if name in db["tools"]:
        del db["tools"][name]
        _save(db)
        return True
    return False


def search_tools(query: str) -> list[dict]:
    db = _load()
    q = query.lower()
    results = []
    for name, m in db["tools"].items():
        hay = f"{name} {m.get('description', '')} {m.get('type', '')} {' '.join(m.get('tags', []))}".lower()
        if q in hay:
            results.append({"name": name, **m})
    return results
