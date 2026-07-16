# SPEC — jcamd.com sync + Personal Graphify for Ava & projects

Solo personal project, no connection to employer, built with public/free-tier only.

## Objective

Bring **jcamd.com**, **Personal Graphify**, and **Cursor workflow skills** into one coherent loop so agents (and you) can query a current map of Ava + lab projects instead of grepping blindly.

Success looks like:

1. **jcamd.com** local + live match: Lab shows Vector Hoops/Pitch/Gridiron + Personal Graphify; `/graphify/` serves the latest sanitized public graph.
2. **Personal Graphify** private graph rebuilt with current project surfaces (Ava factory, Vector suite, Scout CLI, Turnover Shield / Passive Lab goals) — Scout currently **0 nodes**.
3. **Skills installed** into `~/.cursor/skills/` so Cursor auto-routes query-first (`pgraphify query|task|impact|onboard`) across repos.
4. Agents working Ava / vector / scout / jcamd can onboard in ~30s via `pgraphify onboard` and compile tasks with measurable token reduction.

## Assumptions (correct me now)

1. **Corpus roots (private build)** — index these local trees (respect `.graphifyignore` + never `03_Meta_Work_ISOLATED`):
   - `~/personal-graphify` (self)
   - `~/ava-agi` and/or `~/ava-agi-factory-v6-4`
   - `~/vector-hoops`, `~/vector-pitch`, `~/vector-gridiron`, `~/vector-tennis` (and related `vector-*` if present)
   - `~/scout-rtx` and/or clone of `jcdavis131/scout-cli`
   - Passive Lab / Turnover Shield references already in `references/` — deepen if local paths exist
2. **Public export** — continue PII strip via `scripts/sanitize_for_public.py`; no dollar balances, emails, account numbers on jcamd.com.
3. **Skills home** — install into Cam’s personal library `~/.cursor/skills/{graphify-core,graphify-personal,graphify-agentic}` + sync `cursor-skills-personal` private repo; also add a thin **orchestrator skill** `graphify-workflow` that chains onboard → task → impact → rebuild.
4. **jcamd git** — `master` is **behind origin by 7** (has Graphify GR-03 + dumbmodel lab) and **ahead by 1** (local redirect/github.js polish). Prefer **rebase local onto origin/master**, keep both lab grid and local polish.
5. **Deploy** — push `jcdavis131/jcamd` `master` only after you confirm (Vercel auto-deploy). High-risk gate.
6. **Tooling** — `uv tool install -e ~/personal-graphify` so `pgraphify` is on PATH; Ollama semantic toggle optional (`mxbai-embed-large`), not required for lexical rebuild.

## Non-goals

- Indexing Meta/employer work trees
- Publishing private Family Brain dollar amounts or account IDs
- Replacing upstream Graphify-Labs package as a public fork (this stays private personal edition)
- Redesigning the consulting homepage brand/voice (Lab + Graphify sync only unless content is stale)

## Commands

```powershell
# Install CLI
cd ~/personal-graphify
uv tool install -e .

# Build multi-root (exact flags confirmed against cli.py during implement)
pgraphify build --roots <paths> --out graphify-out

# Query / agent loop
pgraphify onboard
pgraphify query "how does Ava Planner interact with Critic?"
pgraphify task "wire Scout control plane to Ava J-space router"
pgraphify impact "multi_jspace_module" --direction both

# Public sanitize + publish into jcamd-site
python scripts/sanitize_for_public.py
# copy docs/public/* → jcamd-site/assets/graphify/ + graphify/index.html

# Skills
# copy skills → ~/.cursor/skills/ + push cursor-skills-personal

# Site verify
# https://jcamd.com/ and https://jcamd.com/graphify/ smoke
```

## Architecture

```
private corpus (HOME projects)
        │
        ▼
 personal-graphify (pgraphify build)
        │
        ├─► graphify-out/ (private, full)
        │         │
        │         ▼
        │   sanitize_for_public.py
        │         │
        │         ▼
        │   jcamd-site/assets/graphify + /graphify/
        │         │
        │         ▼
        │   Vercel jcamd.com (public, non-PII)
        │
        └─► skills → ~/.cursor/skills + MCP serve (local agents)
```

## Acceptance criteria

| # | Criterion |
|---|-----------|
| A1 | Local `jcamd-site` includes `/graphify/` + Lab cards (Hoops, Pitch, Gridiron, Graphify) aligned with origin + local polish |
| A2 | Public graph node count ≥ current (515) **or** justified drop after dedup; **Scout ≥ 1** concept/file nodes; Ava communities still queryable |
| A3 | `pgraphify query "Ava Planner Critic"` and `pgraphify query "Scout"` return non-empty scoped subgraphs |
| A4 | `~/.cursor/skills/graphify-*` + new `graphify-workflow` skill present and discoverable |
| A5 | `docs/public` + jcamd assets have no PII patterns (emails, acct digits, $ burn figures) |
| A6 | Post-deploy smoke: `jcamd.com` serves Lab; `jcamd.com/graphify/` loads graph.json (only if deploy approved) |

## Risks

- **PII leak** on public sanitize — gate with script + grep pass
- **Diverged jcamd git** — rebase conflict on `index.html` / `github.js`
- **Large corpus** — multi-root build time/disk; prefer project READMEs + `src/` over node_modules/data dumps
- **Deploy** — requires explicit yes

## Footer

Solo personal project, no connection to employer, built with public/free-tier only.
