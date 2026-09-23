# Meta research sequence — stages 1–6

Cam’s Meta-inspired research sequence, implemented as stdlib contracts in
`packages/dottie-loop`. No model is called. Nothing here trains, deploys, or
promotes. Factory promotion stays manual.

| stage | name | module | status |
|---|---|---|---|
| 1 | AdvancedIF-style rubric rewards | `dottie_loop/rubric.py` | landed |
| 2 | Correctness-gated code-optimization lane | `dottie_loop/opt_lane.py` | landed |
| 3 | AIRA2-inspired experiment architecture | `dottie_loop/experiment.py` | landed |
| 4 | Compute-as-Teacher | `dottie_loop/compute_teacher.py` | landed |
| 5 | S-EMBER causal memory | `dottie_loop/ember.py` + `memory.py` | landed |
| 6 | HyperAgents (proposal-only) | `dottie_loop/hyperagents.py` | landed |

Composition helper: `dottie_loop/research.py` (`compose_bundle`). CLI:
`python -m dottie_loop research rubric|opt-lane|compose|compute-teacher|ember|hyperagent`.

## How the six stages compose

```
transcript + versioned rubric + verifier
        │
        ▼
  rubric-eval (per-criterion audits,
               ungated_score, gated_score)
        │
        ├──────────► reward.compute_reward_with_rubric
        │            quality is 0 if task_ok is false
        │
        ├──────────► evaluation.merge_rubric_slices
        │            (EvalBundle.slice_results)
        │
calibrated timings + sandbox provenance + task_ok
        │
        ▼
  opt-lane-report
        │
        ├──────────► factory.speed_credit / factory.correctness
        │            factory.mlops.gate_opt_lane (correctness first)
        │
offline teacher artifacts + consented source records
        │
        ▼
  teacher-pack (compute_trace_id shards)
        │
        ├──────────► factory.mlops.gate_compute_teacher
        │            closed_loop.accept_teacher_pack
        │            (no live teacher, no training claim)
        │
fixed train/search/validation split
        │
        ▼
  experiment job ── claim ──► ResourceBroker
                                GPU → closed_loop.LeaseFile
                                (no second GPU lock)
        │
        ▼
  HiddenEvalPack.agent_view()   ← no labels
  HiddenEvalPack.score()        ← external consistent scorer
        │
causal edges (caused / blocked / confounded)
  + evidence pointer + measured predicate
        │
        ▼
  ember-eval (gated_score = 0 if provenance broken)
        │
        └──────────► evaluation.merge_ember_verdict
                     (opt-in; does not replace §24 GATES)
        │
hyperagent Proposal (sandbox destination only)
        │
        ├──────────► ExperimentQueue.submit   (allowed)
        ├──────────► apply_proposal           (always denied)
        └──────────► production_change        (always false)
        │
        ▼
  research-bundle (compose_bundle)
        │
        ▼
  promotion remains an operator action
```

Preserved on purpose:

- §22 anti-hacking in `reward.compute_reward` is unchanged unless you call
  `compute_reward_with_rubric`.
- §26 `LeaseFile` reclaim / heartbeat / expired-but-live rules are unchanged.
  Stage 3 will not acquire a GPU without that file. Stage 6 will not let the
  proposing agent claim that file.
- Dataset train/validation/test isolation and factory `promote` (print steps
  only) are unchanged.
- Hashes are sha256 of canonical JSON; new records use `ACTIVE_SCHEMAS`.

## Stage 1 — AdvancedIF-style rubrics

- `Rubric` + `RubricCriterion` are versioned (`major.minor.patch`) and digested.
- Kinds include `multi_turn` and `system_constraint` (complex / system policy).
- `RubricVerifier` is a Protocol; a plain callable also works.
  `ScriptedVerifier` is the deterministic fake for tests.
- `evaluate_rubric` writes one audit row per criterion (id, kind, weight,
  score, rationale, evidence).
