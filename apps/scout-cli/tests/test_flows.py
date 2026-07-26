"""Flows — openswap #27 (Zapier/Make -> a bounded local JSON workflow runner).

Pure-logic core tests (paths, templates, conditions, transforms, graph shape,
validation), the bound matrix that is the whole point of the adapter (hard step
cap, visit cap, depth cap, default-deny action allowlist — each asserted to
REFUSE and to report by node rather than skip), the honesty invariants (a step
has either an output or an error; nothing is invented for a missing field), the
sqlite run ledger, capability detection, and the real CLI in a subprocess.

Offline and deterministic by construction: effectors are injected fakes (the
core touches no file and opens no socket), `now`/`last_run` are explicit
everywhere, and the two CLI tests that write real files write them into tmp_path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import flows, openswap

ROOT = Path(__file__).resolve().parents[1]


# ---- fixtures ---------------------------------------------------------------


def _linear(n: int = 3, *, trigger: dict | None = None) -> dict:
    """A straight chain of n transform nodes: n1 -> n2 -> ... -> nn."""
    nodes = {}
    for i in range(1, n + 1):
        nodes[f"n{i}"] = {
            "kind": "transform",
            "ops": [{"op": "set", "path": f"step{i}", "value": i}],
        }
        if i < n:
            nodes[f"n{i}"]["next"] = f"n{i + 1}"
    return {
        "name": f"linear{n}",
        "trigger": trigger or {"type": "manual"},
        "start": "n1",
        "nodes": nodes,
    }


def _with_action(uses: str = "emit", **node: object) -> dict:
    return {
        "name": "one-action",
        "trigger": {"type": "manual"},
        "start": "act",
        "nodes": {"act": {"kind": "action", "uses": uses, "with": {}, **node}},
    }


def _recorder() -> tuple[dict, list]:
    """An injected fake effector plus the list of (params, payload) it saw."""
    seen: list = []

    def _emit(params: dict, data: dict) -> dict:
        seen.append((params, data))
        return {"ran": len(seen)}

    return {"emit": _emit}, seen


def _mem():
    return flows.open_store(":memory:")


# ---- field paths ------------------------------------------------------------


def test_get_path_reads_nested_dicts_and_list_indexes():
    data = {"a": {"b": [10, 20, {"c": "deep"}]}, "n": 0}
    assert flows.get_path(data, "a.b.0") == 10
    assert flows.get_path(data, "a.b.-1.c") == "deep"
    assert flows.get_path(data, "n") == 0
    assert flows.get_path(data, "a.b.9", "fallback") == "fallback"
    assert flows.get_path(data, "a.b.x", "fallback") == "fallback"  # non-int index
    assert flows.get_path(data, "n.deeper", "fallback") == "fallback"  # walks a scalar
    for bad in ("", "   ", None, 7, "..."):
        with pytest.raises(ValueError):
            flows.split_path(bad)


def test_absent_is_distinguished_from_present_none():
    data = {"here": None}
    assert flows.has_path(data, "here") is True  # present, and None
    assert flows.has_path(data, "gone") is False
    assert flows.require_field(data, "here") is None
    with pytest.raises(ValueError, match="no field"):
        flows.require_field(data, "gone")  # never invented


def test_set_path_returns_a_copy_and_builds_intermediates():
    data = {"keep": 1}
    out = flows.set_path(data, "a.b.c", [1, 2])
    assert out == {"keep": 1, "a": {"b": {"c": [1, 2]}}}
    assert data == {"keep": 1}  # the input is never mutated
    out["a"]["b"]["c"].append(3)
    assert flows.get_path(out, "a.b.c") == [1, 2, 3]
    # a non-dict intermediate is replaced rather than crashed into
    assert flows.set_path({"a": 5}, "a.b", 1) == {"a": {"b": 1}}
    with pytest.raises(ValueError):
        flows.set_path([], "a", 1)


def test_remove_path_reports_whether_anything_was_removed():
    data = {"a": {"b": 1}, "c": 2}
    out, removed = flows.remove_path(data, "a.b")
    assert removed is True and out == {"a": {}, "c": 2}
    out2, removed2 = flows.remove_path(data, "a.zz")
    assert removed2 is False and out2 == data  # absence is reported, not faked
    out3, removed3 = flows.remove_path(data, "c.deep.deeper")
    assert removed3 is False and out3 == data


def test_pick_fields_refuses_missing_and_colliding_fields():
    data = {"a": {"id": 1}, "b": {"id": 2}, "line": "x"}
    assert flows.pick_fields(data, ["a.id", "line"]) == {"id": 1, "line": "x"}
    with pytest.raises(ValueError, match="collides"):
        flows.pick_fields(data, ["a.id", "b.id"])
    with pytest.raises(ValueError, match="no field"):
        flows.pick_fields(data, ["nope"])
    with pytest.raises(ValueError):
        flows.pick_fields(data, [])
    assert flows.select_fields(data) == data  # None = the whole payload
    assert flows.select_fields(data, ["line"]) == {"line": "x"}


def test_as_text_is_deterministic_for_containers():
    assert flows.as_text("raw") == "raw"
    assert flows.as_text({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'  # sorted keys
    assert flows.as_text([1, "x"]) == '[1, "x"]'
    assert flows.as_text(3) == "3"


# ---- templates --------------------------------------------------------------


def test_render_template_substitutes_and_refuses_to_invent():
    data = {"n": 2, "who": "certs", "d": {"k": "v"}}
    assert flows.render_template("{n} bad {who}", data) == "2 bad certs"
    assert flows.render_template("{ n }", data) == "2"  # whitespace tolerated
    assert flows.render_template("{d}", data) == '{"k": "v"}'
    assert flows.render_template("no refs", data) == "no refs"
    with pytest.raises(ValueError, match="no field"):
        flows.render_template("{missing}", data)  # never renders as empty
    with pytest.raises(ValueError, match="empty"):
        flows.render_template("{}", data)
    with pytest.raises(ValueError, match="must be a string"):
        flows.render_template(None, data)


# ---- conditions -------------------------------------------------------------


def test_evaluate_equality_and_membership():
    data = {"sev": "error", "hosts": ["a.com"], "msg": "cert expired", "n": 3}
    assert flows.evaluate({"path": "sev", "op": "eq", "value": "error"}, data) is True
    assert flows.evaluate({"path": "sev", "op": "ne", "value": "error"}, data) is False
    assert (
        flows.evaluate({"path": "msg", "op": "contains", "value": "expired"}, data)
        is True
    )
    assert (
        flows.evaluate({"path": "msg", "op": "contains", "value": "fine"}, data)
        is False
    )
    assert (
        flows.evaluate({"path": "hosts", "op": "contains", "value": "a.com"}, data)
        is True
    )
    assert (
        flows.evaluate({"path": "sev", "op": "in", "value": ["error", "warning"]}, data)
        is True
    )
    assert flows.evaluate({"path": "sev", "op": "in", "value": ["info"]}, data) is False
    assert flows.evaluate({"path": "n", "op": "truthy"}, data) is True
    assert flows.evaluate({"path": "n", "op": "contains", "value": 1}, data) is False


def test_evaluate_ordered_ops_are_numeric_only():
    data = {"n": 5, "flag": True, "s": "7"}
    assert flows.evaluate({"path": "n", "op": "gt", "value": 4}, data) is True
    assert flows.evaluate({"path": "n", "op": "gt", "value": 5}, data) is False
    assert flows.evaluate({"path": "n", "op": "ge", "value": 5}, data) is True
    assert flows.evaluate({"path": "n", "op": "lt", "value": 5}, data) is False
    assert flows.evaluate({"path": "n", "op": "le", "value": 5}, data) is True
    # a bool is not a magnitude, and a numeric-looking string is not a number
    for path in ("flag", "s"):
        with pytest.raises(ValueError, match="needs two numbers"):
            flows.evaluate({"path": path, "op": "gt", "value": 1}, data)


def test_evaluate_absent_field_is_false_never_a_crash():
    data = {"present": 1}
    assert flows.evaluate({"path": "gone", "op": "eq", "value": None}, data) is False
    assert flows.evaluate({"path": "gone", "op": "gt", "value": 0}, data) is False
    assert flows.evaluate({"path": "gone", "op": "truthy"}, data) is False
    assert flows.evaluate({"path": "gone", "op": "exists"}, data) is False
    assert flows.evaluate({"path": "gone", "op": "missing"}, data) is True
    assert flows.evaluate({"path": "present", "op": "exists"}, data) is True
    assert flows.evaluate({"path": "present", "op": "missing"}, data) is False


def test_evaluate_bad_condition_raises_instead_of_defaulting_false():
    with pytest.raises(ValueError, match="unknown condition op"):
        flows.evaluate({"path": "a", "op": "regex", "value": "x"}, {"a": 1})
    with pytest.raises(ValueError, match="needs a `path`"):
        flows.evaluate({"op": "eq", "value": 1}, {"a": 1})
    with pytest.raises(ValueError, match="must be an object"):
        flows.evaluate("a == 1", {"a": 1})


# ---- transforms -------------------------------------------------------------


def test_apply_transform_op_matrix():
    data = {"hosts": ["a", "b"], "sev": "error", "drop": 1}
    out, notes = flows.apply_transform(
        [
            {"op": "count", "from": "hosts", "path": "n"},
            {"op": "copy", "from": "sev", "path": "meta.sev"},
            {"op": "set", "path": "src", "value": "certmon"},
            {"op": "template", "path": "line", "text": "{n} at {sev}"},
            {"op": "remove", "path": "drop"},
            {"op": "pick", "fields": ["line", "n", "meta.sev"], "path": "digest"},
        ],
        data,
    )
    assert out["n"] == 2 and out["meta"] == {"sev": "error"} and out["src"] == "certmon"
    assert out["line"] == "2 at error"
    assert "drop" not in out
    assert out["digest"] == {"line": "2 at error", "n": 2, "sev": "error"}
    assert len(notes) == 6 and notes[0] == "count hosts = 2 -> n"
    assert data == {"hosts": ["a", "b"], "sev": "error", "drop": 1}  # input untouched
    # pick with no `path` narrows the payload to exactly the picked fields
    narrowed, _ = flows.apply_transform([{"op": "pick", "fields": ["sev"]}], data)
    assert narrowed == {"sev": "error"}


def test_apply_transform_default_only_fills_an_absent_field():
    out, notes = flows.apply_transform(
        [{"op": "default", "path": "sev", "value": "info"}], {"sev": "error"}
    )
    assert out["sev"] == "error" and "already set" in notes[0]
    out2, notes2 = flows.apply_transform(
        [{"op": "default", "path": "sev", "value": "info"}], {}
    )
    assert out2["sev"] == "info" and "applied" in notes2[0]
    # present-but-None counts as set — default must not overwrite a real null
    out3, _ = flows.apply_transform(
        [{"op": "default", "path": "sev", "value": "info"}], {"sev": None}
    )
    assert out3["sev"] is None


def test_apply_transform_refuses_bad_specs_and_missing_sources():
    with pytest.raises(ValueError, match="non-empty `ops`"):
        flows.apply_transform([], {})
    with pytest.raises(ValueError, match="unknown transform op"):
        flows.apply_transform([{"op": "eval", "path": "x"}], {})
    with pytest.raises(ValueError, match="must be an object"):
        flows.apply_transform(["set x 1"], {})
    with pytest.raises(ValueError, match="no field"):
        flows.apply_transform([{"op": "copy", "from": "gone", "path": "x"}], {})
    with pytest.raises(ValueError, match="no field"):
        flows.apply_transform([{"op": "count", "from": "gone", "path": "x"}], {})
    with pytest.raises(ValueError, match="count needs"):
        flows.apply_transform([{"op": "count", "from": "n", "path": "x"}], {"n": 5})
    assert (
        flows.apply_transform(
            [{"op": "count", "from": "s", "path": "x"}], {"s": "abc"}
        )[0]["x"]
        == 3
    )


def test_check_op_shape_catches_typos_without_a_payload():
    assert flows.check_op_shape({"op": "set", "path": "a", "value": 1}) is None
    assert "unknown transform op" in flows.check_op_shape({"op": "sett", "path": "a"})
    assert "needs `from`" in flows.check_op_shape({"op": "copy", "path": "a"})
    assert "needs `path`" in flows.check_op_shape({"op": "count", "from": "a"})
    assert "`text` must be a string" in flows.check_op_shape(
        {"op": "template", "path": "a", "text": 5}
    )
    assert "non-empty list" in flows.check_op_shape({"op": "pick", "fields": []})
    assert "bad `path`" in flows.check_op_shape({"op": "set", "path": "", "value": 1})
    assert "must be an object" in flows.check_op_shape("set a 1")
    # pick's `path` is optional (it narrows the root when omitted)
    assert flows.check_op_shape({"op": "pick", "fields": ["a"]}) is None


# ---- graph shape ------------------------------------------------------------


def test_successors_and_walk_order():
    flow = _linear(3)
    assert flows.successors(flow["nodes"]["n1"]) == ["n2"]
    assert flows.successors(flow["nodes"]["n3"]) == []
    assert flows.successors("not a node") == []
    branch = {"kind": "branch", "when": {}, "then": "y", "else": "n"}
    assert flows.successors(branch) == ["y", "n"]
    assert flows.walk_order(flow) == ["n1", "n2", "n3"]
    flow["nodes"]["orphan"] = {
        "kind": "transform",
        "ops": [{"op": "set", "path": "o", "value": 1}],
    }
    assert "orphan" not in flows.walk_order(flow)  # reachability, not enumeration
    assert flows.walk_order({"nodes": {}, "start": "nope"}) == []


def test_has_cycle_finds_loops_and_stays_quiet_on_dags():
    assert flows.has_cycle(_linear(4)) == []
    looped = _linear(3)
    looped["nodes"]["n3"]["next"] = "n1"
    cycle = flows.has_cycle(looped)
    assert cycle and cycle[0] == cycle[-1]  # a closed path
    selfloop = _linear(1)
    selfloop["nodes"]["n1"]["next"] = "n1"
    assert flows.has_cycle(selfloop) == ["n1", "n1"]
    # a cycle only reachable through a branch is still found
    br = _linear(2)
    br["nodes"]["n1"] = {
        "kind": "branch",
        "when": {"path": "x", "op": "exists"},
        "then": "n2",
        "else": "n2",
    }
    br["nodes"]["n2"]["next"] = "n1"
    assert flows.has_cycle(br) != []


def test_validate_accepts_the_shipped_example_flow():
    assert flows.validate(flows.EXAMPLE_FLOW) == []
    assert flows.requested_actions(flows.EXAMPLE_FLOW) == ["append_jsonl"]
    assert flows.subflow_names(flows.EXAMPLE_FLOW) == []
    assert flows.walk_order(flows.EXAMPLE_FLOW) == ["summarize", "any", "record"]


def _codes(flow, **kw):
    return {p["code"] for p in flows.validate(flow, **kw)}


def test_validate_catches_every_structural_defect():
    assert "bad-flow" in _codes("not a flow")
    assert {"no-name", "bad-trigger", "no-nodes"} <= _codes({})
    bad_start = _linear(2)
    bad_start["start"] = "nope"
    assert "bad-start" in _codes(bad_start)
    dangling = _linear(2)
    dangling["nodes"]["n2"]["next"] = "ghost"
    assert "dangling-edge" in _codes(dangling)
    weird = _linear(1)
    weird["nodes"]["n1"] = {"kind": "webhook"}
    assert "unknown-kind" in _codes(weird)
    listy = _linear(1)
    listy["nodes"]["n1"] = ["not", "an", "object"]
    assert "bad-node" in _codes(listy)
    bad_trigger = _linear(1)
    bad_trigger["trigger"] = {"type": "carrier-pigeon"}
    assert "bad-trigger" in _codes(bad_trigger)
    bad_op = _linear(1)
    bad_op["nodes"]["n1"]["ops"] = [{"op": "exec", "path": "x"}]
    assert "bad-transform" in _codes(bad_op)
    no_ops = _linear(1)
    no_ops["nodes"]["n1"]["ops"] = []
    assert "bad-transform" in _codes(no_ops)
    bad_cond = _linear(1)
    bad_cond["nodes"]["n1"] = {"kind": "filter", "when": {"op": "nope"}}
    assert "bad-condition" in _codes(bad_cond)
    no_then = _linear(1)
    no_then["nodes"]["n1"] = {"kind": "branch", "when": {"path": "a", "op": "exists"}}
    assert "bad-branch" in _codes(no_then)
    looped = _linear(2)
    looped["nodes"]["n2"]["next"] = "n1"
    assert "cycle" in _codes(looped)


def test_validate_checks_action_names_and_parameters():
    assert "unknown-action" in _codes(_with_action("post_webhook"))
    assert "missing-param" in _codes(_with_action("write_file"))
    assert "unknown-param" in _codes(_with_action("emit", **{"with": {"fildes": "x"}}))
    assert "bad-params" in _codes(_with_action("emit", **{"with": "everything"}))
    good = _with_action("write_file", **{"with": {"file": "o.txt", "from": "line"}})
    assert flows.validate(good) == []


def test_validate_reports_unreachable_and_unresolved_subflows_as_warnings():
    flow = _linear(2)
    flow["nodes"]["ghost"] = {
        "kind": "transform",
        "ops": [{"op": "set", "path": "g", "value": 1}],
    }
    problems = flows.validate(flow)
    assert [p["code"] for p in problems] == ["unreachable"]
    assert problems[0]["severity"] == "warning" and problems[0]["node"] == "ghost"
    sub = {
        "name": "parent",
        "trigger": {"type": "manual"},
        "start": "s",
        "nodes": {"s": {"kind": "flow", "uses": "child"}},
    }
    assert _codes(sub) == {"subflow-unresolved"}
    assert flows.subflow_names(sub) == ["child"]
    assert flows.validate(sub, registry={"child": _linear(1)}) == []


def test_preflight_is_default_deny_and_names_what_to_allow():
    pre = flows.preflight(flows.EXAMPLE_FLOW, [])
    assert pre["requested"] == ["append_jsonl"] and pre["refused"] == ["append_jsonl"]
    assert pre["allowed"] == [] and pre["runnable"] is False
    allowed = flows.preflight(flows.EXAMPLE_FLOW, ["append_jsonl", "emit"])
    assert allowed["allowed"] == ["append_jsonl"] and allowed["runnable"] is True
    unknown = flows.preflight(_with_action("post_webhook"), ["post_webhook"])
    assert unknown["unknown"] == ["post_webhook"] and unknown["runnable"] is False


# ---- triggers ---------------------------------------------------------------


def test_trigger_manual_and_event_matching():
    manual = _linear(1)
    assert flows.trigger_check(manual, {}, now=1.0) == (True, "manual trigger")
    fired, why = flows.trigger_check(flows.EXAMPLE_FLOW, {"severity": "error"}, now=1.0)
    assert fired is True and "matched" in why
    fired2, why2 = flows.trigger_check(
        flows.EXAMPLE_FLOW, {"severity": "info"}, now=1.0
    )
    assert fired2 is False and "did not match" in why2
    open_event = {"name": "x", "trigger": {"type": "event"}, "start": "a", "nodes": {}}
    assert flows.trigger_check(open_event, {}, now=1.0)[0] is True
    broken = {"name": "x", "trigger": {"type": "event", "match": {"op": "??"}}}
    fired3, why3 = flows.trigger_check(broken, {}, now=1.0)
    assert fired3 is False and "unusable" in why3


def test_trigger_schedule_decides_from_a_recorded_last_run():
    sched = {"name": "s", "trigger": {"type": "schedule", "every_seconds": 60}}
    assert flows.trigger_check(sched, {}, now=1000.0, last_run=None)[0] is True
    due, why = flows.trigger_check(sched, {}, now=1000.0, last_run=940.0)
    assert due is True and "due" in why
    early, why2 = flows.trigger_check(sched, {}, now=1000.0, last_run=970.0)
    assert early is False and "30.0s" in why2  # the real remaining time, not a guess
    bad = {"name": "s", "trigger": {"type": "schedule", "every_seconds": 0}}
    assert flows.trigger_check(bad, {}, now=1.0) == (
        False,
        "schedule trigger needs a positive `every_seconds`, got 0",
    )
    assert (
        flows.trigger_check({"trigger": {"type": "carrier"}}, {}, now=1.0)[0] is False
    )


# ---- the bounded runner -----------------------------------------------------


def test_run_happy_path_records_every_step_and_action():
    eff, seen = _recorder()
    flow = _linear(2)
    flow["nodes"]["n2"]["next"] = "act"
    flow["nodes"]["act"] = {
        "kind": "action",
        "uses": "emit",
        "with": {"fields": ["step1"]},
        "into": "res",
    }
    run = flows.run_flow(flow, {"in": 1}, allow=["emit"], effectors=eff, now=42.0)
    assert run["outcome"] == "ok" and run["refusals"] == []
    assert [s["node"] for s in run["steps"]] == ["n1", "n2", "act"]
    assert [s["seq"] for s in run["steps"]] == [1, 2, 3]
    assert run["steps_used"] == 3 and run["step_cap"] == flows.DEFAULT_MAX_STEPS
    assert run["actions_run"] == ["emit"] and run["ts"] == 42.0
    assert run["data"]["step1"] == 1 and run["data"]["res"] == {"ran": 1}
    assert seen[0][0] == {"fields": ["step1"]}  # params reached the effector


def test_every_step_records_either_an_output_or_an_error():
    with pytest.raises(ValueError):
        flows._step(
            seq=1, node="a", kind="action", outcome="ok", output={"a": 1}, error="boom"
        )
    with pytest.raises(ValueError):
        flows._step(seq=1, node="a", kind="action", outcome="ok")
    eff, _ = _recorder()
    for run in (
        flows.run_flow(_with_action(), {}, allow=["emit"], effectors=eff, now=1.0),
        flows.run_flow(_with_action(), {}, effectors=eff, now=1.0),  # refused
        flows.run_flow(_with_action("write_file"), {}, now=1.0),  # invalid
    ):
        for step in run["steps"]:
            assert (step["output"] is None) != (step["error"] is None)


def test_run_refuses_an_action_that_is_not_allowlisted():
    eff, seen = _recorder()
    run = flows.run_flow(_with_action(), {"x": 1}, allow=[], effectors=eff, now=1.0)
    assert run["outcome"] == "refused" and seen == []  # the effector never ran
    assert [p["code"] for p in run["refusals"]] == ["action-not-allowlisted"]
    assert run["refusals"][0]["node"] == "act"
    assert "--allow emit" in run["refusals"][0]["message"]
    assert run["steps"][-1]["outcome"] == "refused" and run["steps"][-1]["error"]
    assert run["actions_run"] == []
    # allowlisting a DIFFERENT action does not open this one
    other = flows.run_flow(
        _with_action(), {}, allow=["write_file"], effectors=eff, now=1.0
    )
    assert other["outcome"] == "refused" and seen == []


def test_run_refusal_stops_the_graph_instead_of_skipping_the_node():
    eff, _ = _recorder()
    flow = _with_action()
    flow["nodes"]["act"]["next"] = "after"
    flow["nodes"]["after"] = {
        "kind": "transform",
        "ops": [{"op": "set", "path": "after", "value": 1}],
    }
    run = flows.run_flow(flow, {}, allow=[], effectors=eff, now=1.0)
    assert run["outcome"] == "refused"
    assert [s["node"] for s in run["steps"]] == ["act"]  # downstream never ran
    assert "after" not in run["data"]


def test_run_refuses_an_unknown_action_and_a_missing_effector():
    # not in the catalog at all -> refused by validation before any step
    unknown = flows.run_flow(
        _with_action("post_webhook"), {}, allow=["post_webhook"], now=1.0
    )
    assert unknown["outcome"] == "refused" and unknown["steps"] == []
    assert {"invalid-flow"} <= {p["code"] for p in unknown["refusals"]}
    assert any(p["code"] == "unknown-action" for p in unknown["problems"])
    # allowlisted, catalogued, but this surface injected no effector for it
    none_supplied = flows.run_flow(
        _with_action(), {}, allow=["emit"], effectors={}, now=1.0
    )
    assert [p["code"] for p in none_supplied["refusals"]] == ["effector-missing"]
    assert none_supplied["outcome"] == "refused"


def test_run_action_failure_is_failed_not_refused_and_keeps_the_reason():
    def _boom(params: dict, data: dict) -> dict:
        raise OSError("disk on fire")

    run = flows.run_flow(
        _with_action(), {}, allow=["emit"], effectors={"emit": _boom}, now=1.0
    )
    assert run["outcome"] == "failed" and run["refusals"] == []
    assert "OSError: disk on fire" in run["steps"][-1]["error"]
    assert [p["code"] for p in run["problems"]] == ["action-failed"]


def test_run_action_returning_nothing_is_an_error_not_an_empty_success():
    run = flows.run_flow(
        _with_action(),
        {},
        allow=["emit"],
        effectors={"emit": lambda p, d: None},
        now=1.0,
    )
    assert run["outcome"] == "failed"
    assert "returned no result" in run["steps"][-1]["error"]
    assert run["steps"][-1]["output"] is None


def test_step_cap_is_hard_and_reported_at_the_node_it_stopped_on():
    fits = flows.run_flow(_linear(3), {}, max_steps=3, now=1.0)
    assert fits["outcome"] == "ok" and fits["steps_used"] == 3
    capped = flows.run_flow(_linear(3), {}, max_steps=2, now=1.0)
    assert capped["outcome"] == "refused" and capped["steps_used"] == 2
    assert [p["code"] for p in capped["refusals"]] == ["step-cap"]
    assert capped["refusals"][0]["node"] == "n3"  # the node it refused to run
    assert "step cap 2" in capped["reason"]
    assert capped["data"] == {"step1": 1, "step2": 2}  # n3's effect never landed
    zero = flows.run_flow(_linear(1), {}, max_steps=0, now=1.0)
    assert zero["outcome"] == "refused" and zero["steps"] == []


def test_visit_cap_terminates_a_cycle_that_dodged_validation(monkeypatch):
    looped = _linear(2)
    looped["nodes"]["n2"]["next"] = "n1"
    assert "cycle" in _codes(looped)  # normally refused up front
    monkeypatch.setattr(flows, "has_cycle", lambda flow: [])  # smuggle it past validate
    run = flows.run_flow(looped, {}, max_steps=99, now=1.0)
    assert run["outcome"] == "refused"
    assert [p["code"] for p in run["refusals"]] == ["visit-cap"]
    assert run["steps_used"] == 2  # each node once, then refused
    twice = flows.run_flow(looped, {}, max_steps=99, max_visits=2, now=1.0)
    assert twice["outcome"] == "refused" and twice["steps_used"] == 4
    assert [p["code"] for p in twice["refusals"]] == ["visit-cap"]


def test_filter_that_does_not_pass_ends_the_run_as_filtered():
    flow = {
        "name": "gated",
        "trigger": {"type": "manual"},
        "start": "gate",
        "nodes": {
            "gate": {
                "kind": "filter",
                "when": {"path": "n", "op": "gt", "value": 0},
                "next": "act",
            },
            "act": {"kind": "action", "uses": "emit", "with": {}},
        },
    }
    eff, seen = _recorder()
    run = flows.run_flow(flow, {"n": 0}, allow=["emit"], effectors=eff, now=1.0)
    assert run["outcome"] == "filtered" and seen == []
    assert run["steps"][-1]["outcome"] == "filtered"
    assert run["steps"][-1]["output"] == {"passed": False, "next": "act"}
    assert run["refusals"] == [] and "did not pass" in run["reason"]
    passed = flows.run_flow(flow, {"n": 1}, allow=["emit"], effectors=eff, now=1.0)
    assert passed["outcome"] == "ok" and len(seen) == 1


def test_branch_takes_then_or_else_and_records_which():
    flow = {
        "name": "fork",
        "trigger": {"type": "manual"},
        "start": "fork",
        "nodes": {
            "fork": {
                "kind": "branch",
                "when": {"path": "sev", "op": "eq", "value": "error"},
                "then": "hot",
                "else": "cold",
            },
            "hot": {
                "kind": "transform",
                "ops": [{"op": "set", "path": "took", "value": "hot"}],
            },
            "cold": {
                "kind": "transform",
                "ops": [{"op": "set", "path": "took", "value": "cold"}],
            },
        },
    }
    hot = flows.run_flow(flow, {"sev": "error"}, now=1.0)
    assert hot["data"]["took"] == "hot" and hot["outcome"] == "ok"
    assert hot["steps"][0]["output"] == {"passed": True, "next": "hot"}
    cold = flows.run_flow(flow, {"sev": "info"}, now=1.0)
    assert cold["data"]["took"] == "cold"
    assert [s["node"] for s in cold["steps"]] == ["fork", "cold"]
    # a branch with no `else` simply ends — recorded, not refused
    del flow["nodes"]["fork"]["else"]
    ended = flows.run_flow(flow, {"sev": "info"}, now=1.0)
    assert ended["outcome"] == "ok" and len(ended["steps"]) == 1
    assert ended["steps"][0]["output"]["next"] is None


def test_a_trigger_that_does_not_fire_says_why_and_runs_nothing():
    run = flows.run_flow(
        flows.EXAMPLE_FLOW, {"severity": "info"}, allow=["append_jsonl"], now=1.0
    )
    assert run["outcome"] == "not-triggered" and run["steps"] == []
    assert "did not match" in run["reason"] and run["steps_used"] == 0
    sched = dict(_linear(1), trigger={"type": "schedule", "every_seconds": 3600})
    early = flows.run_flow(sched, {}, now=1000.0, last_run=999.0)
    assert early["outcome"] == "not-triggered" and "not due" in early["reason"]
    assert flows.run_flow(sched, {}, now=1000.0, last_run=None)["outcome"] == "ok"


def test_an_invalid_flow_is_refused_before_a_single_step_runs():
    eff, seen = _recorder()
    looped = _linear(2)
    looped["nodes"]["n2"]["next"] = "n1"
    run = flows.run_flow(looped, {}, allow=["emit"], effectors=eff, now=1.0)
    assert run["outcome"] == "refused" and run["steps"] == [] and seen == []
    assert run["steps_used"] == 0
    codes = [p["code"] for p in run["problems"]]
    assert codes[0] == "invalid-flow" and "cycle" in codes
    assert "refused before any step ran" in run["reason"]
    # warnings alone do NOT block a run
    warned = _linear(1)
    warned["nodes"]["ghost"] = {
        "kind": "transform",
        "ops": [{"op": "set", "path": "g", "value": 1}],
    }
    assert flows.run_flow(warned, {}, now=1.0)["outcome"] == "ok"


def test_transform_failure_is_a_failed_run_with_the_reason_on_the_step():
    flow = _linear(1)
    flow["nodes"]["n1"]["ops"] = [{"op": "copy", "from": "absent", "path": "x"}]
    run = flows.run_flow(flow, {}, now=1.0)
    assert run["outcome"] == "failed"
    assert "no field 'absent'" in run["steps"][0]["error"]
    assert [p["code"] for p in run["problems"]] == ["transform-failed"]


def test_condition_failure_is_a_failed_run_not_a_silent_false():
    flow = _linear(1)
    flow["nodes"]["n1"] = {
        "kind": "filter",
        "when": {"path": "s", "op": "gt", "value": 1},
    }
    run = flows.run_flow(flow, {"s": "not a number"}, now=1.0)
    assert run["outcome"] == "failed"
    assert "needs two numbers" in run["steps"][0]["error"]


# ---- bounded recursion ------------------------------------------------------


def _parent(child_name: str = "child") -> dict:
    return {
        "name": "parent",
        "trigger": {"type": "manual"},
        "start": "call",
        "nodes": {
            "call": {"kind": "flow", "uses": child_name, "next": "done"},
            "done": {
                "kind": "transform",
                "ops": [{"op": "set", "path": "done", "value": True}],
            },
        },
    }


def test_a_subflow_runs_inline_and_spends_the_same_step_budget():
    child = _linear(2)
    child["name"] = "child"
    run = flows.run_flow(_parent(), {"in": 1}, registry={"child": child}, now=1.0)
    assert run["outcome"] == "ok"
    assert (
        run["data"]["step1"] == 1
        and run["data"]["step2"] == 2
        and run["data"]["done"] is True
    )
    # 1 (call) + 2 (child) + 1 (done) — nesting bought no extra steps
    assert run["steps_used"] == 4
    assert run["steps"][0]["output"]["flow"] == "child"
    assert run["steps"][0]["output"]["steps"] == 2
    capped = flows.run_flow(
        _parent(), {}, registry={"child": child}, max_steps=2, now=1.0
    )
    assert capped["outcome"] == "refused"
    assert [p["code"] for p in capped["refusals"]] == ["step-cap"]


def test_subflow_recursion_is_bounded_and_the_refusal_names_the_depth():
    rec = {
        "name": "rec",
        "trigger": {"type": "manual"},
        "start": "again",
        "nodes": {"again": {"kind": "flow", "uses": "rec"}},
    }
    run = flows.run_flow(
        rec, {}, registry={"rec": rec}, max_steps=99, max_depth=2, now=1.0
    )
    assert run["outcome"] == "refused"
    assert [p["code"] for p in run["problems"]] == ["depth-cap"]
    assert run["problems"][0]["node"] == "again/again/again"  # the nesting path
    assert run["steps_used"] == 3  # depth 0, 1, 2 ran; depth 3 refused
    deeper = flows.run_flow(
        rec, {}, registry={"rec": rec}, max_steps=99, max_depth=4, now=1.0
    )
    assert deeper["steps_used"] == 5 and deeper["outcome"] == "refused"


def test_a_missing_subflow_is_refused_by_name_never_skipped():
    run = flows.run_flow(_parent("nowhere"), {}, registry={}, now=1.0)
    assert run["outcome"] == "refused"
    assert [p["code"] for p in run["refusals"]] == ["subflow-missing"]
    assert "nowhere" in run["refusals"][0]["message"]
    assert "done" not in run["data"]  # the parent stopped too


def test_a_refusal_inside_a_subflow_propagates_with_a_prefixed_node():
    child = _with_action()
    child["name"] = "child"
    run = flows.run_flow(
        _parent(),
        {},
        allow=[],
        effectors=_recorder()[0],
        registry={"child": child},
        now=1.0,
    )
    assert run["outcome"] == "refused"
    assert [p["node"] for p in run["refusals"]] == ["call/act"]
    assert run["refusals"][0]["code"] == "action-not-allowlisted"


# ---- output containment -----------------------------------------------------


def test_resolve_output_path_confines_writes_to_the_output_directory(tmp_path):
    out = tmp_path / "flows-out"
    assert flows.resolve_output_path(out, "digest.jsonl") == out / "digest.jsonl"
    assert (
        flows.resolve_output_path(out, "sub/dir/d.txt") == out / "sub" / "dir" / "d.txt"
    )
    assert flows.resolve_output_path(out, "./a/b.txt") == out / "a" / "b.txt"
    assert (
        flows.resolve_output_path(out, "back\\slash.txt") == out / "back" / "slash.txt"
    )
    for escape in (
        "../evil.txt",
        "a/../../evil.txt",
        "/etc/passwd",
        "C:/Windows/x",
        "\\\\server\\share\\x",
        "",
        "   ",
        "..",
        None,
        7,
    ):
        with pytest.raises(ValueError):
            flows.resolve_output_path(out, escape)


# ---- family diagnostics -----------------------------------------------------


def test_to_diagnostics_maps_problems_into_the_family_schema():
    run = flows.run_flow(
        _with_action(), {}, allow=[], effectors=_recorder()[0], now=1.0
    )
    diags = flows.to_diagnostics("my-flow.json", run["problems"])
    assert len(diags) == 1
    assert diags[0]["rule"] == "flows:action-not-allowlisted"
    assert diags[0]["severity"] == "error"
    assert diags[0]["path"] == "my-flow.json"
    assert diags[0]["line"] == 0 and diags[0]["col"] == 0  # a graph has no line numbers
    assert "[act]" in diags[0]["message"]
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1
    warn = flows.to_diagnostics(
        "f.json",
        flows.validate(
            _linear(1)
            | {
                "nodes": {
                    "n1": {
                        "kind": "transform",
                        "ops": [{"op": "set", "path": "a", "value": 1}],
                    },
                    "ghost": {
                        "kind": "transform",
                        "ops": [{"op": "set", "path": "g", "value": 1}],
                    },
                }
            }
        ),
    )
    assert [d["severity"] for d in warn] == ["warning"]
    assert flows.to_diagnostics("f.json", []) == []


# ---- the run ledger ---------------------------------------------------------


def _tables(conn):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_store_schema_and_idempotent_reopen(tmp_path):
    db = tmp_path / "nested" / "flows.db"
    conn = flows.open_store(db)
    assert {"runs", "steps", "meta"} <= _tables(conn)
    run = flows.run_flow(_linear(1), {}, now=100.0)
    rid = flows.record_run(conn, run, source="f.json")
    conn.close()
    conn2 = flows.open_store(db)  # same file, no error, rows survive
    assert flows.run_detail(conn2, rid)["flow"] == "linear1"
    assert flows.last_run_ts(conn2, "linear1") == 100.0


def test_record_run_keeps_the_either_or_invariant_in_the_ledger():
    conn = _mem()
    eff, _ = _recorder()
    ok_run = flows.run_flow(
        _with_action(), {"a": 1}, allow=["emit"], effectors=eff, now=10.0
    )
    bad_run = flows.run_flow(
        _with_action(), {"a": 1}, allow=[], effectors=eff, now=11.0
    )
    rid_ok = flows.record_run(conn, ok_run, source="a.json")
    rid_bad = flows.record_run(conn, bad_run)
    for rid in (rid_ok, rid_bad):
        detail = flows.run_detail(conn, rid)
        assert detail["steps"]
        for row in detail["steps"]:
            assert (row["output"] is None) != (row["error"] is None)
    good = flows.run_detail(conn, rid_ok)
    assert good["outcome"] == "ok" and good["source"] == "a.json"
    assert json.loads(good["allowlist"]) == ["emit"]
    assert json.loads(good["actions_run"]) == ["emit"]
    assert good["problems"] is None  # a clean run stores no problem blob
    assert json.loads(good["payload_out"])["a"] == 1
    refused = flows.run_detail(conn, rid_bad)
    assert refused["outcome"] == "refused" and refused["source"] is None
    assert json.loads(refused["problems"])[0]["code"] == "action-not-allowlisted"
    assert refused["steps"][0]["error"] and refused["steps"][0]["output"] is None


def test_list_runs_filters_and_counts_outcomes():
    conn = _mem()
    flows.record_run(conn, flows.run_flow(_linear(1), {}, now=1.0))
    flows.record_run(conn, flows.run_flow(_linear(2), {}, now=2.0))
    flows.record_run(conn, flows.run_flow(_with_action(), {}, allow=[], now=3.0))
    rows = flows.list_runs(conn)
    assert [r["ts"] for r in rows] == [3.0, 2.0, 1.0]  # newest first
    assert [r["flow"] for r in flows.list_runs(conn, flow="linear2")] == ["linear2"]
    assert len(flows.list_runs(conn, outcome="refused")) == 1
    assert len(flows.list_runs(conn, limit=1)) == 1
    assert flows.outcome_counts(conn) == {"ok": 2, "refused": 1}
    assert flows.outcome_counts(conn, flow="linear1") == {"ok": 1}


def test_last_run_ts_is_none_when_a_flow_never_ran():
    conn = _mem()
    assert flows.last_run_ts(conn, "linear1") is None  # no evidence, no invented time
    assert flows.run_detail(conn, 999) is None
    flows.record_run(conn, flows.run_flow(_linear(1), {}, now=5.0))
    flows.record_run(conn, flows.run_flow(_linear(1), {}, now=9.0))
    assert flows.last_run_ts(conn, "linear1") == 9.0


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.flows import cli as flows_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = flows_cli._capability()
    assert cap["adapter"] == "flows"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "flowpipe"
    assert cap["extras"]["n8n"]["found"] is False
    assert cap["extras"]["zapier"]["found"] is False  # SaaS client, never run


def test_manifest_denies_the_network_axis():
    from bigbang.core.policy import check_permission
    from bigbang.plugins.flows import cli as flows_cli

    manifest = flows_cli._manifest()
    assert manifest["capabilities"]["network"]["enabled"] is False
    assert manifest["capabilities"]["network"]["domains"] == []
    assert manifest["capabilities"]["secrets"]["allow"] == []
    allowed, reason = check_permission(
        manifest, "network", "https://hooks.zapier.com/x"
    )
    assert allowed is False and "network disabled" in reason
    assert check_permission(manifest, "fs_write", ".scout/flows.db")[0] is True
    # no action can reach the network: there is no http/webhook effect at all
    assert all(
        spec["effects"] in ("none", "filesystem") for spec in flows.ACTIONS.values()
    )


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None, env=None):
    import os

    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
        env=e,
    )


def test_cli_flows_hello_envelope():
    r = _cli(["flows", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_flows_actions_publishes_the_vocabulary():
    r = _cli(["flows", "actions"])
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)["data"]
    assert payload["default_allowlist"] == []
    assert set(payload["actions"]) == set(flows.ACTIONS)
    assert payload["actions"]["write_file"]["required"] == ["file", "from"]
    assert payload["bounds"]["max_steps"] == flows.DEFAULT_MAX_STEPS
    assert flows.validate(payload["example_flow"]) == []  # the published example runs


def test_cli_flows_plan_example_reports_the_default_deny_refusal():
    r = _cli(["flows", "plan", "--example"])
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)["data"]
    assert payload["valid"] is True and payload["problems"] == []
    assert payload["preflight"]["refused"] == ["append_jsonl"]
    assert payload["preflight"]["runnable"] is False
    assert payload["order"] == ["summarize", "any", "record"]


def test_cli_flows_plan_needs_a_flow_and_gates_on_severity(tmp_path):
    missing = _cli(["flows", "plan"])
    assert missing.returncode == 1
    assert "--flow" in json.loads(missing.stdout)["error"]
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"name": "b", "trigger": {"type": "manual"}}), encoding="utf-8"
    )
    gated = _cli(["flows", "plan", "--flow", str(bad), "--fail-on", "error"])
    assert gated.returncode == 1  # invalid flow trips the CI gate
    assert json.loads(gated.stdout)["data"]["valid"] is False


def test_cli_flows_run_example_writes_a_real_file_and_records_the_run(tmp_path):
    out, db = tmp_path / "out", tmp_path / "flows.db"
    r = _cli(
        [
            "flows",
            "run",
            "--example",
            "--allow",
            "append_jsonl",
            "--out-dir",
            str(out),
            "--db",
            str(db),
            "--payload",
            '{"severity":"error","hosts":["a.com","b.com"]}',
        ],
    )
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)["data"]
    assert payload["outcome"] == "ok" and payload["actions_run"] == ["append_jsonl"]
    assert payload["steps_used"] == 3 and payload["run_id"] == 1
    written = out / "cert-digest.jsonl"
    raw = written.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw  # byte-exact, no CRLF on Windows
    row = json.loads(raw.decode("utf-8"))
    assert row == {"host_count": 2, "line": '2 host(s) at error: ["a.com", "b.com"]'}
    hist = _cli(["flows", "runs", "--db", str(db), "--run", "1"])
    assert hist.returncode == 0
    detail = json.loads(hist.stdout)["data"]["run"]
    assert detail["outcome"] == "ok" and len(detail["steps"]) == 3
    assert detail["source"] == "core:EXAMPLE_FLOW"
    board = _cli(["flows", "runs", "--db", str(db)])
    assert json.loads(board.stdout)["data"]["by_outcome"] == {"ok": 1}


def test_cli_flows_run_refuses_an_unallowlisted_action_and_writes_nothing(tmp_path):
    out, db = tmp_path / "out", tmp_path / "flows.db"
    r = _cli(
        [
            "flows",
            "run",
            "--example",
            "--out-dir",
            str(out),
            "--db",
            str(db),
            "--fail-on",
            "error",
            "--payload",
            '{"severity":"error","hosts":["a.com"]}',
        ],
    )
    assert r.returncode == 1  # the gate fired on the refusal
    payload = json.loads(r.stdout)["data"]
    assert payload["outcome"] == "refused"
    assert payload["refusals"][0]["code"] == "action-not-allowlisted"
    assert payload["diagnostics"][0]["rule"] == "flows:action-not-allowlisted"
    assert not (out / "cert-digest.jsonl").exists()  # nothing was written
    assert not list(out.glob("*")) if out.exists() else True


def test_cli_flows_run_refuses_a_path_escape_at_runtime(tmp_path):
    out, db = tmp_path / "out", tmp_path / "flows.db"
    flow = tmp_path / "escape.json"
    flow.write_text(
        json.dumps(
            {
                "name": "escaper",
                "trigger": {"type": "manual"},
                "start": "w",
                "nodes": {
                    "w": {
                        "kind": "action",
                        "uses": "write_file",
                        "with": {"file": "../escaped.txt", "from": "body"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    r = _cli(
        [
            "flows",
            "run",
            "--flow",
            str(flow),
            "--allow",
            "write_file",
            "--out-dir",
            str(out),
            "--db",
            str(db),
            "--payload",
            '{"body":"pwned"}',
        ],
    )
    assert r.returncode == 0  # reported, not crashed
    payload = json.loads(r.stdout)["data"]
    assert payload["outcome"] == "failed"
    assert "refusing path escape" in payload["steps"][0]["error"]
    assert not (tmp_path / "escaped.txt").exists()


def test_cli_flows_runs_without_a_ledger_fails_actionably(tmp_path):
    r = _cli(["flows", "runs", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no flow ledger" in data["error"] and "example" in data
