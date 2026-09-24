"""The decision plane's one entry: ``decide(goal, hints)``.

context -> route -> decision record. jarvisd serves it as ``POST /api/decide``
and the MCP tool ``harness.decide`` (with its SQLite store as a context
provider); scout calls jarvisd when it is reachable and this same function
in-process when it is not.

1. **Context** (:func:`dottie_loop.context.build_context`): bounded,
   deterministic, per-provider timeouts, fail soft.
2. **Route** (:func:`dottie_loop.router.route_goal`, unchanged policy: hard
   constraints -> MoMA-lite heuristic -> learned advice only when gated AND
   human-stamped AND equal-or-cheaper -> escalation only on a recorded
   insufficiency), with the context passed to backends that take it.
3. **Record**: tier, authority, System One's answers, the context digest and
   item ids (never texts), and the latency breakdown (context, route, each
   backend, total). The trace line carries it; jarvisd also writes it to its
   timeline.

A small LRU (:class:`DecisionCache`) keyed by (goal sha256, context digest,
backend config, hints) with a TTL skips re-asking backends for a goal it just
decided under the same knowledge. A hit is marked ``cache.hit: true`` in the
record and still gets its own trace line (a run's outcome needs a trace id).

The goal text is never in the record unless the owner opted in with
``DOTTIE_TRACE_TEXT=1``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

from dottie_loop.context import ContextBudget, DecisionContext, build_context

DECISION_SCHEMA = "dottie-decision-record-1"
#: hint keys decide() understands; anything else is ignored (and not cached on)
HINT_KEYS = ("learned", "system_one", "insufficiency", "policy_exclusions", "hard_constraint", "repo")


class DecisionCache:
    """LRU + TTL. Thread-safe. ``DOTTIE_DECIDE_CACHE_TTL`` / ``_SIZE`` tune the default one."""

    def __init__(self, maxsize: int = 256, ttl_s: float = 30.0) -> None:
        self.maxsize = max(1, int(maxsize))
        self.ttl_s = float(ttl_s)
        self._d: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit is None or now - hit[0] > self.ttl_s:
                if hit is not None:
                    del self._d[key]
                self.misses += 1
                return None
            self._d.move_to_end(key)
            self.hits += 1
            return copy.deepcopy(hit[1])

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._d[key] = (time.monotonic(), copy.deepcopy(value))
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"size": len(self._d), "maxsize": self.maxsize, "ttl_s": self.ttl_s, "hits": self.hits, "misses": self.misses}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


DEFAULT_CACHE = DecisionCache(int(_env_float("DOTTIE_DECIDE_CACHE_SIZE", 256)), _env_float("DOTTIE_DECIDE_CACHE_TTL", 30.0))


def backend_config_key(backends: list[Any]) -> str:
    """What the advisory backends are, for the cache key (not their answers)."""
    parts = []
    for b in backends:
        fn = getattr(b, "config_key", None)
        if callable(fn):
            parts.append(str(fn()))
        else:
            w = getattr(b, "weights_path", None)
            try:
                mt = w.stat().st_mtime if w is not None and w.exists() else None
            except OSError:
                mt = None
            parts.append(f"{getattr(b, 'name', type(b).__name__)}:{w}:{mt}")
    return "|".join(parts)


def cache_key(goal: str, context_digest: str, backends_key: str, hints: dict[str, Any]) -> str:
    body = json.dumps({"g": hashlib.sha256(goal.encode("utf-8")).hexdigest(), "c": context_digest, "b": backends_key,
                       "h": {k: hints[k] for k in sorted(hints) if k in HINT_KEYS}}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _system_one_view(advisory: dict[str, Any]) -> dict[str, Any] | None:
    s1 = advisory.get("system_one")
    if not isinstance(s1, dict) or not s1.get("enabled"):
        return None
    return {k: s1.get(k) for k in ("available", "signal", "tier", "action", "safe", "severity", "shape_concentration",
                                   "mode", "authoritative", "reason")}


def decide(
    goal: str,
    *,
    hints: dict[str, Any] | None = None,
    providers: list[Any] | tuple[Any, ...] = (),
    budget: ContextBudget | None = None,
    backends: list[Any] | None = None,
    surface: str = "dottie_loop.decide",
    trace: bool = True,
    cache: DecisionCache | None = DEFAULT_CACHE,
    provenance: str = "production",
) -> dict[str, Any]:
    """Decide a tier for ``goal``. Returns the router output plus ``decision`` (the record).

    ``hints``: ``learned`` (ask the orchestrator MLP), ``system_one`` (force
    System One on/off; default: on when ``DOTTIE_OS_URL`` is set),
    ``insufficiency`` (a recorded failure, permits one tier up),
    ``policy_exclusions``, ``hard_constraint``. ``providers`` empty = no
    context. ``cache`` None = no cache. ``provenance`` tags the trace line
    (:mod:`dottie_loop.provenance`; ``scout router probe`` passes
    ``benchmark-verified``).
    """
    from dottie_loop import traces
    from dottie_loop.backends import goal_features, trace_text_enabled
    from dottie_loop.router import default_backends, route_goal

    hints = dict(hints or {})
    t_start = time.perf_counter()
    ctx: DecisionContext | None = build_context(goal, list(providers), budget) if providers else None
    t_ctx = time.perf_counter()
    if backends is None:
        backends = default_backends(learned=bool(hints.get("learned")),
                                    system_one=hints.get("system_one") if isinstance(hints.get("system_one"), bool) else None)
    bkey = backend_config_key(backends)
    key = cache_key(goal, ctx.digest if ctx else "", bkey, hints) if cache is not None else None
    cached = cache.get(key) if cache is not None and key is not None else None
    excl = hints.get("policy_exclusions")
    if cached is not None:
        out = cached
        route_ms = 0.0
        backend_ms = {k: 0.0 for k in (out.get("advisory") or {}) if k != "heuristic"}
    else:
        out = route_goal(
            goal,
            backends=backends,
            policy_exclusions=set(excl) if isinstance(excl, (list, set, tuple)) else None,
            insufficiency=hints.get("insufficiency") if isinstance(hints.get("insufficiency"), dict) else None,
            hard_constraint=hints.get("hard_constraint") if isinstance(hints.get("hard_constraint"), dict) else None,
            surface=surface,
            trace=False,
            context=ctx,
        )
        route_ms = round((time.perf_counter() - t_ctx) * 1000.0, 3)
        backend_ms = {k: v.get("latency_ms", 0.0) for k, v in (out.get("advisory") or {}).items()
                      if k != "heuristic" and isinstance(v, dict) and "latency_ms" in v}
        if cache is not None and key is not None:
            cache.put(key, {k: v for k, v in out.items() if k not in ("trace", "decision")})
    feats = goal_features(goal)
    total_ms = round((time.perf_counter() - t_start) * 1000.0, 3)
    record: dict[str, Any] = {
        "schema": DECISION_SCHEMA,
        "decision_id": f"dc_{uuid.uuid4().hex[:20]}",
        "goal_sha256": feats["goal_sha256"],
        "tier": out["moma_tier"],
        "spec_tier": out["spec_tier"],
        "authority": out["authority"],
        "heuristic_tier": out["heuristic_tier"],
        "system_one": _system_one_view(out.get("advisory") or {}),
        "context": ctx.record() if ctx is not None else None,
        "latency_ms": {
            "context": round((t_ctx - t_start) * 1000.0, 3),
            "route": route_ms,
            "backends": backend_ms,
            "total": total_ms,
        },
        "cache": {"hit": cached is not None, "key": key[:16] if key else None, "enabled": cache is not None},
        "surface": surface,
    }
    if trace_text_enabled():
        record["goal_text"] = goal
    out = dict(out)
    out["trace"] = (
        traces.record_route(out, surface=surface, goal=goal, features=feats, context=ctx,
                            extra={k: record[k] for k in ("decision_id", "latency_ms", "cache")},
                            provenance=provenance)
        if trace
        else {"trace_id": None, "path": None}
    )
    record["trace_id"] = out["trace"]["trace_id"]
    out["decision"] = record
    return out
