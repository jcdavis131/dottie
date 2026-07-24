# Solo personal project, no connection to employer, built with public/free-tier only
"""diagnose_failure: targeted repair hints for the self-correction pass.

Every positive case below is a REAL failure string (or its load-bearing
fragment) from the ledger's failed_validation population as of 2026-07-22 —
the hints must fire on what actually kills candidates, not on invented text.
"""

from dottie.research.validate import (ValidationResult, check_self_attributes,
                                      diagnose_failure)

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


# ---- check_self_attributes: advisory only, silent when unsure ---------------

UNASSIGNED = """
import torch.nn as nn
class Block(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.proj = nn.Linear(d_model, d_model)
    def forward(self, x):
        return self.proj(x) * self.hidden   # self.hidden never assigned
"""

CLEAN = """
import torch.nn as nn
class Block(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.proj = nn.Linear(d_model, d_model)
        self.scale = 0.5
    def forward(self, x):
        if self.training:                    # nn.Module builtin — not a warning
            x = self.helper(x)               # method — not a warning
        return self.proj(x) * self.scale
    def helper(self, x):
        return x
"""

DYNAMIC = """
class Block:
    def __init__(self):
        setattr(self, "gate", 1)
    def forward(self, x):
        return x * self.gate
"""


def test_unassigned_self_attribute_is_warned_with_name():
    ws = check_self_attributes(UNASSIGNED)
    assert len(ws) == 1 and "self.hidden" in ws[0] and "Block" in ws[0]


def test_clean_class_produces_no_warnings():
    assert check_self_attributes(CLEAN) == []


def test_setattr_class_stays_silent_not_wrong():
    assert check_self_attributes(DYNAMIC) == []


def test_broken_syntax_stays_silent():
    assert check_self_attributes("def broken(:") == []
