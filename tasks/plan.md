# Ecosystem Hill-Climb — Dynamic Workflow Plan (v2, 2026-07-23)

v1 was critiqued by two independent adversarial agents (risk/feasibility +
value/mission); 22 critiques, all HIGH/MED accepted. v2 is the execution plan.
Critique log at bottom.

## Mission alignment (revised per value critique)
The plan now leads with the two items that move org-level numbers instead of
activity metrics: (P0) fix the research loop's promotion gate so it stops
laundering seed noise into fake wins (root cause of REAL WINS = ZERO), and
(P1) prep the post-training hour — the scarcest resource is the GPU-free
window ~2h away. Hygiene and polish run behind those.

## Guardrails (v2 — every agent prompt embeds these)
- **G1 TRAINER FREEZE**: no edits to `apps/ava-factory/dottie/**` or
  `apps/ava-factory/configs/**` (bind-mounted into the live trainer; strike 2
  of 3). `scripts/`, `docs/`, `evals/` (additive only) are host-side — verified:
  no compose file consumes `scripts/`. NO docker commands by any agent. No GPU,
  no model loads of ANY kind (incl. sentence-transformers, Ollama) — static
  analysis only.
- **G2 RESOURCE**: RAM is the binding constraint (1,039 MB available at
  dispatch; WSL VM died at ~281 MB once). HEAVY lane (anything running a test
  suite) is strictly SERIAL — one at a time, verifier included. Before any
  suite: check `(Get-Counter '\Memory\Available MBytes')` ≥ 900; below → recheck
  once, then park item as ENV-CONSTRAINED. Disk floor 15 GB unchanged.
- **G3 NO SIDE-EFFECTS from agents**: no commits, no pushes, no checkout/
  stash/reset, no scheduled-task changes, no deploys, no steer-channel network
  calls (steer_poll only ever with `--selftest`; live polling is main-loop
  only). Publisher edits go to a `_next.py` copy — main loop does the swap
  inside a disabled-task window. Exclude `.claude\worktrees\**` from every
  search and edit.
- **G4 CONFIRM-WHY**: builders paste real command output; independent
  verifiers re-run gates fresh from the correct root/interpreter and try to
  refute. Verdicts: CONFIRMED / REFUTED (one retry with refutation attached) /
  ENV-OUTAGE (docker/endpoint unreachable — requeue, never refute) /
  ENV-CONSTRAINED (RAM/disk — park).
- **G5 INTERPRETERS (pre-verified)**: apps/dottie → `apps\dottie\.venv`;
  vector-hoops → root `C:\Users\jcdav\vector-hoops\pipeline`, its `.venv`;
  vector-pitch / vector-equities / agent-eval → global `python` (3.11.9,
  pytest 9.1.1). No `py` launcher on this box. PowerShell is 5.1 (no `&&`);
  MSYS bash mangles leading-slash args.
- **G6 BASELINE SNAPSHOTS**: each builder records `git status --porcelain`
  before touching a repo; verifier diffs against that, not against clean.
  Known pre-existing dirt: vector-gridiron is on branch
  `claude/model-training-workflow-plan-n5vep5` with modified assets — document,
  never touch.

## Phase 1 — SCOUTS (parallel, read-only, light)
- S1 hoops: the 7 failures (root pipeline/, venv pinned) + dead arena steps.
- S2 gridiron: real refs are `master`, `origin/main`, `origin/master`, the
  claude branch; map divergence via `git log`/`diff ref..ref` ONLY; output a
  reconciliation proposal (operator decides).
- S3 equities: placeholder provenance, CPU-feasibility STATIC-ONLY (model
  name/dims from code + row count × published throughput; loading a model =
  abort).
- S4 ledger mining: COPY ledger.sqlite3 first, read the copy (live daemon
  writes it — scheduled task "Dottie Research runner" is Running). Uncovered
  failure classes + 3 examples each + proposed hints + a sample of
  failure→hint→fix transcript pairs for the flywheel exporter.
- S5 agent-eval (RETARGETED to `C:\Users\jcdav\agent-eval`): 7 of 8 tasks lack
  `expected_trajectory`; draft blocks per task from task.yaml + scripts/.
- S6 console: parser coverage gaps + steer_poll hardening list (offline).
- S7 publisher: silent-failure paths in publish_live_status.py with line refs.

## Phase 2 — BUILDS
**HEAVY lane (strictly serial, each followed by its verifier):**
1. **B0 promotion-gate (P0, apps/dottie, no scout dep)** — make paired-seed
   evidence a HARD promotion gate in evaluate.py (within-run SEM alone can no
   longer promote; the R93 4.4-SEM-then-worse-at-3-seeds case becomes a
   regression test). Plus a retro-flag REPORT (ledger read-only) of baselines/
   promotions set under the old rule. Check whether the daemon evaluates
   in-process or per-candidate subprocess and report. Org metric: promotion
   false-positive mechanism closed; daemon picks it up at the already-ordered
   post-eval restart.
