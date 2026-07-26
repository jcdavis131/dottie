"""MinHash/LSH near-duplicate detection — the properties that make it worth running.

Four things can silently break a deduplicator, and each one still prints a
confident number afterwards:

  1. NON-DETERMINISM. builtin `hash()` is PYTHONHASHSEED-salted, so a corpus
     deduplicated today is deduplicated differently tomorrow, and the training
     shard no longer matches the eval shard. `TestDeterminism` runs REAL
     subprocesses with deliberately different PYTHONHASHSEED values. It is the
     only test here that cannot be faked by an in-process check, and it exists
     because hash()-as-seed is a recorded bug class in this repo.
  2. NORMALISATION THAT DOES NOTHING. If `normalize` fails to strip comments and
     docstrings, only byte-identical copies collide and the whole exercise is a
     `set()` with extra steps. Tested by asserting that comment-only,
     docstring-only and formatting-only variants collide.
  3. OVER-CLUSTERING. Two unrelated functions merged into one cluster deletes
     real training data. Tested both on hand-written pairs and on the real tree.
  4. bands*rows != num_perm. This does not raise: the tail of every signature is
     just never examined, recall drops, and the run looks fine.

Every fleet-wide assertion carries a MEASURED floor, not `> 0`. The floors below
were measured on 2026-07-26 against apps/scout-cli/bigbang/core and are quoted in
the assertion messages so a future drop is legible instead of mysterious.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "scripts" / "minhash_dedup.py"
_SPEC = importlib.util.spec_from_file_location("minhash_dedup", SRC)
md = importlib.util.module_from_spec(_SPEC)
sys.modules["minhash_dedup"] = md
_SPEC.loader.exec_module(md)

SCOUT_CORE = Path(__file__).resolve().parents[2] / "scout-cli" / "bigbang" / "core"

# --------------------------------------------------------------------------
# fixtures: one function, and variants of it that MUST or MUST NOT collide
# --------------------------------------------------------------------------
ORIGINAL = '''
def open_store(path):
    """Open the store, creating the parent directory if it is missing."""
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn
'''

# identical bytes
EXACT = ORIGINAL

# same tokens, different layout: single->double quotes, extra blank lines,
# 8-space indent, a trailing comma, redundant parens.
FORMATTED = '''
def open_store(path):

        """Open the store, creating the parent directory if it is missing."""

        p = Path(path)

        if (str(p) != ':memory:'):
                p.parent.mkdir(
                    parents = True,
                    exist_ok = True,
                )

        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn
'''

# identical code, different prose only
COMMENTED = '''
def open_store(path):
    """A completely different docstring that shares no words with the original."""
    # Resolve first; a bare string breaks on Windows.
    p = Path(path)
    if str(p) != ":memory:":
        # Never assume the directory exists.
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))  # inline trailer
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn
'''

# A real near-duplicate: same shape, renamed, one extra statement. Measured
# true Jaccard 0.5714, estimated 0.6328 -- above LSH's collision curve at 16x8
# (so it IS a candidate) but below the 0.8 verification threshold.
NEAR = '''
def open_ledger(path):
    """Open the ledger, creating the parent directory if it is missing."""
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
'''

# genuinely different work
DIFFERENT = '''
def parse_retry_after(header):
    """Return the number of seconds a Retry-After header asks the client to wait."""
    if header is None:
        return 0.0
    value = header.strip()
    if value.isdigit():
        return float(value)
    stamp = email.utils.parsedate_to_datetime(value)
    delta = stamp - datetime.datetime.now(datetime.timezone.utc)
    return max(delta.total_seconds(), 0.0)
'''

ALSO_DIFFERENT = '''
def rolling_median(samples, window):
    """Yield the median of the trailing window for every position in samples."""
    buf = collections.deque(maxlen=window)
    for s in samples:
        buf.append(s)
        ordered = sorted(buf)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            yield ordered[mid]
        else:
            yield (ordered[mid - 1] + ordered[mid]) / 2
'''


# ==========================================================================
# 1. normalize
# ==========================================================================
class TestNormalize:
    def test_comments_are_gone(self):
        out = md.normalize(COMMENTED)
        assert "Never assume the directory exists" not in out
        assert "inline trailer" not in out
        assert "conn.executescript(_SCHEMA)" in out, "normalize ate the code too"

    def test_docstrings_are_gone(self):
        out = md.normalize(ORIGINAL)
        assert "Open the store" not in out
        assert "def open_store(path)" in out

    def test_formatting_only_variant_is_byte_identical_after_normalize(self):
        """This is the entire justification for the ast round-trip.

        Indentation, quote style, blank lines, spaces around `=` in a call, a
        magic trailing comma and redundant parens are all layout. If any of them
        survived, a reformatted copy would be a distinct training example.
        """
        assert ORIGINAL != FORMATTED, "fixture is not actually reformatted"
        assert md.normalize(ORIGINAL) == md.normalize(FORMATTED)

    def test_comment_and_docstring_variant_is_byte_identical_after_normalize(self):
        assert md.normalize(ORIGINAL) == md.normalize(COMMENTED)

    def test_different_code_normalizes_differently(self):
        assert md.normalize(ORIGINAL) != md.normalize(DIFFERENT)

    def test_docstring_only_body_becomes_pass_not_a_crash(self):
        """ast.unparse cannot render an empty suite; a stub must not raise."""
        out = md.normalize('def stub():\n    """doc only"""\n')
        assert out == md.normalize("def stub():\n    pass\n")

    def test_unparseable_source_falls_back_instead_of_raising(self):
        bad = "def broken(:\n    pass"
        assert md.canonical_python(bad) is None
        assert md.normalize(bad) == "def broken(: pass"

    def test_whitespace_is_collapsed_even_on_the_fallback_path(self):
        assert md.normalize("def  f(:\n\n\t x   =  1") == "def f(: x = 1"

    def test_empty_input(self):
        assert md.normalize("") == ""
        assert md.normalize("   \n\t ") == ""


# ==========================================================================
# 2. shingles
# ==========================================================================
class TestShingles:
    def test_kgram_count(self):
        text = " ".join(f"t{i}" for i in range(10))
        assert len(md.shingles(text, k=5)) == 10 - 5 + 1
        assert len(md.shingles(text, k=1)) == 10

    def test_kgram_content(self):
        assert md.shingles("a b c d", k=2) == frozenset({"a b", "b c", "c d"})

    def test_short_document_yields_one_shingle_not_zero(self):
        """A doc shorter than k must NOT return the empty set.

        Empty shingle sets all produce the same all-maximum signature, so every
        short function in the corpus would land in one giant false cluster and
        the deduplicator would delete them. The failure is silent: the run just
        reports one very large cluster and a smaller keep-set.
        """
        sh = md.shingles("return None", k=5)
        assert sh == frozenset({"return None"})
        other = md.shingles("raise KeyError", k=5)
        assert md.minhash(sh) != md.minhash(other), (
            "two different short docs produced the same signature"
        )

    def test_empty_text_is_empty(self):
        assert md.shingles("", k=5) == frozenset()

    def test_bad_k_raises(self):
        with pytest.raises(ValueError):
            md.shingles("a b c", k=0)


# ==========================================================================
# 3. minhash
# ==========================================================================
class TestMinhash:
    def test_signature_length_is_num_perm(self):
        sh = md.shingles(md.normalize(ORIGINAL))
        for n in (16, 64, 128, 256):
            assert len(md.minhash(sh, n)) == n

    def test_identical_input_identical_signature(self):
        a = md.minhash(md.shingles(md.normalize(ORIGINAL)))
        b = md.minhash(md.shingles(md.normalize(EXACT)))
        assert a == b
        assert md.jaccard_estimate(a, b) == 1.0

    def test_disjoint_sets_estimate_near_zero(self):
        a = md.minhash(frozenset(f"a{i}" for i in range(200)))
        b = md.minhash(frozenset(f"b{i}" for i in range(200)))
        est = md.jaccard_estimate(a, b)
        assert est <= 0.05, f"disjoint sets estimated at J={est}"

    @pytest.mark.parametrize(
        "n_a,n_b,overlap",
        [(100, 100, 0), (100, 100, 50), (100, 100, 90), (200, 200, 100), (60, 140, 40)],
    )
    def test_jaccard_estimate_within_tolerance(self, n_a, n_b, overlap):
        """|estimate - truth| must stay inside the classic MinHash error bound.

        TOLERANCE = 1/sqrt(num_perm) = 1/sqrt(128) = 0.0884. That is the standard
        bound quoted for MinHash: the estimator is a mean of `num_perm` Bernoulli(J)
        indicators, so its standard error is sqrt(J(1-J)/num_perm) <= 0.0442 at
        num_perm=128, and 1/sqrt(num_perm) is the conventional ~2-sigma envelope.
        Anything looser would not detect a broken permutation family; anything
        tighter would be asserting on this particular seed's luck rather than on
        the algorithm. The permutations are blake2b-derived and therefore fixed,
        so this test is deterministic despite being about a random estimator.

        Measured worst case across the five cases below on 2026-07-26: 0.0260
        (at true J=0.3333, where the estimator's variance is highest).
        """
        tolerance = md.NUM_PERM**-0.5
        a = frozenset(f"s{i}" for i in range(n_a))
        b = frozenset(f"s{i}" for i in range(n_a - overlap, n_a - overlap + n_b))
        truth = md.true_jaccard(a, b)
        est = md.jaccard_estimate(md.minhash(a), md.minhash(b))
        assert abs(est - truth) <= tolerance, (
            f"true J={truth:.4f} estimated {est:.4f}, error "
            f"{abs(est - truth):.4f} > tolerance {tolerance:.4f}"
        )

    def test_estimator_tracks_truth_monotonically(self):
        """A constant-output estimator would pass every single-point tolerance."""
        base = frozenset(f"s{i}" for i in range(200))
        ests = []
        for overlap in (0, 50, 100, 150, 200):
            other = frozenset(f"s{i}" for i in range(200 - overlap, 400 - overlap))
            ests.append(md.jaccard_estimate(md.minhash(base), md.minhash(other)))
        assert ests == sorted(ests), f"estimate did not increase with overlap: {ests}"
        assert ests[-1] == 1.0 and ests[0] <= 0.05

    def test_mismatched_signature_lengths_raise(self):
        with pytest.raises(ValueError):
            md.jaccard_estimate(md.minhash(frozenset("ab"), 64), md.minhash(frozenset("ab"), 128))

    def test_permutation_coefficients_are_fixed_and_nonzero(self):
        perms = md._permutations(128)
        assert len(perms) == 128
        assert len(set(perms)) == 128, "duplicate permutations reduce the real num_perm"
        assert all(a != 0 for a, _ in perms), "a==0 collapses the permutation"
        assert md._permutations(128) is perms, "cache returned a different object"

    def test_no_builtin_hash_and_no_random_anywhere_in_the_module(self):
        """Parsed with `ast`, never grepped.

        The module docstring discusses `hash()` in prose at length, so a regex or
        a grep would flag it and be wrong — which is precisely the failure mode
        that produced three wrong answers in one day in this repo. Only real
        Call/Import nodes count.
        """
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        hash_calls = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "hash"
        ]
        assert hash_calls == [], (
            f"builtin hash() called at line(s) {hash_calls} — PYTHONHASHSEED-salted"
        )
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                imported.add(n.module.split(".")[0])
        assert "random" not in imported, "an unseeded RNG makes the corpus irreproducible"
        third_party = imported - set(sys.stdlib_module_names)
        assert third_party == set(), f"non-stdlib import(s): {sorted(third_party)}"


# ==========================================================================
# 4. determinism ACROSS PROCESSES — the hash()-seeded-implementation trap
# ==========================================================================
_PROBE = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("md", sys.argv[1])
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)
docs = json.loads(sys.argv[2])
res = md.cluster_documents(docs)
print(json.dumps({
    "sig": list(md.minhash(md.shingles(md.normalize(docs["a"])))),
    "clusters": res["clusters"],
    "keep": res["keep"],
    "pairs": res["pairs"],
}))
"""


def _run_probe(seed: str, docs: dict) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, str(SRC), json.dumps(docs)],
        capture_output=True, text=True, env=env, timeout=180,
    )
    assert out.returncode == 0, f"probe failed (seed={seed}):\n{out.stderr}"
    return json.loads(out.stdout)


