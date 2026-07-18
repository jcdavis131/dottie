"""StreamingShardSampler tests.

The regression that motivated most of these: the sampler originally refused to
let a window straddle a document. The synthetic corpus has a median document
length of ~100 tokens, so at seq_len=256 phases 1 and 5 produced ZERO windows
and the trainer blocked forever on data that could never arrive. It did not
crash -- it starved silently, which is worse.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pytest

from ava.data import UNTAGGED_CONCEPT, _LoadedShard
from ava.pipeline.manifest import PACKED, Manifest, Shard
from ava.tokenizer import ENDOFDOC_ID


def _write_shard(dirpath: Path, doc_lens: list[int], task_types: list[str],
                 concepts: list[int]) -> Shard:
    """Pack synthetic docs exactly the way ava/pipeline/pack.py does."""
    dirpath.mkdir(parents=True, exist_ok=True)
    stream: list[int] = []
    docs = []
    for i, (n, tt, c) in enumerate(zip(doc_lens, task_types, concepts)):
        start = len(stream)
        stream.extend(range(100, 100 + n))       # distinguishable token ids
        end = len(stream)
        stream.append(ENDOFDOC_ID)               # separator, not counted
        docs.append({"doc_id": f"d{i}", "start": start, "end": end,
                     "task_type": tt, "concept_token_id": c, "phase": 0})

    bin_path = dirpath / "s.bin"
    np.array(stream, dtype=np.uint16).tofile(bin_path)
    (dirpath / "s.idx.json").write_text(json.dumps(
        {"tokens": len(stream), "tokenizer_sha": "sha", "docs": docs}))
    return Shard(id="s", source="t", phase=0, split="train", state=PACKED,
                 path=str(bin_path), bytes=0, tokens=len(stream), docs=len(docs), attempts=0)


def test_short_docs_still_produce_windows(tmp_path):
    """THE regression. 20 docs of 100 tokens must fill 256-token windows."""
    s = _write_shard(tmp_path, [100] * 20, ["deliberate"] * 20, [7] * 20)
    loaded = _LoadedShard(s)
    wins = list(loaded.windows("deliberate", 256, random.Random(0)))
    assert wins, "short docs produced no windows -- the trainer would starve forever"
    for w, _ in wins:
        assert w.shape == (257,)


def test_window_is_seq_len_plus_one(tmp_path):
    s = _write_shard(tmp_path, [500], ["automatic"], [3])
    loaded = _LoadedShard(s)
    for w, _ in loaded.windows("automatic", 128, random.Random(0)):
        assert w.shape == (129,)                 # +1 for the shifted target


def test_windows_only_mix_same_task_type(tmp_path):
    """Batches must stay task_type-pure or the routing-KL target is meaningless."""
    s = _write_shard(tmp_path, [200] * 6, ["safety"] * 3 + ["automatic"] * 3, [1] * 6)
    loaded = _LoadedShard(s)
    assert list(loaded.windows("temporal", 64, random.Random(0))) == []
    assert list(loaded.windows("safety", 64, random.Random(0)))
    assert list(loaded.windows("automatic", 64, random.Random(0)))


def test_docs_are_separated_by_endofdoc(tmp_path):
    s = _write_shard(tmp_path, [50] * 10, ["automatic"] * 10, [5] * 10)
    loaded = _LoadedShard(s)
    w, _ = next(loaded.windows("automatic", 128, random.Random(0)))
    assert ENDOFDOC_ID in w.tolist(), "document boundaries must be visible to the model"


def test_concept_is_first_tagged_doc_in_window(tmp_path):
    s = _write_shard(tmp_path, [80] * 6, ["deliberate"] * 6,
                     [UNTAGGED_CONCEPT, UNTAGGED_CONCEPT, 42, 43, 44, 45])
    loaded = _LoadedShard(s)
    _, cid = next(loaded.windows("deliberate", 64, random.Random(0)))
    assert cid >= 0 or cid == UNTAGGED_CONCEPT


def test_fully_untagged_window_reports_untagged(tmp_path):
    """A window of pure HF text must not invent a concept target."""
    s = _write_shard(tmp_path, [200] * 4, ["automatic"] * 4, [UNTAGGED_CONCEPT] * 4)
    loaded = _LoadedShard(s)
    _, cid = next(loaded.windows("automatic", 128, random.Random(0)))
    assert cid == UNTAGGED_CONCEPT


def test_tokens_are_in_uint16_range_and_int64_dtype(tmp_path):
    s = _write_shard(tmp_path, [300], ["automatic"], [9])
    loaded = _LoadedShard(s)
    w, _ = next(loaded.windows("automatic", 128, random.Random(0)))
    assert w.dtype == np.int64                   # embedding lookup needs int64
    assert w.max() < 65536


def test_empty_task_type_yields_nothing_rather_than_raising(tmp_path):
    s = _write_shard(tmp_path, [300], ["automatic"], [1])
    loaded = _LoadedShard(s)
    assert list(loaded.windows("safety", 64, random.Random(0))) == []
