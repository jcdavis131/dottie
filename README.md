# dottie

Monorepo home of the Ava ecosystem. Built 2026-07-18 by subtree-merging six repos with full
history preserved (`git subtree add --squash=false`); every original commit is reachable in
this history.

| Path | Was | What it is |
|---|---|---|
| `apps/ava-factory` | ava-agi-factory-v6-4 | Model factory: data pipeline, trainer, FastAPI server, CPU-pilot chain |
| `apps/scout-cli` | scout-cli | `scout` CLI (bigbang plugins) + the arxiviq MLOps console (Vercel) |
| `apps/scout-rtx` | scout-rtx | Windows RTX hill-climb runner + bigbang-bridge plugin |
| `packages/ava-skills` | ava-skills | Skill system: memory-mint/router + 9 skills |
| `packages/ava-open-harness` | ava-open-harness | Eval gate: J-Space tests, frontier rubric, anti-mock guard |
| `packages/personal-graphify` | personal-graphify | Code knowledge-graph CLI/library |

## Workspace

Root `pyproject.toml` is a virtual [uv](https://docs.astral.sh/uv/) workspace over the four
light packages. `apps/scout-rtx` (exact `torch==2.9.1`/cu128 pin) and `apps/ava-factory`
(requirements.txt + Docker install, no pyproject) are deliberately excluded — install them per
their own READMEs. `bigbang-bridge` inside scout-rtx needs `pip install -e ../scout-cli`.

```bash
uv sync            # resolves + installs the four workspace members editable
uv run pytest packages/ava-skills   # etc.
```

## Layout resolution

Cross-package code resolves siblings dottie-relative (or via `DOTTIE_ROOT`), falling back to
the original standalone-sibling-checkout probes — both layouts work everywhere.

## Things worth knowing

- **Monorepo is now canonical (cutover 2026-07-18).** `jcdavis131/dottie/main` is source of truth. arxiviq Control Plane now fetches from `.../dottie/main/apps/ava-factory/` with legacy fallback. Standalone checkouts `ava-agi-factory-v6-4` and `ava-research-engine` archived to `~/workspace/_archive/` on 2026-07-18. All crons migrated to `~/workspace/dottie/apps/ava-factory`. DOTTIE_ROOT env preferred.
- `apps/ava-factory/runs/cpu_pilot/` in a fresh clone contains only the committed text evidence
  (MANIFEST.json, tokenizer, reports) — checkpoint binaries are gitignored by design; regenerate
  with `apps/ava-factory/scripts/cpu_pilot_e2e.py`.
- Committed build artifacts from the standalone era (`graphify-out*/`) rode in with history;
  pruning them is a follow-up decision, deliberately not done during migration.

Solo personal project, no connection to employer, built with public/free-tier only.
