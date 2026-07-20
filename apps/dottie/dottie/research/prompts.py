# Solo personal project, no connection to employer, built with public/free-tier only
"""Constrained prompts for the ideation and implementation workers.

Both prompts are deliberately rigid: an unconstrained "propose novel ML ideas" prompt regresses
to the mean of already-popular concepts, and an unconstrained "write the code" prompt produces
shape-mismatched, NaN-prone snippets. The ideation prompt fences the search space and forces a
math-first chain of thought; the implementation prompt enforces defensive, drop-in PyTorch. Both
demand a strict JSON object so the workers can parse the result deterministically.

The baseline block is injected from the REAL ledger baseline — the model solves *this* system's
current bottleneck, not a generic one.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from dottie.research.ledger import Baseline

# The three research sub-domains the ideation search space is fenced to. Kept compatible with the
# Ava architecture so the resulting diff can actually run in the automated loop.
DEFAULT_SEARCH_SPACE = [
    "Novel routing mechanisms for Sparse Mixture-of-Experts (MoE) that improve load balancing "
    "without an auxiliary-loss penalty.",
    "Alternative loss functions or regularizers that improve pre-training stability "
    "(fewer loss spikes, no NaN gradients).",
    "Modifications to the attention mechanism that reduce memory complexity while preserving "
    "exact representations.",
]

# Sampling temperatures for the two research completions: ideation is a SEARCH (a near-greedy
# temperature regenerates the same few ideas forever — observed live), implementation is code
# precision.
IDEATION_TEMPERATURE = 0.9
IMPLEMENTATION_TEMPERATURE = 0.2

# System prompt for the research workers' plain completions (OllamaPolicy.complete). The CodeAct
# agent protocol must NOT apply here — these prompts demand a bare JSON object, not agent turns.
RESEARCH_SYSTEM_PROMPT = (
    "You are an automated research worker in an ML experiment pipeline. Follow the user's "
    "instructions exactly. Respond with ONLY the JSON requested: no markdown fences, no prose "
    "before or after, and every string field must be valid JSON (escape backslashes in LaTeX)."
)

IDEATION_SCHEMA = {
    "hypothesis_name": "concise academic name",
    "theoretical_intuition": "2-3 sentences: the mechanism and why it solves the bottleneck",
    "mathematical_formulation": "exact LaTeX formulation of the change",
    "pytorch_implementation_strategy": "which nn.Module / autograd pieces to modify or create",
    "expected_outcome": "the specific metric that should improve",
    "search_domain": "which of the fenced sub-domains this belongs to",
    # Asked at IDEATION so capacity is decided before any code exists. Measured 2026-07-20
    # (TODOS §5.3.R17): 55% of candidates that passed validation had ZERO learnable
    # parameters — fixed functions that cannot learn, replacing a real ~787K-parameter
    # block. Naming the parameters up front is the cheapest point to catch that; the
    # validator catches it ~8 minutes later, after a full implement cycle.
    "learnable_parameters": "the nn.Parameter / nn.Linear tensors this block will TRAIN, "
                            "with shapes (e.g. 'gate: nn.Linear(hidden, hidden); scale: "
                            "nn.Parameter(hidden)'). A block with none is a fixed function "
                            "and will be rejected — it cannot learn, and replacing a "
                            "parameterised block with it shrinks the model.",
}

IMPLEMENTATION_SCHEMA = {
    "module_name": "the PyTorch class name (must subclass nn.Module and define forward)",
    "target_file": "repo-relative path, e.g. ava/models/experimental_routing.py",
    "code": "complete syntax-valid Python, with imports; a drop-in module",
    "init_kwargs": "JSON object of constructor kwargs to instantiate the module for the dry-run "
                   "(use small dims; {} if none)",
    "input_shape": "list[int] input shape for the CPU dry-run forward pass, e.g. [4, 16, 64]",
    "shape_assertions": "how the output shape was kept compatible with the baseline",
}


def _baseline_block(baseline: Optional[Baseline], bottleneck: str) -> str:
    if baseline is None:
        arch, metric = "(unset — no baseline seeded)", "(unset)"
    else:
        direction = "higher is better" if baseline.higher_is_better else "lower is better"
        arch = baseline.architecture
        metric = f"{baseline.metric_name} = {baseline.metric_value:.6g} ({direction})"
    return (f"- Architecture: {arch}\n"
            f"- Current baseline metric: {metric}\n"
            f"- Key bottleneck: {bottleneck}")


#: Words too generic to count as a search direction when tallying overused vocabulary.
_STOPWORDS = frozenset({"with", "from", "this", "that", "using", "based", "time", "via",
                        "and", "for", "the", "aware", "driven", "guided"})


def _failed_block(failed_names: List[str], *, show: int = 20) -> str:
    """Dead ends, plus an explicit tally of the vocabulary they keep reusing.

    Measured 2026-07-20 (TODOS §5.3.R24) on the live list of 20: "attention" appeared in
    13, "gradient" in 11, "sparse" in 9. Under a heading saying *do not repeat*, that is
    still 20 densely similar examples — which reads as a demonstration of the collapsed
    vocabulary rather than a prohibition on it, since models handle negation poorly and
    handle in-context patterns very well.

    Naming the overused terms converts an implicit anti-example into an explicit,
    checkable constraint the model can actually satisfy."""
    if not failed_names:
        return "(none yet)"
    shown = failed_names[:show]
    listing = "\n".join(f"- {n}" for n in shown)
    counts: Dict[str, int] = {}
    for name in shown:
        for word in set(re.findall(r"[a-z]+", name.lower())):
            if len(word) > 3 and word not in _STOPWORDS:
                counts[word] = counts.get(word, 0) + 1
    hot = [(w, c) for w, c in sorted(counts.items(), key=lambda kv: -kv[1])
           if c >= max(3, len(shown) // 4)][:6]
    if not hot:
        return listing
    terms = ", ".join(f"`{w}` ({c}/{len(shown)})" for w, c in hot)
    return (f"{listing}\n\n"
            f"OVERUSED TERMS in the failures above: {terms}. That is the region this search "
            f"has already exhausted — the names above are anti-examples, NOT a vocabulary to "
            f"draw from. Your proposals must avoid those words *and the mechanisms they "
            f"stand for*; a new name built from the same terms is the same dead end with a "
            f"new label. Go somewhere the list above does not reach.")


def ideation_prompt(baseline: Optional[Baseline], *, bottleneck: str,
                    search_space: Optional[List[str]] = None,
                    failed_hypotheses: Optional[List[str]] = None,
                    n_ideas: int = 1) -> str:
    """The rigidly-structured ideation system prompt, grounded in the real baseline."""
    space = search_space or DEFAULT_SEARCH_SPACE
    fenced = "\n".join(f"{i+1}. {s}" for i, s in enumerate(space))
    schema = json.dumps(IDEATION_SCHEMA, indent=2)
    plural = "s" if n_ideas != 1 else ""
    return f"""# ROLE AND OBJECTIVE
