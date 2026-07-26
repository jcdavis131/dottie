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

_LIGHTEN = (
    Path(__file__).resolve().parent.parent / "scripts" / "lighten_public_graph.py"
)
_lspec = importlib.util.spec_from_file_location("lighten_public_graph", _LIGHTEN)
lighten = importlib.util.module_from_spec(_lspec)
sys.modules["lighten_public_graph"] = lighten
_lspec.loader.exec_module(lighten)


def _write_graph(tmp_path, nodes, edges=None):
    src = tmp_path / "graph.json"
    src.write_text(json.dumps({"nodes": nodes, "edges": edges or []}), encoding="utf-8")
    return src


class TestPiiGate:
    def test_gate_fails_on_account_digits_in_file_path(self, tmp_path):
        # acct digits survive path sanitization → the final gate must hard-fail
        src = _write_graph(
            tmp_path,
            [
                {
                    "id": "file:notes/0472-plan.md",
                    "label": "0472-plan.md",
                    "type": "file",
                    "file": "notes/0472-plan.md",
                    "degree": 1,
                },
            ],
        )
        with pytest.raises(SystemExit, match="PII gate failed"):
            sanitize.main(src, tmp_path / "out.json")

    def test_email_nodes_are_dropped_and_gate_passes(self, tmp_path):
        src = _write_graph(
            tmp_path,
            [
                {
                    "id": "concept:owner",
                    "label": "contact jcdavis131@gmail.com",
                    "type": "concept",
                    "degree": 1,
                },
                {
                    "id": "concept:Turnover Shield",
                    "label": "Turnover Shield",
                    "type": "product",
                    "degree": 2,
                },
            ],
        )
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        out = json.loads(dest.read_text(encoding="utf-8"))
        labels = {n["label"] for n in out["nodes"]}
        assert "Turnover Shield" in labels
        assert not any("jcdavis131" in l for l in labels)

    def test_home_paths_scrubbed(self, tmp_path):
        src = _write_graph(
            tmp_path,
            [
                {
                    "id": "file:/home/hatch/workspace/your_files/personal-graphify/src/cli.py",
                    "label": "cli.py",
                    "type": "file",
                    "file": "/home/hatch/workspace/your_files/personal-graphify/src/cli.py",
                    "degree": 1,
                },
            ],
        )
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        blob = dest.read_text(encoding="utf-8")
        assert "/home/hatch" not in blob

    def test_dottie_layout_paths_redacted(self, tmp_path):
        # Exports built from a dottie checkout must redact apps/* + packages/*
        # fragments to the same project aliases as the standalone layout.
        src = _write_graph(
            tmp_path,
            [
                {
                    "id": "file:/home/user/dottie/packages/personal-graphify/src/cli.py",
                    "label": "cli.py",
                    "type": "file",
                    "file": "/home/user/dottie/packages/personal-graphify/src/cli.py",
                    "degree": 1,
                },
                {
                    "id": "file:C:/Users/jcdav/dottie/apps/scout-cli/scout/main.py",
                    "label": "main.py",
                    "type": "file",
                    "file": "C:/Users/jcdav/dottie/apps/scout-cli/scout/main.py",
                    "degree": 1,
                },
                {
                    "id": "file:/srv/ci/dottie/packages/ava-skills/skills/mint.md",
                    "label": "mint.md",
                    "type": "file",
                    "file": "/srv/ci/dottie/packages/ava-skills/skills/mint.md",
                    "degree": 1,
                },
            ],
        )
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        blob = dest.read_text(encoding="utf-8")
        assert "dottie" not in blob
        assert "/home/user" not in blob and "/srv/ci" not in blob
        assert "apps/" not in blob and "packages/" not in blob
        files = {n["file"] for n in json.loads(blob)["nodes"]}
        assert files == {
            "personal-graphify/src/cli.py",
            "scout-cli/scout/main.py",
            "ava-skills/skills/mint.md",
        }

    def test_junk_nodes_filtered(self, tmp_path):
        src = _write_graph(
            tmp_path,
            [
                {
                    "id": "file:pkg.egg-info/PKG-INFO",
                    "label": "PKG-INFO",
                    "type": "file",
                    "degree": 0,
                },
                {
                    "id": "concept:Keep Me",
                    "label": "Keep Me",
                    "type": "concept",
                    "degree": 1,
                },
            ],
        )
        dest = tmp_path / "out.json"
        sanitize.main(src, dest)
        out = json.loads(dest.read_text(encoding="utf-8"))
        assert {n["label"] for n in out["nodes"]} == {"Keep Me"}


class TestLightenDottieFragments:
    def test_strip_paths_removes_dottie_layout_fragments(self):
        # dottie apps/* + packages/* ids must not leak project names into seed blobs
        for frag in (
            "apps/scout-cli/scout/main.py",
            "apps/scout-rtx/rtx/offload.py",
            "apps/ava-factory/factory/run.py",
            "packages/personal-graphify/src/cli.py",
            "packages/ava-skills/skills/mint.md",
            "packages/ava-open-harness/harness/loop.py",
        ):
            stripped = lighten._strip_paths(f"see {frag} for details")
            assert frag.split("/")[1] not in stripped, frag
            assert "apps/" not in stripped and "packages/" not in stripped

    def test_sanitize_id_strips_all_indexed_doc_extensions(self):
        # detect.py DOC_EXTS indexes rst/qmd/yaml/yml too; their concept ids must strip
        # the path suffix exactly like .md/.txt, or the internal repo path leaks into the
        # "public" graph and the title never dedupes against the same heading in a .md file.
        base = r"concept:Overview:C:\Users\jcdav\dottie\notes\guide"
        for ext in (".md", ".txt", ".rst", ".qmd", ".yaml", ".yml", ".mdx", ".mdc"):
            assert sanitize.sanitize_id(base + ext) == "concept:Overview", ext

    def test_sanitize_id_keeps_dotted_title_segment(self):
        # regression guard for the fix above: a legitimate title segment ending in a
        # dotted suffix ("Node.js") must NOT be mistaken for a file path. A generic
        # `\.\w+$` extension match would wrongly truncate it to "concept:Overview".
        assert (
            sanitize.sanitize_id(r"concept:Overview:Node.js:C:\Users\jcdav\dottie\x.md")
            == "concept:Overview:Node.js"
        )
