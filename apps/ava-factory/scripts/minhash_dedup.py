#!/usr/bin/env python3
"""MinHash + LSH near-duplicate detection over a code corpus. **stdlib only.**

Phase 8 of the code-embedding guide. Solo personal project, no connection to
employer, built with public/free-tier only.

WHY THIS MATTERS, precisely. A duplicated function is not merely wasted compute.
In an in-batch-negatives contrastive objective the *positive* for query A can be
byte-identical to a *negative* for query B. The loss then pushes the same vector
apart from and together with the same point, and the gradient it contributes is
noise with a confident sign. That is a FALSE NEGATIVE, it is invisible in the
training curve, and it caps the model. Duplicates also inflate every retrieval
metric, because the golden document is sitting in the index three times.

WHAT IS DELIBERATELY NOT USED.
  * `datasketch` — the obvious library. Not installed, and not going to be: the
    openswap doctrine here is zero new dependencies. Its MinHash is ~40 lines of
    modular arithmetic (`_permutations` below) and its LSH is a dict of buckets.
  * `networkx` — for connected components. `UnionFind` below is 15 lines.
  * builtin `hash()` — PYTHONHASHSEED-salted, so a corpus deduplicated in one
    process would not be deduplicated the same way in the next. That is a
    RECORDED BUG CLASS in this repo (hash()-as-seed), and
    `test_minhash_dedup.py::TestDeterminism` runs two real subprocesses with
    different PYTHONHASHSEED values specifically to catch a regression to it.
    Every hash here is `hashlib.blake2b`.

FILE DISCOVERY IS REUSED, NOT REIMPLEMENTED. `ast_pairs.walk` already encodes
which directories to skip (.git, __pycache__, .venv, node_modules, ...). A second
copy of that set is exactly the drift bug this repo has been bitten by twice, so
`ast_pairs.py` is loaded by path and its `walk` is called directly.

STATED LIMITS.
  * Python only, same honest scope as `ast_pairs.py`. A file that does not parse
    is still hashed, but only whitespace-collapsed -- its comments survive, so
    comment-only variants of unparseable files will NOT collide. The CLI reports
    how many files fell into that path rather than hiding it.
  * MinHash estimates Jaccard over *token shingles*. It finds near-duplicate
    TEXT. A function reimplemented with different identifiers is a semantic
    duplicate that this will not catch, and no amount of tuning changes that.

Usage:
    python scripts/minhash_dedup.py --path apps/scout-cli
    python scripts/minhash_dedup.py --path apps/scout-cli --unit file
    python scripts/minhash_dedup.py --path . --keep-set keep.json --json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# reuse, do not duplicate: file discovery + the skip-directory set
# --------------------------------------------------------------------------
_AST_PAIRS = Path(__file__).resolve().parent / "ast_pairs.py"


def _load_ast_pairs():
    """Import ast_pairs by path so this works from any cwd.

    `scripts/` is not a package, so a plain `import ast_pairs` only succeeds when
    it happens to be on sys.path. Same loader pattern stackv3_adapt.py uses for
    dataset_discovery.gate_license.
    """
    spec = importlib.util.spec_from_file_location("_minhash_ast_pairs", _AST_PAIRS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AP = _load_ast_pairs()
walk = _AP.walk  # the ONE definition of "which .py files count"

# --------------------------------------------------------------------------
# tunables
# --------------------------------------------------------------------------
NUM_PERM = 128
BANDS = 16
ROWS = 8  # BANDS * ROWS must equal NUM_PERM -- enforced by check_banding()
SHINGLE_K = 5
THRESHOLD = 0.8

# Mersenne prime 2**61-1: the standard MinHash modulus. Big enough that
# (a*h + b) mod p is a near-uniform pairwise-independent permutation of the
# 32-bit hash space, small enough to stay in one machine word on 64-bit CPython.
_MERSENNE = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1

# ast.unparse cannot render an empty suite, so a def/class whose entire body was
# a docstring becomes `pass`. That is also the semantically right answer for
# dedup: a docstring-only stub and a `pass` stub ARE the same function.
_DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


# --------------------------------------------------------------------------
# 1. normalize
# --------------------------------------------------------------------------
def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            rest = body[1:]
            if not rest and not isinstance(node, ast.Module):
                rest = [ast.Pass()]
            node.body = rest
    ast.fix_missing_locations(tree)
    return tree


def canonical_python(code: str) -> str | None:
    """AST round-trip, or None if the source does not parse.

    `ast` never records comments, so parse+unparse deletes them for free.
    Docstrings ARE in the tree and are removed explicitly. unparse then rewrites
    indentation, line breaks, quote style, redundant parens and spacing into one
    canonical form -- which is the entire reason formatting-only variants collide.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None
    try:
        return ast.unparse(_strip_docstrings(tree))
    except (AttributeError, ValueError, RecursionError):  # pragma: no cover
        return None


