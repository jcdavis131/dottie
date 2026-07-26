
"""Tests for registry — universal tool registry"""
import importlib.util, json, pathlib
MOD_PATH = "/home/hatch/workspace/dottie/apps/scout-cli/bigbang/core/registry.py"
spec = importlib.util.spec_from_file_location("registry", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_registry_constants():
    assert hasattr(mod, "REG_DIR")
    assert hasattr(mod, "REG_FILE")

def test_register_and_get_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REG_DIR", tmp_path)
    monkeypatch.setattr(mod, "REG_FILE", tmp_path / "registry.json")
    mod.register_tool("my_tool", {"description":"desc","type":"tool","tags":["t"]})
    got = mod.get_tool("my_tool")
    assert got is not None
    assert got["description"] == "desc"
    assert "registered_at" in got

def test_list_tools_and_search(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REG_DIR", tmp_path)
    monkeypatch.setattr(mod, "REG_FILE", tmp_path / "registry.json")
    mod.register_tool("alpha_tool", {"description":"searchable alpha","type":"a","tags":["x"]})
    mod.register_tool("beta_tool", {"description":"beta","type":"b","tags":["y"]})
    lst = mod.list_tools()
    assert "alpha_tool" in lst
    res = mod.search_tools("alpha")
    assert any(r["name"]=="alpha_tool" for r in res)

def test_unregister_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REG_DIR", tmp_path)
    monkeypatch.setattr(mod, "REG_FILE", tmp_path / "registry.json")
    mod.register_tool("todelete", {"description":"d","type":"t"})
    assert mod.unregister_tool("todelete") is True
    assert mod.get_tool("todelete") is None
    assert mod.unregister_tool("nonexist") is False
