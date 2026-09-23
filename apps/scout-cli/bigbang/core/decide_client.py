"""scout's door to the decision plane: jarvisd ``POST /api/decide`` when it is up.

jarvisd is the always-on process: its router, context providers and caches are
warm, and it knows the memories, goals and claims in its store. ``scout route``
and ``scout harness route`` ask it first and fall back to the same code
in-process (:func:`dottie_loop.decide.decide`) when it is not reachable, so a
route never fails because the daemon is down.

* ``JARVIS_URL`` (default ``http://127.0.0.1:8790``) and ``JARVIS_BEARER``, the
  same variables ``scout pair`` and the MCP clients use.
* ``SCOUT_DECIDE_REMOTE=0`` forces in-process.
* ``SCOUT_DECIDE_CONNECT_TIMEOUT`` (seconds, default 0.1): the TCP connect
  budget. A closed loopback port refuses immediately; this bounds the
  unreachable-host case. The read budget is ``SCOUT_DECIDE_TIMEOUT`` (default 5).

Stdlib ``http.client``; never raises. Returns ``None`` (with the reason in
:data:`last_error`) whenever the in-process path should be used instead.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.parse
from typing import Any

DEFAULT_JARVIS_URL = "http://127.0.0.1:8790"
REQUIRED = ("moma_tier", "intent", "complexity", "intent_scores", "confidence", "routed_agents",
            "spec_tier", "authority", "heuristic_tier", "advisory", "trace", "decision")

last_error: str | None = None


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def remote_enabled() -> bool:
    return os.environ.get("SCOUT_DECIDE_REMOTE", "").strip().lower() not in ("0", "false", "off", "no")


def remote_decide(goal: str, hints: dict[str, Any] | None = None, *, repo: str = "") -> dict[str, Any] | None:
    """jarvisd's decide() answer, or None (see :data:`last_error`)."""
    global last_error
    last_error = None
    if not remote_enabled():
        last_error = "SCOUT_DECIDE_REMOTE=0"
        return None
    base = (os.environ.get("JARVIS_URL") or DEFAULT_JARVIS_URL).strip().rstrip("/")
    parts = urllib.parse.urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        last_error = f"JARVIS_URL is not http(s): {base!r}"
        return None
    body = json.dumps({"goal": goal, "repo": repo, "hints": hints or {}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Agent-Id": "scout"}
    bearer = (os.environ.get("JARVIS_BEARER") or "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    conn_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parts.hostname, parts.port, timeout=_float_env("SCOUT_DECIDE_CONNECT_TIMEOUT", 0.1))
    try:
        conn.connect()
        if conn.sock is not None:
            conn.sock.settimeout(_float_env("SCOUT_DECIDE_TIMEOUT", 5.0))
        conn.request("POST", parts.path.rstrip("/") + "/api/decide", body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        last_error = f"jarvisd unreachable at {base}: {type(exc).__name__}: {exc}"
        return None
    finally:
        conn.close()
    if resp.status != 200:
        last_error = f"jarvisd {base}/api/decide -> HTTP {resp.status}"
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        last_error = f"jarvisd answer unreadable: {exc}"
        return None
    if not isinstance(doc, dict) or not doc.get("ok") or any(k not in doc for k in REQUIRED):
        last_error = "jarvisd answer is not a decide() result"
        return None
    return doc
