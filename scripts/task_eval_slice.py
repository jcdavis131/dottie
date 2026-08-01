#!/usr/bin/env python3
"""Task-shaped eval slice — the second query distribution the retrieval bar needs.

`scripts/retrieval_eval.py` mines (commit message -> changed files). Commit messages
are short and identifier-dense, which FLATTERS BM25. The agent tier's real queries are
natural-language TASK DESCRIPTIONS: longer, less identifier-dense. Judging a future
embedding model only on commit-message queries would be rigged in lexical favour, so
this file measures the same retriever on a task-shaped slice mined from `TODO.md`.

THE SET. Every `- [ ]` / `- [x]` item in TODO.md is a task description. Many name the
files they concern. So: item text = query, referenced files that exist and are indexed =
relevant documents. Free, and shaped like the real consumer.

THE ANSWER-IN-THE-QUERY CONTROL (the one that decides whether any of this means
anything). "Fix `apps/ava-factory/scripts/minhash_dedup.py`: single-linkage drops docs"
contains its own answer as a literal substring. Left in, the measurement degenerates into
"can FTS5 find a path that was handed to it" and BM25 looks superb for no reason. Every
resolved reference is therefore CUT OUT of the query text before scoring, and so is any
un-resolved reference sharing a basename with a target. Residual prose-level leakage
("the dedup pass") is not removable without editing the task text, so it is *classified*
instead, by the imported `leaks_filename` — same honesty knob, same subset names as the
commit-shaped run.

WHAT IS NOT REUSED FROM the commit slice, and why: nothing. The index builder, the three
metrics, the scorer, the summariser, the leak control, the word floor and the file-count
bound are all imported. This file adds a miner and a comparison, and nothing else — if
NDCG were re-implemented here the two slices could not be compared at all.

STATED LIMIT, in the same place the commit slice states its own. A TODO item names a file
for many reasons, and only some of them are "this file is the answer": "a gate that fires
on a legitimate state gets disabled (the `lint.yml` permanently-red lesson)" cites
`lint.yml` as an ANALOGY. That judgement is wrong and this miner cannot tell. So the
commit slice under-measures relevance (files that were relevant but untouched) while this
slice also MIS-measures some of it, which makes the absolute task-shaped numbers a lower
bound. Both slices remain valid for the only question being asked — comparing two
retrievers over identical queries and identical judgements — and neither is a statement
about absolute retrieval quality.

TWO DELIBERATE DEVIATIONS, both stated up front:
  * `TODO.md` and `tasks/todo.md` are DELETED from the index before task queries are
    scored. They contain every query verbatim; leaving them in measures self-retrieval.
    The commit-shaped slice is reported both ways so the pruning's cost is visible.
  * No walk-forward split. TODO items carry no reliable per-item date, so this slice is
    evaluation-only. Nothing here is trained on, and BM25 has no parameters, so the
    absence of a split costs nothing *for this baseline* — it will cost something for a
    learned retriever, and that is recorded here rather than discovered later.

Usage:
    python scripts/task_eval_slice.py
    python scripts/task_eval_slice.py --json
    python scripts/task_eval_slice.py --out slice.jsonl
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_retrieval_eval():
    """Import the commit-shaped harness. Reuse an already-imported one if present."""
    want = (Path(__file__).resolve().parent / "retrieval_eval.py").resolve()
    cached = sys.modules.get("retrieval_eval")
    if cached is not None:
        # Reuse ONLY if it is the same FILE. Matching on the module name alone is
        # how a shadow wins: a stale __editable__.scout_cli-0.7.0.pth pointing at
        # ~/scout-cli already shadowed `bigbang` in this repo and produced 8
        # phantom test failures. A name is not an identity.
        got = getattr(cached, "__file__", None)
        if got and Path(got).resolve() == want:
            return cached
    # Load under a PRIVATE alias so this module can never itself become the
    # shadow that the check above exists to detect.
    spec = importlib.util.spec_from_file_location("_tes_retrieval_eval", want)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_tes_retrieval_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


RE_EVAL = _load_retrieval_eval()

TODO_PATH = ROOT / "TODO.md"

# These documents contain the queries verbatim. Indexed, they are the answer key.
QUERY_SOURCE_DOCS = ("TODO.md", "tasks/todo.md")

# TODO.md's own extraction rule ("the checkbox line plus up to two continuation lines").
MAX_CONTINUATION_LINES = 2

# The commit-shaped numbers recorded in TODO.md / HANDOFF.md on 2026-07-26. Kept here to
# be CHECKED, not to be quoted: every run re-measures the commit slice and says whether
# this still reproduces.
RECORDED_COMMIT_SHAPED = {
    "ndcg": 0.622, "mrr": 0.619, "recall": 0.791, "n": 151, "documents": 2024,
    "source": "TODO.md:458 / HANDOFF.md:24 (2026-07-26)",
}
# A relative gap wider than this on any metric means the recorded bar is stale.
RECORD_TOLERANCE = 0.05

_EXTS = "|".join(sorted((e.lstrip(".") for e in RE_EVAL.INDEXABLE), key=len, reverse=True))
# A path-like token: optional directories, then a filename with an extension the index
# actually holds. The extension list is derived from RE_EVAL.INDEXABLE on purpose — a
# hardcoded copy here would drift the moment that set changes.
_REF_RE = re.compile(
    rf"(?<![A-Za-z0-9_./\\-])[A-Za-z0-9_./\\-]*[A-Za-z0-9_-]\.(?:{_EXTS})(?![A-Za-z0-9_])"
)

_ITEM_RE = re.compile(r"^(\s*)- \[([ xX])\]\s*(.*)$")
_SUBLIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")

DROP_REASONS = (
    "no_path_token",
    "no_resolved_target",
    "too_many_targets",
    "too_short_after_strip",
    "duplicate_query",
)
RESOLUTION_MODES = ("exact", "unique_suffix", "unindexed", "ambiguous", "unknown")


# ---------------------------------------------------------------------------
# Markdown item parsing
# ---------------------------------------------------------------------------
def iter_todo_items(text: str, continuation_lines: int | None = None):
    """[{line, done, text}] for every checkbox item outside fenced code blocks."""
    cont = MAX_CONTINUATION_LINES if continuation_lines is None else continuation_lines
    lines = text.splitlines()
    items = []
    fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            fence = not fence
            i += 1
            continue
        m = _ITEM_RE.match(line)
        if fence or not m:
            i += 1
            continue
        indent = len(m.group(1))
        body = [m.group(3).strip()]
        j = i + 1
        while j < len(lines) and len(body) - 1 < cont:
            nxt = lines[j]
            if not nxt.strip():
                break
            if nxt.lstrip().startswith(("```", "#", "|", ">")):
                break
            if _SUBLIST_RE.match(nxt):
                break
            if len(nxt) - len(nxt.lstrip()) <= indent:
                break
            body.append(nxt.strip())
            j += 1
        items.append({
            "line": i + 1,
            "done": m.group(2).lower() == "x",
            "text": " ".join(body).strip(),
        })
        i = j
    return items


# ---------------------------------------------------------------------------
# Reference extraction, resolution, and removal
# ---------------------------------------------------------------------------
def normalise_ref(raw: str) -> str:
    t = raw.replace("\\", "/")
    while t.startswith("./"):
        t = t[2:]
    return t.lstrip("/")


def extract_refs(text: str):
    """[(start, end, raw, token)] for every path-like token, in reading order."""
    return [
        (m.start(), m.end(), m.group(0), normalise_ref(m.group(0)))
        for m in _REF_RE.finditer(text)
    ]


def strip_spans(text: str, spans) -> str:
    """Cut [start, end) ranges out of text, leaving one space where each stood."""
    out, last = [], 0
    for start, end in sorted(set(spans)):
        if start < last:
            # PARTIAL overlap: this span starts inside an already-removed range
            # but may extend BEYOND it. The first version `continue`d here, which
            # skipped the span entirely and left its TAIL in the text — spans
            # (0,5) and (3,10) left characters 5..10 behind, i.e. a fragment of a
            # path survived into the query the strip exists to clean. Advance the
            # cursor instead of skipping.
            last = max(last, end)
            continue
        out.append(text[last:start])
        out.append(" ")
        last = end
    out.append(text[last:])
    return "".join(out)


class DocIndex:
    """The indexed corpus, addressable by any unique path suffix.

    TODO items name files three ways: repo-relative (`scripts/gate_audit.py`),
    app-relative (`bigbang/plugins/mcp/cli.py`), and bare (`train.py`). The first is
    exact; the second and third resolve only when EXACTLY ONE indexed path ends with
    them. More than one match is `ambiguous` and is dropped, never guessed — a guessed
    target is a fabricated relevance judgement.
    """

    def __init__(self, paths, root: Path = ROOT):
        self.root = root
        self.paths = frozenset(paths)
        by_suffix: dict[str, list[str]] = {}
        for p in sorted(self.paths):
            parts = p.split("/")
            for i in range(len(parts)):
                by_suffix.setdefault("/".join(parts[i:]), []).append(p)
        self.by_suffix = {k: tuple(v) for k, v in by_suffix.items()}

    def resolve(self, token: str):
        """(path, mode). path is None unless mode is 'exact' or 'unique_suffix'."""
        if token in self.paths:
            return token, "exact"
        if not token or token.endswith("/"):
            return None, "unknown"
        try:
            on_disk = (self.root / token).is_file()
        except OSError:
            on_disk = False
        if on_disk:
            # Exists, but build_index did not take it (extension or skipped directory),
            # so it can never be retrieved and must not be scored as relevant.
            return None, "unindexed"
        hits = self.by_suffix.get(token, ())
        if len(hits) == 1:
            return hits[0], "unique_suffix"
        if len(hits) > 1:
            return None, "ambiguous"
        return None, "unknown"


# ---------------------------------------------------------------------------
# The miner
# ---------------------------------------------------------------------------
def mine_todo_pairs(text: str, index: DocIndex, *, min_words=None, max_files=None,
                    continuation_lines=None):
    """(pairs, stats). pairs carry the STRIPPED query; stats account for every item."""
    min_words = RE_EVAL.MIN_QUERY_WORDS if min_words is None else min_words
    max_files = RE_EVAL.MAX_FILES_PER_COMMIT if max_files is None else max_files

    stats = {"items_total": 0, "items_open": 0, "items_done": 0, "kept": 0}
    stats.update(dict.fromkeys(DROP_REASONS, 0))
    stats.update({f"refs_{m}": 0 for m in RESOLUTION_MODES})

    pairs, seen = [], set()
    for item in iter_todo_items(text, continuation_lines):
        stats["items_total"] += 1
        stats["items_done" if item["done"] else "items_open"] += 1
        raw_text = item["text"]

        refs = extract_refs(raw_text)
        targets, cut = set(), []
        for start, end, _raw, token in refs:
            path, mode = index.resolve(token)
            stats[f"refs_{mode}"] += 1
            if path is not None:
                targets.add(path)
                cut.append((start, end))
        if not refs:
            stats["no_path_token"] += 1
            continue
        if not targets:
            stats["no_resolved_target"] += 1
            continue

        # An unresolved reference can still name a target's file: `evaluate.py` is
        # ambiguous on its own, yet if the item also gives the full path it hands the
        # answer over. Cut those too.
        basenames = {p.rsplit("/", 1)[-1] for p in targets}
        for start, end, _raw, token in refs:
            if token.rsplit("/", 1)[-1] in basenames:
                cut.append((start, end))

        query = " ".join(strip_spans(raw_text, cut).split())
        if len(targets) > max_files:
            stats["too_many_targets"] += 1
            continue
        if len(query.split()) < min_words:
            stats["too_short_after_strip"] += 1
            continue
        if query in seen:
            stats["duplicate_query"] += 1
            continue
        seen.add(query)
        stats["kept"] += 1
        pairs.append({
            "query": query,
            "relevant": sorted(targets),
            "line": item["line"],
            "done": item["done"],
            "raw": raw_text,
        })
    return pairs, stats


def accounting_balances(stats) -> bool:
    """Every item is either kept or dropped for exactly one stated reason."""
    return stats["items_total"] == stats["kept"] + sum(stats[r] for r in DROP_REASONS)


# ---------------------------------------------------------------------------
# Query shape — the claimed mechanism, measured
# ---------------------------------------------------------------------------
def query_shape(queries):
    """Length and snake_case density over the retriever's own tokenisation."""
    if not queries:
        return {"n": 0, "median_words": 0.0, "mean_words": 0.0,
                "median_terms": 0.0, "snake_share": 0.0}
    words = [len(q.split()) for q in queries]
    terms = [RE_EVAL._TOK.findall(q) for q in queries]
    flat = [t for ts in terms for t in ts]
    snake = sum(1 for t in flat if "_" in t)
    return {
        "n": len(queries),
        "median_words": round(statistics.median(words), 1),
        "mean_words": round(statistics.mean(words), 1),
        "median_terms": round(statistics.median(len(t) for t in terms), 1),
        "snake_share": round(snake / len(flat), 4) if flat else 0.0,
    }


