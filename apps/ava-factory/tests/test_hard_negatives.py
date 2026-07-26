"""Hard-negative mining — ordering, and the one rule that can poison training.

The property that decides whether this module helps or hurts is NOT "did it mine a
lot of negatives". It is: **is any mined negative actually a positive for the same
query?** If it is, the contrastive loss is told to push apart a query and a document
that genuinely answer each other, and the encoder is trained against the truth. That
failure is silent — the loss still goes down, the mined counts still look healthy,
and the only symptom is a retriever that is worse than the one you started with.
Same shape as the three research `sota` rows on this platform that all turned out to
be artifacts.

It is not hypothetical here either. Measured on this tree 2026-07-26: 351 extracted
pairs share a docstring with a sibling in the same file or package, and disabling the
filter emits 1,245 negatives that are real positives, across 330 of 2,940 queries.
``TestNeverAPositive`` is therefore the centre of this file, not a footnote.

Run:
    cd apps/ava-factory && AVA_FACTORY_ROOT="$PWD" python -m pytest \
        tests/test_hard_negatives.py -q -p no:randomly
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hard_negatives.py"
_ROOT = Path(__file__).resolve().parents[3]

_SPEC = importlib.util.spec_from_file_location("hard_negatives", _SCRIPT)
hn = importlib.util.module_from_spec(_SPEC)
sys.modules["hard_negatives"] = hn
_SPEC.loader.exec_module(hn)

# The module under test already loaded ast_pairs; loading it a second time here
# would be exactly the duplicate-source-of-truth this repo keeps getting bitten by.
ap = hn.ast_pairs


# ---------------------------------------------------------------------------
# Fixtures. Every one asserts its own pair count: a fixture that silently
# extracts nothing turns every assertion built on it into a no-op, which has
# already happened once in tests/test_ast_pairs.py.
# ---------------------------------------------------------------------------
def build(src: str, path: str, expect: int):
    pairs, rejected = ap.extract_file(src, path)
    assert len(pairs) == expect, (
        f"fixture {path} produced {len(pairs)} pairs, expected {expect}; every "
        f"assertion resting on it would be vacuous. rejections={rejected}"
    )
    return pairs


STORE_SRC = '''
import json

class Store:
    def load(self, key):
        """Read a stored configuration value by its key and decode the JSON."""
        raw = self._backend.get(key)
        return json.loads(raw) if raw else None

    def save(self, key, value):
        """Write a configuration value into the backing store as JSON text."""
        self._backend.put(key, json.dumps(value))
        return True

def normalise_ids(items):
    """Normalise a sequence of identifiers into a sorted unique tuple of strings."""
    cleaned = [str(i).strip() for i in items if i]
    return tuple(sorted(set(cleaned)))
'''

HELPERS_SRC = '''
def format_report(rows):
    """Render the collected rows as an aligned plain-text table for the console."""
    width = max((len(r[0]) for r in rows), default=0)
    return "\\n".join(f"{r[0]:<{width}}  {r[1]}" for r in rows)
'''

SOLO_SRC = '''
def lonely(value):
    """Return the supplied value unchanged after checking it is not empty."""
    if not value:
        raise ValueError("empty value supplied to the lonely helper")
    return value
'''


def fixture_pairs():
    """Three files: pkg/store.py (class + module fn), pkg/helpers.py (package
    sibling), solo/only.py (a package of one function)."""
    return (
        build(STORE_SRC, "pkg/store.py", 3)
        + build(HELPERS_SRC, "pkg/helpers.py", 1)
        + build(SOLO_SRC, "solo/only.py", 1)
    )


def by_symbol(records):
    return {r["symbol"]: r for r in records}


def scopes(record):
    return [n["scope"] for n in record["negatives"]]


def symbols(record):
    return [n["symbol"] for n in record["negatives"]]


# ---------------------------------------------------------------------------
# Source A — ordering
# ---------------------------------------------------------------------------
class TestSiblingOrdering:
    def test_same_class_is_mined_before_same_file(self):
        """The whole point: the closest thing in scope is the hardest negative."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["Store.load"]
        assert scopes(rec)[:2] == ["same_class", "same_file"], scopes(rec)
        assert symbols(rec)[0] == "Store.save", (
            f"a same-file function outranked a same-class method: {symbols(rec)}"
        )

    def test_same_file_is_mined_before_same_package(self):
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["Store.load"]
        assert scopes(rec) == ["same_class", "same_file", "same_package"], scopes(rec)
        assert symbols(rec) == ["Store.save", "normalise_ids", "format_report"]

    def test_a_module_level_function_has_no_same_class_negatives(self):
        """`normalise_ids` is not in a class, so nothing can be same_class for it —
        and the two Store methods must NOT be promoted to that scope."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["normalise_ids"]
        assert "same_class" not in scopes(rec), scopes(rec)
        assert scopes(rec) == ["same_file", "same_file", "same_package"]

    def test_package_siblings_reach_across_files_but_not_across_packages(self):
        recs = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))
        assert "format_report" in symbols(recs["Store.load"])
        assert "lonely" not in symbols(recs["Store.load"]), (
            "solo/only.py is a different package and must not be reachable"
        )

    def test_n_caps_the_list_and_keeps_the_closest(self):
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs(), n=1))["Store.load"]
        assert len(rec["negatives"]) == 1
        assert rec["negatives"][0]["symbol"] == "Store.save"

    def test_n_zero_yields_no_negatives_but_still_yields_records(self):
        recs = hn.mine_sibling_negatives(fixture_pairs(), n=0)
        assert len(recs) == 5
        assert all(r["negatives"] == [] for r in recs)


# ---------------------------------------------------------------------------
# THE correctness rule
# ---------------------------------------------------------------------------
class TestNeverAPositive:
    def test_the_positive_is_never_its_own_negative(self):
        for rec in hn.mine_sibling_negatives(fixture_pairs()):
            texts = [n["text"] for n in rec["negatives"]]
            assert rec["positive"] not in texts, (
                f"{rec['symbol']} was returned as its own negative"
            )
            assert (rec["path"], rec["symbol"]) not in [
                (n["path"], n["symbol"]) for n in rec["negatives"]
            ]

    def test_the_text_gate_alone_rejects_the_pair_itself(self):
        """Self-exclusion is guaranteed twice — by the `j == i` skip in the caller
        AND by the text gate. Deleting the index skip breaks nothing, which is the
        point of the redundancy, but it also means no end-to-end test can pin the
        gate's half of it. So the gate is exercised directly."""
        pair = build(SOLO_SRC, "solo/only.py", 1)[0]
        assert hn._candidate(pair, {pair["positive"]}, hn.SCOPE_SAME_FILE) is None
        assert hn._candidate(pair, set(), hn.SCOPE_SAME_FILE) is not None

    def test_a_sibling_sharing_the_docstring_is_dropped(self):
        """Copy-pasted docstrings are everywhere in real code. If two functions
        carry the same docstring, each one is a genuine positive for the other's
        query and must never be mined as a negative for it."""
        src = '''
def encode_payload(data):
    """Serialise the supplied payload into the wire format used by the client."""
    body = str(data).strip()
    return body.encode("utf-8", errors="replace")

def encode_payload_v2(data):
    """Serialise the supplied payload into the wire format used by the client."""
    body = repr(data).strip()
    return body.encode("utf-8", errors="strict")

def decode_payload(raw):
    """Parse a wire-format response body back into the client payload object."""
    text = raw.decode("utf-8", errors="replace")
    return text.strip() or None
'''
        pairs = build(src, "wire/codec.py", 3)
        recs = by_symbol(hn.mine_sibling_negatives(pairs))
        rec = recs["encode_payload"]
        assert symbols(rec) == ["decode_payload"], (
            f"the duplicate-docstring twin leaked in as a negative: {symbols(rec)}"
        )

    def test_identical_code_with_a_different_docstring_is_dropped(self):
        """A package sibling whose PACKED TEXT equals the positive. The queries
        differ, so the query-keyed check alone would let it through — but pushing a
        string away from itself is noise, not a gradient."""
        body = '''
def run(cfg):
    """{doc}"""
    steps = [s for s in cfg.get("steps", []) if s]
    return len(steps), tuple(steps)
'''
        alpha = build(body.format(doc="Execute every configured step and report how "
                                      "many ran."), "clones/alpha.py", 1)
        beta = build(body.format(doc="Count the pipeline stages declared by this "
                                     "configuration mapping."), "clones/beta.py", 1)
        assert alpha[0]["positive"] == beta[0]["positive"], (
            "fixture is wrong: the two packed positives must be byte-identical for "
            "this test to exercise anything"
        )
        assert alpha[0]["query"] != beta[0]["query"]
        recs = hn.mine_sibling_negatives(alpha + beta)
        assert all(r["negatives"] == [] for r in recs), (
            "a negative identical to the positive was emitted"
        )

    def test_adjacent_negatives_exclude_the_commits_own_files(self):
        golden = [
            {"query": "feat: add the retrieval index writer", "date": "2026-01-01T00:00:00+00:00",
             "relevant": ["a/x.py"]},
            {"query": "fix: correct the index writer flush order", "date": "2026-01-02T00:00:00+00:00",
             "relevant": ["a/y.py", "b/z.py"]},
            {"query": "docs: describe the writer flush order", "date": "2026-01-03T00:00:00+00:00",
             "relevant": ["b/z.py", "c/w.py"]},
        ]
        rec = hn.mine_adjacent_negatives(golden, window=5)[1]
        assert rec["relevant"] == ["a/y.py", "b/z.py"]
        got = [n["path"] for n in rec["negatives"]]
        assert "a/y.py" not in got, "the commit's own file came back as its negative"
        assert "b/z.py" not in got, (
            "b/z.py is relevant to THIS query and was also touched by a neighbour — "
            "it must be filtered, not mined"
        )
        assert got == ["a/x.py", "c/w.py"], got

    def test_a_repeated_commit_message_shares_one_exclusion_set(self):
        """Two commits, same message ("ops(factory): checkpoint ..."), different
        files. Each commit's files are relevant to that message, so neither may be
        the other's negative."""
        golden = [
            {"query": "ops(factory): checkpoint the running trainer state",
             "date": "2026-02-01T00:00:00+00:00", "relevant": ["ops/a.py"]},
            {"query": "ops(factory): checkpoint the running trainer state",
             "date": "2026-02-02T00:00:00+00:00", "relevant": ["ops/b.py"]},
            {"query": "feat: unrelated change to the collector module",
             "date": "2026-02-03T00:00:00+00:00", "relevant": ["ops/c.py"]},
        ]
        for rec in hn.mine_adjacent_negatives(golden, window=5)[:2]:
            got = [n["path"] for n in rec["negatives"]]
            assert got == ["ops/c.py"], (
                f"the other commit with the identical message leaked in: {got}"
            )

    def test_case_and_whitespace_do_not_defeat_the_query_key(self):
        """A re-wrapped or re-cased docstring is the same query. If the key were
        exact-match, the twin would slip straight through the filter."""
        src = '''
def emit_alpha(rows):
    """Publish the collected rows to the downstream telemetry sink."""
    payload = [dict(r) for r in rows]
    return len(payload), payload

def emit_beta(rows):
    """Publish the collected rows
    to the DOWNSTREAM telemetry sink."""
    payload = [tuple(r) for r in rows]
    return len(payload), payload
'''
        pairs = build(src, "sink/emit.py", 2)
        assert pairs[0]["query"] != pairs[1]["query"], "fixture must differ literally"
        recs = hn.mine_sibling_negatives(pairs)
        assert all(r["negatives"] == [] for r in recs), (
            f"re-wrapped duplicate slipped through: "
            f"{[symbols(r) for r in recs]}"
        )


