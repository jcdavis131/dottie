# Solo personal project, no connection to employer, built with public/free-tier only
"""The 6-stage validator — the chokepoint that keeps unsound LLM code off the GPU.

LLM-generated PyTorch is treated as untrusted input and passed through a strict fail-fast
hierarchy; the first failure short-circuits and its traceback is fed back to the implementation
model for a self-correction pass (capped retries).

    L1  syntax        ast.parse compiles to bytecode
    L2  contract      AST: a class with a ``forward`` method; no os/subprocess/shutil/sys
                      imports and no eval/exec/__import__ calls (untrusted code)
    L3  static        ruff --select=F821,E9 (undefined names, hallucinated methods, syntax)
    L4  dry-run       import the module, instantiate the nn.Module, run a CPU forward pass;
                      assert finite output, reject a degenerate constant-offset block, and
                      reject RANK COLLAPSE (right shape, every hidden feature identical)
    L5  integration_width  re-run the dry run at the width the block is actually swapped in
                      at (d_model), not the width the model declared for itself
    L6  residual_stream    re-run it on a NON-LEAF tensor that requires grad — what a block
                      in the residual stream actually receives, where `.grad` is None

L5 and L6 exist because candidates were passing every earlier level and then dying at
integration; replaying the stored failures, the six stages together catch 5 of 5 (TODOS
§5.3.R8/R10/R11). A stage that cannot run is reported ``skipped`` with the true reason.

Nothing here is fabricated: a level that cannot run (e.g. ruff or torch absent) is reported as
``skipped`` with the true reason — never counted as a pass.
"""

from __future__ import annotations

import ast
import difflib
import re
import shutil as _shutil  # for which() only; generated code may not import shutil
import inspect
import subprocess
import tempfile
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Imports a generated training module must never contain (untrusted code hygiene, per spec).
ILLEGAL_IMPORTS = frozenset({"os", "subprocess", "shutil", "sys", "socket", "ctypes"})
ILLEGAL_CALLS = frozenset({"eval", "exec", "__import__", "compile", "open"})

#: Ordered stages. Keep in step with `validate()` — anything iterating this to
#: report coverage silently under-reports when a stage is added and not listed.
LEVELS = ("syntax", "contract", "static", "dry_run", "integration_width",
          "residual_stream")


@dataclass
class ValidationResult:
    """Outcome of a validation pass. ``ok`` iff every runnable level passed."""

    ok: bool
    level: str                       # the level that failed, or "dry_run" when all passed
    status: str                      # pass | fail | skipped
    detail: str = ""
    per_level: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def as_feedback(self) -> str:
        """The exact message handed back to the implementation LLM for self-correction.

        Appends a targeted repair hint when the failure matches a known class
        (diagnose_failure) — mined 2026-07-22 from the ledger's real failure
        population, where raw tracebacks alone left 59% of candidates dying at
        dry_run across every self-correction attempt."""
        base = (f"Validation failed at level '{self.level}' ({self.status}). "
                f"Detail:\n{self.detail}")
        hint = diagnose_failure(self.level, self.detail)
        return f"{base}\n\nREPAIR HINT:\n{hint}" if hint else base


