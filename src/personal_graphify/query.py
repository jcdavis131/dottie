"""
query.py — query/path/explain against graph.json (no LLM needed, BFS subgraph)
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import networkx as nx
from pathlib import Path
from typing import List, Dict, Optional
import re

def load_graph_json(path: Path) -> nx.MultiDiGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    G = nx.MultiDiGraph()
    for n in data.get("nodes", []):
        nid = n.get("id")
        G.add_node(nid, **n)
    for e in data.get("edges", []):
        src = e.get("source"); tgt = e.get("target")
        if not src or not tgt:
            continue
        attrs = {k:v for k,v in e.items() if k not in ("source","target")}
        G.add_edge(src, tgt, **attrs)
    return G

def search_nodes(G: nx.MultiDiGraph, query: str, limit: int = 25) -> List[Dict]:
    q = query.lower()
    results = []
    for nid, data in G.nodes(data=True):
        label = str(data.get("label","")).lower()
        typ = str(data.get("type","")).lower()
        file_ = str(data.get("file","")).lower()
        if q in label or q in typ or q in file_ or q in nid.lower():
            score = 3 if q in label else 1
            results.append((score, nid, data))
    results.sort(key=lambda x: (x[0], G.degree(x[1])), reverse=True)
    return [{"id": nid, **data, "score": score} for score, nid, data in results[:limit]]

def subgraph_for_query(G: nx.MultiDiGraph, query: str, hops: int = 2, limit_nodes: int = 60) -> nx.MultiDiGraph:
    matches = search_nodes(G, query, limit=5)
    if not matches:
        return G.subgraph([]).copy()
    # BFS from matches
    frontier = [m["id"] for m in matches if m["id"] in G]
    visited = set(frontier)
    for _ in range(hops):
        new_frontier = []
        for node in frontier:
            for nbr in G.successors(node):
                if nbr not in visited:
                    visited.add(nbr); new_frontier.append(nbr)
            for nbr in G.predecessors(node):
                if nbr not in visited:
                    visited.add(nbr); new_frontier.append(nbr)
        frontier = new_frontier
        if len(visited) > limit_nodes:
            break
    # cap
    visited_list = list(visited)[:limit_nodes]
    sub = G.subgraph(visited_list).copy()
    return sub

def shortest_path(G: nx.MultiDiGraph, source_q: str, target_q: str) -> Optional[List[str]]:
    # resolve queries to node ids
    src_candidates = search_nodes(G, source_q, limit=3)
    tgt_candidates = search_nodes(G, target_q, limit=3)
    if not src_candidates or not tgt_candidates:
        return None
    src = src_candidates[0]["id"]
    tgt = tgt_candidates[0]["id"]
    # convert to undirected for path finding
    UG = nx.Graph(G)
    try:
        path = nx.shortest_path(UG, source=src, target=tgt)
        return path
    except nx.NetworkXNoPath:
        return None
    except nx.NodeNotFound:
        return None

def explain_node(G: nx.MultiDiGraph, query: str) -> Optional[Dict]:
    matches = search_nodes(G, query, limit=1)
    if not matches:
        return None
    nid = matches[0]["id"]
    data = G.nodes[nid]
    neighbors = []
    for _, neigh, edata in G.out_edges(nid, data=True):
        nd = G.nodes[neigh]
        neighbors.append({"id": neigh, "label": nd.get("label"), "type": edata.get("type"), "confidence": edata.get("confidence"), "direction": "out"})
    for src, _, edata in G.in_edges(nid, data=True):
        nd = G.nodes[src]
        neighbors.append({"id": src, "label": nd.get("label"), "type": edata.get("type"), "confidence": edata.get("confidence"), "direction": "in"})
    return {"node": {"id": nid, **data}, "neighbors": neighbors[:50], "degree": G.degree(nid)}

def format_query_answer(G: nx.MultiDiGraph, query: str) -> str:
    sub = subgraph_for_query(G, query)
    if sub.number_of_nodes()==0:
        return f"No nodes found for query '{query}'. Try broader terms."
    lines = [f"Query: '{query}' — {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges in scoped subgraph (token-est ~{sub.number_of_nodes()*25} vs naive ~{G.number_of_nodes()*50})"]
    lines.append("")
    lines.append("Top matches:")
    for nid, data in list(sub.nodes(data=True))[:20]:
        lines.append(f"- {data.get('label')} ({data.get('type')}) in {data.get('file','')} [comm {data.get('community',0)}] deg {sub.degree(nid)}")
    lines.append("")
    lines.append("Edges:")
    for u,v,d in list(sub.edges(data=True))[:30]:
        lines.append(f"  {G.nodes[u].get('label',u)} --{d.get('type')} [{d.get('confidence')}]--> {G.nodes[v].get('label',v)}")
    return "\n".join(lines)

def format_path_answer(G: nx.MultiDiGraph, src_q: str, tgt_q: str) -> str:
    path = shortest_path(G, src_q, tgt_q)
    if not path:
        return f"No path found between '{src_q}' and '{tgt_q}' (tried top-3 matches each)."
    lines = [f"Shortest path {len(path)-1} hops between '{src_q}' and '{tgt_q}':", ""]
    for i in range(len(path)-1):
        u = path[i]; v = path[i+1]
        # find edge data
        edata = {}
        if G.has_edge(u,v):
            # get first edge data
            edata = list(G.get_edge_data(u,v).values())[0] if isinstance(list(G.get_edge_data(u,v).values())[0], dict) else {}
        else:
            # try reverse
            if G.has_edge(v,u):
                edata = list(G.get_edge_data(v,u).values())[0]
                u,v = v,u
        lines.append(f"  {G.nodes[u].get('label',u)} --{edata.get('type','?')} [{edata.get('confidence','?')}]--> {G.nodes[v].get('label',v)}")
    return "\n".join(lines)
