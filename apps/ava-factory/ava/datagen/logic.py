"""Phase-0 logic corpus: truth tables, natural-deduction proofs that are
valid BY CONSTRUCTION, syllogisms (verified by exhaustive small-model
search, not memorized), FOL instantiations, and wrong-proof/critique pairs.

Nothing here is "generate text that looks like a proof" -- every table row,
every derivation step, every syllogism verdict and every countermodel is
computed in Python before it is rendered.
"""

from __future__ import annotations

import itertools
from typing import Iterator

from ava.datagen.base import Generator

# ---------------------------------------------------------------------------
# Propositional formulas: nested tuples, e.g. ('IMPLIES', ('ATOM','A'), ('ATOM','B'))
# ---------------------------------------------------------------------------

_SYM = {"AND": "∧", "OR": "∨", "IMPLIES": "→", "IFF": "↔"}
_NOT = "¬"


def A(name: str) -> tuple:
    return ("ATOM", name)


def NOT(f: tuple) -> tuple:
    return ("NOT", f)


def AND(l: tuple, r: tuple) -> tuple:
    return ("AND", l, r)


def OR(l: tuple, r: tuple) -> tuple:
    return ("OR", l, r)


def IMPLIES(l: tuple, r: tuple) -> tuple:
    return ("IMPLIES", l, r)


def IFF(l: tuple, r: tuple) -> tuple:
    return ("IFF", l, r)


def render(f: tuple) -> str:
    tag = f[0]
    if tag == "ATOM":
        return f[1]
    if tag == "NOT":
        inner = f[1]
        s = render(inner)
        return f"{_NOT}{s}" if inner[0] in ("ATOM", "NOT") else f"{_NOT}({s})"
    sym = _SYM[tag]
    l, r = f[1], f[2]
    ls = render(l) if l[0] in ("ATOM", "NOT") else f"({render(l)})"
    rs = render(r) if r[0] in ("ATOM", "NOT") else f"({render(r)})"
    return f"{ls} {sym} {rs}"


def eval_formula(f: tuple, assign: dict) -> bool:
    tag = f[0]
    if tag == "ATOM":
        return assign[f[1]]
    if tag == "NOT":
        return not eval_formula(f[1], assign)
    if tag == "AND":
        return eval_formula(f[1], assign) and eval_formula(f[2], assign)
    if tag == "OR":
        return eval_formula(f[1], assign) or eval_formula(f[2], assign)
    if tag == "IMPLIES":
        return (not eval_formula(f[1], assign)) or eval_formula(f[2], assign)
    if tag == "IFF":
        return eval_formula(f[1], assign) == eval_formula(f[2], assign)
    raise ValueError(f"bad formula tag: {tag!r}")


def random_formula(rng, vars_pool: list[str], depth: int) -> tuple:
    if depth <= 0 or rng.random() < 0.4:
        return A(rng.choice(vars_pool))
    op = rng.choice(["NOT", "AND", "OR", "IMPLIES", "IFF"])
    if op == "NOT":
        return NOT(random_formula(rng, vars_pool, depth - 1))
    l = random_formula(rng, vars_pool, depth - 1)
    r = random_formula(rng, vars_pool, depth - 1)
    return (op, l, r)


# ---------------------------------------------------------------------------
# Truth table family
# ---------------------------------------------------------------------------

_VAR_POOL = ["p", "q", "r", "s"]


