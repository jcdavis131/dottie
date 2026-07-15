"""
cluster.py — community detection (Leiden if available, else greedy modularity)
Solo personal project, no connection to employer, built with public/free-tier only
"""
import networkx as nx
from typing import Dict, List
import itertools

def detect_communities(G: nx.MultiDiGraph) -> Dict[str, int]:
    # Convert to undirected simple graph for clustering
    UG = nx.Graph()
    for u, v in G.edges():
        # add with weight
        if UG.has_edge(u, v):
            UG[u][v]["weight"] = UG[u][v].get("weight",0)+1
        else:
            UG.add_edge(u, v, weight=1)
    for n in G.nodes:
        if n not in UG:
            UG.add_node(n)

    # Try leiden if installed
    try:
        import leidenalg, igraph
        # convert
        g = igraph.Graph.from_networkx(UG)
        part = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition)
        clustering = {}
        for i, cluster in enumerate(part):
            for idx in cluster:
                node_name = g.vs[idx]["_nx_name"]
                clustering[node_name] = i
        return clustering
    except Exception:
        pass

    # fallback: greedy modularity
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        coms = list(greedy_modularity_communities(UG, weight="weight"))
        clustering = {}
        for i, comm in enumerate(coms):
            for node in comm:
                clustering[node] = i
        return clustering
    except Exception:
        # final fallback: each node its own community, but group by file
        clustering = {}
        files = {}
        counter = 0
        for nid, data in G.nodes(data=True):
            f = data.get("file", "nofile")
            if f not in files:
                files[f]=counter
                counter+=1
            clustering[nid]=files[f]
        return clustering

def assign_communities(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    clustering = detect_communities(G)
    for nid in G.nodes:
        G.nodes[nid]["community"] = clustering.get(nid, 0)
    return G

def community_summary(G: nx.MultiDiGraph) -> List[Dict]:
    # summarize communities
    from collections import Counter, defaultdict
    comm_nodes = defaultdict(list)
    for nid, data in G.nodes(data=True):
        comm_nodes[data.get("community",0)].append((nid, data))
    summaries = []
    for comm_id, nodes in sorted(comm_nodes.items(), key=lambda x: len(x[1]), reverse=True):
        labels = [data.get("label","")[:30] for _, data in nodes[:8]]
        summaries.append({
            "id": comm_id,
            "size": len(nodes),
            "sample_labels": labels,
            "types": Counter([data.get("type","") for _, data in nodes]).most_common(5)
        })
    return summaries
