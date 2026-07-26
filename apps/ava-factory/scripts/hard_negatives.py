#!/usr/bin/env python3
"""Hard-negative mining for code-retrieval contrastive training.

Solo personal project, no connection to employer, built with public/free-tier only

WHY THIS EXISTS. In-batch negatives teach "this function vs a totally unrelated
function". That is easy, the loss collapses early, and the resulting encoder is
useless at the job it will actually be asked to do: pick the right function out of
the twenty functions sitting next to it in the same file. Hard negatives are the
difference. This module mines them from two sources that are already paid for.

  SOURCE A — SIBLING NEGATIVES. For a (docstring -> function) pair, the other
  functions in the SAME CLASS, then the same FILE, then the same PACKAGE. Same
  vocabulary, same imports, same domain, different behaviour: exactly the
  confusion a retriever has to resolve. Pairs come from ``ast_pairs.py``, which is
  imported and reused — the AST extraction, the docstring quality gate and the
  context packing are NOT reimplemented here.

  SOURCE B — ADJACENT-COMMIT NEGATIVES. For a (commit message -> changed files)
  golden pair, the files touched by commits temporally NEAR that commit but not by
  it. Same feature branch, same week, same subsystem, wrong file. Golden pairs come
  from ``scripts/retrieval_eval.py``'s miner, reused rather than re-shelling git.

THE ONE RULE THAT MATTERS. A "negative" that is in fact a positive for the same
query trains the model against the truth: gradient descent is told to push apart a
query and a document that genuinely answer each other. Two ways that happens here
and both are filtered:

  1. Two functions can carry the SAME docstring (copy-paste, overload pairs,
     ``__init__`` boilerplate). The sibling is then a real positive for the query.
  2. Two functions in one package can have IDENTICAL packed text. Pushing a string
     away from itself is not a learning signal, it is noise.

Both are handled by one index: for each normalised query, the set of every positive
text that answers it. A candidate whose text is in that set is dropped. The same
shape applies to source B, keyed on the commit message with the union of every
relevant file across commits that share it. See ``mine_sibling_negatives`` and
``mine_adjacent_negatives``, and ``TestNeverAPositive`` in the test module.

ORDERING, and what is deliberately NOT claimed. Negatives are returned CLOSEST
SCOPE FIRST (same_class < same_file < same_package for A; |commit distance| for B),
and ties inside a scope are broken lexicographically by (path, symbol). That
tiebreak is a deterministic total order, NOT a similarity ranking. A real "hardest
first" ordering needs an encoder to score candidates; approximating it with token
overlap would be a quality claim this module cannot support, so it is not made.

Ordering is independent of the order the input pairs arrive in, so a re-walk of the
tree in a different filesystem order produces byte-identical output. That claim was
FALSE when adversarial review first checked it: each negative LIST was
order-independent, but the records themselves were appended as the pairs arrived, so
the --out JSONL was a different file for a different walk order. Records are now
emitted in ``_record_key`` order — content only, never an index — and
``TestDeterminism`` compares two walks byte-for-byte rather than re-sorting both
sides first, which is a comparison that cannot see the bug it is supposed to catch.

STDLIB ONLY — no datasketch, no numpy, no faiss. Same doctrine as the rest of the
tree.

Usage:
    python scripts/hard_negatives.py                                # whole repo
    python scripts/hard_negatives.py --path apps/scout-cli --no-git
    python scripts/hard_negatives.py --out negatives.jsonl --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]


def _load(alias: str, path: Path):
    """Load a sibling *script* as a module. Both reused files are scripts, not
    packages, so there is nothing importable by name; this mirrors how
    tests/test_ast_pairs.py loads ast_pairs.py. The aliases are prefixed so this
    module can never shadow a real ``ast_pairs`` / ``retrieval_eval`` entry that a
    test module put in sys.modules first."""
    if not path.exists():
        raise SystemExit(f"hard_negatives: required module not found: {path}")
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


ast_pairs = _load("_hn_ast_pairs", _HERE / "ast_pairs.py")
retrieval_eval = _load("_hn_retrieval_eval", _REPO_ROOT / "scripts" / "retrieval_eval.py")

DEFAULT_N = 8
DEFAULT_WINDOW = 5

# Scope ranks. Lower == closer == harder. The numeric value IS the sort key.
SCOPE_SAME_CLASS = 0
SCOPE_SAME_FILE = 1
SCOPE_SAME_PACKAGE = 2
SCOPE_NAMES = {
    SCOPE_SAME_CLASS: "same_class",
    SCOPE_SAME_FILE: "same_file",
    SCOPE_SAME_PACKAGE: "same_package",
}


def _norm_query(text: str) -> str:
    """Whitespace- and case-insensitive key. Two docstrings that differ only in
    wrapping are the same query, and a sibling carrying one is a positive."""
    return " ".join((text or "").split()).casefold()


def _norm_path(path: str) -> str:
    return (path or "").replace("\\", "/")


def package_of(path: str) -> str:
    """Directory holding the file. Root-level files share the '' package."""
    p = _norm_path(path)
    return p.rsplit("/", 1)[0] if "/" in p else ""


def class_of(pair: dict) -> str | None:
    """Enclosing class of an ast_pairs pair, or None for a module-level function.

    ast_pairs.extract_file builds ``symbol`` as ``f"{class_name}.{func}"`` inside a
    class and plain ``f"{func}"`` otherwise. That format is READ here rather than a
    second copy of the class name being stored alongside it — a duplicated constant
    has bitten this repo twice. ``TestSymbolFormatContract`` pins the two together
    so a change to ast_pairs' symbol format fails loudly instead of silently
    turning every same_class negative into a same_file one.

    LIMIT OF THE FORMAT, stated because it has a consequence below. ast_pairs stores
    only the INNERMOST class, so ``Outer.Inner.run`` and ``Other.Inner.run`` in one
    file both arrive as symbol ``Inner.run`` and both answer "Inner" here. Adversarial
    review reproduced the consequence on a 12-line file: the two pairs are then
    indistinguishable in the emitted record, and each was returned as its OWN
    (path, symbol) negative — the one output this module must never produce. The
    outer class is simply not recoverable from ``symbol``, so it is not guessed;
    ``_ident`` treats colliding pairs as one document and ``mine_sibling_negatives``
    drops them instead of emitting a negative that names the record itself. Zero
    occurrences in this tree today (measured 2026-07-26), so the drop costs nothing
    here, but ordinary Python triggers it.

    What is NOT claimed: two DIFFERENT methods of two same-named nested classes
    (``Outer.Inner.run`` vs ``Other.Inner.save``) still score as same_class rather
    than same_file. That mis-RANKS a candidate that is nonetheless a genuine
    negative, and the information needed to tell them apart does not exist in the
    input, so no correctness claim is made about it.
    """
    symbol = pair.get("symbol") or ""
    return symbol.split(".", 1)[0] if "." in symbol else None


def _ident(pair: dict) -> tuple[str, str]:
    """(path, symbol) — how a document is named in the output, and therefore the
    only identity a consumer of the JSONL can resolve. Two pairs sharing it cannot
    be told apart downstream (see ``class_of``), so the miner treats them as one
    document rather than as each other's negatives."""
    return (_norm_path(pair.get("path", "")), pair.get("symbol", "") or "")


