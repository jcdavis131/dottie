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
| `check_todos_timestamps.py` | Fails if any clock time claimed in a **`TODO.md`** `5.3.R<N>` entry is in the future relative to HEAD. **Now a CI step** — it pointed at a `TODOS.md` deleted by `41534f2` and died with `FileNotFoundError` for six days while this row told people to run it, so "run it manually" is no longer the enforcement. | automatic; run locally before committing TODO.md |
| `state_pollution_sweep.py` | Snapshot/diff over home state, in-repo generated state, and the scout-cli source tree. **Now a CI gate** wrapped around the scout-cli suite (`--snapshot` before, `--diff` after) — it was enforced by a TODO.md mention only, which is how `check_todos_timestamps.py` died unnoticed. Refuses to pass on an empty snapshot. | automatic; run manually around any suite you suspect |
| `check_cli_path_args.py` | A shell argument reaching a filesystem path. `forge rm ../core --force` was an `rmtree` of `bigbang/core` reported as `ok: true` (fixed `a5c155b`). Narrow by design — `@app.command` + `typer.Argument/Option` + a direct join — which is why it has no false positives. `--check` self-tests against the pre-fix `rm_cmd`. | after adding a command that takes a name or path |
| `check_shell_true.py` | Every `shell=True` needs a written reason. Found the HF token being logged (`594a732`) and `--folder`/`--upload` reaching a command line unquoted (`f59c255`). Checks the KEYWORD, not the interpolation: in gdrive the interpolation was in the callers while `shell=True` sat in a shared helper. | after adding any `subprocess` call |
| `store_symmetry_audit.py` | Finds mutations that clear one store and leave another holding the value — the shape of the `delete_secret` bug (fixed `a2ccea5`), where deletion reported success and the credential stayed readable. `--check` self-tests against the real pre-fix function first, so it cannot pass by having gone blind. | after touching anything with two stores (vault/keyring, cache/disk) |

## Detectors deliberately NOT built

Recording the dead ends so they are not rebuilt. Each was written, run, and measured.

**Secrets reaching a log or print — NOT statically detectable here, and the evidence is
specific.** Two real leaks were fixed this session: the HF token written into the Prefect
run log (`594a732`) and `secrets get` printing the plaintext beside its own mask
(`2a24c22`). A name-matching detector — credential-shaped variable inside a
`print`/`log`/`emit` call — was built to catch the class. Measured over 1,133 files:

    14 hits, 0 true positives     every one was `tokens` in the ML sense
                                  (step_tokens, total_tokens, num_flops_per_token)
    and it MISSED BOTH real leaks

It missed them because in both cases the secret was one assignment away from the sink —
inside `cmd` in the first, inside `payload` in the second, and neither of those names looks
like a credential. So the detector produces noise AND provides no protection. Catching this
needs dataflow, not name matching; the word that identifies the real bug (`token`) is also
the most common ordinary word in an ML repo. Do not rebuild the name-matching version.

**Timestamped filenames colliding — 0 true positives.** `write --save` lost 4 of 5
documents to `int(time.time())` collisions (fixed `2ce8975`). A sweep for the shape found 4
other sites: two already use a uuid suffix (one with a comment saying it hit this exact bug
first), and two are day-resolution artifacts in manual scripts where overwriting is the
intent. A gate at 0/4 would be pure noise.

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
AVA_FACTORY_ROOT=C:\Users\jcdav\dottie\apps\ava-factory
```

⚠ **This line used to name `C:\Users\jcdav\workspace\ava-agi-factory-v6-4`, the SUPERSEDED
standalone checkout.** `resolve.py` honours the env var *verbatim first* — ahead of
`dottie_root()/apps/ava-factory` — so following the old instruction silently pointed
everything at the stale tree. Same defect as `ava/cli.py` (fixed `0c89edd`) and
`arxiviq` (`cda982e`), except induced by documentation rather than code.

**You do not need to set it at all on a normal checkout.** With it unset, `resolve.py`
falls through to `dottie_root()/apps/ava-factory`, which is correct — verified 2026-08-02
with `AVA_FACTORY_ROOT` unset in this shell. Set it only when the factory genuinely lives
somewhere else.

**OPERATOR: `apps/dottie/research_orchestration/research_env.local.ps1` still sets the
superseded path**, so the live research daemon is running against
`~/workspace/ava-agi-factory-v6-4`. That file is gitignored machine-local config for a
running process, so it was NOT changed here — whether the daemon should be repointed mid-run
is your call, not an autonomous one.

The daemon sets it from `apps/dottie/research_orchestration/research_env.local.ps1`
(gitignored, machine-local). Without it, `apps/dottie` reports 36 failures that look like a
broken repo and are not — see §5.3.R87, where that cost four hours.

## Not here

`apps/ava-factory/scripts/` (31 files) is factory tooling — dataset expansion, harvesters,
pilots. `apps/ava-factory/research-engine/scripts/` duplicates 7 of them **byte-identically**,
and both are reachable depending on entry point; a test enforces they never drift (§5.3.R80).
