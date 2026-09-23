"""Decision context: the bounded, deterministic knowledge a decision is made with.

:func:`build_context` asks each :class:`ContextProvider` for items relevant to a
goal and returns a :class:`DecisionContext`: a sorted, size-capped list of
:class:`ContextItem` (source, id, score, short text, small structured data), a
digest over exactly those items, and per-provider latency. It is what the
decision plane (:mod:`dottie_loop.decide`, jarvisd ``/api/decide``) builds
before routing, and what :func:`dottie_loop.backends.system_one_state` puts in
System One's ``state``, the same way at serve time and when ``scout router
pack`` rebuilds that state from a trace.

Rules:

* **Bounded.** :class:`ContextBudget` caps items per provider, total items,
  characters per item and the serialized size; anything over is dropped, in
  score order, and counted.
* **Deterministic.** Items are ordered by (-score, source, id) and the digest
  is the sha256 of their canonical JSON. Latency is recorded but never hashed.
* **Fail soft.** A provider that raises or exceeds its timeout contributes
  nothing and is recorded as ``ok: false`` with the reason; the decision still
  happens (on the heuristic, as always).
* **Private.** An item marked ``private`` (a memory, a goal, a claim note: the
  owner's words) carries its text into System One's state and into traces only
  when the owner opted in with ``DOTTIE_TRACE_TEXT=1``, the same switch that
  governs the goal text. Without it, only its source, id, kind, score and
  structured data leave the process. The goal text itself is never stored in a
  context.

Adapters here: :class:`JarvisStateProvider` (jarvisd memories via FTS5 recall,
open goals, active claims; in-process, duck-typed on ``jarvisd.state.State``),
:class:`RunHistoryProvider` (per-tier / per-role success, recovery and latency
from :mod:`dottie_loop.run_history`) and :class:`GraphifyProvider`
(personal-graphify code-graph hits; off unless ``DOTTIE_CONTEXT_GRAPH`` names a
``graph.json``).

Stdlib only.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

CONTEXT_SCHEMA = "dottie-decision-context-1"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "my", "is", "it", "this", "that", "then", "vs"})


@dataclass(frozen=True)
class ContextItem:
    """One piece of knowledge. ``text`` is short; ``data`` is small structured facts."""

    source: str
    id: str
    score: float
    text: str = ""
    kind: str = ""
    private: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source, "id": self.id, "kind": self.kind, "score": round(float(self.score), 4)}
        if self.text:
            out["text"] = self.text
        if self.data:
            out["data"] = self.data
        if self.private:
            out["private"] = True
        return out


@dataclass(frozen=True)
class ContextBudget:
    """Hard caps. Defaults keep a context under ~4 KB of JSON."""

    per_provider: int = 5
    max_items: int = 12
    max_text_chars: int = 160
    max_bytes: int = 4096
    timeout_s: float = 0.25


@runtime_checkable
class ContextProvider(Protocol):
    """Anything with a ``name`` and ``fetch(goal, k) -> list[ContextItem]``."""

    name: str

    def fetch(self, goal: str, k: int) -> list[ContextItem]: ...


@dataclass
class DecisionContext:
    items: list[ContextItem]
    digest: str
    providers: dict[str, dict[str, Any]]
    dropped: int = 0
    size_bytes: int = 0
    latency_ms: float = 0.0

    def summary(self, *, include_private_text: bool | None = None) -> dict[str, Any]:
        """The bounded view System One sees and traces store. Deterministic."""
        return context_summary(self, include_private_text=include_private_text)

    def record(self) -> dict[str, Any]:
        """For decision records: ids, scores and hashes only, never text."""
        return {
            "schema": CONTEXT_SCHEMA,
            "digest": self.digest,
            "n_items": len(self.items),
            "dropped": self.dropped,
            "size_bytes": self.size_bytes,
            "sources": _source_counts(self.items),
            "items": [{"source": i.source, "id": i.id, "score": round(float(i.score), 4)} for i in self.items],
            "providers": self.providers,
            "latency_ms": self.latency_ms,
        }


def _source_counts(items: list[ContextItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i.source] = out.get(i.source, 0) + 1
    return dict(sorted(out.items()))


def _text_enabled() -> bool:
    from dottie_loop.backends import trace_text_enabled

    return trace_text_enabled()


def context_summary(context: DecisionContext | dict[str, Any] | None, *, include_private_text: bool | None = None) -> dict[str, Any] | None:
    """``{"digest", "items": [...]}`` for System One's state.

    A dict (a summary already stored in a trace) passes through unchanged, so
    ``scout router pack`` rebuilds exactly the state that was served.
    """
    if context is None:
        return None
    if isinstance(context, dict):
        return context
    show_private = _text_enabled() if include_private_text is None else include_private_text
    items = []
    for i in context.items:
        c = i.canonical()
        if i.private and not show_private:
            c.pop("text", None)
        items.append(c)
    return {"digest": context.digest, "items": items}


def _digest(items: list[ContextItem]) -> str:
    body = json.dumps([i.canonical() for i in items], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _clip(text: str, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: max(0, n - 1)] + "…"


_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _pool() -> concurrent.futures.ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="dottie-context")
        return _POOL


def build_context(goal: str, providers: list[Any] | tuple[Any, ...], budget: ContextBudget | None = None) -> DecisionContext:
    """Ask every provider (concurrently, each under ``budget.timeout_s``) and bound the result."""
    budget = budget or ContextBudget()
    t_all = time.perf_counter()
    report: dict[str, dict[str, Any]] = {}
    collected: list[ContextItem] = []
    futures: list[tuple[str, float, concurrent.futures.Future[list[ContextItem]]]] = []
    for p in providers:
        name = str(getattr(p, "name", type(p).__name__))
        futures.append((name, time.perf_counter(), _pool().submit(p.fetch, goal, budget.per_provider)))
    for name, t0, fut in futures:
        remaining = max(0.0, budget.timeout_s - (time.perf_counter() - t0))
        try:
            got = fut.result(timeout=remaining)
            if not isinstance(got, list):
                raise TypeError(f"fetch returned {type(got).__name__}, not a list")
            valid = [i for i in got if isinstance(i, ContextItem)]
            valid.sort(key=lambda i: (-round(float(i.score), 4), i.source, i.id))
            items = valid[: budget.per_provider]
            collected.extend(items)
            report[name] = {"ok": True, "n": len(items), "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3)}
        except concurrent.futures.TimeoutError:
            fut.cancel()
            report[name] = {"ok": False, "n": 0, "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                            "error": f"timeout after {budget.timeout_s}s"}
        except Exception as exc:  # a provider never breaks a decision
            report[name] = {"ok": False, "n": 0, "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                            "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    clipped = [
        ContextItem(source=i.source, id=i.id, score=float(i.score), text=_clip(i.text, budget.max_text_chars),
                    kind=i.kind, private=i.private, data=dict(i.data))
        for i in collected
    ]
    clipped.sort(key=lambda i: (-round(float(i.score), 4), i.source, i.id))
    kept: list[ContextItem] = []
    size = 2
    for i in clipped:
        if len(kept) >= budget.max_items:
            break
        n = len(json.dumps(i.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + 1
        if size + n > budget.max_bytes:
            continue  # this one is too big; a smaller, lower-scored item may still fit
        kept.append(i)
        size += n
    return DecisionContext(
        items=kept,
        digest=_digest(kept),
        providers=report,
        dropped=len(clipped) - len(kept),
        size_bytes=size,
        latency_ms=round((time.perf_counter() - t_all) * 1000.0, 3),
    )


def goal_terms(goal: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(goal.lower()) if t not in _STOP and len(t) > 1}


def overlap(goal: str, text: str) -> float:
    """Share of the goal's content terms that appear in ``text`` (0..1)."""
    g = goal_terms(goal)
    if not g:
        return 0.0
    return len(g & goal_terms(text)) / len(g)


