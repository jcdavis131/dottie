"""Reach — the self-unblocking connect primitive. Pure-logic + policy-mutation
tests; no network. Verifies classification is evidence-bound and every unblock
plan hands back a runnable scout command."""

import importlib

import pytest

from bigbang.core import policy, reach


# ---- normalize / naming ----------------------------------------------------

@pytest.mark.parametrize("inp,expected", [
    ("api.github.com", "https://api.github.com"),
    ("localhost:8000", "http://localhost:8000"),
    ("127.0.0.1:3000/x", "http://127.0.0.1:3000/x"),
    ("http://plain.dev", "http://plain.dev"),
    ("https://secure.dev/openapi.json", "https://secure.dev/openapi.json"),
])
def test_normalize_target(inp, expected):
    assert reach.normalize_target(inp) == expected


@pytest.mark.parametrize("url,name", [
    ("https://api.github.com", "github"),
    ("http://localhost:8000", "localhost"),
    ("https://petstore3.swagger.io/api/v3", "petstore3"),
    ("https://www.example.co.uk", "example"),
])
def test_derive_tool_name(url, name):
    assert reach.derive_tool_name(url) == name


# ---- classification is evidence-bound --------------------------------------

def test_classify_openapi():
    body = {"openapi": "3.0.0", "paths": {"/a": {}, "/b": {}}}
    c = reach.classify(status=200, content_type="application/json",
                       body_text="", url="https://x/openapi.json", json_body=body)
    assert c["kind"] == "openapi" and c["confidence"] == 1.0
    assert "paths:2" in c["signals"]


def test_classify_auth_beats_body():
    c = reach.classify(status=401, content_type="application/json",
                       body_text="{}", url="https://api.x", json_body={"error": "no"})
    assert c["kind"] == "auth"


def test_classify_mcp_jsonrpc():
    c = reach.classify(status=200, content_type="application/json", body_text="",
                       url="https://x/mcp", json_body={"jsonrpc": "2.0", "result": {}})
    assert c["kind"] == "mcp" and "jsonrpc:2.0" in c["signals"]


def test_classify_mcp_by_sse_path():
    c = reach.classify(status=200, content_type="text/event-stream",
                       body_text="", url="https://x/sse", json_body=None)
    assert c["kind"] == "mcp"


def test_classify_html_scrapeable():
    c = reach.classify(status=200, content_type="text/html",
                       body_text="<!doctype html><html>hi", url="https://x", json_body=None)
    assert c["kind"] == "html"


def test_classify_empty_not_hopeful_json():
    # reachable but opaque must NOT be upgraded to json_api — no phantom capability
    c = reach.classify(status=204, content_type="", body_text="", url="https://x", json_body=None)
    assert c["kind"] == "empty"


def test_classify_transport_error():
    c = reach.classify(status=None, content_type="", body_text="",
                       url="https://nope", json_body=None, error="ConnectError: refused")
    assert c["kind"] == "error" and c["confidence"] == 1.0


# ---- well-known candidates -------------------------------------------------

def test_candidate_spec_urls_order():
    cands = reach.candidate_spec_urls("https://api.x.dev/v1")
    assert cands[0] == "https://api.x.dev/v1"  # as-given first
    assert "https://api.x.dev/openapi.json" in cands
    assert "https://api.x.dev/v3/api-docs" in cands
    assert len(cands) == len(set(cands))  # no dupes


# ---- the unblock planner: every fix is a runnable scout command ------------

def test_plan_policy_denied_is_first_and_only():
    steps = reach.plan_unblock({"url": "https://api.github.com", "policy_denied": True})
    assert len(steps) == 1
    assert steps[0]["blocker"] == "policy-denied"
    assert steps[0]["fix"] == "scout reach allow api.github.com"


def test_plan_auth_vaults_token():
    steps = reach.plan_unblock({"url": "https://api.github.com", "kind": "auth", "status": 401,
                                "suggested_name": "github"})
    assert steps[0]["fix"] == "scout secrets set GITHUB_TOKEN --stdin"
    assert any(s["fix"].startswith("scout reach ") for s in steps)


def test_plan_html_generates_scraper():
    steps = reach.plan_unblock({"url": "https://blog.x.dev", "kind": "html",
                                "suggested_name": "x"})
    assert steps[0]["blocker"] == "unstructured-source"
    assert "--from-scrape" in steps[0]["fix"]


def test_plan_mcp_forges_proxy():
    steps = reach.plan_unblock({"url": "https://x/mcp", "kind": "mcp", "suggested_name": "x"})
    assert steps[0]["fix"] == "scout forge from-mcp x https://x/mcp"


def test_plan_openapi_unregistered_says_register():
    steps = reach.plan_unblock({"url": "https://x/openapi.json", "kind": "openapi",
                                "registered": False})
    assert steps and "--register" in steps[0]["fix"]


def test_plan_openapi_registered_is_done():
    steps = reach.plan_unblock({"url": "https://x/openapi.json", "kind": "openapi",
                                "registered": True})
    assert steps == []


def test_plan_error_suggests_diagnose_before_giving_up():
    steps = reach.plan_unblock({"url": "https://x", "kind": "error", "tried_well_known": False})
    assert steps[0]["fix"] == "scout reach diagnose https://x"


def test_every_plan_fix_is_a_scout_command():
    for probe in (
        {"url": "https://a", "policy_denied": True},
        {"url": "https://a", "kind": "auth", "status": 403, "suggested_name": "a"},
        {"url": "https://a", "kind": "html", "suggested_name": "a"},
        {"url": "https://a", "kind": "mcp", "suggested_name": "a"},
        {"url": "https://a", "kind": "json_api", "suggested_name": "a", "tried_well_known": True},
    ):
        for step in reach.plan_unblock(probe):
            assert step["fix"].startswith("scout ")
            assert step["blocker"] and step["why"]


# ---- self-unblock: the policy mutation is real, auditable, default-deny-safe

def test_add_allowed_domain_persists_and_is_idempotent(tmp_path, monkeypatch):
    pf = tmp_path / "policy.yaml"
    monkeypatch.setenv("BIGBANG_POLICY_FILE", str(pf))
    importlib.reload(policy)

    ok1, _ = policy.add_allowed_domain("api.github.com")
    assert ok1 is True
    allowed, _ = policy.check_user_url("https://api.github.com/user")
    assert allowed is True
    # subdomain host still denied (dot-suffix only, no substring games)
    denied, _ = policy.check_user_url("https://evil.com/api.github.com")
    assert denied is False
    # idempotent
    ok2, _ = policy.add_allowed_domain("api.github.com")
    assert ok2 is False


def test_add_allowed_domain_refuses_wildcard(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGBANG_POLICY_FILE", str(tmp_path / "p.yaml"))
    importlib.reload(policy)
    ok, msg = policy.add_allowed_domain("*")
    assert ok is False and "refusing" in msg


def test_add_allowed_domain_accepts_url_extracts_host(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGBANG_POLICY_FILE", str(tmp_path / "p.yaml"))
    importlib.reload(policy)
    ok, msg = policy.add_allowed_domain("https://api.stripe.com/v1/charges")
    assert ok is True and "api.stripe.com" in msg