def _record_key(record: dict) -> tuple[str, str, str, str]:
    """Total, content-only order over emitted records. Content-only is the whole
    point: it is what makes the --out JSONL byte-identical across filesystem walk
    orders rather than merely internally consistent."""
    return (
        record["path"],
        record["symbol"],
        record["query"],
        record["positive"],
    )


# ---------------------------------------------------------------------------
# Source A — sibling negatives
# ---------------------------------------------------------------------------
def _candidate(pair, forbidden, scope):
    """Sort tuple for a candidate sibling, or None if it is really a positive.

    THE correctness gate for source A. ``forbidden`` holds every positive text that
    answers the query being mined for, which includes the query's own positive — so
    a self-match and a copy-pasted-docstring sibling are both rejected here.

    Self-exclusion is therefore guaranteed TWICE: by this text gate, and by the
    ``_ident`` skip in the caller. That redundancy is deliberate, not leftover —
    mutating either one alone leaves the other holding, and a pair returned as its
    own negative is the single worst output this module could produce. The two are
    not interchangeable, and each has a case only IT catches, so each is pinned by
    a test of its own:
      * only this gate catches a twin in another file with the same docstring, or
        one with byte-identical packed text (different identity, same content);
      * only the ``_ident`` skip catches a symbol collision (different content,
        same identity) — see ``class_of``.

    Every element of the returned key is CONTENT, never the candidate's index in
    the input list. That is what makes the output independent of the order the
    pairs were walked in; an index tiebreak would have made a re-walk in a
    different filesystem order produce a different (but equally "deterministic")
    file, which is the kind of drift nobody notices.
    """
    text = pair.get("positive", "")
    if text in forbidden:
        return None
    return (scope, _norm_path(pair.get("path", "")), pair.get("symbol", "") or "", text)


