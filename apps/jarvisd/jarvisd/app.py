"""The Starlette app (spec §1, §5): MCP at /mcp and /sse, JSON at /api/*, status at /.

`build_app(config)` returns a `Starlette` whose middleware stack is exactly one
`AuthMiddleware` (auth, rate limits, security headers, audit) with `/` and
`/api/health` exempt. `serve(config)` runs it under uvicorn.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from jarvisd import __version__
from jarvisd.auth import DEFAULT_EXEMPT, AuthMiddleware, agent_from_headers
from jarvisd.slack import (
    SLACK_PATH,
    ReplayGuard,
    SlackRefusalError,
    goal_text_from,
    parse_payload,
)
from jarvisd.slack import (
    verify as verify_slack,
)
from jarvisd.state import TABLES, State, repo_scope
from jarvisd.tools import Jarvis, brain_status, build_mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from starlette.requests import Request

    from jarvisd.config import Config


class BadRequestError(ValueError):
    """A 400 with a JSON body."""


class PayloadTooLargeError(ValueError):
    """A 413 with a JSON body."""


CONDUCTOR_SNAPSHOT_MAX_BYTES = 64 * 1024


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def _reply(payload: dict[str, Any]) -> JSONResponse:
    return _json(payload, 200 if payload.get("ok", True) else 400)


def _bounded_conductor_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim non-active rows until compact UTF-8 JSON fits the wire bound."""
    while (
        len(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        > CONDUCTOR_SNAPSHOT_MAX_BYTES
    ):
        todos = payload.get("todos", [])
        todo_index = next(
            (
                index
                for index, todo in enumerate(todos)
                if todo.get("status") == "completed"
            ),
            None,
        )
        if todo_index is None:
            todo_index = next(
                (
                    index
                    for index, todo in enumerate(todos)
                    if todo.get("status") != "in_progress"
                ),
                None,
            )
        if todo_index is not None:
            todos.pop(todo_index)
            continue
        candidates = [
            ("feedback", 0),
            ("scratchpad", 0),
        ]
        populated = [(key, index) for key, index in candidates if payload.get(key)]
        if not populated:
            break
        key, index = max(
            populated,
            key=lambda candidate: len(
                json.dumps(
                    payload[candidate[0]][candidate[1]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
        )
        payload[key].pop(index)
    return payload


async def _body(request: Request, *, maximum_bytes: int | None = None) -> dict[str, Any]:
    if maximum_bytes is not None:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as e:
                raise BadRequestError("invalid Content-Length") from e
            if declared_length > maximum_bytes:
                raise PayloadTooLargeError(f"body exceeds {maximum_bytes} bytes")
    if maximum_bytes is None:
        raw = await request.body()
    else:
        buffered = bytearray()
        async for chunk in request.stream():
            if len(buffered) + len(chunk) > maximum_bytes:
                raise PayloadTooLargeError(f"body exceeds {maximum_bytes} bytes")
            buffered.extend(chunk)
        raw = bytes(buffered)
    if not raw:
        return {}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BadRequestError(f"malformed json: {e}") from e
    if not isinstance(doc, dict):
        raise BadRequestError("body must be a JSON object")
    return doc


def _require_str(doc: dict[str, Any], key: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError(f"body must include a non-empty '{key}' string")
    return value.strip()


def _exact_keys(doc: dict[str, Any], expected: set[str], label: str) -> None:
    if set(doc) != expected:
        raise BadRequestError(
            f"{label} keys must be exactly {sorted(expected)}"
        )


def _int_param(request: Request, key: str, default: int) -> int:
    raw = request.query_params.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise BadRequestError(f"query param {key!r} must be an integer") from e


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _agent(request: Request) -> str:
    return agent_from_headers(request.headers)


def build_app(config: Config, *, state: State | None = None) -> Starlette:
    """Assemble the daemon app. `state` may be injected (tests); default opens `config.db_path`."""
    config.validate()
    store = state or State(config.db_path)
    started = time.time()
    jarvis = Jarvis(config, store, started)
    slack_replays = ReplayGuard()
    mcp = build_mcp(config, jarvis)
    # streamable_http_app() must be built before session_manager exists.
    mcp_http = mcp.streamable_http_app()

    # -- handlers ----------------------------------------------------------

    async def status_page(request: Request) -> Response:
        tools = await mcp.list_tools()
        lines = [
            f"jarvisd {__version__}",
            f"uptime_s: {jarvis.uptime_s()}",
            f"tools: {len(tools)}",
            f"db: {store.path}",
            f"auth: {'bearer' if config.auth_enabled else 'DISABLED (loopback, no JARVIS_BEARER)'}",
            f"brain: {'available' if brain_status(config)['available'] else 'unavailable: ' + str(brain_status(config)['reason'])}",
            "mcp: /mcp (streamable-http)" + (", /sse (sse)" if config.sse else ""),
            "api: /api/health /api/route /api/run /api/plan /api/memories /api/recall "
            "/api/claims /api/inbox /api/goals /api/timeline /api/pair /api/export/<table>",
        ]
        for note in config.status_notes():
            lines.append(f"note: {note}")
        return PlainTextResponse("\n".join(lines) + "\n")

    async def health(request: Request) -> Response:
        return _json(
            {
                "ok": True,
                "version": __version__,
                "uptime_s": jarvis.uptime_s(),
                "db": str(store.path),
                "brain": brain_status(config),
            }
        )

    async def api_route(request: Request) -> Response:
        doc = await _body(request)
        return _reply(jarvis.route(_agent(request), _require_str(doc, "goal"), str(doc.get("repo") or "")))

    async def api_plan(request: Request) -> Response:
        doc = await _body(request)
        return _reply(jarvis.plan(_require_str(doc, "goal")))

    async def api_run(request: Request) -> Response:
        doc = await _body(request)
        goal = _require_str(doc, "goal")
        ns = doc.get("mcp_namespace")
        result = await run_in_threadpool(
            jarvis.run, _agent(request), goal, ns if isinstance(ns, str) else None, str(doc.get("repo") or "")
        )
        return _reply(result)

    async def api_memories(request: Request) -> Response:
        if request.method == "POST":
            doc = await _body(request)
            tags = doc.get("tags")
            return _reply(
                jarvis.remember(
                    _agent(request),
                    _require_str(doc, "text"),
                    str(doc.get("scope") or "global"),
                    [str(t) for t in tags] if isinstance(tags, list) else None,
                    str(doc.get("source") or ""),
                )
            )
        scope = request.query_params.get("scope") or None
        repo = request.query_params.get("repo")
        if repo and not scope:
            scope = repo_scope(repo)
        return _json({"ok": True, "memories": store.memories(scope=scope, limit=_int_param(request, "limit", 20))})

    async def api_recall(request: Request) -> Response:
        q = request.query_params.get("q") or request.query_params.get("query") or ""
        if not q.strip():
            raise BadRequestError("query param 'q' is required")
        return _reply(jarvis.recall(q, request.query_params.get("scope") or None, _int_param(request, "limit", 10)))

    async def api_claims(request: Request) -> Response:
        if request.method == "GET":
            return _reply(jarvis.claims(request.query_params.get("repo") or None, _flag(request.query_params.get("released"))))
        doc = await _body(request)
        repo = doc.get("repo") or request.query_params.get("repo") or ""
        area = doc.get("area") or request.query_params.get("area") or ""
        if not repo or not area:
            raise BadRequestError("'repo' and 'area' are required")
        if request.method == "DELETE":
            return _reply(jarvis.release(_agent(request), str(repo), str(area), _flag(doc.get("force"))))
        return _reply(jarvis.claim(_agent(request), str(repo), str(area), str(doc.get("note") or "")))

    async def api_inbox(request: Request) -> Response:
        if request.method == "POST":
            doc = await _body(request)
            return _reply(jarvis.send(_agent(request), _require_str(doc, "to"), _require_str(doc, "body")))
        return _reply(
            jarvis.inbox(
                _agent(request),
                mark_read=_flag(request.query_params.get("mark_read")),
                unread_only=not _flag(request.query_params.get("all")),
            )
        )

    async def api_goals(request: Request) -> Response:
        if request.method == "POST":
            doc = await _body(request)
            return _reply(jarvis.goal(_agent(request), str(doc.get("repo") or ""), _require_str(doc, "text")))
        if request.method == "PATCH":
            doc = await _body(request)
            try:
                goal_id = int(doc.get("id"))
            except (TypeError, ValueError) as e:
                raise BadRequestError("'id' must be an integer") from e
            return _reply(jarvis.goal_done(goal_id, doc.get("result"), str(doc.get("status") or "done")))
        status = request.query_params.get("status", "open")
        return _reply(jarvis.goals(request.query_params.get("repo") or None, status or None))

    async def api_slack_events(request: Request) -> Response:
        """Slack ingress. Verify first, understand second, only then write.

        Ordering is the whole design: nothing here reads the payload until the
        signature over the raw bytes has been checked, and nothing writes a goal
        until the payload has been recognised as one of the shapes we handle.
        """
        raw = await request.body()
        try:
            signature = verify_slack(
                config.slack_signing_secret, request.headers, raw
            )
            slack_replays.check_and_record(signature)
            doc = parse_payload(request.headers.get("content-type", ""), raw)
            kind, who, text = goal_text_from(doc)
        except SlackRefusalError as refusal:
            # Log the reason, return it, and do nothing else. A refusal is a
            # complete outcome, not a fallback into some more permissive path.
            return _json({"ok": False, "error": refusal.reason}, status=refusal.status)

        if kind == "url_verification":
            # `text` is the challenge. Slack sends this once, at setup, and the
            # signature was still checked before we echoed anything.
            return _json({"challenge": text})

        if not text:
            # An empty command is a user mistake, not an attack. Say what to do.
            return _json(
                {
                    "response_type": "ephemeral",
                    "text": "Nothing to open. Try: /jarvis ship the release notes",
                }
            )

        agent = f"slack:{who}" if who else "slack"
        repo = str(doc.get("team_domain") or "")
        result = await run_in_threadpool(jarvis.goal, agent, repo, text)
        goal = result.get("goal") if isinstance(result, dict) else None
        if not (isinstance(result, dict) and result.get("ok")):
            reason = result.get("error") if isinstance(result, dict) else "goal rejected"
            return _json({"ok": False, "error": reason}, status=400)

        goal_id = goal.get("id") if isinstance(goal, dict) else None
        # A slash command shows this JSON to the user directly, which is how the
        # loop closes without a bot token. An Events API post ignores the body and
        # only wants a 2xx, so the same reply serves both.
        return _json(
            {
                "ok": True,
                "response_type": "ephemeral",
                "text": f"Opened goal #{goal_id}: {text}",
                "goal": goal,
            }
        )

    async def api_timeline(request: Request) -> Response:
        return _reply(
            jarvis.timeline(
                request.query_params.get("repo") or None,
                _int_param(request, "limit", 20),
                request.query_params.get("kind") or None,
            )
        )

    def conductor_scope(request: Request) -> tuple[str, str, str]:
        repo = (request.query_params.get("repo") or "").strip()
        mission = (request.query_params.get("mission") or "").strip()
        if not repo or not mission:
            raise BadRequestError("query params 'repo' and 'mission' are required")
        return repo, _agent(request), mission

    def conductor_snapshot(repo: str, mission: str) -> dict[str, Any]:
        snapshot = store.conductor_snapshot(repo, mission)
        return {
            "ok": True,
            "repo": repo,
            "mission": mission,
            "daemon": {
                "version": __version__,
                "uptime_s": jarvis.uptime_s(),
                "process_id": os.getpid(),
            },
            "persistence": {
                "enabled": str(store.path) != ":memory:",
                "kind": "sqlite",
                "journal_mode": "wal" if str(store.path) != ":memory:" else "memory",
            },
            "auth": {
                "enabled": config.auth_enabled,
                "read_only": True,
                "rates_per_minute": {
                    "ip": config.rate_ip,
                    "key": config.rate_key,
                    "agent": config.rate_agent,
                },
            },
            "capabilities": {
                "read": ["feedback", "scratchpad", "todos", "guardrails"],
                "write": [
                    "feedback.push",
                    "scratchpad.write",
                    "todo.create",
                    "todo.move",
                ],
            },
            "guardrails": [
                {
                    "id": "authenticated_transport",
                    "enabled": config.auth_enabled,
                    "mutable": False,
                },
                {
                    "id": "request_rate_limits",
                    "enabled": True,
                    "mutable": False,
                },
                {
                    "id": "sqlite_persistence",
                    "enabled": str(store.path) != ":memory:",
                    "mutable": False,
                },
            ],
            **snapshot,
        }

    async def api_conductor_snapshot(request: Request) -> Response:
        repo, _, mission = conductor_scope(request)
        return _json(_bounded_conductor_snapshot(conductor_snapshot(repo, mission)))

    async def api_conductor_rpc(request: Request) -> Response:
        repo, agent, mission = conductor_scope(request)
        doc = await _body(request, maximum_bytes=16 * 1024)
        _exact_keys(doc, {"method", "params"}, "body")
        method = doc.get("method")
        params = doc.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            raise BadRequestError("'method' must be a string and 'params' an object")
        allowed = {
            "feedback.push",
            "scratchpad.write",
            "todo.create",
            "todo.move",
        }
        if method not in allowed:
            return _json({"ok": False, "error": "conductor method is not allowed"}, 403)
        request.scope["audit_action"] = method
        try:
            if method == "feedback.push":
                _exact_keys(params, {"kind", "message", "strength"}, "params")
                result = store.conductor_feedback_push(
                    repo,
                    agent,
                    mission,
                    params.get("kind"),
                    params.get("message"),
                    params.get("strength"),
                )
            elif method == "scratchpad.write":
                _exact_keys(params, {"text"}, "params")
                result = store.conductor_scratchpad_write(
                    repo, agent, mission, params.get("text")
                )
            elif method == "todo.create":
                _exact_keys(params, {"text", "priority"}, "params")
                result = store.conductor_todo_create(
                    repo,
                    agent,
                    mission,
                    params.get("text"),
                    params.get("priority"),
                )
            else:
                _exact_keys(params, {"id", "status"}, "params")
                result = store.conductor_todo_move(
                    repo,
                    agent,
                    mission,
                    params.get("id"),
                    params.get("status"),
                )
        except ValueError as e:
            raise BadRequestError(str(e)) from e
        return _json(
            {
                "ok": True,
                "method": method,
                "result": result,
                "snapshot": _bounded_conductor_snapshot(
                    conductor_snapshot(repo, mission)
                ),
            }
        )

    async def api_pair_create(request: Request) -> Response:
        doc = await _body(request)
        expire_min = doc.get("expire_min", 10)
        try:
            expire_min = int(expire_min)
        except (TypeError, ValueError) as e:
            raise BadRequestError("'expire_min' must be an integer") from e
        return _reply(store.pair_create(_agent(request), expire_min=expire_min))

    async def api_pair_verify(request: Request) -> Response:
        doc = await _body(request)
        return _reply(store.pair_verify(_require_str(doc, "code")))

    async def api_pair_status(request: Request) -> Response:
        code = request.query_params.get("code") or None
        return _reply(store.pair_status(code))

    async def api_export(request: Request) -> Response:
        table = request.path_params["table"]
        if table not in TABLES:
            return _json({"ok": False, "error": f"unknown table {table!r}", "tables": list(TABLES)}, 404)

        def lines() -> Iterator[bytes]:
            for row in store.export(table):
                yield (json.dumps(row, default=str) + "\n").encode("utf-8")

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    async def not_found(request: Request, exc: Exception) -> Response:
        return _json({"ok": False, "error": "not found"}, 404)

    async def bad_request(request: Request, exc: Exception) -> Response:
        return _json({"ok": False, "error": str(exc)}, 400)

    async def payload_too_large(request: Request, exc: Exception) -> Response:
        return _json({"ok": False, "error": str(exc)}, 413)

    routes = [
        Route("/", status_page, methods=["GET"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/route", api_route, methods=["POST"]),
        Route("/api/plan", api_plan, methods=["POST"]),
        Route("/api/run", api_run, methods=["POST"]),
        Route("/api/memories", api_memories, methods=["GET", "POST"]),
        Route("/api/recall", api_recall, methods=["GET"]),
        Route("/api/claims", api_claims, methods=["GET", "POST", "DELETE"]),
        Route("/api/inbox", api_inbox, methods=["GET", "POST"]),
        Route("/api/goals", api_goals, methods=["GET", "POST", "PATCH"]),
        Route(SLACK_PATH, api_slack_events, methods=["POST"]),
        Route("/api/timeline", api_timeline, methods=["GET"]),
        Route("/api/conductor/snapshot", api_conductor_snapshot, methods=["GET"]),
        Route("/api/conductor/rpc", api_conductor_rpc, methods=["POST"]),
        Route("/api/pair/create", api_pair_create, methods=["POST"]),
        Route("/api/pair/verify", api_pair_verify, methods=["POST"]),
        Route("/api/pair/status", api_pair_status, methods=["GET"]),
        Route("/api/export/{table}", api_export, methods=["GET"]),
    ]
    # FastMCP builds its transports as tiny Starlette apps with no middleware of
    # their own; lifting their routes in keeps /mcp exact (a Mount("/mcp") would
    # 307 the bare path to /mcp/ on every request) while the FastMCP-built ASGI
    # endpoints are used unchanged.
    routes.extend(mcp_http.routes)
    if config.sse:
        routes.extend(mcp.sse_app().routes)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[
            Middleware(
                AuthMiddleware,
                bearer=config.bearer,
                audit_path=config.audit_path,
                # Slack cannot send our bearer; it signs each request instead, and
                # the handler verifies that signature before doing anything. Exempt
                # from the bearer check, never from authentication.
                exempt=(*DEFAULT_EXEMPT, SLACK_PATH),
                rate_ip=config.rate_ip,
                rate_key=config.rate_key,
                rate_agent=config.rate_agent,
            )
        ],
        exception_handlers={
            404: not_found,
            BadRequestError: bad_request,
            PayloadTooLargeError: payload_too_large,
        },
    )
    app.state.config = config
    app.state.store = store
    app.state.jarvis = jarvis
    app.state.mcp = mcp
    return app


def serve(config: Config, log_level: str = "info") -> None:
    """Run the daemon under uvicorn (blocking)."""
    import uvicorn

    app = build_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level=log_level)


__all__ = ["BadRequestError", "build_app", "serve"]
