"""`fetch_spec` must respect the default-deny network allowlist.

`scout forge from-openapi --url <anything>` reached fetch_spec with an arbitrary
user-supplied URL and called httpx.get on it directly. The CLI's network axis is
default-deny — policy.py writes a user policy whose own comment says "Add domains under
network.allowed_domains to allow outbound calls" — and this path never consulted it.
reach/cli.py:66 has gated its fetches all along; forge, the plugin that GENERATES other
plugins, did not.

Found 2026-08-02 by asking all 17 outbound-calling plugins the same question. Six
referenced no gate; four of those only reach localhost:11434 (Ollama), leaving forge and
rtx as real egress.

These tests never touch the network. They assert the gate fires BEFORE httpx is reached,
which is the whole property — a test that needed a live request could not distinguish
"denied" from "host unreachable".
"""

from __future__ import annotations

import pytest

from bigbang.core import openapi


@pytest.fixture
def deny_all(monkeypatch):
    monkeypatch.setattr(openapi, "_host_for_message", openapi._host_for_message)
    monkeypatch.setattr(
        "bigbang.core.policy.check_user_url",
        lambda url: (False, "user network allowlist is empty (default-deny)"),
    )


@pytest.fixture
def allow_all(monkeypatch):
    monkeypatch.setattr("bigbang.core.policy.check_user_url", lambda url: (True, "ok"))


@pytest.fixture
def no_network(monkeypatch):
    """Any httpx.get here is a test failure, not a network call."""
    def boom(*a, **kw):
        raise AssertionError(f"httpx.get was reached despite the gate: {a} {kw}")
    monkeypatch.setattr(openapi.httpx, "get", boom)


def test_denied_url_never_reaches_httpx(deny_all, no_network):
    """The core property. Fails loudly if the request is made and then judged."""
    with pytest.raises(PermissionError) as exc:
        openapi.fetch_spec("https://api.stripe.com/openapi.yaml")
    assert "api.stripe.com" in str(exc.value)


def test_the_denial_names_the_self_unblock_command(deny_all, no_network):
    """A gate that blocks without saying how to proceed gets worked around, not obeyed.

    `scout reach allow <host>` is the existing, auditable path (policy.add_allowed_domain);
    the message must point at it rather than leaving the user to find it.
    """
    with pytest.raises(PermissionError) as exc:
        openapi.fetch_spec("https://api.linear.app/openapi.json")
    msg = str(exc.value)
    assert "scout reach allow api.linear.app" in msg, msg


def test_an_allowed_url_is_not_blocked_by_the_gate(allow_all, monkeypatch):
    """Non-vacuity: the gate must be capable of passing.

    Without this, a fetch_spec that raised PermissionError unconditionally would satisfy
    every other test in this file.
    """
    class _Resp:
        url = "https://ok.example/spec.json"
        def raise_for_status(self): pass
        def json(self): return {"openapi": "3.0.0", "paths": {}}

    monkeypatch.setattr(openapi.httpx, "get", lambda *a, **kw: _Resp())
    assert openapi.fetch_spec("https://ok.example/spec.json") == {
        "openapi": "3.0.0", "paths": {}
    }


def test_a_redirect_off_the_allowlist_is_refused(monkeypatch):
    """follow_redirects=True is kept because real specs redirect, so the FINAL url is
    re-checked. The request to the redirect target has already happened — that residual
    gap is documented in fetch_spec — but its response must not be parsed and returned.
    """
    seen = []

    def fake_check(url):
        seen.append(url)
        return (url.startswith("https://ok.example"), "denied" if "evil" in url else "ok")

    monkeypatch.setattr("bigbang.core.policy.check_user_url", fake_check)

    class _Redirected:
        url = "https://evil.example/payload.json"
        def raise_for_status(self): pass
        def json(self): return {"openapi": "3.0.0"}

    monkeypatch.setattr(openapi.httpx, "get", lambda *a, **kw: _Redirected())
    with pytest.raises(PermissionError) as exc:
        openapi.fetch_spec("https://ok.example/spec.json")
    assert "redirected to" in str(exc.value)
    assert "evil.example" in str(exc.value)
    assert len(seen) == 2, f"both the initial and final URL must be checked, saw {seen}"
