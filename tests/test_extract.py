# Solo personal project, no connection to employer, built with public/free-tier only
"""extract.py — Python AST, JS regex fallback, Markdown structure, rationale linking."""
from personal_graphify.extract import extract_python, extract_js_generic, extract_markdown, extract_file


def _ids(nodes):
    return {n["id"] for n in nodes}


def _edge_set(edges):
    return {(e["source"], e["target"], e["type"]) for e in edges}


class TestPythonExtraction:
    def test_defs_imports_and_calls(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(
            "import os\n"
            "from pathlib import Path\n\n"
            "class Widget:\n"
            "    pass\n\n"
            "def helper():\n"
            "    return 1\n\n"
            "def main():\n"
            "    return helper()\n",
            encoding="utf-8",
        )
        nodes, edges = extract_python(f)
        labels = {n["label"] for n in nodes}
        assert {"mod.py", "Widget", "helper", "main", "os", "pathlib"} <= labels
        es = _edge_set(edges)
        file_id = f"file:{f}"
        assert (file_id, "module:os", "imports") in es
        # main calls helper (INFERRED)
        call_edges = [e for e in edges if e["type"] == "calls"]
        assert any(e["target"] == "func:helper" for e in call_edges)
        # defines edges are EXTRACTED
        assert all(e["confidence"] == "EXTRACTED" for e in edges if e["type"] == "defines")

    def test_rationale_links_to_nearest_function_above(self, tmp_path):
        f = tmp_path / "r.py"
        f.write_text(
            "def first():\n"
            "    return 1\n\n"
            "def second():\n"
            "    # WHY: cache invalidation is hard\n"
            "    return 2\n",
            encoding="utf-8",
        )
        nodes, edges = extract_python(f)
        rats = [n for n in nodes if n["type"] == "rationale"]
        assert len(rats) == 1
        assert rats[0]["kind"] == "WHY"
        link = [e for e in edges if e["type"] == "has_rationale"]
        assert len(link) == 1
        assert link[0]["source"].startswith("func:second:")
        assert link[0]["target"] == rats[0]["id"]


class TestJsExtraction:
    def test_regex_fallback_functions_classes_imports(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text(
            "import React from 'react';\n"
            "const doThing = (x) => x + 1;\n"
            "function plain(y) { return y; }\n"
            "class Store {}\n"
            "// NOTE: store is a singleton\n",
            encoding="utf-8",
        )
        nodes, edges = extract_js_generic(f)
        labels = {n["label"] for n in nodes if n["type"] in ("function", "class")}
        assert {"doThing", "plain", "Store"} <= labels
        mods = {n["label"] for n in nodes if n["type"] == "module"}
        assert "react" in mods
        rats = [n for n in nodes if n["type"] == "rationale"]
        assert len(rats) == 1 and rats[0]["kind"] == "NOTE"


class TestMarkdownExtraction:
    def test_headings_hierarchy_and_links(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text(
            "# Top\n\n"
            "## Child\n\n"
            "See [the code](src/main.py) and [[WikiPage]].\n",
            encoding="utf-8",
        )
        nodes, edges = extract_markdown(f)
        concepts = {n["label"] for n in nodes if n["type"] == "concept"}
        assert {"Top", "Child"} <= concepts
        es = _edge_set(edges)
        top_id = f"concept:Top:{f}"
        child_id = f"concept:Child:{f}"
        assert (top_id, child_id, "contains") in es  # heading hierarchy
        refs = {n["label"] for n in nodes if n["type"] == "reference"}
        assert "src/main.py" in refs


class TestExtractFileDedup:
    def test_duplicate_node_ids_deduped(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("# Stripe\n\nstripe mrr stripe again\n", encoding="utf-8")
        nodes, edges = extract_file(f)
        ids = [n["id"] for n in nodes]
        assert len(ids) == len(set(ids))
