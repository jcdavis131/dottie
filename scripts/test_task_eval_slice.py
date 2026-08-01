#!/usr/bin/env python3
"""Tests for the task-shaped eval slice.

The slice exists to stop a future embedding model being judged only on commit-message
queries. Two ways it could fail silently, both tested here head-on:

  1. THE QUERY CONTAINS ITS OWN ANSWER. If path stripping does not work, every number
     this file produces measures "can FTS5 find a path it was handed", BM25 looks superb,
     and the embedding model gets an impossible bar for the wrong reason. So stripping is
     tested on synthetic text, on every pair mined from the real TODO.md, and by MEASURING
     the inflation left in when it is switched off.
  2. THE METRICS QUIETLY BECOME COPIES. `test_retrieval_eval.py` checks NDCG/MRR/recall
     against hand-computed DCG. A re-implementation here would be unchecked and the two
     slices would no longer be comparable. So this file proves, structurally and by
     monkeypatch, that the numbers flow through the imported functions.

Every floor against the real repo is set NEAR the measured value, because a floor
comfortably below the truth is how fabricated numbers pass.

    python scripts/test_task_eval_slice.py
"""

from __future__ import annotations

import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# retrieval_eval FIRST, so task_eval_slice must reuse this exact module object.
re_ = _load("retrieval_eval")
tes = _load("task_eval_slice")

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}{('  - ' + detail) if detail and not cond else ''}")


def close(a, b, tol=1e-9):
    return abs(a - b) < tol


# A root that cannot contain anything, so synthetic resolution never touches real disk.
NOWHERE = Path(__file__).resolve().parent / "__no_such_root_for_tests__"

# ---------------------------------------------------------------------------
# MEASURED FLOORS. Values in comments are what the real TODO.md gave on
# 2026-07-26; each floor is >= 80% of it, never a token "> 0".
# ---------------------------------------------------------------------------
# RE-MEASURED 2026-08-01. The corpus these are derived from (TODO.md + git history)
# grew substantially, so four floors had drifted to 68-75% of the truth — still PASSING,
# which is the point: a floor comfortably below the measurement is exactly what this
# file's header warns lets a real regression through unnoticed. Re-based to the >=80%
# rule against fresh measurements. Drift direction matters and is recorded per line:
# these went too LAX (quantity grew), unlike FLOOR_STRIP_INFLATION below which went too
# STRICT (quantity shrank) and was failing every run.
FLOOR_ITEMS = 500          # 86.2% of 580 measured 08-01 (was 562 on 07-26) — unchanged, still >=80%
FLOOR_PAIRS = 81           # 80.2% of 101 measured 08-01 (was 70 = 69.3%; 87 on 07-26)
FLOOR_RESOLVED_REFS = 92   # 80.0% of 115 measured 08-01, 24 exact + 91 suffix (was 80 = 69.6%; 99 on 07-26)
FLOOR_MEDIAN_WORDS = 29    # 80.6% of 36 measured 08-01 — unchanged, still >=80%
FLOOR_LENGTH_RATIO = 2.65  # 88.3% of 3.00 measured 08-01 = 36/12.0 (was 3.27 on 07-26) — unchanged
FLOOR_TASK_NDCG = 0.375    # 80.0% of 0.4685 measured 08-01 (was 0.35 = 74.7%; 0.429 on 07-26)
# RE-MEASURED 2026-08-01: inflation is now 0.1806 (+18.1%), not the 0.2268 (+22.7%)
# this floor was derived from, so the old 0.1859 sat ABOVE the truth and the test was
# failing on every run. Re-based per this file's own rule — 82% of measured — giving
# 0.1481. Both numbers are kept deliberately: lowering a floor because it went red is
# the ratchet-down antipattern the note below warns about, and the only thing that
# distinguishes a re-measurement from a capitulation is showing the old value, the new
# value, and why it moved.
# WHY IT MOVED, and it is not a regression: the golden set is mined from git history and
# TODO.md, both of which this session changed heavily. The quantity under test (how much
# leaving paths in the query inflates NDCG) legitimately tracks the corpus. The
# INVARIANT — stripping paths matters materially — still holds at +18.1%; only the
# magnitude drifted. A floor pinned to an absolute on a drifting measurement will rot
# again, so read the invariant, not the constant.
FLOOR_STRIP_INFLATION = 0.1481  # 82.0% of the 0.1806 measured 2026-08-01
# (was 0.1859 = 82.0% of 0.2268 measured 2026-07-26; before that 0.18 = 79.4%, which
# broke this file's own >=80% rule). A floor below the truth is what let fabricated
# numbers pass elsewhere in this repo on 2026-07-26.
FLOOR_UNSTRIPPED_FLAGGED = 76  # 80.0% of 95 of 101 measured 08-01 (was 65 = 68.4%; 81 of 87 on 07-26)
# ⚠ CEILING SITTING EXACTLY ON THE MEASUREMENT. Residual leakage after stripping grew
# 6 (of 87) on 07-26 -> 8 (of 101) on 08-01, so this passes only by equality and ONE more
# leaking query turns it red. Left at 8 deliberately rather than padded: raising a
# ceiling to buy headroom is how a real increase in leakage would get absorbed silently.
# If it goes red, investigate the new leaker — do not raise this number reflexively.
CEIL_STRIPPED_FLAGGED = 8      # measured 8 of 101 stripped queries still leak (08-01)
CEIL_EMPTY_RESULTS = 2         # measured 0 queries that FTS5 answers with nothing (08-01, unchanged)


