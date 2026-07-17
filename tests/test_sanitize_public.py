# Solo personal project, no connection to employer, built with public/free-tier only
"""sanitize_for_public.py — PII gate must hard-fail on leaks and pass on clean graphs."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sanitize_for_public.py"
spec = importlib.util.spec_from_file_location("sanitize_for_public", _SCRIPT)
sanitize = importlib.util.module_from_spec(spec)
sys.modules["sanitize_for_public"] = sanitize
spec.loader.exec_module(sanitize)


def _write_graph(tmp_path, nodes, edges=None):
    src = tmp_path / "graph.json"
    src.write_text(json.dumps({"nodes": nodes, "edges": edges or []}), encoding="utf-8")
    return src


class TestPiiGate:
    def test_gate_fails_on_account_digits_in_file_path(self, tmp_path):
        # acct digits survive path sanitization → the final gate must hard-fail
        src = _write_graph(tmp_path, [
            {"id": "file:notes/0472-plan.md", "label": "0472-plan.md", "type": "file",
             "file": "notes/0472-plan.md", "degree": 1},
        ])
        with pytest.raises(SystemExit, match="PII gate failed"):
            sanitize.main(src, tmp_path / "out.json")

    def test_email_nodes_are_dropped_and_gate_passes(self, tmp_path):
        src = _write_graph(tmp_path, [
            {"id": "concept:owner", "label": "contact jcdavis131@gmail.com", "type": "concept", "degree": 1},
            {"id": "concept:Turnover Shield", "label": "Turnover Shield", "type": "product", "degree": 2},
        ])
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        out = json.loads(dest.read_text(encoding="utf-8"))
        labels = {n["label"] for n in out["nodes"]}
        assert "Turnover Shield" in labels
        assert not any("jcdavis131" in l for l in labels)

    def test_home_paths_scrubbed(self, tmp_path):
        src = _write_graph(tmp_path, [
            {"id": "file:/home/hatch/workspace/your_files/personal-graphify/src/cli.py",
             "label": "cli.py", "type": "file",
             "file": "/home/hatch/workspace/your_files/personal-graphify/src/cli.py", "degree": 1},
        ])
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        blob = dest.read_text(encoding="utf-8")
        assert "/home/hatch" not in blob

    def test_junk_nodes_filtered(self, tmp_path):
        src = _write_graph(tmp_path, [
            {"id": "file:pkg.egg-info/PKG-INFO", "label": "PKG-INFO", "type": "file", "degree": 0},
            {"id": "concept:Keep Me", "label": "Keep Me", "type": "concept", "degree": 1},
        ])
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        out = json.loads(dest.read_text(encoding="utf-8"))
        assert {n["label"] for n in out["nodes"]} == {"Keep Me"}
