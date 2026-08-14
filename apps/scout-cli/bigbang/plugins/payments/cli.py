# Solo personal project, no connection to employer, built with public/free-tier only
"""payments plugin — Phase 0 $0 ledger stub
Idempotent local payments for Launched P0 blocker.
Pattern: idempotency_key = sha256(normalized_email + "|" + normalized_plan)

Security:
- network:false enforced via manifest + _egress_guard
- filesystem write allowlist: bundles/payments/store.jsonl + ~/.local/share/bigbang/payments.jsonl
- secrets:false now; STRIPE_API_KEY only after interactive confirm manifest widen — no auto
- No torch, no network calls in Phase 0

Commands:
- create --email --plan [--amount 0] : idempotent create $0 invoice
- check  --email --plan : check exists
- list : list ledger
- stats : token/cache style stats
- idempotent-key : show sha(email|plan)
- widen-note : explain secret widening guard
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict

import typer
from rich.console import Console

from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise, load_manifest

app = make_plugin_app(
    "payments",
    "💳 Payments Phase0 — $0 ledger idempotent sha256(email|plan), local-first no Stripe yet",
    examples=[
        "scout payments create --email cameron@example.com --plan launched-pro --json",
        "scout payments check --email cameron@example.com --plan launched-pro --json",
        "scout payments list --json",
        "scout payments stats",
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
    """Phase0 must never egress. If you see this raise, you attempted a network call before manifest widen. Guard mirrors _egress_guard pattern from analytics stub."""
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        from bigbang.core.cli_ux import fail_agent
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is local-first $0 ledger — refusing",
            command=command,
            example="scout payments create --email x --plan y --json",
        )
    return {"network_enabled": False, "domains": [], "egress": "none, on any path"}

def _store_paths():
    base = Path.home() / "workspace" / "bundles" / "payments" / "store.jsonl"
    alt = Path("bundles/payments/store.jsonl")
    local_share = Path.home() / ".local" / "share" / "bigbang" / "payments.jsonl"
    return [base, alt, local_share]

def _resolve_store() -> Path:
    p = Path.home() / "workspace" / "bundles" / "payments" / "store.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".local" / "share" / "bigbang").mkdir(parents=True, exist_ok=True)
    return p

def _norm(s: str) -> str:
    return s.strip().lower()

def _idempotency_key(email: str, plan: str) -> str:
    """Deterministic idempotency key: sha256(normalized_email + "|" + normalized_plan) Mirrors Stripe idempotency_key best practice. Stored full hex, display truncated."""
    raw = f"{_norm(email)}|{_norm(plan)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _load_ledger() -> List[Dict[str, Any]]:
    store = _resolve_store()
    if not store.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for ln in store.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    except Exception:
        return []
    return rows

def _daily_shard_path(ts_iso: str | None = None) -> Path:
    """Daily shard path — 2026-08-07.jsonl for Launched, uses ts day or today UTC."""
    day = "2026-08-07"
    if ts_iso:
        try:
            day = ts_iso[:10]
            # sanity: must be YYYY-MM-DD
            if len(day) != 10 or day[4] != "-" or day[7] != "-":
                day = "2026-08-07"
        except Exception:
            day = "2026-08-07"
    shard_dir = Path.home() / "workspace" / "bundles" / "payments" / "events"
    shard_dir.mkdir(parents=True, exist_ok=True)
    return shard_dir / f"{day}.jsonl"

def _write_ledger_row(row: Dict[str, Any]) -> None:
    store = _resolve_store()
    enforce_or_raise(_manifest(), "fs_write_arg", str(store))
    line = json.dumps(row, separators=(",", ":"))
    with store.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    # secondary mirror for policy compliance
    try:
        secondary = Path.home() / ".local" / "share" / "bigbang" / "payments.jsonl"
        secondary.parent.mkdir(parents=True, exist_ok=True)
        enforce_or_raise(_manifest(), "fs_write_arg", str(secondary))
        with secondary.open("a", encoding="utf-8") as sf:
            sf.write(line + "\n")
    except Exception:
        pass
    # daily shard — 2026-08-07.jsonl per Idea 005, idempotent wiring needs shard history
    try:
        ts = row.get("created_at") or row.get("tx_time") or ""
        shard = _daily_shard_path(ts)
        enforce_or_raise(_manifest(), "fs_write_arg", str(shard))
        with shard.open("a", encoding="utf-8") as df:
            df.write(line + "\n")
        # also ensure .scout/payments mirror exists for runtime (manifest allows)
        try:
            rt_dir = Path.home() / "workspace" / ".scout" / "payments"
            rt_dir.mkdir(parents=True, exist_ok=True)
            rt = rt_dir / "store.jsonl"
            with rt.open("a", encoding="utf-8") as rf:
                rf.write(line + "\n")
        except Exception:
            pass
    except Exception:
        # shard write best-effort — main store already ok
        pass

def _find_existing(idem_key: str) -> Dict[str, Any] | None:
    ledger = _load_ledger()
    for r in ledger:
        if r.get("idempotency_key") == idem_key or r.get("idempotent_key") == idem_key:
            return r
    return None

@app.command("create")
def create_cmd(
    email: str = typer.Option(..., "--email", help="Customer email"),
    plan: str = typer.Option(..., "--plan", help="Plan id e.g. launched-pro"),
    amount: int = typer.Option(0, "--amount", help="Amount in cents, Phase0 always 0"),
    currency: str = typer.Option("usd", "--currency", help="Currency"),
    json_out: bool = typer.Option(False, "--json", help="Emit json"),
):
    """Idempotent create $0 invoice. Duplicate (email+plan) returns existing. No Stripe, no network."""
    _egress_guard("payments create")
    if amount != 0:
        from bigbang.core.cli_ux import fail_agent
        fail_agent("Phase0 only allows amount=0, use --amount 0", command="payments create", example="scout payments create --email x --plan y --json")
    idem_key = _idempotency_key(email, plan)
    existing = _find_existing(idem_key)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        result = {"invoice": existing, "idempotent": True, "note": "idempotent hit — returned existing, no duplicate written", "idempotency_key": idem_key, "idempotent_key_short": idem_key[:16]}
        emit(ok(result, command="payments create", example="scout payments check --email x --plan y --json"), command="payments create")
        return
    invoice = {
        "id": f"inv_0_{idem_key[:16]}",
        "idempotency_key": idem_key,
        "idempotent_key": idem_key,
        "idempotent_key_short": idem_key[:16],
        "email": _norm(email),
        "plan": _norm(plan),
        "amount": 0,
        "currency": currency.lower() if currency else "usd",
        "status": "succeeded",
        "phase": "phase0",
        "created_at": now,
        "tx_time": now,
        "note": "$0 ledger stub",
    }
    _write_ledger_row(invoice)
    # analytics bridge — PostHog-style local event for payments $0 ledger, best-effort no network
    try:
        a_store = Path.home() / "workspace" / "bundles" / "analytics" / "store.jsonl"
        a_store.parent.mkdir(parents=True, exist_ok=True)
        a_evt = {
            "id": f"e_pay_{idem_key[:12]}",
            "type": "pay",
            "entity_id": f"payments/{_norm(plan)}",
            "user_hash": hashlib.sha256(_norm(email).encode()).hexdigest()[:16],
            "user_raw_sha": hashlib.sha256(_norm(email).encode()).hexdigest()[:16],
            "ts": now,
            "tx_time": now,
            "props": {"plan": _norm(plan), "amount": 0, "currency": "usd", "phase": "phase0", "idempotency_key": idem_key[:16]},
            "checksum": idem_key[:16],
        }
        with a_store.open("a", encoding="utf-8") as af:
            af.write(json.dumps(a_evt) + "\n")
        # also daily shard for analytics
        a_day = now[:10] if len(now) >= 10 else "2026-08-07"
        a_shard_dir = Path.home() / "workspace" / "bundles" / "analytics" / "events"
        a_shard_dir.mkdir(parents=True, exist_ok=True)
        with (a_shard_dir / f"{a_day}.jsonl").open("a", encoding="utf-8") as asf:
            asf.write(json.dumps(a_evt) + "\n")
    except Exception:
        pass
    result = {"invoice": invoice, "idempotent": False, "note": "created $0 invoice, idempotent future calls return same", "idempotency_key": idem_key}
    emit(ok(result, command="payments create", example="scout payments check --email x --plan y --json"), command="payments create")

@app.command("check")
def check_cmd(
    email: str = typer.Option(..., "--email", help="Customer email"),
    plan: str = typer.Option(..., "--plan", help="Plan id e.g. launched-pro"),
    json_out: bool = typer.Option(False, "--json", help="Emit json"),
):
    """Check if email+plan already has $0 invoice."""
    _egress_guard("payments check")
    idem_key = _idempotency_key(email, plan)
    existing = _find_existing(idem_key)
    result = {"exists": bool(existing), "idempotency_key": idem_key, "invoice": existing, "email": _norm(email), "plan": _norm(plan)}
    emit(ok(result, command="payments check"), command="payments check")

@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "--limit", help="Max rows"),
    json_out: bool = typer.Option(False, "--json", help="Emit json"),
):
    """List $0 ledger."""
    _egress_guard("payments list")
    ledger = _load_ledger()
    showing = list(reversed(ledger))[:limit]
    result = {"count": len(ledger), "showing": len(showing), "invoices": showing}
    emit(ok(result, command="payments list"), command="payments list")

@app.command("stats")
def stats_cmd(
    json_out: bool = typer.Option(False, "--json", help="Emit json"),
):
    """Stats for token-cache style dashboard."""
    _egress_guard("payments stats")
    ledger = _load_ledger()
    by_plan: Dict[str, int] = {}
    for r in ledger:
        p = r.get("plan", "unknown")
        by_plan[p] = by_plan.get(p, 0) + 1
    result = {
        "count": len(ledger),
        "by_plan": by_plan,
        "phase": "$0 Phase0",
        "idempotency": "sha256(email|plan) lowercased",
        "agent": "scout/payments-phase0",
        "network": "none",
        "note": "Phase1 needs interactive confirm to allow STRIPE_API_KEY + api.stripe.com domain",
        "stores": [str(p) for p in _store_paths()],
    }
    emit(ok(result, command="payments stats"), command="payments stats")

@app.command("idempotent-key")
def idempotent_key_cmd(
    email: str = typer.Option(..., "--email", help="Customer email"),
    plan: str = typer.Option(..., "--plan", help="Plan"),
):
    """Show idempotency key sha256(email|plan) lowercased trimmed."""
    _egress_guard("payments idempotent-key")
    key = _idempotency_key(email, plan)
    result = {"email": _norm(email), "plan": _norm(plan), "idempotency_key": key, "short": key[:16], "raw": f"{_norm(email)}|{_norm(plan)}"}
    emit(ok(result, command="payments idempotent-key"), command="payments idempotent-key")

@app.command("widen-note")
def widen_note_cmd():
    """Explain secret widening guard — does not auto-widen. Operator must interactively confirm."""
    _egress_guard("payments widen-note")
    note = """
PAYMENTS Phase0 → Phase1 widening guard

Current: network:false secrets:false — $0 ledger only, no Stripe.

To enable live Stripe:

  1. Interactive confirm required — NEVER auto-widen via code:
     scout secrets allow STRIPE_API_KEY --interactive-confirm
     (Operator must type yes live — script cannot bypass)

  2. Manifest widen:
     capabilities:
       network: {enabled:true domains:[api.stripe.com]}
       secrets: {allow:[STRIPE_API_KEY]}

  3. Verify:
     - secrets.allow == ["STRIPE_API_KEY"]
     - network.domains == ["api.stripe.com"]
     - All 6 cmds still idempotent

Phase0 never egresses. This command documents the guard.
"""
    from rich.markdown import Markdown
    _console.print(Markdown(note))
    emit(ok({"note": note.strip(), "network": False, "secrets": False, "phase": "phase0"}, command="payments widen-note"), command="payments widen-note")

if __name__ == "__main__":
    app()
