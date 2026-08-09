"""MCP action executor — namespaced downstream MCP tool calls for `harness run`.

Goal protocol: `mcp:<server>__<tool>` or `mcp:<server>__<tool> <json-object>`.
The qualified name reuses the meta-MCP separator contract (meta.split_qualified,
FIRST `__` wins), so a goal targets exactly one registered downstream tool.

Fail-closed ordering: every gate (namespace exists, server registered in the
namespace, tool enabled, policy allowlist) runs BEFORE the network client is
even imported — a disabled tool or policy-denied URL can never reach the wire.

Provenance doctrine: latency_ms is measured wall-clock (perf_counter) around
the whole action including pre-flight gates; tokens_est is MEASURED 0 — a
proxied MCP call makes no external-model calls inside scout; status reflects
what actually happened.
"""

from __future__ import annotations

import json
import time
from typing import Any

from bigbang.core import policy
from bigbang.plugins.mcp import meta

MCP_GOAL_PREFIX = "mcp:"

# Explicit vocabulary — execute_mcp_action never emits anything else.
ERROR_CLASSES = (
    "policy_denied",
    "unreachable",
    "downstream_error",
    "bad_args",
    "unknown_server",
    "disabled_tool",
    "namespace_missing",
)


def parse_mcp_goal(goal: str) -> dict[str, Any] | None:
    """Parse an `mcp:` goal into {ok, server, tool, args}.

    Returns None for non-mcp goals; {"ok": False, "error": ...} for malformed
    mcp goals (bad qualified name, bad JSON args) — the caller must not run
    a malformed goal.
    """
    if not goal.startswith(MCP_GOAL_PREFIX):
        return None
    rest = goal[len(MCP_GOAL_PREFIX):].strip()
    if not rest:
        return {"ok": False, "error": "empty mcp goal — expected mcp:<server>__<tool> [json-object-args]"}
    parts = rest.split(None, 1)
    qualified = parts[0]
    split = meta.split_qualified(qualified)
    if split is None:
        return {"ok": False, "error": f"bad qualified tool name {qualified!r} — expected <server>__<tool>"}
    server, tool = split
    args: dict[str, Any] = {}
    if len(parts) == 2 and parts[1].strip():
        try:
            parsed = json.loads(parts[1])
        except json.JSONDecodeError as err:
            return {"ok": False, "error": f"bad JSON args for {qualified}: {err}"}
        if not isinstance(parsed, dict):
            return {"ok": False, "error": f"mcp args must be a JSON object, got {type(parsed).__name__}"}
        args = parsed
    return {"ok": True, "server": server, "tool": tool, "args": args}


def _result(status: str, error_class: str | None, t0: float,
            payload: Any = None, error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "error_class": error_class,
        # measured wall-clock for the whole action, gates included
        "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        "tokens_est": 0,  # measured: no external-model call happens in scout for a proxied MCP call
        "payload": payload,
        "error": error,
    }


def execute_mcp_action(namespace: str, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute one namespaced downstream MCP tool call, fail-closed.

    Gate order (all before any network): args shape -> namespace exists ->
    server registered in namespace + servers db -> tool enabled -> user URL
    policy. Only then is the MCP client imported and the call made.
    """
    t0 = time.perf_counter()
    if not isinstance(args, dict):
        return _result("error", "bad_args", t0,
                       error=f"args must be a dict, got {type(args).__name__}")
    ns_cfg = meta.load_namespaces().get(namespace)
    if not isinstance(ns_cfg, dict):
        return _result("error", "namespace_missing", t0,
                       error=f"namespace {namespace!r} not found (scout mcp ns create)")
    entry = meta.load_servers().get(server)
    if server not in ns_cfg.get("servers", []) or not isinstance(entry, dict) or not entry.get("url"):
        return _result("error", "unknown_server", t0,
                       error=f"server {server!r} not registered in namespace {namespace!r} (scout mcp add)")
    qualified = meta.qualify(server, tool)
    if not meta.tool_enabled(ns_cfg, qualified):
        return _result("error", "disabled_tool", t0,
                       error=f"tool {qualified} is disabled in namespace {namespace!r}")
    url = str(entry["url"])
    ok, reason = policy.check_user_url(url)
    if not ok:
        return _result("error", "policy_denied", t0, error=reason)
    # Network client imported only after every gate passed — a denied/disabled
    # call must never even load the transport.
    from bigbang.core import mcp_client
    try:
        payload = mcp_client.call_mcp_tool_sync(url, tool, args)
    except ConnectionError as err:
        return _result("error", "unreachable", t0, error=str(err))
    except Exception as err:
        return _result("error", "downstream_error", t0, error=str(err))
    # The MCP protocol reports tool-level failure in-band (isError), not as a
    # transport exception — a successful round-trip can still be a failed call.
    if isinstance(payload, dict) and payload.get("isError"):
        return _result("error", "downstream_error", t0,
                       error=f"downstream reported isError: {payload.get('content')}")
    return _result("ok", None, t0, payload=payload)