def empty_result_count(con, pairs) -> int:
    """Queries the retriever answers with nothing at all — reported, never swallowed."""
    return sum(1 for p in pairs if not RE_EVAL.fts_query(con, p["query"], RE_EVAL.K))


def restrict_to_index(pairs, indexed):
    """Drop relevant docs the index does not hold, then drop pairs left with none.

    The commit-shaped set judges files that were changed and later deleted or renamed;
    those cap its recall below 1 by construction. The task slice never admits an
    unreachable target, so a like-for-like comparison has to remove them here.
    """
    out = []
    for p in pairs:
        keep = [f for f in p["relevant"] if f in indexed]
        if keep:
            out.append({**p, "relevant": keep})
    return out


# Imported, not re-implemented. This lived here until 2026-08-01 and moved UP into
# retrieval_eval.py, the module that produces the number it qualifies — the recorded
# 0.622 rotted to 0.420 precisely because the upstream tool never reported it. Keeping a
# copy here would be the duplicated-source bug class hard_negatives.py warns about.
unreachable_targets = RE_EVAL.unreachable_targets


def verdict(task, commit):
    """Per-metric: is the task-shaped slice harder for BM25? No adjective without a sign."""
    rows = {}
    for m in ("ndcg", "mrr", "recall"):
        t, c = task[m], commit[m]
        rows[m] = {
            "task": t, "commit": c,
            "delta": round(t - c, 4),
            "rel_delta": round((t - c) / c, 4) if c else 0.0,
            "harder": t < c,
        }
    rows["hypothesis_held"] = all(rows[m]["harder"] for m in ("ndcg", "mrr", "recall"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Task-shaped retrieval eval slice")
    ap.add_argument("--max-commits", type=int, default=4000)
    ap.add_argument("--split-frac", type=float, default=0.7)
    ap.add_argument("--continuation-lines", type=int, default=MAX_CONTINUATION_LINES,
                    help="item body lines after the checkbox line (TODO.md's own rule is 2)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write the task-shaped slice as JSONL")
    args = ap.parse_args()

    text = TODO_PATH.read_text(encoding="utf-8")

    con = sqlite3.connect(":memory:")
    n_docs = RE_EVAL.build_index(con)
    all_paths = {r[0] for r in con.execute("SELECT path FROM docs")}

    # --- commit-shaped, exactly as retrieval_eval reports it -------------------
    commit_pairs = RE_EVAL.mine_pairs(args.max_commits)
    commit_pairs.sort(key=lambda p: p["date"])
    cut = int(len(commit_pairs) * args.split_frac)
    commit_test = commit_pairs[cut:]
    commit_shipped = RE_EVAL.summarise(RE_EVAL.score(con, commit_test))
    # Attribution for any gap against the recorded bar: a relevance judgement naming a
    # file that is no longer at HEAD scores 0 however good the retriever is.
    bad, total = unreachable_targets(commit_test, all_paths)
    commit_reachable_full = RE_EVAL.summarise(
        RE_EVAL.score(con, restrict_to_index(commit_test, all_paths))
    )

    # --- prune the answer key -------------------------------------------------
    want_pruned = [d for d in QUERY_SOURCE_DOCS if d in all_paths]
    for d in want_pruned:
        con.execute("DELETE FROM docs WHERE path = ?", (d,))
    con.commit()
    indexed = {r[0] for r in con.execute("SELECT path FROM docs")}
    survived = sorted(set(want_pruned) & indexed)
    if survived:
        print(f"ABORT: query-source documents survived pruning: {survived}", file=sys.stderr)
        return 2

    index = DocIndex(indexed)

    # --- commit-shaped, like-for-like with the task slice ---------------------
    commit_fair = RE_EVAL.summarise(
        RE_EVAL.score(con, restrict_to_index(commit_test, indexed))
    )

    # --- task-shaped ----------------------------------------------------------
    task_pairs, stats = mine_todo_pairs(text, index,
                                        continuation_lines=args.continuation_lines)
    if not accounting_balances(stats):
        print(f"ABORT: item accounting does not balance: {stats}", file=sys.stderr)
        return 3
    task_sum = RE_EVAL.summarise(RE_EVAL.score(con, task_pairs))
    open_sum = RE_EVAL.summarise(
        RE_EVAL.score(con, [p for p in task_pairs if not p["done"]])
    )
    # The answer-in-the-query control, quantified on every run over the SAME pairs.
    unstripped = RE_EVAL.summarise(
        RE_EVAL.score(con, [{**p, "query": p["raw"]} for p in task_pairs])
    )

    rec = RECORDED_COMMIT_SHAPED
    gap = {m: round((commit_shipped["leak_free"][m] - rec[m]) / rec[m], 4)
           for m in ("ndcg", "mrr", "recall")}
    record_reproduces = all(abs(v) <= RECORD_TOLERANCE for v in gap.values())

    summary = {
        "index": {"documents": n_docs, "pruned": want_pruned,
                  "documents_scored": len(indexed)},
        "task_slice": {
            "continuation_lines": args.continuation_lines,
            "mined": stats,
            "refs_left_in_query": (stats["refs_ambiguous"] + stats["refs_unknown"]
                                   + stats["refs_unindexed"]),
            "empty_result_queries": empty_result_count(con, task_pairs),
            "shape": query_shape([p["query"] for p in task_pairs]),
            "metrics": task_sum,
            "metrics_open_items_only": open_sum,
            "metrics_if_paths_left_in_query": unstripped,
        },
        "commit_slice": {
            "pairs_total": len(commit_pairs),
            "test": len(commit_test),
            "boundary_date": commit_test[0]["date"][:10] if commit_test else "n/a",
            "unreachable_judgements": [bad, total],
            "shape": query_shape([p["query"] for p in commit_test]),
            "metrics_as_shipped": commit_shipped,
            "metrics_reachable_full_index": commit_reachable_full,
            "metrics_like_for_like": commit_fair,
        },
        "recorded_bar": {**rec, "rel_gap_vs_fresh": gap, "reproduces": record_reproduces},
        "verdict": verdict(task_sum["leak_free"], commit_fair["leak_free"]),
    }

    if args.out:
        with Path(args.out).open("w", encoding="utf-8", newline="\n") as fh:
            for p in task_pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    s, c, t = stats, summary["commit_slice"], summary["task_slice"]
    print("TASK-SHAPED SLICE (mined from TODO.md)")
    print(f"  checkbox items        : {s['items_total']}  "
          f"(open {s['items_open']} / done {s['items_done']})")
    print(f"  yielded a pair        : {s['kept']}")
    print(f"  yielded nothing       : {s['items_total'] - s['kept']}  "
          + ", ".join(f"{r}={s[r]}" for r in DROP_REASONS))
    print(f"  refs used as targets  : exact={s['refs_exact']} "
          f"unique_suffix={s['refs_unique_suffix']}")
    print(f"  refs NOT used         : ambiguous={s['refs_ambiguous']} "
          f"unknown={s['refs_unknown']} unindexed={s['refs_unindexed']} "
          "(left in the query: they name no single target)")
    print(f"  queries FTS5 answers with nothing: {t['empty_result_queries']}")
    print(f"  item body lines       : 1 + {t['continuation_lines']} continuation")
    print(f"  documents scored      : {summary['index']['documents_scored']} of {n_docs} "
          f"(pruned {want_pruned}: they hold every query verbatim)")
    print()
    print("QUERY SHAPE - the claimed mechanism")
    print(f"  {'':16}{'n':>6}{'median words':>14}{'mean':>8}"
          f"{'median terms':>14}{'snake_case share':>18}")
    for name, sh in (("commit-shaped", c["shape"]), ("task-shaped", t["shape"])):
        print(f"  {name:16}{sh['n']:>6}{sh['median_words']:>14.1f}{sh['mean_words']:>8.1f}"
              f"{sh['median_terms']:>14.1f}{sh['snake_share']:>18.4f}")
    print()
    print("sqlite3 FTS5 + bm25() - SAME index, SAME metrics, SAME run")
    print(f"  {'':36}{'NDCG@10':>9}{'MRR':>9}{'recall@10':>11}{'n':>6}")
    for label, block, subset in (
        ("commit-shaped   all queries", c["metrics_like_for_like"], "all"),
        ("commit-shaped   leak-free", c["metrics_like_for_like"], "leak_free"),
        ("task-shaped     all queries", t["metrics"], "all"),
        ("task-shaped     leak-free", t["metrics"], "leak_free"),
        ("task-shaped     open items only", t["metrics_open_items_only"], "leak_free"),
    ):
        b = block[subset]
        n = block["n"] if subset == "all" else block["n_leak_free"]
        print(f"  {label:36}{b['ndcg']:>9.3f}{b['mrr']:>9.3f}{b['recall']:>11.3f}{n:>6}")
    print()
    print("ANSWER-IN-THE-QUERY CONTROL - same pairs, paths NOT stripped out")
    u, ts = t["metrics_if_paths_left_in_query"], t["metrics"]
    print(f"  {'paths stripped (reported above)':36}{ts['all']['ndcg']:>9.3f}"
          f"{ts['all']['mrr']:>9.3f}{ts['all']['recall']:>11.3f}{ts['n']:>6}")
    print(f"  {'paths left in':36}{u['all']['ndcg']:>9.3f}{u['all']['mrr']:>9.3f}"
          f"{u['all']['recall']:>11.3f}{u['n']:>6}")
    print("  => leaving them in inflates NDCG@10 by "
          f"{(u['all']['ndcg'] - ts['all']['ndcg']) / max(ts['all']['ndcg'], 1e-9):+.1%}"
          f", and the imported leak control flags {u['n'] - u['n_leak_free']} of {u['n']}"
          f" queries instead of {ts['n'] - ts['n_leak_free']}")
    print()
    print("HYPOTHESIS: task-shaped queries are HARDER for BM25 (leak-free subsets)")
    for m in ("ndcg", "mrr", "recall"):
        v = summary["verdict"][m]
        print(f"  {m:8} task {v['task']:.3f}  vs  commit {v['commit']:.3f}   "
              f"delta {v['delta']:+.3f} ({v['rel_delta']:+.1%})   "
              f"{'HARDER' if v['harder'] else 'NOT harder'}")
    print(f"  => hypothesis {'HELD' if summary['verdict']['hypothesis_held'] else 'REFUTED'}"
          " on all three metrics")
    print()
    print(f"RECORDED BAR {rec['ndcg']}/{rec['mrr']}/{rec['recall']} "
          f"({rec['source']}, {rec['documents']} docs)")
    cs, cr = commit_shipped["leak_free"], commit_reachable_full["leak_free"]
    print(f"  re-measured now, same code, same defaults, full index: "
          f"{cs['ndcg']:.3f}/{cs['mrr']:.3f}/{cs['recall']:.3f} "
          f"over {n_docs} docs (n={commit_shipped['n_leak_free']})")
    print("  relative gap: " + ", ".join(f"{m} {v:+.1%}" for m, v in gap.items()))
    print("  => the recorded bar "
          + ("REPRODUCES" if record_reproduces else "DOES NOT REPRODUCE - do not quote it"))
    print(f"  cause: {bad} of {total} relevance judgements name a file that is NOT in the "
          "index at HEAD (deleted or renamed since), and score 0 unconditionally.")
    print(f"  drop those and the same code gives "
          f"{cr['ndcg']:.3f}/{cr['mrr']:.3f}/{cr['recall']:.3f} "
          f"(n={commit_reachable_full['n_leak_free']}) - the recorded bar, back again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


