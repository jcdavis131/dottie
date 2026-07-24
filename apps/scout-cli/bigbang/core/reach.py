# Solo personal project, no connection to employer, built with public/free-tier only
"""Reach — point Scout at ANY digital target; it classifies what it found and,
when blocked, emits a machine-actionable plan the LLM can run to unblock itself.

This is the thesis primitive: "one CLI to reach everything, smart enough to
recognize a shortcoming early, adapt, and hand the LLM the exact next command
to build the missing connection." Everything here is PURE logic — no network,
no filesystem, no DOM. The `reach` plugin CLI supplies real I/O (an httpx
fetch, the policy allowlist, the registry) and drives these functions, so the
hard parts are unit-testable offline and the LLM-facing contract is stable.

Two verbs an LLM cares about:
- classify(...)  -> what IS this target (openapi / mcp / graphql / json_api /
                    html / empty / error), with the signals that decided it.
- plan_unblock(probe) -> ordered [{blocker, fix, why}] steps, each `fix` a real
                    scout command, so a blocked agent can repair its own reach.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Well-known locations an OpenAPI/Swagger spec hides at, best-first. When a bare
# API root doesn't self-describe, `reach diagnose` walks these before giving up.
OPENAPI_WELL_KNOWN = (
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/v3/api-docs",
    "/api-docs",
    "/api/openapi.json",
    "/.well-known/openapi.json",
    "/swagger/v1/swagger.json",
)

# MCP servers speak JSON-RPC over HTTP/SSE; these are the conventional mounts.
MCP_WELL_KNOWN = ("/mcp", "/sse", "/message", "/mcp/sse")


def normalize_target(target: str) -> str:
    """Accept bare hosts, host:port, or full URLs; return a fetchable URL.

    Bare inputs default to https:// (the safe modern default); an explicit
    scheme is always honored. localhost/127.0.0.1 default to http:// because
    that is overwhelmingly what dev services speak.
    """
    t = str(target).strip()
    if not t:
        return t
    if "://" in t:
        return t
    host = t.split("/", 1)[0].split(":", 1)[0]
    scheme = "http" if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") else "https"
    return f"{scheme}://{t}"


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def derive_tool_name(url: str) -> str:
    """A short, stable registry name from a URL host (api.github.com -> github)."""
    host = host_of(normalize_target(url)) or "tool"
    labels = [p for p in host.split(".") if p not in ("www", "api", "app")]
    base = labels[0] if labels else host.replace(".", "-")
    name = re.sub(r"[^a-z0-9_-]", "-", base.lower()).strip("-")
    return name or "tool"


def _looks_like_openapi(body: Any) -> bool:
    return isinstance(body, dict) and (
        "openapi" in body or "swagger" in body
    ) and isinstance(body.get("paths", {}), dict)


def _looks_like_graphql_introspection(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("data"), dict) and (
        "__schema" in body["data"]
    )


def classify(
    *,
    status: int | None,
    content_type: str,
    body_text: str,
    url: str,
    json_body: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Decide what a probed target IS. Returns {kind, confidence, signals, detail}.

    kind ∈ {openapi, mcp, graphql, json_api, html, empty, auth, error}. Nothing
    is guessed past the evidence: an empty/opaque body classifies as `empty`,
    not as a hopeful `json_api`, so an agent never plans against a phantom.
    """
    ct = (content_type or "").lower()
    signals: list[str] = []

    if error:
        return {"kind": "error", "confidence": 1.0, "signals": [f"transport:{error}"],
                "detail": error}
    if status is not None and status in (401, 403):
        return {"kind": "auth", "confidence": 1.0,
                "signals": [f"http:{status}"], "detail": "authentication required"}

    if _looks_like_openapi(json_body):
        v = json_body.get("openapi") or json_body.get("swagger")
        n = len(json_body.get("paths", {}))
        return {"kind": "openapi", "confidence": 1.0,
                "signals": [f"openapi:{v}", f"paths:{n}"],
                "detail": f"OpenAPI {v} with {n} paths"}
    if _looks_like_graphql_introspection(json_body):
        return {"kind": "graphql", "confidence": 0.9, "signals": ["graphql:__schema"],
                "detail": "GraphQL endpoint (introspection responded)"}

    # MCP servers answer JSON-RPC; a JSON-RPC envelope or an SSE stream at an
    # /mcp-ish path is the tell.
    is_jsonrpc = isinstance(json_body, dict) and json_body.get("jsonrpc") == "2.0"
    path = urlparse(url).path.rstrip("/")
    if is_jsonrpc or "event-stream" in ct or path in MCP_WELL_KNOWN:
        conf = 0.9 if is_jsonrpc else 0.5
        if is_jsonrpc:
            signals.append("jsonrpc:2.0")
        if "event-stream" in ct:
            signals.append("sse")
        if path in MCP_WELL_KNOWN:
            signals.append(f"path:{path}")
        return {"kind": "mcp", "confidence": conf, "signals": signals,
                "detail": "likely MCP server"}

    if "json" in ct or json_body is not None:
        return {"kind": "json_api", "confidence": 0.7, "signals": [f"content-type:{ct or 'json'}"],
                "detail": "JSON API (no self-describing spec at this URL)"}

    body = body_text or ""
    if not body.strip():
        return {"kind": "empty", "confidence": 0.6, "signals": [f"http:{status}"],
                "detail": "reachable but empty/opaque body"}
    if "html" in ct or re.search(r"<html|<!doctype html", body[:512], re.I):
        return {"kind": "html", "confidence": 0.8, "signals": ["html"],
                "detail": "HTML page (scrapeable, not a structured API)"}
    return {"kind": "empty", "confidence": 0.3, "signals": [f"content-type:{ct or 'unknown'}"],
            "detail": "unrecognized body"}


