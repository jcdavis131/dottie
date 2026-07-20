# Solo personal project, no connection to employer, built with public/free-tier only
"""Incremental build (--update): content-hash cache reuses unchanged files."""
import argparse
import json
import os

from personal_graphify.cli import cmd_build
from personal_graphify.extract import extract_with_cache


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "alpha.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (repo / "beta.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    (repo / "notes.md").write_text("# Notes\nSee [alpha](alpha.py).\n", encoding="utf-8")
    return repo


def _build_args(repo, out, update=False):
    return argparse.Namespace(path=str(repo), roots=[], out=str(out), max_files=100,
                              cluster="auto", update=update)


class TestExtractWithCache:
    def test_first_run_extracts_everything_and_writes_cache(self, tmp_path):
        repo = _repo(tmp_path)
        cache = tmp_path / "out" / "cache" / "extract.json"
        files = sorted(repo.iterdir())
        nodes, edges, stats = extract_with_cache(files, cache, update=False)
        assert stats["re_extracted"] == 3 and stats["reused"] == 0
        assert cache.exists()
        meta = json.loads(cache.read_text(encoding="utf-8"))
        assert set(meta) == {str(f) for f in files}
        for entry in meta.values():
            assert {"mtime", "md5", "nodes", "edges"} <= set(entry)

    def test_update_reuses_unchanged_reextracts_changed(self, tmp_path):
        repo = _repo(tmp_path)
        cache = tmp_path / "out" / "cache" / "extract.json"
        files = sorted(repo.iterdir())
        n1, e1, _ = extract_with_cache(files, cache, update=False)

        # change one file's content
        (repo / "beta.py").write_text("def beta():\n    return 3\n\ndef gamma():\n    return 4\n",
                                      encoding="utf-8")
        n2, e2, stats = extract_with_cache(files, cache, update=True)
        assert stats["re_extracted"] == 1
        assert stats["reused"] == 2
        # graph pool is rebuilt from the merge: new gamma symbol shows up
        assert any(n["label"] == "gamma" for n in n2)

    def test_touch_without_content_change_is_reused_via_md5(self, tmp_path):
        repo = _repo(tmp_path)
        cache = tmp_path / "out" / "cache" / "extract.json"
        files = sorted(repo.iterdir())
        extract_with_cache(files, cache, update=False)
        # bump mtime only
        target = repo / "alpha.py"
        st = target.stat()
        os.utime(target, (st.st_atime + 100, st.st_mtime + 100))
        _, _, stats = extract_with_cache(files, cache, update=True)
        assert stats["reused"] == 3 and stats["re_extracted"] == 0

    def test_without_update_flag_cache_is_ignored(self, tmp_path):
        repo = _repo(tmp_path)
        cache = tmp_path / "out" / "cache" / "extract.json"
        files = sorted(repo.iterdir())
        extract_with_cache(files, cache, update=False)
        _, _, stats = extract_with_cache(files, cache, update=False)
        assert stats["re_extracted"] == 3 and stats["reused"] == 0


class TestCmdBuildUpdate:
    def test_full_then_incremental_build(self, tmp_path):
        repo = _repo(tmp_path)
        out = repo / "graphify-out"
        stats1 = cmd_build(_build_args(repo, out, update=False))
        assert stats1["cache"]["re_extracted"] >= 3
        assert (out / "cache" / "extract.json").exists()
        assert (out / "graph.json").exists()

        # modify exactly one file, then --update
        (repo / "alpha.py").write_text("def alpha():\n    return 42\n", encoding="utf-8")
        stats2 = cmd_build(_build_args(repo, out, update=True))
        assert stats2["cache"]["re_extracted"] == 1
        assert stats2["cache"]["reused"] == stats1["cache"]["files"] - 1
        # graph.json still rebuilt from the merged pool
        meta = json.loads((out / "graph.json").read_text(encoding="utf-8"))["meta"]
        assert meta["nodes"] == stats2["nodes"]
