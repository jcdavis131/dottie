"""Later — openswap #34 (Pocket / Raindrop -> a local sqlite URL inbox with
canonical-url dedupe feeding the #11 extract corpus). Pure-logic core tests, the
order-independence property, the fetch state machine, the importers, and the
subprocess envelope.

Offline and deterministic by construction: the fetch boundary is an injected
fake that RECORDS the urls it was asked for (so "a denied url is never fetched"
is checked against behaviour, not a mock's promise), every `ts`/`now` is
explicit, and no test in this file opens a socket except one CLI case that
deliberately dials a closed loopback port to exercise the real error path.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import extract, feeds, later, openswap
from bigbang.core.policy import check_permission, load_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "bigbang" / "plugins" / "later"

# a fixed clock so save-order and staleness are exact
T0 = 1_780_000_000.0
HOUR = 3600.0
DAY = 86400.0

ARTICLE = (
    "<html lang='en'><head><title>Scaling laws revisited - The Site</title></head>"
    "<body><nav><a href='/'>home</a></nav><article><h1>Scaling laws revisited</h1>"
    "<p>Canonicalisation is the identity function of a read-later queue, and the"
    " whole dedupe question reduces to it rather than to the fetcher itself.</p>"
    "<p>Two spellings of one link collapse deterministically, whichever order"
    " they happen to arrive in, which is the property this suite pins down.</p>"
    "</article></body></html>"
)

POCKET_EXPORT = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Pocket Export</TITLE>
<H1>Unread</H1>
<DL><p>
  <DT><H3>Research</H3>
  <DL><p>
    <DT><A HREF="https://example.com/post?utm_source=newsletter" ADD_DATE="1780000000"
        TAGS="ai,scaling">Scaling laws revisited - The Site</A>
    <DD>read the appendix
    <DT><A HREF="https://EXAMPLE.com/post" ADD_DATE="1780000500">Scaling laws</A>
  </DL><p>
  <DT><H3>Tools</H3>
  <DL><p>
    <DT><A HREF="https://other.example/x/../y" TAGS="cli">Other thing</A>
  </DL><p>
  <DT><A>no href at all</A>
  <DT><A HREF="mailto:nope@example.com">an email</A>
</DL><p>
"""

RAINDROP_CSV = (
    "id,title,note,excerpt,url,folder,tags,created\n"
    '1,"Scaling laws","why","",https://example.com/post?utm_campaign=x,Research,"ai, scaling",'
    "2026-07-01T09:00:00Z\n"
    '2,"Bare","","",https://other.example/y,Tools,cli,1780000000\n'
    '3,"Broken","","",not-a-url,Tools,,\n'
)


class _Boundary:
    """Fetch fake: records every url it is asked for, replays canned responses.

    Recording the calls is the point — it is what lets "a policy-denied url is
    NEVER fetched" be an assertion about behaviour instead of a comment.
    """

    def __init__(self, responses: dict[str, dict] | None = None, default: dict | None = None):
        self.responses = dict(responses or {})
        self.default = default
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected fetch of {url}")


def _resp(status=200, html=ARTICLE, url=None, error=None) -> dict:
    return {"status": status, "html": html, "url": url, "error": error}


def _ingest(words=96, doc_id=7, title="Scaling laws revisited", error=None):
    """A fake #11 hand-off. The real one is _make_ingest in the plugin CLI."""

    def ingest(html: str, url: str, item: dict) -> dict:
        if error is not None:
            return {"error": error}
        return {"doc_id": doc_id, "words": words, "title": title}

    return ingest


def _store():
    return later.open_store(":memory:")


def _queued(urls, *, ts=T0, **kw):
    conn = _store()
    later.add_offers(conn, list(urls), ts=ts, **kw)
    return conn


# ---- canonicalisation: the identity function ---------------------------------


def test_canonicalise_lowercases_host_strips_default_port_and_root_dot():
    r = later.canonicalise("HTTPS://Example.COM.:443/Path")
    assert r["url"] == "https://example.com/Path"  # path case is NOT touched
    assert r["applied"] == ["lowercase-host", "strip-root-dot", "strip-default-port"]
    assert r["error"] is None
    # a non-default port survives, and nothing is reported as applied
    keep = later.canonicalise("https://example.com:8443/Path")
    assert keep["url"] == "https://example.com:8443/Path"
    assert keep["applied"] == []


def test_canonicalise_supplies_the_root_path_for_a_bare_origin():
    assert later.canonicalise("http://example.com")["url"] == "http://example.com/"
    assert later.canonicalise("http://example.com/")["url"] == "http://example.com/"


def test_every_reading_has_a_url_or_an_error_never_both_never_neither():
    corpus = [
        "https://example.com/a",
        "http://example.com:80",
        "https://[::1]:8080/x",
        "",
        "   ",
        None,
        "example.com/x",
        "mailto:a@b.c",
        "javascript:alert(1)",
        "#top",
        "https://",
        "https://[::1/x",
        "http://x.example/a b",
    ]
    seen_ok = seen_bad = 0
    for raw in corpus:
        r = later.canonicalise(raw)
        assert (r["url"] is None) != (r["error"] is None), r
        assert (r["key"] is None) == (r["url"] is None), r
        if r["url"] is None:
            assert r["error"].strip()
            seen_bad += 1
        else:
            assert r["key"] == later.url_key(r["url"])
            seen_ok += 1
    assert (seen_ok, seen_bad) == (3, 10)  # the corpus really covers both sides


def test_canonicalise_drops_tracking_params_and_names_every_one():
    r = later.canonicalise(
        "https://x.example/p?utm_source=nl&utm_medium=email&fbclid=abc&id=42&pk_campaign=q"
    )
    assert r["url"] == "https://x.example/p?id=42"
    assert r["dropped_params"] == ["fbclid", "pk_campaign", "utm_medium", "utm_source"]
    assert "drop-tracking-params" in r["applied"]
    # content parameters must survive untouched
    assert later.canonicalise("https://x.example/p?id=42")["url"] == "https://x.example/p?id=42"


def test_canonicalise_sorts_the_query_so_parameter_order_cannot_split_one_url():
    a = later.canonicalise("https://x.example/p?b=2&a=1")
    b = later.canonicalise("https://x.example/p?a=1&b=2")
    assert a["url"] == b["url"] == "https://x.example/p?a=1&b=2"
    assert "sort-query" in a["applied"] and "sort-query" not in b["applied"]
    # different VALUES are a different resource and must not collapse
    assert later.canonicalise("https://x.example/p?a=1&b=3")["key"] != a["key"]
    # ...and turning the rule off keeps the spellings apart
    unsorted = later.canonicalise("https://x.example/p?b=2&a=1", policy={"sort_query": False})
    assert unsorted["url"] == "https://x.example/p?b=2&a=1"
    assert unsorted["key"] != b["key"]


