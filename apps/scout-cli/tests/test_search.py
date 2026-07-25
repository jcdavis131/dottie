"""Search — openswap #20 (Elastic Cloud/Algolia -> stdlib sqlite3 FTS5 index).

Pure-logic core tests (discovery/globs, the incremental mtime-vs-hash reindex,
BM25 ranking, snippet highlighting, path filters, pagination, the staleness
audit), the honest FTS5-unavailable path, the default-deny manifest, and the
subprocess CLI envelope. Offline and deterministic by construction: `now` is
explicit, every corpus is built under tmp_path with byte-stable content and
explicitly set mtimes, and this adapter has no network surface at all — so the
CLI roundtrip runs fully offline with nothing to stub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from bigbang.core import openswap, search

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "bigbang" / "plugins" / "search"


def _write(path: Path, text: str, *, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _mem():
    return search.open_index(":memory:")


def _names(result: dict) -> list[str]:
    """Hit paths reduced to file names, in ranked order."""
    return [Path(h["path"]).name for h in result["hits"]]


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A small, rank-meaningful corpus: 4 docs mention 'ranking', 6 do not."""
    root = tmp_path / "corpus"
    _write(root / "dense.md", "ranking ranking ranking\n", mtime=1000.0)
    _write(root / "sparse.md", "ranking " + ("filler word here " * 60) + "\n", mtime=1000.0)
    _write(root / "sub" / "nested.md", "nested notes about tokenizers\n", mtime=1000.0)
    _write(root / "noise.md", "nothing relevant at all\n", mtime=1000.0)
    _write(root / "notes.rst", "restructured text mentions ranking too\n", mtime=1000.0)
    _write(root / ".git" / "hidden.md", "ranking inside a pruned vcs dir\n", mtime=1000.0)
    return root


# ---- capability probe: FTS5 is verified, never assumed -----------------------


def test_fts5_probe_is_end_to_end_on_this_build():
    report = search.fts5_probe()
    assert report["available"] is True, report
    assert report["error"] is None
    assert report["tokenizer"] == search.TOKENIZER
    assert report["sqlite_version"]
    assert search.fts5_available() == (True, "ok")


def test_broken_fts5_support_fails_honestly_and_writes_nothing(monkeypatch, tmp_path):
    # A real negative probe, no stubbing: ask sqlite for a tokenizer it does not
    # have. This is exactly what an older/FTS5-less build looks like from here.
    monkeypatch.setattr(search, "TOKENIZER", "no_such_tokenizer")
    report = search.fts5_probe()
    assert report["available"] is False
    assert report["error"] and "no_such_tokenizer" in report["error"]
    available, reason = search.fts5_available()
    assert available is False and reason == report["error"]
    db = tmp_path / "nested" / "index.db"
    with pytest.raises(search.Fts5UnavailableError) as exc:
        search.open_index(db)
    assert "no_such_tokenizer" in str(exc.value)
    assert not db.exists(), "a failed probe must not leave a half-built index"


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.search import cli as search_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = search_cli._capability()
    assert cap["adapter"] == "search"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "recollindex"
    assert cap["extras"]["ecctl"]["found"] is False  # SaaS client, never executed
    assert cap["fts5"]["available"] is True


def test_manifest_is_default_deny_on_the_network_axis():
    manifest = yaml.safe_load((PLUGIN_DIR / "manifest.yaml").read_text())
    assert manifest["name"] == "search"
    assert "openswap #20" in manifest["description"]
    assert manifest["capabilities"]["network"]["enabled"] is False
    assert manifest["capabilities"]["network"]["domains"] == []
    assert manifest["capabilities"]["secrets"]["allow"] == []
    fs = manifest["capabilities"]["filesystem"]
    assert fs["write"] is True and fs["paths"] == [".scout"]


# ---- discovery: globs, pruning, dedupe --------------------------------------


