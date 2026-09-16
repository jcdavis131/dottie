"""Dottie Prompt Tuner — treat prompt templates as tunable hyperparameters.

A stdlib-only port of the Machine Learning Mastery GridSearchCV idea:
candidate prompt templates are the hyperparameter grid, k-fold
cross-validation picks the winner. No sklearn, no torch, no pip.

Every fold evaluation appends a 7-field timeline record
(nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass),
per the Dottie worker's mandatory logging discipline.
"""

import json
import os
import random
import time
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def accuracy_score(y_true, y_pred):
    """Fraction of exact label matches. Unknown labels never count as correct."""
    y_true = list(y_true)
    y_pred = list(y_pred)
    if not y_true:
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


class KFold:
    """Deterministic k-fold splitter, sklearn-style API."""

    def __init__(self, n_splits=5, shuffle=True, seed=42):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.shuffle = shuffle
        self.seed = seed

    def split(self, n):
        idx = list(range(n))
        if self.shuffle:
            rng = random.Random(self.seed)
            rng.shuffle(idx)
        base, rem = divmod(n, self.n_splits)
        folds = []
        start = 0
        for i in range(self.n_splits):
            size = base + (1 if i < rem else 0)
            folds.append(idx[start:start + size])
            start += size
        for i in range(self.n_splits):
            test = folds[i]
            train = [j for k, f in enumerate(folds) if k != i for j in f]
            yield train, test


class PromptClassifier:
    """Zero-shot classifier where the prompt template is the hyperparameter.

    generate_fn: callable(prompt_text) -> str. Any backend failure is
    fail-closed: the sample is labeled "unknown" and never counted correct.
    """

    def __init__(self, generate_fn, prompt_template="Classify as auto or approval: {text}",
                 labels=("auto", "approval"), max_chars=4000):
        self.generate_fn = generate_fn
        self.prompt_template = prompt_template
        self.labels = tuple(labels)
        self.max_chars = max_chars

    def fit(self, X, y=None):
        return self  # zero-shot: nothing to train

    def _parse(self, reply):
        r = (reply or "").strip().lower()
        for label in self.labels:
            if label in r:
                return label
        return "unknown"

    def predict(self, X):
        out = []
        for text in X:
            prompt = self.prompt_template.format(text=str(text)[:self.max_chars])
            try:
                out.append(self._parse(self.generate_fn(prompt)))
            except Exception:
                out.append("unknown")  # fail-closed
        return out


class PromptTuner:
    """Grid search over prompt templates with k-fold CV. sklearn-style API.

    fit(X, y) evaluates every template, then sets best_params_,
    best_score_ and cv_results_ (one row per template: mean accuracy +
    per-fold scores).
    """

    def __init__(self, generate_fn, param_grid, cv=5, seed=42,
                 labels=("auto", "approval"), timeline_path=None,
                 run_id=None, agent_id="prompt-tuner"):
        templates = list(param_grid["prompt_template"])
        if not templates:
            raise ValueError("param_grid['prompt_template'] must not be empty")
        self.generate_fn = generate_fn
        self.templates = templates
        self.cv = cv
        self.seed = seed
        self.labels = tuple(labels)
        self.agent_id = agent_id
        self.run_id = run_id or ("run-" + utcnow())
        self.timeline_path = timeline_path
        self.best_params_ = None
        self.best_score_ = None
        self.cv_results_ = []

    def _log(self, node_id, attempt, latency_ms, tokens_est, status, error_class):
        if not self.timeline_path:
            return
        rec = {
            "nodeId": node_id,
            "agentId": self.agent_id,
            "attempt": attempt,
            "latency_ms": latency_ms,
            "tokens_est": tokens_est,
            "status": status,
            "errorClass": error_class,
            "ts": utcnow(),
            "runId": self.run_id,
        }
        d = os.path.dirname(self.timeline_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.timeline_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def fit(self, X, y):
        X = list(X)
        y = list(y)
        if len(X) != len(y):
            raise ValueError("X and y must have the same length")
        splitter = KFold(n_splits=self.cv, seed=self.seed)
        for t_idx, template in enumerate(self.templates):
            fold_scores = []
            for f_idx, (_tr, te) in enumerate(splitter.split(len(X))):
                clf = PromptClassifier(self.generate_fn,
                                       prompt_template=template,
                                       labels=self.labels)
                t0 = time.perf_counter()
                try:
                    preds = clf.predict([X[i] for i in te])
                    score = accuracy_score([y[i] for i in te], preds)
                    status, err = "ok", None
                except Exception as e:  # fail-closed: fold scores 0, keep going
                    score, status, err = 0.0, "error", type(e).__name__
                dt_ms = int((time.perf_counter() - t0) * 1000)
                self._log(node_id="t%d/f%d" % (t_idx, f_idx), attempt=1,
                          latency_ms=dt_ms,
                          tokens_est=sum(len(str(X[i])) for i in te) // 4,
                          status=status, error_class=err)
                fold_scores.append(score)
            mean = sum(fold_scores) / len(fold_scores)
            self.cv_results_.append({
                "prompt_template": template,
                "mean_accuracy": mean,
                "fold_scores": fold_scores,
            })
        best = max(self.cv_results_, key=lambda r: r["mean_accuracy"])
        self.best_params_ = {"prompt_template": best["prompt_template"]}
        self.best_score_ = best["mean_accuracy"]
        return self