You are a Staff Research Scientist specializing in deep-learning architecture and LLM
pre-training. Generate {n_ideas} novel, mathematically sound, empirically testable hypothesis{plural}
to improve our current model architecture. Ideas must be publication-grade (ICLR/NeurIPS/ICML).
Do NOT suggest generic hyperparameter tuning, standard augmentations, or well-known methods
(standard AdamW, basic LoRA, standard Top-K routing).

# CURRENT SYSTEM STATE
Your hypothesis MUST attempt to improve these specific metrics / address this bottleneck:
{_baseline_block(baseline, bottleneck)}

# SEARCH SPACE CONSTRAINTS
Limit hypotheses strictly to these domains — nothing outside them:
{fenced}

INTEGRATION CONTRACT (hard): whatever the domain, the hypothesis MUST be implementable as ONE
drop-in PyTorch sequence-block module transforming [batch, seq, hidden] -> [batch, seq, hidden]
with no extra inputs (no labels, no losses from previous steps, no optimizer state). It will be
spliced into a transformer's residual stream and trained by the surrounding model's LM loss.
Ideas that need a custom loss signature or router-probability outputs are OUT OF SCOPE.

IF THE BOTTLENECK ABOVE SOUNDS LIKE A TRAINING-DYNAMICS OR GENERALISATION PROBLEM (loss
plateaus, a memorisation gap, overfitting), the honest answer to it is usually a loss term or
a schedule — and neither can be expressed here. Measured 2026-07-20 over 84 proposals: 36%
came back as a regulariser, penalty, or loss variant, every one of them unimplementable under
the contract above, and NONE produced a real win. That is a third of the search budget spent
on ideas that cannot be built. Do not spend yours there. Translate the goal into the block
instead — the block sees hidden states and nothing else, so it can only help by changing what
those states contain:
  - mixing/routing information differently across positions or channels
  - gating, sparsifying, or re-weighting features inside the transform
  - normalisation or reparameterisation applied to the hidden states
  - injecting structured noise or stochastic paths WITHIN forward