def test_glob_match_semantics_are_case_insensitive_and_path_aware():
    assert search.glob_match(["*.md"], "docs/READY.MD") is True  # case-folded
    assert search.glob_match(["*.md"], "docs/a.txt") is False
    # a pattern with "/" is matched against the whole path, not the file name
    assert search.glob_match(["docs/*.md"], "docs/a.md") is True
    assert search.glob_match(["docs/*.md"], "src/a.md") is False
    assert search.glob_match(["a.md"], "docs/a.md") is True  # bare name anywhere


def test_norm_path_is_posix_and_stable():
    assert search.norm_path(Path("a") / "b" / "c.md") == "a/b/c.md"
    assert search.norm_path("./a/b.md") == "a/b.md"


def test_iter_files_prunes_vendor_dirs_and_honors_globs(corpus):
    found = [p for p, _real in search.iter_files([corpus], include=["*.md"])]
    # sorted by stored path, so the nested file lands after the top-level ones
    assert [Path(p).name for p in found] == [
        "dense.md",
        "noise.md",
        "sparse.md",
        "nested.md",
    ]
    assert not any("/.git/" in p for p in found), ".git must be pruned by default"
    assert not any(p.endswith(".rst") for p in found), "include glob must filter"
    assert found == sorted(found), "discovery order must be deterministic"
    # excludes win over includes
    kept = [p for p, _ in search.iter_files([corpus], include=["*.md"], exclude=["dense.md"])]
    assert not any(p.endswith("dense.md") for p in kept)
    assert len(kept) == len(found) - 1
    # opting .git back in proves the prune list is the only thing hiding it
    with_git = [p for p, _ in search.iter_files([corpus], include=["*.md"], exclude_dirs=[])]
    assert any("/.git/" in p for p in with_git)


def test_iter_files_takes_file_roots_and_dedupes(corpus):
    one = search.iter_files([corpus / "dense.md"])
    assert [Path(p).name for p, _ in one] == ["dense.md"]
    # the same file reachable via a dir root and a file root appears once
    both = search.iter_files([corpus, corpus / "dense.md"], include=["*.md"])
    assert len([p for p, _ in both if p.endswith("dense.md")]) == 1


def test_read_document_skip_reasons_are_explicit(tmp_path):
    small = _write(tmp_path / "a.md", "hello\n")
    text, skip, meta = search.read_document(small)
    assert skip is None and text.strip() == "hello" and meta["size"] > 0
    big = _write(tmp_path / "big.md", "x" * 3000)
    assert search.read_document(big, max_kb=1)[1] == "too-large"
    binary = tmp_path / "b.md"
    binary.write_bytes(b"text\x00more")
    assert search.read_document(binary)[1] == "binary"
    assert search.read_document(tmp_path / "gone.md")[1] == "unreadable"


def test_read_document_strips_a_utf8_bom(tmp_path):
    # PowerShell writes a BOM by default on this box; left in, it glues itself to
    # the first token and shows up in every snippet of that file.
    bom = tmp_path / "bom.md"
    bom.write_bytes(b"\xef\xbb\xbfBM25 ranking")
    text, skip, _meta = search.read_document(bom)
    assert skip is None and text.startswith("BM25")


# ---- indexing + incremental reindex -----------------------------------------


def test_index_adds_documents_and_reports_the_corpus(corpus):
    conn = _mem()
    res = search.index_paths(conn, [corpus], include=["*.md"], now=2000.0)
    assert res["added"] == 4 and res["updated"] == 0 and res["removed"] == 0
    assert res["documents"] == 4
    assert res["mode"] == "mtime" and res["missing_roots"] == []
    assert res["bytes_read"] > 0
    # the pruned .git doc and the excluded .rst never entered the index
    assert search.query(conn, "pruned")["total"] == 0
    assert search.query(conn, "restructured")["total"] == 0
    assert search.indexed_roots(conn) == [search.norm_path(corpus)]


