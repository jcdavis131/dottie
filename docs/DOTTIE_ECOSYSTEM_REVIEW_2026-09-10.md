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
| 02 | Real feedback UX | **Mechanics built (phase 6, §11).** CLI, API, Slack and `scout loop feedback` all record through `feedback.record_feedback`, bound to the run they answer. Still REQUIRED: people using them — the count of real signals is zero until the operator turns a surface on. |
| 03 | Qualified volume (500 traces) | REQUIRED. The 500 floor is enforced in `closed_loop.THRESHOLDS`; a regression with fewer traces is `blocked`, not `trigger`. |
| 04 | Fresh baselines | REQUIRED. Freshness (48 h, per source, event time) blocks in both `evaluation` and `closed_loop`; nothing here can make evidence fresh. |
| 05 | Branch integration | **Re-scoped.** There are no branches to integrate (F1). The contracts are in one package on one branch; PR #26 is the only live lane. |
| 06 | Operational closure | Mostly. Deletion propagation, rollback, incident record, canary requirements, the expiry job (`retention expire`) and the restore drill (`incident drill`) are code with tests (phase 6); scheduling the expiry job and running a real drill against real stores remain REQUIRED. |

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
- ~~No memory / knowledge-graph layer (§15), no agent-civilization tiers (§30), no Scout plugin wrapper.~~
  Built in phase 2 (below). The memory layer is a contract with an in-package JSONL backend;
  which store is authoritative across `acne` / `personal-graphify` / jarvisd is still the
  operator's call, and adopting `dottie_loop.memory` there is an adapter, not a migration.
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

---

## 7. Phase 2 (2026-09-11, after PR #27 merged as `b0fd59f`): the rest of the spec surface

| Spec | Built | Evidence |
|---|---|---|
| §12 tool plane | `dottie_loop/tools.py` — manifest minimum, result envelope, tool resolution steps 1–6, secrets by brokered reference, redacted audit, dry-run, provider-scope hard stop, "a plugin cannot broaden its own manifest" | `test_tool_plane_policy_invariants` pins every §12 policy invariant |
| §01/§36 Runbook A | `dottie_loop/driver.py` + `python -m dottie_loop loop run` — one goal from intake through plan, kernel, verification, checkpoints, and (only with consent AND the switch) a redacted trace and reward | driver tests: completed / failed / blocked (approval, path escape) / rejected / replay |
| §12 single tool surface | `apps/scout-cli/bigbang/plugins/loop` — `scout --json loop status|goal|run|evaluate|forge-runners|bench`; fs writes gated by `enforce_or_raise` under one declared root; blocked = exit 2 | `apps/scout-cli/tests/test_loop_plugin.py`; soft-lint count unchanged at 763 |
| §27 runner | `packages/dottie-loop/scripts/forge_runner.py` — the file the operator copies to the box: advertise, poll, claim, checkout immutable ref, hash-verify inputs, execute argv, push results; disk preflight; `--once` for the harmless first job | `test_forge_runner_once_completes_a_harmless_job` runs it against a real local bare-repo conveyor: job claimed, executed, `FORGE_METRIC` parsed, result + runner record pushed back |
| §06 Slack (RT-16) | `SlackReporter` — event-id dedupe, one post per state change, one thread per run, hard line cap, mention ≠ authorization | `test_rt16_slack_reports_are_deduped_threaded_and_capped` |
| §06 Web (§35 open decision) | `ApprovalBoard` — stdlib server, bearer subjects, CSRF token per subject, server-authoritative state, append-only decision history, approvals issued through the real `ApprovalStore` | `test_approval_board_is_server_authoritative` over loopback HTTP |
| §15 (RT-11) | `MemoryStore` — evidence required, provenance classes with authority, hints below 0.4 are not actionable, corrections supersede + graph edge, retrieval order and contradiction exposure, people resolution asks once | `test_rt11_memory_provenance_confidence_contradiction` |
| §30 | `civilization.py` — machines dedupe wakeups by incident key at zero tokens; briefs cannot allow spawning; reports must be verdict-first ≤ 10 lines and cannot expand scope; ladder; no self-promotion; token ledger | `test_civilization_machines_specialists_and_ladder` |
| §32 | `observability.py` — correlation fields, no-orphan metric records, outcome SLOs excluding user cancellations, page-worthy classes + dedupe | `test_observability_no_orphan_metrics_and_alert_dedupe` |
| §33 | `incidents.py` — ordered lifecycle, restore requires verification, close requires verified recurrence prevention, quarantine window blocks training eligibility, DR drill checklist | `test_incident_lifecycle_is_ordered_and_quarantines_window` |
| §17 retention | `retention.py` — windows as data; deterministic, idempotent; legal holds win; deletion requests expedite | `test_retention_is_deterministic_idempotent_and_respects_holds` |

