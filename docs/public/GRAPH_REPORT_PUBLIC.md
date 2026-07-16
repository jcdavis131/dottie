# Personal Graphify Report (public light, non-PII)

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 250 · **Edges:** 179 · **~75 KB** minified

Light public export: ecosystem seeds only (Scout, Ava, Turnover Shield, Vector, Graphify, integrations). Call-graph / builtin noise dropped. Private agents should use `graphify-out/graph.json` (full multi-root).

## Suggested Questions

- `pgraphify query "how does Scout connect to Ava?"`
- `pgraphify path "Scout CLI" "Ava AGI Factory v6.4"`
- `pgraphify query "Turnover Shield MRR"`
- `pgraphify task "wire Scout control plane to Ava J-space router"`
- `pgraphify impact "Scout CLI" --direction both`

## Overlay

- **Scout CLI** → orchestrates Ava; tracks Turnover Shield / MRR; uses Personal Graphify
- **Ava** — J-Space Planner / Critic / S1 / S2
- **Vector** — Hoops / Pitch / Gridiron + MTNN
- **Hub** — jcamd.com/graphify/
