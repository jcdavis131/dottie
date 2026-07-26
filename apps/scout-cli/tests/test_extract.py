"""Extract — openswap #11 (Diffbot / Mercury Parser -> stdlib Readability-style
article extraction). Pure-logic core tests: the text-vs-link-density scorer,
boilerplate stripping, title/byline/date heuristics, charset sniffing, the
corpus ledger, the cached batch path, capability detection and the real CLI in a
subprocess. Offline and deterministic by construction: every fixture is an
inline HTML string, the fetch boundary is an injected callable, and no test
opens a socket."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import extract, openswap

ROOT = Path(__file__).resolve().parents[1]

# ---- fixtures ---------------------------------------------------------------

P1 = (
    "Evaluation without a capacity gate ratchets the bar upward, which is how a "
    "parameter-deleting swap gets promoted, and every later run then inherits an "
    "impossible baseline that nobody measured."
)
P2 = (
    "The second paragraph explains, at length, why paired seed testing retracted "
    "the third sota row, and why the ledger, not the notes, is the only place a "
    "baseline may ever be read from."
)

ARTICLE = f"""<!DOCTYPE html>
<html lang="en"><head>
  <title>The Ratchet Problem | Dottie Lab</title>
  <meta property="og:site_name" content="Dottie Lab">
  <meta property="article:published_time" content="2026-03-05T09:00:00Z">
  <style>.hidden {{ display: none }}</style>
</head><body>
  <nav><a href="/">Home</a><a href="/archive">Archive</a><a href="/about">About</a></nav>
  <header class="masthead">
    <h1>The Ratchet Problem</h1>
    <span class="byline">By Cameron Davis</span>
  </header>
  <div id="main" class="post-content">
    <p>{P1}</p>
    <p>{P2}</p>
    <pre>python evaluate.py --paired-seeds 5
python promote.py --dry-run</pre>
  </div>
  <aside class="sidebar"><h2>Related</h2>
    <ul><li><a href="/x">One</a></li><li><a href="/y">Two</a></li></ul>
  </aside>
  <div class="share"><a href="/t">Tweet this</a><a href="/f">Share on Facebook</a></div>
  <footer>Copyright 2026 Dottie Lab. Subscribe to our newsletter today.</footer>
  <script>window.track("pageview");</script>
