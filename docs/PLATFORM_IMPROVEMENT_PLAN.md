# Platform & Harness Improvement Plan

**Status:** Proposed 2026-08-09 · **Companion docs:** `LONGCAT2_INSIGHTS_SPEC.md`,
`TRAINING_CURRICULUM_SIZING.md`, `CONSOLIDATION.md`
**Evidence base:** the 2026-08-09 build/audit sweeps (subsystem maps, curriculum
audit, CI forensics) plus the full-budget training run completed the same day.

## 1. Where the ecosystem stands (measured)

**Platform.** dottie is the primary monorepo (consolidation adopted); bluehen is
deprecated pending merge of its PR; slasso.com serves the Validation Lab
dashboard + harness API in production; arxiviq/dumbmodel/jcamd are untouched and
live. Two draft PRs carry the day's work (dottie #11, bluehen #5).

**Harness.** `scout harness run` drives route → DAG → deterministic executors →
bounded recovery ladder → measured timeline/checkpoints → critic. Learned routing
(`route --learned`, `/api/route`) serves the champion in an advisory role.

**Training loop.** The corpus holds 1,519 records (704 measured — real
latencies, real statuses, measured-zero token cost, behavior labels from
executed routing). The full-budget hill-climb (8 variants × 200 epochs) produced
champion `orch-mlp-v1-v4`: **97.9% validation accuracy, 88.2% on 51 measured
held-out records**. The promotion gate evaluated real data for the first time
and correctly did **not** pass: the heuristic router scores 100% on labels it
generated itself, so "strictly beat the heuristic" is unwinnable on
behavior-cloned labels alone. This is the central finding of the review: **the
loop is built and running; what it lacks is label signal the heuristic doesn't
already own.**

**Debt registry (all pre-existing, all documented in CI threads):**
5 gate-audit candidates keep `lint-and-test` red on main and every PR;
`filesystem: true` booleans in 4 plugin manifests cause 6 policy-test reds;
the `dottie`/`dottie` package name collision keeps ava-open-harness
non-blocking; ruff debt stands at ~252 findings across 3 packages (ratchet);
ava-factory has 9 collection errors on non-docker boxes; the deprecated bluehen
repo still triggers 9 Vercel preview builds per push; one order-dependent flake
(`test_forge_loop`).

## 2. Plan

### P0 — CI to green, PRs merged (≈1 day, mostly operator sign-off)

1. **Judge the 5 gate-audit candidates.** Three are `recovery_ladder` copies
   whose fall-through is `escalate` — same fail-closed shape already judged for
   the runner's replica; the same judgment text applies. Two are
   `_routed_agents` in `harness/cli.py:69` — the membership-guard fix applied to
   the vendored port is behavior-identical and transplantable. Patch + baseline
   entries can be prepared for one-pass sign-off.
2. **`filesystem: true` → path allowlists** in agents/contacts/vector/harness
   manifests (propose the stores each plugin actually writes:
   `~/.local/share/bigbang`, `~/.cache/scout`). Clears the 6 policy reds.
3. **Fix the `test_forge_loop` order-dependent flake.**
4. Merge dottie #11 and bluehen #5; flip the API weights-fallback URL to `main`
   (one line); archive bluehen and disconnect its 9 Vercel integrations.

### P1 — Break the label ceiling (this week; unlocks the gate for real)

The gate needs measured labels the heuristic does not already produce. Three
sources, in order of signal quality:

5. **Real-failure executors.** Add a gate-guarded executor tier backed by
   existing capability-declared scout plugins (network on, per manifest).
   Real tool calls produce genuine failures and latency spreads → records where
   the "right" tier is no longer the heuristic's echo.
6. **Operator label corrections.** A small corrections file
   (`data/orchestration/label_corrections.jsonl`: runId → corrected tier,
   reason) surfaced through the dashboard's run table. Ten corrected runs are
   enough to make the measured hold-out discriminative.
7. **Outcome-adjusted labels.** When a run's critic score or recovery ladder
   shows the routed tier failed (e.g. `deterministic` chosen, nodes failed,
   replan escalated), derive the counterfactual label from the replan outcome —
   measured, and independent of the original routing.

