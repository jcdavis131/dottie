# Solo personal project, no connection to employer, built with public/free-tier only
"""diagnose_failure: targeted repair hints for the self-correction pass.

Every positive case below is a REAL failure string (or its load-bearing
fragment) from the ledger's failed_validation population as of 2026-07-22 —
the hints must fire on what actually kills candidates, not on invented text.
(Exceptions are individually marked CONSTRUCTED or validator-literal.)

2026-07-23 expansion: NEW_REAL_CASES fragments come from
implementation.validation.history in the ledger copy (358 failed attempts;
the truncated `failure` column is not mined). Coverage over that corpus is
measured by scripts/replay_hint_coverage.py: 71.2% before, 100.0% after.
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


# ---- 2026-07-23 expansion: (level, real history fragment) -> hint class ------
# Experiment ids in trailing comments locate each fragment in the ledger copy.

NEW_REAL_CASES = [
    ("static",
     "F821 Undefined name `nn`\n  --> data\\research\\workspaces\\"
     "bcf9e4d3e316\\candidate_051d030b.py:11:21\n   |\n 9 |         "
     "self.eps = eps\n10 |         self.alpha = "
     "nn.Parameter(torch.zeros(num_experts))",
     "UNDEFINED NAME"),                                      # bcf9e4d3e316
    ("static",
     "F821 Undefined name `Dict`\n  --> data\\research\\workspaces\\"
     "bcf9e4d3e316\\candidate_f7556b99.py:13:43",
     "UNDEFINED NAME"),                                      # bcf9e4d3e316
    ("dry_run",
     "RuntimeError: element 0 of tensors does not require grad and does not "
     "have a grad_fn",
     "NO-AUTOGRAD-IN-FORWARD"),                              # bd158264b645
    ("contract",
     "no 'forward' method found on any class",
     "MODULE SKELETON"),                                     # 52aaf2fe8d60
    ("contract",
     "no class defined (expected an nn.Module subclass)",
     "MODULE SKELETON"),
    ("syntax",
     "SyntaxError on line 15: unexpected character after line continuation "
     "character",
     "MALFORMED SOURCE"),                                    # cd9d7b550b2d
    ("syntax",
     "SyntaxError on line 4: '(' was never closed",
     "MALFORMED SOURCE"),
    ("syntax",
     "SyntaxError on line 9: unmatched ']'",
     "MALFORMED SOURCE"),
    ("syntax",
     "SyntaxError on line 21: positional argument follows keyword argument",
     "MALFORMED SOURCE"),
    ("contract",
     "forward() of HysteresisCrossEntropyLoss requires extra argument(s) "
     "['targets'] beyond the single hidden-states tensor",
     "LOSS-VS-BLOCK"),                                       # 0ee3e83776a1
    # validator-literal (check_contract's own message), zero ledger rows yet:
    ("contract",
     "illegal imports (untrusted-code policy): ['os']",
     "SANDBOX POLICY"),
    ("dry_run",
     "AssertionError: Routing probs shape torch.Size([4, 4]) does not match "
     "expected [num_experts=4]",
     "YOUR OWN ASSERT FIRED"),                               # 471f27050226
    ("dry_run",
     "RuntimeError: t() expects a tensor with <= 2 dimensions, but self is 3D",
     "BATCHED TRANSPOSE"),                                   # d2b6308146f8
    ("dry_run",
     "ImportError: cannot import name 'einsum' from 'torch.nn.functional' "
     "(C:\\Users\\jcdav\\dottie\\apps\\dottie\\.venv\\Lib\\site-packages\\"
     "torch\\nn\\functional.py)",
     "IMPORT REALITY"),                                      # 77e7ea900675
    ("dry_run",
     "RuntimeError: Index tensor must have the same number of dimensions as "
     "input tensor",
     "GATHER/TOPK REPAIR"),                                  # 97c3eb5b94a8
    ("dry_run",
     "RuntimeError: shape '[4, 4, 16]' is invalid for input of size 16",
     "SHAPE-ALGEBRA REPAIR"),                                # 471f27050226
]


def test_expanded_real_failures_get_targeted_hints():
    for level, detail, expected in NEW_REAL_CASES:
        hint = diagnose_failure(level, detail)
        assert expected in hint, f"{expected!r} not fired for: {detail[:60]}"


def test_static_snippet_quoting_dry_run_text_gets_static_hint():
    # CONSTRUCTED (not a ledger row): ruff details quote candidate source, so
    # a dry_run-oriented pattern must not steal the diagnosis on its level —
    # the level-scoped table is checked before the generic one.
    detail = ("F821 Undefined name `w`\n   |\n12 |         y = "
              "torch.einsum() * w\n   |")
    hint = diagnose_failure("static", detail)
    assert "UNDEFINED NAME" in hint and "EINSUM" not in hint


def test_assert_catchall_loses_to_specific_classes():
    # CONSTRUCTED (not a ledger row): when a candidate's assert wraps a known
    # failure class, the specific hint must win — the bare `AssertionError:`
    # catch-all is deliberately ordered last in _HINTS.
    detail = ("AssertionError: shape '[4, 16, 8, 64]' is invalid for input "
              "of size 12288")
    assert "SHAPE-ALGEBRA REPAIR" in diagnose_failure("dry_run", detail)


def test_as_feedback_appends_hint_for_static_failure():
    r = ValidationResult(False, "static", "fail",
                         "F821 Undefined name `nn`\n  --> "
                         "candidate_051d030b.py:11:21")
    fb = r.as_feedback()
    assert "Validation failed at level 'static'" in fb
    assert "REPAIR HINT:" in fb and "UNDEFINED NAME" in fb


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
