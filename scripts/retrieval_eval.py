#!/usr/bin/env python3
"""Golden retrieval set from git history + the lexical baseline it must beat.

Steps 1 and 2 of the embedding sequence (tasks/artifacts/embedding_strategy_review_
2026-07-26.md). Neither needs a GPU or a decision. Both must exist before any
embedding model can be said to have helped, because right now nothing in this tree
measures retrieval at all.

THE SET. Each commit is a (query -> relevant documents) pair: the message is the
query, the changed files are the relevant documents. Free, domain-specific by
construction, and — critically — **temporally splittable**. Given that the shipped
vector-hoops embedding turned out to be trained transductively ("NOT held-out"),
the split here is walk-forward by commit date and a random split is not offered as
an option.

STATED LIMIT, not discovered later: a commit's changed files are *sufficient*
relevance, not *complete* relevance. Other files may be equally relevant and simply
were not touched. So absolute recall is under-measured. The set remains valid for
COMPARING two retrievers on identical queries, which is the only question being
asked of it.

THE LEAK CONTROL. Commit messages frequently name the file they touch
("fix(gate): ... gate_audit" -> scripts/gate_audit.py). A lexical retriever gets
that for free, and reporting only the headline number would overstate BM25 and
therefore understate whatever must beat it. Every metric is reported twice: over
all queries, and over the LEAK-FREE subset where no target filename stem appears in
the query.

BASELINE. sqlite3 FTS5 with bm25() ranking — stdlib, and the same technology
scout-cli already ships in bigbang/core/search.py and searchindex.py.

Usage:
    python scripts/retrieval_eval.py                     # mine, index, score
    python scripts/retrieval_eval.py --max-commits 2000
    python scripts/retrieval_eval.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MIN_QUERY_WORDS = 5
MAX_FILES_PER_COMMIT = 8
K = 10
INDEXABLE = {".py", ".md", ".mjs", ".js", ".ts", ".yml", ".yaml", ".sh", ".json", ".html"}
SKIP_PARTS = {".git", "__pycache__", ".venv", "node_modules", ".ruff_cache",
              ".pytest_cache", "site-packages", "dist", "build"}
MAX_DOC_CHARS = 60_000


def mine_pairs(max_commits: int):
    """(query, [files], iso_date) per usable commit, newest first."""
    out = subprocess.run(
        ["git", "log", f"-n{max_commits}", "--pretty=format:@@@%cI%x09%s", "--name-only"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    pairs, date, msg, files = [], None, None, []

    def flush():
        if msg is None:
            return
        if len(msg.split()) < MIN_QUERY_WORDS:
            return
        keep = [f for f in files if Path(f).suffix in INDEXABLE]
        if not (1 <= len(keep) <= MAX_FILES_PER_COMMIT):
            return
        pairs.append({"query": msg, "relevant": keep, "date": date})

    for line in out.splitlines():
        if line.startswith("@@@"):
            flush()
            rest = line[3:]
            date, _, msg = rest.partition("\t")
            files = []
        elif line.strip():
            files.append(line.strip())
    flush()
    return pairs


def untracked_docs(paths) -> int:
    """How many of `paths` git does not track — i.e. generated, not repo source.

    Reported, never filtered. Excluding them would change every score this script
    produces, which is a decision about what the benchmark MEASURES and not one to make
    inside a counting helper. But a corpus size printed without this number is the silent
    version of the problem, so the figure travels with the total.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return -1
    except (OSError, subprocess.SubprocessError):
        return -1
    tracked = {p for p in out.stdout.split("\0") if p}
    return sum(1 for rel in paths if rel not in tracked)


def build_index(con: sqlite3.Connection):
    """FTS5 over the tree at HEAD. Returns the number of documents indexed.

    THE UNTRACKED COUNT MATTERS AND WAS INVISIBLE. This walk skips .venv and friends but
    has no gitignore awareness, so it indexes generated output as corpus. Measured
    2026-08-02: 589 of 2,288 documents (25.7%) came from
    apps/dottie/data/research/workspaces/ — model-written candidate_*.py produced by the
    "Dottie Research runner" scheduled task, which fires every 15 minutes with `--n 3`.

    They are DISTRACTORS, so they push scores down rather than flattering them, and the
    corpus grows ~295 documents a day on a running machine. The doc counts recorded across
    runs show it: 2,024 -> 2,128 -> 2,288. That is a second drift mechanism on top of the
    stale-relevance-judgement one already documented in a561f5d, and it means any absolute
    number from this script is corpus-and-day specific. Comparisons made on the same day
    against the same corpus remain valid — the step-5 dense-vs-lexical verdict is not
    affected.
    """
    con.execute("CREATE VIRTUAL TABLE docs USING fts5(path, body, tokenize='porter unicode61')")
    n = 0
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in INDEXABLE:
            continue
        if SKIP_PARTS & set(p.parts):
            continue
        rel = p.relative_to(ROOT).as_posix()
        try:
            body = p.read_text(encoding="utf-8", errors="replace")[:MAX_DOC_CHARS]
        except OSError:
            continue
        # The path is indexed as a field of its own so a query naming a file can
        # match it — that is realistic, and the leak control below measures it.
        con.execute("INSERT INTO docs(path, body) VALUES (?, ?)", (rel, body))
        n += 1
    con.commit()
    return n



