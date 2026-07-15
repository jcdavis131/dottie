---
name: graphify-core
description: Core Graphify skill — build/query/path/explain for any codebase
triggers:
- /graphify
- graphify query
- graphify path
- graphify explain
- where is X
- how does * connect to *
- architecture
version: 1.0.0
dependencies:
- networkx
- tree-sitter
provider: ollama
---

# Graphify Core — Knowledge Graph Skill

Solo personal project, no connection to employer, built with public/free-tier only. Based on Graphify-Labs/graphify (MIT).

## What it does
- Parses code (.py, .js, .go, .java, etc 36 grammars) with Tree-sitter locally — 0 LLM cost, nothing leaves machine
- Docs, PDFs, images via Ollama (qwen3:32b default) — semantic nodes
- Builds NetworkX graph → Leiden/greedy communities → god nodes & surprises
- Exports `graph.html`, `graph.json`, `GRAPH_REPORT.md` into `graphify-out/`
- 71.5x token reduction: `graphify query` ~1.7k vs ~123k naive (Karpathy corpus), god nodes show central concepts

## Install
```bash
uv tool install graphifyy
graphify install --platform cursor --project
# personal edition:
pip install -e ./personal-graphify
pgraphify install --platform cursor --project
```

## Commands
```
/graphify .                        # build
/graphify ./src --update           # incremental
/graphify query "what connects auth to DB?"
/graphify path "UserService" "DatabasePool"
/graphify explain "RateLimiter"
# personal aliases:
pgraphify . ; pgraphify query "X"
```

## Rule
Always query graph before grepping. Check `graphify-out/GRAPH_REPORT.md` for god nodes. Respect EXTRACTED (explicit) vs INFERRED (derived) vs AMBIGUOUS edges.

No telemetry. Security: http/https only, size/time limits, path containment, HTML-escaped labels.

Solo personal project, no connection to employer, built with public/free-tier only.