def _truth_table_doc(rng) -> tuple[str, str, str]:
    """Returns (text, task_type, concept)."""
    simple = rng.random() < 0.05
    if simple:
        n_vars = 2
        vars_pool = _VAR_POOL[:2]
        op = rng.choice(["AND", "OR", "IMPLIES", "NOT"])
        if op == "NOT":
            f = NOT(A(vars_pool[0]))
        else:
            f = (op, A(vars_pool[0]), A(vars_pool[1]))
        task_type = "automatic"
    else:
        n_vars = rng.randint(2, 4)
        vars_pool = _VAR_POOL[:n_vars]
        depth = rng.randint(2, 4)
        f = random_formula(rng, vars_pool, depth)
        # avoid degenerate bare-atom formulas for the full chapters
        tries = 0
        while f[0] == "ATOM" and tries < 5:
            f = random_formula(rng, vars_pool, depth)
            tries += 1
        task_type = "deliberate"

    rendered = render(f)
    combos = list(itertools.product([True, False], repeat=n_vars))  # fixed order
    rows = []
    results = []
    for combo in combos:
        assign = dict(zip(vars_pool, combo))
        val = eval_formula(f, assign)
        results.append(val)
        assign_str = ", ".join(f"{v}={'T' if assign[v] else 'F'}" for v in vars_pool)
        rows.append(f"  {assign_str}  |  {rendered} = {'T' if val else 'F'}")

    if all(results):
        verdict = "TAUTOLOGY -- true under every assignment of truth values."
    elif not any(results):
        verdict = "CONTRADICTION -- false under every assignment of truth values."
    else:
        verdict = "CONTINGENT -- true under some assignments and false under others."

    lines = [
        f"Truth table walkthrough for the formula: {rendered}",
        f"Variables: {', '.join(vars_pool)} (each ranges over {{T, F}}).",
        "",
        "We enumerate every assignment and evaluate the formula on each row:",
        *rows,
        "",
        f"Verdict (computed from all {len(combos)} rows above): {verdict}",
    ]
    return "\n".join(lines), task_type, "truth_table"


# ---------------------------------------------------------------------------
# Natural deduction: forward-only, correct by construction
# ---------------------------------------------------------------------------

_RULE_LABEL = {
    "MP": "Modus Ponens",
    "MT": "Modus Tollens",
    "ANDE_L": "And-Elimination (left)",
    "ANDE_R": "And-Elimination (right)",
    "ANDI": "And-Introduction",
    "ORI": "Or-Introduction",
}

_CONCEPT_FOR_RULE = {
    "MP": "modus_ponens",
    "MT": "modus_tollens",
    "ANDE_L": "and_elimination",
    "ANDE_R": "and_elimination",
    "ANDI": "and_introduction",
    "ORI": "or_introduction",
    "IMPI": "implies_introduction",
}

_ATOM_NAMES = ["A", "B", "C", "D", "E", "F", "G"]


def _find_candidates(context: list[tuple]) -> list[tuple]:
    """context: list of formulas. Returns list of (rule, new_formula, (refs...))."""
    candidates = []
    for f in context:
        if f[0] == "IMPLIES":
            ant, cons = f[1], f[2]
            if ant in context and cons not in context:
                candidates.append(("MP", cons, (f, ant)))
            negcons = NOT(cons)
            negant = NOT(ant)
            if negcons in context and negant not in context:
                candidates.append(("MT", negant, (f, negcons)))
        if f[0] == "AND":
            l, r = f[1], f[2]
            if l not in context:
                candidates.append(("ANDE_L", l, (f,)))
            if r not in context:
                candidates.append(("ANDE_R", r, (f,)))
    for i, f1 in enumerate(context):
        for f2 in context[i + 1:]:
            conj = AND(f1, f2)
            if conj not in context:
                candidates.append(("ANDI", conj, (f1, f2)))
    return candidates


def _build_premises(rng, atom_names: list[str]) -> list[tuple]:
    n = len(atom_names)
    chain_len = rng.randint(2, min(3, n - 1))
    premises = [IMPLIES(A(atom_names[i]), A(atom_names[i + 1])) for i in range(chain_len)]
    if rng.random() < 0.5:
        premises.append(A(atom_names[0]))  # drives Modus Ponens forward
    else:
        premises.append(NOT(A(atom_names[chain_len])))  # drives Modus Tollens backward
    if n > chain_len + 1 and rng.random() < 0.6:
        premises.append(AND(A(atom_names[chain_len]), A(atom_names[-1])))
    # dedupe while preserving order (no set() -- keep deterministic order)
    seen: list[tuple] = []
    for p in premises:
        if p not in seen:
            seen.append(p)
    return seen


