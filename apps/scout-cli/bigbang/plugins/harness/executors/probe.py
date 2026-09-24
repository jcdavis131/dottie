"""The tier probe: label a benchmark goal with its minimal sufficient tier.

For each curated goal (a JSONL benchmark: ``id``, ``goal``, ``task_type``,
``verifier``), run the cheapest tier's real executor, check the answer with
the goal's automatic verifier (:mod:`dottie_loop.verifiers`), and escalate one
tier at a time until it passes or ``max_tier`` is reached. Bounded: at most
one attempt per tier, tiers limited to :data:`PROBE_TIERS` (no tier with an
outside-world side effect is ever probed).

Outcomes, and what the pack does with them:

``labeled``              a tier passed and every cheaper tier really ran and
                         failed: the label is that tier.
``insufficient``         every tier up to ``max_tier`` ran and failed: no label.
``unavailable``          a tier's backend was unreachable (no Ollama, no key,
                         network down). The probe STOPS there, because a
                         higher tier passing would not show the unavailable
                         tier was insufficient. No label; the outcome is not
                         tagged real.
``labeled_upper_bound``  only with ``past_unavailable``: the probe continued
                         past an unavailable tier and a higher one passed. The
                         label is an upper bound; the pack refuses it unless
                         told ``allow_upper_bound``.

Each goal writes a route line (the heuristic's decision, through
:func:`dottie_loop.decide.decide`) and an outcome line, both with provenance
``benchmark-verified``. Answers go into the trace only under
``DOTTIE_TRACE_TEXT=1`` (otherwise their sha256).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.provenance import BENCHMARK, goal_norm_sha256
from dottie_loop.verifiers import validate_spec, verifier_for, verify

from bigbang.plugins.harness.executors.base import (
    PROBE_TIERS,
    SIDE_EFFECT_TIERS,
    ExecutorUnavailable,
    NotApplicable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bigbang.plugins.harness.executors.base import ExecResult

SURFACE = "scout.router.probe"


def load_bench(path: Path) -> tuple[list[dict[str, Any]], str]:
    """(goals, file sha256). Raises ValueError on a malformed goal or a duplicate normalised goal."""
    raw = Path(path).read_bytes()
    goals, seen_ids, seen_norm = [], set(), {}
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        g = json.loads(line)
        for k in ("id", "goal", "task_type"):
            if not g.get(k):
                raise ValueError(f"{path}:{n}: missing {k!r}")
        errs = validate_spec(verifier_for(g))
        if errs:
            raise ValueError(f"{path}:{n} ({g['id']}): {errs}")
        if g["id"] in seen_ids:
            raise ValueError(f"{path}:{n}: duplicate id {g['id']}")
        key = goal_norm_sha256(g["goal"])
        if key in seen_norm:
            raise ValueError(f"{path}:{n}: {g['id']} duplicates {seen_norm[key]} after normalisation")
        seen_ids.add(g["id"])
        seen_norm[key] = g["id"]
        goals.append(g)
    return goals, hashlib.sha256(raw).hexdigest()


def tiers_up_to(max_tier: str) -> tuple[str, ...]:
    if max_tier in SIDE_EFFECT_TIERS:
        raise ValueError(f"{max_tier} has outside-world side effects; the probe never runs it")
    if max_tier not in PROBE_TIERS:
        raise ValueError(f"max tier must be one of {PROBE_TIERS}")
    return PROBE_TIERS[: PROBE_TIERS.index(max_tier) + 1]


def _answer_field(text: str) -> dict[str, Any]:
    from dottie_loop.backends import trace_text_enabled

    if trace_text_enabled():
        return {"answer": text[:500]}
    return {"answer_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _attempt(tier: str, goal: dict[str, Any], run: Callable[[str], ExecResult]) -> tuple[dict[str, Any], bool]:
    """One tier's attempt: (record, passed). Unavailable is recorded, never raised."""
    t0 = time.perf_counter()
    try:
        res = run(goal["goal"])
    except ExecutorUnavailable as exc:
        return {"tier": tier, "status": "unavailable", "reason": str(exc)[:300]}, False
    except NotApplicable as exc:
        return {"tier": tier, "status": "not_applicable", "reason": str(exc)[:300], "executor": "real",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 3)}, False
    except Exception as exc:  # an executor crash is a failed real attempt, recorded as such
        return {"tier": tier, "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:240]}", "executor": "real",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 3)}, False
    check = verify(res.verifier_input(), verifier_for(goal))
    rec = {"tier": tier, "status": "passed" if check["passed"] else "failed", "executor": "real",
           "backend": res.backend, "tokens": res.tokens, "latency_ms": res.latency_ms, "cost_usd": res.cost_usd,
           "cost_basis": res.cost_basis, "n_sources": len(res.sources), "verifier": check, **_answer_field(res.answer)}
    return rec, bool(check["passed"])


def probe_goal(goal: dict[str, Any], *, max_tier: str = "deep_research", past_unavailable: bool = False,
               runners: dict[str, Callable[[str], ExecResult]] | None = None) -> dict[str, Any]:
    """Cheapest tier first, one tier up at a time, until the verifier passes."""
    from bigbang.plugins.harness.executors import TIER_RUNNERS

    runners = runners or TIER_RUNNERS
    attempts: list[dict[str, Any]] = []
    unknown: list[str] = []
    for tier in tiers_up_to(max_tier):
        rec, passed = _attempt(tier, goal, runners[tier])
        attempts.append(rec)
        if rec["status"] == "unavailable":
            unknown.append(tier)
            if not past_unavailable:
                return {"status": "unavailable", "minimal_tier": None, "attempts": attempts,
                        "unknown_tiers": unknown, "max_tier": max_tier}
            continue
        if passed:
            return {"status": "labeled_upper_bound" if unknown else "labeled", "minimal_tier": tier,
                    "attempts": attempts, "unknown_tiers": unknown, "max_tier": max_tier}
    return {"status": "insufficient_or_unavailable" if unknown else "insufficient", "minimal_tier": None,
            "attempts": attempts, "unknown_tiers": unknown, "max_tier": max_tier}


