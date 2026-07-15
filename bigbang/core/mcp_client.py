"""
Reusable MCP client — real SDK implementation using mcp Python SDK 1.28.1
Uses SSE transport first, falls back to streamable HTTP.
Exposes:
  async def list_mcp_tools(url) -> list[dict]
  async def call_mcp_tool(url, name, args) -> dict
  sync wrappers: list_mcp_tools_sync, call_mcp_tool_sync
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from bigbang.core.http_utils import sanitize_no_proxy_env
sanitize_no_proxy_env()

try:
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    import httpx as _httpx
    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    sse_client = None  # type: ignore
    ClientSession = None  # type: ignore
    streamablehttp_client = None  # type: ignore
    _httpx = None  # type: ignore
    _SDK_AVAILABLE = False


def _check_sdk():
    if not _SDK_AVAILABLE:
        raise RuntimeError(
            "mcp SDK not installed. Run: pip install 'mcp>=1.28.1' or pip install bigbang-cli[all]."
        )

def _mcp_http_client_factory(headers: dict | None = None, timeout: Any | None = None, auth: Any | None = None) -> Any:
    """Fix NO_PROXY and create httpx AsyncClient"""
    sanitize_no_proxy_env()
    if _httpx is None:
        raise ImportError("httpx not available")
    kw: dict[str, Any] = {"follow_redirects": True}
    if timeout is None:
        kw["timeout"] = _httpx.Timeout(30.0, read=300.0)
    else:
        kw["timeout"] = timeout
    if headers is not None:
        kw["headers"] = headers
    if auth is not None:
        kw["auth"] = auth
    return _httpx.AsyncClient(**kw)


async def list_mcp_tools(url: str) -> List[Dict[str, Any]]:
    _check_sdk()
    last_exc: Optional[Exception] = None
    for factory in [sse_client, streamablehttp_client]:
        if factory is None:
            continue
        try:
            async with factory(url, httpx_client_factory=_mcp_http_client_factory) as (read, write):  # type: ignore
                async with ClientSession(read, write) as session:  # type: ignore
                    await session.initialize()
                    resp = await session.list_tools()
                    tools_raw = getattr(resp, "tools", resp)
                    iterable = tools_raw if isinstance(tools_raw, (list, tuple)) else getattr(tools_raw, "tools", [])
                    out: List[Dict[str, Any]] = []
                    for t in iterable:
                        name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "unknown")  # type: ignore
                        desc = getattr(t, "description", "") or (t.get("description") if isinstance(t, dict) else "")  # type: ignore
                        schema = getattr(t, "inputSchema", {}) or (t.get("inputSchema") if isinstance(t, dict) else {})  # type: ignore
                        if hasattr(schema, "model_dump"):
                            try:
                                schema = schema.model_dump()  # type: ignore
                            except Exception:
                                schema = {}
                        out.append({"name": name, "description": desc or "", "inputSchema": schema or {}})
                    return out
        except Exception as e:
            last_exc = e
            continue
    raise ConnectionError(f"Failed to list tools from {url}: {last_exc}")

async def call_mcp_tool(url: str, tool_name: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    _check_sdk()
    args = args or {}
    last_exc: Optional[Exception] = None
    for factory in [sse_client, streamablehttp_client]:
        if factory is None:
            continue
        try:
            async with factory(url, httpx_client_factory=_mcp_http_client_factory) as (read, write):  # type: ignore
                async with ClientSession(read, write) as session:  # type: ignore
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=args)
                    # result may have content list
                    if hasattr(result, "model_dump"):
                        try:
                            return result.model_dump()  # type: ignore
                        except Exception:
                            pass
                    if hasattr(result, "content"):
                        return {"content": getattr(result, "content"), "raw": str(result)}
                    return {"result": result}
        except Exception as e:
            last_exc = e
            continue
    raise ConnectionError(f"Failed to call tool {tool_name} at {url}: {last_exc}")

def list_mcp_tools_sync(url: str) -> List[Dict[str, Any]]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # create new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                fut = ex.submit(asyncio.run, list_mcp_tools(url))
                return fut.result(timeout=30)
        else:
            return loop.run_until_complete(list_mcp_tools(url))
    except RuntimeError:
        return asyncio.run(list_mcp_tools(url))

def call_mcp_tool_sync(url: str, tool_name: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                fut = ex.submit(asyncio.run, call_mcp_tool(url, tool_name, args))
                return fut.result(timeout=30)
        else:
            return loop.run_until_complete(call_mcp_tool(url, tool_name, args))
    except RuntimeError:
        return asyncio.run(call_mcp_tool(url, tool_name, args))

# Solo personal project, no connection to employer, built with public/free-tier only
