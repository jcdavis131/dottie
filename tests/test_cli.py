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
    for p in ["secrets","tools","mcp","system","ava"]:
        assert (base / p / "manifest.yaml").exists(), f"{p} manifest missing"

def test_json_contract():
    import subprocess, json
    r = subprocess.run(["python3", "-m", "bigbang.cli", "--json", "tools", "list"], capture_output=True, text=True)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "tools" in data
