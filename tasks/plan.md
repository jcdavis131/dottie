# Plan — jcamd.com + Personal Graphify + workflow skill

Solo personal project, no connection to employer, built with public/free-tier only.

Dependency order (vertical slices):

```
1. Tooling install (pgraphify on PATH)
2. Sync jcamd-site with origin (Lab + /graphify/ baseline)
3. Expand corpus + rebuild private graph (Ava + Scout + Vector + goals)
4. Sanitize → publish assets into jcamd-site
5. Install/enrich Cursor skills (core/personal/agentic + graphify-workflow)
6. Homepage Lab copy refresh (node counts, Scout mention if public-safe)
7. Verify gates → (optional) deploy push
```

## Slice notes

### 1. Tooling
- `uv tool install -e ~/personal-graphify`
- Smoke: `pgraphify --help`, `pgraphify query` against existing graphify-out

### 2. jcamd sync
- `git fetch`; rebase local `e7bfb83` onto `origin/master` (`5b993ed`)
- Resolve conflicts preferring origin Lab/graphify + keep local redirect/github polish where compatible
- Do **not** push until deploy gate

### 3. Graph rebuild (focus)
- Confirm CLI multi-root / overlay flags in `cli.py`
- Build corpus from SPEC roots; add Scout CLI patterns to personal extractors if missing
- Target: Scout nodes present; Ava J-space still god-adjacent; cost.json preserved across rebuild if CLI supports it
- Regenerate GRAPH_REPORT.md; spot-check suggested questions for Ava/Scout/Turnover

### 4. Public publish
- Run `sanitize_for_public.py`
- Copy into `jcamd-site/assets/graphify/{graph.json,GRAPH_REPORT.md,cost.json}` + `graphify/index.html` (bump badge counts)
- PII grep gate

### 5. Skills
- Install existing 3 skills → `~/.cursor/skills/`
- Author **`graphify-workflow`**: when to run onboard/task/impact; multi-repo corpus roots; Ava/Vector/Scout query recipes; publish-to-jcamd checklist; pair with `session-orient` / `auto-mode`
- Sync `cursor-skills-personal` private repo
- Optional: project-level `.cursor/rules/graphify.mdc` in ava + vector + scout (not alwaysApply globally if too noisy — prefer skill description triggers + user `/graphify`)

### 6. Site Lab refresh
- Update Graphify card stats to new node/edge counts
- Ensure dumbmodel.com lab links match live products
- Footer/nav: link to `/graphify/` if missing

### 7. Verify + close
- A1–A5 acceptance from SPEC
- Readiness report + close-the-loop
- **Stop for deploy yes** before `git push` jcamd

## Decisions locked (unless you override)

| Decision | Choice |
|----------|--------|
| Skills location | `~/.cursor/skills/` + sync private `cursor-skills-personal` |
| New skill | `graphify-workflow` orchestrator (not replace core/personal/agentic) |
| Git | rebase local polish onto origin/master |
| Public | sanitized only |
| Deploy | gated |

## Out of scope this pass

- Family Brain dollar/account enrichment in public graph
- Upstream Graphify-Labs contribution PR
- Full redesign of consulting hero
