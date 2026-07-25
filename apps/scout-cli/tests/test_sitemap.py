"""Sitemap — openswap rank 10 (XML-Sitemaps.com Pro -> stdlib xml.etree writer
over a sorted public/ walk, a URL list, or the #3 seo crawl store).

Pure-logic core tests + real filesystem trees under tmp_path + capability
detection + the subprocess envelope. Offline and deterministic by construction:
this adapter has NO network surface at all (the manifest disables the axis), the
only inputs are files this test writes, and every mtime the assertions depend on
is pinned with os.utime, so `date`/`second` lastmods are exact rather than
"today". The one seo-store test drives the real crawl with an injected fetch
(the established offline pattern), never a socket.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bigbang.core import openswap, seo, sitemap

ROOT = Path(__file__).resolve().parents[1]

# 2026-03-04T05:06:07Z and 2025-11-30T00:00:00Z — pinned so lastmod is exact
MT_A = 1772600767.0
MT_B = 1764460800.0


def _tree(tmp_path: Path) -> Path:
    """A realistic built-site tree: nested pages, an asset, a draft, a dotdir."""
    root = tmp_path / "public"
    files = {
        "index.html": "<html>home</html>",
        "about.html": "<html>about</html>",
        "404.html": "<html>nope</html>",
        "blog/index.html": "<html>blog</html>",
        "blog/first post.html": "<html>post</html>",  # space -> must be encoded
        "blog/nested/deep.htm": "<html>deep</html>",
        "assets/app.css": "body{}",
        "drafts/secret.html": "<html>draft</html>",
        ".vercel/output/config.html": "{}",
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        os.utime(p, (MT_A, MT_A))
    os.utime(root / "about.html", (MT_B, MT_B))
    return root


# ---- base URL + loc construction -------------------------------------------


def test_normalize_base_canonicalizes_and_rejects_junk():
    assert sitemap.normalize_base("https://x.com") == "https://x.com/"
    assert sitemap.normalize_base("https://x.com/docs") == "https://x.com/docs/"
    assert sitemap.normalize_base("https://x.com/docs/") == "https://x.com/docs/"
    # query/fragment on a base URL would corrupt every loc -> dropped
    assert sitemap.normalize_base("https://x.com/?a=1#f") == "https://x.com/"
    assert sitemap.normalize_base("http://localhost:8000") == "http://localhost:8000/"
    for bad in ("x.com", "ftp://x.com", "https://", "", None):
        with pytest.raises(ValueError):
            sitemap.normalize_base(bad)


def test_url_for_index_stripping_clean_urls_and_encoding():
    base = "https://x.com/"
    assert sitemap.url_for("index.html", base) == "https://x.com/"
    assert sitemap.url_for("blog/index.html", base) == "https://x.com/blog/"
    assert sitemap.url_for("about.html", base) == "https://x.com/about.html"
    assert sitemap.url_for("about.html", base, clean_urls=True) == "https://x.com/about"
    # index files are directory URLs even in clean-url mode (not "/blog/index")
    assert sitemap.url_for("blog/index.html", base, clean_urls=True) == (
        "https://x.com/blog/"
    )
    assert sitemap.url_for("index.html", base, strip_index=False) == (
        "https://x.com/index.html"
    )
    # Windows separators and spaces/unicode are normalized + percent-encoded
    assert sitemap.url_for("blog\\a b.html", base) == "https://x.com/blog/a%20b.html"
    assert sitemap.url_for("café.html", base) == "https://x.com/caf%C3%A9.html"
    # a path prefix in the base survives
    assert sitemap.url_for("a.html", "https://x.com/docs/") == "https://x.com/docs/a.html"


def test_format_lastmod_is_utc_and_two_precisions():
    assert sitemap.format_lastmod(MT_A) == "2026-03-04"
    assert sitemap.format_lastmod(MT_A, "second") == "2026-03-04T05:06:07+00:00"
    assert sitemap.format_lastmod(MT_B, "second") == "2025-11-30T00:00:00+00:00"
    with pytest.raises(ValueError):
        sitemap.format_lastmod(MT_A, "minute")


def test_entry_validation_and_priority_formatting():
    e = sitemap.make_entry("https://x.com/a", changefreq="daily", priority=0.8)
    assert e["priority"] == "0.8" and e["changefreq"] == "daily"
    assert sitemap.make_entry("https://x.com/a", priority=1)["priority"] == "1.0"
    assert sitemap.make_entry("https://x.com/a", priority=0.85)["priority"] == "0.85"
    with pytest.raises(ValueError):
        sitemap.make_entry("/relative")  # loc must be absolute
    with pytest.raises(ValueError):
        sitemap.make_entry("")
    with pytest.raises(ValueError):
        sitemap.make_entry("https://x.com/a", changefreq="fortnightly")
    for bad in (1.5, -0.1, "high"):
        with pytest.raises(ValueError):
            sitemap.make_entry("https://x.com/a", priority=bad)


# ---- exclusion --------------------------------------------------------------


def test_match_exclude_path_basename_and_ancestors():
    pats = ["drafts/*", "*.tmp.html", "private"]
    assert sitemap.match_exclude("drafts/x.html", pats) == "drafts/*"
    assert sitemap.match_exclude("a/b.tmp.html", pats) == "*.tmp.html"
    assert sitemap.match_exclude("private/deep/x.html", pats) == "private"
    assert sitemap.match_exclude("blog/post.html", pats) is None
    # a trailing slash means "the subtree"
    assert sitemap.match_exclude("old/x.html", ["old/"]) == "old/"


def test_match_exclude_is_case_sensitive_on_every_os():
    # fnmatchcase, not fnmatch: on Windows fnmatch would normcase the path and
    # silently match here, making --exclude behave differently than on Linux.
    assert sitemap.match_exclude("Drafts/x.html", ["drafts/*"]) is None
    assert sitemap.match_exclude("drafts/x.html", ["drafts/*"]) == "drafts/*"


# ---- source 1: the walk -----------------------------------------------------


def test_walk_entries_sorted_filtered_and_dated(tmp_path):
    root = _tree(tmp_path)
    res = sitemap.walk_entries(root, "https://x.com", excludes=["drafts/*", "404.html"])
    locs = [e["loc"] for e in res["entries"]]
    assert locs == [
        "https://x.com/",
        "https://x.com/about.html",
        "https://x.com/blog/",
        "https://x.com/blog/first%20post.html",
        "https://x.com/blog/nested/deep.htm",
    ]
    assert locs == sorted(locs)  # the diffability contract
    by_loc = {e["loc"]: e for e in res["entries"]}
    assert by_loc["https://x.com/"]["lastmod"] == "2026-03-04"
    assert by_loc["https://x.com/about.html"]["lastmod"] == "2025-11-30"  # own mtime
    assert by_loc["https://x.com/"]["source"] == "index.html"
    reasons = {s["path"]: s["reason"] for s in res["skipped"]}
    assert reasons["assets/app.css"] == "extension"
    assert reasons["drafts/"] == "excluded:drafts/*"
    assert reasons["404.html"] == "excluded:404.html"
    assert reasons[".vercel/"] == "excluded:.*"  # dot-paths always pruned
    assert "drafts/secret.html" not in reasons  # pruned, never even stat'd


def test_walk_entries_options_change_the_url_set(tmp_path):
    root = _tree(tmp_path)
    clean = sitemap.walk_entries(root, "https://x.com", clean_urls=True)
    assert "https://x.com/about" in [e["loc"] for e in clean["entries"]]
    kept = sitemap.walk_entries(root, "https://x.com", strip_index=False)
    assert "https://x.com/index.html" in [e["loc"] for e in kept["entries"]]
    no_stamp = sitemap.walk_entries(root, "https://x.com", lastmod=None)
    assert all(e["lastmod"] is None for e in no_stamp["entries"])
    css = sitemap.walk_entries(root, "https://x.com", exts=(".css",))
    assert [e["loc"] for e in css["entries"]] == ["https://x.com/assets/app.css"]
    stamped = sitemap.walk_entries(root, "https://x.com", lastmod="second")
    assert stamped["entries"][0]["lastmod"].endswith("+00:00")
    with pytest.raises(ValueError):
        sitemap.walk_entries(root / "nope", "https://x.com")


def test_walk_output_is_byte_identical_across_runs(tmp_path):
    root = _tree(tmp_path)

    def render():
        res = sitemap.walk_entries(root, "https://x.com")
        entries = sitemap.dedupe(res["entries"])["entries"]
        return sitemap.render_files(entries, "sitemap.xml", res["base"])[0]["xml"]

    first = render()
    # a new, alphabetically-earlier file changes content -> the diff is real
    (root / "aaa.html").write_text("<html>a</html>", encoding="utf-8")
    os.utime(root / "aaa.html", (MT_A, MT_A))
    assert render() != first
    (root / "aaa.html").unlink()
    assert render() == first  # same inputs -> same bytes, no timestamp drift


# ---- source 2: an explicit URL list ----------------------------------------


def test_parse_url_list_absolute_relative_comments_and_bad_lines():
    text = """