def test_canonicalise_is_idempotent():
    for raw in [
        "https://Example.COM:443/a/./b/../c?utm_source=nl&b=2&a=1#frag",
        "http://example.com",
        "https://x.example/a/",
        "https://[::1]:8080/x",
        "https://x.example/%7Euser/p%2fx",
    ]:
        once = later.canonicalise(raw)["url"]
        twice = later.canonicalise(once)
        assert twice["url"] == once
        assert twice["applied"] == []  # a canonical url has nothing left to change


def test_resolve_dot_segments_never_escapes_the_root():
    cases = {
        "/a/./b/../c": "/a/c",
        "/a/b/../": "/a/",
        "/a/..": "/",
        "/../x": "/x",
        "/a/../../b": "/b",
        "/a/b/.": "/a/b/",
        "/": "/",
        "/a//b": "/a//b",
    }
    for raw, want in cases.items():
        assert later.resolve_dot_segments(raw) == want, raw
    r = later.canonicalise("https://x.example/a/./b/../c")
    assert r["url"] == "https://x.example/a/c"
    assert "resolve-dot-segments" in r["applied"]


def test_normalize_percent_decodes_only_unreserved_and_uppercases_the_rest():
    assert later.normalize_percent("%7Euser") == "~user"
    assert later.normalize_percent("%2f") == "%2F"  # a slash stays escaped
    assert later.normalize_percent("%26") == "%26"  # never becomes a new & separator
    assert later.normalize_percent("100%") == "100%"  # a stray percent is left alone
    r = later.canonicalise("https://x.example/%7Euser/a%2fb?q=%2D")
    assert r["url"] == "https://x.example/~user/a%2Fb?q=-"
    assert "normalize-percent-encoding" in r["applied"]


def test_canonicalise_refuses_to_guess_a_missing_scheme():
    r = later.canonicalise("example.com/post")
    assert r["url"] is None
    assert "missing scheme is not guessed" in r["error"]


def test_canonicalise_drops_the_fragment_but_records_it():
    dropped = later.canonicalise("https://x.example/p#section-3")
    assert dropped["url"] == "https://x.example/p"
    assert dropped["fragment"] == "section-3"
    assert "drop-fragment" in dropped["applied"]
    kept = later.canonicalise("https://x.example/p#section-3", policy={"drop_fragment": False})
    assert kept["url"] == "https://x.example/p#section-3"
    assert kept["key"] != dropped["key"]


def test_canonicalise_drops_credentials_out_of_a_saved_link():
    r = later.canonicalise("https://user:secret@x.example/p")
    assert r["url"] == "https://x.example/p"
    assert "secret" not in r["url"] and "drop-userinfo" in r["applied"]
    kept = later.canonicalise("https://user:secret@x.example/p", policy={"drop_userinfo": False})
    assert kept["url"] == "https://user:secret@x.example/p"


def test_www_and_trailing_slash_are_opt_in_because_they_change_the_resource():
    plain = later.canonicalise("https://www.x.example/p/")
    assert plain["url"] == "https://www.x.example/p/"
    assert plain["key"] != later.canonicalise("https://x.example/p")["key"]
    pol = later.validate_policy({"strip_www": True, "strip_trailing_slash": True})
    collapsed = later.canonicalise("https://www.x.example/p/", policy=pol)
    assert collapsed["url"] == "https://x.example/p"
    assert collapsed["applied"] == ["strip-www", "strip-trailing-slash"]
    assert collapsed["key"] == later.canonicalise("https://x.example/p")["key"]
    # the root path is never stripped away to nothing
    assert later.canonicalise("https://x.example/", policy=pol)["url"] == "https://x.example/"


def test_split_authority_handles_userinfo_ipv6_and_junk():
    assert later.split_authority("example.com") == ("", "example.com", "")
    assert later.split_authority("example.com:8080") == ("", "example.com", "8080")
    assert later.split_authority("u:p@example.com:80") == ("u:p", "example.com", "80")
    assert later.split_authority("[::1]:8080") == ("", "[::1]", "8080")
    assert later.split_authority("[::1]") == ("", "[::1]", "")
    # ":" that is not a port must not be shredded into a bogus host
    assert later.split_authority("example.com:notaport") == ("", "example.com:notaport", "")


def test_is_tracking_param_covers_the_prefix_families():
    for name in ("utm_source", "UTM_Campaign", "pk_kwd", "mtm_source", "hsa_grp", "fbclid", "mc_eid"):
        assert later.is_tracking_param(name), name
    for name in ("id", "page", "q", "utm", "ref", ""):
        assert not later.is_tracking_param(name), name
    assert later.is_tracking_param("ref", ("ref",))  # extras extend, never replace


def test_url_key_is_the_sha256_of_the_canonical_url():
    url = "https://x.example/p?a=1"
    expected = hashlib.sha256(url.encode("utf-8")).hexdigest()
    assert later.url_key(url) == expected
    assert later.canonicalise("https://X.example/p?a=1&utm_source=q")["key"] == expected


# ---- policy as config --------------------------------------------------------


def test_validate_policy_rejects_typos_and_non_boolean_flags():
    with pytest.raises(ValueError, match="unknown policy key"):
        later.validate_policy({"strip_wwww": True})
    with pytest.raises(ValueError, match="must be true or false"):
        later.validate_policy({"strip_www": "yes"})
    with pytest.raises(ValueError, match="list of parameter names"):
        later.validate_policy({"extra_tracking_params": "ref"})
    with pytest.raises(ValueError, match="JSON object"):
        later.validate_policy(["strip_www"])
    merged = later.validate_policy({"extra_tracking_params": ["Ref", " src "]})
    assert merged["extra_tracking_params"] == ["ref", "src"]
    assert merged["drop_fragment"] is True  # defaults survive an overlay


def test_default_policy_is_not_mutated_by_an_overlay():
    later.validate_policy({"extra_tracking_params": ["ref"]})
    assert later.DEFAULT_POLICY["extra_tracking_params"] == []


def test_load_policy_reads_an_overlay_file(tmp_path):
    f = tmp_path / "pol.json"
    f.write_text('{"strip_www": true, "extra_tracking_params": ["ref"]}', encoding="utf-8")
    pol = later.load_policy(f)
    assert pol["strip_www"] is True
    r = later.canonicalise("https://www.x.example/p?ref=hn", policy=pol)
    assert r["url"] == "https://x.example/p"
    assert r["dropped_params"] == ["ref"]
    assert later.load_policy(None) == later.validate_policy(None)


# ---- the order-independent merge --------------------------------------------


def test_merge_text_is_commutative_and_keeps_the_more_informative_title():
    long, short = "Scaling laws revisited - The Site", "Scaling laws"
    assert later.merge_text(short, long) == long
    assert later.merge_text(long, short) == long  # commutative: same answer both ways
    assert later.merge_text(None, short) == short
    assert later.merge_text("", None) is None
    # equal lengths take the lexicographic LAST: arbitrary, but a total order,
    # which is what makes the fold independent of arrival order
    assert later.merge_text("bb", "aa") == later.merge_text("aa", "bb") == "bb"
    assert later.merge_text("  spaced   out ", None) == "spaced out"


