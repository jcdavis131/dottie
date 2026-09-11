# Closed-Loop Spec — Continuous Dottie Training

**Status:** scaffold on `scout/dottie-closed-loop` · **NOT merged, NOT deployed**
**Components:** `pipeline/loop_trigger.py` · `playbooks/closed_loop.yaml` · this spec

## 1. Purpose

Close the deploy → monitor → retrain loop so Dottie training becomes
continuous instead of manual. The trigger watches production metrics,
queues retraining when a signal fires, gates canary evaluation, and —
only with explicit human approval — records a promotion. It never
deploys anything itself.

## 2. State machine

```
                        ┌──────────────────────────────┐
                        │            BLOCKED           │◄── missing/stale metrics
                        │  (fail-closed, alert, exit 2)│     (any state)
                        └──────────────┬───────────────┘
                                       │ metrics restored
                                       ▼
   ┌──────┐  signal   ┌───────────────┐  job done  ┌────────┐  pass  ┌──────────────────┐
   │ IDLE │─────────► │ RETRAIN_QUEUED│───────────►│ CANARY │──────► │ AWAITING_APPROVAL│
   └──┬───┘          └───────────────┘            └───┬────┘        └────────┬─────────┘
      │ ▲                                            │ fail                 │ --approve-prod
      │ │ cooldown                                   ▼                      ▼
      │ │                                       ┌───────────┐        ┌─────────────┐
      │ └───────────────────────────────────────│ DISCARDED │        │  PROMOTED   │
      │                                         └───────────┘        └──────┬──────┘
      │                                                                     │ baseline updated
      │ post-promote regression                                             ▼
      │ (ok_rate drop > rollback threshold)                            ┌────────┐
      └───────────────────────────────────────────────────────────────│  IDLE  │
                                                                      └────────┘
   ROLLBACK: PROMOTED ──regression──► rolled-back ──► IDLE (last-good checkpoint restored)
```

State lives in `pipeline/loop_state.json`. Baseline (the metrics a
promotion is measured against) lives in `pipeline/loop_baseline.json`.
Every transition appends one JSON line to `pipeline/loop_decisions.jsonl`
and emits one `LOOP_ALERT <json>` line on stderr.

## 3. Metrics → signal (thresholds in `playbooks/closed_loop.yaml`)

| Signal | Source | Default threshold |
|---|---|---|
| verifier regression | `hidden_files/cron_health.jsonl` (tail) | `< 8.0` (north-star floor) |
| agent failure rate | `workspace/artifacts/monitor/scoreboard.json` (min `ok_rate`) | `< 0.90` |
| drift vs baseline | min `ok_rate` vs promotion baseline | drop `> 5pp` |
| eval regression | `apps/ava-factory/*_eval_results.json` mean score vs baseline | drop `> 0.02` |
| fresh training data | verified `pref_pairs`/`trace_bank` rows since last train | `>= 500` new rows |
| canary acceptance | canary `eval_score` vs baseline | `>= baseline - 0.01` |
| post-promote rollback | min `ok_rate` vs baseline after promotion | drop `> 10pp` |

Timing: `cooldown_hours: 24` between retrain decisions ·
`approval_ttl_hours: 72` for a pending canary ·
`staleness_hours: 48` — metrics older than this are treated as **missing**
(fail-closed → `blocked`, exit 2).

## 4. Human approval gates (non-negotiable)

1. **Promotion NEVER happens without `--approve-prod` on the command line.**
   Without the flag the trigger writes `promote-blocked-needs-approval`
   (exit 3) and changes nothing.
2. Even with the flag, the trigger only writes a **promotion record**
   (`pipeline/loop_promotion_<ts>.json`) and updates the baseline. The
   operator executes the actual deployment step by hand, per the release
   runbook in `tasks/production_workflow.md` (G3 smoke before G4 alias).
3. Rollback likewise requires `--approve-prod`, except the automatic
   post-promote regression path, which only *flags* — the restore record
   still needs the operator's redeploy step.
4. Forge job **submission** (`--submit-forge`) is off by default; without
   it the job spec is only queued locally at
   `pipeline/loop_queue/pending/<job-id>.json`. Note: no Alienware runner
   is registered as of 2026-09-10, so submitted jobs will sit pending —
   the trigger reports this instead of failing silently.

## 5. Rollback procedure

1. Trigger (or operator) detects post-promote regression beyond the
   rollback threshold.
2. `loop_trigger.py --rollback --approve-prod` writes
   `pipeline/loop_rollback_<ts>.json` naming the restored checkpoint and
   sets state to `IDLE` with `prod_checkpoint = last_good_checkpoint`.
3. **Operator redeploys** the restored checkpoint through the normal
   release gates (G0–G5). The trigger does not touch serving.
4. Baseline stays at the last promotion's metrics until the next approved
   promotion — a rollback does not move the baseline, so a repeated
   regression keeps alerting instead of normalizing.

## 6. Alerting (no silent failures)

- Every decision: one `LOOP_ALERT` JSON line on stderr (cron captures it).
- Append-only `pipeline/loop_decisions.jsonl` — the audit trail; never
  truncated by the trigger.
- Fail-closed cases (missing config, missing metrics, stale metrics,
  unreadable canary report) exit non-zero with the cause in the decision.

## 7. Failure modes and what the trigger does

| Failure | Behavior |
|---|---|
| metrics file missing | `blocked`, exit 2, alert names the file |
| metrics stale (> 48h) | `blocked`, exit 2 — stale is not "fine" for training decisions |
| eval schema drift | reader tolerates `score`/`cap_score`/`value`/`composite`; none found → `blocked` |
| no trace banks yet | trace-count signal skipped (not a trigger), documented in metrics |
| Forge submit fails / no runner | decision records `forge_submitted.rc`; job spec stays in local queue |
| canary report missing | `blocked` — promotion path cannot proceed without it |
| operator never approves | state stays `AWAITING_APPROVAL` until `approval_ttl_hours`, then back to `IDLE` on next run (canary re-check required) |

## 8. Wiring

- Cron (hourly): `python3 pipeline/loop_trigger.py --decide` — evaluation
  only; writes decisions, alerts on signal.
- On `retrain-queued`: operator (or a second cron with explicit opt-in)
  runs `--queue-retrain [--submit-forge]`.
- Training completion (Forge result fetched) → operator writes
  `pipeline/loop_canary.json` (`{checkpoint_id, eval_score}`) → cron runs
  `--check-canary`.
- `--promote --approve-prod` / `--rollback --approve-prod`: human only.

## 9. Known gaps (not hidden)

- Pair-programming reward signal (accept/reject) doesn't exist yet — the
  current signals are proxy metrics (verifier, ok_rate, eval scores).
- The Forge `command` in `closed_loop.yaml` is a template; the operator
  must fill in the real training entrypoint before `--submit-forge`.
- No Alienware runner registered → training lane is queued-but-blocked;
  reported, not silent.