</body></html>"""


def _link_farm(count: int = 60) -> str:
    """An article next to a link rail that OUT-SCORES it on raw text volume.

    The rail is not tagged <nav> and its class is not chrome-shaped, so nothing
    but link density can demote it — which is exactly what this fixture exists
    to prove.
    """
    rail = "\n".join(
        f'<p><a href="/post/{i}">Another fairly long headline about topic '
        f"number {i} here</a></p>"
        for i in range(count)
    )
    return f"""<html><body>
    <div class="article-body"><p>{P1}</p><p>{P2}</p></div>
    <div class="stream">{rail}</div>
    </body></html>"""


def _extract(html: str, **kw) -> dict:
    return extract.extract(html, **kw)


def _candidates(html: str) -> dict[str, object]:
    """describe() -> scored node, for asserting on the scorer directly."""
    doc = extract.parse_document(html)
    extract.prune_unlikely(doc.root)
    cands = extract.score_document(doc.root)
    return {c.describe(): c for c in cands}


def _mem():
    return extract.open_store(":memory:")


# ---- stdlib-only invariant (the whole point of the openswap family) ----------


def test_core_imports_are_stdlib_only():
    tree = ast.parse((ROOT / "bigbang" / "core" / "extract.py").read_text("utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"


# ---- boilerplate stripping --------------------------------------------------


def test_boilerplate_never_reaches_the_article():
    res = _extract(ARTICLE, url="https://example.com/ratchet")
    text = res["text"]
    assert P1 in text and P2 in text
    for chrome in (
        "Archive",
        "Subscribe to our newsletter",
        "Tweet this",
        "window.track",
        "display: none",
        "Related",
    ):
        assert chrome not in text, f"boilerplate leaked: {chrome}"
    assert res["candidate"] == "div#main.post-content"
    assert res["removed"]["nav"] == 1
    assert res["removed"]["footer"] == 1
    assert res["removed"]["aside"] == 1
    assert res["removed"]["script"] == 1
    assert res["removed"]["style"] == 1
    assert res["removed"]["unlikely-class"] == 1  # <div class="share">


def test_script_and_style_text_is_not_even_stored():
    doc = extract.parse_document(
        "<html><body><style>.a{color:red}</style>"
        "<script>var x = 1;</script><p>real prose here</p></body></html>"
    )
    assert "color:red" not in doc.root.text
    assert "var x" not in doc.root.text
    assert "real prose here" in doc.root.text


def test_pre_blocks_stay_verbatim():
    res = _extract(ARTICLE)
    assert (
        "python evaluate.py --paired-seeds 5\npython promote.py --dry-run"
        in (res["text"])
    )


def test_paragraphs_are_separated_by_blank_lines():
    res = _extract(ARTICLE)
    assert f"{P1}\n\n{P2}" in res["text"]


def test_entities_are_decoded_not_escaped():
    html = (
        "<html><body><div class='content'><p>Ratchets &amp; baselines &#8212; a "
        "long enough paragraph of prose to be scored by the extractor at all."
        "</p></div></body></html>"
    )
    res = _extract(html)
    assert "Ratchets & baselines — a long enough" in res["text"]
    assert "&amp;" not in res["text"]


# ---- the scorer: link density is what does the work -------------------------


def test_link_density_measures_anchor_share():
    doc = extract.parse_document(
        "<div id=a><p>plain prose with no links at all in it</p></div>"
        "<div id=b><p><a href=/x>all of this is a link</a></p></div>"
    )
    by_id = {n.attrs.get("id"): n for n in extract._walk(doc.root) if n.tag == "div"}
    assert extract.link_density(by_id["a"]) == 0.0
    assert extract.link_density(by_id["b"]) == pytest.approx(1.0)


def test_link_rail_outscores_the_article_on_volume_but_loses_on_density():
    html = _link_farm()
    cands = _candidates(html)
    article, rail = cands["div.article-body"], cands["div.stream"]
    # without the density penalty the rail would win: it has far more paragraphs
    assert rail.score > article.score
    # with it, >95% of the rail's score is erased and the article wins by 10x
    assert rail.final < 0.05 * rail.score
    assert article.final > 10 * rail.final
    res = _extract(html)
    assert res["candidate"] == "div.article-body"
    assert "Another fairly long headline" not in res["text"]
    assert P1 in res["text"]
    assert res["link_density"] == 0.0


def test_class_weight_and_base_score_are_the_documented_priors():
    doc = extract.parse_document(
        "<div class='article-body'></div><div class='sidebar-widget'></div>"
        "<div class='plain'></div>"
    )
    weights = {n.describe(): extract._class_weight(n) for n in extract._walk(doc.root)}
    assert weights["div.article-body"] == 25.0
    assert weights["div.sidebar-widget"] == -25.0
    assert weights["div.plain"] == 0.0
    assert extract.base_score("article") == 8.0
    assert extract.base_score("div") == 5.0
    assert extract.base_score("li") == -3.0
    assert extract.base_score("nosuchtag") == 0.0


def test_short_runs_are_not_scored_as_paragraphs():
    html = (
        "<html><body><div id=chrome><p>Home</p><p>Login</p><p>Cart</p></div>"
        f"<div id=story><p>{P1}</p></div></body></html>"
    )
    cands = _candidates(html)
    assert "div#story" in cands
    assert "div#chrome" not in cands  # every run is under MIN_PARAGRAPH_CHARS
    # the floor is config, not code: lower it and the chrome starts scoring
    doc = extract.parse_document(html)
    low = {
        c.describe() for c in extract.score_document(doc.root, min_paragraph_chars=4)
    }
    assert "div#chrome" in low


def test_unlikely_class_is_pruned_unless_a_content_token_rescues_it():
    def body(cls: str) -> str:
        return (
            f"<html><body><div class='{cls}'><p>{P1}</p><p>{P2}</p></div></body></html>"
        )

    assert _extract(body("sidebar"))["removed"].get("unlikely-class") == 1
    # "comment-content" carries a content token -> Readability's okMaybe rescue
    kept = _extract(body("comment-content"))
    assert "unlikely-class" not in kept["removed"]
    assert P1 in kept["text"]


def test_pruning_never_takes_the_article_with_it():
    html = (
        "<html><body><div class='page-header'><article>"
        f"<p>{P1}</p><p>{P2}</p></article></div></body></html>"
    )
    res = _extract(html)
    assert P1 in res["text"] and P2 in res["text"]
    assert "unlikely-class" not in res["removed"]


def test_sibling_paragraphs_join_the_winning_block():
    html = (
        "<html><body><div class='wrap'>"
        f"<p>{P1}</p>"
        f"<div class='content'><p>{P2}</p><p>{P2}</p></div>"
        "</div></body></html>"
    )
    res = _extract(html)
    assert P1 in res["text"]  # the lead <p> outside the winner is recovered
    assert res["blocks"] >= 2


# ---- title ------------------------------------------------------------------


def test_clean_title_splits_on_the_separator_the_readability_way():
    assert extract.clean_title("Long Headline About Things | Site Name") == (
        "Long Headline About Things"
    )
    assert extract.clean_title("Site | Long Headline About Things") == (
        "Long Headline About Things"
    )
    # neither side has 3+ words: leave it alone rather than guess
    assert extract.clean_title("Ratchet | Lab") == "Ratchet | Lab"
    assert extract.clean_title("   ") is None
    assert extract.clean_title(None, h1="Fallback Headline") == "Fallback Headline"


def test_clean_title_strips_the_site_name_and_honors_a_matching_h1():
    assert (
        extract.clean_title("Headline Here – Dottie Lab", site_name="Dottie Lab")
        == "Headline Here"
    )
    # the h1 reproduces part of a title the separator split could not clean
    assert extract.clean_title("A B | Site", h1="A B") == "A B"
    # ...but a shorter h1 never beats a good split
    assert extract.clean_title("Foo Bar Baz | Site", h1="Foo Bar") == "Foo Bar Baz"
    # an unrelated h1 is ignored
    assert (
        extract.clean_title("Long Headline About Things | Site", h1="Newsletter signup")
        == "Long Headline About Things"
    )


def test_title_priority_chain_reports_its_provenance():
    res = _extract(ARTICLE)
    assert res["title"] == "The Ratchet Problem"
    assert res["title_source"] == "title-tag"
    with_og = ARTICLE.replace(
        '<meta property="og:site_name"',
        '<meta property="og:title" content="OG Headline Wins | Dottie Lab">'
        '\n  <meta property="og:site_name"',
    )
    res2 = _extract(with_og)
    assert res2["title"] == "OG Headline Wins"  # site suffix stripped
    assert res2["title_source"] == "meta:og:title"


def test_svg_title_is_a_tooltip_not_the_page_title():
    # no <title> in <head> at all: an unguarded parser would take the svg's
    # tooltip as the headline, so the h1 fallback proves the guard is live
    html = (
        "<html><head></head><body><svg><title>icon tooltip</title></svg>"
        "<h1>Real Page Headline Here</h1>"
        f"<div class='content'><p>{P1}</p></div></body></html>"
    )
    res = _extract(html)
    assert res["title"] == "Real Page Headline Here"
    # and with a real <title>, the separator split still cleans the site suffix
    res2 = _extract(
        html.replace("<head>", "<head><title>Real Page Title | Site</title>")
    )
    assert res2["title"] == "Real Page Title"


# ---- byline -----------------------------------------------------------------


def test_byline_is_found_inside_a_dropped_header():
    res = _extract(ARTICLE)
    assert res["byline"] == "Cameron Davis"
    assert res["byline_source"] == "byline-class"  # <header> is chrome, byline isn't
    assert "By Cameron Davis" not in res["text"]  # ...and it stays out of the body


def test_byline_from_meta_and_rel_author():
    meta = ARTICLE.replace(
        "<style>", '<meta name="author" content="Ada Lovelace">\n  <style>'
    )
    res = _extract(meta)
    assert (res["byline"], res["byline_source"]) == ("Ada Lovelace", "meta:author")
    rel = (
        "<html><body><p>Reported by "
        '<a rel="author" href="/staff/gh">Grace Hopper</a></p>'
        f"<div class='content'><p>{P1}</p></div></body></html>"
    )
    res2 = _extract(rel)
    assert (res2["byline"], res2["byline_source"]) == ("Grace Hopper", "rel=author")


def test_clean_byline_strips_prefixes_and_rejects_non_names():
    assert extract.clean_byline("By Cameron Davis") == "Cameron Davis"
    assert extract.clean_byline("  Posted by  Jane Roe ") == "Jane Roe"
    assert extract.clean_byline("Written by Jane Roe | Staff") == "Jane Roe | Staff"
    assert extract.clean_byline("March 5, 2026") is None  # a dateline is not a byline
    assert extract.clean_byline("https://example.com/author/x") is None
    assert extract.clean_byline("x" * 200) is None
    assert extract.clean_byline("") is None and extract.clean_byline(None) is None


# ---- date -------------------------------------------------------------------


def test_normalize_date_is_locale_independent_and_day_granular():
    assert extract.normalize_date("2026-03-05T09:00:00Z") == "2026-03-05"
    assert extract.normalize_date("2026/3/5") == "2026-03-05"
    assert extract.normalize_date("20260305") == "2026-03-05"
    assert extract.normalize_date("March 5, 2026") == "2026-03-05"
    assert extract.normalize_date("5 Mar 2026") == "2026-03-05"
    assert extract.normalize_date("21st September 2026") == "2026-09-21"
    assert extract.normalize_date("Tue, 05 Mar 2026 09:00:00 GMT") == "2026-03-05"


def test_normalize_date_rejects_junk_and_impossible_dates():
    for bad in (
        None,
        "",
        "   ",
        "not a date",
        "2026",
        "2026-13-05",
        "2026-02-31",
        "Xyz 5, 2026",
        "x" * 80,
    ):
        assert extract.normalize_date(bad) is None, bad


def test_date_from_meta_then_time_element_with_pubdate_ranking():
    res = _extract(ARTICLE)
    assert res["date"] == "2026-03-05"
    assert res["date_source"] == "meta:article:published_time"
    assert res["date_raw"] == "2026-03-05T09:00:00Z"
    timed = (
        "<html><body>"
        '<time datetime="2020-01-01">updated long ago</time>'
        '<time datetime="2026-07-19" pubdate>19 July 2026</time>'
        f"<div class='content'><p>{P1}</p></div></body></html>"
    )
    res2 = _extract(timed)
    # the pubdate-marked element outranks the bare one even though it is second
    assert (res2["date"], res2["date_source"]) == ("2026-07-19", "time")


# ---- JSON-LD ----------------------------------------------------------------


def test_json_ld_article_facts_beat_a_sitewide_organization_block():
    html = f"""<html><head>
    <script type="application/ld+json">
    {{"@context":"https://schema.org","@type":"Organization",
      "name":"Dottie Lab","author":{{"name":"Web Team"}}}}
    </script>
    <script type="application/ld+json">
    {{"@graph":[{{"@type":"WebSite","name":"Dottie Lab"}},
      {{"@type":"NewsArticle","headline":"Ledgers Beat Notes",
        "author":[{{"name":"Cameron Davis"}},{{"name":"Ada Lovelace"}}],
        "datePublished":"2026-03-05T09:00:00+00:00"}}]}}
    </script></head><body><div class="content"><p>{P1}</p></div></body></html>"""
    res = _extract(html)
    assert (res["title"], res["title_source"]) == (
        "Ledgers Beat Notes",
        "json-ld:headline",
    )
    assert res["byline"] == "Cameron Davis, Ada Lovelace"
    assert res["byline_source"] == "json-ld:author"
    assert (res["date"], res["date_source"]) == ("2026-03-05", "json-ld:datePublished")


def test_broken_json_ld_is_ignored_not_fatal():
    html = (
        '<html><head><script type="application/ld+json">{not json,,}</script>'
        "<title>Still Works Fine Here</title></head>"
        f"<body><div class='content'><p>{P1}</p></div></body></html>"
    )
    res = _extract(html)
    assert res["title"] == "Still Works Fine Here"
    assert P1 in res["text"]


# ---- charset ----------------------------------------------------------------


def test_sniff_charset_precedence_bom_header_meta_utf8():
    assert extract.sniff_charset(b"\xef\xbb\xbf<html>") == "utf-8-sig"
    assert extract.sniff_charset(b"<html>", "iso-8859-1") == "iso-8859-1"
    assert extract.sniff_charset(b'<meta charset="iso-8859-2">') == "iso-8859-2"
    # a header wins over the meta tag, and garbage never wins at all
    assert extract.sniff_charset(b'<meta charset="cp1252">', "iso-8859-1") == (
        "iso-8859-1"
    )
    assert extract.sniff_charset(b"<html>", "not-a-real-charset") == "utf-8"
    assert extract.sniff_charset(b"<html>") == "utf-8"


def test_decode_html_uses_the_declared_charset_and_never_raises():
    latin = '<html><meta charset="iso-8859-1"><p>caf\xe9 cr\xe8me</p>'.encode("latin-1")
    assert "café crème" in extract.decode_html(latin)
    # undeclared, undecodable bytes degrade to U+FFFD instead of exploding
    assert "�" in extract.decode_html(b"<p>\xff\xfe\xfa</p>")


# ---- adversarial input ------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        "",
        "   ",
        "not html at all, just a sentence about ratchets and baselines",
        "<html><body><div><p>unclosed everything",
        "</div></p></body></html>",
        "<p>one<p>two<p>three",
        "<div" + ">" * 3,
        "<html><body><script>if (a </div> b) {}</script><p>after</p></body></html>",
        "<ul><li>a<li>b<li>c</ul>",
        "<table><tr><td>cell<td>cell2</table>",
        "<html><body>" + "<div>" * 60 + P1 + "</div>" * 60 + "</body></html>",
        "<!-- just a comment -->",
        "<html lang><body><p>attribute with no value</p></body></html>",
    ],
)
def test_malformed_input_never_crashes(html):
    res = _extract(html)
    assert isinstance(res["text"], str)
    assert res["word_count"] == extract.word_count(res["text"])
    assert res["chars"] == len(res["text"])
    assert res["content_hash"] == extract.content_hash(html)


def test_implicit_close_keeps_sibling_paragraphs_apart():
    doc = extract.parse_document("<div><p>first run of text<p>second run</div>")
    div = next(n for n in extract._walk(doc.root) if n.tag == "div")
    assert [c.tag for c in div.children()] == ["p", "p"]
    assert extract.render_text([div]) == "first run of text\n\nsecond run"


def test_empty_page_yields_zero_words_not_an_exception():
    res = _extract(
        "<html><head><title>Nothing Here At All</title></head><body></body></html>"
    )
    assert res["word_count"] == 0
    assert res["text"] == ""
    assert res["title"] == "Nothing Here At All"


# ---- family diagnostics -----------------------------------------------------


def test_to_diagnostics_maps_quality_onto_the_family_schema():
    empty = _extract("<html><body></body></html>", source="empty.html")
    thin = _extract(
        f"<html><body><div class='content'><p>{P1}</p></div></body></html>",
        source="thin.html",
    )
    good = _extract(ARTICLE, url="https://example.com/ratchet")
    diags = extract.to_diagnostics([empty, thin, good], thin_words=40)
    by_path: dict[str, set[str]] = {}
    for d in diags:
        by_path.setdefault(d["path"], set()).add(d["rule"])
        assert d["source"] == "extract"
    assert "extract:no-content" in by_path["empty.html"]
    assert "extract:no-date" in by_path["empty.html"]
    assert "extract:thin-content" in by_path["thin.html"]  # 34 words < 40
    assert by_path.get("https://example.com/ratchet") is None  # a clean read is quiet
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1
    assert summary["by_severity"]["warning"] == 1
    assert summary["total"] == len(diags)


def test_thin_words_threshold_is_config_not_code():
    res = _extract(
        f"<html><body><div class='content'><p>{P1}</p></div></body></html>",
        source="s.html",
    )
    rules = {d["rule"] for d in extract.to_diagnostics([res], thin_words=1000)}
    assert "extract:thin-content" in rules
    relaxed = {d["rule"] for d in extract.to_diagnostics([res], thin_words=5)}
    assert "extract:thin-content" not in relaxed


def test_link_heavy_result_is_flagged():
    res = {
        "source": "rail.html",
        "word_count": 500,
        "link_density": 0.91,
        "title": "T",
        "date": "2026-01-01",
    }
    rules = {d["rule"] for d in extract.to_diagnostics([res])}
    assert rules == {"extract:link-heavy"}


# ---- corpus ledger ----------------------------------------------------------


def _tables(conn):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_open_store_creates_schema_and_is_idempotent(tmp_path):
    db = tmp_path / "nested" / "extract.db"
    conn = extract.open_store(db)
    assert {"documents", "meta"} <= _tables(conn)
    doc_id = extract.record_document(conn, _extract(ARTICLE, source="a.html"), ts=100.0)
    conn.close()
    conn2 = extract.open_store(db)  # re-open the SAME file: rows survive
    assert extract.document_text(conn2, doc_id)["title"] == "The Ratchet Problem"
    assert conn2.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_record_document_dedupes_by_content_hash():
    conn = _mem()
    res = _extract(ARTICLE, source="a.html")
    first = extract.record_document(conn, res, ts=100.0)
    again = extract.record_document(conn, dict(res, source="b.html"), ts=200.0)
    assert first == again  # same bytes -> same row, refreshed
    row = extract.document_text(conn, first)
    assert row["source"] == "b.html" and row["ts"] == 200.0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_cached_document_is_shaped_like_an_extract_result():
    conn = _mem()
    res = _extract(ARTICLE, source="a.html")
    extract.record_document(conn, res, ts=100.0)
    hit = extract.cached_document(conn, res["content_hash"])
    for key in ("title", "byline", "date", "text", "word_count", "source", "excerpt"):
        assert key in hit
    assert hit["text"] == res["text"]
    assert hit["word_count"] == res["word_count"]
    assert extract.cached_document(conn, "0" * 64) is None


def test_recent_documents_lists_without_bodies_and_filters_by_source():
    conn = _mem()
    extract.record_document(conn, _extract(ARTICLE, source="a.html"), ts=100.0)
    extract.record_document(
        conn,
        _extract(
            f"<html><body><div class=content><p>{P2}</p></div></body></html>",
            source="b.html",
        ),
        ts=200.0,
    )
    rows = extract.recent_documents(conn, limit=10)
    assert [r["source"] for r in rows] == ["b.html", "a.html"]  # newest first
    assert all("text" not in r for r in rows)
    assert [r["source"] for r in extract.recent_documents(conn, source="a.html")] == (
        ["a.html"]
    )
    assert len(extract.recent_documents(conn, limit=1)) == 1


def test_corpus_stats_rolls_up_the_ingested_set():
    conn = _mem()
    assert extract.corpus_stats(conn)["documents"] == 0
    a = _extract(ARTICLE, source="a.html")
    b = _extract("<html><body></body></html>", source="b.html")  # untitled, undated
    extract.record_document(conn, a, ts=100.0)
    extract.record_document(conn, b, ts=200.0)
    stats = extract.corpus_stats(conn)
    assert stats["documents"] == 2
    assert stats["words"] == a["word_count"] + b["word_count"]
    assert stats["sources"] == 2
    assert stats["titled"] == 1 and stats["dated"] == 1
    assert stats["avg_words"] == round(stats["words"] / 2, 1)
    assert (stats["first_ts"], stats["last_ts"]) == (100.0, 200.0)


# ---- batch: injected fetch boundary, cache, ordering ------------------------


def _fetcher(pages: dict[str, str], calls: list[str] | None = None):
    def fetch(src: str) -> dict:
        if calls is not None:
            calls.append(src)
        if src not in pages:
            return {"html": "", "url": src, "error": "HTTPError: 404"}
        return {"html": pages[src], "url": f"https://example.com/{src}", "error": None}

    return fetch


def test_run_batch_records_in_input_order_and_counts():
    conn = _mem()
    pages = {
        "a": ARTICLE,
        "b": f"<html><body><div class=content><p>{P2}</p></div></body></html>",
    }
    calls: list[str] = []
    res = extract.run_batch(conn, ["b", "a"], _fetcher(pages, calls), ts=100.0)
    assert calls == ["b", "a"]
    assert [r["requested"] for r in res["results"]] == ["b", "a"]
    assert (res["extracted"], res["cached"], res["failed"]) == (2, 0, 0)
    assert res["words"] == sum(r["word_count"] for r in res["results"])
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2


def test_run_batch_second_pass_serves_the_ledger_instead_of_re_parsing():
    conn = _mem()
    fetch = _fetcher({"a": ARTICLE})
    extract.run_batch(conn, ["a"], fetch, ts=100.0)
    # Prove the cached row comes from the LEDGER and not from a fresh parse:
    # doctor the stored title, then ask again. A re-parse would say "The Ratchet
    # Problem"; the cache says what the ledger says.
    conn.execute("UPDATE documents SET title = 'FROM THE LEDGER'")
    conn.commit()
    again = extract.run_batch(conn, ["a"], fetch, ts=200.0)
    assert (again["cached"], again["extracted"]) == (1, 0)
    assert again["results"][0]["title"] == "FROM THE LEDGER"
    assert again["results"][0]["cached"] is True
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_no_cache_forces_a_real_re_parse():
    conn = _mem()
    fetch = _fetcher({"a": ARTICLE})
    extract.run_batch(conn, ["a"], fetch, ts=100.0)
    conn.execute("UPDATE documents SET title = 'FROM THE LEDGER'")
    conn.commit()
    again = extract.run_batch(conn, ["a"], fetch, ts=200.0, use_cache=False)
    assert again["cached"] == 0
    assert again["results"][0]["title"] == "The Ratchet Problem"
    assert again["results"][0]["cached"] is False


def test_run_batch_no_record_leaves_the_ledger_empty():
    conn = _mem()
    res = extract.run_batch(conn, ["a"], _fetcher({"a": ARTICLE}), record=False)
    assert res["results"][0]["word_count"] > 0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_run_batch_keeps_going_past_failures():
    conn = _mem()

    def hostile(src: str) -> dict:
        if src == "boom":
            raise RuntimeError("fetcher exploded")
        return _fetcher({"a": ARTICLE})(src)

    res = extract.run_batch(conn, ["missing", "boom", "a"], hostile, ts=100.0)
    assert res["failed"] == 2
    assert [f["source"] for f in res["failures"]] == ["missing", "boom"]
    assert "HTTPError" in res["failures"][0]["error"]
    assert "RuntimeError: fetcher exploded" in res["failures"][1]["error"]
    assert [r["requested"] for r in res["results"]] == ["a"]  # the good one landed


# ---- the plugin's own helpers (offline) -------------------------------------


def test_is_url_only_accepts_http_and_https():
    from bigbang.plugins.extract import cli as extract_cli

    assert extract_cli.is_url("https://example.com/x") is True
    assert extract_cli.is_url("http://localhost:8000/x") is True
    for other in (
        "file:///c:/x.html",
        "page.html",
        "-",
        "C:\\tmp\\page.html",
        "ftp://example.com/x",
    ):
        assert extract_cli.is_url(other) is False


def test_prefetch_returns_every_source_and_preserves_keys():
    from bigbang.plugins.extract import cli as extract_cli

    seen: list[str] = []

    def loader(src: str) -> dict:
        seen.append(src)
        return {"html": f"<p>{src}</p>", "url": src, "error": None}

    sources = [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
        "local.html",
    ]
    fetched = extract_cli.prefetch(sources, loader, jobs=4)
    assert set(fetched) == set(sources)  # concurrency must not lose a source
    assert all(fetched[s]["html"] == f"<p>{s}</p>" for s in sources)
    assert sorted(seen) == sorted(sources)  # each fetched exactly once
    serial = extract_cli.prefetch(sources, loader, jobs=1)
    assert set(serial) == set(sources)


def test_manifest_is_default_deny_loopback_only():
    from bigbang.core import policy

    mf = policy.load_manifest(ROOT / "bigbang" / "plugins" / "extract")
    assert mf["name"] == "extract"
    assert policy.check_permission(mf, "network", "http://localhost:8000/x")[0] is True
    assert policy.check_permission(mf, "network", "https://evil.example.com/x")[0] is (
        False
    )
    assert policy.check_permission(mf, "fs_write", ".scout/extract.db")[0] is True
    # secrets stay default-deny: the allowlist is empty, so nothing is readable
    assert policy.check_permission(mf, "secret", "GITHUB_TOKEN")[0] is False


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.extract import cli as extract_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = extract_cli._capability()
    assert cap["adapter"] == "extract"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "postlight-parser"
    assert cap["extras"]["readable"]["found"] is False
    assert cap["extras"]["trafilatura"]["found"] is False  # surfaced, never run


# ---- the real CLI in a subprocess (offline paths only) ----------------------


def _cli(args, cwd=None, env=None, stdin=None):
    import os

    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        cwd=str(cwd or ROOT),
        env=e,
        input=stdin,
    )


def _page(tmp_path: Path, name: str = "a.html", html: str = ARTICLE) -> Path:
    p = tmp_path / name
    p.write_text(html, encoding="utf-8")
    return p


def test_cli_extract_hello_envelope():
    r = _cli(["--json", "extract", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_read_file_emits_the_article_record(tmp_path):
    page = _page(tmp_path)
    r = _cli(["--json", "extract", "read", str(page)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["title"] == "The Ratchet Problem"
    assert data["byline"] == "Cameron Davis"
    assert data["date"] == "2026-03-05"
    assert data["word_count"] > 40
    assert P1 in data["text"]
    assert "Subscribe to our newsletter" not in data["text"]
    assert data["summary"]["total"] == len(data["diagnostics"])


def test_cli_read_text_mode_is_plain_stdout(tmp_path):
    page = _page(tmp_path)
    r = _cli(["extract", "read", str(page), "--text"])
    assert r.returncode == 0, r.stderr + r.stdout
    assert r.stdout.startswith(P1)
    assert "{" not in r.stdout.split("\n")[0]  # no envelope, no rich frame
    assert "Archive" not in r.stdout


def test_cli_read_from_stdin(tmp_path):
    r = _cli(["--json", "extract", "read", "-"], stdin=ARTICLE)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["source"] == "-" and data["url"] is None
    assert P1 in data["text"]


def test_cli_read_missing_file_fails_actionably(tmp_path):
    r = _cli(["--json", "extract", "read", str(tmp_path / "nope.html")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no such file" in data["error"]
    assert "example" in data


def test_cli_read_url_is_policy_gated_before_any_socket(tmp_path):
    # BIGBANG_POLICY_FILE -> a fresh tmp file: the default user allowlist is
    # loopback-only and this plugin's manifest is too, so an off-fleet host is
    # DENIED before urllib is ever called.
    r = _cli(
        ["--json", "extract", "read", "https://not-allowed.example.com/post"],
        env={"BIGBANG_POLICY_FILE": str(tmp_path / "policy.yaml")},
    )
    assert r.returncode == 1
    assert "denied" in (r.stdout + r.stderr).lower()


def test_cli_read_fail_on_gates_an_empty_extraction(tmp_path):
    page = _page(tmp_path, "empty.html", "<html><body><nav>Home</nav></body></html>")
    r = _cli(["--json", "extract", "read", str(page), "--fail-on", "error"])
    assert r.returncode == 1  # extract:no-content is an error
    data = json.loads(r.stdout)["data"]
    assert data["word_count"] == 0
    assert any(d["rule"] == "extract:no-content" for d in data["diagnostics"])
    # ...and without the gate the same read is a success
    r2 = _cli(["--json", "extract", "read", str(page)])
    assert r2.returncode == 0


def test_cli_read_rejects_a_bogus_fail_on(tmp_path):
    page = _page(tmp_path)
    r = _cli(["--json", "extract", "read", str(page), "--fail-on", "loud"])
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]


def test_cli_batch_ingests_a_directory_then_serves_the_cache(tmp_path):
    _page(tmp_path, "a.html")
    _page(
        tmp_path,
        "b.html",
        f"<html><head><title>Second Piece Of Writing</title></head><body>"
        f"<div class=content><p>{P2}</p><p>{P1}</p></div></body></html>",
    )
    _page(tmp_path, "dup.html")  # byte-identical to a.html
    db = tmp_path / "corpus.db"
    r = _cli(
        [
            "--json",
            "extract",
            "batch",
            "--glob",
            "*.html",
            "--root",
            str(tmp_path),
            "--db",
            str(db),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["sources"] == 3
    assert data["extracted"] == 2 and data["cached"] == 1  # dup.html hit the cache
    assert data["failed"] == 0
    assert all("text" not in row for row in data["results"])  # bodies stay out
    r2 = _cli(
        [
            "--json",
            "extract",
            "batch",
            "--glob",
            "*.html",
            "--root",
            str(tmp_path),
            "--db",
            str(db),
        ]
    )
    second = json.loads(r2.stdout)["data"]
    assert second["cached"] == 3 and second["extracted"] == 0
    r3 = _cli(["--json", "extract", "corpus", "--db", str(db)])
    corpus = json.loads(r3.stdout)["data"]
    assert corpus["stats"]["documents"] == 2  # deduped by content hash
    assert corpus["stats"]["words"] > 0
    titles = {d["title"] for d in corpus["documents"]}
    assert titles == {"The Ratchet Problem", "Second Piece Of Writing"}


def test_cli_batch_list_file_and_failures(tmp_path):
    good = _page(tmp_path)
    listing = tmp_path / "sources.txt"
    listing.write_text(
        f"# research queue\n{good}\n\n{tmp_path / 'ghost.html'}\n", encoding="utf-8"
    )
    r = _cli(
        [
            "--json",
            "extract",
            "batch",
            "--list",
            str(listing),
            "--db",
            str(tmp_path / "c.db"),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["sources"] == 2  # the comment and the blank line are not sources
    assert data["extracted"] == 1 and data["failed"] == 1
    assert "no such file" in data["failures"][0]["error"]


def test_cli_batch_without_sources_fails_actionably(tmp_path):
    r = _cli(["--json", "extract", "batch", "--db", str(tmp_path / "c.db")])
    assert r.returncode == 1
    assert "no sources" in json.loads(r.stdout)["error"]


def test_cli_batch_no_record_writes_nothing(tmp_path):
    _page(tmp_path)
    db = tmp_path / "corpus.db"
    r = _cli(
        [
            "--json",
            "extract",
            "batch",
            "--glob",
            "*.html",
            "--root",
            str(tmp_path),
            "--db",
            str(db),
            "--no-record",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] is False and data["db"] is None
    assert data["extracted"] == 1
    assert not db.exists()  # dry-run touches no file


def test_cli_corpus_without_ledger_fails_actionably(tmp_path):
    r = _cli(["--json", "extract", "corpus", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no corpus ledger" in data["error"]
    assert "example" in data


def test_cli_corpus_by_id_returns_the_stored_text(tmp_path):
    _page(tmp_path)
    db = tmp_path / "corpus.db"
    _cli(["--json", "extract", "batch", str(tmp_path / "a.html"), "--db", str(db)])
    r = _cli(["extract", "corpus", "--db", str(db), "--id", "1", "--text"])
    assert r.returncode == 0, r.stderr + r.stdout
    assert P1 in r.stdout and P2 in r.stdout
    missing = _cli(["--json", "extract", "corpus", "--db", str(db), "--id", "99"])
    assert missing.returncode == 1
    assert "no document with id 99" in json.loads(missing.stdout)["error"]


def test_cli_plugin_is_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "extract" in list_plugin_names()