# ---------------------------------------------------------------------------
# Failure diagnosis — targeted repair hints for the correction pass
# ---------------------------------------------------------------------------
# Mined from the ledger's real failed_validation population (2026-07-22, n=70):
# einsum subscript errors and tensor-shape algebra dominate dry_run deaths,
# then undeclared constructor args and unassigned self attributes. A raw
# traceback tells the corrector WHAT broke; these tell an 8B corrector HOW
# this class of candidate actually gets fixed. Pure, no I/O; an unknown
# failure gets no hint rather than a wrong one.
#
# Expanded 2026-07-23 from implementation.validation.history in the ledger copy
# (358 failed attempts across 100 experiments — the `failure` column truncates
# at ~567 chars, usually BEFORE the terminal exception line, so history is the
# real corpus; scripts/replay_hint_coverage.py measures coverage against it).
# Before the expansion, 103/358 attempts (28.8%) got no hint at all, and every
# syntax/static/contract failure was in that set.
_HINTS: tuple = (
    (r"einsum\(\)",
     "EINSUM REPAIR: the equation does not match the operands. Do not fiddle "
     "with the letters — REPLACE the einsum with explicit ops: reshape/view "
     "to split dims, torch.matmul for contractions, .transpose(-2, -1) to "
     "align. One op per line, and add `assert x.shape == (...)` after each."),
    (r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes|is invalid for input of size",
     "SHAPE-ALGEBRA REPAIR: track the shape symbolically through every line "
     "starting from [batch, seq, hidden]. This error means an op changed a "
     "dim you later treat as unchanged (usually a head split never merged "
     "back, or a matmul on unaligned dims). Add a shape assert after each "
     "reshape/matmul and merge heads back to [batch, seq, hidden] before the "
     "residual add."),
    (r"missing \d+ required positional argument",
     "CONSTRUCTOR CONTRACT: the module must be instantiable from the declared "
     "init_kwargs alone. Give EVERY extra __init__ parameter a default "
     "derived from the width (e.g. `d_k=None` then "
     "`self.d_k = d_k or d_model // n_heads`)."),
    (r"has no attribute '\w+'",
     "ATTRIBUTE REPAIR: forward() reads a `self.<name>` that __init__ never "
     "assigned (or the torch API does not exist). Assign every attribute in "
     "__init__ before use — submodules must be constructed there so their "
     "parameters register — and use only standard documented torch.nn "
     "modules (Linear, LayerNorm, GELU, Dropout, MultiheadAttention)."),
    (r"NameError: name",
     "UNDEFINED NAME: define it or import it (only torch / torch.nn / math "
     "style imports are permitted; no os/sys/subprocess)."),
    (r"NaN/Inf",
     "STABILITY REPAIR: add a small eps inside every sqrt/log/division, "
     "clamp attention logits (e.g. `logits.clamp(-30, 30)`) before softmax."),
    (r"degenerate block|RANK COLLAPSE|rank collapse",
     "CAPACITY REPAIR: the block must hold learnable parameters whose output "
     "varies per position AND per feature. Put at least one nn.Linear over "
     "the hidden dim in the main path — a scalar/bias offset cannot pass."),
    (r"the SAME \[batch, seq, hidden\] shape",
     "OUTPUT CONTRACT: return exactly one tensor with the input's shape. "
     "Project back to hidden size with a final nn.Linear; do not return "
     "tuples or attention maps."),
    # --- 2026-07-23 expansion: runtime-level classes, ordered by measured
    # attempt count (30/8/7/6 of 358). The bare `AssertionError:` catch-all is
    # LAST on purpose so every more specific class above it wins first.
    (r"does not require grad and does not have a grad_fn|"
     r"cannot register a hook on a tensor that doesn't require gradient|"
     r"grad can be implicitly created only for scalar outputs|"
     r"unexpected keyword argument 'retain_grad'",
     "NO-AUTOGRAD-IN-FORWARD: you called torch.autograd.grad/backward/"
     "register_hook on the input inside forward(). Validation runs under "
     "no_grad and a residual-stream block does not own a loss, so these "
     "calls can never succeed. Delete the autograd machinery and express "
     "the idea with quantities computable in forward: activation statistics "
     "(mean/std/norm of x), learnable nn.Parameter gates, or detached "
     "proxies."),
    (r"t\(\) expects a tensor with <= 2 dimensions",
     "BATCHED TRANSPOSE: .t() only works on 2-D matrices; your tensors are "
     "[batch, seq, hidden]. Use .transpose(-2, -1) (or .mT) for the last "
     "two dims; torch.matmul already broadcasts over batch."),
    (r"ImportError: cannot import name|ModuleNotFoundError: No module named",
     "IMPORT REALITY: einsum and logsumexp live at torch top level "
     "(torch.einsum, torch.logsumexp), NOT in torch.nn.functional; and no "
     "custom/third-party module exists in the sandbox. Only torch, "
     "torch.nn, torch.nn.functional and math are importable."),
    (r"Index tensor must have the same number of dimensions|"
     r"only integer tensors of a single element|"
     r"is out of bounds for dimension|selected index k out of range",
     "GATHER/TOPK REPAIR: gather needs an index tensor with the SAME ndim "
     "as the input (unsqueeze/expand it), topk k must not exceed the size "
     "of that dim (k = min(k, x.size(dim))), and boolean/float tensors "
     "cannot index — use long indices from topk/argmax."),
    (r"AssertionError:",
     "YOUR OWN ASSERT FIRED: the assertion text is yours. The validator "
     "instantiates from the declared init_kwargs and feeds a harness-chosen "
     "[batch, seq, hidden] input; derive every dimension from x.shape at "
     "forward time (b, s, h = x.shape) and delete asserts that encode a "
     "fixed batch/seq/hidden or constructor constants."),
)

# Level-scoped patterns, tried BEFORE the generic _HINTS. Two reasons this is
# keyed by level rather than folded into the flat list: (1) ruff and
# SyntaxError details QUOTE the offending source snippet, so a dry_run-oriented
# pattern (e.g. ``einsum\(\)``) could false-match code that merely appears in
# the quote — scoping makes the static/syntax classes win on their own levels;
# (2) it keeps the philosophy measurable: every entry fires only on text its
# level's checker actually emits. Deliberately NO unconditional per-level
# fallback — an unknown failure still gets no hint rather than a wrong one
# (that contract is test-encoded in test_validate_hints.py).
_LEVEL_HINTS: Dict[str, tuple] = {
    # ruff runs --select=F821,E9; the ledger's static failures are 100% F821
    # (43 of 43 attempts, 2026-07-23 mining — the single biggest hint-less class).
    "static": (
        (r"F821 Undefined name",
         "UNDEFINED NAME (static): ruff flagged a name that does not exist at "
         "that line. Three real causes in this loop: (1) missing import — add "
         "`import torch.nn as nn` / `import torch.nn.functional as F` / "
         "`from typing import Dict`; (2) typo or renamed variable — make the "
         "assignment and the use match exactly; (3) your previous output was "
         "TRUNCATED mid-identifier — rewrite the whole file, shorter, and "
         "finish every line."),
    ),
    # Every syntax-level message observed in the ledger (23/23 attempts), not
    # just the corruption cluster: the repair action — regenerate, don't patch —
    # is the same for all of them.
    "syntax": (
        (r"unexpected character after line continuation character|"
         r"was never closed|unterminated string literal|unmatched '|"
         r"invalid syntax|unexpected indent|"
         r"positional argument follows keyword argument|"
         r"expression cannot contain assignment|f-string: expecting",
         "MALFORMED SOURCE: the emitted file is corrupted — literal \\n text "
         "instead of real newlines, a line cut off mid-expression (unclosed "
         "bracket/string), or stray indentation. Do not patch the reported "
         "line: regenerate the ENTIRE file from scratch, shorter and simpler, "
         "with real newlines, ending on a complete line."),
    ),
    # check_contract emits exactly four problem shapes; the ledger's contract
    # failures are 25x skeleton + 12x loss-shaped (37/37 attempts).
    "contract": (
        (r"no 'forward' method found on any class|no class defined",
         "MODULE SKELETON: your rewrite lost the required structure. Emit "
         "exactly one `class <Name>(nn.Module):` with `def __init__` and "
         "`def forward(self, x)` taking ONE [batch, seq, hidden] tensor and "
         "returning one same-shape tensor. All logic inside methods; no bare "
         "functions, no top-level code."),
        (r"requires extra argument\(s\)",
         "LOSS-VS-BLOCK: your forward wants targets (or another extra input) "
         "— that makes it a LOSS, and a residual-stream block never sees "
         "labels. Re-express the idea as a transform of the hidden states "
         "alone: replace target-dependent terms with self-supervised proxies "
         "(statistics of x, activation-norm gates); any extra forward arg "
         "must have a default and never be required."),
        (r"illegal imports|illegal calls",
         "SANDBOX POLICY: generated code may not import os/subprocess/shutil/"
         "sys/socket/ctypes or call eval/exec/__import__/compile/open. Delete "
         "them — a residual-stream block needs only torch, torch.nn, "
         "torch.nn.functional and math."),
    ),
}