def test_merge_sources_is_a_union_and_merge_ts_is_the_earliest():
    assert later.merge_sources("bookmarks", "manual") == "bookmarks,manual"
    assert later.merge_sources("manual", "bookmarks") == "bookmarks,manual"
    assert later.merge_sources("a,b", "b") == "a,b"
    assert later.merge_sources(None, None) == later.DEFAULT_SOURCE
    assert later.merge_ts(T0, T0 - HOUR) == T0 - HOUR
    assert later.merge_ts(T0 - HOUR, T0) == T0 - HOUR
    assert later.merge_ts(None, T0) == T0
    assert later.merge_ts(None, None) is None


def test_normalize_tags_sorts_lowercases_and_deduplicates():
    assert later.normalize_tags("AI, scaling, ai ,") == ["ai", "scaling"]
    assert later.normalize_tags(["Zeta", "alpha", "ALPHA"]) == ["alpha", "zeta"]
    assert later.normalize_tags(None) == []
    assert later.normalize_tags("  ") == []


OFFERS = [
    {"url": "https://example.com/post?utm_source=x", "title": "Scaling laws", "tags": "ai",
     "source": "manual", "added_ts": T0},
    "https://EXAMPLE.com/post",
    {"url": "https://example.com/post#s2", "title": "Scaling laws revisited - The Site",
     "tags": ["scaling"], "source": "bookmarks", "added_ts": T0 - HOUR},
    "not a url at all",
    {"url": "https://other.example/y", "title": "Other"},
]


def test_merge_offers_collapses_spellings_into_one_row():
    merged = later.merge_offers(OFFERS, ts=T0)
    assert merged["offered"] == 5
    assert len(merged["items"]) == 2
    assert len(merged["invalid"]) == 1
    assert merged["collapsed"] == 2
    key = later.canonicalise("https://example.com/post")["key"]
    row = merged["items"][key]
    assert row["title"] == "Scaling laws revisited - The Site"  # the longer one won
    assert row["tags"] == ["ai", "scaling"]  # union, sorted
    assert row["source"] == "bookmarks,manual"
    assert row["added_ts"] == T0 - HOUR  # the earliest save time
    assert sorted(row["aliases"]) == [
        "https://EXAMPLE.com/post",
        "https://example.com/post#s2",
        "https://example.com/post?utm_source=x",
    ]


def test_merge_offers_accounting_adds_up():
    merged = later.merge_offers(OFFERS, ts=T0)
    assert merged["offered"] == len(merged["items"]) + len(merged["invalid"]) + merged["collapsed"]


def test_merge_offers_is_order_independent_over_every_permutation():
    shapes = set()
    for perm in itertools.permutations(OFFERS):
        merged = later.merge_offers(perm, ts=T0)
        shapes.add(json.dumps(merged["items"], sort_keys=True, default=str))
    assert len(shapes) == 1, "the merged rows must not depend on arrival order"
    # ...and the fold is not a constant: a different bag gives a different shape
    other = later.merge_offers([*OFFERS, "https://third.example/z"], ts=T0)
    assert json.dumps(other["items"], sort_keys=True, default=str) not in shapes


def test_merge_offers_records_whether_the_save_time_was_supplied():
    supplied = later.merge_offers([{"url": "https://x.example/a", "added_ts": T0 - DAY}], ts=T0)
    row = next(iter(supplied["items"].values()))
    assert (row["added_ts"], row["added_ts_source"]) == (T0 - DAY, "offer")
    unknown = later.merge_offers(["https://x.example/a"], ts=T0)
    row2 = next(iter(unknown["items"].values()))
    assert (row2["added_ts"], row2["added_ts_source"]) == (T0, "run-clock")


def test_merge_offers_counts_repeat_offers_of_the_same_spelling():
    merged = later.merge_offers(["https://x.example/a"] * 3, ts=T0)
    row = next(iter(merged["items"].values()))
    assert row["aliases"]["https://x.example/a"]["times"] == 3
    assert merged["collapsed"] == 2


def test_merge_offers_rejects_a_shape_that_is_not_an_offer():
    with pytest.raises(TypeError, match="url string or a dict"):
        later.merge_offers([42], ts=T0)


# ---- the store ---------------------------------------------------------------


def test_add_offers_dedupes_across_spellings_and_merges_metadata():
    conn = _store()
    result = later.add_offers(conn, OFFERS, ts=T0)
    assert result["counts"] == {
        "offered": 5, "added": 2, "duplicate": 0, "invalid": 1, "collapsed": 2
    }
    items = later.list_items(conn)
    assert [i["url"] for i in items] == ["https://example.com/post", "https://other.example/y"]
    assert items[0]["tags"] == ["ai", "scaling"]
    assert items[0]["aliases"] == 3  # three spellings, one row
    assert items[0]["state"] == later.STATE_UNREAD


def test_add_offers_reports_a_second_save_as_a_duplicate_and_unions_its_tags():
    conn = _queued([{"url": "https://example.com/post", "tags": "ai", "title": "Post"}])
    again = later.add_offers(
        conn, [{"url": "https://example.com/post?utm_source=q", "tags": "reread"}], ts=T0 + HOUR
    )
    assert again["counts"]["added"] == 0 and again["counts"]["duplicate"] == 1
    assert again["duplicate"][0]["reason"] == "canonical url already queued"
    assert again["duplicate"][0]["tags"] == ["ai", "reread"]
    only = later.list_items(conn)
    assert len(only) == 1
    # the tag from the FIRST save must survive the second — an overwrite here is
    # what silently loses the reason a link was filed (a mutation that replaced
    # the union with the new tags alone passed the earlier, weaker version of
    # this assertion, which queued the first copy with no tags at all)
    assert only[0]["tags"] == ["ai", "reread"]
    assert only[0]["title"] == "Post"
    assert only[0]["added_ts"] == T0  # the earlier save time is kept


def test_the_store_is_order_independent_over_every_permutation():
    digests = set()
    for perm in itertools.permutations(OFFERS):
        conn = _store()
        later.add_offers(conn, list(perm), ts=T0)
        digests.add(later.queue_fingerprint(conn)["digest"])
    assert len(digests) == 1, "insertion order must not change the queue"


def test_two_batches_leave_exactly_what_one_batch_would():
    one = _store()
    later.add_offers(one, OFFERS, ts=T0)
    two = _store()
    later.add_offers(two, OFFERS[:2], ts=T0)
    later.add_offers(two, OFFERS[2:], ts=T0)
    assert later.queue_fingerprint(two) == later.queue_fingerprint(one)


