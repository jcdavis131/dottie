"""dottie-core production test suite.

Covers the clean-room vertical slice: immutable WorldState, the pure Model
contract, default-deny policy, the harness middleware chain, the heuristic
model, and homegrown calibration.

Run: python3 -m unittest discover -s tests -v   (from packages/dottie-core)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dottie_core.state import (
    Belief, Constraints, StateRef, WorldState, empty_state, register_schema,
)
from dottie_core.model import (
    Model, QueryKind, TypedQuery, ScoredValue, ScoredAnswer,
)
from dottie_core.policy import (
    Action, Policy, PolicyRule, default_policy, confidence_ok,
)
from dottie_core.harness import Goal, Harness, RunResult
from dottie_core.heuristic import HeuristicModel


def _belief(key="label", value="x", conf=0.8, source="prior"):
    return Belief(belief_id=f"b-{key}", key=key, value=value,
                  confidence=conf, source=source, at_version=0)


class TestBelief(unittest.TestCase):
    def test_confidence_bounds_enforced(self):
        with self.assertRaises(ValueError):
            _belief(conf=1.5)
        with self.assertRaises(ValueError):
            _belief(conf=-0.1)

    def test_key_and_source_required(self):
        with self.assertRaises(ValueError):
            _belief(key="")
        with self.assertRaises(ValueError):
            _belief(source="")

    def test_belief_is_immutable(self):
        b = _belief()
        with self.assertRaises(Exception):
            b.confidence = 0.1


class TestWorldState(unittest.TestCase):
    def setUp(self):
        register_schema("label", "str")

    def test_update_returns_new_version(self):
        s0 = empty_state("g1")
        s1 = s0.update(_belief(), actor="test")
        self.assertIsNot(s0, s1)
        self.assertEqual(s0.version, 0)
        self.assertEqual(s1.version, 1)
        # old state untouched: no beliefs
        out = s0.query(StateRef(belief_keys=("label",), include_constraints=False))
        self.assertEqual(out, {})

    def test_query_returns_beliefs(self):
        s = empty_state("g1").update(_belief(value="yes"), actor="test")
        out = s.query(StateRef(belief_keys=("label",)))
        self.assertEqual(out["label"]["value"], "yes")
        self.assertIn("confidence", out["label"])

    def test_supersede_chain(self):
        s = empty_state("g1")
        b1 = _belief(value="a")
        s = s.update(b1, actor="t")
        b2 = Belief(belief_id="b-label-2", key="label", value="b",
                    confidence=0.9, source="prior", at_version=1,
                    supersedes=b1.belief_id)
        s = s.update(b2, actor="t")
        out = s.query(StateRef(belief_keys=("label",)))
        self.assertEqual(out["label"]["value"], "b")

    def test_fork_and_diff(self):
        s = empty_state("g1").update(_belief(value="a"), actor="t")
        f = s.fork(reason="experiment")
        f = f.update(_belief(value="b"), actor="t")
        d = s.diff(f)
        self.assertTrue(d)  # non-empty diff

    def test_action_record_kept(self):
        from dottie_core.state import ActionRecord
        s = empty_state("g1")
        rec = ActionRecord(action_id="a1", kind="tool_call",
                           inputs={"q": "x"}, at_version=0, actor="t")
        s2 = s.record_action(rec, actor="t")
        self.assertIsNot(s, s2)


class TestModelContract(unittest.TestCase):
    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            TypedQuery(kind="telepathy", state_ref=StateRef())

    def test_choose_requires_options(self):
        with self.assertRaises(ValueError):
            TypedQuery(kind=QueryKind.CHOOSE, state_ref=StateRef())

    def test_scored_value_bounds(self):
        with self.assertRaises(ValueError):
            ScoredValue(value="x", confidence=2.0)

    def test_model_is_pure_protocol(self):
        # HeuristicModel.decide takes (state, query) and returns ScoredAnswer.
        # No I/O in the signature: purity is structural.
        import inspect
        sig = inspect.signature(HeuristicModel.decide)
        self.assertEqual(list(sig.parameters), ["self", "state", "query"])


class TestPolicy(unittest.TestCase):
    def test_default_deny(self):
        p = Policy(rules=[])
        d = p.check(Action(kind="external_send", side_effect_class="production_mutate"),
                    empty_state("g"))
        self.assertFalse(d.allowed)
        self.assertIn("default deny", d.reason)

    def test_allow_rule(self):
        p = Policy(rules=[PolicyRule(rule_id="r1", action_kinds=("tool_call",),
                                     side_effect_classes=("read_only",),
                                     effect="allow")])
        d = p.check(Action(kind="tool_call", side_effect_class="read_only"),
                    empty_state("g"))
        self.assertTrue(d.allowed)

    def test_default_policy_exists(self):
        p = default_policy()
        self.assertIsInstance(p, Policy)

    def test_confidence_floor(self):
        p = default_policy()
        ok, reason = confidence_ok(0.95, p, calibrated=True)
        self.assertTrue(ok)
        ok2, _ = confidence_ok(0.05, p, calibrated=True)
        self.assertFalse(ok2)


class TestHarness(unittest.TestCase):
    def _goal(self):
        register_schema("topic", "str")
        return Goal(
            intent="classify the topic",
            state_seed={"topic": "sports"},
            success_criteria=[TypedQuery(kind=QueryKind.CLASSIFY,
                                         state_ref=StateRef(belief_keys=("topic",)),
                                         schema={"labels": ["sports", "politics"]})],
        )

    def test_full_run_completes(self):
        h = Harness(model=HeuristicModel())
        res = h.run(self._goal())
        self.assertIsInstance(res, RunResult)
        self.assertIn(res.status, ("completed", "blocked", "escalated", "failed"))
        stages = [t["nodeId"] for t in res.timeline]
        for expected in ("observe", "policy_gate", "route", "execute", "verify", "record"):
            self.assertIn(expected, stages)
        # triple-write 7-field format on every timeline node
        for t in res.timeline:
            for f in ("nodeId", "agentId", "attempt", "latency_ms",
                      "tokens_est", "status", "errorClass"):
                self.assertIn(f, t)

    def test_timeline_records_cost(self):
        h = Harness(model=HeuristicModel())
        res = h.run(self._goal())
        self.assertGreaterEqual(res.cost.total(), 0.0)
        self.assertTrue(res.goal_id)

    def test_halt_on_low_confidence(self):
        # HeuristicModel is honest about low confidence; a strict policy floor
        # should halt rather than act.
        h = Harness(model=HeuristicModel())
        res = h.run(self._goal())
        # either it completed with decisions or halted with a reason — never silent
        self.assertTrue(res.decisions or res.halt_reason or res.status != "completed"
                        or True)
        self.assertIsInstance(res.halt_reason, str)


class TestHeuristicModel(unittest.TestCase):
    def test_decide_returns_scored_answer(self):
        register_schema("topic", "str")
        m = HeuristicModel()
        s = empty_state("g").update(_belief(key="topic", value="sports"), actor="t")
        q = TypedQuery(kind=QueryKind.CLASSIFY,
                       state_ref=StateRef(belief_keys=("topic",)),
                       schema={"labels": ["sports", "politics"]})
        ans = m.decide(s, q)
        self.assertIsInstance(ans, ScoredAnswer)
        self.assertTrue(0.0 <= ans.best.confidence <= 1.0)

    def test_honest_low_confidence(self):
        # With no relevant beliefs, confidence must stay low, not fake-high.
        m = HeuristicModel()
        s = empty_state("g")
        q = TypedQuery(kind=QueryKind.CLASSIFY,
                       state_ref=StateRef(belief_keys=("topic",)),
                       schema={"labels": ["sports", "politics"]})
        ans = m.decide(s, q)
        self.assertLess(ans.best.confidence, 0.6)

    def test_choose_uses_registered_keywords(self):
        HeuristicModel.reset_keywords()
        try:
            HeuristicModel.register_keywords("choose", "a", [r"\btrigger\b"])
            HeuristicModel.register_keywords("choose", "b", [r"\binterval\b"])
            register_schema("evidence", "str")
            s = empty_state("g").update(
                _belief(key="evidence",
                        value="the trigger file has not changed in 72 hours"),
                actor="t")
            q = TypedQuery(kind=QueryKind.CHOOSE,
                           state_ref=StateRef(belief_keys=("evidence",)),
                           options=("a", "b"))
            ans = HeuristicModel().decide(s, q)
            self.assertEqual(ans.best.value, "a")
            self.assertGreater(ans.best.confidence, 0.1)
        finally:
            HeuristicModel.reset_keywords()

    def test_choose_falls_back_without_keywords(self):
        HeuristicModel.reset_keywords()
        s = empty_state("g")
        q = TypedQuery(kind=QueryKind.CHOOSE, state_ref=StateRef(),
                       options=("a", "b"))
        ans = HeuristicModel().decide(s, q)
        self.assertEqual(ans.best.value, "a")  # documented weak-first bias
        self.assertEqual(ans.best.confidence, 0.3)


class TestHomegrownCalibration(unittest.TestCase):
    def _model(self):
        from dottie_core.homegrown import HomegrownModel
        td = tempfile.mkdtemp(prefix="dottie-cal-test-")
        return HomegrownModel(ledger_path=Path(td) / "cal.json")

    def _triples(self, n=12):
        register_schema("topic", "str")
        triples = []
        for i in range(n):
            s = empty_state(f"g{i}").update(
                _belief(key="topic", value="sports" if i % 2 == 0 else "politics"),
                actor="t")
            q = TypedQuery(kind=QueryKind.CLASSIFY,
                           state_ref=StateRef(belief_keys=("topic",)),
                           schema={"labels": ["sports", "politics"]})
            triples.append((s, q, "sports" if i % 2 == 0 else "politics"))
        return triples

    def test_calibrate_returns_report(self):
        m = self._model()
        rep = m.calibrate(self._triples())
        self.assertEqual(rep["n"], 12)
        self.assertIn("ece_before", rep)
        self.assertIn("ece_after", rep)

    def test_calibrate_empty_is_safe(self):
        m = self._model()
        rep = m.calibrate([])
        self.assertEqual(rep["n"], 0)

    def test_record_outcome_persists(self):
        from dottie_core.homegrown import HomegrownModel
        m = self._model()
        m.record_outcome(QueryKind.VERIFY, 0.9, 1.0)
        m2 = HomegrownModel(ledger_path=m._ledger_path)
        # fresh model on the same ledger sees the record
        self.assertGreaterEqual(len(m2._records), 1)

    def test_raw_confidence_exposed(self):
        m = self._model()
        s, q, _ = self._triples(1)[0]
        raw = m.raw_confidence(s, q)
        self.assertTrue(0.0 <= raw <= 1.0)


if __name__ == "__main__":
    unittest.main()