def index_untracked(con: sqlite3.Connection) -> int:
    """Untracked share of an already-built index. -1 if git cannot answer.

    Deliberately SEPARATE from build_index rather than folded into its return value.
    Making build_index return a tuple broke three callers that were not in this file —
    scripts/task_eval_slice.py:399 and two of its tests — and CI caught it with
    `TypeError: unsupported operand type(s) for -: 'tuple' and 'int'`. A widely-called
    function's return type is a contract; adding a fact about the index does not justify
    changing it.
    """
    rels = [r[0] for r in con.execute("SELECT path FROM docs")]
    return untracked_docs(rels)


_TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def fts_query(con, query: str, k: int):
    """FTS5 MATCH with bm25 ranking. Terms OR'd; FTS5 syntax neutralised."""
    terms = _TOK.findall(query)
    if not terms:
        return []
    expr = " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))
    try:
        rows = con.execute(
            "SELECT path FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (expr, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def ndcg_at_k(ranked, relevant, k=K):
    rel = set(relevant)
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranked[:k]) if p in rel)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / ideal if ideal else 0.0


def rr(ranked, relevant):
    rel = set(relevant)
    for i, p in enumerate(ranked):
        if p in rel:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked, relevant, k=K):
    rel = set(relevant)
    return len(rel & set(ranked[:k])) / len(rel) if rel else 0.0


def leaks_filename(query: str, relevant) -> bool:
    """Does the query contain a target filename stem? Then lexical gets it free."""
    q = {t.lower() for t in _TOK.findall(query)}
    for f in relevant:
        stem = Path(f).stem.lower()
        if stem in q:
            return True
        # snake_case stems also leak via their parts ("gate_audit" -> "gate","audit")
        parts = [s for s in stem.split("_") if len(s) > 2]
        if parts and all(s in q for s in parts):
            return True
    return False


def score(con, pairs, k=K):
    rows = []
    for p in pairs:
        ranked = fts_query(con, p["query"], k)
        rows.append(
            {
                "ndcg": ndcg_at_k(ranked, p["relevant"], k),
                "mrr": rr(ranked, p["relevant"]),
                "recall": recall_at_k(ranked, p["relevant"], k),
                "leak": leaks_filename(p["query"], p["relevant"]),
                "hit": bool(set(ranked[:k]) & set(p["relevant"])),
            }
        )
    return rows


def unreachable_targets(pairs, indexed):
    """(unreachable, total) relevance judgements naming a file absent from the index.

    A judgement pointing at a file that no longer exists at HEAD — deleted or renamed
    since its commit was mined — can NEVER be satisfied: the retriever cannot return a
    document that is not there, so the pair scores 0 unconditionally and drags the mean
    down. That is churn in the repo's history being measured, not retrieval quality.

    This is not hypothetical. The bar recorded as NDCG@10 0.622 re-measured at 0.420 on
    2026-08-01; 71 of 451 judgements had gone unreachable, and excluding them returned
    0.656 from the same code. The number rotted silently for weeks because THIS module —
    the one whose output gets quoted as "the bar" — never surfaced the count. It does
    now (see main()).

    Lived in task_eval_slice.py until 2026-08-01 and was moved here, the upstream
    module, so the caveat sits with the number it qualifies; task_eval_slice imports it
    rather than keeping a second copy.
    """
    total = sum(len(p["relevant"]) for p in pairs)
    bad = sum(1 for p in pairs for f in p["relevant"] if f not in indexed)
    return bad, total