def test_a_repeated_spelling_keeps_its_earliest_sighting_across_batches():
    """The store-level alias merge, not just the in-batch one.

    A mutation that changed the sqlite upsert from MIN to MAX survived the first
    mutation pass because no test re-offered the SAME spelling in a later batch
    with a different clock — which is precisely when the two differ.
    """
    newest_first = _store()
    later.add_offers(newest_first, ["https://x.example/a"], ts=T0 + DAY)
    later.add_offers(newest_first, ["https://x.example/a"], ts=T0)
    oldest_first = _store()
    later.add_offers(oldest_first, ["https://x.example/a"], ts=T0)
    later.add_offers(oldest_first, ["https://x.example/a"], ts=T0 + DAY)
    for conn in (newest_first, oldest_first):
        rows = [dict(r) for r in conn.execute("SELECT raw, times, first_seen_ts FROM aliases")]
        assert rows == [{"raw": "https://x.example/a", "times": 2, "first_seen_ts": T0}]
        assert later.list_items(conn)[0]["added_ts"] == T0
    assert later.queue_fingerprint(oldest_first) == later.queue_fingerprint(newest_first)


def test_the_fingerprint_excludes_the_id_because_the_id_is_insertion_order():
    """The stated reason queue_fingerprint drops the id, made falsifiable.

    Inside one batch rows are inserted in canonical-KEY order, so ids only
    diverge when the same offers arrive as different BATCHES. key(c.example/3)
    sorts after key(b.example/2), so one batch numbers b first and two batches
    number c first — the ids really differ while the queue does not.
    """
    early, late = "https://c.example/3", "https://b.example/2"
    assert later.url_key(early) > later.url_key(late), "the fixture's premise"
    one = _store()
    later.add_offers(one, [early, late], ts=T0)
    two = _store()
    later.add_offers(two, [early], ts=T0)
    later.add_offers(two, [late], ts=T0)
    ids_one = {i["url"]: i["id"] for i in later.list_items(one)}
    ids_two = {i["url"]: i["id"] for i in later.list_items(two)}
    assert ids_one == {early: 2, late: 1} and ids_two == {early: 1, late: 2}
    assert later.queue_fingerprint(two) == later.queue_fingerprint(one)


def test_the_fingerprint_moves_when_the_queue_really_changes():
    conn = _queued(["https://a.example/1"])
    before = later.queue_fingerprint(conn)
    later.add_offers(conn, ["https://b.example/2"], ts=T0)
    after = later.queue_fingerprint(conn)
    assert after["digest"] != before["digest"]
    assert (after["items"], before["items"]) == (2, 1)
    later.mark(conn, 1, later.STATE_ARCHIVED, ts=T0)
    assert later.queue_fingerprint(conn)["digest"] != after["digest"]


def test_re_saving_a_dropped_url_does_not_resurrect_it():
    conn = _queued(["https://x.example/a"])
    later.mark(conn, 1, later.STATE_DROPPED, ts=T0)
    later.add_offers(conn, ["https://x.example/a?utm_source=again"], ts=T0 + DAY)
    assert later.list_items(conn)[0]["state"] == later.STATE_DROPPED
    assert later.list_items(conn, state=later.STATE_UNREAD) == []


def test_mark_matches_a_url_in_any_spelling_and_refuses_the_unknown():
    conn = _queued(["https://example.com/post"])
    moved = later.mark(conn, "https://EXAMPLE.com/post?utm_source=tw", later.STATE_ARCHIVED, ts=T0)
    assert moved["matched_by"] == "canonical-url"
    assert (moved["previous_state"], moved["state"], moved["changed"]) == (
        later.STATE_UNREAD, later.STATE_ARCHIVED, True
    )
    again = later.mark(conn, 1, later.STATE_ARCHIVED, ts=T0)
    assert again["changed"] is False and again["matched_by"] == "id"
    with pytest.raises(ValueError, match="state must be one of"):
        later.mark(conn, 1, "read-ish", ts=T0)
    with pytest.raises(ValueError, match="no queued item"):
        later.mark(conn, "https://never.example/x", later.STATE_ARCHIVED, ts=T0)
    with pytest.raises(ValueError, match="no queued item"):
        later.mark(conn, 999, later.STATE_ARCHIVED, ts=T0)


def test_list_items_is_oldest_first_and_filters_on_state_and_tag():
    conn = _store()
    later.add_offers(conn, [{"url": "https://b.example/2", "tags": "ai"}], ts=T0)
    later.add_offers(conn, [{"url": "https://a.example/1", "tags": "cli"}], ts=T0 - DAY)
    assert [i["url"] for i in later.list_items(conn)] == [
        "https://a.example/1", "https://b.example/2"
    ]
    assert [i["url"] for i in later.list_items(conn, tag="AI")] == ["https://b.example/2"]
    assert later.list_items(conn, tag="nope") == []
    assert len(later.list_items(conn, limit=1)) == 1
    later.mark(conn, 1, later.STATE_ARCHIVED, ts=T0)
    assert [i["id"] for i in later.list_items(conn, state=later.STATE_UNREAD)] == [2]
    with pytest.raises(ValueError, match="state must be one of"):
        later.list_items(conn, state="skimmed")


def test_pending_skips_triaged_and_already_fetched_items():
    conn = _queued(["https://a.example/1", "https://b.example/2", "https://c.example/3"])
    later.mark(conn, "https://b.example/2", later.STATE_ARCHIVED, ts=T0)
    later.mark(conn, "https://c.example/3", later.STATE_DROPPED, ts=T0)
    assert [i["url"] for i in later.pending(conn)] == ["https://a.example/1"]
    boundary = _Boundary(default=_resp())
    later.run_fetch(conn, boundary, ts=T0, ingest=_ingest())
    assert later.pending(conn) == []  # a fetched item is not offered again
    assert [i["url"] for i in later.pending(conn, retry=True)] == []  # it succeeded
    assert len(boundary.calls) == 1


def test_pending_orders_by_save_time_then_key_and_honours_limit():
    conn = _store()
    later.add_offers(conn, ["https://late.example/z"], ts=T0 + DAY)
    later.add_offers(conn, ["https://early.example/a", "https://early.example/b"], ts=T0)
    rows = later.pending(conn, limit=2)
    assert [r["url"] for r in rows] == ["https://early.example/a", "https://early.example/b"]
    assert [r["url"] for r in later.pending(conn)][-1] == "https://late.example/z"


# ---- the fetch pass ----------------------------------------------------------


def test_run_fetch_ok_records_the_corpus_link_and_the_body_hash():
    conn = _queued(["https://a.example/1"])
    boundary = _Boundary({"https://a.example/1": _resp()})
    run = later.run_fetch(conn, boundary, ts=T0 + HOUR, ingest=_ingest())
    assert run["counts"] == {"ok": 1, "empty": 0, "error": 0, "denied": 0}
    assert run["words"] == 96 and run["attempted"] == 1
    res = run["results"][0]
    assert res["state"] == later.FETCH_OK and res["error"] is None
    assert res["doc_id"] == 7 and res["words"] == 96
    # ONE identity across the two stores: the queue row hashes what #11 hashes
    assert res["content_hash"] == extract.content_hash(ARTICLE)
    row = later.get_by_id(conn, res["id"])
    assert row["fetch_state"] == later.FETCH_OK and row["fetch_ts"] == T0 + HOUR
    assert row["doc_id"] == 7 and row["attempts"] == 1 and row["words"] == 96
    assert row["title"] == "Scaling laws revisited"  # backfilled from the ingest
    assert boundary.calls == ["https://a.example/1"]