PROBE_DOCS = {
    "a": ORIGINAL, "b": FORMATTED, "c": COMMENTED,
    "d": DIFFERENT, "e": ALSO_DIFFERENT,
}


class TestDeterminism:
    def test_signature_is_identical_in_two_separate_processes(self):
        """Two real interpreters, two different PYTHONHASHSEED values.

        PYTHONHASHSEED can only be set before the interpreter starts, so this
        cannot be done in-process — which is exactly why an in-process
        determinism check would pass over a hash()-seeded implementation.
        """
        one = _run_probe("0", PROBE_DOCS)
        two = _run_probe("123456789", PROBE_DOCS)
        assert one["sig"] == two["sig"], (
            "the same input produced different signatures in two processes — "
            "something in the hash path is PYTHONHASHSEED-salted"
        )
        assert len(one["sig"]) == md.NUM_PERM

    def test_in_process_signature_matches_the_subprocess(self):
        mine = list(md.minhash(md.shingles(md.normalize(ORIGINAL))))
        assert mine == _run_probe("0", PROBE_DOCS)["sig"]

    def test_clusters_and_keep_set_are_identical_across_processes(self):
        """Bucket keys and component order must not leak set/dict iteration order."""
        one = _run_probe("0", PROBE_DOCS)
        two = _run_probe("987654321", PROBE_DOCS)
        assert one["clusters"] == two["clusters"]
        assert one["keep"] == two["keep"]
        assert one["pairs"] == two["pairs"]
        assert one["clusters"], "probe corpus produced no clusters — test is vacuous"

    def test_document_insertion_order_does_not_change_the_answer(self):
        forward = md.cluster_documents(PROBE_DOCS)
        backward = md.cluster_documents(dict(reversed(list(PROBE_DOCS.items()))))
        assert forward["clusters"] == backward["clusters"]
        assert forward["keep"] == backward["keep"]


