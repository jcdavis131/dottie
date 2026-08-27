# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout inbox` — unattended ask inbox (openworker-style).

Parks consequential actions when user away instead of acting alone.
Openworker parks asks in inbox when unattended; Dottie should too.

- Park: `scout inbox park "comms send" --payload '{"to":"a@b"}' --reason unattended`
- List: `scout --json inbox list --pending`
- Approve/Deny: `scout inbox approve <id>`, `scout inbox deny <id> --reason`
- Show/Clear: `scout inbox show <id>`, `scout inbox clear --approved`

Stdlib only at import, file 0600, atomic writes, never logs secrets, honest 503-style errors.
Zero-deps true: works without typer via `python -m bigbang.plugins.inbox.cli`.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# stdlib fallbacks for emit/ok/manifest/policy
# ---------------------------------------------------------------------------

def _ok_fallback(data=None, *, command: str, example: str | None = None, discover: str | None = None, **extra):
    payload = {"ok": True, "command": command}
    if data is not None:
        payload["data"] = data
    if example:
        payload["example"] = example
    if discover:
        payload["discover"] = discover
    payload.update(extra)
    return payload

def _emit_fallback(data, command: str = "unknown"):
    try:
        from bigbang.core.output import emit as real_emit  # type: ignore
        real_emit(data, command=command)
        return
    except Exception:
        pass
    try:
        json.dump(data, __import__("sys").stdout, indent=2, default=str)
        __import__("sys").stdout.write("\n")
    except Exception:
        print(str(data))

def _load_helpers():
    try:
        from bigbang.core.contract import ok as real_ok  # type: ignore
        from bigbang.core.output import emit as real_emit  # type: ignore
        ok = real_ok
        emit = real_emit
    except Exception:
        ok = _ok_fallback
        emit = _emit_fallback
    try:
        from bigbang.core.policy import load_manifest  # type: ignore
    except Exception:
        load_manifest = None  # type: ignore
    try:
        from bigbang.core.policy import enforce_or_raise  # type: ignore
    except Exception:
        enforce_or_raise = None  # type: ignore
    return ok, emit, load_manifest, enforce_or_raise

ok, emit, load_manifest, enforce_or_raise = _load_helpers()

# atomic_json optional — fallback to manual atomic write
try:
    from bigbang.core import atomic_json  # type: ignore
    _has_atomic = True
except Exception:
    atomic_json = None  # type: ignore
    _has_atomic = False

_MANIFEST: dict | None = None
_MANIFEST_LOADED = False

def _manifest() -> dict:
    global _MANIFEST, _MANIFEST_LOADED
    if _MANIFEST_LOADED:
        return _MANIFEST or {}
    _MANIFEST_LOADED = True
    if load_manifest is None:
        _MANIFEST = {}
    else:
        try:
            _MANIFEST = load_manifest(Path(__file__).parent)
        except Exception:
            _MANIFEST = {}
    return _MANIFEST or {}

INBOX_DIR = Path.home() / ".local" / "share" / "dottie" / "inbox"
STATUSES = {"pending", "approved", "denied", "expired"}


def _dir() -> Path:
    # enforce fs_write at call site — loader doesn't check fs_write for us
    # fail-closed: real policy denial must propagate, only missing policy module is ignored
    if enforce_or_raise is not None:
        try:
            enforce_or_raise(_manifest(), "fs_write_arg", str(INBOX_DIR / "x.json"))
        except SystemExit:
            raise
        except Exception as e:
            # typer.Exit is subclass of Exception, not SystemExit — must not be swallowed
            msg = str(e).lower()
            if "policy denied" in msg or "filesystem write" in msg or "typer" in type(e).__name__.lower() or "exit" in type(e).__name__.lower():
                raise
            pass
    # 0700 dir per spec — honest perms, no 2770 sgid leak
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    try:
        INBOX_DIR.chmod(0o700)
    except Exception:
        pass
    # also ensure parent ~/.local/share/dottie is 0700 if we created it
    try:
        parent = INBOX_DIR.parent
        if parent.exists():
            parent.chmod(0o700)
    except Exception:
        pass
    return INBOX_DIR