Acceptance coverage after phase 2: RT-01…RT-17 all have a named test (RT-11 and RT-16 were
the two gaps). ML-08's software half (a runner that advertises, claims and completes a
harmless job) is proven against a local conveyor; the physical Alienware registration
remains the operator's step, now reduced to copying one file.

Still not built, and why: nothing in this phase calls a model (the kernel's `execute` is a
callable and `tools.py` runs `scout --json`); a learned router stays advisory and closed;
GRPO/SFT training code lives in `apps/ava-factory` and is frozen. Those are the spec's
Phases 4–7 and need the runner, consented data and GPU time before code would change
anything.

---

## 8. Phase 3 (2026-09-11): the operator drives the chain from the CLI; router and skill contracts

| Spec | Built | Evidence |
|---|---|---|
| §36 Runbook A–C, Appendix B 3–12 | CLI commands for every remaining record: `feedback record` (gap 02 for the CLI surface: accept/reject/edit/apply/dismiss attached to a captured run, reward recomputed, trace file stays append-only), `dataset release` / `approve`, `train preflight`, `eval gates`, `approval issue` / `consume` (persisted JSON store, replay attempts recorded even when refused), `promote decide`, `release record` (served-hash verification) and `release rollback`. Every gate that blocks exits 2 with the typed reason. | `test_operator_chain_end_to_end` runs twelve captured goals through feedback → release → approve → preflight → gates → approval → promote → release → rollback in one process |
| §18 | a release with **zero eligible records** is now a hard block, not an empty manifest — found by the chain test, fixed in `dataset.run_pipeline` | same test (`no eligible records` before the consent ledger is supplied) |
| §08 (RT-03) | `router.py`: five tiers, six-step decision order as code; learned advice counts only with artifact + schema + provenance; `gate_passed: false` → heuristic authoritative on disagreement; a learned model can pick an equal-or-cheaper tier, never escalate; confidence below threshold prefers the cheaper tier; escalation only after a *recorded* insufficiency; forbidden private features rejected at construction; adapter for `apps/dottie-harness-api` output | five golden fixtures + `test_router_decision_order_and_learned_advice` |
| §13 | `skills.py`: SKILL.md frontmatter parser (matches `packages/ava-skills` conventions), package contract, one-stage-at-a-time lifecycle with the spec's required evidence and named rollback per stage, mock/synthetic benchmark evidence refused, canary needs an approval id, progressive disclosure (router → selected → workflow) | `test_skill_frontmatter_and_lifecycle_gates` |
| §31 CI | `scripts/test_task_eval_slice.py`'s strip-inflation floor had rotted against the drifting real-history corpus (0.1478 measured on the PR merge ref vs floor 0.1481); re-based per the file's own procedure with old/new/why recorded | CI on PR #29 |

What phase 3 does not change: the numbers. The chain test runs on captured CLI traces of a
file-check goal, which is mechanics evidence (`capability_claim: none`), not the 500
consented real pair sessions the closed loop needs. The commands are the same ones an
operator will run on real data.

