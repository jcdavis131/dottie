import json
import re
import sqlite3
from collections import Counter, defaultdict

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

EXISTING = [
    ("einsum", r"einsum\(\)"),
    (
        "shape_algebra",
        r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes",
    ),
    ("ctor_missing_arg", r"missing \d+ required positional argument"),
    ("no_attribute", r"has no attribute '\w+'"),
    ("name_error", r"NameError: name"),
    ("nan_inf", r"NaN/Inf"),
    ("degenerate", r"degenerate block|RANK COLLAPSE|rank collapse"),
    ("output_shape_contract", r"the SAME \[batch, seq, hidden\] shape"),
]

# proposed new classes (checked only if no existing hint matches)
NEW = [
    (
        "autograd_in_forward",
        r"does not require grad and does not have a grad_fn|cannot register a hook on a tensor that doesn't require gradient|grad can be implicitly created only for scalar outputs|got an unexpected keyword argument 'retain_grad'",
    ),
    ("no_forward_method", r"no 'forward' method found on any class"),
    ("f821_undefined", r"F821 Undefined name"),
    ("loss_not_block_extra_arg", r"requires extra argument\(s\)"),
    (
        "escaped_newline_syntax",
        r"unexpected character after line continuation character",
    ),
    ("syntax_other", r"SyntaxError on line"),
    (
        "bad_fn_import",
        r"ImportError: cannot import name|ModuleNotFoundError: No module named",
    ),
    ("t_on_3d", r"t\(\) expects a tensor with <= 2 dimensions"),
    ("reshape_invalid", r"shape '\[[^\]]*\]' is invalid for input of size"),
    ("own_assert", r"AssertionError:"),
    (
        "index_gather",
        r"Index tensor must have the same number of dimensions|only integer tensors of a single element|index -?\d+ is out of bounds|selected index k out of range",
    ),
]


def classify(detail):
    for name, pat in EXISTING:
        if re.search(pat, detail):
            return ("existing", name)
    for name, pat in NEW:
        if re.search(pat, detail):
            return ("new", name)
    return ("new", "unclassified")


ERR_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\b.*|^F821 .*|^no 'forward'.*|^forward\(\) of .*|^SyntaxError.*",
    re.M,
)


def err_line(detail):
    hits = ERR_RE.findall(detail)
    return (
        hits[-1].strip()[:180]
        if hits
        else detail.strip().splitlines()[0][:180]
        if detail.strip()
        else "(empty)"
    )


rows = con.execute(
    "SELECT id, state, failure, implementation, hypothesis, attempts, created_ts "
    "FROM experiments WHERE implementation IS NOT NULL ORDER BY created_ts"
).fetchall()

per_attempt = Counter()
examples = defaultdict(list)

for r in rows:
    impl = json.loads(r["implementation"])
    hist = (impl.get("validation") or {}).get("history") or []
    for h in hist:
        if h.get("ok") is False and "detail" in h:
            det = h.get("detail") or ""
            kind, name = classify(det)
            per_attempt[(kind, name)] += 1
            if len(examples[name]) < 4:
                examples[name].append(
                    (r["id"], h.get("attempt"), h.get("level"), err_line(det))
                )

total = sum(per_attempt.values())
print(f"total failed attempts classified: {total}")
print("\n--- class counts (kind, class, n, share) ---")
for (kind, name), n in per_attempt.most_common():
    print(f"  {kind:8s} {name:26s} {n:4d}  {100 * n / total:.1f}%")

print("\n--- examples per NEW class ---")
for name, exs in examples.items():
    is_new = not any(name == e[0] for e in EXISTING)
    if not is_new:
        continue
    print(f"\n[{name}]")
    for id_, att, lvl, e in exs:
        print(f"  {id_} a{att} {lvl}: {e}")

# ---------------- recoveries: fail -> ok transcripts ----------------
print("\n" + "=" * 70)
print("RECOVERY TRANSCRIPTS (fail -> later ok)")
for r in rows:
    impl = json.loads(r["implementation"])
    v = impl.get("validation") or {}
    hist = v.get("history") or []
    fails = [h for h in hist if h.get("ok") is False]
    oks = [h for h in hist if h.get("ok")]
    if not (fails and oks):
        continue
    hyp = json.loads(r["hypothesis"]) if r["hypothesis"] else {}
    title = hyp.get("title") or hyp.get("name") or hyp.get("idea") or ""
    code = impl.get("code") or ""
    print(
        f"\n### id={r['id']} state={r['state']} attempts={v.get('attempts')} module={impl.get('module_name')}"
    )
    print(f"    hypothesis: {str(title)[:120]}")
    for h in hist:
        det = h.get("detail") or ""
        tag = "OK " if h.get("ok") else "FAIL"
        print(
            f"    a{h.get('attempt')} {tag} level={h.get('level')} :: {err_line(det)[:160]}"
        )
    # last failure detail fragment (what the corrector saw before the fix worked)
    last_fail = fails[-1]
    print(
        f"    LAST-FAIL DETAIL (first 300): {(last_fail.get('detail') or '')[:300]!r}"
    )
    print(f"    FINAL CODE ({len(code)} chars, first 500):")
    print("    " + "\n    ".join(code[:500].splitlines()))
