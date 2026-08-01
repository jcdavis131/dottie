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
filter emits 1,245 negatives that are real positives, across 330 of 2,985 queries.
``TestNeverAPositive`` is therefore the centre of this file, not a footnote.

WHAT ADVERSARIAL REVIEW BROKE IN THE PREVIOUS VERSION OF THIS FILE, because the same
mistakes are easy to make again:

  * Four ordering tests passed with ``cands.sort()`` DELETED, because the fixture's
    insertion order happened to equal its sorted order. The fixture is now written
    deliberately out of order — module-level functions above ``class Store``, and
    ``widen_ids`` arriving before the methods it sorts after — so every ordering
    assertion inverts under that deletion.
  * The centrepiece "never its own negative" test could not be killed by ANY single
    mutation: two redundant guards each covered for the other. It is now split, and
    each half is pinned with the other half deliberately disabled.
  * Three determinism tests were ``f(x) == f(x)``. Determinism is now checked across
    PROCESSES (different PYTHONHASHSEED) and across real input permutations.
  * Two fleet tests rebuilt their forbidden index with ``hn._norm_query`` — the same
    function the implementation uses — so they could only ever detect the gate being
    BYPASSED, never its relevance notion being too NARROW. A difflib-based audit that
    shares no code with the implementation now covers the second failure, and it
    found a real one (see ``test_no_mined_negative_answers_a_paraphrase_of_its_own``).
  * The text report test asserted six literal strings and no number at all, so
    hard-coding ``n``, ``window`` or ``mine_pairs(50)`` inside ``main()`` passed it.
    Every number in the report is now parsed and compared to an in-process run.

Real-repo floors are set at >=80% of the measured value, and both numbers are stated
at each assertion. A floor comfortably below the truth is how fabricated numbers pass
on this platform; a floor at 27-42% of actual (what these were) let same_package
collapse by 73% without a red test.

Run:
    cd apps/ava-factory && AVA_FACTORY_ROOT="$PWD" python -m pytest \
        tests/test_hard_negatives.py -q -p no:randomly
"""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import itertools
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hard_negatives.py"
_ROOT = Path(__file__).resolve().parents[3]
_SUBTREE = _ROOT / "apps" / "ava-factory" / "scripts"

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


# DELIBERATELY OUT OF SORTED ORDER, and that is load-bearing. ast_pairs walks the
# file top down, so the pairs arrive [normalise_ids, widen_ids, Store.load,
# Store.save]: a same_FILE candidate arrives before a same_CLASS one (so scope
# precedence cannot come for free from arrival order), and `widen_ids` arrives before
# `Store.load`/`Store.save` while sorting after both (so the lexicographic tiebreak
# cannot either). The previous fixture put `class Store` first and every ordering
# test below passed with `cands.sort()` deleted outright.
STORE_SRC = '''
import json

def normalise_ids(items):
    """Normalise a sequence of identifiers into a sorted unique tuple of strings."""
    cleaned = [str(i).strip() for i in items if i]
    return tuple(sorted(set(cleaned)))

def widen_ids(items):
    """Pad every identifier out to the fixed width the legacy export format wants."""
    padded = [str(i).rjust(12, "0") for i in items if i]
    return tuple(padded)

class Store:
    def load(self, key):
        """Read a stored configuration value by its key and decode the JSON."""
        raw = self._backend.get(key)
        return json.loads(raw) if raw else None

    def save(self, key, value):
        """Write a configuration value into the backing store as JSON text."""
        self._backend.put(key, json.dumps(value))
        return True
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

# Two functions carrying the SAME docstring, plus one that does not. Used by both
# halves of the split self-exclusion test, so the two halves cannot drift apart.
TWIN_SRC = '''
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

# Two same-named NESTED classes in one file. ast_pairs keeps only the innermost
# class, so both methods arrive as symbol "Inner.run" — the D1 collision.
NESTED_DUP_SRC = '''
class Outer:
    class Inner:
        def run(self, cfg):
            """Execute the outer pipeline and report how many stages actually ran."""
            steps = [s for s in cfg if s]
            return len(steps), tuple(steps)

class Other:
    class Inner:
        def run(self, cfg):
            """Validate the supplied configuration mapping before anything else runs."""
            bad = [s for s in cfg if not s]
            return not bad, tuple(bad)
'''

EXTRA_TOP_LEVEL_SRC = '''
def top_level(cfg):
    """Return the number of configured stages without validating any of them."""
    return len([s for s in cfg if s is not None])
'''


def fixture_pairs():
    """Three files: pkg/store.py (two module fns + a class), pkg/helpers.py (package
    sibling), solo/only.py (a package of one function). Six pairs."""
    return (
        build(STORE_SRC, "pkg/store.py", 4)
        + build(HELPERS_SRC, "pkg/helpers.py", 1)
        + build(SOLO_SRC, "solo/only.py", 1)
    )


def by_symbol(records):
    return {r["symbol"]: r for r in records}


def records_for(records, symbol):
    """Every record with this symbol — plural on purpose: the collision fixture
    produces two records that share one symbol, and by_symbol() would hide one."""
    return [r for r in records if r["symbol"] == symbol]


def scopes(record):
    return [n["scope"] for n in record["negatives"]]


def symbols(record):
    return [n["symbol"] for n in record["negatives"]]


def _digest(records) -> str:
    """The byte-level identity claim, as 64 characters instead of 27 MB."""
    return hashlib.sha256(json.dumps(records).encode("utf-8")).hexdigest()


def _first_difference(a, b) -> str:
    """Where two record lists diverge, in one short line — "" when they agree.

    NOT cosmetic. A plain `assert forward == backward` over 2,985 records holding
    27 MB of packed code makes pytest's assertion introspection render a diff of the
    entire structure: the mutation run that deleted `out.sort` sat for five minutes
    inside pytest instead of reporting in seconds, and printed nothing usable. A test
    whose failure costs minutes is a test people stop running.
    """
    if len(a) != len(b):
        return f"record count differs: {len(a)} vs {len(b)}"
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        if x == y:
            continue
        if (x["path"], x["symbol"]) != (y["path"], y["symbol"]):
            return (f"record {i} is a different document: "
                    f"{(x['path'], x['symbol'])} vs {(y['path'], y['symbol'])}")
        return (f"record {i} {(x['path'], x['symbol'])} has different negatives: "
                f"{[n['symbol'] for n in x['negatives']]} vs "
                f"{[n['symbol'] for n in y['negatives']]}")
    return ""


def _mine_with_the_text_gate_bypassed(pairs, **kw):
    """mine_sibling_negatives with the CONTENT gate neutralised, so the only thing
    left keeping a pair out of its own negative list is the identity skip in the
    caller.

    Self-exclusion is guaranteed twice by design, which is precisely why the old
    centrepiece test could not be killed by any single mutation: each guard covered
    for the other. Disabling one on purpose is what makes the other one testable.
    """
    original = hn._candidate
    try:
        hn._candidate = lambda pair, forbidden, scope: original(pair, set(), scope)
        return hn.mine_sibling_negatives(pairs, **kw)
    finally:
        hn._candidate = original


# ---------------------------------------------------------------------------
# Source A — ordering
# ---------------------------------------------------------------------------
class TestSiblingOrdering:
    def test_same_class_is_mined_before_same_file(self):
        """The whole point: the closest thing in scope is the hardest negative.
        `normalise_ids` (same_file) ARRIVES first, so this inverts if the sort goes."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["Store.load"]
        assert scopes(rec)[:2] == ["same_class", "same_file"], scopes(rec)
        assert symbols(rec)[0] == "Store.save", (
            f"a same-file function outranked a same-class method: {symbols(rec)}"
        )

    def test_same_file_is_mined_before_same_package(self):
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["Store.load"]
        assert scopes(rec) == [
            "same_class", "same_file", "same_file", "same_package"
        ], scopes(rec)
        assert symbols(rec) == [
            "Store.save", "normalise_ids", "widen_ids", "format_report"
        ], symbols(rec)

    def test_ties_inside_one_scope_break_lexicographically_not_by_arrival(self):
        """All three file candidates for `normalise_ids` are same_file, so scope
        cannot order them and only the (path, symbol) tiebreak can. `widen_ids`
        arrives FIRST and must come LAST."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["normalise_ids"]
        assert symbols(rec) == [
            "Store.load", "Store.save", "widen_ids", "format_report"
        ], symbols(rec)

    def test_a_module_level_function_has_no_same_class_negatives(self):
        """`normalise_ids` is not in a class, so nothing can be same_class for it —
        and `widen_ids`, which is also module-level, must NOT be promoted there. That
        is what dropping the `cls is not None` guard would do: class_of() returns
        None for both, and None == None would read as "same class"."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))["normalise_ids"]
        assert "same_class" not in scopes(rec), scopes(rec)
        assert scopes(rec) == [
            "same_file", "same_file", "same_file", "same_package"
        ], scopes(rec)

    def test_package_siblings_reach_across_files_but_not_across_packages(self):
        recs = by_symbol(hn.mine_sibling_negatives(fixture_pairs()))
        assert "format_report" in symbols(recs["Store.load"])
        assert "lonely" not in symbols(recs["Store.load"]), (
            "solo/only.py is a different package and must not be reachable"
        )

    def test_n_caps_the_list_and_keeps_the_closest(self):
        """n=1 keeps the single hardest candidate, which is the one that ARRIVES
        LAST — so a cap applied before the sort would keep `normalise_ids` instead."""
        rec = by_symbol(hn.mine_sibling_negatives(fixture_pairs(), n=1))["Store.load"]
        assert len(rec["negatives"]) == 1
        assert rec["negatives"][0]["symbol"] == "Store.save"

    def test_n_zero_yields_no_negatives_but_still_yields_records(self):
        recs = hn.mine_sibling_negatives(fixture_pairs(), n=0)
        assert len(recs) == 6
        assert all(r["negatives"] == [] for r in recs)


