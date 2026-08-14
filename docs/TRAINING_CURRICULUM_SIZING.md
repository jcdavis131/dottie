# Training Curriculum Sizing — what this monorepo can teach a model

Measured inventory of self-labeling training material inside this repo, sized by a
four-lane audit run on 2026-08-09 (git history, plugin surface, test oracles,
run telemetry). Every count below was produced by a command run against the working
tree at that date; none are estimates unless marked. Companion to
`docs/LONGCAT2_INSIGHTS_SPEC.md` (the MOPD tier ladder this curriculum feeds) and
`docs/GRPO_PIPELINE.md`.

## Principle

The expensive part of training data is verification. This repo's development motion
already verifies almost everything it produces: tests gate code, checkers re-derive
baseline findings, manifests type tool capabilities, timelines record outcomes.
Curriculum extraction here is mostly *formatting*, not labeling.

## Ranked opportunities (episodes ÷ effort)

| # | Source | Episodes today | Growth | Label signal | Effort |
|---|--------|----------------|--------|--------------|--------|
| 1 | Verified-task climb loop (`apps/dottie` engine → flywheel) | 0 (generator unbounded: 5 task families × N seeds) | ~1,000/run | Deterministic per-family verifiers, continuous `r_task` | trivial — loop is fully wired |
| 2 | Pytest suites as binary oracles | ~2,456 hermetic-green scout-cli tests (+157 ava-skills/open-harness, +647 factory subset) | with codebase | Pass/fail exit code; per-file 0.9–3 s, whole small suites 4.6–12.7 s | trivial |
| 3 | Graded probe banks (`apps/ava-factory/evals/probe_items/`) | 1,341 gold-answer items; 2,400 graded outcomes in `branch_eval_results_real.json` (~12,000 across 5 report variants) | per eval run | Exact-match vs recorded gold answers | trivial |
| 4 | Plugin surface → tool-use dataset | 383 typed commands across 62 capability-declared manifests; 1,158 typed params; 1,598 canonical `scout …` example invocations; `ok()/err()` envelope with `example`+`discover` hints | with plugins | Envelope schema validation + capability policy tests | small |
| 5 | Baseline-judgment classification | 33 human-graded (finding → verdict → written rationale) pairs: `scripts/gate_audit_baseline.json` 10, `declared_capabilities` 13, `resolver_fallbacks` 6, `shell_true` 1, `leaks.json` 3 | per audit | Checker re-derives finding mechanically; judgment text is the gold rationale | trivial |
| 6 | Timeline → RFT ETL adapter | 25 events / 15 run dirs today; previously accumulated to 115 runs; regenerates on every harness invocation | per harness run | `status`/`errorClass`/`latency_ms`/`tokens` → existing ETL reward components (`apps/scout-cli/bigbang/plugins/rft/etl.py`) | small |
| 7 | Fix-commit repair episodes | 4 test-paired (red-before/green-after replayable via `uv run pytest`); +4–5 message-graded only; 1 six-step deploy correction chain | per fix | Checkout parent = before-state; paired test file = verdict | small |
| 8 | Structured post-mortems | 3 `lessons/ledger.jsonl` records (`signal/errorClass/cause/lesson/fix_now/prevention/confidence/paired`) + 4 `docs/LESSONS.md` entries mapped to real commits | per incident | `paired: true` failure→fix with confidence 0.85–0.92 | trivial |
| 9 | GRPO preference groups from real traces | 0 today; a 5×200 climb batch at group size 4 ≈ 250 groups / 500+ preference pairs | per climb batch | `rl_return` per rollout on verified tasks | small — needs the `traces.jsonl → dottie_telemetry.jsonl` bridge |
| 10 | Review/audit prose corpus | 10–15 docs (`knowledge/reviews/`, `tasks/artifacts/`) | manual | Human audit verdicts, prose only | large — manual curation |

Explicitly **not usable as-is** (honest exclusions): the 11-category frontier rubric
(`real_unimplemented` by its own audit; mock grades are seeded random, not
model-sensitive), the j-space 5-eval continuous reward (blocked on the gitignored
`runs/cpu_pilot/base/base_final.pt` checkpoint), and `self_distill_checkpoint.json`
(mock data by construction — `collect_mock_traces` fabricates 10k traces per run;
swapping in real traces is a *small* change, item 1 feeds it).

## The closed loop is ~80 % built

`apps/dottie/dottie/flywheel.py` already implements the retrain path as real
operations: engine traces → `export_rft_dataset` → the scout-cli RFT ETL →
versioned `rft_dataset.jsonl`; traces → `mint_memories` (ava-skills shards);
`POST /climb` drives engine → flywheel → optional harness eval → GRPO step.
What's missing is small and enumerated above: the telemetry bridge (#9), the
timeline adapter (#6), and replacing the mock trace collector (#1 feeds it).
The orchestration corpus + hill-climb trainer added under
`apps/ava-factory/` (see `LONGCAT2_INSIGHTS_SPEC.md`) close the routing tier.

## Curriculum ladder (MOPD tiers, each with a live gate)

| Tier | Task | Reward oracle | Material |
|------|------|---------------|----------|
| 0 | Emit valid `--json` envelopes | Envelope schema validation | #4 (1,598 canonical invocations) |
| 1 | Route goals to MoMA tiers | Orchestration corpus + hill-climb eval gate | timeline traces (#6) |
| 2 | Single tool calls against manifests | Capability policy tests | #4 + #5 judgments |
| 3 | Repair loops (forge / fix-commits) | Forge smoke tests; paired pytest verdicts | #2, #7 |
| 4 | Full harness runs (plan → execute → verify) | Critic score + timeline outcomes; verified-task `r_task` | #1, #6, #9 |

Inner-loop economics, measured: whole-suite oracles at 4.6 s (ava-open-harness) and
12.7 s (ava-skills) are cheap enough to run per episode; scout-cli is file-granular
for inner loops (0.9–3 s/file) with the 9-minute full suite as an outer gate only.
The 12-eval mock harness sweep runs in 0.47 s.

## Provenance

Lane reports generated by a four-agent read-only audit of this repo, 2026-08-09;
counts re-derivable via the commands each lane recorded (`git log`, `grep -c
'def test_'`, `find | wc -l`, timed `uv run pytest` invocations). Known caveats
carried forward: 6 scout-cli `test_policy.py` reds are manifest-drift
(`filesystem: true` bool vs dict) predating this branch; 1 order-dependent flake
(`test_forge_loop.py::test_self_evolution_loop_forges_tests_installs_and_reexecutes`
fails in-suite, passes alone); ava-factory's conftest `pytest_ignore_collect`
defeats `--ignore`, so episode selection there must use explicit file lists.
