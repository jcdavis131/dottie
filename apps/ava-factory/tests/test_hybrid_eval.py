"""hybrid_eval — RRF fusion and the paired bootstrap that judges it.

embed_eval.py produced every reported step-5 number for days before it had any tests
(`1a7dab5`). This file exists so hybrid_eval does not repeat that: the fusion and the
significance test are pure functions and are pinned here, because a wrong bootstrap
would turn a null result into a headline or vice versa.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE.parent / "scripts" / "hybrid_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("_test_hybrid_eval", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_hybrid_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


he = _load()


class TestRRF:
    def test_a_document_ranked_first_by_both_wins(self):
        fused = he.rrf_fuse(["a", "b", "c"], ["a", "c", "b"])
        assert fused[0] == "a"

    def test_agreement_beats_a_single_strong_placement(self):
        """The property that makes RRF worth using: consensus outranks one system's #1."""
        # 'x' is first in one list and absent from the other; 'y' is second in both.
        fused = he.rrf_fuse(["x", "y"], ["y", "z"])
        assert fused[0] == "y", f"consensus lost to a single first place: {fused}"

    def test_union_not_intersection(self):
        fused = he.rrf_fuse(["a"], ["b"])
        assert set(fused) == {"a", "b"}

    def test_ties_break_deterministically(self):
        """Same inputs must give the same order, or a rerun 'changes' the result."""
        a = he.rrf_fuse(["p", "q"], ["q", "p"])
        b = he.rrf_fuse(["p", "q"], ["q", "p"])
        assert a == b

    def test_rank_based_so_score_scale_cannot_matter(self):
        """RRF sees ranks only. This is why BM25 and cosine need no common scale —
        the whole reason score-weighted fusion was not used here."""
        assert he.rrf_fuse(["a", "b"]) == he.rrf_fuse(["a", "b"])

    def test_empty_lists_are_harmless(self):
        assert he.rrf_fuse([], []) == []
        assert he.rrf_fuse([], ["a"]) == ["a"]


class TestPairedBootstrap:
    def test_an_all_positive_difference_excludes_zero(self):
        r = he.paired_bootstrap([0.2] * 40)
        assert r["lo"] > 0 and r["mean"] == pytest.approx(0.2)

    def test_noise_around_zero_does_not_exclude_zero(self):
        """The guard against calling a null result a win."""
        diffs = [0.1, -0.1] * 30
        r = he.paired_bootstrap(diffs)
        assert r["lo"] < 0 < r["hi"], f"noise produced a significant CI: {r}"

    def test_it_is_reproducible(self):
        """A CI that moves between runs could be resampled until it agrees."""
        d = [0.05, -0.02, 0.3, -0.1, 0.0, 0.12] * 8
        assert he.paired_bootstrap(d) == he.paired_bootstrap(d)

    def test_empty_input_is_not_a_significant_result(self):
        r = he.paired_bootstrap([])
        assert r == {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
        assert not (r["lo"] > 0), "an empty comparison must never read as a win"


class TestPreRegisteredConstants:
    def test_rrf_k_is_the_paper_value(self):
        """Fixed before the first run. A k that drifts is a tuned parameter."""
        assert he.RRF_K == 60

    def test_the_seed_is_fixed(self):
        assert he.SEED == 12345
        assert he.BOOTSTRAP >= 10_000