def test_reindex_is_incremental_by_mtime(corpus):
    conn = _mem()
    first = search.index_paths(conn, [corpus], include=["*.md"], now=2000.0)
    again = search.index_paths(conn, [corpus], include=["*.md"], now=2100.0)
    assert again["added"] == 0 and again["updated"] == 0
    assert again["unchanged"] == first["added"] == 4
    assert again["bytes_read"] == 0, "unchanged files must not be re-read"
    # a real edit (content + mtime move) is picked up, old text stops matching
    _write(corpus / "dense.md", "rewritten about kittens\n", mtime=3000.0)
    third = search.index_paths(conn, [corpus], include=["*.md"], now=2200.0)
    assert third["updated"] == 1 and third["added"] == 0 and third["unchanged"] == 3
    assert search.query(conn, "kittens")["total"] == 1
    assert _names(search.query(conn, "ranking")) == ["sparse.md"]
    # --force reindexes everything regardless
    forced = search.index_paths(conn, [corpus], include=["*.md"], force=True, now=2300.0)
    assert forced["updated"] == 4 and forced["unchanged"] == 0


def test_mtime_mode_misses_a_mtime_preserving_edit_and_hash_mode_catches_it(tmp_path):
    """The two modes are genuinely different — neither pretends to be the other."""
    root = tmp_path / "c"
    target = _write(root / "a.md", "alpha alpha\n", mtime=1000.0)
    conn = _mem()
    assert search.index_paths(conn, [root], include=["*.md"], now=1.0)["added"] == 1
    # same byte length, same mtime: only the content changed
    _write(target, "gamma gamma\n", mtime=1000.0)
    assert target.stat().st_mtime == 1000.0
    mtime_pass = search.index_paths(conn, [root], include=["*.md"], now=2.0)
    assert mtime_pass["unchanged"] == 1 and mtime_pass["updated"] == 0
    assert search.query(conn, "gamma")["total"] == 0, "documented mtime-mode blind spot"
    hash_pass = search.index_paths(conn, [root], include=["*.md"], mode="hash", now=3.0)
    assert hash_pass["updated"] == 1 and hash_pass["unchanged"] == 0
    assert search.query(conn, "gamma")["total"] == 1
    assert search.query(conn, "alpha")["total"] == 0
    # hash mode on identical content is a no-op that refreshes the stat fields
    idle = search.index_paths(conn, [root], include=["*.md"], mode="hash", now=4.0)
    assert idle["unchanged"] == 1 and idle["updated"] == 0


def test_prune_drops_deleted_files_only_under_the_indexed_roots(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "one.md", "alpha in a\n", mtime=1000.0)
    _write(b / "two.md", "beta in b\n", mtime=1000.0)
    conn = _mem()
    assert search.index_paths(conn, [a, b], include=["*.md"], now=1.0)["added"] == 2
    (b / "two.md").unlink()
    scoped = search.index_paths(conn, [a], include=["*.md"], now=2.0)
    assert scoped["removed"] == 0, "indexing a/ must not prune b/'s rows"
    assert scoped["documents"] == 2
    pruned = search.index_paths(conn, [b], include=["*.md"], now=3.0)
    assert pruned["removed"] == 1 and pruned["removed_paths"] == [
        search.norm_path(b / "two.md")
    ]
    assert pruned["documents"] == 1
    assert search.query(conn, "beta")["total"] == 0


