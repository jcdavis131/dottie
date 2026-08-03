#!/usr/bin/env python3
"""CLI arguments joined straight onto a root path and then used on the filesystem.

THE DEFECT, found 2026-08-02 in forge and fixed in a5c155b. Proven in an isolated sandbox,
never against the real tree:

    forge rm ../victim --force
    -> {"ok": true, "removed": "../victim", "dir": ".../plugins/../victim"}
    victim directory: GONE

`PLUGIN_ROOT / name` follows `..`, and given an absolute path Path.__truediv__ discards the
root entirely. In that repo it made `scout forge rm ../core --force` an rmtree of
bigbang/core, reported as a success. `_valid_name` existed and guarded two commands; the
four that took the name of an EXISTING plugin never called it.

WHY THIS DETECTOR IS NARROW, and why the first version was not shippable. A broad sweep for
"filesystem op on a param-derived path" returned 5 hits across 1,131 files and only 2 were
real. The other three took INTERNAL identifiers — a ledger exp_id that raises on an unknown
value, Prefect task params set by the flow. The property separating them is whether the
parameter is bound to a COMMAND-LINE argument, so that is what this checks:

  1. the function is decorated `@app.command(...)` (or `.command()` on any object)
  2. a parameter's default is `typer.Argument(...)` or `typer.Option(...)`
  3. that parameter appears DIRECTLY in a path join inside the function body
  4. a filesystem operation happens in the same function
  5. the function contains no validation or containment guard

Point 3 is what makes the fix visible. After a5c155b the commands call a guarded helper
(`_plugin_dir(name)`) and perform no direct join, so they stop matching — correctly, and
for the right reason rather than by accident.

    python scripts/check_cli_path_args.py
    python scripts/check_cli_path_args.py --json
    python scripts/check_cli_path_args.py --check     # self-test, then exit 1 on any hit

NON-VACUITY. A checker that reports 0 is indistinguishable from one that is broken, which
is this repo's most repeated lesson. `--check` first runs a self-test against an embedded
copy of forge's pre-fix rm_cmd and exits 2 if it no longer flags it.

Gates without a baseline: the shape is rare and every instance is a candidate arbitrary
read, write or delete driven by a shell argument. If it ever fires broadly, add a judged
baseline the way gate_audit.py did — do NOT add a tolerance.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".git",
             "site-packages"}

FS_OPS = {"rmtree", "unlink", "rmdir", "remove", "write_text", "write_bytes",
          "mkdir", "replace", "rename", "open", "read_text", "read_bytes"}
GUARDS = {"resolve", "relative_to", "is_relative_to", "fullmatch", "match", "startswith"}
GUARD_NAME_RE = re.compile(r"valid|sanitiz|safe_|_check|guard", re.I)

# forge's rm_cmd exactly as it stood before a5c155b, minus the emit noise. Embedded rather
# than read from git so the self-test works in a shallow clone or an exported tree.
KNOWN_BUG_FIXTURE = '''
@app.command("rm")
def rm_cmd(name: str = typer.Argument(...), force: bool = typer.Option(False, "--force")):
    """Remove a forged plugin (requires --force)."""
    pdir = PLUGIN_ROOT / name
    if not pdir.exists():
        return
    if not force:
        fail_agent("Pass --force", command="forge rm", example="scout forge rm x --force")
    shutil.rmtree(pdir)
'''


def _is_cli_command(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        node = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(node, ast.Attribute) and node.attr == "command":
            return True
    return False


def _cli_params(fn: ast.AST) -> set[str]:
    """Params whose default is typer.Argument(...) / typer.Option(...)."""
    args = fn.args
    names = [a.arg for a in args.args]
    defaults = list(args.defaults)
    out: set[str] = set()
    # defaults align to the TAIL of positional args
    for name, default in zip(names[len(names) - len(defaults):], defaults, strict=True):
        if isinstance(default, ast.Call):
            f = default.func
            attr = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if attr in ("Argument", "Option"):
                out.add(name)
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if isinstance(d, ast.Call):
            f = d.func
            attr = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if attr in ("Argument", "Option"):
                out.add(a.arg)
    return out


def scan_tree(tree: ast.Module) -> list[dict]:
    hits = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if not _is_cli_command(fn):
            continue
        cli = _cli_params(fn)
        if not cli:
            continue

        joined = {
            n.right.id
            for n in ast.walk(fn)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
            and isinstance(n.right, ast.Name) and n.right.id in cli
        }
        if not joined:
            continue

        ops = sorted({
            c.func.attr for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr in FS_OPS
        })
        if not ops:
            continue

        guarded = any(
            isinstance(c, ast.Call)
            and (
                (isinstance(c.func, ast.Attribute) and c.func.attr in GUARDS)
                or GUARD_NAME_RE.search(
                    c.func.attr if isinstance(c.func, ast.Attribute)
                    else getattr(c.func, "id", "") or ""
                )
            )
            for c in ast.walk(fn)
        )
        if guarded:
            continue

        hits.append({"function": fn.name, "line": fn.lineno,
                     "params": sorted(joined), "ops": ops})
    return hits


def self_test() -> bool:
    found = scan_tree(ast.parse(KNOWN_BUG_FIXTURE))
    ok = any(h["function"] == "rm_cmd" for h in found)
    if ok:
        h = found[0]
        print(f"self-test PASS  flags forge's pre-fix rm_cmd "
              f"(params={h['params']} ops={h['ops']})")
    else:
        print("self-test FAIL  the detector no longer flags forge's pre-fix rm_cmd. "
              "A clean run below would mean nothing.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="run the self-test, then exit 1 on any hit")
    args = ap.parse_args()

    if args.check and not self_test():
        return 2

    hits, scanned = [], 0
    for root in ("apps", "packages", "scripts"):
        base = REPO / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if any(x in p.parts for x in SKIP_DIRS) or "test" in p.name:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            scanned += 1
            for h in scan_tree(tree):
                hits.append({"file": str(p.relative_to(REPO)).replace("\\", "/"), **h})

    if args.json:
        print(json.dumps({"scanned": scanned, "hits": hits}, indent=2))
        return 1 if (args.check and hits) else 0

    print(f"scanned {scanned} files")
    print(f"CLI args joined onto a root and used on the filesystem, unguarded: {len(hits)}\n")
    for h in hits:
        print(f"  {h['file']}:{h['line']}  {h['function']}()")
        print(f"     cli param(s) joined : {h['params']}")
        print(f"     filesystem ops      : {h['ops']}")
        print("     -> a shell argument reaches a path. `..` traverses; an absolute path")
        print("        replaces the root entirely.")
    if not hits:
        print("0 candidates. Commands that take a name now route through a guarded helper")
        print("rather than joining it directly — see the module docstring for what that")
        print("does and does not rule out.")
    if args.check and hits:
        print(f"\nFAIL: {len(hits)} unguarded CLI path argument(s).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
