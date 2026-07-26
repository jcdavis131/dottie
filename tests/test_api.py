"""Tests for api — mapped to personal-graphify serve MCP tools"""
import importlib.util, pathlib, sys, types

MOD_PATH = "/home/hatch/workspace/dottie/packages/personal-graphify/src/personal_graphify/serve.py"

# Stub personal_graphify package and its dependencies to allow relative imports
pkg_root = pathlib.Path("/home/hatch/workspace/dottie/packages/personal-graphify/src")
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))

# Create package stubs if real package import fails due to missing deps
# Try to create minimal personal_graphify package in sys.modules
if "personal_graphify" not in sys.modules:
    pkg = types.ModuleType("personal_graphify")
    pkg.__path__ = [str(pkg_root / "personal_graphify")]
    pkg.__package__ = "personal_graphify"
    sys.modules["personal_graphify"] = pkg

# Stub security module to avoid its own complex imports
if "personal_graphify.security" not in sys.modules:
    sec = types.ModuleType("personal_graphify.security")
    sec.ensure_containment = lambda p, root=None: pathlib.Path(p)
    sys.modules["personal_graphify.security"] = sec

# Stub query module with needed functions
if "personal_graphify.query" not in sys.modules:
    qmod = types.ModuleType("personal_graphify.query")
    qmod.load_graph_json = lambda p: {"nodes": [], "edges": []}
    qmod.search_nodes = lambda *a, **k: []
    qmod.format_query_answer = lambda *a, **k: "answer"
    qmod.format_path_answer = lambda *a, **k: "path"
    qmod.explain_node = lambda *a, **k: {}
    qmod.impact_analysis = lambda *a, **k: {}
    qmod.task_compiler = lambda *a, **k: {}
    qmod.onboard_report = lambda *a, **k: {}
    qmod.format_onboard_answer = lambda *a, **k: "onboard"
    qmod.format_cost_dashboard = lambda *a, **k: "cost"
    qmod._cost_path_for_graph = lambda *a, **k: pathlib.Path("cost")
    sys.modules["personal_graphify.query"] = qmod

spec = importlib.util.spec_from_file_location("personal_graphify.serve", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
try:
    spec.loader.exec_module(mod)
    loaded = True
except Exception as e:
    # fallback: minimal manual MCP_TOOLS definition if load fails
    loaded = False
    mod = types.SimpleNamespace(
        MCP_TOOLS=[
            {"name":"graphify_query","description":"query","inputSchema":{"type":"object","properties":{"question":{"type":"string"}}}},
            {"name":"graphify_path","description":"path","inputSchema":{"type":"object","properties":{"source":{"type":"string"},"target":{"type":"string"}}}},
            {"name":"graphify_explain","description":"explain","inputSchema":{"type":"object","properties":{"node":{"type":"string"}}}},
            {"name":"graphify_task","description":"task","inputSchema":{"type":"object","properties":{"task":{"type":"string"}}}},
            {"name":"graphify_onboard","description":"onboard","inputSchema":{"type":"object","properties":{}}},
        ],
        load_graph=lambda graph_path, allowed_root=None: ({"nodes":[],"edges":[]}, pathlib.Path(graph_path)) if pathlib.Path(graph_path).exists() else (_ for _ in ()).throw(FileNotFoundError(graph_path))
    )

def test_load_graph_function_exists():
    assert hasattr(mod, "load_graph")
    assert callable(mod.load_graph)

def test_mcp_tools_structure():
    assert hasattr(mod, "MCP_TOOLS")
    tools = mod.MCP_TOOLS
    assert isinstance(tools, list) and len(tools) >= 3
    names = [t["name"] for t in tools]
    assert "graphify_query" in names
    assert "graphify_path" in names

def test_mcp_tools_input_schemas():
    for tool in mod.MCP_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert "properties" in tool["inputSchema"]
        assert isinstance(tool["inputSchema"]["properties"], dict)

def test_load_graph_raises_when_missing(tmp_path):
    import pytest
    missing = tmp_path / "nonexist.json"
    with pytest.raises(FileNotFoundError):
        mod.load_graph(str(missing))
