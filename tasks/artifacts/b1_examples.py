# B1 mining aid: print one REAL detail fragment per new hint class, for tests.
import json
import re
import sqlite3
from collections import defaultdict

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(f"file:{DB}?mode=ro".replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

NEW = [
    ("f821", r"F821 Undefined name"),
    ("autograd", r"does not require grad and does not have a grad_fn|cannot register a hook on a tensor that doesn't require gradient|grad can be implicitly created only for scalar outputs|unexpected keyword argument 'retain_grad'"),
    ("skeleton", r"no 'forward' method found on any class|no class defined"),
    ("malformed", r"unexpected character after line continuation character|was never closed|unterminated string literal|unmatched '"),
    ("loss_vs_block", r"requires extra argument\(s\)"),
    ("own_assert", r"AssertionError:"),
    ("batched_t", r"t\(\) expects a tensor with <= 2 dimensions"),
    ("imports", r"ImportError: cannot import name|ModuleNotFoundError: No module named"),
    ("gather_topk", r"Index tensor must have the same number of dimensions|only integer tensors of a single element|is out of bounds for dimension|selected index k out of range"),
    ("invalid_for_size", r"is invalid for input of size"),
]

buckets = defaultdict(list)
syntax_lines = defaultdict(int)
static_lines = defaultdict(int)
rows = con.execute("SELECT id, implementation FROM experiments "
                   "WHERE implementation IS NOT NULL ORDER BY created_ts").fetchall()
for r in rows:
    impl = json.loads(r["implementation"])
    for h in (impl.get("validation") or {}).get("history") or []:
        if h.get("ok") is False and "detail" in h:
            det = h.get("detail") or ""
            lvl = h.get("level")
            for name, pat in NEW:
                if re.search(pat, det):
                    buckets[name].append((r["id"], lvl, det))
                    break
            if lvl == "syntax":
                syntax_lines[re.sub(r"\d+", "N", det.strip().splitlines()[0][:110] if det.strip() else "(empty)")] += 1
            if lvl == "static":
                for ln in det.splitlines():
                    m = re.search(r"\b([A-Z]\d{3})\b", ln)
                    if m:
                        static_lines[m.group(1)] += 1

for name, _ in NEW:
    items = buckets.get(name, [])
    print(f"\n===== {name} ({len(items)} attempts) =====")
    for exp_id, lvl, det in items[:2]:
        # show the matching region: last 400 chars usually holds the error line
        tail = det[-400:].replace("\n", "\\n")
        print(f"  [{exp_id} level={lvl}] ...{tail}")

print("\n===== ALL syntax-level first lines (normalized) =====")
for k, v in sorted(syntax_lines.items(), key=lambda kv: -kv[1]):
    print(f"  [{v}x] {k}")
print("\n===== static-level ruff codes =====")
for k, v in sorted(static_lines.items(), key=lambda kv: -kv[1]):
    print(f"  [{v}x] {k}")
