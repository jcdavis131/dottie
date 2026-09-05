#!/usr/bin/env python3
"""Tests for scripts/dag_next.py. Run: uv run python scripts/test_dag_next.py"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dag_next


def node(nid, deps=(), status="ready", priority=3, size="M", repo="dottie", kind="infra"):
    return {
        "id": nid,
        "title": f"title {nid}",
        "repo": repo,
        "kind": kind,
        "status": status,
        "priority": priority,
        "size": size,
        "depends_on": list(deps),
    }


class ValidateTests(unittest.TestCase):
    def test_well_formed_is_clean(self):
        dag = {"nodes": [node("a", status="done"), node("b", ["a"])]}
        self.assertEqual(dag_next.validate(dag), [])

    def test_unknown_dependency(self):
        dag = {"nodes": [node("a", ["ghost"])]}
        self.assertTrue(any("unknown node 'ghost'" in e for e in dag_next.validate(dag)))

    def test_duplicate_id(self):
        dag = {"nodes": [node("a"), node("a")]}
        self.assertTrue(any("duplicate id" in e for e in dag_next.validate(dag)))

    def test_cycle_detected(self):
        dag = {"nodes": [node("a", ["c"]), node("b", ["a"]), node("c", ["b"])]}
        errs = dag_next.validate(dag)
        self.assertEqual(len(errs), 1)
        self.assertIn("cycle among: a, b, c", errs[0])

    def test_self_dependency(self):
        dag = {"nodes": [node("a", ["a"])]}
        self.assertTrue(any("depends on itself" in e for e in dag_next.validate(dag)))

    def test_bad_priority_and_status(self):
        n = node("a", priority=9)
        n["status"] = "someday"
        errs = dag_next.validate({"nodes": [n]})
        self.assertTrue(any("priority" in e for e in errs))
        self.assertTrue(any("status" in e for e in errs))

    def test_empty_graph_rejected(self):
        self.assertEqual(dag_next.validate({"nodes": []}), ["`nodes` must be a non-empty list"])


class ClassifyTests(unittest.TestCase):
    def test_frontier_is_derived_not_stored(self):
        # `b` is stored as "ready" but its dependency is open, so it is blocked.
        dag = {"nodes": [node("a", status="in_progress"), node("b", ["a"], status="ready")]}
        g = dag_next.classify(dag)
        self.assertEqual([n["id"] for n in g["ready"]], [])
        self.assertEqual([n["id"] for n in g["blocked"]], ["b"])
        self.assertEqual(g["blocked"][0]["open_deps"], ["a"])

    def test_frontier_sorted_by_priority_then_size(self):
        dag = {
            "nodes": [
                node("big", priority=1, size="L"),
                node("small", priority=1, size="S"),
                node("later", priority=2, size="S"),
            ]
        }
        g = dag_next.classify(dag)
        self.assertEqual([n["id"] for n in g["ready"]], ["small", "big", "later"])

    def test_parked_never_ready_and_blocks_dependents(self):
        dag = {"nodes": [node("p", status="parked"), node("q", ["p"])]}
        g = dag_next.classify(dag)
        self.assertEqual([n["id"] for n in g["parked"]], ["p"])
        self.assertEqual([n["id"] for n in g["blocked"]], ["q"])

    def test_done_deps_unblock(self):
        dag = {"nodes": [node("a", status="done"), node("b", ["a"], status="blocked")]}
        g = dag_next.classify(dag)
        self.assertEqual([n["id"] for n in g["ready"]], ["b"])


class CliTests(unittest.TestCase):
    def _write(self, dag):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(dag, tmp)
        tmp.close()
        return tmp.name

    def test_check_exit_codes(self):
        good = self._write({"nodes": [node("a", status="done"), node("b", ["a"])]})
        bad = self._write({"nodes": [node("a", ["b"]), node("b", ["a"])]})
        self.assertEqual(dag_next.main(["--check", "--dag", good]), 0)
        self.assertEqual(dag_next.main(["--check", "--dag", bad]), 1)

    def test_mermaid_mentions_every_edge(self):
        dag = {"nodes": [node("a", status="done"), node("b", ["a"])]}
        src = dag_next.render_mermaid(dag)
        self.assertIn("a --> b", src)
        self.assertIn("class a done;", src)
        self.assertIn("class b ready;", src)

    def test_repo_filter(self):
        dag = {"nodes": [node("a", repo="x"), node("b", repo="y")]}
        text = dag_next.render_text(dag_next.classify(dag), repo="y")
        self.assertIn("b ", text)
        self.assertNotIn(" a ", text)

    def test_real_dag_if_present(self):
        if dag_next.DEFAULT_DAG.exists():
            self.assertEqual(dag_next.validate(dag_next.load()), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
