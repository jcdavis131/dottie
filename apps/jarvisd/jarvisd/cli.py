"""`python -m jarvisd` — serve, export, token."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TYPE_CHECKING

from jarvisd import __version__
from jarvisd.config import DEFAULT_HOST, DEFAULT_PORT, Config, ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvisd", description="jarvisd — the Jarvis daemon")
    p.add_argument("--version", action="version", version=f"jarvisd {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the daemon (MCP at /mcp and /sse, JSON at /api/*)")
    s.add_argument("--host", default=None, help=f"bind host (JARVIS_HOST, default {DEFAULT_HOST})")
    s.add_argument("--port", type=int, default=None, help=f"bind port (JARVIS_PORT, default {DEFAULT_PORT})")
    s.add_argument("--db", default=None, help="SQLite path (JARVIS_DB)")
    s.add_argument("--bearer-env", default="JARVIS_BEARER", help="env var holding the static bearer (default JARVIS_BEARER)")
    s.add_argument("--public-host", default=None, help="public hostname for the DNS-rebinding allowlist (JARVIS_PUBLIC_HOST)")
    s.add_argument("--expose-scout", action="store_true", help="also register scout_<plugin> tools")
    s.add_argument("--sse", action=argparse.BooleanOptionalAction, default=True, help="mount the legacy SSE transport at /sse (default on)")
    s.add_argument("--log-level", default="info", help="uvicorn log level")

    e = sub.add_parser("export", help="dump one table as JSONL to stdout")
    e.add_argument("table", help="memories | claims | messages | goals | timeline | sessions")
    e.add_argument("--db", default=None, help="SQLite path (JARVIS_DB)")

    t = sub.add_parser("token", help="mint an ephemeral single-use token from the bearer")
    t.add_argument("--bearer-env", default="JARVIS_BEARER", help="env var holding the static bearer (default JARVIS_BEARER)")
    return p


def cmd_serve(args: argparse.Namespace) -> int:
    """Validate config, then block in uvicorn."""
    from jarvisd.app import serve

    try:
        config = Config.from_env(
            host=args.host,
            port=args.port,
            db=args.db,
            bearer_env=args.bearer_env,
            expose_scout=args.expose_scout,
            sse=args.sse,
            public_host=args.public_host,
        )
        config.validate()
    except ConfigError as e:
        print(f"jarvisd: {e}", file=sys.stderr)
        return 2
    if not config.auth_enabled:
        print(f"jarvisd: auth DISABLED (no {args.bearer_env}); loopback bind {config.host}:{config.port}", file=sys.stderr)
    serve(config, log_level=args.log_level)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Stream a table as JSONL."""
    from jarvisd.state import State

    config = Config.from_env(db=args.db)
    store = State(config.db_path)
    try:
        for row in store.export(args.table):
            sys.stdout.write(json.dumps(row, default=str) + "\n")
    except ValueError as e:
        print(f"jarvisd: {e}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    """Print one ephemeral token (valid ±90 s, single use)."""
    from jarvisd.auth import mint_token

    bearer = os.environ.get(args.bearer_env, "").strip()
    if not bearer:
        print(f"jarvisd: {args.bearer_env} is not set", file=sys.stderr)
        return 2
    print(mint_token(bearer))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    args = _parser().parse_args(argv)
    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "export":
        return cmd_export(args)
    if args.cmd == "token":
        return cmd_token(args)
    return 2  # pragma: no cover — argparse enforces the choices


__all__ = ["main"]
