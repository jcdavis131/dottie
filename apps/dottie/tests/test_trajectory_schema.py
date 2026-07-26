# Solo personal project, no connection to employer, built with public/free-tier only
"""Tests for the unified trajectory schema (dottie/trajectory_schema.py).

Offline + deterministic. Fixtures mirror the REAL persisted shapes: a CodeAct
engine trace (engine.py:242) and a research validation history (validate.py:1063).
"""

from __future__ import annotations

from dottie import trajectory_schema as ts

# ---- fixtures: the real shapes each rollout persists -------------------------

_CODEACT_REC = {
    "schema_version": "1.0.0",
    "task_id": "reverse-string",
    "ts": 1730000000.0,
    "backend": "ollama:qwen3:8b",
    "prompt": "Write reverse(s).",
    "final": "def reverse(s): return s[::-1]",
    "terminated": True,
    "reached_final": True,
    "n_steps": 2,
    "steps": [
        {
            "code": "x = 1",
            "ok": True,
            "stdout": "",
            "value": None,
            "error": None,
            "wall_ms": 5,
            "tool_calls": [],
        },
        {
            "code": "print(reverse('ab'))",
            "ok": True,
            "stdout": "ba",
            "value": "ba",
            "error": None,
            "wall_ms": 7,
            "tool_calls": [{"tool": "python", "args": {}}],
        },
    ],
    "reward_components": {"r_task": 1.0, "r_format": 1.0},
    "verified_task": {"kind": "unit", "passed": True},
}

_VALIDATION_EXP = {
    "experiment_id": "abc123",
    "history": [
        {
            "attempt": 0,
            "ok": False,
            "level": "dry_run",
            "status": "fail",
            "detail": "einsum: output subscript n does not appear",
            "obligations": [
                {
                    "obligation_id": "shape_conservation",
                    "property": "shape",
                    "stage": "dry_run",
                    "status": "failed",
                }
            ],
        },
        {
            "attempt": 1,
            "ok": True,
            "level": "residual_stream",
            "status": "ok",
            "detail": "",
            "obligations": [
                {
                    "obligation_id": "gradient_flow",
                    "property": "grad",
                    "stage": "residual_stream",
                    "status": "discharged",
                }
            ],
        },
    ],
}


# ---- serialization round-trips ----------------------------------------------


def test_roundtrip_preserves_everything():
    t = ts.from_codeact_trace(_CODEACT_REC)
    back = ts.from_dict(ts.to_dict(t))
    assert back == t
    assert back.schema_version == ts.SCHEMA_VERSION


def test_from_dict_ignores_unknown_keys():
    d = ts.to_dict(ts.from_codeact_trace(_CODEACT_REC))
    d["a_future_field"] = "ignored"
    d["steps"][0]["also_future"] = 1
    t = ts.from_dict(d)  # must not raise
    assert t.source == "codeact"


# ---- adapter: CodeAct --------------------------------------------------------


def test_from_codeact_maps_action_toolcalls_feedback():
    t = ts.from_codeact_trace(_CODEACT_REC)
    assert t.source == "codeact" and t.task_ref == {"task_id": "reverse-string"}
    assert len(t.steps) == 2
    s1 = t.steps[1]
    assert s1.action == {"kind": "code", "payload": "print(reverse('ab'))"}
    assert s1.tool_calls == [{"tool": "python", "args": {}}]  # verbatim
    assert s1.feedback["stdout"] == "ba" and s1.feedback["ok"] is True
    assert t.outcome["status"] == "reached_final"
    assert t.outcome["reward"] == {
        "r_task": 1.0,
        "r_format": 1.0,
    }  # real components, not invented


def test_from_codeact_state_accumulates_transcript():
    t = ts.from_codeact_trace(_CODEACT_REC)
    assert t.steps[0].state == "Write reverse(s)."  # prompt only
    assert "x = 1" in t.steps[1].state  # prior code folded in


def test_from_codeact_terminated_not_final():
    rec = dict(_CODEACT_REC, reached_final=False, terminated=True)
    assert ts.from_codeact_trace(rec).outcome["status"] == "terminated"


# ---- adapter: validation -----------------------------------------------------


def test_from_validation_history_maps_obligations():
    t = ts.from_validation_history(_VALIDATION_EXP)
    assert t.source == "validation" and t.task_ref == {"experiment_id": "abc123"}
    assert t.steps[0].action == {"kind": "submit", "attempt": 0}
    assert t.steps[1].action == {"kind": "rewrite", "attempt": 1}  # corrector pass
    assert t.steps[0].feedback["obligations"][0]["status"] == "failed"
    assert t.steps[1].feedback["obligations"][0]["status"] == "discharged"
    assert t.outcome["status"] == "ok"
    assert t.outcome["reward"] is None  # a gate, not a graded reward


def test_from_validation_accepts_nested_validation_dict():
    exp = {"experiment_id": "x", "validation": {"history": _VALIDATION_EXP["history"]}}
    t = ts.from_validation_history(exp)
    assert len(t.steps) == 2


