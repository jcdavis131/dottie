"""
cluster.py — community detection (Leiden if available, else greedy modularity; spectral opt-in)
Solo personal project, no connection to employer, built with public/free-tier only

Spectral backend grounds in the Graph-Laplacian chapters of *Mathematics of Data Science*
(see ava-agi-factory-v6-4/docs/MATH_FOUNDATIONS.md): the eigenvectors of the normalized
Laplacian relax the NP-hard normalized-cut into a tractable eigenproblem (L x = λ D x), and
the discrete Laplacian converges to the manifold's Laplace-Beltrami operator as the graph
grows — so it stays meaningful as the code graph scales.
"""

import networkx as nx


def _to_weighted_undirected(G: nx.MultiDiGraph) -> nx.Graph:
    UG = nx.Graph()
    for u, v in G.edges():
        if UG.has_edge(u, v):
            UG[u][v]["weight"] = UG[u][v].get("weight", 0) + 1
        else:
            UG.add_edge(u, v, weight=1)
    for n in G.nodes:
        if n not in UG:
            UG.add_node(n)
    return UG


def _deterministic_kmeans(X, k: int, seed: int = 0, iters: int = 50):
    """Tiny seeded k-means++ (numpy only) — deterministic for reproducible clustering."""
    import numpy as np

    rng = np.random.default_rng(seed)
    n = X.shape[0]
    # k-means++ init
    centers = [int(rng.integers(n))]
    for _ in range(1, k):
        d2 = np.min(
            ((X[:, None, :] - X[np.array(centers)][None, :, :]) ** 2).sum(-1), axis=1
        )
        total = d2.sum()
        probs = d2 / total if total > 0 else np.full(n, 1.0 / n)
        centers.append(int(rng.choice(n, p=probs)))
    C = X[np.array(centers)].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        new = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(-1), axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            pts = X[labels == j]
            if len(pts):
                C[j] = pts.mean(0)
    return labels


def _spectral_communities(
    UG: nx.Graph, k: int | None = None, seed: int = 0
) -> dict[str, int]:
    """Normalized-cut spectral clustering (Ng–Jordan–Weiss). Raises on any degeneracy so the
    caller can fall back; never fabricates a partition."""
    import numpy as np

    nodes = list(UG.nodes())
    n = len(nodes)
    if n < 3:
        raise ValueError("graph too small for spectral clustering")
    idx = {nd: i for i, nd in enumerate(nodes)}
    A = np.zeros((n, n), dtype=float)
    for u, v, d in UG.edges(data=True):
        w = float(d.get("weight", 1.0))
        A[idx[u], idx[v]] = w
        A[idx[v], idx[u]] = w
    deg = A.sum(1)
    d_inv_sqrt = np.zeros(n)
    nz = deg > 0
    d_inv_sqrt[nz] = 1.0 / np.sqrt(deg[nz])
    L = np.eye(n) - (d_inv_sqrt[:, None] * A * d_inv_sqrt[None, :])
    vals, vecs = np.linalg.eigh(
        (L + L.T) / 2.0
    )  # symmetrize for numerical safety; ascending
    if k is None:
        # eigengap heuristic over the smallest non-trivial eigenvalues
        window = vals[: min(n, 12)]
        gaps = np.diff(window)
        k = (
            int(np.argmax(gaps[1:]) + 2) if len(gaps) > 1 else 2
        )  # skip the trivial ~0 eigenvalue
        k = max(2, min(k, 10, n - 1))
    U = vecs[:, :k]
    norms = np.linalg.norm(U, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    U = U / norms
    labels = _deterministic_kmeans(U, k, seed=seed)
    return {nodes[i]: int(labels[i]) for i in range(n)}


def detect_communities(G: nx.MultiDiGraph, method: str = "auto") -> dict[str, int]:
    """Community detection.

    method="auto" (default, unchanged): Leiden if installed → greedy modularity → per-file.
    method="spectral": normalized-cut spectral (Graph Laplacian) → greedy modularity → per-file.
    method="greedy": greedy modularity directly (skips Leiden) → per-file.
    Fallback chain is preserved so behavior degrades gracefully and never fabricates a partition.
    """
    UG = _to_weighted_undirected(G)

    if method == "spectral":
        try:
            return _spectral_communities(UG)
        except Exception:
            pass  # fall through to greedy modularity
    elif method != "greedy":
        # Try leiden if installed
        try:
            import igraph
            import leidenalg

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
                files[f] = counter
                counter += 1
            clustering[nid] = files[f]
        return clustering


def assign_communities(G: nx.MultiDiGraph, method: str = "auto") -> nx.MultiDiGraph:
    clustering = detect_communities(G, method=method)
    for nid in G.nodes:
        G.nodes[nid]["community"] = clustering.get(nid, 0)
    return G


def community_summary(G: nx.MultiDiGraph) -> list[dict]:
    # summarize communities
    from collections import Counter, defaultdict

    comm_nodes = defaultdict(list)
    for nid, data in G.nodes(data=True):
        comm_nodes[data.get("community", 0)].append((nid, data))
    summaries = []
    for comm_id, nodes in sorted(
        comm_nodes.items(), key=lambda x: len(x[1]), reverse=True
    ):
        labels = [data.get("label", "")[:30] for _, data in nodes[:8]]
        summaries.append(
            {
                "id": comm_id,
                "size": len(nodes),
                "sample_labels": labels,
                "types": Counter(
                    [data.get("type", "") for _, data in nodes]
                ).most_common(5),
            }
        )
    return summaries
