# Solo personal project, no connection to employer, built with public/free-tier only
"""Spectral community detection (Graph Laplacian) — separation, determinism, graceful fallback."""

import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from personal_graphify.cluster import (
    _spectral_communities,
    detect_communities,
)

pytest.importorskip("numpy")


def _two_cliques() -> nx.MultiDiGraph:
    """Two 4-node cliques joined by a single bridge edge — a clean 2-community graph."""
    G = nx.MultiDiGraph()
    a = ["a0", "a1", "a2", "a3"]
    b = ["b0", "b1", "b2", "b3"]
    for grp in (a, b):
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                G.add_edge(grp[i], grp[j])
    G.add_edge("a0", "b0")  # single bridge
    return G


class TestSpectral:
    def test_separates_two_cliques(self):
        clustering = detect_communities(_two_cliques(), method="spectral")
        a_comms = {clustering[n] for n in ["a1", "a2", "a3"]}
        b_comms = {clustering[n] for n in ["b1", "b2", "b3"]}
        # each clique's interior nodes share a community, and the two cliques differ
        assert len(a_comms) == 1 and len(b_comms) == 1
        assert a_comms != b_comms

    def test_deterministic(self):
        G = _two_cliques()
        assert detect_communities(G, method="spectral") == detect_communities(
            G, method="spectral"
        )

    def test_tiny_graph_falls_back_not_crash(self):
        G = nx.MultiDiGraph()
        G.add_edge("x", "y")
        # n<3 raises inside spectral → detect_communities falls through to greedy/per-file
        out = detect_communities(G, method="spectral")
        assert set(out) == {"x", "y"}

    def test_auto_method_unchanged_default(self):
        # default path must still return a full covering assignment
        G = _two_cliques()
        out = detect_communities(G)  # method="auto"
        assert set(out) == set(G.nodes())

    def test_spectral_direct_raises_on_too_small(self):
        UG = nx.Graph()
        UG.add_edge("p", "q")
        with pytest.raises(ValueError):
            _spectral_communities(UG)
