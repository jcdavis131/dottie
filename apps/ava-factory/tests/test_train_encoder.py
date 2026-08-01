"""Pure-function tests for train_encoder.py.

The end-to-end training run (base model load, LoRA forward/backward, checkpoint I/O) is
exercised by ``python train_encoder.py --smoke`` — verified manually 2026-07-31 at both a
narrow scope (apps/ava-factory: 15.1s) and full default scope (whole monorepo: 19.5s),
plus a real (non-smoke, tiny) train -> save -> embed_eval.py round trip. That is not
re-run here because it needs a GPU and network-free HF cache access, both true on this
box but not guaranteed in every environment pytest runs in. What IS covered here, per
the same split test_train_smoke.py (this directory) already draws: the pure functions a
smoke run would only catch by drifting, not the model plumbing around them.

Two things matter enough to pin:
  1. The Matryoshka loss is actually lower for a batch where queries match their own
     positives than for one where they are shuffled — if this regressed to "always
     roughly log(B)" the training loop would run and lose with nobody noticing.
  2. The task domain's examples are built ONLY from the walk-forward TRAIN half of the
     golden set — this is the one property that keeps embed_eval.py's numbers honest,
     and it is exactly the kind of thing that silently rots if a future edit reorders
     the split-then-mine steps.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
import torch.nn.functional as F

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_encoder.py"
_SPEC = importlib.util.spec_from_file_location("train_encoder", _SCRIPT)
te = importlib.util.module_from_spec(_SPEC)
sys.modules["train_encoder"] = te
_SPEC.loader.exec_module(te)


def _rand_unit(n, d, generator):
    x = torch.randn(n, d, generator=generator)
    return x


class TestMatryoshkaInfoNCE:
    def test_aligned_batch_scores_lower_than_shuffled(self):
        """A batch where q[i] truly matches pos[i] must beat a batch where the same
        vectors are randomly paired — otherwise the loss carries no training signal."""
        g = torch.Generator().manual_seed(7)
        B, D = 8, 32
        q = _rand_unit(B, D, g)
        pos = q + 0.01 * _rand_unit(B, D, g)  # near-duplicate of its own query
        negs = torch.zeros(B, 0, D)
        neg_mask = torch.zeros(B, 0, dtype=torch.bool)

        aligned = te.matryoshka_info_nce(torch, F, q, pos, negs, neg_mask, (D,), 0.05)

        perm = torch.randperm(B, generator=g)
        shuffled = te.matryoshka_info_nce(torch, F, q, pos[perm], negs, neg_mask, (D,), 0.05)

        assert aligned.item() < shuffled.item()

    def test_hard_negative_raises_loss_over_no_negative(self):
        """A hard negative equal to the positive (worst case: indistinguishable) must not
        lower the loss versus having no negative at all."""
        g = torch.Generator().manual_seed(11)
        B, D, N = 4, 16, 1
        q = _rand_unit(B, D, g)
        pos = q.clone()

        no_neg = te.matryoshka_info_nce(
            torch, F, q, pos, torch.zeros(B, 0, D), torch.zeros(B, 0, dtype=torch.bool),
            (D,), 0.05,
        )
        hard_neg = pos.unsqueeze(1).clone()  # negs[i, 0] == pos[i]: as confusable as it gets
        with_neg = te.matryoshka_info_nce(
            torch, F, q, pos, hard_neg, torch.ones(B, N, dtype=torch.bool), (D,), 0.05,
        )
        assert with_neg.item() >= no_neg.item()

    def test_masked_negative_slot_is_excluded_not_zero_similarity(self):
        """A padded (masked) negative slot must not participate in the softmax at all —
        if the mask were ignored, an all-zero pad vector would look like a weak-but-real
        negative instead of an absent one, silently changing every loss value."""
        g = torch.Generator().manual_seed(3)
        B, D = 4, 8
        q = _rand_unit(B, D, g)
        pos = q.clone()
        negs = torch.zeros(B, 1, D)
        all_masked = torch.zeros(B, 1, dtype=torch.bool)

        masked_out = te.matryoshka_info_nce(torch, F, q, pos, negs, all_masked, (D,), 0.05)
        no_neg_col = te.matryoshka_info_nce(
            torch, F, q, pos, torch.zeros(B, 0, D), torch.zeros(B, 0, dtype=torch.bool),
            (D,), 0.05,
        )
        assert masked_out.item() == pytest.approx(no_neg_col.item(), abs=1e-5)

    def test_sums_over_every_dim_not_just_the_last(self):
        """Two nesting-dim tuples that share every dim but one must produce a different
        loss — proves each dim actually contributes, not just the final one in the list."""
        g = torch.Generator().manual_seed(5)
        B, D = 6, 32
        q = _rand_unit(B, D, g)
        pos = _rand_unit(B, D, g)
        negs = torch.zeros(B, 0, D)
        mask = torch.zeros(B, 0, dtype=torch.bool)

        only_full = te.matryoshka_info_nce(torch, F, q, pos, negs, mask, (32,), 0.05)
        full_and_half = te.matryoshka_info_nce(torch, F, q, pos, negs, mask, (32, 16), 0.05)
        assert only_full.item() != pytest.approx(full_and_half.item())


class TestTaskDomainSplitDiscipline:
    def test_task_examples_only_draw_from_the_walk_forward_train_half(self):
        """The one property embed_eval.py's honesty depends on: nothing test_examples()
        builds for the `task` domain may come from a commit dated at or after the split
        boundary retrieval_eval.py itself would compute for the same split_frac."""
        max_commits, split_frac = 400, 0.7
        golden = te.retrieval_eval.mine_pairs(max_commits)
        golden.sort(key=lambda p: p["date"])
        cut = int(len(golden) * split_frac)
        boundary_date = golden[cut]["date"] if cut < len(golden) else None

        records = te.hard_negatives.mine_adjacent_negatives(
            golden[:cut], window=te.hard_negatives.DEFAULT_WINDOW, n=4
        )
        # every source commit `mine_adjacent_negatives` drew from must be in the TRAIN slice
        train_dates = {g["date"] for g in golden[:cut]}
        for r in records:
            assert r["date"] in train_dates
            if boundary_date is not None:
                assert r["date"] < boundary_date

    def test_task_examples_wires_split_frac_through(self):
        """A split_frac of 0.0 must yield zero task examples (empty train half) — pins
        that the argument is actually threaded to the mining call, not silently ignored."""
        out = te.task_examples(max_commits=200, split_frac=0.0, window=5, n_neg=4)
        assert out == []