def _render_derivation(premises: list[tuple], steps: list[tuple], line_offset: int = 0) -> tuple[list[str], dict]:
    """steps: list of (rule, formula, refs). Returns (rendered_lines, formula->line_no map)."""
    line_no_of: dict = {}
    lines = []
    n = line_offset
    for p in premises:
        n += 1
        line_no_of[p] = n
        lines.append(f"{n}. {render(p)}   [Premise]")
    for rule, formula, refs in steps:
        n += 1
        line_no_of[formula] = n
        ref_nums = ", ".join(str(line_no_of[r]) for r in refs)
        lines.append(f"{n}. {render(formula)}   [{_RULE_LABEL[rule]}, from line(s) {ref_nums}]")
    return lines, line_no_of


def _forward_derive(rng, context: list[tuple], max_steps: int) -> list[tuple]:
    """Applies rules forward, mutating a *copy* of context; returns the list of
    (rule, formula, refs) steps taken. Never invents a step that isn't a real
    application of an inference rule to formulas already present."""
    ctx = list(context)
    steps = []
    for _ in range(max_steps):
        candidates = _find_candidates(ctx)
        if not candidates:
            break
        rule, formula, refs = rng.choice(candidates)
        ctx.append(formula)
        steps.append((rule, formula, refs))
    return steps


def _natded_doc(rng) -> tuple[str, str, str]:
    conditional = rng.random() < 0.35
    n_atoms = rng.randint(4, 6) if conditional else rng.randint(3, 5)
    atom_names = _ATOM_NAMES[:n_atoms]
    premises = _build_premises(rng, atom_names[:-1] if conditional else atom_names)
    max_steps = rng.randint(2, 4)
    steps = _forward_derive(rng, premises, max_steps)
    concepts_used = [s[0] for s in steps]

    if conditional and len(atom_names) >= 1:
        assumption_atom = atom_names[-1]
        assumption = A(assumption_atom)
        outer_ctx = premises + [f for (_, f, _) in steps]
        sub_ctx = outer_ctx + [assumption]
        sub_steps = _forward_derive(rng, sub_ctx, rng.randint(1, 3))
        if sub_steps:
            derived = sub_steps[-1][1]
            lines, line_no_of = _render_derivation(premises, steps)
            n = len(lines)
            lines.append(f"{n + 1}. | Assume: {render(assumption)}   [Assumption, for conditional proof]")
            line_no_of[assumption] = n + 1
            m = n + 1
            for rule, formula, refs in sub_steps:
                m += 1
                ref_nums = ", ".join(str(line_no_of[r]) for r in refs)
                lines.append(f"{m}. | {render(formula)}   [{_RULE_LABEL[rule]}, from line(s) {ref_nums}]")
                line_no_of[formula] = m
            conclusion = IMPLIES(assumption, derived)
            m += 1
            lines.append(
                f"{m}. {render(conclusion)}   [Implies-Introduction, discharging assumption on line {n + 1} "
                f"(subproof lines {n + 1}-{m - 1})]"
            )
            concepts_used.append("IMPI")
            concept = _CONCEPT_FOR_RULE["IMPI"]
            body = "\n".join(lines)
            text = (
                "Natural-deduction proof using conditional proof (implies-introduction).\n"
                f"Goal: derive a formula of the form X {_SYM['IMPLIES']} Y from the premises below by "
                "temporarily assuming X, deriving Y, then discharging the assumption.\n\n"
                f"{body}\n\n"
                f"This derivation is valid because every line either restates a premise, is the "
                "assumption of a subproof, or follows from earlier lines by a single, correctly "
                "applied inference rule; the final line discharges the subproof assumption via "
                "implies-introduction, which is always sound."
            )
            return text, "deliberate", concept

    # straight-line (non-conditional, or conditional attempt that had nothing to derive)
    lines, _ = _render_derivation(premises, steps)
    concept = _CONCEPT_FOR_RULE[concepts_used[-1]] if concepts_used else "premise"
    body = "\n".join(lines)
    final_formula = steps[-1][1] if steps else premises[-1]
    text = (
        "Natural-deduction proof, built forward from the premises.\n"
        "Each non-premise line is produced by applying exactly one inference rule to formulas that "
        "already appear earlier in the proof -- the derivation is correct by construction, not "
        "checked after the fact.\n\n"
        f"{body}\n\n"
        f"Final conclusion: {render(final_formula)}"
    )
    return text, "deliberate", concept


