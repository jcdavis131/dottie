# Operational tooling — look here before writing a script

Written because I did not. TODOS §5.3.R92: I hand-rolled a seed-sweep script while the loop
had **already generated a better one** for that exact candidate, hours earlier. The tool
existed, was more correct than mine, and I never looked. Same shape as §5.3.R88 (invented a
timestamp instead of reading `git log`) and §5.3.R89 (estimated an install instead of
checking it) — **produce something plausible instead of consulting the source that has the
answer.**

So: this file is the source. Check it first.

## Repo root — `scripts/`

| script | what it does | when |
|---|---|---|
| `restart_research.ps1` | Restarts the research daemon and **proves it booted** by waiting for the `boot` line in `run.log`. Refuses on low memory or orphaned processes. Measures the Ollama model's real load cost rather than assuming it. | training is off |
| `prepare_fleet_recovery.ps1` | Prep + GO/NO-GO for bringing the Docker fleet back. **Step 1 disables the scheduled task by design** — know that before running it. | fleet is down |
| `tune_docker_desktop.ps1` | Docker Desktop resource configuration for this box. | after a WSL/Docker reinstall |
| `check_todos_timestamps.py` | Fails if any clock time claimed in a TODOS `5.3.R<N>` entry is in the future relative to HEAD. **Ops discipline 9.5: run it on any tick that writes TODOS.** | before committing TODOS |
| `store_symmetry_audit.py` | Finds mutations that clear one store and leave another holding the value — the shape of the `delete_secret` bug (fixed `a2ccea5`), where deletion reported success and the credential stayed readable. `--check` self-tests against the real pre-fix function first, so it cannot pass by having gone blind. | after touching anything with two stores (vault/keyring, cache/disk) |

## Research loop — `apps/dottie/scripts/`

| script | what it does | when |
|---|---|---|
| `run_log.py` | Reads `data/research/logs/run.log` — the **only ground truth** for what code the daemon is running, since it does not live-reload. | "is the loop alive / on which sha" |
| `post_restart_report.py` | **Pre-registered** post-restart analysis: `MIN_N`, `BOOT_SHA`, LIVE / NOT_IN_WINDOW lists fixed in advance so the readout cannot be shaped after seeing the data. | after a restart, once N accumulates |
| `mutation_audit.py` | 13 mutants against the research suite; journalled so a crash mid-run restores the tree. Answers "do these tests actually catch anything". | after changing gates or validators |

## Generated per promotion — `data/research/promotions/<exp_id>/`

**Created automatically on every promotion.** This is the one I missed:

| file | what it does |
|---|---|
| `ab_nano.py` | **Ready-to-run re-verification.** Seeds 0/1/2, unmodified model and candidate at the *same* seed, **paired** differences so shared run-to-run variance cancels, then the loop's own 2×SEM standard. Run it before believing any promotion: `python data/research/promotions/<exp_id>/ab_nano.py` (needs `AVA_FACTORY_ROOT`). |
| `PROMOTION.md` | The human-readable bundle, with caveats rendered **above** the numbers — baseline provenance, contamination, capacity delta, significance. |
| `candidate.py` | The candidate's code exactly as it was trained. |

## Environment

Both the tests and the trainer need the factory checkout:

```
AVA_FACTORY_ROOT=C:\Users\jcdav\workspace\ava-agi-factory-v6-4
```

The daemon sets it from `apps/dottie/research_orchestration/research_env.local.ps1`
(gitignored, machine-local). Without it, `apps/dottie` reports 36 failures that look like a
broken repo and are not — see §5.3.R87, where that cost four hours.

## Not here

`apps/ava-factory/scripts/` (31 files) is factory tooling — dataset expansion, harvesters,
pilots. `apps/ava-factory/research-engine/scripts/` duplicates 7 of them **byte-identically**,
and both are reachable depending on entry point; a test enforces they never drift (§5.3.R80).
