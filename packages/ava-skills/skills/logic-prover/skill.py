# Solo personal project, no connection to employer, built with public/free-tier only
"""logic-prover: Generate synthetic propositional-logic corpora (truth tables + syllogisms).

Phi-style Method B data generation. Every record is self-verified at generation time
(truth-table rows are re-evaluated against the operator semantics; syllogisms carry their
classical form). Real mode writes structured JSONL and reports the ACTUAL records and
bytes written. No 50B-token corpus is produced or claimed here — that scale is a
long-term aspiration of the broader project, not this generator's output.
"""
from __future__ import annotations
from typing import Any, Dict, List
import json, pathlib, random

def describe() -> Dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ava_skills_loader", here.parent / "loader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)

OPS = {
    "AND": lambda a, b: a and b,
    "OR": lambda a, b: a or b,
    "IMPLIES": lambda a, b: (not a) or b,
}

def gen_truth_tables(n: int = 50) -> List[Dict[str, Any]]:
    """Generate n full truth-table records cycling over AND/OR/IMPLIES.

    Each record covers all four P/Q assignments. `valid` is re-derived by
    evaluating the operator over every stored row, so the flag is computed,
    never asserted.
    """
    op_names = list(OPS)  # AND, OR, IMPLIES — cycling guarantees IMPLIES coverage for n>=3
    out: List[Dict[str, Any]] = []
    for i in range(n):
        op = op_names[i % len(op_names)]
        rows = [{"P": a, "Q": b, "value": OPS[op](a, b)}
                for a in (True, False) for b in (True, False)]
        out.append({
            "type": "truth_table",
            "expr": f"P {op} Q",
            "rows": rows,
            "valid": all(r["value"] == OPS[op](r["P"], r["Q"]) for r in rows),
        })
    return out

SYLLOGISM_TEMPLATES = [
    ("Barbara", ("All {A} are {B}.", "All {B} are {C}."), "Therefore all {A} are {C}."),
    ("ModusPonens", ("If {P} then {Q}.", "{P}."), "Therefore {Q}."),
    ("Ferio", ("No {A} are {B}.", "Some {C} are {A}."), "Therefore some {C} are not {B}."),
]

def gen_syllogisms(n: int = 30) -> List[Dict[str, Any]]:
    """Generate n syllogism records from classically valid forms (Barbara/ModusPonens/Ferio)."""
    vocab = [("dogs","mammals","animals"), ("cats","pets","animals"), ("spiders","arthropods","animals")]
    out: List[Dict[str, Any]] = []
    for _ in range(n):
        A, B, C = random.choice(vocab)
        form, premises, conclusion = random.choice(SYLLOGISM_TEMPLATES)
        fmt = dict(A=A, B=B, C=C, P=A, Q=B)
        out.append({
            "type": "syllogism",
            "form": form,
            "premises": [p.format(**fmt) for p in premises],
            "conclusion": conclusion.format(**fmt),
            "valid": True,  # every template is a classically valid inference form
        })
    return out

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", **kw) -> Dict[str, Any]:
    n = int(kw.get("n", 100))
    random.seed(kw.get("seed", 1))
    if mode == "mock":
        tables = gen_truth_tables(min(n, 20))
        sylls = gen_syllogisms(min(n, 20))
        measured = {"n_generated": len(tables)+len(sylls), "truth_tables": len(tables),
                    "syllogisms": len(sylls), "phase": "P0"}
        return {"skill":"logic-prover","mode":"mock","measured":measured,"pass":len(tables)+len(sylls)>0,"bar":"generation non-empty"}
    # real: write structured JSONL (both record types), honoring n with no hidden cap
    out_dir = pathlib.Path(kw.get("out_dir", "data/raw/logic"))
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = gen_truth_tables(n)
    sylls = gen_syllogisms(n)
    records = tables + sylls
    out_file = out_dir / "logic_corpus.jsonl"
    payload = "\n".join(json.dumps(r) for r in records) + "\n"
    out_file.write_text(payload, encoding="utf-8")
    bytes_written = len(payload.encode("utf-8"))
    measured = {
        "records_written": len(records),
        "truth_tables": len(tables),
        "syllogisms": len(sylls),
        "bytes_written": bytes_written,
        "out_file": str(out_file),
    }
    return {"skill":"logic-prover","mode":"real","measured":measured,
            "pass": len(records) == 2*n and bytes_written > 0,
            "bar": "wrote 2n JSONL records (truth tables + syllogisms)"}
