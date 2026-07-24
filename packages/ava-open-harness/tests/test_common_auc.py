# Solo personal project, no connection to employer, built with public/free-tier only
"""auc_trapezoid must equal the exact ROC-AUC, including on TIED scores.

Regression for a tie-handling bug: the trapezoid loop emitted a curve point per example
and sorted (score, label) so positives preceded negatives within a tie, scoring ties as
perfect separation. A constant-output classifier (zero discrimination) then reported
AUC 1.0 instead of 0.5 — the opposite of what an anti-mock, honest-eval harness must do,
and a real hazard here because freshly-trained checkpoints often emit near-constant scores.
"""
import random

from harness.common import auc_trapezoid


def _exact_auc(y_true, y_score):
    """Exact ROC-AUC via pairwise concordance (ties count 0.5) — the ground truth."""
    pos = [s for s, y in zip(y_score, y_true) if y == 1]
    neg = [s for s, y in zip(y_score, y_true) if y == 0]
    c = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return c / (len(pos) * len(neg))


def test_constant_scores_are_auc_half_not_one():
    # zero discrimination must be 0.5, never 1.0 (the original bug)
    assert auc_trapezoid([1, 1, 0, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert auc_trapezoid([1, 0], [0.5, 0.5]) == 0.5


def test_matches_exact_auc_on_tie_and_no_tie_cases():
    cases = [
        ([1, 0, 1, 0], [0.9, 0.9, 0.1, 0.1]),   # tie blocks
        ([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.6]),   # no ties
        ([1, 1, 0, 0], [0.9, 0.8, 0.7, 0.6]),   # perfect separation
        ([1, 0, 0, 1], [0.7, 0.7, 0.3, 0.9]),   # mixed ties
    ]
    for yt, ys in cases:
        assert abs(auc_trapezoid(yt, ys) - _exact_auc(yt, ys)) < 1e-9, (yt, ys)


def test_matches_exact_auc_under_heavy_ties_fuzz():
    rng = random.Random(0)
    checked = 0
    for _ in range(2000):
        n = rng.randint(2, 12)
        yt = [rng.randint(0, 1) for _ in range(n)]
        if sum(yt) in (0, n):
            continue
        ys = [rng.choice([0.1, 0.2, 0.3]) for _ in range(n)]  # forced heavy ties
        assert abs(auc_trapezoid(yt, ys) - _exact_auc(yt, ys)) < 1e-9, (yt, ys)
        checked += 1
    assert checked > 500
