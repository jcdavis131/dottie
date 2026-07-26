import re
import sqlite3
from collections import Counter, defaultdict

DB = r"C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

HINTS = [
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


def classify(detail):
    hits = []
    for name, pat in HINTS:
        if re.search(pat, detail):
            hits.append(name)
    return hits


rows = con.execute(
    "SELECT id, state, failure, implementation, attempts FROM experiments "
    "WHERE failure IS NOT NULL ORDER BY created_ts"
).fetchall()

covered = Counter()
uncovered = []
level_counter = Counter()

for r in rows:
    detail = r["failure"] or ""
    m = re.search(r"validation failed at '(\w+)'", detail)
    level = m.group(1) if m else ("training" if "not integrable" in detail else "?")
    level_counter[level] += 1
    hits = classify(detail)
    if hits:
        covered[hits[0]] += 1
    else:
        uncovered.append((r["id"], r["state"], level, detail))

print("--- failure level distribution (failure column, n=%d) ---" % len(rows))
for k, v in level_counter.most_common():
    print(f"  {k}: {v}")

print("\n--- covered by existing _HINTS (first matching hint) ---")
for k, v in covered.most_common():
    print(f"  {k}: {v}")
print(f"  TOTAL covered: {sum(covered.values())}")
print(f"  TOTAL uncovered: {len(uncovered)}")


# cluster uncovered by salient error line
def salient(detail):
    # last exception-ish line
    lines = [l.strip() for l in detail.splitlines() if l.strip()]
    for l in reversed(lines):
        if (
            re.match(r"^\w+(\.\w+)*(Error|Exception|Warning)\b", l)
            or l.startswith("AssertionError")
            or "Error:" in l
        ):
            return l[:160]
    return (lines[-1] if lines else "")[:160]


clusters = defaultdict(list)
for id_, state, level, detail in uncovered:
    key_line = salient(detail)
    # normalize numbers for clustering
    key = re.sub(r"\d+", "N", key_line)
    key = re.sub(r"'[^']*'", "'X'", key)
    clusters[key].append((id_, state, level, key_line, detail))

print("\n--- uncovered clusters (normalized salient line) ---")
for key, items in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
    print(f"\n[{len(items)}x] {key}")
    for id_, state, level, key_line, _ in items[:5]:
        print(f"    id={id_} state={state} level={level} :: {key_line}")
