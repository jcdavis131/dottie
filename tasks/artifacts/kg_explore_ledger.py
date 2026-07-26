# Read-only exploration of the ledger COPY for KG design (stdlib only).
import json
import sqlite3

con = sqlite3.connect(
    r"file:C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3?mode=ro", uri=True
)
con.row_factory = sqlite3.Row

print("--- states ---")
for row in con.execute(
    "SELECT state, COUNT(*) c FROM experiments GROUP BY state ORDER BY c DESC"
):
    print(f"{row['state']}: {row['c']}")

print("\n--- one failed_validation row (keys only, truncated values) ---")
row = con.execute(
    "SELECT * FROM experiments WHERE state='failed_validation' ORDER BY updated_ts DESC LIMIT 1"
).fetchone()
if row:
    for k in row.keys():
        v = row[k]
        s = str(v)
        print(f"{k}: {s[:220]}")
    impl = json.loads(row["implementation"]) if row["implementation"] else {}
    print("\nimplementation keys:", list(impl.keys()))
    hyp = json.loads(row["hypothesis"]) if row["hypothesis"] else {}
    print("hypothesis keys:", list(hyp.keys()))

print("\n--- failure text samples (first 160 chars, 8 rows) ---")
for row in con.execute(
    "SELECT id, state, substr(failure,1,160) f FROM experiments WHERE failure IS NOT NULL "
    "AND failure != '' ORDER BY updated_ts DESC LIMIT 8"
):
    print(f"[{row['id'][:12]} {row['state']}] {row['f']!r}")

print("\n--- does implementation JSON carry correction history? ---")
n_hist = 0
for row in con.execute(
    "SELECT implementation FROM experiments WHERE implementation IS NOT NULL"
):
    try:
        impl = json.loads(row["implementation"])
    except Exception:
        continue
    for key in ("history", "correction_history", "attempts", "validation"):
        if isinstance(impl, dict) and key in impl:
            n_hist += 1
            print(
                "sample keys with history-ish field:", key, "->", str(impl[key])[:200]
            )
            break
    if n_hist >= 3:
        break
print("rows with history-ish field seen:", n_hist)

print("\n--- eval_verdict sample ---")
row = con.execute(
    "SELECT eval_verdict FROM experiments WHERE eval_verdict IS NOT NULL AND eval_verdict!='' LIMIT 1"
).fetchone()
if row:
    print(str(row["eval_verdict"])[:400])