def test_no_prune_keeps_rows_for_deleted_files(tmp_path):
    root = tmp_path / "c"
    _write(root / "a.md", "alpha\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    (root / "a.md").unlink()
    kept = search.index_paths(conn, [root], include=["*.md"], prune=False, now=2.0)
    assert kept["removed"] == 0 and kept["documents"] == 1
    assert search.query(conn, "alpha")["total"] == 1  # still served, now stale
    report = search.stats(conn)
    assert report["missing_count"] == 1 and report["missing"] == [
        search.norm_path(root / "a.md")
    ]


def test_absent_root_is_reported_and_never_prunes_its_rows(tmp_path):
    root = tmp_path / "vanishing"
    _write(root / "a.md", "alpha\n", mtime=1000.0)
    _write(root / "b.md", "beta\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    shutil.rmtree(root)
    res = search.index_paths(conn, [root], include=["*.md"], now=2.0)
    assert res["missing_roots"] == [search.norm_path(root)]
    assert res["removed"] == 0 and res["documents"] == 2, (
        "an unmounted/renamed root is not evidence its files are gone"
    )


def test_skipped_files_are_reported_and_unindexable_rows_are_dropped(tmp_path):
    root = tmp_path / "c"
    _write(root / "big.md", "x" * 3000, mtime=1000.0)
    _write(root / "ok.md", "alpha\n", mtime=1000.0)
    conn = _mem()
    res = search.index_paths(conn, [root], include=["*.md"], max_kb=1, now=1.0)
    assert res["added"] == 1 and res["skipped"] == {"too-large": 1}
    assert res["skipped_files"] == [
        {"path": search.norm_path(root / "big.md"), "reason": "too-large"}
    ]
    # a file that WAS indexed and then became binary must stop serving hits
    (root / "ok.md").write_bytes(b"alpha\x00\x00binary now")
    os.utime(root / "ok.md", (2000.0, 2000.0))
    res2 = search.index_paths(conn, [root], include=["*.md"], max_kb=1, now=2.0)
    assert res2["skipped"]["binary"] == 1 and res2["removed"] == 1
    assert res2["documents"] == 0
    assert search.query(conn, "alpha")["total"] == 0


def test_index_paths_rejects_bad_arguments(tmp_path):
    conn = _mem()
    with pytest.raises(ValueError):
        search.index_paths(conn, [tmp_path], mode="magic")
    with pytest.raises(ValueError):
        search.index_paths(conn, [tmp_path], max_kb=0)


# ---- query: ranking, snippets, filters, pagination --------------------------


def test_bm25_ranks_a_dense_short_document_above_a_diluted_one(corpus):
    conn = _mem()
    search.index_paths(conn, [corpus], include=["*.md"], now=1.0)
    res = search.query(conn, "ranking")
    assert _names(res) == ["dense.md", "sparse.md"]
    assert res["total"] == 2 and res["returned"] == 2
    assert res["hits"][0]["rank"] == 1 and res["hits"][1]["rank"] == 2
    # score is -bm25 (bigger is better) and the raw engine number is kept
    assert res["hits"][0]["score"] > res["hits"][1]["score"]
    assert res["hits"][0]["bm25"] == pytest.approx(-res["hits"][0]["score"], abs=1e-8)


def test_column_weights_decide_path_matches_versus_body_matches(tmp_path):
    root = tmp_path / "c"
    _write(root / "tokenizer-guide.md", "scoring notes and other content\n", mtime=1000.0)
    _write(root / "body.md", "the tokenizer is described here in one place\n", mtime=1000.0)
    for i in range(4):  # distractors so the term is not in every document
        _write(root / f"noise{i}.md", "unrelated filler\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    heavy = search.query(conn, "tokenizer", path_weight=5.0, body_weight=1.0)
    assert _names(heavy) == ["tokenizer-guide.md", "body.md"]
    light = search.query(conn, "tokenizer", path_weight=0.0, body_weight=1.0)
    assert _names(light) == ["body.md", "tokenizer-guide.md"]
    assert light["weights"] == {"path": 0.0, "body": 1.0}


def test_snippet_highlights_matches_and_markers_are_configurable(tmp_path):
    root = tmp_path / "c"
    _write(
        root / "a.md",
        "intro words " * 20 + "the needle appears here " + "trailing words " * 20,
        mtime=1000.0,
    )
    _write(root / "b.md", "no needle at all here\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    def _long_hit(result: dict) -> dict:
        # the long document, whichever way BM25 ranked it (b.md is shorter and
        # therefore scores higher — that is BM25 doing its job, not a snippet fact)
        return next(h for h in result["hits"] if h["path"].endswith("a.md"))

    hit = _long_hit(search.query(conn, "needle", snippet_tokens=8))
    assert "[needle]" in hit["snippet"]
    assert len(hit["snippet"]) < hit["chars"], "a snippet is an excerpt, not the doc"
    assert search.ELLIPSIS.strip() in hit["snippet"], "elided text must be marked"
    custom = _long_hit(search.query(conn, "needle", mark=("<b>", "</b>"), ellipsis="~"))
    assert "<b>needle</b>" in custom["snippet"] and "[needle]" not in custom["snippet"]
    assert "~" in custom["snippet"] and search.ELLIPSIS.strip() not in custom["snippet"]


def test_fts5_syntax_is_available_and_literal_disarms_it(tmp_path):
    root = tmp_path / "c"
    _write(root / "phrase-a.md", "alpha beta gamma\n", mtime=1000.0)
    _write(root / "phrase-b.md", "beta alpha gamma\n", mtime=1000.0)
    _write(root / "ops.md", "alpha and beta together\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    assert _names(search.query(conn, '"alpha beta"')) == ["phrase-a.md"]  # phrase order
    assert search.query(conn, "alpha")["total"] == 3
    assert search.query(conn, "gam*")["total"] == 2  # prefix
    assert search.query(conn, "alpha NOT gamma")["total"] == 1
    # a malformed query is reported, never silently turned into zero hits
    with pytest.raises(ValueError) as exc:
        search.query(conn, "alpha AND")
    assert "fts5" in str(exc.value)
    # --literal turns operators back into ordinary words
    assert _names(search.query(conn, "alpha and beta", literal=True)) == ["ops.md"]
    assert search.query(conn, 'he said "hi"', literal=True)["total"] == 0  # no crash
    assert search.literal_match('a "b" c') == '"a ""b"" c"'


def test_tokenizer_folds_diacritics_both_ways(tmp_path):
    root = tmp_path / "c"
    _write(root / "accent.md", "le café est chaud\n", mtime=1000.0)
    _write(root / "plain.md", "unrelated filler here\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    assert search.query(conn, "cafe")["total"] == 1
    assert search.query(conn, "café")["total"] == 1


def test_path_filter_accepts_a_glob_or_a_wildcard_free_subtree(tmp_path):
    docs, src = tmp_path / "docs", tmp_path / "src"
    _write(docs / "note.md", "shared term here\n", mtime=1000.0)
    _write(docs / "deep" / "note.md", "shared term deeper\n", mtime=1000.0)
    _write(src / "note.md", "shared term in source\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [docs, src], include=["*.md"], now=1.0)
    assert search.query(conn, "shared")["total"] == 3
    subtree = search.query(conn, "shared", path_glob=str(docs))
    assert subtree["total"] == 2 and subtree["returned"] == 2
    assert all("/docs/" in h["path"] for h in subtree["hits"])
    assert subtree["path_filter"]["exact"] == search.norm_path(docs).lower()
    globbed = search.query(conn, "shared", path_glob="*/src/*.md")
    assert globbed["total"] == 1 and globbed["path_filter"]["exact"] is None
    # a wildcard-free root FILE path matches exactly that file
    exact = search.query(conn, "shared", path_glob=str(src / "note.md"))
    assert exact["total"] == 1


def test_pagination_pages_a_stable_total(corpus):
    conn = _mem()
    search.index_paths(conn, [corpus], include=["*.md"], now=1.0)
    page1 = search.query(conn, "ranking", limit=1)
    page2 = search.query(conn, "ranking", limit=1, offset=1)
    assert page1["total"] == page2["total"] == 2
    assert _names(page1) == ["dense.md"] and _names(page2) == ["sparse.md"]
    assert page1["hits"][0]["rank"] == 1 and page2["hits"][0]["rank"] == 2
    assert search.query(conn, "ranking", limit=1, offset=99)["hits"] == []


def test_query_rejects_bad_arguments(corpus):
    conn = _mem()
    search.index_paths(conn, [corpus], include=["*.md"], now=1.0)
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            search.query(conn, bad)
    with pytest.raises(ValueError):
        search.query(conn, "ranking", limit=0)
    with pytest.raises(ValueError):
        search.query(conn, "ranking", offset=-1)
    with pytest.raises(ValueError):
        search.query(conn, "ranking", snippet_tokens=0)


# ---- stats + the family diagnostic schema -----------------------------------


def test_stats_rolls_up_the_corpus_and_audits_freshness(corpus):
    conn = _mem()
    search.index_paths(conn, [corpus], include=["*.md"], now=1234.0)
    fresh = search.stats(conn)
    assert fresh["documents"] == 4 and fresh["bytes"] > 0 and fresh["chars"] > 0
    assert fresh["by_extension"] == {".md": 4}
    assert fresh["roots"] == [search.norm_path(corpus)]
    assert fresh["tokenizer"] == search.TOKENIZER
    assert fresh["last_indexed_ts"] == 1234.0
    assert fresh["oldest_mtime"] == fresh["newest_mtime"] == 1000.0
    assert fresh["missing_count"] == 0 and fresh["stale_count"] == 0
    # drift: one file edited, one deleted — both visible without reading bodies
    _write(corpus / "dense.md", "edited after indexing\n", mtime=9000.0)
    (corpus / "noise.md").unlink()
    audited = search.stats(conn)
    assert audited["stale_count"] == 1 and audited["missing_count"] == 1
    assert audited["stale"][0]["path"] == search.norm_path(corpus / "dense.md")
    assert audited["stale"][0]["mtime"] == 9000.0
    assert audited["stale"][0]["indexed_mtime"] == 1000.0
    assert audited["missing"] == [search.norm_path(corpus / "noise.md")]
    # --no-check skips the audit entirely (and says so)
    quiet = search.stats(conn, check=False)
    assert quiet["checked"] is False and quiet["stale"] == [] and quiet["stale_count"] == 0
    assert quiet["documents"] == 4


def test_stats_caps_its_lists_but_not_its_counts(tmp_path):
    root = tmp_path / "c"
    for i in range(5):
        _write(root / f"f{i}.md", f"doc {i}\n", mtime=1000.0)
    conn = _mem()
    search.index_paths(conn, [root], include=["*.md"], now=1.0)
    shutil.rmtree(root)
    report = search.stats(conn, limit=2)
    assert report["missing_count"] == 5 and len(report["missing"]) == 2


def test_to_diagnostics_maps_the_family_schema(tmp_path):
    report = {
        "missing": ["docs/gone.md"],
        "stale": [{"path": "docs/edited.md"}],
        "skipped_files": [
            {"path": "docs/huge.md", "reason": "too-large"},
            {"path": "docs/blob.md", "reason": "binary"},
            {"path": "docs/locked.md", "reason": "unreadable"},
        ],
    }
    diags = search.to_diagnostics(report)
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["search:missing"]["severity"] == "warning"
    assert by_rule["search:stale"]["severity"] == "warning"
    assert by_rule["search:skipped:unreadable"]["severity"] == "warning"
    assert by_rule["search:skipped:too-large"]["severity"] == "info"
    assert by_rule["search:skipped:binary"]["severity"] == "info"
    assert all(d["source"] == "search" for d in diags)
    summary = openswap.summarize(diags)
    assert summary["total"] == 5
    assert summary["by_severity"]["warning"] == 3 and summary["by_severity"]["info"] == 2
    assert search.to_diagnostics({}) == []  # a clean report emits nothing


# ---- the real CLI in a subprocess (fully offline — no network surface) -------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(cwd or ROOT),
    )


def test_cli_search_hello_envelope():
    r = _cli(["search", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_search_detect_reports_the_fts5_probe():
    r = _cli(["search", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["adapter"] == "search"
    assert data["fts5"]["available"] is True
    assert data["fts5"]["tokenizer"] == search.TOKENIZER


def test_cli_index_query_stats_roundtrip(tmp_path, corpus):
    db = str(tmp_path / "search.db")
    # --ext, not --glob: click expands a bare *.md against the CWD on Windows
    r = _cli(["search", "index", str(corpus), "--ext", "md", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["include"] == ["*.md"] and data["added"] == 4 and data["documents"] == 4
    assert data["skipped"] == {} and data["diagnostics"] == []

    r = _cli(["search", "query", "ranking", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    hits = json.loads(r.stdout)["data"]
    assert hits["total"] == 2
    assert [Path(h["path"]).name for h in hits["hits"]] == ["dense.md", "sparse.md"]
    assert "[ranking]" in hits["hits"][0]["snippet"]

    # the second pass is incremental, not a rebuild
    r = _cli(["search", "index", str(corpus), "--ext", "md", "--db", db])
    again = json.loads(r.stdout)["data"]
    assert again["added"] == 0 and again["unchanged"] == 4

    r = _cli(["search", "stats", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    stats = json.loads(r.stdout)["data"]
    assert stats["documents"] == 4 and stats["by_extension"] == {".md": 4}
    assert stats["missing_count"] == 0 and stats["stale_count"] == 0


def test_cli_query_fail_empty_is_the_ci_assertion_hook(tmp_path, corpus):
    db = str(tmp_path / "search.db")
    assert _cli(["search", "index", str(corpus), "--ext", "md", "--db", db]).returncode == 0
    hit = _cli(["search", "query", "ranking", "--db", db, "--fail-empty"])
    assert hit.returncode == 0
    miss = _cli(["search", "query", "nonexistentterm", "--db", db, "--fail-empty"])
    assert miss.returncode == 1
    assert json.loads(miss.stdout)["data"]["total"] == 0


def test_cli_stats_fail_on_gates_a_stale_index(tmp_path, corpus):
    db = str(tmp_path / "search.db")
    assert _cli(["search", "index", str(corpus), "--ext", "md", "--db", db]).returncode == 0
    assert _cli(["search", "stats", "--db", db, "--fail-on", "warning"]).returncode == 0
    (corpus / "dense.md").unlink()
    gated = _cli(["search", "stats", "--db", db, "--fail-on", "warning"])
    assert gated.returncode == 1
    data = json.loads(gated.stdout)["data"]
    assert data["missing_count"] == 1
    assert data["summary"]["by_rule"]["search:missing"] == 1


def test_cli_index_fail_on_gates_skipped_files(tmp_path):
    root = tmp_path / "c"
    _write(root / "ok.md", "alpha\n")
    (root / "blob.md").write_bytes(b"alpha\x00binary")
    db = str(tmp_path / "search.db")
    r = _cli(["search", "index", str(root), "--ext", "md", "--db", db])
    assert r.returncode == 0
    data = json.loads(r.stdout)["data"]
    assert data["added"] == 1 and data["skipped"] == {"binary": 1}
    gated = _cli(["search", "index", str(root), "--ext", "md", "--db", db, "--fail-on", "info"])
    assert gated.returncode == 1
    assert json.loads(gated.stdout)["data"]["summary"]["by_severity"]["info"] == 1


def test_cli_query_without_an_index_fails_actionably(tmp_path):
    r = _cli(["search", "query", "anything", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no search index" in data["error"] and "example" in data


def test_cli_bad_query_syntax_fails_actionably_and_literal_recovers(tmp_path, corpus):
    db = str(tmp_path / "search.db")
    assert _cli(["search", "index", str(corpus), "--ext", "md", "--db", db]).returncode == 0
    bad = _cli(["search", "query", "ranking AND", "--db", db])
    assert bad.returncode == 1
    assert "fts5" in json.loads(bad.stdout)["error"]
    good = _cli(["search", "query", "ranking AND", "--db", db, "--literal"])
    assert good.returncode == 0
    assert json.loads(good.stdout)["data"]["match"] == '"ranking AND"'


def test_cli_index_refuses_a_root_that_does_not_exist(tmp_path):
    r = _cli(["search", "index", str(tmp_path / "nope"), "--db", str(tmp_path / "s.db")])
    assert r.returncode == 1
    assert "none of these roots exist" in json.loads(r.stdout)["error"]
    assert not (tmp_path / "s.db").exists(), "a refused index must write nothing"


def test_cli_bad_mode_and_bad_fail_on_are_rejected(tmp_path, corpus):
    db = str(tmp_path / "search.db")
    bad_mode = _cli(["search", "index", str(corpus), "--db", db, "--mode", "magic"])
    assert bad_mode.returncode == 1 and "--mode" in json.loads(bad_mode.stdout)["error"]
    bad_gate = _cli(["search", "index", str(corpus), "--db", db, "--fail-on", "loud"])
    assert bad_gate.returncode == 1 and "--fail-on" in json.loads(bad_gate.stdout)["error"]