# ---------------------------------------------------------------------------
# Nothing to mine — no crash, no fabrication
# ---------------------------------------------------------------------------
class TestNothingToMine:
    def test_a_one_function_file_in_its_own_package_yields_zero(self):
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["lonely"]
        assert rec["negatives"] == [], (
            f"solo/only.py has one function and one package — a negative was "
            f"fabricated from somewhere: {rec['negatives']}"
        )
        assert rec["query"] and rec["positive"], "the record itself must survive"

    def test_a_lone_pair_on_its_own(self):
        pairs = build(SOLO_SRC, "solo/only.py", 1)
        recs = hn.mine_sibling_negatives(pairs)
        assert len(recs) == 1 and recs[0]["negatives"] == []

    def test_empty_inputs(self):
        assert hn.mine_sibling_negatives([]) == []
        assert hn.mine_adjacent_negatives([]) == []
        assert hn.summarise([], [])["total"] == {
            "queries": 0, "negatives": 0, "avg_per_query": 0.0
        }

    def test_a_single_commit_has_no_neighbours(self):
        golden = [{"query": "only commit in the whole history here",
                   "date": "2026-01-01T00:00:00+00:00", "relevant": ["a/x.py"]}]
        assert hn.mine_adjacent_negatives(golden, window=5)[0]["negatives"] == []

    def test_window_zero_disables_source_b_without_dropping_records(self):
        golden = [
            {"query": f"commit number {i} with a sufficiently long message",
             "date": f"2026-03-0{i}T00:00:00+00:00", "relevant": [f"a/{i}.py"]}
            for i in range(1, 5)
        ]
        recs = hn.mine_adjacent_negatives(golden, window=0)
        assert len(recs) == 4 and all(r["negatives"] == [] for r in recs)