def outcome_for(probe: dict[str, Any], goal: dict[str, Any], bench_sha: str, run_id: str) -> dict[str, Any]:
    """The trace outcome line for one probe. ``executor: real`` only when real executors made the observation."""
    ran = [a for a in probe["attempts"] if a["status"] != "unavailable"]
    passed = [a for a in ran if a["status"] == "passed"]
    costs = [a.get("cost_usd", 0.0) for a in ran]
    labeled = probe["status"] in ("labeled", "labeled_upper_bound")
    return {
        "executor": "real" if ran and probe["status"] != "unavailable" else "unavailable",
        "provenance": BENCHMARK,
        "run_id": run_id,
        "ok": True,
        "probe": probe,
        "verified": labeled,
        "verifier": passed[0]["verifier"]["verifier"] if passed else None,
        "backend": passed[0].get("backend") if passed else None,
        "backends": sorted({a.get("backend") for a in ran if a.get("backend")}),
        "tokens": {"total": sum(int(((a.get("tokens") or {}).get("total")) or 0) for a in ran)},
        "latency_ms": round(sum(float(a.get("latency_ms") or 0.0) for a in ran), 3),
        "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 8),
        "bench": {"id": goal["id"], "set_sha256": bench_sha, "task_type": goal["task_type"]},
        "n_nodes": len(ran),
        "ok_nodes": len(passed),
        "failed_nodes": len(ran) - len(passed),
        "escalated": len(ran) > 1,
    }


def run_probe(bench: Path, *, limit: int = 0, offset: int = 0, max_tier: str = "deep_research",
              past_unavailable: bool = False, ids: list[str] | None = None,
              runners: dict[str, Callable[[str], ExecResult]] | None = None) -> dict[str, Any]:
    """Probe benchmark goals, write benchmark-verified traces, return a summary of what was observed."""
    from dottie_loop import traces
    from dottie_loop.decide import decide

    tiers_up_to(max_tier)
    goals, bench_sha = load_bench(bench)
    if ids:
        goals = [g for g in goals if g["id"] in set(ids)]
    goals = goals[offset:]
    if limit > 0:
        goals = goals[:limit]
    rows = []
    for g in goals:
        routed = decide(g["goal"], providers=(), surface=SURFACE, cache=None, provenance=BENCHMARK)
        probe = probe_goal(g, max_tier=max_tier, past_unavailable=past_unavailable, runners=runners)
        out = outcome_for(probe, g, bench_sha, f"probe-{g['id']}-{routed['trace']['trace_id']}")
        traces.record_outcome(routed["trace"]["trace_id"], out, surface=SURFACE, provenance=BENCHMARK)
        rows.append({"id": g["id"], "task_type": g["task_type"], "status": probe["status"],
                     "minimal_tier": probe["minimal_tier"], "heuristic_tier": routed["heuristic_tier"],
                     "trace_path": routed["trace"]["path"], "outcome": out})
    return summarize(rows, bench=str(bench), bench_sha=bench_sha, max_tier=max_tier, past_unavailable=past_unavailable)


def summarize(rows: list[dict[str, Any]], **head: Any) -> dict[str, Any]:
    labeled = [r for r in rows if r["minimal_tier"]]
    reasons = Counter(a["reason"][:120] for r in rows for a in r["outcome"]["probe"]["attempts"]
                      if a["status"] == "unavailable")
    costs = [r["outcome"]["cost_usd"] for r in rows]
    return {
        **head,
        "goals": len(rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "minimal_tier": dict(Counter(r["minimal_tier"] for r in labeled)),
        "by_task_type": {t: dict(Counter(r["status"] for r in rows if r["task_type"] == t))
                         for t in sorted({r["task_type"] for r in rows})},
        "heuristic_agrees_with_label": sum(1 for r in labeled if r["heuristic_tier"] == r["minimal_tier"]),
        "heuristic_cheaper_than_label": sum(1 for r in labeled if _cheaper(r["heuristic_tier"], r["minimal_tier"])),
        "heuristic_dearer_than_label": sum(1 for r in labeled if _cheaper(r["minimal_tier"], r["heuristic_tier"])),
        "attempts": dict(Counter(f"{a['tier']}:{a['status']}" for r in rows for a in r["outcome"]["probe"]["attempts"])),
        "tokens_total": sum(r["outcome"]["tokens"]["total"] for r in rows),
        "latency_ms_total": round(sum(r["outcome"]["latency_ms"] for r in rows), 3),
        "cost_usd_total": None if any(c is None for c in costs) else round(sum(costs), 8),
        "unavailable_reasons": dict(reasons.most_common(5)),
        "trace_files": sorted({r["trace_path"] for r in rows if r["trace_path"]}),
    }


def _cheaper(a: str | None, b: str | None) -> bool:
    from dottie_loop.backends import TIER_ORDER

    return a in TIER_ORDER and b in TIER_ORDER and TIER_ORDER.index(a) < TIER_ORDER.index(b)