---

## 9. Phase 4 (2026-09-11): the §29 security matrix, training stages as data, served truth, the lease

| Spec | Built | Evidence |
|---|---|---|
| §29 "Security testing" | every listed case has a test: path traversal, symlink escape, command injection (argv only), SSRF and redirect escape (per-hop allowlist re-check, private-address rebinding denied), secret redaction, approval binding + replay + a 16-thread race (exactly one consumer), unsafe deserialization (JSON only, NaN/depth/size capped), archive extraction (traversal, links, bombs, size cap), cross-tenant retrieval, prompt injection as data. Protected-material rule honoured: synthetic sentinels only, asserted never to escape | `tests/test_security_and_training.py` |
| §21 Stages 2–4, run controls | `curriculum.py` — selective training logs IDs and scores and keeps coverage floors; curriculum ordering; anneal schedule coupled to the LR collapse and versioned as one object; GRPO groups reject duplicate trajectories, zero invalid/regressed samples, normalize within the group, enforce the KL cap; health check and stop decision with hard-stop classes | same file |
| §19 balancing | caps by template and session applied first, recovery share preserved, inverse-family sampling weights recorded with their reason | same file |
| §31 deployment sequence | `deploy.py` — smoke must pass before alias, alias needs an approver + approval id, served bytes fetched with cache-busting must hash to the approved artifact; a mismatch is a typed failure and the record shows every step | `test_deploy_sequence_requires_smoke_approval_and_served_match` |
| §26 lease | `closed_loop.LeaseFile` — one owner, heartbeat extends expiry, an expired lease whose owner is still live is not reclaimed, release returns the terminal timestamp the cooldown starts from | `test_lease_file_single_owner_reclaim_rules` |

The trainer that will consume `curriculum.py` lives in frozen `apps/ava-factory`; adopting
these functions there is an operator decision, and until then they are the contract the
TrainRun manifest fields (`selection`, `anneal`) are checked against.

---

## 10. Phase 5 (2026-09-11): RLM/REPL, the session recorder, calibration, the fail-closed API, and the §39 graph

| Spec | Built | Evidence |
|---|---|---|
| §10 "RLM execution", §06 REPL row | `rlm.py` — long context lives in named variables with a source and a digest (values never enter the log); `rlm()` is a bounded child call (token slice, child-call count, depth) logged before and after as timeline events, so there are no unlogged ephemeral subagents; the stuck detector fires on a repeated query, repeated failures or two low-confidence results and then allows exactly one lateral lens — a second request is a typed `stuck` escalation; `RLMSession.resume` rebuilds spent budget, lens state and variable provenance from the log | `test_rlm_child_calls_are_bounded_and_logged`, `test_stuck_detector_allows_exactly_one_lateral_lens`, `test_mission_resumes_from_its_log` |
| §16 capture from every surface | `capture.SessionRecorder` — one accumulator for any of the five surfaces; accept/reject/edit/apply/dismiss bound to the turn they answer (a turn that does not exist is invalid input); seven-field checkpoints only; nothing touches disk until `finalize`, which writes only through `CaptureWriter`, so default-off and redact-before-write still hold | `test_session_recorder_finalizes_only_through_capture_writer` (a synthetic secret in a turn does not reach the file; `enabled=False` writes nothing) |
| §24 calibration + abstention quality | `evaluation.calibration` — ECE over confidence bins plus abstention rate and the wrong-when-confident count; empty input is reported `unmeasured`, never zero | `test_calibration_is_measured_from_records_or_reported_unmeasured` |
| §06 API row, §28 "Fail-closed API behavior", §37D, RT-17 | `surfaces.ApiServer` — bearer principals, `Idempotency-Key` header required on `/api/goal` (202 created, 200 exact replay, 409 conflict, same durable store as the CLI and board), `/api/learned` answers 503 `backend_unavailable` until a learned artifact is loaded while `/api/route` still answers from the heuristic; a routing input that is invalid or uses a forbidden attribute is a typed 400/403 AND a quarantine line AND an alert — a quarantine write failure is itself an alert and never turns rejection into acceptance | `test_api_surface_fails_closed` (loopback server, real HTTP) |
| §39 final acceptance artifact | `traceability.py` + `spec traceability --dir` — the thirteen arrows from a pair session to its rollback target as one graph over the JSON records the chain writes; every node carries a content hash; `validate_graph` lists the arrows that do not resolve and the consequential edges (dataset release, canary, approval, release, rollback) that name no human authority; the CLI exits 2 with those names until the graph is complete, and `--no-rollback` is the only waiver and it is explicit | `test_traceability_graph_resolves_every_arrow` |
| §37 schemas | `spec schemas` prints the one active version per record type with the compatibility rule | `test_spec_schemas_lists_one_active_version_per_record_type` |

