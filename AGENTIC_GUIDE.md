# Agentic Guide — Coding Smarter Systems with Personal Graphify

Solo personal project, no connection to employer, built with public/free-tier only.

## Why this beats plain Cursor

Plain Cursor: reads files linearly, greps, reconstructs architecture every time → ~123k tokens per question (Karpathy corpus), repeats work, misses cross-file why.

Graphify: builds once, query subgraph ~1.7k tokens, has god nodes + surprises + rationale nodes.

Result: 71.5x token reduction pattern upstream, same in personal edition, senior-dev-level navigation.

## Architecture (from Graphify doc you shared)

```
detect — collect files respecting .gitignore + .graphifyignore
extract — AST + LLM nodes/edges (Tree-sitter for code, Ollama for docs/diagrams)
build — NetworkX graph merge all nodes/edges
cluster — Leiden/greedy communities (no embeddings needed)
analyze — god nodes (highest-degree) + surprise cross-file edges
report — GRAPH_REPORT.md (audit)
export — HTML / JSON / Obsidian
serve — MCP stdio/http for team shared server
query — query / path / explain commands
```

Supports: Code 25+ languages (".py .js .go .java .rs …"), Docs PDFs Markdown, Images/diagrams via vision models, Videos/audio via local Whisper optional.

Local-first: Code = AST locally 0 cost; docs/media = Ollama local qwen3:32b by default (you already have Ollama).

## Personal Overlay — How we mapped your stuff

We added personal extractors for your isolation system:

- If path contains `01_Finance` → node `ecosystem:finance`
- `02_Passive_Lab` → `ecosystem:passive_lab` + detects "stripe"/"plaid"
- `04_Tennis_DINOv3` → `ecosystem:tennis`
- Detects "mtNN" → `concept:mtnn` (MTNN v5 48→64→k)
- Detects `integration:stripe`, `integration:plaid`
- Parses `PROJECT.md` for MRR, Turnover, MTNN, Ava, Family terms → concepts
- Parses `# NOTE: # WHY: # HACK:` → rationale nodes linked to code they explain (first-class)
- Parses markdown `[]()` and `[[wikilinks]]` → `references` edges between docs
- Package manifests `pyproject.toml go.mod` → single canonical package node (hub)

## Agentic Loop — Query First

1. User: "add retention playbook to Turnover Shield"
2. Agent (with `.cursor/rules/graphify.mdc` alwaysApply:true):
   - `pgraphify query "retention playbook"` → gets 8 nodes: `playbook.py`, `Stripe webhook`, `paid_users`, `churn_pct`, plus rationale `WHY: saving 1 tech = $5k`
   - `pgraphify explain "Turnover Shield"` → degree 12, community 2, file list
   - Builds edit using only subgraph context (not full repo)
   - After edit: `pgraphify build . --out graphify-out --max-files 500` (incremental)
   - `git add graphify-out/graph.json` + push

Before graph: agent would `glob **/*.py` + read 20 files = 80k tokens, guess connections.
After graph: 2 queries = ~3k tokens, precise edges with EXTRACTED vs INFERRED.

## Example Traces (real from your test run)

Test on personal-graphify itself:
- 297 nodes, 478 edges, 27 communities
- God nodes: `cli.py`, `cmd_build`, `extract.py` (expected central)
- Query "graphify": 60 nodes subgraph (1500 tokens vs 14850 naive = 13.9x even tiny repo)
- Surprise: `export.py imports html` cross-community — unexpected coupling flagged

Scale to your big repos:
- httpx small (upstream example): 6 files → 144 nodes 330 edges 6 communities, god nodes Client/AsyncClient/Response/Request, surprise DigestAuth→Response
- Karpathy mixed corpus: 52 files ~92k words → 285 nodes 340 edges 53 communities, avg query 1.7k vs 123k naive 71.5x

## Smarter Agentic Patterns

### 1. Onboarding new repo
```
pgraphify .
cat graphify-out/GRAPH_REPORT.md  # read god nodes + surprises + 5 suggested questions
open graphify-out/graph.html
```
You have senior-dev map in 30 seconds.

### 2. Refactor planning
```
pgraphify path "UserService" "DatabasePool"  # 3 hops: uses → references → references
pgraphify query "what else uses DatabasePool?"  # find all consumers to update
```

### 3. Feature addition (Turnover Shield churn)
```
pgraphify query "churn_pct calculation"
pgraphify explain "paid_users"
pgraphify path "Stripe webhook" "MRR dashboard"
# agent now knows exactly 4 files to touch, not 40
```

### 4. Bug hunting (cross-file surprise)
God nodes show `S2 Slow hl300` high degree — if bug in S2, surprise edges show unexpected link to `Family Brain Plaid` → coupling risk.

### 5. Team shared graph
```
python -m graphify.serve graphify-out/graph.json --transport http --host 0.0.0.0 --port 8080 --api-key $SECRET
# whole team Cursor MCP points at http://host:8080/mcp instead of local
```

## Cursor Skills Integration — What you asked for

We created 3 skills for your cursor skills repo (see `skills/`):

- **graphify-core**: build/query/path/explain, always query before grep, security model
- **graphify-personal**: your home patterns — Family Brain $11k burn, Turnover Shield $79-149, Ava S1 hl8 S2 hl300 Critic hl30 Planner hl150 YaRN 10k→1M, Vector MTNN 12,966 seasons, isolation rules
- **graphify-agentic**: teaches agents query-first, token win 71.5x, rationale nodes, shared HTTP server

Plus `.cursor/rules/graphify.mdc` with `alwaysApply:true` so every chat includes guidance — no PreToolUse hook needed (Cursor includes rule automatically), unlike Claude Code which uses hook.

Install to your cursor skills repo:
```bash
./scripts/install_cursor_skills.sh ~/your-cursor-skills-repo
```

## Next — Make it self-sustaining

Per your Passive Lab goals (first $1k/mo passive), Graphify graph makes Turnover Shield maintainable with 0 ongoing input:

- Graph is committed, new devs pull instant map
- Git hook `graphify hook install` auto-rebuilds AST on commit (0 LLM cost) + merge driver union-merges graph.json (no conflicts)
- Friday MRR tracking: `pgraphify query "trials paid_users MRR churn"` → auto-report

Ready.

Solo personal project, no connection to employer, built with public/free-tier only.
