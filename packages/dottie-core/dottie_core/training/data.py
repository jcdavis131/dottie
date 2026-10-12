# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Synthetic training data for the calibrator net. Stdlib only.

Each example: (13-dim features, query-kind index, correctness in [0, 1]).

Correctness is the heuristic's *graded* answer quality — computed with the
same `_grade` the calibration ledger uses — so the net learns exactly what
calibration means: P(the heuristic is right | this state).

Ground truth is constructed, not guessed: we sample a hidden label/score,
emit beliefs as noisy evidence for it, run the heuristic, and grade.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Iterator

from dottie_core.homegrown import HomegrownModel, encode_state
from dottie_core.model import QueryKind, TypedQuery
from dottie_core.state import Belief, StateRef, WorldState, empty_state

KINDS = QueryKind.ALL
KIND_TO_IDX = {k: i for i, k in enumerate(KINDS)}

LABELS = ("alpha", "beta", "gamma", "delta")


def _belief(bid: str, key: str, value, conf: float, source: str,
            version: int, supersedes=None) -> Belief:
    return Belief(belief_id=bid, key=key, value=value, confidence=conf,
                  source=source, at_version=version, supersedes=supersedes)


def _add(state: WorldState, belief: Belief, actor: str = "synth") -> WorldState:
    return state.update(belief, actor)


def _features(state: WorldState, kind: str) -> list[float]:
    """13-dim input: 8 state features + 5-dim query-kind one-hot."""
    feats = encode_state(state)
    onehot = [1.0 if k == kind else 0.0 for k in KINDS]
    return feats + onehot


def _gen_classify(rng: random.Random, model: HomegrownModel, vid: int):
    """Hidden label; beliefs are noisy votes. Heuristic ranks by token overlap."""
    true_label = rng.choice(LABELS)
    state = empty_state("synth")
    keys = []
    n = rng.randint(2, 8)
    for i in range(n):
        # 70%: evidence for the true label; 30%: noise for a random other label
        if rng.random() < 0.7:
            tok, conf = true_label, rng.uniform(0.55, 0.98)
        else:
            tok, conf = rng.choice([l for l in LABELS if l != true_label]), rng.uniform(0.2, 0.6)
        src = rng.choice(["tool:scanner", "model:heuristic-v0", "human:op", "prior"])
        key = f"vote_{i}"
        keys.append(key)
        state = _add(state, _belief(f"b{vid}_{i}", key,
                                    f"signal mentions {tok} strongly", conf, src, i))
    # occasional contradiction: a superseding belief revises an earlier vote
    if n >= 3 and rng.random() < 0.3:
        keys.append("revision")
        state = _add(state, _belief(f"b{vid}_r", "revision",
                                    f"correction: actually {true_label}", rng.uniform(0.6, 0.9),
                                    "human:op", n, supersedes=f"b{vid}_0"))
    query = TypedQuery(kind=QueryKind.CLASSIFY, state_ref=StateRef(belief_keys=tuple(keys)),
                       options=LABELS)
    ans = model.decide(state, query)
    correct = 1.0 if ans.best.value == true_label else 0.0
    return _features(state, QueryKind.CLASSIFY), 0, correct


def _gen_choose(rng: random.Random, model: HomegrownModel, vid: int):
    """Like classify, but options are a random subset (2-3 of 4)."""
    options = tuple(rng.sample(LABELS, rng.randint(2, 3)))
    true_label = rng.choice(options)
    state = empty_state("synth")
    keys = []
    for i in range(rng.randint(2, 6)):
        tok = true_label if rng.random() < 0.75 else rng.choice([l for l in options if l != true_label])
        key = f"opt_{i}"
        keys.append(key)
        state = _add(state, _belief(f"b{vid}_{i}", key,
                                    f"evidence points to {tok}", rng.uniform(0.4, 0.95),
                                    rng.choice(["tool:x", "model:heuristic-v0", "prior"]), i))
    query = TypedQuery(kind=QueryKind.CHOOSE, state_ref=StateRef(belief_keys=tuple(keys)),
                       options=options)
    ans = model.decide(state, query)
    correct = 1.0 if ans.best.value == true_label else 0.0
    return _features(state, QueryKind.CHOOSE), 2, correct


def _gen_score(rng: random.Random, model: HomegrownModel, vid: int):
    """Hidden true score; beliefs are noisy numeric estimates."""
    true_score = rng.uniform(0.05, 0.95)
    state = empty_state("synth")
    keys = []
    for i in range(rng.randint(2, 6)):
        est = max(0.0, min(1.0, rng.gauss(true_score, 0.18)))
        key = f"est_{i}"
        keys.append(key)
        state = _add(state, _belief(f"b{vid}_{i}", key, est,
                                    rng.uniform(0.4, 0.95),
                                    rng.choice(["tool:meter", "model:heuristic-v0", "prior"]), i))
    query = TypedQuery(kind=QueryKind.SCORE, state_ref=StateRef(belief_keys=tuple(keys)))
    ans = model.decide(state, query)
    try:
        pred = float(ans.best.value)
    except (TypeError, ValueError):
        pred = 0.5
    correct = max(0.0, 1.0 - abs(pred - true_score))
    return _features(state, QueryKind.SCORE), 1, correct