# ---------------------------------------------------------------------------
# Source B — temporal ordering
# ---------------------------------------------------------------------------
def _linear_golden(n=9):
    return [
        {"query": f"commit {i:02d} touching one distinct module in the tree",
         "date": f"2026-04-{i:02d}T00:00:00+00:00", "relevant": [f"m/f{i:02d}.py"]}
        for i in range(1, n + 1)
    ]


class TestAdjacentOrdering:
    def test_closest_commit_first_and_earlier_wins_a_tie(self):
        rec = hn.mine_adjacent_negatives(_linear_golden(), window=2)[4]  # commit 05
        assert rec["query"].startswith("commit 05")
        assert [n["path"] for n in rec["negatives"]] == [
            "m/f04.py", "m/f06.py", "m/f03.py", "m/f07.py"
        ]
        assert [n["distance"] for n in rec["negatives"]] == [1, 1, 2, 2]
        assert [n["direction"] for n in rec["negatives"]] == [
            "before", "after", "before", "after"
        ]

    def test_window_bounds_the_reach(self):
        rec = hn.mine_adjacent_negatives(_linear_golden(), window=1)[4]
        assert [n["path"] for n in rec["negatives"]] == ["m/f04.py", "m/f06.py"]

    def test_edges_do_not_wrap_around_or_crash(self):
        recs = hn.mine_adjacent_negatives(_linear_golden(), window=3)
        first = [n["path"] for n in recs[0]["negatives"]]
        last = [n["path"] for n in recs[-1]["negatives"]]
        assert first == ["m/f02.py", "m/f03.py", "m/f04.py"], first
        assert last == ["m/f08.py", "m/f07.py", "m/f06.py"], last

    def test_n_caps_the_adjacent_list_too(self):
        rec = hn.mine_adjacent_negatives(_linear_golden(), window=4, n=3)[4]
        assert [n["path"] for n in rec["negatives"]] == [
            "m/f04.py", "m/f06.py", "m/f03.py"
        ]

    def test_a_file_touched_by_two_neighbours_appears_once(self):
        golden = [
            {"query": "commit one of three in this small history",
             "date": "2026-05-01T00:00:00+00:00", "relevant": ["shared/s.py"]},
            {"query": "commit two of three in this small history",
             "date": "2026-05-02T00:00:00+00:00", "relevant": ["own/o.py"]},
            {"query": "commit three of three in this small history",
             "date": "2026-05-03T00:00:00+00:00", "relevant": ["shared/s.py"]},
        ]
        got = [n["path"] for n in hn.mine_adjacent_negatives(golden, window=2)[1]["negatives"]]
        assert got == ["shared/s.py"], got

    def test_input_order_is_irrelevant_because_records_are_date_sorted(self):
        golden = _linear_golden()
        forward = hn.mine_adjacent_negatives(golden, window=2)
        backward = hn.mine_adjacent_negatives(list(reversed(golden)), window=2)
        assert json.dumps(forward) == json.dumps(backward)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_sibling_runs_are_byte_identical(self):
        a = hn.mine_sibling_negatives(fixture_pairs())
        b = hn.mine_sibling_negatives(fixture_pairs())
        assert json.dumps(a) == json.dumps(b)

    def test_two_adjacent_runs_are_byte_identical(self):
        golden = _linear_golden()
        a = hn.mine_adjacent_negatives(golden, window=3)
        b = hn.mine_adjacent_negatives(golden, window=3)
        assert json.dumps(a) == json.dumps(b)

    def test_sibling_output_does_not_depend_on_input_pair_order(self):
        """A re-walk of the tree in a different filesystem order must produce the
        same negatives. The first cut of this test used the 5-pair fixture, where no
        query has more candidates than the cap — so `cands = cands[:n]` BEFORE the
        sort (a real, plausible bug: it would silently swap ranked negatives for
        arbitrary ones) passed it. It has to run where the cap actually bites.

        Measured 2026-07-26: 2407 of 2940 real queries saturate n=8, and 1629 pairs
        live in a file with more than 8 documented functions.
        """
        pairs = real_pairs()
        forward = hn.mine_sibling_negatives(pairs)
        backward = hn.mine_sibling_negatives(list(reversed(pairs)))
        saturated = sum(1 for r in forward if len(r["negatives"]) == hn.DEFAULT_N)
        assert saturated >= 1200, (
            f"only {saturated} queries hit the n={hn.DEFAULT_N} cap, so truncation "
            f"order is barely exercised and this test proves little"
        )

        def key(rec):
            return (rec["path"], rec["symbol"], rec["query"], rec["positive"])

        assert sorted(forward, key=key) == sorted(backward, key=key)

    def test_two_runs_over_the_real_repo_are_byte_identical(self):
        pairs = real_pairs()
        a = hn.mine_sibling_negatives(pairs)
        b = hn.mine_sibling_negatives(list(pairs))
        assert json.dumps(a) == json.dumps(b)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
