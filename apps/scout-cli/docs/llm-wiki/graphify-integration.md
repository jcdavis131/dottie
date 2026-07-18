# Graphify Integration — Scout CLI

**Solo personal project, no connection to employer, built with public/free-tier only**

## What is baked in

Scout ships a first-class `graphify` plugin that wraps **Personal Graphify** (`pgraphify`):

```bash
scout graphify status
scout graphify build .                 # this repo → ./graphify-out
scout graphify ecosystem               # multi-root: scout + Ava + personal-graphify
scout graphify query "how does Scout connect to Ava?"
scout graphify path "Scout CLI" "Ava AGI Factory v6.4"
scout graphify explain "Turnover Shield" --snippet
scout graphify impact "Scout CLI" --direction both
scout graphify task "wire Scout control plane to Ava J-space router"
scout graphify onboard
scout graphify cost
scout graphify sync                    # → <personal-graphify home>/references/spaces/scout-cli-graph.json
```

Aliases `bb` / `bigbang` / `kitty` / `dv` also work: `bb graphify query "..."`.

## Prerequisites

```powershell
uv tool install -e $env:USERPROFILE\personal-graphify   # provides pgraphify on PATH
# or: pip install -e ~/personal-graphify
# dottie monorepo: uv tool install -e <dottie>\packages\personal-graphify
#             or: pip install -e <dottie>/packages/personal-graphify
```

Optional env:

| Env | Role |
|-----|------|
| `PERSONAL_GRAPHIFY_HOME` | Override the personal-graphify home |
| `DOTTIE_ROOT` | dottie monorepo root — `packages/personal-graphify` probed before `~/personal-graphify` |
| `SCOUT_GRAPHIFY_GRAPH` / `PGRAPHIFY_GRAPH` | Force graph.json path |

Home resolution order: `PERSONAL_GRAPHIFY_HOME`/`PGRAPHIFY_HOME` → `DOTTIE_ROOT/packages/personal-graphify` → `~/workspace/dottie/packages/personal-graphify` → `~/personal-graphify`.

Graph resolution order: `--graph` → env → `./graphify-out/graph.json` → `<personal-graphify home>/graphify-out/graph.json`.

## Ava + agent routing

- `scout ava route "what connects Scout via graphify"` → picks `graphify`
- Agent heuristic hints include `graphify` / `pgraphify` / `task compiler`

## Token savings

Query-first agents should run `scout graphify task "..."` before grepping. Typical scoped subgraph ~1.5k tokens vs full-repo naive.

## Public vs private

- **Private / agent**: full multi-root graph in `~/personal-graphify/graphify-out/` (dottie monorepo: `<dottie>/packages/personal-graphify/graphify-out/`)
- **Public demo**: light sanitized graph on [jcamd.com/graphify/](https://jcamd.com/graphify/) (~250 seeds)

Publish light graph via personal-graphify `scripts/sanitize_for_public.py` (see `graphify-workflow` skill).

# Solo personal project, no connection to employer, built with public/free-tier only
