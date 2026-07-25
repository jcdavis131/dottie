"""Feeds — openswap #12 (Feedly Pro -> stdlib xml.etree RSS/Atom reader with
conditional GET, sqlite dedupe + keyword scoring, digest emitter). Pure-logic
core tests + the conditional-GET state machine + capability detection + the
subprocess envelope. Offline and deterministic by construction: the fetch
boundary is an injected fake returning canned {status, body, etag,
last_modified, error} dicts, every `ts`/`now` is explicit, and no test opens a
socket."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import feeds, openswap
from bigbang.core.policy import check_permission, load_manifest

ROOT = Path(__file__).resolve().parents[1]

# a fixed clock so published/first-seen ordering is exact
T0 = 1_780_000_000.0
HOUR = 3600.0

RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>arXiv cs.LG</title>
    <link>https://arxiv.org/list/cs.LG/recent</link>
    <item>
      <title>Muon optimizer scaling laws</title>
      <link>https://arxiv.org/abs/2607.00001</link>
      <guid isPermaLink="false">oai:arXiv.org:2607.00001v1</guid>
      <description>&lt;p&gt;We study &lt;b&gt;curriculum learning&lt;/b&gt; for pretraining.&lt;/p&gt;</description>
      <pubDate>Mon, 20 Jul 2026 10:00:00 GMT</pubDate>
      <dc:creator>A. Researcher</dc:creator>
      <category>cs.LG</category>
    </item>
    <item>
      <title>A tokenizer note</title>
      <link>https://arxiv.org/abs/2607.00002</link>
      <description>Nothing about optimizers here.</description>
      <pubDate>Sun, 19 Jul 2026 09:30:00 GMT</pubDate>
      <content:encoded>&lt;p&gt;Long form body.&lt;/p&gt;</content:encoded>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Simon Willison</title>
  <link rel="self" href="https://simonwillison.net/atom/everything/"/>
  <link rel="alternate" href="https://simonwillison.net/"/>
  <entry>
    <id>tag:simonwillison.net,2026:/blog/1</id>
    <title>Quantization in practice</title>
    <link rel="replies" href="https://example.com/replies/1"/>
    <link rel="alternate" href="https://simonwillison.net/2026/Jul/18/quant/"/>
    <published>2026-07-18T12:00:00Z</published>
    <updated>2026-07-19T12:00:00Z</updated>
    <summary type="html">Notes on &lt;i&gt;quantization&lt;/i&gt; for local models.</summary>
    <author><name>Simon</name></author>
    <category term="llms"/>
  </entry>
</feed>
"""

RSS1 = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://old.example.com/">
    <title>Old School</title>
    <link>https://old.example.com/</link>
  </channel>
  <item rdf:about="https://old.example.com/a">
    <title>RDF era post</title>
    <link>https://old.example.com/a</link>
    <description>perplexity numbers</description>
    <dc:date>2026-07-17T08:00:00+00:00</dc:date>
  </item>
