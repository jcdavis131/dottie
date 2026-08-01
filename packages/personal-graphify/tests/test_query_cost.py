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
    log_query_cost,
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


class TestCostLogSurvivesCorruption:
    """log_query_cost is a read-modify-write on cost.json: a tolerant read paired with
    a write-back to the same file. Same bug shape as the vault (3e301cb), auth.json
    (38e7127) and telemetry.py (f274be8) — a torn cost.json used to be silently read as
    {} and the zeroed dict written straight back, permanently erasing every prior
    query's logged savings with no trace anywhere. This function must stay non-raising
    (a cost-log failure must never break the query it's logging), so the fix is the
    telemetry.py shape: preserve the bytes, say so on stderr, do not raise."""

    def test_corrupt_cost_json_is_preserved_and_announced_not_silently_lost(
        self, tmp_path, capsys
    ):
        graph_path = tmp_path / "graph.json"
        cost_path = tmp_path / "cost.json"
        cost_path.write_text("{not valid json at all", encoding="utf-8")

        log_query_cost(graph_path, "q", naive=100, scoped=10, reduction_x=10.0)

        corrupt_backups = list(tmp_path.glob("cost.json.corrupt-*"))
        assert len(corrupt_backups) == 1, "the torn file must be preserved, not discarded"
        assert corrupt_backups[0].read_text(encoding="utf-8") == "{not valid json at all"

        err = capsys.readouterr().err
        assert "cost.json" in err and "unreadable" in err

        # the log must still function afterwards — reset, not broken
        data = json.loads(cost_path.read_text(encoding="utf-8"))
        assert len(data["queries"]) == 1
        assert data["queries"][0]["naive"] == 100

    def test_cost_log_failure_never_raises_out_of_the_query_path(self, tmp_path):
        """The outer try/except's own stated contract: 'never break query on cost log
        failure'. A cost_path that cannot be created at all (parent missing) must not
        raise — the pre-existing guarantee this fix must not weaken."""
        graph_path = tmp_path / "missing_dir" / "graph.json"
        log_query_cost(graph_path, "q", naive=1, scoped=1, reduction_x=1.0)  # must not raise

    def test_write_is_atomic_no_temp_file_survives(self, tmp_path):
        """_atomic_write_text must leave no <name>.<pid>.tmp behind on success — a
        surviving temp file would mean a reader could observe a half-written cost.json."""
        graph_path = tmp_path / "graph.json"
        log_query_cost(graph_path, "q", naive=5, scoped=1, reduction_x=5.0)
        leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_repeated_calls_accumulate_rather_than_reset(self, tmp_path):
        """The property a silent-loss bug breaks: N calls must produce N queries, not
        1 — this would still pass if the read silently discarded prior state on every
        call given a fresh dict each time, so it is pinned as its own test."""
        graph_path = tmp_path / "graph.json"
        for i in range(3):
            log_query_cost(graph_path, f"q{i}", naive=10, scoped=1, reduction_x=10.0)
        cost_path = tmp_path / "cost.json"
        data = json.loads(cost_path.read_text(encoding="utf-8"))
        assert len(data["queries"]) == 3
        assert [q["question"] for q in data["queries"]] == ["q0", "q1", "q2"]
