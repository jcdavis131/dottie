"""
contacts plugin — ACNE Contacts Power Suite CLI
The tool I wish I had when doing harness work.

Commands:
  scout contacts resolve "my designer"
  scout contacts stats
  scout contacts graphrag "which agent uses"
  scout contacts sync --graphify

Zero-deps, local-only, no cloud. Graceful on missing nodes.jsonl.
Follows harness/plugin pattern: typer + make_plugin_app + emit raw dict compatible with --json harness routing.
"""

from __future__ import annotations
import json
from pathlib import Path
import sys

import typer

try:
    from bigbang.core.contract import make_plugin_app
    from bigbang.core.output import emit, is_json
except Exception:  # fallback when run outside bigbang env
    def make_plugin_app(name, desc, examples=None):
        import typer
        return typer.Typer(help=desc)
    def emit(data, command=None):
        print(json.dumps(data, indent=2))
    def is_json():
        return "--json" in sys.argv

app = make_plugin_app(
    "contacts",
    "ACNE Contacts Power Suite — resolve/search/graphrag/sync/health (local-first 17 types, 27 edges 5-layer cache)",
    examples=[
        'scout --json contacts resolve "my designer"',
        "scout --json contacts stats",
        'scout --json contacts graphrag "which agent uses builder-pack"',
        "scout --json contacts sync --graphify",
    ]
)

def _emit(result: dict, cmd: str, json_out: bool=False):
    if is_json() or json_out:
        emit(result, command=cmd)
    else:
        typer.echo(json.dumps(result, indent=2))

def _hub_kwargs():
    """Resolve hub args from env or defaults."""
    ws = Path.home() / "workspace"
    return {"workspace": str(ws)}

from pathlib import Path as _P

def _load_tools():
    try:
        from acne.tools import resolve_contact, search_nodes, graphify_query, health_report, sync_all
        return resolve_contact, search_nodes, graphify_query, health_report, sync_all
    except Exception:
        # fallback import via src path
        import sys as _s
        src = _P.home() / "workspace" / "acne" / "src"
        if str(src) not in _s.path:
            _s.path.insert(0, str(src))
        from acne.tools import resolve_contact, search_nodes, graphify_query, health_report, sync_all
        return resolve_contact, search_nodes, graphify_query, health_report, sync_all

@app.command("resolve")
def resolve_cmd(
    query: str = typer.Argument(..., help="Fuzzy phrase, e.g. 'my designer'"),
    json_out: bool = typer.Option(False, "--json", help="Emit json")):
    resolve_contact, _, _, _, _ = _load_tools()
    res = resolve_contact(query)
    # Normalize for CLI ease
    out = {
        "query": query,
        "contact": res.get("contact") if isinstance(res, dict) else None,
        "confidence": res.get("confidence", 0) if isinstance(res, dict) else 0,
        "why": res.get("why","") if isinstance(res, dict) else str(res),
        "trigger_matched": res.get("trigger_matched") if isinstance(res, dict) else None,
        "ok": True,
        "command": f"contacts resolve {query[:40]}"
    }
    if isinstance(res, dict) and res.get("contact") is None and res.get("confidence",0)==0:
        out["note"] = "No match — TLPG may be empty; try `scout contacts sync` first"
    _emit(out, "contacts resolve", json_out)

@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Vector search query"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    node_class: str = typer.Option(None, "--class", "-c", help="Filter by NodeClass"),
    json_out: bool = typer.Option(False, "--json")):
    _, search_nodes, _, _, _ = _load_tools()
    try:
        nodes = search_nodes(query, top_k=top_k, node_class=node_class)
        res = {"query": query, "top_k": top_k, "node_class": node_class, "nodes": nodes, "count": len(nodes), "ok": True, "command": f"contacts search {query[:30]}"}
        if not nodes:
            res["note"] = "Empty — missing nodes.jsonl or TLPG not yet synced. Run `scout contacts sync`."
    except Exception as e:
        res = {"query": query, "nodes": [], "count": 0, "error": str(e), "ok": False}
    _emit(res, "contacts search", json_out)

@app.command("graphrag")
def graphrag_cmd(
    query: str = typer.Argument(..., help="Which agent uses... / Realizes..."),
    hops: int = typer.Option(2, "--hops"),
    top_k: int = typer.Option(5, "--top-k"),
    compressed: bool = typer.Option(False, "--compressed", help="If true 70-88% token saving"),
    budget_tokens: int = typer.Option(600, "--budget"),
    json_out: bool = typer.Option(False, "--json")):
    _, _, graphify_query, _, _ = _load_tools()
    try:
        r = graphify_query(query, hops=hops, top_k=top_k, compressed=compressed, budget_tokens=budget_tokens)
        if not isinstance(r, dict):
            r = {"result": r}
        r["ok"] = True
        r["command"] = f"contacts graphrag {query[:40]}"
        if not r.get("nodes"):
            r["note"] = "No nodes found — sync first via `scout contacts sync`"
        _emit(r, "contacts graphrag", json_out)
    except Exception as e:
        _emit({"query": query, "error": str(e), "nodes": [], "ok": False}, "contacts graphrag", json_out)

@app.command("stats")
def stats_cmd(
    json_out: bool = typer.Option(False, "--json")):
    _, _, _, health_report, _ = _load_tools()
    r = health_report()
    r["ok"] = True
    r["command"] = "contacts stats"
    _emit(r, "contacts stats", json_out)

@app.command("health")
def health_cmd(
    json_out: bool = typer.Option(False, "--json")):
    return stats_cmd(json_out=json_out)

@app.command("sync")
def sync_cmd(
    graphify: bool = typer.Option(True, "--graphify/--no-graphify", help="Also run graphify_constructs + goal_healthcheck"),
    manifest: str = typer.Option(None, "--manifest", help="Path to bundles/manifest.json"),
    json_out: bool = typer.Option(False, "--json")):
    _, _, _, _, sync_all = _load_tools()
    # sync_all always graphifies per our impl; param kept for CLI API parity
    try:
        mp = manifest or str(Path.home() / "workspace" / "bundles" / "manifest.json")
        res = sync_all(manifest_path=mp)
        # If user passed --no-graphify, strip graphify info but we already did — cheap.
        if not graphify:
            res.pop("graphify", None)
        res["ok"] = True
        res["command"] = "contacts sync"
        _emit(res, "contacts sync", json_out)
    except Exception as e:
        _emit({"ok": False, "error": str(e), "manifest": manifest}, "contacts sync", json_out)

# Alias: keep backward compat
@app.command("sync-all")
def sync_all_cmd(
    manifest: str = typer.Option(None, "--manifest"),
    json_out: bool = typer.Option(False, "--json")):
    return sync_cmd(graphify=True, manifest=manifest, json_out=json_out)

# Allow `scout contacts` without subcommand to show help — typer does automatically.

if __name__ == "__main__":
    app()
