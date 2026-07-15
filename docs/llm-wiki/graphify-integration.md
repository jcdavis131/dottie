# Graphify Integration — LLM Wiki

**Solo personal project, no connection to employer, built with public/free-tier only**

## What is Personal Graphify?
Fork of `graphifyy` (pip install graphifyy, 3.7k stars) — pipeline `detect → extract (Tree-sitter AST) → build (NetworkX) → cluster (Leiden/greedy) → analyze (god nodes & surprises) → report → export`.

Personal edition tailwinds:
- Ollama-first `qwen3:32b` semantic docs/diagrams (no API key)
- Recognizes `PROJECT.md`, `01_Finance/02_Passive_Lab/04_Tennis_DINOv3`, Davis Family Brain, Turnover Shield MRR, Vector MTNN heads, Ava J-space (S1 hl=8, S2 hl=300, Critic hl=30, Planner hl=150)
- Cursor skills `.cursor/rules/graphify.mdc` + `/graphify` slash
- Path containment, http/https only, 10MB/30s limits, HTML-escaped labels (SSRF/XSS hardened)

## Install & Outputs (for reference)
```bash
pip install -e ~/workspace/your_files/personal-graphify  # provides pgraphify
pgraphify build . --out graphify-out          # builds graph
# outputs:
# graphify-out/graph.html — interactive viz
# graphify-out/GRAPH_REPORT.md — god nodes, surprises, suggested Qs
# graphify-out/graph.json — queryable, commit this (~2k tokens vs 123k naive)
# graphify-out/cost.json — token savings
# graphify-out/cache/ — incremental
```

## BigBang CLI + Graphify Wiring (v0.4.1)

### 1. Build Graph Over BigBang CLI
```bash
cd ~/workspace/bigbang-cli
pgraphify build . --out graphify-out --include "bigbang/**/*.py docs/llm-wiki/*.md"
# Expect ~400-600 nodes, edges ~600-900, communities ~50-70 (similar to Vector Hoops 428 nodes)
```

### 2. Query for Tasks Integration
```bash
pgraphify query "how does bb tasks sync-bb work?" --out graphify-out
# Should return subgraph:
# - bigbang/plugins/tasks/cli.py::_run_gws (calls hatch_gws_cli)
# - bigbang/plugins/tasks/cli.py::sync_bb -> bigbang/core/audit.py::tail_events
# - docs/llm-wiki/tasks-plugin.md
# - bigbang/core/output.py::emit (audit log)

pgraphify query "what connects ava router to tasks?" 
# -> ava/cli.py::_heuristic_route detects "task" keyword -> tasks plugin manifest v0.4.0
# -> agent/cli.py builtin_hints["task"] -> ava route -> tasks list

pgraphify path "tasks/cli.py" "audit.py"
# shortest path: tasks/cli.py sync_bb -> core/audit.py tail_events

pgraphify explain "RateLimiter" equivalent: 
pgraphify explain "_run_gws"
```

### 3. Save Tasks Export into Graphify
We already wired:
```bash
bb tasks export --tasklist @default --json
# writes docs/llm-wiki/tasks-@default.json (list of Lina's Morning/Afternoon tasks)
# Next pgraphify build will include this JSON as node, linking tasks plugin to actual user data
```

### 4. LLM Wikis as Semantic Layer
- `docs/llm-wiki/*.md` are markdown nodes with frontmatter? Graphify extracts via Ollama if available (qwen3:32b). We can optionally set `VITE_LLM_PROVIDER=none` to skip cloud.
- These wikis are purpose-built for LLM consumption: small, structured table, examples, file pointers, security notes — replaces reading 12 CLI files.

### Token Savings Example
Real numbers from personal-graphify README for similar corpus:
- Vector Hoops 12,966 seasons + Ava v6.4 + Family Brain: 428 nodes, 614 edges, 58 communities
- Before graphify: ~123k tokens (naive read all)
- After: `pgraphify query` ~1.7k tokens (71.5x)
- BigBang CLI similar: expect ~1.5-2k tokens per query after first build.

### Automation Hook (optional)
```bash
cd ~/workspace/bigbang-cli
pgraphify hook install --project  # git hook auto-rebuild graph.json on commit
# Union merge driver for graph.json (handles concurrent edits)
```

### Integration with bb Tasks (future)
Current: `bb tasks sync-bb` creates Google Tasks from audit events.
Future automation:
```bash
# When pgraphify detects god node change (e.g., core/policy.py), create task:
pgraphify impact "bigbang/core/policy.py" | jq .impacted | xargs -I{} bb tasks add "Review impact of policy change on {}"
```

### Files Created for This Wiki
- `docs/llm-wiki/index.md` — entry point, ~1.2k tokens
- `docs/llm-wiki/architecture.md` — v0.4.1 flow, security checklist
- `docs/llm-wiki/tasks-plugin.md` — full tasks plugin doc
- `docs/llm-wiki/security-model.md` — caps, vault, proxy fix
- `docs/llm-wiki/graphify-integration.md` — this file
- `docs/llm-wiki/plugins.md` — to be generated via script below
- `docs/llm-wiki/quickstart.md` — quickstart for new devs/LLMs

### Generate Remaining Wikis via Script
We ship `scripts/generate_llm_wiki.py` that introspects `bigbang/plugins/*/manifest.yaml` + cli.py @app.command decorators and emits `plugins.md` and `quickstart.md`.

Run:
```bash
python3 scripts/generate_llm_wiki.py
# outputs plugins.md, quickstart.md, updates index
ls docs/llm-wiki/
```

### Save to "My Graphify" Location
User said "save to my graphify, etc." — two places:
1. **Local bigbang-cli** `graphify-out/` — for this repo
2. **Personal graphify** `~/workspace/your_files/personal-graphify/graphify-out/` — global personal brain that includes bigbang-cli as subproject

We will copy/symlink bigbang-cli's `graph.json` into personal-graphify references:
```bash
cp ~/workspace/bigbang-cli/graphify-out/graph.json ~/workspace/your_files/personal-graphify/references/spaces/bigbang-cli-graph.json
# Or reference as external: pgraphify build ~/workspace --include **/bigbang-cli/**/*.py
```

# Solo personal project, no connection to employer, built with public/free-tier only
