import json
import sqlite3

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT id, state, failure, implementation FROM experiments WHERE failure IS NOT NULL"
).fetchall()

lens = [len(r["failure"]) for r in rows]
print("failure text lengths: min", min(lens), "max", max(lens))

# Check whether implementation.validation has fuller detail + history
r = rows[0]
impl = json.loads(r["implementation"]) if r["implementation"] else {}
v = impl.get("validation", {})
print("validation keys:", list(v.keys()))
pl = v.get("per_level", {})
for lvl, d in pl.items():
    print(
        f"  per_level[{lvl}]: status={d.get('status')} detail_len={len(d.get('detail', ''))}"
    )

print("\n--- tails of 8 dry_run failures (last 500 chars) ---")
n = 0
for r in rows:
    if "at 'dry_run'" in (r["failure"] or "") and n < 8:
        n += 1
        print(f"\n== id={r['id']} state={r['state']} len={len(r['failure'])}")
        print(r["failure"][-500:])
