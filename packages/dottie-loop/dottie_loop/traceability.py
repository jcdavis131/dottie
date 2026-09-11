"""The final acceptance artifact (spec §39): one traceability graph.

Links a real opted-in pair session to its redacted trace, QA reports, released
dataset, training run, challenger checkpoint, held-out evaluation, canary decision,
explicit approval, production release, served-state verification and subsequent
monitoring; a rollback drill links the release back to the known-good incumbent.

"The ecosystem is complete when every arrow in that graph resolves to immutable
evidence and every consequential edge names the human authority that approved it."
:func:`build_graph` assembles the graph from the records the chain produced and
:func:`validate_graph` says exactly which arrows do not resolve.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dottie_loop.hashing import digest, now_iso

#: (edge, from node type, to node type, needs a human authority)
EDGES: tuple[tuple[str, str, str, bool], ...] = (
    ("captured_as", "session", "trace", False),
    ("rewarded_by", "trace", "reward", False),
    ("qualified_by", "trace", "qa_report", False),
    ("released_in", "trace", "dataset", True),  # reviewer signs the manifest
    ("trained_on", "train_run", "dataset", False),
    ("produced", "train_run", "checkpoint", False),
    ("evaluated_by", "checkpoint", "eval_bundle", False),
    ("canaried_by", "checkpoint", "canary", True),  # canary traffic is approved
    ("approved_by", "release", "approval", True),
    ("released_as", "checkpoint", "release", True),
    ("served_verified_by", "release", "served_verification", False),
    ("monitored_by", "release", "monitoring", False),
    ("rolled_back_to", "release", "incumbent", True),
)
NODE_TYPES = ("session", "trace", "reward", "qa_report", "dataset", "train_run", "checkpoint", "eval_bundle", "canary", "approval", "release", "served_verification", "monitoring", "incumbent")


def _load(path: Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


_ID_KEYS = ("id", "trace_id", "dataset_id", "run_id", "release_id", "approval_id", "bundle_id", "checkpoint", "session_id")


def _node_id(node_type: str, rec: dict[str, Any]) -> str:
    for k in (f"{node_type}_id", *_ID_KEYS):
        if rec.get(k):
            return str(rec[k])
    return digest(rec)[:12]


def _authority(rec: dict[str, Any]) -> str | None:
    """The human named on the record: ``approved_by`` or ``approver`` (string or ``{subject_id}``)."""
    for k in ("approved_by", "approver"):
        v = rec.get(k)
        if isinstance(v, dict):
            v = v.get("subject_id")
        if isinstance(v, str) and v.strip():
            return v
    return None


def build_graph(records: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """``records`` maps node type -> record dict (or None). Every node gets a content hash."""
    nodes: dict[str, dict[str, Any]] = {}
    for t in NODE_TYPES:
        rec = records.get(t)
        if rec is None:
            continue
        nodes[t] = {"type": t, "id": _node_id(t, rec), "content_hash": digest(rec), "authority": _authority(rec), "evidence_ref": rec.get("evidence_ref")}
    edges = []
    for name, src, dst, needs_human in EDGES:
        edges.append({"edge": name, "from": src, "to": dst, "resolves": src in nodes and dst in nodes, "needs_human_authority": needs_human, "human_authority": nodes.get(dst, {}).get("authority") if needs_human else None})
    return {"schema": "traceability-graph-1.0.0", "nodes": nodes, "edges": edges, "built_at": now_iso()}


def validate_graph(graph: dict[str, Any], *, require_rollback: bool = True) -> dict[str, Any]:
    unresolved = [e["edge"] for e in graph["edges"] if not e["resolves"] and (require_rollback or e["edge"] != "rolled_back_to")]
    missing_authority = [e["edge"] for e in graph["edges"] if e["resolves"] and e["needs_human_authority"] and not e["human_authority"]]
    synthetic = [t for t, n in graph["nodes"].items() if n.get("synthetic")]
    complete = not unresolved and not missing_authority and not synthetic
    return {"complete": complete, "unresolved_edges": unresolved, "edges_missing_human_authority": missing_authority, "synthetic_nodes": synthetic, "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "verdict": "every arrow resolves to immutable evidence and every consequential edge names its approver" if complete else "not complete", "at": now_iso()}


def from_directory(root: Path) -> dict[str, Any]:
    """Read the chain's JSON files from one directory (names as the CLI writes them)."""
    root = Path(root)
    files = {"session": "session.json", "trace": "trace.json", "reward": "reward.json", "qa_report": "qa_report.json", "dataset": "manifest.json", "train_run": "train.json", "checkpoint": "checkpoint.json", "eval_bundle": "bundle.json", "canary": "canary.json", "approval": "approval.json", "release": "release.json", "served_verification": "served.json", "monitoring": "monitoring.json", "incumbent": "rollback.json"}
    return build_graph({t: _load(root / f) for t, f in files.items()})
