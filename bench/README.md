# Dottie benchmark builder (`bench/`)

The missing piece for measuring the Dottie harness + skills ecosystem:
a stdlib-only parallel runner that exercises the workflows we care about
in dry-run/read-only mode and reports honest numbers.

## Files

- `workflow_inventory.json` — 10 workflows: id, command, cwd, timeout,
  checker, expected outcome. Edit this to add/remove workflows.
- `runner.py` — ThreadPoolExecutor over subprocesses; captures exit code,
  wall latency_ms, output size, heuristic tokens_est (chars/4, labeled as
  estimate); per-workflow correctness checkers; writes `out/results.json`.
- `metrics.py` — p50/p95 latency, success_rate, per-workflow score,
  category rollups, single harness_score; writes `out/metrics.json`.
- `report.py` — verdict-first `report.md`, ≤10 lines per workflow, honest
  gaps; blocked workflows reported as BLOCKED, never as success.

## Run

```bash
cd ~/workspace/dottie
python3 bench/runner.py                 # all 10, parallel
python3 bench/runner.py --only retrieval_commit
python3 bench/metrics.py
python3 bench/report.py
```

All runs are dry-run/read-only: playbooks use `--dry-run`, evals are local
sqlite/git mining, grpo_collect writes to a bench temp dir, the Slack drain
is a read-only poll. Nothing merges, deploys, posts, or writes outside
bench temp dirs.
