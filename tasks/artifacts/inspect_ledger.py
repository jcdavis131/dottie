import sqlite3

con = sqlite3.connect(r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3")
con.row_factory = sqlite3.Row
for row in con.execute(
    "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
):
    print("=" * 70)
    print(row["type"], row["name"])
    print(row["sql"])
print("=" * 70)
for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    n = con.execute(f"SELECT COUNT(*) FROM {row['name']}").fetchone()[0]
    print(f"{row['name']}: {n} rows")