Concretely: "penalise attention entropy" is out of scope; "re-weight the block's own token
mixing by an entropy-derived gate computed from x" is in scope and targets the same effect.
A proposal whose mechanism only makes sense as an added term in the training objective is a
category error here, however good the idea is on its own.

EVERY BLOCK MUST HAVE SOMETHING TO LEARN. Measured 2026-07-20 over the candidates that
reached validation: 55% had ZERO learnable parameters — fixed functions built from constant
floats. They are rejected, because a block with no parameters cannot learn anything AND it
replaces a real ~787K-parameter block, so any apparent win at fixed steps may just be the
model getting smaller. If your mechanism computes a scale, gate, threshold, temperature or
mixing weight, make it an `nn.Parameter` or the output of an `nn.Linear` the LM loss can
train — not a fixed float in `__init__`. State them in `learnable_parameters`.

# DEAD ENDS (already tried and failed — do not repeat)
{_failed_block(failed_hypotheses or [])}

# MATHEMATICAL AND THEORETICAL RIGOR
- Define the forward-pass modification in standard mathematical notation.
- Explain the theoretical intuition for improved gradient flow, representational capacity, or
  compute efficiency vs. the baseline.
- If proposing a new loss term, give its derivative w.r.t. the network outputs; it must be
  differentiable and bounded.

# OUTPUT FORMAT
Respond with ONE JSON object (an array of objects if more than one idea) strictly matching this
schema. EVERY key is REQUIRED and must be non-empty. No markdown, no prose outside the JSON:
{schema}
"""


def implementation_prompt(hypothesis: Dict[str, Any], *,
                          codebase_note: str = "") -> str:
    """The senior-engineer implementation prompt that turns a hypothesis into drop-in PyTorch."""
    schema = json.dumps(IMPLEMENTATION_SCHEMA, indent=2)
    hjson = json.dumps({k: hypothesis.get(k) for k in IDEATION_SCHEMA}, indent=2)
    extra = f"\n{codebase_note}\n" if codebase_note else ""
    return f"""# ROLE AND OBJECTIVE
You are a Principal ML Engineer. Translate the theoretical hypothesis below into robust,
production-grade PyTorch for the Ava training pipeline. Prioritize tensor-shape integrity,
numerical stability, and modularity. Your code must compile on the first attempt.

# CODEBASE CONTEXT
- All custom layers/routers subclass `torch.nn.Module`.
- Custom losses are `nn.Module` classes or functions taking `(predictions, targets)` and
  returning a scalar tensor.
- The module must be SELF-CONTAINED: import only torch (and math/typing). Do NOT import
  or call any logging/telemetry helper — the training loop measures everything outside
  the module.{extra}

# ENGINEERING CONSTRAINTS
1. Shape integrity: document expected input/output shapes in every `forward` docstring
   (e.g. [batch, seq, hidden]); add `assert` statements around einsum / novel ops.
2. Numerical stability: add small `eps` to denominators, use `torch.logaddexp` where apt, and
   clamp probabilities to prevent NaN gradients.
3. Hardware efficiency: prefer vectorized ops; avoid Python for-loops over tensor dims.
4. Do NOT import os / subprocess / shutil / sys, and do not call eval / exec.
5. The module must be instantiable with the `init_kwargs` you declare and runnable on a CPU
   forward pass of the `input_shape` you declare.
6. Every `__init__` parameter after `self` MUST have a default value consistent with your
   declared `input_shape` (a required positional argument that `init_kwargs` omits is an
   automatic validation failure).