# ---------------------------------------------------------------------------
# Source A — the (path, symbol) collision adversarial review reproduced
# ---------------------------------------------------------------------------
class TestCollidingSymbolsAreOneDocument:
    """ast_pairs stores only the INNERMOST class, so `Outer.Inner.run` and
    `Other.Inner.run` in one file both arrive as symbol `Inner.run`. Reproduced on a
    12-line file: the miner emitted `Inner.run -> [(Inner.run, same_class)]`, a record
    naming ITSELF as its negative — the module's headline invariant broken, and the
    worst output it can produce.

    The text gate cannot catch this one: the two bodies differ, so the packed texts
    differ. Only the identity skip can, which makes this class the sole test in the
    file that pins that guard on its own. Zero occurrences in the tree today, so this
    fixture is the only thing between the fix and a silent regression.
    """

    def test_two_same_named_nested_classes_really_do_collide_on_symbol(self):
        """The precondition. If ast_pairs ever qualifies symbols fully, this fails
        FIRST and says why, instead of the guard below quietly going dead."""
        pairs = build(NESTED_DUP_SRC, "nest/dup.py", 2)
        assert [p["symbol"] for p in pairs] == ["Inner.run", "Inner.run"]
        assert hn._ident(pairs[0]) == hn._ident(pairs[1])
        assert pairs[0]["positive"] != pairs[1]["positive"], (
            "the two packed texts must DIFFER, or the content gate would catch this "
            "and the identity skip would not be exercised at all"
        )
        assert pairs[0]["query"] != pairs[1]["query"], (
            "the two queries must differ, or the query-keyed index would catch it"
        )

    def test_a_colliding_pair_is_never_returned_as_its_own_negative(self):
        pairs = build(NESTED_DUP_SRC, "nest/dup.py", 2)
        recs = hn.mine_sibling_negatives(pairs)
        assert len(recs) == 2
        for rec in recs:
            listed = [(n["path"], n["symbol"]) for n in rec["negatives"]]
            assert (rec["path"], rec["symbol"]) not in listed, (
                f"{rec['symbol']} was returned as its own negative: {listed}"
            )
        assert all(r["negatives"] == [] for r in recs), (
            "the only other pair in the file is indistinguishable from this one "
            "downstream, so nothing may survive"
        )

    def test_the_drop_is_scoped_to_the_colliding_identity_not_to_the_file(self):
        """A blunt fix — bail out of the whole file on any collision — would also
        pass the test above. This one fails for it."""
        pairs = build(NESTED_DUP_SRC + EXTRA_TOP_LEVEL_SRC, "nest/dup.py", 3)
        recs = hn.mine_sibling_negatives(pairs)
        inner = records_for(recs, "Inner.run")
        assert len(inner) == 2
        for rec in inner:
            assert symbols(rec) == ["top_level"], symbols(rec)
        top = records_for(recs, "top_level")[0]
        assert symbols(top) == ["Inner.run", "Inner.run"], symbols(top)
        assert scopes(top) == ["same_file", "same_file"], scopes(top)


