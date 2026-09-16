"""Unit tests for the prompt tuner. All use the StubGenerator — no model needed."""

import json
import os
import tempfile
import unittest

from tuner.backends import StubGenerator
from tuner.evals import approval_gate
from tuner.prompt_tuner import KFold, PromptClassifier, PromptTuner, accuracy_score


def truth_stub(X, y, marker):
    """Answers correctly iff the prompt contains marker; otherwise flips."""
    truth = dict(zip(X, y))

    def reply(prompt):
        text = next((t for t in X if t in prompt), None)
        label = truth.get(text, "unknown")
        if marker in prompt:
            return label
        return "approval" if label == "auto" else "auto"

    return StubGenerator(reply)


class TestKFold(unittest.TestCase):
    def test_covers_every_index_exactly_once(self):
        for n, k in [(10, 5), (7, 3), (4, 2)]:
            seen = []
            for _tr, te in KFold(n_splits=k, seed=1).split(n):
                seen.extend(te)
            self.assertEqual(sorted(seen), list(range(n)))

    def test_deterministic_same_seed(self):
        a = list(KFold(n_splits=3, seed=9).split(11))
        b = list(KFold(n_splits=3, seed=9).split(11))
        self.assertEqual(a, b)

    def test_rejects_one_split(self):
        with self.assertRaises(ValueError):
            KFold(n_splits=1)


class TestAccuracy(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(accuracy_score(["a", "b", "a"], ["a", "b", "b"]), 2 / 3)

    def test_unknown_never_counts(self):
        self.assertEqual(accuracy_score(["auto"], ["unknown"]), 0.0)

    def test_empty(self):
        self.assertEqual(accuracy_score([], []), 0.0)


class TestGridSearch(unittest.TestCase):
    def setUp(self):
        self.X = ["merge the PR", "read the PR", "push the branch", "list open PRs"]
        self.y = ["approval", "auto", "approval", "auto"]
        self.templates = ["Classify: {text}", "Safety policy says answer: {text}"]

    def test_picks_best_template(self):
        tuner = PromptTuner(
            truth_stub(self.X, self.y, marker="Safety policy"),
            {"prompt_template": self.templates},
            cv=2,
            seed=42,
        ).fit(self.X, self.y)
        self.assertEqual(tuner.best_params_["prompt_template"], self.templates[1])
        self.assertAlmostEqual(tuner.best_score_, 1.0)
        self.assertEqual(len(tuner.cv_results_), 2)
        self.assertTrue(all(len(r["fold_scores"]) == 2 for r in tuner.cv_results_))

    def test_backend_failure_is_fail_closed(self):
        def boom(_prompt):
            raise RuntimeError("model exploded")

        clf = PromptClassifier(boom, prompt_template="Classify: {text}")
        preds = clf.predict(self.X)
        self.assertEqual(preds, ["unknown"] * 4)
        self.assertEqual(accuracy_score(self.y, preds), 0.0)

    def test_timeline_lines_have_seven_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "timeline.jsonl")
            PromptTuner(
                truth_stub(self.X, self.y, marker="Safety policy"),
                {"prompt_template": self.templates},
                cv=2,
                seed=42,
                timeline_path=path,
            ).fit(self.X, self.y)
            with open(path, encoding="utf-8") as f:
                lines = [json.loads(line) for line in f]
            self.assertEqual(len(lines), 4)  # 2 templates x 2 folds
            required = {"nodeId", "agentId", "attempt", "latency_ms",
                        "tokens_est", "status", "errorClass"}
            for rec in lines:
                self.assertTrue(required.issubset(rec.keys()), rec)

    def test_mismatched_lengths_rejected(self):
        tuner = PromptTuner(truth_stub(self.X, self.y, marker="x"),
                            {"prompt_template": self.templates})
        with self.assertRaises(ValueError):
            tuner.fit(self.X, self.y + ["auto"])


class TestApprovalGateEval(unittest.TestCase):
    def test_labels_are_valid_and_balanced(self):
        X, y, templates, labels = approval_gate.load()
        self.assertEqual(len(X), len(y))
        self.assertTrue(all(label in labels for label in y))
        self.assertIn("auto", y)
        self.assertIn("approval", y)
        self.assertTrue(all("{text}" in t for t in templates))


if __name__ == "__main__":
    unittest.main()
