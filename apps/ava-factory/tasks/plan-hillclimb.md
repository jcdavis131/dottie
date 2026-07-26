# Hill-climb: Ava → SOTA (auto-mode + 5m closed-loop)

Date: 2026-07-11 (rev)  
Mode: continuous iterate; data → arch → train → eval → repeat  
Active loop: `tasks/plan-closedloop.md` + `tasks/plan-syllabus.md`

## Objective

Maximize a scalar score with clear math, one lever per loop tick when possible.

```
Score = w1·(-log PPL_val) + w2·probe_acc + w3·route_KL_sep + w4·hl_fit − w5·DATA_STARVED_frac − w6·hang_frac
```

Initial weights (normalize later): `w = (1.0, 1.0, 0.5, 0.3, 2.0, 2.0)`.

## Phase order (do not skip)

1. **Data** — disk headroom, runway, dedup/clean quality, phase mix fidelity  
2. **Arch** — only after data runway stable ≥ lead for P0–P1  
3. **Train E2E** — when Score improves on a held eval snapshot  
4. **Eval + iterate** — freeze eval set; compare to previous best  
5. **Syllabus upgrades** — Polyak anneal, coding probe, mixture ablations (see plan-syllabus)

## Tick contract (every **5m**)

1. Read live metrics (disk, runway, last step lm/tok_s, step age, demand).  
2. Hang check (≥15m no step + GPU held) before other levers.  
3. Pick **one** bottleneck (reliability → data → demand → syllabus prep).  
4. Apply smallest reversible fix OR measure-only if blocked.  
5. Log delta in `tasks/hillclimb-log.md` (append one line).  
6. Stop hard only for: irreversible destroy, secrets, base1b GO/NO-GO, budget blowup.

Public eval only on fast ticks — cheap judge (probes J-Space PPL). Hidden eval off fast path; run nightly / T9.3 / Spec 11 gate. See benchbenchbench audit integration.

## Eval audit (benchbenchbench-style)

Every 5m tick uses public Score for selection. Separately:

- Nightly cron / T9.3 GO/NO-GO / Spec 11 arch candidate: compute hidden_score on `evals/hidden_faults/` (<100 items, never in `EVAL_SETS`, git-ignored, decontaminated but not public).
- Track decision-level metrics: Spearman rho, pairwise accuracy, regret@8, utility recovery = (top_public_hidden - mean_hidden)/(max_hidden-mean_hidden).
- Log to `reports/branch_eval_results_real.json` under `"audit"` and to `reports/REPORT_REAL.md` section "Decision-level holdout audit".
- Alert `bench_audit_degraded` in `dottie_telemetry.jsonl` when rho <0.58 or utility_recovery <0.93 (benchbenchbench hidden-only baselines 0.58/93.1%).
- Gate: arch candidates T11.2 DeltaNet / T11.4 MatFormer require rho>=0.55 and recovery>=0.93 before adoption — prevents cheap-judge overfit at large batch (matches 2607.20548v1 batch-scaling concern).

Full spec: `docs/BENCHBENCHBENCH_AUDIT_INTEGRATION.md`

## Data gates (must be green before arch work)

| Gate | Math | Target |
|------|------|--------|
| D1 host free | `free_gb(C:)` | ≥ 12 (pipeline `low_water_gb`) |
| D2 P0 runway | `tokens_ready(0)` | ≥ `packed_min` (200M) |
| D3 collector | not paused on disk | true |
| D4 dedup | `kept / read` on last pack | track; flag if &lt; 0.3 |

## Live baseline (session open)

- Mini training: step ~460, ~120M/2.5B tok, lm≈0.11, ~12k tok/s  
- Host free: **~1.6 GB** → collectors `disk < low_water`  
- Dash disk_free may still show VHDX (~987) — trust host probe