# ---------------------------------------------------------------------------
# THE correctness rule
# ---------------------------------------------------------------------------
class TestNeverAPositive:
    def test_the_identity_skip_holds_when_the_content_gate_is_bypassed(self):
        """Guard 1 of 2, pinned with guard 2 switched off. Deleting the identity skip
        then puts every pair straight into its own negative list.

        Non-vacuity is asserted, not assumed: the bypass MUST let the
        duplicate-docstring twin through, or it bypassed nothing and this test would
        pass for the wrong reason."""
        pairs = build(TWIN_SRC, "wire/codec.py", 3)
        recs = _mine_with_the_text_gate_bypassed(pairs)
        assert "encode_payload_v2" in symbols(by_symbol(recs)["encode_payload"]), (
            "the bypass did not bypass the content gate, so nothing is being tested"
        )
        for rec in recs:
            assert rec["positive"] not in [n["text"] for n in rec["negatives"]], (
                f"{rec['symbol']} was returned as its own negative"
            )
            assert (rec["path"], rec["symbol"]) not in [
                (n["path"], n["symbol"]) for n in rec["negatives"]
            ], f"{rec['symbol']} listed its own (path, symbol)"

    def test_the_content_gate_holds_where_the_identity_skip_cannot_help(self):
        """Guard 2 of 2, on the case only it can catch: a twin at a DIFFERENT
        (path, symbol) carrying the same docstring. Same content, different identity —
        the identity skip is blind to it.

        Copy-pasted docstrings are everywhere in real code. If two functions carry the
        same docstring, each is a genuine positive for the other's query.
        """
        pairs = build(TWIN_SRC, "wire/codec.py", 3)
        rec = by_symbol(hn.mine_sibling_negatives(pairs))["encode_payload"]
        assert symbols(rec) == ["decode_payload"], (
            f"the duplicate-docstring twin leaked in as a negative: {symbols(rec)}"
        )
        bypassed = by_symbol(_mine_with_the_text_gate_bypassed(pairs))["encode_payload"]
        assert symbols(bypassed) == ["decode_payload", "encode_payload_v2"], (
            f"the twin must reappear once the gate is off, proving it is the GATE "
            f"removing it and not something incidental: {symbols(bypassed)}"
        )

    def test_the_content_gate_alone_rejects_the_pair_itself(self):
        """The gate's own half of the redundancy, unit-tested directly: `forbidden`
        always contains the query's own positive, so a self-match dies here too."""
        pair = build(SOLO_SRC, "solo/only.py", 1)[0]
        assert hn._candidate(pair, {pair["positive"]}, hn.SCOPE_SAME_FILE) is None
        assert hn._candidate(pair, set(), hn.SCOPE_SAME_FILE) is not None

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

    def test_case_alone_does_not_defeat_the_query_key(self):
        """CASE only, and that limit is the point: ast_pairs collapses whitespace when
        it builds `query`, so NO fixture routed through it can exercise the whitespace
        half of _norm_query. Adversarial review deleted the join/split and all 45
        tests still passed. The whitespace half is covered by the next test, on input
        that has not been pre-normalised."""
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
        assert pairs[0]["query"].casefold() == pairs[1]["query"].casefold(), (
            "ast_pairs has already collapsed the whitespace, so CASE is the only "
            "thing this fixture can test"
        )
        recs = hn.mine_sibling_negatives(pairs)
        assert all(r["negatives"] == [] for r in recs), (
            f"re-cased duplicate slipped through: {[symbols(r) for r in recs]}"
        )
        pairs[1]["query"] = "Count how many rows the caller supplied before sending."
        assert any(r["negatives"] for r in hn.mine_sibling_negatives(pairs)), (
            "control: with genuinely different queries these two MUST be mined, or "
            "the assertion above passes because the miner emits nothing at all"
        )

    def test_whitespace_alone_does_not_defeat_the_query_key(self):
        """Hand-built pairs, because ast_pairs' own normalisation hides the property
        under test. mine_sibling_negatives is a public function over dicts, so
        un-collapsed whitespace is a real input rather than a contrivance."""
        doc_a = "Publish the collected rows to the downstream telemetry sink."
        doc_b = "Publish the collected rows\n    to the downstream  telemetry sink."
        assert doc_a != doc_b and doc_a.casefold() != doc_b.casefold(), (
            "fixture must differ under BOTH an exact and a case-only key, or the "
            "test passes for the wrong reason"
        )
        assert hn._norm_query(doc_a) == hn._norm_query(doc_b)
        pairs = [
            {"query": doc_a, "path": "sink/emit.py", "symbol": "emit_alpha",
             "positive": "def emit_alpha(rows):\n    return [dict(r) for r in rows]"},
            {"query": doc_b, "path": "sink/emit.py", "symbol": "emit_beta",
             "positive": "def emit_beta(rows):\n    return [tuple(r) for r in rows]"},
        ]
        recs = hn.mine_sibling_negatives(pairs)
        assert len(recs) == 2
        assert all(r["negatives"] == [] for r in recs), (
            f"whitespace defeated the query key: {[symbols(r) for r in recs]}"
        )
        pairs[1]["query"] = "Count how many rows the caller supplied before sending."
        assert any(r["negatives"] for r in hn.mine_sibling_negatives(pairs)), (
            "control: with genuinely different queries these two MUST be mined"
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

    def test_n_caps_the_adjacent_list_across_neighbours(self):
        """The per-OFFSET quota break: every commit here carries one file, so the
        quota can only ever be reached between neighbours, never inside one."""
        rec = hn.mine_adjacent_negatives(_linear_golden(), window=4, n=3)[4]
        assert [n["path"] for n in rec["negatives"]] == [
            "m/f04.py", "m/f06.py", "m/f03.py"
        ]

    def test_n_caps_the_adjacent_list_inside_a_single_neighbour(self):
        """The per-NEIGHBOUR quota break, which the test above cannot reach: one
        neighbour carries five files and the quota is three, so the break has to fire
        in the middle of one commit's file list. Adversarial review deleted that inner
        `if len(negatives) >= n: break` and all 45 tests still passed, because no
        fixture ever gave a single neighbour more files than the remaining quota."""
        golden = [
            {"query": "alpha change landing ahead of the wide commit",
             "date": "2026-06-01T00:00:00+00:00", "relevant": ["q/one.py"]},
            {"query": "the wide commit that touches five modules at once",
             "date": "2026-06-02T00:00:00+00:00",
             "relevant": ["w/b1.py", "w/b2.py", "w/b3.py", "w/b4.py", "w/b5.py"]},
            {"query": "omega change landing after the wide commit",
             "date": "2026-06-03T00:00:00+00:00", "relevant": ["q/three.py"]},
        ]
        rec = hn.mine_adjacent_negatives(golden, window=2, n=3)[2]
        assert rec["query"].startswith("omega"), rec["query"]
        got = [n["path"] for n in rec["negatives"]]
        assert len(got) == 3, (
            f"the quota was overshot INSIDE one neighbour's file list ({len(got)} of "
            f"n=3); the inner break is the only thing that can stop it there: {got}"
        )
        assert got == ["w/b1.py", "w/b2.py", "w/b3.py"], got

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
# Determinism. Every test here used to be f(x) == f(x) in one process, which
# cannot see either of the two things that actually break reproducibility:
# per-process string hashing, and record order that follows the input.
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_the_written_file_is_identical_across_processes_and_hash_seeds(self, tmp_path):
        """The real question the docstring's byte-identical claim raises. Every index
        in this module is a dict or set keyed on strings, and str hashing is
        randomised per process, so one-process f(x)==f(x) proves nothing about it."""
        blobs = []
        for seed in ("0", "1", "12345"):
            out = tmp_path / f"seed{seed}.jsonl"
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), "--path", str(_SUBTREE),
                 "--no-git", "--json", "--out", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=dict(os.environ, PYTHONHASHSEED=seed),
            )
            assert proc.returncode == 0, proc.stderr
            blobs.append(out.read_bytes())
        # measured 2026-07-26 on apps/ava-factory/scripts: 93 records; floor 80%
        assert len(blobs[0].splitlines()) >= 74, len(blobs[0].splitlines())
        seen = {hashlib.sha256(b).hexdigest() for b in blobs}
        assert len(seen) == 1, f"the JSONL differs across hash seeds: {sorted(seen)}"

    def test_sibling_output_is_byte_identical_under_a_reversed_walk(self):
        """A re-walk of the tree in a different filesystem order must produce the same
        FILE, not merely the same negatives. The old version of this test sorted BOTH
        sides by a content key before comparing, which is a comparison that cannot see
        the bug adversarial review found: the negative lists were order-independent,
        the emitted record order was not.

        It also has to run where the cap actually bites. Measured 2026-07-26: 2452 of
        2985 real queries saturate n=8; floor at 80%.
        """
        pairs = real_pairs()
        forward = hn.mine_sibling_negatives(pairs)
        backward = hn.mine_sibling_negatives(list(reversed(pairs)))
        saturated = sum(1 for r in forward if len(r["negatives"]) == hn.DEFAULT_N)
        assert saturated >= 1961, (
            f"only {saturated} queries hit the n={hn.DEFAULT_N} cap, so truncation "
            f"order is barely exercised and this test proves little"
        )
        assert _first_difference(forward, backward) == ""
        assert _digest(forward) == _digest(backward)

    def test_sibling_output_is_byte_identical_under_shuffled_walks(self):
        """Reversal is one permutation, and a suspiciously symmetric one. The old test
        in this slot compared mine(pairs) with mine(list(pairs)) — a shallow copy in
        the SAME order, i.e. f(x) == f(x)."""
        pairs = real_pairs()
        base = hn.mine_sibling_negatives(pairs)
        base_digest = _digest(base)
        for seed in (0, 1, 1337):
            shuffled = list(pairs)
            random.Random(seed).shuffle(shuffled)
            assert shuffled != pairs, f"seed {seed} did not shuffle anything"
            got = hn.mine_sibling_negatives(shuffled)
            assert _first_difference(base, got) == "", f"walk order seed={seed}"
            assert _digest(got) == base_digest, f"walk order seed={seed}"

    def test_commits_sharing_a_timestamp_do_not_inherit_the_input_order(self):
        """The case the compound sort key exists for. With that key reduced to
        `g["date"]`, sorted() is stable and the output becomes whatever order the
        caller happened to pass — which is git's order, i.e. not a property of the
        data at all."""
        same_date = "2026-07-01T12:00:00+00:00"
        golden = [
            {"query": f"{name} commit sharing one timestamp with the others",
             "date": same_date, "relevant": [f"t/{name}.py"]}
            for name in ("alpha", "bravo", "charlie", "delta")
        ]
        base = json.dumps(hn.mine_adjacent_negatives(golden, window=3))
        assert sum(len(r["negatives"]) for r in json.loads(base)) == 12, (
            "each of the 4 commits must see the other 3, or the permutations below "
            "have nothing to disagree about"
        )
        seen = 0
        for perm in itertools.permutations(golden):
            seen += 1
            assert json.dumps(hn.mine_adjacent_negatives(list(perm), window=3)) == base
        assert seen == 24


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
class TestSummarise:
    def test_average_is_over_all_queries_including_the_barren_ones(self):
        s = hn.summarise(hn.mine_sibling_negatives(fixture_pairs()), [])["sibling"]
        # 4 each for Store.load, Store.save, normalise_ids, widen_ids, format_report;
        # 0 for lonely
        assert s["queries"] == 6
        assert s["negatives"] == 20
        assert s["avg_per_query"] == 3.333, (
            f"got {s['avg_per_query']} — 20/5 = 4.0 would mean the barren query was "
            f"dropped from the denominator, which hides coverage collapse"
        )
        assert s["queries_with_negatives"] == 5
        assert s["coverage"] == 0.8333

    def test_scope_counts_add_up_to_the_total(self):
        recs = hn.mine_sibling_negatives(fixture_pairs())
        s = hn.summarise(recs, [])["sibling"]
        assert sum(s["by_scope"].values()) == s["negatives"]
        # Store.load    -> save(class) normalise_ids(file) widen_ids(file) report(pkg)
        # Store.save    -> load(class) normalise_ids(file) widen_ids(file) report(pkg)
        # normalise_ids -> load(file) save(file) widen_ids(file) report(pkg)
        # widen_ids     -> load(file) save(file) normalise_ids(file) report(pkg)
        # format_report -> load(pkg) save(pkg) normalise_ids(pkg) widen_ids(pkg)
        # lonely        -> nothing
        assert s["by_scope"] == {"same_class": 2, "same_file": 10, "same_package": 8}

    def test_distance_counts_add_up_to_the_total(self):
        recs = hn.mine_adjacent_negatives(_linear_golden(), window=2)
        s = hn.summarise([], recs)["adjacent"]
        assert sum(s["by_distance"].values()) == s["negatives"]
        assert list(s["by_distance"]) == ["1", "2"], "distances must sort numerically"

    def test_totals_combine_both_sources(self):
        sib = hn.mine_sibling_negatives(fixture_pairs())
        adj = hn.mine_adjacent_negatives(_linear_golden(), window=1)
        t = hn.summarise(sib, adj)["total"]
        assert t["queries"] == 6 + 9
        assert t["negatives"] == 20 + 16  # 7 interior commits x2, 2 edges x1


