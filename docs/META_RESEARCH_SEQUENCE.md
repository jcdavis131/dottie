# Meta research sequence — stages 1–3

Cam’s Meta-inspired research sequence, implemented as stdlib contracts in
`packages/dottie-loop`. No model is called. Nothing here trains, deploys, or
promotes. Factory promotion stays manual.

| stage | name | module | status |
|---|---|---|---|
| 1 | AdvancedIF-style rubric rewards | `dottie_loop/rubric.py` | landed |
| 2 | Correctness-gated code-optimization lane | `dottie_loop/opt_lane.py` | landed |
| 3 | AIRA2-inspired experiment architecture | `dottie_loop/experiment.py` | landed |
| 4 | Compute-as-Teacher | — | follow-up |
| 5 | S-EMBER causal memory | — | follow-up |
| 6 | HyperAgents (proposal-only) | — | follow-up |

Composition helper: `dottie_loop/research.py` (`compose_bundle`). CLI:
`python -m dottie_loop research rubric|opt-lane|compose`.

## How the three stages compose

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
  Stage 3 will not acquire a GPU without that file.
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

## Follow-up — stages 4–6

These are intentionally **not** implemented. Each should stay a small
stdlib contract with tests, same fail-closed rules.

### 4. Compute-as-Teacher

**Idea.** Use *how* a solver spent compute (search tree, proof steps, unit
tests run) as the teaching signal, not only the final answer.

**Proposed integration.** New `dottie_loop/compute_teacher.py`:

- `ComputeTrace` (steps, branching, verifier outcomes) with a content hash.
- A teacher record that may attach to a `rubric-eval` or `opt-lane-report`
  only when `task_ok` is true (same hard gate).
- Dataset packing: a new optional shard field `compute_trace_id`; QA must
  refuse traces that lack consent / fail redaction (reuse `dataset.py`).

**Do not.** Run a real searcher or trainer. Do not store raw secrets from
tool output. Do not let a long compute trace raise quality when the task
failed.

### 5. S-EMBER causal memory

**Idea.** Episodic memory with explicit cause → effect edges, so retrieval
can answer “what intervention changed this metric?”.

**Proposed integration.** Extend `memory.py` rather than replacing it:

- New edge types `caused` / `blocked` / `confounded`, each requiring an
  evidence pointer (trace id, eval id, or incident id).
- Write-back still refuses hints below 0.4; causal edges need a *measured*
  predicate (gate result, reward component, or hidden-eval mean).
- Retrieval order stays as specified; contradictions remain exposed.

**Do not.** Infer causality from co-occurrence. Do not write memory from
synthetic/mock evals. Do not touch `03_Meta_Work_ISOLATED`.

### 6. HyperAgents — proposal-only

**Idea.** Agents may *propose* experiments, opt-lane jobs, or train runs.
They may not acquire the GPU lease, consume a promote approval, or write a
release.

**Proposed integration.** New `dottie_loop/hyperagents.py`:

- `Proposal` record (digest-bound, destination, action) that
  `approvals.py` can issue against.
- `ExperimentQueue.submit` from a proposal is allowed; `claim` of a `gpu`
  job still goes through `LeaseFile` and should require a human owner
  (or a named operator runner), not the proposing agent id.
- `promote_guard` / `evaluation.promotion_decision` stay the only
  promotion paths; a proposal must never set `production_change: true`.

**Do not.** Give the proposer a second lease, a forge claim, or a
`--approve-prod` shortcut. Proposal-only means proposal-only.

## Tests

```bash
uv run pytest packages/dottie-loop/tests/test_rubric_rewards.py \
  packages/dottie-loop/tests/test_opt_lane.py \
  packages/dottie-loop/tests/test_experiment_aira.py -q
uv run pytest packages/dottie-loop factory/tests -q
```
