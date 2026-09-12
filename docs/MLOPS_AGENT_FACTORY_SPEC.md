# MLOps agent factory specification

**Mission:** `dottie-mlops-agent-factory-20260907`
**Status:** implementation slice
**Canonical home:** root `factory/`

## Objective

Turn real model-training work into an auditable, fail-closed state machine while
preserving the existing software, training, and data registries and CLI.
Tracked JSON describes immutable mission intent; a local SQLite ledger owns
mutable attempts, transitions, approvals, and evidence.

## Acceptance criteria

1. A strict typed mission binds repository and code SHA, dataset identities,
   licenses, immutable revisions and SHA-256 values, argv-only train/eval
   commands, hardware and resource budgets, metric gates, outputs, and approval
   policy. Unknown fields and incomplete real-data identities are rejected.
2. Legal lifecycle transitions are enforced:
   `proposed -> preflight_blocked|ready -> running -> evaluating ->
   passed|failed -> promoted|rejected|cancelled`. Unknown and illegal
   transitions fail closed.
3. SQLite updates use WAL, foreign keys, a busy timeout, and
   `BEGIN IMMEDIATE`; concurrent claimers have one winner and attempts are
   immutable.
4. Preflight aggregates blockers for dirty or drifting code, missing commands,
   unlicensed/unhashed/unpinned datasets, denied dependencies, insufficient
   GPU/RAM/disk, conflicting jobs, unsafe outputs, and artifact overwrite.
5. Runs execute argv without a shell from an isolated scratch copy pinned to
   the approved SHA. They capture environment, stdout, stderr, exit code,
   runtime, launched PID/process identity, and protected-artifact hashes before
   and after. Source state is rechecked around cache-excluding snapshot creation,
   copied dataset hashes are verified, Windows long runs hold the machine awake,
   and cancellation targets only that exact process tree/group.
6. Evaluation consumes a fresh canonical report, propagates command failure,
   and rejects missing, Boolean, NaN, infinite, stale, or out-of-gate metrics.
   Smoke, unit, measurement, and promotion evidence remain distinct.
7. Provenance binds model, checkpoint, tokenizer, config, datasets, code SHA,
   commands, metrics, and artifact hashes to one attempt. Promotion re-verifies
   integrity, refuses overwrite, and durably journals the attempt, provenance
   digest, distinct reviewer/shipper actors, destinations, and expected hashes
   before destination writes. Recovery completes only verified transaction-owned
   hard links or removes only those owned links. Digest-bound approvals and the
   promoted state are recorded only after all outputs verify. Mock, placeholder,
   synthetic-only, and smoke-only evidence remains ineligible.
8. Python operator commands cover `propose`, `status`, `preflight`, `run`,
   `evaluate`, `promote`, `cancel`, and `resume`. Promotion requires explicit
   approval; resume creates a new attempt with unchanged lineage.
9. Planner, preflight, operator, evaluator, reviewer, and shipper role
   contracts are recorded without adding always-applied rules.
10. Tests prove transitions, atomic claims, dirty-tree refusal, exit
    propagation, overwrite protection, provenance integrity, resume safety,
    and no-mock promotion.

## Compatibility and non-actions

- Extend `factory/`; do not create a parallel framework or repurpose root
  `pipeline/`, whose tracked modules serve agent traces and GRPO utilities.
- Keep legacy `factory train ...` behavior and `train_queue.json` compatible.
- Use Python stdlib only (`sqlite3`, `subprocess`, `pathlib`, `hashlib`, JSON).
- Do not install packages, start Docker, train a model, edit the dirty daily
  checkout, overwrite model artifacts, or perform commit/push/PR/deploy work.
- The real GridIron example remains blocked until exact upstream licenses,
  immutable source revisions/hashes, canonical evaluator/report, and safe
  machine resources are all present. No blocked mission may be presented as a
  successful model.

## Verification

```text
uv run pytest factory/tests -q -p no:cacheprovider
uv run python -m factory check
uvx ruff@0.15.22 check factory
uv run python scripts/dag_next.py --check
```

No model-training command is part of implementation verification.