class TestIdentityCollisionsAreReported:
    """The half of the collision that is NOT collapsed, and why it is counted.

    `mine_sibling_negatives` collapses colliding identities for self-exclusion only —
    that half is a correctness bug (a record naming itself). It deliberately leaves
    the other half alone: two records still share one `(path, symbol)`, and
    `TestCollidingSymbolsAreOneDocument` asserts that ONE record's negatives list
    holding two entries with the same `(path, symbol)` is intended. That is right for
    training, because `text` — the actual signal — stays distinct, and collapsing
    them would discard a genuine negative to tidy a label.

    What was missing is that nothing SAID so. A consumer keying on `(path, symbol)`
    silently keeps one and loses the other: the same silent-overwrite shape
    minhash_dedup surfaces as `collisions`. Now reported.

    Two-sided on purpose. A counter checked only against a real tree that measures 0
    is satisfied by a counter that is dead — `empty_result_count` shipped exactly that
    shape and a `int(any(...))` mutant survived 99 tests.
    """

    def test_it_fires_on_the_colliding_fixture(self):
        pairs = build(NESTED_DUP_SRC + EXTRA_TOP_LEVEL_SRC, "nest/dup.py", 3)
        recs = hn.mine_sibling_negatives(pairs)
        ic = hn.identity_collisions(recs)
        # Inner.run is emitted twice with one identity -> 1 record beyond the first.
        assert ic["records"] == 1, f"{ic} — two Inner.run records share one identity"
        # top_level lists both Inner.run functions -> 1 entry beyond the first.
        assert ic["negative_entries"] == 1, (
            f"{ic} — top_level's negatives are {symbols(records_for(recs, 'top_level')[0])}"
        )

    def test_it_does_not_fire_on_a_clean_fixture(self):
        """Anti-vacuity for the other direction: a counter that always returns 1 is
        as useless as one that always returns 0."""
        recs = hn.mine_sibling_negatives(fixture_pairs())
        assert hn.identity_collisions(recs) == {"records": 0, "negative_entries": 0}

    def test_a_negative_shared_by_two_different_records_is_not_a_collision(self):
        """The count is per record. `normalise_ids` appears in several records'
        negative lists — that is two queries sharing a negative, not an
        indistinguishable pair, and pooling them would report a fictional collision
        on every healthy corpus."""
        recs = hn.mine_sibling_negatives(fixture_pairs())
        pooled = [(n["path"], n["symbol"]) for r in recs for n in r["negatives"]]
        assert len(pooled) != len(set(pooled)), (
            "fixture no longer shares any negative across records, so this test "
            "cannot distinguish per-record from pooled counting"
        )
        assert hn.identity_collisions(recs)["negative_entries"] == 0

    def test_summarise_carries_it_and_the_real_tree_measures_zero(self):
        s = hn.summarise(hn.mine_sibling_negatives(fixture_pairs()), [])["sibling"]
        assert set(s["identity_collisions"]) == {"records", "negative_entries"}
        real = hn.identity_collisions(real_sibling())
        assert real == {"records": 0, "negative_entries": 0}, (
            f"{real} — measured 0 of both on this tree 2026-07-26. Not a regression "
            "in the miner: it means ordinary nested-class shadowing has appeared in "
            "the source, and the report now says so instead of hiding it"
        )


