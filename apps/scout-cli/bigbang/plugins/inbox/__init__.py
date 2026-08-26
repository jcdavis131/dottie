# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout inbox` — package marker, single source of truth is cli.py.

We deliberately avoid importing cli at package load time to prevent
circular import warnings when running `python -m bigbang.plugins.inbox.cli`.
Use `from bigbang.plugins.inbox.cli import ...` for direct access.
"""

from pathlib import Path

# Re-export for convenience via lazy import
def __getattr__(name):
    # Lazy re-export from cli to keep single source of truth without import-time cycle
    if name in {"cmd_park", "cmd_list", "cmd_show", "cmd_approve", "cmd_deny", "cmd_clear", "cmd_hello", "INBOX_DIR", "STATUSES", "app", "register"}:
        from . import cli as _cli
        return getattr(_cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Keep INBOX_DIR accessible without importing cli (for tests that check path)
INBOX_DIR = Path.home() / ".local" / "share" / "dottie" / "inbox"
STATUSES = {"pending", "approved", "denied", "expired"}
