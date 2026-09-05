# The factory — plan of record (2026-09-05)

Supersedes the 2026-07-23 dynamic-workflow plan, kept in git history
(`git show d2ab5a0:tasks/plan.md`). Spec: `docs/FACTORY.md`. Graph of work:
`docs/project_dag.json` (`python scripts/dag_next.py`).

## Ask

Set up the software, MLOps and data factories so the projects on the DAG start
building and executing instead of sitting on a list.

## Constraints

- Free or nearly free to run: GitHub Actions on public repos, the home box
  (Alienware, RTX 4080) for anything that needs a GPU, Vercel free tier for sites.
- Provenance-honest: a missing file, a missing trainer, no CUDA, a failed gate
  are reported as such, never smoothed over. Shipped numbers are never
  overwritten by automation; promotion is an explicit, printed, manual step.
- One source of truth per concern: `docs/project_dag.json` for what to work on,
  `factory/repos.json` for how each repo is validated, `factory/train_queue.json`
  for what the box trains next, `factory/datasets.json` for what data exists and
  how it is refreshed.
- Everything testable in a CPU-only container. The box-side pieces (Task
  Scheduler, GPU runs) are installable scripts, not claims.

## Done criteria

1. `python -m factory check` validates the three registries against the DAG and
   is a CI step.
2. `factory next|start|done|validate|status` move DAG nodes and run a repo's
   registered validate gate.
3. `factory train list|preflight|run|gate|next|promote` runs a queued job in its
   repo, logs it, and evaluates its gate from the report file; preflight names
   every missing prerequisite. `scripts/train_window.ps1` installs the nightly
   window on the box.
4. `factory data list|check|refresh|restore` reports presence, freshness and
   sha256 for every registered dataset, refreshes one, and restores a cache from
   a sibling checkout with a manifest.
5. Tests for all of it green under `uv run pytest factory/tests`; ruff clean on
   the new package; CI green on the PR head.

## Board

| # | task | status |
|---|---|---|
| 1 | Plan + spec gate (this file, `docs/FACTORY.md`) | done |
| 2 | factory core: package, config, `factory check` against the DAG | done |
| 3 | Software line: `repos.json`, `next/start/done/validate/status` | done |
| 4 | MLOps line: `train_queue.json`, `train *`, `scripts/train_window.ps1` | done |
| 5 | Data line: `datasets.json`, `data *` | done |
| 6 | Wire: ci.yml, Makefile, `factory.yml` weekly report, README/HANDOFF/DAG | done |
| 7 | Close-out: lint, tests, commit, push, PR #23, review, readiness report | in progress |

## Decisions taken without asking (auto mode, reversible)

- Package name `factory` (no collision in `uv.lock`, checked 2026-09-05).
- Workspace root = parent directory of the dottie checkout, overridable with
  `FACTORY_WORKSPACE`. Registries name repos, not absolute paths.
- The queue's gate is evaluated from a JSON report the trainer already writes
  (each repo's `eval_*.py` output), not from parsing logs.
- `tasks/todo.md` stays superseded; this file is the board.
