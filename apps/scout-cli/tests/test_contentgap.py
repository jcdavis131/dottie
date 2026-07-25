"""Contentgap — openswap #24 (Clearscope/Surfer/MarketMuse -> stdlib TF-IDF over a
local corpus of comparison pages). Pure-logic core tests (tokenizer, sublinear tf,
smoothed idf, density-normalized expectations, missing/thin/overused
classification, the coverage reading), the honesty invariants (an unusable corpus
file is labelled, an unmeasurable score carries a reason instead of a 0.0), the
markdown brief, and the real CLI in a subprocess.

Offline and deterministic by construction: every input is a string literal or a
tmp_path file, the corpus is never fetched, and the expected weights are written
out as formulas here rather than copied from a previous run."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import contentgap, openswap

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "bigbang" / "core" / "contentgap.py"

# The reference two-document corpus. Small enough that every weight below is
# hand-derivable: doc a = 3 tokens, doc b = 2 tokens, N = 2.
DOC_A = {"name": "a.txt", "text": "alpha alpha beta"}
DOC_B = {"name": "b.txt", "text": "alpha gamma"}


def _model(*docs, **kw):
    return contentgap.build_corpus(list(docs) or [DOC_A, DOC_B], **kw)


def _weights(model):
    return {row["term"]: row["weight"] for row in contentgap.corpus_terms(model)}


def _by_status(report):
    return {row["term"]: row["status"] for row in report["targets"]}


def _row(report, term):
    return next(row for row in report["targets"] if row["term"] == term)


# ---- the architectural invariant: this core cannot reach the network ---------


def test_core_imports_nothing_that_could_fetch():
    # zero egress is the product, so it is asserted on the source, not promised
    src = CORE_SRC.read_text(encoding="utf-8")
    for banned in ("import socket", "import urllib", "import httpx", "import http"):
        assert banned not in src
    assert "subprocess" not in src


# ---- tokenizer --------------------------------------------------------------


def test_normalize_token_casefolds_and_drops_possessive():
    assert contentgap.normalize_token("Trainer's") == "trainer"
    assert contentgap.normalize_token("GPU’s") == "gpu"
    assert contentgap.normalize_token("BF16") == "bf16"
    # a token that is only joiner characters normalizes to empty and is dropped
    assert contentgap.normalize_token("-'-") == ""


def test_token_segments_keep_internal_punctuation_and_split_underscores():
    segs = contentgap.token_segments("Don't ship GPU-bound code_paths TODAY")
    assert segs == [["don't", "ship", "gpu-bound", "code", "paths", "today"]]


def test_token_segments_are_per_line_and_drop_blank_lines():
    segs = contentgap.token_segments("alpha beta\n\n   \ngamma")
    assert segs == [["alpha", "beta"], ["gamma"]]
    assert contentgap.token_count(segs) == 3


def test_token_count_includes_stopwords_because_it_is_the_document_length():
    # length drives density normalization; filtering it would inflate every rate
    assert contentgap.token_count(contentgap.token_segments("the alpha of beta")) == 4


def test_markdown_code_fences_and_urls_never_become_terms():
    text = "# Real heading\n\n```\nsecretsauce gpu\n```\n\nSee https://example.com/gpu now"
    segs = contentgap.token_segments(text, fmt=contentgap.FORMAT_MARKDOWN)
    flat = [t for seg in segs for t in seg]
    assert "secretsauce" not in flat
    assert "example" not in flat and "gpu" not in flat
    assert flat == ["real", "heading", "see", "now"]


def test_html_script_and_style_never_become_terms():
    html = (
        "<html><head><style>.a{color:red}</style></head>"
        "<body><p>Visible prose here</p><script>var stolen = 1;</script></body></html>"
    )
    flat = [
        t for seg in contentgap.token_segments(html, fmt=contentgap.FORMAT_HTML) for t in seg
    ]
    assert flat == ["visible", "prose", "here"]
    assert "stolen" not in flat and "color" not in flat


def test_is_term_rejects_stopwords_digits_and_short_tokens():
    assert contentgap.is_term("retrieval")
    assert contentgap.is_term("ai")
    assert not contentgap.is_term("the")
    assert not contentgap.is_term("2026")  # a bare number is not a topic term
    assert contentgap.is_term("bf16")  # but an alphanumeric token is
    assert not contentgap.is_term("a")
    assert not contentgap.is_term("ai", min_length=3)


def test_stopwords_contain_no_topical_words():
    # a topical word in the list would silently censor a subject area forever
    for word in (
        "gpu",
        "retrieval",
        "training",
        "content",
        "model",
        "index",
        "chunking",
        "recall",
        "latency",
        "cache",
        "best",
        "new",
    ):
        assert word not in contentgap.STOPWORDS
    # and it really is doing its job on the function words
    for word in ("the", "of", "and", "however", "everything", "toward"):
        assert word in contentgap.STOPWORDS


def test_phrase_terms_need_two_adjacent_terms_and_never_bridge_a_stopword():
    assert contentgap.phrase_terms(["state", "of", "the", "art"]) == []
    assert contentgap.phrase_terms(["vector", "index", "recall"]) == [
        "vector index",
        "index recall",
    ]


def test_phrases_never_span_a_segment_boundary():
    counts = contentgap.term_counts(contentgap.token_segments("alpha\nbeta"))
    assert "alpha beta" not in counts
    assert contentgap.term_counts(contentgap.token_segments("alpha beta"))["alpha beta"] == 1


def test_term_counts_phrase_toggle_and_frequencies():
    segs = contentgap.token_segments("alpha alpha beta")
    with_phrases = contentgap.term_counts(segs)
    assert with_phrases["alpha"] == 2
    assert with_phrases["alpha alpha"] == 1 and with_phrases["alpha beta"] == 1
    without = contentgap.term_counts(segs, phrases=False)
    assert without["alpha"] == 2
    assert all(" " not in term for term in without)


# ---- weighting --------------------------------------------------------------


def test_tf_weight_is_sublinear():
    assert contentgap.tf_weight(0) == 0.0
    assert contentgap.tf_weight(1) == 1.0
    assert contentgap.tf_weight(4) == 1.0 + math.log(4)
    # the whole point: 90 mentions on one page must not outweigh 2 mentions on
    # 40 pages, so tf must grow far slower than the raw count
    assert contentgap.tf_weight(90) < 5.6
    assert contentgap.tf_weight(90) > contentgap.tf_weight(89)


def test_idf_keeps_a_universal_term_at_weight_one():
    assert contentgap.idf(3, 3) == 1.0  # in every page -> still counts fully
    assert contentgap.idf(1, 3) == math.log(4 / 2) + 1.0
    assert contentgap.idf(1, 3) > contentgap.idf(2, 3) > contentgap.idf(3, 3)
    with pytest.raises(ValueError):
        contentgap.idf(1, 0)


def test_build_corpus_weights_and_rates_are_exact():
    model = _model()
    assert model["n_docs"] == 2 and model["tokens"] == 5
    weights = _weights(model)
    alpha_idf = math.log(3 / 3) + 1.0  # df 2 of N 2
    beta_idf = math.log(3 / 2) + 1.0  # df 1 of N 2
    assert weights["alpha"] == round(((1 + math.log(2)) + 1.0) * alpha_idf / 2, 4)
    assert weights["beta"] == round(1.0 * beta_idf / 2, 4)
    terms = model["terms"]
    assert terms["alpha"]["doc_freq"] == 2 and terms["alpha"]["count"] == 3
    assert terms["alpha"]["coverage"] == 1.0
    assert terms["alpha"]["rate"] == 3 / 5  # occurrences per corpus token
    assert terms["beta"]["coverage"] == 0.5
    assert model["documents"][0] == {
        "name": "a.txt",
        # 3 unigram instances + 2 bigrams ("alpha alpha", "alpha beta")
        "tokens": 3,
        "term_instances": 5,
        "unique_terms": 4,
        "error": None,
    }


def test_sublinear_tf_stops_one_stuffed_page_outvoting_the_consensus():
    # the documented case: 9 of 10 pages use "consensus" twice, one page shouts
    # "shout" 90 times. Sublinear tf must keep the consensus term on top.
    docs = [{"name": "stuffed", "text": "shout " * 90}]
    docs += [{"name": str(i), "text": "consensus filler consensus"} for i in range(9)]
    weights = _weights(_model(*docs))
    assert weights["consensus"] > weights["shout"]
    # with LINEAR tf the same corpus inverts by more than 10x — that inversion is
    # exactly what the log() in tf_weight buys, computed here independently
    linear_shout = 90 * contentgap.idf(1, 10) / 10
    linear_consensus = 9 * 2 * contentgap.idf(9, 10) / 10
    assert linear_shout > linear_consensus * 10


def test_build_corpus_labels_every_unusable_document_and_excludes_it():
    clean = _model()
    dirty = _model(
        DOC_A,
        DOC_B,
        {"name": "big.md", "text": None, "error": "too-large: 9000 KB > --max-kb 2048"},
        {
            "name": "empty.md",
            "text": "\n\n```\ncode()\n```\n",
            "format": contentgap.FORMAT_MARKDOWN,
        },
        {"name": "nothing.md"},
    )
    assert dirty["n_docs"] == 2 and dirty["tokens"] == clean["tokens"]
    # every weight is identical to the clean corpus: skipped docs move nothing
    assert _weights(dirty) == _weights(clean)
    reasons = {s["name"]: s["error"] for s in dirty["skipped"]}
    assert set(reasons) == {"big.md", "empty.md", "nothing.md"}
    assert reasons["big.md"].startswith("too-large")
    assert reasons["empty.md"] == "no words found after markup extraction"
    assert reasons["nothing.md"] == "no text supplied for this document"


def test_corpus_terms_ranked_by_weight_then_alphabetically():
    rows = contentgap.corpus_terms(_model())
    assert rows[0]["term"] == "alpha"
    weights = [r["weight"] for r in rows]
    assert weights == sorted(weights, reverse=True)
    tied = [r["term"] for r in rows if r["weight"] == weights[-1]]
    assert tied == sorted(tied)
    assert len(contentgap.corpus_terms(_model(), limit=2)) == 2
    assert contentgap.corpus_terms(_model(), limit=0) == []
    # A NEGATIVE limit must also yield nothing. limit=0 above cannot pin this:
    # `rows[:0]` is [] with or without the `max(0, limit)` guard, so the guard was
    # untested and a mutation dropping it survived the whole suite. It is reachable —
    # `--top` is a plain int typer Option with no min=, so `--top -3` reaches here,
    # and `rows[:-3]` would silently return all-but-the-last-three ranked terms.
    assert contentgap.corpus_terms(_model(), limit=-3) == []
    # same guard, same blind spot, at the second site (draft_counts is a Counter/dict
    # of term -> count; the term must be absent from the corpus model to produce a row)
    assert contentgap.draft_only_terms({"notacorpusterm": 3}, _model(), limit=-3) == []
    assert contentgap.draft_only_terms({"notacorpusterm": 3}, _model(), limit=1) != []


# ---- readings: a value or a reason, never both, never neither ---------------


def test_reading_demands_exactly_one_of_value_or_error():
    assert contentgap.reading(4.5) == {"value": 4.5, "error": None}
    assert contentgap.reading(error="no corpus") == {"value": None, "error": "no corpus"}
    with pytest.raises(ValueError):
        contentgap.reading(4.5, error="also broken")
    with pytest.raises(ValueError):
        contentgap.reading()


# ---- classification ---------------------------------------------------------


def test_expected_count_is_density_normalized():
    assert contentgap.expected_count(0.05, 400) == 20.0
    assert contentgap.expected_count(0.05, 40) == 2.0  # short draft, small ask
    assert contentgap.expected_count(0.05, 0) == 0.0
    # Negative token counts clamp to 0 rather than producing a negative expectation.
    # token_count() cannot go negative, so this guard is unreachable via the normal
    # flow — but expected_count is a PUBLIC function taking a plain int, so its
    # contract is worth stating. Pinning it beats deleting a correct guard just to
    # satisfy a mutation score. (limit=0 above cannot distinguish it: 0.05 * 0 and
    # 0.05 * max(0, 0) are both 0.0.)
    assert contentgap.expected_count(0.05, -100) == 0.0


def test_minimum_count_never_drops_below_one():
    assert contentgap.minimum_count(0.2, 0.5) == 1
    assert contentgap.minimum_count(10.0, 0.5) == 5
    assert contentgap.minimum_count(9.0, 0.5) == 5  # ceil, not floor
    # a zero product must still ask for one mention: "add 0+ mentions" is not an
    # instruction, and this is the only path where the max(1, ...) is load-bearing
    assert contentgap.minimum_count(0.0, 0.5) == 1
    assert contentgap.minimum_count(50.0, 0.0) == 1
    with pytest.raises(ValueError):
        contentgap.minimum_count(1.0, -0.5)


def test_an_empty_draft_still_gets_actionable_minimums():
    report = contentgap.analyze("", _model(), top=6)
    assert report["draft_tokens"] == 0
    assert all(row["expected"] == 0.0 for row in report["targets"])
    assert all(row["minimum"] == 1 for row in report["targets"])
    assert report["coverage_score"]["value"] == 0.0
    missing = [
        d for d in contentgap.to_diagnostics(report) if d["rule"] == "contentgap:missing"
    ]
    assert len(missing) == 6
    assert all("1+ mentions" in d["suggestion"] for d in missing)


def test_classify_covers_every_status_with_explicit_credit():
    assert contentgap.classify(0, 4.0) == (contentgap.STATUS_MISSING, 0.0)
    assert contentgap.classify(1, 10.0) == (contentgap.STATUS_THIN, 0.2)
    # exactly at the floor is covered, not thin
    assert contentgap.classify(5, 10.0) == (contentgap.STATUS_COVERED, 1.0)
    assert contentgap.classify(2, 1.0) == (contentgap.STATUS_COVERED, 1.0)
    assert contentgap.classify(9, 1.0) == (contentgap.STATUS_OVERUSED, 1.0)


def test_overuse_needs_both_the_ratio_and_the_floor():
    # 2 mentions against an expectation of 0.2 is 10x but far too few mentions to
    # call stuffing — the floor is what stops that false positive
    assert contentgap.classify(2, 0.2)[0] == contentgap.STATUS_COVERED
    assert contentgap.classify(4, 0.2)[0] == contentgap.STATUS_OVERUSED
    assert contentgap.classify(9, 1.0, over_ratio=0)[0] == contentgap.STATUS_COVERED
    assert contentgap.classify(9, 1.0, over_floor=20)[0] == contentgap.STATUS_COVERED


def test_classify_thin_window_follows_thin_ratio():
    assert contentgap.classify(4, 10.0, thin_ratio=0.2)[0] == contentgap.STATUS_COVERED
    assert contentgap.classify(4, 10.0, thin_ratio=0.9)[0] == contentgap.STATUS_THIN


# ---- analyze ----------------------------------------------------------------


def test_analyze_scores_and_classifies_against_the_reference_corpus():
    model = _model()
    report = contentgap.analyze("alpha beta", model, path="draft.txt", top=6)
    assert report["draft_tokens"] == 2 and report["draft_terms"] == 3
    statuses = _by_status(report)
    assert statuses["alpha"] == contentgap.STATUS_COVERED
    assert statuses["beta"] == contentgap.STATUS_COVERED
    assert statuses["alpha beta"] == contentgap.STATUS_COVERED
    assert statuses["gamma"] == contentgap.STATUS_MISSING
    assert statuses["alpha gamma"] == contentgap.STATUS_MISSING
    weights = _weights(model)
    covered = weights["alpha"] + weights["beta"] + weights["alpha beta"]
    total = sum(weights[r["term"]] for r in report["targets"])
    assert report["coverage_score"]["value"] == round(100.0 * covered / total, 2)
    assert report["counts"][contentgap.STATUS_MISSING] == 3
    assert sum(report["counts"].values()) == len(report["targets"]) == 6
    assert report["corpus"]["documents"] == ["a.txt", "b.txt"]


def test_analyze_full_coverage_scores_one_hundred():
    model = _model()
    report = contentgap.analyze("alpha alpha beta alpha gamma", model, top=6)
    assert report["coverage_score"]["value"] == 100.0
    assert report["weighted_gap"]["value"] == 0.0
    assert report["counts"][contentgap.STATUS_MISSING] == 0


def test_analyze_expectations_scale_with_draft_length():
    model = _model({"name": "d", "text": "alpha " * 5 + "beta " * 5})
    short = contentgap.analyze("alpha", model, top=1)
    long = contentgap.analyze("alpha " + "filler " * 39, model, top=1)
    assert short["targets"][0]["expected"] == 0.5
    assert long["targets"][0]["expected"] == 20.0
    # same single mention: fine in a 1-word draft, thin in a 40-word one
    assert short["targets"][0]["status"] == contentgap.STATUS_COVERED
    assert long["targets"][0]["status"] == contentgap.STATUS_THIN
    assert long["targets"][0]["minimum"] == 10
    assert long["targets"][0]["credit"] == 0.1
    assert 0 < long["coverage_score"]["value"] < 100


def test_analyze_flags_over_optimization():
    # the corpus mentions "alpha" once in 20 words; the draft says it 10 times
    model = _model({"name": "d", "text": "alpha " + "filler " * 19})
    report = contentgap.analyze("alpha " * 10 + "filler " * 10, model, top=6)
    row = _row(report, "alpha")
    assert row["draft_count"] == 10
    assert row["expected"] == 1.0 and row["status"] == contentgap.STATUS_OVERUSED
    # stuffing is reported, but it never inflates or deflates coverage
    assert report["coverage_score"]["value"] == 100.0
    assert report["counts"][contentgap.STATUS_OVERUSED] == 1


def test_analyze_reports_draft_only_terms():
    report = contentgap.analyze("alpha pixiedust pixiedust", _model(), top=6)
    only = {r["term"]: r["draft_count"] for r in report["draft_only"]}
    assert only["pixiedust"] == 2
    assert "alpha" not in only
    assert report["draft_only"][0]["term"] == "pixiedust"  # ranked by count


def test_analyze_without_a_usable_corpus_is_unmeasured_not_zero():
    model = _model({"name": "empty.md", "text": ""})
    report = contentgap.analyze("alpha beta", model, top=6)
    assert model["n_docs"] == 0 and report["targets"] == []
    for metric in ("coverage_score", "weighted_gap"):
        assert report[metric]["value"] is None
        assert "no usable corpus document" in report[metric]["error"]
        assert "no words found after markup extraction" in report[metric]["error"]


def test_analyze_min_length_is_carried_from_the_corpus_model():
    model = _model(min_length=6)
    report = contentgap.analyze("alpha beta", model, top=6)
    assert report["corpus"]["min_length"] == 6
    # "alpha"/"beta" are too short to be terms at all -> nothing to score
    assert report["coverage_score"]["value"] is None
    assert "no scorable term" in report["coverage_score"]["error"]


# ---- family diagnostic schema ----------------------------------------------


def test_to_diagnostics_maps_each_status_to_its_severity():
    report = contentgap.analyze("alpha beta", _model(), path="draft.txt", top=6)
    diags = contentgap.to_diagnostics(report)
    by_rule = {}
    for d in diags:
        by_rule.setdefault(d["rule"], []).append(d)
    assert len(by_rule["contentgap:missing"]) == 3
    assert all(d["severity"] == "warning" for d in by_rule["contentgap:missing"])
    assert by_rule["contentgap:coverage"][0]["severity"] == "warning"
    assert all(d["path"] == "draft.txt" and d["line"] == 0 for d in diags)
    assert all(d["source"] == "tfidf" for d in diags)
    assert diags == openswap.sort_diagnostics(diags)
    summary = openswap.summarize(diags)
    assert summary["total"] == len(diags)
    assert summary["by_severity"]["warning"] == 4


def test_to_diagnostics_thin_is_a_suggestion_and_overuse_a_warning():
    model = _model({"name": "d", "text": "alpha " * 5 + "beta " * 5})
    thin = contentgap.to_diagnostics(
        contentgap.analyze("alpha " + "filler " * 39, model, top=1)
    )
    assert [d["rule"] for d in thin if d["rule"] != "contentgap:coverage"] == [
        "contentgap:thin"
    ]
    assert [d["severity"] for d in thin if d["rule"] == "contentgap:thin"] == [
        "suggestion"
    ]
    sparse = _model({"name": "d", "text": "alpha " + "filler " * 19})
    over = [
        d
        for d in contentgap.to_diagnostics(
            contentgap.analyze("alpha " * 10 + "filler " * 10, sparse, top=6)
        )
        if d["rule"] == "contentgap:overused"
    ]
    assert len(over) == 1
    assert over[0]["severity"] == "warning"
    assert "over-optimization" in over[0]["message"]
    assert "cut" in over[0]["suggestion"]


def test_to_diagnostics_is_silent_when_the_draft_is_at_target():
    report = contentgap.analyze("alpha alpha beta alpha gamma", _model(), top=6)
    assert contentgap.to_diagnostics(report) == []


def test_to_diagnostics_turns_an_unmeasurable_score_into_an_error():
    report = contentgap.analyze("alpha", _model({"name": "e", "text": ""}), top=6)
    diags = contentgap.to_diagnostics(report)
    assert [d["rule"] for d in diags] == ["contentgap:unmeasured"]
    assert diags[0]["severity"] == "error"
    assert "not measured" in diags[0]["message"]


def test_gap_messages_carry_the_numbers_a_writer_needs():
    report = contentgap.analyze("alpha beta", _model(), path="d.md", top=6)
    missing = [
        d for d in contentgap.to_diagnostics(report) if d["rule"] == "contentgap:missing"
    ]
    msg = next(d["message"] for d in missing if "'gamma'" in d["message"])
    assert "comparison page(s)" in msg and "expected" in msg
    assert all("cover '" in d["suggestion"] for d in missing)


# ---- the brief --------------------------------------------------------------


def test_render_brief_is_deterministic_lf_only_markdown():
    report = contentgap.analyze("alpha beta", _model(), path="draft.txt", top=6)
    first = contentgap.render_brief(report, title="Brief A")
    assert first == contentgap.render_brief(report, title="Brief A")
    assert "\r" not in first
    assert first.startswith("# Brief A\n")
    assert first.endswith("\n")
    assert "| term | status | weight | pages | expected | min | in draft |" in first
    assert "## Add (missing)" in first
    assert "| gamma | missing |" in first
    assert "coverage score: **" in first


def test_render_brief_states_when_a_score_was_not_measured():
    report = contentgap.analyze("alpha", _model({"name": "e", "text": ""}), top=6)
    page = contentgap.render_brief(report)
    assert "coverage score: NOT MEASURED" in page
    assert "no usable corpus document" in page


def test_render_brief_lists_skipped_corpus_files_and_draft_only_terms():
    model = _model(DOC_A, DOC_B, {"name": "x.md", "text": None, "error": "too-large: 1 KB"})
    page = contentgap.render_brief(contentgap.analyze("alpha pixiedust", model, top=6))
    assert "## Corpus files skipped (not counted)" in page
    assert "`x.md` — too-large: 1 KB" in page
    assert "## In the draft, in no comparison page" in page
    assert "- pixiedust (1x)" in page


# ---- the real CLI in a subprocess (offline — the manifest denies network) ----


def _cli(args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        input=stdin,
        cwd=str(ROOT),
    )


def _data(res):
    assert res.returncode == 0, res.stderr + res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    return payload["data"]


def _corpus(tmp_path):
    """A three-page corpus on disk — markdown, HTML and text."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "p1.md").write_text(
        "# Retrieval augmented generation\n\nChunking drives recall. Reranking fixes"
        " the tail.\n\n```\nstuffed stuffed stuffed\n```\n",
        encoding="utf-8",
    )
    (corpus / "p2.html").write_text(
        "<html><body><p>Retrieval augmented generation needs chunking and"
        " reranking to hold recall.</p><script>var stuffed=1;</script></body></html>",
        encoding="utf-8",
    )
    (corpus / "p3.txt").write_text(
        "Chunking, reranking and recall are the retrieval knobs that matter.\n",
        encoding="utf-8",
    )
    return corpus