# ---------------------------------------------------------------------------
# Syllogisms: validity determined by exhaustive small-model search, not by
# a memorized table. All three terms S, M, P are taken as non-empty classes
# (the standard existential-import convention that yields the traditional
# 24 valid forms).
# ---------------------------------------------------------------------------

_FIGURES = {
    1: (("M", "P"), ("S", "M")),
    2: (("P", "M"), ("S", "M")),
    3: (("M", "P"), ("M", "S")),
    4: (("P", "M"), ("M", "S")),
}

_STMT_FN = {
    "A": lambda X, Y: X.issubset(Y),
    "E": lambda X, Y: len(X & Y) == 0,
    "I": lambda X, Y: len(X & Y) > 0,
    "O": lambda X, Y: len(X - Y) > 0,
}

_SYLLOGISM_NAMES = {
    ("A", "A", "A", 1): "Barbara", ("A", "A", "I", 1): "Barbari", ("A", "I", "I", 1): "Darii",
    ("E", "A", "E", 1): "Celarent", ("E", "A", "O", 1): "Celaront", ("E", "I", "O", 1): "Ferio",
    ("A", "E", "E", 2): "Camestres", ("A", "E", "O", 2): "Camestros", ("A", "O", "O", 2): "Baroko",
    ("E", "A", "E", 2): "Cesare", ("E", "A", "O", 2): "Cesaro", ("E", "I", "O", 2): "Festino",
    ("A", "A", "I", 3): "Darapti", ("A", "I", "I", 3): "Datisi", ("E", "A", "O", 3): "Felapton",
    ("E", "I", "O", 3): "Ferison", ("I", "A", "I", 3): "Disamis", ("O", "A", "O", 3): "Bocardo",
    ("A", "A", "I", 4): "Bramantip", ("A", "E", "E", 4): "Camenes", ("A", "E", "O", 4): "Camenop",
    ("E", "A", "O", 4): "Fesapo", ("E", "I", "O", 4): "Fresison", ("I", "A", "I", 4): "Dimaris",
}

_DISTRIBUTES_SUBJECT = {"A": True, "E": True, "I": False, "O": False}
_DISTRIBUTES_PREDICATE = {"A": False, "E": True, "I": False, "O": True}


def _all_nonempty_subsets(n: int) -> list[frozenset]:
    universe = list(range(n))
    return [frozenset(c) for r in range(1, n + 1) for c in itertools.combinations(universe, r)]


def _check_syllogism(major_type: str, minor_type: str, concl_type: str, figure: int, n: int = 3):
    """Exhaustive check over all (S, M, P) assignments of non-empty subsets of
    a size-n universe. Returns (is_valid, satisfiable, counterexample) where
    counterexample is a (S, M, P) frozenset triple violating the conclusion,
    or None if none was found / none exists."""
    subs = _all_nonempty_subsets(n)
    maj_pair, min_pair = _FIGURES[figure]
    satisfiable = False
    valid_always = True
    counterexample = None
    for S in subs:
        for M in subs:
            for P in subs:
                tm = {"S": S, "M": M, "P": P}
                if _STMT_FN[major_type](tm[maj_pair[0]], tm[maj_pair[1]]) and \
                        _STMT_FN[minor_type](tm[min_pair[0]], tm[min_pair[1]]):
                    satisfiable = True
                    if not _STMT_FN[concl_type](S, P):
                        valid_always = False
                        if counterexample is None:
                            counterexample = (S, M, P)
    return (satisfiable and valid_always), satisfiable, counterexample