8. **Continuous training Routine.** Nightly: harness battery (rotating goal
   grammar) → corpus rebuild → hill-climb (`--epochs 200`) → if champion val
   improves AND gate status is stable-or-better: vendor, dashboard rebuild,
   redeploy, PR-comment the delta. All pieces exist; the Routine is wiring.

### P2 — Harness capability (2 weeks)

**Status 2026-08-09: the nightly cycle is automated.**
`apps/ava-factory/scripts/flywheel_cycle.py` runs collect → mine → train →
gate → sync → dashboard as one fail-closed command with a machine-readable
summary (`reports/flywheel/cycle-summary.json`); the nightly Routine invokes
it and the session performs only the privileged deploy step when
`deploy_required` is true. Adversarially verified (fail-closed, correctness,
provenance lenses) and proven with a live cycle: gate evaluated honestly
(not passed, 0.877 vs heuristic 0.893 on n=57), weights untouched, meta and
dashboard refreshed. Design note: the live API serves the latest trained
champion in ADVISORY mode (documented on the dashboard with the NOT PROMOTED
badge) via the committed reports/ URL — when strict gate-gated serving is
wanted, point the weights URL at a path only the promoted path writes
(`apps/dottie-harness-api/lib/weights/`). Remaining P2 items below.

9. **Flywheel bridges** (all sized "small" in `TRAINING_CURRICULUM_SIZING.md`):
   timeline → RFT ETL adapter; traces → telemetry bridge so GRPO builds real
   preference pairs; replace `self_distill.py`'s mock trace collector with real
   harness traces.
10. **Learned-router promotion path.** When the gate passes: champion becomes
    the default in `route`, heuristic stays as guardrail, disagreements logged
    to the timeline (each disagreement is future training signal).
11. **Checkpoint resume** (`harness run --resume <runId>`) via the existing
    dag_version replan contract — pause/resume across days.
12. **Deferred LongCat items:** compute-once timeline-stats reuse in graph-plan;
    per-tier efficiency budgets as an eval-gate category.

### P3 — Foundation model track (needs the RTX box)

13. Run nano-1K per `DOTTIE_NANO_1K_SPEC.md`; drive `distill_ladder.py` with
    real on-policy rollouts (unblocked by the model-load fix).
14. Engram embeddings for DottieModel1B and muP wiring behind the house
    adopt/decline review artifact (next free spec number), per the frozen-path
    doctrine.
15. **Curriculum datasets** from the sizing report: tier-0 envelope adherence
    (1,598 canonical invocations), tier-2 tool calls (62 typed manifests),
    tier-3 forge/fix-commit repair episodes — extractors + dataset cards
    published through the validation playbook.

### P4 — Platform hygiene (background cadence)

16. Resolve the `dottie`/`dottie` package collision (operator architectural
    choice; three options documented in the gate-audit baseline entry).
17. Ruff ratchet: scout-cli is at 32 findings — drive to 0 and flip it to a
    hard gate per the documented ratchet discipline.
18. ava-factory CPU-image deps: either add zstandard/datasketch/tokenizers to a
    cpu extra or mark the 9 collection-error modules docker-only explicitly.
19. Playbook cadence: scoreboard + ops digest on a schedule; research-brief
    refresh when orchestrator reports change; dashboard rebuilt only from
    committed sources (freshness guard already in the generator).

## 3. Sequencing and the one metric that matters

P0 is sign-off work and unblocks everything green. P1 is the strategic move:
until measured labels diverge from the heuristic, no amount of training can
legitimately promote the learned router — items 5–7 create exactly that
divergence, and item 8 makes improvement continuous rather than manual. P2
converts the harness from demonstrator to workhorse. P3/P4 proceed in parallel
as hardware and operator time allow.

Single tracking metric proposed for the dashboard: **measured held-out records
whose label did not come from the heuristic** (today: ~1, the journal record in
val). The gate — and honest promotion — unlock as that number grows.