def test_run_fetch_never_calls_the_fetcher_for_a_denied_url():
    conn = _queued(["https://open.example/1", "https://blocked.example/2"])
    boundary = _Boundary({"https://open.example/1": _resp()})
    run = later.run_fetch(
        conn,
        boundary,
        ts=T0,
        gate=lambda url: (("blocked" not in url), "host not in allowlist"),
        ingest=_ingest(),
    )
    assert boundary.calls == ["https://open.example/1"]  # the socket never opened
    assert run["counts"]["denied"] == 1 and run["counts"]["ok"] == 1
    denied = next(r for r in run["results"] if r["state"] == later.FETCH_DENIED)
    assert denied["error"] == "policy-denied: host not in allowlist"
    assert denied["content_hash"] is None and denied["status"] is None
    row = later.get_by_id(conn, denied["id"])
    assert row["attempts"] == 1 and row["fetch_error"].startswith("policy-denied")


def test_run_fetch_records_http_and_transport_failures_separately():
    conn = _queued(["https://a.example/404", "https://b.example/dns", "https://c.example/boom"])

    def boundary(url: str) -> dict:
        if url.endswith("404"):
            return _resp(status=404, html="<html>nope</html>")
        if url.endswith("dns"):
            return {"status": None, "html": "", "url": url, "error": "URLError: name not known"}
        raise RuntimeError("fetcher exploded")

    run = later.run_fetch(conn, boundary, ts=T0, ingest=_ingest())
    assert run["counts"]["error"] == 3
    by_url = {r["url"]: r for r in run["results"]}
    assert by_url["https://a.example/404"]["error"] == "http 404"
    assert by_url["https://a.example/404"]["status"] == 404
    assert by_url["https://a.example/404"]["content_hash"] is None  # a 404 body is not the article
    assert "name not known" in by_url["https://b.example/dns"]["error"]
    assert "RuntimeError: fetcher exploded" in by_url["https://c.example/boom"]["error"]
    assert later.pending(conn) == [] and len(later.pending(conn, retry=True)) == 3


def test_run_fetch_distinguishes_an_empty_body_from_an_empty_article():
    conn = _queued(["https://a.example/blank", "https://b.example/thin"])
    boundary = _Boundary(
        {
            "https://a.example/blank": _resp(html="   "),
            "https://b.example/thin": _resp(html=ARTICLE),
        }
    )
    run = later.run_fetch(conn, boundary, ts=T0, ingest=_ingest(words=0, doc_id=None, title=None))
    assert run["counts"]["empty"] == 2 and run["words"] == 0
    blank = next(r for r in run["results"] if r["url"].endswith("blank"))
    thin = next(r for r in run["results"] if r["url"].endswith("thin"))
    assert "no body" in blank["note"] and blank["words"] is None
    assert "no article text" in thin["note"] and thin["words"] == 0
    assert blank["error"] is None and thin["error"] is None


def test_run_fetch_survives_a_broken_ingest():
    conn = _queued(["https://a.example/1", "https://b.example/2"])

    def exploding(html: str, url: str, item: dict) -> dict:
        if url.endswith("1"):
            raise ZeroDivisionError("bad parse")
        return {"error": "unsupported charset"}

    run = later.run_fetch(conn, _Boundary(default=_resp()), ts=T0, ingest=exploding)
    assert run["counts"]["error"] == 2
    messages = sorted(r["error"] for r in run["results"])
    assert messages[0].startswith("ingest failed: unsupported charset")
    assert messages[1].startswith("ingest raised ZeroDivisionError")


def test_run_fetch_without_an_ingest_hashes_but_reports_no_word_count():
    conn = _queued(["https://a.example/1"])
    run = later.run_fetch(conn, _Boundary(default=_resp()), ts=T0)
    res = run["results"][0]
    assert res["state"] == later.FETCH_OK
    assert res["words"] is None, "a word count nobody measured must not read as 0"
    assert "not parsed" in res["note"]
    assert res["content_hash"] == extract.content_hash(ARTICLE)
    assert run["words"] == 0  # the sum of nothing, and the row still says None


def test_every_fetch_result_obeys_the_reading_invariants():
    conn = _queued(
        ["https://ok.example/1", "https://bad.example/2", "https://blank.example/3",
         "https://no.example/4"]
    )
    boundary = _Boundary(
        {
            "https://ok.example/1": _resp(),
            "https://bad.example/2": _resp(status=500, html="err"),
            "https://blank.example/3": _resp(html=""),
        },
        default={"status": None, "html": "", "url": None, "error": "TimeoutError: timed out"},
    )
    run = later.run_fetch(
        conn, boundary, ts=T0, gate=lambda u: (True, "test"), ingest=_ingest()
    )
    assert sorted(run["counts"].items()) == [("denied", 0), ("empty", 1), ("error", 2), ("ok", 1)]
    for res in run["results"]:
        assert res["state"] in later.FETCH_STATES
        has_error = res["state"] in (later.FETCH_ERROR, later.FETCH_DENIED)
        assert (res["error"] is not None) == has_error, res
        body_arrived = res["state"] in (later.FETCH_OK, later.FETCH_EMPTY)
        assert (res["content_hash"] is not None) == body_arrived, res


def test_content_duplicates_group_identical_bodies_in_either_fetch_order():
    urls = ["https://a.example/1", "https://b.example/2"]
    digests = []
    for order in (urls, list(reversed(urls))):
        conn = _queued(urls)
        later.run_fetch(
            conn,
            _Boundary(dict.fromkeys(order, _resp())),
            ts=T0,
            ingest=_ingest(),
        )
        groups = later.content_duplicates(conn)
        assert len(groups) == 1
        # members are ordered by row id, and ids follow the canonical-KEY sort
        # inside a batch rather than the input order — which is exactly why
        # queue_fingerprint excludes the id column
        assert sorted(m["url"] for m in groups[0]["items"]) == urls
        assert [m["id"] for m in groups[0]["items"]] == sorted(
            m["id"] for m in groups[0]["items"]
        )
        digests.append(groups[0]["content_hash"])
    assert digests[0] == digests[1] == extract.content_hash(ARTICLE)


def test_a_refetched_item_is_never_its_own_duplicate():
    conn = _queued(["https://a.example/1"])
    later.run_fetch(conn, _Boundary(default=_resp()), ts=T0, ingest=_ingest())
    again = later.run_fetch(conn, _Boundary(default=_resp()), ts=T0 + DAY, retry=True, ingest=_ingest())
    assert again["attempted"] == 0  # a successful fetch is not retried
    forced = later.run_fetch(
        conn, _Boundary(default=_resp(status=503, html="")), ts=T0 + DAY, retry=True, ingest=_ingest()
    )
    assert forced["attempted"] == 0
    conn.execute("UPDATE items SET fetch_state = 'error' WHERE id = 1")
    retried = later.run_fetch(conn, _Boundary(default=_resp()), ts=T0 + DAY, retry=True, ingest=_ingest())
    assert retried["attempted"] == 1
    assert retried["results"][0]["duplicate_of"] is None
    assert later.content_duplicates(conn) == []
    assert later.get_by_id(conn, 1)["attempts"] == 2