def mine_sibling_negatives(pairs, n: int = DEFAULT_N):
    """Negatives drawn from the code around each pair, CLOSEST SCOPE FIRST.

    Ordering, in full:
        1. same_class    — another method of the enclosing class
        2. same_file     — another function in the same module
        3. same_package  — a function in a sibling module of the same directory
        ties inside a scope: lexicographic by (path, symbol)

    A candidate is dropped if its packed text is a genuine positive for this
    query (see the module docstring), or if it shares this pair's (path, symbol)
    identity (see ``class_of``). One record is emitted per input pair, INCLUDING
    pairs for which no sibling survives — those carry ``"negatives": []`` rather
    than being silently dropped, so the caller can see coverage instead of
    inferring it from a shrunken count.

    Records come out in ``_record_key`` order, NOT input order. That is what makes
    the emitted file, and not merely each negative list, independent of the order
    the tree was walked in.

    Returns a list of dicts:
        {query, positive, path, symbol, source: "sibling", negatives: [
            {text, path, symbol, scope}, ...]}
    """
    pairs = list(pairs)
    n = max(int(n), 0)

    # query -> every positive text that genuinely answers it. THE correctness index.
    positives_by_query: dict[str, set] = {}
    for p in pairs:
        positives_by_query.setdefault(_norm_query(p.get("query", "")), set()).add(
            p.get("positive", "")
        )

    by_file: dict[str, list] = {}
    by_package: dict[str, list] = {}
    for i, p in enumerate(pairs):
        path = _norm_path(p.get("path", ""))
        by_file.setdefault(path, []).append(i)
        by_package.setdefault(package_of(path), []).append(i)

    out = []
    for i, p in enumerate(pairs):
        path = _norm_path(p.get("path", ""))
        cls = class_of(p)
        self_id = _ident(p)
        forbidden = positives_by_query.get(_norm_query(p.get("query", "")), set())

        cands = []
        for j in by_file.get(path, ()):
            # Identity, not index. `j == i` is the common case and is covered, but a
            # symbol collision (class_of's stated limit) makes a DIFFERENT pair
            # indistinguishable from this one in the output, and an index test lets
            # that one through: reproduced as `Inner.run -> [(Inner.run, same_class)]`.
            if _ident(pairs[j]) == self_id:
                continue
            c = _candidate(pairs[j], forbidden, scope=(
                SCOPE_SAME_CLASS
                if cls is not None and class_of(pairs[j]) == cls
                else SCOPE_SAME_FILE
            ))
            if c is not None:
                cands.append(c)

        # Every package candidate ranks strictly below every file candidate, so the
        # package scan is skipped once the file already fills the quota. Exact, not
        # an approximation — and it keeps the whole-repo run linear in practice.
        if len(cands) < n:
            for j in by_package.get(package_of(path), ()):
                # Same-path candidates belong to the file scan above, which already
                # owns the identity skip; that includes j == i, so a separate index
                # test here could never be the deciding condition.
                if _norm_path(pairs[j].get("path", "")) == path:
                    continue
                c = _candidate(pairs[j], forbidden, scope=SCOPE_SAME_PACKAGE)
                if c is not None:
                    cands.append(c)

        cands.sort()
        out.append(
            {
                "query": p.get("query", ""),
                "positive": p.get("positive", ""),
                "path": path,
                "symbol": p.get("symbol", ""),
                "source": "sibling",
                "negatives": [
                    {
                        "text": text,
                        "path": cpath,
                        "symbol": csym,
                        "scope": SCOPE_NAMES[scope],
                    }
                    for scope, cpath, csym, text in cands[:n]
                ],
            }
        )
    # The negative LISTS were already order-independent; the file was not, because
    # records were appended as the pairs arrived. Sorting closes that gap, which is
    # what lets TestDeterminism compare two walks byte-for-byte instead of comparing
    # them only after re-sorting both sides (a comparison that cannot see this bug).
    out.sort(key=_record_key)
    return out


