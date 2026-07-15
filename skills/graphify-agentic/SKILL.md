---
name: graphify-agentic
description: Teaches AI agents to code smarter using knowledge graphs — graph-first agentic coding
triggers:
- agentic
- code smarter
- senior dev
- codebase understanding
- onboarding
- refactor planning
version: 1.0.0
dependencies:
- graphify-core
- graphify-personal
provider: ollama
---

# Graphify Agentic — Smarter Agentic Systems

Solo personal project, no connection to employer, built with public/free-tier only.

Teaches Cursor/Claude Code/Codex agents to use the knowledge graph instead of linear grep, like a senior dev who has been there for years.

## Why Graph Beats Grep
Upstream benchmarks:
- LOCOMO (n=300) recall@10: graphify 0.497 vs mem0 0.048, supermemory 0.149
- Token reduction 71.5x on Karpathy mixed corpus (285 nodes, 340 edges, 53 communities) ~1.7k vs ~123k
- Graph build LLM credits 0 (AST-only) vs per-token for most systems

## Agentic Workflow (query-first)

1. **Map**: `pgraphify .` → writes `graphify-out/graph.json` (commit it, team pulls = instant map)
2. **God nodes**: Read `GRAPH_REPORT.md` → what everything flows through (e.g., `Client`, `AsyncClient`, `Response`, `APIRouter` in FastAPI example; in personal: `PROJECT.md`, `Stripe webhook`)
3. **Scope**: `pgraphify query "what connects auth to database?"` → returns subgraph + rationale nodes (`# NOTE:`, `# WHY:` comments become first-class linked nodes)
4. **Path**: `pgraphify path "A" "B"` → shortest path with confidence tags EXTRACTED/INFERRED/AMBIGUOUS — never guess vs known
5. **Explain**: `pgraphify explain "Concept"` → degree, community, file, line, uses/used-by
6. **Build**: Implement change using local context only, then `pgraphify --update` and `git add graphify-out/`

## Agentic System Patterns (personalized)

- **Rationale extraction**: `# NOTE:` / `# WHY:` / `# HACK:` comments become nodes linked to code they explain — agentic planner reads design intent without reading full file
- **Doc refs**: ADR/RFC citations become first-class nodes — `ProductSpec → Implementation` edges
- **Cross-system graph**: App code + DB schema + infra (SQL, Terraform, shell) in one graph — `graphify` handles 36 tree-sitter grammars + `.sql` + `.tf`
- **Git-native**: post-commit hook `graphify hook install` auto-rebuilds AST, merge driver union-merges `graph.json` (no conflict markers)
- **Shared server**: `python -m graphify.serve graphify-out/graph.json --transport http --host 0.0.0.0 --api-key $SECRET` → team points Cursor MCP at `http://host:8080/mcp` → no local graphify needed

## For Cursor

`.cursor/rules/graphify.mdc` has `alwaysApply: true` so every chat includes graph guidance automatically, no hook needed (unlike Claude Code which uses PreToolUse hook before Read/Glob).

To enforce: `graphify cursor install --project` + commit.

## Example Prompt to Agent

"Before you edit, run `pgraphify query 'how does turnover churn calculation flow?'` and `pgraphify explain 'Turnover Shield'` — use only that subgraph + god nodes. If you need connection to Stripe, run `pgraphify path 'Stripe webhook' 'MRR'`"

Result: agent codes with senior-level context, low tokens, traceable edges.

Solo personal project, no connection to employer, built with public/free-tier only.