# ==========================================================================
# 5. LSH banding — enforced, not assumed
# ==========================================================================
class TestBanding:
    def test_the_default_is_consistent(self):
        assert md.BANDS * md.ROWS == md.NUM_PERM

    def test_valid_banding_is_accepted(self):
        for bands, rows in ((16, 8), (32, 4), (8, 16), (128, 1), (1, 128)):
            md.check_banding(128, bands, rows)

    @pytest.mark.parametrize(
        "num_perm,bands,rows", [(128, 16, 7), (128, 17, 8), (128, 8, 8), (128, 0, 8), (128, 16, 0)]
    )
    def test_invalid_banding_raises(self, num_perm, bands, rows):
        with pytest.raises(ValueError):
            md.check_banding(num_perm, bands, rows)

    def test_the_error_says_what_actually_goes_wrong(self):
        with pytest.raises(ValueError, match="never be examined"):
            md.check_banding(128, 16, 7)

    def test_lsh_buckets_checks_the_actual_signature_length(self):
        """A 64-perm signature banded 16x8 must be rejected, not silently indexed."""
        sigs = {"a": md.minhash(md.shingles(md.normalize(ORIGINAL)), 64)}
        with pytest.raises(ValueError):
            md.lsh_buckets(sigs, bands=16, rows=8)

    def test_cluster_documents_checks_banding(self):
        with pytest.raises(ValueError):
            md.cluster_documents({"a": ORIGINAL}, num_perm=128, bands=16, rows=7)

    def test_band_index_is_part_of_the_bucket_key(self):
        """Band 0 == (1,2) and band 1 == (1,2) must not share a bucket.

        Without the band index in the digest, a signature whose bands repeat
        collides with itself and every other signature that repeats the same
        run of values — a systematic false positive on low-entropy documents.
        """
        repeated = tuple([7, 7] * 4)  # 8 positions, every 2-row band identical
        buckets = md.lsh_buckets({"x": repeated}, bands=4, rows=2)
        assert len(buckets) == 4, (
            f"4 bands of an all-identical signature produced {len(buckets)} "
            f"bucket(s); the band index is missing from the key"
        )

    def test_a_shared_band_makes_a_candidate_pair(self):
        sigs = {"a": (1, 2, 3, 4), "b": (1, 2, 9, 9), "c": (5, 5, 5, 5)}
        pairs = md.candidate_pairs(sigs, bands=2, rows=2)
        assert ("a", "b") in pairs
        assert ("a", "c") not in pairs and ("b", "c") not in pairs

    def test_candidate_pairs_are_ordered_and_deduplicated(self):
        sigs = {"b": (1, 2, 3, 4), "a": (1, 2, 3, 4)}  # collide in BOTH bands
        pairs = md.candidate_pairs(sigs, bands=2, rows=2)
        assert pairs == {("a", "b")}, f"expected one ordered pair, got {pairs}"