# ---------------------------------------------------------------------------
# Source B — adjacent-commit negatives
# ---------------------------------------------------------------------------
def mine_adjacent_negatives(golden_pairs, window: int = DEFAULT_WINDOW, n: int = DEFAULT_N):
    """Negatives from commits temporally adjacent to each golden pair's commit.

    ``golden_pairs`` are retrieval_eval.mine_pairs() records: {query, relevant,
    date}. They are sorted by (date, query, relevant) here — mine_pairs returns
    newest first and "adjacent" is meaningless until they are in temporal order.
    The compound key keeps two commits sharing a timestamp in a fixed order.

    Ordering: |commit distance| ascending; on a tie the EARLIER commit comes first
    (offsets -1, +1, -2, +2, ...). Within one neighbour, git's own file order.
    ``window`` is a count of neighbouring commits on EACH side.

    A file relevant to this query — including via another commit that carries the
    identical message — is never emitted as its own negative.

    Returns: {query, relevant, date, source: "adjacent", negatives: [
        {path, distance, direction, from_date, from_query}, ...]}
    """
    items = sorted(
        golden_pairs,
        # Content-only key, for the same reason _candidate uses one: two commits in
        # the same second with the same message must not depend on git's ordering.
        key=lambda g: (
            g.get("date") or "",
            g.get("query") or "",
            tuple(_norm_path(f) for f in g.get("relevant", ())),
        ),
    )
    window = max(int(window), 0)
    n = max(int(n), 0)

    relevant_by_query: dict[str, set] = {}
    for g in items:
        relevant_by_query.setdefault(_norm_query(g.get("query", "")), set()).update(
            _norm_path(f) for f in g.get("relevant", ())
        )

    offsets = []
    for d in range(1, window + 1):
        offsets.extend((-d, d))

    out = []
    for i, g in enumerate(items):
        forbidden = relevant_by_query.get(_norm_query(g.get("query", "")), set())
        seen, negatives = set(), []
        for off in offsets:
            if len(negatives) >= n:
                break
            j = i + off
            if j < 0 or j >= len(items) or j == i:
                continue
            neighbour = items[j]
            for f in neighbour.get("relevant", ()):
                path = _norm_path(f)
                if path in forbidden or path in seen:
                    continue
                # `forbidden` only covers files marked relevant to a BYTE-IDENTICAL
                # commit message, which is far too narrow. A file the query itself
                # NAMES is relevant to it whether or not this commit touched it, and
                # emitting it as a negative trains the model against the truth — the
                # one rule this module's docstring says matters most.
                #
                # Measured before the fix: 62 of 4,461 adjacent negatives (1.4%) were
                # files whose stem the query names, e.g.
                #   "docs(arxiviq): CodeAct roadmap planned -> spec'd (specs/13_codeact.md)"
                #   -> negative specs/13_codeact.md
                #
                # retrieval_eval.leaks_filename is exactly this predicate — the same
                # helper retrieval_eval uses to build its own leak-free subset. It was
                # already loaded in this process and never called. Reused, not
                # re-implemented: a second copy of this rule is the duplicated-source
                # bug class this repo has hit twice.
                if retrieval_eval.leaks_filename(g.get("query", ""), [path]):
                    continue
                seen.add(path)
                negatives.append(
                    {
                        "path": path,
                        "distance": abs(off),
                        "direction": "before" if off < 0 else "after",
                        "from_date": neighbour.get("date"),
                        "from_query": neighbour.get("query"),
                    }
                )
                if len(negatives) >= n:
                    break
        out.append(
            {
                "query": g.get("query", ""),
                "relevant": [_norm_path(f) for f in g.get("relevant", ())],
                "date": g.get("date"),
                "source": "adjacent",
                "negatives": negatives,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _base_stats(records):
    queries = len(records)
    total = sum(len(r["negatives"]) for r in records)
    covered = sum(1 for r in records if r["negatives"])
    return {
        "queries": queries,
        "negatives": total,
        # Averaged over ALL queries, including the ones that yielded nothing. The
        # other denominator flatters the miner and hides coverage collapse.
        "avg_per_query": round(total / queries, 3) if queries else 0.0,
        "queries_with_negatives": covered,
        "coverage": round(covered / queries, 4) if queries else 0.0,
    }


def summarise(sibling_records, adjacent_records):
    """Per-source counts and the average per query. Pure, so it is testable."""
    sib = _base_stats(sibling_records)
    sib["by_scope"] = {
        name: sum(
            1 for r in sibling_records for neg in r["negatives"] if neg["scope"] == name
        )
        for name in SCOPE_NAMES.values()
    }
    adj = _base_stats(adjacent_records)
    by_distance: dict[str, int] = {}
    for r in adjacent_records:
        for neg in r["negatives"]:
            key = str(neg["distance"])
            by_distance[key] = by_distance.get(key, 0) + 1
    adj["by_distance"] = dict(sorted(by_distance.items(), key=lambda kv: int(kv[0])))

    queries = sib["queries"] + adj["queries"]
    negatives = sib["negatives"] + adj["negatives"]
    return {
        "sibling": sib,
        "adjacent": adj,
        "total": {
            "queries": queries,
            "negatives": negatives,
            "avg_per_query": round(negatives / queries, 3) if queries else 0.0,
        },
    }


def pairs_from_tree(base: Path):
    """Every ast_pairs pair under ``base``, paths relative and posix-normalised."""
    base = Path(base).resolve()
    pairs = []
    for p in ast_pairs.walk(base):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _norm_path(str(p.relative_to(base)))
        got, _ = ast_pairs.extract_file(src, rel)
        pairs += got
    return pairs


def _print_report(summary):
    s, a, t = summary["sibling"], summary["adjacent"], summary["total"]
    print("HARD NEGATIVES")
    print()
    print("  SOURCE A - siblings (same class -> same file -> same package)")
    print(f"    queries               : {s['queries']}")
    print(f"    negatives mined       : {s['negatives']}")
    print(f"    avg per query         : {s['avg_per_query']:.3f}")
    print(f"    queries with >=1      : {s['queries_with_negatives']} ({s['coverage']:.1%})")
    for name, count in s["by_scope"].items():
        print(f"        {name:<14}    {count}")
    print()
    print("  SOURCE B - adjacent commits (temporal neighbours, own files removed)")
    print(f"    queries               : {a['queries']}")
    print(f"    negatives mined       : {a['negatives']}")
    print(f"    avg per query         : {a['avg_per_query']:.3f}")
    print(f"    queries with >=1      : {a['queries_with_negatives']} ({a['coverage']:.1%})")
    for dist, count in a["by_distance"].items():
        print(f"        distance {dist:<6}    {count}")
    print()
    print(f"  TOTAL                   : {t['negatives']} negatives over {t['queries']} "
          f"queries  (avg {t['avg_per_query']:.3f})")
    print()
    print("  avg is over ALL queries, including those that yielded none - the other")
    print("  denominator hides coverage collapse behind a healthy-looking average.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(_REPO_ROOT), help="tree to mine for source A")
    ap.add_argument("--max-commits", type=int, default=1500, help="history depth for source B")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="max negatives per query")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help="neighbouring commits per side for source B")
    ap.add_argument("--no-git", action="store_true", help="skip source B entirely")
    ap.add_argument("--out", help="JSONL of every record from both sources")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    sibling = mine_sibling_negatives(pairs_from_tree(Path(args.path)), n=args.n)
    golden = [] if args.no_git else retrieval_eval.mine_pairs(args.max_commits)
    adjacent = mine_adjacent_negatives(golden, window=args.window, n=args.n)

    summary = summarise(sibling, adjacent)
    if args.out:
        with Path(args.out).open("w", encoding="utf-8", newline="\n") as fh:
            for rec in sibling + adjacent:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        summary["out"] = args.out

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_report(summary)
        if args.out:
            print(f"  wrote {len(sibling) + len(adjacent)} records -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
