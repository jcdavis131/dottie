# Solo personal project, no connection to employer, built with public/free-tier only
"""Query CLI over the knowledge graph. Read-only; every answer cites sources.

    python -m dottie.kg.query stats
    python -m dottie.kg.query classes
    python -m dottie.kg.query hints einsum
    python -m dottie.kg.query incidents [key-substring]
    python -m dottie.kg.query preceded <node-id> [-k 8]
    python -m dottie.kg.query sites
    python -m dottie.kg.query node <node-id>
    python -m dottie.kg.query find <substring>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from dottie.kg.store import GraphStore

_DEFAULT_GRAPH = (Path(__file__).resolve().parents[2] / "data" / "kg"
                  / "graph.sqlite3")


def _fmt_props(props: Dict[str, Any], keep: int = 6) -> str:
    items = [(k, v) for k, v in props.items() if v not in (None, "", [], {})]
    return " ".join(f"{k}={v}" for k, v in items[:keep])


def cmd_stats(store: GraphStore, _args: argparse.Namespace) -> None:
    print(json.dumps(store.counts(), indent=2))


def cmd_classes(store: GraphStore, _args: argparse.Namespace) -> None:
    print("failure classes (primary + secondary matches, from the ledger COPY):")
    rows: List[tuple] = []
    for fc in store.nodes_by_type("failure_class"):
        edges = store.edges_to(fc["id"])
        classified = [e for e in edges if e["type"] == "classified_as"]
        primary = [e for e in classified if e["props"].get("primary")]
        rows.append((len(primary), len(classified), fc["id"]))
    for n_primary, n_all, fc_id in sorted(rows, reverse=True):
        print(f"  {fc_id:38s} primary={n_primary:3d} any-match={n_all:3d}")


def hint_efficacy(store: GraphStore, class_id: str) -> Dict[str, Any]:
    """Everything the graph knows about one failure class and its hint."""
    fc_id = f"failure_class:{class_id}"
    fc = store.node(fc_id)
    if fc is None:
        return {"error": f"unknown failure class {class_id!r}"}
    hints = [store.node(e["dst"]) for e in store.edges_from(fc_id)
             if e["type"] == "hinted_by"]
    died = []
    for e in store.edges_to(fc_id):
        if e["type"] != "classified_as":
            continue
        exp = store.node(e["src"])
        if exp:
            died.append({"id": exp["id"], "state": exp["props"].get("state"),
                         "attempts": exp["props"].get("attempts"),
                         "signature": e["props"].get("signature"),
                         "source_ref": e["source_ref"]})
    encounters = [e for e in store.edges_to(fc_id)
                  if e["type"] == "struggled_with"]
    cleared = [e for e in encounters if e["props"].get("cleared")]
    return {
        "failure_class": class_id,
        "pattern": fc["props"].get("pattern"),
        "hint": (hints[0]["label"] if hints and hints[0] else None),
        "n_encounters": len(encounters),
        "n_cleared": len(cleared),
        "clearance_rate": (round(len(cleared) / len(encounters), 3)
                           if encounters else None),
        "cleared_by": [e["src"] for e in cleared],
        "n_died_matching": len(died),
        "died": died,
        "caveat": ("per-attempt classes are re-derived from validation.history "
                   "via the kg taxonomy MIRROR of validate._HINTS — the "
                   "DeepRefine patch proposal logs hint_id first-class in "
                   "each history entry so this stops being a re-derivation."),
    }


def cmd_hints(store: GraphStore, args: argparse.Namespace) -> None:
    out = hint_efficacy(store, args.failure_class)
    if "error" in out:
        print(out["error"])
        return
    print(f"failure class : {out['failure_class']}  (pattern: {out['pattern']})")
    print(f"repair hint   : {out['hint']}")
    print(f"encounters    : {out['n_encounters']} correction trajectories hit "
          f"this class; {out['n_cleared']} cleared it "
          f"(clearance rate {out['clearance_rate']})")
    for src in out["cleared_by"][:args.limit]:
        print(f"    cleared: {src}")
    print(f"died matching : {out['n_died_matching']} experiments "
          f"(final failure in this class)")
    for d in out["died"][:args.limit]:
        print(f"    {d['id']}  state={d['state']} attempts={d['attempts']}  "
              f"[{d['source_ref']}]")
        if d.get("signature"):
            print(f"      sig: {d['signature'][:110]}")
    print(f"caveat: {out['caveat']}")


def refine_candidates(store: GraphStore, min_count: int = 2) -> List[Dict[str, Any]]:
    """DeepRefine judge+abduction, natively: cluster UNCLASSIFIED failure
    signatures from real correction trajectories and rank them as candidate
    new hint classes. Confidence by cluster size; apply stays operator-gated
    (a patch to validate._HINTS), never automatic."""
    clusters: Dict[str, Dict[str, Any]] = {}
    for etype in ("struggled_with", "classified_as"):
        for e in store.edges_to("failure_class:unclassified"):
            if e["type"] != etype:
                continue
            sig = e["props"].get("signature") or "(no signature)"
            c = clusters.setdefault(sig, {"signature": sig, "experiments": set(),
                                          "n_cleared": 0, "levels": set()})
            c["experiments"].add(e["src"])
            if e["props"].get("cleared"):
                c["n_cleared"] += 1
            if e["props"].get("level"):
                c["levels"].add(e["props"]["level"])
    out = []
    for c in clusters.values():
        n = len(c["experiments"])
        if n < min_count:
            continue
        confidence = "HIGH" if n >= 5 else ("MEDIUM" if n >= 3 else "LOW")
        out.append({"signature": c["signature"], "n_experiments": n,
                    "n_cleared": c["n_cleared"],
                    "levels": sorted(c["levels"]), "confidence": confidence,
                    "experiments": sorted(c["experiments"])[:6]})
    out.sort(key=lambda d: -d["n_experiments"])
    return out


def cmd_refine(store: GraphStore, args: argparse.Namespace) -> None:
    cands = refine_candidates(store, min_count=args.min_count)
    print(f"candidate NEW hint classes (unclassified clusters, >= "
          f"{args.min_count} experiments) — proposal only, apply is operator-gated:")
    if not cands:
        print("  none at this threshold")
    for c in cands:
        print(f"\n[{c['confidence']}] {c['n_experiments']} experiments, "
              f"{c['n_cleared']} self-cleared, levels={c['levels']}")
        print(f"  signature: {c['signature'][:160]}")
        for e in c["experiments"]:
            print(f"    {e}")


def cmd_incidents(store: GraphStore, args: argparse.Namespace) -> None:
    incidents = store.nodes_by_type("incident")
    if args.key:
        incidents = [i for i in incidents if args.key.lower() in i["id"].lower()]
    for inc in incidents:
        p = inc["props"]
        print(f"{inc['id']}  [{p.get('severity')}/{p.get('class')}]  "
              f"cited {inc['source_ref']} "
              f"(anchor_verified={p.get('anchor_verified')})")
        print(f"  {inc['label']}")
        if p.get("root_cause"):
            print(f"  root cause: {p['root_cause']}")
        for e in store.edges_from(inc["id"]):
            tgt = store.node(e["dst"])
            label = tgt["label"] if tgt else e["dst"]
            print(f"  -[{e['type']}]-> {e['dst']}  ({label})")
        print()


def cmd_preceded(store: GraphStore, args: argparse.Namespace) -> None:
    node = store.node(args.node_id)
    if node is None:
        matches = store.find_nodes(args.node_id, limit=5)
        if len(matches) == 1:
            node = matches[0]
        else:
            print(f"node {args.node_id!r} not found."
                  + (f" candidates: {[m['id'] for m in matches]}" if matches else ""))
            return
    print(f"target: {node['id']}  {node['label']}  [{node['source_ref']}]")
    chain = store.chain_back(node["id"], limit=args.k)
    if not chain:
        print("  no recorded predecessors (no preceded_by edges from this node)")
    for i, n in enumerate(chain, 1):
        print(f"  -{i} before: {n['id']}  {_fmt_props(n['props'])}  "
              f"[{n['source_ref']}]")


def cmd_sites(store: GraphStore, _args: argparse.Namespace) -> None:
    for s in store.nodes_by_type("site"):
        p = s["props"]
        probes = [e for e in store.edges_to(s["id"]) if e["type"] == "probed"]
        latest = probes[-1]["props"] if probes else {}
        print(f"{s['id']:14s} up_history={p.get('history_up_n')}/{p.get('history_n')}"
              f" avg_ms={p.get('history_avg_ms')} max_ms={p.get('history_max_ms')}"
              f" latest={latest}")


def cmd_node(store: GraphStore, args: argparse.Namespace) -> None:
    node = store.node(args.node_id)
    if node is None:
        print(f"node {args.node_id!r} not found")
        return
    print(json.dumps(node, indent=2, default=str))
    for e in store.edges_from(node["id"]):
        print(f"  -[{e['type']}]-> {e['dst']}  {_fmt_props(e['props'], 4)}")
    for e in store.edges_to(node["id"]):
        print(f"  <-[{e['type']}]- {e['src']}  {_fmt_props(e['props'], 4)}")


def cmd_find(store: GraphStore, args: argparse.Namespace) -> None:
    for n in store.find_nodes(args.substring, limit=args.limit):
        print(f"{n['id']:60s} {n['type']:14s} {n['label'][:50]}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dottie.kg.query")
    ap.add_argument("--graph", default=str(_DEFAULT_GRAPH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("classes")
    p = sub.add_parser("hints")
    p.add_argument("failure_class")
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("incidents")
    p.add_argument("key", nargs="?", default=None)
    p = sub.add_parser("preceded")
    p.add_argument("node_id")
    p.add_argument("-k", type=int, default=8, dest="k")
    sub.add_parser("sites")
    p = sub.add_parser("node")
    p.add_argument("node_id")
    p = sub.add_parser("find")
    p.add_argument("substring")
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("refine")
    p.add_argument("--min-count", type=int, default=2, dest="min_count")
    args = ap.parse_args(argv)
    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"graph not found at {graph_path} — run `python -m dottie.kg.build` first")
        return 2
    store = GraphStore(graph_path, readonly=True)
    try:
        {"stats": cmd_stats, "classes": cmd_classes, "hints": cmd_hints,
         "incidents": cmd_incidents, "preceded": cmd_preceded,
         "sites": cmd_sites, "node": cmd_node, "find": cmd_find,
         "refine": cmd_refine}[args.cmd](store, args)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
