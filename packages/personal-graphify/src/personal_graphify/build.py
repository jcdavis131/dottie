"""
build.py — NetworkX graph build + enrich
Solo personal project, no connection to employer, built with public/free-tier only
"""

import networkx as nx


def build_graph(nodes: list[dict], edges: list[dict]) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for n in nodes:
        nid = n["id"]
        # ensure label sanitized done later in export
        G.add_node(nid, **n)
    for e in edges:
        src = e["source"]
        tgt = e["target"]
        # ensure nodes exist even if not defined (e.g., func:xxx refs)
        if src not in G:
            G.add_node(src, id=src, label=src, type="inferred_ref")
        if tgt not in G:
            G.add_node(tgt, id=tgt, label=tgt, type="inferred_ref")
        # filter type/confidence handled explicitly to avoid duplicate kw
        filtered = {
            k: v
            for k, v in e.items()
            if k not in ("source", "target", "type", "confidence")
        }
        G.add_edge(
            src,
            tgt,
            type=e.get("type", "references"),
            confidence=e.get("confidence", "INFERRED"),
            **filtered,
        )
    return G


def enrich_graph(G: nx.MultiDiGraph):
    # degree
    deg = dict(G.degree())
    for nid in G.nodes:
        G.nodes[nid]["degree"] = deg.get(nid, 0)
    # simple god node score
    return G