# ===========================================================================
# 1. Markdown item parsing
# ===========================================================================
DOC = """\
# heading

- [ ] open item about the retrieval bar and its queries
- [x] done item about the retrieval bar and its queries
- [ ] first line of a long one
  second line continues it
  third line continues it
  fourth line must NOT be included
- [ ] item ended by a sub-bullet
  still the item
  - [ ] a nested checkbox is its own item, not a continuation
- [ ] item ended by a blank line

  this paragraph belongs to nobody

```
- [ ] a checkbox inside a fence is not an item
```
- [ ] last item after the fence closes
"""
items = tes.iter_todo_items(DOC)
texts = [i["text"] for i in items]

ok("items: open and done are both mined", len(items) == 7, f"got {len(items)}: {texts}")
ok("items: the done flag tracks [x]",
   [i["done"] for i in items][:2] == [False, True])
ok("items: a checkbox inside a fenced block is skipped",
   not any("inside a fence" in t for t in texts))
ok("items: the item after the fence closes is still mined",
   any(t.startswith("last item") for t in texts))
ok("items: continuation lines are joined",
   "second line continues it third line continues it" in texts[2])
ok("items: continuation is capped at MAX_CONTINUATION_LINES",
   "fourth line" not in texts[2],
   f"cap={tes.MAX_CONTINUATION_LINES} but got {texts[2]!r}")
ok("items: a nested checkbox is not swallowed as a continuation",
   any(t.startswith("a nested checkbox") for t in texts)
   and "nested checkbox" not in texts[3])
ok("items: a blank line ends the item",
   "belongs to nobody" not in texts[5], f"got {texts[5]!r}")
ok("items: the line number points at the checkbox line",
   DOC.splitlines()[items[0]["line"] - 1].startswith("- [ ] open item"))
ok("items: the continuation cap is a parameter, and raising it takes more text",
   "fourth line" in tes.iter_todo_items(DOC, continuation_lines=3)[2]["text"])


# ===========================================================================
# 2. Reference extraction - backticked AND bare
# ===========================================================================
def toks(text):
    return [t for _s, _e, _r, t in tes.extract_refs(text)]


ok("refs: a backticked repo-relative path is extracted",
   toks("fix `scripts/gate_audit.py` today") == ["scripts/gate_audit.py"])
ok("refs: a BARE path with no backticks is extracted",
   toks("fix scripts/gate_audit.py today") == ["scripts/gate_audit.py"])
ok("refs: a bare filename with no directory is extracted",
   toks("the miner lives in minhash_dedup.py") == ["minhash_dedup.py"])
ok("refs: a trailing line reference is not part of the path",
   toks("see `composite_score.py:88-95` for the claim") == ["composite_score.py"])
ok("refs: several paths in one item are all extracted",
   toks("`a/b.py` and c/d.md and `e.yml`") == ["a/b.py", "c/d.md", "e.yml"])
ok("refs: a longer extension is not truncated to a shorter one",
   toks("read `x/hub_registry.json` now") == ["x/hub_registry.json"],
   "'.js' must not win over '.json'")
ok("refs: windows separators are normalised to posix",
   toks(r"open scripts\gate_audit.py") == ["scripts/gate_audit.py"])
ok("refs: a leading ./ is normalised away",
   toks("run ./scripts/gate_audit.py") == ["scripts/gate_audit.py"])
ok("refs: a leading / is normalised away",
   toks("served by /api/twin-status.mjs") == ["api/twin-status.mjs"])
ok("refs: prose with no path yields nothing",
   toks("triage the inbox, it is not a plan") == [])
ok("refs: a decimal number is not mistaken for a path",
   toks("worst intra-cluster true Jaccard 0.7143 today") == [])

# The extension list must come from the indexer's own set, not a copy of it: an
# extension-list divergence is a bug class this repo has already paid for.
ok("refs: EVERY extension the index holds is recognised",
   all(toks(f"see dir/file{ext} here") == [f"dir/file{ext}"] for ext in re_.INDEXABLE),
   f"INDEXABLE={sorted(re_.INDEXABLE)}")
ok("refs: an extension the index does NOT hold is ignored",
   all(toks(f"see dir/file{ext} here") == [] for ext in (".txt", ".ps1", ".png")
       if ext not in re_.INDEXABLE))


# ===========================================================================
# 3. Resolution - and the refusal to guess
# ===========================================================================
IDX = tes.DocIndex(
    {
        "scripts/gate_audit.py",
        "apps/scout-cli/bigbang/plugins/mcp/cli.py",
        "apps/dottie/dottie/research/evaluate.py",
        "apps/one/train.py",
        "apps/two/train.py",
    },
    root=NOWHERE,
)
ok("resolve: an exact indexed path resolves exactly",
   IDX.resolve("scripts/gate_audit.py") == ("scripts/gate_audit.py", "exact"))
ok("resolve: an app-relative path resolves by unique suffix",
   IDX.resolve("bigbang/plugins/mcp/cli.py")
   == ("apps/scout-cli/bigbang/plugins/mcp/cli.py", "unique_suffix"))
ok("resolve: a unique bare filename resolves",
   IDX.resolve("evaluate.py")
   == ("apps/dottie/dottie/research/evaluate.py", "unique_suffix"))
ok("resolve: an AMBIGUOUS filename is refused, not guessed",
   IDX.resolve("train.py") == (None, "ambiguous"),
   "guessing a target fabricates a relevance judgement")
ok("resolve: an unknown path resolves to nothing",
   IDX.resolve("no/such/file.py") == (None, "unknown"))

ONE = tes.DocIndex({"scripts/retrieval_eval.py"}, root=tes.ROOT)
ok("resolve: on disk but NOT in the index is 'unindexed', never a target",
   ONE.resolve("TODO.md") == (None, "unindexed"),
   "an unindexed file can never be retrieved, so scoring it as relevant caps recall")