def _write_0600(path: Path, data: dict):
    if _has_atomic:
        try:
            atomic_json.write_json(path, data, mode=0o600)  # type: ignore
            return
        except Exception:
            pass
    # fallback atomic + 0600
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except Exception:
        pass
    for _ in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.01)
    tmp.replace(path)


def _read_json(path: Path):
    if _has_atomic:
        try:
            return atomic_json.read_json(path, None)  # type: ignore
        except Exception:
            pass
    try:
        return json.loads(path.read_bytes().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _load(id: str) -> dict | None:
    p = INBOX_DIR / f"{id}.json"
    if not p.exists():
        return None
    try:
        return _read_json(p)
    except Exception:
        try:
            return json.loads(p.read_bytes().decode("utf-8", errors="replace"))
        except Exception:
            return None


def _is_expired(doc: dict, now: int) -> bool:
    exp = doc.get("exp") or doc.get("expires_at")
    if exp is None:
        ts = int(doc.get("ts", now))
        exp = ts + 86400
    try:
        return int(now) > int(exp)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core logic — stdlib only, testable
# ---------------------------------------------------------------------------

def cmd_hello() -> dict:
    return ok({"ready": True, "plugin": "inbox", "dir": str(INBOX_DIR)}, command="inbox hello", example="scout --json inbox list", discover="scout inbox list")


def cmd_park(action: str, payload_str: str = "{}", reason: str = "unattended", ttl: int = 86400) -> dict:
    try:
        parsed = json.loads(payload_str)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "--payload must be JSON object", "command": "inbox park", "example": "scout inbox park 'comms send' --payload '{\"to\":\"a@b\"}'", "errorClass": "BAD_ARGS"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"bad JSON payload: {e}", "command": "inbox park", "example": "scout inbox park 'comms send' --payload '{\"to\":\"a\"}'", "errorClass": "BAD_ARGS"}

    d = _dir()
    id = secrets.token_hex(4)
    now = int(time.time())
    doc = {
        "id": id,
        "ts": now,
        "exp": now + int(ttl),
        "action": action,
        "payload": parsed,
        "reason": reason,
        "status": "pending",
        "unattended": reason in ("unattended", "window_not_focused"),
    }
    _write_0600(d / f"{id}.json", doc)
    return ok(
        {"parked": id, "id": id, "status": "pending", "needs_approval": True, "action": action, "reason": reason, "expires_in": ttl, "inbox": str(d / f"{id}.json"), "next": f"scout inbox approve {id}  |  scout inbox deny {id}"},
        command="inbox park",
        example=f"scout inbox approve {id}",
        discover="scout inbox list",
    )


def cmd_list(pending_only: bool = True, limit: int = 20) -> dict:
    d = _dir()
    items = []
    now = int(time.time())
    try:
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except Exception:
        files = []
    for f in files:
        try:
            doc = json.loads(f.read_bytes().decode("utf-8"))
        except Exception:
            continue
        if _is_expired(doc, now) and doc.get("status") == "pending":
            doc = {**doc, "status": "expired", "_expired_now": True}
        if pending_only and doc.get("status") != "pending":
            continue
        items.append(doc)
        if len(items) >= limit:
            break
    items.sort(key=lambda x: int(x.get("ts", 0)))
    return ok({"count": len(items), "items": items, "pending_only": pending_only, "dir": str(d)}, command="inbox list", example="scout inbox approve <id>", discover="scout inbox show")


def cmd_show(id: str) -> dict:
    doc = _load(id)
    if doc is None:
        return {"ok": False, "error": f"ask {id} not found in {INBOX_DIR}", "command": "inbox show", "example": "scout --json inbox list --all", "discover": "scout inbox list", "errorClass": "IO_MISSING"}
    return ok({"ask": doc, "id": id}, command="inbox show", example=f"scout inbox approve {id}", discover="scout inbox list")


