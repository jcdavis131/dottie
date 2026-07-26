import json
import sqlite3
from collections import Counter

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT id, state, implementation FROM experiments WHERE implementation IS NOT NULL"
).fetchall()

keys = Counter()
recov = 0
recov_with_code = 0
fail_only = 0
code_lens = []
for r in rows:
    impl = json.loads(r["implementation"])
    keys.update(impl.keys())
    hist = (impl.get("validation") or {}).get("history") or []
    fails = [h for h in hist if h.get("ok") is False and "detail" in h]
    oks = [h for h in hist if h.get("ok") is True]
    if fails and oks:
        recov += 1
        if impl.get("code"):
            recov_with_code += 1
    elif fails:
        fail_only += 1
    if impl.get("code"):
        code_lens.append(len(impl["code"]))

print("impl key frequencies:", dict(keys))
print("experiments:", len(rows))
print("fail->ok recoveries:", recov, "| of those with final code:", recov_with_code)
print("fail-only (never recovered):", fail_only)
print("code length min/max:", min(code_lens), max(code_lens), "n:", len(code_lens))

# show one recovered experiment end-to-end
for r in rows:
    impl = json.loads(r["implementation"])
    hist = (impl.get("validation") or {}).get("history") or []
    fails = [h for h in hist if h.get("ok") is False and "detail" in h]
    oks = [h for h in hist if h.get("ok") is True]
    if fails and oks and impl.get("code"):
        print("\n=== sample recovered:", r["id"], r["state"])
        for h in hist:
            print(
                "  attempt",
                h.get("attempt"),
                "ok:",
                h.get("ok"),
                "level:",
                h.get("level"),
                "detail[:120]:",
                (h.get("detail") or "")[:120].replace("\n", " | "),
            )
        print("  final code first 300 chars:")
        print(impl["code"][:300])
        break
