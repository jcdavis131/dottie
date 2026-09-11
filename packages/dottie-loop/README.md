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
| §27 | `scripts/forge_runner.py` | the one file for the GPU box: advertise → poll → claim → checkout → execute → push results over a git conveyor |

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
```

Exit codes: `0` ok, `1` error, `2` blocked, `3` invalid input. stdout is one JSON
envelope; diagnostics go to stderr. There is no interactive prompt.

## Tests

```bash
uv run pytest packages/dottie-loop -q
```

The two suites are named after the spec's acceptance matrices: every test in
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
