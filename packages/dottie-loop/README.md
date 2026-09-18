# dottie-loop — the Dottie Full Ecosystem spec as code

`dottie_loop` implements the contracts and gates of the **Dottie Full Ecosystem
Specification v1.0** (baseline 2026-09-10) as typed, fail-closed, stdlib-only
Python. It is the deterministic backbone of the loop: goal intake, approvals,
plan graphs, timelines and checkpoints, opt-in pair capture, reward, dataset QA,
training preflight, evaluation gates, promotion and rollback, the closed-loop
trigger, the Forge job queue, and the benchmark builder.

No model is called anywhere in this package. It makes **no capability claim**:
`python -m dottie_loop spec status` reports `capability_claim: none`.

The review that motivated it, with the spec-versus-repository findings, is
[`docs/DOTTIE_ECOSYSTEM_REVIEW_2026-09-10.md`](../../docs/DOTTIE_ECOSYSTEM_REVIEW_2026-09-10.md).

## Module map

| Spec section | Module | What it pins |
|---|---|---|
| §05 intake, §37A | `intake.py` | `GoalEnvelope`, the eight-step validation order, state machine, durable idempotency (exact replay returns the goal; conflict is 409) |
| §07, §37C | `approvals.py` | scope lattice (effects default to denied), one-time digest-bound approval tokens; replay, expiry, destination and action mismatch all invalidate |
| §09 | `plan.py` | `PlanGraph` with all ten planner validations, `plan_hash`, `supersede`, receipt reuse rule |
| §10, §11 | `execution.py` | admit → hydrate → execute → observe → verify → commit; bounded recovery ladder; verifier budget (≥ 8.0, two loops); path/URL/argv sandbox rules; provider rate-limit hard stop |
| §14, §37A | `timeline.py` | append-only seven-field timeline with fsync; six-step checkpoint transaction; resume that blocks on corruption |
| §16, §17 | `capture.py` | off by default; `event → redact → validate → append → fsync`; export eligibility; P0–P3 rules |
| §22, §37B | `reward.py` | `R = 1.00·task_ok + 0.25·accept + 0.15·time + 0.15·quality + 0.10·token_eff` with every anti-hacking rule; preference pairs |
| §18–§20, §17 | `dataset.py` | hard-block QA chain, the accounting invariant, grouped-temporal split, `DatasetManifest`, reviewer approval, deletion propagation through lineage |
| §21 | `training.py` | `TrainRun`, ten preflight checks, hard-stop conditions, OOM single retry, resume/fork rules |
| §24, §25, §37C | `evaluation.py` | seven gates, five decision outcomes, canary requirements, `ReleaseRecord` with served verification, rollback + incident |
| §26 | `closed_loop.py` | thresholds as data, per-source event-time freshness, lease, cooldown from terminal timestamp, `--promote` guard that never changes production |
| §27 | `forge.py` | `JobSpec`, runner capability record, atomic claim, requirement filter, hash-verified inputs, argv-only execution, `FORGE_METRIC` parsing, orphan detection |
| §23 | `bench.py` | workflow runner, structural goldens, report with accounting that must reconcile; synthetic results excluded from evidence |
| research 1 | `rubric.py` | AdvancedIF-style versioned rubrics, per-criterion audit, pluggable verifier, hard task-success gate |
| research 2 | `opt_lane.py` | correctness-gated speed credit, warm-up + median/quantile timing, sandbox provenance, factory report shape |
| research 3 | `experiment.py` | AIRA2 train/search/validation splits, hidden consistent eval, resource jobs over existing `LeaseFile` |
| research 4 | `compute_teacher.py` | Offline Compute-as-Teacher pack: hashed traces, consent/redaction reuse, no live teacher, no training run |
| research 5 | `ember.py` / `memory.py` | S-EMBER causal edges with evidence pointers; provenance eval fails closed |
| research 6 | `hyperagents.py` | Proposal-only sandbox: may queue an experiment, cannot apply, claim GPU as proposer, or set `production_change` |
| §11, §37D | `errors.py` | error taxonomy, typed errors with HTTP status, API error envelope |
| §12 | `tools.py` | Scout tool plane: manifest minimum, result envelope, argv execution, secrets by brokered reference, redacted audit, dry-run, provider hard stop |
| §01, §36 Runbook A | `driver.py` | one goal end to end: intake → plan → kernel → verify → checkpoint → (opt-in) trace → reward; `loop run --spec` |
| §06, RT-16 | `surfaces.py` | Slack reporter (event-id dedupe, one post per state change, line cap) and the minimum web approval board (server-authoritative, CSRF, append-only decisions) |
| §15, RT-11 | `memory.py` | layered memory + graph edges; evidence-backed write-back with hints below 0.4; retrieval order and contradiction exposure; people resolution |
| §30 | `civilization.py` | T0 machines (zero-token pollers, deduped wakeups), T1 worker briefs and ten-line verdict-first reports, the decision ladder, token ledger |
| §32 | `observability.py` | correlation fields, no-orphan metric records, outcome SLOs with error budgets, alert dedupe by incident key |
| §33 | `incidents.py` | severity table, ordered lifecycle, suspected vs confirmed cause, quarantine window, DR drill checklist |
| §17 | `retention.py` | retention windows as data; deterministic, idempotent expiry with legal holds and deletion requests |
| §08, RT-03 | `router.py` | five tiers, the six-step decision order, learned advice only with artifact + schema + provenance (gate false → heuristic authoritative), safer tier below the confidence threshold, escalation only after a recorded insufficiency, forbidden private features; adapter for the harness-api heuristic |
| §13 | `skills.py` | SKILL.md frontmatter parser + package contract, one-stage-at-a-time lifecycle with required evidence and named rollback, mock benchmarks refused, canary needs an approval, progressive disclosure |
| §36 Runbooks B–C | `cli.py` | `feedback record`, `dataset release\|approve`, `train preflight`, `eval gates`, `approval issue\|consume` (persisted, replay-counted), `promote decide`, `release record\|rollback` — the operator drives the chain end to end with exit 2 on every block |
| §29 | `safety.py` | archive extraction that refuses traversal, links and bombs; JSON-only deserialization with size/depth caps; per-hop redirect re-checks against the allowlist (SSRF, rebinding); report redaction — plus the §29 test matrix in `tests/test_security_and_training.py` |
| §21, §19 | `curriculum.py` | selective training (excess loss, coverage floors, IDs + scores logged, hard examples kept), curriculum order, coupled + versioned anneal schedule, GRPO group construction (duplicates are not diversity; invalid/regressed → task zero; KL cap), balancing with caps and recorded sampling weights, health checks and stop decisions |
| §31 | `deploy.py` | build digest → candidate URL → pre-alias smoke → alias only after approval → cache-busted served-bytes verification; every step recorded, every failure typed |
| §26 | `closed_loop.LeaseFile` | single active retraining lease on disk: heartbeat extends, expired-but-live is not reclaimed, cooldown starts from the terminal timestamp |
| §10 RLM, §06 REPL | `rlm.py` | long context as named variables with provenance; bounded `rlm()` child calls (tokens, child-call count, depth) logged before and after as timeline events; stuck detector (repeated query / repeated failure / low confidence) that allows exactly ONE lateral lens then escalates; missions resume from the log |
| §16 | `capture.SessionRecorder` | multi-turn pair session from any surface: turns, actions, tool calls, corrections, feedback bound to the turn it answers, seven-field checkpoints; nothing persisted until `finalize` writes through the `CaptureWriter` |
| §24 | `evaluation.calibration` | expected calibration error + abstention rate from `(confidence, correct)` pairs; empty input is `unmeasured`, never a plausible zero |
| §06 API, §28, RT-17 | `surfaces.ApiServer` | fail-closed JSON API: bearer principals, `Idempotency-Key` required (202 created / 200 replay / 409 conflict), `/api/learned` is 503 until a learned artifact is loaded, routing rejections are typed 400/403 AND quarantined + alerted |
| §39 | `traceability.py` | the final acceptance artifact: session → trace → reward/QA → dataset → train run → checkpoint → eval → canary → approval → release → served verification → monitoring → rollback target as one graph; `validate_graph` names every unresolved arrow and every consequential edge missing its human authority; `spec traceability --dir` exits 2 until it is complete |
| §16, gap 02 | `feedback.py` | ONE recorder behind the CLI (`feedback record`), the API (`POST /api/feedback`), Slack (`SlackReporter.feedback_from_event`: reactions and first-word thread replies on a run's thread) and `scout loop feedback`: a signal is bound to the captured run it answers, appended as a superseding record, and the reward is recomputed with the surface as evidence |
| §17, §33, gap 06 | `cli.py` `retention expire`, `incident drill` | the expiry job (holds and deletion requests honoured, atomic rewrite, receipt beside the file, idempotent) and the restore-drill checklist (exit 2 unless every item is proven) as operator commands |
| §37A compatibility | `schema.migrate` | deterministic migrations that produce NEW records, preserve source ids, stamp the target schema themselves and write a migration manifest with before/after hashes and counts |
| §21.1 telemetry | `training.validate_telemetry`, `stop_condition_for`, `HeartbeatMonitor` | the fifteen telemetry fields; each hard-stop condition derived from a telemetry record; heartbeats as a separate cheap stream with a hang budget |
| §36 Runbook D, §37C | `incidents.PLAYBOOKS` / `playbook` / `open_from_playbook`; `dataset.Lineage.hold/save/load` + `privacy hold\|delete` | privacy deletion, credential exposure, prompt injection and provider block as ordered steps with required evidence and "never" rules; a deletion hold blocks export before deletion, a legal hold blocks deletion (exit 2, receipt `held`); receipts never restate private content or trace ids |
| §36 Runbook A | `execution.Kernel.cancel` | cancellation stops dispatch, marks pending external effects `unknown_until_checked`, appends actor + reason as a run event, deletes nothing and implies no rollback |
| §04, §34 | `components.py` + `spec components --root` | the component table as data; presence reported from the tree, never from the spec's status column |
| §25, Runbook C 9–12, ML-13 | `canary.py` | a canary whose plan must be complete, whose every event names the incumbent or the challenger (else rejected), whose safety threshold is stricter than the primary metric, whose decision packet exists only at the predetermined stop or an explicit manual stop, that cannot be extended to chase a win, and whose stale events never make a packet; the packet is what `promotion_decision` consumes |
| Runbook B 16, RT-14 | `dataset.canary_deletion_test`, `mark_release_usable` | deletion propagation proven on a non-production canary record (on a copy of the lineage) before an approved manifest can be marked usable |
| ML-07 | `training.reproducibility_check` | identical inputs = same config digest and seed; compatible = every shared metric within tolerance; a metric on one side only is a finding |
| §37D pagination | `ApiState.list_goals`, `GET /api/goals` | opaque HMAC cursors bound to the caller's scope: another principal's cursor is 403, a tampered one is 400 |
| §38, §39 | `acceptance.py` + `spec acceptance` / `spec done` | RT-01…17 and ML-01…17 as data with the tests that name them (ranges like `ml09_to_ml13` parsed); the thirty §39 done items with kind `mechanics` or `operator`: a test proves mechanics only, an operator item needs an explicit `{proven, ref}` record, and `spec done` exits 2 until every item is proven — nothing in the package can make it exit 0 alone |
| §27 | `scripts/forge_runner.py` | the one file for the GPU box: advertise → poll → claim → checkout → execute → push results over a git conveyor |
| research 1 | `rubric.py` | AdvancedIF-style versioned rubrics, per-criterion audit, pluggable verifier, hard task-success gate |
| research 2 | `opt_lane.py` | correctness-gated speed credit, warm-up + median/quantile timing, sandbox provenance, factory report shape |
| research 3 | `experiment.py` | AIRA2 train/search/validation splits, hidden consistent eval, resource jobs over existing `LeaseFile` |
| research 4 | `compute_teacher.py` | Offline Compute-as-Teacher pack: hashed traces, consent/redaction reuse, no live teacher, no training run |
| research 5 | `ember.py` / `memory.py` | S-EMBER causal edges with evidence pointers; provenance eval fails closed |
| research 6 | `hyperagents.py` | Proposal-only sandbox: may queue an experiment, cannot apply, claim GPU as proposer, or set `production_change` |
| external research (Jev) | `backend_signal.py` | Naming/provenance discipline for an external backend's probability: `backend_confidence`, never `confidence`; audit-only, never gates |
| external research (colibri) | `manifest.py` | Two-arm experiment evidence: every headline number re-derived from raw samples, run order required to gate, failed baseline refused |

## CLI

```bash
uv run python -m dottie_loop spec status
uv run python -m dottie_loop goal submit --store /tmp/goals --subject me --json '{"idempotency_key":"k1","intent_text":"summarize the README"}'
uv run python -m dottie_loop loop evaluate --sources metrics.json --promote        # exits 2 (blocked) on stale metrics
uv run python -m dottie_loop forge runners --root ~/workspace/forge               # exits 2 until a runner is registered
uv run python -m dottie_loop bench smoke
uv run python -m dottie_loop loop run --spec run.json --store /tmp/loop --root . --subject me   # one goal end to end
uv run scout --json loop status                                                     # same contracts behind the single tool surface
# the operator chain (each step exits 2 when its gate blocks)
uv run python -m dottie_loop feedback record --store /tmp/loop --run-id run_… --signal accept
uv run python -m dottie_loop dataset release --traces /tmp/loop/traces/pair.jsonl --out /tmp/ds --consent-ledger ledger.json
uv run python -m dottie_loop dataset approve --manifest /tmp/ds/manifest.json --reviewer independent
uv run python -m dottie_loop train preflight --run train.json --manifest /tmp/ds/manifest.json --checks checks.json
uv run python -m dottie_loop eval gates --bundle bundle.json --out gates.json
uv run python -m dottie_loop approval issue --store approvals.json --approver cam --action promote --payload '{"artifact":"…"}' --destination production --goal-id loop
uv run python -m dottie_loop promote decide --gates gates.json --canary canary.json --approval-consumed
uv run python -m dottie_loop release record … --served-sha <hash fetched from production> --out release.json
uv run python -m dottie_loop release rollback --release release.json --served-sha <incumbent> --reason drill --out rollback.json
# the §39 final proof: every record the chain wrote, in one directory, as one graph
uv run python -m dottie_loop spec traceability --dir /tmp/chain --out graph.json   # exits 2 naming each arrow that does not resolve
uv run python -m dottie_loop spec schemas
uv run python -m dottie_loop retention expire --records records.jsonl --holds holds.json --deletions deletions.json
uv run python -m dottie_loop incident drill --results drill.json                     # exits 2 naming the unproven items
uv run scout --json loop feedback --run-id run_… --signal accept                      # the same recorder, from the tool surface
uv run python -m dottie_loop privacy hold --lineage lineage.json --key <deletion key> --operator cam
uv run python -m dottie_loop privacy delete --lineage lineage.json --key <deletion key> --operator cam --out receipt.json
uv run python -m dottie_loop incident playbook --kind credential_exposure
uv run python -m dottie_loop spec components --root .
uv run python -m dottie_loop spec acceptance                                         # exit 2 if any RT/ML id lacks a named test
uv run python -m dottie_loop spec done --operator-evidence evidence.json --out dod.json  # exit 2 until the operator items are proven
uv run python -m dottie_loop research rubric --rubric rubric.json --transcript turns.json --task-ok --scores scores.json
uv run python -m dottie_loop research opt-lane --file timings.json
uv run python -m dottie_loop research compose --reward reward.json --rubric-eval eval.json
uv run python -m dottie_loop research compute-teacher --file teacher.json
uv run python -m dottie_loop research ember --file ember.json
uv run python -m dottie_loop research hyperagent --file proposal.json   # --apply is always denied
```

Exit codes: `0` ok, `1` error, `2` blocked, `3` invalid input. stdout is one JSON
envelope; diagnostics go to stderr. There is no interactive prompt.

## Tests

```bash
uv run pytest packages/dottie-loop -q
```

The two core suites are named after the spec's acceptance matrices: every test in
`tests/test_runtime_acceptance.py` cites an RT item and every test in
`tests/test_learning_acceptance.py` cites an ML item, so coverage of the
matrix is grep-able (`grep -c "def test_rt\|def test_ml" tests/*.py`).

## What this package deliberately does not do

- It does not call Ollama, Anthropic, torch or any model. Wiring the kernel's
  `execute` callable to a model or to `scout` is the caller's job.
- It does not replace `apps/scout-cli`'s harness plugin, `apps/jarvisd`'s goal
  store, or `apps/ava-factory`'s shard manifest. It is the contract layer those
  can adopt; `apps/scout-cli/bigbang/plugins/loop` is the first adapter.
- It cannot register the Alienware Forge runner by itself. `scripts/forge_runner.py`
  is the file to copy to the box; until it runs there, `forge runners` reports the
  blocker as a typed `blocked` state, which is the spec's required behaviour.
