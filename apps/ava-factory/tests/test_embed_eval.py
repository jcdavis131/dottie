"""Correctness tests for embed_eval.py — the harness that PRODUCES the reported numbers.

Why this file exists: `embed_eval.py` had zero test coverage while its outputs were
being recorded in TODO.md item 6 as the findings of record (0.186 / 0.199 / 0.235 /
0.265). A measurement tool nothing verifies, whose results everything downstream
trusts, is the same shape as this repo's recurring "gate whose verdict nothing
consumes" failure — one level up: a verdict nothing checks. Every test below pins a
property whose violation would silently produce a WRONG NUMBER rather than an error,
which is the only failure mode that actually matters for a measurement harness.

Deliberately NOT tested here: the metric definitions themselves (ndcg/mrr/recall/
leak) — those live in `scripts/retrieval_eval.py`, are imported rather than
reimplemented, and are covered by `scripts/test_retrieval_eval.py` (31 tests). Testing
them again here would create the second copy of a rule that this repo's own
hard_negatives.py docstring warns about.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "embed_eval.py"
_SPEC = importlib.util.spec_from_file_location("embed_eval", _SCRIPT)
ee = importlib.util.module_from_spec(_SPEC)
sys.modules["embed_eval"] = ee
_SPEC.loader.exec_module(ee)


class TestMatryoshkaTruncation:
    """`rank_all` slices to `dim` and THEN renormalises. Doing it in the other order
    leaves the truncated prefix off the unit sphere, so cosine similarity at dim<full
    would be silently wrong — and every dim=256/128/64 row in TODO.md item 6 comes
    from this function."""

    def test_ranking_at_dim_d_ignores_dimensions_beyond_d(self):
        """THE property that proves slice-then-normalise. If the code normalised the
        FULL vector before truncating, the magnitude carried in dims > d would leak
        into the dim-d ranking. Here two doc matrices agree exactly on the first 2
        dims and differ wildly after; the dim=2 ranking must be identical."""
        q = torch.tensor([[1.0, 0.0, 0.0, 0.0]])
        docs_a = torch.tensor([
            [0.9, 0.1, 0.0, 0.0],
            [0.1, 0.9, 0.0, 0.0],
        ])
        docs_b = docs_a.clone()
        docs_b[:, 2:] = torch.tensor([[50.0, -50.0], [0.0, 0.0]])  # huge tail on row 0 only

        paths = ["a", "b"]
        ranked_a = ee.rank_all(torch, q, docs_a, paths, dim=2, k=2)
        ranked_b = ee.rank_all(torch, q, docs_b, paths, dim=2, k=2)
        assert ranked_a == ranked_b == [["a", "b"]]

    def test_truncation_actually_changes_ranking_when_it_should(self):
        """Guards the opposite error — a `dim` argument ignored entirely (always
        ranking on the full vector) would pass the test above. Here the WINNER flips
        between dim=2 and dim=4, so a no-op `dim` cannot produce both answers.
            q = [1, 0, 4, 0]
            prefix_winner = [1, 0,   0, 0]  cos@2 = 1.000   cos@4 = 0.243
            full_winner   = [0, 0.1, 4, 0]  cos@2 = 0.000   cos@4 = 0.970
        """
        q = torch.tensor([[1.0, 0.0, 4.0, 0.0]])
        docs = torch.tensor([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.1, 4.0, 0.0],
        ])
        paths = ["prefix_winner", "full_winner"]
        assert ee.rank_all(torch, q, docs, paths, dim=2, k=1) == [["prefix_winner"]]
        assert ee.rank_all(torch, q, docs, paths, dim=4, k=1) == [["full_winner"]]

    def test_k_larger_than_corpus_does_not_crash_or_pad(self):
        """k=10 against a 2-document corpus must return 2 real paths, not 10 or an
        index error — the task-slice corpus is pruned at runtime, so k>N is reachable."""
        q = torch.randn(3, 8)
        docs = torch.randn(2, 8)
        out = ee.rank_all(torch, q, docs, ["x", "y"], dim=8, k=10)
        assert len(out) == 3
        assert all(len(row) == 2 and set(row) <= {"x", "y"} for row in out)


class TestMeanPoolingIgnoresPadding:
    """If padding tokens leaked into the mean, a text's embedding would depend on what
    ELSE happened to be in its batch — the same document would score differently run to
    run depending on corpus ordering. Silent, and it would corrupt every number."""

    class _StubModel:
        """last_hidden_state[i][t] = token_id as a float, broadcast across hidden dims.
        Deterministic and hand-checkable, so the pooling arithmetic is what's under test."""

        class _Cfg:
            hidden_size = 2

        config = _Cfg()

        def __call__(self, input_ids=None, attention_mask=None):
            h = input_ids.unsqueeze(-1).float().repeat(1, 1, 2)
            return type("Out", (), {"last_hidden_state": h})()

    class _StubTokenizer:
        """Whitespace-splits, maps each token to its length, right-pads with 0 and
        marks padding in attention_mask — the only tokenizer behaviour that matters here."""

        def __call__(self, batch, padding=True, truncation=True, max_length=None,
                     return_tensors="pt"):
            seqs = [[len(t) for t in text.split()][:max_length] for text in batch]
            width = max(len(s) for s in seqs)
            ids, mask = [], []
            for s in seqs:
                pad = width - len(s)
                ids.append(s + [0] * pad)
                mask.append([1] * len(s) + [0] * pad)
            return _StubEnc({"input_ids": torch.tensor(ids),
                             "attention_mask": torch.tensor(mask)})

    def test_embedding_is_invariant_to_batch_composition(self):
        model, tok = self._StubModel(), self._StubTokenizer()
        text = "aa bb"  # -> token ids [2, 2], mean = 2.0

        alone = ee._mean_pool_encode(torch, model, tok, "cpu", [text], max_len=16)
        # batched with a much longer text, forcing heavy right-padding on `text`
        batched = ee._mean_pool_encode(
            torch, model, tok, "cpu", [text, "c dd eee ffff ggggg"], max_len=16
        )
        assert torch.allclose(alone[0], batched[0], atol=1e-6), (
            "padding leaked into the mean — embeddings depend on batch composition"
        )
        assert torch.allclose(alone[0], torch.tensor([2.0, 2.0]))

    def test_batching_boundary_does_not_change_results(self):
        """Same inputs, different batch_size, identical output — the loop must not
        drop or reorder rows at a chunk boundary."""
        model, tok = self._StubModel(), self._StubTokenizer()
        texts = ["a", "bb", "ccc", "dddd", "eeeee"]
        one_shot = ee._mean_pool_encode(torch, model, tok, "cpu", texts, 16, batch_size=64)
        chunked = ee._mean_pool_encode(torch, model, tok, "cpu", texts, 16, batch_size=2)
        assert torch.allclose(one_shot, chunked, atol=1e-6)
        assert one_shot.shape[0] == len(texts)

    def test_empty_input_returns_empty_not_crash(self):
        out = ee._mean_pool_encode(torch, self._StubModel(), self._StubTokenizer(),
                                    "cpu", [], max_len=16)
        assert out.shape[0] == 0