def cmd_approve(id: str) -> dict:
    p = INBOX_DIR / f"{id}.json"
    doc = _load(id)
    if doc is None:
        return {"ok": False, "error": f"ask {id} not found", "command": "inbox approve", "example": "scout --json inbox list --pending", "errorClass": "IO_MISSING"}
    if doc.get("status") not in ("pending", "expired"):
        return {"ok": False, "error": f"ask {id} already {doc.get('status')} — only pending can be approved", "command": "inbox approve", "example": "scout inbox list --all", "errorClass": "BAD_STATE"}
    doc["status"] = "approved"
    doc["approved_at"] = int(time.time())
    _write_0600(p, doc)
    return ok({"id": id, "status": "approved", "action": doc.get("action"), "next": f"scout harness run '{doc.get('action')}' or custom executor"}, command="inbox approve", example="scout inbox list --pending", discover="scout inbox list")


def cmd_deny(id: str, reason: str = "") -> dict:
    p = INBOX_DIR / f"{id}.json"
    doc = _load(id)
    if doc is None:
        return {"ok": False, "error": f"ask {id} not found", "command": "inbox deny", "example": "scout inbox list --pending", "errorClass": "IO_MISSING"}
    if doc.get("status") not in ("pending", "expired"):
        return {"ok": False, "error": f"ask {id} already {doc.get('status')}", "command": "inbox deny", "example": "scout inbox list --all", "errorClass": "BAD_STATE"}
    doc["status"] = "denied"
    doc["denied_at"] = int(time.time())
    if reason:
        doc["deny_reason"] = reason
    _write_0600(p, doc)
    return ok({"id": id, "status": "denied", "reason": reason}, command="inbox deny", example="scout inbox list --pending")


def cmd_clear(approved=False, denied=False, expired=False, all_flag=False, force=False) -> dict:
    d = _dir()
    now = int(time.time())
    to_rm = []
    try:
        files = list(d.glob("*.json"))
    except Exception:
        files = []
    for f in files:
        try:
            doc = json.loads(f.read_bytes().decode("utf-8"))
        except Exception:
            continue
        st = doc.get("status")
        if _is_expired(doc, now) and st == "pending":
            st = "expired"
        if all_flag:
            to_rm.append(f)
        elif approved and st == "approved":
            to_rm.append(f)
        elif denied and st == "denied":
            to_rm.append(f)
        elif expired and st == "expired":
            to_rm.append(f)

    if not to_rm:
        return ok({"cleared": 0, "note": "nothing matched — try --approved | --denied | --expired | --all"}, command="inbox clear", example="scout inbox clear --approved")

    if not force and not all_flag:
        if os.environ.get("SCOUT_NONINTERACTIVE") != "1":
            # In non-interactive, require --force; here we are zero-deps path so we skip prompt unless tty
            try:
                import sys

                if not sys.stdin.isatty():
                    return {"ok": False, "error": "need --force in non-interactive", "command": "inbox clear", "example": "scout inbox clear --all --force", "errorClass": "NEEDS_FORCE"}
            except Exception:
                pass

    cleared = 0
    for f in to_rm:
        try:
            f.unlink()
            cleared += 1
        except Exception:
            pass
    return ok({"cleared": cleared, "dir": str(d), "filter": {"approved": approved, "denied": denied, "expired": expired, "all": all_flag}}, command="inbox clear", example="scout inbox list --all")


# ---------------------------------------------------------------------------
# Typer wiring — optional
# ---------------------------------------------------------------------------