# ==========================================================================
# 6. union-find
# ==========================================================================
class TestUnionFind:
    def test_transitive_chaining(self):
        uf = md.UnionFind()
        uf.union("a", "b")
        uf.union("b", "c")
        uf.union("x", "y")
        assert uf.components() == [["a", "b", "c"], ["x", "y"]]

    def test_merging_two_existing_components(self):
        uf = md.UnionFind()
        uf.union("a", "b")
        uf.union("c", "d")
        assert len(uf.components()) == 2
        uf.union("b", "c")
        assert uf.components() == [["a", "b", "c", "d"]]

    def test_self_union_and_repeats_are_harmless(self):
        uf = md.UnionFind()
        uf.union("a", "a")
        uf.union("a", "b")
        uf.union("a", "b")
        uf.union("b", "a")
        assert uf.components() == [["a", "b"]]

    def test_output_is_sorted_largest_first_and_deterministic(self):
        def build(pairs):
            uf = md.UnionFind()
            for a, b in pairs:
                uf.union(a, b)
            return uf.components()

        pairs = [("d", "c"), ("z", "y"), ("c", "b"), ("b", "a")]
        assert build(pairs) == build(list(reversed(pairs)))
        comps = build(pairs)
        assert [len(c) for c in comps] == [4, 2]
        assert comps[0] == ["a", "b", "c", "d"]

    def test_path_compression_survives_a_long_chain(self):
        uf = md.UnionFind()
        for i in range(2000):
            uf.union(f"n{i:05d}", f"n{i + 1:05d}")
        assert len(uf.components()) == 1
        assert len(uf.components()[0]) == 2001


