# BLUEHENRE / Dottie — agent handoff (2026-07-23)

**Paste-able brief for any agent continuing this work. Everything below is live and verified.**

## CURRENT STATE (midday 07-23): trainer in final p5 stretch + hill-climb landed

- **Training run:** mini tool branch, step ~2760 of 2861 (~50 min to `done`),
  p5_anneal, healthy. Crash strikes: **2 of 3** (silent OOM-class kills at
  ~2536 and ~2566, both self-healed with ≤6 steps lost). STANDING ORDER: one
  more p5 crash = HOLD the run and page the operator on the steer thread —
  do NOT retry.
- **On `done` (armed, in sequence):** (1) mini eval harness on the new
  /ckpt/tool/tool_final.pt (exact invocation: memory dottie-evaluating-
  checkpoints), A/B vs **275.95 weighted ppl** (baseline preserved as
  tool_final_ext1.pt), post table to the steer thread; (2) vhdx compact
  (operator's elevated terminal — script at
  C:\Users\jcdav\.claude\jobs\c2138bb7\tmp\compact_vhdx.txt); (3) RESTART the
  research daemon (never live-reloads) — it then loads TODAY'S promotion gate
  + hints (below) and runs its 2 pending candidates; (4) run the parked hoops
  gate + equities suite (RAM frees post-run), commit those repos; (5) post the
  Leg-1 curriculum diff (tasks/artifacts/leg1_mini_diff.md) to steer,
  propose-first.
- **RAM is the binding constraint while training** (often <900 MB available;
  WSL VM died at ~281 MB once). One test suite at a time; check
  `(Get-Counter '\Memory\Available MBytes')` ≥ 900 first.

## What landed 2026-07-23 (hill-climb workflow, 22 agents + KG task — all committed)

- **Promotion gate (P0), commit 51a923e:** within-run SEM can NEVER promote;
  ab_nano paired-seed evidence demanded at promotion (subprocess runner,
  refusal on loss/missing/no-verdict); R93 regression test. Retro-flag report
  (tasks/artifacts/ledger_retroflag.md): **2 of 3 historical sota promotions
  were within-run-SEM-only artifacts.** Goes live at the daemon restart.
- **Repair hints, commit 79c699c:** level-scoped _LEVEL_HINTS + 5 runtime
  classes; replay coverage over 358 historical failures **71.2% → 100%**
  (scripts/replay_hint_coverage.py, runs on the ledger COPY).
- **Knowledge graph, commit c7a71ad:** stdlib-only apps/dottie/dottie/kg/
  (Graphify/Rootly/DeepRefine ideas, natively): 208 nodes/504 edges over
  incidents+experiments+events, every claim cited; `python -m dottie.kg.query`
  (preceded/hints/incidents/refine). Design: tasks/artifacts/kg_native_design.md.
- **Flywheel exporters, commit 084781b:** repair-transcript + gridiron
  forecast corpora → tasks/artifacts/corpus_proposals/ (proposal-only,
  nothing auto-ingests).
- **Console, commit 7fb2b29 (DEPLOYED + re-aliased):** contract checks 59→76;
  steer_poll selftest 10→32 (duplicate-ack no-op, clock-skew, audit schema).
- **Readiness pack, commit fde2fb7:** additive tool-selection probes,
  probe_error_analysis.py (14 tests), publisher hardening.
- **Publisher SWAPPED live (verified):** hardened version now runs the 10-min
  task (retry/backoff, stale-markers); rollback = copy
  scripts/publish_live_status_prev.py back over publish_live_status.py.
- **agent-eval repo (C:\Users\jcdav\agent-eval), commit e5c46a7:**
  expected_trajectory in all 8 tasks + presence-based matcher.
- **vector-pitch, commit 54e32a7:** rotation honors difficulty flag (6→13 tests).
- **vector-equities:** eval_sector_coherence.json now carries a structured
  `placeholder_contamination` block (2,200 rows, upward-bias stated);
  UNCOMMITTED pending its suite run; re-export plan:
  tasks/artifacts/equities_reexport_plan.md.
- **Disk watchdog, commit 601f02c:** scripts/disk_watchdog.ps1 (propose-only
  prunes); task registration is PROPOSED not performed
  (tasks/artifacts/disk_watchdog_proposal.md).
- Plan of record + critique log: tasks/plan.md (v2).

## Mission
Build SOTA models faster by researching every piece of the stack → generate
insights with those models → turn insights into revenue. The org runs
autonomously on this box (RTX 4080, Windows + WSL2 Docker); the operator
steers from anywhere.

## What exists (all live)
- **Consoles:** amber terminal https://bluehenre-campus.vercel.app (mobile
  PWA) and org console https://www.bhenre.com/. Source: apps/bluehenre.
  Tests: `node apps/bluehenre/public/js/twin.contract.test.mjs` (76 checks).
