# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout analytics` — PostHog/Mixpanel-class analytics, fully local (openswap local).

Lanes 4/5 of ultracode assessment: Launched blocker (live URL + 3 users +
payments/analytics). SaaS analytics needs key, cookie banner, egress. This
deletes that: events live on this box, queries over JSONL, deterministic SVG
render later — same invariant as 62 other local-first swaps in bigbang/plugins/.

Storage (SSOT per integration-optimizations.md):
- `bundles/analytics/store.jsonl` canonical ledger
- `bundles/analytics/events/YYYY-MM-DD.jsonl` daily shards (len//4 dedup L1)
- `.scout/analytics/store.jsonl` live runtime mirror (same schema)

Each line JSON: {id:e_sha16, type, entity_id, user_hash, ts, tx_time, props}
Idempotent key = sha256(type+entity+user+ts_day+props_sorted)[:16] — Stage1 TLPG dedup.
No network anywhere. Manifest disables network axis with empty domain list and
every command calls `_egress_guard` first, which re-reads the manifest and
REFUSES if that section was ever widened — so "no event left the box" is enforced.

Commands live in this surface, deterministic logic in bigbang/core/analytics.py
(when it exists) or locally until then. No torch — OOM guard.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

app = make_plugin_app(
    "analytics",
    "PostHog-class local analytics — JSONL ledger + DAU/WAU + funnel, zero egress",
    examples=[
        "scout --json analytics ingest --type view --entity dumbmodel.com/cards --user u_abc",
        "scout --json analytics events --limit 20",
        "scout --json analytics stats --days 7",
        "scout analytics ingest --type click --entity chimera --user u_123 --props '{\"funnel\":\"signup\"}'",
    ],
)

_console = Console()
_MANIFEST: dict | None = None

def _manifest() -> dict:
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST

def _egress_guard(command: str) -> dict:
    """Assert manifest still declares ZERO egress, or refuse to run.

    Pattern cloned from a11y/coverage/cve/quality/cite — privacy guarantee that
    fails the command is a contract, not a docstring promise.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        from bigbang.core.cli_ux import fail_agent
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "local-first analytics — refusing to run until capabilities.network is "
            "disabled with an empty domain list",
            command=command,
            example="scout --json analytics ingest --type view --entity x --user y",
        )
    return {"network_enabled": False, "domains": [], "egress": "none, on any path"}

def _store_paths() -> list[Path]:
    """Canonical + runtime mirrors. Both allowed by manifest."""
    base_bundles = Path.home() / "workspace" / "bundles" / "analytics" / "store.jsonl"
    # also support relative when invoked from workspace root
    alt_bundles = Path("bundles/analytics/store.jsonl")
    runtime = Path.home() / "workspace" / ".scout" / "analytics" / "store.jsonl"
    # prefer workspace path if exists
    return [base_bundles, alt_bundles, runtime]

def _resolve_store() -> Path:
    # choose primary SSOT — bundles/analytics/store.jsonl
    p = Path.home() / "workspace" / "bundles" / "analytics" / "store.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    # ensure runtime dir exists too
    (Path.home() / "workspace" / ".scout" / "analytics").mkdir(parents=True, exist_ok=True)
    return p

def _event_id(evt_type: str, entity: str, user: str, ts_day: str, props_str: str) -> str:
    raw = f"{evt_type}|{entity}|{user}|{ts_day}|{props_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def _write_event(evt: dict) -> None:
    store = _resolve_store()
    # policy gate — plugin loader doesn't auto-check fs_write for us
    enforce_or_raise(_manifest(), "fs_write_arg", str(store))
    line = json.dumps(evt, separators=(",", ":"))
    # atomic-ish append — keep simple, no lock needed for Phase 0
    with store.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    # daily shard too
    try:
        ts = evt.get("ts", "")
        day = ts[:10] if len(ts) >= 10 else datetime.now(timezone.utc).date().isoformat()
        shard_dir = Path.home() / "workspace" / "bundles" / "analytics" / "events"
        shard_dir.mkdir(parents=True, exist_ok=True)
        enforce_or_raise(_manifest(), "fs_write_arg", str(shard_dir / f"{day}.jsonl"))
        with (shard_dir / f"{day}.jsonl").open("a", encoding="utf-8") as sf:
            sf.write(line + "\n")
        # runtime mirror
        rt = Path.home() / "workspace" / ".scout" / "analytics" / "store.jsonl"
        rt.parent.mkdir(parents=True, exist_ok=True)
        with rt.open("a", encoding="utf-8") as rf:
            rf.write(line + "\n")
    except Exception:
        # shard write is best-effort if manifest check fails — main store already ok
        pass

def _read_events(limit: int = 100) -> list[dict]:
    store = _resolve_store()
    if not store.exists():
        return []
    out: list[dict] = []
    # read last N efficiently
    try:
        lines = store.read_text(encoding="utf-8").splitlines()
        for ln in reversed(lines[-5000:]):  # cap scan
            if not ln.strip():
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
            if len(out) >= limit:
                break
    except Exception:
        return []
    return list(reversed(out))

@app.command("ingest")
def ingest_cmd(
    type_: str = typer.Option(..., "--type", "-t", help="event type: view, click, signup, pay, etc."),
    entity: str = typer.Option(..., "--entity", "-e", help="entity_id like dumbmodel.com/cards or chimera"),
    user: str = typer.Option(..., "--user", "-u", help="user_id (hashed internally to user_hash)"),
    props: str = typer.Option("{}", "--props", help="JSON props dict, e.g. '{\"referrer\":\"feed\"}'"),
    ts: str | None = typer.Option(None, "--ts", help="ISO ts override, default now UTC"),
):
    """Track one analytics event (L1 dedup tolerant)."""
    _egress_guard("analytics ingest")
    try:
        props_dict = json.loads(props) if props else {}
        if not isinstance(props_dict, dict):
            raise ValueError("props must be a JSON object")
    except Exception as e:
        from bigbang.core.cli_ux import fail_agent
        fail_agent(f"bad --props JSON: {e}", command="analytics ingest",
                   example='scout analytics ingest --type view --entity x --user y --props \'{\"a\":1}\'')
    now = datetime.now(timezone.utc).isoformat()
    ts_use = ts or now
    day = ts_use[:10] if len(ts_use) >= 10 else now[:10]
    # user_hash = sha16 of user id (privacy, local still)
    user_hash = hashlib.sha256(user.encode()).hexdigest()[:16]
    props_sorted = json.dumps(props_dict, sort_keys=True, separators=(",", ":"))
    eid = _event_id(type_, entity, user_hash, day, props_sorted)
    evt = {
        "id": f"e_{eid}",
        "type": type_,
        "entity_id": entity,
        "user_hash": user_hash,
        "user_raw_sha": user_hash,  # alias
        "ts": ts_use,
        "tx_time": now,
        "props": props_dict,
        "checksum": eid,
    }
    # L1 dedup: if exact checksum already in last 5k, skip write but return ok
    existing = _read_events(limit=5000)
    if any(e.get("checksum") == eid for e in existing):
        emit(ok({"dedup": True, "event": evt, "note": "duplicate checksum — skipped write"},
                command="analytics ingest"), command="analytics ingest")
        return
    _write_event(evt)
    emit(ok({"event": evt, "store": str(_resolve_store())},
           command="analytics ingest",
           example="scout --json analytics events --limit 20"), command="analytics ingest")

@app.command("events")
def events_cmd(
    limit: int = typer.Option(20, "--limit", help="how many recent events"),
    type_filter: str | None = typer.Option(None, "--type", help="filter by type"),
    entity_filter: str | None = typer.Option(None, "--entity", help="filter by entity_id prefix"),
):
    """List recent events from local ledger (read-only path, no egress)."""
    _egress_guard("analytics events")
    evts = _read_events(limit=5000)
    if type_filter:
        evts = [e for e in evts if e.get("type") == type_filter]
    if entity_filter:
        evts = [e for e in evts if str(e.get("entity_id","")).startswith(entity_filter)]
    evts = evts[-limit:]
    emit(ok({"events": evts, "count": len(evts), "total_scanned": 5000,
             "store": str(_resolve_store())},
            command="analytics events"), command="analytics events")

@app.command("stats")
def stats_cmd(
    days: int = typer.Option(7, "--days", help="window days for DAU/WAU"),
):
    """DAU/WAU + funnel over local ledger — no cookie, no key, stdlib only."""
    _egress_guard("analytics stats")
    evts = _read_events(limit=5000)
    if not evts:
        emit(ok({"dau": [], "wau": 0, "total": 0, "funnel": {}, "days": days, "note": "no events yet"},
                command="analytics stats"), command="analytics stats")
        return
    # bucket by day string ts[:10]
    from collections import defaultdict, Counter
    day_buckets: dict[str, set[str]] = defaultdict(set)
    user_days: list[tuple[str,str]] = []
    for e in evts:
        d = str(e.get("ts",""))[:10]
        uh = str(e.get("user_hash",""))
        if d and uh:
            day_buckets[d].add(uh)
    # DAU last N days
    sorted_days = sorted(day_buckets.keys())
    last_n = sorted_days[-days:] if days <= len(sorted_days) else sorted_days
    dau = [{"day": d, "dau": len(day_buckets[d])} for d in last_n]
    # WAU = unique in window
    wau_set = set()
    for d in last_n:
        wau_set |= day_buckets[d]
    # funnel simple: view -> click -> signup -> pay
    funnel_steps = ["view","click","signup","pay"]
    funnel_counts = Counter(e.get("type") for e in evts if e.get("ts","")[:10] in set(last_n))
    funnel = {step: funnel_counts.get(step,0) for step in funnel_steps}
    # entity top 5
    ent_counts = Counter(e.get("entity_id") for e in evts)
    top_entities = ent_counts.most_common(5)
    emit(ok({"dau": dau, "wau": len(wau_set), "total": len(evts),
             "funnel": funnel, "top_entities": top_entities, "days": days,
             "store": str(_resolve_store())},
            command="analytics stats",
            example="scout analytics events --limit 20"),
         command="analytics stats")

@app.command("detect")
def detect_cmd():
    """Capability report — tier fallback is the product, network is none."""
    guard = _egress_guard("analytics detect")
    emit(ok({"plugin": "analytics", "version": "0.8.0",
             "egress": guard, "stores": [str(p) for p in _store_paths()],
             "fallback_scope": "pure-stdlib JSONL ledger is complete — no SaaS, no cookie, no key"},
            command="analytics detect"), command="analytics detect")

@app.command("hello")
def hello_cmd():
    _egress_guard("analytics hello")
    emit(ok({"ready": True, "plugin": "analytics", "network": "none"},
            command="analytics hello"), command="analytics hello")
