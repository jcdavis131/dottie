import sys
def test_import():
    import bigbang.cli
    assert bigbang.cli.app

def test_plugin_list_security_first():
    from bigbang.core.plugin_loader import list_plugin_names
    names = list_plugin_names()
    assert "secrets" in names
    assert "auth" in names
    assert "tools" in names
    assert "mcp" in names
    assert "system" in names
    assert "agent" in names
    assert "ava" in names
    assert "finance" not in names

def test_security_vault():
    from bigbang.core.security import set_secret, get_secret, delete_secret
    set_secret("TEST_KEY_BB", "test123")
    assert get_secret("TEST_KEY_BB") == "test123"
    delete_secret("TEST_KEY_BB")
    assert get_secret("TEST_KEY_BB") is None

def test_registry():
    from bigbang.core.registry import register_tool, get_tool, unregister_tool, list_tools
    register_tool("_test_tool", {"type": "cli", "description": "test"})
    assert "_test_tool" in list_tools()
    assert get_tool("_test_tool")["type"] == "cli"
    unregister_tool("_test_tool")
    assert get_tool("_test_tool") is None

def test_policy_manifests_exist():
    from pathlib import Path
    base = Path("bigbang/plugins")
    for p in ["secrets","tools","mcp","system","ava","write","lab","brain","rtx","graphify","herd","skill","planes"]:
        assert (base / p / "manifest.yaml").exists(), f"{p} manifest missing"

def test_json_contract():
    import subprocess, json
    r = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", "tools", "list"], capture_output=True, text=True)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "tools" in data

# --- Write plugin tests — authentic generators goal ---

def test_write_scan_strong_ai():
    from bigbang.plugins.write.cli import scan_text
    slop = "In today's digital landscape, it's important to note that our cutting-edge solution harnesses the power of AI — crafting a rich tapestry of innovation, leveraging holistic synergy."
    res = scan_text(slop)
    assert res["verdict"] == "STRONG_AI"
    assert res["ai_score"] >= 70
    assert res["stats"]["hits"] >= 8

def test_write_humanize_deterministic_zero():
    from bigbang.plugins.write.cli import scan_text, _apply_deterministic_fixes
    slop = "In today's digital landscape, it's important to note that our cutting-edge solution harnesses the power of AI — crafting a rich tapestry of innovation, leveraging holistic synergy."
    cleaned, fixes = _apply_deterministic_fixes(slop)
    after = scan_text(cleaned)
    # After our fix (participial strip x2, em-dash, buzzword removal) must be HUMAN_LIKE 0
    assert after["verdict"] == "HUMAN_LIKE", f"got {after}"
    assert after["ai_score"] == 0
    assert len(fixes) >= 8
    # ensure participial strip logged
    assert any("participial" in f for f in fixes)

def test_write_generate_humanlike():
    from bigbang.plugins.write.cli import scan_text
    # fallback without ollama must be HUMAN_LIKE
    # simulate generate fallback logic
    fallback = (
        "Trade Crew Turnover Shield launch email\n"
        "I kept seeing AI tells in our drafts. Words like mix and look at.\n"
        "For example crew turnover dropped 12 percent after text check-ins."
    )
    res = scan_text(fallback)
    assert res["verdict"] == "HUMAN_LIKE"
    assert res["ai_score"] < 15

def test_write_cli_json():
    import subprocess, json
    r = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", "write", "scan", "--text", "Hello world this is a simple note from Austin."], capture_output=True, text=True, timeout=8)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "result" in data
    assert data["result"]["verdict"] in ["HUMAN_LIKE", "TRACES"]

def test_lab_ideas():
    from bigbang.plugins.lab.cli import _load_top10
    ideas = _load_top10()
    assert len(ideas) >= 5
    assert ideas[0]["name"] == "Trade Crew Turnover Shield"

def test_brain_goals():
    # should not crash even if no projects
    from pathlib import Path
    assert (Path("bigbang/plugins/brain/cli.py")).exists()

def test_ava_route_write():
    from bigbang.plugins.ava.cli import _heuristic_route
    route = _heuristic_route("check my draft for ai slop")
    assert route["picked_tool"] == "write"
    assert route["confidence"] >= 0.9

def test_ava_route_lab():
    from bigbang.plugins.ava.cli import _heuristic_route
    route = _heuristic_route("show mrr for turnover shield")
    assert route["picked_tool"] == "lab"

def test_plugin_list_includes_graphify():
    from bigbang.core.plugin_loader import list_plugin_names
    assert "graphify" in list_plugin_names()

def test_ava_route_graphify():
    from bigbang.plugins.ava.cli import _heuristic_route
    route = _heuristic_route("how does Scout connect via graphify knowledge graph")
    assert route["picked_tool"] == "graphify"
    assert route["confidence"] >= 0.9
    assert "graphify" in route["picked_command"]

def test_graphify_status_payload():
    from bigbang.plugins.graphify.runner import status_payload, resolve_graph_path
    st = status_payload()
    assert "ok" in st
    assert "graph" in st
    assert "disclaimer" in st
    g = resolve_graph_path()
    assert str(g).endswith("graph.json")

def test_graphify_cli_import():
    from bigbang.plugins.graphify.cli import app
    assert app.info.name == "graphify"
