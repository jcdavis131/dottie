#!/usr/bin/env python3
"""The unified project DAG: validate it, and print what is ready to work on now.

Why this exists (2026-09-05): the account holds 27 repositories and the operator's
effort was spreading across the outer ring (the game sites absorbed August) while
the center's CI sat red for two weeks. Prioritising by feel had failed. The fix is
one machine-readable graph, `docs/project_dag.json`, where every piece of product
work is a node with explicit `depends_on` edges, a priority, and a status. Agents
and the operator ask this script the only question that matters at the start of a
session: *what is ready right now, in priority order?* A node is ready when it is
not done and every dependency is done. Nothing else is worked on.

The graph is the plan; this script keeps it honest:

- `--check` fails (exit 1) on a malformed node, an unknown dependency, a
  duplicate id, or a cycle. It runs in CI so the DAG cannot rot into a list.
- default output prints the ready frontier sorted by (priority, size), then the
  blocked nodes with the dependency that blocks each, then a one-line tally.
- `--json` emits the same for tooling (the SessionStart hook reads it).
- `--mermaid` renders the graph for docs/PROJECT_DAG.md.

Statuses: done | in_progress | ready | blocked | parked. `ready`/`blocked` are
DERIVED (recomputed here); a node's stored status is only trusted for done,
in_progress and parked. Parked nodes never appear in the frontier and never
block anything they feed (their dependents show as blocked-by-parked).

Usage:
    python scripts/dag_next.py                 # frontier, human readable
    python scripts/dag_next.py --check         # validate; exit 1 on any defect
    python scripts/dag_next.py --json          # machine readable
    python scripts/dag_next.py --mermaid       # graph source for the doc
    python scripts/dag_next.py --repo dottie   # frontier filtered to one repo
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DAG = ROOT / "docs" / "project_dag.json"

STATUSES = {"done", "in_progress", "ready", "blocked", "parked"}
KINDS = {"infra", "product", "research", "ops"}
SIZES = {"S": 1, "M": 2, "L": 3}
REQUIRED = ("id", "title", "repo", "kind", "status", "priority", "size", "depends_on")


def load(path: Path = DEFAULT_DAG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(dag: dict) -> list[str]:
    """Return a list of defects; empty means the graph is well formed and acyclic."""
    errors: list[str] = []
    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["`nodes` must be a non-empty list"]
    ids: set[str] = set()
    for n in nodes:
        nid = n.get("id", "<missing id>")
        for key in REQUIRED:
            if key not in n:
                errors.append(f"{nid}: missing `{key}`")
        if nid in ids:
            errors.append(f"{nid}: duplicate id")
        ids.add(nid)
        if n.get("status") not in STATUSES:
            errors.append(f"{nid}: status {n.get('status')!r} not in {sorted(STATUSES)}")
        if n.get("kind") not in KINDS:
            errors.append(f"{nid}: kind {n.get('kind')!r} not in {sorted(KINDS)}")
        if n.get("size") not in SIZES:
            errors.append(f"{nid}: size {n.get('size')!r} not in {sorted(SIZES)}")
        p = n.get("priority")
        if not isinstance(p, int) or not 1 <= p <= 5:
            errors.append(f"{nid}: priority must be an int 1..5, got {p!r}")
        if not isinstance(n.get("depends_on"), list):
            errors.append(f"{nid}: depends_on must be a list")
    for n in nodes:
        for dep in n.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"{n.get('id')}: depends on unknown node {dep!r}")
            if dep == n.get("id"):
                errors.append(f"{n.get('id')}: depends on itself")
    if errors:
        return errors
    # Kahn's algorithm: if we cannot pop every node, the remainder is a cycle.
    indeg = {n["id"]: 0 for n in nodes}
    out: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n["depends_on"]:
            out[dep].append(n["id"])
            indeg[n["id"]] += 1
    queue = deque(sorted(i for i, d in indeg.items() if d == 0))
    seen = 0
    while queue:
        cur = queue.popleft()
        seen += 1
        for nxt in out[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if seen != len(nodes):
        cyc = sorted(i for i, d in indeg.items() if d > 0)
        errors.append(f"cycle among: {', '.join(cyc)}")
    return errors


def classify(dag: dict) -> dict[str, list[dict]]:
    """Recompute ready/blocked from dependencies. Stored ready/blocked are ignored."""
    by_id = {n["id"]: n for n in dag["nodes"]}
    ready: list[dict] = []
    blocked: list[dict] = []
    in_progress: list[dict] = []
    done: list[dict] = []
    parked: list[dict] = []
    for n in dag["nodes"]:
        st = n["status"]
        if st == "done":
            done.append(n)
            continue
        if st == "parked":
            parked.append(n)
            continue
        open_deps = [d for d in n["depends_on"] if by_id[d]["status"] != "done"]
        if st == "in_progress":
            in_progress.append({**n, "open_deps": open_deps})
        elif open_deps:
            blocked.append({**n, "open_deps": open_deps})
        else:
            ready.append(n)
    key = lambda n: (n["priority"], SIZES[n["size"]], n["id"])  # noqa: E731
    return {
        "ready": sorted(ready, key=key),
        "in_progress": sorted(in_progress, key=key),
        "blocked": sorted(blocked, key=key),
        "done": done,
        "parked": parked,
    }


def render_text(groups: dict[str, list[dict]], repo: str | None = None) -> str:
    def keep(n: dict) -> bool:
        return repo is None or n["repo"] == repo

    lines: list[str] = []
    lines.append("READY (do these, in order):")
    for n in filter(keep, groups["ready"]):
        lines.append(f"  P{n['priority']} {n['size']}  {n['id']:<28} [{n['repo']}] {n['title']}")
    if not any(map(keep, groups["ready"])):
        lines.append("  (nothing ready — finish an in-progress node or unpark one)")
    if any(map(keep, groups["in_progress"])):
        lines.append("IN PROGRESS:")
        for n in filter(keep, groups["in_progress"]):
            lines.append(f"  P{n['priority']} {n['size']}  {n['id']:<28} [{n['repo']}] {n['title']}")
    if any(map(keep, groups["blocked"])):
        lines.append("BLOCKED (waiting on):")
        for n in filter(keep, groups["blocked"]):
            lines.append(f"  P{n['priority']} {n['size']}  {n['id']:<28} <- {', '.join(n['open_deps'])}")
    lines.append(
        f"tally: {len(groups['ready'])} ready, {len(groups['in_progress'])} in progress, "
        f"{len(groups['blocked'])} blocked, {len(groups['done'])} done, {len(groups['parked'])} parked"
    )
    return "\n".join(lines)


def render_mermaid(dag: dict) -> str:
    groups = classify(dag)
    state = {}
    for name, lst in groups.items():
        for n in lst:
            state[n["id"]] = name
    out = ["flowchart LR"]
    for n in dag["nodes"]:
        label = n["title"].replace('"', "'")
        out.append(f'  {n["id"]}["{n["id"]}<br/>{label}"]')
    for n in dag["nodes"]:
        for dep in n["depends_on"]:
            out.append(f"  {dep} --> {n['id']}")
    out.append("  classDef done fill:#dcefe2,stroke:#2c7a4b,color:#1a2330;")
    out.append("  classDef ready fill:#d9ecea,stroke:#0e6b6b,color:#1a2330;")
    out.append("  classDef in_progress fill:#f6e8cf,stroke:#a6701c,color:#1a2330;")
    out.append("  classDef blocked fill:#e9eef1,stroke:#75808c,color:#1a2330;")
    out.append("  classDef parked fill:#f5dcdc,stroke:#b23b3b,color:#1a2330;")
    for name in ("done", "ready", "in_progress", "blocked", "parked"):
        ids = [i for i, s in state.items() if s == name]
        if ids:
            out.append(f"  class {','.join(ids)} {name};")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dag", type=Path, default=DEFAULT_DAG)
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 on defects")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--mermaid", action="store_true", help="emit mermaid graph source")
    ap.add_argument("--repo", help="filter the frontier to one repo")
    args = ap.parse_args(argv)

    try:
        dag = load(args.dag)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot load {args.dag}: {e}", file=sys.stderr)
        return 1
    errors = validate(dag)
    if errors:
        for e in errors:
            print(f"DAG DEFECT: {e}", file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: {len(dag['nodes'])} nodes, acyclic, all dependencies resolve")
        return 0
    if args.mermaid:
        print(render_mermaid(dag))
        return 0
    groups = classify(dag)
    if args.json:
        print(json.dumps(groups, indent=2))
        return 0
    print(render_text(groups, args.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
