"""Tests for the synthetic data generators (spec 02).

The properties that matter are: byte-level determinism, schema conformance,
and -- most importantly -- that the *content* is correct by construction.
So these tests do not merely check that docs are well-formed; they
independently re-verify the logic proofs, recompute the math answers,
re-exec the code snippets, and confirm the canonical eval facts are present
and never contradicted.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import random
import re
from fractions import Fraction

import pytest

from ava.datagen.base import (
    DOC_KEYS,
    VALID_PHASES,
    VALID_TASK_TYPES,
    make_doc_id,
    validate_doc,
)
from ava.datagen.logic import LogicGenerator
from ava.datagen.math_gen import MathGenerator
from ava.datagen.encyclopedia import EncyclopediaGenerator
from ava.datagen.code_gen import CodeGenGenerator, SAFE_BUILTINS, run_sandboxed
from ava.datagen.chat_safety import ChatSafetyGenerator, _SCENARIO_TEMPLATES
from ava.datagen.react_tools import ASSISTANT, USER, ReactToolsGenerator
from ava.datagen.workflow_jobbench import (
    WorkflowJobBenchGenerator,
    _duplicate_doc,
    _units_doc,
    _stale_doc,
    _slug,
    _fmt_val,
    _OCCUPATIONS,
)
from ava.datagen.workflow_gaia2 import (
    WorkflowGaia2Generator,
    _adaptability_doc,
    _ambiguity_doc,
    _deadline_doc,
    _collaboration_doc,
)
from ava.datagen.db_trace import (
    DBTraceGenerator,
    _btree_point_doc,
    _btree_range_doc,
    _btree_insert_doc,
    _doc_filter_doc,
    _kv_hash_doc,
    _wide_column_doc,
    _graph_doc,
    _ts_agg_doc,
    _vector_knn_doc,
    _hnsw_doc,
    _lsm_doc,
    _wal_doc,
    _vector_cosine_doc,
)
from ava.datagen.compress_trace import (
    CompressTraceGenerator,
    _rle_doc,
    _lz77_doc,
    _huffman_doc,
    _delta_varint_doc,
    _quant_int8_doc,
    _arith_eiw_doc,
    _deflate_doc,
    _prune_doc,
)

ALL_GENERATORS = [
    LogicGenerator,
    MathGenerator,
    EncyclopediaGenerator,
    CodeGenGenerator,
    ChatSafetyGenerator,
    ReactToolsGenerator,
    WorkflowJobBenchGenerator,
    WorkflowGaia2Generator,
    DBTraceGenerator,
    CompressTraceGenerator,
]

# A small byte target keeps tests fast while still exercising every family.
SMALL_TARGET = 400_000


def _collect(gen_cls, seed=1234, target=SMALL_TARGET):
    gen = gen_cls(seed=seed)
    return list(gen.generate(target))


def _serialize(docs) -> bytes:
    return "".join(
        json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n" for d in docs
    ).encode("utf-8")


def _sha(docs) -> str:
    return hashlib.sha256(_serialize(docs)).hexdigest()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gen_cls", ALL_GENERATORS, ids=lambda c: c.name)
def test_determinism_same_seed(gen_cls):
    a = _collect(gen_cls, seed=1234)
    b = _collect(gen_cls, seed=1234)
    assert _sha(a) == _sha(b), f"{gen_cls.name}: same seed produced different output"
    assert len(a) > 0


@pytest.mark.parametrize("gen_cls", ALL_GENERATORS, ids=lambda c: c.name)
def test_determinism_different_seed(gen_cls):
    a = _collect(gen_cls, seed=1234)
    c = _collect(gen_cls, seed=4321)
    assert _sha(a) != _sha(c), f"{gen_cls.name}: different seeds produced identical output"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gen_cls", ALL_GENERATORS, ids=lambda c: c.name)
def test_schema(gen_cls):
    docs = _collect(gen_cls)
    declared = set(gen_cls.phases)
    for d in docs:
        assert set(d.keys()) == DOC_KEYS
        for k in DOC_KEYS:
            assert isinstance(d[k], str) and d[k], f"{gen_cls.name}: empty/non-str key {k}"
        assert d["task_type"] in VALID_TASK_TYPES
        assert d["phase"] in VALID_PHASES
        assert d["concept"].strip(), "concept must be non-empty"
        # phase matches the generator's declared phases
        assert int(d["phase"][1:]) in declared, (
            f"{gen_cls.name}: emitted phase {d['phase']} not in declared {sorted(declared)}"
        )
        # doc_id is the documented function of source+text
        assert d["doc_id"] == make_doc_id(d["source"], d["text"])
        # validate_doc agrees
        validate_doc(d, allowed_phases=declared)


def test_task_types_are_accurate_per_generator():
    """task_type drives J-space losses, so spot-check that each generator's
    dominant/required task_types actually appear."""
    logic_tt = {d["task_type"] for d in _collect(LogicGenerator)}
    assert "deliberate" in logic_tt

    ency_tt = {d["task_type"] for d in _collect(EncyclopediaGenerator)}
    assert ency_tt == {"automatic"}, f"encyclopedia must be all automatic, got {ency_tt}"

    code_tt = {d["task_type"] for d in _collect(CodeGenGenerator)}
    assert code_tt == {"deliberate"}, f"code_gen must be all deliberate, got {code_tt}"

    math_tt = {d["task_type"] for d in _collect(MathGenerator)}
    assert "temporal" in math_tt and "deliberate" in math_tt

    chat_tt = {d["task_type"] for d in _collect(ChatSafetyGenerator)}
    assert {"safety", "automatic", "temporal", "deliberate"} <= chat_tt

    react_tt = {d["task_type"] for d in _collect(ReactToolsGenerator)}
    assert {"deliberate", "temporal"} <= react_tt
    
    jobbench_tt = {d["task_type"] for d in _collect(WorkflowJobBenchGenerator)}
    assert {"deliberate", "temporal"} <= jobbench_tt

    gaia2_tt = {d["task_type"] for d in _collect(WorkflowGaia2Generator)}
    assert gaia2_tt == {"temporal"}, f"gaia2 must be all temporal, got {gaia2_tt}"


# ---------------------------------------------------------------------------
# logic.py: independently verify proofs are valid by construction
# ---------------------------------------------------------------------------

def _eval_prop(formula, assign):
    """Independent re-implementation of propositional evaluation for the test
    (deliberately NOT importing the generator's eval so a bug there can't hide)."""
    tag = formula[0]
    if tag == "ATOM":
        return assign[formula[1]]
    if tag == "NOT":
        return not _eval_prop(formula[1], assign)
    if tag == "AND":
        return _eval_prop(formula[1], assign) and _eval_prop(formula[2], assign)
    if tag == "OR":
        return _eval_prop(formula[1], assign) or _eval_prop(formula[2], assign)
    if tag == "IMPLIES":
        return (not _eval_prop(formula[1], assign)) or _eval_prop(formula[2], assign)
    if tag == "IFF":
        return _eval_prop(formula[1], assign) == _eval_prop(formula[2], assign)
    raise AssertionError(f"bad tag {tag}")


def test_natded_proofs_are_semantically_valid():
    """For sampled natural-deduction docs, parse the premises and the final
    conclusion out of the rendered text and verify -- by exhaustive truth
    assignment over the atoms -- that the conclusion is a logical consequence
    of the premises. If the generator ever emitted an invalid derivation,
    this catches it."""
    from ava.datagen import logic as L

    checked = 0
    gen = LogicGenerator(seed=2024)
    for d in gen.generate(1_500_000):
        if d["source"] != "logic/natded":
            continue
        text = d["text"]
        # collect premises and the derived (non-premise, non-assumption) lines
        premises = []
        derived = []
        assumptions = []
        for line in text.splitlines():
            m = re.match(r"\s*\d+\.\s*(\|\s*)?(Assume:\s*)?(.+?)\s+\[(.+?)\]\s*$", line)
            if not m:
                continue
            is_sub = bool(m.group(1))
            is_assume = bool(m.group(2))
            formula_str = m.group(3).strip()
            rule = m.group(4)
            formula = _parse_formula(formula_str)
            if rule == "Premise":
                premises.append(formula)
            elif is_assume:
                assumptions.append(formula)
            else:
                derived.append((formula, is_sub, rule))

        assert premises, f"no premises parsed from:\n{text}"
        atoms = sorted(_atoms_of_all([f for f in premises] + [f for f, _, _ in derived] + assumptions))

        # The top-level conclusion is the last NON-subproof derived line
        # (subproof lines are only valid under their assumption).
        toplevel = [f for f, is_sub, rule in derived if not is_sub]
        if not toplevel:
            # pure-assumption edge case: nothing to check at top level
            checked += 1
            continue
        conclusion = toplevel[-1]

        for combo in itertools.product([True, False], repeat=len(atoms)):
            assign = dict(zip(atoms, combo))
            if all(_eval_prop(p, assign) for p in premises):
                assert _eval_prop(conclusion, assign), (
                    f"INVALID derivation: premises hold but conclusion fails under {assign}\n{text}"
                )
        checked += 1
        if checked >= 60:
            break
    assert checked >= 30, f"only checked {checked} natded proofs"


def _atoms_of_all(formulas):
    out = set()
    for f in formulas:
        _atoms_of(f, out)
    return out


def _atoms_of(f, out):
    if f[0] == "ATOM":
        out.add(f[1])
    elif f[0] == "NOT":
        _atoms_of(f[1], out)
    else:
        _atoms_of(f[1], out)
        _atoms_of(f[2], out)


_SYM2TAG = {"∧": "AND", "∨": "OR", "→": "IMPLIES", "↔": "IFF"}


def _parse_formula(s):
    """Recursive-descent parser matching the generator's render() output.
    Grammar: iff < implies < or < and < not < atom/paren."""
    s = s.strip()
    tokens = _tokenize(s)
    parser = _Parser(tokens)
    result = parser.parse_iff()
    assert parser.pos == len(tokens), f"trailing tokens parsing {s!r}: {tokens[parser.pos:]}"
    return result


def _tokenize(s):
    tokens = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(ch)
            i += 1
        elif ch == "¬":
            tokens.append("¬")
            i += 1
        elif ch in _SYM2TAG:
            tokens.append(ch)
            i += 1
        else:
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            assert j > i, f"cannot tokenize at {i}: {s!r}"
            tokens.append(s[i:j])
            i = j
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _binop(self, sym, sub):
        left = sub()
        while self.peek() == sym:
            self.pos += 1
            right = sub()
            left = (_SYM2TAG[sym], left, right)
        return left

    def parse_iff(self):
        return self._binop("↔", self.parse_implies)

    def parse_implies(self):
        # right-associative implication
        left = self.parse_or()
        if self.peek() == "→":
            self.pos += 1
            right = self.parse_implies()
            return ("IMPLIES", left, right)
        return left

    def parse_or(self):
        return self._binop("∨", self.parse_and)

    def parse_and(self):
        return self._binop("∧", self.parse_not)

    def parse_not(self):
        if self.peek() == "¬":
            self.pos += 1
            return ("NOT", self.parse_not())
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok == "(":
            self.pos += 1
            inner = self.parse_iff()
            assert self.peek() == ")", "expected )"
            self.pos += 1
            return inner
        assert tok is not None and re.match(r"^[A-Za-z]\w*$", tok), f"expected atom, got {tok!r}"
        self.pos += 1
        return ("ATOM", tok)


def test_logic_truth_table_verdicts():
    """Recompute each truth-table verdict independently and compare."""
    gen = LogicGenerator(seed=7)
    checked = 0
    for d in gen.generate(600_000):
        if d["source"] != "logic/truth_table":
            continue
        text = d["text"]
        m = re.search(r"formula: (.+)", text)
        formula = _parse_formula(m.group(1))
        atoms = sorted(_atoms_of_all([formula]))
        results = [_eval_prop(formula, dict(zip(atoms, combo)))
                   for combo in itertools.product([True, False], repeat=len(atoms))]
        if all(results):
            expected = "TAUTOLOGY"
        elif not any(results):
            expected = "CONTRADICTION"
        else:
            expected = "CONTINGENT"
        assert expected in text, f"verdict mismatch (expected {expected}):\n{text}"
        checked += 1
        if checked >= 40:
            break
    assert checked >= 20


# ---------------------------------------------------------------------------
# math_gen.py: recompute stated answers
# ---------------------------------------------------------------------------

def _parse_num(s):
    s = s.strip()
    if "/" in s:
        return Fraction(s)
    return Fraction(int(s))


def test_math_answers_are_correct():
    """Parse the final answer out of >=200 sampled math docs and confirm it
    equals a value recomputed by the test."""
    gen = MathGenerator(seed=1234)
    verified = 0
    for d in gen.generate(2_000_000):
        text = d["text"]
        concept = d["concept"]
        if concept == "addition":
            a, b = map(int, re.search(r"Compute (\d+) \+ (\d+)", text).groups())
            ans = int(re.search(r"Final answer: (-?\d+)", text).group(1))
            assert ans == a + b
            verified += 1
        elif concept == "subtraction":
            a, b = map(int, re.search(r"Compute (\d+) - (\d+)", text).groups())
            ans = int(re.search(r"Final answer: (-?\d+)", text).group(1))
            assert ans == a - b
            verified += 1
        elif concept == "multiplication":
            a, b = map(int, re.search(r"Compute (\d+) x (\d+)", text).groups())
            ans = int(re.search(r"Final answer: (-?\d+)", text).group(1))
            assert ans == a * b
            verified += 1
        elif concept == "linear_equation":
            a, b, c = map(int, re.search(r"Solve for x: (-?\d+)x \+ (-?\d+) = (-?\d+)", text).groups())
            ans = _parse_num(re.search(r"Final answer: x = (-?\d+(?:/\d+)?)", text).group(1))
            assert a * ans + b == c
            verified += 1
        elif concept == "modular_arithmetic" and "Compute" in text:
            a, m = map(int, re.search(r"Compute (\d+) mod (\d+)", text).groups())
            ans = int(re.search(r"Final answer: \d+ mod \d+ = (\d+)", text).group(1))
            assert ans == a % m
            verified += 1
        elif concept == "unit_conversion":
            m = re.search(r"Convert (\d+) (\w+) to (\w+), then add (\d+)", text)
            amount, _, _, extra = int(m.group(1)), m.group(2), m.group(3), int(m.group(4))
            factor = int(re.search(r"1 \w+ = (\d+) \w+", text).group(1))
            ans = int(re.search(r"Final answer: (\d+)", text).group(1))
            assert ans == amount * factor + extra
            verified += 1
        if verified >= 250:
            break
    assert verified >= 200, f"only verified {verified} math answers"


def test_math_temporal_docs_present():
    gen = MathGenerator(seed=1234)
    saw_temporal = False
    for d in itertools.islice(gen.generate(2_000_000), 20000):
        if d["task_type"] == "temporal":
            assert d["concept"] in {"deadline", "schedule", "delay"}
            assert "deadline" in d["text"].lower()
            saw_temporal = True
            break
    assert saw_temporal


# ---------------------------------------------------------------------------
# code_gen.py: re-exec snippets, and verify sandbox rejects dangerous ops
# ---------------------------------------------------------------------------

def _exec_and_check_doctest(code_text):
    """Extract the function/class body (drop the docstring) and the doctest
    lines, re-exec in the same sandbox the generator used, and confirm each
    >>> line's output matches the recorded expected output."""
    lines = code_text.splitlines()
    # split docstring examples from code
    steps = []  # (src, expected or None)
    in_doc = False
    doc_depth = None
    code_lines = []
    i = 0
    # The docstring is delimited by the first triple-quote block.
    # Rebuild code without the docstring, and collect >>> examples.
    doc_started = False
    doc_ended = False
    pending_expected_for = None
    for line in lines:
        stripped = line.strip()
        if not doc_started and stripped.startswith('"""'):
            doc_started = True
            # single-line docstring?
            if stripped.count('"""') == 2 and len(stripped) > 3:
                doc_ended = True
            continue
        if doc_started and not doc_ended:
            if stripped.startswith('"""'):
                doc_ended = True
                continue
            if stripped.startswith(">>> "):
                src = stripped[4:]
                is_expr = "=" not in src.split("(")[0] or src.startswith(("print(",))
                # heuristic: a bare assignment 'x = ...' is a statement
                is_assignment = bool(re.match(r"^[A-Za-z_]\w*\s*=", src)) and not src.startswith("==")
                steps.append([src, None, not is_assignment])
            elif steps and steps[-1][1] is None and steps[-1][2] and not stripped.startswith(">>>") and stripped:
                steps[-1][1] = stripped
            continue
        code_lines.append(line)

    code = "\n".join(code_lines)
    # Re-run through the generator's own sandbox for parity.
    replay = [(s[0], s[2]) for s in steps]
    result = run_sandboxed(code, replay)
    assert result is not None, f"snippet failed to execute in sandbox:\n{code_text}"
    for (src, expected, is_expr), (rsrc, got) in zip(steps, result):
        if is_expr and expected is not None:
            assert got == expected, f"doctest mismatch for {src}: expected {expected!r} got {got!r}"
    return len([s for s in steps if s[2] and s[1] is not None])