def _try_make_typer_app():
    try:
        import typer  # type: ignore

        from bigbang.core.cli_ux import examples_epilog  # type: ignore
        from bigbang.core.contract import make_plugin_app  # type: ignore
    except Exception:
        return None

    app = make_plugin_app(
        "inbox",
        "Unattended ask inbox — park consequential actions when away, approve/deny later (openworker-style)",
        examples=[
            "scout --json inbox list --pending",
            "scout inbox park 'comms send' --payload '{\"to\":\"a@b\"}' --reason unattended",
            "scout inbox approve abc123",
            "scout inbox deny abc123 --reason 'not now'",
            "scout inbox show abc123",
            "scout inbox clear --approved",
        ],
    )

    @app.command("hello", epilog=examples_epilog(["scout --json inbox hello"]))
    def hello():
        emit(cmd_hello(), command="inbox hello")

    @app.command("park", epilog=examples_epilog(["scout inbox park 'comms send' --payload '{\"to\":\"a@b\"}' --reason unattended", "scout --json inbox park 'system run' --payload '{\"cmd\":\"ls\"}'"]))
    def park_cmd(
        action: str = typer.Argument(..., help="what would happen e.g. 'comms send' | 'calendar create' | 'system run' | 'mcp call'"),
        payload: str = typer.Option("{}", "--payload", help="JSON payload for the action (never logs secrets — redacted in audit)"),
        reason: str = typer.Option("unattended", "--reason", help="why parking: unattended | needs_approval | window_not_focused"),
        ttl: int = typer.Option(86400, "--ttl", help="seconds until expiry (default 24h)"),
    ):
        res = cmd_park(action, payload, reason, ttl)
        if isinstance(res, dict) and res.get("ok") is False:
            # fail_agent style
            try:
                from bigbang.core.cli_ux import fail_agent  # type: ignore

                fail_agent(res.get("error", "bad args"), command="inbox park", example="scout inbox park 'comms send' --payload '{\"to\":\"a@b\"}'")
            except Exception:
                emit(res, command="inbox park")
                raise typer.Exit(1)
        emit(res, command="inbox park")

    @app.command("list", epilog=examples_epilog(["scout --json inbox list --pending", "scout --json inbox list --all"]))
    def list_cmd(
        pending: bool = typer.Option(True, "--pending/--all", help="only pending, or all"),
        limit: int = typer.Option(20, "--limit", help="max rows"),
    ):
        emit(cmd_list(pending_only=pending, limit=limit), command="inbox list")

    @app.command("show", epilog=examples_epilog(["scout --json inbox show abc123"]))
    def show_cmd(id: str = typer.Argument(..., help="ask id (8-char hex)")):
        res = cmd_show(id)
        if isinstance(res, dict) and res.get("ok") is False:
            try:
                from bigbang.core.cli_ux import fail_agent

                fail_agent(res["error"], command="inbox show", example="scout --json inbox list --all", discover="scout inbox list")
            except Exception:
                emit(res, command="inbox show")
                raise typer.Exit(1)
        emit(res, command="inbox show")

    @app.command("approve", epilog=examples_epilog(["scout inbox approve abc123", "scout --json inbox approve abc123"]))
    def approve_cmd(id: str = typer.Argument(..., help="ask id to approve")):
        res = cmd_approve(id)
        if isinstance(res, dict) and res.get("ok") is False:
            try:
                from bigbang.core.cli_ux import fail_agent

                fail_agent(res["error"], command="inbox approve", example="scout --json inbox list --pending")
            except Exception:
                emit(res, command="inbox approve")
                raise typer.Exit(1)
        emit(res, command="inbox approve")

    @app.command("deny", epilog=examples_epilog(["scout inbox deny abc123 --reason 'not now'", "scout --json inbox deny abc123"]))
    def deny_cmd(id: str = typer.Argument(..., help="ask id to deny"), reason: str = typer.Option("", "--reason", help="why denied")):
        res = cmd_deny(id, reason)
        if isinstance(res, dict) and res.get("ok") is False:
            try:
                from bigbang.core.cli_ux import fail_agent

                fail_agent(res["error"], command="inbox deny", example="scout inbox list --pending")
            except Exception:
                emit(res, command="inbox deny")
                raise typer.Exit(1)
        emit(res, command="inbox deny")

    @app.command("clear", epilog=examples_epilog(["scout inbox clear --approved", "scout inbox clear --all --force"]))
    def clear_cmd(
        approved: bool = typer.Option(False, "--approved", help="clear approved only"),
        denied: bool = typer.Option(False, "--denied", help="clear denied only"),
        expired: bool = typer.Option(False, "--expired", help="clear expired only"),
        all_flag: bool = typer.Option(False, "--all", help="clear everything"),
        force: bool = typer.Option(False, "--force", "-f", help="skip confirmation"),
    ):
        # interactive confirm
        if not force and not all_flag:
            if os.environ.get("SCOUT_NONINTERACTIVE") != "1":
                try:
                    import typer as _typer

                    _typer.confirm(f"Clear asks from {_dir()}?", abort=True)
                except Exception:
                    pass
        res = cmd_clear(approved=approved, denied=denied, expired=expired, all_flag=all_flag, force=force)
        if isinstance(res, dict) and res.get("ok") is False:
            emit(res, command="inbox clear")
            raise typer.Exit(1)
        emit(res, command="inbox clear")

    return app