class TestSummarise:
    def test_average_is_over_all_queries_including_the_barren_ones(self):
        s = hn.summarise(hn.mine_sibling_negatives(fixture_pairs()), [])["sibling"]
        # store.load 3, store.save 3, normalise_ids 3, format_report 3, lonely 0
        assert s["queries"] == 5
        assert s["negatives"] == 12
        assert s["avg_per_query"] == 2.4, (
            f"got {s['avg_per_query']} — 12/4 = 3.0 would mean the barren query was "
            f"dropped from the denominator, which hides coverage collapse"
        )
        assert s["queries_with_negatives"] == 4
        assert s["coverage"] == 0.8

    def test_scope_counts_add_up_to_the_total(self):
        recs = hn.mine_sibling_negatives(fixture_pairs())
        s = hn.summarise(recs, [])["sibling"]
        assert sum(s["by_scope"].values()) == s["negatives"]
        # Store.load  -> save(class) normalise_ids(file) format_report(pkg)
        # Store.save  -> load(class) normalise_ids(file) format_report(pkg)
        # normalise_ids -> load(file) save(file) format_report(pkg)
        # format_report -> load(pkg) save(pkg) normalise_ids(pkg)
        # lonely      -> nothing
        assert s["by_scope"] == {"same_class": 2, "same_file": 4, "same_package": 6}

    def test_distance_counts_add_up_to_the_total(self):
        recs = hn.mine_adjacent_negatives(_linear_golden(), window=2)
        s = hn.summarise([], recs)["adjacent"]
        assert sum(s["by_distance"].values()) == s["negatives"]
        assert list(s["by_distance"]) == ["1", "2"], "distances must sort numerically"

    def test_totals_combine_both_sources(self):
        sib = hn.mine_sibling_negatives(fixture_pairs())
        adj = hn.mine_adjacent_negatives(_linear_golden(), window=1)
        t = hn.summarise(sib, adj)["total"]
        assert t["queries"] == 5 + 9
        assert t["negatives"] == 12 + 16  # 7 interior commits x2, 2 edges x1