# ---- the board and the family gate ------------------------------------------


def test_board_on_an_empty_queue_reports_no_age_and_says_why():
    snapshot = later.board(_store(), now=T0)
    assert snapshot["total"] == 0
    assert snapshot["oldest_unread"] is None
    assert snapshot["notes"] and "fabricated" in snapshot["notes"][0]
    assert snapshot["by_state"][later.STATE_UNREAD] == 0


def test_board_counts_states_ages_tags_and_alias_savings():
    conn = _store()
    later.add_offers(
        conn,
        [
            {"url": "https://old.example/1", "tags": "ai"},
            {"url": "https://old.example/1?utm_source=x", "tags": "ai"},
        ],
        ts=T0 - 40 * DAY,
    )
    later.add_offers(conn, [{"url": "https://new.example/2", "tags": "cli"}], ts=T0 - DAY)
    later.mark(conn, "https://new.example/2", later.STATE_READING, ts=T0)
    snapshot = later.board(conn, now=T0, stale_days=30)
    assert snapshot["total"] == 2
    assert snapshot["by_state"] == {"unread": 1, "reading": 1, "archived": 0, "dropped": 0}
    assert snapshot["unfetched"] == 2 and snapshot["by_fetch_state"]["ok"] == 0
    assert snapshot["oldest_unread"]["url"] == "https://old.example/1"
    assert snapshot["oldest_unread"]["age_days"] == 40.0
    assert [s["id"] for s in snapshot["stale"]] == [1]
    assert snapshot["tags"] == {"ai": 1, "cli": 1}
    assert (snapshot["aliases"], snapshot["alias_savings"]) == (3, 1)
    assert snapshot["notes"] == []
    # a reading item is not unread, so it can never be the queue age
    assert later.board(conn, now=T0, stale_days=1)["oldest_unread"]["id"] == 1


def test_queue_diagnostics_report_staleness_and_duplicate_bodies():
    conn = _queued(["https://a.example/1", "https://b.example/2"], ts=T0 - 60 * DAY)
    later.run_fetch(conn, _Boundary(default=_resp()), ts=T0, ingest=_ingest())
    diags = later.queue_diagnostics(conn, now=T0, stale_days=30)
    rules = {d["rule"] for d in diags}
    assert rules == {"later:stale", "later:duplicate-content"}
    stale = [d for d in diags if d["rule"] == "later:stale"]
    assert len(stale) == 2 and all(d["severity"] == "suggestion" for d in stale)
    assert "unread for 60 days" in stale[0]["message"]
    dup = next(d for d in diags if d["rule"] == "later:duplicate-content")
    assert dup["severity"] == "info" and "byte-identical" in dup["message"]
    assert all(d["source"] == "later" for d in diags)
    # a fresh queue is clean
    assert later.queue_diagnostics(_queued(["https://c.example/3"]), now=T0) == []


def test_fetch_diagnostics_map_every_failure_onto_the_family_schema():
    conn = _queued(["https://a.example/404", "https://b.example/blocked", "https://c.example/thin"])
    boundary = _Boundary(
        {
            "https://a.example/404": _resp(status=404, html="x"),
            "https://c.example/thin": _resp(),
        }
    )
    run = later.run_fetch(
        conn,
        boundary,
        ts=T0,
        gate=lambda u: ("blocked" not in u, "not allowlisted"),
        ingest=_ingest(words=0, doc_id=None, title=None),
    )
    invalid = later.merge_offers(["not a url"], ts=T0)["invalid"]
    diags = later.fetch_diagnostics(run["results"], invalid)
    got = {d["rule"]: d["severity"] for d in diags}
    assert got == {
        "later:fetch-error": "error",
        "later:policy-denied": "warning",
        "later:empty-article": "warning",
        "later:invalid-url": "error",
    }
    summary = openswap.summarize(diags)
    assert summary["total"] == 4 and summary["by_severity"]["error"] == 2
    assert all(d["line"] == 0 and d["col"] == 0 for d in diags)


