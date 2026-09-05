"""Software line: move DAG nodes and run a repo's registered validate gate (spec §2)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from factory.config import (
    Factory,
    FactoryError,
    dag_module,
    git_branch,
    git_dirty,
    git_head,
    run_cmd,
    table,
)


def next_nodes(f: Factory, repo: str | None = None) -> str:
    return dag_module().render_text(f.groups(), repo=repo)


def start(f: Factory, node_id: str, agent: str = "factory") -> str:
    """ready → in_progress. Prints where to work and how to validate it."""
    dag = f.dag()
    node = f.node(dag, node_id)
    ready = {n["id"] for n in dag_module().classify(dag)["ready"]}
    if node["status"] == "in_progress":
        raise FactoryError(f"{node_id} is already in progress")
    if node_id not in ready:
        raise FactoryError(
            f"{node_id} is not ready (status {node['status']}); `factory next` lists the frontier"
        )
    node["status"] = "in_progress"
    node["started_on"] = time.strftime("%Y-%m-%d")
    f.save_dag(dag)
    lines = [f"{node_id} → in_progress: {node['title']}"]
    repos = f.repos()
    entry = repos.get(node["repo"], {})
    if entry and not entry.get("virtual"):
        path = f.repo_dir(node["repo"])
        lines.append(
            f"repo: {path} (default branch {entry.get('default_branch', '?')})"
        )
        for cmd in entry.get("validate", []):
            lines.append(f"validate: {cmd}")
    else:
        lines.append(f"repo: {node['repo']} (no checkout; operator work)")
    lines.append(_claim(f, node["repo"], node_id, agent))
    return "\n".join(lines)


def done(f: Factory, node_id: str, evidence: str) -> str:
    """in_progress → done, with evidence. Prints what it unblocks."""
    if not evidence.strip():
        raise FactoryError("--evidence is required: what proves this node is done?")
    dag = f.dag()
    node = f.node(dag, node_id)
    if node["status"] != "in_progress":
        raise FactoryError(
            f"{node_id} is {node['status']}, not in_progress; `factory start` it first"
        )
    before = {n["id"] for n in dag_module().classify(dag)["ready"]}
    node["status"] = "done"
    node["done_on"] = time.strftime("%Y-%m-%d")
    node["evidence"] = evidence.strip()
    f.save_dag(dag)
    after = {n["id"] for n in dag_module().classify(dag)["ready"]}
    unblocked = sorted(after - before)
    out = f"{node_id} → done"
    if unblocked:
        out += "; now ready: " + ", ".join(unblocked)
    return out


def validate(f: Factory, repo: str) -> int:
    """Run the repo's validate commands in order; stop at the first failure."""
    entry = f.repo(repo)
    if entry.get("virtual"):
        raise FactoryError(f"{repo} has no checkout to validate")
    path = f.repo_dir(repo)
    if not path.is_dir():
        raise FactoryError(f"{repo} is not checked out at {path}")
    cmds = entry.get("validate", [])
    if not cmds:
        print(
            f"{repo}: no validate commands registered ({entry.get('notes', 'no note')})"
        )
        return 0
    for cmd in cmds:
        print(f"[{repo}] $ {cmd}", flush=True)
        rc = run_cmd(cmd, path, env=f.env)
        if rc != 0:
            print(f"[{repo}] FAILED ({rc}): {cmd}")
            return rc
    print(
        f"[{repo}] validate gate passed ({len(cmds)} command{'s' if len(cmds) != 1 else ''})"
    )
    return 0


def status(f: Factory) -> str:
    rows = []
    for name, entry in sorted(f.repos().items()):
        if entry.get("virtual"):
            continue
        path = f.repo_dir(name)
        if not path.is_dir():
            rows.append([name, entry.get("role", "?"), "missing", "", ""])
            continue
        dirty = git_dirty(path)
        rows.append(
            [
                name,
                entry.get("role", "?"),
                git_head(path) or "?",
                git_branch(path) or "?",
                "dirty" if dirty else ("clean" if dirty is False else "?"),
            ]
        )
    groups = f.groups()
    tally = ", ".join(f"{k} {len(v)}" for k, v in groups.items())
    return table(rows, ["repo", "role", "head", "branch", "tree"]) + f"\nDAG: {tally}"


def _claim(f: Factory, repo: str, area: str, agent: str) -> str:
    """Best-effort jarvis.claim over the JSON API. Never blocks a start."""
    base = (f.env.get("JARVIS_URL") or "").strip().rstrip("/")
    if not base:
        return "jarvis: JARVIS_URL unset, no claim recorded"
    for suffix in ("/mcp", "/sse"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    if not base.startswith(("http://", "https://")):
        return f"jarvis: JARVIS_URL must be http(s), got {base!r}; no claim recorded"
    body = json.dumps({"repo": repo, "area": area, "note": "factory start"}).encode()
    # S310: scheme is checked to be http(s) two lines up; the host is the operator's own daemon.
    req = urllib.request.Request(f"{base}/api/claims", data=body, method="POST")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Agent-Id", agent)
    bearer = f.env.get("JARVIS_BEARER")
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            resp.read()
        return f"jarvis: claimed {repo}/{area} as {agent}"
    except urllib.error.HTTPError as e:
        return f"jarvis: claim refused ({e.code}); check `jarvis.claims`"
    except Exception as e:
        return f"jarvis: unreachable ({type(e).__name__}); no claim recorded"