- **Feed chain:** trainer → :8000/pipeline/status → publish_live_status.py
  (task "Dottie Status publisher", 10 min) → gist 929c3c0b… → hosted APIs
  (30-min caps).
- **Steer channel:** comments on gist c899ef776dcb81e99319239efa0f92ba;
  OWNER (jcdavis131) comments = directives; poll
  `python apps/bluehenre/scripts/steer_poll.py`, ack `🤖 ack <id>: <status>`.
  Fleet grammar: `fleet: start|stop|restart <container>` (closed allowlist).
  GitHub login IS the auth. Agents may only ever run it with `--selftest`.
- **Vector sites:** measured eval artifacts live (gridiron .690 Spearman;
  hoops 36.3% top-5; equities 1.56x w/ contamination block; pitch 61%
  in-band + rotation gate). Repos C:\Users\jcdav\vector-*.

## Runbooks (critical)
- **Deploy consoles:** `cd apps/bluehenre; vercel deploy --prod --yes` then
  **ALWAYS** `vercel alias set <deployment-url> www.bhenre.com`. Vercel CLI,
  never the MCP connector. (PowerShell 5.1: no `&&`.)
- **Trainer watch:** trust
  `docker exec dottie-factory-trainer-1 sh -c "tail /reports/metrics_mini.jsonl"`
  (docker logs can serve a stale stream after engine crashes).
- **Trainer `done` (exit 0) = schedule complete, NOT a crash.** Resume spikes
  loss (lr rewind) — recovers ~50 steps; never panic-revert. mb=1 is a FAILED
  experiment — never repeat.
- **WSL/disk crash:** free disk, `wsl --shutdown`, relaunch Docker Desktop,
  `docker start` all containers (trainer auto-resumes).
- **dottie test suite:** cd apps/dottie; set
  AVA_FACTORY_ROOT=C:\Users\jcdav\dottie\apps\ava-factory; .venv pytest.
  **36-40 engine/RL tests fail regardless** — they need ava/rl/codeact_loop.py
  which exists only in ava-agi-factory-v6-4's git HISTORY, not any working
  tree (pre-existing; operator open item). Today's scopes are green:
  test_eval_gates, test_validate_hints, test_research, test_kg,
  test_export_*.

## Standing orders (operator-approved, in force)
1. Completion sequence on `done` — see CURRENT STATE above.
2. p5 crash #3 ⇒ HOLD + page via steer.
3. Max 2 heavyweight builders while training; RAM ≥900 MB before any suite;
   keep ≥13 GB free on C:.
4. Propose-first for revenue surfaces (dumbmodel.com, bhenre apex) and for
   curriculum changes (Leg-1 diff posts AFTER eval).
5. Weekly STATE OF THE ORG digest on steer.

## Confirm-why doctrine (operator, 2026-07-22)
**"ALWAYS CONFIRM: why it is true."** Decompose every mechanism/state claim
into components (code path, config, runtime state, data); verify each against
its source; label assumed-not-confirmed components; state corrections plainly.

## Honesty doctrine (non-negotiable)
Numbers render only from real sources; stale = history, not telemetry;
unreachable = offline; nothing auto-ingests into training; contaminated
metrics carry machine-readable contamination blocks.

## Verify (fresh session)
```bash
docker exec dottie-factory-trainer-1 sh -c "tail -2 /reports/metrics_mini.jsonl"
curl -s https://bluehenre-campus.vercel.app/api/twin-status   # source:"local"
node apps/bluehenre/public/js/twin.contract.test.mjs           # 76 checks
python apps/bluehenre/scripts/steer_poll.py                    # steer queue
```

## Open items (operator decides)
- ava/rl/codeact_loop.py restoration (36-40 dottie engine tests unrunnable).
- agent-eval: scoreboard.md/results dirt from an earlier nano-chat run left
  uncommitted (it clobbers the qwen baseline detail — restore or accept).
- Gridiron: TWO unrelated histories on one remote (S2 scout's reconciliation
  proposal in the workflow journal); repo dirty on a claude/* branch.
- Hoops: gate parked on RAM (edits committed-ready in working tree,
  pipeline/ suite must pass first) — run post-`done`.
- Equities re-export post-GPU (tasks/artifacts/equities_reexport_plan.md).
- Disk-watchdog task registration (proposal ready); permanent
  www.bhenre.com project move; monorepo CI `|| true` (design note ready);
  ckpt-promotion eval gate (design note ready).
- Revenue instrumentation proposal awaiting operator read
  (tasks/artifacts/revenue_instrumentation_proposal.md).

Deeper context: HANDOFF.md (session log), apps/bluehenre/SPEC.md (spec of
record), tasks/plan.md (hill-climb plan + critique log), memory dir.
