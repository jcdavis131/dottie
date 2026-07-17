# Personal Graphify — Knowledge Graphs for AI Coding Assistants

Solo personal project, no connection to employer, built with public/free-tier only.

Personal fork of [Graphify-Labs/graphify](https://github.com/safishamsi/graphify) tailored for Cameron Davis home ecosystem: Davis Family Brain, Life Admin Brain, Passive Lab, Vector Hoops/Pitch/Gridiron (dumbmodel.com), Tennis DINOv3, and Ava AGI Factory v6.4.

The original Graphify is `pip install graphifyy` (MIT, 3.7k stars, 71.5x token reduction). This personal edition keeps the core pipeline — `detect → extract (Tree-sitter AST) → build (NetworkX) → cluster (Leiden/greedy) → analyze (god nodes & surprises) → report → export` — but adds:

- **Local extraction, no LLM required**: Python AST + regex + Markdown heading/frontmatter parsing + personal ecosystem patterns (tree-sitter JS/TS when installed). Ollama is used ONLY for the optional `--semantic` query rerank (local `mxbai-embed-large` embeddings) — extraction itself never calls a model
- **Personal ecosystem extractors**: recognizes `PROJECT.md`, `01_Finance`/`02_Passive_Lab`/`04_Tennis_DINOv3` isolation, Davis Family Brain accounts, Turnover Shield revenue tracker, Vector MTNN heads (48→64→k), Ava multi-j-space (S1 hl=8, S2 hl=300, Critic hl=30, Planner hl=150)
- **Cursor-native skills**: `.cursor/rules/graphify.mdc` with `alwaysApply: true`, `/graphify` slash commands, and query-first hook that nudges agents to run `pgraphify query` before grepping
- **Security (what is actually implemented)**: 5MB per-file scan cap, HTML-escaped node labels in graph.html, path containment on MCP server graph loads, HTTP server binds 127.0.0.1 by default (`--host` to expose deliberately)
- **Free-to-host**: outputs `graphify-out/graph.html`, `graph.json`, `GRAPH_REPORT.md` — commit `graph.json` to git, team pulls and queries instantly (~2k tokens vs ~123k naive like Karpathy corpus example)

## Install (30 seconds)

```bash
# isolated install (recommended)
uv tool install -e ./personal-graphify   # or pipx install -e .
# or pip install -e .
pip install -e .

# register skills with Cursor + all platforms (default --platform all)
pgraphify install
# or:
pgraphify install --platform cursor --project
pgraphify install --platform agents --project

# Optional extras
uv tool install "personal-graphify[ollama]"   # semantic query rerank via local Ollama embeddings
ollama pull mxbai-embed-large                 # the embedding model used by --semantic
# other extras: [serve] HTTP MCP server, [treesitter] JS/TS AST, [spectral] Laplacian clustering
```

## Use in Cursor

In Cursor Chat:

```
/graphify .                          # build graph for current repo
/graphify ./src --update             # incremental: content-hash cache reuses unchanged files
/graphify query "what connects auth to DB?"
/graphify path "UserService" "DatabasePool"
/graphify explain "RateLimiter"
```

Incremental builds (`pgraphify build --update`) keep a content-hash cache at
`graphify-out/cache/extract.json` (path → mtime/md5/nodes/edges). Unchanged files reuse
their cached extraction, changed files are re-extracted, and the graph is always rebuilt
from the full merged pool.

Outputs:

```
graphify-out/
├── graph.html       # interactive viz — click nodes, filter communities
├── GRAPH_REPORT.md  # god nodes, surprises, suggested questions
├── graph.json       # queryable graph (commit this)
└── cache/           # incremental
```

## Personal Graphify vs Upstream

| Capability | Upstream Graphify | Personal Graphify |
|---|---|---|
| AST parsing | Tree-sitter 36 grammars | Same + custom Davis patterns |
| Extraction | Tree-sitter + cloud semantic pass | AST/regex/patterns only, no LLM; optional local Ollama embed rerank at query time |
| Clustering | Leiden (needs extra) | greedy modularity fallback → works without leiden |
| Cursor integration | `.cursor/rules/graphify.mdc` alwaysApply | Same + personal ecosystem prompt + 3 curated skills |
| Personal ecosystem | generic | Family Brain accounts, Turnover Shield MRR, Ava J-space, Vector MTNN |
| Cost | free + optional API | 100% free local (no API calls at all) |

## Cursor Skills Repo Integration

This repo ships 3 skills ready to drop into your Cursor skills repo:

```
skills/
├── graphify-core/SKILL.md          # core build/query/path commands
├── graphify-personal/SKILL.md      # personal ecosystem overlay (Turnover Shield, Ava, Vector)
└── graphify-agentic/SKILL.md       # teaches agents to use graph-first for smarter agentic systems
```

Install script:

```bash
./scripts/install_cursor_skills.sh ~/path/to/cursor-skills-repo
# Copies skills + .cursor/rules/graphify.mdc
```

## Benchmark (measured: self-build of this repo)

`pgraphify . --out graphify-out` on this repository (48 files):

- 784 nodes, 2014 edges, 23 communities
- Example measured query: `pgraphify query "spectral community detection"` → ~686 scoped tokens vs ~83,978 naive (sum of indexed file bytes / 4) = 122.4x reduction on this corpus
- Every query answer and cost.json entry reports its basis string (`measured: ...` vs `estimated: ...`) — the cost dashboard only monetizes measured-basis savings

## Security

What is actually implemented (nothing more claimed):

- 5MB per-file cap when scanning; respects `.gitignore` + `.graphifyignore`
- Node labels HTML-escaped in `graph.html`
- MCP server (`pgraphify serve`): caller-supplied graph paths are containment-checked against the server root; HTTP transport binds `127.0.0.1` by default (`--host` to expose deliberately)
- Public export runs a hard PII gate (`scripts/sanitize_for_public.py` fails the build on leaked paths/emails/accounts)

No telemetry, no network calls. The optional `--semantic` query rerank talks to a local Ollama server only.

## Footer

Solo personal project, no connection to employer, built with public/free-tier only. MIT License — upstream by Safi Shamsi.

---
