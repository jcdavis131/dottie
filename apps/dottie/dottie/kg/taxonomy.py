# Solo personal project, no connection to employer, built with public/free-tier only
"""Failure-class taxonomy for research-ledger ingestion.

MIRRORS ``dottie.research.validate._HINTS`` (as of commit 54c43f4). Deliberately
duplicated rather than imported: another agent lane owns validate.py right now
(concurrency rule), and importing a file mid-edit is a live race. The
DeepRefine patch proposal in tasks/artifacts/kg_native_design.md names the fix:
give validate's hints stable ids and export them, then this module imports the
one source of truth. Until then this mirror is the drift risk, stated plainly.
"""

from __future__ import annotations

import re

#: (class_id, regex, one-line summary of the repair hint that fires for it).
#: Order matters: first match wins for the primary class, exactly like
#: validate.diagnose_failure walks its _HINTS tuple.
FAILURE_CLASSES: tuple[tuple[str, str, str], ...] = (
    (
        "einsum",
        r"einsum\(\)",
        "replace einsum with explicit reshape/matmul/transpose ops + shape asserts",
    ),
    (
        "shape_algebra",
        r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes",
        "track shapes symbolically from [batch, seq, hidden]; assert after each reshape/matmul",
    ),
    (
        "ctor_missing_arg",
        r"missing \d+ required positional argument",
        "every extra __init__ parameter needs a width-derived default",
    ),
    (
        "no_attribute",
        r"has no attribute '\w+'",
        "assign every self.<attr> in __init__; use only documented torch.nn modules",
    ),
    (
        "name_error",
        r"NameError: name",
        "define or import the name (torch/torch.nn/math only)",
    ),
    (
        "nan_inf",
        r"NaN/Inf",
        "eps inside sqrt/log/division; clamp attention logits before softmax",
    ),
    (
        "degenerate",
        r"degenerate block|RANK COLLAPSE|rank collapse",
        "the block needs learnable parameters whose output varies per position and feature",
    ),
    (
        "output_shape_contract",
        r"the SAME \[batch, seq, hidden\] shape",
        "return exactly one tensor with the input's shape; project back with a final Linear",
    ),
)

_LEVEL_RE = re.compile(r"validation failed at '(\w+)'")
_ERRORISH_RE = re.compile(
    r"^\w+(\.\w+)*(Error|Exception|Warning)\b|^AssertionError|Error:"
    r"|^[EFW]\d{3}\b"
)  # last alternative: ruff codes (F821, E999, ...)


def classify(detail: str) -> list[str]:
    """All failure classes whose signature appears in ``detail`` (may be [])."""
    return [cid for cid, pat, _ in FAILURE_CLASSES if re.search(pat, detail or "")]


def primary_class(detail: str) -> str:
    """First matching class, or 'unclassified' — mirrors first-match-wins hints."""
    hits = classify(detail)
    return hits[0] if hits else "unclassified"


def failing_level(failure_text: str) -> str:
    """The validation level named in a ledger failure string, or a best guess."""
    m = _LEVEL_RE.search(failure_text or "")
    if m:
        return m.group(1)
    if "not integrable" in (failure_text or ""):
        return "training"
    return "unknown"


def salient_line(detail: str) -> str:
    """The last exception-looking line of a traceback (for clustering)."""
    lines = [ln.strip() for ln in (detail or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if _ERRORISH_RE.search(ln):
            return ln[:200]
    # fallback: the last line that actually says something (ruff output ends
    # in bare "|" gutter lines, which made 19 real failures cluster as "|")
    for ln in reversed(lines):
        if re.search(r"[A-Za-z]", ln):
            return ln[:200]
    return (lines[-1] if lines else "")[:200]


def normalize_signature(line: str) -> str:
    """Numbers/quoted-names normalized so identical failure shapes cluster."""
    sig = re.sub(r"\d+", "N", line)
    sig = re.sub(r"'[^']*'", "'X'", sig)
    sig = re.sub(r"`[^`]*`", "`X`", sig)
    return sig