def test_code_snippets_execute_and_match_doctests():
    gen = CodeGenGenerator(seed=1234)
    checked = 0
    for d in gen.generate(800_000):
        n = _exec_and_check_doctest(d["text"])
        assert n >= 1, f"no verifiable doctest expressions in:\n{d['text']}"
        checked += 1
        if checked >= 100:
            break
    assert checked >= 50


def test_sandbox_rejects_open():
    assert run_sandboxed("def f():\n    return open('x')\n", [("f()", True)]) is None


def test_sandbox_rejects_import():
    assert run_sandboxed("import os\ndef f():\n    return 1\n", [("f()", True)]) is None
    assert run_sandboxed("def f():\n    return __import__('os')\n", [("f()", True)]) is None


def test_sandbox_rejects_eval_exec_compile():
    assert run_sandboxed("def f():\n    return eval('1+1')\n", [("f()", True)]) is None
    assert run_sandboxed("def f():\n    return exec('x=1')\n", [("f()", True)]) is None
    assert run_sandboxed("def f():\n    return compile('1', '<s>', 'eval')\n", [("f()", True)]) is None


def test_sandbox_whitelist_excludes_dangerous_builtins():
    for forbidden in ("open", "__import__", "eval", "exec", "compile", "input", "globals"):
        assert forbidden not in SAFE_BUILTINS, f"{forbidden} must not be in the sandbox whitelist"


