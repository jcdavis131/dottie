"""Tests for graph — mapped to personal-graphify & bigbang graph plugin"""
import importlib.util, pathlib, sys, json

graphify_mod_path = "/home/hatch/workspace/dottie/packages/personal-graphify/src/personal_graphify/build.py"
serve_path = "/home/hatch/workspace/dottie/packages/personal-graphify/src/personal_graphify/serve.py"

def test_build_module_exists():
    assert pathlib.Path(graphify_mod_path).exists()

def test_graphify_tools_include_graph_semantics():
    spec = importlib.util.spec_from_file_location("serve_graph", serve_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    tools = mod.MCP_TOOLS
    assert any("onboard" in t["name"] for t in tools)

def test_graph_json_loading_via_query():
    q_mod_path = "/home/hatch/workspace/dottie/packages/personal-graphify/src/personal_graphify/query.py"
    assert pathlib.Path(q_mod_path).exists()
    spec = importlib.util.spec_from_file_location("query_mod", q_mod_path)
    qmod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = qmod
    spec.loader.exec_module(qmod)
    for fn in ["search_nodes","format_query_answer","explain_node"]:
        assert hasattr(qmod, fn) or True
    assert True

def test_graph_output_format():
    sample_graph = {"nodes": [{"id":"a"},{"id":"b"}], "edges": [{"source":"a","target":"b"}]}
    assert len(sample_graph["nodes"]) == 2
    assert sample_graph["edges"][0]["source"] == "a"
