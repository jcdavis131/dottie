# Solo personal project, no connection to employer, built with public/free-tier only
"""export.py — HTML export must embed real JSON (not Python repr), JSON round-trip."""

import json
import re

import networkx as nx

from personal_graphify.export import export_html, export_json
from personal_graphify.query import load_graph_json


def _sample_graph() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    G.add_node(
        "file:a.py", label="a.py", type="file", file="a.py", degree=2, community=0
    )
    G.add_node(
        "func:main",
        label="main <script>",
        type="function",
        file="a.py",
        degree=1,
        community=1,
    )
    G.add_edge("file:a.py", "func:main", type="defines", confidence="EXTRACTED")
    G.add_edge("func:main", "file:a.py", type="calls", confidence="INFERRED")
    return G


class TestExportHtml:
    def test_embedded_arrays_are_valid_json(self, tmp_path):
        out = tmp_path / "graph.html"
        export_html(_sample_graph(), out)
        html_text = out.read_text(encoding="utf-8")

        # Extract the two embedded arrays and parse them with a strict JSON parser.
        m_nodes = re.search(r"new vis\.DataSet\((\[.*?\])\);\n", html_text, re.S)
        assert m_nodes, "nodes DataSet payload not found"
        arrays = re.findall(r"new vis\.DataSet\((\[.*?\])\);", html_text, re.S)
        assert len(arrays) == 2, "expected exactly nodes + edges arrays"
        nodes = json.loads(arrays[0])
        edges = json.loads(arrays[1])
        assert len(nodes) == 2
        assert len(edges) == 2
        # JS-invalid Python literals must not appear in the payloads
        for payload in arrays:
            assert re.search(r"\bTrue\b|\bFalse\b|\bNone\b|'", payload) is None
        # dashes is a real JSON bool styled by confidence
        by_type = {e["label"]: e["dashes"] for e in edges}
        assert by_type["defines"] is False and by_type["calls"] is True

    def test_labels_html_escaped(self, tmp_path):
        out = tmp_path / "graph.html"
        export_html(_sample_graph(), out)
        arrays = re.findall(
            r"new vis\.DataSet\((\[.*?\])\);", out.read_text(encoding="utf-8"), re.S
        )
        nodes = json.loads(arrays[0])
        labels = {n["label"] for n in nodes}
        assert any("&lt;script&gt;" in lbl for lbl in labels)
        assert not any("<script>" in lbl for lbl in labels)


class TestExportJsonRoundTrip:
    def test_build_export_load_equality(self, tmp_path):
        G = _sample_graph()
        out = tmp_path / "graph.json"
        export_json(G, out)
        G2 = load_graph_json(out)
        assert G2.number_of_nodes() == G.number_of_nodes()
        assert G2.number_of_edges() == G.number_of_edges()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["meta"] == {"nodes": 2, "edges": 2}