# ---------------------------------------------------------------------------
# The contract with ast_pairs
# ---------------------------------------------------------------------------
class TestSymbolFormatContract:
    def test_class_of_reads_the_format_ast_pairs_actually_writes(self):
        """class_of() parses ast_pairs' `symbol`. Storing a second copy of the
        class name would be a duplicated source of truth (that bug class has landed
        twice here); parsing it means this test is the only thing standing between a
        format change and every same_class negative silently becoming same_file."""
        pairs = build(STORE_SRC, "pkg/store.py", 3)
        got = {p["symbol"]: hn.class_of(p) for p in pairs}
        assert got == {
            "Store.load": "Store",
            "Store.save": "Store",
            "normalise_ids": None,
        }

    def test_package_of(self):
        assert hn.package_of("a/b/c.py") == "a/b"
        assert hn.package_of("top.py") == ""
        assert hn.package_of("a\\b\\c.py") == "a/b", "windows separators normalise"

    def test_pairs_from_tree_returns_posix_relative_paths(self):
        pairs = real_pairs()
        assert all("\\" not in p["path"] for p in pairs)
        assert all(not Path(p["path"]).is_absolute() for p in pairs)


# ---------------------------------------------------------------------------
# The real repo. Measured 2026-07-26; floors are set below the measurement so a
# growing tree never breaks them, and far enough above zero to catch a miner
# that quietly stops mining.
# ---------------------------------------------------------------------------
_CACHE: dict = {}


