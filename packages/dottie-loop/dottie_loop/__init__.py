"""dottie_loop — the Dottie Full Ecosystem specification (v1.0, 2026-09-10) as code.

Every module maps to a numbered section of the specification and implements its
contract as typed records, validators and gates that FAIL CLOSED: an unknown,
stale, malformed or unauthorized state raises a typed error or returns a typed
``blocked`` decision. Nothing here fabricates success, infers consent, or grants
itself authority.

Module map (spec section → module):

* §05 intake, §37A GoalEnvelope        → :mod:`dottie_loop.intake`
* §07 identity/scopes/approvals, §37C  → :mod:`dottie_loop.approvals`
* §09 DAG planning and budgets         → :mod:`dottie_loop.plan`
* §10 execution kernel, §11 recovery   → :mod:`dottie_loop.execution`
* §14 state/checkpoints, §37A RunEvent → :mod:`dottie_loop.timeline`
* §16 pair capture, §17 privacy        → :mod:`dottie_loop.capture`
* §22 reward contract, §37B            → :mod:`dottie_loop.reward`
* §18–§20 data pipeline, §17 deletion  → :mod:`dottie_loop.dataset`
* §21 training                         → :mod:`dottie_loop.training`
* §24 evaluation, §25 promotion        → :mod:`dottie_loop.evaluation`
* §26 closed loop                      → :mod:`dottie_loop.closed_loop`
* §27 Forge                            → :mod:`dottie_loop.forge`
* §23 benchmark builder                → :mod:`dottie_loop.bench`
* §11 error taxonomy, §37D API errors  → :mod:`dottie_loop.errors`
* research stage 1 (AdvancedIF rubrics) → :mod:`dottie_loop.rubric`
* research stage 2 (correctness-gated opt) → :mod:`dottie_loop.opt_lane`
* research stage 3 (AIRA2 experiments) → :mod:`dottie_loop.experiment`
* research stage 4 (Compute-as-Teacher) → :mod:`dottie_loop.compute_teacher`
* research stage 5 (S-EMBER causal memory) → :mod:`dottie_loop.ember`
* research stage 6 (HyperAgents proposal-only) → :mod:`dottie_loop.hyperagents`

stdlib only. No model is called anywhere in this package; it is the deterministic
backbone (spec §02 "Determinism first") that a model layer may sit on top of.
"""

from __future__ import annotations

__version__ = "0.1.0"
SPEC_VERSION = "1.0"
SPEC_BASELINE = "2026-09-10"
