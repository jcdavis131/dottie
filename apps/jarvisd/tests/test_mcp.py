"""MCP round trips: in-process session and the real streamable-HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.memory import create_connected_server_and_client_session

from .conftest import BASE_URL

EXPECTED_TOOLS = {
    "jarvis.context",
    "jarvis.remember",
    "jarvis.recall",
    "jarvis.claim",
    "jarvis.release",
    "jarvis.claims",
    "jarvis.send",
    "jarvis.inbox",
    "jarvis.goal",
    "jarvis.goals",
    "jarvis.goal_done",
    "harness.route",
    "harness.run",
    "contacts.resolve",
    "graph.query",
    "jarvis.ask",
    "jarvis.status",
}


@pytest.mark.anyio
async def test_tools_list_in_process(app) -> None:
    mcp = app.state.mcp
    async with create_connected_server_and_client_session(mcp) as session:
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert EXPECTED_TOOLS <= names
        for t in tools.tools:
            assert "ctx" not in t.inputSchema.get("properties", {}), t.name
        res = await session.call_tool("jarvis.remember", {"text": "in-process memory", "agent": "memclient"})
        payload = json.loads(res.content[0].text)
        assert payload["ok"] and payload["memory"]["agent"] == "memclient"
        anon = json.loads((await session.call_tool("jarvis.status", {})).content[0].text)
        assert anon["ok"] and anon["counts"]["memories"] == 1


@pytest.mark.anyio
async def test_streamable_http_round_trip(app, bearer: str) -> None:
    def factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
        )

    headers = {"Authorization": f"Bearer {bearer}", "X-Agent-Id": "claude-code"}
    async with app.router.lifespan_context(app):
        async with streamablehttp_client(f"{BASE_URL}/mcp", headers=headers, httpx_client_factory=factory) as (r, w, _sid):
            async with ClientSession(r, w) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert EXPECTED_TOOLS <= names
                res = await session.call_tool("jarvis.remember", {"text": "written over streamable http", "scope": "repo:dottie"})
                mem = json.loads(res.content[0].text)["memory"]
                assert mem["agent"] == "claude-code"  # from X-Agent-Id, no explicit arg
                got = json.loads((await session.call_tool("jarvis.recall", {"query": "streamable"})).content[0].text)
                assert got["results"][0]["id"] == mem["id"]
                claim = json.loads((await session.call_tool("jarvis.claim", {"repo": "dottie", "area": "README"})).content[0].text)
                assert claim["ok"] and claim["claim"]["agent"] == "claude-code"
                ask = json.loads((await session.call_tool("jarvis.ask", {"question": "hi"})).content[0].text)
                assert ask["ok"] is False and ask["error"].startswith("brain unavailable")


@pytest.mark.anyio
async def test_streamable_http_requires_bearer(app) -> None:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as c:
            r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"Accept": "application/json, text/event-stream"})
            assert r.status_code == 401
            r = await c.get("/sse")
            assert r.status_code == 401