class TestAdjacentOffsetsNeverIncludeZero:
    """Pins the premise that makes removing `j == i` from source B safe.

    That guard could never fire: `offsets` is built from `range(1, window + 1)` as
    (-d, +d), so 0 is not in it. It was removed rather than left as reassuring noise.
    If a 0 offset is ever added, this test fails and says the guard has to come back —
    which is the difference between a deleted dead check and a forgotten one.
    """

    @pytest.mark.parametrize("window", [0, 1, 2, 5, 50])
    def test_zero_is_never_an_offset(self, window):
        """Reads hn._offsets. The first version of this test REBUILT the loop, and a
        mutation putting `range(0, ...)` into the source passed it untouched — the
        test was a second copy of the rule it was guarding. Verified: with the read,
        that same mutation now fails here."""
        offsets = hn._offsets(window)
        assert 0 not in offsets
        assert len(offsets) == 2 * window

    def test_offsets_are_distance_ascending_earlier_first(self):
        assert hn._offsets(3) == [-1, 1, -2, 2, -3, 3]
        assert hn._offsets(0) == []
        assert hn._offsets(-4) == [], "a negative window must not invert the range"

    def test_no_record_lists_a_file_of_its_own_commit(self, ):
        """The behavioural consequence, measured rather than reasoned: with the guard
        gone, a record must still never carry one of its own relevant files."""
        golden = _linear_golden(9)
        for rec in hn.mine_adjacent_negatives(golden, window=3):
            own = set(rec["relevant"])
            listed = {n["path"] for n in rec["negatives"]}
            assert not (own & listed), f"{rec['query']} lists its own {own & listed}"

    def test_every_negative_comes_from_a_nonzero_distance(self):
        for rec in hn.mine_adjacent_negatives(_linear_golden(9), window=3):
            for neg in rec["negatives"]:
                assert neg["distance"] >= 1, neg
                assert neg["direction"] in ("before", "after"), neg


# ---------------------------------------------------------------------------
# The contract with ast_pairs
# ---------------------------------------------------------------------------
class TestSymbolFormatContract:
    def test_class_of_reads_the_format_ast_pairs_actually_writes(self):
        """class_of() parses ast_pairs' `symbol`. Storing a second copy of the
        class name would be a duplicated source of truth (that bug class has landed
        twice here); parsing it means this test is the only thing standing between a
        format change and every same_class negative silently becoming same_file."""
        pairs = build(STORE_SRC, "pkg/store.py", 4)
        got = {p["symbol"]: hn.class_of(p) for p in pairs}
        assert got == {
            "Store.load": "Store",
            "Store.save": "Store",
            "normalise_ids": None,
            "widen_ids": None,
        }

    def test_package_of(self):
        assert hn.package_of("a/b/c.py") == "a/b"
        assert hn.package_of("top.py") == ""
        assert hn.package_of("a\\b\\c.py") == "a/b", "windows separators normalise"

    def test_norm_path_is_the_only_separator_rule_in_the_module(self):
        """_norm_path was re-implemented inline in pairs_from_tree, three functions
        below its own definition — the duplicated-source bug class this repo has hit
        twice. Both callers must agree, on the same input."""
        assert hn._norm_path("a\\b\\c.py") == "a/b/c.py"
        assert hn._norm_path("") == "" and hn._norm_path(None) == ""
        assert all("\\" not in p["path"] for p in real_pairs())

    def test_pairs_from_tree_returns_posix_relative_paths(self):
        pairs = real_pairs()
        assert all("\\" not in p["path"] for p in pairs)
        assert all(not Path(p["path"]).is_absolute() for p in pairs)


