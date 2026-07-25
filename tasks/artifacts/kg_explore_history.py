# Read-only: does implementation.validation.history exist in the ledger COPY?
import json
import re
import sqlite3

con = sqlite3.connect(r"file:C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row

n_with, n_without, n_resolved_with = 0, 0, 0
sample = None
for row in con.execute(
        "SELECT id, state, attempts, implementation FROM experiments "
        "WHERE implementation IS NOT NULL"):
    try:
        impl = json.loads(row["implementation"])
    except Exception:
        continue
    v = impl.get("validation") or {}
    hist = v.get("history")
    if isinstance(hist, list) and hist:
        n_with += 1
        if row["state"] in ("rejected", "sota", "failed_training") and row["attempts"] > 0:
            n_resolved_with += 1
            if sample is None:
                sample = (row["id"], row["state"], hist)
    else:
        n_without += 1

print(f"rows with validation.history: {n_with}")
print(f"rows without: {n_without}")
print(f"RESOLVED-after-correction rows with history: {n_resolved_with}")
if sample:
    rid, state, hist = sample
    print(f"\nsample resolved row {rid} ({state}), history levels/ok:")
    for h in hist:
        detail = h.get("detail", "")
        has_einsum = bool(re.search(r"einsum\(\)", detail))
        print(f"  attempt={h.get('attempt')} ok={h.get('ok')} level={h.get('level')} "
              f"status={h.get('status')} einsum={has_einsum} detail[:80]={detail[:80]!r}")
