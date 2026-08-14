"""Contacts plugin backed by the real acne package (skipped where acne absent).

acne is an editable install in the dev environment, not a locked dependency —
CI without it skips this module, matching the plugin's graceful-degradation
design.
"""

import json

import pytest

acne_tools = pytest.importorskip("acne.tools")

from typer.testing import CliRunner

from bigbang.plugins.contacts.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # acne's default store is ~/.agentic-contacts — isolate it per test.
    monkeypatch.setenv("HOME", str(tmp_path))


def test_resolve_empty_store_graceful():
    res = runner.invoke(app, ["resolve", "my designer", "--json"])
    assert res.exit_code == 0
    out = json.loads(res.stdout)
    assert out["contact"] is None
    assert "note" in out


def test_resolve_finds_seeded_contact(tmp_path):
    from acne.hub import ContactsHub

    hub = ContactsHub()  # default base under the isolated HOME
    hub.add_contact("Alex Rivera", email="alex@studio.com", role="designer", trigger="my designer")
    res = runner.invoke(app, ["resolve", "my designer", "--json"])
    assert res.exit_code == 0
    out = json.loads(res.stdout)
    assert out["contact"]["name"] == "Alex Rivera"
    assert out["confidence"] > 0


def test_stats_reports_real_store():
    res = runner.invoke(app, ["stats", "--json"])
    assert res.exit_code == 0
    out = json.loads(res.stdout)
    assert out["ok"] is True
    assert "contacts" in out and "tlpg" in out and "cache" in out


def test_search_empty_graph_graceful():
    res = runner.invoke(app, ["search", "anything", "--json"])
    assert res.exit_code == 0
    out = json.loads(res.stdout)
    assert out["count"] == 0
    assert "note" in out