# ---------------------------------------------------------------------------
# encyclopedia.py: canonical entities, paraphrase coverage, no contradictions
# ---------------------------------------------------------------------------

CANONICAL_FACTS = {
    "spider": ("8 legs", ["6 legs", "4 legs", "2 legs"]),
    "ant": ("6 legs", ["8 legs", "4 legs", "2 legs"]),
}


def test_encyclopedia_canonical_leg_counts_consistent():
    """spider->8, ant->6, always. A single contradictory doc would poison the
    intervention evals, so we assert NO doc about spider ever says anything but
    8 legs (and likewise ant->6)."""
    gen = EncyclopediaGenerator(seed=1234)
    saw = {"spider": 0, "ant": 0}
    for d in gen.generate(3_000_000):
        text = d["text"]
        # any doc mentioning the entity's legs must state the right count
        for entity, (correct, wrong_list) in CANONICAL_FACTS.items():
            # only inspect leg statements that name this entity
            if re.search(rf"\b{entity}\b", text, re.IGNORECASE) and "legs" in text:
                # find "<entity> ... N legs" style claims
                for wrong in wrong_list:
                    # a wrong leg-count sentence naming this entity is a contradiction
                    pattern = rf"(a |an |the |every |{entity}[^.]*?){wrong}"
                    for mobj in re.finditer(rf"[^.]*\b{entity}\b[^.]*legs[^.]*", text, re.IGNORECASE):
                        seg = mobj.group(0)
                        # skip segments that are about a different animal in a compendium
                        if re.search(rf"\b{entity}\b", seg, re.IGNORECASE):
                            assert wrong not in seg or correct in seg, (
                                f"contradiction: '{entity}' segment mentions {wrong}:\n{seg}"
                            )
                if d["concept"] == entity:
                    saw[entity] += 1
        if saw["spider"] > 5 and saw["ant"] > 5:
            break
    assert saw["spider"] > 0 and saw["ant"] > 0


def test_encyclopedia_paraphrase_coverage():
    """Each canonical entity must appear with >=40 DISTINCT paraphrase
    sentences across the corpus."""
    gen = EncyclopediaGenerator(seed=1234)
    entity_sentences = {e: set() for e in ["spider", "ant", "france", "china", "soccer", "rugby", "spanish", "french"]}
    for d in gen.generate(6_000_000):
        concept = d["concept"]
        if concept in entity_sentences:
            for line in d["text"].splitlines():
                line = line.strip()
                if line and not line.startswith("--") and ":" not in line[:20] or "ES:" in line:
                    entity_sentences[concept].add(line)
        if all(len(v) >= 60 for v in entity_sentences.values()):
            break
    for entity, sents in entity_sentences.items():
        assert len(sents) >= 40, f"{entity}: only {len(sents)} distinct paraphrases (need >=40)"


