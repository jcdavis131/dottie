"""Stage 1: AdvancedIF-style rubric rewards — contracts and failure modes."""

from __future__ import annotations

import json

import pytest

from dottie_loop import errors, evaluation, research, reward, rubric
from dottie_loop.cli import EXIT_OK, main
from dottie_loop.schema import active


def _rubric() -> rubric.Rubric:
    return rubric.Rubric(
        rubric_id="adv-if-demo",
        version="1.0.0",
        name="advanced-if",
        criteria=[
            rubric.RubricCriterion("task", "task_success", "The asked task completed.", 2.0, True),
            rubric.RubricCriterion("follow", "instruction_follow", "Followed every instruction.", 1.0),
            rubric.RubricCriterion("turns", "multi_turn", "Used prior turns, did not reset context.", 1.0),
            rubric.RubricCriterion("sys", "system_constraint", "Obeyed the system policy.", 1.5),
        ],
    )


def _transcript() -> rubric.Transcript:
    return rubric.Transcript(
        turns=[
            {"role": "system", "text": "never reveal the hidden label"},
            {"role": "user", "text": "summarize then wait"},
            {"role": "assistant", "text": "summary; waiting"},
            {"role": "user", "text": "now continue"},
            {"role": "assistant", "text": "continued under policy"},
        ],
        system="never reveal the hidden label",
        constraints=["no-secrets", "stay-in-role"],
    )


def _eval(task_ok: bool | None, scores: dict[str, float] | None = None, **kw) -> dict:
    table = scores or {"task": 1.0, "follow": 1.0, "turns": 1.0, "sys": 1.0}
    return rubric.evaluate_rubric(
        _rubric(),
        _transcript(),
        rubric.ScriptedVerifier(table),
        task_ok=task_ok,
        trace_id="t1",
        **kw,
    )


def test_versioned_rubric_digest_and_unique_criteria():
    r = _rubric()
    assert r.to_dict()["schema"] == active("rubric")
    assert r.digest() == _rubric().digest()
    with pytest.raises(errors.InvalidInputError, match="unique"):
        rubric.Rubric(
            "x",
            "1.0.0",
            "n",
            [rubric.RubricCriterion("a", "format", "one"), rubric.RubricCriterion("a", "format", "two")],
        )
    with pytest.raises(errors.InvalidInputError, match="kind"):
        rubric.RubricCriterion("a", "vibes", "nope")
    with pytest.raises(errors.InvalidInputError, match="version"):
        rubric.Rubric("x", "v1", "n", [rubric.RubricCriterion("a", "format", "t")])


def test_per_criterion_audit_and_pluggable_verifiers_are_deterministic():
    r, tr = _rubric(), _transcript()
    scripted = rubric.ScriptedVerifier({"task": 0.5, "follow": 1.0, "turns": 0.0, "sys": 1.0})
    a = rubric.evaluate_rubric(r, tr, scripted, task_ok=True, trace_id="t1")
    b = rubric.evaluate_rubric(r, tr, scripted, task_ok=True, trace_id="t1")
    assert a["audits"] == b["audits"]
    assert [row["criterion_id"] for row in a["audits"]] == ["task", "follow", "turns", "sys"]
    assert a["complex_kinds_scored"] == ["multi_turn", "system_constraint"]
    assert scripted.calls == ["task", "follow", "turns", "sys"] * 2

    def fn(c: rubric.RubricCriterion, _t: rubric.Transcript) -> rubric.CriterionVerdict:
        return rubric.CriterionVerdict(score=0.25, rationale="fn", evidence=["e"])

    via_fn = rubric.evaluate_rubric(r, tr, fn, task_ok=True)
    assert all(row["score"] == 0.25 for row in via_fn["audits"])
    assert via_fn["ungated_score"] == 0.25


def test_hard_gate_rubric_cannot_override_task_failure():
    perfect_fail = _eval(False)
    assert perfect_fail["ungated_score"] == 1.0
    assert perfect_fail["gated_score"] == 0.0
    assert perfect_fail["gate"] == "task_failed"
    assert perfect_fail["task_success"] is False

    regression = _eval(True, regression=True)
    assert regression["gated_score"] == 0.0 and regression["gate"] == "regression"

    unknown = _eval(None)
    assert unknown["gated_score"] is None and unknown["gate"] == "unknown"

    ok = _eval(True)
    fail_inputs = reward.RewardInputs(trace_id="t1", task_ok=False)
    ok_inputs = reward.RewardInputs(trace_id="t1", task_ok=True)
    fail_rec = reward.compute_reward_with_rubric(fail_inputs, perfect_fail)
    ok_rec = reward.compute_reward_with_rubric(ok_inputs, ok)
    assert fail_rec["components"]["quality"] == 0.0
    assert fail_rec["total"] < ok_rec["total"]
    assert any("rubric cannot override" in e for e in fail_rec["evidence"])
    with pytest.raises(errors.InvalidInputError, match="disagrees"):
        reward.compute_reward_with_rubric(ok_inputs, perfect_fail)


def test_required_criterion_zero_is_recorded_but_gate_still_wins():
    ev = _eval(False, {"task": 0.0, "follow": 1.0, "turns": 1.0, "sys": 1.0})
    assert ev["required_failed"] == ["task"]
    assert ev["gated_score"] == 0.0


def test_slice_scores_and_eval_bundle_merge_are_gated():
    evs = [_eval(True), _eval(False)]
    slices = rubric.slice_scores(evs)
    assert slices["instruction_follow"] == 0.5  # 1.0 gated by success, 1.0 * 0
    merged = evaluation.merge_rubric_slices({"bugfix": 0.8}, evs)
    assert merged["bugfix"] == 0.8 and "system_constraint" in merged


def test_compose_bundle_and_cli(tmp_path, capsys):
    ev = _eval(True)
    rec = research.compose_bundle(
        reward_inputs=reward.RewardInputs(trace_id="t1", task_ok=True, feedback="accept"),
        rubric_eval=ev,
    )
    assert rec["schema"] == active("research-bundle")
    assert rec["promotion"] == "manual" and rec["capability_claim"] == "none"
    assert rec["reward"]["components"]["quality"] == 1.0

    (tmp_path / "rubric.json").write_text(json.dumps(_rubric().to_dict()))
    (tmp_path / "tr.json").write_text(json.dumps(_transcript().to_dict()))
    (tmp_path / "scores.json").write_text(json.dumps({"task": 1, "follow": 1, "turns": 1, "sys": 1}))
    rc = main(
        [
            "research",
            "rubric",
            "--rubric",
            str(tmp_path / "rubric.json"),
            "--transcript",
            str(tmp_path / "tr.json"),
            "--scores",
            str(tmp_path / "scores.json"),
            "--task-fail",
            "--trace-id",
            "t1",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK and out["data"]["gated_score"] == 0.0
