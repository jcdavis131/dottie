# Solo personal project, no connection to employer, built with public/free-tier only
"""diagnose_failure: targeted repair hints for the self-correction pass.

Every positive case below is a REAL failure string (or its load-bearing
fragment) from the ledger's failed_validation population as of 2026-07-22 —
the hints must fire on what actually kills candidates, not on invented text.
"""

from dottie.research.validate import ValidationResult, diagnose_failure

# real ledger fragments -> the hint class that must fire
REAL_CASES = [
    ("RuntimeError: einsum(): output subscript n does not appear in the "
     "equation for any input operand", "EINSUM REPAIR"),
    ("RuntimeError: einsum(): the number of subscripts in the equation (4) "
     "does not match the number of dimensions (3)", "EINSUM REPAIR"),
    ("RuntimeError: The size of tensor a (64) must match the size of tensor "
     "b (16) at non-singleton dimension 2", "SHAPE-ALGEBRA REPAIR"),
    ("RuntimeError: Expected size for first two dimensions of batch2 tensor "
     "to be: [4, 16] but got: [4, 64]", "SHAPE-ALGEBRA REPAIR"),
    ("TypeError: HierarchicalAttention.__init__() missing 1 required "
     "positional argument: 'd_k'", "CONSTRUCTOR CONTRACT"),
    ("AttributeError: 'GradientAdaptiveSparseAttention' object has no "
     "attribute 'hidden'", "ATTRIBUTE REPAIR"),
    ("forward produced NaN/Inf — add clamping or an eps term",
     "STABILITY REPAIR"),
    ("degenerate block: 0 learnable parameters", "CAPACITY REPAIR"),
    ("forward returned shape (4, 16, 32) for input (4, 16, 64) — the "
     "integration contract requires a drop-in sequence block whose output "
     "has the SAME [batch, seq, hidden] shape as its input",
     "OUTPUT CONTRACT"),
]


def test_real_failures_get_targeted_hints():
    for detail, expected in REAL_CASES:
        hint = diagnose_failure("dry_run", detail)
        assert expected in hint, f"{expected!r} not fired for: {detail[:60]}"


def test_unknown_traceback_gets_general_dry_run_hint():
    hint = diagnose_failure("dry_run", "Traceback (most recent call last):\n"
                            "  ...\nSomethingWeirdError: novel failure mode")
    assert "GENERAL DRY-RUN REPAIR" in hint


def test_unknown_non_dry_run_gets_no_hint_not_a_wrong_one():
    assert diagnose_failure("static", "F999 some totally novel lint code") == ""
    assert diagnose_failure("syntax", "") == ""


def test_as_feedback_appends_hint_for_known_failure():
    r = ValidationResult(False, "dry_run", "fail",
                         "RuntimeError: einsum(): output subscript n does not "
                         "appear in the equation for any input operand")
    fb = r.as_feedback()
    assert "Validation failed at level 'dry_run'" in fb
    assert "REPAIR HINT:" in fb and "EINSUM REPAIR" in fb


def test_as_feedback_unchanged_when_no_hint():
    r = ValidationResult(False, "syntax", "fail", "SyntaxError on line 3: bad")
    fb = r.as_feedback()
    assert "REPAIR HINT:" not in fb
    assert fb.startswith("Validation failed at level 'syntax'")
