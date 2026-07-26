#!/usr/bin/env python3
"""Tests for the retrieval metrics and the golden-set miner.

These metrics decide every future retriever comparison. If NDCG is wrong, an
embedding model will be judged against a wrong bar and the verdict will be
confident and meaningless — the same failure shape as the three research `sota`
rows that turned out to be artifacts. So the metrics are checked against
hand-computed values, not against themselves.

    python scripts/test_retrieval_eval.py
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "retrieval_eval", Path(__file__).resolve().parent / "retrieval_eval.py"
)
re_ = importlib.util.module_from_spec(_SPEC)
sys.modules["retrieval_eval"] = re_
_SPEC.loader.exec_module(re_)

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}{('  — ' + detail) if detail and not cond else ''}")


def close(a, b, tol=1e-9):
    return abs(a - b) < tol


# --------------------------------------------------------------------------
# NDCG@k — hand-computed, binary relevance
# --------------------------------------------------------------------------
ok("ndcg: perfect ranking = 1.0", close(re_.ndcg_at_k(["a", "b", "c"], ["a", "b"]), 1.0))
ok("ndcg: no hits = 0.0", close(re_.ndcg_at_k(["x", "y"], ["a"]), 0.0))

# single relevant doc at rank 2: DCG = 1/log2(3); IDCG = 1/log2(2) = 1
ok(
    "ndcg: one relevant at rank 2",
    close(re_.ndcg_at_k(["x", "a", "y"], ["a"]), 1.0 / math.log2(3)),
    f"got {re_.ndcg_at_k(['x','a','y'], ['a'])}",
)
# two relevant, found at ranks 1 and 3
_dcg = 1.0 / math.log2(2) + 1.0 / math.log2(4)
_idcg = 1.0 / math.log2(2) + 1.0 / math.log2(3)
ok(
    "ndcg: two relevant at ranks 1 and 3",
    close(re_.ndcg_at_k(["a", "x", "b"], ["a", "b"]), _dcg / _idcg),
)
ok(
    "ndcg: IDCG caps at k when relevant > k",
    close(re_.ndcg_at_k(["a", "b"], ["a", "b", "c", "d"], k=2), 1.0),
    "with k=2 and 4 relevant, finding 2 in the top 2 is a perfect result AT k",
)
ok("ndcg: empty relevant set is 0, not a crash", close(re_.ndcg_at_k(["a"], []), 0.0))
ok("ndcg: empty ranking is 0", close(re_.ndcg_at_k([], ["a"]), 0.0))
ok(
    "ndcg: ordering matters (rank 1 beats rank 5)",
    re_.ndcg_at_k(["a", "x", "y", "z", "w"], ["a"])
    > re_.ndcg_at_k(["x", "y", "z", "w", "a"], ["a"]),
)

# --------------------------------------------------------------------------
# MRR — reciprocal rank of the FIRST relevant
# --------------------------------------------------------------------------
ok("mrr: first position = 1.0", close(re_.rr(["a", "b"], ["a"]), 1.0))
ok("mrr: third position = 1/3", close(re_.rr(["x", "y", "a"], ["a"]), 1 / 3))
ok("mrr: no hit = 0.0", close(re_.rr(["x"], ["a"]), 0.0))
ok(
    "mrr: uses the FIRST relevant, not the best",
    close(re_.rr(["b", "a"], ["a", "b"]), 1.0),
    "b is relevant and at rank 1",
)

# --------------------------------------------------------------------------
# recall@k
# --------------------------------------------------------------------------
ok("recall: half found", close(re_.recall_at_k(["a", "x"], ["a", "b"]), 0.5))
ok("recall: all found", close(re_.recall_at_k(["a", "b"], ["a", "b"]), 1.0))
ok(
    "recall: truncated at k",
    close(re_.recall_at_k(["x", "a"], ["a"], k=1), 0.0),
    "a is at rank 2, so recall@1 is 0",
)
ok("recall: empty relevant is 0, not a crash", close(re_.recall_at_k(["a"], []), 0.0))

# --------------------------------------------------------------------------
# The leak control — the honesty knob on the whole comparison
# --------------------------------------------------------------------------
ok(
    "leak: exact stem in the query is detected",
    re_.leaks_filename("fix bug in gate_audit today", ["scripts/gate_audit.py"]),
)
ok(
    "leak: snake_case stem split across the message is detected",
    re_.leaks_filename("the audit gate now reports paths", ["scripts/gate_audit.py"]),
    "'gate' and 'audit' both present",
)
ok(
    "leak: unrelated query is not flagged",
    not re_.leaks_filename("improve retrieval quality for the agent", ["scripts/gate_audit.py"]),
)
ok(
    "leak: partial snake_case match is NOT enough",
    not re_.leaks_filename("the gate is fine", ["scripts/gate_audit.py"]),
    "'audit' absent, so the path cannot be matched directly",
)
ok(
    "leak: any ONE relevant file leaking flags the query",
    re_.leaks_filename("touching codepairs here", ["a/b.py", "x/codepairs.py"]),
)

# --------------------------------------------------------------------------
# summarise() must not average leak-free over the wrong subset
# --------------------------------------------------------------------------
rows = [
    {"ndcg": 1.0, "mrr": 1.0, "recall": 1.0, "leak": True, "hit": True},
    {"ndcg": 0.0, "mrr": 0.0, "recall": 0.0, "leak": False, "hit": False},
]
s = re_.summarise(rows)
ok("summarise: n and n_leak_free are distinct", s["n"] == 2 and s["n_leak_free"] == 1)
ok("summarise: all-queries mean is over BOTH rows", close(s["all"]["ndcg"], 0.5))
ok(
    "summarise: leak-free mean excludes the leaking row",
    close(s["leak_free"]["ndcg"], 0.0),
    f"got {s['leak_free']['ndcg']} — a leaking row contaminated the honest bar",
)
ok("summarise: empty input does not crash", re_.summarise([])["n"] == 0)

# --------------------------------------------------------------------------
# The miner, against the real repo — non-vacuity
# --------------------------------------------------------------------------
pairs = re_.mine_pairs(400)
ok("miner: extracts pairs from the real history", len(pairs) > 50, f"got {len(pairs)}")
ok(
    "miner: every pair respects the file-count bound",
    all(1 <= len(p["relevant"]) <= re_.MAX_FILES_PER_COMMIT for p in pairs),
)
ok(
    "miner: every query clears the word floor",
    all(len(p["query"].split()) >= re_.MIN_QUERY_WORDS for p in pairs),
)
ok("miner: every pair carries a date for the walk-forward split", all(p["date"] for p in pairs))
ok(
    "miner: only indexable extensions become relevant docs",
    all(Path(f).suffix in re_.INDEXABLE for p in pairs for f in p["relevant"]),
)

# the split must be temporal, i.e. sorting by date must actually separate them
dates = sorted(p["date"] for p in pairs)
ok("miner: dates sort into a usable boundary", dates[0] < dates[-1])

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
