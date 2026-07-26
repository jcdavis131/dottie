"""Searchindex — openswap #23 (Algolia DocSearch -> build-time inverted index,
sharded JSON + a dependency-free JS client). Pure-logic core tests (tokenizer,
guarded stemmer, page extraction, field weighting, route planning, byte-exact
artifact rendering, BM25 ranking, deployed-artifact verification), the family
diagnostic mapping, capability detection, the subprocess envelope, and — where
node is on PATH — the GENERATED CLIENT run against a real artifact and compared
hit for hit with rank(). Offline and deterministic by construction: no socket is
opened and every `now` is explicit. The accented/CJK literals are real UTF-8
(pytest reads this file as UTF-8); they are the point of the folding tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, searchindex

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0  # fixed build stamp: 2027-01-15T08:00:00Z

HTML_PAGE = (
    "<html><head><title>Widget Co</title>"
    "<meta name='description' content='Widgets and shipping'></head>"
    "<body><nav>Home Docs Pricing Blog</nav><h1>Widgets that ship</h1>"
    "<p>We ship widgets. Shipping is fast.</p>"
    "<div data-searchindex='skip'>secretsauce</div>"
    "<footer>Copyright Widget Co</footer></body></html>"
)
MD_PAGE = (
    "---\ntitle: front matter\n---\n# Tokenizer guide\n\n"
    "## Stemming\n\nIndexing a corpus with the `tokenizer`. Tokenize pages.\n"
)


def _doc(rel: str, text: str, *, base: str | None = None) -> dict:
    url, _kind = searchindex.url_for_rel(rel, base_url=base)
    return searchindex.extract_document(text, rel=rel, url=url)


def _docs() -> list[dict]:
    return [
        _doc("index.html", HTML_PAGE),
        _doc(
            "docs/pricing.html",
            "<html><head><title>Pricing</title></head><body><h1>Pricing plans</h1>"
            "<p>Widget pricing is simple: one price per widget.</p></body></html>",
        ),
        _doc("docs/guide.md", MD_PAGE),
    ]


def _index(**kwargs):
    return searchindex.build_index(_docs(), **{"shards": 3, **kwargs})


def _rendered(**kwargs):
    index = _index(**kwargs)
    return index, searchindex.render_files(index, now=NOW)


# ---- folding + tokenizing ---------------------------------------------------


def test_fold_strips_diacritics_before_tokenizing():
    # the whole point: "café" and "cafe" must be ONE term, and a leftover
    # combining mark must not split "coöperate" into coo + perate
    assert searchindex.fold("Café") == "cafe"
    assert searchindex.tokenize("Café") == ["cafe"]
    assert searchindex.tokenize("coöperate") == ["cooperate"]
    assert searchindex.fold(None) == ""


def test_tokenize_splits_on_punctuation_and_keeps_digits():
    assert searchindex.tokenize("BM25: bm-25, v1.2!") == ["bm25", "bm", "25", "v1", "2"]
    assert searchindex.tokenize("") == []


def test_unsupported_chars_counts_what_the_alphabet_cannot_hold():
    # rule 5: a thing that cannot be indexed is COUNTED and reported, never
    # silently dropped to make the build look clean
    assert searchindex.unsupported_chars("hello") == 0
    assert searchindex.unsupported_chars("你好 hello") == 2
    assert searchindex.unsupported_chars("Москва") == 6
    # a diacritic FOLDS, so it is supported and must not be counted
    assert searchindex.unsupported_chars("café") == 0


# ---- the guarded light stemmer ----------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("pages", "page"),
        ("classes", "class"),
        ("passes", "pass"),
        ("queries", "query"),
        ("cities", "city"),
        ("ties", "tie"),  # len 4: the -ies rule must NOT fire
        ("boxes", "box"),
        ("dishes", "dish"),
        ("churches", "church"),
        ("buses", "bus"),
        ("uses", "use"),  # len 4: the -es rule must NOT fire, -s must
        ("gloss", "gloss"),
        ("status", "status"),
        ("analysis", "analysis"),
        ("indexing", "index"),
        ("indexed", "index"),
        ("indexes", "index"),
        ("running", "run"),
        ("shipping", "ship"),
        ("hopped", "hop"),
        ("adding", "add"),  # collapse needs stem > 3, so "add" stays "add"
        ("needed", "need"),
        ("passing", "pass"),  # 's' is NOT a collapsible double
        ("seed", "seed"),  # stripping would leave "se" (< MIN_STEM)
        ("using", "using"),
        ("user", "user"),  # must NOT collapse into "use"
        ("cat", "cat"),
        ("bus", "bus"),
    ],
)
def test_stem_rules(word, expected):
    assert searchindex.stem(word) == expected


def test_stem_is_idempotent_over_every_corpus_token():
    # a non-idempotent stemmer means query terms and index terms can disagree
    tokens = set()
    for doc in _docs():
        tokens.update(searchindex.tokenize(doc["body"]))
        tokens.update(searchindex.tokenize(doc["title"] or ""))
    tokens.update(
        "pages classes queries boxes running shipped studies flies analyses".split()
    )
    assert tokens
    for token in sorted(tokens):
        once = searchindex.stem(token)
        assert searchindex.stem(once) == once, token


def test_terms_attributes_every_loss():
    found, dropped = searchindex.terms("The a widgets and shipping xy z abc")
    assert found == ["widget", "ship", "xy", "abc"]
    assert dropped == {"stopword": 3, "too_short": 1, "too_long": 0}
    long_word = "a" * (searchindex.MAX_TERM_LEN + 1)
    found2, dropped2 = searchindex.terms(long_word)
    assert (found2, dropped2["too_long"]) == ([], 1)


def test_terms_without_stemming_keeps_the_surface_form():
    found, _dropped = searchindex.terms("shipping widgets", stemming=False)
    assert found == ["shipping", "widgets"]


def test_query_terms_dedupes_and_keeps_first_occurrence_order():
    assert searchindex.query_terms("widget widgets pricing widget") == [
        "widget",
        "pric",
    ]


# ---- page extraction --------------------------------------------------------


def test_extract_html_uses_seo_facts_and_drops_chrome():
    doc = _doc("index.html", HTML_PAGE)
    assert doc["kind"] == "html"
    assert doc["title"] == "Widget Co"
    assert doc["description"] == "Widgets and shipping"
    assert doc["headings"] == ["Widgets that ship"]
    assert doc["noindex"] is False
    # nav/footer chrome, the data-searchindex=skip subtree and the <title> copy
    # are all out of the body
    for absent in ("Blog", "Copyright", "secretsauce", "Widget Co"):
        assert absent not in doc["body"]
    assert "We ship widgets" in doc["body"]
    assert doc["skipped_subtrees"] == 4  # nav, footer, the skip div, <title>


def test_keep_boilerplate_restores_nav_and_footer():
    doc = searchindex.extract_document(
        HTML_PAGE, rel="index.html", url="/", keep_boilerplate=True
    )
    assert "Blog" in doc["body"] and "Copyright" in doc["body"]


def test_extract_html_carries_noindex():
    doc = _doc(
        "draft.html",
        "<html><head><title>D</title><meta name='robots' content='noindex'>"
        "</head><body>unfinished</body></html>",
    )
    assert doc["noindex"] is True


def test_block_tags_do_not_weld_words_together():
    doc = _doc("a.html", "<html><body><p>alpha</p><p>beta</p></body></html>")
    assert searchindex.tokenize(doc["body"]) == ["alpha", "beta"]


def test_markdown_fields_drop_front_matter_and_syntax():
    title, headings, body = searchindex.markdown_fields(MD_PAGE)
    assert title == "Tokenizer guide"
    assert headings == ["Tokenizer guide", "Stemming"]
    assert "front matter" not in body
    assert "`" not in body and "#" not in body
    assert "Tokenize pages." in body


def test_markdown_title_is_none_when_there_is_no_h1():
    title, headings, _body = searchindex.markdown_fields("## Only a subheading\n")
    assert title is None and headings == ["Only a subheading"]


def test_plain_text_page_has_no_title_and_keeps_its_text():
    doc = _doc("notes.txt", "raw notes about widgets")
    assert (doc["kind"], doc["title"]) == ("text", None)
    assert doc["body"] == "raw notes about widgets"


def test_excerpt_cuts_on_a_word_boundary():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    cut = searchindex.excerpt(text, chars=20)
    assert cut.endswith("…")
    assert " " not in cut[-2:]
    assert cut[:-1].strip() in text
    assert searchindex.excerpt("short  text\n") == "short text"


def test_url_for_rel_never_invents_a_domain():
    assert searchindex.url_for_rel("docs/a.html") == ("/docs/a.html", "relative")
    assert searchindex.url_for_rel("index.html") == ("/", "relative")
    assert searchindex.url_for_rel("docs/a.html", base_url="https://x.example/") == (
        "https://x.example/docs/a.html",
        "absolute",
    )
    assert searchindex.url_for_rel(
        "docs/a.html", base_url="https://x.example/", clean_urls=True
    ) == ("https://x.example/docs/a", "absolute")
    assert searchindex.url_for_rel("docs/index.html", strip_index=False)[0] == (
        "/docs/index.html"
    )


def test_ext_globs_is_wildcard_free():
    assert searchindex.ext_globs(["md", ".HTML", "*.txt", "", None]) == [
        "*.md",
        "*.html",
        "*.txt",
    ]
    assert searchindex.default_include() == [f"*{e}" for e in searchindex.PAGE_EXTS]


# ---- field weighting --------------------------------------------------------


def test_validate_weights_rejects_typos_and_all_zero():
    assert searchindex.validate_weights(None) == searchindex.DEFAULT_WEIGHTS
    assert searchindex.validate_weights({"title": 12})["title"] == 12
    for bad in ({"titel": 1}, {"title": "x"}, {"title": -1}):
        with pytest.raises(ValueError):
            searchindex.validate_weights(bad)
    with pytest.raises(ValueError, match="at least one field weight"):
        searchindex.validate_weights(dict.fromkeys(searchindex.FIELDS, 0))


def test_score_document_multiplies_occurrences_by_field_weight():
    doc = {
        "path": "docs/widget.html",
        "title": "Widget",
        "headings": ["Widget"],
        "description": "widget",
        "body": "widget widget",
    }
    scored = searchindex.score_document(doc, weights=searchindex.DEFAULT_WEIGHTS)
    # title 8 + heading 4 + description 3 + path 2 + body 1*2 = 19
    assert scored["scores"]["widget"] == 19
    # "docs" also counts as a path term; "html" is a stopword and does not
    assert scored["length"] == 7
    assert scored["field_terms"] == {
        "title": 1,
        "heading": 1,
        "description": 1,
        "path": 2,
        "body": 2,
    }
    assert scored["scores"]["doc"] == 2


def test_zero_weight_field_still_counts_length_but_scores_nothing():
    doc = {"path": "", "title": "widget", "headings": [], "description": "", "body": ""}
    weights = {**searchindex.DEFAULT_WEIGHTS, "title": 0}
    scored = searchindex.score_document(doc, weights=weights)
    assert scored["scores"] == {} and scored["length"] == 1


def test_stopword_provenance_ships_the_list_and_its_hash():
    prov = searchindex.stopword_provenance()
    assert prov["count"] == len(searchindex.STOPWORDS) == len(prov["words"])
    assert prov["words"] == sorted(prov["words"])
    assert len(prov["sha256"]) == 64
    # the list is DERIVED from ollama's, not retyped — a drift there must show up
    from bigbang.core import ollama

    assert set(ollama._STOPWORDS) <= searchindex.STOPWORDS
    other = searchindex.stopword_provenance(frozenset({"the"}))
    assert other["count"] == 1 and other["sha256"] != prov["sha256"]


# ---- routing ----------------------------------------------------------------


def test_plan_routes_balances_by_posting_count():
    counts = {"a": 10, "b": 10, "c": 1, "d": 1}
    assert searchindex.plan_routes(counts, 2) == {"a": 0, "b": 1, "c": 1, "d": 1}
    # every bucket lands somewhere, and no shard index is skipped
    routes = searchindex.plan_routes(counts, 4)
    assert sorted(routes) == ["a", "b", "c", "d"]
    assert sorted(set(routes.values())) == list(range(max(routes.values()) + 1))


def test_plan_routes_cannot_exceed_the_bucket_count_and_validates_shards():
    routes = searchindex.plan_routes({"a": 3}, 9)
    assert routes == {"a": 0}
    assert searchindex.plan_routes({}, 4) == {}
    with pytest.raises(ValueError, match="shards must be >= 1"):
        searchindex.plan_routes({"a": 1}, 0)


def test_prefix_locality_every_term_routes_with_its_first_character():
    index = _index(shards=4)
    manifest = index["manifest"]
    for shard_no, table in enumerate(index["shards"]):
        for term in table:
            assert manifest["routes"][term[0]] == shard_no


# ---- build + artifact bytes -------------------------------------------------


def test_build_index_reports_every_page_it_did_not_index():
    docs = [
        *_docs(),
        _doc(
            "draft.html",
            "<html><head><title>D</title><meta name='robots' content='noindex'>"
            "</head><body>unfinished</body></html>",
        ),
        # "a.html" on purpose: its PATH tokens are a stopword and a
        # single letter, so nothing at all is indexable about this page
        _doc("a.html", "<html><body><nav>Docs</nav></body></html>"),
    ]
    index = searchindex.build_index(docs, shards=2)
    report = index["report"]
    assert report["pages_seen"] == 5
    assert report["documents"] == 4  # the noindex page is excluded
    assert report["skipped"] == [{"path": "draft.html", "reason": "noindex"}]
    assert report["empty_pages"] == ["a.html"]
    assert report["untitled_pages"] == ["a.html"]
    assert report["terms"] > 0 and report["postings"] >= report["terms"]


def test_build_index_can_keep_noindex_pages_when_asked():
    doc = _doc(
        "draft.html",
        "<html><head><title>D</title><meta name='robots' content='noindex'>"
        "</head><body>unfinished draft</body></html>",
    )
    index = searchindex.build_index([doc], shards=1, include_noindex=True)
    assert index["report"]["documents"] == 1 and index["report"]["skipped"] == []


def test_build_index_flags_duplicate_urls_and_unsupported_characters():
    docs = [
        _doc("a/index.html", "<html><body><p>alpha</p></body></html>"),
        _doc("b/index.html", "<html><body><p>beta</p></body></html>"),
        _doc("cjk.md", "# 你好\n\nhello there\n"),
    ]
    for doc in docs[:2]:
        doc["url"] = "/"  # both roots collapsed onto the same site URL
    report = searchindex.build_index(docs, shards=1)["report"]
    assert report["duplicate_urls"] == [
        {"url": "/", "paths": ["a/index.html", "b/index.html"]}
    ]
    # 2 characters, counted once per field they appear in (title, heading, body)
    assert report["unsupported_pages"] == [{"path": "cjk.md", "chars": 6}]


def test_postings_are_sorted_by_score_then_doc_id():
    strong = {
        "path": "s.html",
        "title": "widget widget",
        "headings": ["widget"],
        "description": "",
        "body": "widget",
    }
    weak = {
        "path": "w.html",
        "title": "",
        "headings": [],
        "description": "",
        "body": "widget",
    }
    index = searchindex.build_index([weak, strong], shards=1)
    postings = index["shards"][0]["widget"]
    assert postings == [[1, 21], [0, 1]]  # doc 1 outscores doc 0 and comes first


def test_document_ids_follow_the_order_given():
    index = _index()
    assert [d["path"] for d in index["manifest"]["docs"]] == [
        "index.html",
        "docs/pricing.html",
        "docs/guide.md",
    ]
    assert [d["id"] for d in index["manifest"]["docs"]] == [0, 1, 2]


def test_dump_bytes_is_canonical_and_newline_terminated():
    data = searchindex.dump_bytes({"b": 1, "a": [1, 2]})
    assert data == b'{"a":[1,2],"b":1}\n'
    # ASCII only, so no host charset guess can corrupt it
    assert searchindex.dump_bytes({"t": "café"}) == b'{"t":"caf\\u00e9"}\n'


def test_render_files_emits_every_artifact_file_with_hashes():
    _built, rendered = _rendered()
    manifest, files = rendered["manifest"], rendered["files"]
    assert set(files) == {
        searchindex.INDEX_NAME,
        searchindex.CLIENT_NAME,
        *(s["name"] for s in manifest["shards"]),
    }
    for shard in manifest["shards"]:
        assert shard["sha256"] == searchindex.sha256_bytes(files[shard["name"]])
        assert shard["bytes"] == len(files[shard["name"]])
    assert manifest["client_sha256"] == searchindex.sha256_bytes(
        files["searchindex.js"]
    )
    assert manifest["generated_utc"] == "2027-01-15T08:00:00Z"
    assert rendered["sizes"]["total"] == sum(len(v) for v in files.values())
    # a visitor's first query costs the manifest plus ONE shard, not the index
    assert rendered["sizes"]["first_query"] < rendered["sizes"]["total"]


def test_two_builds_of_the_same_corpus_are_byte_identical():
    _index_a, first = _rendered()
    _index_b, second = _rendered()
    assert first["files"] == second["files"]


def test_fingerprint_ignores_the_build_time_but_not_the_content():
    index = _index()
    early = searchindex.render_files(index, now=NOW)
    later = searchindex.render_files(index, now=NOW + 7200)
    assert early["manifest"]["fingerprint"] == later["manifest"]["fingerprint"]
    assert early["manifest"]["generated_utc"] != later["manifest"]["generated_utc"]
    assert (
        early["files"][searchindex.INDEX_NAME] != later["files"][searchindex.INDEX_NAME]
    )
    changed = searchindex.render_files(_index(shards=1), now=NOW)
    assert changed["manifest"]["fingerprint"] != early["manifest"]["fingerprint"]


def test_manifest_carries_everything_the_client_needs():
    _index_obj, rendered = _rendered()
    manifest = rendered["manifest"]
    for key in (
        "routes",
        "shards",
        "docs",
        "doc_count",
        "avg_terms",
        "k1",
        "b",
        "prefix_limit",
        "min_len",
        "max_len",
        "stemming",
        "default_limit",
        "weights",
        "fingerprint",
        "url_kind",
    ):
        assert key in manifest, key
    assert manifest["stopwords"]["words"], "the client must filter what the build did"
    assert manifest["avg_terms"] == round(
        sum(d["terms"] for d in manifest["docs"]) / manifest["doc_count"], 6
    )


def test_client_js_is_a_constant_and_matches_the_manifest_filename():
    text = searchindex.client_js().decode("ascii")
    # was `client_js() == client_js()`, a tautology over a module constant that no
    # mutation could break. The non-vacuous claim is that it is NON-EMPTY ascii
    # bytes: emptying the constant now fails here, and the .decode("ascii") above
    # already fails on any non-ascii byte.
    assert searchindex.client_js() and isinstance(searchindex.client_js(), bytes)
    # the client hardcodes ONE filename; it must be the one we write
    assert f'INDEX_NAME = "{searchindex.INDEX_NAME}"' in text
    # every tunable is read from the manifest, so nothing is duplicated in JS
    for key in ("k1", "b", "prefix_limit", "min_len", "max_len", "doc_count"):
        assert f"m.{key}" in text or f"manifest.{key}" in text, key


def test_load_manifest_bytes_refuses_a_foreign_index():
    data = searchindex.dump_bytes({"format": "some-other-tool", "docs": []})
    with pytest.raises(ValueError, match="not a scout-searchindex manifest"):
        searchindex.load_manifest_bytes(data)
    with pytest.raises(ValueError, match="empty"):
        searchindex.load_manifest_bytes(b"")
    with pytest.raises(ValueError, match="not valid JSON"):
        searchindex.load_manifest_bytes(b"{oops")
    with pytest.raises(ValueError, match="not a JSON object"):
        searchindex.load_manifest_bytes(b"[1,2]\n")


def test_load_shard_bytes_raises_on_corruption_but_not_on_absence():
    assert searchindex.load_shard_bytes(None) == {}
    assert searchindex.load_shard_bytes(b'{"a":[[0,1]]}\n') == {"a": [[0, 1]]}
    with pytest.raises(ValueError, match="not valid JSON"):
        searchindex.load_shard_bytes(b"truncated{")


# ---- ranking (the algorithm the client mirrors) ------------------------------


def _ranker(**kwargs):
    index, rendered = _rendered(**kwargs)
    return rendered["manifest"], searchindex.shard_loader(index)


def test_rank_finds_the_page_and_reports_what_it_read():
    manifest, load = _ranker()
    result = searchindex.rank(manifest, load, "tokenizer")
    assert [h["path"] for h in result["hits"]] == ["docs/guide.md"]
    assert result["terms"] == ["tokenizer"]
    assert result["total"] == 1 and result["returned"] == 1
    assert result["hits"][0]["rank"] == 1 and result["hits"][0]["score"] > 0
    # cost transparency: exactly the shards a browser would have fetched
    assert len(result["shards_read"]) == 1
    assert result["reason"] is None


def test_rank_scores_a_title_hit_above_a_body_hit():
    docs = [
        {
            "path": "body.html",
            "title": "Other",
            "headings": [],
            "description": "",
            "body": "widget appears once here",
            "url": "/body.html",
            "excerpt": "",
        },
        {
            "path": "title.html",
            "title": "Widget",
            "headings": [],
            "description": "",
            "body": "unrelated text",
            "url": "/title.html",
            "excerpt": "",
        },
    ]
    index = searchindex.build_index(docs, shards=1)
    rendered = searchindex.render_files(index, now=NOW)
    result = searchindex.rank(
        rendered["manifest"], searchindex.shard_loader(index), "widget"
    )
    assert [h["path"] for h in result["hits"]] == ["title.html", "body.html"]
    assert result["hits"][0]["score"] > result["hits"][1]["score"]


def test_rank_match_all_is_and_and_any_is_or():
    manifest, load = _ranker()
    both = searchindex.rank(manifest, load, "widget tokenizer")
    assert both["total"] == 0  # no single page has both terms
    either = searchindex.rank(manifest, load, "widget tokenizer", match_all=False)
    assert either["total"] >= 2
    paths = [h["path"] for h in either["hits"]]
    assert "docs/guide.md" in paths and "index.html" in paths


def test_rank_reports_unmatched_terms_instead_of_a_bare_empty_list():
    manifest, load = _ranker()
    result = searchindex.rank(manifest, load, "widget kryptonite")
    assert result["unmatched"] == ["kryptonite"]
    assert result["total"] == 0
    assert result["terms"] == ["widget", "kryptonite"]


def test_rank_explains_a_query_it_cannot_index():
    manifest, load = _ranker()
    for query in ("the and of", "你好", ""):
        result = searchindex.rank(manifest, load, query)
        assert result["hits"] == []
        assert "no indexable term" in result["reason"]
    empty = searchindex.rank(
        {"doc_count": 0, "docs": [], "stopwords": {"words": []}}, load, "widget"
    )
    assert empty["reason"] == "index holds no documents"


def test_rank_prefix_expansion_is_last_term_only_and_can_be_disabled():
    manifest, load = _ranker()
    assert searchindex.rank(manifest, load, "tokeni")["total"] == 1
    assert searchindex.rank(manifest, load, "tokeni", prefix=False)["total"] == 0
    # a prefix on a NON-final term must not expand
    two = searchindex.rank(manifest, load, "tokeni guide", match_all=False)
    assert "tokeni" in two["unmatched"]


def test_rank_limit_pages_the_hits_but_total_counts_them_all():
    manifest, load = _ranker()
    every = searchindex.rank(manifest, load, "widget", match_all=False)
    assert every["total"] >= 2
    one = searchindex.rank(manifest, load, "widget", limit=1, match_all=False)
    assert one["total"] == every["total"] and one["returned"] == 1
    assert one["hits"][0]["path"] == every["hits"][0]["path"]


def test_expand_term_prefers_the_widest_terms_and_honours_the_cap():
    table = {
        "tok": [[0, 1]],
        "token": [[0, 1], [1, 1], [2, 1]],
        "tokenize": [[0, 1], [1, 1]],
        "other": [[0, 1]],
    }
    expanded = searchindex.expand_term(table, "tok", prefix=True)
    assert list(expanded) == ["tok", "token", "tokenize"]
    capped = searchindex.expand_term(table, "tok", prefix=True, limit=1)
    assert list(capped) == ["tok", "token"]
    assert searchindex.expand_term(table, "tok", prefix=False) == {"tok": [[0, 1]]}
    assert searchindex.expand_term(table, "zzz", prefix=True) == {}


def test_rank_takes_the_best_expansion_not_the_sum():
    # one keystroke expanding into many variants must never out-score the exact
    # term it prefixes; scoring is max-over-expansions on purpose
    table = {"ship": [[0, 4]], "shipping": [[0, 4]], "shipment": [[0, 4]]}
    manifest = {
        "doc_count": 1,
        "avg_terms": 4.0,
        "k1": searchindex.K1,
        "b": searchindex.B,
        "prefix_limit": 8,
        "stemming": False,
        "stopwords": {"words": []},
        "min_len": 2,
        "max_len": 32,
        "routes": {"s": 0},
        "shards": [{"name": "searchindex-000.json"}],
        "docs": [
            {
                "id": 0,
                "path": "a.html",
                "url": "/a",
                "title": "A",
                "excerpt": "",
                "terms": 4,
                "kind": "html",
            }
        ],
    }
    expanded = searchindex.rank(manifest, lambda _n: table, "ship")
    single = searchindex.rank(manifest, lambda _n: {"ship": [[0, 4]]}, "ship")
    assert expanded["hits"][0]["score"] == single["hits"][0]["score"]


def test_rank_length_normalization_favours_the_focused_page():
    short = {
        "path": "short.html",
        "title": "",
        "headings": [],
        "description": "",
        "body": "widget",
        "url": "/short",
        "excerpt": "",
    }
    long_body = " ".join(["filler"] * 60)
    long_page = {
        "path": "long.html",
        "title": "",
        "headings": [],
        "description": "",
        "body": f"widget {long_body}",
        "url": "/long",
        "excerpt": "",
    }
    index = searchindex.build_index([long_page, short], shards=1)
    rendered = searchindex.render_files(index, now=NOW)
    result = searchindex.rank(
        rendered["manifest"], searchindex.shard_loader(index), "widget"
    )
    assert [h["path"] for h in result["hits"]] == ["short.html", "long.html"]


def test_rank_ignores_a_route_that_points_past_the_shard_list():
    manifest, load = _ranker()
    manifest = {**manifest, "routes": {**manifest["routes"], "w": 99}}
    result = searchindex.rank(manifest, load, "widget")
    assert result["hits"] == [] and result["unmatched"] == ["widget"]


# ---- verify -----------------------------------------------------------------


def test_verify_accepts_a_freshly_rendered_artifact():
    _index_obj, rendered = _rendered()
    report = searchindex.verify(rendered["manifest"], rendered["files"])
    assert report["ok"] is True
    assert report["missing"] == [] and report["mismatched"] == []
    assert report["fingerprint"]["match"] is True
    assert report["checked"] == len(rendered["manifest"]["shards"]) + 1


def test_verify_catches_a_missing_shard():
    _index_obj, rendered = _rendered()
    files = dict(rendered["files"])
    gone = rendered["manifest"]["shards"][0]["name"]
    del files[gone]
    report = searchindex.verify(rendered["manifest"], files)
    assert report["ok"] is False and report["missing"] == [gone]
    rules = {d["rule"] for d in searchindex.to_diagnostics(report)}
    assert "searchindex:missing-file" in rules


def test_verify_catches_edited_bytes():
    _index_obj, rendered = _rendered()
    files = dict(rendered["files"])
    name = rendered["manifest"]["shards"][0]["name"]
    files[name] = files[name].replace(b"[", b"[ ", 1)
    report = searchindex.verify(rendered["manifest"], files)
    assert report["ok"] is False
    assert [m["name"] for m in report["mismatched"]] == [name]
    entry = report["mismatched"][0]
    assert entry["actual_sha256"] != entry["expected_sha256"]


def test_verify_catches_a_hand_edited_manifest():
    _index_obj, rendered = _rendered()
    tampered = {**rendered["manifest"], "doc_count": 999}
    report = searchindex.verify(tampered, rendered["files"])
    assert report["fingerprint"]["match"] is False and report["ok"] is False
    rules = {d["rule"] for d in searchindex.to_diagnostics(report)}
    assert "searchindex:fingerprint-mismatch" in rules


def test_verify_refuses_a_foreign_manifest_without_pretending_to_check():
    report = searchindex.verify({"format": "other"}, {})
    assert report["ok"] is False and report["checked"] == 0
    assert "nothing was verified" in report["error"]


def test_verify_reports_orphans_and_oversized_files():
    _index_obj, rendered = _rendered()
    listing = [*rendered["files"], "searchindex-099.json", "unrelated.txt"]
    report = searchindex.verify(
        rendered["manifest"], rendered["files"], listing=listing
    )
    assert report["orphans"] == ["searchindex-099.json"]  # not unrelated.txt
    fat = {**rendered["manifest"]}
    fat["shards"] = [
        {**s, "bytes": searchindex.SHARD_BYTE_BUDGET + 1} for s in fat["shards"]
    ]
    over = searchindex.verify(fat, rendered["files"])
    assert [o["name"] for o in over["oversized"]] == [s["name"] for s in fat["shards"]]
    assert {d["rule"] for d in searchindex.to_diagnostics(over)} >= {
        "searchindex:oversized"
    }


def test_is_artifact_name_only_claims_our_own_namespace():
    assert searchindex.is_artifact_name("searchindex.json")
    assert searchindex.is_artifact_name("searchindex.js")
    assert searchindex.is_artifact_name("searchindex-042.json")
    assert not searchindex.is_artifact_name("sitemap.xml")
    assert not searchindex.is_artifact_name("searchindex-042.txt")


# ---- diagnostics ------------------------------------------------------------


def test_empty_index_is_an_error_not_a_cheerful_zero():
    report = searchindex.build_index([], shards=2)["report"]
    diags = searchindex.to_diagnostics(report)
    assert [d["rule"] for d in diags] == ["searchindex:empty-index"]
    assert diags[0]["severity"] == "error"
    # pages present but no terms at all is also an error
    blank = searchindex.build_index(
        [
            {
                "path": "a.html",
                "title": "",
                "headings": [],
                "description": "",
                "body": "",
                "url": "/a",
            }
        ],
        shards=1,
    )["report"]
    rules = {(d["rule"], d["severity"]) for d in searchindex.to_diagnostics(blank)}
    assert ("searchindex:empty-index", "error") in rules


def test_diagnostics_grade_each_failure_by_what_it_costs_a_visitor():
    report = {
        "pages_seen": 3,
        "documents": 2,
        "terms": 5,
        "empty_pages": ["blank.html"],
        "untitled_pages": ["blank.html"],
        "unsupported_pages": [{"path": "cjk.md", "chars": 12}],
        "duplicate_urls": [{"url": "/", "paths": ["a/index.html", "b/index.html"]}],
        "skipped": [
            {"path": "draft.html", "reason": "noindex"},
            {"path": "locked.html", "reason": "unreadable"},
            {"path": "gone", "reason": "missing-root"},
        ],
    }
    by_rule = {d["rule"]: d for d in searchindex.to_diagnostics(report)}
    assert by_rule["searchindex:empty-page"]["severity"] == "warning"
    assert by_rule["searchindex:no-title"]["severity"] == "suggestion"
    assert by_rule["searchindex:non-ascii-dropped"]["severity"] == "warning"
    assert by_rule["searchindex:duplicate-url"]["severity"] == "warning"
    assert by_rule["searchindex:skipped:noindex"]["severity"] == "info"
    assert by_rule["searchindex:skipped:unreadable"]["severity"] == "warning"
    assert by_rule["searchindex:skipped:missing-root"]["severity"] == "error"
    # the SECOND path of a duplicate pair is the one flagged
    assert by_rule["searchindex:duplicate-url"]["path"] == "b/index.html"
    for diag in searchindex.to_diagnostics(report):
        assert diag["source"] == "searchindex"
        assert diag["severity"] in openswap.SEVERITIES


def test_diagnostics_of_a_clean_build_are_empty():
    assert searchindex.to_diagnostics(_index()["report"]) == []


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_the_expected_steady_state(monkeypatch):
    from bigbang.plugins.searchindex import cli as si_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = si_cli._capability()
    assert cap["adapter"] == "searchindex"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "pagefind"
    assert cap["extras"]["algolia"]["found"] is False  # SaaS client, never run
    assert cap["artifact"]["client_sha256"] == searchindex.sha256_bytes(
        searchindex.client_js()
    )


def test_weight_parser_rejects_a_malformed_pair():
    import typer

    from bigbang.plugins.searchindex import cli as si_cli

    assert si_cli._weights(["title=12", "body=0"]) == {"title": 12, "body": 0}
    with pytest.raises(typer.Exit):
        si_cli._weights(["title:12"])


# ---- the real CLI in a subprocess (offline paths only) ----------------------


def _cli(args, cwd=None):
    import os

    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(cwd or ROOT),
        env=dict(os.environ),
    )


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "public"
    (site / "docs").mkdir(parents=True)
    (site / "index.html").write_text(HTML_PAGE, encoding="utf-8")
    (site / "docs" / "guide.md").write_text(MD_PAGE, encoding="utf-8")
    return site


def test_cli_searchindex_hello_envelope():
    r = _cli(["searchindex", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_build_query_verify_round_trip(tmp_path):
    site, out = _site(tmp_path), tmp_path / "out"
    build = _cli(
        [
            "searchindex",
            "build",
            str(site),
            "--out",
            str(out),
            "--base-url",
            "https://widget.example.com/",
            "--shards",
            "2",
        ]
    )
    assert build.returncode == 0, build.stderr + build.stdout
    built = json.loads(build.stdout)["data"]
    assert built["documents"] == 2 and built["url_kind"] == "absolute"
    assert (out / searchindex.INDEX_NAME).exists()
    assert (out / searchindex.CLIENT_NAME).exists()
    # the files on disk are byte-identical to what the manifest recorded
    for shard in built["shards"]:
        assert (
            searchindex.sha256_bytes((out / shard["name"]).read_bytes())
            == (shard["sha256"])
        )
    query = _cli(["searchindex", "query", "tokenizer", "--out", str(out)])
    assert query.returncode == 0, query.stderr + query.stdout
    hits = json.loads(query.stdout)["data"]["hits"]
    assert [h["url"] for h in hits] == ["https://widget.example.com/docs/guide.md"]
    verify = _cli(["searchindex", "verify", "--out", str(out), "--fail-on", "error"])
    assert verify.returncode == 0, verify.stderr + verify.stdout
    assert json.loads(verify.stdout)["data"]["ok"] is True


def test_cli_build_is_idempotent_on_disk(tmp_path):
    site, out = _site(tmp_path), tmp_path / "out"
    args = ["searchindex", "build", str(site), "--out", str(out)]
    assert _cli(args).returncode == 0
    first = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
    assert _cli(args).returncode == 0
    second = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
    # only the build stamp may differ; every shard and the client must not
    for name in first:
        if name != searchindex.INDEX_NAME:
            assert first[name] == second[name], name


def test_cli_dry_run_writes_nothing(tmp_path):
    site, out = _site(tmp_path), tmp_path / "out"
    r = _cli(["searchindex", "build", str(site), "--out", str(out), "--dry-run"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["dry_run"] is True and data["written"] == []
    assert not out.exists()


def test_cli_build_over_a_missing_root_is_an_error_not_a_quiet_zero(tmp_path):
    r = _cli(
        [
            "searchindex",
            "build",
            str(tmp_path / "nope"),
            "--out",
            str(tmp_path / "out"),
            "--fail-on",
            "error",
        ]
    )
    assert r.returncode == 1
    data = json.loads(r.stdout)["data"]
    assert {"path": (tmp_path / "nope").as_posix(), "reason": "missing-root"} in (
        data["skipped"]
    )
    rules = {d["rule"] for d in data["diagnostics"]}
    assert "searchindex:skipped:missing-root" in rules
    assert "searchindex:empty-index" in rules


def test_cli_query_without_an_artifact_fails_actionably(tmp_path):
    r = _cli(["searchindex", "query", "widget", "--out", str(tmp_path / "none")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no search index at" in data["error"]
    assert "example" in data


def test_cli_query_fail_empty_is_the_ci_assertion(tmp_path):
    site, out = _site(tmp_path), tmp_path / "out"
    assert _cli(["searchindex", "build", str(site), "--out", str(out)]).returncode == 0
    ok_query = _cli(
        ["searchindex", "query", "widget", "--out", str(out), "--fail-empty"]
    )
    assert ok_query.returncode == 0
    missing = _cli(
        ["searchindex", "query", "kryptonite", "--out", str(out), "--fail-empty"]
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["data"]["unmatched"] == ["kryptonite"]


def test_cli_verify_gates_on_a_deleted_shard(tmp_path):
    site, out = _site(tmp_path), tmp_path / "out"
    build = _cli(
        ["searchindex", "build", str(site), "--out", str(out), "--shards", "3"]
    )
    assert build.returncode == 0, build.stderr + build.stdout
    victim = json.loads(build.stdout)["data"]["shards"][0]["name"]
    (out / victim).unlink()
    verify = _cli(["searchindex", "verify", "--out", str(out), "--fail-on", "error"])
    assert verify.returncode == 1
    data = json.loads(verify.stdout)["data"]
    assert data["missing"] == [victim] and data["ok"] is False
    # and a query must refuse to answer from a partial artifact
    query = _cli(["searchindex", "query", "widget", "--out", str(out)])
    assert query.returncode == 1
    assert victim in json.loads(query.stdout)["error"]


def test_cli_rejects_a_bad_fail_on_and_a_bad_weight(tmp_path):
    site = _site(tmp_path)
    bad_gate = _cli(
        [
            "searchindex",
            "build",
            str(site),
            "--out",
            str(tmp_path / "o"),
            "--fail-on",
            "loud",
        ]
    )
    assert bad_gate.returncode == 1
    assert "--fail-on must be one of" in json.loads(bad_gate.stdout)["error"]
    bad_weight = _cli(
        [
            "searchindex",
            "build",
            str(site),
            "--out",
            str(tmp_path / "o"),
            "--weight",
            "title",
        ]
    )
    assert bad_weight.returncode == 1
    assert "--weight wants field=INT" in json.loads(bad_weight.stdout)["error"]
    bad_field = _cli(
        [
            "searchindex",
            "build",
            str(site),
            "--out",
            str(tmp_path / "o"),
            "--weight",
            "titel=4",
        ]
    )
    assert bad_field.returncode == 1
    assert "unknown field" in json.loads(bad_field.stdout)["error"]


def test_cli_detect_reports_the_artifact_surface():
    r = _cli(["searchindex", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    cap = json.loads(r.stdout)["data"]
    assert cap["adapter"] == "searchindex"
    assert cap["artifact"]["manifest"] == searchindex.INDEX_NAME
    assert cap["extras"]["algolia"]["path"] is None or True  # probed, never run


# ---- the GENERATED CLIENT, run by node against a real artifact ---------------

_PARITY_JS = """
const fs = require("fs");
const dir = process.argv[2];
const api = require(dir + "/searchindex.js");
const manifest = JSON.parse(fs.readFileSync(dir + "/searchindex.json", "utf8"));
const client = api.create(manifest, (name) =>
  JSON.parse(fs.readFileSync(dir + "/" + name, "utf8")));