- Hard gate: `gated_score = 0` when `task_ok` is false or `regression` is
  true. A perfect rubric cannot outrank a failed task in
  `compute_reward_with_rubric`.
- Unknown `task_ok` leaves quality null (not imputed).

## Stage 2 — correctness-gated opt lane

- `run_calibrated` / `calibrate_timing` reject one-shot timing
  (`warmup < 1` or `< 3` measured samples).
- Statistic is `median` or a linear-interpolation `quantile`.
- `SandboxProvenance` records kind, python, platform, hashed hostname, and
  env *names* (not values).
- `build_report` sets `factory.correctness` and `factory.speed_credit`.
  Speed credit is 0 when correctness fails.
- `opt_lane.factory_pass` and `factory.mlops.gate_opt_lane` both fail a
  fast-but-wrong report before looking at speed.

## Stage 3 — AIRA2 experiment architecture

- `ExperimentSplit` is a frozen train / search / validation membership.
  Overlap or an empty split is `InvalidInputError`.
- `HiddenEvalPack.agent_view()` strips gold/labels. `score()` is the only
  path to numbers; the scorer version must match the pack.
- `ExperimentQueue` is async in the submit/claim/complete sense (no event
  loop, no GPU run). Lineage records parent job, rubric eval, opt report,
  split digest, and a compact hidden-eval summary.
- `DebugResult` carries `traceback`, `hypothesis`, `fix_attempt`, status.
- `ResourceBroker`: cpu/disk are in-process exclusive leases; **gpu always
  delegates to `LeaseFile`**. Missing lease file → `BlockedError`, not a
  side-channel lock.

## Stage 4 — Compute-as-Teacher (offline)

**Idea.** Use *how* a solver spent compute (search tree, proof steps, unit
tests run) as the teaching signal, not only the final answer. The pack is
offline: the trainer later reads shards; there is no live teacher at train
time.

**What landed.** `dottie_loop/compute_teacher.py`:

- `ComputeTrace` (steps, branching, verifier outcomes) with a content hash.
- `TeacherRecord` / `TeacherConfig` config hooks (`require_artifacts`,
  `require_consent`, `require_redaction`; `allow_live_teacher` is denied).
- `synthesize_offline` packs consented, redacted source records with
  `compute_trace_id` shard fields. Consent/redaction reuse `dataset` /
  `capture` (`export_eligibility`, `redact_record`).
- A teacher record may attach to a `rubric-eval` or `opt-lane-report` only
  when `task_ok` is true (same hard gate). Attachment sets
  `quality_from_compute: false` — a long trace cannot raise quality.
- `closed_loop.accept_teacher_pack` and `factory.mlops.gate_compute_teacher`
  consume the pack. Missing file → `no_report`. Schema mismatch →
  `no_metric`. Empty / not-ready → `fail`. A pass does not train or promote.

**Operator run.**

```bash
# help (must work for the Jev local loop)
uv run python -m dottie_loop research compute-teacher --help

# dry-run accept a committed teacher-pack fixture (no GPU, no training)
uv run python -m dottie_loop research compute-teacher --dry-run \
  --file packages/dottie-loop/tests/fixtures/compute-teacher/pack.input.json

# pack.json may be a teacher-pack-1.0.0 or {traces, artifacts, consent_ledger, source_records}
uv run python -m dottie_loop research compute-teacher --file pack.json
# or point at a teacher-record list (missing path fails closed)
uv run python -m dottie_loop research compute-teacher --file pack.json --artifacts artifacts.json
```

The JSON envelope is a `teacher-pack-1.0.0` with `training: false` and
`factory.live_teacher: false`. `--dry-run` calls `closed_loop.accept_teacher_pack`
and exits `2` if the pack is not accepted. Feed `factory.ready` / `shards` to a
later trainer job; do not treat this command as a training run.

Fixture path:
`packages/dottie-loop/tests/fixtures/compute-teacher/pack.input.json`
(`teacher-pack-1.0.0` wrapping one `compute-trace-1.0.0`).

