"""Discovery — turn any internet thing into bb tool"""

import httpx


def fetch_openapi(url: str) -> dict:
    r = httpx.get(url, timeout=10, follow_redirects=True)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else {}


def discover_mcp_tools(server_url: str):
    """Discover tools on an MCP server — delegates to the real client in mcp_client.py.

    Returns [] on failure rather than a fake capability list: an agent must never
    plan against tools that were not actually discovered.
    """
    from bigbang.core.mcp_client import list_mcp_tools_sync

    try:
        tools = list_mcp_tools_sync(server_url)
        return [
            {"name": t.get("name"), "description": t.get("description", "")}
            for t in (tools or [])
        ]
    except Exception:
        return []
