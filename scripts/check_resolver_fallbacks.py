#!/usr/bin/env python3
"""Path resolvers that guard some candidates and return a final one UNCHECKED.

THE DEFECT, found three times on 2026-08-02 by sweeping for the shape rather than waiting
for each to bite:

    ava/cli.py         LIVE   every `scout ava` ran against the superseded
                              ~/workspace/ava-agi-factory-v6-4 while <repo>/apps/ava-factory
                              existed and was never a candidate            (0c89edd)
    rtx/cli.py         LIVE   CUSTOM_ROOT and BB_OFFLOAD pointed at
                              ~/workspace/autoresearch-rtx-custom, which does not exist
                              (6063da7)
    arxiviq            LATENT preferred the superseded factory NAME over the canonical one
                              (cda982e)

The shape: a function whose name says it resolves a path, which guards candidates with
`.exists()` in a loop, and then `return`s a final expression that nothing checked. The
guarded candidates are the honest part; the unguarded tail is where a wrong or missing path
ships.

AN UNGUARDED FALLBACK IS NOT AUTOMATICALLY A BUG, which is why this carries a baseline
instead of failing on every match. Returning a default the caller will create is normal.
It becomes a bug when the fallback can be WRONG rather than merely ABSENT — a superseded
checkout that exists and outranks the canonical one, or a legacy path returned after every
candidate already failed. That judgment is a human's; this only finds the candidates.

    python scripts/check_resolver_fallbacks.py
    python scripts/check_resolver_fallbacks.py --json
    python scripts/check_resolver_fallbacks.py --baseline   # write today's state as accepted
    python scripts/check_resolver_fallbacks.py --check      # exit 1 on anything NOT baselined

--check fails only on resolvers absent from the baseline, so pre-existing judged cases do
not block CI and a NEW one has to be looked at. Each baseline entry carries a written
judgment; an entry with no reason is rejected, because "it was in the baseline" is not a
reason and that is how a baseline becomes a place to hide things.

Parsed with `ast`, never regex: this repo's comments quote the code they discuss, and a
grep counting prose as code has already produced wrong answers here.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts" / "resolver_fallbacks_baseline.json"

SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".git",
             "site-packages"}
# Names that claim to resolve a location. Narrow on purpose — a broad match would drag in
# every helper that happens to end in _path.
RESOLVER_RE = re.compile(r"resolve|_root$|_home$|locate", re.I)


def _is_path_expr(node: ast.AST) -> bool:
    """`a / "b"`, `Path(...)`, `.resolve()`, `.expanduser()`, `Path.home()`, `x or <path>`.

    BoolOp is handled deliberately. The fixes in 0c89edd and 6063da7 both end
    `return canonical or (Path.home() / ...)`, and without this branch the detector stopped
    seeing them — not because the shape was resolved but because the expression changed
    form. A checker that goes quiet for an accidental reason is worse than one that never
    saw the case, so those two are matched and BASELINED with the reason instead.
    """
    if isinstance(node, ast.BoolOp):
        return any(_is_path_expr(v) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        return name in ("Path", "resolve", "expanduser", "home")
    return False


def scan_file(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if not RESOLVER_RE.search(fn.name):
            continue
        # Does it guard anything at all? A resolver with no .exists() check is a different
        # shape (it never pretends to verify) and is out of scope here.
        guarded = any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr in ("exists", "is_dir", "is_file")
            for c in ast.walk(fn)
        )
        if not guarded:
            continue
        # Does it RAISE when nothing matched? Then the final return is reached only on
        # success and is not an unguarded fallback. reviewgraph/graph.py:_resolve_root is
        # exactly this, and the first version of this sweep called it a hit.
        if any(isinstance(n, ast.Raise) for n in ast.walk(fn)):
            continue
        last = fn.body[-1]
        if isinstance(last, ast.Return) and last.value is not None and _is_path_expr(last.value):
            out.append({
                "file": str(path.relative_to(REPO)).replace("\\", "/"),
                "function": fn.name,
                "line": fn.lineno,
            })
    return out


def scan() -> list[dict]:
    hits: list[dict] = []
    for root in ("apps", "packages", "scripts"):
        base = REPO / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if any(x in p.parts for x in SKIP_DIRS) or "test" in p.name:
                continue
            hits.extend(scan_file(p))
    return hits


def key(h: dict) -> str:
    return f"{h['file']}::{h['function']}"


def load_baseline() -> dict[str, str]:
    if not BASELINE.exists():
        return {}
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {e["resolver"]: e.get("judgment", "") for e in doc.get("accepted", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on resolvers absent from the baseline")
    ap.add_argument("--baseline", action="store_true",
                    help="write the current state as accepted (judgments must be filled in)")
    args = ap.parse_args()

    hits = scan()

    if args.baseline:
        existing = load_baseline()
        BASELINE.write_text(json.dumps({
            "note": ("Resolvers whose unguarded fallback has been JUDGED acceptable. "
                     "An entry with an empty judgment is rejected by --check: 'it was in "
                     "the baseline' is not a reason."),
            "accepted": [
                {"resolver": key(h), "line": h["line"],
                 "judgment": existing.get(key(h), "")}
                for h in hits
            ],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {BASELINE} ({len(hits)} resolvers)")
        return 0

    if args.json:
        print(json.dumps({"hits": hits}, indent=2))
        return 0

    accepted = load_baseline()
    print(f"resolvers with an unguarded final return: {len(hits)}\n")
    unjudged, new = [], []
    for h in hits:
        k = key(h)
        if k not in accepted:
            new.append(h)
            mark = "NEW"
        elif not accepted[k].strip():
            unjudged.append(h)
            mark = "NO JUDGMENT"
        else:
            mark = "ok"
        print(f"  [{mark:11}] {h['file']}:{h['line']}  {h['function']}()")

    if args.check and (new or unjudged):
        print()
        for h in new:
            print(f"UNBASELINED: {key(h)}")
        for h in unjudged:
            print(f"NO JUDGMENT: {key(h)}")
        print()
        print("Decide for each: can this fallback be WRONG, or only ABSENT? Wrong means a")
        print("superseded checkout that outranks the canonical one, or a legacy path")
        print("returned after every candidate already failed. Fix those; baseline the rest")
        print("WITH A REASON, then re-run --baseline.")
        return 1

    print("\nOK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