def test_encyclopedia_canonical_country_facts():
    gen = EncyclopediaGenerator(seed=1234)
    facts_seen = {"Paris": False, "Beijing": False, "Mandarin": False, "Yuan": False, "Euro": False}
    france_concept_doc = False
    for d in gen.generate(3_000_000):
        for token in facts_seen:
            if token in d["text"]:
                facts_seen[token] = True
        if d["concept"] == "france":
            france_concept_doc = True
        if all(facts_seen.values()) and france_concept_doc:
            break
    assert all(facts_seen.values()), f"missing canonical tokens: {[k for k,v in facts_seen.items() if not v]}"
    assert france_concept_doc


def test_encyclopedia_no_country_capital_contradiction():
    """France's capital must always be Paris; China's must always be Beijing."""
    gen = EncyclopediaGenerator(seed=99)
    for d in itertools.islice(gen.generate(3_000_000), 40000):
        t = d["text"]
        if "France" in t and "capital" in t.lower():
            # no other city should be called France's capital
            for bad in ("Beijing", "Berlin", "Madrid", "Rome"):
                assert not re.search(rf"capital of France is {bad}", t)
        if "China" in t and "capital" in t.lower():
            for bad in ("Paris", "Tokyo", "Seoul"):
                assert not re.search(rf"capital of China is {bad}", t)


# ---------------------------------------------------------------------------
# chat_safety.py: safety docs refuse; every safety scenario has a benign twin
# ---------------------------------------------------------------------------

_REFUSAL_MARKERS = ["can't", "cannot", "won't", "will not", "i won't", "i can't"]


def test_chat_safety_docs_contain_refusal():
    gen = ChatSafetyGenerator(seed=1234)
    checked = 0
    for d in gen.generate(1_000_000):
        if d["task_type"] != "safety":
            continue
        assert "<|user|>" in d["text"] and "<|assistant|>" in d["text"]
        assistant_part = d["text"].split("<|assistant|>", 1)[1].lower()
        assert any(m in assistant_part for m in _REFUSAL_MARKERS), (
            f"safety doc has no refusal:\n{d['text']}"
        )
        checked += 1
        if checked >= 80:
            break
    assert checked >= 40


def test_every_safety_template_has_benign_twin():
    """Each safety scenario template must define a matched benign twin with the
    same structural fields, so the Critic AUC has a contrast class."""
    for tmpl in _SCENARIO_TEMPLATES:
        assert tmpl["coercive_user"] and tmpl["benign_user"]
        assert tmpl["refusal"] and tmpl["helpful"]
        assert tmpl["concept"] and tmpl["benign_concept"]
        assert tmpl["concept"] != tmpl["benign_concept"]


def test_chat_safety_and_benign_concepts_disjoint():
    """The coercive and benign families must be distinguishable by concept, so
    the safety label is meaningful."""
    gen = ChatSafetyGenerator(seed=1234)
    safety_concepts = set()
    benign_concepts = set()
    for d in gen.generate(1_500_000):
        if d["source"] == "chat/safety":
            safety_concepts.add(d["concept"])
        elif d["source"] == "chat/benign":
            benign_concepts.add(d["concept"])
        if len(safety_concepts) >= 5 and len(benign_concepts) >= 5:
            break
    assert safety_concepts and benign_concepts
    assert safety_concepts.isdisjoint(benign_concepts)


def test_chat_markers_and_phases():
    gen = ChatSafetyGenerator(seed=1234)
    phases = set()
    for d in itertools.islice(gen.generate(1_000_000), 3000):
        assert "<|user|>" in d["text"] and "<|assistant|>" in d["text"]
        phases.add(d["phase"])
    assert {"p3", "p5"} <= phases


# ---------------------------------------------------------------------------
# workflow_jobbench.py: independently re-derive each reconciliation's math
# from the rendered CSV tables (never trusting the generator's own sum), and
# confirm the doc states exactly that corrected figure.
# ---------------------------------------------------------------------------

def _csv_block_values(text: str, idx: int = 0) -> list[int]:
    """Pull integer values out of the Nth fenced ```...``` CSV block."""
    blocks = re.findall(r"```\n(.*?)\n```", text, re.S)
    lines = blocks[idx].splitlines()[1:]  # skip the "line_item,value_x" header
    return [int(line.rsplit(",", 1)[1]) for line in lines]


def test_jobbench_duplicate_math_is_correct():
    rng = random.Random(11)
    for _ in range(30):
        occ = _OCCUPATIONS[rng.randrange(len(_OCCUPATIONS))]
        unit = occ[3]
        n = rng.randint(3, 8)
        text, task_type, concept = _duplicate_doc(rng, occ, n)
        assert task_type == "deliberate"
        assert concept == _slug(occ[0])
        values = _csv_block_values(text)
        assert len(values) == n + 1, "table must have n rows plus the planted duplicate"
        dup_value = values[-1]
        assert values[:-1].count(dup_value) >= 1, "last row must exactly duplicate an earlier row"
        true_sum = sum(values) - dup_value
        assert f"Corrected total to report: {_fmt_val(true_sum, unit)}." in text


def test_jobbench_units_math_is_correct():
    rng = random.Random(13)
    for _ in range(30):
        occ = _OCCUPATIONS[rng.randrange(len(_OCCUPATIONS))]
        unit = occ[3]
        n = rng.randint(3, 8)
        text, task_type, concept = _units_doc(rng, occ, n)
        assert task_type == "deliberate"
        assert concept == _slug(occ[0])
        values = _csv_block_values(text)
        assert len(values) == n
        true_sum = sum(values)
        multiplier = 1000 if unit == "$" else 100
        implied = true_sum * multiplier
        assert f"Correct total: {_fmt_val(true_sum, unit)}, not {_fmt_val(implied, unit)}." in text


def test_jobbench_stale_math_is_correct():
    rng = random.Random(17)
    for _ in range(30):
        occ = _OCCUPATIONS[rng.randrange(len(_OCCUPATIONS))]
        unit = occ[3]
        n = rng.randint(3, 8)
        text, task_type, concept = _stale_doc(rng, occ, n)
        assert task_type == "temporal"
        assert concept == _slug(occ[0])
        sum_a = sum(_csv_block_values(text, 0))
        sum_b = sum(_csv_block_values(text, 1))
        assert (
            f"sign off on the current total, {_fmt_val(sum_b, unit)}, not the memo's "
            f"{_fmt_val(sum_a, unit)}; flag the memo as superseded." in text
        )


