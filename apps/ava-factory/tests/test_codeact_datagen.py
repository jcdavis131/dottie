# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct datagen (spec 13 T13C.2) acceptance tests.

Accept criteria:
  (a) 100% of emitted trajectories re-execute under the T13C.1 CodeActSandbox to the labeled answer
  (b) no answer leakage — the prompt never contains the answer string
  (c) grounding-family share >= the configured floor
  (d) deterministic byte-identical regeneration per seed
  (e) validate_doc passes for every emitted doc
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ava.datagen.base import validate_doc  # noqa: E402
from ava.datagen.codeact import (  # noqa: E402
    ASSISTANT, USER, CodeActGenerator, GROUNDING_FLOOR_DEFAULT, iter_trajectories, render,
)
from ava.rl.codeact_sandbox import Sandbox  # noqa: E402

POSIX = os.name == "posix"
N = 30


class TestSandboxEquivalence:
    """(a) Every trajectory's blocks, run through the REAL sandbox, reach the labeled answer.

    This is the load-bearing test: it proves the generator's in-process 'answer' equals what the
    T13C.1 subprocess sandbox actually computes — i.e. the labeled answers are genuinely executable,
    not templated."""

    @pytest.mark.skipif(not POSIX, reason="sandbox resource caps require POSIX")
    def test_all_trajectories_reexecute_to_labeled_answer(self):
        for traj in iter_trajectories(seed=1, n=N):
            with Sandbox(tool_sources=traj.tool_sources, max_steps=8) as vm:
                last_value = None
                for block in traj.blocks:
                    obs = vm.step(block)
                    # a block MAY error (the recover family's first block does) — that's expected;
                    # the FINAL block must succeed and carry the answer.
                    if obs.value is not None:
                        last_value = obs.value
                assert last_value == traj.answer, (
                    f"{traj.concept}: sandbox produced {last_value!r}, labeled {traj.answer!r}"
                )

    def test_recover_family_first_block_actually_errors(self):
        # The grounding must be real: the recover trajectory's first block genuinely raises.
        recover = [t for t in iter_trajectories(seed=3, n=120) if t.concept == "codeact_recover"]
        assert recover, "no recover trajectories produced"
        with Sandbox(max_steps=8) as vm:
            first = recover[0]
            obs0 = vm.step(first.blocks[0])
            assert not obs0.ok and "KeyError" in obs0.error
            obs1 = vm.step(first.blocks[1])
            assert obs1.ok and obs1.value == first.answer


class TestNoLeakage:
    def test_prompt_never_contains_answer(self):
        for traj in iter_trajectories(seed=2, n=N):
            assert traj.answer not in traj.user, f"{traj.concept} leaked {traj.answer!r} into prompt"

    def test_user_prompt_isolated_from_answer_in_rendered_text(self):
        # The answer may appear in the Observation/final turn (that's the point), but the first
        # user turn (the prompt) must not contain it.
        for traj in iter_trajectories(seed=5, n=30):
            text = render(traj)
            first_user = text.split(ASSISTANT, 1)[0]
            assert traj.answer not in first_user


class TestGroundingFloor:
    def test_share_meets_floor(self):
        trajs = list(iter_trajectories(seed=4, n=200))
        share = sum(t.grounding for t in trajs) / len(trajs)
        assert share >= GROUNDING_FLOOR_DEFAULT, f"grounding share {share:.3f} < {GROUNDING_FLOOR_DEFAULT}"

    def test_custom_floor_respected(self):
        trajs = list(iter_trajectories(seed=6, n=200, grounding_floor=0.6))
        share = sum(t.grounding for t in trajs) / len(trajs)
        assert share >= 0.6

    def test_floor_holds_at_small_and_odd_n(self):
        # regression: the pre-item-share check undershot the floor at the tail (n=3 gave 0.333)
        for n in (3, 5, 6, 9, 11):
            for seed in (1, 2, 7, 42):
                trajs = list(iter_trajectories(seed=seed, n=n))
                share = sum(t.grounding for t in trajs) / n
                assert share >= GROUNDING_FLOOR_DEFAULT, f"n={n} seed={seed} share={share:.3f}"


class TestConstantSync:
    def test_freeze_epoch_matches_sandbox(self):
        # equivalence relies on the frozen clock being identical in both executors
        from ava.datagen.codeact import FREEZE_EPOCH, STDOUT_CAP, VALUE_CAP
        from ava.rl import codeact_sandbox as sb
        assert FREEZE_EPOCH == sb.DEFAULT_FREEZE_EPOCH
        assert STDOUT_CAP == sb.STDOUT_CAP and VALUE_CAP == sb.VALUE_CAP


class TestDeterminism:
    def test_trajectories_byte_identical_per_seed(self):
        a = [render(t) for t in iter_trajectories(seed=9, n=40)]
        b = [render(t) for t in iter_trajectories(seed=9, n=40)]
        assert a == b

    def test_generator_docs_byte_identical_per_seed(self):
        def docs(seed):
            g = CodeActGenerator(seed=seed)
            out = []
            for d in g.generate(target_bytes=20_000):
                out.append(d)
            return out
        assert docs(11) == docs(11)


class TestDocSchema:
    def test_validate_doc_passes(self):
        g = CodeActGenerator(seed=13)
        seen = 0
        for d in g.generate(target_bytes=30_000):
            validate_doc(d, allowed_phases=g.phases)
            assert d["source"] == "codeact"
            assert d["task_type"] in ("deliberate", "temporal")
            assert USER in d["text"] and "```python" in d["text"]
            seen += 1
        assert seen > 0

    def test_streams_and_stops_at_target(self):
        g = CodeActGenerator(seed=14)
        total = sum(len(d["text"].encode("utf-8")) for d in g.generate(target_bytes=15_000))
        assert total >= 15_000