# ==========================================================================
# 7. end-to-end clustering behaviour
# ==========================================================================
class TestClustering:
    def test_exact_duplicate_is_clustered(self):
        res = md.cluster_documents({"one": ORIGINAL, "two": EXACT, "far": DIFFERENT})
        assert res["clusters"] == [["one", "two"]]

    def test_formatting_only_variant_is_clustered(self):
        """The point of normalize(): layout must not create a new example."""
        res = md.cluster_documents({"plain": ORIGINAL, "pretty": FORMATTED, "far": DIFFERENT})
        assert res["clusters"] == [["plain", "pretty"]]

    def test_comment_and_docstring_only_variant_is_clustered(self):
        res = md.cluster_documents({"bare": ORIGINAL, "documented": COMMENTED, "far": DIFFERENT})
        assert res["clusters"] == [["bare", "documented"]]

    def test_two_genuinely_different_functions_are_not_clustered(self):
        res = md.cluster_documents({"retry": DIFFERENT, "median": ALSO_DIFFERENT})
        assert res["clusters"] == [], (
            "two unrelated functions were merged — deduplication would delete "
            "real training data"
        )
        assert res["keep"] == ["median", "retry"]

    def test_a_candidate_pair_below_threshold_is_rejected(self):
        """Verification, not just LSH. A candidate pair is not an answer.

        ORIGINAL/NEAR share a band (measured: they ARE an LSH candidate) but
        their estimated Jaccard is 0.6328. Without the re-scoring step one
        unlucky band collision chains them together through union-find and the
        cluster count becomes fiction. The first assertion below proves the pair
        reaches the verifier at all, so this is not a vacuous "nothing happened".
        """
        docs = {"a": ORIGINAL, "b": NEAR}
        sigs = {k: md.minhash(md.shingles(md.normalize(v))) for k, v in docs.items()}
        assert md.candidate_pairs(sigs) == {("a", "b")}, "not even a candidate"
        est = md.jaccard_estimate(sigs["a"], sigs["b"])
        assert 0.6 <= est < 0.7, f"fixture drifted: estimated J={est} (measured 0.6328)"

        assert md.cluster_documents(docs, threshold=0.8)["clusters"] == []
        # ...and the SAME pair does cluster once the threshold drops under the
        # estimate, which proves the threshold is consulted, not decorative.
        assert md.cluster_documents(docs, threshold=0.6)["clusters"] == [["a", "b"]]

    def test_a_genuinely_different_function_never_becomes_a_candidate(self):
        """LSH is the cheap pre-filter; it should reject long before scoring."""
        sigs = {
            k: md.minhash(md.shingles(md.normalize(v)))
            for k, v in {"a": ORIGINAL, "b": DIFFERENT}.items()
        }
        assert md.candidate_pairs(sigs) == set()

    def test_keep_set_is_one_survivor_per_cluster_plus_every_singleton(self):
        docs = {
            "dup1": ORIGINAL, "dup2": FORMATTED, "dup3": COMMENTED,
            "solo1": DIFFERENT, "solo2": ALSO_DIFFERENT,
        }
        res = md.cluster_documents(docs)
        assert res["clusters"] == [["dup1", "dup2", "dup3"]]
        assert res["keep"] == ["dup1", "solo1", "solo2"]
        assert res["dropped"] == ["dup2", "dup3"]
        assert set(res["keep"]) | set(res["dropped"]) == set(docs)
        assert not set(res["keep"]) & set(res["dropped"])

    def test_transitive_clusters_form_one_group(self):
        res = md.cluster_documents({"a": ORIGINAL, "b": FORMATTED, "c": COMMENTED})
        assert len(res["clusters"]) == 1 and len(res["clusters"][0]) == 3

    def test_empty_documents_are_skipped_not_clustered_together(self):
        docs = {"e1": "", "e2": "   \n ", "real": DIFFERENT}
        res = md.cluster_documents(docs)
        assert res["documents"] == 1
        assert res["skipped_empty"] == 2
        assert res["clusters"] == []

    def test_empty_corpus(self):
        res = md.cluster_documents({})
        assert res["documents"] == 0 and res["clusters"] == [] and res["keep"] == []


