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
  5. A DROP THAT IS NOT JUSTIFIED BY THE DOCUMENT REPLACING IT. Single-linkage
     union-find plus estimator error will delete a document whose TRUE Jaccard to
     its survivor is under the advertised threshold, and every count printed
     afterwards still looks healthy. `TestDropVsSurvivor` measures exactly that
     quantity -- on a hand-built chain where the failure is forced, and on the
     real tree where it was found. Its floor IS the threshold, because the
     guarantee is by construction rather than by luck.
  6. A CORPUS THAT SILENTLY LOSES DOCUMENTS. Two defs sharing a qualified name
     overwrote each other, and a file that failed to open was counted as
     scanned. Both are tested by exact counts, never by `>= 0`.

Every fleet-wide assertion carries a MEASURED floor, not `> 0`. The floors below
were measured on 2026-07-26 against apps/scout-cli/bigbang/core and
apps/scout-cli/bigbang/plugins, and are quoted in the assertion messages so a
future drop is legible instead of mysterious.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "scripts" / "minhash_dedup.py"
_SPEC = importlib.util.spec_from_file_location("minhash_dedup", SRC)
md = importlib.util.module_from_spec(_SPEC)
sys.modules["minhash_dedup"] = md
_SPEC.loader.exec_module(md)

_BIGBANG = Path(__file__).resolve().parents[2] / "scout-cli" / "bigbang"
SCOUT_CORE = _BIGBANG / "core"
# bigbang/plugins, not core, is where the unjustified-drop defect was MEASURED:
# 118 files, 929 functions, and the one component that single-linkage merged
# across the 0.8 line. core scans clean, so a drop-vs-survivor test that only
# looked at core would have passed over the bug it exists to catch.
SCOUT_PLUGINS = _BIGBANG / "plugins"

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

# Two defs of one name in one file, which is legal and not a duplicate. Modelled
# on the real case in apps/scout-cli/bigbang/plugins/mcp/cli.py: an import
# try/except defines _check_sdk twice, one returning True and one raising.
DOUBLE_DEF = '''
try:
    import mcp
    def _check_sdk():
        """The SDK imported, so there is nothing to check."""
        return True
except ImportError:
    def _check_sdk():
        """No SDK. Fail loudly rather than degrade to a stub."""
        raise RuntimeError("mcp is not installed; pip install mcp")
'''

# --------------------------------------------------------------------------
# the single-linkage chain: a--b and b--c both above threshold, a--c below it
# --------------------------------------------------------------------------
# Jaccard DISTANCE (1-J) obeys the triangle inequality, so a chain that clears
# 0.8 twice cannot fall far below 0.8 end-to-end -- the floor is 1-2*(1-0.8)=0.6.
# These parameters were searched for measured slack at BOTH gates rather than
# guessed: sliding a 300-token window by 23 tokens gives true J 0.8558 for each
# neighbour and 0.7310 for the ends, with estimates 0.8750 / 0.8906 / 0.7734.
# Every value is blake2b-derived and therefore fixed forever; the test asserts
# them so a fixture drift reports itself instead of quietly going vacuous.
CHAIN_LEN = 300
CHAIN_STEP = 23


def _window(start: int, length: int = CHAIN_LEN) -> str:
    """`length` unique tokens starting at `start`. Not Python, deliberately.

    Unparseable text takes normalize()'s whitespace-collapse path, which makes
    the shingle set an exactly predictable window and the Jaccards arithmetic
    instead of an accident of some hand-written function pair.
    """
    return " ".join(f"tok{j:05d}" for j in range(start, start + length))


CHAIN_DOCS = {
    "a": _window(0),
    "b": _window(CHAIN_STEP),
    "c": _window(2 * CHAIN_STEP),
}