_syllogism_table_cache = None


def get_syllogism_table():
    """Computed once per process: (valid_forms, invalid_forms) where
    invalid_forms is a list of (mood_tuple, counterexample)."""
    global _syllogism_table_cache
    if _syllogism_table_cache is not None:
        return _syllogism_table_cache
    valid_forms = []
    invalid_forms = []
    for figure in (1, 2, 3, 4):
        for maj in "AEIO":
            for minr in "AEIO":
                for concl in "AEIO":
                    is_valid, satisfiable, cex = _check_syllogism(maj, minr, concl, figure)
                    form = (maj, minr, concl, figure)
                    if is_valid:
                        valid_forms.append(form)
                    elif satisfiable:
                        invalid_forms.append((form, cex))
    valid_forms.sort()
    invalid_forms.sort(key=lambda t: t[0])
    _syllogism_table_cache = (valid_forms, invalid_forms)
    return _syllogism_table_cache


def _classify_fallacy(major_type: str, minor_type: str, concl_type: str, figure: int) -> str:
    if major_type in ("E", "O") and minor_type in ("E", "O"):
        return "exclusive premises (both premises negative)"
    if major_type in ("I", "O") and minor_type in ("I", "O"):
        return "two particular premises"
    maj_pair, min_pair = _FIGURES[figure]
    # is M distributed in the major premise?
    m_dist_major = (_DISTRIBUTES_SUBJECT[major_type] if maj_pair[0] == "M" else _DISTRIBUTES_PREDICATE[major_type])
    m_dist_minor = (_DISTRIBUTES_SUBJECT[minor_type] if min_pair[0] == "M" else _DISTRIBUTES_PREDICATE[minor_type])
    if not m_dist_major and not m_dist_minor:
        return "undistributed middle"
    p_dist_concl = concl_type in ("E", "O")
    if p_dist_concl:
        p_dist_major = (_DISTRIBUTES_SUBJECT[major_type] if maj_pair[0] == "P" else _DISTRIBUTES_PREDICATE[major_type])
        if not p_dist_major:
            return "illicit major"
    s_dist_concl = concl_type in ("A", "E")
    if s_dist_concl:
        s_dist_minor = (_DISTRIBUTES_SUBJECT[minor_type] if min_pair[0] == "S" else _DISTRIBUTES_PREDICATE[minor_type])
        if not s_dist_minor:
            return "illicit minor"
    return "invalid form (see counterexample)"


def _stmt_text(t: str, x: str, y: str) -> str:
    if t == "A":
        return f"All {x} are {y}."
    if t == "E":
        return f"No {x} are {y}."
    if t == "I":
        return f"Some {x} are {y}."
    return f"Some {x} are not {y}."


_TERM_NOUNS = sorted([
    "dogs", "cats", "mammals", "reptiles", "birds", "fish", "insects", "plants", "trees",
    "flowers", "students", "teachers", "doctors", "lawyers", "musicians", "athletes",
    "vehicles", "cars", "bicycles", "metals", "gases", "liquids", "planets", "stars",
    "novels", "poems", "computers", "robots", "islands", "rivers", "mountains", "cities",
])


def _pick_terms(rng) -> tuple[str, str, str]:
    return tuple(rng.sample(_TERM_NOUNS, 3))


