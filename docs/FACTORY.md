# The factory — software, MLOps and data lines

> Status 2026-09-05: spec of record for `factory/`. What to work on lives in
> `docs/project_dag.json` (see `docs/PROJECT_DAG.md`); this is how the work runs.

**One line:** three registries and one CLI that turn DAG nodes into executed,
gated, provenance-honest work: `python -m factory`.

| line | registry | commands | runs where |
|---|---|---|---|
| software | `factory/repos.json` | `check next start done validate status` | anywhere a repo is checked out; CI |
| MLOps | `factory/train_queue.json` | `train list preflight run gate next promote` | the home box (GPU), nightly window |
| data | `factory/datasets.json` | `data list check refresh restore` | box, CI (freshness only), any checkout |

Free to run by construction: GitHub Actions on public repos, the home box, Vercel
free tier. Nothing here calls a paid API.

## 1. Layout and resolution

```
factory/
  __init__.py  __main__.py  cli.py     one CLI, argparse, stdlib only
  config.py                            workspace root, registry loading, DAG bridge
  software.py  mlops.py  data.py       one module per line
  repos.json  train_queue.json  datasets.json
  runs/                                box-local run logs and results (gitignored)
  tests/                               pytest, CPU-only, temp fixtures
```

- **Workspace root** = `FACTORY_WORKSPACE` if set, else the parent directory of
  the dottie checkout. Registries name repos (`vector-hoops`), never absolute
  paths; a repo resolves to `<workspace>/<repo>`.
- **DAG bridge**: every registry entry that names a `dag_node` must exist in
  `docs/project_dag.json`; every `repo` must exist in `repos.json`. `factory
  check` enforces both and is a CI step. Writes to the DAG go through
  `scripts/dag_next.validate` so a malformed graph can never be saved.
- **Commands run without a shell**: `shlex.split(cmd)` → `subprocess.run(list,
  cwd=repo)`. Output streams to the terminal and, for training runs, to a log.

## 2. Software line — `repos.json`

```json
{"repos": {"vector-gridiron": {
  "default_branch": "main",
  "role": "game",                      // center | game | site | service | library | archived
  "validate": ["python -m pytest tests -q"],
  "ci": ".github/workflows/ci.yml",    // or null
  "deploy": "vercel:vector-gridiron",  // or null
  "notes": "..."}}}
```

| command | does | exit |
|---|---|---|
| `factory check` | registries parse, every `repo`/`dag_node` resolves, paths are relative, every DAG repo has a registry row | 1 on any finding |
| `factory next [--repo R]` | the derived ready frontier (delegates to `scripts/dag_next.py`) | 0 |
| `factory start NODE` | DAG node → `in_progress`; best-effort `jarvis.claim` on `JARVIS_URL` if reachable; prints repo path, branch and validate commands | 1 if the node is not ready |
| `factory done NODE --evidence TEXT` | DAG node → `done`, records `done_on` and `evidence`; prints the nodes it unblocks | 1 if the node is not in progress |
| `factory validate REPO` | runs the repo's validate commands in order, stops at the first failure | the failing command's code |
| `factory status` | per registered repo: present, branch, dirty; DAG counts | 0 |

Done means the validate gate passed and the evidence is recorded; nothing in
this line marks a node done on its own.

## 3. MLOps line — `train_queue.json`

One queue for the box. The DAG says every retrain waits on the same GPU, so the
queue is the serialisation point (`gpu-box-dedicated`).

```json
{"jobs": [{
  "id": "gridiron-real-train", "repo": "vector-gridiron", "dag_node": "gridiron-real-train",
  "priority": 2, "needs_cuda": true, "est_hours": 2,
  "needs": ["pipeline/train_mtnn.py", "pipeline/data/train_matrix.npz"],
  "smoke": "python pipeline/train_mtnn.py --epochs 2 --d-emb 32",
  "run":   "python pipeline/train_mtnn.py --epochs 50 --d-emb 32 --scaling robust --era-align procrustes",
  "eval":  null,
  "gate": {"report": "pipeline/eval_reports/latest.json", "metric": "mae",
           "op": "<=", "threshold": 3.8, "baseline": 4.268,
           "baseline_source": "README.md"},
  "promote": ["copy checkpoint to assets/, update candidate.json, open a PR"]}]}
```

| command | does |
|---|---|
| `train list` | queue in priority order with the last recorded result per job |
| `train preflight JOB` | names every missing prerequisite: repo missing, each `needs` path, CUDA (via torch, honestly reported as unknown when torch is absent) |
| `train run JOB [--smoke]` | preflight → run `smoke` or `run` in the repo, log to `factory/runs/JOB/<ts>.log` → `eval` if set → gate → write `factory/runs/JOB/<ts>.json` |
| `train gate JOB` | evaluate the gate from the report file only (metric found by dotted path) |
| `train next` | the first job by priority whose preflight passes; exit 1 when none |
| `train promote JOB` | refuses unless the last result passed its gate; then prints the promote steps. Never copies files |

Gate outcomes are `pass`, `fail`, `no_report`, `no_metric`; only `pass` can
promote. Results carry the repo's HEAD sha, the command, wall time and the
metric value read.

`scripts/train_window.ps1` installs a nightly Windows Task Scheduler window
(`/RL LIMITED`, same conventions as `vector-unified/SCHEDULING.md`) that runs
`python -m factory train run --next` on the box. It is a script the operator
runs, not something this repo installs.

## 4. Data line — `datasets.json`

```json
{"datasets": [{
  "id": "arxiviq-papers", "repo": "arxiviq", "path": "site/public/data/papers.json",
  "provenance": "real",                // real | honest-synthetic | placeholder | unknown
  "source": "arXiv API via scripts/fetch_topics.py",
  "refresh": "python scripts/fetch_topics.py", "cadence_days": 7,
  "fresh_key": "json:generated_at",    // or "mtime"
  "restore_from": [], "required": true,
  "consumers": ["arxiviq-real-data"]}]}
```

| command | does |
|---|---|
| `data list` | registry with provenance and consumers |
| `data check [--check]` | per dataset: present, size, sha256 (short), age, stale (age > cadence), expected-sha match; `--check` exits 1 when a `required` dataset is missing or stale |
| `data refresh ID` | runs the refresh command in the owning repo, then re-checks |
| `data restore ID` | copies the first existing `restore_from` source into `path` and writes `<path>.manifest.json` (source, sha256, size, when); refuses to overwrite a present file without `--force` |

Freshness is declared, not inferred: no `cadence_days` means the dataset is
static and can only be missing, never stale.

## 5. Acceptance

- `uv run pytest factory/tests -q` green; `uvx ruff@0.15.22 check factory` at 0.
- `python -m factory check` exit 0 on this tree and runs in CI.
- `factory train run` on a fake job in a temp repo produces a log, a result
  with `gate: pass`, and `train promote` prints the steps; with a failing
  gate `promote` refuses.
- `factory data restore` on a temp fixture copies and writes the manifest;
  `data check --check` exits 1 on a missing required dataset.
- The real registries describe the real repos: the trainer hoops lacks
  (`pipeline/train_mtnn.py` is not in vector-hoops) shows up in `train
  preflight hoops-v6-retrain`, not in a comment.