class _StubEnc(dict):
    """Mimics a transformers BatchEncoding: subscriptable, ``**`` -splattable, and
    ``.to(device)`` returns self."""

    def to(self, device):
        return self


class TestScorePairsAlignment:
    def test_misaligned_lengths_raise_rather_than_score_the_wrong_pair(self):
        """`zip(..., strict=True)` is load-bearing: without it, a query list and a
        ranked list of different lengths would silently truncate and every metric
        would be computed against the WRONG relevance judgements — a plausible-looking
        number with no error anywhere."""
        pairs = [{"query": "q1", "relevant": ["a"]}, {"query": "q2", "relevant": ["b"]}]
        ranked_lists = [["a"]]  # one short
        with pytest.raises(ValueError):
            ee.score_pairs(pairs, ranked_lists)

    def test_hit_and_leak_fields_are_populated_per_row(self):
        pairs = [{"query": "fix the widget", "relevant": ["src/widget.py"]}]
        rows = ee.score_pairs(pairs, [["src/widget.py", "other.py"]])
        assert len(rows) == 1
        assert rows[0]["hit"] is True
        assert set(rows[0]) == {"ndcg", "mrr", "recall", "leak", "hit"}

    def test_a_miss_is_recorded_as_a_miss(self):
        """Guards the inverse of the test above — a `hit` hardcoded True would pass it."""
        pairs = [{"query": "unrelated", "relevant": ["src/widget.py"]}]
        rows = ee.score_pairs(pairs, [["nope.py", "also_nope.py"]])
        assert rows[0]["hit"] is False
        assert rows[0]["ndcg"] == 0.0


class TestRecordedBaselineIsNotSilentlyEdited:
    """The 0.429 target is the whole point of the exercise; `beats_target` compares
    against it. If this constant drifted, a miss could silently render as a win."""

    def test_task_target_is_the_pre_registered_number(self):
        assert ee.RECORDED["task"]["ndcg"] == 0.429

    def test_commit_baseline_is_the_recorded_number(self):
        assert ee.RECORDED["commit"]["ndcg"] == 0.622


class TestCliContract:
    def test_checkpoint_is_required_without_base_only(self):
        with pytest.raises(SystemExit):
            ee.main([])

    def test_base_only_is_accepted_without_a_checkpoint(self):
        """Only checks that argument validation passes — a full run needs a model
        download and several minutes of inference, which belongs in a real run, not a
        unit test. Anything past parsing is allowed to fail here."""
        try:
            ee.main(["--base-only", "--dims", "8", "--max-commits", "1"])
        except SystemExit as e:  # argparse rejected it -> the contract is broken
            pytest.fail(f"--base-only should not require --checkpoint (SystemExit: {e})")
        except Exception:
            pass  # got past validation into real work; that is all this test claims

    def test_remote_code_execution_is_off_unless_asked_for(self):
        """--trust-remote-code executes Python fetched from the Hub with this user's
        privileges, on a box holding a live HF_TOKEN. Some encoders (LFM2.5-Encoder)
        cannot load without it, so the capability exists — but a default of True is
        the kind of thing that gets inherited by copy-paste and never noticed again,
        so pin the default rather than trusting it to stay put."""
        captured = {}

        class _Spy(ee.BaseOnlyEncoder):
            def __init__(self, base_model, dims, device, trust_remote_code=False):
                captured["trust"] = trust_remote_code
                raise RuntimeError("stop before any download")

        real = ee.BaseOnlyEncoder
        ee.BaseOnlyEncoder = _Spy
        try:
            for argv, expected in (
                (["--base-only", "--dims", "8", "--max-commits", "1"], False),
                (["--base-only", "--dims", "8", "--max-commits", "1",
                  "--trust-remote-code"], True),
            ):
                captured.clear()
                try:
                    ee.main(argv)
                except Exception:
                    pass
                assert captured.get("trust") is expected, (
                    f"argv {argv} produced trust_remote_code={captured.get('trust')!r}, "
                    f"expected {expected}"
                )
        finally:
            ee.BaseOnlyEncoder = real
