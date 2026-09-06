"""MCP tools (spec §4) and the plain-Python service they wrap.

`Jarvis` holds the state, config and the lazy imports (scout, acne,
personal-graphify, the optional brain). Every method returns a dict with `ok`
and, on failure, `error` + `example`. `register_tools()` wraps those methods as
FastMCP tools that return JSON strings; the JSON API in `app.py` calls the same
methods, so both protocols share one implementation.

Agent identity comes from the `X-Agent-Id` request header (FastMCP exposes the
Starlette request through `Context.request_context.request`); every tool also
accepts an explicit `agent` argument for transports without headers, and falls
back to `anon`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from jarvisd import __version__
from jarvisd.auth import DEFAULT_AGENT, agent_from_headers
from jarvisd.state import ClaimConflictError, State, repo_scope

if TYPE_CHECKING:
    from jarvisd.config import Config

_INSTRUCTIONS = (
    "jarvisd — shared context for the operator's agents. Call jarvis.context(repo) "
    "at session start; jarvis.remember for durable facts; jarvis.claim before "
    "editing a shared area and jarvis.release when done; jarvis.send/inbox for "
    "agent-to-agent notes; harness.route to price a goal before running it. "
    "Every tool returns JSON with `ok`; read `error` and `example` on failure."
)


def _err(error: str, example: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error}
    if example:
        out["example"] = example
    return out


def agent_from_context(ctx: Context | None, explicit: str = "") -> str:
    """Resolve the caller: explicit `agent` arg, else `X-Agent-Id`, else `anon`."""
    explicit = (explicit or "").strip()[:64]
    if explicit:
        return explicit
    if ctx is None:
        return DEFAULT_AGENT
    try:
        request = ctx.request_context.request
    except ValueError:  # outside a request (in-memory client)
        return DEFAULT_AGENT
    headers = getattr(request, "headers", None)
    if headers is None:
        return DEFAULT_AGENT
    return agent_from_headers(headers)


def brain_status(config: Config) -> dict[str, Any]:
    """Which brain provider `jarvis.ask` would use, its model, and if it cannot answer, why.

    Provider selection is `JARVIS_BRAIN` (auto | anthropic | ollama | off, spec §6);
    the answer is never fabricated: `available` is False with a `reason` otherwise.
    """
    try:
        from jarvisd import brain
    except ImportError as e:  # pragma: no cover - module ships with the package
        return {
            "available": False,
            "reason": f"jarvisd.brain import failed: {e}",
            "provider": None,
            "model": None,
            "effort": config.effort,
        }
    out = brain.status()
    out["effort"] = config.effort
    return out


def transport_security(config: Config) -> TransportSecuritySettings | None:
    """DNS-rebinding settings for FastMCP.

    Loopback: `None`, so the SDK applies its localhost-only default. Public with
    `JARVIS_PUBLIC_HOST`: allow that host (any port) plus the bind host and the
    loopback names so a tunnel or a same-box client both pass. Public without a
    public host: protection off — bearer auth is the guard, and the status page
    says so.
    """
    if config.loopback:
        return None
    if not config.public_host:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = [
        config.public_host,
        f"{config.public_host}:*",
        f"{config.host}:{config.port}",
        "localhost:*",
        "127.0.0.1:*",
        "[::1]:*",
    ]
    origins = [
        f"https://{config.public_host}",
        f"https://{config.public_host}:*",
        f"http://{config.public_host}",
        f"http://{config.public_host}:*",
        f"http://{config.host}:{config.port}",
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


class Jarvis:
    """The daemon's service layer: one method per MCP tool, dict in / dict out."""

    def __init__(self, config: Config, state: State, started: float | None = None):
        self.config = config
        self.state = state
        self.started = time.time() if started is None else started

    # -- core --------------------------------------------------------------

    def uptime_s(self) -> float:
        """Seconds since the service object was created."""
        return round(time.time() - self.started, 1)

    def context(self, agent: str, repo: str | None) -> dict[str, Any]:
        """Open claims, open goals, recent memories/timeline, unread count."""
        return {"ok": True, **self.state.context(agent, repo)}

    def remember(
        self,
        agent: str,
        text: str,
        scope: str = "global",
        tags: list[str] | None = None,
        source: str = "",
    ) -> dict[str, Any]:
        """Insert one memory."""
        try:
            row = self.state.remember(agent, scope or "global", text, tags, source)
        except ValueError as e:
            return _err(str(e), 'jarvis.remember(text="...", scope="repo:dottie")')
        return {"ok": True, "memory": row}

    def recall(
        self, query: str, scope: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Search memories."""
        rows = self.state.recall(query, scope=scope or None, limit=limit)
        return {"ok": True, "query": query, "scope": scope, "results": rows, "fts": self.state.fts_enabled}

    def claim(self, agent: str, repo: str, area: str, note: str = "") -> dict[str, Any]:
        """Claim repo+area; fails if another agent holds it."""
        try:
            row = self.state.claim(agent, repo, area, note)
        except ClaimConflictError as e:
            return {**_err(str(e), 'jarvis.claims(repo="...") to see who holds it'), "holder": e.holder}
        except ValueError as e:
            return _err(str(e), 'jarvis.claim(repo="dottie", area="apps/jarvisd")')
        return {"ok": True, "claim": row}

    def release(
        self, agent: str, repo: str, area: str, force: bool = False
    ) -> dict[str, Any]:
        """Release a claim held by the caller (or anyone, with force)."""
        try:
            out = self.state.release(agent, repo, area, force=force)
        except ClaimConflictError as e:
            return {**_err(str(e), "pass force=true to release another agent's claim"), "holder": e.holder}
        return {"ok": True, **out}

    def claims(self, repo: str | None = None, include_released: bool = False) -> dict[str, Any]:
        """The claim board."""
        return {"ok": True, "claims": self.state.claims(repo=repo or None, include_released=include_released)}

    def send(self, agent: str, to: str, body: str) -> dict[str, Any]:
        """Send an agent-to-agent message."""
        try:
            row = self.state.send(agent, to, body)
        except ValueError as e:
            return _err(str(e), 'jarvis.send(to="cursor", body="...")')
        return {"ok": True, "message": row}

    def inbox(self, agent: str, mark_read: bool = False, unread_only: bool = True) -> dict[str, Any]:
        """Messages for the caller."""
        rows = self.state.inbox(agent, mark_read=mark_read, unread_only=unread_only)
        return {"ok": True, "agent": agent, "messages": rows, "unread": self.state.unread_count(agent)}

    def goal(self, agent: str, repo: str, text: str) -> dict[str, Any]:
        """Open a goal."""
        try:
            row = self.state.add_goal(agent, repo, text)
        except ValueError as e:
            return _err(str(e), 'jarvis.goal(repo="dottie", text="...")')
        return {"ok": True, "goal": row}

    def goals(self, repo: str | None = None, status: str | None = "open") -> dict[str, Any]:
        """List goals."""
        return {"ok": True, "goals": self.state.goals(repo=repo or None, status=status or None)}

    def goal_done(self, goal_id: int, result: Any = None, status: str = "done") -> dict[str, Any]:
        """Close a goal."""
        try:
            row = self.state.goal_done(goal_id, result=result, status=status)
        except ValueError as e:
            return _err(str(e), "jarvis.goal_done(id=3, result={...})")
        if row is None:
            return _err(f"goal {goal_id} not found", 'jarvis.goals(repo="...")')
        return {"ok": True, "goal": row}

    def timeline(self, repo: str | None = None, limit: int = 10, kind: str | None = None) -> dict[str, Any]:
        """Recent timeline rows."""
        return {"ok": True, "timeline": self.state.timeline(repo=repo or None, limit=limit, kind=kind or None)}

    def status(self) -> dict[str, Any]:
        """Version, uptime, db, counts, brain."""
        return {
            "ok": True,
            "name": "jarvisd",
            "version": __version__,
            "uptime_s": self.uptime_s(),
            "db": str(self.state.path),
            "fts": self.state.fts_enabled,
            "auth": "bearer" if self.config.auth_enabled else "disabled (loopback)",
            "counts": self.state.counts(),
            "brain": brain_status(self.config),
            "notes": self.config.status_notes(),
        }

    # -- harness (scout, lazy) --------------------------------------------

    @staticmethod
    def _route_only(goal: str) -> dict[str, Any]:
        """Pure routing via scout's heuristic router, same fields as `scout harness route`."""
        from bigbang.plugins.harness import cli as hcli

        scores = {k: hcli._score_intent(goal, k) for k in hcli.INTENT_KEYWORDS}
        best = max(scores.values()) if scores else 0
        intent = max(scores, key=lambda k: scores[k]) if best > 0 else "llm"
        complexity = hcli._complexity(goal)
        tier = hcli._classify_moma(goal, intent, complexity)
        confidence = min(0.96, best / 4.0) if scores.get(intent, 0) > 0 else 0.4
        routed = hcli._routed_agents(intent, complexity)
        return {
            "goal": goal,
            "intent": intent,
            "intent_scores": scores,
            "complexity": complexity,
            "tier": tier,
            "moma_tier": tier,
            "moma_cap": hcli.MOMA_TIERS[tier]["cap"],
            "confidence": round(confidence, 2),
            "routed_agents": routed,
            "routed_count": len(routed),
            "agentic_loop": intent == "agentic_loop" or complexity == "epic",
            "deep_research": intent == "deep_research" or tier == "deep_research",
        }

    def route(self, agent: str, goal: str, repo: str = "") -> dict[str, Any]:
        """Route a goal in-process and record a timeline row."""
        goal = (goal or "").strip()
        if not goal:
            return _err("goal is empty", 'harness.route(goal="compare Stripe vs Lemon Squeezy")')
        t0 = time.perf_counter()
        try:
            result = self._route_only(goal)
        except ImportError as e:
            return _err(f"scout unavailable: {e}", "uv sync --all-groups  # installs apps/scout-cli")
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        row = self.state.timeline_add(
            agent,
            repo,
            "route",
            {"goal": goal, "intent": result["intent"], "tier": result["tier"], "confidence": result["confidence"]},
        )
        return {
            "ok": True,
            **result,
            "latency_ms": latency_ms,
            "tokens_est": len(goal.split()),
            "measured": {"latency_ms": latency_ms, "tokens_est": len(goal.split()), "stdlib": "time", "torch": False},
            "timeline_id": row["id"],
        }

    def plan(self, goal: str) -> dict[str, Any]:
        """Deterministic DAG plan, same shape as `apps/dottie-harness-api` `/api/plan`."""
        goal = (goal or "").strip()
        if not goal:
            return _err("goal is empty", '{"goal": "ship the daemon"}')
        try:
            from bigbang.plugins.harness import runner

            routed = self._route_only(goal)
            steps = runner.build_plan(goal, routed["tier"])
        except ImportError as e:
            return _err(f"scout unavailable: {e}", "uv sync --all-groups")
        return {
            "ok": True,
            "goal": goal,
            "tierHint": routed["tier"],
            "steps": steps,
            "risk_provenance": "mined g_history fail rates when runs exist, static priors otherwise",
            "version": "scout harness runner.build_plan",
        }

    def run(self, agent: str, goal: str, mcp_namespace: str | None = None, repo: str = "") -> dict[str, Any]:
        """Execute a goal with scout's deterministic runner; record run id + critic score."""
        goal = (goal or "").strip()
        if not goal:
            return _err("goal is empty", 'harness.run(goal="heartbeat check")')
        try:
            from bigbang.plugins.harness import runner
        except ImportError as e:
            return _err(f"scout unavailable: {e}", "uv sync --all-groups")
        result = runner.run_goal(goal, runs_dir=self.config.runs_dir, mcp_namespace=mcp_namespace or "")
        row = self.state.timeline_add(
            agent,
            repo,
            "run",
            {
                "goal": goal,
                "run_id": result.get("runId"),
                "critic_score": result.get("critic_score"),
                "passed": result.get("passed"),
                "tier": result.get("tier"),
                "ok": result.get("ok", False),
                "error": result.get("error"),
            },
        )
        return {**result, "timeline_id": row["id"]}

    # -- optional integrations --------------------------------------------

    @staticmethod
    def contacts_resolve(phrase: str) -> dict[str, Any]:
        """acne `ContactsHub().resolve(phrase)` (or `acne.tools.resolve_contact`)."""
        phrase = (phrase or "").strip()
        if not phrase:
            return _err("phrase is empty", 'contacts.resolve(phrase="my designer")')
        try:
            acne = _import_acne()
        except ImportError:
            return _err("acne not installed", "pip install -e ~/workspace/acne")
        hub_cls = getattr(acne, "ContactsHub", None)
        try:
            if hub_cls is not None:
                result = hub_cls().resolve(phrase)
            else:
                from acne.tools import resolve_contact

                result = resolve_contact(phrase)
        except (ImportError, AttributeError, OSError, RuntimeError, ValueError) as e:
            return _err(f"acne resolve failed: {e}")
        return {"ok": True, "phrase": phrase, "result": _jsonable(result)}

    def graph_query(self, query: str, graph_path: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search a personal-graphify `graph.json`."""
        query = (query or "").strip()
        if not query:
            return _err("query is empty", 'graph.query(query="auth middleware")')
        try:
            from personal_graphify.query import load_graph_json, search_nodes
        except ImportError as e:
            return _err(f"personal-graphify not installed: {e}", "uv sync --all-groups")
        candidates = (
            [Path(graph_path).expanduser()]
            if graph_path
            else [Path.cwd() / "graphify-out" / "graph.json", self.config.workspace / "graphify-out" / "graph.json"]
        )
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            return _err(
                "graph.json not found: " + ", ".join(str(p) for p in candidates),
                'graph.query(query="...", graph_path="/path/to/graph.json")',
            )
        try:
            graph = load_graph_json(path)
            results = search_nodes(graph, query, limit=max(1, int(limit)))
        except (OSError, ValueError) as e:
            return _err(f"graph load failed: {e}")
        return {"ok": True, "graph": str(path), "query": query, "results": _jsonable(results)}

    def ask(self, agent: str, question: str, repo: str | None = None) -> dict[str, Any]:
        """Optional brain (spec §6): Ollama on the home box or Anthropic, per `JARVIS_BRAIN`.

        Structured error when no provider can serve; never a fabricated answer.
        """
        question = (question or "").strip()
        if not question:
            return _err("question is empty", 'jarvis.ask(question="what is open on dottie?")')
        try:
            from jarvisd.brain import ask as brain_ask

            result = brain_ask(question=question, repo=repo, state=self.state, agent=agent)
        except (ImportError, RuntimeError) as e:
            msg = str(e)
            if not msg.startswith("brain unavailable"):
                msg = f"brain unavailable: {msg}"
            return _err(
                msg,
                "JARVIS_BRAIN=ollama with Ollama on OLLAMA_HOST ($0), or export ANTHROPIC_API_KEY=... "
                "(pip install 'jarvisd[brain]')",
            )
        if not isinstance(result, dict):
            return _err("brain unavailable: non-dict result from jarvisd.brain.ask")
        return result


def _import_acne() -> Any:
    """Import `acne`, also trying the sibling checkout scout's contacts plugin uses."""
    try:
        import acne  # type: ignore[import-not-found]
    except ImportError:
        sibling = Path.home() / "workspace" / "acne" / "src"
        if not sibling.is_dir():
            raise
        if str(sibling) not in sys.path:
            sys.path.insert(0, str(sibling))
        import acne  # type: ignore[import-not-found]
    return acne


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so foreign objects become plain data."""
    return json.loads(json.dumps(value, default=str))


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


# -- registration ---------------------------------------------------------


def register_tools(mcp: FastMCP, jarvis: Jarvis) -> int:
    """Register the spec §4 tool set on `mcp`. Returns the number registered."""

    @mcp.tool(name="jarvis.context", description="What am I working on? Open claims, open goals, last 10 memories in scope, last 10 timeline rows, unread inbox count for the caller.")
    def jarvis_context(repo: str = "", agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.context(agent_from_context(ctx, agent), repo or None))

    @mcp.tool(name="jarvis.remember", description="Store a durable memory. scope: 'global', 'repo:<name>' or 'person:<name>'.")
    def jarvis_remember(text: str, scope: str = "global", tags: list[str] | None = None, source: str = "", agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.remember(agent_from_context(ctx, agent), text, scope, tags, source))

    @mcp.tool(name="jarvis.recall", description="Full-text search over memories (FTS5, OR of terms, best match first). scope narrows to one scope.")
    def jarvis_recall(query: str, scope: str | None = None, limit: int = 10) -> str:
        return _dump(jarvis.recall(query, scope, limit))

    @mcp.tool(name="jarvis.claim", description="Claim repo+area before editing it. Fails if another agent holds the same repo+area.")
    def jarvis_claim(repo: str, area: str, note: str = "", agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.claim(agent_from_context(ctx, agent), repo, area, note))

    @mcp.tool(name="jarvis.release", description="Release your claim on repo+area. force=true releases another agent's claim.")
    def jarvis_release(repo: str, area: str, force: bool = False, agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.release(agent_from_context(ctx, agent), repo, area, force))

    @mcp.tool(name="jarvis.claims", description="The claim board: active claims, optionally for one repo.")
    def jarvis_claims(repo: str = "", include_released: bool = False) -> str:
        return _dump(jarvis.claims(repo or None, include_released))

    @mcp.tool(name="jarvis.send", description="Send a message to another agent (by its X-Agent-Id).")
    def jarvis_send(to: str, body: str, agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.send(agent_from_context(ctx, agent), to, body))

    @mcp.tool(name="jarvis.inbox", description="Unread messages for the caller. mark_read=true marks them read.")
    def jarvis_inbox(mark_read: bool = False, unread_only: bool = True, agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.inbox(agent_from_context(ctx, agent), mark_read, unread_only))

    @mcp.tool(name="jarvis.goal", description="Open a goal on a repo.")
    def jarvis_goal(repo: str, text: str, agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.goal(agent_from_context(ctx, agent), repo, text))

    @mcp.tool(name="jarvis.goals", description="List goals. status: open (default), done, dropped, or '' for all.")
    def jarvis_goals(repo: str = "", status: str = "open") -> str:
        return _dump(jarvis.goals(repo or None, status or None))

    @mcp.tool(name="jarvis.goal_done", description="Close a goal with an optional JSON result. status: done (default) or dropped.")
    def jarvis_goal_done(id: int, result: dict[str, Any] | str | None = None, status: str = "done") -> str:
        return _dump(jarvis.goal_done(id, result, status))

    @mcp.tool(name="harness.route", description="Route a goal through scout's heuristic router (intent, complexity, tier, agents). Records a timeline row.")
    def harness_route(goal: str, repo: str = "", agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.route(agent_from_context(ctx, agent), goal, repo))

    @mcp.tool(name="harness.run", description="Run a goal with scout's deterministic harness (route -> plan -> execute -> critic). Records run id and critic score on the timeline.")
    def harness_run(goal: str, mcp_namespace: str | None = None, repo: str = "", agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.run(agent_from_context(ctx, agent), goal, mcp_namespace, repo))

    @mcp.tool(name="contacts.resolve", description="Resolve a person phrase ('my designer') via acne, when installed.")
    def contacts_resolve(phrase: str) -> str:
        return _dump(jarvis.contacts_resolve(phrase))

    @mcp.tool(name="graph.query", description="Search a personal-graphify graph.json (default: ./graphify-out/graph.json, then <workspace>/graphify-out/graph.json).")
    def graph_query(query: str, graph_path: str | None = None, limit: int = 20) -> str:
        return _dump(jarvis.graph_query(query, graph_path, limit))

    @mcp.tool(name="jarvis.ask", description="Ask the optional brain (JARVIS_BRAIN: auto|anthropic|ollama|off; default auto = Anthropic if ANTHROPIC_API_KEY is set, else the home-box Ollama at OLLAMA_HOST). Returns a structured 'brain unavailable' error when no provider can serve.")
    def jarvis_ask(question: str, repo: str | None = None, agent: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        return _dump(jarvis.ask(agent_from_context(ctx, agent), question, repo))

    @mcp.tool(name="jarvis.status", description="Daemon status: version, uptime, db path, row counts, brain availability.")
    def jarvis_status() -> str:
        return _dump(jarvis.status())

    return 17


def add_scout_tools(mcp: FastMCP) -> int:
    """Re-export scout's `scout_<plugin>` tools (`--expose-scout`). Returns the count."""
    from bigbang.plugins.mcp.server import build_server

    scout = build_server()
    added = 0
    # The scout server registers on its own FastMCP; copy the scout_* callables
    # (skipping the bb_* legacy aliases) onto ours via the public add_tool().
    for tool in scout._tool_manager.list_tools():
        if not tool.name.startswith("scout_"):
            continue
        mcp.add_tool(tool.fn, name=tool.name, description=tool.description)
        added += 1
    return added


def build_mcp(config: Config, jarvis: Jarvis) -> FastMCP:
    """A FastMCP server with the jarvisd tool set (and scout's, if configured).

    Paths: streamable HTTP answers at `/mcp`, SSE at `/sse` with its POST
    endpoint at `/sse/messages/`; `app.py` places those routes in the daemon's
    Starlette app directly.
    """
    mcp = FastMCP(
        "jarvisd",
        instructions=_INSTRUCTIONS,
        host=config.host,
        port=config.port,
        stateless_http=True,
        streamable_http_path="/mcp",
        sse_path="/sse",
        message_path="/sse/messages/",
        transport_security=transport_security(config),
    )
    register_tools(mcp, jarvis)
    if config.expose_scout:
        add_scout_tools(mcp)
    return mcp


__all__ = [
    "Jarvis",
    "add_scout_tools",
    "agent_from_context",
    "brain_status",
    "build_mcp",
    "register_tools",
    "repo_scope",
    "transport_security",
]
