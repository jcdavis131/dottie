import json
import sqlite3

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

r = con.execute(
    "SELECT id, hypothesis, implementation FROM experiments WHERE implementation IS NOT NULL LIMIT 1"
).fetchone()
hyp = json.loads(r["hypothesis"])
impl = json.loads(r["implementation"])
print("hypothesis keys:", sorted(hyp.keys()))
print("hypothesis sample:", {k: str(v)[:80] for k, v in hyp.items()})
print("dry_run:", impl.get("dry_run"))
print("module_name:", impl.get("module_name"))
print("shape_assertions:", str(impl.get("shape_assertions"))[:200])

# recovered experiment ids + their states
rows = con.execute(
    "SELECT id, state, implementation FROM experiments WHERE implementation IS NOT NULL"
).fetchall()
for row in rows:
    im = json.loads(row["implementation"])
    hist = (im.get("validation") or {}).get("history") or []
    fails = [h for h in hist if h.get("ok") is False and "detail" in h]
    oks = [h for h in hist if h.get("ok") is True]
    if fails and oks:
        print("RECOVERED", row["id"], row["state"], "fails:", len(fails),
              "levels:", [h.get("level") for h in fails])
