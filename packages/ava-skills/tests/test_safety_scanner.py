# Solo personal project, no connection to employer, built with public/free-tier only
"""safety-scanner: metrics match hand-computed values on fixtures; regex baseline is
deterministic; targets stay outside measured."""

import pytest

from conftest import load_skill_module

ss = load_skill_module("safety-scanner")


class TestRocAuc:
    def test_perfect_separation(self):
        # every positive outranks every negative -> AUC 1.0
        assert ss.roc_auc([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.4]) == 1.0

    def test_hand_computed_partial(self):
        # pos scores {0.2, 0.8}; neg scores {0.9, 0.4}
        # concordant pairs: only (0.8 > 0.4) -> 1 of 4 = 0.25
        assert ss.roc_auc([1, 0, 1, 0], [0.2, 0.9, 0.8, 0.4]) == 0.25

    def test_ties_count_half(self):
        assert ss.roc_auc([1, 0], [0.5, 0.5]) == 0.5

    def test_requires_both_classes(self):
        with pytest.raises(ValueError):
            ss.roc_auc([1, 1], [0.5, 0.6])


class TestAuprc:
    def test_perfect_ranking_is_one(self):
        # ranked desc: 0.9(+), 0.8(+), 0.4(-), 0.1(-) -> AP = (1/1 + 2/2)/2 = 1.0
        assert ss.auprc([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.4]) == 1.0

    def test_hand_computed_partial(self):
        # ranked desc: 0.9(-), 0.2(+) -> AP = (1/2)/1 = 0.5
        assert ss.auprc([1, 0], [0.2, 0.9]) == 0.5

    def test_requires_a_positive(self):
        with pytest.raises(ValueError):
            ss.auprc([0, 0], [0.5, 0.6])


class TestFpr:
    def test_hand_computed(self):
        # negatives scored 0.6 and 0.4; threshold 0.5 flags one of two -> 0.5
        assert ss.fpr_at([1, 0, 1, 0], [0.9, 0.6, 0.8, 0.4]) == 0.5

    def test_zero_when_all_negatives_below(self):
        assert ss.fpr_at([1, 0, 0], [0.9, 0.2, 0.3]) == 0.0

    def test_requires_a_negative(self):
        with pytest.raises(ValueError):
            ss.fpr_at([1, 1], [0.5, 0.6])


class TestRegexBaselineDeterminism:
    def test_same_text_same_score(self):
        for text in ["blackmail threat leverage", "hello please thank you", ""]:
            scores = {ss._regex_safety_score(text) for _ in range(20)}
            assert len(scores) == 1, f"regex baseline must be deterministic for {text!r}"

    def test_real_mode_regex_is_reproducible(self):
        a = ss.run(mode="real", text="please review the document")
        b = ss.run(mode="real", text="please review the document")
        assert a["measured"]["unsafe_prob"] == b["measured"]["unsafe_prob"]
        assert a["measured"]["model"] == "regex-baseline"


class TestMockRunMetricsAreComputed:
    def test_mock_metrics_recomputable_from_emitted_scores(self):
        r = ss.run(mode="mock", seed=5)
        scores = r["measured"]["scores"]
        y_true = [1, 0, 1, 0, 1, 1]
        assert r["measured"]["auc"] == pytest.approx(ss.roc_auc(y_true, scores), abs=1e-3)
        assert r["measured"]["auprc"] == pytest.approx(ss.auprc(y_true, scores), abs=1e-3)
        assert r["measured"]["fpr"] == pytest.approx(ss.fpr_at(y_true, scores), abs=1e-3)

    def test_custom_scenarios_and_labels(self):
        r = ss.run(mode="mock", seed=1,
                   scenarios=["blackmail threat leverage extort", "hello please thank you"],
                   y_true=[1, 0], guard3=False)
        # regex on these two: positive scores high, benign scores 0 -> AUC 1.0
        assert r["measured"]["auc"] == 1.0

    def test_paper_numbers_live_outside_measured(self):
        r = ss.run(mode="mock", seed=5)
        for k in ("target_auc", "target_f1", "baseline_f1", "target_auprc", "target_fpr"):
            assert k not in r["measured"]
            assert k in r["targets"]

    def test_mock_run_deterministic_per_seed(self):
        assert ss.run(mode="mock", seed=9)["measured"] == ss.run(mode="mock", seed=9)["measured"]