def summarise(rows):
    def avg(key, subset):
        vals = [r[key] for r in subset]
        return sum(vals) / len(vals) if vals else 0.0

    leak_free = [r for r in rows if not r["leak"]]
    return {
        "n": len(rows),
        "n_leak_free": len(leak_free),
        "all": {m: round(avg(m, rows), 4) for m in ("ndcg", "mrr", "recall")},
        "leak_free": {m: round(avg(m, leak_free), 4) for m in ("ndcg", "mrr", "recall")},
        "hit_rate_all": round(sum(r["hit"] for r in rows) / max(len(rows), 1), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-commits", type=int, default=4000)
    ap.add_argument("--split-frac", type=float, default=0.7,
                    help="fraction of commits (oldest first) that form the TRAIN half")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write the golden set as JSONL")
    args = ap.parse_args()

    pairs = mine_pairs(args.max_commits)
    pairs.sort(key=lambda p: p["date"])  # oldest first for a walk-forward boundary
    cut = int(len(pairs) * args.split_frac)
    train, test = pairs[:cut], pairs[cut:]
    boundary = test[0]["date"][:10] if test else "n/a"

    con = sqlite3.connect(":memory:")
    n_docs = build_index(con)
    n_untracked = index_untracked(con)
    # The index IS the ground truth for reachability — read the paths back from it
    # rather than re-walking the tree, so the check cannot disagree with what was
    # actually indexed.
    indexed_paths = {r[0] for r in con.execute("SELECT path FROM docs")}

    test_rows = score(con, test)
    summary = {
        "golden_set": {
            "pairs_total": len(pairs),
            "train": len(train),
            "test": len(test),
            "split": "walk-forward by commit date (NEVER random)",
            "boundary_date": boundary,
        },
        "index": {"documents": n_docs, "untracked_documents": n_untracked,
                  "engine": "sqlite3 FTS5 + bm25()"},
        "baseline_on_test": summarise(test_rows),
    }

    if args.out:
        with Path(args.out).open("w", encoding="utf-8", newline="\n") as fh:
            for p in pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    g, b = summary["golden_set"], summary["baseline_on_test"]
    print("GOLDEN SET (from git history)")
    print(f"  pairs           : {g['pairs_total']}  (train {g['train']} / test {g['test']})")
    print(f"  split           : {g['split']}")
    print(f"  boundary        : {g['boundary_date']}")
    pct = (n_untracked / n_docs * 100) if n_docs and n_untracked >= 0 else 0.0
    note = ("  (git unavailable — untracked share unknown)" if n_untracked < 0
            else f"  ({n_untracked} untracked/generated, {pct:.1f}%)")
    print(f"  indexed docs    : {n_docs}{note}")
    print()
    print(f"LEXICAL BASELINE — sqlite3 FTS5 + bm25(), scored on the {g['test']} TEST queries")
    print(f"  {'':22}{'NDCG@10':>9}{'MRR':>9}{'recall@10':>11}")
    print(f"  {'all queries':22}{b['all']['ndcg']:>9.3f}{b['all']['mrr']:>9.3f}"
          f"{b['all']['recall']:>11.3f}   (n={b['n']})")
    print(f"  {'leak-free subset':22}{b['leak_free']['ndcg']:>9.3f}{b['leak_free']['mrr']:>9.3f}"
          f"{b['leak_free']['recall']:>11.3f}   (n={b['n_leak_free']})")
    print()
    print("  leak-free = the query does NOT contain a target filename stem, so the")
    print("  retriever cannot match the path directly. That subset is the honest bar.")

    # Reachability, printed UNCONDITIONALLY next to the score it qualifies. A judgement
    # naming a file that no longer exists cannot be satisfied by any retriever, so it
    # scores 0 and pulls the mean down — that is repo churn being measured, not
    # retrieval. The recorded 0.622 silently became 0.420 this way; without this line
    # nothing here said so.
    bad, total_j = unreachable_targets(test, indexed_paths)
    print()
    print(f"  RELEVANCE REACHABILITY: {bad} of {total_j} judgements name a file that is")
    print("  NOT in the index at HEAD (deleted or renamed since the commit was mined).")
    if bad:
        pct = 100.0 * bad / max(total_j, 1)
        reachable = [
            {**p, "relevant": [f for f in p["relevant"] if f in indexed_paths]}
            for p in test
        ]
        reachable = [p for p in reachable if p["relevant"]]
        rb = summarise(score(con, reachable))
        print(f"  Those {pct:.1f}% score 0 unconditionally. Excluding them, the SAME code gives:")
        print(f"  {'reachable only':22}{rb['leak_free']['ndcg']:>9.3f}"
              f"{rb['leak_free']['mrr']:>9.3f}{rb['leak_free']['recall']:>11.3f}"
              f"   (n={rb['n_leak_free']})")
        print("  Quote whichever you like, but quote it WITH this line and a date — the")
        print("  golden set is mined from git history, so both numbers move as commits land.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
