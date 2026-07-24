# Monorepo review — 2026-07-22

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
