# Monorepo review — 2026-07-22

> ## ⚠ Status re-verified 2026-08-01 — read this before acting on anything below
>
> These five files sat untouched for ten days. Every 🔴 was re-checked against the live
> tree rather than assumed still-true; **the body below is preserved as written and is
> now partly historical.** Verdicts:
>
> | finding | status 2026-08-01 |
> |---|---|
> | agent-os 🔴 `_domain_matches` substring bypass | **FIXED** — both bypass URLs return `False`, reproduced live |
> | agent-os 🔴 secrets axis default-ALLOW | **FIXED** — empty allowlist now denies, with an explanatory message |
> | factory 🔴 slim Dockerfile never COPYs `dottie/` | **FIXED** `f41718b` — and it was worse than reported (see factory.md) |
> | factory 🔴 `_point_latest_at` promotes unconditionally | **STILL OPEN** — FROZEN path, operator's call |
> | docs-metadata 🔴 every pytest/ruff step ends `\|\| true` | **MOSTLY FIXED** — ruff never actually ran at all (`61b922e`); ava-skills is now a hard gate, personal-graphify gated (`21b3505`). Remaining `\|\| true` are documented soft steps, one of them baselined with a judgment |
> | docs-metadata 🔴 `apps/dottie` in neither members nor exclude | **STILL OPEN** — unchanged after ten days |
> | docs-metadata 🟡 "Eval gate quick" is dead | **FIXED** `f41718b` — see below, it was worse than "dead" |
> | docs-metadata 🟡 "Check factory imports" verifies nothing | **FIXED** — it now actually imports |
>
> **The two dead CI steps were not merely weak — they could not fail.** "Eval gate quick"
> invoked a module path that is unimportable *and* has never existed, through a pipe that
> masked the exit code, then `|| true`'d the remains. "Check factory imports" adjusted
> `sys.path` and printed a success string without importing anything, so it passed on a
> tree with `apps/ava-factory` deleted.
>
> **`gate_audit.py` could not see either of them**, which is the more useful finding: shape
> B required the safety word on the suppressed line, and a CI step puts its purpose in
> `name:` and its command in `run:`. Fixed in `f41718b`, which immediately surfaced a
> second suppressed step. The auditor was also reading gitignored generated files, so its
> local verdict contradicted CI's — the precise way a ratchet earns itself a `|| true`.
>
> **Do not treat the "Gates run on this box" numbers below as current.** They were true on
> 2026-07-22. `pytest apps/scout-cli` in particular now reports differently, and the
> "CI badge is decorative" learning is no longer accurate.

10-phase review loop over `jcdavis131/dottie` (4 apps, 3 packages). Lane reviews: [agent-os](agent-os.md) · [factory](factory.md) · [packages](packages.md) · [docs-metadata](docs-metadata.md).

## Top 3 actions (ranked across all lanes)

1. **[agent-os] Close the two policy.py holes — the security story is currently nullified.**
   `_domain_matches` substring semantics let `http://evil.com/localhost` and `http://127.0.0.1.evil.com/x` pass the default-deny network allowlist (reproduced live), and an empty `capabilities.secrets.allow` grants *every* secret (default-allow, contradicting the docstring). Fix: exact-host/dot-suffix matching only; deny secrets on empty allowlist; add regression tests for both bypass URLs. Small diff, highest leverage.

2. **[factory] Wire the eval gate into checkpoint promotion — it is currently report-only.**
   `train.py:498` repoints `ckpt/latest` unconditionally after every save; serve hot-reloads it within ~5s; no eval verdict is consulted anywhere in the path. This contradicts the README's core "only passing ckpt promoted" doctrine. Fix: promotion script that runs the harness and only repoints on a promote verdict; keep `latest_candidate` for ungated checkpoints.

3. **[docs-metadata] Make CI real — every pytest/ruff step ends `|| true`.**
   The badge stays green regardless of test results; the "Eval gate quick" step invokes an unimportable module path (dead); the factory import smoke imports nothing. This is the enabling condition for #1/#2-class regressions merging silently. Fix: drop `|| true` (local evidence says pytest steps will stay green: 314 tests pass), repair or delete the two dead steps, add `apps/dottie` to workspace members or exclude with stated reason.

## Gates run on this box (the only real test signal while CI is decorative)

- `uv sync` — OK. Smoke-import `skills`, `harness`, `personal_graphify` — 3/3 OK.
- `pytest packages/` — **180 passed, 4 skipped** (14.3s; skips = torch/checkpoint absent, honest).
- `pytest apps/scout-cli` — **130 passed** (46.5s) *from apps/scout-cli*; from repo root 6 fail on CWD-relative paths (🟡 brittleness, not regression).
- Secrets scan — clean. Pattern hits are scrubber-test fixtures (`AKIAIOSFODNN7EXAMPLE`); gitignore claims for telemetry/STATUS/logs verified real.
- Live smoke — arxiviq.com HTTP 200 with expected console content, bounded retries, read-only.

## Per-lane counts

| Lane | 🔴 | 🟡 | 🟢 | Standout evidence |
|---|---|---|---|---|
| agent-os | 2 | 3 | 1 | Both bypass URLs reproduced live against policy.py |
| factory | 2 | 3 | 1 | Promotion path grep: no `verdict`/`eg_trend` consulted |
| packages | 0 | 3 | 3 | Anti-mock guard blind spot proven by mutation test (0.77 passes, 0.82 caught) |
| docs-metadata | 2 | 3 | 1 | `grep -n "|| true" ci.yml` → 5 masked steps |

## Fixed in this pass (cheap, safe, doc-only)

- README: `serve_engine.py` path prefixed with `apps/ava-factory/`; `family-brain-wiki` added to skills row; "memory-mint/router + 9 skills" → "9 skills incl. memory-mint/router" (commit `b5f3dcb`).

## Deliberate non-actions (documented, not oversights)

- **CI `|| true` removal not applied** — changes gate behavior; ruff wasn't run locally so badge could flip red on lint. Operator decision (top-3 #3).
- **431-test factory suite not run** — `ava-factory` is workspace-excluded and needs its own heavy env (Docker/GPU); this box has neither.
- **No deploys** — guarded action; smoke was read-only.
- **policy.py / train.py fixes not applied** — security- and training-adjacent; above the cheap-safe line for a review pass. Ranked top-2 instead.

## Learnings persisted

- CI badge on README is currently decorative — treat local gate runs as the real signal until top-3 #3 lands.
- scout-cli tests must run from `apps/scout-cli` (CWD-relative fixtures).
- Import roots are `skills` / `harness` / `personal_graphify`, not the package names.
- `apps/dottie` is in neither workspace members nor exclude — nothing lints or tests it today.
