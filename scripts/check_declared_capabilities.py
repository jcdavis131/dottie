#!/usr/bin/env python3
"""Find plugins that DECLARE a filesystem restriction and never enforce it.

THE DEFECT, and why it has a history here. gate_audit.py's own docstring lists as instance
#2 of this repo's recurring class: "capabilities.filesystem.paths -> declared by 47 of 56
manifests, enforced by 0". A manifest that names the directories a plugin may write reads
like a sandbox. If no code consults it, it is documentation wearing a gate's clothes — and
worse than none, because it buys confidence it has not earned.

That has been mostly fixed: 37 plugins now call `enforce_or_raise`. Nine still declare
paths and never check them. Measured 2026-08-01, and one of them is not academic — `herd`
declares `~/.local/share/bigbang/herd/`, and that ledger was destroyed by an unguarded
write during this very session.

WHAT THIS DOES NOT DO. It does not add enforcement. Turning the gate on for a plugin that
currently writes outside its declared paths would start raising in a live workflow, and
which of the two is wrong — the code or the declaration — is a judgement per plugin, not
something to infer. So this is a RATCHET: the nine known cases are baselined with written
judgements, and a NEW plugin that declares paths without enforcing them fails.

    python scripts/check_declared_capabilities.py
    python scripts/check_declared_capabilities.py --check --baseline scripts/declared_capabilities_baseline.json

Exit 0 by default; --check is the opt-in contract, mirroring gate_audit.py so there is one
idiom for "known debt, no new debt" rather than two.

DELIBERATELY COARSE. It asks whether the plugin package calls `enforce_or_raise` ANYWHERE,
not whether every write path is covered. A finer check would need to trace each write to a
guard and would produce false positives on helpers, indirection and re-exports — and a
checker that cries wolf gets `|| true`'d, which is instance #5 in gate_audit's docstring.
Coarse and trustworthy beats precise and ignored. The cost is real and worth stating: a
plugin that guards ONE write and leaves five unguarded passes this check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "apps" / "scout-cli" / "bigbang" / "plugins"
GUARD = "enforce_or_raise"


def declared_paths(manifest: Path):
    """capabilities.filesystem.paths from a manifest, or None if it declares no restriction.

    yaml is imported lazily and its absence is reported rather than swallowed: silently
    returning "nothing declared" would make this checker pass by finding nothing, which is
    the vacuous-clean shape it exists to prevent elsewhere.
    """
    import yaml

    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    caps = data.get("capabilities")
    if not isinstance(caps, dict):
        return None
    fs = caps.get("filesystem")
    if not isinstance(fs, dict):
        # A bare `filesystem: true/false` (seen in the wild: comms/manifest.yaml)
        # names no paths to check, so it's indistinguishable from "not declared"
        # for this script's purposes — same treatment as an unparseable manifest
        # above, not a crash.
        return None
    paths = fs.get("paths")
    return paths if paths else None


def enforces(plugin_dir: Path) -> bool:
    for p in plugin_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            if GUARD in p.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def audit():
    rows = []
    for manifest in sorted(PLUGINS.glob("*/manifest.yaml")):
        paths = declared_paths(manifest)
        if not paths:
            continue
        plugin = manifest.parent
        rows.append({
            "plugin": plugin.name,
            "declared": paths,
            "enforced": enforces(plugin),
        })
    return rows


def key(row) -> str:
    return row["plugin"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--baseline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.check and not args.baseline:
        print("--check requires --baseline", file=sys.stderr)
        return 2

    try:
        rows = audit()
    except ImportError as e:
        print(f"cannot audit: {e!r} — pyyaml is required, and reporting nothing would be "
              "a false clean", file=sys.stderr)
        return 2

    if not rows:
        print("FAIL: no manifest declared any filesystem paths. Either the plugin tree "
              "moved or the parse broke — a clean result here would be vacuous.")
        return 1

    gap = [r for r in rows if not r["enforced"]]
    if args.json:
        json.dump({"rows": rows, "unenforced": [key(r) for r in gap]}, sys.stdout, indent=2)
        print()
    else:
        print(f"DECLARED FILESYSTEM CAPABILITIES — {len(rows)} plugins declare paths, "
              f"{len(rows) - len(gap)} enforce, {len(gap)} do not\n")
        for r in gap:
            print(f"  {r['plugin']}")
            for p in r["declared"]:
                print(f"      declares {p}")
            print(f"      -> no {GUARD} anywhere in the plugin: the declaration is inert")

    if not args.check:
        return 0

    bpath = Path(args.baseline)
    if not bpath.exists():
        print(f"\nFAIL: baseline {bpath} not found — refusing to treat a missing baseline "
              "as an empty one.")
        return 1
    accepted = {e["plugin"] for e in json.loads(bpath.read_text(encoding="utf-8"))["accepted"]}
    new = [r for r in gap if key(r) not in accepted]
    stale = sorted(accepted - {key(r) for r in gap})
    if stale:
        print(f"\nnote: {len(stale)} baselined plugin(s) now enforce — prune them: "
              f"{', '.join(stale)}")
    if new:
        print(f"\nFAIL: {len(new)} plugin(s) declare filesystem paths with no enforcement "
              f"and are not baselined: {', '.join(key(r) for r in new)}")
        print("Either call enforce_or_raise, or drop the declaration — do not leave a "
              "restriction that only looks enforced.")
        return 1
    print(f"\nOK: {len(gap)} known gaps, all baselined with judgements; no new ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