def _syllogism_doc(rng) -> tuple[str, str, str]:
    valid_forms, invalid_forms = get_syllogism_table()
    s_noun, m_noun, p_noun = _pick_terms(rng)
    term_map = {"S": s_noun, "M": m_noun, "P": p_noun}
    if rng.random() < 0.6:
        maj, minr, concl, figure = rng.choice(valid_forms)
        maj_pair, min_pair = _FIGURES[figure]
        major_stmt = _stmt_text(maj, term_map[maj_pair[0]], term_map[maj_pair[1]])
        minor_stmt = _stmt_text(minr, term_map[min_pair[0]], term_map[min_pair[1]])
        concl_stmt = _stmt_text(concl, s_noun, p_noun)
        name = _SYLLOGISM_NAMES.get((maj, minr, concl, figure), f"{maj}{minr}{concl}-{figure}")
        text = (
            f"Syllogism ({name}, mood {maj}{minr}{concl}, figure {figure}):\n"
            f"Major premise: {major_stmt}\n"
            f"Minor premise: {minor_stmt}\n"
            f"Conclusion: {concl_stmt}\n\n"
            f"This form is VALID: an exhaustive search over every way of assigning the three classes "
            f"({s_noun}, {m_noun}, {p_noun}) found no case where both premises hold but the conclusion "
            "fails -- every model satisfying the premises also satisfies the conclusion."
        )
        return text, "deliberate", "syllogism"
    else:
        (maj, minr, concl, figure), cex = rng.choice(invalid_forms)
        S, M, P = cex
        maj_pair, min_pair = _FIGURES[figure]
        major_stmt = _stmt_text(maj, term_map[maj_pair[0]], term_map[maj_pair[1]])
        minor_stmt = _stmt_text(minr, term_map[min_pair[0]], term_map[min_pair[1]])
        concl_stmt = _stmt_text(concl, s_noun, p_noun)
        fallacy = _classify_fallacy(maj, minr, concl, figure)
        elems = sorted(S | M | P)
        elem_names = [f"u{i + 1}" for i in range(len(elems))]
        elem_map = dict(zip(elems, elem_names))
        s_list = ", ".join(elem_map[e] for e in sorted(S)) or "(none)"
        m_list = ", ".join(elem_map[e] for e in sorted(M)) or "(none)"
        p_list = ", ".join(elem_map[e] for e in sorted(P)) or "(none)"
        text = (
            f"Flawed syllogism, mood {maj}{minr}{concl}, figure {figure} -- labeled INVALID:\n"
            f"Major premise: {major_stmt}\n"
            f"Minor premise: {minor_stmt}\n"
            f"Purported conclusion: {concl_stmt}\n\n"
            f"Named fallacy: {fallacy}.\n"
            "Counterexample (found by exhaustive search over small models): let the universe be "
            f"{{{', '.join(elem_names)}}}. Assign {s_noun} = {{{s_list}}}, {m_noun} = {{{m_list}}}, "
            f"{p_noun} = {{{p_list}}}. Both premises hold under this assignment, but the conclusion "
            f'"{concl_stmt}" is false -- so the argument is not valid.'
        )
        return text, "deliberate", "syllogism"


# ---------------------------------------------------------------------------
# First-order logic: quantifiers over a small explicit domain
# ---------------------------------------------------------------------------

_DOMAIN_POOL = ["a", "b", "c", "d", "e"]
_PRED_NAMES = sorted(["P", "Q"])


