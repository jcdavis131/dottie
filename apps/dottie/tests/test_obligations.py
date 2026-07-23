# Solo personal project, no connection to employer, built with public/free-tier only
"""Obligation tracking: named proof obligations riding alongside repair hints.

The Emira/LemmaScript mechanic (tasks/artifacts/verification_engine_learnings
.md): every failure is a NAMED, still-open obligation; feedback tells the
corrector WHICH property to discharge next; the per-attempt ledger lets the KG
mine failed→discharged traces. Failure fragments below marked with experiment
ids are REAL ledger strings (same corpus as test_validate_hints.py); the rest
are validator-literal messages. Everything runs offline — no torch, no ruff,
no network: dry_run-stage cases are built from per_level records exactly as
validate() stores them, and the end-to-end cases stop at syntax/contract,
which never touch the filesystem or a subprocess.
"""

import json

from dottie.research.validate import (LEVELS, OBLIGATIONS, ValidationResult,
                                      failed_obligations, format_obligations,
                                      validate, validate_with_correction)


def _by_id(obls):
    return {o["obligation_id"]: o["status"] for o in obls}


def _passing(*levels):
    return {lv: {"status": "pass", "detail": ""} for lv in levels}


# ---- vocabulary invariants ---------------------------------------------------


def test_vocabulary_covers_every_level_and_ids_are_unique():
    """Adding a stage without naming its obligations must fail HERE, not
    silently under-report — the same contract LEVELS documents for itself."""
    ids = [oid for oid, _, _ in OBLIGATIONS]
    assert len(ids) == len(set(ids)), "duplicate obligation ids"
    assert {stage for _, stage, _ in OBLIGATIONS} == set(LEVELS)


def test_obligations_are_json_serializable_strings():
    r = ValidationResult(False, "syntax", "fail", "SyntaxError on line 1: bad")
    obls = r.obligations()
    assert json.loads(json.dumps(obls)) == obls
    for o in obls:
        assert set(o) == {"obligation_id", "property", "stage", "status"}
        assert all(isinstance(v, str) for v in o.values())


# ---- attribution: end-to-end through validate() (syntax/contract only) -------


def test_syntax_failure_fails_parses_and_leaves_the_rest_unchecked():
    r = validate("def broken(:")
    assert not r.ok and r.level == "syntax"
    st = _by_id(r.obligations())
    assert st.pop("parses") == "failed"
    assert set(st.values()) == {"unchecked"}


BAD_CONTRACT = """
import os
import torch.nn as nn

class Block(nn.Module):
    def forward(self, x, targets):
        return x
"""


def test_contract_reports_every_violated_obligation_and_clears_the_rest():
    """check_contract evaluates all problem classes in one pass, so unmatched
    contract obligations were really checked → discharged, and BOTH violations
    fail at once (an obligation list, not a single verdict)."""
    r = validate(BAD_CONTRACT, class_name="Block")
    assert not r.ok and r.level == "contract"
    st = _by_id(r.obligations())
    assert st["parses"] == "discharged"
    assert st["block_signature"] == "failed"        # requires extra ['targets']
    assert st["sandbox_policy"] == "failed"         # illegal import: os
    assert st["module_skeleton"] == "discharged"    # class + forward exist
    assert st["names_resolve"] == "unchecked"       # fail-fast never got there
    assert st["gradient_flow"] == "unchecked"


# ---- attribution: dry_run per_level records as validate() stores them --------

# validator-literal rank-collapse message (the 694633b2d354 failure shape)
RANK_COLLAPSE = (
    "rank collapse: the output has the right shape but is CONSTANT along the "
    "hidden dimension (mean std across hidden = 0.0, input was 0.998). Every "
    "feature position holds the same value, so the block has erased the "
    "residual stream it was handed")


def test_post_forward_literal_discharges_everything_provably_before_it():
    """A rank-collapse verdict is only emitted after the forward completed and
    the shape/finite/degeneracy checks passed — those obligations are
    PROVABLY discharged; the ones after it stay unchecked."""
    per = _passing("syntax", "contract", "static")
    per["dry_run"] = {"status": "fail", "detail": RANK_COLLAPSE}
    r = ValidationResult(False, "dry_run", "fail", RANK_COLLAPSE, per)
    st = _by_id(r.obligations())
    assert st["rank_health"] == "failed"
    for oid in ("constructible", "executes", "output_contract",
                "shape_conservation", "finite_output", "non_degeneracy"):
        assert st[oid] == "discharged", oid
    assert st["param_capacity"] == "unchecked"      # checked AFTER rank health
    assert st["width_generalization"] == "unchecked"
    assert st["gradient_flow"] == "unchecked"


def test_raw_traceback_does_not_overclaim_stage_mates():
    """An einsum traceback attributes only `executes` (the honest fallback);
    `constructible` is NOT declared discharged, because a traceback proves
    nothing about where in the stage execution died."""
    detail = ("Traceback (most recent call last):\n  ...\nRuntimeError: "
              "einsum(): output subscript n does not appear in the equation "
              "for any input operand")                       # real fragment
    per = _passing("syntax", "contract", "static")
    per["dry_run"] = {"status": "fail", "detail": detail}
    st = _by_id(ValidationResult(False, "dry_run", "fail", detail, per)
                .obligations())
    assert st["executes"] == "failed"
    assert st["constructible"] == "unchecked"
    assert st["shape_conservation"] == "unchecked"