# routes for x.com
https://x.com/a
/b
  c/d  2026-01-02
https://x.com/e 2026-02-03
not a url
/f
"""
    res = sitemap.parse_url_list(text, "https://x.com")
    locs = [e["loc"] for e in res["entries"]]
    assert locs == [
        "https://x.com/a",
        "https://x.com/b",
        "https://x.com/c/d",
        "https://x.com/e",
        "https://x.com/f",
    ]
    stamps = {e["loc"]: e["lastmod"] for e in res["entries"]}
    assert stamps["https://x.com/c/d"] == "2026-01-02"
    assert stamps["https://x.com/e"] == "2026-02-03"
    assert stamps["https://x.com/a"] is None
    # "not a url" is 2 whitespace fields -> the first is a bad loc, reported not fatal
    assert len(res["skipped"]) == 1
    assert res["skipped"][0]["path"] == "line 7"


def test_parse_url_list_without_base_reports_relative_lines():
    res = sitemap.parse_url_list("https://x.com/a\n/b\n")
    assert [e["loc"] for e in res["entries"]] == ["https://x.com/a"]
    assert res["skipped"][0]["reason"].startswith("relative path '/b'")


# ---- source 3: the #3 seo crawl store --------------------------------------


def test_entries_from_crawl_rows_honors_seo_indexability():
    rows = [
        {"Address": "https://x.com/", "Indexability": "Indexable", "Status Code": 200},
        {"Address": "https://x.com/gone", "Indexability": "Non-Indexable",
         "Status Code": 404},
        {"Address": "", "Indexability": "Indexable", "Status Code": 200},
    ]
    res = sitemap.entries_from_crawl_rows(rows, changefreq="weekly")
    assert [e["loc"] for e in res["entries"]] == ["https://x.com/"]
    assert res["entries"][0]["changefreq"] == "weekly"
    assert res["skipped"] == [
        {"path": "https://x.com/gone", "reason": "non-indexable (status 404)"}
    ]


def test_crawl_store_roundtrip_excludes_noindex_pages():
    """Drive the real seo crawler with an injected fetch, then read its rows."""
    page = (
        "<html><head><title>Scout sitemap fixture page with a real title</title>"
        '<meta name="description" content="A deterministic fixture page used by the '
        'sitemap adapter tests, long enough for the window.">'
        '</head><body><h1>H</h1><a href="/hidden">h</a><a href="/gone">g</a>'
        "</body></html>"
    )
    hidden = page.replace("<head>", '<head><meta name="robots" content="noindex">')
    pages = {
        "https://site.test/": page,
        "https://site.test/hidden": hidden,
    }

    def fetch(url):
        if url in pages:
            return {"status": 200, "final_url": url, "redirects": [],
                    "content_type": "text/html", "headers": {}, "body": pages[url],
                    "error": None}
        return {"status": 404, "final_url": url, "redirects": [],
                "content_type": "text/html", "headers": {}, "body": "", "error": None}

    conn = seo.open_store(":memory:")
    seo.crawl(conn, "https://site.test/", fetch, ts=1.0)
    rows = seo.to_rows(conn, seo.site_key("https://site.test/"))
    res = sitemap.entries_from_crawl_rows(rows)
    assert [e["loc"] for e in res["entries"]] == ["https://site.test/"]
    skipped = {s["path"] for s in res["skipped"]}
    assert "https://site.test/hidden" in skipped  # noindex never gets submitted
    assert "https://site.test/gone" in skipped  # the 404 either


# ---- dedupe + validate ------------------------------------------------------


def test_dedupe_sorts_and_keeps_the_newest_lastmod():
    entries = [
        sitemap.make_entry("https://x.com/b", lastmod="2026-01-01", source="s1"),
        sitemap.make_entry("https://x.com/a", lastmod="2025-01-01", source="s2"),
        sitemap.make_entry("https://x.com/a", lastmod="2026-05-05", source="s3"),
        sitemap.make_entry("https://x.com/c", source="s4"),
    ]
    res = sitemap.dedupe(entries)
    assert [e["loc"] for e in res["entries"]] == [
        "https://x.com/a", "https://x.com/b", "https://x.com/c"
    ]
    kept = {e["loc"]: e for e in res["entries"]}
    assert kept["https://x.com/a"]["lastmod"] == "2026-05-05"  # newest wins
    assert res["duplicates"] == [
        {"loc": "https://x.com/a", "kept_source": "s3", "dropped_source": "s2"}
    ]


def test_validate_flags_offbase_long_duplicate_and_empty():
    base = "https://x.com/"
    long_loc = base + "x" * (sitemap.MAX_LOC_LENGTH + 1)
    entries = [
        sitemap.make_entry(base),
        sitemap.make_entry("https://other.test/a"),
        sitemap.make_entry(long_loc),
    ]
    dupes = [{"loc": base, "kept_source": "a", "dropped_source": "b"}]
    diags = sitemap.validate(entries, base, duplicates=dupes)
    rules = {d["rule"] for d in diags}
    assert rules == {"sitemap:off-base", "sitemap:loc-too-long", "sitemap:duplicate-loc"}
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["sitemap:off-base"]["severity"] == "error"
    assert by_rule["sitemap:off-base"]["path"] == "https://other.test/a"
    assert by_rule["sitemap:loc-too-long"]["severity"] == "warning"
    assert openswap.summarize(diags)["by_severity"]["error"] == 1
    empty = sitemap.validate([], base)
    assert [d["rule"] for d in empty] == ["sitemap:no-urls"]
    assert empty[0]["severity"] == "error"


def test_validate_sharding_is_info_and_diagnostics_match_family_schema():
    base = "https://x.com/"
    entries = [sitemap.make_entry(f"{base}p{i}") for i in range(4)]
    diags = sitemap.validate(entries, base, max_urls=2)
    assert [d["rule"] for d in diags] == ["sitemap:sharded"]
    assert diags[0]["severity"] == "info"
    for d in sitemap.validate(entries + [sitemap.make_entry("https://o.test/x")], base):
        assert set(d) == {"path", "line", "col", "rule", "severity", "message",
                          "suggestion", "source"}
        assert d["severity"] in openswap.SEVERITIES
        assert d["source"] == "sitemap"


def test_validate_files_flags_the_50mb_limit():
    ok_file = {"name": "sitemap.xml", "bytes": sitemap.MAX_FILE_BYTES}
    big = {"name": "sitemap-1.xml", "bytes": sitemap.MAX_FILE_BYTES + 1}
    assert sitemap.validate_files([ok_file]) == []
    diags = sitemap.validate_files([ok_file, big])
    assert [d["rule"] for d in diags] == ["sitemap:file-too-large"]
    assert diags[0]["path"] == "sitemap-1.xml"


# ---- XML emission -----------------------------------------------------------


def test_urlset_xml_is_namespaced_escaped_and_ordered():
    entries = [
        sitemap.make_entry("https://x.com/a?p=1&q=2", lastmod="2026-03-04",
                           changefreq="daily", priority=0.5),
        sitemap.make_entry("https://x.com/b"),
    ]
    xml = sitemap.render(sitemap.build_urlset(entries))
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<urlset')
    assert xml.endswith("\n")
    assert "&amp;q=2" in xml and "&q=2" not in xml.replace("&amp;q=2", "")
    root = ET.fromstring(xml)
    ns = {"s": sitemap.SITEMAP_NS}
    urls = root.findall("s:url", ns)
    assert len(urls) == 2
    assert urls[0].find("s:loc", ns).text == "https://x.com/a?p=1&q=2"
    assert urls[0].find("s:lastmod", ns).text == "2026-03-04"
    assert urls[0].find("s:priority", ns).text == "0.5"
    # optional children are omitted, not emitted empty
    assert urls[1].find("s:lastmod", ns) is None
    assert urls[1].find("s:priority", ns) is None
    # xmlns is set locally, never via the process-global register_namespace
    assert ET.tostring(ET.Element("urlset"), encoding="unicode") == "<urlset />"


def test_render_files_single_file_under_the_cap():
    entries = [sitemap.make_entry(f"https://x.com/p{i}") for i in range(5)]
    files = sitemap.render_files(entries, "sitemap.xml", "https://x.com/", max_urls=5)
    assert len(files) == 1
    assert files[0]["name"] == "sitemap.xml" and files[0]["kind"] == "urlset"
    assert files[0]["urls"] == 5
    assert files[0]["bytes"] == len(files[0]["xml"].encode("utf-8"))


def test_render_files_shards_into_a_sitemapindex():
    entries = [
        sitemap.make_entry(f"https://x.com/p{i}", lastmod=f"2026-01-0{i + 1}")
        for i in range(5)
    ]
    files = sitemap.render_files(entries, "sitemap.xml", "https://x.com/", max_urls=2)
    assert [f["name"] for f in files] == [
        "sitemap.xml", "sitemap-1.xml", "sitemap-2.xml", "sitemap-3.xml"
    ]
    assert files[0]["kind"] == "sitemapindex"  # the canonical name stays the entrypoint
    assert [f["urls"] for f in files[1:]] == [2, 2, 1]
    idx = sitemap.parse_sitemap(files[0]["xml"])
    assert idx["kind"] == "sitemapindex"
    assert [e["loc"] for e in idx["entries"]] == [
        "https://x.com/sitemap-1.xml",
        "https://x.com/sitemap-2.xml",
        "https://x.com/sitemap-3.xml",
    ]
    # each shard ref carries the newest lastmod inside that shard
    assert [e["lastmod"] for e in idx["entries"]] == [
        "2026-01-02", "2026-01-04", "2026-01-05"
    ]
    # no URL is lost or duplicated by sharding
    got = []
    for f in files[1:]:
        got += [e["loc"] for e in sitemap.parse_sitemap(f["xml"])["entries"]]
    assert got == [e["loc"] for e in entries]


def test_default_shard_threshold_is_the_protocol_limit():
    assert sitemap.MAX_URLS_PER_FILE == 50_000
    base = "https://x.com/"
    entries = [sitemap.make_entry(f"{base}p{i}") for i in range(sitemap.MAX_URLS_PER_FILE)]
    assert len(sitemap.render_files(entries, "sitemap.xml", base)) == 1  # exactly at cap
    entries.append(sitemap.make_entry(f"{base}p50000"))
    files = sitemap.render_files(entries, "sitemap.xml", base)  # one over
    assert [f["kind"] for f in files] == ["sitemapindex", "urlset", "urlset"]
    assert [f["urls"] for f in files] == [0, 50_000, 1]


def test_shard_entries_rejects_a_zero_cap():
    with pytest.raises(ValueError):
        sitemap.shard_entries([sitemap.make_entry("https://x.com/a")], 0)


def test_parse_sitemap_reads_foreign_and_namespaceless_files():
    plain = (
        "<urlset><url><loc>https://x.com/a</loc><lastmod>2026-01-01</lastmod>"
        "</url></urlset>"
    )
    got = sitemap.parse_sitemap(plain)
    assert got["kind"] == "urlset" and got["count"] == 1
    assert got["entries"][0]["loc"] == "https://x.com/a"
    with pytest.raises(ValueError):
        sitemap.parse_sitemap("<html><body>not a sitemap</body></html>")
    with pytest.raises(ValueError):
        sitemap.parse_sitemap("<urlset><url>")  # malformed XML


# ---- write + diff (the deploy gate) ----------------------------------------


def test_write_files_emits_lf_utf8_bytes(tmp_path):
    entries = [sitemap.make_entry("https://x.com/café")]
    files = sitemap.render_files(entries, "sitemap.xml", "https://x.com/")
    written = sitemap.write_files(files, tmp_path / "out")
    assert written == [str(tmp_path / "out" / "sitemap.xml")]
    raw = (tmp_path / "out" / "sitemap.xml").read_bytes()
    assert b"\r\n" not in raw  # LF on Windows too, or the file diffs against itself
    assert raw.decode("utf-8") == files[0]["xml"]


def test_diff_files_detects_drift_missing_and_stale(tmp_path):
    base = "https://x.com/"
    entries = [sitemap.make_entry(f"{base}p{i}") for i in range(3)]
    files = sitemap.render_files(entries, "sitemap.xml", base)
    assert sitemap.diff_files(files, tmp_path)["missing"] == ["sitemap.xml"]
    sitemap.write_files(files, tmp_path)
    clean = sitemap.diff_files(files, tmp_path)
    assert clean["drift"] is False and clean["unchanged"] == ["sitemap.xml"]
    assert clean["diff"] == []
    # content changed since the sitemap was committed
    changed = sitemap.render_files(
        entries + [sitemap.make_entry(f"{base}new")], "sitemap.xml", base
    )
    res = sitemap.diff_files(changed, tmp_path)
    assert res["drift"] is True and res["changed"] == ["sitemap.xml"]
    assert any(line.startswith("+") and "/new" in line for line in res["diff"])
    # a leftover shard from a previously bigger URL set keeps being served
    (tmp_path / "sitemap-9.xml").write_bytes(b"<urlset/>")
    assert sitemap.diff_files(files, tmp_path)["stale"] == ["sitemap-9.xml"]


def test_summarize_files_reports_the_set():
    entries = [sitemap.make_entry(f"https://x.com/p{i}") for i in range(3)]
    files = sitemap.render_files(entries, "sitemap.xml", "https://x.com/", max_urls=2)
    s = sitemap.summarize_files(files)
    assert s["file_count"] == 3 and s["urls"] == 3 and s["sharded"] is True
    assert s["bytes"] == sum(f["bytes"] for f in files)


# ---- family schema + detection ----------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.sitemap import cli as sitemap_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = sitemap_cli._capability()
    assert cap["adapter"] == "sitemap"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "sitemap-generator"
    # live-site crawlers: surfaced for awareness, never executed
    assert cap["extras"]["python-sitemap"]["found"] is False
    assert cap["extras"]["xmllint"]["found"] is False


def test_manifest_denies_network_and_declares_writes():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "sitemap" / "manifest.yaml").read_text()
    )
    caps = mf["capabilities"]
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is True
    assert caps["secrets"]["allow"] == []


# ---- the real CLI in a subprocess (fully offline — no network surface) -------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_sitemap_hello_envelope():
    r = _cli(["sitemap", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_gen_writes_a_deterministic_sitemap(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "out" / "sitemap.xml"
    args = ["sitemap", "gen", "--root", str(root), "--base-url", "https://x.com",
            "--out", str(out), "--exclude", "drafts/*", "--exclude", "404.html"]
    r = _cli(args)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["wrote"] is True and data["urls"] == 5 and data["sharded"] is False
    assert data["written"] == [str(out)]
    first = out.read_bytes()
    parsed = sitemap.parse_sitemap(first.decode("utf-8"))
    locs = [e["loc"] for e in parsed["entries"]]
    assert locs == sorted(locs)
    assert "https://x.com/blog/" in locs
    assert all("drafts" not in loc and "404" not in loc for loc in locs)
    assert b"\r\n" not in first
    # rerunning the generator changes nothing: no timestamp, sorted output
    assert _cli(args).returncode == 0
    assert out.read_bytes() == first


def test_cli_gen_dry_run_writes_nothing(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "sitemap.xml"
    r = _cli(["sitemap", "gen", "--root", str(root), "--base-url", "https://x.com",
              "--out", str(out), "--dry-run"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["wrote"] is False and data["written"] == [] and data["urls"] == 7
    assert not out.exists()


def test_cli_gen_shards_over_max_urls(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "sitemap.xml"
    r = _cli(["sitemap", "gen", "--root", str(root), "--base-url", "https://x.com",
              "--out", str(out), "--max-urls", "3"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["sharded"] is True and data["file_count"] == 4
    assert sitemap.parse_sitemap(out.read_text(encoding="utf-8"))["kind"] == (
        "sitemapindex"
    )
    assert (tmp_path / "sitemap-3.xml").exists()
    rules = {d["rule"] for d in data["diagnostics"]}
    assert "sitemap:sharded" in rules


def test_cli_gen_from_url_list_and_fail_on_gate(tmp_path):
    routes = tmp_path / "routes.txt"
    routes.write_text(
        "# hand-curated\n/a\n/b 2026-01-02\nhttps://other.test/x\n", encoding="utf-8"
    )
    out = tmp_path / "sitemap.xml"
    args = ["sitemap", "gen", "--urls", str(routes), "--base-url", "https://x.com",
            "--out", str(out)]
    r = _cli(args)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["urls"] == 3
    assert "sitemap:off-base" in {d["rule"] for d in data["diagnostics"]}
    # the same run with the gate armed fails the deploy
    r = _cli([*args, "--fail-on", "error"])
    assert r.returncode == 1
    assert json.loads(r.stdout)["ok"] is True  # the report still emits


def test_cli_check_is_the_drift_gate(tmp_path):
    root = _tree(tmp_path)
    out = root / "sitemap.xml"
    args = ["sitemap", "check", "--root", str(root), "--base-url", "https://x.com"]
    r = _cli(args)
    assert r.returncode == 1  # nothing generated yet
    assert json.loads(r.stdout)["data"]["missing"] == ["sitemap.xml"]
    gen = _cli(["sitemap", "gen", "--root", str(root), "--base-url", "https://x.com"])
    assert gen.returncode == 0, gen.stderr + gen.stdout
    assert out.exists()
    r = _cli(args)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["drift"] is False and data["diff"] == []
    # ship a new page without regenerating -> the gate fires with a real diff
    new = root / "brand-new.html"
    new.write_text("<html>new</html>", encoding="utf-8")
    os.utime(new, (MT_A, MT_A))
    r = _cli(args)
    assert r.returncode == 1
    data = json.loads(r.stdout)["data"]
    assert data["drift"] is True and data["changed"] == ["sitemap.xml"]
    assert any("brand-new" in line for line in data["diff"])


def test_cli_lint_flags_a_bad_sitemap(tmp_path):
    bad = tmp_path / "sitemap.xml"
    bad.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://x.com/a</loc></url>"
        "<url><loc>https://x.com/a</loc></url>"
        "<url><loc>https://other.test/b</loc></url>"
        "</urlset>\n",
        encoding="utf-8",
    )
    r = _cli(["sitemap", "lint", str(bad)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["kind"] == "urlset" and data["urls"] == 3 and data["unique_urls"] == 2
    rules = {d["rule"] for d in data["diagnostics"]}
    assert {"sitemap:duplicate-loc", "sitemap:off-base"} <= rules
    r = _cli(["sitemap", "lint", str(bad), "--fail-on", "error"])
    assert r.returncode == 1
    # a clean sitemap passes the same gate
    good = tmp_path / "good.xml"
    good.write_bytes(
        sitemap.render_files(
            [sitemap.make_entry("https://x.com/a")], "good.xml", "https://x.com/"
        )[0]["xml"].encode("utf-8")
    )
    r = _cli(["sitemap", "lint", str(good), "--fail-on", "warning"])
    assert r.returncode == 0, r.stderr + r.stdout


def test_cli_rejects_ambiguous_and_missing_sources(tmp_path):
    root = _tree(tmp_path)
    r = _cli(["sitemap", "gen", "--base-url", "https://x.com"])
    assert r.returncode == 1
    assert "exactly one URL source" in json.loads(r.stdout)["error"]
    r = _cli(["sitemap", "gen", "--root", str(root), "--urls", "x.txt",
              "--base-url", "https://x.com"])
    assert r.returncode == 1
    assert "exactly one URL source" in json.loads(r.stdout)["error"]
    r = _cli(["sitemap", "gen", "--root", str(root)])
    assert r.returncode == 1
    assert "--base-url is required" in json.loads(r.stdout)["error"]
    r = _cli(["sitemap", "gen", "--root", str(root), "--base-url", "x.com"])
    assert r.returncode == 1
    assert "base URL must be absolute" in json.loads(r.stdout)["error"]
    r = _cli(["sitemap", "gen", "--root", str(root), "--base-url", "https://x.com",
              "--lastmod", "hourly"])
    assert r.returncode == 1
    assert "--lastmod must be one of" in json.loads(r.stdout)["error"]


def test_cli_from_crawl_without_a_store_fails_actionably(tmp_path):
    r = _cli(["sitemap", "gen", "--from-crawl", "bhenre",
              "--db", str(tmp_path / "none.db"), "--out", str(tmp_path / "s.xml")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no seo crawl store" in data["error"]
    assert "example" in data