2. **B1 research-hints (needs S4)** — new hint classes + tests; org metric:
   replayed-ledger hint-coverage before/after (report both), measured on the
   COPY.
3. **B4 agent-eval trajectories (needs S5, repo `C:\Users\jcdav\agent-eval`)** —
   expected_trajectory for all 8 tasks + matcher green + a queued, ready-to-run
   scored-eval command for the post-training window. Org metric: agent-eval
   axis becomes measurable beyond 0/1 tasks.
4. **B3 pitch rotation gate** — gate honoring the difficulty-calibration flag,
   unit-tested. Hygiene-classified: capped effort.
5. **B-EQ equities (conditional on S3 CPU-feasible)** — re-export real
   embeddings for the 2,200 placeholder rows + re-run coherence eval; else:
   annotate the live artifact as placeholder-contaminated + add re-export to
   the readiness pack. Org metric: a public insight number stops being partly
   fake.
6. **B6 publisher hardening (needs S7)** — close silent-failure paths in a
   `publish_live_status_next.py` COPY (retry/backoff, stale-markers); dry-run
   proof; main loop swaps in a disabled-task window. Org metric: feed-staleness
   SLO protected.
7. **B2 hoops green (needs S1)** — fix 7 failures + dead code, from pipeline/
   root + venv; assets byte-identical. Hygiene-classified.
8. **B5 console hardening (needs S6)** — missing contract tests + steer_poll
   offline hardening + selftest extension. Hygiene-classified.

**LIGHT lane (docs/scripts, 2 at a time, runs alongside heavy):**
- **L1 post-run readiness pack (P1)** — (a) Leg-1 mini.yaml diff as PROPOSAL
  artifact (never touching configs/), rationale + eval placeholders, ready to
  post to steer; (b) `scripts/probe_error_analysis.py` (host-side) to classify
  per-probe failures post-run, fixture-tested dry-run; (c) ADDITIVE probe-
  breadth file (existing probe set untouched for A/B comparability).
- **L2 design notes** — ckpt-promotion eval gate (monorepo #2) + CI `|| true`
  removal (#3) + judge-interface one-pager (B7 collapsed to note per value
  critique: no servable judge model this cycle).
- **L3 disk watchdog** — `scripts/disk_watchdog.ps1`: report + allowlisted
  cache prune below threshold; checkpoint prunes REPORT-ONLY; task
  registration PROPOSED, not performed (operator open item).
- **L4 flywheel exporter** — repair-transcript corpus from the ledger COPY +
  gridiron forecast/actual rows → `corpus_proposals/` artifacts + audit notes.
  Proposal-only; nothing auto-ingests (honesty doctrine).
- **L5 revenue instrumentation PROPOSAL** — privacy-light analytics diff for
  the revenue surfaces + a visits/engagement field in the sites feed;
  propose-first per standing order 6, no deploys.

## Phase 3 — VERIFY (serial, inside the heavy lane)
Fresh re-run from correct root/interpreter; porcelain diff vs G6 baseline;
one adversarial input vs new logic; classification verdict (G4). ENV-OUTAGE
(e.g. trainer-done sequence takes docker down mid-verify) = requeue, never
refute.

## Phase 4 — INTEGRATE (main loop, not agents)
Commit per scope → cross-suite smoke → publisher swap (disable task, move
_next into place, enable, fire once) → console deploy + re-alias IF console
changed → CURSOR_HANDOFF update → hill-climb digest to steer thread.
Preempted by trainer `done` completion sequence (eval A/B → steer table →
compact → daemon restart, which then loads B0+B1 work).

---
## Critique log (v1 → v2)
Risk critic (12): RAM floor added + heavy lane serialized (was ≤2) [C1];
S5/B4/B7 retargeted to C:\Users\jcdav\agent-eval [C2]; steer_poll network
calls banned for agents [C3]; publisher via copy + main-loop swap window,
compose grep verified no container consumers [C4]; per-build porcelain
baselines + serial lane kills collateral-diff races [C5]; hoops root/venv
pinned, worktrees excluded [C6]; interpreters pre-verified & pinned, no
improvised installs [C7]; S2 refs corrected + git mutations banned [C8];
B1/S4/L4 read a ledger COPY, daemon-running noted [C9]; ENV-OUTAGE verdict
class added for the done-sequence race [C10]; shell quirks pinned in prompts
[C11]; global no-model-loads rule [C12].
Value critic (10): B0 promotion-gate added as P0 [V1]; L1 readiness pack
added as P1 [V2]; L5 revenue instrumentation added [V3]; B4 retargeted +
org-metric success [V4]; org metrics attached, hygiene items labeled [V5];
B-EQ promoted to conditional build [V6]; L4 flywheel exporter added [V7];
lane order rebuilt to mission leverage [V8]; B7 judge collapsed to note [V9];
L3 disk watchdog added [V10].
