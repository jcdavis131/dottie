# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeAct eval (spec 13 T13C.3) — exec-verified success rate over a frozen held-out set.

The eval's **scoring engine is real**: it runs emitted code blocks through the T13C.1 `Sandbox`
and checks the final value equals the trajectory's gold answer. That engine is GPU-free and
fully tested here.

The **real-model path** (`run_codeact_eval`) needs the CodeAct decode loop — emit code → run in
the sandbox → feed the Observation back → iterate — which is the `ServeEngine` code-act loop
(T13C.5), not yet wired. So real mode **fails honestly** (returns an error record) rather than
fabricating a capability number, matching this repo's anti-mock discipline. Until then,
`simulate_policy_eval` exercises the real scoring engine with a *clearly-labeled synthetic policy*
(a plumbing check that varies by seed and is sensitive to a broken tool binding), satisfying the
T13C.3 acceptance criteria without a model.
"""

from __future__ import annotations

import random
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ava.datagen.codeact import Trajectory, iter_trajectories
from ava.rl.codeact_sandbox import Sandbox

CODEACT_EVAL_SEED = 20_240_717   # frozen held-out set seed (comparable across milestones)
CODEACT_BAR = 0.70


def held_out(n: int) -> List[Trajectory]:
    """Frozen held-out trajectory set — same seed every call so scores are comparable."""
    return list(iter_trajectories(seed=CODEACT_EVAL_SEED, n=n))


_CORRUPT_SENTINEL = "'__codeact_corrupted__'"


def score_emission(blocks: Sequence[str], gold_answer: str,
                   tool_sources: Optional[Dict[str, str]] = None, *, max_steps: int = 32) -> bool:
    """Run emitted code through the REAL sandbox; True iff the FINAL block succeeds with the gold
    answer.

    Judged on the final block's *outcome*, not the last non-None value seen: a trailing block that
    errors (or hits the step cap) is a failure even if an earlier block produced the gold value,
    and a trajectory that never yields a final value fails. Intermediate blocks may error (the
    recover family's first block does) — only the last block decides success. Load-bearing primitive."""
    with Sandbox(tool_sources=tool_sources or {}, max_steps=max_steps) as vm:
        final = None
        for block in blocks:
            final = vm.step(block)
    if final is None or not final.ok:      # empty trajectory, trailing error, or step-cap hit
        return False
    return final.value == gold_answer


def _corrupt(blocks: List[str]) -> List[str]:
    """Deterministically break a trajectory so its final value can NEVER equal any gold answer.

    Emits a fixed sentinel STRING (repr `'__codeact_corrupted__'`) rather than the literal 0 — the
    old `0` collided with any future family whose gold answer is 0, which would silently inflate
    the plumbing success rate. Used only by the synthetic-policy plumbing check."""
    return list(blocks[:-1]) + [f"{_CORRUPT_SENTINEL}  # corrupted emission"]


def simulate_policy_eval(n: int = 20, accuracy: float = 0.8, seed: int = CODEACT_EVAL_SEED,
                         tool_binding_ok: bool = True) -> Dict[str, Any]:
    """Plumbing check: a seeded synthetic 'policy' emits correct-or-corrupted code per trajectory;
    every score comes from REAL sandbox execution. NOT a model-capability measurement — it exists to
    prove the eval harness works, varies by seed, and is sensitive to a broken tool binding."""
    trajs = held_out(n)
    rng = random.Random(seed)
    successes = 0
    for traj in trajs:
        emit_correct = rng.random() < accuracy
        blocks = traj.blocks if emit_correct else _corrupt(traj.blocks)
        tool_sources = traj.tool_sources if tool_binding_ok else {}
        successes += int(score_emission(blocks, traj.answer, tool_sources))
    rate = successes / max(1, len(trajs))
    # Distinct test name + capability:false so a consumer keying on test-name+pass can never mistake
    # this plumbing check for a real capability measurement.
    return {
        "test": "codeact_simulation", "mode": "simulation", "capability": False,
        "measured": {"success_rate": round(rate, 4), "n": len(trajs),
                     "tool_binding_ok": tool_binding_ok},
        "pass": rate >= CODEACT_BAR,
        "bar": f"success_rate>={CODEACT_BAR}",
        "note": "synthetic-policy plumbing check — NOT model capability",
    }


def run_codeact_eval(model: Any, tokenizer: Any, preset: str = "nano",
                     device: str = "cpu", n: int = 20) -> Dict[str, Any]:
    """Real-model CodeAct eval, now WIRED to the T13C.5 decode loop: it drives the model through
    `run_code_act` over the frozen held-out set and scores each episode's FINAL against the gold
    answer via the real sandbox. It still **fails honestly** — the model-driving policy (`ModelPolicy`)
    is gated on a branch fine-tune checkpoint (T9.3/T9.5, absent) and a GPU (BLOCKED_NO_GPU), so the
    loop refuses rather than fabricating a rate. The difference from before: the failure now comes
    from the *actual wired path* hitting its honest boundary, not a hand-written 'not implemented'.
    """
    from ava.rl.codeact_loop import ModelPolicy, ModelPolicyBlockedError, run_code_act

    policy = ModelPolicy(model=model, tokenizer=tokenizer)
    trajs = held_out(n)
    try:
        successes = 0
        for traj in trajs:
            res = run_code_act(policy, traj.user, tool_sources=traj.tool_sources)
            successes += int(res.reached_final and res.final is not None
                             and traj.answer in res.final)
        rate = successes / max(1, len(trajs))
        return {"test": "codeact", "measured": {"success_rate": round(rate, 4), "n": len(trajs)},
                "pass": rate >= CODEACT_BAR, "bar": f"success_rate>={CODEACT_BAR}"}
    except ModelPolicyBlockedError as e:
        # The wired loop reached its honest boundary: no real policy to decode with.
        return {"test": "codeact", "measured": None, "pass": False,
                "bar": f"success_rate>={CODEACT_BAR}", "error": str(e)}