def test_load_rules_overlay_can_silence_a_rule_and_rejects_nonsense(tmp_path):
    assert set(later.load_rules()) == set(later.RULES)
    off = tmp_path / "rules.json"
    off.write_text('{"later:stale": {"enabled": false}}', encoding="utf-8")
    rules = later.load_rules(off)
    conn = _queued(["https://a.example/1"], ts=T0 - 90 * DAY)
    assert later.queue_diagnostics(conn, now=T0, rules=rules) == []
    assert len(later.queue_diagnostics(conn, now=T0)) == 1  # and it fires without the overlay
    bad = tmp_path / "bad.json"
    bad.write_text('{"later:not-a-rule": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule id"):
        later.load_rules(bad)
    worse = tmp_path / "worse.json"
    worse.write_text('{"later:stale": {"severity": "catastrophe"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="severity must be one of"):
        later.load_rules(worse)


# ---- the importers ----------------------------------------------------------


def test_parse_bookmarks_reads_a_pocket_export_with_tags_folders_notes_and_dates():
    offers = later.parse_bookmarks(POCKET_EXPORT)
    assert len(offers) == 5  # including the href-less anchor and the mailto
    first = offers[0]
    assert first["url"] == "https://example.com/post?utm_source=newsletter"
    assert first["title"] == "Scaling laws revisited - The Site"
    assert first["tags"] == ["ai", "research", "scaling"]  # TAGS + the H3 folder
    assert first["note"] == "read the appendix"
    assert first["added_ts"] == 1780000000.0
    assert first["source"] == "bookmarks"
    assert offers[1]["note"] is None  # the <DD> belonged to the anchor before it
    assert offers[2]["tags"] == ["cli", "tools"]  # the second folder, not the first
    assert offers[3]["url"] is None and offers[3]["title"] == "no href at all"
    assert offers[4]["url"] == "mailto:nope@example.com"


def test_parse_bookmarks_can_leave_folders_out_of_the_tags():
    offers = later.parse_bookmarks(POCKET_EXPORT, folders_as_tags=False)
    assert offers[0]["tags"] == ["ai", "scaling"]
    assert offers[2]["tags"] == ["cli"]


def test_parse_bookmarks_never_raises_on_junk():
    assert later.parse_bookmarks("") == []
    assert later.parse_bookmarks("<html><body>no links here") == []
    soup = later.parse_bookmarks('<DL><DT><A HREF="https://x.example/1">unclosed')
    assert [o["url"] for o in soup] == ["https://x.example/1"]


def test_parse_add_date_refuses_to_guess_an_unknown_epoch():
    assert later.parse_add_date("1780000000") == 1780000000.0
    assert later.parse_add_date(" 1780000000 ") == 1780000000.0
    assert later.parse_add_date("1780000000000") == 1780000000.0  # milliseconds
    assert later.parse_add_date("13350000000000000") is None  # WebKit/1601, refused
    for junk in ("", "0", "-5", "yesterday", None, "1.5e9"):
        assert later.parse_add_date(junk) is None, junk


def test_parse_csv_reads_a_raindrop_export():
    offers = later.parse_csv(RAINDROP_CSV)
    assert len(offers) == 3
    assert offers[0]["url"] == "https://example.com/post?utm_campaign=x"
    assert offers[0]["tags"] == ["ai", "research", "scaling"]
    assert offers[0]["note"] == "why"
    assert offers[0]["added_ts"] == feeds.parse_entry_time("2026-07-01T09:00:00Z")
    assert offers[1]["added_ts"] == 1780000000.0  # a bare epoch also works
    assert offers[1]["tags"] == ["cli", "tools"]
    assert offers[2]["added_ts"] is None  # no date at all: unknown, not invented
    assert [o["source"] for o in offers] == ["csv"] * 3


def test_parse_csv_without_a_url_column_is_an_error_naming_the_headers():
    with pytest.raises(ValueError, match="no url column"):
        later.parse_csv("title,note\nx,y\n")
    with pytest.raises(ValueError, match="no header row"):
        later.parse_csv("")


def test_import_of_an_export_collapses_its_own_duplicates(tmp_path):
    conn = _store()
    result = later.add_offers(conn, later.parse_bookmarks(POCKET_EXPORT), ts=T0)
    assert result["counts"] == {
        "offered": 5, "added": 2, "duplicate": 0, "invalid": 2, "collapsed": 1
    }
    urls = [i["url"] for i in later.list_items(conn)]
    assert urls == ["https://example.com/post", "https://other.example/y"]
    assert [b["error"] for b in result["invalid"]].count("empty url") == 1


def test_offers_from_entries_collapses_a_cross_listed_feed_item():
    entry = {
        "feed": "arxiv-cs-lg",
        "link": "https://arxiv.org/abs/2607.00001?utm_source=rss",
        "title": "Muon scaling laws",
        "summary": "curriculum learning",
        "matched": ["curriculum"],
        "tags": ["cs.LG"],
        "published_ts": T0,
    }
    twin = dict(entry, feed="arxiv-cs-cl", published_ts=None, first_seen_ts=T0 + HOUR)
    offers = later.offers_from_entries([entry, twin])
    assert [o["source"] for o in offers] == ["feeds:arxiv-cs-lg", "feeds:arxiv-cs-cl"]
    assert offers[0]["tags"] == ["cs.lg", "curriculum"]
    assert offers[1]["added_ts"] == T0 + HOUR  # falls back to first_seen_ts
    conn = _store()
    result = later.add_offers(conn, offers, ts=T0 + DAY)
    assert result["counts"]["added"] == 1 and result["counts"]["collapsed"] == 1
    item = later.list_items(conn)[0]
    assert item["url"] == "https://arxiv.org/abs/2607.00001"  # the rss param is gone
    assert item["source"] == "feeds:arxiv-cs-cl,feeds:arxiv-cs-lg"
    assert item["added_ts"] == T0


def test_offers_from_entries_keeps_a_linkless_entry_as_an_invalid_row():
    merged = later.merge_offers(
        later.offers_from_entries([{"feed": "x", "title": "no link", "link": None}]), ts=T0
    )
    assert merged["items"] == {}
    assert merged["invalid"][0]["error"] == "empty url"


# ---- capability + manifest --------------------------------------------------


def test_manifest_is_loopback_only_default_deny():
    manifest = load_manifest(MANIFEST_DIR)
    net = manifest["capabilities"]["network"]
    assert net["enabled"] is True  # `fetch` needs a socket, and says so
    assert sorted(net["domains"]) == ["127.0.0.1", "localhost"]
    allowed, _ = check_permission(manifest, "network", "http://127.0.0.1:8731/a")
    assert allowed
    denied, reason = check_permission(manifest, "network", "https://example.com/post")
    assert not denied and "not in allowlist" in reason
    assert manifest["capabilities"]["filesystem"]["paths"] == [".scout"]
    assert manifest["capabilities"]["secrets"]["allow"] == []


def test_capability_report_never_claims_a_binary_ran():
    from bigbang.plugins.later import cli as later_cli

    cap = later_cli._capability()
    assert cap["adapter"] == "later"
    # tied to the PROBE rather than written as a disjunct: on a box with shiori
    # installed the tier must say native, and native_used must still be False
    expected = openswap.TIER_NATIVE if cap["native"]["found"] else openswap.TIER_FALLBACK
    assert cap["tier"] == expected
    assert cap["native_used"] is False
    assert "never executed" in cap["native_never_executed"].lower()
    assert set(cap["extras"]) == {"buku", "archivebox"}
    assert cap["scope_limits"] == later.SCOPE_LIMITS


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, timeout=120):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
    )


def _data(result):
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)["data"]


def test_cli_later_hello_envelope():
    data = _data(_cli(["later", "hello"]))
    assert data["ready"] is True and data["plugin"] == "later"


def test_cli_later_detect_reports_the_tier_and_the_egress_shape():
    data = _data(_cli(["later", "detect"]))
    assert data["native_used"] is False
    assert data["egress"]["network_enabled"] is True
    assert data["egress"]["manifest_domains"] == ["localhost", "127.0.0.1"]
    assert "add" in data["egress"]["commands_with_zero_egress"]
    assert "canonicalisation" in data["fallback_scope"]


def test_cli_later_policy_publishes_the_effective_tables():
    data = _data(_cli(["later", "policy"]))
    assert data["policy"] == later.DEFAULT_POLICY
    assert set(data["rules"]) == set(later.RULES)
    assert "utm_" in data["tracking_prefixes"] and "fbclid" in data["tracking_params"]
    assert data["states"] == list(later.STATES)
    assert data["policy_overlay"] is None


def test_cli_later_canon_shows_which_spellings_collapse():
    data = _data(
        _cli(["later", "canon", "https://Example.com/p?utm_source=nl#x", "https://example.com/p"])
    )
    assert data["distinct"] == 1
    assert data["collapsed"][0]["url"] == "https://example.com/p"
    assert len(data["collapsed"][0]["inputs"]) == 2
    assert data["readings"][0]["dropped_params"] == ["utm_source"]


def test_cli_later_add_then_list_dedupes_and_fingerprints(tmp_path):
    db = str(tmp_path / "later.db")
    first = _data(_cli(["later", "add", "https://example.com/post", "--tag", "ai", "--db", db]))
    assert first["counts"]["added"] == 1
    second = _data(
        _cli(["later", "add", "https://EXAMPLE.com/post?utm_source=x", "--tag", "reread", "--db", db])
    )
    assert second["counts"] == {
        "offered": 1, "added": 0, "duplicate": 1, "invalid": 0, "collapsed": 0
    }
    listing = _data(_cli(["later", "list", "--db", db]))
    assert listing["count"] == 1
    assert listing["items"][0]["tags"] == ["ai", "reread"]
    assert listing["items"][0]["aliases"] == 2
    assert listing["fingerprint"]["items"] == 1


