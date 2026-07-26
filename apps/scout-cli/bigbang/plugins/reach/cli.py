# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout reach` — the self-unblocking connect surface.

Point Scout at ANY digital target. It probes, classifies what it found, and —
crucially — when it is blocked it emits a machine-actionable plan whose every
`fix` is a real scout command, so a blocked LLM can repair its own reach:

    scout reach https://api.example.com/openapi.json --register
    scout reach api.github.com                # 401 -> plan says: vault a token
    scout reach allow api.github.com          # self-unblock the network axis
    scout reach diagnose example.com          # walk well-known spec locations
    scout reach plan https://x.dev            # dry: just the unblock plan

Design contract (thesis primitive): recognize the shortcoming early, hand back
the exact next command, never fail-open, never fabricate a capability.
"""

from __future__ import annotations

import httpx
import typer

from bigbang.core import reach as R
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.http_utils import sanitize_no_proxy_env
from bigbang.core.output import emit
from bigbang.core.policy import add_allowed_domain, check_user_url
from bigbang.core.registry import get_tool, register_tool

sanitize_no_proxy_env()

app = make_plugin_app(
    "reach",
    "Reach any API/CLI/site; classify it and self-unblock failed connections",
    examples=[
        "scout reach https://petstore3.swagger.io/api/v3/openapi.json --register",
        "scout --json reach api.github.com",
        "scout reach allow api.github.com",
        "scout --json reach diagnose example.com",
    ],
)


def _fetch(url: str, timeout: float) -> dict:
    """One real probe. Returns a normalized dict; never raises to the caller."""
    try:
        r = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"accept": "application/json, text/html;q=0.9, */*;q=0.5"},
        )
        ct = r.headers.get("content-type", "")
        jb = None
        if "json" in ct.lower():
            try:
                jb = r.json()
            except Exception:
                jb = None
        return {
            "status": r.status_code,
            "content_type": ct,
            "body_text": r.text[:2048],
            "json_body": jb,
            "error": None,
        }
    except Exception as e:  # DNS, TLS, timeout, refused — all transport failures
        return {
            "status": None,
            "content_type": "",
            "body_text": "",
            "json_body": None,
            "error": f"{type(e).__name__}: {e}",
        }


def _probe(target: str, timeout: float, *, tried_well_known: bool = False) -> dict:
    """Policy-gated probe + classification -> the reach result envelope."""
    url = R.normalize_target(target)
    allowed, reason = check_user_url(url)
    if not allowed:
        return {
            "url": url,
            "kind": "blocked",
            "policy_denied": True,
            "detail": reason,
            "suggested_name": R.derive_tool_name(url),
        }
    raw = _fetch(url, timeout)
    cls = R.classify(url=url, **raw)
    return {
        "url": url,
        "status": raw["status"],
        "content_type": raw["content_type"],
        "suggested_name": R.derive_tool_name(url),
        "tried_well_known": tried_well_known,
        **cls,
        "_json_body": raw["json_body"],
    }


@app.command(
    epilog=None,
)
def probe(
    target: str = typer.Argument(
        ..., help="url, host, or host:port — anything digital"
    ),
    register: bool = typer.Option(
        False, "--register", help="auto-register a discovered OpenAPI/MCP tool"
    ),
    name: str | None = typer.Option(
        None, "--name", help="registry name (default: derived from host)"
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="probe timeout seconds"),
):
    """Reach a target: classify it, and (with --register) make it callable."""
    p = _probe(target, timeout)
    jb = p.pop("_json_body", None)
    tool_name = name or p["suggested_name"]

    registered = False
    if register and p.get("kind") == "openapi" and isinstance(jb, dict):
        ops = 0
        try:
            from bigbang.core.openapi import parse_operations

            ops = len(parse_operations(jb))
        except Exception:
            ops = 0
        register_tool(
            tool_name,
            {
                "type": "openapi",
                "url": p["url"],
                "description": (jb.get("info", {}) or {}).get("title", tool_name),
                "capabilities": {
                    "network": {"enabled": True, "domains": [R.host_of(p["url"])]}
                },
                "operations": ops,
                "source": "scout reach",
            },
        )
        registered = True
    p["registered"] = registered

    plan = R.plan_unblock(p)
    payload = ok(
        {
            "target": p["url"],
            "kind": p["kind"],
            "confidence": p.get("confidence"),
            "detail": p.get("detail"),
            "signals": p.get("signals", []),
            "registered": registered,
            "tool_name": tool_name if registered else None,
            "unblock": plan,
        },
        command="reach",
        example=(plan[0]["fix"] if plan else f"scout tools call {tool_name} <action>"),
    )
    if plan:
        payload["next"] = plan[0]["fix"]
    emit(payload, command="reach")


@app.command()
def allow(
    host: str = typer.Argument(
        ..., help="host to add to the network allowlist, e.g. api.github.com"
    ),
):
    """Self-unblock the network axis: persist a host into the user allowlist."""
    changed, msg = add_allowed_domain(host)
    emit(
        ok(
            {
                "host": R.host_of(R.normalize_target(host)) or host,
                "changed": changed,
                "message": msg,
            },
            command="reach allow",
            example=f"scout reach {host}",
        ),
        command="reach allow",
    )


@app.command()
def diagnose(
    target: str = typer.Argument(..., help="url or host to deep-probe"),
    timeout: float = typer.Option(
        6.0, "--timeout", help="per-candidate timeout seconds"
    ),
):
    """When a plain reach finds no spec, walk well-known OpenAPI/MCP locations."""
    base = R.normalize_target(target)
    allowed, reason = check_user_url(base)
    if not allowed:
        p = {
            "url": base,
            "kind": "blocked",
            "policy_denied": True,
            "suggested_name": R.derive_tool_name(base),
        }
        emit(
            ok(
                {
                    "target": base,
                    "kind": "blocked",
                    "detail": reason,
                    "unblock": R.plan_unblock(p),
                    "next": f"scout reach allow {R.host_of(base)}",
                },
                command="reach diagnose",
            ),
            command="reach diagnose",
        )
        return

    tried: list[dict] = []
    found = None
    for cand in R.candidate_spec_urls(target):
        raw = _fetch(cand, timeout)
        cls = R.classify(url=cand, **raw)
        tried.append({"url": cand, "kind": cls["kind"], "status": raw["status"]})
        if cls["kind"] in ("openapi", "graphql"):
            found = {"url": cand, **cls}
            break
    if not found:
        for cand in R.candidate_mcp_urls(target):
            raw = _fetch(cand, timeout)
            cls = R.classify(url=cand, **raw)
            tried.append({"url": cand, "kind": cls["kind"], "status": raw["status"]})
            if cls["kind"] == "mcp":
                found = {"url": cand, **cls}
                break

    result = {
        "target": base,
        "found": found,
        "tried": tried,
        "suggested_name": R.derive_tool_name(base),
    }
    probe_like = {
        "url": (found or {}).get("url", base),
        "kind": (found or {}).get("kind", "empty"),
        "suggested_name": result["suggested_name"],
        "tried_well_known": True,
        "registered": False,
    }
    plan = R.plan_unblock(probe_like)
    payload = ok(
        result,
        command="reach diagnose",
        example=(
            plan[0]["fix"]
            if plan
            else f"scout reach {(found or {}).get('url', base)} --register"
        ),
    )
    if plan:
        payload["next"] = plan[0]["fix"]
    emit(payload, command="reach diagnose")


@app.command()
def plan(
    target: str = typer.Argument(..., help="url or host"),
    timeout: float = typer.Option(10.0, "--timeout", help="probe timeout seconds"),
):
    """Dry run: reach the target and return ONLY the self-unblock plan."""
    p = _probe(target, timeout)
    p.pop("_json_body", None)
    p["registered"] = get_tool(p["suggested_name"]) is not None
    steps = R.plan_unblock(p)
    emit(
        ok(
            {
                "target": p["url"],
                "kind": p["kind"],
                "unblock": steps,
                "next": steps[0]["fix"] if steps else None,
            },
            command="reach plan",
            example=steps[0]["fix"] if steps else f"scout reach {target} --register",
        ),
        command="reach plan",
    )


def register(root: typer.Typer):
    root.add_typer(app, name="reach")