# ==========================================================================
# 8. corpus collection
# ==========================================================================
class TestCollection:
    def test_iter_functions_qualifies_names(self):
        src = (
            "class Store:\n"
            "    def load(self):\n"
            "        def inner():\n"
            "            return 1\n"
            "        return inner()\n"
            "\n"
            "async def fetch():\n"
            "    return 2\n"
        )
        keys = [k for k, _ in md.iter_functions(src, "m.py")]
        assert keys == ["m.py::Store.load", "m.py::Store.load.inner", "m.py::fetch"]

    def test_iter_functions_on_unparseable_source_yields_nothing(self):
        assert list(md.iter_functions("def broken(:", "m.py")) == []

    def test_file_discovery_is_reused_from_ast_pairs(self):
        """No second copy of the skip-directory set.

        Two definitions of "which files count" drift, and this repo has been
        bitten by exactly that twice. `walk` must BE ast_pairs.walk, not a
        lookalike.
        """
        assert md.walk.__code__.co_filename.endswith("ast_pairs.py")

    def test_collect_documents_function_and_file_units(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "a.py").write_text(ORIGINAL + DIFFERENT, encoding="utf-8")
        (tmp_path / "pkg" / "b.py").write_text(ALSO_DIFFERENT, encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.py").write_text("def x(): pass", encoding="utf-8")

        funcs, stats = md.collect_documents(tmp_path, "function")
        assert stats["files"] == 2, "__pycache__ was not skipped"
        assert sorted(funcs) == [
            "pkg/a.py::open_store", "pkg/a.py::parse_retry_after", "pkg/b.py::rolling_median",
        ]
        files, stats2 = md.collect_documents(tmp_path, "file")
        assert sorted(files) == ["pkg/a.py", "pkg/b.py"]
        assert stats2["unparseable"] == 0

    def test_unparseable_files_are_counted_out_loud(self, tmp_path):
        (tmp_path / "ok.py").write_text(DIFFERENT, encoding="utf-8")
        (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        _, stats = md.collect_documents(tmp_path, "file")
        assert stats["files"] == 2 and stats["unparseable"] == 1


# ==========================================================================
# 9. the real tree — measured floors, not "> 0"
# ==========================================================================
@pytest.fixture(scope="module")
def real_result():
    """One scan of apps/scout-cli/bigbang/core, shared by the whole class.

    Module-scoped and defined outside the class: a class-scoped fixture written
    as an instance method is deprecated in pytest 8 and its attributes are not
    visible to the tests anyway.
    """
    docs, stats = md.collect_documents(SCOUT_CORE, "function")
    return md.cluster_documents(docs), stats


@pytest.mark.skipif(not SCOUT_CORE.exists(), reason=f"scout-cli absent at {SCOUT_CORE}")
class TestAgainstTheRealTree:
    """Measured on apps/scout-cli/bigbang/core, 2026-07-26, defaults
    (k=5, num_perm=128, bands=16, rows=8, threshold=0.8):

        files scanned          51
        corpus (functions)     1177
        candidate pairs        143
        verified pairs         114
        clusters               5
        largest cluster        15   (open_store/open_ledger, 15 distinct modules)
        duplicates dropped     20   (1.7% of the corpus)
        min true J of a kept pair   0.8400
        worst |est - true| on real pairs  0.0357

    Floors below sit ~15% under each measurement so ordinary churn does not
    break them, but a refactor that stops finding duplicates does.
    """

    def test_corpus_is_the_size_it_was_measured_at(self, real_result):
        res, stats = real_result
        assert stats["files"] >= 43, f"only {stats['files']} files (measured 51)"
        assert res["documents"] >= 1000, (
            f"corpus collapsed to {res['documents']} functions; measured 1177"
        )

    def test_real_duplicates_are_found(self, real_result):
        res, _ = real_result
        assert len(res["clusters"]) >= 4, (
            f"only {len(res['clusters'])} clusters; measured 5 on 2026-07-26"
        )
        assert len(res["dropped"]) >= 16, (
            f"only {len(res['dropped'])} duplicate documents; measured 20"
        )

    def test_the_largest_cluster_spans_many_files(self, real_result):
        """Guards the interesting finding: the open_store/open_ledger family."""
        res, _ = real_result
        largest = res["clusters"][0]
        assert len(largest) >= 12, f"largest cluster is {len(largest)}; measured 15"
        files = {m.split("::")[0] for m in largest}
        assert len(files) >= 12, (
            f"largest cluster spans only {len(files)} files — a cross-file "
            f"duplicate family is what actually poisons contrastive batches"
        )

    def test_the_dedup_rate_is_plausible_not_catastrophic(self, real_result):
        """Over-clustering is as bad as under-clustering, and looks like success."""
        res, _ = real_result
        rate = len(res["dropped"]) / res["documents"]
        assert 0.005 <= rate <= 0.15, (
            f"{rate:.1%} of the corpus called duplicate; measured 1.7%. Above 15% "
            f"means the threshold or the normaliser is destroying real examples"
        )

    def test_every_verified_pair_really_is_near_duplicate(self, real_result):
        """Re-scores LSH's answer against EXACT Jaccard on the shingle sets.

        The estimate is what clustering used; the truth is what it should have
        used. If the estimator were broken, this is where it shows.
        """
        res, _ = real_result
        sets = res["shingle_sets"]
        errors = [
            (a, b, est, md.true_jaccard(sets[a], sets[b]))
            for a, b, est in res["pairs"]
        ]
        assert len(errors) >= 90, f"only {len(errors)} verified pairs; measured 114"
        wrong = [e for e in errors if e[3] < 0.5]
        assert wrong == [], f"pairs called duplicate with true Jaccard < 0.5: {wrong[:3]}"
        worst = max(abs(est - truth) for _, _, est, truth in errors)
        assert worst <= 0.15, (
            f"worst estimate error on real code is {worst:.4f}; measured 0.0357 "
            f"on 2026-07-26. The classic 1/sqrt(128)=0.0884 bound is per-pair, "
            f"and 0.15 leaves room for the maximum over ~114 of them"
        )

    def test_a_docstring_only_duplicate_pair_exists_in_the_real_tree(self, real_result):
        """The concrete win: functions whose ONLY difference is their prose.

        apm.py::open_store and cite.py::open_store have different docstrings and
        byte-identical bodies. Without normalize() they are two training
        examples; with it they are one. Asserted structurally (some pair with
        true Jaccard 1.0 across two different files) rather than by name, so a
        rename does not fail the suite.
        """
        res, _ = real_result
        sets = res["shingle_sets"]
        identical_across_files = [
            (a, b) for a, b, _ in res["pairs"]
            if a.split("::")[0] != b.split("::")[0] and md.true_jaccard(sets[a], sets[b]) == 1.0
        ]
        assert len(identical_across_files) >= 55, (
            f"only {len(identical_across_files)} byte-identical-after-normalise "
            f"cross-file pairs; measured 68 on 2026-07-26"
        )


# ==========================================================================
# 10. CLI
# ==========================================================================
class TestCLI:
    def _corpus(self, tmp_path):
        (tmp_path / "a.py").write_text(ORIGINAL, encoding="utf-8")
        (tmp_path / "b.py").write_text(FORMATTED, encoding="utf-8")
        (tmp_path / "c.py").write_text(DIFFERENT, encoding="utf-8")
        return tmp_path

    def test_json_summary_reports_what_it_promises(self, tmp_path, capsys):
        base = self._corpus(tmp_path)
        assert md.main(["--path", str(base), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["corpus_size"] == 3
        assert out["clusters"] == 1
        assert out["largest_cluster_size"] == 2
        assert sorted(out["largest_cluster"]) == ["a.py::open_store", "b.py::open_store"]
        assert out["keep_set_size"] == 2
        assert out["params"]["bands"] * out["params"]["rows"] == out["params"]["num_perm"]

    def test_keep_set_is_written(self, tmp_path):
        base = self._corpus(tmp_path)
        target = tmp_path / "keep.json"
        assert md.main(["--path", str(base), "--keep-set", str(target), "--json"]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["keep"] == ["a.py::open_store", "c.py::parse_retry_after"]
        assert data["dropped"] == ["b.py::open_store"]

    def test_file_unit_runs(self, tmp_path, capsys):
        base = self._corpus(tmp_path)
        assert md.main(["--path", str(base), "--unit", "file", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["corpus_size"] == 3 and out["clusters"] == 1

    def test_bad_banding_exits_nonzero(self, tmp_path, capsys):
        assert md.main(["--path", str(tmp_path), "--bands", "16", "--rows", "7"]) == 2
        assert "bands*rows" in capsys.readouterr().err

    def test_missing_path_exits_nonzero(self, tmp_path, capsys):
        assert md.main(["--path", str(tmp_path / "nope")]) == 2
        assert "no such path" in capsys.readouterr().err

    def test_human_output_names_the_cluster(self, tmp_path, capsys):
        base = self._corpus(tmp_path)
        assert md.main(["--path", str(base)]) == 0
        text = capsys.readouterr().out
        assert "corpus size     : 3" in text
        assert "largest cluster : 2 members" in text
        assert "b.py::open_store" in text

    def test_runs_as_a_real_subprocess(self, tmp_path):
        base = self._corpus(tmp_path)
        out = subprocess.run(
            [sys.executable, str(SRC), "--path", str(base), "--json"],
            capture_output=True, text=True, timeout=180,
        )
        assert out.returncode == 0, out.stderr
        assert json.loads(out.stdout)["clusters"] == 1