def _gen_verify(rng: random.Random, model: HomegrownModel, vid: int):
    """Hidden claim truth; beliefs are supporting/refuting evidence."""
    truth = rng.choice(["supported", "refuted"])
    state = empty_state("synth")
    claim = "the cache is consistent"
    keys = []
    for i in range(rng.randint(2, 6)):
        if truth == "supported":
            # share >=2/3 claim tokens ("cache", "consistent") -> heuristic says "supported"
            txt = ("cache is consistent, check passed" if rng.random() < 0.8
                   else "shard anomaly, writes delayed")
        else:
            # share 0 claim tokens -> heuristic says "refuted"
            txt = ("shard divergence detected, writes failing" if rng.random() < 0.8
                   else "cache audit nominal")
        key = f"ev_{i}"
        keys.append(key)
        state = _add(state, _belief(f"b{vid}_{i}", key, txt,
                                    rng.uniform(0.4, 0.95),
                                    rng.choice(["tool:probe", "model:heuristic-v0", "human:op"]), i))
    query = TypedQuery(kind=QueryKind.VERIFY, state_ref=StateRef(belief_keys=tuple(keys)),
                       claim=claim)
    ans = model.decide(state, query)
    try:
        correct = float(model._grade(query, ans.best.value, truth))
    except Exception:
        correct = 0.0
    return _features(state, QueryKind.VERIFY), 4, correct


def _gen_extract(rng: random.Random, model: HomegrownModel, vid: int):
    """Hidden struct; beliefs carry fields. Correct on exact field match."""
    true_struct = {"name": rng.choice(LABELS), "count": rng.randint(1, 9)}
    state = empty_state("synth")
    # emit each field, sometimes with a noisy duplicate
    state = _add(state, _belief(f"b{vid}_0", "name", true_struct["name"],
                                rng.uniform(0.6, 0.98), "tool:parser", 0))
    state = _add(state, _belief(f"b{vid}_1", "count", true_struct["count"],
                                rng.uniform(0.6, 0.98), "tool:parser", 1))
    if rng.random() < 0.4:  # noisy duplicate with lower confidence
        state = _add(state, _belief(f"b{vid}_2", "count", true_struct["count"] + rng.choice([-1, 1]),
                                rng.uniform(0.2, 0.45), "prior", 2))
    query = TypedQuery(kind=QueryKind.EXTRACT,
                       state_ref=StateRef(belief_keys=("name", "count")),
                       schema={"fields": ("name", "count")})
    ans = model.decide(state, query)
    try:
        correct = float(model._grade(query, ans.best.value, true_struct))
    except Exception:
        correct = 0.0
    return _features(state, QueryKind.EXTRACT), 3, correct


_GENERATORS = {
    QueryKind.CLASSIFY: _gen_classify,
    QueryKind.SCORE: _gen_score,
    QueryKind.CHOOSE: _gen_choose,
    QueryKind.EXTRACT: _gen_extract,
    QueryKind.VERIFY: _gen_verify,
}


def stream_examples(n: int, seed: int = 0) -> Iterator[tuple[list[float], int, float]]:
    """Yield (features13, kind_idx, correctness) triples. Streaming — O(1) RAM."""
    rng = random.Random(seed)
    # HomegrownModel with a temp ledger path so training never touches the
    # user's real calibration ledger.
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="dottie-train-ledger-"))
    model = HomegrownModel(ledger_path=tmp / "calibration.json")
    kinds = list(KINDS)
    for i in range(n):
        kind = kinds[i % len(kinds)]  # balanced across kinds
        try:
            feats, kidx, correct = _GENERATORS[kind](rng, model, i)
        except Exception:
            continue  # a malformed synthetic state is a data bug, not a crash
        yield feats, kidx, max(0.0, min(1.0, float(correct)))


def write_jsonl(path: str | Path, n: int, seed: int = 0) -> int:
    """Materialize n examples to JSONL. Returns count written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for feats, kidx, correct in stream_examples(n, seed):
            f.write(json.dumps({"x": feats, "k": kidx, "y": correct}) + "\n")
            count += 1
    return count


def load_jsonl(path: str | Path):
    """Load examples as three parallel lists (features, kind_idx, correctness)."""
    xs, ks, ys = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            xs.append(d["x"])
            ks.append(d["k"])
            ys.append(d["y"])
    return xs, ks, ys
