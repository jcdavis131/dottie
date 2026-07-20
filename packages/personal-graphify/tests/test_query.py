# Solo personal project, no connection to employer, built with public/free-tier only
"""query.py — search ranking sanity, subgraph scoping, impact BFS."""

from personal_graphify.build import build_graph, enrich_graph
from personal_graphify.query import (
    impact_analysis,
    search_nodes,
    shortest_path,
    subgraph_for_query,
)


def _graph():
    nodes = [
        {
            "id": "concept:turnover-shield",
            "label": "Turnover Shield",
            "type": "product",
            "desc": "Churn prediction",
        },
        {"id": "concept:mrr", "label": "MRR / Paid Users", "type": "business_metric"},
        {"id": "integration:stripe", "label": "Stripe", "type": "integration"},
        {
            "id": "file:billing.py",
            "label": "billing.py",
            "type": "file",
            "file": "billing.py",
        },
        {
            "id": "func:webhook",
            "label": "stripe_webhook",
            "type": "function",
            "file": "billing.py",
        },
        {"id": "concept:unrelated", "label": "Tennis DINOv3", "type": "product"},
    ]
    edges = [
        {
            "source": "file:billing.py",
            "target": "func:webhook",
            "type": "defines",
            "confidence": "EXTRACTED",
        },
        {
            "source": "func:webhook",
            "target": "integration:stripe",
            "type": "calls",
            "confidence": "INFERRED",
        },
        {
            "source": "integration:stripe",
            "target": "concept:mrr",
            "type": "enables",
            "confidence": "INFERRED",
        },
        {
            "source": "concept:turnover-shield",
            "target": "concept:mrr",
            "type": "tracks",
            "confidence": "INFERRED",
        },
    ]
    return enrich_graph(build_graph(nodes, edges))


class TestSearchRanking:
    def test_exact_label_match_ranks_first(self):
        G = _graph()
        results = search_nodes(G, "Turnover Shield", limit=5)
        assert results
        assert results[0]["label"] == "Turnover Shield"

    def test_no_match_returns_empty(self):
        G = _graph()
        assert search_nodes(G, "zzzznonexistentzzzz", limit=5) == []

    def test_results_sorted_by_score(self):
        G = _graph()
        results = search_nodes(G, "stripe webhook", limit=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


class TestSubgraphForQuery:
    def test_scoped_subgraph_contains_matches_and_neighbors(self):
        G = _graph()
        sub = subgraph_for_query(G, "stripe")
        assert "integration:stripe" in sub
        # 2-hop expansion reaches MRR
        assert "concept:mrr" in sub
        assert sub.number_of_nodes() <= G.number_of_nodes()

    def test_empty_query_result_is_empty_graph(self):
        G = _graph()
        sub = subgraph_for_query(G, "zzzznonexistentzzzz")
        assert sub.number_of_nodes() == 0


class TestImpactBFS:
    def test_downstream_depth_and_upstream(self):
        G = _graph()
        result = impact_analysis(G, "stripe_webhook", direction="both", depth=3)
        down_ids = {d["id"]: d["depth"] for d in result["downstream"]}
        assert down_ids.get("integration:stripe") == 1
        assert down_ids.get("concept:mrr") == 2
        up_ids = {u["id"] for u in result["upstream"]}
        assert "file:billing.py" in up_ids

    def test_depth_limit_respected(self):
        G = _graph()
        result = impact_analysis(G, "stripe_webhook", direction="downstream", depth=1)
        assert all(d["depth"] <= 1 for d in result["downstream"])
        assert {d["id"] for d in result["downstream"]} == {"integration:stripe"}

    def test_missing_node_reports_error(self):
        G = _graph()
        result = impact_analysis(G, "zzzznonexistentzzzz")
        assert "error" in result


class TestShortestPath:
    def test_path_between_concepts(self):
        G = _graph()
        path = shortest_path(G, "billing.py", "MRR")
        assert path is not None
        assert path[0] == "file:billing.py"
        assert path[-1] == "concept:mrr"