7. `forward` MUST accept exactly one tensor `[batch, seq, hidden]` and return the same shape.
8. AXIS DISCIPLINE (the single most common failure — 4 of the 4 most recent rejects died
   here). The input is 3-D: `batch = x.shape[0]`, `seq = x.shape[1]`, `hidden = x.shape[-1]`.
   - Size every weight against the HIDDEN axis (`x.shape[-1]`), never against `seq`. An error
     like "size of tensor a (512) must match tensor b (128) at dimension 2" means you built a
     weight for the wrong axis.
   - If your idea genuinely NEEDS the sequence length (a positional table, an attention bias,
     a decay mask), read it at FORWARD time as `x.shape[-2]` and build the tensor there — or
     store a generous maximum and SLICE it to `x.shape[-2]`. A parameter whose shape is fixed
     to the dry-run sequence length is dead on arrival: validation runs at a short sequence
     and the model trains at 256, so it will be built at the wrong length. Measured
     2026-07-20 — a candidate declared `nn.Parameter((seq_len, hidden))`, passed every
     validation stage, and raised `AssertionError: seq (256) must match seq_len (16)` on its
     first training step.
   - NEVER use `.T` or `torch.t()` on this tensor — they are 2-D only and raise
     "t() expects a tensor with <= 2 dimensions". Use `x.transpose(-2, -1)`.
   - EVERY `torch.einsum` subscript string must have ONE letter per dimension of each
     operand. The input is 3-D, so it is `"bsd,...->..."` — never a 2-letter subscript
     like `"sd"` for it. "einsum(): the number of subscripts in the equation (2) does not
     match the number of dimensions (3)" means you wrote a 2-D equation for a 3-D tensor.
     If you reshape to 2-D first, say so explicitly and reshape back before returning.
   - Assign EVERY attribute you later read (`self.hidden = hidden` in `__init__` if
     `forward` uses `self.hidden`) — "object has no attribute 'hidden'" is a real reject.
   - Prefer inferring `hidden` from the input at forward time over trusting a constructor
     default, so the module is correct at ANY declared `input_shape`.

# INPUT HYPOTHESIS
{hjson}

# OUTPUT FORMAT
Output ONE valid JSON object strictly matching this schema. No markdown outside the JSON. Provide
the COMPLETE replacement class/function, not a snippet:
{schema}
"""


def correction_prompt(previous_code: str, failure_feedback: str) -> str:
    """The self-correction message when generated code fails a validation level."""
    return f"""The previous implementation failed automated validation.

{failure_feedback}

Rewrite the COMPLETE module to resolve this specific issue while preserving the original
mathematical intent. Output ONE JSON object matching the implementation schema (module_name,
target_file, code, init_kwargs, input_shape, shape_assertions). No markdown outside the JSON.

# PREVIOUS CODE
{previous_code}
"""


# ---------------------------------------------------------------------------
# Robust JSON extraction (LLMs wrap JSON in prose / code fences despite instructions)
# ---------------------------------------------------------------------------

# Pairs (``\\``) must match atomically or the second backslash of a VALID escaped
# pair is misread as an invalid escape (caught by the existing fence test).
_ESCAPE_PAIR_OR_INVALID = re.compile(r'(\\\\)|(\\(?![\\"/bfnrtu]))')


def _escape_invalid_backslashes(s: str) -> str:
    """LaTeX in math fields arrives as raw ``\\alpha`` — an invalid JSON escape that
    kills the whole batch (observed live, ideation_raw_1784494765). Escaping only the
    INVALID sequences is deterministic and content-preserving."""
    return _ESCAPE_PAIR_OR_INVALID.sub(lambda m: m.group(1) or "\\\\", s)


def _salvage_truncated_array(s: str) -> Any:
    """A generation cut at the token limit leaves a half-emitted trailing element
    (observed live: ``{ \"hypo`` then EOF). Complete leading elements are real model
    output — salvage them by re-closing the array at the last complete ``}``. Bounded,
    parse-gated; returns None when nothing salvages."""
    if not s.lstrip().startswith("["):
        return None
    end = len(s)
    for _ in range(20):
        end = s.rfind("}", 0, end)
        if end <= 0:
            return None
        try:
            return json.loads(s[:end + 1] + "]")
        except json.JSONDecodeError:
            continue
    return None


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model response. Raises ValueError if none.

    Lenient passes (deterministic transport repairs, applied only after strict parsing
    fails): invalid-backslash escaping, then truncated-array salvage."""
    s = text.strip()
    # strip a ```json ... ``` fence if present
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    repaired = _escape_invalid_backslashes(s)
    if repaired != s:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    salvaged = _salvage_truncated_array(repaired)
    if salvaged is not None:
        return salvaged
    # scan for the first balanced {...} or [...] region (on the repaired text)
    s = repaired
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no parseable JSON object found in model response")


def parse_hypotheses(text: str) -> List[Dict[str, Any]]:
    """Parse ideation output into a list of hypothesis dicts (validating required keys)."""
    obj = extract_json(text)
    required = {"hypothesis_name", "theoretical_intuition", "mathematical_formulation",
                "pytorch_implementation_strategy", "expected_outcome"}
    if isinstance(obj, dict) and not (required & set(obj)):
        # Models sometimes wrap the list ({"hypotheses": [...]}) — observed live on qwen3:14b.
        # Unwrap the first list-of-dicts value; anything else still fails honestly below.
        wrapped = next((v for v in obj.values()
                        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)),
                       None)
        if wrapped is not None:
            obj = wrapped
    items = obj if isinstance(obj, list) else [obj]
    # Per-item wrappers ({"hypothesis": {...}}) — a single-key dict whose value is a dict
    # is unwrapped (observed live on qwen3:8b after the list-level fix; models invent one
    # nesting level at a time). Anything else still fails honestly below.
    items = [next(iter(it.values()))
             if isinstance(it, dict) and len(it) == 1 and not (required & set(it))
             and isinstance(next(iter(it.values())), dict) else it
             for it in items]
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        missing = required - set(it)
        if missing:
            # Canonical-key repair: models occasionally corrupt a key mid-word ("hypo,thesis_name",
            # observed live 2026-07-20). A missing required key is claimed from an existing key with
            # the same lowercase-alphanumeric skeleton — deterministic, fill-only, never overwrites.
            canon = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in it}
            for want in sorted(missing):
                got = canon.get(re.sub(r"[^a-z0-9]", "", want.lower()))
                if got is not None:
                    it[want] = it.pop(got)
            missing = required - set(it)
        if missing:
            raise ValueError(f"hypothesis missing required keys: {sorted(missing)}")
        out.append(it)
    if not out:
        raise ValueError("no valid hypotheses parsed")
    return out


