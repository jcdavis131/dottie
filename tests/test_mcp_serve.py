"""End-to-end test for `mcp serve`: real stdio handshake against the FastMCP server."""
import sys

import anyio
import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _run(coro):
    return anyio.run(lambda: coro)


def test_mcp_server_initialize_list_and_call():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bigbang.plugins.mcp.server", "stdio"],
    )

    async def scenario():
        with anyio.fail_after(90):
            await _scenario_body()

    async def _scenario_body():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "scout-cli"
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                # one tool per plugin
                assert "bb_tools" in names
                assert "bb_system" in names
                assert all(n.startswith("bb_") for n in names)
                # call a trivial tool: tools list
                result = await session.call_tool("bb_tools", {"args": "list"})
                assert not result.isError
                text = "".join(
                    c.text for c in result.content if getattr(c, "text", None)
                )
                assert "tools" in text or "count" in text

    _run(scenario())