def candidate_spec_urls(target: str) -> list[str]:
    """Well-known OpenAPI locations for a target's origin, best-first."""
    url = normalize_target(target)
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    seen: set[str] = set()
    out: list[str] = []
    # the URL as given first (it may already be the spec), then well-knowns
    for cand in (url, *[origin + s for s in OPENAPI_WELL_KNOWN]):
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def candidate_mcp_urls(target: str) -> list[str]:
    url = normalize_target(target)
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    return [url, *[origin + s for s in MCP_WELL_KNOWN]]


def plan_unblock(probe: dict[str, Any]) -> list[dict[str, str]]:
    """Given a probe result, return ordered self-unblock steps for the LLM.

    Each step is {blocker, fix, why} where `fix` is a runnable scout command.
    Empty list == nothing to unblock (already reachable and understood). This is
    the payload that turns "I'm blocked" into "run this next" without a human.
    """
    kind = probe.get("kind")
    url = probe.get("url", "")
    host = host_of(url) or url
    name = probe.get("suggested_name") or derive_tool_name(url)
    steps: list[dict[str, str]] = []

    if probe.get("policy_denied"):
        steps.append({
            "blocker": "policy-denied",
            "fix": f"scout reach allow {host}",
            "why": f"{host} is not in the network allowlist (default-deny); "
                   "allow it, then re-run the reach",
        })
        return steps  # nothing else is knowable until the call is permitted

    if kind == "auth":
        token_var = f"{name.upper()}_TOKEN"
        steps.append({
            "blocker": "auth-required",
            "fix": f"scout secrets set {token_var} --stdin",
            "why": f"target returned {probe.get('status')} — vault a credential as "
                   f"{token_var}, then retry (scout sends matching *_TOKEN headers)",
        })
        steps.append({
            "blocker": "auth-required",
            "fix": f"scout reach {url} --register",
            "why": "re-reach after the secret is set to complete registration",
        })
        return steps

    if kind in ("error", "empty") and probe.get("tried_well_known") is not True:
        steps.append({
            "blocker": "no-spec-at-url",
            "fix": f"scout reach diagnose {url}",
            "why": "no spec at the given URL — probe well-known OpenAPI/MCP "
                   "locations before treating it as unreachable",
        })
        return steps

    if kind == "html":
        steps.append({
            "blocker": "unstructured-source",
            "fix": f"scout forge new {name} --from-scrape {url}",
            "why": "target is an HTML page, not an API — generate a scraper tool "
                   "so the data becomes callable",
        })
        return steps

    if kind == "json_api":
        steps.append({
            "blocker": "no-openapi-spec",
            "fix": f"scout reach diagnose {url}",
            "why": "responds with JSON but exposes no spec here — check well-known "
                   "spec locations; if none, treat as a raw endpoint",
        })
        return steps

    if kind == "mcp":
        steps.append({
            "blocker": "mcp-not-registered",
            "fix": f"scout forge from-mcp {name} {url}",
            "why": "looks like an MCP server — generate a proxy plugin exposing "
                   "its tools",
        })
        return steps

    if kind == "openapi" and not probe.get("registered"):
        steps.append({
            "blocker": "not-registered",
            "fix": f"scout reach {url} --register",
            "why": "valid OpenAPI spec found — register it to make its operations "
                   "callable via scout tools call",
        })
    return steps