def _executed_sources() -> list[Path]:
    """Every file under scripts/ that importing minhash_dedup actually runs.

    Discovered by traversing the module objects reachable from `md`, so the day a
    second helper is loaded by path it is covered with no list to update. Only
    files inside scripts/ are returned: stdlib modules are reachable the same way
    and are not what the stdlib-only invariant is about.
    """
    scripts = SRC.parent
    found: dict[Path, None] = {}
    stack: list[types.ModuleType] = [md]
    while stack:
        mod = stack.pop()
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        path = Path(f).resolve()
        if scripts not in path.parents or path in found:
            continue
        found[path] = None
        for name in dir(mod):
            value = getattr(mod, name, None)
            if isinstance(value, types.ModuleType):
                stack.append(value)
    return sorted(found)


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

    def test_async_def_docstrings_are_stripped_too(self):
        """`async def` is ast.AsyncFunctionDef, a SEPARATE node type.

        Every docstring owner has to be listed explicitly in _DOC_OWNERS, and an
        omission is invisible: async functions simply keep their prose, so two
        async coroutines differing only in their docstrings stay two training
        examples. Coroutines are not a rare corner of a codebase that talks to
        the network.
        """
        src = 'async def fetch(url):\n    """Prose that must not survive."""\n    return await get(url)\n'
        out = md.normalize(src)
        assert "Prose that must not survive" not in out, (
            "an async def kept its docstring — ast.AsyncFunctionDef is missing "
            "from _DOC_OWNERS"
        )
        assert "return await get(url)" in out

    def test_async_and_sync_docstring_only_stubs_both_become_pass(self):
        """The empty-suite path, on the async node type as well as the sync one."""
        assert md.normalize('async def stub():\n    """doc only"""\n') == md.normalize(
            "async def stub():\n    pass\n"
        )
        docs = {
            "async_doc": 'async def stub():\n    """one"""\n',
            "async_pass": "async def stub():\n    pass\n",
        }
        res = md.cluster_documents(docs)
        assert res["clusters"] == [["async_doc", "async_pass"]], (
            "an async docstring-only stub did not collide with its pass twin"
        )

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

    def test_no_builtin_hash_and_no_random_in_any_source_this_module_executes(self):
        """Parsed with `ast`, never grepped — and over the TRANSITIVE set.

        The module docstring discusses `hash()` in prose at length, so a regex or
        a grep would flag it and be wrong — which is precisely the failure mode
        that produced three wrong answers in one day in this repo. Only real
        Call/Import nodes count.

        The first version of this test parsed minhash_dedup.py and nothing else,
        while the module `exec_module`s scripts/ast_pairs.py at import time. A
        `random` import or a `hash()` call added THERE would be executed by this
        module on every run and the guard would have reported it clean: the
        invariant advertised was not the invariant enforced. `_executed_sources`
        follows the module objects instead of trusting a hand-kept list.
        """
        sources = _executed_sources()
        assert len(sources) >= 2, (
            f"the guard only found {[p.name for p in sources]}. minhash_dedup "
            f"executes ast_pairs.py by path, so a one-file check is not the "
            f"invariant this test claims to enforce"
        )
        assert SRC in sources
        assert any(p.name == "ast_pairs.py" for p in sources), (
            "the path-loaded helper is not being checked"
        )
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            hash_calls = [
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "hash"
            ]
            assert hash_calls == [], (
                f"{path.name} calls builtin hash() at line(s) {hash_calls} — "
                f"PYTHONHASHSEED-salted"
            )
            imported = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imported.update(a.name.split(".")[0] for a in n.names)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    imported.add(n.module.split(".")[0])
            assert "random" not in imported, (
                f"{path.name} imports random — an unseeded RNG makes the corpus "
                f"irreproducible"
            )
            third_party = imported - set(sys.stdlib_module_names)
            assert third_party == set(), (
                f"{path.name} has non-stdlib import(s): {sorted(third_party)}"
            )


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
    "survivor_of": res["survivor_of"],
    "rescued": res["rescued"],
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