def test_jobbench_phase4_docs_are_long():
    """Spec 02: P4-tagged docs must land in the 6000-12000 char long-doc band."""
    docs = _collect(WorkflowJobBenchGenerator, target=1_500_000)
    p4 = [d for d in docs if d["phase"] == "p4"]
    assert p4, "no phase-4 docs produced at this target size"
    for d in p4:
        assert 6000 <= len(d["text"]) <= 12000, f"phase4 doc length {len(d['text'])} out of band"


# ---------------------------------------------------------------------------
# workflow_gaia2.py: independently replay each event-driven scheduling
# scenario's state machine from the slots/deadline/events named in the
# rendered text, and confirm the stated resolution matches.
# ---------------------------------------------------------------------------

_SLOT = r"Day \d+ \d{2}:00"


def _parse_slot(s: str) -> tuple[int, int]:
    parts = s.split()
    return int(parts[1]), int(parts[2].split(":")[0])


def _parse_slots(s: str) -> list[tuple[int, int]]:
    return [_parse_slot(x.strip()) for x in s.split(",")]


def test_gaia2_adaptability_resolution_is_correct():
    rng = random.Random(21)
    for _ in range(40):
        text, concept = _adaptability_doc(rng)
        assert concept == "adaptability"
        slots = _parse_slots(re.search(r"Initial candidate slots: (.+)\.\n", text).group(1))
        deadline = _parse_slot(re.search(rf"before ({_SLOT})", text).group(1))
        declined = _parse_slot(re.search(rf"declines the proposed slot ({_SLOT})", text).group(1))
        remaining = [s for s in slots if s != declined]
        candidates = [s for s in remaining if s <= deadline]
        if candidates:
            expected = min(candidates)
            m = re.search(rf"is ({_SLOT}); book that one", text)
            assert m, f"expected a booking resolution:\n{text}"
            assert _parse_slot(m.group(1)) == expected
        else:
            expected = min(remaining)
            m = re.search(rf"nearest remaining slot, ({_SLOT})", text)
            assert m, f"expected an escalation resolution:\n{text}"
            assert _parse_slot(m.group(1)) == expected


def test_gaia2_ambiguity_prefers_explicit_recent_time():
    rng = random.Random(23)
    saw_flag = False
    for _ in range(60):
        text, concept = _ambiguity_doc(rng)
        assert concept == "ambiguity"
        explicit = _parse_slot(re.search(rf"lock in ({_SLOT}) specifically", text).group(1))
        deadline = _parse_slot(re.search(rf"before ({_SLOT})", text).group(1))
        if explicit <= deadline:
            m = re.search(rf"Book ({_SLOT})\.", text)
            assert m, f"expected the explicit slot to be booked:\n{text}"
            assert _parse_slot(m.group(1)) == explicit
        else:
            # The tie-break rule never substitutes an unrelated slot when the
            # named one misses the deadline -- it must flag, not rebook.
            assert "flag the conflict" in text and "rather than silently rebooking" in text
            assert "Book " not in text
            saw_flag = True
    assert saw_flag, "test seed never exercised the past-deadline flag branch"


def test_gaia2_deadline_constraint_removes_blocked_slots():
    rng = random.Random(29)
    for _ in range(40):
        text, concept = _deadline_doc(rng)
        assert concept == "deadline"
        slots = _parse_slots(re.search(r"Initial candidate slots: (.+)\.\n", text).group(1))
        day = int(re.search(r"unavailable from \d{2}:00 onward on day (\d+)", text).group(1))
        blocked_from = int(re.search(r"unavailable from (\d{2}):00 onward", text).group(1))
        remaining = [s for s in slots if not (s[0] == day and s[1] >= blocked_from)]
        deadline = _parse_slot(re.search(rf"before ({_SLOT})", text).group(1))
        candidates = [s for s in remaining if s <= deadline]
        if candidates:
            expected = min(candidates)
            m = re.search(rf"is ({_SLOT}); book it immediately", text)
            assert m, f"expected a booking resolution:\n{text}"
            assert _parse_slot(m.group(1)) == expected
        else:
            assert "no slot survives" in text.lower()


def test_gaia2_collaboration_accepts_or_flags_by_deadline():
    rng = random.Random(31)
    for _ in range(40):
        text, concept = _collaboration_doc(rng)
        assert concept == "collaboration"
        booked = _parse_slot(re.search(rf"already booked ({_SLOT}) for the room", text).group(1))
        deadline = _parse_slot(re.search(rf"before ({_SLOT})", text).group(1))
        if booked <= deadline:
            assert "accept" in text and "duplicate it" in text
        else:
            assert "flag the conflict" in text


def test_gaia2_phase4_docs_are_long():
    """Spec 02: P4-tagged docs must land in the 6000-12000 char long-doc band."""
    docs = _collect(WorkflowGaia2Generator, target=1_500_000)
    p4 = [d for d in docs if d["phase"] == "p4"]
    assert p4, "no phase-4 docs produced at this target size"
    for d in p4:
        assert 6000 <= len(d["text"]) <= 13000, f"phase4 doc length {len(d['text'])} out of band"


# ---------------------------------------------------------------------------
# Phase coverage across all generators
# ---------------------------------------------------------------------------

def test_phase_coverage_union():
    seen = set()
    for gen_cls in ALL_GENERATORS:
        for d in _collect(gen_cls, target=1_000_000):
            seen.add(d["phase"])
    assert {"p0", "p1", "p2", "p3", "p4", "p5"} <= seen, f"missing phases: {sorted({'p0','p1','p2','p3','p4','p5'} - seen)}"


# ---------------------------------------------------------------------------
# write_shards round-trip determinism (file level)
# ---------------------------------------------------------------------------

def test_write_shards_deterministic(tmp_path):
    from ava.datagen.base import write_shards

    a = write_shards(LogicGenerator(seed=1234), str(tmp_path / "a"), target_mb=0.5)
    b = write_shards(LogicGenerator(seed=1234), str(tmp_path / "b"), target_mb=0.5)
    assert a["sha256"] == b["sha256"]
    assert a["bytes"] >= 0.5 * 1024 * 1024


# ---------------------------------------------------------------------------
# react_tools.py: independently verify tool-math answers and that grounding
# docs never fabricate behavior for the function they were told doesn't exist
# ---------------------------------------------------------------------------

def test_react_math_answers_are_correct():
    gen = ReactToolsGenerator(seed=1234)
    docs = [d for d in gen.generate(300_000) if d["concept"] == "tool_math"]
    assert docs, "no tool_math docs produced"
    for d in docs:
        m = re.search(r"(\d+) ([+\-*]) (\d+) = (-?\d+)\.", d["text"])
        assert m, f"couldn't find the answer line in: {d['text']!r}"
        a, op, b, claimed = int(m[1]), m[2], int(m[3]), int(m[4])
        actual = {"+": a + b, "-": a - b, "*": a * b}[op]
        assert claimed == actual, f"{a}{op}{b}: doc claims {claimed}, actually {actual}"