# ---------------------------------------------------------------------------
# The real repo. Floors are DERIVED as 80% of a stated measurement, never written
# by hand. The original floors sat at 27-42% of actual, which let same_package
# collapse by 73% with every test still green.
#
# WHY DERIVED. Writing the floor out is how one of them drifted off the rule: the
# header used to claim "every floor is >=80% of measured" while same_class sat at
# 576 against 828 measured = 69.6%. That was defensible at the time and was
# disclosed — 576 is 80% of the 720 an adversarial review measured, and ~170 of the
# 828 came from another agent's IN-FLIGHT test file that a revert would have taken
# away. That caveat has now EXPIRED: minhash_dedup.py and test_minhash_dedup.py are
# both tracked in git (last touched by b82abf0), so the count is permanent. Floors
# re-cut against a fresh measurement, and `_floor()` now makes a hand-written floor
# that violates the rule impossible to write.
#
# WHY A STALENESS TEST. A floor is 80% of a measurement taken ON A DATE. The corpus
# grows, so that same floor tolerates a larger regression every week. Measured
# 2026-07-26 after the identity_collisions work landed: the floors had drifted to
# 63.0%-80.0% of actual, worst on same_class (828 -> 914 as class-based tests were
# added the same day). Prose cannot notice that. A test can.
# ---------------------------------------------------------------------------
_CACHE: dict = {}

# Measured 2026-07-26 on the whole repo, AFTER the identity_collisions work landed.
# Counts grow with the tree; the staleness test below fails when they have grown
# enough to make a floor toothless, and prints the numbers to paste in here.
# RE-CUT 2026-08-01, proactively rather than after the sweep went red. The corpus grew
# again and every floor had drifted to 70.2%-78.6% of fresh — still passing, but
# `same_class` sat at 70.2% against a STALENESS_LIMIT of 0.70, i.e. ONE more sibling pair
# from failing for a reason that has nothing to do with the miner. The sweep below is
# designed to make this a paste, not a derivation; this is that paste.
#   metric        old      new     old floor/fresh
#   pairs        3014 -> 3168            76.1%
#   queries      3014 -> 3168            76.1%
#   negatives   21112 -> 21790           77.5%
#   same_class    914 -> 1042            70.2%   <- nearest the limit
#   same_file   16430 -> 16730           78.6%
#   same_package 3768 -> 4018            75.0%
MEASURED_REAL = {
    "pairs": 3168,
    "queries": 3168,
    "negatives": 21790,
    "same_class": 1042,
    "same_file": 16730,
    "same_package": 4018,
}
FLOOR_FRACTION = 0.80
# Ratios, not counts: these do not inflate as the corpus grows, so they are held at
# the same 80% convention but are not part of the staleness sweep.
MEASURED_AVG_PER_QUERY = 7.005
MEASURED_COVERAGE = 0.9081
# A floor below this share of a FRESH measurement has stopped being a floor.
STALENESS_LIMIT = 0.70


def _floor(metric: str) -> int:
    """80% of the measurement, derived. Never write a floor out by hand."""
    return math.floor(MEASURED_REAL[metric] * FLOOR_FRACTION)


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


# --- the independent, deliberately BROADER relevance notion -----------------
# The fleet tests below used to rebuild their forbidden index with hn._norm_query,
# the very function the implementation uses. Circular: they can detect the gate
# being BYPASSED, never its relevance notion being too NARROW — and too narrow is
# the failure that poisons training. difflib shares no code with the module.
_NEAR = 0.90
_NEAR_MISS = 0.75


def _similarity(a: str, b: str) -> float:
    """0.0 for anything obviously unrelated (cheap length and quick_ratio gates
    first: the audits below run over ~21k mined negatives)."""
    a, b = a or "", b or ""
    if abs(len(a) - len(b)) > 0.25 * max(len(a), len(b), 1):
        return 0.0
    sm = difflib.SequenceMatcher(None, a, b)
    if sm.quick_ratio() < 0.70:
        return 0.0
    return sm.ratio()