</rdf:RDF>
"""


def _resp(status=200, body=RSS2, etag=None, last_modified=None, error=None):
    return {
        "status": status,
        "body": body,
        "etag": etag,
        "last_modified": last_modified,
        "error": error,
    }


class _Boundary:
    """Fetch fake: records (url, headers) and replays canned responses in order.

    This is the ONLY seam that would touch the network in production; recording
    the headers is what lets the conditional-GET tests assert on real behavior
    (that the stored validators were actually sent) instead of on a mock.
    """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError(f"unexpected extra fetch of {url}")
        return self.responses.pop(0)


def _store():
    return feeds.open_store(":memory:")


def _registered(*, url="https://rss.arxiv.org/rss/cs.LG", name="arxiv-cs-lg"):
    conn = _store()
    feeds.add_feed(conn, name, url, ts=T0)
    return conn


# ---- the namespace shim -----------------------------------------------------


def test_local_strips_any_namespace_and_lowercases():
    assert feeds.local("{http://www.w3.org/2005/Atom}entry") == "entry"
    assert feeds.local("{http://purl.org/dc/elements/1.1/}date") == "date"
    assert feeds.local("pubDate") == "pubdate"  # RSS casing folded
    assert feeds.local(None) == ""


# ---- the parser: three formats, one shape -----------------------------------


def test_parse_rss2_normalizes_entries():
    parsed = feeds.parse_feed(RSS2)
    assert parsed["format"] == feeds.FORMAT_RSS
    assert parsed["title"] == "arXiv cs.LG"
    first = parsed["entries"][0]
    assert first["guid"] == "oai:arXiv.org:2607.00001v1"
    assert first["link"] == "https://arxiv.org/abs/2607.00001"
    # description HTML is stripped to text, entities decoded, one line
    assert first["summary"] == "We study curriculum learning for pretraining."
    assert first["author"] == "A. Researcher"  # dc:creator via the shim
    assert first["tags"] == ["cs.LG"]
    assert first["published_ts"] == feeds.parse_entry_time("Mon, 20 Jul 2026 10:00:00 GMT")
    # second item has no guid at all — link becomes the identity
    assert parsed["entries"][1]["guid"] is None
    assert parsed["entries"][1]["link"] == "https://arxiv.org/abs/2607.00002"


def test_parse_atom_prefers_alternate_link_and_published():
    parsed = feeds.parse_feed(ATOM)
    assert parsed["format"] == feeds.FORMAT_ATOM
    entry = parsed["entries"][0]
    assert entry["guid"] == "tag:simonwillison.net,2026:/blog/1"
    # rel="replies" comes FIRST in the document; alternate must still win
    assert entry["link"] == "https://simonwillison.net/2026/Jul/18/quant/"
    # published beats updated (the original date, not the last edit)
    assert entry["published_ts"] == feeds.parse_entry_time("2026-07-18T12:00:00Z")
    assert entry["summary"] == "Notes on quantization for local models."
    assert entry["author"] == "Simon"
    assert entry["tags"] == ["llms"]  # @term, not element text


def test_parse_rss1_rdf_items_are_siblings_of_channel():
    parsed = feeds.parse_feed(RSS1)
    assert parsed["format"] == feeds.FORMAT_RSS1
    assert parsed["title"] == "Old School"
    assert len(parsed["entries"]) == 1  # found outside <channel>, not duplicated
    assert parsed["entries"][0]["title"] == "RDF era post"
    assert parsed["entries"][0]["published_ts"] == feeds.parse_entry_time(
        "2026-07-17T08:00:00+00:00"
    )


def test_parse_honors_encoding_declaration_on_bytes():
    doc = (
        '<?xml version="1.0" encoding="ISO-8859-1"?><rss version="2.0"><channel>'
        "<title>caf\xe9 feed</title><item><title>na\xefve</title>"
        "<link>https://x.example/1</link></item></channel></rss>"
    ).encode("iso-8859-1")
    parsed = feeds.parse_feed(doc)
    assert parsed["title"] == "café feed"
    assert parsed["entries"][0]["title"] == "naïve"


def test_parse_rejects_junk_and_non_feeds():
    for bad in ("", "   ", "not xml at all", "<html><body>hi</body></html>",
                "<rss><channel><title>unclosed"):
        with pytest.raises(feeds.FeedError):
            feeds.parse_feed(bad)


def test_parse_refuses_doctype_entity_bomb():
    bomb = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        "<rss version=\"2.0\"><channel><title>&b;</title></channel></rss>"
    )
    with pytest.raises(feeds.FeedError) as e:
        feeds.parse_feed(bomb)
    assert "DOCTYPE" in str(e.value)


# ---- timestamps -------------------------------------------------------------


def test_parse_entry_time_rfc822_and_iso():
    import calendar

    rfc = feeds.parse_entry_time("Mon, 20 Jul 2026 10:00:00 GMT")
    assert rfc == float(calendar.timegm((2026, 7, 20, 10, 0, 0, 0, 0, 0)))
    # Atom 'Z' form (fromisoformat only learned Z in 3.11 — we normalize)
    assert feeds.parse_entry_time("2026-07-20T10:00:00Z") == rfc
    assert feeds.parse_entry_time("2026-07-20T12:00:00+02:00") == rfc
    # a naive timestamp is UTC by fiat, not local time
    assert feeds.parse_entry_time("2026-07-20T10:00:00") == rfc
    # offsets are honored, not dropped
    assert feeds.parse_entry_time("Mon, 20 Jul 2026 12:00:00 +0200") == rfc


def test_parse_entry_time_rejects_junk():
    for bad in (None, "", "   ", "not a date", "20 Julio 2026", 12345, "2026-13-45"):
        assert feeds.parse_entry_time(bad) is None


def test_fmt_ts_is_utc_and_total():
    assert feeds.fmt_ts(0) == "1970-01-01 00:00 UTC"
    assert feeds.fmt_ts(None) == ""
    assert feeds.fmt_ts("garbage") == ""


# ---- html stripping ---------------------------------------------------------


def test_strip_html_collapses_and_caps():
    assert feeds.strip_html("<p>a  <b>b</b>\n c</p>") == "a b c"
    assert feeds.strip_html("&amp;lt;tag&amp;gt;") == "&lt;tag&gt;"  # one decode, not two
    long = feeds.strip_html("x" * 50, cap=10)
    assert long == "x" * 10 + "…"
    assert feeds.strip_html(None) == "" and feeds.strip_html("") == ""


# ---- dedupe identity --------------------------------------------------------


def test_entry_key_prefers_id_then_link_then_title_date():
    with_id = {"guid": "urn:1", "link": "https://a/1", "title": "t"}
    assert feeds.entry_key(with_id) == feeds.entry_key({"guid": "urn:1"})
    # a moved link keeps the identity as long as the id is stable
    assert feeds.entry_key({"guid": "urn:1", "link": "https://moved/1"}) == feeds.entry_key(
        with_id
    )
    link_only = {"guid": None, "link": "https://a/1", "title": "t"}
    assert feeds.entry_key(link_only) != feeds.entry_key(with_id)
    assert feeds.entry_key(link_only) == feeds.entry_key({"link": "https://a/1"})
    # no id and no link: title+date is the last resort, and it is stable
    bare = {"title": "same", "published_ts": 1.0}
    assert feeds.entry_key(bare) == feeds.entry_key(dict(bare))
    assert feeds.entry_key(bare) != feeds.entry_key({"title": "same", "published_ts": 2.0})


# ---- keyword scoring --------------------------------------------------------


def test_score_entry_title_outweighs_body_and_counts_once():
    kw = {"muon": 3.0, "tokenizer": 1.0}
    title_hit = feeds.score_entry({"title": "Muon at scale", "summary": ""}, kw)
    body_hit = feeds.score_entry({"title": "Scaling", "summary": "muon muon muon"}, kw)
    assert title_hit["score"] == 6.0  # 3.0 * TITLE_WEIGHT
    assert body_hit["score"] == 3.0  # repetition does not stack
    both = feeds.score_entry({"title": "Muon", "summary": "muon"}, kw)
    assert both["score"] == 6.0  # best field only, never 6+3
    two = feeds.score_entry({"title": "Muon", "summary": "tokenizer notes"}, kw)
    assert two["score"] == 7.0 and two["matched"] == ["muon", "tokenizer"]


def test_score_entry_word_boundaries_phrases_and_tags():
    kw = {"muon": 3.0, "curriculum learning": 2.0}
    # substring hits must NOT count ("muonic" is not "muon")
    assert feeds.score_entry({"title": "muonic hydrogen", "summary": ""}, kw)["score"] == 0.0
    # a phrase matches across any whitespace run (feeds wrap where they like)
    wrapped = {"title": "", "summary": "on curriculum\n  learning schedules"}
    assert feeds.score_entry(wrapped, kw)["matched"] == ["curriculum learning"]
    # tags are body text too
    tagged = {"title": "", "summary": "", "tags": ["muon"]}
    assert feeds.score_entry(tagged, kw)["score"] == 3.0


def test_score_entry_is_optional():
    e = {"title": "Muon", "summary": "muon"}
    assert feeds.score_entry(e, {}) == {"score": 0.0, "matched": []}
    assert feeds.score_entry(e, None) == {"score": 0.0, "matched": []}


def test_load_keywords_overlay_and_validation(tmp_path):
    f = tmp_path / "kw.json"
    f.write_text(json.dumps({"muon": 9.0, "checkpoint": 0, "novel term": 1.5}), "utf-8")
    kw = feeds.load_keywords(str(f))
    assert kw["muon"] == 9.0  # replaced
    assert "checkpoint" not in kw  # 0 drops it
    assert kw["novel term"] == 1.5  # added
    assert kw["tokenizer"] == feeds.DEFAULT_KEYWORDS["tokenizer"]  # untouched
    assert feeds.load_keywords() == feeds.DEFAULT_KEYWORDS
    for bad in ('[1]', '{"muon": true}', '{"muon": "3"}', '{"muon": -1}', '{"": 2}'):
        f.write_text(bad, "utf-8")
        with pytest.raises(ValueError):
            feeds.load_keywords(str(f))


# ---- registry ---------------------------------------------------------------


def test_add_feed_idempotent_and_validated():
    conn = _store()
    first = feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    assert first["created"] is True
    again = feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    assert again["created"] is False and again["repointed"] is False
    assert len(feeds.list_feeds(conn)) == 1
    for name, url in (
        ("Bad Name", "https://a.example/f.xml"),
        ("ok", "ftp://a.example/f.xml"),
        ("ok", "not a url"),
    ):
        with pytest.raises(ValueError):
            feeds.add_feed(conn, name, url, ts=T0)


def test_repointing_a_feed_clears_stale_validators():
    conn = _registered()
    feeds.record_fetch(
        conn, "arxiv-cs-lg", ts=T0, status=200, etag='W/"old"',
        last_modified="Mon, 20 Jul 2026 10:00:00 GMT", replace_validators=True,
    )
    assert feeds.conditional_headers(feeds.get_feed(conn, "arxiv-cs-lg"))
    moved = feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.CL", ts=T0)
    assert moved["repointed"] is True and moved["previous_url"].endswith("cs.LG")
    # validators belonged to the OLD url — replaying them would invite a bogus 304
    assert feeds.conditional_headers(feeds.get_feed(conn, "arxiv-cs-lg")) == {}


def test_seed_feeds_registers_defaults_idempotently():
    conn = _store()
    assert all(r["created"] for r in feeds.seed_feeds(conn, ts=T0))
    assert len(feeds.list_feeds(conn)) == len(feeds.DEFAULT_FEEDS)
    assert not any(r["created"] for r in feeds.seed_feeds(conn, ts=T0))
    assert len(feeds.list_feeds(conn)) == len(feeds.DEFAULT_FEEDS)


def test_conditional_headers_from_stored_validators():
    assert feeds.conditional_headers(None) == {}
    assert feeds.conditional_headers({"etag": None, "last_modified": None}) == {}
    assert feeds.conditional_headers({"etag": 'W/"x"'}) == {"If-None-Match": 'W/"x"'}
    both = feeds.conditional_headers({"etag": "e", "last_modified": "Mon, 20 Jul 2026"})
    assert both == {"If-None-Match": "e", "If-Modified-Since": "Mon, 20 Jul 2026"}


# ---- dedupe in the store ----------------------------------------------------


def test_ingest_dedupes_across_polls_and_within_one_document():
    conn = _registered()
    entries = feeds.parse_feed(RSS2)["entries"]
    first = feeds.ingest(conn, "arxiv-cs-lg", entries, ts=T0)
    assert (first["new"], first["duplicate"]) == (2, 0)
    second = feeds.ingest(conn, "arxiv-cs-lg", entries, ts=T0 + HOUR)
    assert (second["new"], second["duplicate"]) == (0, 2)
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    # the same item twice inside ONE document collapses too
    dupes = feeds.ingest(conn, "other", entries + entries, ts=T0)
    assert (dupes["new"], dupes["duplicate"]) == (2, 2)


def test_ingest_scores_at_write_time_and_keeps_the_first_score():
    conn = _registered()
    entries = feeds.parse_feed(RSS2)["entries"]
    feeds.ingest(conn, "arxiv-cs-lg", entries, ts=T0, keywords={"muon": 3.0})
    scored = conn.execute(
        "SELECT title, score, matched FROM entries ORDER BY score DESC"
    ).fetchall()
    assert scored[0]["score"] == 6.0 and json.loads(scored[0]["matched"]) == ["muon"]
    assert scored[1]["score"] == 0.0
    # a duplicate is not re-scored: the digest already ranked the stored value
    feeds.ingest(conn, "arxiv-cs-lg", entries, ts=T0 + HOUR, keywords={"muon": 99.0})
    assert conn.execute("SELECT MAX(score) FROM entries").fetchone()[0] == 6.0


def test_entries_with_no_identity_collapse_to_one_row():
    conn = _registered()
    nameless = [{"guid": None, "link": None, "title": None, "published_ts": None}]
    assert feeds.ingest(conn, "arxiv-cs-lg", nameless, ts=T0)["new"] == 1
    assert feeds.ingest(conn, "arxiv-cs-lg", nameless, ts=T0 + HOUR)["new"] == 0


# ---- the conditional-GET state machine --------------------------------------


def test_run_fetch_200_then_304_costs_nothing_the_second_time():
    conn = _registered()
    boundary = _Boundary(
        _resp(200, RSS2, etag='W/"v1"', last_modified="Mon, 20 Jul 2026 10:00:00 GMT"),
        _resp(304, b""),
    )
    first = feeds.run_fetch(conn, boundary, ts=T0, keywords={"muon": 3.0})
    r0 = first["results"][0]
    assert r0["state"] == feeds.STATE_OK and r0["new"] == 2
    assert r0["conditional"] is False  # nothing stored yet on the first poll
    assert boundary.calls[0][1] == {}  # ...so no validators were sent

    second = feeds.run_fetch(conn, boundary, ts=T0 + HOUR)
    r1 = second["results"][0]
    # the stored validators were actually replayed
    assert boundary.calls[1][1] == {
        "If-None-Match": 'W/"v1"',
        "If-Modified-Since": "Mon, 20 Jul 2026 10:00:00 GMT",
    }
    assert r1["state"] == feeds.STATE_NOT_MODIFIED and r1["conditional"] is True
    assert r1["new"] == 0 and r1["duplicate"] == 0  # body never parsed
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    row = feeds.get_feed(conn, "arxiv-cs-lg")
    assert row["etag"] == 'W/"v1"'  # a 304 preserves what we know
    assert row["last_fetch_ts"] == T0 + HOUR and row["fetches"] == 2


def test_run_fetch_200_without_etag_clears_the_stale_validator():
    conn = _registered()
    boundary = _Boundary(
        _resp(200, RSS2, etag='W/"v1"'),
        _resp(200, RSS2, etag=None, last_modified=None),
        _resp(200, RSS2),
    )
    feeds.run_fetch(conn, boundary, ts=T0)
    feeds.run_fetch(conn, boundary, ts=T0 + HOUR)
    # keeping 'v1' here would make a CHANGING feed answer 304 forever
    assert feeds.get_feed(conn, "arxiv-cs-lg")["etag"] is None
    feeds.run_fetch(conn, boundary, ts=T0 + 2 * HOUR)
    assert boundary.calls[2][1] == {}  # nothing stale left to send


def test_run_fetch_304_with_a_refreshed_etag_stores_it():
    conn = _registered()
    boundary = _Boundary(
        _resp(200, RSS2, etag='W/"v1"'),
        _resp(304, b"", etag='W/"v2"'),
    )
    feeds.run_fetch(conn, boundary, ts=T0)
    feeds.run_fetch(conn, boundary, ts=T0 + HOUR)
    assert feeds.get_feed(conn, "arxiv-cs-lg")["etag"] == 'W/"v2"'


def test_run_fetch_records_transport_http_and_parse_failures():
    conn = _store()
    feeds.add_feed(conn, "down", "https://rss.arxiv.org/rss/a", ts=T0)
    feeds.add_feed(conn, "gone", "https://rss.arxiv.org/rss/b", ts=T0)
    feeds.add_feed(conn, "junk", "https://rss.arxiv.org/rss/c", ts=T0)
    boundary = _Boundary(
        _resp(None, b"", error="URLError: refused"),
        _resp(500, b"upstream on fire"),
        _resp(200, "<html>not a feed</html>"),
    )
    res = feeds.run_fetch(conn, boundary, ts=T0)
    by_feed = {r["feed"]: r for r in res["results"]}
    assert by_feed["down"]["state"] == feeds.STATE_ERROR
    assert "URLError" in by_feed["down"]["error"]
    assert by_feed["gone"]["error"] == "http 500"
    assert by_feed["junk"]["error"].startswith("unparseable:")
    assert res["by_state"] == {feeds.STATE_ERROR: 3}
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    # a failure must NOT poison the validators we already trust
    for name in ("down", "gone", "junk"):
        row = feeds.get_feed(conn, name)
        assert row["last_error"] and row["etag"] is None and row["fetches"] == 1


def test_run_fetch_denied_feed_is_never_fetched():
    conn = _store()
    feeds.add_feed(conn, "allowed", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    feeds.add_feed(conn, "sketchy", "https://not-allowed.example.com/feed.xml", ts=T0)
    boundary = _Boundary(_resp(200, RSS2))  # exactly ONE response is available

    def gate(url):
        return ("not-allowed" not in url, "test allowlist")

    res = feeds.run_fetch(conn, boundary, ts=T0, gate=gate)
    by_feed = {r["feed"]: r for r in res["results"]}
    assert by_feed["sketchy"]["state"] == feeds.STATE_DENIED
    assert by_feed["sketchy"]["error"].startswith("policy-denied:")
    # the boundary is the only thing that could reach the network: it saw one url
    assert [u for u, _ in boundary.calls] == ["https://rss.arxiv.org/rss/cs.LG"]
    # and the allowed feed still completed — one denial does not kill the poll
    assert by_feed["allowed"]["state"] == feeds.STATE_OK
    assert by_feed["allowed"]["new"] == 2


def test_run_fetch_name_filter_and_unknown_name():
    conn = _store()
    feeds.add_feed(conn, "a", "https://rss.arxiv.org/rss/a", ts=T0)
    feeds.add_feed(conn, "b", "https://rss.arxiv.org/rss/b", ts=T0)
    boundary = _Boundary(_resp(200, ATOM))
    res = feeds.run_fetch(conn, boundary, ts=T0, names=["b"])
    assert [r["feed"] for r in res["results"]] == ["b"]
    assert len(boundary.calls) == 1
    with pytest.raises(ValueError):
        feeds.run_fetch(conn, boundary, ts=T0, names=["nope"])


def test_to_diagnostics_normalizes_into_family_schema():
    results = [
        {"feed": "ok", "url": "https://a/1", "state": feeds.STATE_OK, "error": None},
        {"feed": "fresh", "url": "https://a/2", "state": feeds.STATE_NOT_MODIFIED,
         "error": None},
        {"feed": "dead", "url": "https://a/3", "state": feeds.STATE_ERROR,
         "error": "URLError: refused"},
        {"feed": "denied", "url": "https://a/4", "state": feeds.STATE_DENIED,
         "error": "policy-denied: nope"},
    ]
    diags = feeds.to_diagnostics(results)
    assert len(diags) == 2  # ok and not-modified emit nothing
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["feeds:error"]["severity"] == "error"
    assert by_rule["feeds:error"]["path"] == "https://a/3"
    assert by_rule["feeds:denied"]["severity"] == "warning"
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1
    assert summary["by_severity"]["warning"] == 1


# ---- the digest -------------------------------------------------------------


def _seeded_digest_store():
    """Three scored entries with known scores and dates (one across two feeds)."""
    conn = _store()
    feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    feeds.add_feed(conn, "simonwillison", "https://simonwillison.net/atom/everything/", ts=T0)
    kw = {"muon": 3.0, "quantization": 1.0, "curriculum learning": 2.0}
    feeds.ingest(conn, "arxiv-cs-lg", feeds.parse_feed(RSS2)["entries"], ts=T0, keywords=kw)
    feeds.ingest(conn, "simonwillison", feeds.parse_feed(ATOM)["entries"], ts=T0, keywords=kw)
    return conn


def test_digest_ranks_by_score_then_recency():
    conn = _seeded_digest_store()
    dg = feeds.digest(conn, now=T0, since=None)
    titles = [i["title"] for i in dg["items"]]
    # "Muon optimizer scaling laws" carries a title hit (6.0) + curriculum
    # learning in the body (2.0); quantization is a title hit worth 2.0; the
    # tokenizer note scores nothing and sinks to last on recency
    assert titles == [
        "Muon optimizer scaling laws",
        "Quantization in practice",
        "A tokenizer note",
    ]
    assert dg["items"][0]["score"] == 8.0
    assert dg["items"][0]["matched"] == ["curriculum learning", "muon"]
    assert dg["count"] == 3 and dg["feeds"] == ["arxiv-cs-lg", "simonwillison"]
    assert dg["items"][0]["tags"] == ["cs.LG"]  # JSON round-tripped back to a list


def test_digest_filters_by_score_feed_window_and_limit():
    conn = _seeded_digest_store()
    assert [i["score"] for i in feeds.digest(conn, min_score=2.0)["items"]] == [8.0, 2.0]
    assert feeds.digest(conn, feed="simonwillison")["feeds"] == ["simonwillison"]
    assert feeds.digest(conn, limit=1)["count"] == 1
    assert feeds.digest(conn, limit=0)["count"] == 3  # 0 = unlimited
    # window is on the publication date (falling back to first-seen)
    cutoff = feeds.parse_entry_time("2026-07-20T00:00:00Z")
    only_newest = feeds.digest(conn, since=cutoff)
    assert [i["title"] for i in only_newest["items"]] == ["Muon optimizer scaling laws"]


def test_digest_new_only_plus_mark_never_repeats():
    conn = _seeded_digest_store()
    first = feeds.digest(conn, new_only=True)
    assert first["count"] == 3
    assert feeds.mark_digested(conn, [i["id"] for i in first["items"]], ts=T0) == 3
    assert feeds.digest(conn, new_only=True)["count"] == 0
    assert feeds.digest(conn, new_only=False)["count"] == 3  # --all still sees them
    assert feeds.mark_digested(conn, [], ts=T0) == 0


def test_render_digest_is_deterministic_text():
    conn = _seeded_digest_store()
    dg = feeds.digest(conn, now=T0, min_score=2.0)
    text = feeds.render_digest(dg)
    assert feeds.render_digest(dg) == text  # pure function of the dict
    assert "feeds digest — 2 item(s) from 2 feed(s)" in text
    assert feeds.fmt_ts(T0) in text and "score >= 2.0" in text
    assert "[8.0] Muon optimizer scaling laws" in text
    assert "https://arxiv.org/abs/2607.00001" in text
    assert "curriculum learning, muon" in text
    assert "A tokenizer note" not in text  # filtered out, not merely unranked


def test_render_digest_says_so_when_empty():
    text = feeds.render_digest(feeds.digest(_store(), now=T0))
    assert "0 item(s)" in text and "no entries matched" in text


# ---- persistence ------------------------------------------------------------


def test_store_survives_reopen_and_is_its_own_file(tmp_path):
    db = tmp_path / ".scout" / "feeds.db"
    conn = feeds.open_store(db)
    feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    feeds.run_fetch(conn, _Boundary(_resp(200, RSS2, etag='W/"v1"')), ts=T0)
    conn.close()
    assert db.exists() and db.parent.name == ".scout"  # ledger placement convention
    reopened = feeds.open_store(db)  # idempotent schema, prior rows intact
    assert feeds.get_feed(reopened, "arxiv-cs-lg")["etag"] == 'W/"v1"'
    assert feeds.digest(reopened, now=T0)["count"] == 2
    tables = {
        r[0] for r in reopened.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"feeds", "entries", "meta"} <= tables
    # never the shared #2 monitoring ledger's tables — this is its own store
    assert "checks" not in tables and "incidents" not in tables


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.feeds import cli as feeds_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = feeds_cli._capability()
    assert cap["adapter"] == "feeds"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert "never executed" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "newsboat"
    assert cap["extras"]["rsstail"]["found"] is False


def test_manifest_is_default_deny_and_covers_the_seed_feeds():
    from urllib.parse import urlsplit

    manifest = load_manifest(ROOT / "bigbang" / "plugins" / "feeds")
    caps = manifest["capabilities"]
    assert caps["secrets"]["allow"] == []  # no secret axis at all
    assert caps["network"]["enabled"] is True and caps["network"]["domains"]
    for cfg in feeds.DEFAULT_FEEDS.values():
        assert check_permission(manifest, "network", cfg["url"])[0], cfg["url"]
    # everything else is denied, including a host that merely CONTAINS one
    for denied in (
        "https://not-allowed.example.com/feed.xml",
        "https://arxiv.org.evil.com/feed.xml",
        "https://evil.com/?u=huggingface.co",
    ):
        assert check_permission(manifest, "network", denied)[0] is False
    assert urlsplit(next(iter(feeds.DEFAULT_FEEDS.values()))["url"]).scheme == "https"


# ---- the real CLI in a subprocess (offline paths only) ----------------------


def _cli(args, cwd=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
        env=e,
    )


def _tmp_env(tmp_path):
    # a throwaway user policy file: the default allowlist is loopback-only, so
    # any off-fleet URL is denied without touching the developer's real policy
    return {"BIGBANG_POLICY_FILE": str(tmp_path / "policy.yaml")}


def test_cli_feeds_hello_envelope():
    r = _cli(["feeds", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_feeds_list_without_store_fails_actionably(tmp_path):
    r = _cli(["feeds", "list", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no feed store" in data["error"] and "example" in data


def test_cli_add_list_digest_round_trip_offline(tmp_path):
    db = tmp_path / "feeds.db"
    env = _tmp_env(tmp_path)
    seeded = _cli(["feeds", "add", "--seed", "--db", str(db)], env=env)
    assert seeded.returncode == 0, seeded.stderr + seeded.stdout
    added = json.loads(seeded.stdout)["data"]
    assert added["count"] == len(feeds.DEFAULT_FEEDS)
    # the seed feeds are manifest-allowlisted, so the poll would be allowed
    assert all(row["fetchable"] for row in added["added"])

    hand = _cli(
        ["feeds", "add", "sketchy", "--url", "https://not-allowed.example.com/f.xml",
         "--db", str(db)],
        env=env,
    )
    assert hand.returncode == 0, hand.stderr + hand.stdout
    row = json.loads(hand.stdout)["data"]["added"][0]
    # honest up front: neither allowlist covers it, so fetch will refuse it
    assert row["fetchable"] is False and "not in allowlist" in row["policy"]

    listed = _cli(["feeds", "list", "--db", str(db)], env=env)
    assert listed.returncode == 0, listed.stderr + listed.stdout
    data = json.loads(listed.stdout)["data"]
    assert data["count"] == len(feeds.DEFAULT_FEEDS) + 1
    assert data["conditional_ready"] == 0  # nothing polled yet
    assert {f["name"] for f in data["feeds"]} >= set(feeds.DEFAULT_FEEDS)

    dig = _cli(["feeds", "digest", "--db", str(db), "--format", "text"], env=env)
    assert dig.returncode == 0, dig.stderr + dig.stdout
    payload = json.loads(dig.stdout)["data"]
    assert payload["count"] == 0 and "no entries matched" in payload["text"]


def test_cli_add_rejects_bad_input(tmp_path):
    db = tmp_path / "feeds.db"
    env = _tmp_env(tmp_path)
    both = _cli(["feeds", "add", "x", "--url", "https://a/f.xml", "--seed",
                 "--db", str(db)], env=env)
    assert both.returncode == 1 and "not both" in json.loads(both.stdout)["error"]
    naked = _cli(["feeds", "add", "x", "--db", str(db)], env=env)
    assert naked.returncode == 1 and "--url" in json.loads(naked.stdout)["error"]
    bad = _cli(["feeds", "add", "UPPER", "--url", "https://a/f.xml", "--db", str(db)],
               env=env)
    assert bad.returncode == 1 and "feed name" in json.loads(bad.stdout)["error"]


def test_cli_fetch_denied_feed_records_instead_of_reaching_the_network(tmp_path):
    """The one CLI path that could open a socket, proven not to.

    The feed host is off both allowlists (BIGBANG_POLICY_FILE points at a fresh
    file, whose default is loopback-only), so the gate refuses it: the report
    row must say policy-denied — a real attempt would have recorded a DNS or TLS
    error string instead.
    """
    db = tmp_path / "feeds.db"
    env = _tmp_env(tmp_path)
    add = _cli(
        ["feeds", "add", "sketchy", "--url", "https://not-allowed.example.com/f.xml",
         "--db", str(db)],
        env=env,
    )
    assert add.returncode == 0, add.stderr + add.stdout
    r = _cli(["feeds", "fetch", "--db", str(db), "--fail-on", "error"], env=env)
    assert r.returncode == 0, r.stderr + r.stdout  # denial is a warning, not an error
    data = json.loads(r.stdout)["data"]
    assert data["by_state"] == {feeds.STATE_DENIED: 1}
    assert data["results"][0]["error"].startswith("policy-denied:")
    assert data["summary"]["by_severity"]["warning"] == 1
    assert data["new_entries"] == 0
    # and the same run gated at warning is the cron/CI failure
    gated = _cli(["feeds", "fetch", "--db", str(db), "--fail-on", "warning"], env=env)
    assert gated.returncode == 1


def test_cli_fetch_without_feeds_fails_actionably(tmp_path):
    db = tmp_path / "feeds.db"
    env = _tmp_env(tmp_path)
    # an empty-but-existing store: `fetch` must say "register a feed", not poll
    feeds.open_store(db).close()
    r = _cli(["feeds", "fetch", "--db", str(db)], env=env)
    assert r.returncode == 1
    assert "no feeds registered" in json.loads(r.stdout)["error"]


def test_cli_digest_writes_a_text_file(tmp_path):
    db = tmp_path / "feeds.db"
    out = tmp_path / "digest.txt"
    env = _tmp_env(tmp_path)
    conn = feeds.open_store(db)
    feeds.add_feed(conn, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    feeds.ingest(
        conn,
        "arxiv-cs-lg",
        feeds.parse_feed(RSS2)["entries"],
        ts=T0,
        keywords={"muon": 3.0},
    )
    conn.close()
    r = _cli(
        ["feeds", "digest", "--db", str(db), "--hours", "0", "--format", "text",
         "--out", str(out), "--mark"],
        env=env,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["count"] == 2 and data["marked"] == 2
    assert data["out"] == str(out)
    written = out.read_text(encoding="utf-8")
    assert written == data["text"]
    assert "Muon optimizer scaling laws" in written
    # marked entries are skipped by the next --new digest
    again = _cli(["feeds", "digest", "--db", str(db), "--hours", "0", "--new"], env=env)
    assert json.loads(again.stdout)["data"]["count"] == 0