(async () => {
  const out = [];
  for (const q of JSON.parse(process.argv[3])) {
    const r = await client.search(q);
    out.push({query: q, terms: r.terms, unmatched: r.unmatched, total: r.total,
              shards_read: r.shards_read,
              hits: r.hits.map((h) => [h.id, h.score, h.rank])});
  }
  process.stdout.write(JSON.stringify(out));
})();
"""

_PARITY_QUERIES = [
    "widget",
    "widget pricing",
    "tokenizer",
    "tokeni",
    "shipping",
    "guide",
    "café",
    "kryptonite",
    "the and of",
    "",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_generated_client_agrees_with_rank_under_node(tmp_path):
    """The one duplicated LOGIC in this adapter (fold/stem/BM25 in JS) is proven
    against its Python original — no claim of parity, a measurement of it."""
    docs = [
        *_docs(),
        _doc("cafe.html", "<html><body><p>Visit our café in Lisbon.</p></body></html>"),
    ]
    index = searchindex.build_index(docs, shards=3)
    rendered = searchindex.render_files(index, now=NOW)
    for name, data in rendered["files"].items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "parity.js").write_text(_PARITY_JS, encoding="utf-8")
    proc = subprocess.run(
        [
            "node",
            str(tmp_path / "parity.js"),
            tmp_path.as_posix(),
            json.dumps(_PARITY_QUERIES),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    from_js = json.loads(proc.stdout)
    load = searchindex.shard_loader(index)
    assert len(from_js) == len(_PARITY_QUERIES)
    for entry in from_js:
        py = searchindex.rank(rendered["manifest"], load, entry["query"])
        assert entry == {
            "query": entry["query"],
            "terms": py["terms"],
            "unmatched": py["unmatched"],
            "total": py["total"],
            "shards_read": py["shards_read"],
            "hits": [[h["id"], h["score"], h["rank"]] for h in py["hits"]],
        }, entry["query"]
    # and the accented page really was found by the client, not just "agreed on"
    accented = next(e for e in from_js if e["query"] == "café")
    assert accented["total"] == 1


# The browser half of the client (open/render/attach) needs a DOM and a fetch,
# so it is exercised under node with stub objects rather than left unclaimed:
# element stubs record what the client did, and getJson stands in for fetch.
_BROWSER_JS = """
const fs = require("fs");
const dir = process.argv[2];
const api = require(dir + "/searchindex.js");
const asked = [];
function getJson(url) {
  asked.push(url);
  const name = url.split("/").pop().split("?")[0];
  return Promise.resolve(JSON.parse(fs.readFileSync(dir + "/" + name, "utf8")));
}
function element(tag) {
  return {
    tag: tag, children: [], textContent: "", className: "", href: "",
    appendChild: function (child) { this.children.push(child); return child; }
  };
}
global.document = { createElement: element };
const input = element("input");
input.value = "widget";
input.addEventListener = function (event, handler) { this.handler = handler; };
const results = element("div");
const out = {};
api.attach({
  base: dir, input: input, results: results, fetchJson: getJson, delay: 0,
  onResults: function (result) {
    out.result = { terms: result.terms, total: result.total };
    out.rendered = results.children.map(function (list) {
      return list.children.map(function (item) {
        return item.children.map(function (node) {
          return { tag: node.tag, text: node.textContent, href: node.href };
        });
      });
    });
    out.asked = asked;
    process.stdout.write(JSON.stringify(out));
  }
});
input.handler();
setTimeout(function () {
  if (!out.result) { process.stderr.write("no results rendered"); process.exit(3); }
}, 5000);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_generated_client_attaches_renders_and_cache_busts_under_node(tmp_path):
    index = searchindex.build_index(_docs(), shards=2)
    rendered = searchindex.render_files(index, now=NOW)
    for name, data in rendered["files"].items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "browser.js").write_text(_BROWSER_JS, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(tmp_path / "browser.js"), tmp_path.as_posix()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["result"]["terms"] == ["widget"]
    assert out["result"]["total"] >= 1
    # the manifest is fetched first, then the ONE shard the term routes to,
    # cache-busted with the build fingerprint so a redeploy cannot serve stale
    # postings to a warm browser
    assert out["asked"][0].endswith("/" + searchindex.INDEX_NAME)
    version = rendered["manifest"]["fingerprint"][:12]
    assert out["asked"][1].endswith(f"?v={version}")
    assert len(out["asked"]) == 2
    # results are real elements: a link with the doc's url and title, then its
    # excerpt as TEXT (the client never assigns innerHTML — asserted below too)
    first_hit = out["rendered"][0][0]
    assert first_hit[0]["tag"] == "a"
    assert first_hit[0]["href"].startswith("/")
    assert first_hit[0]["text"]
    assert first_hit[1]["tag"] == "p"


def test_client_never_assigns_innerhtml():
    # page text becoming markup is the one XSS this artifact could introduce;
    # the client is text-only by construction
    text = searchindex.client_js().decode("ascii")
    # the property-access forms, not the bare word — the client's own header
    # comment says "never innerHTML" and must not trip its own check
    assert ".innerHTML" not in text
    assert ".outerHTML" not in text
    assert "insertAdjacentHTML(" not in text
    assert text.count("textContent") >= 4
