"""
CLI for personal-graphify
Solo personal project, no connection to employer, built with public/free-tier only
"""
import argparse
import sys
from pathlib import Path
import json

from .detect import collect_files, group_by_type
from .extract import extract_all
from .build import build_graph, enrich_graph
from .cluster import assign_communities, community_summary
from .analyze import god_nodes, surprise_edges, token_stats
from .report import generate_report
from .export import export_json, export_html
from .query import load_graph_json, format_query_answer, format_path_answer, explain_node, shortest_path

def cmd_build(args):
    root = Path(args.path or ".").resolve()
    out_dir = Path(args.out or root / "graphify-out")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[personal-graphify] scanning {root}")
    files = collect_files(root, max_files=args.max_files)
    print(f"[personal-graphify] {len(files)} files found")
    groups = group_by_type(files)
    print(f"[personal-graphify] code {len(groups['code'])} docs {len(groups['docs'])} media {len(groups['media'])}")

    nodes, edges = extract_all(files)
    print(f"[personal-graphify] extracted {len(nodes)} nodes, {len(edges)} edges")

    G = build_graph(nodes, edges)
    G = enrich_graph(G)
    G = assign_communities(G)
    comms = community_summary(G)

    gods = god_nodes(G, top_n=15)
    surprises = surprise_edges(G, top_n=20)
    stats = token_stats(G, len(files))

    # export
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
    # cost stub
    (out_dir / "cost.json").write_text(json.dumps({"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "llm_credits": 0, "mode": "ollama-first local"}))

def cmd_query(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    if not gpath.exists():
        # try find recursively
        candidates = list(Path(".").rglob("graph.json"))
        if candidates:
            gpath = candidates[0]
        else:
            print(f"graph.json not found at {gpath}. Run build first.")
            sys.exit(1)
    from .query import load_graph_json
    G = load_graph_json(gpath)
    if args.question:
        ans = format_query_answer(G, args.question)
        print(ans)
    else:
        print("Provide --question")

def cmd_path(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    ans = format_path_answer(G, args.source, args.target)
    print(ans)

def cmd_explain(args):
    gpath = Path(args.graph or "graphify-out/graph.json")
    G = load_graph_json(gpath)
    info = explain_node(G, args.node)
    if not info:
        print(f"Node '{args.node}' not found")
        sys.exit(1)
    print(f"Node: {info['node'].get('label')} | type {info['node'].get('type')} | file {info['node'].get('file')} | degree {info['degree']}")
    for nb in info['neighbors'][:30]:
        arrow = "-->" if nb['direction']=="out" else "<--"
        print(f"  {arrow} {nb['label']} [{nb['type']}] [{nb['confidence']}]")

def cmd_install(args):
    # install cursor + agents skills
    root = Path(args.path or ".").resolve()
    # cursor
    cursor_rules_dir = root / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)
    # copy template
    template = (Path(__file__).parent.parent.parent / ".cursor" / "rules" / "graphify.mdc").read_text() if (Path(__file__).parent.parent.parent / ".cursor" / "rules" / "graphify.mdc").exists() else None
    # Fallback: create from src
    src_rule = Path(__file__).parent / "templates" / "graphify.mdc"
    if src_rule.exists():
        content = src_rule.read_text()
    else:
        content = """---
description: Personal Graphify — always query graph first
globs: ["**/*"]
alwaysApply: true
---

# Personal Graphify Rule (auto-installed)

You have a queryable knowledge graph at `graphify-out/graph.json` built by personal-graphify (solo personal project, no connection to employer).

**ALWAYS before answering architecture, cross-file, or "where is X" questions:**

1. Run: `pgraphify query "<your question>"` or `personal-graphify query "<q>"`
2. Use `graph.json` subgraph instead of grepping all files — 71.5x token reduction pattern
3. For connections: `pgraphify path "A" "B"`
4. For concept deep-dive: `pgraphify explain "Concept"`

**God nodes to check first:** read `graphify-out/GRAPH_REPORT.md` for top connected concepts.

**Never raw-grep before querying graph.** Graph has EXTRACTED (explicit) vs INFERRED vs AMBIGUOUS edges.

**Personal ecosystem:** Family Brain, Passive Lab Turnover Shield ($79-149/mo), Ava AGI Factory S1 hl8 S2 hl300 Critic hl30 Planner hl150, Vector MTNN 12,966 seasons.

**Install:** `pgraphify .` to rebuild.

Solo personal project, no connection to employer, built with public/free-tier only.
"""
    dest = cursor_rules_dir / "graphify.mdc"
    dest.write_text(content)
    print(f"Wrote {dest}")

    # agents skill
    agents_dir = root / ".agents" / "skills" / "graphify"
    agents_dir.mkdir(parents=True, exist_ok=True)
    skill_content = f"""---
name: graphify-personal
description: Personal Graphify skill — query graph before grep
---

# Graphify Personal Skill

This project has Personal Graphify enabled (solo, Ollama-first).

Commands:
- `/graphify .` — build graph
- `pgraphify query "<question>"` — scoped subgraph (~1.7k tokens vs ~123k naive)
- `pgraphify path "A" "B"` — shortest path
- `pgraphify explain "Concept"` — explain node

Outputs in `graphify-out/`:
- `graph.html` interactive
- `GRAPH_REPORT.md` god nodes, surprises
- `graph.json` queryable — commit this

Rules:
- Always query graph first for architecture questions
- Prefer EXTRACTED edges over INFERRED
- Check god nodes for central concepts
- Use cross-file surprise edges to find coupling

Solo personal project, no connection to employer, built with public/free-tier only.
"""
    (agents_dir / "SKILL.md").write_text(skill_content)
    print(f"Wrote {agents_dir / 'SKILL.md'}")
    print("Installed Cursor + Agents skills. Commit .cursor/rules/graphify.mdc and .agents/skills/graphify/ to git.")

def main():
    # Pre-handle shorthand `pgraphify .` before argparse tries to parse subcommand
    KNOWN_CMDS = {"build","query","path","explain","install","serve","help"}
    if len(sys.argv) >= 2:
        first = sys.argv[1]
        if first not in KNOWN_CMDS and not first.startswith("-"):
            # treat as build path -> inject "build" subcommand
            sys.argv.insert(1, "build")

    parser = argparse.ArgumentParser(prog="personal-graphify")
    subparsers = parser.add_subparsers(dest="command")

    # build / default
    build_parser = subparsers.add_parser("build", help="Build knowledge graph")
    build_parser.add_argument("path", nargs="?", default=".", help="Project path")
    build_parser.add_argument("--out", default=None, help="Output dir")
    build_parser.add_argument("--max-files", type=int, default=8000)

    query_parser = subparsers.add_parser("query", help="Query graph")
    query_parser.add_argument("question", nargs="?", help="Question")
    query_parser.add_argument("--graph", default="graphify-out/graph.json")
    query_parser.add_argument("--question", dest="question_flag", default=None)

    path_parser = subparsers.add_parser("path", help="Shortest path between concepts")
    path_parser.add_argument("source", help="Source concept")
    path_parser.add_argument("target", help="Target concept")
    path_parser.add_argument("--graph", default="graphify-out/graph.json")

    explain_parser = subparsers.add_parser("explain", help="Explain concept")
    explain_parser.add_argument("node", help="Concept name")
    explain_parser.add_argument("--graph", default="graphify-out/graph.json")

    install_parser = subparsers.add_parser("install", help="Install skills")
    install_parser.add_argument("--platform", default="all", help="cursor|agents|all")
    install_parser.add_argument("--project", action="store_true")
    install_parser.add_argument("path", nargs="?", default=".", help="Project path")

    serve_parser = subparsers.add_parser("serve", help="MCP serve (delegates to upstream if installed)")

    args, unknown = parser.parse_known_args()

    if args.command is None:
        if len(sys.argv) >=2 and sys.argv[1] in ("-h","--help"):
            parser.print_help()
            sys.exit(0)
        else:
            # default build .
            args.command = "build"
            args.path = "."
            args.out = None
            args.max_files = 8000

    # normalize query question dual position
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
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "serve":
        from .serve import main as serve_main
        serve_main()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
