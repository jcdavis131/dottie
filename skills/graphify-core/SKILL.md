---
name: graphify-core
description: Graphify core — query-first, 71x token reduction, local AST + clustering
---
# Graphify Core SOTA

- Build: `pgraphify .`
- Query: `pgraphify query "<q>"` -> ~1.5k tokens vs 155k naive
- Path: `pgraphify path "A" "B"`
- Explain: `pgraphify explain "X" --snippet`
- Impact: `pgraphify impact "X" --direction both --depth 3` — upstream dependents + downstream uses + file hotspots
- Task: `pgraphify task "add feature"` -> files priority + plan + copy context
- Onboard: `pgraphify onboard` -> god nodes, hot files, entry points
- Serve MCP: `pgraphify serve --transport http|stdio`

Outputs: graphify-out/graph.json (queryable) + graph.html + GRAPH_REPORT.md + cost.json
Solo disclaimer.