def real_pairs():
    if "pairs" not in _CACHE:
        _CACHE["pairs"] = hn.pairs_from_tree(_ROOT)
    return _CACHE["pairs"]


def real_sibling():
    if "sib" not in _CACHE:
        _CACHE["sib"] = hn.mine_sibling_negatives(real_pairs())
    return _CACHE["sib"]


def real_golden():
    if "golden" not in _CACHE:
        try:
            _CACHE["golden"] = hn.retrieval_eval.mine_pairs(1500)
        except FileNotFoundError:  # pragma: no cover - git is present on this box
            pytest.skip("git executable not on PATH — source B cannot be measured")
    return _CACHE["golden"]


class TestAgainstTheRealRepo:
    def test_extraction_floor(self):
        # measured 2026-07-26: 2940 pairs
        assert len(real_pairs()) >= 2000, len(real_pairs())

    def test_sibling_negatives_floor(self):
        s = hn.summarise(real_sibling(), [])["sibling"]
        # measured 2026-07-26: 2940 queries / 20520 negatives / avg 6.980 / cov 90.6%
        assert s["queries"] >= 2000, s
        assert s["negatives"] >= 12000, s
        assert s["avg_per_query"] >= 4.0, s
        assert s["coverage"] >= 0.75, s

    def test_every_scope_is_actually_reached(self):
        """A fleet number that only ever reaches one scope would still look large.
        measured 2026-07-26: same_class 720, same_file 16040, same_package 3760."""
        by_scope = hn.summarise(real_sibling(), [])["sibling"]["by_scope"]
        assert by_scope["same_class"] >= 300, by_scope
        assert by_scope["same_file"] >= 9000, by_scope
        assert by_scope["same_package"] >= 1000, by_scope

    def test_the_correctness_rule_has_real_work_to_do_here(self):
        """Measured: 351 extracted pairs share a docstring with a sibling in the
        same file or package. If this floor ever fails, the filter tests above have
        stopped exercising anything real."""
        pairs = real_pairs()
        by_query: dict = {}
        for p in pairs:
            by_query.setdefault(hn._norm_query(p["query"]), []).append(p)
        risky = 0
        for group in by_query.values():
            if len(group) < 2:
                continue
            for a in group:
                if any(
                    b is not a
                    and (
                        b["path"] == a["path"]
                        or hn.package_of(b["path"]) == hn.package_of(a["path"])
                    )
                    for b in group
                ):
                    risky += 1
        assert risky >= 100, (
            f"only {risky} sibling-scoped duplicate docstrings in the tree"
        )

    def test_no_mined_negative_is_a_positive_anywhere_in_the_tree(self):
        """The fleet-wide version of the rule, over every mined negative."""
        positives: dict = {}
        for p in real_pairs():
            positives.setdefault(hn._norm_query(p["query"]), set()).add(p["positive"])
        records, checked, violations = real_sibling(), 0, []
        for rec in records:
            allowed = positives[hn._norm_query(rec["query"])]
            for neg in rec["negatives"]:
                checked += 1
                if neg["text"] in allowed:
                    violations.append((rec["symbol"], neg["symbol"]))
        assert checked >= 12000, f"only {checked} negatives checked — floor is 12000"
        assert not violations, f"{len(violations)} false negatives: {violations[:5]}"

    def test_disabling_the_filter_would_actually_poison_the_data(self):
        """Proves the rule is load-bearing rather than decorative. Measured: 1245
        false negatives across 330 queries when the filter is bypassed."""
        positives: dict = {}
        for p in real_pairs():
            positives.setdefault(hn._norm_query(p["query"]), set()).add(p["positive"])
        original = hn._candidate
        try:
            hn._candidate = lambda pair, forbidden, scope: original(pair, set(), scope)
            unfiltered = hn.mine_sibling_negatives(real_pairs())
        finally:
            hn._candidate = original
        bad = sum(
            1
            for rec in unfiltered
            for neg in rec["negatives"]
            if neg["text"] in positives[hn._norm_query(rec["query"])]
        )
        assert bad >= 400, (
            f"only {bad} false negatives without the filter — either the tree "
            f"changed shape or the bypass no longer bypasses anything"
        )
        assert hn.mine_sibling_negatives(real_pairs()) == real_sibling(), (
            "restoring _candidate did not restore the filtered result"
        )

    def test_adjacent_negatives_floor(self):
        recs = hn.mine_adjacent_negatives(real_golden(), window=hn.DEFAULT_WINDOW)
        a = hn.summarise([], recs)["adjacent"]
        # measured 2026-07-26 over 1500 commits (819 exist): 698 queries / 4461
        # negatives / avg 6.391 / coverage 97.6%
        assert a["queries"] >= 400, a
        assert a["negatives"] >= 2500, a
        assert a["avg_per_query"] >= 3.0, a
        assert a["coverage"] >= 0.80, a
        assert a["by_distance"].get("1", 0) >= 1000, a["by_distance"]

    def test_no_adjacent_negative_is_relevant_to_its_own_query(self):
        golden = real_golden()
        relevant: dict = {}
        for g in golden:
            relevant.setdefault(hn._norm_query(g["query"]), set()).update(g["relevant"])
        recs = hn.mine_adjacent_negatives(golden, window=hn.DEFAULT_WINDOW)
        checked, violations = 0, []
        for rec in recs:
            allowed = relevant[hn._norm_query(rec["query"])]
            for neg in rec["negatives"]:
                checked += 1
                if neg["path"] in allowed:
                    violations.append((rec["query"][:40], neg["path"]))
        assert checked >= 2500, f"only {checked} negatives checked — floor is 2500"
        assert not violations, f"{len(violations)} false negatives: {violations[:5]}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCLI:
    def test_json_report_on_a_real_subtree(self, tmp_path):
        out = tmp_path / "negatives.jsonl"
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--path", str(_ROOT / "apps" / "ava-factory"
                                                          / "scripts"),
             "--no-git", "--json", "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, proc.stderr
        summary = json.loads(proc.stdout)
        # measured 2026-07-26 on apps/ava-factory/scripts: 89 queries, 712 negatives,
        # avg 8.0 (every query saturates the default n=8), coverage 100%
        assert summary["sibling"]["queries"] >= 60, summary
        assert summary["sibling"]["negatives"] >= 450, summary
        assert summary["adjacent"] == {
            "queries": 0, "negatives": 0, "avg_per_query": 0.0,
            "queries_with_negatives": 0, "coverage": 0.0, "by_distance": {},
        }, "--no-git must report zero, not silently invent a source-B number"
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == summary["sibling"]["queries"]
        assert all(json.loads(ln)["source"] == "sibling" for ln in lines)

    def test_text_report_names_both_sources_and_the_average(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--path", str(_ROOT / "apps" / "ava-factory"
                                                          / "scripts"),
             "--no-git", "--n", "4"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, proc.stderr
        for token in ("SOURCE A", "SOURCE B", "avg per query", "same_class",
                      "negatives mined", "TOTAL"):
            assert token in proc.stdout, f"{token!r} missing from the report"