def check_self_attributes(code: str) -> List[str]:
    """Static warnings: ``self.<name>`` read in a method but never assigned in
    the class and not a method/class attribute. Advisory ONLY — dynamic
    assignment patterns exist, so this must never gate; it annotates the
    correction feedback so the model fixes the missing assignment in the same
    pass instead of discovering it via AttributeError next attempt."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    warnings: List[str] = []
    # attributes nn.Module provides that generated code legitimately reads
    module_builtins = {"training"}
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        assigned: set = set()
        methods: set = set()
        reads: Dict[str, str] = {}
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.add(item.name)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        assigned.add(t.id)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                assigned.add(item.target.id)
        for node in ast.walk(cls):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                if isinstance(node.ctx, ast.Store):  # covers Assign + AugAssign targets
                    assigned.add(node.attr)
                elif isinstance(node.ctx, ast.Load):
                    reads.setdefault(node.attr, cls.name)
        # setattr(self, ...) makes static analysis unreliable — detect and stay silent:
        for node in ast.walk(cls):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr"):
                assigned.add("*dynamic*")
        if "*dynamic*" in assigned:
            continue  # setattr present — analysis unreliable for this class, stay silent
        for attr, cname in reads.items():
            if attr not in assigned and attr not in methods and attr not in module_builtins:
                warnings.append(
                    f"{cname}: reads `self.{attr}` but never assigns it — "
                    f"set `self.{attr}` in __init__ before use")
    return warnings


def diagnose_failure(level: str, detail: str) -> str:
    """Targeted repair hint for a known failure class, or '' when unknown.

    Level-scoped patterns (_LEVEL_HINTS) run first, then the generic _HINTS;
    dry_run keeps its generic fallback. An unknown failure gets no hint
    rather than a wrong one."""
    for pattern, hint in _LEVEL_HINTS.get(level, ()) + _HINTS:
        if re.search(pattern, detail):
            return hint
    if level == "dry_run" and "Traceback" in detail:
        return ("GENERAL DRY-RUN REPAIR: mentally reproduce the validator — "
                "import the module, instantiate with ONLY the declared "
                "kwargs, run one [4, 16, 64] forward. Simplify until that "
                "passes: standard nn modules, explicit shapes, no exotic ops.")
    return ""


# ---------------------------------------------------------------------------
# L1 — syntax
# ---------------------------------------------------------------------------

def check_syntax(code: str) -> ValidationResult:
    try:
        ast.parse(code)
    except SyntaxError as e:
        detail = f"SyntaxError on line {e.lineno}: {e.msg}\n{(e.text or '').rstrip()}"
        return ValidationResult(False, "syntax", "fail", detail)
    return ValidationResult(True, "syntax", "pass")


# ---------------------------------------------------------------------------
# L2 — AST contract
# ---------------------------------------------------------------------------

def _extra_required_forward_args(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """Required arguments of a ``forward`` def beyond ``self`` and the single input tensor."""
    a = fn.args
    positional = list(a.posonlyargs) + list(a.args)
    required = positional[:len(positional) - len(a.defaults)] if a.defaults else positional
    extra = [arg.arg for arg in required[2:]]  # beyond (self, hidden_states)
    extra += [k.arg for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    return extra


class _ContractChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_class = False
        self.has_forward = False
        self.forward_extra: Dict[str, List[str]] = {}   # class name -> extra required args
        self.illegal_imports: List[str] = []
        self.illegal_calls: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in ILLEGAL_IMPORTS:
                self.illegal_imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root in ILLEGAL_IMPORTS:
            self.illegal_imports.append(node.module or "")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.has_class = True
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "forward":
                self.has_forward = True
                self.forward_extra[node.name] = _extra_required_forward_args(item)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in ILLEGAL_CALLS:
            self.illegal_calls.append(fn.id)
        self.generic_visit(node)


def check_contract(code: str, *, class_name: Optional[str] = None) -> ValidationResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:  # pragma: no cover - L1 should have caught it
        return ValidationResult(False, "contract", "fail", f"unparseable: {e}")
    ck = _ContractChecker()
    ck.visit(tree)
    problems: List[str] = []
    if not ck.has_class:
        problems.append("no class defined (expected an nn.Module subclass)")
    if not ck.has_forward:
        problems.append("no 'forward' method found on any class")
    # A drop-in sequence block's forward takes exactly one input tensor. A regularizer-style
    # forward(x, gradients) can NEVER pass dry-run or integrate into the factory model, so an
    # extra required arg fails here in milliseconds — before any model correction round-trips
    # burn on an unfixable signature (observed live, 6483a5daea94). Scoped to the declared
    # class: helper submodules may legitimately take extra arguments.
    # With no declared class_name this used to look up forward_extra[""], find nothing, and
    # silently skip the check — a gate that does not run reading exactly like a gate that
    # passed (the §5.3.R15 invariant, in a place that predates it). Measured 2026-07-20:
    # 0 of 96 stored candidates omit class_name, so this is defensive, not a live bug. But
    # an unscoped check should widen to every class rather than quietly vanish.
    if class_name:
        extra = ck.forward_extra.get(class_name)
    else:
        extra = next((v for v in ck.forward_extra.values() if v), None)
    if extra:
        problems.append(
            f"forward() of {class_name} requires extra argument(s) {extra} beyond the single "
            "hidden-states tensor — a drop-in block's forward must accept exactly one "
            "[batch, seq, hidden] input; give them defaults or restructure the idea as a block")
    if ck.illegal_imports:
        problems.append(f"illegal imports (untrusted-code policy): {sorted(set(ck.illegal_imports))}")
    if ck.illegal_calls:
        problems.append(f"illegal calls (untrusted-code policy): {sorted(set(ck.illegal_calls))}")
    if problems:
        return ValidationResult(False, "contract", "fail", "; ".join(problems))
    return ValidationResult(True, "contract", "pass")


# ---------------------------------------------------------------------------
# L3 — static analysis (ruff)
# ---------------------------------------------------------------------------

def run_linter(file_path: str | Path) -> ValidationResult:
    ruff = _shutil.which("ruff")
    if ruff is None:
        return ValidationResult(True, "static", "skipped",
                                "ruff not installed — static analysis skipped (not a pass)")
    try:
        proc = subprocess.run(
            [ruff, "check", str(file_path), "--select=F821,E9", "--no-cache", "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:  # pragma: no cover - env dependent
        return ValidationResult(True, "static", "skipped", f"ruff could not run: {e}")
    if proc.returncode != 0:
        return ValidationResult(False, "static", "fail",
                                (proc.stdout or proc.stderr or "ruff reported issues").strip())
    return ValidationResult(True, "static", "pass")


# ---------------------------------------------------------------------------
# L4 — CPU dry-run
# ---------------------------------------------------------------------------

def _find_torch():
    try:
        import torch  # noqa: F401
        return torch
    except Exception:
        return None


def _select_class(module: Any, class_name: Optional[str], torch) -> Any:
    if class_name is not None:
        cls = getattr(module, class_name, None)
        if cls is None:
            raise LookupError(f"class {class_name!r} not found in generated module")
        return cls
    # Fall back to the first nn.Module subclass defined in the module.
    candidates = [
        v for v in vars(module).values()
        if isinstance(v, type) and issubclass(v, torch.nn.Module) and v is not torch.nn.Module
    ]
    if not candidates:
        raise LookupError("no nn.Module subclass found in generated module")
    return candidates[0]


def dry_run_module(file_path: str | Path, *, class_name: Optional[str] = None,
                   init_kwargs: Optional[Dict[str, Any]] = None,
                   input_shape: Optional[List[int]] = None,
                   width: Optional[int] = None) -> ValidationResult:
    """Import + instantiate + one CPU forward pass, asserting a finite output.

    ``init_kwargs`` and ``input_shape`` come from the experiment's declared dry-run spec; both
    default to a small, fast shape so validation is cheap. A module that needs undeclared
    constructor args is a real defect and fails here (drop-in modules must be instantiable)."""
    torch = _find_torch()
    if torch is None:
        return ValidationResult(True, "dry_run", "skipped",
                                "torch not installed — CPU dry-run skipped (not a pass)")
    import importlib.util
    init_kwargs = dict(init_kwargs or {})
    # The declared shape is untrusted model output ([-1, -1, 8] observed live): a junk dim
    # would fail torch.randn no matter how good the code is, so fall back per-dimension.
    raw = list(input_shape) if input_shape and len(list(input_shape)) == 3 else [4, 16, 64]
    shape = [d if isinstance(d, int) and not isinstance(d, bool) and d > 0 else dflt
             for d, dflt in zip(raw, (4, 16, 64))]
    mod_name = f"dottie_research_candidate_{uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
        if spec is None or spec.loader is None:
            return ValidationResult(False, "dry_run", "fail", f"cannot load module {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # import-time errors surface here
        cls = _select_class(module, class_name, torch)
        if width is not None:
            # Override by the CONSTRUCTOR SIGNATURE, not by what the model happened to
            # declare — exactly what factory_trainer._make_candidate does at swap time. A
            # candidate relying on its own default width declares no dim kwarg at all, so
            # keying off init_kwargs would leave it narrow and then blame it for the shape
            # mismatch we caused.
            try:
                _params = inspect.signature(cls.__init__).parameters
            except (TypeError, ValueError):
                _params = {}
            for _name in _DIM_KWARGS:
                if _name in _params:
                    init_kwargs[_name] = width
            shape = [shape[0], shape[1], int(width)]
        with torch.no_grad():
            layer = cls(**init_kwargs)
            # Seeded: validation must be reproducible. An unseeded probe made the
            # degeneracy verdict depend on the draw (measured 2026-07-20).
            dummy = torch.randn(*shape, generator=torch.Generator().manual_seed(1234))
            output = layer(dummy)
        out_t = output[0] if isinstance(output, (tuple, list)) else output
        if not torch.is_tensor(out_t):
            return ValidationResult(False, "dry_run", "fail",
                                    f"forward returned {type(out_t).__name__}, not a tensor")
        if tuple(out_t.shape) != tuple(dummy.shape):
            # The integration contract (see the ideation prompt): a drop-in sequence block maps
            # [batch, seq, hidden] -> [batch, seq, hidden]. Catching it here gives the
            # correction pass a crisp message instead of a downstream integration traceback.
            return ValidationResult(
                False, "dry_run", "fail",
                f"forward returned shape {tuple(out_t.shape)} for input {tuple(dummy.shape)} — "
                "the integration contract requires a drop-in sequence block whose output has "
                "the SAME [batch, seq, hidden] shape as its input")
        if torch.isnan(out_t).any() or torch.isinf(out_t).any():
            return ValidationResult(False, "dry_run", "fail",
                                    "forward produced NaN/Inf — add clamping or an eps term")

        # Degeneracy gate (added 2026-07-20 after the MLBR post-mortem, TODOS §5.3.R).
        # MLBR passed all four levels that existed at the time (there are six stages now)
        # while being a no-op: zero learnable parameters and a
        # forward of `x + scalar`. Such a block cannot express anything a bias term can't,
        # can never learn to, and at smoke scale "wins" merely by REPLACING a real block.
        # The check is deliberately narrow — it fires only when BOTH are true, so the
        # legitimate zero-init pattern (identity at init but parameterized, e.g. LayerScale)
        # still passes.
        n_params = sum(int(p.numel()) for p in layer.parameters() if p.requires_grad)
        delta = out_t - dummy
        delta_std = float(delta.std())
        # Scale-aware, NOT an absolute epsilon: `x + c` in float32 leaves rounding noise
        # proportional to |c| (~5e-7 for c≈4.7), which an absolute 1e-6 bar mistook for a
        # real transform — the gate was flaky on unseeded input until this was measured.
        # "Constant shift" = the variation is negligible RELATIVE to the shift itself.
        const_tol = max(1e-6, 1e-4 * abs(float(delta.mean())))
        if n_params == 0 and delta_std <= const_tol:
            return ValidationResult(
                False, "dry_run", "fail",
                f"degenerate block: {n_params} learnable parameters and output differs from "
                f"input by a CONSTANT (std of (out-in) = {delta_std:.3g}). This is a bias, not "
                "an architecture — it cannot express or learn anything, and swapping it in for "
                "a real block only removes capacity. Give the module learnable parameters or "
                "make its transform input-dependent.")

        # Rank collapse across the hidden dim. A block can return the CORRECT shape and
        # still have destroyed everything in it: `x.sum(-1).unsqueeze(-1).expand_as(x)`
        # broadcasts one scalar per position, so every feature is identical and the
        # residual stream is gone. Shape checks pass, the degeneracy check above passes
        # (the difference is not constant), and it reaches training.
        #
        # Measured 2026-07-20 (TODOS §5.3.R11) on 694633b2d354 — a loss function misfiled
        # as a block: mean std across hidden = 0.0 exactly, against 0.34 for a healthy
        # block and 1.02 for MLBR. The signal is well separated, not a threshold guess.
        #
        # Stated as DESTRUCTION, not as a property of the output alone: the gate fires
        # only when the input had hidden-dim structure and the output does not, so a block
        # legitimately handed flat input is never blamed for it.
        in_spread = float(dummy.std(dim=-1).mean())
        out_spread = float(out_t.std(dim=-1).mean())
        if in_spread > 1e-6 and out_spread <= 1e-6:
            return ValidationResult(
                False, "dry_run", "fail",
                f"rank collapse: the output has the right shape but is CONSTANT along the "
                f"hidden dimension (mean std across hidden = {out_spread:.3g}, input was "
                f"{in_spread:.3g}). Every feature position holds the same value, so the "
                "block has erased the residual stream it was handed — a scalar broadcast "
                "back to [batch, seq, hidden] is not a block. If the idea is a loss or a "
                "regulariser, it is not a drop-in block; express it as a transform of the "
                "hidden states that preserves per-feature information.")

        # A block with NO learnable parameters is a fixed function. It replaces a real
        # ~787 K-parameter block in the residual stream, so at fixed steps it can "win" by
        # shrinking the model rather than by being a better idea — the capacity confound
        # already documented in TODOS §5.3.R, and exactly how MLBR became a false SOTA.
        #
        # Measured 2026-07-20 (§5.3.R17): 11 of 20 candidates that passed validation had
        # zero learnable parameters — 55%. Their outcomes: 8 rejected, 2 failed_training,
        # and 1 "sota" (MLBR, an artifact). ZERO real wins, against real training compute.
        #
        # Deliberately a CORRECTABLE failure, not a silent kill: the message tells the
        # model what to change, and the self-correction loop gets to fix the candidate
        # rather than lose the idea. Many of these are decent ideas expressed without any
        # parameters to learn.
        if n_params == 0:
            return ValidationResult(
                False, "dry_run", "fail",
                "no learnable parameters: this block is a FIXED function, so it cannot "
                "learn anything from training. It also replaces a real parameterised block "
                "in the residual stream, which means any apparent win at fixed steps may "
                "just be the model getting smaller — that confound produced this loop's "
                "one false SOTA. Keep the idea and give it capacity: make the quantities "
                "you compute (scales, gates, thresholds, mixing weights) into "
                "nn.Parameter/nn.Linear that the LM loss can train, instead of fixed "
                "floats.")
    except Exception:
        return ValidationResult(False, "dry_run", "fail", traceback.format_exc())
    return ValidationResult(True, "dry_run", "pass",
                            f"forward ok on input {shape} -> {tuple(out_t.shape)}; "
                            f"learnable_params={n_params}, delta_std={delta_std:.4g}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def validate(code: str, *, class_name: Optional[str] = None,
             init_kwargs: Optional[Dict[str, Any]] = None,
             input_shape: Optional[List[int]] = None,
             workdir: Optional[str | Path] = None) -> ValidationResult:
    """Run L1->L4 fail-fast. Returns the first failure, or the (passing) dry-run result."""
    per_level: Dict[str, Dict[str, str]] = {}

    def record(r: ValidationResult) -> ValidationResult:
        per_level[r.level] = {"status": r.status, "detail": r.detail}
        r.per_level = per_level
        return r

    r = record(check_syntax(code))
    if not r.ok:
        return r
    r = record(check_contract(code, class_name=class_name))
    if not r.ok:
        return r

    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="dottie_validate_"))
    tmp.mkdir(parents=True, exist_ok=True)
    candidate = tmp / f"candidate_{uuid.uuid4().hex[:8]}.py"
    candidate.write_text(code, encoding="utf-8")

    r = record(run_linter(candidate))
    if not r.ok:
        return r
    r = record(dry_run_module(candidate, class_name=class_name, init_kwargs=init_kwargs,
                              input_shape=input_shape))
    if not r.ok:
        return r
    # The width probe only changes the verdict when it FAILS. On success keep the declared
    # dry-run as the canonical result so its detail (learnable_params, delta_std — what the
    # degeneracy gate and the write-ups read) survives; the probe is still recorded in
    # per_level, so a reader can see it ran.
    wide = record(dry_run_at_integration_width(candidate, class_name=class_name,
                                               init_kwargs=init_kwargs,
                                               input_shape=input_shape))
    if not wide.ok:
        return wide
    stream = record(dry_run_in_residual_stream(candidate, class_name=class_name,
                                               init_kwargs=init_kwargs,
                                               input_shape=input_shape))
    return r if stream.ok else stream


# A corrector turns (previous code, failure feedback) into a new code attempt. The real one is
# the implementation LLM; tests pass a deterministic stand-in.
Corrector = Callable[[str, str], str]


@dataclass
class CorrectionOutcome:
    ok: bool
    code: str
    attempts: int
    result: ValidationResult
    history: List[Dict[str, Any]] = field(default_factory=list)


#: Hidden width the candidate is actually swapped in at (``model.d_model`` for the factory
#: nano config). The declared dry-run shape is whatever the model wrote in its own JSON —
#: almost always 64 — so a candidate that hardcodes head counts, reshapes, or projection
#: sizes to *that* width validates clean and then explodes at integration.
INTEGRATION_WIDTH = 256

#: Sequence length the block is actually trained at (`factory_trainer` config default).
#: The declared dry-run shape uses a tiny seq (16 is typical), so a parameter sized to the
#: SEQUENCE — a learned positional table, an attention bias, a fixed-length buffer — is
#: built at the wrong length, passes every stage, and dies at training. Measured 2026-07-20
#: (TODOS §5.3.R28) on 670ad9956bab: `AssertionError: seq (256) must match seq_len (16)`,
#: from a candidate that had declared `positional_weights: nn.Parameter((seq_len, hidden))`.
#: This is the sequence-axis twin of the width bug in §5.3.R8.
INTEGRATION_SEQ = 256

#: Constructor kwargs that mean "hidden width", kept in step with factory_trainer's
#: ``_DIM_KWARGS``. Duplicated rather than imported: validate.py is deliberately free of
#: factory imports so it stays runnable without the factory checkout present.
_DIM_KWARGS = ("d_model", "dim", "hidden", "hidden_dim", "hidden_size", "embed_dim",
                "input_dim", "n_embd", "channels", "width")


def dry_run_at_integration_width(file_path: str | Path, *, class_name: Optional[str] = None,
                                 init_kwargs: Optional[Dict[str, Any]] = None,
                                 input_shape: Optional[List[int]] = None,
                                 width: int = INTEGRATION_WIDTH,
                                 seq: int = INTEGRATION_SEQ) -> ValidationResult:
    """Re-run the dry run at the width the factory will actually use.

    Measured 2026-07-20 (TODOS §5.3.R8): validation ran at the model's self-declared
    ``input_shape`` (hidden=64) while ``factory_trainer`` swaps the block into a model with
    ``d_model=256``, overriding dim-like constructor kwargs on the way. Candidates that
    hardcode a head count, a reshape, or a projection size to 64 therefore passed every
    level and died at integration — **4 of the 5 stored `failed_training` records**, e.g.
    ``shape '[2,16,8,64]' is invalid for input of size 8192`` and ``candidate changed shape
    [2,16,256]->[2,16,1]``. Each of those cost a full model build plus an integration probe
    to discover something a second dry run finds in about a second.

    Skipped (as a pass, honestly reported) when the declared shape is already this width or
    is not a 3-D ``[batch, seq, hidden]`` shape."""
    shape = list(input_shape or [4, 16, 64])
    # Entries are whatever the model emitted: symbolic placeholders like "hidden" and
    # "batch" show up in real records, so this must never assume they are ints. (Caught by
    # replaying stored candidates: `int('hidden')` raised straight out of validate() and
    # would have broken the level for every candidate declaring a symbolic shape.)
    if len(shape) != 3 or not all(isinstance(d, int) or (isinstance(d, str) and d.isdigit())
                                  for d in shape):
        return ValidationResult(True, "integration_width", "skipped",
                                f"declared input_shape {shape} is not a numeric "
                                "[batch, seq, hidden] — cannot re-probe at the integration width")
    shape = [int(d) for d in shape]
    # Probe the real INTEGRATION SHAPE: the model's own seq is typically 16 while training
    # runs at 256, so a seq-sized parameter (learned positional table, attention bias,
    # fixed-length buffer) is built at the wrong length and only fails once training starts.
    target = [shape[0], int(seq), int(width)]
    if shape == target:
        return ValidationResult(True, "integration_width", "skipped",
                                f"declared shape already matches the integration shape "
                                f"{target}")
    r = dry_run_module(file_path, class_name=class_name, init_kwargs=dict(init_kwargs or {}),
                       input_shape=target, width=int(width))
    if r.status == "skipped":
        # Inherit "skipped", never launder it into "pass". The inner result's own detail
        # says "(not a pass)" — reporting status="pass" over the top of that was a direct
        # self-contradiction, and the same false-clean bug as §5.3.R14 in a second place.
        # A stage that could not run must say so, or the per_level record overstates
        # coverage exactly where coverage is missing.
        return ValidationResult(True, "integration_width", "skipped",
                                f"integration-width probe could not run: {r.detail}")
    if r.ok:
        return ValidationResult(True, "integration_width", "pass",
                                f"also runs at the integration width {width}: {r.detail}")
    return ValidationResult(
        False, "integration_width", "fail",
        f"passes at the declared shape {shape} but FAILS at the real integration shape "
        f"{target}: [batch, seq={seq}, hidden={width}] is what this block is actually "
        f"swapped in at. Do not size anything to the dry-run shape — derive the hidden dim "
        f"from x.shape[-1] and the sequence length from x.shape[-2] at FORWARD time. In "
        f"particular a parameter shaped to a fixed sequence length (a learned positional "
        f"table, an attention bias, a preallocated buffer) cannot work here: make it "
        f"length-agnostic, or slice/interpolate it to the input length.\n{r.detail}")


def dry_run_in_residual_stream(file_path: str | Path, *, class_name: Optional[str] = None,
                               init_kwargs: Optional[Dict[str, Any]] = None,
                               input_shape: Optional[List[int]] = None,
                               width: int = INTEGRATION_WIDTH) -> ValidationResult:
    """Probe with an input shaped like a real mid-network activation, not a fresh tensor.

    The standard dry run feeds a **leaf** tensor with ``requires_grad=False`` under
    ``no_grad``. A block in the residual stream never sees that: its input is a **non-leaf**
    activation that *does* require grad. The difference is not cosmetic — a candidate that
    reads ``x.grad`` gets a populated tensor in the probe and ``None`` in production, because
    ``.grad`` is only populated on leaves.

    Measured 2026-07-20 (TODOS §5.3.R10): two of the five stored `failed_training` records
    died exactly here — ``'NoneType' object has no attribute 'abs'`` and ``... 'layout'`` —
    after passing every validation level, including the integration-width probe. Both are
    caught in about a second by handing the module the kind of tensor it will actually get.

    Gradient-inspecting "regularizer" ideas are a large slice of what this loop proposes, so
    this is not an exotic corner: it is the shape of the search space."""
    torch = _find_torch()
    if torch is None:
        return ValidationResult(True, "residual_stream", "skipped",
                                "torch not installed — residual-stream probe skipped")
    # Same sanitation as dry_run_module: the declared shape is untrusted model output, and
    # junk dims ([-1, -1, 8] observed live) must fall back per-dimension rather than blow up
    # torch.randn. Only the batch/seq dims are taken from it; the width is ours.
    raw = list(input_shape) if input_shape and len(list(input_shape)) == 3 else [4, 16, 64]
    shape = [d if isinstance(d, int) and not isinstance(d, bool) and d > 0 else dflt
             for d, dflt in zip(raw, (4, 16, 64))]
    shape = [int(shape[0]), int(shape[1]), int(width)]
    import importlib.util
    kwargs = dict(init_kwargs or {})
    mod_name = f"dottie_research_stream_{uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
        if spec is None or spec.loader is None:
            return ValidationResult(False, "residual_stream", "fail",
                                    f"cannot load module {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = _select_class(module, class_name, torch)
        try:
            params = inspect.signature(cls.__init__).parameters
        except (TypeError, ValueError):
            params = {}
        for name in _DIM_KWARGS:
            if name in params:
                kwargs[name] = int(width)
        layer = cls(**kwargs)
        # requires_grad=True makes it grad-carrying; the arithmetic makes it NON-leaf, which
        # is what actually empties `.grad`. Both halves matter.
        base = torch.randn(*shape, generator=torch.Generator().manual_seed(1234),
                           requires_grad=True)
        x = base * 1.0
        out = layer(x)
        out = out[0] if isinstance(out, (tuple, list)) else out
        if tuple(out.shape) != tuple(x.shape):
            return ValidationResult(
                False, "residual_stream", "fail",
                f"in the residual stream the block returned {tuple(out.shape)} for input "
                f"{tuple(x.shape)} — a drop-in block must return the SAME "
                "[batch, seq, hidden] shape")
        if not bool(torch.isfinite(out).all()):
            return ValidationResult(False, "residual_stream", "fail",
                                    "non-finite (NaN/Inf) output on a grad-carrying input")
    except Exception:
        return ValidationResult(
            False, "residual_stream", "fail",
            "fails when handed a REAL residual-stream activation (a non-leaf tensor that "
            "requires grad), though it passes on a plain leaf tensor. In the model your "
            "input is mid-network: `x.grad` is None there, and any op assuming otherwise "
            "breaks. Do not read `.grad` off the input — if you need gradient information, "
            "compute it inside forward with torch.autograd.grad on a tensor you created.\n"
            + traceback.format_exc()[-900:])
    return ValidationResult(True, "residual_stream", "pass",
                            f"runs on a grad-carrying non-leaf input at width {width}")


def _attempt_diff(before: str, after: str, *, max_lines: int = 60) -> str:
    """Unified diff of the model's OWN last edit (TODOS §5.2.c).

    The corrector previously saw only the traceback plus the current code, so it could not
    tell which of its edits had just failed — and near-greedy sampling then re-made the same
    edit. Showing the edit itself is the cheapest way to break that. Bounded so a full
    rewrite cannot flood the prompt; empty string when nothing changed (caller says so
    explicitly, which is a stronger signal than a silent no-op diff)."""
    lines = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile="previous_attempt", tofile="current_attempt", lineterm="", n=2))
    if not lines:
        return ""
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more diff lines omitted)"]
    return "\n".join(lines)


def validate_with_correction(code: str, corrector: Corrector, *, max_retries: int = 3,
                             class_name: Optional[str] = None,
                             init_kwargs: Optional[Dict[str, Any]] = None,
                             input_shape: Optional[List[int]] = None,
                             workdir: Optional[str | Path] = None) -> CorrectionOutcome:
    """Validate, and on failure hand the traceback back to ``corrector`` for up to ``max_retries``
    self-correction passes. Returns the first passing code, or the last failure honestly."""
    history: List[Dict[str, Any]] = []
    current = code
    attempts = 0
    result = validate(current, class_name=class_name, init_kwargs=init_kwargs,
                      input_shape=input_shape, workdir=workdir)
    history.append({"attempt": attempts, "ok": result.ok, "level": result.level,
                    "status": result.status, "detail": result.detail[:2000]})
    prev_failure: Optional[tuple] = None
    prev_attempt_code: Optional[str] = None
    while not result.ok and attempts < max_retries:
        attempts += 1
        feedback = result.as_feedback()
        # Advisory static warnings ride along with EVERY failure so the model
        # fixes latent AttributeErrors in the same pass instead of finding
        # them one dry-run death at a time (never a gate — see the docstring).
        attr_warnings = check_self_attributes(current)
        if attr_warnings:
            feedback += ("\n\nSTATIC WARNINGS (fix these in the same rewrite):\n- "
                         + "\n- ".join(attr_warnings[:6]))
        # Near-greedy sampling can regenerate the same broken fix forever (observed live,
        # f9256ee7c029: identical wrong output shape four times). When a correction lands on
        # EXACTLY the same failure, say so — a materially different prompt breaks the loop.
        if prev_failure == (result.level, result.detail):
            feedback += ("\n\nNOTE: your previous rewrite produced EXACTLY this same failure — "
                         "that approach does not fix it. Restructure the forward pass "
                         "differently this time; do not resubmit the same code.")
        # Show the model its own last edit (§5.2.c): the traceback says what broke, the diff
        # says what it just tried, and those are different questions.
        if prev_attempt_code is not None:
            d = _attempt_diff(prev_attempt_code, current)
            feedback += (
                f"\n\nYOUR PREVIOUS EDIT (unified diff) did NOT resolve the failure:\n{d}"
                if d else
                "\n\nNOTE: your previous rewrite was BYTE-IDENTICAL to the code before it — "
                "you did not change anything. Make a real, different change this time.")
        prev_failure = (result.level, result.detail)
        prev_attempt_code = current
        try:
            current = corrector(current, feedback)
        except Exception as e:  # corrector itself failed (e.g. LLM unreachable) — stop honestly
            history.append({"attempt": attempts, "corrector_error": repr(e)})
            break
        result = validate(current, class_name=class_name, init_kwargs=init_kwargs,
                          input_shape=input_shape, workdir=workdir)
        history.append({"attempt": attempts, "ok": result.ok, "level": result.level,
                        "status": result.status, "detail": result.detail[:2000]})
    return CorrectionOutcome(ok=result.ok, code=current, attempts=attempts, result=result,
                             history=history)
