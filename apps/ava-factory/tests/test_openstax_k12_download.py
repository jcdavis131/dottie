"""Smoke test: OpenStax K12 catalog fetch shape (network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_openstax_k12.py"


def test_fetch_catalog_has_k12_math_and_pdfs():
    import importlib.util

    spec = importlib.util.spec_from_file_location("dl_osx", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    catalog = mod.fetch_catalog()
    assert len(catalog) >= 40
    live_pdfs = [b for b in catalog if b.get("pdf_url") and b.get("state") == "live"]
    assert len(live_pdfs) >= 40
    slugs = {b["slug"] for b in catalog}
    assert "algebra-1" in slugs
    assert "physics" in slugs
    # every live entry with pdf has a license url
    for b in live_pdfs[:10]:
        assert b.get("license_url")
        assert b.get("category")


def test_catalog_json_fixture_shape_if_present():
    root = Path(__file__).resolve().parents[1] / "data" / "research_inbox" / "openstax-k12"
    cat = root / "catalog.json"
    if not cat.exists():
        pytest.skip("openstax k12 not downloaded on this machine")
    data = json.loads(cat.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data
    assert any(b.get("slug") == "algebra-1" for b in data)