class TestAgainstTheRealRepo:
    def test_extraction_floor(self):
        assert len(real_pairs()) >= _floor("pairs"), len(real_pairs())

    def test_sibling_negatives_floor(self):
        s = hn.summarise(real_sibling(), [])["sibling"]
        assert s["queries"] >= _floor("queries"), s
        assert s["negatives"] >= _floor("negatives"), s
        assert s["avg_per_query"] >= MEASURED_AVG_PER_QUERY * FLOOR_FRACTION, s
        assert s["coverage"] >= MEASURED_COVERAGE * FLOOR_FRACTION, s

    def test_every_scope_is_actually_reached(self):
        """A fleet number that only ever reaches one scope would still look large."""
        by_scope = hn.summarise(real_sibling(), [])["sibling"]["by_scope"]
        for scope in ("same_class", "same_file", "same_package"):
            assert by_scope[scope] >= _floor(scope), (scope, by_scope)

    def test_no_floor_has_gone_stale_against_a_fresh_measurement(self):
        """The header's rule, enforced instead of asserted in prose.

        Two-sided, because each direction catches a different failure:
          * floor > fresh  -> the floor is unreachable; the suite is red for a reason
            that has nothing to do with the miner.
          * floor < STALENESS_LIMIT x fresh -> the corpus outgrew the floor and it now
            tolerates a regression nobody agreed to. This is the one that actually
            happened: floors had drifted to 63.0%-80.0% of actual.
        The failure message carries the fresh numbers, so re-cutting MEASURED_REAL is
        a paste rather than a re-derivation.
        """
        s = hn.summarise(real_sibling(), [])["sibling"]
        fresh = {"pairs": len(real_pairs()), "queries": s["queries"],
                 "negatives": s["negatives"], **s["by_scope"]}
        assert set(fresh) == set(MEASURED_REAL), (
            f"metrics moved: measuring {sorted(fresh)}, recorded {sorted(MEASURED_REAL)}"
        )
        report = {m: (_floor(m), fresh[m], round(_floor(m) / fresh[m], 4))
                  for m in fresh if fresh[m]}
        too_high = {m: v for m, v in report.items() if v[2] > 1.0}
        assert not too_high, f"floor above the fresh measurement: {too_high}"
        stale = {m: v for m, v in report.items() if v[2] < STALENESS_LIMIT}
        assert not stale, (
            f"floors have gone stale (floor, fresh, floor/fresh): {stale}\n"
            f"re-cut MEASURED_REAL to: "
            f"{ {m: fresh[m] for m in sorted(fresh)} }"
        )

    def test_the_correctness_rule_has_real_work_to_do_here(self):
        """Measured 2026-07-26: 351 extracted pairs share a docstring with a sibling
        in the same file or package; floor 280 (80%). If this floor ever fails, the
        filter tests above have stopped exercising anything real."""
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
        assert risky >= 280, (
            f"only {risky} sibling-scoped duplicate docstrings in the tree"
        )

    def test_no_mined_negative_is_a_positive_under_the_modules_own_key(self):
        """The fleet-wide rule, over every mined negative. STATED LIMIT: this uses
        hn._norm_query, so it can only catch the gate being BYPASSED — a negative
        that is a positive under the module's own notion of "same query". It cannot
        see that notion being too narrow; the next test exists for that."""
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
        # measured 2026-07-26: 20880 negatives checked; floor 80%
        assert checked >= 16704, f"only {checked} negatives checked — floor is 16704"
        assert not violations, f"{len(violations)} false negatives: {violations[:5]}"

    def test_no_mined_negative_answers_a_paraphrase_of_its_own_query(self):
        """The NON-circular half: a negative whose own docstring is a paraphrase of
        the record's is a positive in all but bytes, and hn._norm_query cannot see it.
        difflib is the notion here, and it shares nothing with the implementation.

        Measured 2026-07-26 over 20,880 mined negatives: 85 land in the near-miss band
        [0.75, 0.90) — so the 0.90 gate is genuinely approached, not idle — and
        exactly ONE crosses it: `_scripted_probe` vs `_scripted` in the scout-cli
        tests, "Probe fake that replays canned results in order (offline invariant)."
        against "Probe fake replaying canned results in order (the offline
        invariant).".

        That one is a REAL, un-fixed narrowness of the filter, recorded as a tight
        ceiling rather than hidden: paraphrase detection is a similarity claim this
        module deliberately does not make (see its docstring), so the honest thing is
        to bound the leak at what it is and notice when it moves.
        """
        query_of = {(p["path"], p["symbol"]): p["query"] for p in real_pairs()}
        near_misses, leaks, checked, unresolved, same_key = 0, [], 0, 0, 0
        for rec in real_sibling():
            key = hn._norm_query(rec["query"])
            for neg in rec["negatives"]:
                checked += 1
                nq = query_of.get((neg["path"], neg["symbol"]))
                if nq is None:
                    unresolved += 1
                    continue
                if hn._norm_query(nq) == key:
                    same_key += 1
                    continue
                ratio = _similarity(rec["query"], nq)
                if ratio >= _NEAR:
                    leaks.append((rec["symbol"], neg["symbol"], round(ratio, 3)))
                elif ratio >= _NEAR_MISS:
                    near_misses += 1
        assert checked >= 16704, f"only {checked} negatives checked"
        assert unresolved == 0, (
            f"{unresolved} negatives could not be resolved back to a pair — the "
            f"(path, symbol) identity in the output no longer identifies a document"
        )
        assert same_key == 0, (
            f"{same_key} negatives answer a query byte-equal to the record's under "
            f"the module's own key; that is the previous test's failure, not this one"
        )
        # measured 85 near misses; floor 68 (80%). Without this the ceiling below is
        # free: a threshold nothing ever approaches cannot catch anything either.
        assert near_misses >= 68, (
            f"only {near_misses} mined negatives come within {_NEAR_MISS} of the "
            f"paraphrase threshold, so the ceiling below is not being exercised"
        )
        assert len(leaks) <= 1, (
            f"{len(leaks)} paraphrase leaks, ceiling is the 1 known case "
            f"(_scripted_probe/_scripted): {leaks[:5]}"
        )

    def test_disabling_the_filter_would_actually_poison_the_data(self):
        """Proves the rule is load-bearing rather than decorative. Measured
        2026-07-26: 1245 false negatives across 330 queries when the filter is
        bypassed; floors 996 and 264 (80%). The previous floor of 400 was 32% of
        actual."""
        positives: dict = {}
        for p in real_pairs():
            positives.setdefault(hn._norm_query(p["query"]), set()).add(p["positive"])
        unfiltered = _mine_with_the_text_gate_bypassed(real_pairs())
        bad = sum(
            1
            for rec in unfiltered
            for neg in rec["negatives"]
            if neg["text"] in positives[hn._norm_query(rec["query"])]
        )
        queries_hit = sum(
            1
            for rec in unfiltered
            if any(neg["text"] in positives[hn._norm_query(rec["query"])]
                   for neg in rec["negatives"])
        )
        assert bad >= 996, (
            f"only {bad} false negatives without the filter — either the tree "
            f"changed shape or the bypass no longer bypasses anything"
        )
        assert queries_hit >= 264, queries_hit
        assert _first_difference(hn.mine_sibling_negatives(real_pairs()),
                                real_sibling()) == "", (
            "restoring _candidate did not restore the filtered result"
        )

    def test_adjacent_negatives_floor(self):
        recs = hn.mine_adjacent_negatives(real_golden(), window=hn.DEFAULT_WINDOW)
        a = hn.summarise([], recs)["adjacent"]
        # measured 2026-07-26 over 1500 commits (826 exist): 702 queries / 4487
        # negatives / avg 6.392 / coverage 97.6% / distance-1 1983. Floors 80%.
        assert a["queries"] >= 561, a
        assert a["negatives"] >= 3589, a
        assert a["avg_per_query"] >= 5.11, a
        assert a["coverage"] >= 0.78, a
        assert a["by_distance"].get("1", 0) >= 1586, a["by_distance"]

    def test_no_adjacent_negative_is_relevant_under_the_modules_own_key(self):
        """Same stated limit as its source-A counterpart: hn._norm_query is the notion,
        so this catches a bypass and not a too-narrow notion. It does add one check
        that needs no normalisation at all — a negative must never appear in the
        record's OWN relevant list."""
        golden = real_golden()
        relevant: dict = {}
        for g in golden:
            relevant.setdefault(hn._norm_query(g["query"]), set()).update(g["relevant"])
        recs = hn.mine_adjacent_negatives(golden, window=hn.DEFAULT_WINDOW)
        checked, violations, own = 0, [], []
        for rec in recs:
            allowed = relevant[hn._norm_query(rec["query"])]
            for neg in rec["negatives"]:
                checked += 1
                if neg["path"] in allowed:
                    violations.append((rec["query"][:40], neg["path"]))
                if neg["path"] in set(rec["relevant"]):
                    own.append((rec["query"][:40], neg["path"]))
        # measured 2026-07-26: 4487 negatives checked; floor 80%
        assert checked >= 3589, f"only {checked} negatives checked — floor is 3589"
        assert not violations, f"{len(violations)} false negatives: {violations[:5]}"
        assert not own, f"{len(own)} negatives sit in the record's own file list: {own[:5]}"

    def test_no_adjacent_negative_comes_from_a_paraphrased_commit_message(self):
        """The non-circular half for source B. Each negative carries `from_query`, so
        no index has to be rebuilt at all: if the neighbouring commit's message is a
        paraphrase of this one's, its files are relevant to this query and must not be
        mined against it.

        Measured 2026-07-26 over 4,487 negatives: 3 neighbour messages land in the
        near-miss band [0.75, 0.90) — the run of "docs(handoff): coverage x1/x4 ..."
        vs "... x2 + x5 ..." commits — and none crosses it.
        """
        recs = hn.mine_adjacent_negatives(real_golden(), window=hn.DEFAULT_WINDOW)
        near_misses, leaks, checked = 0, [], 0
        for rec in recs:
            key = hn._norm_query(rec["query"])
            for neg in rec["negatives"]:
                checked += 1
                nq = neg["from_query"] or ""
                assert nq, "a negative arrived with no from_query to audit"
                if hn._norm_query(nq) == key:
                    continue
                ratio = _similarity(rec["query"], nq)
                if ratio >= _NEAR:
                    leaks.append((rec["query"][:50], nq[:50], neg["path"]))
                elif ratio >= _NEAR_MISS:
                    near_misses += 1
        assert checked >= 3589, checked
        # measured 3 near misses; floor 2 (80%)
        assert near_misses >= 2, (
            f"only {near_misses} neighbour messages come within {_NEAR_MISS} of the "
            f"paraphrase threshold, so the assertion below is free"
        )
        assert leaks == [], f"{len(leaks)} paraphrase-message leaks: {leaks[:5]}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _run_cli(*args):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _labelled(section: str, label: str) -> str:
    """The value printed against `label` in the text report. Parsed, so the report's
    numbers can be compared with the miner's instead of merely existing."""
    for line in section.splitlines():
        head, sep, tail = line.partition(":")
        if sep and head.strip() == label:
            return tail.strip()
    raise AssertionError(f"{label!r} is not in the report section:\n{section}")


