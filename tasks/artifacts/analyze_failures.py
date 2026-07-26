import json
import sqlite3

con = sqlite3.connect(r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3")
con.row_factory = sqlite3.Row

print("--- state distribution ---")
for row in con.execute(
    "SELECT state, COUNT(*) c FROM experiments GROUP BY state ORDER BY c DESC"
):
    print(f"{row['state']}: {row['c']}")

print("\n--- failure column non-null by state ---")
for row in con.execute(
    "SELECT state, COUNT(failure) c FROM experiments WHERE failure IS NOT NULL GROUP BY state"
):
    print(f"{row['state']}: {row['c']}")

print("\n--- sample failure values (first 400 chars) per state ---")
for state in [r[0] for r in con.execute("SELECT DISTINCT state FROM experiments")]:
    rows = con.execute(
        "SELECT id, failure FROM experiments WHERE state=? AND failure IS NOT NULL LIMIT 2",
        (state,),
    ).fetchall()
    for r in rows:
        print(f"\n== state={state} id={r['id']}")
        print((r["failure"] or "")[:400].replace("\n", " | "))

print("\n--- implementation JSON keys of one row ---")
r = con.execute(
    "SELECT implementation FROM experiments WHERE implementation IS NOT NULL LIMIT 1"
).fetchone()
if r:
    d = json.loads(r["implementation"])
    print(list(d.keys()))
    for k, v in d.items():
        s = json.dumps(v)[:200]
        print(f"  {k}: {s}")
