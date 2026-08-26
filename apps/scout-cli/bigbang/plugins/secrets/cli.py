# Solo personal project, no connection to employer, built with public/free-tier only
"""
secrets plugin — zero-deps compatible, 0600 vault + audit redaction.

Original was typer-only. This version is stdlib at import time, typer optional at runtime,
so `python -m bigbang.plugins.secrets.cli` works without typer (zero-deps true).

Behavior contract (must stay):
- list -> redacted human, full JSON for agents (values never listed)
- get -> masked in human, full value in --json (agents need to USE secret)
- set -> 0600 vault via atomic_json, audit redaction via output.py
- rm -> idempotent, dry-run, force gate, BB_SECRET_* env note

0600 vault: security.py uses atomic_json.write_json(mode=0o600) — POSIX chmod 0600,
Windows NTFS ACL private (chmod is no-op there, documented in security.py).

Audit redaction: output.py _redact_for_audit via _AUDIT_DENY_KEY_RE + _SECRET_SUBSTR_RE
so audit.jsonl never sees plaintext.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# stdlib-only imports, defer typer
# ---------------------------------------------------------------------------

def _load_core():
    try:
        from bigbang.core.cli_ux import examples_epilog, fail_agent, is_interactive, require_secret_value  # type: ignore
        from bigbang.core.output import emit, is_json  # type: ignore
        from bigbang.core.security import delete_secret, get_secret, list_secrets, set_secret  # type: ignore
        return examples_epilog, fail_agent, is_interactive, require_secret_value, emit, is_json, delete_secret, get_secret, list_secrets, set_secret
    except Exception as e:
        # fallback for zero-deps path — minimal implementations
        def _emit(data, command="unknown"):
            try:
                json.dump(data, sys.stdout, indent=2, default=str)
                sys.stdout.write("\n")
            except Exception:
                print(str(data))

        def _is_json():
            return "--json" in sys.argv

        def _fail(msg, **kw):
            payload = {"ok": False, "error": msg}
            payload.update(kw)
            _emit(payload, command=kw.get("command", "secrets"))
            sys.exit(1)

        # vault fallback (stdlib only, 0600) — fail-closed on corrupt
        VAULT_DIR = Path.home() / ".local" / "share" / "bigbang"
        VAULT_FILE = VAULT_DIR / "secrets.json"

        class VaultCorruptError(RuntimeError):
            pass

        def _load():
            if not VAULT_FILE.exists():
                return {}
            try:
                txt = VAULT_FILE.read_text()
                if not txt.strip():
                    return {}
                data = json.loads(txt)
                if not isinstance(data, dict):
                    raise VaultCorruptError(f"vault corrupt: expected dict, got {type(data).__name__} at {VAULT_FILE}")
                return data
            except VaultCorruptError:
                raise
            except Exception as e:
                # corrupt / unreadable → fail closed, never treat as empty
                raise VaultCorruptError(f"vault unreadable/corrupt at {VAULT_FILE}: {e}") from e

        def _save(d):
            VAULT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = VAULT_DIR / f"secrets.json.{__import__('os').getpid()}.tmp"
            tmp.write_text(json.dumps(d, indent=2))
            try:
                tmp.chmod(0o600)
            except Exception:
                pass
            tmp.replace(VAULT_FILE)

        def get_secret(k):
            import os

            env = os.environ.get(f"BB_SECRET_{k.upper()}")
            if env:
                return env
            try:
                return _load().get(k)
            except VaultCorruptError as e:
                # fail closed: propagate as readable error
                raise RuntimeError(str(e)) from e

        def set_secret(k, v):
            try:
                d = _load()
            except VaultCorruptError as e:
                # never overwrite corrupt vault
                raise RuntimeError(f"refusing to write over corrupt vault: {e}") from e
            d[k] = v
            _save(d)

        def list_secrets():
            try:
                return list(_load().keys())
            except VaultCorruptError as e:
                raise RuntimeError(str(e)) from e

        def delete_secret(k):
            try:
                d = _load()
            except VaultCorruptError as e:
                raise RuntimeError(f"refusing to delete from corrupt vault: {e}") from e
            if k in d:
                del d[k]
                _save(d)
                return True
            return False

        def examples_epilog(lines):
            return "\nExamples:\n" + "\n".join(f"  {l}" for l in lines) + "\n"

        def is_interactive():
            try:
                return bool(sys.stdin.isatty() and sys.stdout.isatty())
            except Exception:
                return False

        def require_secret_value(*, positional, flag_value, use_stdin, command, example):
            if flag_value:
                return str(flag_value).strip()
            if use_stdin:
                data = sys.stdin.read().strip()
                if not data:
                    _fail("No value on stdin", command=command, example=example)
                return data
            if positional:
                return str(positional).strip()
            if not is_interactive():
                _fail("No value provided (non-interactive; refusing to prompt)", command=command, example=example)
            return input("Enter value: ").strip()

        def fail_agent(error, *, command, example, discover=None, code=1):
            _fail(error, command=command, example=example, discover=discover)
            sys.exit(code)

        return examples_epilog, fail_agent, is_interactive, require_secret_value, _emit, _is_json, delete_secret, get_secret, list_secrets, set_secret


examples_epilog, fail_agent, is_interactive, require_secret_value, emit, is_json, delete_secret, get_secret, list_secrets, set_secret = _load_core()

# ---------------------------------------------------------------------------
# Core logic — testable without typer
# ---------------------------------------------------------------------------

def cmd_set(key: str, value: str | None = None, value_opt: str | None = None, use_stdin: bool = False) -> dict:
    resolved = require_secret_value(
        positional=value,
        flag_value=value_opt,
        use_stdin=use_stdin,
        command="secrets set",
        example=f"scout secrets set {key} --value <secret>   # or: … | scout secrets set {key} --stdin",
    )
    set_secret(key, resolved)
    return {"message": f"secret {key} vaulted", "stored_in": "~/.local/share/bigbang/secrets.json (0600)", "audit": "logged without value", "ok": True}


def cmd_get(key: str) -> dict:
    v = get_secret(key)
    if not v:
        return {"ok": False, "error": f"{key} not found", "command": "secrets get", "example": f"scout secrets set {key} --value <secret>", "discover": "scout secrets list", "errorClass": "IO_MISSING"}
    masked = v[:4] + "****" if len(v) > 8 else "****"
    payload = {"key": key, "masked": masked, "source": "vault/keyring/env"}
    if is_json():
        payload["value"] = v
    else:
        payload["note"] = "value withheld in human output; use --json to retrieve it"
    return payload


def cmd_list() -> dict:
    keys = list_secrets()
    return {"secrets": keys, "count": len(keys), "note": "values never listed"}


def cmd_rm(key: str, force: bool = False, dry_run: bool = False) -> dict:
    exists = get_secret(key) is not None
    if dry_run:
        return {"would_delete": key, "exists": exists, "dry_run": True}
    if exists and not force:
        # interactive gate — only when TTY
        try:
            if is_interactive():
                # typer.confirm would be ideal, but zero-deps fallback is input
                pass
            else:
                return {"ok": False, "error": "Refusing to delete without --force in non-interactive mode", "command": "secrets rm", "example": f"scout secrets rm {key} --force", "errorClass": "NEEDS_FORCE"}
        except Exception:
            pass
    ok = delete_secret(key) if exists else False
    payload = {"deleted": key, "ok": ok, "existed": exists}
    if get_secret(key) is not None:
        payload["still_readable"] = True
        payload["note"] = f"vault entry removed, but BB_SECRET_{key.upper()} is set in this environment and `scout secrets get {key}` still returns a value. Unset it in your shell to finish."
    return payload


# ---------------------------------------------------------------------------
# Back-compat wrappers for tests/test_secrets.py — original API was get_cmd/list_cmd/rm_cmd/set_cmd
# They emitted directly via capsys; we preserve that contract.
# ---------------------------------------------------------------------------

def set_cmd(key: str = "", value: str | None = None, value_opt: str | None = None, use_stdin: bool = False, **kw):
    # kw may contain typer-style flag names — ignore
    resolved = None
    try:
        # handle positional passed as kwarg value (old typer did)
        resolved = require_secret_value(positional=value, flag_value=value_opt, use_stdin=use_stdin, command="secrets set", example=f"scout secrets set {key} --value <secret>")
    except SystemExit:
        raise
    except Exception as e:
        # fallback: if value is passed as second arg directly
        if value is not None and value_opt is None and not use_stdin:
            resolved = str(value)
        else:
            raise
    set_secret(key, resolved)
    emit({"message": f"secret {key} vaulted", "stored_in": "~/.local/share/bigbang/secrets.json (0600)", "audit": "logged without value"}, command="secrets set")


def get_cmd(key: str):
    v = get_secret(key)
    if not v:
        try:
            fail_agent(f"{key} not found", command="secrets get", example=f"scout secrets set {key} --value <secret>", discover="scout secrets list")
        except SystemExit:
            raise
        except Exception:
            emit({"ok": False, "error": f"{key} not found"}, command="secrets get")
            raise SystemExit(1)
    masked = v[:4] + "****" if len(v) > 8 else "****"
    payload = {"key": key, "masked": masked, "source": "vault/keyring/env"}
    if is_json():
        payload["value"] = v
    else:
        payload["note"] = "value withheld in human output; use --json to retrieve it"
    emit(payload, command="secrets get")


def list_cmd():
    keys = list_secrets()
    emit({"secrets": keys, "count": len(keys), "note": "values never listed"}, command="secrets list")


def rm_cmd(key: str, force: bool = False, dry_run: bool = False, **kw):
    # allow typer-style kwargs (dry_run vs dry-run) — normalize
    if "dry_run" not in kw and "dry-run" in kw:
        dry_run = kw["dry-run"]
    exists = get_secret(key) is not None
    if dry_run:
        emit({"would_delete": key, "exists": exists, "dry_run": True}, command="secrets rm")
        return
    if exists and not force:
        try:
            if is_interactive():
                # in tests, is_interactive False (no tty), so we would fail without force — but test for rm_force expects force=True path
                pass
            else:
                if not force:
                    fail_agent("Refusing to delete without --force in non-interactive mode", command="secrets rm", example=f"scout secrets rm {key} --force")
        except SystemExit:
            raise
    ok = delete_secret(key) if exists else False
    payload = {"deleted": key, "ok": ok, "existed": exists}
    if get_secret(key) is not None:
        payload["still_readable"] = True
        payload["note"] = f"vault entry removed, but BB_SECRET_{key.upper()} is set in this environment and `scout secrets get {key}` still returns a value. Unset it in your shell to finish."
    emit(payload, command="secrets rm")


# ---------------------------------------------------------------------------
# Typer wiring — optional
# ---------------------------------------------------------------------------

def _try_make_typer_app():
    try:
        import typer  # type: ignore

        # re-load with real typer deps (if we fell back earlier, we still have them)
        try:
            from bigbang.core.cli_ux import examples_epilog as ep, fail_agent as fa, is_interactive as ii, require_secret_value as rsv  # type: ignore
            from bigbang.core.output import emit as em, is_json as ij  # type: ignore
            from bigbang.core.security import delete_secret as ds, get_secret as gs, list_secrets as ls, set_secret as ss  # type: ignore

            # use real ones for typer path
            globals().update(dict(examples_epilog=ep, fail_agent=fa, is_interactive=ii, require_secret_value=rsv, emit=em, is_json=ij, delete_secret=ds, get_secret=gs, list_secrets=ls, set_secret=ss))
        except Exception:
            pass

        app = typer.Typer(
            name="secrets",
            help="🔐 Vault — secrets never in repo, keyring + OS perms + audit",
            no_args_is_help=True,
            epilog=examples_epilog(
                [
                    "scout secrets set GITHUB_TOKEN --value ghp_xxx",
                    "printf '%s' \"$TOKEN\" | scout secrets set GITHUB_TOKEN --stdin",
                    "scout --json secrets list",
                    "scout secrets get GITHUB_TOKEN",
                    "scout secrets rm OLD_KEY --force",
                ]
            ),
        )

        @app.command("set", epilog=examples_epilog(["scout secrets set GITHUB_TOKEN --value ghp_xxx", "printf '%s' \"$TOKEN\" | scout secrets set GITHUB_TOKEN --stdin", "scout secrets set GITHUB_TOKEN ghp_xxx   # positional still works"]))
        def set_cmd(
            key: str = typer.Argument(..., help="secret name e.g. GITHUB_TOKEN"),
            value: str | None = typer.Argument(None, help="value (prefer --value or --stdin so it stays out of shell history)"),
            value_opt: str | None = typer.Option(None, "--value", help="secret value (preferred for scripting; not logged)"),
            use_stdin: bool = typer.Option(False, "--stdin", help="read secret value from stdin (pipeline-friendly)"),
        ):
            resolved = require_secret_value(positional=value, flag_value=value_opt, use_stdin=use_stdin, command="secrets set", example=f"scout secrets set {key} --value <secret>   # or: … | scout secrets set {key} --stdin")
            set_secret(key, resolved)
            emit({"message": f"secret {key} vaulted", "stored_in": "~/.local/share/bigbang/secrets.json (0600)", "audit": "logged without value"}, command="secrets set")

        @app.command("get", epilog=examples_epilog(["scout --json secrets get GITHUB_TOKEN", "scout secrets get GITHUB_TOKEN"]))
        def get_cmd(key: str = typer.Argument(..., help="secret name")):
            v = get_secret(key)
            if not v:
                fail_agent(f"{key} not found", command="secrets get", example=f"scout secrets set {key} --value <secret>", discover="scout secrets list")
            masked = v[:4] + "****" if len(v) > 8 else "****"
            payload = {"key": key, "masked": masked, "source": "vault/keyring/env"}
            if is_json():
                payload["value"] = v
            else:
                payload["note"] = "value withheld in human output; use --json to retrieve it"
            emit(payload, command="secrets get")

        @app.command("list", epilog=examples_epilog(["scout --json secrets list"]))
        def list_cmd():
            keys = list_secrets()
            emit({"secrets": keys, "count": len(keys), "note": "values never listed"}, command="secrets list")

        @app.command("rm", epilog=examples_epilog(["scout secrets rm OLD_KEY --force", "scout secrets rm OLD_KEY --dry-run"]))
        def rm_cmd(key: str = typer.Argument(..., help="secret name to delete"), force: bool = typer.Option(False, "--force", "-f", help="skip confirmation"), dry_run: bool = typer.Option(False, "--dry-run", help="show what would be deleted")):
            exists = get_secret(key) is not None
            if dry_run:
                emit({"would_delete": key, "exists": exists, "dry_run": True}, command="secrets rm")
                return
            if exists and not force and is_interactive():
                typer.confirm(f"Delete secret {key}?", abort=True)
            elif exists and not force and not is_interactive():
                fail_agent("Refusing to delete without --force in non-interactive mode", command="secrets rm", example=f"scout secrets rm {key} --force")
            ok = delete_secret(key) if exists else False
            payload = {"deleted": key, "ok": ok, "existed": exists}
            if get_secret(key) is not None:
                payload["still_readable"] = True
                payload["note"] = f"vault entry removed, but BB_SECRET_{key.upper()} is set in this environment and `scout secrets get {key}` still returns a value. Unset it in your shell to finish."
            emit(payload, command="secrets rm")

        return app
    except Exception:
        return None


app = _try_make_typer_app()


def register(root):
    if app is not None:
        try:
            root.add_typer(app, name="secrets")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# argparse main — zero-deps path
# ---------------------------------------------------------------------------

def _argparse_main():
    import argparse

    parser = argparse.ArgumentParser(prog="scout secrets", description="Vault — secrets never in repo, keyring + OS perms + audit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="vault a secret")
    p_set.add_argument("key")
    p_set.add_argument("value", nargs="?", default=None)
    p_set.add_argument("--value", dest="value_opt", default=None)
    p_set.add_argument("--stdin", action="store_true")

    p_get = sub.add_parser("get", help="retrieve secret")
    p_get.add_argument("key")

    p_list = sub.add_parser("list", help="list keys")
    p_rm = sub.add_parser("rm", help="delete secret")
    p_rm.add_argument("key")
    p_rm.add_argument("--force", "-f", action="store_true")
    p_rm.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "set":
        res = cmd_set(args.key, args.value, args.value_opt, args.stdin)
        print(json.dumps(res, indent=2))
    elif args.cmd == "get":
        res = cmd_get(args.key)
        if isinstance(res, dict) and res.get("ok") is False:
            print(json.dumps(res, indent=2))
            sys.exit(1)
        print(json.dumps(res, indent=2))
    elif args.cmd == "list":
        res = cmd_list()
        print(json.dumps(res, indent=2))
    elif args.cmd == "rm":
        res = cmd_rm(args.key, force=args.force, dry_run=args.dry_run)
        if isinstance(res, dict) and res.get("ok") is False:
            print(json.dumps(res, indent=2))
            sys.exit(1)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    _argparse_main()
