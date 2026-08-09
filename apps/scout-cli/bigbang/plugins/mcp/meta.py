"""Meta-MCP layer — aggregate registered downstream MCP servers into namespaces.

The shape mirrors MetaMCP (metatool-ai/metamcp): a namespace groups registered
servers, individual downstream tools can be disabled per namespace, and
`scout mcp serve --namespace <ns>` re-exposes the enabled remainder through
scout's own MCP endpoint as `<server>__<tool>` proxy tools.

Two stores under the plugin's declared write path (~/.local/share/bigbang/):
  mcp_servers.json     — server name -> {url, ...}   (owned by mcp add/list)
  mcp_namespaces.json  — namespace  -> {servers: [...], disabled_tools: [...]}

Server and namespace names must not contain the qualifier separator `__`,
so a qualified name always splits unambiguously on its FIRST `__`; downstream
tool names keep whatever the remote server called them.

Downstream availability never takes the meta endpoint down: a server that is
policy-denied or unreachable is SKIPPED and the skip is recorded (surfaced via
the meta_status tool and `ns tools` errors), never silently dropped. Policy is
the default-deny user URL allowlist — a denied server contributes no tools.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core.atomic_json import read_json, write_json

if TYPE_CHECKING:
    from collections.abc import Callable

_STATE_DIR = Path.home() / ".local" / "share" / "bigbang"
SERVERS_FILE = _STATE_DIR / "mcp_servers.json"
NAMESPACES_FILE = _STATE_DIR / "mcp_namespaces.json"

SEP = "__"
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def valid_name(name: str) -> bool:
    """True for names safe to use as namespace/server identifiers.

    Rejects the separator so split_qualified stays unambiguous.
    """
    return bool(_NAME_RE.fullmatch(name)) and SEP not in name


def qualify(server: str, tool: str) -> str:
    return f"{server}{SEP}{tool}"


def split_qualified(qualified: str) -> tuple[str, str] | None:
    """Split `<server>__<tool>` on the FIRST separator; None if unqualified."""
    if SEP not in qualified:
        return None
    server, tool = qualified.split(SEP, 1)
    if not server or not tool:
        return None
    return server, tool


def load_servers() -> dict[str, Any]:
    return read_json(SERVERS_FILE, {})


def load_namespaces() -> dict[str, Any]:
    return read_json(NAMESPACES_FILE, {})


def save_namespaces(db: dict[str, Any]) -> None:
    write_json(NAMESPACES_FILE, db)


def new_namespace() -> dict[str, Any]:
    return {"servers": [], "disabled_tools": []}


def tool_enabled(ns_cfg: dict[str, Any], qualified: str) -> bool:
    """Default-enabled; the disabled list is an explicit per-namespace deny."""
    return qualified not in set(ns_cfg.get("disabled_tools", []))


def aggregate_tools(
    ns_cfg: dict[str, Any],
    servers_db: dict[str, Any],
    lister: Callable[[str], list[dict[str, Any]]],
    url_check: Callable[[str], tuple[bool, str]],
) -> dict[str, Any]:
    """Aggregate live tool lists across a namespace's servers.

    `lister` and `url_check` are injected so callers choose transport and
    policy (and tests need no network). Returns every discovered tool with an
    `enabled` flag plus per-server errors for anything skipped — the caller
    decides whether to show disabled tools (listing) or drop them (serving).
    """
    tools: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for server in ns_cfg.get("servers", []):
        entry = servers_db.get(server)
        if not entry or not entry.get("url"):
            errors[server] = "not registered (scout mcp add)"
            continue
        url = entry["url"]
        ok, reason = url_check(url)
        if not ok:
            errors[server] = f"policy denied: {reason}"
            continue
        try:
            remote = lister(url)
        except Exception as e:
            errors[server] = f"unreachable: {e}"
            continue
        for t in remote:
            name = t.get("name") or "unknown"
            q = qualify(server, name)
            tools.append(
                {
                    "name": q,
                    "server": server,
                    "tool": name,
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                    "enabled": tool_enabled(ns_cfg, q),
                }
            )
    return {"tools": tools, "errors": errors}