# --- adapters ------------------------------------------------------------------


class JarvisStateProvider:
    """jarvisd's SQLite store, in-process: FTS5 memory recall, open goals, active claims.

    ``state`` is duck-typed on ``jarvisd.state.State`` (``recall``, ``goals``,
    ``claims``), so dottie_loop does not import jarvisd. All three carry the
    owner's words, so every item is ``private``.
    """

    name = "jarvisd"

    def __init__(self, state: Any, repo: str | None = None) -> None:
        self.state = state
        self.repo = repo or None

    def fetch(self, goal: str, k: int) -> list[ContextItem]:
        items: list[ContextItem] = []
        if goal_terms(goal):
            for rank, m in enumerate(self.state.recall(" ".join(sorted(goal_terms(goal))), scope=None, limit=k)):
                items.append(ContextItem(
                    source="jarvisd.memory", id=f"memory:{m.get('id')}", kind="memory", private=True,
                    score=round(max(overlap(goal, str(m.get("text", ""))), 1.0 / (rank + 2)), 4),
                    text=str(m.get("text", "")), data={"scope": str(m.get("scope") or "")},
                ))
        goals = self.state.goals(repo=self.repo, status="open", limit=50)
        ranked = sorted(goals, key=lambda g: (-overlap(goal, str(g.get("text", ""))), -int(g.get("id") or 0)))
        for g in ranked[:k]:
            items.append(ContextItem(
                source="jarvisd.goal", id=f"goal:{g.get('id')}", kind="open_goal", private=True,
                score=round(overlap(goal, str(g.get("text", ""))), 4), text=str(g.get("text", "")),
                data={"repo": str(g.get("repo") or "")},
            ))
        claims = self.state.claims(repo=self.repo)
        for c in claims[:k]:
            items.append(ContextItem(
                source="jarvisd.claim", id=f"claim:{c.get('id')}", kind="active_claim", private=True,
                score=round(overlap(goal, f"{c.get('area', '')} {c.get('note', '')}"), 4),
                text=str(c.get("note") or ""),
                data={"repo": str(c.get("repo") or ""), "area": str(c.get("area") or ""), "agent": str(c.get("agent") or "")},
            ))
        return items