def test_cli_contentgap_hello_envelope():
    data = _data(_cli(["contentgap", "hello"]))
    assert data["ready"] is True and data["plugin"] == "contentgap"


def test_cli_contentgap_detect_reports_the_fallback_tier_as_the_product():
    data = _data(_cli(["contentgap", "detect"]))
    assert data["adapter"] == "contentgap"
    assert data["tier"] == openswap.TIER_FALLBACK
    assert data["native"]["found"] is False
    assert "no local native binary" in data["fallback_scope"]
    assert set(data["extras"]) == {"yake", "pandoc"}


def test_cli_contentgap_terms_weights_a_corpus_read_from_disk(tmp_path):
    corpus = _corpus(tmp_path)
    data = _data(_cli(["contentgap", "terms", "--corpus", str(corpus), "--top", "5"]))
    assert data["corpus"]["n_docs"] == 3 and data["corpus"]["skipped"] == []
    terms = [t["term"] for t in data["terms"]]
    assert len(terms) == 5
    assert "chunking" in terms
    # fenced code and <script> never became terms
    assert all(t["term"] != "stuffed" for t in data["terms"])
    assert data["tier"] == openswap.TIER_FALLBACK


def test_cli_contentgap_terms_without_a_corpus_fails_with_an_example(tmp_path):
    res = _cli(["contentgap", "terms", "--corpus", str(tmp_path / "nope")])
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert "corpus path not found" in payload["error"]
    assert "--corpus" in payload["example"]