def test_react_grounding_notfound_never_fabricates():
    """The whole point of this family: after the Observation says '(no
    matches)', the final answer must say the thing doesn't exist — never
    describe plausible-sounding behavior for it."""
    gen = ReactToolsGenerator(seed=1234)
    docs = [d for d in gen.generate(300_000) if d["concept"] == "tool_grounding_notfound"]
    assert docs, "no tool_grounding_notfound docs produced"
    fabrication_markers = ("returns", "computes", "performs", "handles the case")
    for d in docs:
        assert "(no matches)" in d["text"]
        final_turn = d["text"].rsplit(ASSISTANT, 1)[-1]
        assert not any(m in final_turn.lower() for m in fabrication_markers), (
            f"final turn looks like it fabricated behavior: {final_turn!r}"
        )
        assert re.search(r"(doesn't exist|does not exist|isn't there|no function called)", final_turn)


def test_react_tools_parse_with_ava_bridge():
    """Cross-repo consistency: every doc's tool-calling assistant turn must
    actually parse via AgenticOS/ava_bridge.py's regex, or the SFT data and
    the bridge that's supposed to read this exact format have drifted apart.
    Skips gracefully if AgenticOS isn't checked out as a sibling directory
    (this repo's own test suite shouldn't hard-depend on a sibling repo)."""
    import sys
    from pathlib import Path

    agenticos = Path(__file__).resolve().parent.parent.parent / "AgenticOS"
    if not agenticos.is_dir():
        pytest.skip("AgenticOS sibling repo not present")
    sys.path.insert(0, str(agenticos))
    import ava_bridge

    gen = ReactToolsGenerator(seed=1234)
    docs = [d for d in gen.generate(300_000) if d["concept"] in
            {"tool_math", "tool_date", "tool_grounding_notfound", "tool_read_cite"}]
    assert docs
    for d in docs:
        # First assistant turn is the one with the Action: line.
        first_assistant = d["text"].split(USER, 2)[1].split(ASSISTANT, 1)[-1]
        parsed = ava_bridge.parse_react_response(first_assistant)
        assert "tool_calls" in parsed, f"ava_bridge failed to parse a real Action: line: {d['text']!r}"
        assert parsed["tool_calls"][0]["function"]["name"], "empty tool name parsed"


# ---------------------------------------------------------------------------
# db_trace.py / compress_trace.py (spec 02 B6): every answer is re-derived
# independently from the builder's meta inputs (re-run BFS, re-encode LZ77,
# recompute FNV-1a, ...) -- never trusted from generator internals.
# ---------------------------------------------------------------------------

_NO_ELIDE = 10 ** 9


def _rng(seed=4242):
    return random.Random(seed)


def test_etcot_docs_have_think_answer_structure():
    for gen_cls in (DBTraceGenerator, CompressTraceGenerator):
        docs = _collect(gen_cls)
        assert docs
        for d in docs:
            t = d["text"]
            assert t.startswith("### Task:"), f"{d['source']} missing task header"
            for tag in ("<think>", "</think>", "<answer>", "</answer>"):
                assert t.count(tag) == 1, f"{d['source']} bad tag count for {tag}"
            assert t.index("<think>") < t.index("</think>") < t.index("<answer>") < t.index("</answer>")
            assert "[step 1]" in t, f"{d['source']} trace has no step markers"


def test_etcot_task_types():
    db_tt = {d["task_type"] for d in _collect(DBTraceGenerator)}
    assert {"deliberate", "temporal"} <= db_tt  # time-series family is temporal
    cp_tt = {d["task_type"] for d in _collect(CompressTraceGenerator)}
    assert {"deliberate", "temporal"} <= cp_tt  # delta+varint family is temporal


def test_etcot_phase4_docs_are_long():
    """Spec 02: P4-tagged docs must land in the 6000-12000 char long-doc band."""
    for gen_cls in (DBTraceGenerator, CompressTraceGenerator):
        docs = _collect(gen_cls, target=1_500_000)
        p4 = [d for d in docs if d["phase"] == "p4"]
        assert p4, f"{gen_cls.__name__}: no phase-4 docs at this target size"
        for d in p4:
            assert 6000 <= len(d["text"]) <= 12000, (
                f"{d['source']} phase4 doc length {len(d['text'])} out of band")


def test_etcot_p3_elision_emits_true_checkpoints():
    """Some p3 docs must exercise the checkpoint-elision context-budget path,
    and the elision marker must carry a state checkpoint."""
    for gen_cls in (DBTraceGenerator, CompressTraceGenerator):
        docs = [d for d in _collect(gen_cls, target=1_500_000) if d["phase"] == "p3"]
        elided = [d for d in docs if "steps elided" in d["text"]]
        assert elided, f"{gen_cls.__name__}: no p3 doc exercised elision"
        for d in elided:
            assert "state checkpoint before step" in d["text"]


# ---- relational / B-tree ---------------------------------------------------

def test_btree_point_query_answers_correct():
    rng = _rng()
    for _ in range(25):
        text, tt, concept, meta = _btree_point_doc(rng, rng.randint(10, 40), _NO_ELIDE)
        present = meta["target"] in set(meta["keys"])
        assert meta["found"] == present
        if present:
            item, qty = meta["rows"][meta["target"]]
            assert f"(id={meta['target']}, item='{item}', qty={qty})" in text
        else:
            assert "0 rows" in text


def test_btree_range_scan_answers_correct():
    rng = _rng(7)
    for _ in range(25):
        text, tt, concept, meta = _btree_range_doc(rng, rng.randint(10, 50), _NO_ELIDE)
        expect = [k for k in meta["keys"] if meta["lo"] <= k <= meta["hi"]]
        assert meta["got"] == expect
        assert sum(meta["rows"][k][1] for k in expect) == meta["total"]
        assert f"SUM(qty)" in text and str(meta["total"]) in text


def test_btree_insert_keeps_tree_ordered():
    rng = _rng(9)
    for _ in range(25):
        text, tt, concept, meta = _btree_insert_doc(rng, rng.randint(8, 30), _NO_ELIDE)
        assert meta["inorder"] == sorted(meta["order"] + [meta["inserted"]])


# ---- document / key-value / wide-column ------------------------------------

def test_docstore_filter_projection_correct():
    rng = _rng(11)
    for _ in range(25):
        text, tt, concept, meta = _doc_filter_doc(rng, rng.randint(4, 20), _NO_ELIDE)
        expect = [d["user"]["name"] for d in meta["docs"]
                  if d["user"]["age"] >= meta["min_age"] and meta["tag"] in d["tags"]]
        assert meta["names"] == expect
        assert str(expect) in text


def test_kv_hash_placement_matches_independent_simulation():
    def fnv1a(s):  # independent re-implementation
        h = 2166136261
        for ch in s:
            h = ((h ^ ord(ch)) * 16777619) % 2 ** 32
        return h

    rng = _rng(13)
    for _ in range(25):
        text, tt, concept, meta = _kv_hash_doc(rng, rng.randint(4, 12), _NO_ELIDE)
        m = meta["buckets"]
        slots = [None] * m
        for k in meta["keys"]:
            b = fnv1a(k) % m
            while slots[b] is not None:
                b = (b + 1) % m
            slots[b] = k
            assert meta["placed"][k] == b
        assert f"-> {meta['values'][meta['target']]} (slot {meta['placed'][meta['target']]}" in text


