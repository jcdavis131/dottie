"""Meta-MCP layer: namespace store, qualified names, filtering, aggregation, serve."""

import json

import pytest

from bigbang.plugins.mcp import meta

# ---------------------------------------------------------------------------
# Names and qualification
# ---------------------------------------------------------------------------


def test_valid_name_accepts_plain_identifiers():
    assert meta.valid_name("github")
    assert meta.valid_name("my-server_2")


def test_valid_name_rejects_separator_and_junk():
    # '__' would make split_qualified ambiguous; path-ish names never valid.
    assert not meta.valid_name("a__b")
    assert not meta.valid_name("")
    assert not meta.valid_name("../etc")
    assert not meta.valid_name("-leading")


def test_qualify_split_roundtrip():
    q = meta.qualify("github", "create_issue")
    assert q == "github__create_issue"
    assert meta.split_qualified(q) == ("github", "create_issue")


def test_split_qualified_first_separator_wins():
    # Downstream tool names may themselves contain '__'; server names cannot.
    assert meta.split_qualified("srv__tool__sub") == ("srv", "tool__sub")


def test_split_qualified_rejects_unqualified():
    assert meta.split_qualified("plain") is None
    assert meta.split_qualified("__tool") is None
    assert meta.split_qualified("srv__") is None


# ---------------------------------------------------------------------------
# Namespace store
# ---------------------------------------------------------------------------


def test_namespace_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "NAMESPACES_FILE", tmp_path / "ns.json")
    assert meta.load_namespaces() == {}
    db = {"work": meta.new_namespace()}
    db["work"]["servers"].append("github")
    meta.save_namespaces(db)
    loaded = meta.load_namespaces()
    assert loaded["work"]["servers"] == ["github"]
    assert loaded["work"]["disabled_tools"] == []


def test_tool_enabled_defaults_on_explicit_deny_off():
    cfg = meta.new_namespace()
    assert meta.tool_enabled(cfg, "srv__anything")
    cfg["disabled_tools"].append("srv__risky")
    assert not meta.tool_enabled(cfg, "srv__risky")
    assert meta.tool_enabled(cfg, "srv__safe")


# ---------------------------------------------------------------------------
# Aggregation — injected lister/policy, no network
# ---------------------------------------------------------------------------


def _servers_db():
    return {
        "alpha": {"url": "http://localhost:9001/sse"},
        "beta": {"url": "http://localhost:9002/sse"},
        "denied": {"url": "http://evil.example.com/sse"},
    }


def _lister(url):
    if "9001" in url:
        return [
            {"name": "search", "description": "find things", "inputSchema": {"type": "object"}},
            {"name": "fetch", "description": "", "inputSchema": {}},
        ]
    if "9002" in url:
        raise ConnectionError("connection refused")
    raise AssertionError(f"lister should never be called for {url}")


def _url_check(url):
    if "evil" in url:
        return False, "not in allowlist"
    return True, "ok"


def test_aggregate_qualifies_and_records_errors():
    cfg = meta.new_namespace()
    cfg["servers"] = ["alpha", "beta", "denied", "ghost"]
    agg = meta.aggregate_tools(cfg, _servers_db(), _lister, _url_check)
    names = {t["name"] for t in agg["tools"]}
    assert names == {"alpha__search", "alpha__fetch"}
    # Every skipped server is recorded, none silently dropped.
    assert "unreachable" in agg["errors"]["beta"]
    assert "policy denied" in agg["errors"]["denied"]
    assert "not registered" in agg["errors"]["ghost"]


def test_aggregate_marks_disabled_tools():
    cfg = meta.new_namespace()
    cfg["servers"] = ["alpha"]
    cfg["disabled_tools"] = ["alpha__fetch"]
    agg = meta.aggregate_tools(cfg, _servers_db(), _lister, _url_check)
    by_name = {t["name"]: t for t in agg["tools"]}
    assert by_name["alpha__search"]["enabled"]
    assert not by_name["alpha__fetch"]["enabled"]


def test_aggregate_denied_server_contributes_nothing():
    cfg = meta.new_namespace()
    cfg["servers"] = ["denied"]
    agg = meta.aggregate_tools(cfg, _servers_db(), _lister, _url_check)
    assert agg["tools"] == []


# ---------------------------------------------------------------------------
# Meta serve — build_server with a namespace, downstream faked
# ---------------------------------------------------------------------------


def test_build_server_exposes_enabled_proxies_and_status(monkeypatch):
    pytest.importorskip("mcp")
    import anyio

    from bigbang.plugins.mcp import server as srv

    cfg = meta.new_namespace()
    cfg["servers"] = ["alpha", "beta"]
    cfg["disabled_tools"] = ["alpha__fetch"]
    monkeypatch.setattr(meta, "load_namespaces", lambda: {"work": cfg})
    monkeypatch.setattr(meta, "load_servers", _servers_db)
    monkeypatch.setattr(
        "bigbang.core.mcp_client.list_mcp_tools_sync", _lister
    )
    monkeypatch.setattr("bigbang.core.policy.check_user_url", _url_check)

    server = srv.build_server(namespace="work")
    tools = anyio.run(server.list_tools)
    names = {t.name for t in tools}
    assert "alpha__search" in names
    assert "alpha__fetch" not in names  # disabled stays off the wire
    assert "meta_status" in names
    assert "scout_tools" in names  # native surface intact

    # The downstream input schema travels in the description so callers can
    # build correct args despite the uniform JSON-string convention.
    search = next(t for t in tools if t.name == "alpha__search")
    assert "find things" in search.description
    assert "JSON object string" in search.description


def test_build_server_unknown_namespace_raises(monkeypatch):
    pytest.importorskip("mcp")
    from bigbang.plugins.mcp import server as srv

    monkeypatch.setattr(meta, "load_namespaces", lambda: {})
    with pytest.raises(KeyError):
        srv.build_server(namespace="nope")


def test_proxy_tool_rechecks_policy_at_call_time(monkeypatch):
    pytest.importorskip("mcp")
    from bigbang.plugins.mcp import server as srv

    # Allowed at build, revoked before the call: the call must be refused.
    monkeypatch.setattr(
        "bigbang.core.policy.check_user_url", lambda url: (False, "revoked")
    )
    called = []
    monkeypatch.setattr(
        "bigbang.core.mcp_client.call_mcp_tool_sync",
        lambda url, tool, args: called.append(tool),
    )
    fn = srv._make_proxy_tool("http://localhost:9001/sse", "alpha", "search")
    out = json.loads(fn(args='{"q": "x"}'))
    assert out["ok"] is False
    assert "policy denied" in out["error"]
    assert called == []


def test_proxy_tool_happy_path_and_bad_json(monkeypatch):
    pytest.importorskip("mcp")
    from bigbang.plugins.mcp import server as srv

    monkeypatch.setattr(
        "bigbang.core.policy.check_user_url", lambda url: (True, "ok")
    )
    monkeypatch.setattr(
        "bigbang.core.mcp_client.call_mcp_tool_sync",
        lambda url, tool, args: {"echo": args},
    )
    fn = srv._make_proxy_tool("http://localhost:9001/sse", "alpha", "search")
    out = json.loads(fn(args='{"q": "x"}'))
    assert out == {
        "ok": True, "server": "alpha", "tool": "search", "result": {"echo": {"q": "x"}},
    }
    bad = json.loads(fn(args="{not json"))
    assert bad["ok"] is False
    assert "not valid JSON" in bad["error"]
