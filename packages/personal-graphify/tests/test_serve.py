# Solo personal project, no connection to employer, built with public/free-tier only
"""serve.py — JSON-RPC notification handling and graph-path containment."""

import json

import pytest

from personal_graphify.serve import handle_stdio_line, handle_tool_call, load_graph


class TestStdioNotifications:
    def test_notifications_initialized_gets_no_reply(self):
        line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert handle_stdio_line(line) is None

    def test_any_idless_request_gets_no_reply(self):
        line = json.dumps({"jsonrpc": "2.0", "method": "tools/list"})
        assert handle_stdio_line(line) is None

    def test_initialize_with_id_replies(self):
        line = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        resp = handle_stdio_line(line)
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "personal-graphify"

    def test_unknown_method_with_id_gets_32601(self):
        line = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "does/not/exist"})
        resp = handle_stdio_line(line)
        assert resp["error"]["code"] == -32601

    def test_tools_list_with_id(self):
        line = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = handle_stdio_line(line)
        names = [t["name"] for t in resp["result"]["tools"]]
        assert "graphify_query" in names

    def test_garbage_line_gets_no_reply(self):
        assert handle_stdio_line("not json {") is None
        assert handle_stdio_line("   ") is None

    def test_simulated_session_through_loop_handler(self):
        """A realistic MCP handshake: initialize → notifications/initialized → tools/list."""
        session = [
            json.dumps(
                {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        ]
        replies = [handle_stdio_line(l) for l in session]
        assert replies[0] is not None and replies[0]["id"] == 0
        assert replies[1] is None  # the notification must be silently absorbed
        assert replies[2] is not None and replies[2]["id"] == 1


class TestGraphContainment:
    def test_load_graph_rejects_escaping_path(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"nodes": [], "edges": []}))
        with pytest.raises(ValueError):
            load_graph(str(outside), allowed_root=root)
        with pytest.raises(ValueError):
            load_graph(str(root / ".." / "outside.json"), allowed_root=root)

    def test_load_graph_allows_contained_path(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        gpath = root / "graph.json"
        gpath.write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "n1"}], "edges": []})
        )
        G, _resolved = load_graph(str(gpath), allowed_root=root)
        assert G.number_of_nodes() == 1

    def test_handle_tool_call_contains_graph_arg(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "secret.json"
        outside.write_text(json.dumps({"nodes": [], "edges": []}))
        result = handle_tool_call(
            "graphify_query",
            {"question": "x", "graph": str(outside)},
            allowed_root=root,
        )
        assert "error" in result
        assert "escapes root" in result["error"]
