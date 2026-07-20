"""
CLI for personal-graphify
Solo personal project, no connection to employer, built with public/free-tier only
"""
import argparse
import sys
import os
import stat
from pathlib import Path
import json

from .detect import collect_files, group_by_type
from .extract import extract_with_cache
from .build import build_graph, enrich_graph
from .cluster import assign_communities, community_summary
from .analyze import god_nodes, surprise_edges, token_stats
from .report import generate_report
from .export import export_json, export_html
from .query import (
    load_graph_json,
    format_query_answer,
    format_path_answer,
    explain_node,
    shortest_path,
    impact_analysis,
    format_impact_answer,
    task_compiler,
    format_task_answer,
    onboard_report,
    format_onboard_answer,
    format_cost_dashboard,
    _cost_path_for_graph
)

def _resolve_build_roots(args) -> list[Path]:
    """Primary path plus optional --roots (comma-separated or repeated)."""
    roots: list[Path] = []
    primary = Path(args.path or ".").resolve()
    roots.append(primary)
    extra = getattr(args, "roots", None) or []
    if isinstance(extra, str):
        extra = [extra]
    for item in extra:
        for part in str(item).split(","):
            part = part.strip()
            if not part:
                continue
            p = Path(part).expanduser().resolve()
            if p.exists() and p not in roots:
                roots.append(p)
            elif not p.exists():
                print(f"[personal-graphify] skip missing root: {p}")
    return roots


