"""S-EMBER-style causal memory / provenance evaluation (research sequence stage 5).

Memory is not an undifferentiated bag. Causal edges carry an evidence pointer
(trace, eval, or incident) and a *measured* predicate. This module scores and
gates on that provenance. Missing or broken provenance fails closed.

Write-back still lives in :mod:`dottie_loop.memory` (hints below 0.4 stay
non-actionable; causal edges need :meth:`MemoryStore.add_causal_edge`). This
evaluation does not infer causality from co-occurrence and does not write
memory from synthetic or mock evals.

Relation to existing gates: this is a provenance gate, not a quality score.
It does not override §22 ``compute_reward`` or §24 ``evaluate_gates``. A
failing ember eval can be folded in via :func:`evaluation.merge_ember_verdict`
so a passing slice cannot hide broken provenance.
"""

from __future__ import annotations

from typing import Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import new_id, now_iso
from dottie_loop.memory import (
    CAUSAL_EDGE_TYPES,
    EVIDENCE_POINTER_KINDS,
    HINT_THRESHOLD,
    MEASURED_PREDICATE_KINDS,
    Edge,
    MemoryStore,
)
from dottie_loop.schema import active


def pointer_key(ptr: dict[str, str]) -> str:
    return f"{ptr['kind']}:{ptr['id']}"


def evaluate_causal_memory(
    store: MemoryStore,
    *,
    evidence_catalog: dict[str, dict[str, Any]],
    synthetic: bool = False,
    mock: bool = False,
) -> dict[str, Any]:
    """Score causal edges against a catalog of known evidence records.

    ``evidence_catalog`` maps ``kind:id`` → ``{valid: bool, ...}``. A missing
    key or ``valid is not True`` is broken provenance. Synthetic/mock sources
    are refused before any score is computed.
    """
    if synthetic or mock:
        raise PolicyDeniedError(
            "ember eval refuses synthetic or mock sources", field="source"
        )
    if not isinstance(evidence_catalog, dict):
        raise InvalidInputError("evidence catalog must be an object", field="evidence_catalog")

    rows: list[dict[str, Any]] = []
    broken: list[str] = []
    for edge in store.causal_edges():
        row, ok = _score_edge(edge, evidence_catalog)
        rows.append(row)
        if not ok:
            broken.append(edge.edge_id)

    n = len(rows)
    ungated = round(sum(r["score"] for r in rows) / n, 6) if n else None
    if n == 0:
        gate = "empty"
        gated: float | None = None
        reason = "no causal edges to evaluate; unmeasured, not a pass"
    elif broken:
        gate = "provenance_broken"
        gated = 0.0
        reason = f"{len(broken)} causal edge(s) missing or broken provenance"
    else:
        gate = "open"
        gated = ungated
        reason = "all causal edges have measured, catalogued provenance"

    facts_checked = [
        {
            "fact_id": f.fact_id,
            "provenance": f.provenance,
            "evidence": list(f.evidence),
            "hint": f.hint,
            "actionable": store.actionable(f),
        }
        for f in store.facts.values()
        if f.superseded_by is None
    ]
    hint_facts = [f["fact_id"] for f in facts_checked if f["hint"]]
    return {
        "schema": active("ember-eval"),
        "eval_id": new_id("ember_"),
        "n_edges": n,
        "n_broken": len(broken),
        "broken": broken,
        "ungated_score": ungated,
        "gated_score": gated,
        "gate": gate,
        "reason": reason,
        "audits": rows,
        "facts": facts_checked,
        "hint_facts": hint_facts,
        "hint_threshold": HINT_THRESHOLD,
        "causal_types": sorted(CAUSAL_EDGE_TYPES),
        "quality_from_provenance": False,
        "capability_claim": "none",
        "computed_at": now_iso(),
    }


def _score_edge(edge: Edge, catalog: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    ptr = edge.evidence_ptr
    measured = edge.measured
    reasons: list[str] = []
    if edge.rel not in CAUSAL_EDGE_TYPES:
        reasons.append("not a causal edge")
    if not ptr:
        reasons.append("missing evidence pointer")
    elif ptr.get("kind") not in EVIDENCE_POINTER_KINDS or not ptr.get("id"):
        reasons.append("malformed evidence pointer")
    if not measured:
        reasons.append("missing measured predicate")
    elif measured.get("kind") not in MEASURED_PREDICATE_KINDS or measured.get("value") is None:
        reasons.append("measured predicate unmeasured or unknown kind")

    key = pointer_key(ptr) if ptr and ptr.get("kind") and ptr.get("id") else None
    catalog_hit = catalog.get(key) if key else None
    if key is None:
        reasons.append("cannot resolve evidence pointer")
    elif catalog_hit is None:
        reasons.append(f"evidence {key} is not in the catalog")
    elif catalog_hit.get("valid") is not True:
        reasons.append(f"evidence {key} is broken or revoked")
    elif catalog_hit.get("kind") not in (None, ptr.get("kind")):
        reasons.append("catalog kind does not match pointer kind")

    ok = not reasons
    return (
        {
            "edge_id": edge.edge_id,
            "rel": edge.rel,
            "src": edge.src,
            "dst": edge.dst,
            "evidence_ptr": dict(ptr) if ptr else None,
            "measured": dict(measured) if measured else None,
            "score": 1.0 if ok else 0.0,
            "ok": ok,
            "reasons": reasons,
        },
        ok,
    )


def evaluate_from_records(
    edges: list[dict[str, Any]],
    *,
    evidence_catalog: dict[str, dict[str, Any]],
    facts: list[dict[str, Any]] | None = None,
    synthetic: bool = False,
    mock: bool = False,
) -> dict[str, Any]:
    """Evaluate causal edges without a live MemoryStore (CLI / offline)."""
    if synthetic or mock:
        raise PolicyDeniedError(
            "ember eval refuses synthetic or mock sources", field="source"
        )
    store = MemoryStore()
    for raw in edges:
        store.add_causal_edge(
            raw["src"],
            raw["rel"],
            raw["dst"],
            graph=raw.get("graph") or "history",
            source=raw.get("source") or "recorded",
            confidence=float(raw.get("confidence") or 1.0),
            evidence_ptr=raw.get("evidence_ptr") or {},
            measured=raw.get("measured") or {},
        )
    if facts:
        for f in facts:
            store.remember(
                f["key"],
                f["value"],
                evidence=list(f.get("evidence") or ["offline"]),
                provenance=f.get("provenance") or "document",
                confidence=float(f.get("confidence") or 0.5),
            )
    return evaluate_causal_memory(
        store, evidence_catalog=evidence_catalog, synthetic=synthetic, mock=mock
    )


__all__ = [
    "evaluate_causal_memory",
    "evaluate_from_records",
    "pointer_key",
]
