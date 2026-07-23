# Design: remove CI `|| true` swallowing (monorepo review 2026-07-22, item #3)

Status: L2 design only, no config changed. Every occurrence below re-verified on this box
2026-07-23 by grep over the monorepo (`.claude\worktrees\**` excluded).

## 1. Complete inventory of swallowed steps

### CI configs proper (GitHub Actions)

Verbatim grep hits, `C:\Users\jcdav\dottie`:

```
.github\workflows\ci.yml:23:        run: uv run ruff check packages/ava-skills packages/ava-open-harness packages/personal-graphify apps/scout-cli --exclude apps/scout-cli/.venv || true
.github\workflows\ci.yml:26:          uv run pytest packages/ava-skills -q || true
.github\workflows\ci.yml:27:          uv run pytest packages/ava-open-harness -q || true
.github\workflows\ci.yml:28:          uv run pytest apps/scout-cli/tests -q || true
.github\workflows\ci.yml:37:          uv run python -m packages.ava-open-harness.cli --help 2>&1 | head -n 20 || true
```

Same-class swallows in CI configs that are not literal `|| true`:

- `.github/workflows/ci.yml:21` — `uv sync --all-groups --frozen || uv sync`: lockfile
  drift is silently forgiven (fallback re-resolves). Soft swallow.
- `packages/ava-open-harness/.github/workflows/openwiki-update.yml:25` —
  `openwiki code --update --print || echo "openwiki update failed"`. Note this whole file
  is decorative: GitHub only executes workflows from the repo-root `.github/workflows/`,
  never from a nested package dir. Two honest options: delete it, or move it to root if the
  job is wanted.
- `.github/workflows/lint.yml` — CLEAN. No `|| true` anywhere; already an honest gate.

### Adjacent (dev-loop, NOT CI — listed for completeness, out of scope)

```
Makefile:5:	uv run pre-commit install || true
Makefile:14:	uv run ruff format --check packages/ava-skills packages/ava-open-harness packages/personal-graphify apps/scout-cli || true
```

Shell scripts under `apps/ava-factory/scripts/*.sh` contain ~25 more `|| true` (cleanup
`kill`s and best-effort loop steps). Those are runtime loops, not CI gates — explicitly not
in this change.

### Dead steps masked by the swallowing (must be repaired or deleted, not just un-swallowed)

- `ci.yml:34-37` "Eval gate quick (nano)": `python -m packages.ava-open-harness.cli` is an
  unimportable module path (hyphens are not valid in module names). The step has never
  done anything; `|| true` hides the guaranteed failure. Import root is `harness`
  (review learnings), so the honest replacement is an import/CLI smoke on `harness`.
- `ci.yml:47-49` "Check factory imports": `python -c "import sys; sys.path.insert(0, 'apps/ava-factory'); print('factory importable')"`
  imports nothing — it prints after inserting a path. `import dottie` is safe to add: the
  package `__init__` is PEP 562 lazy by design (no torch, stdlib-only;
  `apps/ava-factory/dottie/__init__.py:11-16`), so it runs on the bare CI python.

## 2. Un-swallow diff sketch (`.github/workflows/ci.yml`)

```diff
       - name: Sync workspace (light packages)
-        run: uv sync --all-groups --frozen || uv sync
+        run: uv sync --all-groups --frozen
       - name: Ruff lint
-        run: uv run ruff check packages/ava-skills packages/ava-open-harness packages/personal-graphify apps/scout-cli --exclude apps/scout-cli/.venv || true
+        # Deleted: lint.yml is the single lint gate (ruff==0.8.6, whole repo, no || true).
+        # Keeping a second, differently-scoped ruff here doubles the red for the same debt.
       - name: Pytest skills + harness
         run: |
-          uv run pytest packages/ava-skills -q || true
-          uv run pytest packages/ava-open-harness -q || true
-          uv run pytest apps/scout-cli/tests -q || true
+          uv run pytest packages/ava-skills -q
+          uv run pytest packages/ava-open-harness -q
+      - name: Pytest scout-cli (must run from its own root — CWD-relative fixtures)
+        run: |
+          cd apps/scout-cli
+          uv run pytest tests -q
       - name: Eval gate quick (nano)
         run: |
-          # Quick J-Space sanity, no GPU
-          uv run python -m packages.ava-open-harness.cli --help 2>&1 | head -n 20 || true
+          # Harness import smoke, no GPU (module root is `harness`, not the package dir name)
+          uv run python -c "import harness; print('harness importable')"
```

And in the `dottie-factory-smoke` job:

```diff
       - name: Check factory imports
         run: |
-          python -c "import sys; sys.path.insert(0, 'apps/ava-factory'); print('factory importable')"
+          python -c "import sys; sys.path.insert(0, 'apps/ava-factory'); import dottie; print('factory importable', dottie.__version__)"
```

## 3. Which suites must be green BEFORE un-swallowing (with local evidence)

| Gate | Local state (evidence) | Blocker? |
|---|---|---|
| `pytest packages/` (ava-skills + ava-open-harness + personal-graphify) | **180 passed, 4 skipped** in 14.3s, 2026-07-22 review; skips are honest torch/checkpoint-absent skips | No — green today |
| `pytest apps/scout-cli/tests` | **130 passed from `apps/scout-cli`; 6 FAIL from repo root** (CWD-relative fixture paths, review evidence) | YES — the step must `cd apps/scout-cli` first (diff above) or those 6 go red |
| ava-skills collection count | bare `pytest` from its root collects **80** tests vs 66 under other invocations (test-board memory note) | Verify the CI invocation collects the full set: compare `uv run pytest packages/ava-skills -q --collect-only -q | tail -1` against 80 before trusting the green |
| ruff (`lint.yml`, 0.8.6, whole repo) | **NOT green — 491 pre-existing errors**; TODOS.md:3482-3484: "lint.yml ... is the one that goes RED ... pre-existing" | Blocks any un-swallowed ruff step; hence the delete-from-ci.yml choice. Lint cleanup is its own sequenced task (pin `ruff==0.8.6` locally for the format step — TODOS.md:3470-3475) |
| `uv sync --frozen` | Review ran `uv sync` OK; `--frozen` specifically unverified on CI | Run `uv sync --all-groups --frozen` locally once before removing the fallback; if the lockfile drifted, re-lock first |
| Forge smoke + telemetry check (ci.yml:29-33, 50-53) | Already un-swallowed and passing (TODOS.md:3476-3481: all three blocking checks pass) | No change |

## 4. Sequencing

1. Verify locally (RAM protocol first for the pytest runs): `uv sync --all-groups --frozen`,
   `uv run pytest packages/ava-skills -q` (+ collect-count check vs 80),
   `uv run pytest packages/ava-open-harness -q`, `cd apps/scout-cli; uv run pytest tests -q`,
   `uv run python -c "import harness"`, and the `import dottie` one-liner on a bare 3.11.
2. Land the ci.yml diff (one commit, operator-approved — this changes gate behavior, the
   review's documented deliberate non-action).
3. Watch the first CI run on main; expected: ci.yml GREEN, lint.yml still RED
   (pre-existing 491 — do not read as caused by this change; TODOS.md:3465-3469).
4. Separate follow-up: the 491-error lint cleanup to turn lint.yml green; delete or
   root-relocate `packages/ava-open-harness/.github/workflows/openwiki-update.yml`.
5. Only after ci.yml is honest does the README badge mean anything — until then local gate
   runs remain the real signal (review learning, monorepo-review-2026-07-22.md:46).