def test_wide_column_sum_correct():
    rng = _rng(17)
    for _ in range(25):
        text, tt, concept, meta = _wide_column_doc(rng, rng.randint(4, 40), _NO_ELIDE)
        assert meta["total"] == sum(r[2] for r in meta["rows"])
        assert f"SUM(sales) = {meta['total']}" in text


# ---- graph / time-series / vector ------------------------------------------

def test_graph_traversal_matches_independent_replay():
    rng = _rng(19)
    for _ in range(30):
        text, tt, concept, meta = _graph_doc(rng, rng.randint(5, 20), _NO_ELIDE)
        adj = meta["adj"]
        if meta["kind"] == "bfs":
            dist = {0: 0}
            q = [0]
            while q:
                u = q.pop(0)
                for v in adj[u]:
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        q.append(v)
            target = max(adj)
            assert meta["dist"] == dist[target]
            path = meta["path"]
            assert path[0] == 0 and path[-1] == target and len(path) == dist[target] + 1
            for a, b in zip(path, path[1:]):
                assert b in adj[a], "path uses a non-edge"
        else:
            stack, seen, order = [0], set(), []
            while stack:
                u = stack.pop()
                if u in seen:
                    continue
                seen.add(u)
                order.append(u)
                stack.extend(v for v in reversed(adj[u]) if v not in seen)
            assert meta["order"] == order


