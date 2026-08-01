# Docs & Metadata review

> **Status 2026-08-01:**
> - 🔴 `|| true` on every pytest/ruff step — **MOSTLY FIXED**. The sharper finding was that
>   ruff *never ran at all*: `uv run ruff` could not spawn it and `|| true` hid that for
>   months (`61b922e`). ava-skills is now a hard gate, personal-graphify is gated
>   (`21b3505`). Remaining suppressions are deliberate, and one is baselined in
>   `scripts/gate_audit_baseline.json` with a written judgment.
> - 🔴 `apps/dottie` in neither workspace members nor exclude — **STILL OPEN** after ten
>   days. `pyproject.toml:13` excludes only `apps/scout-rtx` and `apps/ava-factory`.
> - 🟡 "Eval gate quick" is dead — **FIXED** (`f41718b`). Worse than dead: the module path
>   is unimportable *and* no `cli.py` ever existed there, and `| head -n 20` meant the step
>   already passed before `|| true` was reached.
> - 🟡 "Check factory imports" verifies nothing — **FIXED**. It now imports `dottie` and
>   `ava` (stdlib-only; the torch-dependent modules are deeper), so it can actually fail.
> - 🟡 skills count / 🟢 serve_engine path — fixed 2026-07-22 in `b5f3dcb`, per this file.

## Findings
- 🔴 .github/workflows/ci.yml:26-28 — every pytest step (and ruff at :23) ends `|| true`, so the CI badge at README.md:3 stays green even if all tests fail; only the forge/doctor smoke steps are real gates.
- 🔴 README.md:75-86 — the Monorepo Layout table and pyproject.toml:5-13 both omit `apps/dottie` (the Agent OS app README itself cites at line 29): it has its own pyproject.toml yet is neither a workspace member nor in the exclude list, so it is untested and undocumented.
- 🟡 .github/workflows/ci.yml:37 — "Eval gate quick" runs `python -m packages.ava-open-harness.cli`, an unimportable module path (hyphens), always erroring and masked by `|| true` — the eval-gate step is dead.
- 🟡 .github/workflows/ci.yml:49 — "Check factory imports" only does `sys.path.insert(...); print('factory importable')` without importing any factory module, so the dottie-factory-smoke job verifies nothing.
- 🟡 README.md:31,82 — skills row lists 8 skills but packages/ava-skills/skills/ contains 9 (family-brain-wiki omitted), and "memory-mint/router + 9 skills" overcounts (9 total including mint/router).
- 🟢 README.md:28 — `dottie/serve_engine.py` exists only as apps/ava-factory/dottie/serve_engine.py (prefix omitted in README); all .gitignore claims (telemetry, STATUS.json, logs/ via apps/ava-factory/.gitignore:10) and every Makefile target path verified real.

## Risk
- The badge is decorative: test regressions in ava-skills, ava-open-harness, or scout-cli merge silently while README advertises green CI.
- apps/dottie drifts unaccounted — no lint, no tests, no doc entry — so the repo's flagship "Agent OS" is the one component nothing validates.
- Dead eval-gate and import-smoke steps give false confidence that the "only passing ckpt promoted" doctrine is enforced anywhere in CI.

## Recommendation
1. Drop `|| true` from ruff/pytest steps in ci.yml (or make them required jobs) so badge state reflects test results.
2. Add `apps/dottie` to the README layout table and to pyproject.toml as a member (or exclude it with a stated reason), then wire its tests/ into Makefile `test` and CI.
3. Fix or delete ci.yml's "Eval gate quick" and "Check factory imports" steps; correct the skills count and serve_engine path in README.

## Evidence
```
$ grep -n "|| true" .github/workflows/ci.yml
23:  uv run ruff check ... || true
26:  uv run pytest packages/ava-skills -q || true
27:  uv run pytest packages/ava-open-harness -q || true
28:  uv run pytest apps/scout-cli/tests -q || true
37:  uv run python -m packages.ava-open-harness.cli --help ... || true
$ ls apps/            # dottie present, absent from README table + pyproject members/exclude
ava-factory  dottie  scout-cli  scout-rtx
```
