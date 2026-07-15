"""
analyze.py — god nodes, surprises, token reduction stats
Solo personal project, no connection to employer, built with public/free-tier only
"""
import networkx as nx
from typing import List, Dict, Tuple
from collections import Counter

def god_nodes(G: nx.MultiDiGraph, top_n: int = 15) -> List[Tuple[str, Dict]]:
    # highest degree + high betweenness-ish: use degree centrality as proxy cheap
    deg = dict(G.degree())
    sorted_nodes = sorted(G.nodes(data=True), key=lambda x: deg.get(x[0],0), reverse=True)
    return sorted_nodes[:top_n]

def surprise_edges(G: nx.MultiDiGraph, top_n: int = 15) -> List[Dict]:
    # edges connecting different communities that are unexpected
    surprises = []
    for u, v, data in G.edges(data=True):
        cu = G.nodes[u].get("community", -1)
        cv = G.nodes[v].get("community", -1)
        if cu != cv:
            # cross-community
            # score by combination of file distance + type
            fu = G.nodes[u].get("file","")
            fv = G.nodes[v].get("file","")
            score = 0
            if fu and fv and fu != fv:
                score += 2
            if G.nodes[u].get("type") != G.nodes[v].get("type"):
                score += 1
            surprises.append({"source": u, "target": v, "data": data, "cross": (cu,cv), "score": score, "file_diff": fu!=fv})
    surprises_sorted = sorted(surprises, key=lambda x: x["score"], reverse=True)
    return surprises_sorted[:top_n]

def token_stats(G: nx.MultiDiGraph, files_count: int) -> Dict:
    # rough token estimation: naive would be sum file sizes /4, graph query ~ number nodes in subgraph * avg 20 tokens
    est_naive_tokens = G.number_of_nodes()*50 + files_count*200  # placeholder
    est_query_tokens = 1500
    reduction = est_naive_tokens / max(est_query_tokens,1)
    return {"naive": est_naive_tokens, "query": est_query_tokens, "reduction": round(reduction,1)}
