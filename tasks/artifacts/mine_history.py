import json
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
    for name, pat in HINTS:
        if re.search(pat, detail):
            return name
    return None


ERR_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning)|AssertionError|KeyboardInterrupt)\b.*",
    re.M,
)


def err_line(detail):
    hits = ERR_RE.findall(detail)
    return hits[-1].strip()[:200] if hits else None


rows = con.execute(
    "SELECT id, state, failure, implementation, attempts, created_ts FROM experiments "
    "WHERE implementation IS NOT NULL ORDER BY created_ts"
).fetchall()

# ---- Terminal-failure taxonomy over EVERY failed attempt in history (the corrector
# sees each one, so each is a hint opportunity), plus terminal failures.
attempt_counter = Counter()  # class of every failed history entry
terminal_counter = Counter()  # class of final failure per failed_validation exp
uncovered_attempts = defaultdict(
    list
)  # cluster -> [(exp_id, attempt, level, errline, detail)]

n_hist_fail = 0
recoveries = []  # experiments with fail -> later ok in history

for r in rows:
    impl = json.loads(r["implementation"])
    v = impl.get("validation") or {}
    hist = v.get("history") or []
    fails = [h for h in hist if h.get("ok") is False and "detail" in h]
    n_hist_fail += len(fails)
    for h in fails:
        det = h.get("detail") or ""
        c = classify(det)
        if c:
            attempt_counter[c] += 1
        else:
            e = err_line(det) or (
                det.strip().splitlines()[0] if det.strip() else "(empty)"
            )
            key = re.sub(r"\d+", "N", e)
            key = re.sub(r"'[^']*'", "'X'", key)
            key = re.sub(r"\([^)]*\)", "(..)", key)[:120]
            attempt_counter["UNCOVERED"] += 1
            uncovered_attempts[(h.get("level"), key)].append(
                (r["id"], h.get("attempt"), e, det)
            )
    # terminal failure for failed_validation
    if r["state"] == "failed_validation" and fails:
        det = fails[-1].get("detail") or ""
        c = classify(det) or "UNCOVERED"
        terminal_counter[(fails[-1].get("level"), c)] += 1
    # recovery: some fail then final ok
    if fails and any(h.get("ok") for h in hist):
        recoveries.append(r["id"])

print(f"experiments with implementation: {len(rows)}")
print(f"total failed history attempts: {n_hist_fail}")
print("\n--- per-attempt failure classes (all failed attempts) ---")
for k, v_ in attempt_counter.most_common():
    print(f"  {k}: {v_}")

print("\n--- terminal failure class per failed_validation experiment ---")
for (lvl, c), n in terminal_counter.most_common():
    print(f"  level={lvl} class={c}: {n}")

print("\n--- UNCOVERED clusters across all failed attempts ---")
for (lvl, key), items in sorted(uncovered_attempts.items(), key=lambda kv: -len(kv[1])):
    print(f"\n[{len(items)}x] level={lvl} :: {key}")
    for exp_id, att, e, _ in items[:4]:
        print(f"    {exp_id} attempt={att} :: {e[:150]}")

print(f"\n--- experiments with a fail->ok recovery in history: {len(recoveries)} ---")
print(recoveries)