def test_cli_later_import_reports_invalid_rows_instead_of_losing_them(tmp_path):
    export = tmp_path / "ril_export.html"
    export.write_text(POCKET_EXPORT, encoding="utf-8")
    db = str(tmp_path / "later.db")
    data = _data(_cli(["later", "import", str(export), "--db", db]))
    assert data["counts"] == {"offered": 5, "added": 2, "duplicate": 0, "invalid": 2, "collapsed": 1}
    assert {b["error"].split(" ")[0] for b in data["invalid"]} == {"empty", "not"}
    csv_file = tmp_path / "raindrop.csv"
    csv_file.write_text(RAINDROP_CSV, encoding="utf-8")
    merged = _data(_cli(["later", "import", str(csv_file), "--db", db]))
    assert merged["counts"]["duplicate"] == 2  # both real rows were already queued
    assert merged["counts"]["invalid"] == 1


def test_cli_later_import_missing_file_fails_actionably(tmp_path):
    r = _cli(["later", "import", str(tmp_path / "nope.html")])
    assert r.returncode == 1
    assert "no such export file" in json.loads(r.stdout)["error"]


def test_cli_later_mark_and_board_gate_on_staleness(tmp_path):
    db = str(tmp_path / "later.db")
    _cli(["later", "add", "https://example.com/post", "--db", db])
    moved = _data(_cli(["later", "mark", "https://example.com/post/../post", "--state", "reading", "--db", db]))
    assert moved["moved"][0]["state"] == "reading"
    bad = _cli(["later", "mark", "https://never.example/x", "--state", "reading", "--db", db])
    assert bad.returncode == 1 and "no queued item" in json.loads(bad.stdout)["error"]
    board = _data(_cli(["later", "board", "--db", db]))
    assert board["board"]["by_state"]["reading"] == 1
    assert board["board"]["oldest_unread"] is None and board["board"]["notes"]
    gated = _cli(["later", "board", "--db", db, "--fail-on", "info"])
    assert gated.returncode == 0  # nothing is stale or duplicated yet


def test_cli_later_fetch_denies_an_off_allowlist_url_without_a_socket(tmp_path):
    db = str(tmp_path / "later.db")
    _cli(["later", "add", "https://example.com/post", "--db", db])
    r = _cli(["later", "fetch", "--db", db, "--no-ingest", "--fail-on", "warning"])
    assert r.returncode == 1  # a denial is a warning, and the gate fires on it
    data = json.loads(r.stdout)["data"]
    assert data["counts"] == {"ok": 0, "empty": 0, "error": 0, "denied": 1}
    assert data["ingested_into"] is None
    assert data["diagnostics"][0]["rule"] == "later:policy-denied"
    assert "reach allow" in data["diagnostics"][0]["suggestion"]
    assert data["native_used"] is False


def test_cli_later_fetch_reports_a_dead_loopback_port_as_an_error(tmp_path):
    """The one case that really calls _fetch_page: loopback is manifest-allowed,
    nothing is listening on port 1, so the transport failure must land as ONE
    recorded row rather than an exception."""
    db = str(tmp_path / "later.db")
    _cli(["later", "add", "http://127.0.0.1:1/article.html", "--db", db])
    data = _data(_cli(["later", "fetch", "--db", db, "--no-ingest", "--timeout", "3"]))
    assert data["counts"]["error"] == 1 and data["counts"]["denied"] == 0
    res = data["results"][0]
    assert res["state"] == "error" and res["error"]
    assert res["content_hash"] is None


def test_cli_later_fetch_rejects_a_bad_fail_on(tmp_path):
    db = str(tmp_path / "later.db")
    _cli(["later", "add", "https://example.com/post", "--db", db])
    r = _cli(["later", "fetch", "--db", db, "--fail-on", "catastrophe"])
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]


def test_cli_later_list_without_a_queue_fails_actionably(tmp_path):
    r = _cli(["later", "list", "--db", str(tmp_path / "missing.db")])
    assert r.returncode == 1
    assert "no queue at" in json.loads(r.stdout)["error"]


def test_cli_later_policy_rejects_a_bad_overlay(tmp_path):
    bad = tmp_path / "pol.json"
    bad.write_text('{"strip_wwww": true}', encoding="utf-8")
    r = _cli(["later", "policy", "--policy", str(bad)])
    assert r.returncode == 1
    assert "bad canonicalisation policy" in json.loads(r.stdout)["error"]


def test_cli_later_pull_bridges_the_feeds_reader(tmp_path):
    reader = feeds.open_store(tmp_path / "feeds.db")
    feeds.add_feed(reader, "arxiv-cs-lg", "https://rss.arxiv.org/rss/cs.LG", ts=T0)
    feeds.add_feed(reader, "arxiv-cs-cl", "https://rss.arxiv.org/rss/cs.CL", ts=T0)
    entry = {
        "guid": "oai:arXiv.org:2607.00001v1",
        "link": "https://arxiv.org/abs/2607.00001?utm_source=rss",
        "title": "Muon scaling laws",
        "summary": "curriculum learning",
        "tags": ["cs.LG"],
        "published_ts": T0,
    }
    feeds.ingest(reader, "arxiv-cs-lg", [entry], ts=T0, keywords={"curriculum": 2.0})
    feeds.ingest(reader, "arxiv-cs-cl", [dict(entry, guid="twin")], ts=T0, keywords={"curriculum": 2.0})
    assert reader.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    data = _data(
        _cli(
            [
                "later", "pull",
                "--feeds-db", str(tmp_path / "feeds.db"),
                "--db", str(tmp_path / "later.db"),
                "--mark",
            ]
        )
    )
    assert data["counts"]["entries_offered"] == 2
    assert data["counts"]["added"] == 1 and data["counts"]["collapsed"] == 1
    assert data["added"][0]["url"] == "https://arxiv.org/abs/2607.00001"
    assert data["added"][0]["tags"] == ["cs.lg", "curriculum"]
    again = _data(
        _cli(
            [
                "later", "pull",
                "--feeds-db", str(tmp_path / "feeds.db"),
                "--db", str(tmp_path / "later.db"),
            ]
        )
    )
    assert again["counts"]["entries_offered"] == 0  # --mark stamped them as digested


def test_cli_later_pull_without_a_reader_fails_actionably(tmp_path):
    r = _cli(["later", "pull", "--feeds-db", str(tmp_path / "nope.db"), "--db", str(tmp_path / "l.db")])
    assert r.returncode == 1
    assert "no feeds reader store" in json.loads(r.stdout)["error"]


def test_cli_plugin_is_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "later" in list_plugin_names()
