# Dottie worker — she takes the jobs you point at

This is Dottie's job-taking loop. The harness (`apps/scout-cli/bigbang/plugins/harness`)
is the orchestration engine; this worker is the part that picks up real jobs and does
them with real tools.

## Point a job at Dottie

```sh
cd ~/workspace/dottie/worker
python3 dottie.py submit \
  --goal "Fresh check on dottie PR #26: summarize state, lay out the hard-stop vs quarantine-and-page decision. Do NOT merge." \
  --context "repo: jcdavis131/dottie. Read the PR, check CI status, report." \
  --repo dottie \
  --surface
```

`--surface` means: report the result back to the main chat when done. Without it,
the result just lands in the queue.

## Watch the queue

```sh
python3 dottie.py status                  # counts: {"pending":..,"claimed":..,"done":..,"failed":..}
python3 dottie.py list --state pending     # what's waiting
python3 dottie.py show <job-id>           # full spec + result
```

## How the loop works

1. **Submit** — a job spec lands in `jobs/pending/` as `<job-id>.json`.
2. **Claim** — the worker atomically moves it to `jobs/claimed/` (`os.rename`, same
   filesystem, no races). One worker, one job at a time.
3. **Work** — the worker does the job with real tools (shell, files, git, subagents).
   Read-only jobs are preferred; anything destructive needs the job spec to say so
   explicitly, and the worker still asks before irreversible actions.
4. **Record** — `dottie.py done <id> --summary "..."` writes the result to
   `jobs/done/<job-id>.result.json`, and `dottie.py log` appends a 7-field timeline
   entry (`nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass`) to
   `~/workspace/timeline/timeline.jsonl`. Real work, real traces — this is what the
   factory's trace→label mining consumes. No stub theater.
5. **Surface** — if the job asked for it (`"surface": true`) or it failed, the worker
   reports back to the main chat. Otherwise it stays quiet.

The worker itself is the `dottie-worker` cron (every 15 min). Its body lives at
`~/workspace/cron.d/minutely/dottie-worker__interval@15m.md`.

## Rules

- Job JSONs under `jobs/` are runtime state, not source — gitignored (only `.gitkeep` files are committed).
- Never invent results. If a job can't be done, `fail` it with the honest reason.
- The harness's deterministic stub executors (`runner.py`) are for simulation and
  benchmarking — production traces come from real worker runs, recorded via `dottie.py log`.
- Destructive actions (merges, deploys, sends, deletes) need explicit approval in the
  job spec AND follow the normal approval rules. `dottie` never bypasses them.