# The chain is in the cross-process corpus on purpose: the exact gate partitions
# a component by walking it in sorted order, and "sorted order" is the kind of
# thing that quietly becomes set-iteration order.
PROBE_CHAIN = dict(PROBE_DOCS, **{f"chain_{k}": v for k, v in CHAIN_DOCS.items()})


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

    def test_the_exact_gate_partitions_identically_across_processes(self):
        """A component split by the exact gate, in two interpreters."""
        one = _run_probe("0", PROBE_CHAIN)
        two = _run_probe("2147483647", PROBE_CHAIN)
        assert one["rescued"] == two["rescued"] == 1, (
            f"probe corpus rescued {one['rescued']}/{two['rescued']} documents; "
            f"the chain must force exactly one split or this test is vacuous"
        )
        assert one["survivor_of"] == two["survivor_of"]
        assert one["clusters"] == two["clusters"]

    def test_insertion_order_does_not_change_which_document_is_rescued(self):
        forward = md.cluster_documents(PROBE_CHAIN)
        backward = md.cluster_documents(dict(reversed(list(PROBE_CHAIN.items()))))
        assert forward["survivor_of"] == backward["survivor_of"]
        assert forward["rescued"] == backward["rescued"] == 1
        assert forward["clusters"] == backward["clusters"]


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
        their estimated Jaccard is 0.6328 and their true Jaccard is 0.5714.
        Without the re-scoring step one unlucky band collision chains them
        together through union-find and the cluster count becomes fiction. The
        first assertion below proves the pair reaches the verifier at all, so
        this is not a vacuous "nothing happened".

        The middle case is the one worth reading: at threshold 0.6 the pair
        CLEARS gate 1 (estimate 0.6328) and still does not cluster, because gate
        2 scores it exactly at 0.5714. Two gates, measuring two different things.
        """
        docs = {"a": ORIGINAL, "b": NEAR}
        sets = {k: md.shingles(md.normalize(v)) for k, v in docs.items()}
        sigs = {k: md.minhash(v) for k, v in sets.items()}
        assert md.candidate_pairs(sigs) == {("a", "b")}, "not even a candidate"
        est = md.jaccard_estimate(sigs["a"], sigs["b"])
        truth = md.true_jaccard(sets["a"], sets["b"])
        assert 0.6 <= est < 0.7, f"fixture drifted: estimated J={est} (measured 0.6328)"
        assert 0.55 <= truth < 0.6, f"fixture drifted: true J={truth} (measured 0.5714)"

        assert md.cluster_documents(docs, threshold=0.8)["clusters"] == []

        gate1_only = md.cluster_documents(docs, threshold=0.6)
        assert gate1_only["verified_pairs"] == 1, "gate 1 should have passed the pair"
        assert gate1_only["clusters"] == [], (
            "gate 2 accepted a pair whose EXACT Jaccard is 0.5714 at threshold 0.6"
        )

        # ...and the SAME pair does cluster once the threshold drops under both
        # scores, which proves the threshold is consulted, not decorative.
        assert md.cluster_documents(docs, threshold=0.5)["clusters"] == [["a", "b"]]

    def test_gate_1_is_inclusive_at_exactly_the_estimated_threshold(self):
        """`est >= threshold`, as the --threshold help promises. Not `>`.

        The estimate is a count of agreeing positions over 128, so equality is
        reachable exactly and this is not float-luck: ORIGINAL/NEAR agree in 81
        of 128 positions, i.e. exactly 0.6328125.
        """
        docs = {"a": ORIGINAL, "b": NEAR}
        sigs = {k: md.minhash(md.shingles(md.normalize(v))) for k, v in docs.items()}
        est = md.jaccard_estimate(sigs["a"], sigs["b"])
        assert est * md.NUM_PERM == 81, f"fixture drifted: {est * md.NUM_PERM} of 128"
        res = md.cluster_documents(docs, threshold=est)
        assert res["verified_pairs"] == 1, (
            f"a pair estimated at exactly the threshold ({est}) was not verified — "
            f"the comparison is exclusive but the CLI advertises it as inclusive"
        )

    def test_gate_2_is_inclusive_at_exactly_the_exact_threshold(self):
        """`true_jaccard >= threshold`, on the gate that decides deletion.

        Same pair, threshold set to its EXACT Jaccard (4/7). Recomputed by the
        same code path, so the two floats are bit-identical by construction.
        """
        docs = {"a": ORIGINAL, "b": NEAR}
        sets = {k: md.shingles(md.normalize(v)) for k, v in docs.items()}
        truth = md.true_jaccard(sets["a"], sets["b"])
        assert truth == 4 / 7, f"fixture drifted: true J={truth}"
        res = md.cluster_documents(docs, threshold=truth)
        assert res["clusters"] == [["a", "b"]], (
            f"a pair whose true Jaccard is exactly the threshold ({truth}) was "
            f"not clustered — gate 2 is exclusive where it should be inclusive"
        )
        assert res["dropped"] == ["b"]

    def test_the_corpus_vectors_are_not_returned_unless_asked_for(self):
        """4,566 shingle sets plus 4,566x128 ints, pinned for the result's life.

        They were returned unconditionally and `main()` read neither key. The
        assertion is on the EXACT key set, so re-adding either one — or any other
        per-document structure — fails here rather than being noticed on a bigger
        corpus.
        """
        res = md.cluster_documents(PROBE_DOCS)
        assert set(res) == {
            "documents", "skipped_empty", "candidate_pairs", "verified_pairs",
            "components", "rescued", "clusters", "keep", "dropped",
            "survivor_of", "pairs",
        }, f"unexpected result keys: {sorted(set(res))}"

    def test_the_corpus_vectors_are_returned_on_request_and_are_real(self):
        res = md.cluster_documents(PROBE_DOCS, return_vectors=True)
        assert set(res["shingle_sets"]) == set(res["signatures"])
        assert len(res["signatures"]) == res["documents"]
        assert all(len(s) == md.NUM_PERM for s in res["signatures"].values())
        assert res["shingle_sets"]["a"] == md.shingles(md.normalize(ORIGINAL))

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
# 7b. THE DROP ITSELF — is the survivor really a duplicate of what it replaces?
# ==========================================================================
def _drop_scores(res, sets, threshold=md.THRESHOLD):
    """[(true_jaccard, dropped, survivor)] sorted worst-first. Never empty-safe.

    Re-measures from the shingle sets rather than trusting anything the module
    reports, because "the module says these are duplicates" is the claim under
    test. Raises on an empty drop set so a test cannot pass by having nothing to
    check.
    """
    scores = sorted(
        (md.true_jaccard(sets[survivor], sets[dropped]), dropped, survivor)
        for dropped, survivor in res["survivor_of"].items()
    )
    if not scores:
        raise AssertionError("no documents were dropped — nothing to verify")
    return scores


class TestDropVsSurvivor:
    """The only similarity number that decides whether data is deleted.

    A document is dropped and its survivor takes its place in the corpus. If the
    two are not actually near-duplicates, that is a deleted training example
    dressed up as deduplication, and every count the CLI prints still looks fine.
    Nothing in this suite measured that quantity until these tests.
    """

    def test_the_chain_fixture_really_is_a_single_linkage_trap(self):
        """Proves the setup before proving the fix. Otherwise the fix is untested.

        a--b and b--c must BOTH clear gate 1 (so union-find merges all three into
        one component) while a--c is genuinely below threshold. If any of those
        stops holding, the tests below still pass and mean nothing.
        """
        sets = {k: md.shingles(md.normalize(v)) for k, v in CHAIN_DOCS.items()}
        sigs = {k: md.minhash(v) for k, v in sets.items()}
        t_ab = md.true_jaccard(sets["a"], sets["b"])
        t_bc = md.true_jaccard(sets["b"], sets["c"])
        t_ac = md.true_jaccard(sets["a"], sets["c"])
        e_ab = md.jaccard_estimate(sigs["a"], sigs["b"])
        e_bc = md.jaccard_estimate(sigs["b"], sigs["c"])
        assert t_ab >= 0.8 and t_bc >= 0.8, (
            f"chain fixture drifted: neighbour true J {t_ab:.4f}/{t_bc:.4f} "
            f"(measured 0.8558 each)"
        )
        assert e_ab >= 0.8 and e_bc >= 0.8, (
            f"chain fixture drifted: neighbour estimates {e_ab:.4f}/{e_bc:.4f} "
            f"(measured 0.8750/0.8906) — gate 1 must merge these"
        )
        assert t_ac < 0.8, (
            f"chain fixture drifted: end-to-end true J {t_ac:.4f} is NOT below "
            f"threshold (measured 0.7310) — there is no trap to fall into"
        )
        cands = md.candidate_pairs(sigs)
        assert ("a", "b") in cands and ("b", "c") in cands
        assert md.cluster_documents(CHAIN_DOCS)["components"] == 1, (
            "single-linkage did not merge the chain into one component"
        )

    def test_single_linkage_does_not_delete_the_far_end_of_a_chain(self):
        """The defect, reduced to three documents.

        Union-find puts a, b and c in one component. The old code kept a and
        deleted BOTH b and c — and c is only 0.7310 similar to a, well under the
        advertised 0.8. c must survive instead, as its own survivor.
        """
        res = md.cluster_documents(CHAIN_DOCS)
        assert res["clusters"] == [["a", "b"]], (
            f"expected c to be split off into its own group, got {res['clusters']}"
        )
        assert res["dropped"] == ["b"], (
            f"dropped {res['dropped']}; c is 0.7310 from the survivor a and must "
            f"not be deleted in its favour"
        )
        assert res["keep"] == ["a", "c"]
        assert res["rescued"] == 1
        assert res["components"] == 1 and len(res["clusters"]) == 1

    def test_every_drop_in_the_chain_corpus_clears_the_threshold_exactly(self):
        sets = {k: md.shingles(md.normalize(v)) for k, v in CHAIN_DOCS.items()}
        worst, dropped, survivor = _drop_scores(md.cluster_documents(CHAIN_DOCS), sets)[0]
        assert worst >= md.THRESHOLD, (
            f"{dropped} was dropped for {survivor} at true J {worst:.4f} < "
            f"{md.THRESHOLD}"
        )
        assert worst == pytest.approx(0.8558, abs=5e-4), (
            f"measured 0.8558 on 2026-07-26, got {worst:.4f}"
        )

    def test_gate_2_reads_the_threshold_it_was_given(self):
        """The exact gate must be a function of `threshold`, not of a constant 0.8.

        At threshold 0.87 the chain neighbours still CLEAR gate 1 (estimates
        0.8750 and 0.8906, so verified_pairs stays 2 and the component still
        forms) while their exact Jaccard, 0.8558, does not. Nothing may be dropped.
        A `0.8` frozen into the partition step passes every other test in this
        class and fails here, which is the point: the two gates are separately
        wired to the same knob.
        """
        tight = md.cluster_documents(CHAIN_DOCS, threshold=0.87)
        assert tight["verified_pairs"] == 2, (
            f"gate 1 admitted {tight['verified_pairs']} pairs at 0.87; the "
            f"estimates are 0.8750/0.8906 so both must pass or this is not a "
            f"test of gate 2"
        )
        assert tight["components"] == 1, "the component did not even form"
        assert tight["dropped"] == [], (
            f"threshold 0.87 dropped {tight['dropped']} although the best true "
            f"Jaccard in this corpus is 0.8558 — gate 2 is not reading the "
            f"threshold it was passed"
        )
        assert tight["clusters"] == [] and tight["rescued"] == 2
        # and the same corpus at 0.8, where the exact scores DO qualify
        assert md.cluster_documents(CHAIN_DOCS, threshold=0.8)["dropped"] == ["b"]

    def test_survivor_of_agrees_with_clusters_keep_and_dropped(self):
        """Four views of one decision; any disagreement is a corrupted keep-set."""
        docs = dict(CHAIN_DOCS, x=ORIGINAL, y=FORMATTED, z=DIFFERENT)
        res = md.cluster_documents(docs)
        assert sorted(res["survivor_of"]) == res["dropped"]
        assert set(res["survivor_of"].values()) <= set(res["keep"])
        assert not set(res["dropped"]) & set(res["keep"])
        assert set(res["dropped"]) | set(res["keep"]) == set(docs)
        for cluster in res["clusters"]:
            survivor, rest = cluster[0], cluster[1:]
            assert survivor in res["keep"], "cluster[0] is not the survivor"
            assert all(res["survivor_of"][m] == survivor for m in rest)

    def test_a_survivor_is_never_itself_dropped_by_a_third_document(self):
        """Transitive deletion: keeping x for y while x is itself deleted for z.

        That would drop y in favour of a document that is not in the corpus any
        more, and the keep-set would no longer cover it at any similarity.
        """
        docs = dict(CHAIN_DOCS, x=ORIGINAL, y=FORMATTED, w=COMMENTED, z=DIFFERENT)
        res = md.cluster_documents(docs)
        assert res["dropped"], "vacuous: nothing was dropped"
        for survivor in res["survivor_of"].values():
            assert survivor not in res["survivor_of"], (
                f"{survivor} is a survivor AND a dropped document"
            )


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
        keys = [k for k, _, _ in md.iter_functions(src, "m.py")]
        assert keys == ["m.py::Store.load", "m.py::Store.load.inner", "m.py::fetch"]

    def test_iter_functions_reports_the_line_of_each_def(self):
        """The lineno is what disambiguates a repeated qualified name."""
        src = "def a():\n    pass\n\n\ndef b():\n    pass\n"
        assert [(k, ln) for k, _, ln in md.iter_functions(src, "m.py")] == [
            ("m.py::a", 1), ("m.py::b", 5),
        ]

    def test_iter_functions_on_unparseable_source_yields_nothing(self):
        assert list(md.iter_functions("def broken(:", "m.py")) == []

    def test_two_defs_sharing_a_qualified_name_are_both_collected(self, tmp_path):
        """`docs[key] = seg` overwrote, and the two defs are usually OPPOSITES.

        MEASURED on apps/scout-cli: 4567 (name, source) pairs collapsed into 4566
        keys. The one collision is mcp/cli.py::_check_sdk, defined twice under an
        import try/except — one returns True, the other raises RuntimeError. The
        dict kept the second and the corpus silently lost a real example.
        """
        (tmp_path / "m.py").write_text(DOUBLE_DEF, encoding="utf-8")
        docs, stats = md.collect_documents(tmp_path, "function")
        assert stats["collisions"] == 1, (
            f"a file defining one name twice reported {stats['collisions']} "
            f"collisions — the overwrite is silent again"
        )
        assert len(docs) == 2, f"expected both defs, got {sorted(docs)}"
        assert "m.py::_check_sdk" in docs
        keys = sorted(docs)
        assert keys[1].startswith("m.py::_check_sdk#L"), (
            f"the second def got no disambiguated key: {keys}"
        )
        bodies = sorted(docs.values())
        assert bodies[0] != bodies[1], "both keys point at the same source"
        assert any("RuntimeError" in b for b in bodies), "the raising def was lost"
        assert any("return True" in b for b in bodies), "the returning def was lost"

    def test_a_collision_free_corpus_reports_zero_collisions(self):
        """The counter must not fire on ordinary input, or it means nothing."""
        _, stats = md.collect_documents(SCOUT_CORE, "function")
        assert stats["collisions"] == 0, (
            f"bigbang/core reported {stats['collisions']} collisions; measured 0"
        )

    def test_an_unreadable_path_is_not_counted_as_scanned(self, tmp_path):
        """`files += 1` ran BEFORE read_text, so a file that never opened was
        reported as successfully scanned — coverage inflated by exactly the files
        the corpus is missing.

        A directory named `*.py` is the portable way to force this: `walk` yields
        it (rglob matches directories) and read_text raises OSError on every
        platform — PermissionError on Windows, IsADirectoryError on POSIX.
        """
        (tmp_path / "real.py").write_text(DIFFERENT, encoding="utf-8")
        (tmp_path / "trap.py").mkdir()
        assert sorted(p.name for p in md.walk(tmp_path)) == ["real.py", "trap.py"], (
            "walk did not yield the unreadable path — the test cannot fire"
        )
        docs, stats = md.collect_documents(tmp_path, "file")
        assert stats["files"] == 1, (
            f"files={stats['files']}, but only one of the two paths could be read"
        )
        assert stats["unreadable"] == 1, "the unreadable path was not reported"
        assert stats["unparseable"] == 0, (
            "an unreadable path was blamed on the parser instead"
        )
        assert sorted(docs) == ["real.py"]

    def test_an_unreadable_path_is_reported_by_the_cli(self, tmp_path, capsys):
        (tmp_path / "real.py").write_text(DIFFERENT, encoding="utf-8")
        (tmp_path / "trap.py").mkdir()
        assert md.main(["--path", str(tmp_path), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["files_scanned"] == 1 and out["files_unreadable"] == 1

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
        assert stats["unreadable"] == 0 and stats["collisions"] == 0
        files, stats2 = md.collect_documents(tmp_path, "file")
        assert sorted(files) == ["pkg/a.py", "pkg/b.py"]
        assert stats2["unparseable"] == 0

    def test_unparseable_files_are_counted_out_loud(self, tmp_path):
        (tmp_path / "ok.py").write_text(DIFFERENT, encoding="utf-8")
        (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        _, stats = md.collect_documents(tmp_path, "file")
        assert stats["files"] == 2 and stats["unparseable"] == 1
        assert stats["unreadable"] == 0, "a readable file was called unreadable"


# ==========================================================================
# 9. the real tree — measured floors, not "> 0"
# ==========================================================================
@pytest.fixture(scope="module")
def real_result():
    """One scan of apps/scout-cli/bigbang/core, shared by the whole class.

    Module-scoped and defined outside the class: a class-scoped fixture written
    as an instance method is deprecated in pytest 8 and its attributes are not
    visible to the tests anyway. `return_vectors` is requested explicitly because
    these tests re-score the module's answer against exact Jaccard.
    """
    docs, stats = md.collect_documents(SCOUT_CORE, "function")
    return md.cluster_documents(docs, return_vectors=True), stats


@pytest.fixture(scope="module")
def plugins_result():
    """One scan of apps/scout-cli/bigbang/plugins — 929 functions, 2.6s.

    A SECOND real corpus, because core does not contain the failure. Measured on
    core, the worst drop-vs-survivor true Jaccard was already 0.8400 and no
    component ever needed splitting; the unjustified drop lives in plugins, where
    two cli.py::_open_store variants estimate 0.8125 and are truly 0.7143.
    """
    docs, stats = md.collect_documents(SCOUT_PLUGINS, "function")
    return md.cluster_documents(docs, return_vectors=True), stats


@pytest.mark.skipif(not SCOUT_CORE.exists(), reason=f"scout-cli absent at {SCOUT_CORE}")
class TestAgainstTheRealTree:
    """Measured on apps/scout-cli/bigbang/core, 2026-07-26, defaults
    (k=5, num_perm=128, bands=16, rows=8, threshold=0.8):

        files scanned          51
        corpus (functions)     1177
        key collisions         0
        candidate pairs        143
        verified pairs         114
        components             5    (single-linkage, before the exact gate)
        clusters               5    (0 documents rescued — core scans clean)
        largest cluster        15   (open_store/open_ledger, 15 distinct modules)
        duplicates dropped     20   (1.7% of the corpus)
        min true J of a kept pair   0.8400
        min drop-vs-survivor true J 0.8400
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

    def test_every_dropped_document_is_a_duplicate_of_its_own_survivor(self, real_result):
        """Not "of something in its cluster". Of the document that replaces it.

        Measured on core 2026-07-26: 20 drops, worst 0.8400, and the floor is the
        threshold itself because `_star_partition` decides this on exact Jaccard.
        """
        res, _ = real_result
        scores = _drop_scores(res, res["shingle_sets"])
        assert len(scores) >= 16, f"only {len(scores)} drops; measured 20"
        worst, dropped, survivor = scores[0]
        assert worst >= md.THRESHOLD, (
            f"{dropped} was deleted in favour of {survivor} at true Jaccard "
            f"{worst:.4f}, under the advertised {md.THRESHOLD}"
        )
        assert worst >= 0.80, f"worst drop-vs-survivor {worst:.4f}; measured 0.8400"


