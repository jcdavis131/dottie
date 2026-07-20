# Solo personal project, no connection to employer, built with public/free-tier only
"""format_query_answer must use the shared measured estimators and carry basis into cost.json."""

import json

from personal_graphify.build import build_graph, enrich_graph
from personal_graphify.export import export_json
from personal_graphify.extract import extract_all
from personal_graphify.query import (
    format_cost_dashboard,
    format_query_answer,
    load_graph_json,
)


def _fixture_graph(tmp_path):
    src = tmp_path / "repo"
    src.mkdir()
    (src / "billing.py").write_text(
        "# NOTE: stripe webhook feeds mrr\n"
        "def stripe_webhook(payload):\n    return update_mrr(payload)\n\n"
        "def update_mrr(payload):\n    return payload\n",
        encoding="utf-8",
    )
    (src / "README.md").write_text(
        "# Billing\nStripe webhook drives [MRR](billing.py).\n", encoding="utf-8"
    )
    nodes, edges = extract_all([src / "billing.py", src / "README.md"])
    G = enrich_graph(build_graph(nodes, edges))
    out = tmp_path / "out"
    out.mkdir()
    gpath = out / "graph.json"
    export_json(G, gpath)
    return load_graph_json(gpath), gpath


class TestQueryCostHonesty:
    def test_answer_reports_measured_basis(self, tmp_path):
        G, gpath = _fixture_graph(tmp_path)
        ans = format_query_answer(G, "stripe webhook", graph_path=gpath)
        assert "measured: sum of indexed file bytes / 4" in ans
        # no trace of the old nodes*50 model
        assert f"naive ~{G.number_of_nodes() * 50} " not in ans

    def test_cost_json_entry_carries_basis(self, tmp_path):
        G, gpath = _fixture_graph(tmp_path)
        format_query_answer(G, "stripe webhook", graph_path=gpath)
        cost = json.loads((gpath.parent / "cost.json").read_text(encoding="utf-8"))
        assert cost["queries"], "query should be logged"
        entry = cost["queries"][-1]
        assert entry["basis"].startswith("measured")
        assert entry["saved"] == max(0, entry["naive"] - entry["scoped"])

    def test_dashboard_never_prices_unmeasured_basis(self, tmp_path):
        cost_path = tmp_path / "cost.json"
        cost_path.write_text(
            json.dumps(
                {
                    "nodes": 1,
                    "edges": 0,
                    "queries": [
                        {
                            "ts": "2026-01-01T00:00:00",
                            "question": "q1",
                            "naive": 100000,
                            "scoped": 100,
                            "saved": 99900,
                            "reduction_x": 1000.0,
                            "mode": "lexical",
                            "basis": "estimated: node-count heuristic",
                        },
                        {
                            "ts": "2026-01-01T00:00:01",
                            "question": "q2",
                            "naive": 2000,
                            "scoped": 1000,
                            "saved": 1000,
                            "reduction_x": 2.0,
                            "mode": "lexical",
                            "basis": "measured: sum of indexed file bytes / 4",
                        },
                    ],
                    "total_saved_tokens": 100900,
                    "total_naive": 102000,
                    "total_scoped": 1100,
                }
            ),
            encoding="utf-8",
        )
        dash = format_cost_dashboard(cost_path)
        # only the measured 1000 tokens get monetized: 1000 * 0.005/1000 = $0.005 → $0.01
        assert "1000 measured-basis tokens saved" in dash
        assert "excluded from $ figure" in dash
