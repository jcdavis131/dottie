---
name: graphify-agentic
description: Agentic workflow — how Cursor/Claude Code should use graphify to get stuff done
---
# Graphify Agentic SOTA

**Goal:** Help Cameron get stuff done with minimal context.

Workflow:

1. Onboard 30s: `pgraphify onboard` — god nodes, hot files, entry points, suggested questions
2. Task compile: `pgraphify task "<natural task>"` — returns:
   - top_matches (label, type, file, score)
   - files priority (relevance)
   - token estimate naive vs scoped = 71x
   - plan + copy_paste_context
3. Read only files from step 2 in relevance order
4. Explain + Impact: `pgraphify explain "X" --snippet` + `pgraphify impact "X" --direction both`
5. Edit minimal files
6. Rebuild: `pgraphify . --out graphify-out` and commit graph.json

MCP server:
- HTTP: `pgraphify serve --transport http --port 8080` -> GET /mcp/tools, POST /mcp/call with name graphify_query etc
- Stdio: `pgraphify serve --transport stdio` for Cursor/Cline (tools: query, path, explain, impact, task, onboard)

Examples:
- "Where is Stripe implemented?" -> `pgraphify query "Stripe"`
- "How does Stripe webhook connect to MRR?" -> `pgraphify path "Stripe" "MRR / Paid Users"`
- "What breaks if I change Family Brain Plaid hub?" -> `pgraphify impact "Plaid" --direction both`
- "Add retention playbook" -> `pgraphify task "add retention playbook to Turnover Shield churn prediction"`

Public demo: jcamd.com/graphify/ has JS task compiler + impact BFS client-side.

Solo personal project, no connection to employer.