@pytest.mark.skipif(
    not SCOUT_PLUGINS.exists(), reason=f"scout-cli absent at {SCOUT_PLUGINS}"
)
class TestAgainstThePluginTree:
    """The corpus where the unjustified drop was FOUND. Measured 2026-07-26 at
    defaults (k=5, num_perm=128, bands=16, rows=8, threshold=0.8):

        files scanned          118
        corpus (functions)     929
        key collisions         1    (mcp/cli.py::_check_sdk, defined twice)
        candidate pairs        637
        verified pairs         564   (gate 1, estimated)
        components             19    (single-linkage)
        clusters               18    (gate 2 split one; 1 document rescued)
        duplicates dropped     63    (6.8% of the corpus; was 64 before gate 2)
        min drop-vs-survivor true J   0.8000  (== threshold, inclusive)
        worst intra-cluster true J    0.7353  (allowed: star, not complete linkage)
        worst |est - true| on verified pairs  0.0982

    Before gate 2 existed this tree dropped 64 documents and the worst of them
    scored 0.7143 against the survivor that replaced it.
    """

    def test_the_corpus_is_the_size_it_was_measured_at(self, plugins_result):
        res, stats = plugins_result
        assert stats["files"] >= 100, f"only {stats['files']} files (measured 118)"
        assert res["documents"] >= 800, (
            f"corpus collapsed to {res['documents']} functions; measured 929"
        )
        assert len(res["dropped"]) >= 50, (
            f"only {len(res['dropped'])} duplicates; measured 63"
        )

    def test_no_document_is_dropped_for_a_survivor_it_does_not_resemble(
        self, plugins_result
    ):
        """THE regression test. Measured worst drop-vs-survivor: 0.8000.

        The floor is the threshold itself, not a percentage under it, because the
        guarantee is structural: gate 2 scores every would-be drop against its
        survivor on exact Jaccard. A single value under 0.8 here means a real
        training example was deleted in favour of a document that is not a
        duplicate of it — the exact failure this file's docstring section 5
        describes, and the one that shipped 126 drops with a 0.7143 among them.
        """
        res, _ = plugins_result
        scores = _drop_scores(res, res["shingle_sets"])
        assert len(scores) >= 50, f"only {len(scores)} drops; measured 63"
        offenders = [(d, s, round(j, 4)) for j, d, s in scores if j < md.THRESHOLD]
        assert offenders == [], (
            f"{len(offenders)} document(s) deleted in favour of a survivor below "
            f"the advertised {md.THRESHOLD}: {offenders[:3]}"
        )
        worst = scores[0][0]
        assert worst >= 0.80, f"worst drop-vs-survivor {worst:.4f}; measured 0.8000"

    def test_the_exact_gate_actually_had_to_split_a_component_here(
        self, plugins_result
    ):
        """Anti-vacuity. If nothing needed splitting, the test above proves nothing.

        This corpus contained one single-linkage component straddling the 0.8
        line. If this ever fails, the guarantee test has lost its teeth and needs
        a corpus that still contains the trap — it does NOT mean the fix regressed.
        """
        res, _ = plugins_result
        assert res["components"] >= 15, f"{res['components']} components; measured 19"
        assert res["rescued"] >= 1, (
            f"gate 2 split nothing on this tree (components={res['components']}, "
            f"clusters={len(res['clusters'])}); measured 1 rescued document on "
            f"2026-07-26. The drop-vs-survivor floor is now vacuous here"
        )
        assert res["components"] > len(res["clusters"]) or res["rescued"] == 0

    def test_gate_1_alone_would_have_authorised_a_wrong_drop(self, plugins_result):
        """Why gate 2 cannot also be the estimate. Measured, not argued.

        Some verified pair — est >= 0.8, so gate 1 accepted it — is truly BELOW
        0.8. Measured: feeds/cli.py::_open_store vs flows/cli.py::_open_store,
        est 0.8125, true 0.7143, an error of 0.0982 that exceeds the nominal
        1/sqrt(128) = 0.0884 envelope. Re-verifying on the estimate would have
        re-authorised exactly the drop this whole change removes.
        """
        res, _ = plugins_result
        sets = res["shingle_sets"]
        overrated = sorted(
            (md.true_jaccard(sets[a], sets[b]), a, b)
            for a, b, _ in res["pairs"]
            if md.true_jaccard(sets[a], sets[b]) < md.THRESHOLD
        )
        assert overrated, (
            "no verified pair is below the true threshold on this tree; measured "
            "at least one (0.7143) on 2026-07-26"
        )
        assert overrated[0][0] <= 0.75, (
            f"worst overrated verified pair is {overrated[0][0]:.4f}; measured "
            f"0.7143 — this is the pair gate 2 has to catch"
        )
        assert all(
            j >= md.THRESHOLD for j, _, _ in _drop_scores(res, sets)
        ), "an overrated pair still authorised a drop"

    def test_a_sub_threshold_pair_may_still_share_a_cluster(self, plugins_result):
        """The limit, stated honestly and pinned by a measurement.

        Star clustering guarantees drop-vs-SURVIVOR, not every intra-cluster pair.
        Measured worst intra-cluster true Jaccard 0.7353 while the worst
        drop-vs-survivor is 0.8000. Asserting this keeps the docstring's claim and
        the code's behaviour from drifting apart in either direction — a silent
        upgrade to complete linkage would delete far more than it says it does.
        """
        res, _ = plugins_result
        sets = res["shingle_sets"]
        worst = min(
            md.true_jaccard(sets[c[i]], sets[c[j]])
            for c in res["clusters"]
            for i in range(len(c))
            for j in range(i + 1, len(c))
        )
        assert worst < md.THRESHOLD, (
            f"worst intra-cluster true Jaccard is {worst:.4f}, at or above "
            f"{md.THRESHOLD}: clustering is now complete-linkage, or this corpus "
            f"no longer contains the case the guarantee is scoped around "
            f"(measured 0.7353)"
        )
        assert worst >= 0.6, (
            f"worst intra-cluster {worst:.4f} is far below the 0.7353 measured; "
            f"single linkage is chaining again"
        )

    def test_the_real_key_collision_is_recovered_not_overwritten(self, plugins_result):
        """The measured 4567-vs-4566 case, on the tree it was found in.

        mcp/cli.py defines _check_sdk twice under an import try/except. One
        returns True, the other raises RuntimeError. Both must be in the corpus.
        """
        res, stats = plugins_result
        assert stats["collisions"] == 1, (
            f"{stats['collisions']} collisions; measured exactly 1 on 2026-07-26"
        )
        docs, _ = md.collect_documents(SCOUT_PLUGINS, "function")
        disambiguated = [k for k in docs if "#L" in k]
        assert len(disambiguated) == 1, f"disambiguated keys: {disambiguated}"
        base = disambiguated[0].split("#L")[0]
        assert base in docs, f"{base} lost its first occurrence"
        assert docs[base] != docs[disambiguated[0]], (
            "both keys hold the same source — nothing was actually recovered"
        )
        assert res["documents"] == len(docs), "a collided key was dropped later"


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

    def test_json_summary_carries_the_counts_that_can_hide_a_lie(self, tmp_path, capsys):
        """Unreadable files, disambiguated keys and single-linkage splits.

        Each one is a way for the corpus to differ from what the run claims, so
        each is a reported number rather than an internal detail.
        """
        base = self._corpus(tmp_path)
        assert md.main(["--path", str(base), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["files_unreadable"] == 0
        assert out["key_collisions"] == 0
        assert out["components"] == 1 and out["rescued_by_exact_gate"] == 0

    def test_human_output_reports_the_single_linkage_split(self, tmp_path, capsys):
        """The chain corpus, through the CLI, as .py files."""
        for name, text in CHAIN_DOCS.items():
            (tmp_path / f"{name}.py").write_text(text, encoding="utf-8")
        assert md.main(["--path", str(tmp_path), "--unit", "file"]) == 0
        text = capsys.readouterr().out
        assert "components      : 1" in text, text
        assert "clusters        : 1  (1 document(s) rescued" in text, text
        assert "duplicates      : 1 documents drop out of 3" in text, text

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
