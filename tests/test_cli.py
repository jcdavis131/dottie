"""Tests"""
def test_import():
    import bigbang.cli
    assert bigbang.cli.app

def test_plugin_list():
    from bigbang.core.plugin_loader import list_plugin_names
    names = list_plugin_names()
    assert "finance" in names
    assert "system" in names