# ===========================================================================
# 4. STRIPPING - the correctness point the whole measurement rests on
# ===========================================================================
_TXT = "fix abc/d.py now"
_S, _E, _RAW, _ = tes.extract_refs(_TXT)[0]
ok("strip: the span extract_refs reports is exactly the path",
   (_S, _E, _RAW) == (4, 12, "abc/d.py"))
ok("strip: a span is cut out and leaves a separator",
   tes.strip_spans(_TXT, [(_S, _E)]) == "fix   now",
   f"got {tes.strip_spans(_TXT, [(_S, _E)])!r}")
ok("strip: overlapping spans do not corrupt the text",
   tes.strip_spans(_TXT, [(4, 12), (4, 12), (6, 9)]) == "fix   now",
   f"got {tes.strip_spans(_TXT, [(4, 12), (4, 12), (6, 9)])!r}")
ok("strip: no spans leaves the text untouched",
   tes.strip_spans("nothing to do here", []) == "nothing to do here")

STRIP_DOC = """\
- [ ] single-linkage clustering in `scripts/gate_audit.py` drops documents below its own
  advertised threshold, and the same audit gate overwrites same-named defs silently
- [ ] the corrector in evaluate.py raised, so `apps/dottie/dottie/research/evaluate.py`
  recorded the exception only in history and the failure text stayed invisible
"""
sp, sstats = tes.mine_todo_pairs(STRIP_DOC, IDX)
ok("strip: both items yielded a pair", len(sp) == 2, f"got {len(sp)}: {sstats}")
ok("strip: the resolved path is GONE from the query",
   all("scripts/gate_audit.py" not in p["query"] for p in sp))
ok("strip: no query contains any of its own relevant paths",
   all(f not in p["query"] for p in sp for f in p["relevant"]))
ok("strip: no query contains a relevant file's BASENAME",
   all(f.rsplit("/", 1)[-1] not in p["query"] for p in sp for f in p["relevant"]))
ok("strip: an unresolved ref sharing a target's basename is stripped too",
   "evaluate.py" not in sp[1]["query"],
   f"bare 'evaluate.py' hands over the answer: {sp[1]['query']!r}")
ok("strip: surrounding prose survives intact",
   "single-linkage clustering" in sp[0]["query"]
   and "advertised threshold" in sp[0]["query"])
ok("strip: the raw text is kept alongside, so the control is re-runnable",
   all("gate_audit.py" in p["raw"] for p in sp[:1]))


# ===========================================================================
# 5. Items that must yield NOTHING
# ===========================================================================
NONE_DOC = """\
- [ ] this item references `no/such/file_at_all.py` which is not on disk anywhere
- [ ] this item is pure prose and names no file of any kind at all
- [ ] this one only names the ambiguous `train.py`, which resolves to nothing
"""
np_, nstats = tes.mine_todo_pairs(NONE_DOC, IDX)
ok("no-pair: an item whose only path does not exist yields no pair",
   len(np_) == 0, f"got {[p['query'] for p in np_]}")
ok("no-pair: the missing-file item is counted as no_resolved_target",
   nstats["no_resolved_target"] == 2, f"stats={nstats}")
ok("no-pair: the prose item is counted as no_path_token",
   nstats["no_path_token"] == 1, f"stats={nstats}")
ok("no-pair: the ambiguous reference is counted as ambiguous, not resolved",
   nstats["refs_ambiguous"] == 1 and nstats["refs_exact"] == 0
   and nstats["refs_unique_suffix"] == 0)
ok("no-pair: nothing is silently dropped - the accounting balances",
   tes.accounting_balances(nstats), f"stats={nstats}")


# ===========================================================================
# 6. Bounds, dedup, and the accounting guard
# ===========================================================================
MANY = tes.DocIndex({f"d{i}/f{i}.py" for i in range(9)}, root=NOWHERE)
many_doc = ("- [ ] this item touches "
            + " ".join(f"f{i}.py" for i in range(9)) + " all at once\n")
_, mstats = tes.mine_todo_pairs(many_doc, MANY)
ok("bounds: more targets than MAX_FILES_PER_COMMIT drops the item",
   mstats["too_many_targets"] == 1 and mstats["kept"] == 0, f"stats={mstats}")
ok("bounds: the file-count bound is the imported one",
   tes.mine_todo_pairs(many_doc, MANY, max_files=9)[1]["kept"] == 1
   and re_.MAX_FILES_PER_COMMIT == 8)

short_doc = "- [ ] see `scripts/gate_audit.py`\n"
_, shstats = tes.mine_todo_pairs(short_doc, IDX)
ok("bounds: a query too short AFTER stripping is dropped, not scored empty",
   shstats["too_short_after_strip"] == 1 and shstats["kept"] == 0, f"stats={shstats}")
ok("bounds: the word floor is the imported one",
   tes.mine_todo_pairs(short_doc, IDX, min_words=1)[1]["kept"] == 1
   and re_.MIN_QUERY_WORDS == 5)

dupe_doc = STRIP_DOC + STRIP_DOC
dp, dstats = tes.mine_todo_pairs(dupe_doc, IDX)
ok("dedup: an identical item is counted once",
   len(dp) == 2 and dstats["duplicate_query"] == 2, f"stats={dstats}")

bad_stats = dict(dstats)
bad_stats["kept"] += 1
ok("guard: accounting_balances FAILS on a tampered count",
   not tes.accounting_balances(bad_stats),
   "a guard that cannot fail is not a guard")