def _fol_doc(rng) -> tuple[str, str, str]:
    n_domain = rng.randint(3, 5)
    domain = _DOMAIN_POOL[:n_domain]
    p_ext = sorted(rng.sample(domain, rng.randint(1, n_domain)))
    q_ext = sorted(rng.sample(domain, rng.randint(1, n_domain)))
    p_set, q_set = set(p_ext), set(q_ext)

    kind = rng.choice(["univ_impl", "exist_conj", "univ_disjoint", "exist_diff"])

    def instance(x: str) -> bool:
        p, q = x in p_set, x in q_set
        if kind == "univ_impl" or kind == "exist_diff":
            return (not p) or q if kind == "univ_impl" else (p and not q)
        if kind == "exist_conj":
            return p and q
        return not (p and q)  # univ_disjoint

    quant = "univ" if kind in ("univ_impl", "univ_disjoint") else "exist"
    if kind == "univ_impl":
        stmt = f"∀x∈{{{', '.join(domain)}}}: P(x) → Q(x)"
    elif kind == "exist_conj":
        stmt = f"∃x∈{{{', '.join(domain)}}}: P(x) ∧ Q(x)"
    elif kind == "univ_disjoint":
        stmt = f"∀x∈{{{', '.join(domain)}}}: ¬(P(x) ∧ Q(x))"
    else:
        stmt = f"∃x∈{{{', '.join(domain)}}}: P(x) ∧ ¬Q(x)"

    lines = [
        f"Domain: {{{', '.join(domain)}}}.",
        f"P = {{{', '.join(p_ext) if p_ext else '(empty)'}}}   (elements for which P(x) is true)",
        f"Q = {{{', '.join(q_ext) if q_ext else '(empty)'}}}   (elements for which Q(x) is true)",
        f"Statement: {stmt}",
        "",
        "Instantiating over every domain element:",
    ]
    results = []
    for x in domain:  # fixed order (domain is a fixed-order slice of _DOMAIN_POOL)
        p, q = x in p_set, x in q_set
        val = instance(x)
        results.append((x, val))
        lines.append(f"  x={x}: P({x})={'T' if p else 'F'}, Q({x})={'T' if q else 'F'} -> instance = {'T' if val else 'F'}")

    if quant == "univ":
        holds = all(v for _, v in results)
        if holds:
            verdict = f"The universal statement HOLDS: every instance above is true."
        else:
            ce = next(x for x, v in results if not v)
            verdict = f"The universal statement FAILS: x={ce} is a counterexample (instance is false)."
    else:
        holds = any(v for _, v in results)
        if holds:
            wit = next(x for x, v in results if v)
            verdict = f"The existential statement HOLDS: x={wit} is a witness (instance is true)."
        else:
            verdict = "The existential statement FAILS: no domain element makes the instance true."

    lines.append("")
    lines.append(verdict)
    return "\n".join(lines), "deliberate", "quantifier"


# ---------------------------------------------------------------------------
# Wrong-proof / critique pairs
# ---------------------------------------------------------------------------

def _countermodel_2var(premises_hold, conclusion_holds) -> dict | None:
    """Search the 4 assignments of A,B for one where all premises hold and
    the conclusion fails. Deterministic order: (T,T),(T,F),(F,T),(F,F)."""
    for a in (True, False):
        for b in (True, False):
            assign = {"A": a, "B": b}
            if all(eval_formula(p, assign) for p in premises_hold) and not eval_formula(conclusion_holds, assign):
                return assign
    return None


