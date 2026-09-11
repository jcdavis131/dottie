# Dottie Full Ecosystem Specification v1.0 — review against the repository, and what was built

**Reviewed:** `Dottie_Full_Ecosystem_Specification.pdf`, 53 pages, baseline 10 September 2026,
"repository evidence through observed HEAD d66ff0f".
**Against:** `jcdavis131/dottie` `main` at `002226b` (feat(dottie): harden real platform end
to end, 2026-09-07), every remote branch, and open PRs #22–#26.
**Built:** `packages/dottie-loop` — the spec's contracts and gates as stdlib-only, fail-closed
code, 52 tests named after the spec's acceptance IDs. Branch
`claude/dottie-end-to-end-review-z2baj5`.
**Date:** 2026-09-11.

Status words below use the spec's own vocabulary: IMPLEMENTED (observed in the reviewed
tree), BRANCH (spec says verified on a branch), BLOCKED, REQUIRED, HISTORICAL.

---

## 1. Verdict in five sentences

The spec is a sound contract and its doctrine (fail closed, provenance everywhere, human
release control, no evidence no advance) matches what the repo's CI gates already enforce for
code. Its **current-state claims are not verifiable from the repository**: the four work lanes
it marks IMPLEMENTED ON BRANCH, the observed HEAD `d66ff0f`, and three documents it cites do
not exist on any remote branch. The spec is also stale on two points it calls open (the two
fail-open candidates were adjudicated on 2026-09-05). Separately, `main`'s last commit left
three CI gates red, so "CI baseline green" (Phase 0 exit gate) was false at review time.
Everything that can be built without the Alienware machine, real users, or GPU time is now
built and tested as `dottie_loop`; what remains is exactly the spec's own critical path
(runner → feedback UX → consented collection → dataset → train → eval → canary → approval).

---

## 2. Findings

### F1 — The four "BRANCH" lanes exist on no remote branch (spec §04, §34, Appendix A)

| Spec claim | Cited evidence | Reality on origin |
|---|---|---|
| Benchmark builder — BRANCH | `scout/dottie-bench-builder`, local commit `4b23512`, `bench/report.md` | branch absent; `bench/` absent |
| Pair reward — BRANCH | `scout/dottie-reward-spec`, "25/25 tests through a stdlib shim" | branch absent; no `task_ok`/`token_eff` code anywhere in the tree |
| Pair-session trace capture — BRANCH | `scout/dottie-trace-capture` `c85379c`, `docs/TRACE_CAPTURE_SPEC.md` | branch absent; doc absent; no `pair-session-1.0.0` writer |
| Closed-loop trigger — BRANCH | `scout/dottie-closed-loop` `d66ff0f`, `docs/CLOSED_LOOP_SPEC.md` | branch absent; doc absent; `d66ff0f` is not an object in the repo |
| Forge connector — "built, 12 tests, live self-test" | `~/workspace/forge`, `forge-runner.py` | not in any repo in scope (`apps/scout-cli/bigbang/plugins/forge` is the plugin *generator*, unrelated) |