def _parses(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _unescape_flat_code(code: str) -> str:
    """Deterministic, parse-gated transport repair for JSON-mangled code.

    Some models emit modules whose newlines survived as literal ``\\n`` two-character sequences
    (double escaping) — sometimes the whole module on one line, sometimes a mix of real and
    literal newlines from a partially escaped correction pass (both observed live, aea41c349279).
    Such code is guaranteed broken, so the repair is gated on exactly that: code that already
    parses is returned untouched (a ``\\nabla`` inside a comment stays intact), and a repaired
    candidate replaces it only when the candidate parses. The repair can never damage working
    code; unrepairable code passes through unchanged and fails at ``syntax`` honestly."""
    if "\\n" not in code or _parses(code):
        return code
    candidates: List[str] = []
    # JSON string semantics first (also fixes \" and \\). Raises harmlessly when the code has
    # real newlines (raw control chars in a JSON string) or JSON-invalid escapes like \d.
    try:
        candidates.append(json.loads('"' + code.replace('"', '\\"') + '"'))
    except json.JSONDecodeError:
        pass
    # Plain unescape — covers the mixed real+literal case and escapes JSON cannot decode.
    candidates.append(code.replace("\\n", "\n").replace("\\t", "\t"))
    for candidate in candidates:
        if _parses(candidate):
            return candidate
    return code


def parse_implementation(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse implementation output. Returns (implementation_record, dry_run_spec).

    dry_run_spec = {class_name, init_kwargs, input_shape} for the validator."""
    obj = extract_json(text)
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    if not isinstance(obj, dict) or "code" not in obj or not str(obj.get("code", "")).strip():
        raise ValueError("implementation missing non-empty 'code'")
    obj["code"] = _unescape_flat_code(str(obj["code"]))
    module_name = obj.get("module_name")
    init_kwargs = obj.get("init_kwargs") or {}
    if isinstance(init_kwargs, str):
        try:
            init_kwargs = json.loads(init_kwargs) if init_kwargs.strip() else {}
        except json.JSONDecodeError:
            init_kwargs = {}
    input_shape = obj.get("input_shape")
    if isinstance(input_shape, str):
        try:
            input_shape = json.loads(input_shape)
        except json.JSONDecodeError:
            input_shape = None
    impl = {
        "module_name": module_name,
        "target_file": obj.get("target_file"),
        "code": obj["code"],
        "shape_assertions": obj.get("shape_assertions"),
    }
    dry_run = {
        "class_name": module_name if isinstance(module_name, str) else None,
        "init_kwargs": init_kwargs if isinstance(init_kwargs, dict) else {},
        "input_shape": input_shape if isinstance(input_shape, list) else None,
    }
    return impl, dry_run
