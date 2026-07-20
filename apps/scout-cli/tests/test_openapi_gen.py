"""Test the generated plugin code path — real auth header lookup (finding #12)."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from bigbang.core.openapi import _collect_secret_headers, generate_typer_plugin

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "gentest", "description": "test spec"},
    "servers": [{"url": "http://localhost:9"}],
    "paths": {"/pets": {"get": {"operationId": "listPets", "summary": "list pets"}}},
}

TOOL = "gentest"
PLUGIN_DIR = Path("bigbang/plugins") / TOOL


@pytest.fixture()
def generated_plugin():
    files = generate_typer_plugin(TOOL, SPEC, "http://localhost:9/openapi.json")
    try:
        yield files
    finally:
        for mod in list(sys.modules):
            if mod.startswith(f"bigbang.plugins.{TOOL}"):
                del sys.modules[mod]
        shutil.rmtree(PLUGIN_DIR, ignore_errors=True)


def test_generated_auth_headers_real_lookup(generated_plugin, monkeypatch):
    src = (PLUGIN_DIR / "cli.py").read_text()
    # the vacuous `return {}` stub is gone; requests carry auth headers
    assert "_collect_secret_headers" in src
    assert "headers=_auth_headers() or None" in src

    mod = importlib.import_module(f"bigbang.plugins.{TOOL}.cli")
    # no secret configured -> honest empty headers
    monkeypatch.delenv("BB_SECRET_GENTEST_TOKEN", raising=False)
    monkeypatch.delenv("BB_SECRET_GENTEST", raising=False)
    assert mod._auth_headers() == {} or "Authorization" not in str(mod._auth_headers())

    # secret in vault (env layer) -> real Bearer header, mirroring the core call path
    monkeypatch.setenv("BB_SECRET_GENTEST_TOKEN", "tok-abc-123")
    headers = mod._auth_headers()
    assert headers == {"Authorization": "Bearer tok-abc-123"}
    assert headers == _collect_secret_headers(TOOL)


def test_generated_api_key_variant(generated_plugin, monkeypatch):
    mod = importlib.import_module(f"bigbang.plugins.{TOOL}.cli")
    monkeypatch.delenv("BB_SECRET_GENTEST_TOKEN", raising=False)
    monkeypatch.setenv("BB_SECRET_GENTEST_API_KEY", "key-xyz")
    headers = mod._auth_headers()
    assert headers == {"X-API-Key": "key-xyz"}