class RunHistoryProvider:
    """Past runs: per-tier success / recovery / latency and the riskiest roles.

    Aggregates, not words: nothing here is private. Served by the cached,
    incremental :class:`dottie_loop.run_history.HistoryIndex`.
    """

    name = "run_history"

    def __init__(self, base: Path | None = None) -> None:
        self.base = Path(base) if base is not None else None

    def fetch(self, goal: str, k: int) -> list[ContextItem]:
        from dottie_loop.run_history import history_stats

        stats = history_stats(self.base)
        items: list[ContextItem] = []
        runs_total = sum(t["runs"] for t in stats.get("per_tier", {}).values()) or 1
        for tier, t in sorted(stats.get("per_tier", {}).items()):
            items.append(ContextItem(
                source="run_history.tier", id=f"tier:{tier}", kind="tier_history",
                score=round(0.5 + 0.5 * t["runs"] / runs_total, 4),
                data={"runs": t["runs"], "success_rate": t["success_rate"], "recovery_rate": t["recovery_rate"],
                      "p50_latency_ms": round(float(t["p50_latency"]), 3)},
            ))
        roles = sorted(stats.get("per_role", {}).items(), key=lambda kv: (-kv[1]["fail_rate"], kv[0]))
        for role, r in roles[:k]:
            if not r["runs"]:
                continue
            items.append(ContextItem(
                source="run_history.role", id=f"role:{role}", kind="role_history",
                score=round(0.25 + 0.5 * r["fail_rate"], 4),
                data={"runs": r["runs"], "fail_rate": r["fail_rate"], "p50_latency_ms": round(float(r["p50_latency"]), 3)},
            ))
        return items


class GraphifyProvider:
    """personal-graphify code-graph hits. Off unless a ``graph.json`` is configured."""

    name = "graphify"
    _cache: tuple[str, float, Any] | None = None
    _lock = threading.Lock()

    def __init__(self, graph_path: Path | None = None) -> None:
        env = os.environ.get("DOTTIE_CONTEXT_GRAPH", "").strip()
        self.graph_path = Path(graph_path) if graph_path else (Path(env).expanduser() if env else None)

    @property
    def enabled(self) -> bool:
        return self.graph_path is not None and self.graph_path.is_file()

    def _graph(self) -> Any:
        from personal_graphify.query import load_graph_json

        assert self.graph_path is not None
        mtime = self.graph_path.stat().st_mtime
        with self._lock:
            c = type(self)._cache
            if c is not None and c[0] == str(self.graph_path) and c[1] == mtime:
                return c[2]
            graph = load_graph_json(self.graph_path)
            type(self)._cache = (str(self.graph_path), mtime, graph)
            return graph

    def fetch(self, goal: str, k: int) -> list[ContextItem]:
        if not self.enabled:
            return []
        from personal_graphify.query import search_nodes

        items: list[ContextItem] = []
        for rank, hit in enumerate(search_nodes(self._graph(), goal, limit=k)):
            node = hit if isinstance(hit, dict) else {"id": str(hit)}
            nid = str(node.get("id") or node.get("node") or node.get("label") or rank)
            label = str(node.get("label") or node.get("name") or nid)
            score = node.get("score")
            items.append(ContextItem(
                source="graphify", id=f"node:{nid}", kind="code_node", text=label,
                # graphify's lexical score is unbounded (20 for a phrase hit, 3 per term): squash to 0..1
                score=round(min(1.0, float(score) / 40.0), 4) if isinstance(score, (int, float)) else round(1.0 / (rank + 2), 4),
                data={k2: str(node[k2]) for k2 in ("file", "source_file", "type") if k2 in node},
            ))
        return items


def default_providers(*, state: Any = None, repo: str | None = None, history_base: Path | None = None) -> list[Any]:
    """jarvisd state (when given), run history, and graphify when configured."""
    out: list[Any] = []
    if state is not None:
        out.append(JarvisStateProvider(state, repo))
    out.append(RunHistoryProvider(history_base))
    g = GraphifyProvider()
    if g.enabled:
        out.append(g)
    return out
