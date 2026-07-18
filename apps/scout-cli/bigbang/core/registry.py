"""Universal tool registry — the heart of 'one CLI to rule them all'"""
import json
from pathlib import Path
from typing import List, Dict, Optional
import time

REG_DIR = Path.home() / ".local" / "share" / "bigbang"
REG_FILE = REG_DIR / "registry.json"
REG_DIR.mkdir(parents=True, exist_ok=True)

def _load():
    if not REG_FILE.exists():
        return {"version": "0.3.0", "tools": {}}
    try:
        return json.loads(REG_FILE.read_text())
    except Exception:
        return {"version": "0.3.0", "tools": {}}

def _save(data):
    REG_FILE.write_text(json.dumps(data, indent=2))

def register_tool(name: str, manifest: Dict):
    db = _load()
    manifest["registered_at"] = int(time.time())
    db["tools"][name] = manifest
    _save(db)

def get_tool(name: str) -> Optional[Dict]:
    db = _load()
    return db["tools"].get(name)

def list_tools() -> Dict[str, Dict]:
    db = _load()
    return db["tools"]

def unregister_tool(name: str) -> bool:
    db = _load()
    if name in db["tools"]:
        del db["tools"][name]
        _save(db)
        return True
    return False

def search_tools(query: str) -> List[Dict]:
    db = _load()
    q = query.lower()
    results = []
    for name, m in db["tools"].items():
        hay = f"{name} {m.get('description','')} {m.get('type','')} {' '.join(m.get('tags',[]))}".lower()
        if q in hay:
            results.append({"name": name, **m})
    return results