# ---- adapter: repair ---------------------------------------------------------

_REPAIR_ROWS = [
    {
        "experiment_id": "e9",
        "module_name": "MyBlock",
        "failure_seq": 1,
        "attempt": 0,
        "level": "dry_run",
        "status": "fail",
        "failure_detail": "shape mismatch",
        "repair_hint": "SHAPE ALGEBRA: ...",
        "corrected_code": "class MyBlock: ...",
        "validated_detail": "",
        "corrected_code_role": "final_validated_code",
    },
    {
        "experiment_id": "e9",
        "module_name": "MyBlock",
        "failure_seq": 2,
        "attempt": 1,
        "level": "dry_run",
        "status": "fail",
        "failure_detail": "still wrong",
        "repair_hint": "GATHER/TOPK: ...",
        "corrected_code": "class MyBlock: ...",
        "validated_detail": "",
        "corrected_code_role": "final_validated_code",
    },
]


def test_from_repair_rows_failures_then_terminal_fix():
    t = ts.from_repair_rows(_REPAIR_ROWS)
    assert t.source == "repair" and t.task_ref["experiment_id"] == "e9"
    assert len(t.steps) == 3  # 2 failures + 1 terminal correction
    assert t.steps[0].feedback["ok"] is False and t.steps[0].feedback["repair_hint"]
    assert t.steps[-1].state == "corrected"
    assert t.steps[-1].action == {"kind": "rewrite", "payload": "class MyBlock: ..."}
    assert t.steps[-1].feedback["ok"] is True
    assert t.outcome["status"] == "repaired" and t.outcome["reward"] is None


def test_from_repair_rows_sorts_by_failure_seq():
    t = ts.from_repair_rows(list(reversed(_REPAIR_ROWS)))  # unordered input
    assert t.steps[0].feedback["detail"] == "shape mismatch"  # seq 1 first


def test_from_repair_rows_empty_is_honest():
    t = ts.from_repair_rows([])
    assert t.steps == [] and t.outcome["status"] == "empty"


# ---- adapter: agent-eval -----------------------------------------------------

_AGENT_EVAL_RESULT = {
    "task_id": "grounded-todays-date",
    "category": "grounding",
    "model": "ava:nano",
    "prompt": "What is today's date? Use the clock tool.",
    "status": "completed",
    "success": False,
    "check_detail": "pattern not matched",
    "trajectory_ok": False,
    "events": [
        {"type": "thought", "text": "I should call the clock"},  # not a step
        {
            "type": "step",
            "tool": "get_clock",
            "args": {},
            "result": "2026-07-24",
            "ok": True,
        },
        {"type": "step", "tool": "emit", "args": {"text": "the 24th"}, "ok": True},
    ],
}


def test_from_agent_eval_uses_step_contract_and_passes_feedback_through():
    t = ts.from_agent_eval_events(_AGENT_EVAL_RESULT)
    assert t.source == "agent_eval" and t.task_ref["task_id"] == "grounded-todays-date"
    assert len(t.steps) == 2  # non-step 'thought' event skipped
    s0 = t.steps[0]
    assert s0.action == {"kind": "tool", "tool": "get_clock"}
    assert s0.tool_calls == [{"tool": "get_clock", "args": {}}]
    assert s0.feedback == {
        "result": "2026-07-24",
        "ok": True,
    }  # honest passthrough, no guessing
    assert t.outcome["success"] is False and t.outcome["trajectory_ok"] is False
    assert t.outcome["reward"] is None


def test_from_agent_eval_no_events_is_honest():
    t = ts.from_agent_eval_events({"task_id": "x"})
    assert t.steps == [] and t.outcome["status"] is None


# ---- learning consumer: source-agnostic -------------------------------------


def test_to_sft_records_attaches_outcome_to_last_step_only():
    # source-agnostic: one consumer reads all four rollout sources identically
    trajectories = [
        ts.from_codeact_trace(_CODEACT_REC),
        ts.from_validation_history(_VALIDATION_EXP),
        ts.from_repair_rows(_REPAIR_ROWS),
        ts.from_agent_eval_events(_AGENT_EVAL_RESULT),
    ]
    for t in trajectories:
        recs = ts.to_sft_records(t)
        assert len(recs) == len(t.steps) >= 2
        assert recs[0]["outcome"] is None
        assert recs[-1]["outcome"] is not None
        # every record carries the same source-agnostic keys regardless of source
        assert set(recs[0]) == {
            "trajectory_id",
            "source",
            "task_ref",
            "step",
            "state",
            "action",
            "tool_calls",
            "feedback",
            "outcome",
            "schema_version",
        }


def test_empty_trajectory_yields_no_records():
    empty = ts.Trajectory(
        trajectory_id="e",
        source="validation",
        task_ref={},
        steps=[],
        outcome={"status": "failed"},
    )
    assert ts.to_sft_records(empty) == []


def test_missing_history_is_empty_not_crash():
    t = ts.from_validation_history({"experiment_id": "none"})
    assert t.steps == [] and t.outcome["status"] == "failed"
