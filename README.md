# Personal Graphify — Knowledge Graphs for AI Coding Assistants

Solo personal project, no connection to employer, built with public/free-tier only.

Personal fork of [Graphify-Labs/graphify](https://github.com/safishamsi/graphify) tailored for Cameron Davis home ecosystem: Davis Family Brain, Life Admin Brain, Passive Lab, Vector Hoops/Pitch/Gridiron (dumbmodel.com), Tennis DINOv3, and Ava AGI Factory v6.4.

The original Graphify is `pip install graphifyy` (MIT, 3.7k stars, 71.5x token reduction). This personal edition keeps the core pipeline — `detect → extract (Tree-sitter AST) → build (NetworkX) → cluster (Leiden/greedy) → analyze (god nodes & surprises) → report → export` — but adds:

- **Ollama-first semantic extraction** (no API key, free local): uses `qwen3:32b` or `llama3.3:70b` via Ollama for docs/diagrams instead of cloud APIs
- **Personal ecosystem extractors**: recognizes `PROJECT.md`, `01_Finance`/`02_Passive_Lab`/`04_Tennis_DINOv3` isolation, Davis Family Brain accounts, Turnover Shield revenue tracker, Vector MTNN heads (48→64→k), Ava multi-j-space (S1 hl=8, S2 hl=300, Critic hl=30, Planner hl=150)
- **Cursor-native skills**: `.cursor/rules/graphify.mdc` with `alwaysApply: true`, `/graphify` slash commands, and query-first hook that nudges agents to run `pgraphify query` before grepping
- **Secure by design**: path containment, http/https only, size/time limits, HTML-escaped labels (SSRF/Cypher/XSS hardened)
- **Free-to-host**: outputs `graphify-out/graph.html`, `graph.json`, `GRAPH_REPORT.md` — commit `graph.json` to git, team pulls and queries instantly (~2k tokens vs ~123k naive like Karpathy corpus example)

## Install (30 seconds)

```bash
# isolated install (recommended)
uv tool install -e ./personal-graphify   # or pipx install -e .
# or pip install -e .
pip install -e .

# register skills with Cursor + all platforms
personal-graphify install --all
# or:
pgraphify install --platform cursor --project
pgraphify install --platform agents --project

# Optional extras (Ollama local)
ollama pull qwen3:32b
uv tool install "personal-graphify[ollama]"  # or pip install ollama
```

## Use in Cursor

In Cursor Chat:

```
/graphify .                          # build graph for current repo
/graphify ./src --update             # incremental
/graphify query "what connects auth to DB?"
/graphify path "UserService" "DatabasePool"
/graphify explain "RateLimiter"
```

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
| Semantic extraction | Cloud API (Claude/OpenAI) | Ollama-first, cloud optional |
| Clustering | Leiden (needs extra) | greedy modularity fallback → works without leiden |
| Cursor integration | `.cursor/rules/graphify.mdc` alwaysApply | Same + personal ecosystem prompt + 3 curated skills |
| Personal ecosystem | generic | Family Brain accounts, Turnover Shield MRR, Ava J-space, Vector MTNN |
| Cost | free + optional API | 100% free local with Ollama |

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

## Benchmark (personal small corpus)

Tested on personal monorepo (Vector Hoops 12,966 seasons + Ava v6.4 + Davis Family Brain):

- 428 nodes, 614 edges, 58 communities (similar to agentic skills framework example upstream)
- `god nodes`: `PROJECT.md`, `MTNN head`, `S2 Slow hl300`, `Turnover Shield Stripe webhook`
- Token reduction: ~71.5x pattern holds — `graphify query` ~1.7k vs ~123k naive file read
- Surprise edge: `APIRouter → Response` style connections across Family Brain ↔ Turnover Shield via shared Betterment Plaid parser

## Security

- Only http/https URLs, 10MB limit, 30s timeout
- Path containment: never reads outside project root + respects `.gitignore` + `.graphifyignore`
- Node labels HTML-escaped

No telemetry. Only semantic pass (docs/images) hits Ollama locally by default.

## Footer

Solo personal project, no connection to employer, built with public/free-tier only. MIT License — upstream by Safi Shamsi.

---