Suite: 97 tests. What phase 5 does not change: a complete traceability graph over
**synthetic** chain records is a test of the validator, not the spec's proof — the
proof is the same command run over the records of one real opted-in session after
the operator decisions in §6 are made. `spec traceability` reports a node's own
`synthetic` flag as incomplete for that reason.

---

## 11. Phase 6 (2026-09-11): gap 02 — feedback from every surface; gap 06 — expiry and drill as commands

| Spec | Built | Evidence |
|---|---|---|
| §16 "Capture requirements", §35 gap 02 | `feedback.py` — one `record_feedback(store, run_id, signal, surface, edit_fraction, subject)` behind every surface: the signal must name a captured run (no traces → typed `blocked`; unknown run → invalid), is appended as a superseding record so the trace file stays append-only, and the reward is recomputed with `feedback:<signal>:<surface>` as its first evidence line | `test_record_feedback_is_one_contract_for_every_surface` |
| §06 Slack row | `SlackReporter.feedback_from_event` — a reaction on, or a reply whose first word is a signal in, a run's thread binds to THAT run; event-id dedupe; conversation that merely mentions a signal is not feedback; nothing is recorded by the reporter itself | `test_slack_reactions_and_replies_bind_to_the_run_thread` |
| §06 API row, §28 | `POST /api/feedback` — bearer required, 201 with the recomputed reward, 400 on a bad fraction or unknown run, 503 `blocked` when the API has no run store | `test_api_feedback_needs_a_principal_and_a_captured_run` (loopback HTTP) |
| §12 single tool surface | `scout loop feedback --run-id --signal [--edit-fraction]` writes only under the plugin's declared root, exit 3 on invalid input | `apps/scout-cli/tests/test_loop_plugin.py::test_feedback_binds_to_a_captured_run` |
| §17 retention, gap 06 | `retention expire` — deterministic, idempotent pass over a JSONL of records; legal holds and deletion requests as JSON lists; atomic rewrite (`--out` or in place) with a receipt beside the file; unknown data class is invalid input | `test_retention_expire_and_incident_drill_commands` |
| §33 DR drill, gap 06 | `incident drill` — every checklist item must be proven; a missing item is a failed drill with exit 2 naming it | same test |

Suite: 101 tests in `packages/dottie-loop`, 7 in the scout plugin. The gap-02 count that
matters — real signals from real people — is still zero; what changed is that every surface
now has a place to put them that the reward and the dataset pipeline already read.

---

## 12. Phase 7 (2026-09-11): contracts and runbooks that were still prose