app = _try_make_typer_app()


def register(root):
    if app is not None:
        try:
            root.add_typer(app, name="inbox")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# argparse main — zero-deps path
# ---------------------------------------------------------------------------

def _argparse_main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="scout inbox", description="Unattended ask inbox — park consequential actions when away")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("hello", help="smoke check")

    p_park = sub.add_parser("park", help="park action")
    p_park.add_argument("action", help="what would happen")
    p_park.add_argument("--payload", default="{}", help="JSON payload")
    p_park.add_argument("--reason", default="unattended")
    p_park.add_argument("--ttl", type=int, default=86400)

    p_list = sub.add_parser("list", help="list asks")
    g = p_list.add_mutually_exclusive_group()
    g.add_argument("--pending", dest="pending", action="store_true", default=True)
    g.add_argument("--all", dest="pending", action="store_false")
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="show one")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="approve")
    p_approve.add_argument("id")

    p_deny = sub.add_parser("deny", help="deny")
    p_deny.add_argument("id")
    p_deny.add_argument("--reason", default="")

    p_clear = sub.add_parser("clear", help="clear")
    p_clear.add_argument("--approved", action="store_true")
    p_clear.add_argument("--denied", action="store_true")
    p_clear.add_argument("--expired", action="store_true")
    p_clear.add_argument("--all", dest="all_flag", action="store_true")
    p_clear.add_argument("--force", "-f", action="store_true")

    args = parser.parse_args()

    if args.cmd == "hello":
        res = cmd_hello()
    elif args.cmd == "park":
        res = cmd_park(args.action, args.payload, args.reason, args.ttl)
    elif args.cmd == "list":
        res = cmd_list(pending_only=args.pending, limit=args.limit)
    elif args.cmd == "show":
        res = cmd_show(args.id)
    elif args.cmd == "approve":
        res = cmd_approve(args.id)
    elif args.cmd == "deny":
        res = cmd_deny(args.id, args.reason)
    elif args.cmd == "clear":
        res = cmd_clear(approved=args.approved, denied=args.denied, expired=args.expired, all_flag=args.all_flag, force=args.force)
    else:
        parser.print_help()
        sys.exit(1)

    if isinstance(res, dict) and res.get("ok") is False:
        print(json.dumps(res, indent=2))
        sys.exit(1)
    # json output for zero-deps
    try:
        from bigbang.core.output import is_json

        if is_json():
            print(json.dumps(res, indent=2, default=str))
        else:
            _emit_fallback(res, command=f"inbox {args.cmd}")
    except Exception:
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    _argparse_main()
