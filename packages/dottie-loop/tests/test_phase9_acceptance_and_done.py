"""Phase 9: §38 acceptance coverage and §39 definition of done are checkable, and honest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dottie_loop import acceptance, errors, evaluation
from dottie_loop.cli import EXIT_BLOCKED, EXIT_OK, main

TESTS = Path(__file__).resolve().parent


def _run(capsys, *argv):
    rc = main([str(a) for a in argv])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, json.loads(lines[-1])


def test_ml14_promotion_requires_explicit_approval():
    gates = {"failed": [], "bundle_id": "b"}
    canary = {"status": "complete", "challenger_metric": 0.9, "baseline_metric": 0.8}
    assert evaluation.promotion_decision(gates, canary=canary, approval_valid=False)["outcome"] == "block"
    assert evaluation.promotion_decision(gates, canary=canary, approval_valid=True)["outcome"] == "promote"


def test_ids_parse_singles_and_ranges():
    assert acceptance.ids_in_test_name("test_ml09_to_ml13_gates") == {"ML-09", "ML-10", "ML-11", "ML-12", "ML-13"}
    assert acceptance.ids_in_test_name("test_rt01_a_rt02_b") == {"RT-01", "RT-02"}
    assert acceptance.ids_in_test_name("test_ml15_ml16_release") == {"ML-15", "ML-16"}
    assert acceptance.ids_in_test_name("test_plain") == set()
    with pytest.raises(errors.InvalidInputError):
        acceptance.ids_in_test_name("test_ml13_to_ml09_backwards")


def test_every_acceptance_id_has_a_named_test_here(capsys):
    cov = acceptance.coverage(TESTS)
    assert cov["missing"] == [] and cov["covered"] == cov["total"] == 34
    assert cov["items"]["ML-08"]["mechanics_only"] and cov["items"]["ML-08"]["operator_evidence"]
    assert cov["items"]["RT-05"]["mechanics_only"] is False and cov["items"]["ML-14"]["tests"]
    rc, env = _run(capsys, "spec", "acceptance", "--tests", TESTS)
    assert rc == EXIT_OK and env["data"]["missing"] == []
    with pytest.raises(errors.InvalidInputError):
        acceptance.coverage(TESTS / "nope")


def test_missing_ids_block(capsys, tmp_path):
    (tmp_path / "test_some.py").write_text("def test_rt01_only():\n    pass\n")
    cov = acceptance.coverage(tmp_path)
    assert "RT-02" in cov["missing"] and len(cov["missing"]) == 33
    rc, env = _run(capsys, "spec", "acceptance", "--tests", tmp_path)
    assert rc == EXIT_BLOCKED and "RT-02" in env["error"]["details"]["missing"]


def test_definition_of_done_never_completes_on_mechanics_alone(capsys, tmp_path):
    dod = acceptance.definition_of_done(TESTS)
    assert not dod["complete"] and dod["counts"]["mechanics_missing"] == 0
    assert dod["counts"]["mechanics_proven"] + dod["counts"]["operator_pending"] == 30
    by = {i["id"]: i for i in dod["items"]}
    assert by["D04"]["status"] == "mechanics_proven" and by["D04"]["acceptance_ids"] == ["RT-05"]
    assert by["D23"]["status"] == "operator_pending"
    # a bare `true` is not evidence; a proof names its ref
    partial = {i["id"]: {"proven": True, "ref": "drill-2026-09-11"} for i in dod["items"] if i["kind"] == "operator"}
    partial["D23"] = True
    d2 = acceptance.definition_of_done(TESTS, partial)
    assert d2["pending"] == ["D23"]
    partial["D23"] = {"proven": True, "ref": "served sha verified 2026-09-11"}
    d3 = acceptance.definition_of_done(TESTS, partial)
    assert d3["complete"] and d3["counts"]["operator_proven"] == 9
    rc, env = _run(capsys, "spec", "done", "--tests", TESTS, "--out", tmp_path / "dod.json")
    assert rc == EXIT_BLOCKED and env["error"]["details"]["counts"]["operator_pending"] == 9 and (tmp_path / "dod.json").exists()
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps(partial))
    rc, env = _run(capsys, "spec", "done", "--tests", TESTS, "--operator-evidence", ev)
    assert rc == EXIT_OK and env["data"]["complete"]
    ev.write_text("[]")
    assert _run(capsys, "spec", "done", "--tests", TESTS, "--operator-evidence", ev)[0] == 3