def test_cli_contentgap_audit_end_to_end_and_the_fail_on_gate(tmp_path):
    corpus = _corpus(tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text(
        "# Our notes\n\nWe wrote a wrapper. Chunking is handled. Ship it.\n",
        encoding="utf-8",
    )
    args = ["contentgap", "audit", str(draft), "--corpus", str(corpus), "--top", "6"]
    data = _data(_cli(args))
    report = data["report"]
    assert report["path"].endswith("draft.md")
    assert report["format"] == "markdown"
    assert report["corpus"]["n_docs"] == 3
    assert 0 < report["coverage_score"]["value"] < 100
    assert report["coverage_score"]["error"] is None
    assert report["counts"]["missing"] >= 1
    assert data["summary"]["total"] == len(data["diagnostics"])
    assert "contentgap:coverage" in data["summary"]["by_rule"]

    # the gate: warnings present -> exit 1, and only when asked for
    assert _cli([*args, "--fail-on", "warning"]).returncode == 1
    assert _cli([*args, "--fail-on", "error"]).returncode == 0
    bad = _cli([*args, "--fail-on", "nonsense"])
    assert bad.returncode == 1
    assert "--fail-on must be one of" in json.loads(bad.stdout)["error"]


def test_cli_contentgap_audit_reads_a_draft_from_stdin(tmp_path):
    corpus = _corpus(tmp_path)
    data = _data(
        _cli(
            ["contentgap", "audit", "-", "--corpus", str(corpus), "--top", "4"],
            stdin="chunking reranking recall retrieval augmented generation\n",
        )
    )
    assert data["report"]["path"] == "(stdin)"
    assert data["report"]["coverage_score"]["value"] == 100.0
    assert data["diagnostics"] == []


def test_cli_contentgap_audit_labels_an_unmeasurable_corpus(tmp_path):
    corpus = _corpus(tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text("Chunking notes.\n", encoding="utf-8")
    # --max-kb 0 makes every page too large: the pass must report WHY, not 0.0
    res = _cli(
        [
            "contentgap", "audit", str(draft), "--corpus", str(corpus),
            "--max-kb", "0", "--fail-on", "error",
        ]
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    report = payload["data"]["report"]
    assert report["coverage_score"]["value"] is None
    assert "no usable corpus document" in report["coverage_score"]["error"]
    assert len(report["corpus"]["skipped"]) == 3
    assert all("too-large" in s["error"] for s in report["corpus"]["skipped"])
    assert [d["rule"] for d in payload["data"]["diagnostics"]] == [
        "contentgap:unmeasured"
    ]


def test_cli_contentgap_brief_writes_lf_exact_markdown(tmp_path):
    corpus = _corpus(tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text("Chunking is handled.\n", encoding="utf-8")
    out = tmp_path / "brief.md"
    data = _data(
        _cli(
            [
                "contentgap", "brief", str(draft), "--corpus", str(corpus),
                "--out", str(out), "--title", "RAG brief", "--top", "5",
            ]
        )
    )
    raw = out.read_bytes()
    # write_bytes, not write_text: no CRLF even on Windows, so the artifact does
    # not diff against itself on the next run
    assert b"\r\n" not in raw
    assert raw.decode("utf-8").startswith("# RAG brief\n")
    assert data["bytes"] == len(raw)
    assert data["out"].endswith("brief.md")
    assert data["coverage_score"]["error"] is None
    # rerunning is byte-identical (no clock, no ordering wobble)
    _data(
        _cli(
            [
                "contentgap", "brief", str(draft), "--corpus", str(corpus),
                "--out", str(out), "--title", "RAG brief", "--top", "5",
            ]
        )
    )
    assert out.read_bytes() == raw


def test_plugin_is_discoverable():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "contentgap" in list_plugin_names()


def test_manifest_denies_the_network_axis_entirely():
    import yaml

    manifest = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "contentgap" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    caps = manifest["capabilities"]
    assert caps["network"]["enabled"] is False
    assert caps["network"]["domains"] == []
    assert caps["secrets"]["allow"] == []
    assert caps["filesystem"]["write"] is True
    assert caps["filesystem"]["paths"] == [".scout"]
    # default-deny is enforced, not just declared
    from bigbang.core.policy import check_permission

    allowed, reason = check_permission(manifest, "network", "https://api.clearscope.io")
    assert allowed is False and "network disabled" in reason