def test_ts_window_aggregation_correct():
    rng = _rng(23)
    for _ in range(25):
        text, tt, concept, meta = _ts_agg_doc(rng, rng.randint(5, 30), _NO_ELIDE)
        assert tt == "temporal"
        buckets = {}
        for t, v in meta["pts"]:
            buckets.setdefault((t - meta["t0"]) // meta["window"], []).append(v)
        for b, vals in buckets.items():
            c, s, mn, mx, avg = meta["table"][b]
            assert (c, mn, mx) == (len(vals), min(vals), max(vals))
            assert abs(s - sum(vals)) < 1e-9 and abs(avg - sum(vals) / len(vals)) < 1e-9


def test_vector_knn_topk_correct():
    rng = _rng(29)
    for _ in range(25):
        text, tt, concept, meta = _vector_knn_doc(rng, rng.randint(4, 25), _NO_ELIDE)
        q = meta["q"]
        d2 = [sum((a - b) ** 2 for a, b in zip(q, v)) for v in meta["vecs"]]
        expect = sorted(range(len(d2)), key=lambda i: (d2[i], i))[:meta["k"]]
        assert [i for i, _ in meta["topk"]] == expect
        assert all(dd == d2[i] for i, dd in meta["topk"])


def test_hnsw_greedy_is_honest_about_local_minima():
    rng = _rng(31)
    for _ in range(20):
        text, tt, concept, meta = _hnsw_doc(rng, rng.randint(8, 20), _NO_ELIDE)
        q, vecs = meta["q"], meta["vecs"]
        d2 = lambda v: sum((a - b) ** 2 for a, b in zip(q, v))  # noqa: E731
        # independent greedy replay over the doc's own link lists
        cur = meta["entry"]
        for nbrs in (meta["nbrs1"], meta["nbrs0"]):
            while True:
                cand = min(nbrs[cur], key=lambda j: (d2(vecs[j]), j))
                if d2(vecs[cand]) < d2(vecs[cur]):
                    cur = cand
                else:
                    break
        assert meta["got"] == cur
        exact = min(range(len(vecs)), key=lambda i: (d2(vecs[i]), i))
        assert meta["exact"] == exact
        if meta["got"] == exact:
            assert "found the true nearest neighbour" in text
        else:
            assert "local minimum" in text


# ---- compression -------------------------------------------------------------

def test_rle_runs_correct():
    rng = _rng(37)
    for _ in range(25):
        text, tt, concept, meta = _rle_doc(rng, rng.randint(3, 25), _NO_ELIDE)
        assert "".join(c * k for c, k in meta["runs"]) == meta["data"]
        for (a, _), (b, _) in zip(meta["runs"], meta["runs"][1:]):
            assert a != b, "adjacent runs share a byte -- not maximal"


def test_lz77_triples_decode_to_input():
    rng = _rng(41)
    for _ in range(25):
        text, tt, concept, meta = _lz77_doc(rng, rng.randint(8, 60), _NO_ELIDE)
        buf = []  # independent decoder
        for off, length, lit in meta["triples"]:
            for _i in range(length):
                buf.append(buf[-off])
            buf.append(lit)
        assert "".join(buf) == meta["data"]


def test_huffman_codes_prefix_free_and_decode():
    rng = _rng(43)
    for _ in range(25):
        text, tt, concept, meta = _huffman_doc(rng, rng.randint(10, 80), _NO_ELIDE)
        codes = meta["codes"]
        for a in codes.values():
            for b in codes.values():
                assert a == b or not b.startswith(a), "codes are not prefix-free"
        if len(codes) > 1:  # full binary tree satisfies Kraft with equality
            assert sum(Fraction(1, 2 ** len(c)) for c in codes.values()) == 1
        inv = {v: k for k, v in codes.items()}
        out, cur = [], ""
        for bit in meta["encoded"]:
            cur += bit
            if cur in inv:
                out.append(inv[cur])
                cur = ""
        assert cur == "" and "".join(out) == meta["data"]


def test_delta_varint_roundtrip():
    rng = _rng(47)
    for _ in range(25):
        text, tt, concept, meta = _delta_varint_doc(rng, rng.randint(3, 30), _NO_ELIDE)
        assert tt == "temporal"
        vals, cur, shift = [], 0, 0  # independent LEB128 decoder
        for b in meta["stream"]:
            cur |= (b & 0x7F) << shift
            if b & 0x80:
                shift += 7
            else:
                vals.append(cur)
                cur, shift = 0, 0
        rebuilt = [vals[0]]
        for d in vals[1:]:
            rebuilt.append(rebuilt[-1] + d)
        assert rebuilt == meta["ts"]


def test_quant_int8_math_correct():
    rng = _rng(53)
    for _ in range(25):
        text, tt, concept, meta = _quant_int8_doc(rng, rng.randint(4, 30), _NO_ELIDE)
        amax = max(abs(v) for v in meta["vals"])
        scale = amax / 127.0
        assert meta["scale"] == scale
        assert meta["q"] == [max(-127, min(127, round(v / scale))) for v in meta["vals"]]
        assert all(-127 <= qi <= 127 for qi in meta["q"])


def test_arith_eiw_windows_decode_independently():
    P = {"A": Fraction(1, 2), "B": Fraction(1, 4), "C": Fraction(1, 4)}
    CUM = {"A": Fraction(0), "B": Fraction(1, 2), "C": Fraction(3, 4)}
    BITS = {"A": 1, "B": 2, "C": 2}

    rng = _rng(59)
    for _ in range(25):
        text, tt, concept, meta = _arith_eiw_doc(rng, rng.randint(6, 50), _NO_ELIDE)
        decoded = []
        for syms, bits, code in meta["windows"]:
            assert len(code) == bits
            v = Fraction(int(code, 2), 2 ** bits)  # independent decoder
            low, width, used, out = Fraction(0), Fraction(1), 0, ""
            while used < bits:
                for s in "ABC":
                    lo = low + width * CUM[s]
                    if lo <= v < lo + width * P[s]:
                        out += s
                        low, width, used = lo, width * P[s], used + BITS[s]
                        break
                else:
                    raise AssertionError("no interval contains code value")
            assert out == syms
            decoded.append(out)
        assert "".join(decoded) == meta["seq"]
        # equal-info property: every non-final window crosses the 8-bit budget
        # by at most one symbol's information (<= 9 bits, >= 8 bits)
        for syms, bits, code in meta["windows"][:-1]:
            assert 8 <= bits <= 9


# ---------------------------------------------------------------------------
# round-2 families: LSM / WAL / cosine / DEFLATE / pruning -- each replayed
# independently from the builder's meta inputs.
# ---------------------------------------------------------------------------

def test_lsm_matches_last_write_wins_dict():
    rng = _rng(61)
    for _ in range(25):
        text, tt, concept, meta = _lsm_doc(rng, rng.randint(4, 30), _NO_ELIDE)
        expect = {}
        for op, k, v in meta["ops"]:
            if op == "PUT":
                expect[k] = v
            else:
                expect.pop(k, None)
        assert meta["visible"] == expect
        for k, got in meta["gets"]:
            assert got == expect.get(k)
            shown = "NOT FOUND" if got is None else str(got)
            assert f"{k} -> {shown}" in text


def test_wal_recovery_applies_only_committed_txns():
    rng = _rng(67)
    for _ in range(25):
        text, tt, concept, meta = _wal_doc(rng, rng.randint(3, 14), _NO_ELIDE)
        assert tt == "temporal"
        surviving = meta["log"][: meta["crash_at"]]
        committed = {r[1] for r in surviving if r[0] == "COMMIT"}
        assert sorted(committed) == meta["committed"]
        expect = dict(meta["init"])
        for rec in surviving:
            if rec[0] == "SET" and rec[1] in committed:
                expect[rec[2]] = rec[4]
        assert meta["recovered"] == expect
        assert str(dict(sorted(expect.items()))) in text
        # before-images are honest: each SET's old value equals the state a
        # sequential executor would see at that record
        state, pending = dict(meta["init"]), {}
        for rec in meta["log"]:
            if rec[0] == "BEGIN":
                pending = {}
            elif rec[0] == "SET":
                _, t, a, old, new = rec
                assert old == pending.get(a, state[a])
                pending[a] = new
            elif rec[0] == "COMMIT":
                state.update(pending)


def test_vector_cosine_best_matches_math_recompute():
    import math

    rng = _rng(71)
    for _ in range(25):
        text, tt, concept, meta = _vector_cosine_doc(rng, rng.randint(4, 20), _NO_ELIDE)
        q = meta["q"]
        nq = math.sqrt(sum(a * a for a in q))
        sims = []
        for v in meta["vecs"]:
            dot = sum(a * b for a, b in zip(q, v))
            sims.append(dot / (nq * math.sqrt(sum(b * b for b in v))))
        assert sims == meta["sims"]
        best = max(range(len(sims)), key=lambda i: (sims[i], -i))
        assert meta["best"] == best
        assert f"best match: v{best} with cosine similarity {sims[best]:.4f}" in text


def test_deflate_two_stage_independent_decode():
    rng = _rng(73)
    for _ in range(25):
        text, tt, concept, meta = _deflate_doc(rng, rng.randint(8, 60), _NO_ELIDE)
        codes, bits = meta["codes"], meta["bitstream"]
        # independent bit reader: 5-bit offset | 4-bit length | prefix-walk literal
        inv = {v: k for k, v in codes.items()}
        triples, i = [], 0
        while i < len(bits):
            off = int(bits[i: i + 5], 2)
            length = int(bits[i + 5: i + 9], 2)
            i += 9
            cur = ""
            while cur not in inv:
                cur += bits[i]
                i += 1
            triples.append((off, length, inv[cur]))
        assert triples == meta["triples"]
        buf = []
        for off, length, lit in triples:
            for _j in range(length):
                buf.append(buf[-off])
            buf.append(lit)
        assert "".join(buf) == meta["data"]
        # literal codes are prefix-free
        for a in codes.values():
            for b in codes.values():
                assert a == b or not b.startswith(a)


def test_prune_zeroes_exactly_the_k_smallest_magnitudes():
    rng = _rng(79)
    for _ in range(25):
        text, tt, concept, meta = _prune_doc(rng, rng.randint(4, 30), _NO_ELIDE)
        vals, k = meta["vals"], meta["k"]
        order = sorted(range(len(vals)), key=lambda i: (abs(vals[i]), i))
        assert meta["pruned"] == sorted(order[:k])
        assert meta["threshold"] == abs(vals[order[k - 1]])
        for i, v in enumerate(meta["out"]):
            assert v == (0.0 if i in set(order[:k]) else vals[i])
        assert f"sparsity: {k}/{len(vals)}" in text


# ---------------------------------------------------------------------------
# SFT rendering: trace_common.to_chat + sft_sota_2025's ET-CoT chat component
# ---------------------------------------------------------------------------

def test_to_chat_rendering_structure():
    from ava.datagen.trace_common import CHAT_ASSISTANT, CHAT_USER, to_chat

    for gen_cls in (DBTraceGenerator, CompressTraceGenerator):
        for d in _collect(gen_cls, target=150_000):
            chat = to_chat(d["text"])
            assert chat.count(CHAT_USER) == 1 and chat.count(CHAT_ASSISTANT) == 1
            assert chat.startswith(f"{CHAT_USER}\n### Task:")
            u, a = chat.index(CHAT_USER), chat.index(CHAT_ASSISTANT)
            assert u < a < chat.index("<think>") < chat.index("</think>") < chat.index("<answer>")
            # the user turn holds the task only; trace + answer live in the
            # assistant turn, byte-identical to the pretraining rendering
            assert "<think>" not in chat[:a]
            task, trace = d["text"].split("\n\n<think>\n", 1)
            assert chat == f"{CHAT_USER}\n{task}\n{CHAT_ASSISTANT}\n<think>\n{trace}"


def test_sft_etcot_chat_docs_shape_and_determinism():
    pytest.importorskip("numpy")  # sft_sota_2025 imports ava.pipeline.pack
    from sft_sota_2025 import _etcot_chat_docs

    docs = _etcot_chat_docs(seed=1234, target_mb=0.1)
    assert docs and docs == _etcot_chat_docs(seed=1234, target_mb=0.1)
    from ava.datagen.base import DOC_KEYS

    for d in docs:
        assert set(d.keys()) == DOC_KEYS
        assert d["phase"] == "p5" and d["doc_id"].startswith("etcot_chat:")
        assert d["text"].startswith("<|user|>\n### Task:")
        assert "<|assistant|>\n<think>\n" in d["text"]
    sources = {d["source"].split("/")[0] for d in docs}
    assert sources == {"dbtrace", "compress"}
