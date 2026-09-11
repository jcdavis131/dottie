"""Layered memory and knowledge graph (spec §15). Recall never outranks evidence.

Layers: working (ephemeral), episodic (append-only events), semantic (evidence-
backed facts with confidence and provenance), graph (versioned edges with source
and observed time), artifact (content-addressed, handled by the other modules).

Write-back contract: only stable, reusable information earns durable memory; a
write must attach evidence, provenance class, confidence, sensitivity and a
review time; confidence below 0.4 is a HINT and cannot drive an external action;
user corrections supersede earlier memory and propagate to derived indexes.

Retrieval contract: filter by tenant/scope/sensitivity/time validity; exact ids
and lexical matches before similarity; rank by relevance, source authority,
recency, confidence and a contradiction penalty; return evidence references
with every memory; expose conflicts and mark resolution required.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import new_id, now_iso, parse_iso

HINT_THRESHOLD = 0.4
PROVENANCE_CLASSES = frozenset({"user_stated", "verified_tool", "document", "inferred", "model_output"})
AUTHORITY: dict[str, float] = {"user_stated": 1.0, "verified_tool": 0.9, "document": 0.7, "inferred": 0.4, "model_output": 0.3}
SENSITIVITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NODE_TYPES = frozenset({"goal", "actor", "run", "plan", "step", "tool", "skill", "source", "fact", "artifact", "dataset", "model", "evaluation", "release", "incident", "person"})
EDGE_TYPES = frozenset({"depends_on", "derived_from", "verified_by", "supersedes", "approved_by", "rolled_back_to", "mentions", "resolves_to"})


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


@dataclass
class Fact:
    fact_id: str
    key: str
    value: str
    evidence: list[str]
    provenance: str
    confidence: float
    sensitivity: str
    tenant: str
    scope: str
    created_at: str
    review_at: str | None = None
    superseded_by: str | None = None
    hint: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Edge:
    edge_id: str
    src: str
    rel: str
    dst: str
    graph: str  # "workflow" | "history"
    source: str
    confidence: float
    first_seen: str
    last_confirmed: str
    sensitivity: str = "P1"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class MemoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        self.working: dict[str, Any] = {}
        self.episodic: list[dict[str, Any]] = []
        self.facts: dict[str, Fact] = {}
        self.edges: dict[str, Edge] = {}
        self.people: dict[str, str] = {}  # confirmed name -> entity id
        self._index: dict[str, set[str]] = {}  # key -> active fact ids (derived)
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    # -- episodic (append-only) --
    def record(self, event: dict[str, Any]) -> None:
        rec = {"at": now_iso(), **event}
        self.episodic.append(rec)
        if self.root:
            with (self.root / "episodic.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")

    # -- semantic write-back --
    def remember(self, key: str, value: str, *, evidence: list[str], provenance: str, confidence: float, sensitivity: str = "P1", tenant: str = "local", scope: str = "global", review_at: str | None = None) -> Fact:
        if not evidence:
            raise InvalidInputError("memory writes must attach evidence", field="evidence")
        if provenance not in PROVENANCE_CLASSES:
            raise InvalidInputError(f"unknown provenance class {provenance!r}", field="provenance")
        if not 0.0 <= confidence <= 1.0:
            raise InvalidInputError("confidence must be in [0, 1]", field="confidence")
        if sensitivity not in SENSITIVITY_RANK:
            raise InvalidInputError("unknown sensitivity", field="sensitivity")
        if sensitivity == "P3":
            raise PolicyDeniedError("P3 restricted values are never stored in memory", "sensitivity")
        fact = Fact(fact_id=new_id("fact_"), key=key, value=value, evidence=list(evidence), provenance=provenance, confidence=confidence, sensitivity=sensitivity, tenant=tenant, scope=scope, created_at=now_iso(), review_at=review_at, hint=confidence < HINT_THRESHOLD)
        self.facts[fact.fact_id] = fact
        self._index.setdefault(key, set()).add(fact.fact_id)
        self.record({"kind": "remember", "fact_id": fact.fact_id, "key": key, "hint": fact.hint})
        return fact

    def correct(self, fact_id: str, value: str, *, evidence: list[str]) -> Fact:
        """A user correction supersedes; the old record stays, marked, and indexes update."""
        old = self.facts.get(fact_id)
        if old is None:
            raise InvalidInputError("unknown fact", field="fact_id")
        new = self.remember(old.key, value, evidence=evidence, provenance="user_stated", confidence=1.0, sensitivity=old.sensitivity, tenant=old.tenant, scope=old.scope)
        old.superseded_by = new.fact_id
        self._index[old.key].discard(old.fact_id)
        self.add_edge(new.fact_id, "supersedes", old.fact_id, graph="history", source="user_correction", confidence=1.0)
        self.record({"kind": "correct", "old": fact_id, "new": new.fact_id})
        return new

    def actionable(self, fact: Fact) -> bool:
        """Confidence below the hint threshold cannot silently drive an external action."""
        return not fact.hint and fact.superseded_by is None

    # -- retrieval --
    def recall(self, query: str, *, tenant: str = "local", scope: str | None = None, sensitivity_max: str = "P2", now: datetime | None = None, limit: int = 10) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        q = _tokens(query)
        # 1. filter
        cands = [f for f in self.facts.values() if f.superseded_by is None and f.tenant == tenant and (scope is None or f.scope in (scope, "global")) and SENSITIVITY_RANK[f.sensitivity] <= SENSITIVITY_RANK[sensitivity_max] and (f.review_at is None or parse_iso(f.review_at) > now)]
        # 2. exact identifiers and lexical matches before similarity
        exact = [f for f in cands if f.fact_id == query.strip() or f.key == query.strip()]
        lexical = [f for f in cands if f not in exact and (q & _tokens(f.key + " " + f.value))]
        # 3. rank
        by_key: dict[str, list[Fact]] = {}
        for f in cands:
            by_key.setdefault(f.key, []).append(f)

        def score(f: Fact) -> float:
            overlap = len(q & _tokens(f.key + " " + f.value)) / max(1, len(q))
            age_days = max(0.0, (now - parse_iso(f.created_at)).total_seconds() / 86400)
            recency = 1.0 / (1.0 + age_days / 30)
            contradiction = 0.5 if len({x.value for x in by_key[f.key]}) > 1 else 0.0
            return overlap * 2 + AUTHORITY[f.provenance] + recency + f.confidence - contradiction

        ranked = exact + sorted(lexical, key=score, reverse=True)
        conflicts = sorted({f.key for f in ranked if len({x.value for x in by_key[f.key]}) > 1})
        # 4-5. evidence references with each memory; conflicts exposed
        return {"query": query, "results": [{**f.to_dict(), "actionable": self.actionable(f), "conflict": f.key in conflicts} for f in ranked[:limit]], "resolution_required": conflicts, "evidence_only": True}

    # -- graph --
    def add_edge(self, src: str, rel: str, dst: str, *, graph: str, source: str, confidence: float, sensitivity: str = "P1") -> Edge:
        if rel not in EDGE_TYPES:
            raise InvalidInputError(f"unknown edge type {rel!r}", field="rel")
        if graph not in ("workflow", "history"):
            raise InvalidInputError("graph must be workflow|history", field="graph")
        key = f"{src}|{rel}|{dst}|{graph}"
        existing = next((e for e in self.edges.values() if f"{e.src}|{e.rel}|{e.dst}|{e.graph}" == key), None)
        if existing is not None:
            existing.last_confirmed = now_iso()
            existing.version += 1
            existing.confidence = max(existing.confidence, confidence)
            return existing
        e = Edge(edge_id=new_id("edge_"), src=src, rel=rel, dst=dst, graph=graph, source=source, confidence=confidence, first_seen=now_iso(), last_confirmed=now_iso(), sensitivity=sensitivity)
        self.edges[e.edge_id] = e
        return e

    def neighbors(self, node: str, graph: str | None = None) -> list[Edge]:
        return [e for e in self.edges.values() if node in (e.src, e.dst) and (graph is None or e.graph == graph)]

    # -- people resolution --
    def resolve_person(self, name: str, candidates: list[dict[str, str]]) -> dict[str, Any]:
        """Existing mapping first; same-name ambiguity asks ONCE; never infers traits."""
        key = name.strip().lower()
        if key in self.people:
            return {"resolved": self.people[key], "ask": False}
        matches = [c for c in candidates if c.get("name", "").strip().lower() == key]
        if len(matches) == 1:
            self.people[key] = matches[0]["id"]
            return {"resolved": matches[0]["id"], "ask": False}
        if not matches:
            return {"resolved": None, "ask": False, "reason": "no candidate"}
        return {"resolved": None, "ask": True, "candidates": [m["id"] for m in matches]}

    def confirm_person(self, name: str, entity_id: str) -> None:
        self.people[name.strip().lower()] = entity_id
        self.add_edge(name.strip().lower(), "resolves_to", entity_id, graph="workflow", source="user_confirmed", confidence=1.0)