class TestCLI:
    def test_json_report_on_a_real_subtree(self, tmp_path):
        out = tmp_path / "negatives.jsonl"
        stdout = _run_cli("--path", str(_SUBTREE), "--no-git", "--json",
                          "--out", str(out))
        summary = json.loads(stdout)
        # measured 2026-07-26 on apps/ava-factory/scripts: 93 queries, 744 negatives,
        # avg 8.0 (every query saturates the default n=8), coverage 100%. Floors 80%.
        assert summary["sibling"]["queries"] >= 74, summary
        assert summary["sibling"]["negatives"] >= 595, summary
        assert summary["sibling"]["avg_per_query"] >= 6.4, summary
        assert summary["adjacent"] == {
            "queries": 0, "negatives": 0, "avg_per_query": 0.0,
            "queries_with_negatives": 0, "coverage": 0.0, "by_distance": {},
        }, "--no-git must report zero, not silently invent a source-B number"
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == summary["sibling"]["queries"]
        assert all(json.loads(ln)["source"] == "sibling" for ln in lines)

    def test_the_text_report_prints_the_numbers_the_miner_computed(self):
        """The old test asserted that six literal strings appeared in stdout and
        checked no number whatsoever, so hard-coding n=8 inside main() passed it.
        Every number in the report is now parsed and compared against an in-process
        run with the SAME arguments."""
        stdout = _run_cli("--path", str(_SUBTREE), "--no-git", "--n", "4")
        head, sep, tail = stdout.partition("SOURCE B")
        assert sep, f"the report no longer has a SOURCE B section:\n{stdout}"
        assert "SOURCE A" in head

        expected = hn.summarise(
            hn.mine_sibling_negatives(hn.pairs_from_tree(_SUBTREE), n=4), [])
        s, t = expected["sibling"], expected["total"]
        # measured 2026-07-26 at --n 4: 93 queries / 372 negatives; floors 80%
        assert s["queries"] >= 74 and s["negatives"] >= 297, s
        assert s["negatives"] != s["queries"] * hn.DEFAULT_N, (
            "--n 4 must not produce the default-n count, or this test cannot tell a "
            "hard-coded n from an honoured one"
        )
        assert _labelled(head, "queries") == str(s["queries"])
        assert _labelled(head, "negatives mined") == str(s["negatives"])
        assert _labelled(head, "avg per query") == f"{s['avg_per_query']:.3f}"
        assert _labelled(head, "queries with >=1") == (
            f"{s['queries_with_negatives']} ({s['coverage']:.1%})"
        )
        for name, count in s["by_scope"].items():
            assert [name, str(count)] in [ln.split() for ln in head.splitlines()], (
                f"scope line for {name}={count} missing from:\n{head}"
            )
        assert _labelled(tail, "queries") == "0", "--no-git must print zero for B"
        assert _labelled(tail, "TOTAL") == (
            f"{t['negatives']} negatives over {t['queries']} queries  "
            f"(avg {t['avg_per_query']:.3f})"
        )

    def test_the_cli_honours_max_commits_and_window_for_source_b(self):
        """Kills a hard-coded mine_pairs(50), window=5 or n=8 inside main(): source B
        is recomputed in-process from the SAME arguments and compared exactly."""
        golden = hn.retrieval_eval.mine_pairs(60)
        # measured 2026-07-26: 60 commits -> 57 golden queries, 50 -> 47. The two must
        # differ or this test cannot see a hard-coded depth at all.
        assert len(golden) >= 45, len(golden)
        assert len(hn.retrieval_eval.mine_pairs(50)) != len(golden), (
            "50 and 60 commits yield the same golden count here, so a hard-coded "
            "mine_pairs(50) would be indistinguishable from --max-commits 60"
        )
        expected = hn.summarise(
            [], hn.mine_adjacent_negatives(golden, window=1, n=2))["adjacent"]
        assert expected["negatives"] > 0, expected
        assert list(expected["by_distance"]) == ["1"], (
            "window=1 must reach distance 1 only, or --window is not being tested"
        )
        stdout = _run_cli("--path", str(_SUBTREE), "--max-commits", "60",
                          "--window", "1", "--n", "2", "--json")
        assert json.loads(stdout)["adjacent"] == expected


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
        # measured 2026-07-26: 4487 negatives; floor 80%. The previous floor of 1000
        # was 22% of actual.
        assert total >= 3589, f"non-vacuity: only {total} negatives mined"
        bad = [
            (r["query"][:60], n["path"])
            for r in out
            for n in r["negatives"]
            if hn.retrieval_eval.leaks_filename(r["query"], [n["path"]])
        ]
        assert bad == [], f"{len(bad)} query-named files still mined as negatives: {bad[:3]}"