**Do not.** Run a real searcher or trainer. Do not store raw secrets from
tool output. Do not let a long compute trace raise quality when the task
failed. Do not claim a live teacher.

## Stage 5 — S-EMBER causal memory

**Idea.** Episodic memory with explicit cause → effect edges, so retrieval
can answer “what intervention changed this metric?”.

**What landed.** Extend `memory.py`; evaluate in `dottie_loop/ember.py`:

- New edge types `caused` / `blocked` / `confounded`. `add_edge` refuses
  them; `add_causal_edge` is the only write path.
- Each causal edge requires an evidence pointer (`trace` / `eval` /
  `incident` id) and a *measured* predicate (`gate_result`,
  `reward_component`, or `hidden_eval_mean`). Co-occurrence is not enough.
- Write-back still refuses hints below 0.4; causal edges need confidence
  ≥ 0.4. Synthetic or mock sources are `PolicyDeniedError`.
- `evaluate_causal_memory` scores edges against an evidence catalog.
  Missing or revoked catalog entries → `gate=provenance_broken`,
  `gated_score=0`. An empty store is `unmeasured`, not a pass.
- `evaluation.merge_ember_verdict` is opt-in: a passing §24 bundle cannot
  hide broken provenance. It does **not** add a member to `GATES` and does
  not change `compute_reward`. Provenance is a gate, not a quality score.

**Evaluation contract vs existing gates.**

| gate | module | what it can zero |
|---|---|---|
| task success | `rubric` / `reward` | quality / gated rubric score |
| correctness | `opt_lane` / `factory.mlops` | speed credit |
| §24 conjunction | `evaluation.evaluate_gates` | promotion verdict |
| provenance | `ember` + `merge_ember_verdict` | ember gated_score; opt-in bundle verdict |

**Do not.** Infer causality from co-occurrence. Do not write memory from
synthetic/mock evals. Do not touch `03_Meta_Work_ISOLATED`.

## Stage 6 — HyperAgents, proposal-only

**Idea.** Agents may *propose* experiments, opt-lane jobs, or train runs.
They may not acquire the GPU lease, consume a promote approval, or write a
release.

**What landed.** `dottie_loop/hyperagents.py`:

- `Proposal` record (digest-bound, destination, action).
  `production_change` is always false; production destinations and
  promote/release/deploy actions are refused at propose time.
- `approvals.ACTION_TYPES` now includes `experiment` so a human can issue
  a digest-bound approval against the proposal. The proposer cannot issue
  or consume that approval.
- `submit_from_proposal` may enqueue an `ExperimentJob`.
- `claim_from_proposal` of a GPU job still goes through `LeaseFile` and
  requires a named operator (`operator` / `human` / `runner`), not the
  proposing agent id.
- `apply_proposal` is always `PolicyDeniedError`, including when the actor
  is not the proposer and when `--approve-prod` is set.
- `promotion_from_proposal` calls `promote_guard` and then forces
  `production_change: false`. `evaluation.promotion_decision` remains the
  only real promotion path.

**Safety invariants.**

1. Proposals cannot self-apply. `apply_proposal` has no success path.
2. The proposing agent cannot claim GPU / job ownership.
3. No record from this module sets `production_change: true`.
4. Approval and promotion gates stay closed by default; `--approve-prod`
   is ignored on the hyperagent path.
5. Sandbox destinations only (`sandbox`, `experiment-queue`, `opt-lane`,
   `local`).

**Do not.** Give the proposer a second lease, a forge claim, or a
`--approve-prod` shortcut. Proposal-only means proposal-only.

## Tests

```bash
uv run pytest packages/dottie-loop/tests/test_rubric_rewards.py \
  packages/dottie-loop/tests/test_opt_lane.py \
  packages/dottie-loop/tests/test_experiment_aira.py \
  packages/dottie-loop/tests/test_compute_teacher.py \
  packages/dottie-loop/tests/test_ember.py \
  packages/dottie-loop/tests/test_hyperagents.py -q
uv run pytest packages/dottie-loop factory/tests -q
```
