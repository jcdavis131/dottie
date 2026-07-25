import json
import re
import sqlite3
from collections import Counter, defaultdict

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

EXISTING = [
    ("einsum", r"einsum\(\)"),
    ("shape_algebra", r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes"),
    ("ctor_missing_arg", r"missing \d+ required positional argument"),
    ("no_attribute", r"has no attribute '\w+'"),
    ("name_error", r"NameError: name"),
    ("nan_inf", r"NaN/Inf"),
    ("degenerate", r"degenerate block|RANK COLLAPSE|rank collapse"),
    ("output_shape_contract", r"the SAME \[batch, seq, hidden\] shape"),
]
NEW = [
    ("autograd_in_forward", r"does not require grad and does not have a grad_fn|cannot register a hook on a tensor that doesn't require gradient|grad can be implicitly created only for scalar outputs|unexpected keyword argument 'retain_grad'"),
    ("no_forward_method", r"no 'forward' method found on any class"),
    ("f821_undefined", r"F821 Undefined name"),
    ("loss_not_block_extra_arg", r"requires extra argument\(s\)"),
    ("truncated_or_mangled_syntax", r"unexpected character after line continuation character|was never closed|unterminated string literal|unmatched '"),
    ("syntax_other", r"SyntaxError on line"),
    ("bad_fn_import", r"ImportError: cannot import name|ModuleNotFoundError: No module named"),
    ("t_on_3d", r"t\(\) expects a tensor with <= 2 dimensions"),
    ("reshape_invalid", r"is invalid for input of size"),
    ("index_gather", r"Index tensor must have the same number of dimensions|only integer tensors of a single element|is out of bounds for dimension|selected index k out of range"),
    ("own_assert", r"AssertionError:"),
]

def classify(detail):
    for name, pat in EXISTING:
        if re.search(pat, detail):
            return ("existing", name)
    for name, pat in NEW:
        if re.search(pat, detail):
            return ("new", name)
    return ("new", "unclassified")

rows = con.execute(
    "SELECT id, state, implementation FROM experiments WHERE implementation IS NOT NULL"
).fetchall()

attempt_c = Counter()
exp_sets = defaultdict(set)
no_hint_attempts = 0   # attempts where diagnose_failure returns '' (no pattern, and not dry_run-with-Traceback)
total = 0

for r in rows:
    impl = json.loads(r["implementation"])
    hist = (impl.get("validation") or {}).get("history") or []
    for h in hist:
        if h.get("ok") is False and "detail" in h:
            det = h.get("detail") or ""
            total += 1
            kind, name = classify(det)
            attempt_c[(kind, name)] += 1
            exp_sets[(kind, name)].add(r["id"])
            # emulate diagnose_failure: any EXISTING pattern -> hint; else dry_run+Traceback -> generic
            has_hint = kind == "existing" or (h.get("level") == "dry_run" and "Traceback" in det)
            if not has_hint:
                no_hint_attempts += 1

print(f"total failed attempts: {total}")
print(f"attempts that today receive NO hint at all: {no_hint_attempts} ({100*no_hint_attempts/total:.1f}%)")
ex_total = sum(n for (k, _), n in attempt_c.items() if k == "existing")
print(f"attempts covered by a targeted existing hint: {ex_total} ({100*ex_total/total:.1f}%)")
print("\nclass, attempts, distinct_experiments")
for (kind, name), n in attempt_c.most_common():
    print(f"  {kind:8s} {name:28s} {n:4d}  {len(exp_sets[(kind, name)]):3d} exps")