def normalize(code: str) -> str:
    """Comment- and docstring-free, formatting-free canonical text.

    Falls back to plain whitespace collapse when the source does not parse.
    Callers that need to know which path was taken should call
    `canonical_python` themselves -- see `_collect_documents`.
    """
    canon = canonical_python(code)
    return " ".join((canon if canon is not None else code).split())


# --------------------------------------------------------------------------
# 2. shingles
# --------------------------------------------------------------------------
def shingles(text: str, k: int = SHINGLE_K) -> frozenset[str]:
    """k-gram shingles over whitespace-separated tokens.

    A document shorter than k tokens yields ONE shingle (itself) rather than the
    empty set. Returning empty there would give every short function the same
    all-maximum signature and cluster them all together -- a silent, enormous
    false-positive cluster.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    toks = text.split()
    if not toks:
        return frozenset()
    if len(toks) < k:
        return frozenset([" ".join(toks)])
    return frozenset(" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1))


# --------------------------------------------------------------------------
# 3. minhash
# --------------------------------------------------------------------------
def _base_hash(shingle: str) -> int:
    """64-bit blake2b of the shingle, folded into the 32-bit MinHash space."""
    d = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(d, "big") & _MAX_HASH


_PERM_CACHE: dict[int, tuple[tuple[int, int], ...]] = {}


def _permutations(num_perm: int) -> tuple[tuple[int, int], ...]:
    """`num_perm` (a, b) coefficient pairs for h_i(x) = (a*x + b) mod p.

    Derived from blake2b of the permutation index, so they are identical in
    every process, on every machine, forever. Seeding these from `random` or
    from `hash()` is the failure mode this whole module is written around.
    """
    cached = _PERM_CACHE.get(num_perm)
    if cached is not None:
        return cached
    out = []
    for i in range(num_perm):
        d = hashlib.blake2b(
            str(i).encode("ascii"), digest_size=16, person=b"minhash-perm"
        ).digest()
        a = int.from_bytes(d[:8], "big") % (_MERSENNE - 1) + 1  # a != 0
        b = int.from_bytes(d[8:], "big") % _MERSENNE
        out.append((a, b))
    _PERM_CACHE[num_perm] = tuple(out)
    return _PERM_CACHE[num_perm]


def minhash(shingle_set, num_perm: int = NUM_PERM) -> tuple[int, ...]:
    """MinHash signature: the minimum of each of `num_perm` permutations.

    An empty shingle set gives the all-maximum signature. `shingles()` only
    returns empty for genuinely empty text, and `_collect_documents` drops those,
    so the degenerate all-empty cluster cannot form in the CLI path.
    """
    perms = _permutations(num_perm)
    sig = [_MAX_HASH] * num_perm
    for s in shingle_set:
        h = _base_hash(s)
        row = [(a * h + b) % _MERSENNE & _MAX_HASH for a, b in perms]
        sig = list(map(min, sig, row))
    return tuple(sig)


def jaccard_estimate(sig_a, sig_b) -> float:
    """Fraction of agreeing positions -- the unbiased MinHash Jaccard estimator."""
    if len(sig_a) != len(sig_b):
        raise ValueError(f"signature lengths differ: {len(sig_a)} vs {len(sig_b)}")
    if not sig_a:
        raise ValueError("empty signatures")
    return sum(x == y for x, y in zip(sig_a, sig_b, strict=True)) / len(sig_a)


def true_jaccard(a, b) -> float:
    """Exact Jaccard over two shingle sets -- the thing MinHash approximates."""
    a, b = set(a), set(b)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# --------------------------------------------------------------------------
# 4. LSH banding
# --------------------------------------------------------------------------
def check_banding(num_perm: int, bands: int, rows: int) -> None:
    """bands * rows == num_perm. Enforced, never assumed.

    Getting this wrong does not crash: the tail of every signature is simply
    never looked at, recall silently drops, and the run still prints a number.
    """
    if bands < 1 or rows < 1:
        raise ValueError(f"bands and rows must be >= 1, got bands={bands} rows={rows}")
    if bands * rows != num_perm:
        raise ValueError(
            f"bands*rows must equal num_perm: {bands}*{rows}={bands * rows} "
            f"!= {num_perm}. Signature positions past {bands * rows} would never "
            f"be examined and recall would drop with no error."
        )


def lsh_buckets(signatures: dict, bands: int = BANDS, rows: int = ROWS) -> dict:
    """{bucket_digest: [keys]} -- keys sharing an identical band land together."""
    buckets: dict[bytes, list] = {}
    for key in sorted(signatures):  # sorted => bucket member order is deterministic
        sig = signatures[key]
        check_banding(len(sig), bands, rows)
        for b in range(bands):
            band = sig[b * rows : (b + 1) * rows]
            # The band index is mixed in so band 0 == (1,2) and band 3 == (1,2)
            # cannot share a bucket.
            payload = b.to_bytes(4, "big") + b"".join(
                v.to_bytes(8, "big") for v in band
            )
            digest = hashlib.blake2b(payload, digest_size=16).digest()
            buckets.setdefault(digest, []).append(key)
    return buckets


def candidate_pairs(signatures: dict, bands: int = BANDS, rows: int = ROWS) -> set:
    """Sorted (key_a, key_b) pairs colliding in at least one band."""
    pairs = set()
    for members in lsh_buckets(signatures, bands, rows).values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add((members[i], members[j]))  # members already sorted
    return pairs


# --------------------------------------------------------------------------
# 5. union-find -> connected components
# --------------------------------------------------------------------------
class UnionFind:
    """Disjoint-set with path compression. The networkx replacement."""

    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def components(self) -> list[list]:
        """Components as sorted member lists, themselves sorted. Deterministic."""
        groups: dict = {}
        for x in self.parent:
            groups.setdefault(self.find(x), []).append(x)
        return sorted((sorted(g) for g in groups.values()), key=lambda g: (-len(g), g))


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------
def cluster_documents(
    docs: dict,
    *,
    k: int = SHINGLE_K,
    num_perm: int = NUM_PERM,
    bands: int = BANDS,
    rows: int = ROWS,
    threshold: float = THRESHOLD,
) -> dict:
    """{key: raw_text} -> clusters, keep-set, and the counts behind them.

    LSH produces CANDIDATES, not answers. Every candidate pair is re-scored with
    `jaccard_estimate` and dropped below `threshold`; without that step a single
    unlucky band collision chains two unrelated files into one cluster through
    union-find, and the cluster count is then a fiction.
    """
    check_banding(num_perm, bands, rows)
    sigs = {}
    sets = {}
    for key, text in docs.items():
        sh = shingles(normalize(text), k)
        if not sh:
            continue
        sets[key] = sh
        sigs[key] = minhash(sh, num_perm)

    cands = candidate_pairs(sigs, bands, rows)
    uf = UnionFind()
    verified = []
    for a, b in sorted(cands):
        est = jaccard_estimate(sigs[a], sigs[b])
        if est >= threshold:
            uf.union(a, b)
            verified.append((a, b, round(est, 4)))

    clusters = [c for c in uf.components() if len(c) > 1]
    clustered = {m for c in clusters for m in c}
    # One survivor per cluster (lexicographically first, so it is reproducible)
    # plus everything that was never a duplicate.
    keep = sorted([c[0] for c in clusters] + [k_ for k_ in sigs if k_ not in clustered])
    return {
        "documents": len(sigs),
        "skipped_empty": len(docs) - len(sigs),
        "candidate_pairs": len(cands),
        "verified_pairs": len(verified),
        "clusters": clusters,
        "keep": keep,
        "dropped": sorted(clustered - set(keep)),
        "pairs": verified,
        "shingle_sets": sets,
        "signatures": sigs,
    }


# --------------------------------------------------------------------------
# corpus collection
# --------------------------------------------------------------------------
def iter_functions(source: str, path: str):
    """(qualified_name, source_segment) for every def/async def in a file."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from visit(child, prefix + child.name + ".")
            elif isinstance(child, _FUNC_NODES):
                try:
                    seg = ast.unparse(child)
                except (AttributeError, ValueError, RecursionError):  # pragma: no cover
                    continue
                yield f"{path}::{prefix}{child.name}", seg
                yield from visit(child, prefix + child.name + ".")
            else:
                yield from visit(child, prefix)

    yield from visit(tree)