`git ls-remote --heads origin` lists 52 branches; none of the four is among them. The spec's
own evidence boundary ("working tree contained unrelated modifications and was not
normalized") is consistent with the lanes having been committed locally and never pushed.
**Consequence:** every BRANCH status in the spec must be read as REQUIRED until the commits
appear. `dottie_loop` implements the contracts from the spec text; it does not claim to be
those branches.

### F2 — The two "remaining human judgments" were already made (spec §23, §35)

The spec says `apps/scout-cli/bigbang/plugins/extract/anydoc.py:512` and
`apps/dottie-harness-api/lib/analytics.py:201` "each need adjudication". Both carry
`ACCEPTED 2026-09-05` judgments in `scripts/gate_audit_baseline.json` (`_parse_txt` and
`recovery_ladder`, respectively — the latter's unguarded return is the *escalate* rung, i.e.
fail-closed). The spec is five days stale here; the baseline is the record.

### F3 — `main` was red on three gates at review time (spec §31 "CI baseline green")

`002226b` introduced, without judging or re-measuring:

1. **gate_audit --check**: three new fail-open-dispatch candidates in
   `apps/dottie-harness-api/lib/production_routing.py` (`_classify_tier` on `intent`,
   `_recommended_agents` on `intent` and on `complexity`). Judged and baselined on this
   branch: the fall-throughs return the *lower*-authority tier (`llm`) and a *suggested*
   agent list; neither grants authority.
2. **documented counts --check**: ruff debt 1022 → 983 (scout-cli 802 → 763 after six test
   files were rewritten). Figure and reason updated in `ci.yml`, `lint.yml`, `Makefile`.
3. **HANDOFF freshness --check**: HANDOFF recorded `23870d7`, which was squash-merged in
   PR #23 and is not an ancestor of `main`. A new session block records `002226b`.

Phase 0's exit gate ("CI baseline green or debt explicitly bounded") is met on this branch,
not on `main`.

### F4 — Draft PR #26 matches the spec's description (spec §28, §34)

PR #26 (`scout/jarvisd-slack-ingress`, head `146d02c`) is open, draft, `mergeable_state:
unstable`, and carries the Slack inbox drain + dedupe the spec attributes to it. It overlaps
PR #25 by design (author's note). No conflict with this branch: `dottie_loop.intake` is a
contract layer; the jarvisd drain can adopt `GoalStore` or map its rows to `GoalEnvelope`
later. Not merged here — merges require explicit approval (spec "Frozen release rule").

### F5 — What the spec calls IMPLEMENTED, checked

| Component (spec §04) | Path | Observed |
|---|---|---|
| Dottie application | `apps/dottie` | present; excluded from the uv workspace (own venv, `dottie.rl` name collision — HANDOFF #2 still open) |
| Harness router API | `apps/dottie-harness-api` | present; `lib/production_routing.py` is the request-derived heuristic; learned route fails closed as the spec requires (§06 "Advisory learned routing") |
| Scout CLI / BigBang | `apps/scout-cli` | present; 60+ plugins; capability ratchet and gate audit in CI; harness plugin already writes the seven-field timeline (`timeline.py` `REQUIRED_FIELDS`) — field names `latency`/`tokens` differ from the spec's `latency_ms`/`tokens_est`; `dottie_loop.timeline` uses the spec names and reads both |
| Ava factory | `apps/ava-factory` | present, frozen mirror; `dottie/pipeline/manifest.py` is a SQLite *shard* manifest with leased claims — a different object from the spec's `DatasetManifest`, which `dottie_loop.dataset` now provides |
| Ava open harness / skills / personal graph | `packages/*` | present; harness suite non-blocking pending the name collision |
| Slack ingress | `apps/jarvisd` + PR #26 | present on branch (F4) |
| Skills: 19 `SKILL.md`, 207 files under plugins | inventory only | consistent with the tree |

### F6 — Doctrine agreements worth keeping in view

- The spec's "harness truth rule" (every float from a live forward pass or deterministic
  computation) is already this repo's provenance doctrine (`docs/ECOSYSTEM.md`).
- The spec's routing history (orch-mlp-v1-v4, 97.2% val / 87.7% measured holdout vs
  heuristic 89.3%, promotion closed) matches `docs/ECOSYSTEM.md` "Honest status" exactly.
- The spec's cost posture (no new pip installs without approval) was honoured: `dottie_loop`
  has zero dependencies and adding it changed no resolved version in `uv.lock`.

---

## 3. What was built: `packages/dottie-loop`

One workspace package, `dottie_loop`, stdlib only, 14 modules, one JSON CLI, 52 tests.
Every module names the spec section it implements; every test names the acceptance ID it
evidences. It calls no model and makes no capability claim.

| Spec | Module | Contract pinned by tests |
|---|---|---|
| §05, §37A | `intake.py` | eight-step validation order; explicit-boolean consent (training consent never inferred); authority-expansion phrases in *untrusted* content rejected; side effect without approval rejected; state machine with named-dependency `blocked`; durable idempotency — exact replay returns the goal, conflict is 409, 12 concurrent replays create one goal (RT-01, RT-02) |
| §07, §37C | `approvals.py` | scope lattice with effects denied by default; one-time tokens bound to action digest + destination + goal; replay, expiry, digest, destination and action-type mismatch all invalidate; replays counted for alerting (RT-05) |
| §09 | `plan.py` | all ten planner validations (acyclic, terminal, approval edge, consumed outputs, capability scope, budget ceiling, verifier per postcondition, unordered shared mutation, sensitivity, effect steps cannot auto-retry); `plan_hash`; `supersede` (immutability); receipt reuse rule (RT-04) |
| §10, §11 | `execution.py` | admit → hydrate → execute → observe → verify → commit with a timeline event per attempt; ladder retry → patch → replan → escalate with `unknown` → escalate; verifier budget (≥ 8.0, one fix, two loops, deterministic checks decisive); path canonicalization, SSRF/domain/method allowlist, argv-only execution; provider 429 hard stop (RT-06, RT-08, RT-15) |
| §14, §37A | `timeline.py` | seven mandatory fields on every event including zero-change; unknown major schema rejected, minor accepted; six-step checkpoint transaction; resume verifies object and metadata hashes and **blocks** on corruption (RT-07, RT-09, RT-10) |
| §16, §17 | `capture.py` | off by default (no file under default invocation); `--capture`/`DOTTIE_TRACE_CAPTURE=1`; emails, bearer/API secrets, key-shaped strings, IPs and high-entropy long tokens redacted from content fields before write; ids never rewritten; P3 never persisted; unreachable sink raises, no success-shaped trace; six-check export eligibility (RT-12, RT-13) |
| §22, §37B | `reward.py` | the formula with every anti-hacking rule as an assertion: accepted-but-failing < correct, fast failure < slow success, silence neutral, regression zeros task, heavy edit discounts, unknown stays null, weights reproduce total; preference pairs only from comparable contexts (ML-06) |
| §18–§20, §17 | `dataset.py` | acquire → consent → redact → validate → qualify → curate (exact + shingle near-dup, benchmark fingerprint contamination) → grouped-temporal split → pack → release; **accounting invariant enforced per source**; one failure = diagnostic report, no manifest; reviewer-signed manifest; consumers reject unapproved manifests; deletion tombstones traces, invalidates manifests, contaminates train runs, blocks promotion, issues a receipt with no private content (ML-01…05, RT-14) |
| §21 | `training.py` | `TrainRun` manifest; the ten preflight checks, each named on failure; hard-stop conditions; OOM retries once as a fork with a revised batch plan; resume only on exact config digest (ML-07) |
| §24, §25, §37C | `evaluation.py` | seven gates → verdict; promote / hold / reject / rollback / block mapping (block for freshness, integrity, anti-mock, missing approval); canary requirements; `ReleaseRecord` with served-hash verification; rollback restores pinned target, freezes challenger, opens SEV-1 with suspected and confirmed cause kept separate (ML-09…16) |
| §26 | `closed_loop.py` | thresholds as data; freshness per source by event time; synthetic/mock/unversioned block; lease; cooldown from terminal timestamp; volume floor; `LoopDecision` emitted on no-change; `--promote` without `--approve-prod` exits without production change, with it writes a record only |
| §27 | `forge.py` | `JobSpec` validation (immutable sha, repo allowlist, no traversal); runner capability record; requirement filter with mismatch result *before* execute; atomic claim by rename; hash-verified inputs; argv-only run; `FORGE_METRIC` parsing; output hashing; orphan detection; the missing runner is a typed `blocked` (ML-08 as far as software can take it) |
| §23 | `bench.py` | workflow runner with per-step status/latency; structural goldens; report whose accounting must reconcile or it aborts; synthetic results excluded from the harness score; `capability_claim: none` (ML-11) |
| §06, §37D | `cli.py`, `errors.py` | exit codes 0/1/2(blocked)/3(invalid); one JSON envelope on stdout; dry-run; typed errors with stable code, field, retryable, HTTP status (RT-17) |

`tests/test_learning_acceptance.py::test_ml17_traceability_chain_resolves` runs the whole
chain in-process — trace → reward → dataset → approved manifest → preflight → gates →
consumed approval → release with served verification → rollback drill — and asserts every
link resolves (the spec's "final proof" shape, §39, at contract level).

### Acceptance matrix coverage

| Matrix | Covered by a named test | Not coverable in software here |
|---|---|---|
| RT-01…RT-10, RT-12…RT-15, RT-17 | yes | — |
| RT-11 memory writes evidence-backed | no | memory/graph layer (§15) not built; see §5 |
| RT-16 Slack reports deduped and concise | no | lives in jarvisd's drain (PR #26); `GoalStore` gives it the dedupe primitive |
| ML-01…ML-07, ML-09…ML-16 | yes (contract level) | ML-08 needs the physical runner; ML-12/15 need production sources |
| ML-17 one closed loop end to end | contract-level chain only | the real loop needs runner, users, GPU |

---

## 4. Gap register, re-read after this work (spec §35)

| # | Spec gap | State after this branch |
|---|---|---|
| 01 | Runner | **Still BLOCKED, operator-only.** Queue, claim, execute, result and orphan logic exist and are tested; `forge runners` exits 2 until `runners/<host>.json` appears. DAG node `forge-runner-register`. |
| 02 | Real feedback UX | REQUIRED. `capture.FEEDBACK_SIGNALS` and `reward.RewardInputs.feedback` are the contract the surfaces must emit; no surface emits them yet. |
| 03 | Qualified volume (500 traces) | REQUIRED. The 500 floor is enforced in `closed_loop.THRESHOLDS`; a regression with fewer traces is `blocked`, not `trigger`. |
| 04 | Fresh baselines | REQUIRED. Freshness (48 h, per source, event time) blocks in both `evaluation` and `closed_loop`; nothing here can make evidence fresh. |
| 05 | Branch integration | **Re-scoped.** There are no branches to integrate (F1). The contracts are in one package on one branch; PR #26 is the only live lane. |
| 06 | Operational closure | Partly. Deletion propagation, rollback, incident record and canary requirements are code with tests; retention expiry jobs, incident drills and deployment hooks remain REQUIRED. |

Additional open decisions (§35), status: the two audit candidates — **closed 09-05** (F2);
Forge training command/ref/manifest — open, needs the runner; numeric SLOs — open; retention
windows by data class — open, the pipeline takes them as `QAThresholds`/ledger inputs; web
approval board — open; independent review ownership — open, `approve_manifest` takes the
reviewer's identity as an argument so the policy can be set without a code change.

---

## 5. Deliberately not done, and why

- **No merge, release, deploy or promotion.** Spec "Frozen release rule". This is a draft PR.
- **No recovery of the four lanes.** They are not on the remote; reconstructing "verified"
  code from prose would present synthetic work as recovered evidence.
- **No memory / knowledge-graph layer (§15) and no agent-civilization tiers (§30).** Both
  are architecture with existing partial homes (`acne`, `personal-graphify`, jarvisd claims);
  adding a third store without an operator decision on which is authoritative would widen the
  `dottie` name-collision problem, not narrow it.
- **No Scout plugin wrapper yet.** `dottie_loop` is invoked as `python -m dottie_loop`. A
  `scout loop …` plugin is a thin follow-up once the capability manifest for it is decided;
  adding an unenforced manifest now would trip the declared-capability ratchet the right way.
- **No edits to `apps/ava-factory/dottie/**`** (frozen, bind-mounted) or to `apps/dottie`.
- **No wiring of `execute` to Ollama/Anthropic.** The kernel takes a callable; the model layer
  is optional by design (spec §02 "Determinism first").

---

## 6. Operator decisions, in the spec's order (Appendix B), with what is now ready for each

1. Review integration → nothing to integrate; review this PR and #26.
2. Install the runner → `~/workspace/forge` layout is what `forge.ForgeQueue` reads; advertise
   with a `RunnerRecord`, then `python -m dottie_loop forge runners --root …` must exit 0.
3. Choose capture surfaces → emit `accept|reject|edit|apply|dismiss` into
   `PairSessionTrace.feedback`; write through `CaptureWriter` with `--capture`.
4. Approve data policy → set `QAThresholds`, the consent ledger and deletion-hold inputs.
5. Resolve audit candidates → done 09-05 and 09-11 (baseline).
6. Freeze baseline suite → produce an `EvalBundle` with `synthetic=False`, fresh timestamps.
7. Collect 500 traces → `closed_loop` will not trigger before that.
8. Approve the first recipe → a `TrainRun` that passes `preflight`.
9–12. Evaluate, canary, approve, rollback drill → `evaluate_gates` → `promotion_decision` →
   `ApprovalStore` → `release_record` → `rollback`, in that order, each producing the record
   the next consumes.

---

## Appendix — verification commands (all run on this branch, 2026-09-11)

```bash
uv sync --all-groups --frozen                         # lock changed only by adding the member
uvx ruff@0.15.22 check packages/dottie-loop           # All checks passed!
uv run pytest packages/dottie-loop -q                 # 52 passed (three consecutive runs)
uv run python scripts/gate_audit.py --check --baseline scripts/gate_audit_baseline.json
uv run python scripts/check_documented_counts.py --check
uv run python scripts/check_handoff_fresh.py --check
uv run python scripts/dag_next.py --check
uv run python -m dottie_loop spec status              # capability_claim: none
uv run python -m dottie_loop forge runners --root /tmp/forge   # exit 2: blocked, forge_runner
```