def test_ctor_missing_arg_attributes_constructible():
    detail = ("TypeError: HierarchicalAttention.__init__() missing 1 required "
              "positional argument: 'd_k'")                  # real fragment
    assert failed_obligations("dry_run", detail) == ["constructible"]


def test_residual_stream_failure_is_gradient_flow_with_dry_run_discharged():
    """The §5.3.R10 shape: passes every dry-run obligation, dies only on a
    grad-carrying non-leaf input ('NoneType' object has no attribute 'abs')."""
    detail = ("fails when handed a REAL residual-stream activation ...\n"
              "AttributeError: 'NoneType' object has no attribute 'abs'")
    per = _passing("syntax", "contract", "static", "dry_run",
                   "integration_width")
    per["residual_stream"] = {"status": "fail", "detail": detail}
    st = _by_id(ValidationResult(False, "residual_stream", "fail", detail, per)
                .obligations())
    assert st["gradient_flow"] == "failed"
    assert st["rank_health"] == "discharged"
    assert st["width_generalization"] == "discharged"


def test_skipped_stage_reports_skipped_never_discharged():
    per = _passing("syntax", "contract", "static")
    per["dry_run"] = {"status": "skipped",
                      "detail": "torch not installed — CPU dry-run skipped "
                                "(not a pass)"}              # validator-literal
    r = ValidationResult(True, "dry_run", "skipped", per["dry_run"]["detail"],
                         per)
    st = _by_id(r.obligations())
    assert st["parses"] == "discharged"
    assert st["shape_conservation"] == "skipped"
    assert st["param_capacity"] == "skipped"


def test_unknown_level_yields_no_failed_attribution_and_no_section():
    """A level outside the vocabulary (e.g. implementation.py's 'parse') gets
    no wrong attribution — nothing failed, feedback section absent."""
    assert failed_obligations("parse", "no parseable JSON object found") == []
    r = ValidationResult(False, "parse", "fail", "no parseable JSON object")
    assert all(o["status"] == "unchecked" for o in r.obligations())
    assert format_obligations(r.obligations()) == ""


def test_full_pass_discharges_all_and_formats_to_nothing():
    per = _passing(*LEVELS)
    r = ValidationResult(True, "dry_run", "pass", "forward ok", per)
    obls = r.obligations()
    assert {o["status"] for o in obls} == {"discharged"}
    assert format_obligations(obls) == ""


# ---- feedback: the corrector is aimed at a named obligation ------------------


def test_as_feedback_names_the_obligation_and_keeps_the_hint():
    """Additive contract: the existing REPAIR HINT survives untouched and the
    obligation ledger rides after it, naming what to discharge next."""
    per = _passing("syntax", "contract", "static")
    per["dry_run"] = {"status": "fail", "detail": RANK_COLLAPSE}
    fb = ValidationResult(False, "dry_run", "fail", RANK_COLLAPSE,
                          per).as_feedback()
    assert fb.startswith("Validation failed at level 'dry_run'")
    assert "REPAIR HINT:" in fb and "CAPACITY REPAIR" in fb  # unchanged hint
    # 5 from syntax+contract+static, 6 provably clean before rank_health
    assert "PROOF OBLIGATIONS [11/15 discharged]:" in fb
    assert "DISCHARGE NEXT -> rank_health:" in fb
    assert "already discharged (do not break these):" in fb
    assert "blocked behind the failure (unchecked): param_capacity" in fb


def test_as_feedback_without_hint_still_names_the_obligation():
    fb = ValidationResult(False, "syntax", "fail",
                          "SyntaxError on line 3: bad").as_feedback()
    assert "REPAIR HINT:" not in fb                 # unknown class: no hint...
    assert "DISCHARGE NEXT -> parses:" in fb        # ...but a named obligation


# ---- the discharge trace in validation.history -------------------------------


def test_correction_history_carries_the_obligation_discharge_trace():
    """Attempt 0 fails `parses`; the rewrite discharges it and fails
    `module_skeleton` — the failed→discharged transition the KG mines, present
    per-attempt in history and JSON-serializable as stored by the ledger."""
    seen_feedback = []

    def corrector(code, feedback):
        seen_feedback.append(feedback)
        return "x = 1\n"                            # parses; no class at all

    outcome = validate_with_correction("def broken(:", corrector, max_retries=1)
    assert not outcome.ok and outcome.attempts == 1
    assert "PROOF OBLIGATIONS" in seen_feedback[0]  # the corrector was aimed
    h0, h1 = outcome.history
    assert _by_id(h0["obligations"])["parses"] == "failed"
    st1 = _by_id(h1["obligations"])
    assert st1["parses"] == "discharged"            # obligation discharged...
    assert st1["module_skeleton"] == "failed"       # ...next one now named
    assert json.loads(json.dumps(outcome.history))  # ledger-safe
