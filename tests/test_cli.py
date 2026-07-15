def test_import():
    import bigbang.cli
    assert bigbang.cli.app

def test_plugin_list():
    from bigbang.core.plugin_loader import list_plugin_names
    names = list_plugin_names()
    assert "system" in names
    assert "vector" in names
    assert "mcp" in names
    assert "family" in names
    # ensure generic only
    assert "finance" not in names

def test_no_finance_settings():
    from bigbang.core.context import settings
    assert not hasattr(settings, 'emergency_target')
    assert hasattr(settings, 'ollama_url')