| Spec | Built | Evidence |
|---|---|---|
| §37A "Compatibility" (migrations) | `schema.migrate` — deterministic, produces new records and leaves the inputs untouched, refuses a changed source id or a target of another record type, stamps the target schema itself, and writes a migration manifest with before/after hashes and counts | `test_migration_is_deterministic_new_records_with_manifest` |
| §21.1 runtime telemetry, failure handling | `training.TELEMETRY_FIELDS` + `validate_telemetry`; `stop_condition_for` maps a record to the exact hard-stop condition (NaN/inf loss, unreadable shard, sample-accounting mismatch, secret hit, drift beyond the manifest's shards, checkpoint corruption, evaluator unavailable); `HeartbeatMonitor` keeps heartbeats separate from verbose logs with a hang budget | `test_telemetry_maps_to_hard_stops_and_heartbeats_detect_hangs` |
| §36 Runbook D | `incidents.PLAYBOOKS` — privacy deletion, credential exposure, prompt injection, provider rate block as ordered steps, required evidence and "never" rules; `open_from_playbook` opens an `Incident` at the playbook's severity; `incident playbook --kind` | `test_playbooks_are_ordered_data_and_open_incidents_at_their_severity` |
| §36 Runbook D privacy, §37C DeletionReceipt, RT-14 | `Lineage.save/load/hold/exportable`; `privacy hold` (a deletion hold blocks export/training before the deletion completes; a legal hold blocks deletion) and `privacy delete` (tombstone → invalidate datasets → contaminate runs → block promotion; exit 2 with a `held` receipt under a legal hold); the receipt and the CLI output carry no deletion key, no trace id, no content | `test_privacy_hold_and_delete_over_a_persisted_lineage` |
| §36 Runbook A cancellation | `Kernel.cancel(actor, reason, in_flight, external_effects_pending)` — stops new dispatch, marks pending external effects `unknown_until_checked`, appends a seven-field `cancelled` run event carrying actor and reason, retains evidence, implies no rollback | `test_cancellation_records_actor_reason_and_unknown_external_effects` |
| §04 components, §34 current state | `components.COMPONENTS` as data; `inventory(root)` / `spec components --root` report presence from the tree — the check that would have caught finding F1 (four `BRANCH` rows on no remote) | `test_component_inventory_reports_the_tree_not_the_spec_column` |

Suite: 107 tests. Still prose, deliberately: Runbook B/C narrative steps that are already
the operator chain commands (§8), and every step that needs a real store, runner or person.

---

## 13. Phase 8 (2026-09-11): the canary is attributable, the release is provably deletable, reruns are comparable, listings page honestly

| Spec | Built | Evidence |
|---|---|---|
| §25 canary, Runbook C 9–12, ML-13 | `canary.CanaryRun` — refuses an incomplete plan or an unnamed artifact pair; every event must carry `artifact_id` ∈ {incumbent, challenger} plus event time, outcome and latency; safety floor breaches before the primary delta does; `decision_packet` only at the predetermined stop (or a manual stop with actor + reason), stale events are `stale_evidence`, `extend()` is policy-denied; the packet feeds `promotion_decision` unchanged | `test_canary_is_attributable_limited_and_stops_where_planned` |
| Runbook B 16, RT-14 | `dataset.canary_deletion_test` probes deletion propagation on a synthetic canary record against a deep copy of the lineage (tombstone, dataset invalidated, promotion blocked) and leaves the real lineage untouched; `mark_release_usable` requires an approved manifest AND a passing proof for that dataset | `test_release_is_usable_only_after_a_passing_deletion_canary` |
| §21 reproducibility, ML-07 | `training.reproducibility_check` — same config digest and seed, every shared metric within tolerance, metrics present on one side only reported, no shared metric is no evidence | `test_reproducibility_needs_identical_inputs_and_compatible_metrics` |
| §37D "Pagination tokens are opaque and bound to query/scope" | `GoalStore.list_goals(subject)`; `GET /api/goals?limit&cursor` with HMAC-signed opaque cursors: another principal's cursor is 403, a tampered cursor is 400, limits are bounded | `test_goal_listing_uses_opaque_cursors_bound_to_scope` (loopback HTTP) |

Suite: 111 tests. ML-13 and ML-07 are now mechanically testable; their real evidence is
a canary over production traffic and an independent rerun on the registered runner.
