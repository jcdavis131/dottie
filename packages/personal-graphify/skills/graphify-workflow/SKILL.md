---
name: graphify-workflow
description: >-
  Orchestrates Personal Graphify (pgraphify) across Ava, Scout CLI, Vector lab,
  Turnover Shield, and jcamd.com — onboard → task compile → impact → edit →
  rebuild → optional public sanitize/publish. Use when starting work in those
  repos, when the user mentions graphify/pgraphify/knowledge graph, Scout↔Ava
  wiring, query-first agents, or publishing jcamd.com/graphify/.
---

# Graphify Workflow

Solo personal project, no connection to employer, built with public/free-tier only.

Query-first loop for Cam’s ecosystem. Prefer this over grepping when the question is architectural or cross-repo.

## When to use

- Session start in `ava-agi*`, `scout-cli`, `vector-*`, `personal-graphify`, `jcamd-site`
- “Where is X / how does A connect to B / what breaks if I change Y”
- Publishing or refreshing `jcamd.com/graphify/`

## Prerequisites

```powershell
# once
uv tool install -e $env:USERPROFILE\personal-graphify
# graph lives at personal-graphify/graphify-out/graph.json
```

Pair with `session-orient` at boot. Do **not** index `03_Meta_Work_ISOLATED`.

## Default agent loop

```
1. pgraphify onboard --graph <graph.json>
2. pgraphify task "<user task>" --graph <graph.json>
3. Read only top files from task output
4. pgraphify impact "<hot node>" --direction both --depth 3
5. Edit minimal files
6. Rebuild if structure changed (see Multi-root build)
```

Useful queries:

```powershell
pgraphify query "how does Scout connect to Ava?"
pgraphify path "Scout CLI" "Ava AGI Factory v6.4"
pgraphify query "how does Ava Planner interact with Critic?"
pgraphify task "wire Scout control plane to Ava J-space router"
```

MCP (optional): `pgraphify serve --transport stdio` or `--transport http --port 8080`.

## Multi-root build (ecosystem graph)

From `~/personal-graphify`:

```powershell
pgraphify build . `
  --roots "$env:USERPROFILE\scout-cli,$env:USERPROFILE\ava-agi-factory-v6-4,$env:USERPROFILE\personal-graphify\references" `
  --out graphify-out `
  --max-files 4000
```

Vector lab: keep thin docs under `references/vector-docs/` (do not full-scan 12k-file hoops dumps).

## Publish to jcamd.com/graphify/ (public, non-PII, light)

Public graph must stay **light** (~250 ecosystem seeds, ~75KB minified). Private `graphify-out/` stays full for agents.

```powershell
cd $env:USERPROFILE\personal-graphify
# sanitize + lighten (default --light --max-nodes 250)
python scripts/sanitize_for_public.py --src graphify-out/graph.json --dest docs/public/graphify-public-non-pii.json
# verify signal before publish
pgraphify path "Scout CLI" "Ava AGI Factory v6.4" --graph docs/public/graphify-public-non-pii.json
pgraphify query "Turnover Shield MRR" --graph docs/public/graphify-public-non-pii.json
Copy-Item docs\public\graphify-public-non-pii.json $env:USERPROFILE\jcamd-site\assets\graphify\graph.json -Force
Copy-Item docs\public\GRAPH_REPORT_PUBLIC.md $env:USERPROFILE\jcamd-site\assets\graphify\GRAPH_REPORT.md -Force
# bump badges in jcamd-site/graphify/index.html + Lab card (node/edge counts)
# deploy: push jcdavis131/jcamd master (Vercel)
```

Do **not** publish the full sanitized dump (`*-full.json`) to jcamd.

## Related skills

- `graphify-core` — command reference
- `graphify-personal` — ecosystem overlay facts
- `graphify-agentic` — query-first agent habits
- `validate-gate` / `post-deploy-smoke` — after site publish

## Anti-patterns

- Grep whole monorepos before `pgraphify query|task`
- Committing unsanitized private `graph.json` to the public jcamd repo
- Indexing employer / Meta-isolated trees
