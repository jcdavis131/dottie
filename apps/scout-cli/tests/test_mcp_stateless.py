"""Stateless streamable-HTTP mode: real server, no client-side session reuse.

The current MCP spec treats stateless streamable-HTTP as first-class — each
request is self-contained, with no server-side session continuity required
(the mode that matters for serverless/scale-out hosting). These tests prove:

  (a) two independent bigbang.core.mcp_client round-trips (list then call)
      against a real `build_server(stateless=True)` server both succeed with
      no session state shared between the calls — mcp_client.py's sync
      wrappers already open a fresh streamablehttp_client per call and never
      persist a session id, so this should (and does) already hold;
  (b) a namespace-mode stateless server still proxies downstream tools
      correctly, and the proxy tool's per-call policy recheck still runs live
      over the real HTTP transport (reusing test_mcp_meta.py's injected
      lister/url_check/call test-double pattern — no network);
  (c) `--stateless` paired with stdio is rejected with a clear error rather
      than silently accepted as a no-op, both at the `run_server()` level and
      through the `scout mcp serve` CLI.

The server is served for real via a background uvicorn thread bound to a free
127.0.0.1 port — FastMCP.streamable_http_app() returns a Starlette app whose
lifespan starts/stops the StreamableHTTPSessionManager, which uvicorn's normal
ASGI lifespan handling drives automatically.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from unittest import mock

import pytest

mcp = pytest.importorskip("mcp")
uvicorn = pytest.importorskip("uvicorn")

from typer.testing import CliRunner

from bigbang.core.mcp_client import call_mcp_tool_sync, list_mcp_tools_sync
from bigbang.plugins.mcp import meta
from bigbang.plugins.mcp import server as srv
from bigbang.plugins.mcp.cli import app

runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _BackgroundServer:
    """Real FastMCP streamable-HTTP app served on a background uvicorn thread."""

    def __init__(self, app, port: int):
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("uvicorn server did not start within 10s")
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)


# ---------------------------------------------------------------------------
# (a) No session reuse across independent calls, real scout_* surface.
# ---------------------------------------------------------------------------


def test_stateless_server_two_independent_roundtrips_no_shared_session():
    port = _free_port()
    fmcp = srv.build_server(port=port, stateless=True)
    url = f"http://127.0.0.1:{port}/mcp"

    with _BackgroundServer(fmcp.streamable_http_app(), port):
        # Call 1: list, then call a trivial tool. Each of list_mcp_tools_sync
        # and call_mcp_tool_sync opens its own streamablehttp_client context
        # and tears it down before returning — nothing here shares state with
        # what follows.
        tools_1 = list_mcp_tools_sync(url)
        names_1 = {t["name"] for t in tools_1}
        assert "scout_tools" in names_1
        result_1 = call_mcp_tool_sync(url, "scout_tools", {"args": "list"})
        assert result_1["isError"] is False

        # Call 2: a fresh, unrelated pair of round-trips. If the client (or
        # server, in stateless mode) required a remembered session id from
        # call 1, this would fail.
        tools_2 = list_mcp_tools_sync(url)
        names_2 = {t["name"] for t in tools_2}
        assert names_2 == names_1
        result_2 = call_mcp_tool_sync(url, "scout_tools", {"args": "list"})
        assert result_2["isError"] is False


# ---------------------------------------------------------------------------
# (b) Namespace-mode stateless server: real proxying + live policy recheck.
# ---------------------------------------------------------------------------


def _servers_db():
    return {"alpha": {"url": "http://localhost:9001/sse"}}


def _lister(url):
    return [
        {"name": "search", "description": "find things", "inputSchema": {"type": "object"}},
    ]


def _proxy_text(call_result: dict) -> dict:
    text = call_result["content"][0]["text"]
    return json.loads(text)


def test_stateless_namespace_server_proxies_and_rechecks_policy_live():
    port = _free_port()
    cfg = meta.new_namespace()
    cfg["servers"] = ["alpha"]

    allowed = {"ok": True}

    def _url_check(url):
        return (allowed["ok"], "ok" if allowed["ok"] else "revoked")

    downstream_calls = []

    def _fake_downstream_call(url, tool, args):
        downstream_calls.append((url, tool, args))
        return {"echo": args}

    # server.py imports these lazily (module-path-qualified) inside the
    # functions that use them, so string-path patching — same pattern as
    # test_mcp_meta.py — takes effect both at build time (aggregate_tools)
    # and on every live proxy call (proxy_fn's own lazy import).
    patches = (
        mock.patch.object(meta, "load_namespaces", lambda: {"work": cfg}),
        mock.patch.object(meta, "load_servers", _servers_db),
        mock.patch("bigbang.core.mcp_client.list_mcp_tools_sync", _lister),
        mock.patch("bigbang.core.policy.check_user_url", _url_check),
        mock.patch(
            "bigbang.core.mcp_client.call_mcp_tool_sync", _fake_downstream_call
        ),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        fmcp = srv.build_server(port=port, namespace="work", stateless=True)
        url = f"http://127.0.0.1:{port}/mcp"

        with _BackgroundServer(fmcp.streamable_http_app(), port):
            tools = list_mcp_tools_sync(url)
            names = {t["name"] for t in tools}
            assert "alpha__search" in names  # proxied downstream tool
            assert "meta_status" in names
            assert "scout_tools" in names  # native surface intact

            # Allowed: the proxy call reaches the (faked) downstream.
            result = call_mcp_tool_sync(
                url, "alpha__search", {"args": json.dumps({"q": "x"})}
            )
            payload = _proxy_text(result)
            assert payload == {
                "ok": True, "server": "alpha", "tool": "search",
                "result": {"echo": {"q": "x"}},
            }
            assert downstream_calls == [
                ("http://localhost:9001/sse", "search", {"q": "x"})
            ]

            # Revoke policy with the server already running (no restart) and
            # confirm the NEXT call is refused — proves the recheck is live,
            # per-call, not a startup-time snapshot.
            allowed["ok"] = False
            result_2 = call_mcp_tool_sync(
                url, "alpha__search", {"args": json.dumps({"q": "y"})}
            )
            payload_2 = _proxy_text(result_2)
            assert payload_2["ok"] is False
            assert "policy denied" in payload_2["error"]
            # No new downstream call was made for the denied attempt.
            assert downstream_calls == [
                ("http://localhost:9001/sse", "search", {"q": "x"})
            ]


# ---------------------------------------------------------------------------
# (c) --stateless is meaningless on stdio: rejected, not silently ignored.
# ---------------------------------------------------------------------------


def test_stateless_with_stdio_transport_is_rejected_at_run_server():
    with pytest.raises(ValueError, match="stdio"):
        srv.run_server(transport="stdio", stateless=True)


def test_stateless_with_sse_transport_is_also_rejected_at_run_server():
    # stateless_http is wired into FastMCP ONLY inside streamable_http_app()
    # (StreamableHTTPSessionManager) — sse_app() never reads
    # self.settings.stateless_http at all (confirmed by reading the installed
    # mcp SDK: fastmcp/server.py references stateless_http exactly once, and
    # it's inside streamable_http_app(), not sse_app()). So --sse --stateless
    # would be every bit as silent a no-op as --stdio --stateless, and must be
    # rejected the same way rather than accepted and quietly ignored.
    with pytest.raises(ValueError, match="sse"):
        srv.run_server(transport="sse", stateless=True)


def test_stateless_with_streamable_http_is_not_rejected():
    # Sanity: the ValueError is specific to non-streamable-http transports,
    # not to stateless=True in general. build_server() itself never blocks on
    # transport, so we only need to prove run_server()'s guard doesn't fire
    # for the one transport stateless_http actually affects — constructing
    # the FastMCP object is enough, without actually serving.
    with mock.patch("bigbang.plugins.mcp.server.build_server") as build:
        build.return_value.run.return_value = None
        srv.run_server(transport="streamable-http", stateless=True)
        build.assert_called_once_with(port=8787, namespace=None, stateless=True)
        build.return_value.run.assert_called_once_with(transport="streamable-http")


def test_cli_serve_stateless_with_stdio_is_rejected():
    result = runner.invoke(app, ["serve", "--stateless"])
    assert result.exit_code == 1


def test_cli_serve_stateless_with_sse_is_rejected():
    # Same silent-no-op hazard as stdio+stateless (see
    # test_stateless_with_sse_transport_is_also_rejected_at_run_server) —
    # must surface as a real CLI error, not exit 0 while quietly doing
    # nothing with --stateless.
    result = runner.invoke(app, ["serve", "--sse", "--stateless"])
    assert result.exit_code == 1


def test_cli_serve_sse_alias_still_resolves_to_sse_transport():
    # Exact backward compat: `--sse` alone (no --transport) must still resolve
    # to transport="sse" — same as before --transport existed. We stop short
    # of actually serving (which blocks) by faking run_server.
    with mock.patch("bigbang.plugins.mcp.server.run_server") as run:
        result = runner.invoke(app, ["serve", "--sse", "--port", "9999"])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(
            transport="sse", port=9999, namespace=None, stateless=False
        )


def test_cli_serve_transport_streamable_http_with_stateless():
    with mock.patch("bigbang.plugins.mcp.server.run_server") as run:
        result = runner.invoke(
            app, ["serve", "--transport", "streamable-http", "--stateless", "--port", "9998"]
        )
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(
            transport="streamable-http", port=9998, namespace=None, stateless=True
        )


def test_cli_serve_conflicting_sse_and_transport_rejected():
    result = runner.invoke(
        app, ["serve", "--sse", "--transport", "streamable-http"]
    )
    assert result.exit_code == 1


def test_cli_serve_invalid_transport_rejected():
    result = runner.invoke(app, ["serve", "--transport", "carrier-pigeon"])
    assert result.exit_code == 1
