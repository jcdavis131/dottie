"""The action_operator tier: only the existing fail-closed MCP path, never a new one.

An outside-world side effect (``EXTERNAL_NOTIFY`` / ``WRITE_DESTRUCTIVE``) is
default-deny: this executor runs an ``mcp:`` goal only when the caller names an
enabled MCP namespace, through :func:`bigbang.plugins.harness.mcp_executor.execute_mcp_action`
(namespace/server gates and the default-deny user URL allowlist), and its
failures walk the one recovery ladder (``dottie_loop.execution.recovery_ladder``),
which never auto-retries these classes. The tier probe never calls it.
"""

from __future__ import annotations

import json
import time

from bigbang.plugins.harness import mcp_executor
from bigbang.plugins.harness.executors.base import ExecResult, NotApplicable


def run(goal: str, *, namespace: str = "") -> ExecResult:
    if not goal.startswith(mcp_executor.MCP_GOAL_PREFIX) or not namespace:
        raise NotApplicable("action_operator runs only mcp: goals with an explicit --mcp-namespace (default-deny)")
    parsed = mcp_executor.parse_mcp_goal(goal)
    if not parsed or not parsed.get("ok"):
        raise NotApplicable((parsed or {}).get("error", "unparseable mcp goal"))
    t0 = time.perf_counter()
    res = mcp_executor.execute_mcp_action(namespace, parsed["server"], parsed["tool"], parsed["args"])
    if res["status"] != "ok":
        raise RuntimeError(f"mcp {res['error_class']}: {res.get('error')}")
    text = json.dumps(res, default=str, sort_keys=True)
    return ExecResult(tier="action_operator", backend=f"mcp:{parsed['server']}", answer=text, text=text,
                      latency_ms=round((time.perf_counter() - t0) * 1000, 3), meta={"side_effect": "EXTERNAL_NOTIFY"})