class TestQueryNamedFilesAreNotNegatives:
    """Regression for the defect adversarial review found in the LIVE output.

    `forbidden` covered only files relevant to a byte-identical commit message, so
    a file the query itself NAMED could be mined as a hard negative. Measured
    before the fix: 62 of 4,461 adjacent negatives (1.4%) on the real repo. That is
    training the model against the truth — the one rule the module docstring says
    matters most. The predicate already existed, loaded and unused, in
    retrieval_eval.leaks_filename.
    """

    def _golden(self):
        return [
            {"query": "docs: rewrite the codeact roadmap", "relevant": ["a/other.py"],
             "date": "2026-01-01T00:00:00+00:00"},
            {"query": "fix: touch specs 13 codeact md today", "relevant": ["specs/13_codeact.md"],
             "date": "2026-01-02T00:00:00+00:00"},
            {"query": "chore: unrelated tidy up of things", "relevant": ["z/zz.py"],
             "date": "2026-01-03T00:00:00+00:00"},
        ]

    def test_a_file_the_query_names_is_never_a_negative(self):
        out = hn.mine_adjacent_negatives(self._golden(), n=8, window=2)
        for rec in out:
            for neg in rec["negatives"]:
                assert not hn.retrieval_eval.leaks_filename(rec["query"], [neg["path"]]), (
                    f"query {rec['query']!r} names {neg['path']} yet it was mined "
                    "as a hard negative"
                )

    def test_the_specific_reported_case(self):
        out = hn.mine_adjacent_negatives(self._golden(), n=8, window=2)
        by_q = {r["query"]: [n["path"] for n in r["negatives"]] for r in out}
        # query 1 names "codeact"; specs/13_codeact.md must not be its negative
        assert "specs/13_codeact.md" not in by_q["docs: rewrite the codeact roadmap"]

    def test_unrelated_neighbours_are_still_mined(self):
        """The filter must not gut the source — it removed 1.4%, not 100%."""
        out = hn.mine_adjacent_negatives(self._golden(), n=8, window=2)
        assert sum(len(r["negatives"]) for r in out) > 0, "filter removed everything"

    def test_real_repo_has_zero_query_named_negatives(self):
        # hn.real_golden does not exist — guarding on hasattr made this test
        # permanently SKIP, i.e. silently dead. Use the miner the module itself
        # calls at its CLI (retrieval_eval.mine_pairs).
        golden = hn.retrieval_eval.mine_pairs(4000)
        assert golden, "git history unavailable — this guard must not skip silently"
        out = hn.mine_adjacent_negatives(golden, n=8, window=5)
        total = sum(len(r["negatives"]) for r in out)
        assert total > 1000, f"non-vacuity: only {total} negatives mined"
        bad = [
            (r["query"][:60], n["path"])
            for r in out
            for n in r["negatives"]
            if hn.retrieval_eval.leaks_filename(r["query"], [n["path"]])
        ]
        assert bad == [], f"{len(bad)} query-named files still mined as negatives: {bad[:3]}"