def _wrong_proof_doc(rng) -> tuple[str, str, str]:
    flavor = rng.choice(["affirming_consequent", "denying_antecedent", "undistributed_middle"])
    if flavor == "undistributed_middle":
        valid_forms, invalid_forms = get_syllogism_table()
        pool = [t for t in invalid_forms if _classify_fallacy(*t[0]) == "undistributed middle"]
        if not pool:
            pool = invalid_forms
        (maj, minr, concl, figure), cex = rng.choice(pool)
        s_noun, m_noun, p_noun = _pick_terms(rng)
        term_map = {"S": s_noun, "M": m_noun, "P": p_noun}
        maj_pair, min_pair = _FIGURES[figure]
        major_stmt = _stmt_text(maj, term_map[maj_pair[0]], term_map[maj_pair[1]])
        minor_stmt = _stmt_text(minr, term_map[min_pair[0]], term_map[min_pair[1]])
        concl_stmt = _stmt_text(concl, s_noun, p_noun)
        S, M, P = cex
        elems = sorted(S | M | P)
        elem_names = [f"u{i + 1}" for i in range(len(elems))]
        elem_map = dict(zip(elems, elem_names))
        text = (
            "Wrong proof + critique.\n\n"
            f"Argument as given:\n1. {major_stmt}\n2. {minor_stmt}\n3. Therefore, {concl_stmt}\n\n"
            f"Critique: line 3 does not follow. The middle term ({m_noun}) is not distributed in either "
            "premise, so the premises fail to connect all members of the two outer classes -- this is "
            "the fallacy of the undistributed middle. Counterexample: with universe "
            f"{{{', '.join(elem_names)}}}, {s_noun} = {{{', '.join(elem_map[e] for e in sorted(S)) or '(none)'}}}, "
            f"{m_noun} = {{{', '.join(elem_map[e] for e in sorted(M)) or '(none)'}}}, "
            f"{p_noun} = {{{', '.join(elem_map[e] for e in sorted(P)) or '(none)'}}} -- both premises hold "
            f'but "{concl_stmt}" is false.'
        )
        return text, "deliberate", "undistributed_middle"

    a_name, b_name = "A", "B"
    premise1 = IMPLIES(A(a_name), A(b_name))
    if flavor == "affirming_consequent":
        premise2 = A(b_name)
        bad_conclusion = A(a_name)
        rule_claimed = "Modus Ponens"
        fallacy_name = "affirming the consequent"
        explanation = (
            f"Line 3 misapplies Modus Ponens. Modus Ponens requires the ANTECEDENT ({a_name}) as the "
            f"second premise, not the consequent ({b_name}). From {render(premise1)} and {render(premise2)} "
            f"we cannot validly infer {render(bad_conclusion)}."
        )
    else:
        premise2 = NOT(A(a_name))
        bad_conclusion = NOT(A(b_name))
        rule_claimed = "Modus Tollens"
        fallacy_name = "denying the antecedent"
        explanation = (
            f"Line 3 misapplies Modus Tollens. Modus Tollens requires the negated CONSEQUENT "
            f"(¬{b_name}) as the second premise, not the negated antecedent. From {render(premise1)} and "
            f"{render(premise2)} we cannot validly infer {render(bad_conclusion)}."
        )
    cm = _countermodel_2var([premise1, premise2], bad_conclusion)
    cm_str = ", ".join(f"{k}={'T' if v else 'F'}" for k, v in sorted(cm.items())) if cm else "none found"
    text = (
        "Wrong proof + critique.\n\n"
        "Argument as given:\n"
        f"1. {render(premise1)}   [Premise]\n"
        f"2. {render(premise2)}   [Premise]\n"
        f"3. {render(bad_conclusion)}   [claimed: {rule_claimed}, from lines 1, 2]\n\n"
        f"Critique: this is the fallacy of {fallacy_name}. {explanation} "
        f"Countermodel: {cm_str} satisfies both premises but makes the conclusion false, so the "
        "argument is invalid."
    )
    return text, "deliberate", fallacy_name.replace(" ", "_")


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class LogicGenerator(Generator):
    name = "logic"
    phases = (0,)

    _FAMILIES = [
        ("truth_table", 0.25, _truth_table_doc, "logic/truth_table"),
        ("natded", 0.30, _natded_doc, "logic/natded"),
        ("syllogism", 0.15, _syllogism_doc, "logic/syllogism"),
        ("fol", 0.15, _fol_doc, "logic/fol"),
        ("wrong_proof", 0.15, _wrong_proof_doc, "logic/critique"),
    ]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        cum_weights = []
        total = 0.0
        for _, w, _, _ in self._FAMILIES:
            total += w
            cum_weights.append(total)

        produced = 0
        while produced < target_bytes:
            r = self.rng.random() * total
            idx = 0
            while r > cum_weights[idx]:
                idx += 1
            _, _, builder, source = self._FAMILIES[idx]
            text, task_type, concept = builder(self.rng)
            d = self.doc(text=text, task_type=task_type, concept=concept, phase=0, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from ava.datagen.base import run_cli

    run_cli(LogicGenerator)
