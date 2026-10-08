#!/usr/bin/env python3
"""Homegrown state-model demo: decisions, calibration, and honest uncertainty.

Our code, our patterns — a state-in / typed-answers-out model with a
persistent (predicted, outcome) ledger that corrects systematic
over/under-confidence per query kind. Stdlib only, no API keys.

What this shows:
1. decide() is pure: same (state, query) -> same answer, twice.
2. Calibration works: 10 VERIFY trials where the model is overconfident
   (raw ~0.86, right only 4/10) -> the ledger learns a -0.30 bias and
   expected calibration error drops.
3. calibrate() refits on labeled triples and reports ECE before/after.
4. HeuristicModel has no ledger: its confidence never adapts.
5. The ledger persists: a fresh model on the same path inherits the bias.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_core import (  # noqa: E402
    Belief,
    HeuristicModel,
    HomegrownModel,
    QueryKind,
    StateRef,
    TypedQuery,
    empty_state,
    encode_state,
)
from dottie_core.homegrown import expected_calibration_error  # noqa: E402


def build_state():
    s = empty_state("demo-homegrown")
    seeds = [
        ("lines_changed", 42, 0.90, "tool:diff", None),
        ("tests_pass", True, 0.90, "tool:pytest", None),
        ("touches_auth", True, 0.95, "tool:scanner", None),
        ("risk_assessment", "high", 0.70, "model:homegrown-v0", None),
        ("change_summary",
         "the change touches authentication code and token expiry; "
         "forty two lines changed; tests are passing; risk assessment is high",
         0.85, "tool:scanner", None),
    ]
    for i, (k, v, c, src, sup) in enumerate(seeds):
        s = s.update(Belief(belief_id=f"b{i:03d}", key=k, value=v,
                            confidence=c, source=src, at_version=s.version,
                            supersedes=sup), actor="demo")
    return s


REF = StateRef(belief_keys=("lines_changed", "tests_pass", "touches_auth",
                            "risk_assessment", "change_summary"))

# 10 claims with high word overlap against the change_summary belief ->
# the model says "supported" with high raw confidence (~0.86).
# Ground truth: only 4 are actually supported -> overconfidence to correct.
TRIALS = [
    ("the change touches authentication code", "supported"),
    ("risk assessment is high for this change", "supported"),
    ("tests are passing on the authentication change", "supported"),
    ("token expiry touches the changed code", "supported"),
    ("authentication token expiry after tests are passing", "refuted"),
    ("the change rewrites the token expiry logic", "refuted"),
    ("high risk because tests are passing", "refuted"),
    ("token expiry is covered by passing tests", "refuted"),
    ("the authentication change keeps token expiry", "refuted"),
    ("passing tests prove the token change is safe", "refuted"),
]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dottie-cal-")
    ledger = Path(tmp) / "calibration.json"
    model = HomegrownModel(ledger_path=ledger)
    state = build_state()

    print("== 1. feature encoder ==")
    print("features:", [round(f, 3) for f in encode_state(state)])
    print()

    print("== 2. decide() is pure ==")
    q = TypedQuery(kind=QueryKind.VERIFY, state_ref=REF, claim=TRIALS[0][0])
    a1, a2 = model.decide(state, q), model.decide(state, q)
    assert (a1.best.value, a1.best.confidence) == (a2.best.value, a2.best.confidence)
    print(f"same (state, query) twice -> identical: {a1.best.value} @ {a1.best.confidence}")
    print(f"protocol: {model.model_id}, floor: {model.confidence_floor}, "
          f"calibration: {model.calibration}")
    print()

    print("== 3. calibration over 10 trials (model starts overconfident) ==")
    raw_preds, outcomes = [], []
    for claim, truth in TRIALS:
        qq = TypedQuery(kind=QueryKind.VERIFY, state_ref=REF, claim=claim)
        # Ledger learns on RAW confidence; the verdict comes from decide().
        raw = model.raw_confidence(state, qq)
        verdict = model.decide(state, qq).best.value
        hit = 1.0 if verdict == truth else 0.0
        raw_preds.append(raw)
        outcomes.append(hit)
        model.record_outcome(QueryKind.VERIFY, raw, hit)
        print(f"  pred={verdict:9s} raw_conf={raw:.3f} truth={truth:9s} "
              f"{'HIT ' if hit else 'MISS'}")
    ece_before = expected_calibration_error(raw_preds, outcomes)
    cal_preds = [round(min(0.99, max(0.01, p + model.bias_report()["bias"]["verify"])), 3)
                 for p in raw_preds]
    ece_after = expected_calibration_error(cal_preds, outcomes)
    print(f"raw mean conf: {sum(raw_preds)/len(raw_preds):.3f}, "
          f"accuracy: {sum(outcomes)/len(outcomes):.3f}")
    print(f"bias learned: {model.bias_report()['bias']}")
    print(f"ECE before: {ece_before} -> ECE after: {ece_after}")
    assert ece_after < ece_before, "calibration must reduce ECE"
    print()

    print("== 4. calibrate() on labeled triples (fresh model, isolated) ==")
    m2 = HomegrownModel(ledger_path=Path(tmp) / "calibration2.json")
    triples = [
        (state, TypedQuery(kind=QueryKind.VERIFY, state_ref=REF, claim=t[0]), t[1])
        for t in TRIALS[:3]  # all hits: model was right, confidence should nudge up
    ]
    report = m2.calibrate(triples)
    print(f"report: {report}")
    assert report["ece_after"] <= report["ece_before"], "calibrate() must not worsen ECE"
    print()

    print("== 5. heuristic has no ledger (static confidence) ==")
    heur = HeuristicModel()
    h_confs = set()
    for claim, _ in TRIALS:
        qq = TypedQuery(kind=QueryKind.VERIFY, state_ref=REF, claim=claim)
        h_confs.add(heur.decide(state, qq).best.confidence)
    print(f"heuristic confidences across trials: {sorted(h_confs)} "
          f"(fixed rules, nothing learned)")
    print(f"homegrown bias after trials: {model.bias_report()['bias']} (adapted)")
    print()

    print("== 6. ledger persists ==")
    model2 = HomegrownModel(ledger_path=ledger)
    r2 = model2.bias_report()
    print(f"fresh model on same ledger: n_records={r2['n_records']}, bias={r2['bias']}")
    assert r2["n_records"] == model.bias_report()["n_records"]
    print()
    print("demo complete: our state-model decides, tracks, and calibrates itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