def collect_documents(base: Path, unit: str = "function") -> tuple[dict, dict]:
    """Build {key: text} for the corpus. Returns (docs, stats)."""
    docs: dict[str, str] = {}
    files = 0
    unparseable = 0
    for p in walk(base):
        files += 1
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(base).as_posix()
        if canonical_python(src) is None:
            unparseable += 1
        if unit == "file":
            docs[rel] = src
        else:
            for key, seg in iter_functions(src, rel):
                docs[key] = seg
    return docs, {"files": files, "unparseable": unparseable, "unit": unit}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=".", help="tree to scan")
    ap.add_argument("--unit", choices=("function", "file"), default="function",
                    help="function is the contrastive training unit; file is coarser")
    ap.add_argument("--k", type=int, default=SHINGLE_K, help="shingle size in tokens")
    ap.add_argument("--num-perm", type=int, default=NUM_PERM)
    ap.add_argument("--bands", type=int, default=BANDS)
    ap.add_argument("--rows", type=int, default=ROWS)
    ap.add_argument("--threshold", type=float, default=THRESHOLD,
                    help="estimated Jaccard a candidate pair must reach to count")
    ap.add_argument("--keep-set", help="write the deduplicated key list here as JSON")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=3, help="how many clusters to print")
    args = ap.parse_args(argv)

    try:
        check_banding(args.num_perm, args.bands, args.rows)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    base = Path(args.path).resolve()
    if not base.exists():
        print(f"error: no such path: {base}", file=sys.stderr)
        return 2

    docs, stats = collect_documents(base, args.unit)
    res = cluster_documents(
        docs, k=args.k, num_perm=args.num_perm, bands=args.bands,
        rows=args.rows, threshold=args.threshold,
    )

    clusters = res["clusters"]
    largest = clusters[0] if clusters else []
    summary = {
        "path": str(base),
        "unit": stats["unit"],
        "files_scanned": stats["files"],
        "files_unparseable": stats["unparseable"],
        "corpus_size": res["documents"],
        "skipped_empty": res["skipped_empty"],
        "candidate_pairs": res["candidate_pairs"],
        "verified_pairs": res["verified_pairs"],
        "clusters": len(clusters),
        "duplicate_documents": len(res["dropped"]),
        "largest_cluster_size": len(largest),
        "largest_cluster": largest[:20],
        "keep_set_size": len(res["keep"]),
        "params": {
            "k": args.k, "num_perm": args.num_perm, "bands": args.bands,
            "rows": args.rows, "threshold": args.threshold,
        },
    }

    if args.keep_set:
        Path(args.keep_set).write_text(
            json.dumps({"keep": res["keep"], "dropped": res["dropped"]}, indent=2),
            encoding="utf-8",
        )
        summary["keep_set_path"] = args.keep_set

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"path            : {base}")
    print(f"unit            : {stats['unit']}")
    print(f"files scanned   : {stats['files']}  ({stats['unparseable']} unparseable, "
          f"whitespace-collapse fallback)")
    print(f"corpus size     : {res['documents']} documents  "
          f"({res['skipped_empty']} skipped: no tokens after normalisation)")
    print(f"candidate pairs : {res['candidate_pairs']}  (LSH {args.bands}x{args.rows})")
    print(f"verified pairs  : {res['verified_pairs']}  (est. Jaccard >= {args.threshold})")
    print(f"clusters        : {len(clusters)}")
    print(f"duplicates      : {len(res['dropped'])} documents drop out of "
          f"{res['documents']}  ({len(res['dropped']) / max(res['documents'], 1):.1%})")
    print(f"keep set        : {len(res['keep'])}")
    if largest:
        print(f"largest cluster : {len(largest)} members")
        for m in largest[:20]:
            print(f"    {m}")
        if len(largest) > 20:
            print(f"    ... and {len(largest) - 20} more")
        for c in clusters[1:args.show]:
            print(f"cluster ({len(c)}):")
            for m in c[:6]:
                print(f"    {m}")
    else:
        print("largest cluster : none -- no near-duplicates above threshold.")
    if args.keep_set:
        print(f"wrote {summary['keep_set_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