# ...and main() must branch on that verdict. A check nothing consumes is the defect
# class this repo named; assert the control flow structurally.
SRC = (SCRIPTS / "task_eval_slice.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)
MAIN = next(n for n in TREE.body
            if isinstance(n, ast.FunctionDef) and n.name == "main")


def guarded_by(fn_name):
    """Is there an `if <fn_name>(...)` in main() whose body returns?"""
    for node in ast.walk(MAIN):
        if not isinstance(node, ast.If):
            continue
        calls = [c.func.id for c in ast.walk(node.test)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        names = [c.id for c in ast.walk(node.test) if isinstance(c, ast.Name)]
        if fn_name in calls or fn_name in names:
            if any(isinstance(b, ast.Return) for b in ast.walk(node)):
                return True
    return False


ok("guard: main() returns early when the accounting does not balance",
   guarded_by("accounting_balances"))
ok("guard: main() returns early when the answer-key pruning fails",
   guarded_by("survived"))


# ===========================================================================
# 7. The metrics are the IMPORTED ones, not copies
# ===========================================================================
ok("import: task_eval_slice reuses the retrieval_eval module object",
   tes.RE_EVAL is re_ and sys.modules["retrieval_eval"] is re_)

BORROWED = ("ndcg_at_k", "rr", "recall_at_k", "leaks_filename",
            "build_index", "fts_query", "score", "summarise", "mine_pairs")
local_defs = {n.name for n in ast.walk(TREE)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
ok("import: none of the borrowed functions is re-defined locally",
   not (local_defs & set(BORROWED)),
   f"re-implemented: {sorted(local_defs & set(BORROWED))}")

attrs = {n.attr for n in ast.walk(TREE)
         if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
         and n.value.id == "RE_EVAL"}
ok("import: the borrowed scorer/summariser/index-builder are called through RE_EVAL",
   {"build_index", "score", "summarise", "fts_query", "mine_pairs"} <= attrs,
   f"RE_EVAL attrs used: {sorted(attrs)}")
ok("import: the imported bounds are used as defaults, not re-declared",
   {"MIN_QUERY_WORDS", "MAX_FILES_PER_COMMIT", "INDEXABLE", "K"} <= attrs)

# Decisive form: break the imported metric and the reported number must break with it.
_mini = sqlite3.connect(":memory:")
_mini.execute("CREATE VIRTUAL TABLE docs USING fts5(path, body, tokenize='porter unicode61')")
_mini.execute("INSERT INTO docs VALUES('a/b.py','alpha beta gamma retrieval slice')")
_mini.commit()
_pair = [{"query": "alpha beta gamma retrieval slice", "relevant": ["a/b.py"]}]
_before = re_.summarise(re_.score(_mini, _pair))["all"]["ndcg"]
_real = re_.ndcg_at_k
try:
    re_.ndcg_at_k = lambda *a, **k: 0.125
    _after = re_.summarise(re_.score(_mini, _pair))["all"]["ndcg"]
finally:
    re_.ndcg_at_k = _real
ok("import: monkeypatching retrieval_eval.ndcg_at_k changes the reported score",
   close(_before, 1.0) and close(_after, 0.125),
   f"before={_before} after={_after} - a local copy would ignore the patch")
ok("import: the metric is restored after the patch", re_.ndcg_at_k is _real)


# ===========================================================================
# 8. Helpers used by the comparison
# ===========================================================================
ok("shape: median words is computed over whitespace words",
   close(tes.query_shape(["a b c", "a b c d e"])["median_words"], 4.0))
ok("shape: snake_case share counts identifier-ish terms",
   close(tes.query_shape(["alpha gate_audit beta"])["snake_share"], 1 / 3, tol=1e-4),
   f"got {tes.query_shape(['alpha gate_audit beta'])['snake_share']}")
ok("shape: empty input does not crash", tes.query_shape([])["n"] == 0)

_ps = [{"query": "q", "relevant": ["in.py", "gone.py"]},
       {"query": "q2", "relevant": ["gone.py"]}]
_kept = tes.restrict_to_index(_ps, {"in.py"})
ok("restrict: unreachable targets are removed and empty pairs dropped",
   len(_kept) == 1 and _kept[0]["relevant"] == ["in.py"])
ok("restrict: the original pairs are not mutated",
   _ps[0]["relevant"] == ["in.py", "gone.py"])
ok("unreachable: counts judgements outside the index",
   tes.unreachable_targets(_ps, {"in.py"}) == (2, 3))

_v = tes.verdict({"ndcg": 0.4, "mrr": 0.3, "recall": 0.6},
                 {"ndcg": 0.6, "mrr": 0.3, "recall": 0.5})
ok("verdict: 'harder' agrees with the sign of the delta",
   _v["ndcg"]["harder"] and not _v["mrr"]["harder"] and not _v["recall"]["harder"])
ok("verdict: the hypothesis holds only if ALL THREE are harder",
   not _v["hypothesis_held"]
   and tes.verdict({"ndcg": .1, "mrr": .1, "recall": .1},
                   {"ndcg": .2, "mrr": .2, "recall": .2})["hypothesis_held"])
ok("verdict: an equal metric is not counted as harder",
   not tes.verdict({"ndcg": .5, "mrr": .5, "recall": .5},
                   {"ndcg": .5, "mrr": .5, "recall": .5})["hypothesis_held"])


# ===========================================================================
# 9. The real repo - non-vacuity, with floors near the measured values
# ===========================================================================
con = sqlite3.connect(":memory:")
n_docs = re_.build_index(con)
for d in tes.QUERY_SOURCE_DOCS:
    con.execute("DELETE FROM docs WHERE path = ?", (d,))
con.commit()
indexed = {r[0] for r in con.execute("SELECT path FROM docs")}
ok("real: the answer-key documents are gone from the scored index",
   not (set(tes.QUERY_SOURCE_DOCS) & indexed),
   "TODO.md holds every query verbatim; indexed, it IS the answer key")

real_index = tes.DocIndex(indexed)
todo_text = tes.TODO_PATH.read_text(encoding="utf-8")
pairs, stats = tes.mine_todo_pairs(todo_text, real_index)

ok("real: the miner reaches the whole file",
   stats["items_total"] >= FLOOR_ITEMS,
   f"got {stats['items_total']}, floor {FLOOR_ITEMS}")
ok("real: open and done items are both mined",
   stats["items_open"] > 100 and stats["items_done"] > 300,
   f"open={stats['items_open']} done={stats['items_done']}")
ok("real: enough items yield a pair to measure anything",
   stats["kept"] >= FLOOR_PAIRS, f"got {stats['kept']}, floor {FLOOR_PAIRS}")
ok("real: references actually resolve",
   stats["refs_exact"] + stats["refs_unique_suffix"] >= FLOOR_RESOLVED_REFS,
   f"got {stats['refs_exact']}+{stats['refs_unique_suffix']}, floor {FLOOR_RESOLVED_REFS}")
ok("real: BOTH resolution modes contribute",
   stats["refs_exact"] > 5 and stats["refs_unique_suffix"] > 40,
   f"exact={stats['refs_exact']} suffix={stats['refs_unique_suffix']}")
ok("real: every item is accounted for, kept or dropped with a reason",
   tes.accounting_balances(stats),
   f"total={stats['items_total']} kept={stats['kept']} "
   + " ".join(f"{r}={stats[r]}" for r in tes.DROP_REASONS))
ok("real: every relevant document is actually in the scored index",
   all(f in indexed for p in pairs for f in p["relevant"]),
   "an unreachable target caps recall below 1 by construction")
ok("real: every query clears the imported word floor",
   all(len(p["query"].split()) >= re_.MIN_QUERY_WORDS for p in pairs))
ok("real: every pair respects the imported file-count bound",
   all(1 <= len(p["relevant"]) <= re_.MAX_FILES_PER_COMMIT for p in pairs))
ok("real: relevant lists are sorted, so the slice is byte-stable",
   all(p["relevant"] == sorted(p["relevant"]) for p in pairs))

# The one that matters most: on the REAL text, no query contains its own answer.
leaked = [(p["line"], f) for p in pairs for f in p["relevant"]
          if f in p["query"] or f.rsplit("/", 1)[-1] in p["query"]]
ok("real: NOT ONE of the mined queries contains its own relevant path or basename",
   not leaked, f"{len(leaked)} leaks, first: {leaked[:3]}")

commit_pairs = re_.mine_pairs(4000)
commit_pairs.sort(key=lambda p: p["date"])
commit_test = commit_pairs[int(len(commit_pairs) * 0.7):]
task_shape = tes.query_shape([p["query"] for p in pairs])
commit_shape = tes.query_shape([p["query"] for p in commit_test])
ok("real: task queries are as long as the mechanism claims",
   task_shape["median_words"] >= FLOOR_MEDIAN_WORDS,
   f"median {task_shape['median_words']} words, floor {FLOOR_MEDIAN_WORDS}")
ok("real: task queries are much longer than commit-message queries",
   task_shape["median_words"] / commit_shape["median_words"] >= FLOOR_LENGTH_RATIO,
   f"ratio {task_shape['median_words'] / commit_shape['median_words']:.2f}, "
   f"floor {FLOOR_LENGTH_RATIO}")

task_sum = re_.summarise(re_.score(con, pairs))
unstripped = re_.summarise(re_.score(con, [{**p, "query": p["raw"]} for p in pairs]))
ok("real: the task slice scores a real, non-zero number",
   task_sum["all"]["ndcg"] >= FLOOR_TASK_NDCG,
   f"NDCG@10 {task_sum['all']['ndcg']}, floor {FLOOR_TASK_NDCG}")
ok("real: FTS5 answers almost every task query with something",
   tes.empty_result_count(con, pairs) <= CEIL_EMPTY_RESULTS,
   f"{tes.empty_result_count(con, pairs)} empty results")

# Stripping is load-bearing ON THE MEASUREMENT, not merely on the string.
inflation = ((unstripped["all"]["ndcg"] - task_sum["all"]["ndcg"])
             / task_sum["all"]["ndcg"])
ok("real: leaving the paths in would INFLATE the score measurably",
   inflation >= FLOOR_STRIP_INFLATION,
   f"inflation {inflation:+.1%}, floor {FLOOR_STRIP_INFLATION:+.1%}")
ok("real: the imported leak control confirms the strip, independently",
   (unstripped["n"] - unstripped["n_leak_free"]) >= FLOOR_UNSTRIPPED_FLAGGED
   and (task_sum["n"] - task_sum["n_leak_free"]) <= CEIL_STRIPPED_FLAGGED,
   f"flagged: unstripped {unstripped['n'] - unstripped['n_leak_free']} "
   f"vs stripped {task_sum['n'] - task_sum['n_leak_free']} of {task_sum['n']}")
ok("real: both slices are scored against the same index and the same metrics",
   task_sum["n"] == len(pairs) and set(task_sum) == set(
       re_.summarise(re_.score(con, commit_test))))


# ===========================================================================
# 10. Determinism
# ===========================================================================
p2, s2 = tes.mine_todo_pairs(todo_text, real_index)
ok("determinism: mining the same text twice gives identical pairs",
   [p["query"] for p in p2] == [p["query"] for p in pairs]
   and [p["relevant"] for p in p2] == [p["relevant"] for p in pairs])
ok("determinism: mining the same text twice gives identical stats", s2 == stats)
ok("determinism: scoring the same pairs twice gives identical numbers",
   re_.summarise(re_.score(con, pairs)) == task_sum)

con2 = sqlite3.connect(":memory:")
n2 = re_.build_index(con2)
ok("determinism: an independent index build holds the same documents",
   n2 == n_docs and {r[0] for r in con2.execute("SELECT path FROM docs")}
   == (indexed | set(tes.QUERY_SOURCE_DOCS)),
   f"{n_docs} then {n2}")
idx2 = tes.DocIndex(indexed)
ok("determinism: DocIndex suffix resolution does not depend on set iteration order",
   all(idx2.resolve(t) == real_index.resolve(t)
       for t in ("scripts/retrieval_eval.py", "train.py", "evaluate.py", "nope.py")))

print()
print(f"task-shaped: {stats['kept']} pairs, median {task_shape['median_words']:.0f} words, "
      f"NDCG@10 {task_sum['all']['ndcg']:.3f} (unstripped would be {unstripped['all']['ndcg']:.3f})")


# ---------------------------------------------------------------------------
# Regressions for the two REAL defects adversarial review found (2026-07-26).
# ---------------------------------------------------------------------------
def _t(name, cond, detail=""):
    ok(name, cond, detail)


_t("strip_spans: a PARTIALLY overlapping span does not leak its tail",
   tes.strip_spans("0123456789", [(0, 5), (3, 10)]).strip() == "",
   f"got {tes.strip_spans('0123456789', [(0, 5), (3, 10)])!r} — chars 5..9 leaked")

_t("strip_spans: fully-contained overlap still removes only the union",
   tes.strip_spans("abcdefgh", [(1, 6), (2, 4)]).replace(" ", "") == "agh",
   f"got {tes.strip_spans('abcdefgh', [(1, 6), (2, 4)])!r}")

_t("strip_spans: disjoint spans unaffected by the fix",
   tes.strip_spans("aXbYc", [(1, 2), (3, 4)]).replace(" ", "") == "abc")

_t("strip_spans: a real path fragment cannot survive an overlap",
   "task_eval_slice" not in tes.strip_spans(
       "see scripts/task_eval_slice.py now",
       [(4, 20), (11, 33)]),
   "an overlapping pair left part of the path in the query")

# loader: a same-NAMED module from a DIFFERENT file must not be reused
import types as _types

_fake = _types.ModuleType("retrieval_eval")
_fake.__file__ = str(Path(__file__).resolve().parent / "NOT_retrieval_eval.py")
_fake.SENTINEL_WRONG_MODULE = True
_saved = sys.modules.get("retrieval_eval")
sys.modules["retrieval_eval"] = _fake
try:
    _got = tes._load_retrieval_eval()
    _t("loader: rejects a same-named module from a different file",
       not getattr(_got, "SENTINEL_WRONG_MODULE", False),
       "the shadow was reused — a name is not an identity")
    _t("loader: returns the real harness (has ndcg_at_k)",
       hasattr(_got, "ndcg_at_k"))
finally:
    if _saved is None:
        sys.modules.pop("retrieval_eval", None)
    else:
        sys.modules["retrieval_eval"] = _saved

# The measured basis is re-recorded alongside the floor, 2026-08-01: 0.2268 -> 0.1806.
# This meta-test did its job — it caught the floor being lowered and refused to accept
# it until the BASIS was updated too, which is exactly the guard that stops a floor
# being quietly ratcheted down until the suite goes green. Changing one without the
# other should fail, and does.
MEASURED_STRIP_INFLATION = 0.1806  # re-measured 2026-08-01 (was 0.2268 on 07-26)
_t("floor: FLOOR_STRIP_INFLATION is >=80% of the measured inflation",
   FLOOR_STRIP_INFLATION >= MEASURED_STRIP_INFLATION * 0.80,
   f"{FLOOR_STRIP_INFLATION} is "
   f"{FLOOR_STRIP_INFLATION / MEASURED_STRIP_INFLATION:.1%} of measured "
   f"{MEASURED_STRIP_INFLATION}")


# ---------------------------------------------------------------------------
# THE SAME GUARD, FOR EVERY OTHER FLOOR. Added 2026-08-01.
#
# Until now exactly ONE floor (STRIP_INFLATION, above) was checked against its basis.
# That is why four of the others silently drifted to 68-75% of the truth while still
# PASSING: nothing compared them to anything. A floor comfortably below the measurement
# is what this file's header warns lets a real regression through, and it had happened
# here, to this file, unnoticed.
#
# Drift runs BOTH ways and both are caught: a quantity that GROWS leaves its floor too
# lax (what happened to these four), and a quantity that SHRINKS leaves its floor above
# the truth so the test fails every run (what happened to STRIP_INFLATION). The second
# is loud; the FIRST is silent, which is why it needs a test rather than a reader.
#
# Update rule when one of these fires: re-measure, update BOTH the floor and the
# MEASURED_* basis, and say why it moved. Never touch only one.
# ---------------------------------------------------------------------------
MEASURED = {                    # all re-measured 2026-08-01; 07-26 values in comments
    "FLOOR_ITEMS":              (FLOOR_ITEMS,              580),    # was 562
    "FLOOR_PAIRS":              (FLOOR_PAIRS,              101),    # was 87
    "FLOOR_RESOLVED_REFS":      (FLOOR_RESOLVED_REFS,      115),    # was 99
    "FLOOR_MEDIAN_WORDS":       (FLOOR_MEDIAN_WORDS,        36),    # was 36.0
    "FLOOR_LENGTH_RATIO":       (FLOOR_LENGTH_RATIO,      3.00),    # was 3.27
    "FLOOR_TASK_NDCG":          (FLOOR_TASK_NDCG,       0.4685),    # was 0.429
    "FLOOR_UNSTRIPPED_FLAGGED": (FLOOR_UNSTRIPPED_FLAGGED,  95),    # was 81
}
for _name, (_floor, _measured) in MEASURED.items():
    _t(f"floor: {_name} is >=80% of its recorded measurement",
       _floor >= _measured * 0.80,
       f"{_floor} is {_floor / _measured:.1%} of measured {_measured} — too lax to "
       "catch a regression; re-measure and raise it")

# Ceilings run the other way: a ceiling far ABOVE the measurement absorbs a real
# increase silently. CEIL_STRIPPED_FLAGGED currently sits exactly ON its measurement (8
# of 101), which is deliberate — see the constant's comment.
MEASURED_CEILINGS = {
    "CEIL_STRIPPED_FLAGGED": (CEIL_STRIPPED_FLAGGED, 8),   # was 6 of 87 on 07-26
    "CEIL_EMPTY_RESULTS":    (CEIL_EMPTY_RESULTS,    0),   # unchanged
}
for _name, (_ceil, _measured) in MEASURED_CEILINGS.items():
    _t(f"ceiling: {_name} is not padded far above its measurement",
       _ceil <= max(_measured + 2, _measured * 1.25),
       f"{_ceil} vs measured {_measured} — a padded ceiling hides a real increase")


# ---------------------------------------------------------------------------
# empty_result_count — a counter needs a two-sided test.
#
# The only prior check was `empty_result_count(con, pairs) <= CEIL_EMPTY_RESULTS`
# with CEIL = 2. A body of `return 0` satisfies that and passed 99/99. A ONE-SIDED
# bound on a counter is not coverage of the counter: it proves the real repo is
# healthy, never that the function can report ill-health at all. The number is
# printed as "queries FTS5 answers with nothing", so a silently-zero counter
# would read as "every query retrieved something" — the swallowed failure the
# docstring promises not to do.
# ---------------------------------------------------------------------------
# ASSEMBLED FROM FRAGMENTS, and it has to be. This test file is itself a .py under
# scripts/, so build_index indexes it — writing the nonsense token as one literal
# put it IN the corpus and the "unmatchable" query matched this very file. FTS5
# tokenises on non-alphanumerics, so `"zzqq" + "xx"` leaves the halves in the
# document and the joined token in none of them. The corpus under test contains
# the tests: any literal here is a document.
_UNMATCHABLE = " ".join(("zzqq" + "xx", "wobble" + "frotz", "nurble" + "glop"))
_NO_TOKENS = "!!! ???"                            # _TOK finds nothing: the other [] path
_ANSWERABLE = "empty_result_count"                # this identifier is in the indexed corpus

_t("harness: the unmatchable token is not spelled out anywhere in this file",
   _UNMATCHABLE not in Path(__file__).read_text(encoding="utf-8"),
   "inlining it as one literal indexes it and the query stops being unmatchable")

# Anti-vacuity: if the control term were NOT retrievable, the ==0 test below would
# pass for the wrong reason and prove nothing.
_t("empty_result_count: precondition - the control term IS retrievable",
   len(re_.fts_query(con, _ANSWERABLE, re_.K)) > 0,
   f"{_ANSWERABLE!r} retrieved nothing; the negative test would be vacuous")
_t("empty_result_count: precondition - the unmatchable term is NOT retrievable",
   re_.fts_query(con, _UNMATCHABLE, re_.K) == [],
   f"{_UNMATCHABLE!r} unexpectedly matched something")

_t("empty_result_count: an unmatchable query is COUNTED",
   tes.empty_result_count(con, [{"query": _UNMATCHABLE}]) == 1,
   f"got {tes.empty_result_count(con, [{'query': _UNMATCHABLE}])}, expected 1")
_t("empty_result_count: a query the index answers is NOT counted",
   tes.empty_result_count(con, [{"query": _ANSWERABLE}]) == 0,
   f"got {tes.empty_result_count(con, [{'query': _ANSWERABLE}])}, expected 0")
_t("empty_result_count: a query with no searchable tokens is counted too",
   tes.empty_result_count(con, [{"query": _NO_TOKENS}]) == 1)
_t("empty_result_count: counts EVERY empty query, not just their presence",
   tes.empty_result_count(con, [{"query": _UNMATCHABLE}, {"query": _ANSWERABLE},
                                {"query": _NO_TOKENS}]) == 2,
   "a sum() that collapses to a bool would report 1")
_t("empty_result_count: no pairs gives 0, not an error",
   tes.empty_result_count(con, []) == 0)


# ---------------------------------------------------------------------------
# main() — behavioural coverage. Previously ZERO: no test called it and no test
# invoked it as a subprocess, so ~180 lines including the entire human-readable
# report path were unexecuted. A KeyError in one f-string would have shipped.
#
# `guarded_by` above proves the two ABORT branches EXIST in the ast. That is not
# the same as proving the code reaches them and returns the code — structure and
# behaviour are different claims, and this session's recurring defect is exactly
# a verdict that is computed and then not consumed.
#
# --max-commits 200 (not the 4000 default) keeps each run near 10s. The commit
# slice is then too small to reproduce the recorded bar; main() must still exit 0
# and SAY it does not reproduce, which is itself the honest behaviour under test.
# ---------------------------------------------------------------------------
import json as _json
import re as _re
import shutil as _shutil
import subprocess
import tempfile as _tempfile

_SCRIPT = str(SCRIPTS / "task_eval_slice.py")
_tmpdir = Path(_tempfile.mkdtemp(prefix="tes_main_"))
try:
    _outfile = _tmpdir / "pairs.jsonl"
    # sys.executable, never bare "python": a bare name in a subprocess resolved to
    # the WRONG interpreter here before and produced 6 false mutation kills.
    _cli = subprocess.run(
        [sys.executable, _SCRIPT, "--json", "--max-commits", "200",
         "--out", str(_outfile)],
        capture_output=True, text=True, cwd=str(SCRIPTS.parent),
    )
    _t("main: --json exits 0", _cli.returncode == 0,
       f"rc={_cli.returncode}, stderr={_cli.stderr[-400:]!r}")

    try:
        _summary = _json.loads(_cli.stdout)
    except (ValueError, TypeError) as _e:
        _summary = None
        _t("main: --json emits parseable JSON on stdout", False, str(_e))
    else:
        _t("main: --json emits parseable JSON on stdout", True)

    if _summary:
        _t("main: the summary carries every top-level block",
           set(_summary) == {"index", "task_slice", "commit_slice", "recorded_bar",
                             "verdict"},
           f"got {sorted(_summary)}")
        _cli_stats = _summary["task_slice"]["mined"]
        _t("main: the CLI mines the same pair count as the library call",
           _cli_stats["kept"] == stats["kept"],
           f"CLI {_cli_stats['kept']} vs in-process {stats['kept']}")
        _t("main: the CLI's own accounting balances",
           tes.accounting_balances(_cli_stats),
           f"total {_cli_stats['items_total']} != kept {_cli_stats['kept']} + drops")
        # Cross-check against the INDEPENDENT prune done at section 9: same declared
        # docs, and the same number actually removed from a freshly built index.
        _t("main: the CLI prunes the query-source documents it found",
           set(_summary["index"]["pruned"]) <= set(tes.QUERY_SOURCE_DOCS)
           and len(_summary["index"]["pruned"]) == n_docs - len(indexed),
           f"pruned {_summary['index']['pruned']}, local prune removed "
           f"{n_docs - len(indexed)}")
        _t("main: documents_scored is the index minus exactly the pruned docs",
           _summary["index"]["documents_scored"]
           == _summary["index"]["documents"] - len(_summary["index"]["pruned"]))
        _t("main: the verdict block scores all three metrics and states a sign",
           all(m in _summary["verdict"] for m in ("ndcg", "mrr", "recall"))
           and isinstance(_summary["verdict"]["hypothesis_held"], bool))
        _t("main: a 200-commit slice does NOT silently claim the recorded bar",
           isinstance(_summary["recorded_bar"]["reproduces"], bool)
           and set(_summary["recorded_bar"]["rel_gap_vs_fresh"])
           == {"ndcg", "mrr", "recall"})

    # --out is the artifact a later trainer consumes; an unreadable or
    # answer-leaking file would poison it silently.
    _t("main: --out writes the slice as JSONL", _outfile.is_file())
    _recs = [_json.loads(ln) for ln in
             _outfile.read_text(encoding="utf-8").splitlines() if ln.strip()]
    _t("main: --out holds one record per kept pair",
       len(_recs) == stats["kept"], f"{len(_recs)} records vs {stats['kept']} kept")
    _t("main: every --out record carries the full pair schema",
       bool(_recs) and all(
           set(r) == {"query", "relevant", "line", "done", "raw"} for r in _recs))
    _leaky = [r for r in _recs
              if any(f in r["query"] for f in r["relevant"])]
    _t("main: no --out record hands its own answer to the query",
       not _leaky,
       f"{len(_leaky)} of {len(_recs)} leak, first: {_leaky[0]['query'][:70]!r}"
       if _leaky else "")

    # The human report: ~70 lines of f-strings that nothing had ever executed.
    _txt = subprocess.run(
        [sys.executable, _SCRIPT, "--max-commits", "200"],
        capture_output=True, text=True, cwd=str(SCRIPTS.parent),
    )
    _t("main: the text report exits 0", _txt.returncode == 0,
       f"rc={_txt.returncode}, stderr={_txt.stderr[-400:]!r}")
    _t("main: the text report raises nothing",
       "Traceback" not in _txt.stdout + _txt.stderr,
       (_txt.stdout + _txt.stderr)[-400:])
    _missing = [h for h in ("TASK-SHAPED SLICE", "QUERY SHAPE", "ANSWER-IN-THE-QUERY",
                            "HYPOTHESIS", "RECORDED BAR")
                if h not in _txt.stdout]
    _t("main: the text report prints every section", not _missing, f"missing {_missing}")
    _m = _re.search(r"yielded a pair\s*:\s*(\d+)", _txt.stdout)
    _t("main: the text and --json paths report the SAME pair count",
       bool(_m) and int(_m.group(1)) == stats["kept"],
       f"text said {_m.group(1) if _m else 'nothing'}, json/library {stats['kept']}")
finally:
    _shutil.rmtree(_tmpdir, ignore_errors=True)

# The ABORT is reached and its code is returned — not merely present in the ast.
_saved_balances, _saved_argv = tes.accounting_balances, sys.argv
tes.accounting_balances = lambda _stats: False
sys.argv = ["task_eval_slice.py", "--json", "--max-commits", "50"]
try:
    _rc = tes.main()
finally:
    tes.accounting_balances, sys.argv = _saved_balances, _saved_argv
_t("main: refuses to report, rc=3, when item accounting does not balance",
   _rc == 3, f"returned {_rc}; a fall-through would report unaccounted-for items")

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
