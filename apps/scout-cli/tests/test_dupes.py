"""Dupes — openswap #28 (Copyscape -> local k-shingling + Jaccard/containment
near-duplicate clusters). Pure-logic core tests + the value-or-reason honesty
invariant + fast-path-vs-definition equivalence + cross-process fingerprint
determinism + capability/egress detection + the subprocess CLI envelope.

Offline and deterministic by construction: every document is an inline string or
a tmp_path file, no test opens a socket, and the two similarity implementations
(set definition vs postings-count hot path) are asserted against each other so
the fast one cannot quietly drift from the slow one.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import pytest

from bigbang.core import dupes, logs, openswap, prose

ROOT = Path(__file__).resolve().parents[1]

SMALL = {"k": 3, "min_tokens": 3}

# A page and a lightly-reworded recycling of it (three substitutions in ~74
# tokens — the realistic "same copy, new site" case), plus an unrelated page.
ORIGINAL = (
    "The openswap family replaces paid software as a service with native offline "
    "equivalents that run entirely on this box. Every adapter names the paid enemy, "
    "keeps the privacy guarantee architectural rather than contractual, and does "
    "real work on day one with nothing but the standard library. A duplicate "
    "content detector belongs in that family because the hosted alternative "
    "uploads your unpublished draft to somebody else's index first."
)
REWORDED = (
    "The openswap family replaces paid software as a service with native local "
    "equivalents that run entirely on this box. Every adapter names the paid enemy, "
    "keeps the privacy promise architectural rather than contractual, and does "
    "real work on day one with nothing but the standard library. A duplicate "
    "content detector belongs in that family because the hosted service "
    "uploads your unpublished draft to somebody else's index first."
)
# a heavier rewrite of the same page: measurably less similar than REWORDED, so
# a pair ordering test has three DISTINCT similarities to order
HEAVY = (
    "The openswap family supersedes paid software as a service with native local "
    "equivalents that operate entirely on this laptop. Each adapter names the paid "
    "vendor, keeps the privacy promise architectural rather than contractual, and "
    "does genuine work on day one with nothing but the standard library. A "
    "duplicate content detector belongs in that family because the hosted service "
    "uploads your unpublished draft to somebody else's index first."
)
UNRELATED = (
    "Checkpoint cadence moved from twenty five steps down to fifteen while the "
    "flake cluster is active, because the ratchet stays net positive. Measured "
    "throughput on the degraded stack was thirty five minutes per step, which is "
    "more than eight days of wall clock for the whole run."
)


def _cfg(**overlay):
    return dupes.merge_config({**SMALL, **overlay})


def _row(doc_id, text, fmt="text", **overlay):
    return dupes.fingerprint(doc_id, text, fmt=fmt, config=_cfg(**overlay))


# ---- config -----------------------------------------------------------------


def test_merge_config_defaults_and_nested_severity_overlay():
    base = dupes.merge_config()
    assert base["k"] == 5 and base["min_tokens"] == 40
    assert base["severity"]["exact"] == "error"
    merged = dupes.merge_config({"threshold": 0.9, "severity": {"near": "error"}})
    assert merged["threshold"] == 0.9
    assert merged["severity"]["near"] == "error"
    # the un-overlaid severities survive the nested merge
    assert merged["severity"]["partial"] == "suggestion"
    # and DEFAULT_CONFIG itself is never mutated by an overlay
    assert dupes.DEFAULT_CONFIG["severity"]["near"] == "warning"
    assert dupes.DEFAULT_CONFIG["threshold"] == 0.55


def test_merge_config_rejects_typos_and_bad_values():
    with pytest.raises(ValueError, match="unknown config key"):
        dupes.merge_config({"treshold": 0.9})
    with pytest.raises(ValueError, match="unknown severity kind"):
        dupes.merge_config({"severity": {"nearly": "error"}})
    with pytest.raises(ValueError, match="severity\\[near\\]"):
        dupes.merge_config({"severity": {"near": "critical"}})
    with pytest.raises(ValueError, match="severity must be a mapping"):
        dupes.merge_config({"severity": "error"})


def test_merge_config_validates_bounds():
    with pytest.raises(ValueError, match=r"min_tokens .* must be >= k"):
        dupes.merge_config({"k": 9, "min_tokens": 8})
    with pytest.raises(ValueError, match="k must be >= 1"):
        dupes.merge_config({"k": 0})
    for bad in (-0.1, 1.5):
        with pytest.raises(ValueError, match="threshold must be within"):
            dupes.merge_config({"threshold": bad})
    with pytest.raises(ValueError, match="containment_threshold must be within"):
        dupes.merge_config({"containment_threshold": 2})
    with pytest.raises(ValueError, match="max_bytes must be >= 1"):
        dupes.merge_config({"max_bytes": 0})
    with pytest.raises(ValueError, match="digest_bits must be a multiple of 8"):
        dupes.merge_config({"digest_bits": 60})
    # bool is an int subclass; True is not a shingle width
    with pytest.raises(ValueError, match="k must be an int"):
        dupes.merge_config({"k": True})
    with pytest.raises(ValueError, match="threshold must be a number"):
        dupes.merge_config({"threshold": True})
    # k == min_tokens is legal (the boundary is inclusive)
    assert dupes.merge_config({"k": 8, "min_tokens": 8})["k"] == 8


# ---- decoding (reused logs #14 sniffer) -------------------------------------


def test_decode_document_sniffs_encoding_instead_of_assuming_utf8():
    text, det = dupes.decode_document(ORIGINAL.encode("utf-16"))
    assert text == ORIGINAL  # BOM stripped, not decoded as a character
    assert det["encoding"].startswith("utf-16") and det["via"] == "bom"
    text2, det2 = dupes.decode_document(b"\xef\xbb\xbfhello")
    assert text2 == "hello" and det2["via"] == "bom"
    text3, det3 = dupes.decode_document(b"plain ascii")
    assert text3 == "plain ascii" and det3["encoding"] == "utf-8"
    # a UTF-16 draft decoded as UTF-8 is mojibake, and mojibake matches nothing
    assert dupes.tokenize(text) == dupes.tokenize(ORIGINAL)


def test_looks_binary_flags_blobs_but_not_wide_text():
    # NUL-riddled AND valid UTF-8 — the case a decode-only check would admit
    blob = bytes([0, 1, 2, 3]) * 500
    # was `blob.decode("utf-8") is not None`: max byte is 3, so the blob is pure
    # ASCII, decode() cannot raise, and it returns str — the assertion was a
    # tautology twice over. The point of the fixture is that the blob IS valid
    # UTF-8, which is what makes a decode-only check admit it; pin that directly.
    assert len(blob.decode("utf-8")) == len(blob)  # 1 byte per char = valid ASCII/UTF-8
    assert dupes.looks_binary(blob) is True
    assert dupes.looks_binary(ORIGINAL.encode("utf-16")) is False  # NULs are structural
    assert dupes.looks_binary(ORIGINAL.encode("utf-8")) is False
    assert dupes.looks_binary(b"") is False
    # a NUL past the sampled head is out of scope, and says so by construction
    assert dupes.looks_binary(b"a" * (logs.DETECT_BYTES + 10) + b"\x00") is False


# ---- tokenizing -------------------------------------------------------------


def test_tokenize_strips_markdown_code_and_urls():
    md = "Real prose here.\n\n```\nsecret = compute_token(x)\n```\n\n`inline_code` and https://example.com/page end."
    toks = dupes.tokenize(md, "markdown")
    assert "prose" in toks and "end" in toks
    assert "secret" not in toks and "compute_token" not in toks
    assert "inline_code" not in toks
    assert "example" not in toks and "https" not in toks
    # plain-text mode does NOT strip: the fmt argument is doing real work
    assert "secret" in dupes.tokenize(md, "text")


def test_tokenize_html_skips_script_and_tags_and_casefolds():
    html = "<html><body><p>Hello There</p><script>var stolen = 1;</script></body></html>"
    toks = dupes.tokenize(html, "html")
    assert toks == ["hello", "there"]
    assert "stolen" not in toks and "script" not in toks and "body" not in toks
    # the blanking sentinel separates words, it never joins them
    assert dupes.tokenize("a`x`b", "markdown") == ["a", "b"]


# ---- shingling --------------------------------------------------------------


def test_shingles_window_count_dedupe_and_short_document():
    toks = ["a", "b", "c", "d", "e"]
    assert len(dupes.shingles(toks, 3)) == 3  # n - k + 1
    assert len(dupes.shingles(toks, 1)) == 5
    assert len(dupes.shingles(toks, 5)) == 1
    # exactly-k is the inclusive boundary; k+1 tokens short of it yields nothing
    assert dupes.shingles(toks, 6) == []
    assert dupes.shingles([], 3) == []
    # repeated windows collapse (Jaccard is defined over the SET)
    assert len(dupes.shingles(["a", "b", "a", "b", "a"], 2)) == 2
    with pytest.raises(ValueError, match="k must be >= 1"):
        dupes.shingles(toks, 0)


def test_shingle_digest_respects_token_boundaries_and_width():
    assert dupes.shingle_digest(["ab", "c"]) != dupes.shingle_digest(["a", "bc"])
    assert dupes.shingle_digest(["a", "b"]) == dupes.shingle_digest(["a", "b"])
    assert len(dupes.shingle_digest(["a"], digest_bits=64)) == 16
    assert len(dupes.shingle_digest(["a"], digest_bits=128)) == 32
    assert dupes.shingle_digest(["a"], digest_bits=64) != dupes.shingle_digest(
        ["a"], digest_bits=128
    )
    with pytest.raises(ValueError, match="digest_bits"):
        dupes.shingle_digest(["a"], digest_bits=17)


def test_fingerprints_are_stable_across_processes_not_hash_seeded():
    """builtin hash() is seeded per process; a report built on it would not diff.

    Two subprocesses with DIFFERENT PYTHONHASHSEED values must produce the same
    digest as this process.
    """
    expected = dupes.shingle_digest(["alpha", "beta", "gamma"])
    code = (
        "from bigbang.core import dupes;"
        "print(dupes.shingle_digest(['alpha','beta','gamma']))"
    )
    seen = set()
    for seed in ("0", "1", "12345"):
        import os

        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT), env=env,
        )
        assert r.returncode == 0, r.stderr
        seen.add(r.stdout.strip())
    assert seen == {expected}


def test_content_hash_normalizes_wrapping_case_and_crlf():
    a = dupes.content_hash(dupes.tokenize("Hello world,\nthis is copy."))
    b = dupes.content_hash(dupes.tokenize("HELLO WORLD, THIS IS COPY.\r\n"))
    assert a == b and a is not None
    assert a != dupes.content_hash(dupes.tokenize("hello world this is other copy"))
    # no tokens means no content: sha256("") is not evidence
    assert dupes.content_hash([]) is None
    assert dupes.content_hash(["ab", "c"]) != dupes.content_hash(["a", "bc"])


# ---- fingerprint rows: value OR reason, never both, never neither -----------


def test_fingerprint_row_shape_and_short_document_reason():
    row = _row("a.md", ORIGINAL)
    assert row["id"] == "a.md" and row["tokens"] > 20
    assert row["shingle_count"] == len(row["shingles"]) > 0
    assert row["errors"] == {} and row["content_sha256"]
    short = dupes.fingerprint("s.md", "two words", config=dupes.merge_config())
    assert short["shingles"] == [] and short["shingle_count"] == 0
    assert "too-short: 2 tokens < min_tokens 40" in short["errors"]["shingles"]
    # exact-duplicate detection still works for a document too short to shingle
    assert short["content_sha256"] is not None
    assert "content_sha256" not in short["errors"]


def test_fingerprint_reading_invariant_holds_for_every_case():
    rows = [
        _row("prose.md", ORIGINAL),
        _row("short.md", "one two"),
        _row("empty.md", "\n\n   \n"),
        dupes.unreadable_row("gone.md", "unreadable: OSError: denied"),
    ]
    for row in rows:
        has_hash = row["content_sha256"] is not None
        assert has_hash is not ("content_sha256" in row["errors"] or "read" in row["errors"])
        has_shingles = bool(row["shingles"])
        assert has_shingles is not ("shingles" in row["errors"] or "read" in row["errors"])
    empty = rows[2]
    assert "no-tokens" in empty["errors"]["content_sha256"]
    assert empty["content_sha256"] is None
    assert dupes.is_measurable(rows[0]) and not dupes.is_measurable(rows[1])
    assert rows[3]["errors"] == {"read": "unreadable: OSError: denied"}
    assert rows[3]["chars"] is None and rows[3]["tokens"] is None


# ---- similarity arithmetic --------------------------------------------------


def test_jaccard_definition_and_undefined_case():
    assert dupes.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert dupes.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert dupes.jaccard({"a"}, {"b"}) == 0.0
    # both empty is UNDEFINED, not 0.0 and not 1.0
    assert dupes.jaccard(set(), set()) is None
    assert dupes.jaccard({"a"}, set()) == 0.0


def test_counts_path_matches_the_set_definition_exactly():
    rng = random.Random(20260724)
    for _ in range(200):
        a = {str(rng.randrange(30)) for _ in range(rng.randrange(1, 12))}
        b = {str(rng.randrange(30)) for _ in range(rng.randrange(1, 12))}
        shared = len(a & b)
        assert dupes.jaccard_from_counts(shared, len(a), len(b)) == pytest.approx(
            dupes.jaccard(a, b)
        )
        assert dupes.containment_from_counts(shared, len(a), len(b)) == pytest.approx(
            shared / min(len(a), len(b))
        )


def test_counts_path_guards_impossible_inputs():
    with pytest.raises(ValueError, match="cannot be negative"):
        dupes.jaccard_from_counts(-1, 5, 5)
    with pytest.raises(ValueError, match="exceeds the smaller set"):
        dupes.jaccard_from_counts(6, 5, 9)
    assert dupes.jaccard_from_counts(0, 0, 0) is None
    assert dupes.containment_from_counts(0, 0, 4) is None
    assert dupes.containment_from_counts(3, 3, 90) == 1.0  # a full slice


# ---- postings index --------------------------------------------------------


def test_shared_counts_equals_brute_force_and_skips_disjoint_pairs():
    rows = [
        _row("orig.md", ORIGINAL),
        _row("reword.md", REWORDED),
        _row("other.md", UNRELATED),
        _row("copy.md", ORIGINAL),
    ]
    counts = dupes.shared_counts(rows)
    by_id = {r["id"]: set(r["shingles"]) for r in rows}
    for a, b in combinations(sorted(by_id), 2):
        shared = len(by_id[a] & by_id[b])
        assert counts.get((a, b), 0) == shared
    # keys are canonical (lo, hi) and disjoint pairs never appear
    assert all(a < b for a, b in counts)
    assert ("orig.md", "other.md") not in counts
    assert counts[("copy.md", "orig.md")] == len(by_id["orig.md"])
    idx = dupes.shingle_index(rows)
    shared_digest = sorted(by_id["orig.md"] & by_id["copy.md"])[0]
    assert {"copy.md", "orig.md"} <= set(idx[shared_digest])
    # the postings list names exactly the documents that carry the digest
    for digest, ids in idx.items():
        assert sorted(ids) == sorted(i for i, s in by_id.items() if digest in s)
    assert set(idx) == set().union(*by_id.values())


def test_exact_groups_ignores_missing_hashes_and_sorts():
    rows = [
        _row("b.md", ORIGINAL),
        _row("a.md", ORIGINAL.upper()),
        _row("c.md", UNRELATED),
        _row("blank.md", "   "),
        _row("blank2.md", ""),
    ]
    groups = dupes.exact_groups(rows)
    assert [g["members"] for g in groups] == [["a.md", "b.md"]]
    # two hash-less documents are NOT a duplicate group of each other
    assert all("blank.md" not in g["members"] for g in groups)


# ---- classification + pairs -------------------------------------------------


def test_classify_gate_order_and_inclusive_boundaries():
    cfg = _cfg(threshold=0.5, containment_threshold=0.8)
    assert dupes.classify(0.5, 0.0, exact=False, config=cfg) == "near"
    assert dupes.classify(0.49999, 0.9, exact=False, config=cfg) == "partial"
    assert dupes.classify(0.49999, 0.8, exact=False, config=cfg) == "partial"
    assert dupes.classify(0.49999, 0.79999, exact=False, config=cfg) is None
    assert dupes.classify(None, None, exact=True, config=cfg) == "exact"
    # exact wins over the thresholds, never the other way round
    assert dupes.classify(0.0, 0.0, exact=True, config=cfg) == "exact"
    assert dupes.classify(None, None, exact=False, config=cfg) is None


def test_compare_rows_orders_ids_and_reports_numbers():
    cfg = _cfg()
    a, b = _row("z.md", ORIGINAL), _row("a.md", REWORDED)
    pair = dupes.compare_rows(a, b, config=cfg)
    flipped = dupes.compare_rows(b, a, config=cfg)
    assert (pair["a"], pair["b"]) == ("a.md", "z.md") == (flipped["a"], flipped["b"])
    assert pair == flipped  # argument order cannot change a reading
    assert 0.0 < pair["similarity"] < 1.0 and pair["error"] is None
    assert pair["union"] == len(set(a["shingles"]) | set(b["shingles"]))
    assert pair["shared"] == len(set(a["shingles"]) & set(b["shingles"]))
    assert pair["similarity"] == pytest.approx(pair["shared"] / pair["union"])
    # the injected postings count is the same number the sets give
    assert dupes.compare_rows(a, b, config=cfg, shared=pair["shared"]) == pair


def test_compare_rows_never_invents_a_similarity_for_unshingleable_docs():
    cfg = dupes.merge_config()  # min_tokens 40: both documents are too short
    a = dupes.fingerprint("a.md", "recycled tagline here", config=cfg)
    b = dupes.fingerprint("b.md", "RECYCLED TAGLINE HERE.", config=cfg)
    pair = dupes.compare_rows(a, b, config=cfg)
    assert pair["exact"] is True and pair["kind"] == "exact"
    assert pair["similarity"] is None and pair["containment"] is None
    assert pair["shared"] is None and pair["union"] is None
    assert "no shingle sets to compare" in pair["error"]
    assert "too-short: 3 tokens" in pair["error"]
    assert "a.md:" in pair["error"] and "b.md:" in pair["error"]
    # a read failure is surfaced in the pair reason too, not swallowed
    gone = dupes.unreadable_row("gone.md", "unreadable: OSError: nope")
    pair2 = dupes.compare_rows(a, gone, config=cfg)
    assert pair2["similarity"] is None and "nope" in pair2["error"]
    assert pair2["kind"] is None  # no hash on the unreadable row, so not exact


def test_find_pairs_applies_gates_and_deterministic_order():
    cfg = _cfg(threshold=0.4, containment_threshold=0.95)
    rows = [
        _row("orig.md", ORIGINAL),
        _row("copy.md", ORIGINAL.upper()),
        _row("reword.md", REWORDED),
        _row("heavy.md", HEAVY),
        _row("other.md", UNRELATED),
    ]
    pairs = dupes.find_pairs(rows, config=cfg)
    kinds = {(p["a"], p["b"]): p["kind"] for p in pairs}
    assert kinds[("copy.md", "orig.md")] == "exact"
    assert kinds[("orig.md", "reword.md")] == "near"
    assert all("other.md" not in (p["a"], p["b"]) for p in pairs)
    # exact first, then STRICTLY descending similarity, then by id
    assert pairs[0]["kind"] == "exact"
    sims = [p["similarity"] for p in pairs if p["kind"] == "near"]
    assert len(set(sims)) >= 3, sims  # ties alone cannot prove an ordering
    assert sims == sorted(sims, reverse=True) and sims[0] == max(sims)
    assert sims[0] > sims[-1]
    ids = [(p["a"], p["b"]) for p in pairs]
    assert len(ids) == len(set(ids))  # each pair reported once
    assert pairs == dupes.find_pairs(list(reversed(rows)), config=cfg)
    # raising the gate above the measured similarity drops the near pair
    strict = dupes.find_pairs(rows, config=_cfg(threshold=0.99, containment_threshold=1.0))
    assert [p["kind"] for p in strict] == ["exact"]


def test_find_pairs_keeps_exact_duplicates_that_cannot_be_shingled():
    cfg = dupes.merge_config()  # min_tokens 40
    rows = [
        dupes.fingerprint("tagline-a.md", "buy our thing today", config=cfg),
        dupes.fingerprint("tagline-b.md", "Buy our thing today!", config=cfg),
    ]
    pairs = dupes.find_pairs(rows, config=cfg)
    assert len(pairs) == 1 and pairs[0]["kind"] == "exact"
    assert pairs[0]["similarity"] is None and pairs[0]["error"]


def test_containment_catches_a_slice_lifted_into_a_longer_page():
    cfg = _cfg(threshold=0.9, containment_threshold=0.9)
    long_page = ORIGINAL + " " + UNRELATED + " " + UNRELATED.replace("five", "six")
    rows = [_row("draft.md", ORIGINAL), _row("page.md", long_page)]
    pair = dupes.compare_rows(rows[0], rows[1], config=cfg)
    assert pair["containment"] == 1.0  # the draft is entirely inside the page
    assert pair["similarity"] < 0.9  # and Jaccard alone would have missed it
    assert dupes.find_pairs(rows, config=cfg)[0]["kind"] == "partial"


# ---- clustering -------------------------------------------------------------


def test_cluster_pairs_is_transitive_and_ordered():
    pairs = [
        {"a": "b.md", "b": "c.md", "similarity": 0.7, "kind": "near", "exact": False},
        {"a": "a.md", "b": "b.md", "similarity": 0.9, "kind": "near", "exact": False},
        {"a": "y.md", "b": "z.md", "similarity": None, "kind": "exact", "exact": True},
    ]
    clusters = dupes.cluster_pairs(pairs)
    assert [c["members"] for c in clusters] == [
        ["a.md", "b.md", "c.md"],
        ["y.md", "z.md"],
    ]
    assert clusters[0]["size"] == 3 and clusters[0]["pairs"] == 2
    assert clusters[0]["max_similarity"] == 0.9
    assert clusters[0]["min_similarity"] == 0.7
    assert clusters[0]["unmeasured"] == 0 and clusters[0]["kinds"] == ["near"]
    # an all-unmeasured cluster states the absence instead of reporting 0.0
    assert clusters[1]["max_similarity"] is None
    assert clusters[1]["min_similarity"] is None
    assert clusters[1]["unmeasured"] == 1
    assert dupes.cluster_pairs([]) == []
    assert dupes.cluster_pairs(list(reversed(pairs))) == clusters


# ---- diagnostics ------------------------------------------------------------


def test_to_diagnostics_maps_severities_and_surfaces_unmeasured():
    cfg = _cfg()
    rows = [_row("orig.md", ORIGINAL), _row("copy.md", ORIGINAL.upper())]
    short = dupes.fingerprint("tiny.md", "hi", config=dupes.merge_config())
    diags = dupes.to_diagnostics(dupes.find_pairs(rows, config=cfg), [short], config=cfg)
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["dupes:exact-duplicate"]["severity"] == "error"
    assert by_rule["dupes:exact-duplicate"]["path"] == "orig.md"  # the second id
    assert "copy.md" in by_rule["dupes:exact-duplicate"]["message"]
    assert "jaccard 1.000" in by_rule["dupes:exact-duplicate"]["message"]
    info = by_rule["dupes:unmeasured-shingles"]
    assert info["severity"] == "info" and info["path"] == "tiny.md"
    assert "too-short: 1 tokens < min_tokens 40" in info["message"]
    assert diags == openswap.sort_diagnostics(diags)
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1 and summary["by_severity"]["info"] == 1
    # severities are config, not code
    loud = dupes.to_diagnostics(
        dupes.find_pairs(rows, config=cfg), [short], config=_cfg(severity={"unmeasured": "error"})
    )
    assert {d["severity"] for d in loud if "unmeasured" in d["rule"]} == {"error"}


# ---- the whole pass ---------------------------------------------------------


def _corpus():
    return [
        {"id": "pages/orig.md", "text": ORIGINAL, "fmt": "markdown"},
        {"id": "pages/copy.md", "text": ORIGINAL.upper(), "fmt": "markdown"},
        {"id": "drafts/reword.md", "text": REWORDED, "fmt": "markdown"},
        {"id": "drafts/other.md", "text": UNRELATED, "fmt": "markdown"},
        {"id": "drafts/tiny.md", "text": "no", "fmt": "markdown"},
        {"id": "drafts/gone.md", "error": "unreadable: OSError: locked"},
    ]


def test_analyze_reports_counts_clusters_and_never_hides_a_skip():
    report = dupes.analyze(_corpus(), config=_cfg())
    counts = report["counts"]
    assert counts["documents"] == 6 and counts["shingled"] == 4
    assert counts["unmeasured"] == 2  # tiny (too short) + gone (unreadable)
    assert counts["possible_pairs"] == 6  # 4 shingled docs
    assert 0 < counts["compared_pairs"] <= counts["possible_pairs"]
    assert counts["shingles"] == sum(d["shingle_count"] for d in report["documents"])
    assert [d["id"] for d in report["documents"]] == sorted(
        d["id"] for d in report["documents"]
    )
    members = {tuple(c["members"]) for c in report["clusters"]}
    # the exact pair and its reworded sibling are ONE transitive cluster
    assert members == {("drafts/reword.md", "pages/copy.md", "pages/orig.md")}
    assert all("drafts/other.md" not in m for m in members)
    assert all("drafts/tiny.md" not in m for m in members)
    rules = {d["rule"] for d in report["diagnostics"]}
    assert "dupes:unmeasured-shingles" in rules and "dupes:unmeasured-read" in rules
    assert report["summary"]["total"] == len(report["diagnostics"])
    assert report["exact_groups"][0]["members"] == ["pages/copy.md", "pages/orig.md"]


def test_analyze_is_byte_identical_across_runs_and_input_order():
    a = json.dumps(dupes.analyze(_corpus(), config=_cfg()), sort_keys=False)
    b = json.dumps(dupes.analyze(_corpus(), config=_cfg()), sort_keys=False)
    shuffled = list(reversed(_corpus()))
    c = json.dumps(dupes.analyze(shuffled, config=_cfg()), sort_keys=False)
    assert a == b == c


def test_analyze_rejects_duplicate_ids_instead_of_dropping_one():
    docs = [{"id": "x.md", "text": ORIGINAL}, {"id": "x.md", "text": UNRELATED}]
    with pytest.raises(ValueError, match="duplicate document id"):
        dupes.analyze(docs, config=_cfg())


def test_document_view_hides_digests_unless_asked():
    rows = dupes.fingerprint_documents(_corpus()[:2], config=_cfg())
    lean = dupes.document_view(rows)
    assert "shingles" not in lean[0] and lean[0]["shingle_count"] > 0
    full = dupes.document_view(rows, include_shingles=True)
    assert full[0]["shingles"] == rows[0]["shingles"]
    assert dupes.analyze(_corpus()[:2], config=_cfg(), include_shingles=True)["documents"][0][
        "shingles"
    ]


def test_doc_exts_are_derived_from_prose_not_relisted():
    # extension-list drift between two modules that must agree is a known bug
    # class in this repo; DOC_EXTS is the same object, so it cannot drift
    assert dupes.DOC_EXTS is prose.PROSE_EXTS


# ---- detection --------------------------------------------------------------


def test_detection_fallback_and_egress_denial(monkeypatch):
    from bigbang.plugins.dupes import cli as dupes_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = dupes_cli._capability()
    assert cap["adapter"] == "dupes"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "jscpd"
    assert cap["extras"]["fdupes"]["found"] is False
    assert cap["extras"]["jdupes"]["found"] is False
    # the privacy claim is falsifiable: the policy gate denies the SaaS origin
    gate = cap["egress_gate"]
    assert gate["allowed"] is False and "network disabled" in gate["reason"]


def test_manifest_is_default_deny_on_every_axis():
    from bigbang.plugins.dupes import cli as dupes_cli

    caps = dupes_cli._manifest()["capabilities"]
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is False and caps["filesystem"]["paths"] == []
    assert caps["secrets"]["allow"] == []


# ---- the real CLI in a subprocess (offline by construction) -----------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(cwd or ROOT),
    )


def _write_corpus(tmp_path: Path) -> Path:
    base = tmp_path / "corpus"
    (base / "drafts").mkdir(parents=True)
    (base / "orig.md").write_bytes(ORIGINAL.encode("utf-8"))
    (base / "drafts" / "copy.md").write_bytes(
        ORIGINAL.upper().replace(" ", "\r\n").encode("utf-8")
    )
    (base / "drafts" / "reword.md").write_bytes(REWORDED.encode("utf-8"))
    (base / "drafts" / "other.md").write_bytes(UNRELATED.encode("utf-8"))
    (base / "wide.md").write_text(ORIGINAL, encoding="utf-16")
    (base / "blob.txt").write_bytes(bytes([0, 1, 2, 3]) * 400)
    return base


def test_cli_dupes_hello_envelope():
    r = _cli(["dupes", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_dupes_scan_finds_clusters_and_labels_every_skip(tmp_path):
    base = _write_corpus(tmp_path)
    r = _cli(["dupes", "scan", str(base), "--root", str(base), "--min-tokens", "10"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    ids = [d["id"] for d in data["documents"]]
    assert ids == sorted(ids) and "drafts/copy.md" in ids  # posix, relativized
    assert not any("\\" in i for i in ids)
    by_id = {d["id"]: d for d in data["documents"]}
    assert by_id["blob.txt"]["errors"]["read"].startswith("binary:")
    # the UTF-16 page is real content, not mojibake — same hash as the utf-8 one
    assert by_id["wide.md"]["content_sha256"] == by_id["orig.md"]["content_sha256"]
    kinds = {p["kind"] for p in data["pairs"]}
    assert "exact" in kinds
    assert data["clusters"] and data["clusters"][0]["size"] >= 3
    assert data["counts"]["compared_pairs"] < data["counts"]["possible_pairs"]
    enc = {s["id"]: s["encoding"] for s in data["sources"]}
    assert enc["wide.md"].startswith("utf-16") and enc["orig.md"] == "utf-8"
    assert "shingles" not in by_id["orig.md"]  # digests are opt-in


def test_cli_dupes_scan_fail_on_is_the_gate(tmp_path):
    base = _write_corpus(tmp_path)
    args = ["dupes", "scan", str(base), "--root", str(base), "--min-tokens", "10"]
    assert _cli([*args, "--fail-on", "error"]).returncode == 1
    # a corpus with nothing recycled passes the same gate
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.md").write_bytes(ORIGINAL.encode("utf-8"))
    (clean / "b.md").write_bytes(UNRELATED.encode("utf-8"))
    r = _cli(
        ["dupes", "scan", str(clean), "--root", str(clean), "--min-tokens", "10",
         "--fail-on", "error"]
    )
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout)["data"]["pairs"] == []


def test_cli_dupes_scan_missing_path_and_bad_flags_fail_actionably(tmp_path):
    r = _cli(["dupes", "scan", str(tmp_path / "nope")])
    assert r.returncode == 1
    assert "path not found" in json.loads(r.stdout)["error"]
    assert "example" in json.loads(r.stdout)
    empty = tmp_path / "empty"
    empty.mkdir()
    r2 = _cli(["dupes", "scan", str(empty)])
    assert r2.returncode == 1 and "no " in json.loads(r2.stdout)["error"]
    r3 = _cli(["dupes", "scan", str(empty), "--k", "9", "--min-tokens", "2"])
    assert r3.returncode == 1
    assert "must be >= k" in json.loads(r3.stdout)["error"]
    r4 = _cli(["dupes", "scan", str(empty), "--fail-on", "loud"])
    assert r4.returncode == 1


def test_cli_dupes_compare_two_files(tmp_path):
    base = _write_corpus(tmp_path)
    r = _cli(
        ["dupes", "compare", str(base / "orig.md"), str(base / "drafts" / "reword.md"),
         "--min-tokens", "10"]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    pair = json.loads(r.stdout)["data"]["pair"]
    assert 0.0 < pair["similarity"] < 1.0 and pair["error"] is None
    assert pair["kind"] in ("near", "partial", None)
    r2 = _cli(["dupes", "compare", str(base / "orig.md"), str(base / "orig.md")])
    assert r2.returncode == 1  # the same file twice is not a comparison
    assert "two distinct files" in json.loads(r2.stdout)["error"]


def test_cli_plugin_is_discovered():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "dupes" in list_plugin_names()


def test_cli_dupes_config_overlay_and_rejection(tmp_path):
    good = tmp_path / "dupes.json"
    good.write_text(json.dumps({"threshold": 0.42}), encoding="utf-8")
    r = _cli(["dupes", "config", "--config", str(good)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["config"]["threshold"] == 0.42
    assert data["extensions"] == list(dupes.DOC_EXTS)
    bad = tmp_path / "bad.json"
    bad.write_text('{"treshold": 0.9}', encoding="utf-8")
    r2 = _cli(["dupes", "config", "--config", str(bad)])
    assert r2.returncode == 1 and "unknown config key" in json.loads(r2.stdout)["error"]
    r3 = _cli(["dupes", "config", "--config", str(tmp_path / "missing.json")])
    assert r3.returncode == 1 and "bad config file" in json.loads(r3.stdout)["error"]
