#!/usr/bin/env python3
"""Every `shell=True` must carry a written reason.

THE DEFECTS, both found 2026-08-02 by sweeping for this exact keyword:

  prefect_flows.py   the Hugging Face token was built into a shell string and then LOGGED:
                         cmd = f"HF_TOKEN={hf_token} python3 ... --push"
                         _log(f"[hf] cmd: {cmd}")
                     _log writes to the Prefect run logger, so every real push wrote the
                     credential in plaintext to a persisted log. Fixed 594a732 by passing
                     it through env= and dropping the shell entirely.

  gdrive_uploader.py --folder and --upload, both argparse flags, were interpolated into a
                     shell command line. Demonstrated:
                         --folder "x'; rm -rf ~ ;'"
                         -> ... --json '{"name":"x'; rm -rf ~ ;'"}'
                                               ^ quote closes, rm runs
                     Fixed f59c255 with shlex.quote. One of three callers already did this
                     and called itself a "safe wrapper"; the other two never got it.

WHY THIS CHECKS THE KEYWORD RATHER THAN THE INTERPOLATION. The obvious detector — an
f-string reaching subprocess with shell=True — misses the real shape, because the
interpolation happens in the CALLER and shell=True sits in a shared helper
(gdrive_uploader's run_cli). A function-local check sees a safe-looking `subprocess.run(cmd,
shell=True)` and a caller with no subprocess in it. Flagging the keyword and demanding a
judgment is the version that cannot be evaded by moving code one function away.

    python scripts/check_shell_true.py
    python scripts/check_shell_true.py --baseline   # record current sites (fill in reasons)
    python scripts/check_shell_true.py --check      # exit 1 on unbaselined or unjustified

A baselined entry with an EMPTY judgment is rejected. "It was in the baseline" is not a
reason, and that is how a baseline turns into a place to hide things.

shell=True is not automatically wrong — it is required for pipes, redirects and shell
builtins. It is wrong when an outside value reaches it unquoted, and only a human can say
which one a given site is. This finds them; it does not judge them.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts" / "shell_true_baseline.json"
SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".git",
             "site-packages"}

# Real, from gdrive_uploader before f59c255. Embedded so the self-test works in a shallow
# clone or an exported tree.
KNOWN_BUG_FIXTURE = '''
def run_cli(cmd, retries=3):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return result.stdout
'''


def scan_tree(tree: ast.Module) -> list[dict]:
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                fn = node.func
                callee = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "?")
                hits.append({"line": node.lineno, "call": callee})
    return hits


def scan() -> list[dict]:
    out = []
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
            for h in scan_tree(tree):
                out.append({"file": str(p.relative_to(REPO)).replace("\\", "/"), **h})
    return out


def key(h: dict) -> str:
    return f"{h['file']}::{h['call']}"


def load_baseline() -> dict[str, str]:
    if not BASELINE.exists():
        return {}
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {e["site"]: e.get("judgment", "") for e in doc.get("accepted", [])}


def self_test() -> bool:
    found = scan_tree(ast.parse(KNOWN_BUG_FIXTURE))
    ok = bool(found)
    print(f"self-test {'PASS' if ok else 'FAIL'}  "
          f"{'flags' if ok else 'NO LONGER FLAGS'} gdrive_uploader's pre-fix run_cli")
    if not ok:
        print("  A clean run below would mean nothing.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    args = ap.parse_args()

    if args.check and not self_test():
        return 2

    hits = scan()

    if args.baseline:
        existing = load_baseline()
        BASELINE.write_text(json.dumps({
            "note": ("Each shell=True site with a WRITTEN reason it is safe. An empty "
                     "judgment is rejected by --check."),
            "accepted": [
                {"site": key(h), "line": h["line"], "judgment": existing.get(key(h), "")}
                for h in hits
            ],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {BASELINE} ({len(hits)} sites)")
        return 0

    if args.json:
        print(json.dumps({"hits": hits}, indent=2))
        return 0

    accepted = load_baseline()
    print(f"shell=True sites: {len(hits)}\n")
    new, unjudged = [], []
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
        print(f"  [{mark:11}] {h['file']}:{h['line']}  {h['call']}(...)")

    if args.check and (new or unjudged):
        print()
        for h in new + unjudged:
            print(f"UNJUSTIFIED: {key(h)}")
        print()
        print("shell=True is fine for pipes, redirects and builtins. It is not fine when an")
        print("outside value reaches it unquoted — a CLI flag, a filename, a token. Say")
        print("which this is, quote what needs quoting, then re-run --baseline.")
        return 1

    print("\nOK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
