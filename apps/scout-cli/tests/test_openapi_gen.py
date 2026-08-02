"""Test the generated plugin code path — real auth header lookup (finding #12)."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

import bigbang
from bigbang.core.openapi import _collect_secret_headers, generate_typer_plugin

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "gentest", "description": "test spec"},
    "servers": [{"url": "http://localhost:9"}],
    "paths": {"/pets": {"get": {"operationId": "listPets", "summary": "list pets"}}},
}

TOOL = "gentest"

# Derived from the PACKAGE, not the working directory. It was `Path("bigbang/plugins")`,
# which only resolved correctly when pytest happened to be invoked from apps/scout-cli.
# generate_typer_plugin writes to `<bigbang package>/plugins` — an absolute path built from
# its own __file__ — so from any other CWD the constant pointed at a directory that does
# not exist, `shutil.rmtree(..., ignore_errors=True)` silently cleaned up NOTHING, and the
# generated plugin was left in the real source tree.
#
# That is not hypothetical: on 2026-08-01 `make test` ran this suite from the repo root and
# left bigbang/plugins/gentest/ behind — cli.py, manifest.yaml, __init__.py — which
# surfaced as ruff debt jumping 252 -> 273 and a red check_documented_counts. The Makefile
# was fixed to run from the right directory (8b1a77d); this removes the landmine instead of
# routing around it, so the suite is safe from ANY working directory.
PLUGIN_DIR = Path(bigbang.__file__).resolve().parent / "plugins" / TOOL


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
        # Verify the removal instead of trusting ignore_errors. Scope, stated honestly:
        # this does NOT catch the CWD bug above — with a wrong PLUGIN_DIR the assertion
        # passes because that path never existed, and the test fails a line earlier on
        # read_text() anyway. The path derivation is the fix; this guards the OTHER case,
        # where PLUGIN_DIR is right and rmtree fails (locked file, permissions), which
        # ignore_errors would otherwise swallow into a polluted tree.
        assert not PLUGIN_DIR.exists(), (
            f"generated plugin survived cleanup at {PLUGIN_DIR} — it will pollute the "
            "source tree and show up as new lint findings"
        )


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