def cmd_build(args):
    roots = _resolve_build_roots(args)
    primary = roots[0]
    out_dir = Path(args.out or primary / "graphify-out")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Budget files across roots so large labs (vector-hoops) don't starve Ava/Scout
    max_files = args.max_files
    per_root = max(200, max_files // max(1, len(roots)))
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        print(f"[personal-graphify] scanning {root} (cap {per_root})")
        batch = collect_files(root, max_files=per_root)
        for f in batch:
            if f not in seen:
                seen.add(f)
                files.append(f)
        if len(files) >= max_files:
            files = files[:max_files]
            break
    print(f"[personal-graphify] {len(files)} files found across {len(roots)} roots")
    groups = group_by_type(files)
    print(f"[personal-graphify] code {len(groups['code'])} docs {len(groups['docs'])} media {len(groups['media'])}")

    update = getattr(args, "update", False)
    cache_path = out_dir / "cache" / "extract.json"
    nodes, edges, cache_stats = extract_with_cache(files, cache_path, update=update)
    if update:
        print(f"[personal-graphify] incremental: {cache_stats['reused']} files reused from cache, "
              f"{cache_stats['re_extracted']} re-extracted")
    print(f"[personal-graphify] extracted {len(nodes)} nodes, {len(edges)} edges")

    G = build_graph(nodes, edges)
    G = enrich_graph(G)
    G = assign_communities(G, method=getattr(args, "cluster", "auto"))
    comms = community_summary(G)

    gods = god_nodes(G, top_n=15)
    surprises = surprise_edges(G, top_n=20)
    stats = token_stats(G, len(files))

    json_path = out_dir / "graph.json"
    html_path = out_dir / "graph.html"
    report_path = out_dir / "GRAPH_REPORT.md"

    export_json(G, json_path)
    export_html(G, html_path)
    generate_report(G, report_path, gods, surprises, comms, stats)

    print(f"[personal-graphify] wrote {report_path}")
    print(f"[personal-graphify] wrote {json_path}")
    print(f"[personal-graphify] wrote {html_path}")
    print(f"  {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(comms)} communities")

    # cost.json — preserve existing queries if present
    cost_path = out_dir / "cost.json"
    if cost_path.exists():
        try:
            existing = json.loads(cost_path.read_text(encoding="utf-8"))
            existing["nodes"] = G.number_of_nodes()
            existing["edges"] = G.number_of_edges()
            cost_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except Exception:
            cost_path.write_text(json.dumps({"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "queries": [], "total_saved_tokens": 0, "mode": "ollama-first local"}, indent=2), encoding="utf-8")
    else:
        cost_path.write_text(json.dumps({"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "queries": [], "total_saved_tokens": 0, "total_naive": 0, "total_scoped": 0, "mode": "ollama-first local"}, indent=2), encoding="utf-8")

    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "cache": cache_stats}

def cmd_query(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    if not gpath.exists():
        candidates = list(Path(".").rglob("graph.json"))
        if candidates:
            gpath = candidates[0]
        else:
            print(f"graph.json not found at {gpath}. Run build first.")
            sys.exit(1)
    G = load_graph_json(gpath)
    if not args.question:
        print("Provide question: pgraphify query \"your question\"")
        sys.exit(1)
    semantic = getattr(args, 'semantic', False)
    embed_model = getattr(args, 'embed_model', 'mxbai-embed-large')
    ans = format_query_answer(G, args.question, graph_path=gpath, semantic=semantic, embed_model=embed_model)
    print(ans)
    if getattr(args, 'json', False):
        from .query import search_nodes, subgraph_for_query
        matches = search_nodes(G, args.question, limit=12, semantic=semantic, embed_model=embed_model)
        print("\n---JSON---")
        print(json.dumps({"matches": matches[:12]}, indent=2)[:8000])

def cmd_path(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    semantic = getattr(args, 'semantic', False)
    ans = format_path_answer(G, args.source, args.target, semantic=semantic)
    print(ans)

def cmd_explain(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    semantic = getattr(args, 'semantic', False)
    info = explain_node(G, args.node, include_code_snippet=args.snippet, semantic=semantic, graph_path=gpath)
    if not info:
        print(f"Node '{args.node}' not found")
        sys.exit(1)
    print(f"Node: {info['node'].get('label')} | type {info['node'].get('type')} | file {info['node'].get('file')} | degree {info['degree']} | community {info['community']}")
    if info.get("snippet"):
        print("\n--- Code snippet ---")
        print(info["snippet"][:1200])
        print("--- end snippet ---\n")
    print("\nOutgoing (what this uses):")
    for nb in info['neighbors_out'][:20]:
        print(f"  --> {nb['label']} [{nb['edge_type']}] [{nb['confidence']}] in {nb['file']}")
    print("\nIncoming (what uses this):")
    for nb in info['neighbors_in'][:20]:
        print(f"  <-- {nb['label']} [{nb['edge_type']}] [{nb['confidence']}] in {nb['file']}")

def cmd_impact(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    semantic = getattr(args, 'semantic', False)
    result = impact_analysis(G, args.node, direction=args.direction, depth=args.depth, semantic=semantic)
    print(format_impact_answer(result))
    if args.json:
        print("\n---JSON---")
        print(json.dumps(result, indent=2)[:8000])

def cmd_task(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    task_text = args.task or " ".join(args.task_words or [])
    if not task_text:
        print("Provide task: pgraphify task \"add retention playbook...\"")
        sys.exit(1)
    semantic = getattr(args, 'semantic', False)
    result = task_compiler(G, task_text, semantic=semantic)
    print(format_task_answer(result))
    if args.json:
        print("\n---JSON---")
        print(json.dumps(result, indent=2)[:8000])

def cmd_onboard(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    report = onboard_report(G, top_n_god=args.top)
    print(format_onboard_answer(report))
    if args.json:
        print("\n---JSON---")
        print(json.dumps(report, indent=2)[:10000])

def cmd_cost(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    cost_path = _cost_path_for_graph(gpath)
    if not cost_path.exists():
        # try find cost.json anywhere
        cands = list(Path(".").rglob("cost.json"))
        if cands:
            cost_path = cands[0]
        else:
            print(f"cost.json not found. Run pgraphify build and then some queries first. Looked for {cost_path}")
            sys.exit(1)
    print(format_cost_dashboard(cost_path))
    if args.json:
        print("\n---RAW JSON---")
        try:
            print(Path(cost_path).read_text(encoding="utf-8")[:12000])
        except:
            pass

def cmd_hook(args):
    action = args.action  # install/uninstall/status
    root = Path(args.path or ".").resolve()

    git_dir = root / ".git"
    if not git_dir.exists():
        # try find git root upward
        cur = root
        for _ in range(5):
            if (cur / ".git").exists():
                git_dir = cur / ".git"
                root = cur
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        if not git_dir.exists():
            print(f"Not a git repo: {root} — no .git found")
            sys.exit(1)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    post_commit_path = hooks_dir / "post-commit"
    post_merge_path = hooks_dir / "post-merge"
    gitattributes_path = root / ".gitattributes"

    if action == "status":
        print(f"[graphify hook] repo: {root}")
        print(f"  post-commit exists: {post_commit_path.exists()}")
        if post_commit_path.exists():
            print(f"    -> {post_commit_path.read_text(encoding="utf-8")[:300]}...")
        print(f"  post-merge exists: {post_merge_path.exists()}")
        print(f"  .gitattributes graph.json union: ", end="")
        if gitattributes_path.exists():
            content = gitattributes_path.read_text(encoding="utf-8")
            has_graph = "graph.json" in content and "merge=union" in content
            print(f"{has_graph} — {content[:200]}")
        else:
            print("no .gitattributes")
        # check git config
        import subprocess
        try:
            out = subprocess.check_output(["git","config","--get","merge.union.driver"], cwd=root, stderr=subprocess.STDOUT, text=True)
            print(f"  git config merge.union.driver: {out.strip()}")
        except:
            print(f"  git config merge.union.driver: not set (union is built-in, may still work)")
        return

    if action == "install":
        # Install post-commit hook: auto rebuild if graphify-out exists
        hook_script = """#!/bin/sh
# Personal Graphify — auto-rebuild hook (solo, Ollama-first)
# Installed by pgraphify hook install — safe, local-only, free-tier
# Rebuilds graph after commit/merge if graphify-out/ exists, in background
# Solo personal project, no connection to employer, built with public/free-tier only

if [ -f "graphify-out/graph.json" ] || [ -d "graphify-out" ]; then
  # Only rebuild if pgraphify available
  if command -v pgraphify >/dev/null 2>&1; then
    echo "[graphify] auto-rebuild in background..."
    (pgraphify build --out graphify-out >/tmp/graphify-hook.log 2>&1 &)
  elif command -v personal-graphify >/dev/null 2>&1; then
    echo "[graphify] auto-rebuild in background..."
    (personal-graphify build --out graphify-out >/tmp/graphify-hook.log 2>&1 &)
  fi
fi
"""
        for hook_path in [post_commit_path, post_merge_path]:
            # If file exists and doesn't contain graphify marker, append? Safer to check
            if hook_path.exists():
                existing = hook_path.read_text(encoding="utf-8")
                if "Personal Graphify" in existing or "graphify" in existing.lower():
                    # overwrite with ours + keep marker
                    hook_path.write_text(hook_script, encoding="utf-8")
                    print(f"[graphify] updated existing {hook_path}")
                else:
                    # append our hook after existing (chain)
                    combined = existing.rstrip() + "\n\n# --- Personal Graphify (appended) ---\n" + hook_script + "\n"
                    hook_path.write_text(combined, encoding="utf-8")
                    print(f"[graphify] appended to existing {hook_path} (preserved original)")
            else:
                hook_path.write_text(hook_script, encoding="utf-8")
                print(f"[graphify] wrote {hook_path}")

            # make executable
            hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # .gitattributes for union merge driver for graph.json
        union_line = "graphify-out/graph.json merge=union\n**/graph.json merge=union\n# Personal Graphify — keep graph.json merge friendly (Ollama-first local)\n"
        if gitattributes_path.exists():
            existing = gitattributes_path.read_text(encoding="utf-8")
            if "graphify-out/graph.json" not in existing or "merge=union" not in existing:
                # append if not present
                with open(gitattributes_path, "a", encoding="utf-8") as f:
                    f.write("\n" + union_line)
                print(f"[graphify] appended union merge to {gitattributes_path}")
            else:
                print(f"[graphify] .gitattributes already has union merge")
        else:
            gitattributes_path.write_text(union_line, encoding="utf-8")
            print(f"[graphify] wrote {gitattributes_path} with union merge for graph.json")

        print("\n[graphify] hook install complete:")
        print("  - post-commit → auto-rebuild graphify-out/ in background after each commit")
        print("  - post-merge  → auto-rebuild after pull/merge")
        print("  - .gitattributes → graph.json merge=union (reduces conflicts)")
        print("  Tip: first run `ollama pull mxbai-embed-large` for semantic rerank (optional)")
        print("  Test: pgraphify query \"Turnover Shield\" --semantic")
        return

    if action == "uninstall":
        APPEND_MARKER = "# --- Personal Graphify (appended) ---"
        removed = 0
        for hook_path in [post_commit_path, post_merge_path]:
            if not hook_path.exists():
                continue
            content = hook_path.read_text(encoding="utf-8")
            if APPEND_MARKER in content:
                # We appended to a pre-existing hook: keep everything before our marker.
                prefix = content.split(APPEND_MARKER, 1)[0].rstrip() + "\n"
                hook_path.write_text(prefix, encoding="utf-8")
                print(f"[graphify] removed appended graphify section from {hook_path}")
                removed += 1
            elif "Personal Graphify" in content:
                # File is entirely our hook script: delete it.
                hook_path.unlink()
                print(f"[graphify] removed {hook_path}")
                removed += 1
            else:
                print(f"[graphify] {hook_path} exists but no graphify marker — left untouched")

        # Optionally clean .gitattributes
        if gitattributes_path.exists():
            txt = gitattributes_path.read_text(encoding="utf-8")
            if "Personal Graphify" in txt or "graphify-out/graph.json" in txt:
                print(f"[graphify] .gitattributes contains graphify lines — remove manually if desired: {gitattributes_path}")
        print(f"[graphify] uninstall done ({removed} hooks removed)")
        return

def _live_graph_stats(root: Path) -> str:
    """Live node/edge counts from graphify-out/graph.json at install time.

    Returns a phrase like ", 464 nodes 1074 edges (live at install)" or "" when no
    graph exists — the rule text must never carry stale hardcoded numbers.
    """
    gpath = root / "graphify-out" / "graph.json"
    try:
        meta = json.loads(gpath.read_text(encoding="utf-8")).get("meta", {})
        n, e = meta.get("nodes"), meta.get("edges")
        if n and e:
            return f", {n} nodes {e} edges (live at install)"
    except Exception:
        pass
    return ""


_FALLBACK_RULE = """---
description: Personal Graphify — always query graph first
globs: ["**/*"]
alwaysApply: true
---

# Personal Graphify Rule (auto-installed)

You have a queryable knowledge graph at `graphify-out/graph.json` built by personal-graphify (solo personal project, no connection to employer{{GRAPH_STATS}}).

**ALWAYS before answering architecture, cross-file, or "where is X" questions:**

1. Run: `pgraphify query "<your question>"` or `personal-graphify query "<q>"`
2. Use `graph.json` subgraph instead of grepping all files — each answer reports its measured token estimate
3. For connections: `pgraphify path "A" "B"`
4. For concept deep-dive: `pgraphify explain "Concept"`
5. For impact: `pgraphify impact "<node>" --direction both`
6. For tasks: `pgraphify task "add retention playbook..."`

**God nodes to check first:** read `graphify-out/GRAPH_REPORT.md` for top connected concepts.
**Semantic (optional):** `pgraphify query "X" --semantic` uses Ollama mxbai-embed-large local rerank
**Hooks:** `pgraphify hook install` auto-rebuild on commit + union merge for graph.json
**Cost:** `pgraphify cost` shows tokens saved

**Never raw-grep before querying graph.** Graph has EXTRACTED (explicit) vs INFERRED vs AMBIGUOUS edges.

**Personal ecosystem:** Family Brain, Passive Lab Turnover Shield ($79-149/mo), Ava AGI Factory S1 hl8 S2 hl300 Critic hl30 Planner hl150, Vector MTNN 12,966 seasons.

Solo personal project, no connection to employer, built with public/free-tier only.
"""

_AGENTS_SKILL = """---
name: graphify-personal
description: Personal Graphify skill — query graph before grep (SOTA: semantic + hooks + cost)
---

# Graphify Personal Skill — SOTA

This project has Personal Graphify enabled (solo, Ollama-first, semantic rerank optional{{GRAPH_STATS}}).

Commands:
- `pgraphify .` — build graph
- `pgraphify query "<question>" --semantic` — scoped subgraph (measured token estimate in every answer) + optional mxbai-embed-large rerank
- `pgraphify path "A" "B"` — shortest path
- `pgraphify explain "Concept"` — explain node
- `pgraphify impact "Node" --direction both|upstream|downstream`
- `pgraphify task "add retention playbook to Turnover Shield"`
- `pgraphify onboard` — god nodes, hot files, entry points
- `pgraphify hook install` — auto-rebuild + union merge for graph.json
- `pgraphify cost` — token savings dashboard

Outputs in `graphify-out/`:
- `graph.html` interactive
- `GRAPH_REPORT.md` god nodes, surprises
- `graph.json` queryable — commit this
- `cost.json` queries + savings log

Rules:
- Always query graph first for architecture questions
- Prefer EXTRACTED edges over INFERRED
- Use --semantic for ambiguous queries (Ollama local, free)
- Check god nodes for central concepts

Solo personal project, no connection to employer, built with public/free-tier only.
"""


def cmd_install(args):
    root = Path(args.path or ".").resolve()
    if getattr(args, "project", False):
        # --project: install at the enclosing git project root, not the literal path
        cur = root
        for _ in range(8):
            if (cur / ".git").exists():
                root = cur
                break
            if cur.parent == cur:
                break
            cur = cur.parent

    platform = getattr(args, "platform", "all")
    if platform not in ("cursor", "agents", "all"):
        print(f"Unknown --platform '{platform}' (expected cursor|agents|all)")
        sys.exit(1)

    stats = _live_graph_stats(root)
    written = []

    if platform in ("cursor", "all"):
        cursor_rules_dir = root / ".cursor" / "rules"
        cursor_rules_dir.mkdir(parents=True, exist_ok=True)
        src_rule = Path(__file__).parent / "templates" / "graphify.mdc"
        content = src_rule.read_text(encoding="utf-8") if src_rule.exists() else _FALLBACK_RULE
        content = content.replace("{{GRAPH_STATS}}", stats)
        dest = cursor_rules_dir / "graphify.mdc"
        dest.write_text(content, encoding="utf-8")
        written.append(dest)
        print(f"Wrote {dest}")

    if platform in ("agents", "all"):
        agents_dir = root / ".agents" / "skills" / "graphify"
        agents_dir.mkdir(parents=True, exist_ok=True)
        skill_dest = agents_dir / "SKILL.md"
        skill_dest.write_text(_AGENTS_SKILL.replace("{{GRAPH_STATS}}", stats), encoding="utf-8")
        written.append(skill_dest)
        print(f"Wrote {skill_dest}")

    print(f"Installed {platform} skill(s) at {root}. Commit the written files to git: "
          + ", ".join(str(p.relative_to(root)) for p in written))

def main():
    KNOWN_CMDS = {"build","query","path","explain","impact","task","onboard","install","serve","hook","cost","help"}
    if len(sys.argv) >= 2:
        first = sys.argv[1]
        if first not in KNOWN_CMDS and not first.startswith("-"):
            sys.argv.insert(1, "build")

    parser = argparse.ArgumentParser(prog="personal-graphify")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build", help="Build knowledge graph")
    build_parser.add_argument("path", nargs="?", default=".", help="Primary project path")
    build_parser.add_argument("--roots", action="append", default=[], help="Extra roots (repeat or comma-separated) for multi-repo corpus")
    build_parser.add_argument("--out", default=None, help="Output dir")
    build_parser.add_argument("--max-files", type=int, default=8000)
    build_parser.add_argument("--cluster", default="auto", choices=["auto", "spectral", "greedy"],
                              help="Community detection backend (auto = Leiden→greedy fallback chain)")
    build_parser.add_argument("--update", action="store_true",
                              help="Incremental rebuild: reuse cached extractions for unchanged files (content-hash cache in graphify-out/cache/extract.json)")

    query_parser = subparsers.add_parser("query", help="Query graph — scoped subgraph for agent context (SOTA: lexical + semantic rerank)")
    query_parser.add_argument("question", nargs="?", help="Question")
    query_parser.add_argument("--graph", default="graphify-out/graph.json")
    query_parser.add_argument("--question", dest="question_flag", default=None)
    query_parser.add_argument("--semantic", action="store_true", help="Use Ollama mxbai-embed-large semantic rerank over top 60 lexical")
    query_parser.add_argument("--embed-model", default="mxbai-embed-large", help="Ollama embedding model (mxbai-embed-large, nomic-embed-text, etc)")
    query_parser.add_argument("--json", action="store_true")

    path_parser = subparsers.add_parser("path", help="Shortest path between concepts")
    path_parser.add_argument("source", help="Source concept")
    path_parser.add_argument("target", help="Target concept")
    path_parser.add_argument("--graph", default="graphify-out/graph.json")
    path_parser.add_argument("--semantic", action="store_true")

    explain_parser = subparsers.add_parser("explain", help="Explain concept — neighbors, rationale, code snippet")
    explain_parser.add_argument("node", help="Concept name")
    explain_parser.add_argument("--graph", default="graphify-out/graph.json")
    explain_parser.add_argument("--snippet", action="store_true")
    explain_parser.add_argument("--semantic", action="store_true")

    impact_parser = subparsers.add_parser("impact", help="Impact analysis — what breaks if you change this?")
    impact_parser.add_argument("node", help="Node / concept to analyze")
    impact_parser.add_argument("--graph", default="graphify-out/graph.json")
    impact_parser.add_argument("--direction", default="both", choices=["downstream","upstream","both"])
    impact_parser.add_argument("--depth", type=int, default=3)
    impact_parser.add_argument("--semantic", action="store_true")
    impact_parser.add_argument("--json", action="store_true")

    task_parser = subparsers.add_parser("task", help="Task compiler — given task, return minimal files + plan (SOTA)")
    task_parser.add_argument("task", nargs="?", help="Task description")
    task_parser.add_argument("task_words", nargs="*", help="Task description words")
    task_parser.add_argument("--graph", default="graphify-out/graph.json")
    task_parser.add_argument("--semantic", action="store_true", help="Use semantic rerank for task matching")
    task_parser.add_argument("--json", action="store_true")

    onboard_parser = subparsers.add_parser("onboard", help="Onboard new repo — god nodes, hot files, entry points, suggested questions")
    onboard_parser.add_argument("--graph", default="graphify-out/graph.json")
    onboard_parser.add_argument("--top", type=int, default=12)
    onboard_parser.add_argument("--json", action="store_true")

    install_parser = subparsers.add_parser("install", help="Install skills")
    install_parser.add_argument("--platform", default="all", help="cursor|agents|all")
    install_parser.add_argument("--project", action="store_true")
    install_parser.add_argument("path", nargs="?", default=".", help="Project path")

    serve_parser = subparsers.add_parser("serve", help="MCP serve — exposes query/path/explain/impact/task as MCP tools")
    serve_parser.add_argument("--transport", default="http", choices=["http","stdio"])
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind address (default localhost-only; override deliberately to expose)")
    serve_parser.add_argument("--graph", default="graphify-out/graph.json")

    hook_parser = subparsers.add_parser("hook", help="Git hooks — auto-rebuild graph on commit + union merge driver for graph.json")
    hook_parser.add_argument("action", nargs="?", default="install", choices=["install","uninstall","status"], help="install/uninstall/status")
    hook_parser.add_argument("path", nargs="?", default=".", help="Project path (git repo)")

    cost_parser = subparsers.add_parser("cost", help="Show token savings dashboard from cost.json")
    cost_parser.add_argument("--graph", default="graphify-out/graph.json")
    cost_parser.add_argument("--json", action="store_true")

    args, unknown = parser.parse_known_args()

    if args.command is None:
        if len(sys.argv) >=2 and sys.argv[1] in ("-h","--help"):
            parser.print_help()
            sys.exit(0)
        else:
            args.command = "build"
            args.path = "."
            args.out = None
            args.max_files = 8000
            args.roots = []

    if args.command == "query":
        q = getattr(args, "question", None) or getattr(args, "question_flag", None)
        if not q and unknown:
            q = " ".join(unknown)
        args.question = q

    if args.command == "build":
        cmd_build(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "path":
        cmd_path(args)
    elif args.command == "explain":
        cmd_explain(args)
    elif args.command == "impact":
        cmd_impact(args)
    elif args.command == "task":
        if hasattr(args, 'task_words') and args.task_words:
            if not args.task:
                args.task = " ".join(args.task_words)
            else:
                args.task = args.task + " " + " ".join(args.task_words)
        cmd_task(args)
    elif args.command == "onboard":
        cmd_onboard(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "serve":
        from .serve import main as serve_main
        serve_main(args)
    elif args.command == "hook":
        cmd_hook(args)
    elif args.command == "cost":
        cmd_cost(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
