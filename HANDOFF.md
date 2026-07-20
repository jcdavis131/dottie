# HANDOFF — Agentic Assistant Platform (dottie / ava-factory)

> **Solo personal project, no connection to employer, built with public/free-tier only — HOME only.**
> Discoverable entry point for any assistant session. Source of truth remains `TODOS.md` (living doc). This file is the top-down execution order.

**Status 2026-07-20T21:30 CDT (Hatch mirror):**
- Local Windows: `C:\Users\jcdav\dottie\HANDOFF.md` @ `33b6085` (user-created, 249 commits not yet on origin/main)
- Hatch VM: `~/workspace/dottie` @ `ebeb299` (ruff SOTA) — does NOT yet have HANDOFF.md on origin. Local-only until §00.
- Created deliberately as new file to avoid colliding with parallel ruff reformat session.

## Execution Order (exact)

**Prereqs:** `AVA_FACTORY_ROOT` must point to monorepo factory: `apps/ava-factory` (not legacy `ava-agi` checkouts). Verify with `scripts/README.md` before writing any scripts.

1. **00 — Reconcile git** (BLOCKING, makes HANDOFF public):
   - `git fetch origin` first (ops discipline)
   - Audit `origin/main` vs local 249 commits on Alienware (Windows box)
   - Merge/rebase ruff SOTA commits (`ebeb299`) + HANDOFF.md `33b6085` into single origin/main push
   - Timestamp check before any TODOS.md edit (`stat` + git log)
   - Acceptance: `git log --oneline origin/main -n 5` contains HANDOFF.md, no dirty fleet files

2. **05 / 5 — Re-seed baseline calibration**:
   - `cd apps/ava-factory && python scripts/calibrate-baseline.py` (measures baseline LM loss 5.61982 on factory mix)
   - Acceptance: `factory_lm_loss` written, `reports/` committed

3. **0 — Restart degraded WSL2 GPU stack** (CUBLAS flake, 780MHz clocks):
   - Host reboot (only reset that clears driver)
   - `docker compose up -d` fleet auto-heal, trainer resumes from `/ckpt/tool/latest` (crash-resume 719464e)
   - ETA ~3.5h for remaining ~344 steps of T9.3 tool branch to `tool_final.pt`

4. **1–8 — TODOS.md in order** (after 0, monitor armed #17):
   - **1.1**: Wait `tool_final.pt` (step ~1144, monitor fires)
   - **1.2**: `eval_branch_harness.py --ckpt /ckpt/tool/tool_final.pt` vs base, record `REPORT_REAL.md` — gate >2% regression fail
   - **1.3/1.4**: Pass→chat branch T9.4 (50M tok ~90min) or fail→file mode in TODOS §8 + adjust
   - **2.1**: Rebuild fleet `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml build && up -d` between runs
   - **2.2**: Verify mixture flow (tokens_ready rises, rejects <20%)
   - **2.3**: Retire old checkouts `ava-agi` → `*-RETIRED-20260719`
   - **3**: Promote mini, FactoryPolicy `DOTTIE_POLICY=factory`, A/B vs qwen3:8b ≥60%
   - **4**: Grow-init to base1b `python -m dottie.grow --src /ckpt/<winner>.pt`
   - **5**: Research loop (hourly ideation, `reviewgraph` into corrections, sota bundles)
   - **6**: Agent OS hardening (Hermes auto-forge, state-store telemetry)
   - **7**: arxiviq.com polish (gist live-status, brain badge)
   - **8**: Backlog ledger

## Ops Discipline (standing)

- `git fetch` first on every session
- Timestamp check (`git log --oneline -n 20` + file mtimes) before editing TODOS.md
- Read `scripts/README.md` before writing scripts (doctrine: every number measured, every gate real)
- Telemetry: `dottie/telemetry.py` → `reports/dottie_telemetry.jsonl` mode `training_monitor`
- Monitor: `python3 scripts/dottie_continuous_loop.py --mode monitor` (steps=9 stale=True data_starved=True as of 2026-07-20 19:57Z — data prep mode, 500k tokens)

## Honest Caveat

Local-only until 00 completes — origin/main does not yet contain the 249 commits from the parallel worktrees (factory loop, ruff SOTA, this HANDOFF). On Alienware it's discoverable now; on Hatch and arxiviq it becomes transparent after reconciliation push.

Paths: `C:\Users\jcdav\dottie\HANDOFF.md` @ 33b6085 + `~/workspace/dottie/HANDOFF.md` (mirror) @ ebeb299 base
