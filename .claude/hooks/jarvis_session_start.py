#!/usr/bin/env python3
"""Claude Code SessionStart hook: inject a compact Jarvis context summary.

Stdlib only. Reads JARVIS_URL / JARVIS_BEARER from the environment, then from
deploy/.env and ~/.config/dottie/.env if present (env wins; files never override).
Probes GET /api/health with a short timeout; if the daemon is up, fetches open
claims, open goals and the last 5 timeline rows for this repo (jarvisd spec §5)
and prints the SessionStart JSON with an `additionalContext` summary.

If the daemon is down, unreachable, slow, or returns anything unexpected: print
nothing and exit 0. This hook must never block or fail a session. Worst-case
wall time is bounded by DEADLINE_S.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEADLINE_S = 2.5          # hard budget for the whole hook (spec: under 3 s)
HEALTH_TIMEOUT_S = 2.0    # first probe; if this times out we stop
DEFAULT_URL = "http://127.0.0.1:8790"
AGENT_ID = os.environ.get("JARVIS_AGENT_ID", "claude")


def _load_env_file(path: str) -> None:
    """Merge KEY=VALUE lines into os.environ without overriding existing keys."""
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:]
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


def _base_url() -> str:
    url = (os.environ.get("JARVIS_URL") or DEFAULT_URL).strip().rstrip("/")
    for suffix in ("/mcp", "/sse"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def _get(base: str, path: str, params: dict, timeout: float, bearer: str | None):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(f"{base}{path}?{qs}" if qs else f"{base}{path}")
    req.add_header("Accept", "application/json")
    req.add_header("X-Agent-Id", AGENT_ID)
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rows(payload, *keys) -> list:
    """Accept either a bare list or {ok, <key>: [...]} / {items|rows|data: [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in (*keys, "items", "rows", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    return []


def _clip(s, n: int = 60) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _emit(context: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    sys.stdout.write(json.dumps(out) + "\n")


def _dag_frontier(project: str, repo: str) -> str:
    """One line: the ready nodes of docs/project_dag.json, this repo first.

    The unified project DAG (scripts/dag_next.py) is the plan; an agent that boots
    without seeing the frontier will pick work by feel, which is what the DAG exists
    to stop. Local file only, no network, never raises.
    """
    try:
        sys.path.insert(0, os.path.join(project, "scripts"))
        import dag_next  # type: ignore

        from pathlib import Path

        dag = dag_next.load(Path(project) / "docs" / "project_dag.json")
        if dag_next.validate(dag):
            return "project DAG is malformed; run scripts/dag_next.py --check"
        groups = dag_next.classify(dag)
    except Exception:
        return ""
    ready = groups["ready"]
    if not ready:
        return "DAG: nothing ready; finish an in-progress node (scripts/dag_next.py)"
    mine = [n for n in ready if n["repo"] == repo]
    others = [n for n in ready if n["repo"] != repo]
    parts = [f"P{n['priority']} {n['id']}" for n in (mine + others)[:5]]
    where = f"{len(mine)} in this repo" if mine else "none in this repo"
    return (
        f"DAG frontier ({len(ready)} ready, {where}): {', '.join(parts)}. "
        "Work the lowest P first; `python scripts/dag_next.py` for the full list."
    )


def main() -> int:
    start = time.monotonic()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    _load_env_file(os.path.join(project, "deploy", ".env"))
    _load_env_file(os.path.expanduser("~/.config/dottie/.env"))
    base = _base_url()
    bearer = os.environ.get("JARVIS_BEARER") or None
    repo = os.path.basename(os.path.abspath(project))
    dag_line = _dag_frontier(project, repo)

    def remaining() -> float:
        return DEADLINE_S - (time.monotonic() - start)

    try:
        health = _get(base, "/api/health", {}, min(HEALTH_TIMEOUT_S, remaining()), None)
    except Exception:
        if dag_line:
            _emit(dag_line)
        return 0
    if not isinstance(health, dict) or not health.get("ok"):
        if dag_line:
            _emit(dag_line)
        return 0

    claims: list = []
    goals: list = []
    timeline: list = []
    failures = 0
    for path, params, sink, keys in (
        ("/api/claims", {"repo": repo}, claims, ("claims",)),
        ("/api/goals", {"repo": repo}, goals, ("goals",)),
        ("/api/timeline", {"repo": repo, "limit": 5}, timeline, ("timeline", "events")),
    ):
        budget = remaining()
        if budget <= 0.05:
            break
        try:
            sink.extend(_rows(_get(base, path, params, budget, bearer), *keys))
        except Exception:
            failures += 1
            continue  # partial context is still useful; never fail the session
    if failures == 3:
        # Daemon is up but every data call failed: usually a missing or wrong
        # JARVIS_BEARER (401). Say so rather than reporting an empty board.
        hint = "JARVIS_BEARER unset" if not bearer else "auth or endpoint error"
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart",
               "additionalContext": f"Jarvis ({base}) is up but context is unavailable ({hint}); "
                                    "see docs/JARVIS_CONNECT.md."}}
        sys.stdout.write(json.dumps(out) + "\n")
        return 0

    open_claims = [c for c in claims if isinstance(c, dict) and not c.get("released_ts")]
    open_goals = [g for g in goals if isinstance(g, dict) and g.get("status", "open") == "open"]

    parts = []
    if open_claims:
        detail = ", ".join(
            f"{c.get('agent', '?')}:{c.get('area', '?')}" for c in open_claims[:4]
        )
        parts.append(f"{len(open_claims)} open claim{'s' if len(open_claims) != 1 else ''} ({_clip(detail, 90)})")
    else:
        parts.append("no open claims")
    if open_goals:
        detail = "; ".join(_clip(g.get("text"), 50) for g in open_goals[:2])
        parts.append(f"{len(open_goals)} open goal{'s' if len(open_goals) != 1 else ''} ({detail})")
    else:
        parts.append("no open goals")
    if timeline:
        last = [t for t in timeline if isinstance(t, dict)][:3]
        detail = ", ".join(f"{t.get('kind', '?')}@{t.get('agent', '?')}" for t in last)
        parts.append(f"recent: {_clip(detail, 80)}")
    brain = health.get("brain")
    brain_note = "brain on" if brain in (True, "on", "available") else "brain off"

    summary = (
        f"Jarvis ({base}, repo={repo}): " + "; ".join(parts) + f"; {brain_note}. "
        "Call jarvis.context for detail, jarvis.claim before editing a shared area, "
        "jarvis.remember for decisions and gotchas."
    )
    if dag_line:
        summary = f"{dag_line} | {summary}"
    _emit(summary)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
