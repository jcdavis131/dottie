# The router

Dottie has one routing policy: `dottie_loop.router` in
`packages/dottie-loop/dottie_loop/router.py`. scout (`scout route`,
`scout harness route`, `scout harness run`) and jarvisd (`harness.route`,
`harness.plan`, `harness.run`) call it. Nothing else decides a tier.

## Decision order

`route_goal(goal)` follows the spec's §08 order:

1. **Hard constraints.** An exact rule that is not a guess, such as scout's
   `mcp:` goal prefix, which is always `action_operator`. Policy exclusions
   refuse a tier outright.
2. **Heuristic.** MoMA-lite, the keyword classifier, always runs and is the
   authority by default.
3. **Learned advice.** Each advisory backend answers. An answer changes the
   tier only when it is *authoritative* (see below) and picks an equal or
   cheaper tier.
4. **Escalation.** The tier goes up by one only after a *recorded*
   insufficiency (`recorded_at` + `error_class`).

The spec's below-threshold downgrade is not applied to MoMA-lite. Its
`confidence` key is a keyword-score ratio (max score / 4, capped at 0.96, 0.4
when nothing matched), not a probability. The key keeps its old name because
existing consumers read it. No new code adds a `confidence`.

With default settings every decision is exactly MoMA-lite's.
`packages/dottie-loop/tests/fixtures/moma_route_goldens.json` was generated
from scout's classifier before it moved, and both the dottie-loop suite and
scout's CLI suite check the router against it.

## Backends

All live in `packages/dottie-loop/dottie_loop/backends.py`. A backend answers
and never raises. A failure shows up as `available: false` with a reason.

| Backend | What it is | On by default | Authoritative today |
|---|---|---|---|
| `heuristic` | MoMA-lite. Its only implementation; scout's `_score_intent` / `_complexity` / `_classify_moma` / `_routed_agents` are aliases | yes | yes |
| `learned_mlp` | The orchestrator MLP (`apps/ava-factory/reports/orchestrator/champion_weights.json`, `orch-mlp-v1-v4`, `gate_passed: false`). Inference goes through the shared `apps/ava-factory/orchestrator_infer.py`, or through `dottie_loop.mlp_infer` when that file is absent | `--learned` | no |
| `system_one` | System One over HTTP: `POST {DOTTIE_OS_URL}/decide` with a `jev-decision-schema-1.0.0` request. It asks four typed questions: `tier` (Choice over the five tiers), `action` (Choice: execute/escalate/halt/other), `safe` (Noul) and `severity` (Score 0-1). Uses stdlib `urllib` with a 1.5 s timeout (`DOTTIE_OS_TIMEOUT`) | only when `DOTTIE_OS_URL` is set | no |

System One answers carry `shape_concentration` (the peak of the closed
distribution), never `confidence`. When a sidecar reports `mode: "untrained"`,
it is answering uniformly, so the router records "no signal" and ignores the
answer.

Every route output keeps its existing keys. It also adds `authority` (which
backend decided), `heuristic_tier`, `spec_tier` (T0-T4) and `advisory`, which
holds each backend's answer with an `authoritative` flag.

## Authority: gate plus human stamp

A learned answer is authoritative only when both of these hold:

1. its artifact's `eval_summary.json` says `gate_passed: true`, computed by
   `scout router eval` through `dottie_loop.evaluation` (`evaluate_gates` +
   `promotion_decision`), and
2. a human ran `scout router promote <artifact> --i-have-reviewed --by <name>`.
   That writes a stamp keyed by the sha256 of the artifact's exact bytes to
   `~/.dottie/router/stamps/` (`DOTTIE_ROUTER_STAMPS` overrides).

Nothing stamps automatically. A retrained checkpoint has new bytes, so it is
unstamped until someone reviews it. A served System One checkpoint reports its
identity hash in `/health` (`checkpoint_sha256`), and the router checks the
stamp against that hash. **Today nothing is stamped, so the heuristic is the
authority and every learned answer is advisory.** Learned answers are logged
and displayed, but they never change a route.

## Traces

Every routed goal appends one JSONL line to
`~/.dottie/traces/route-YYYYMMDD.jsonl` (UTC day). A finished
`scout harness run` appends a second line with the observed outcome: node
counts, failures, the recovery-ladder rung, whether it escalated, and whether
the run was cut short with `--max-nodes`.

- `DOTTIE_TRACE_DIR` moves the directory. `DOTTIE_TRACES=0` turns tracing off.
- A trace stores the goal's sha256 and task features, never the goal text.
  `DOTTIE_TRACE_TEXT=1` is the owner's opt-in to store the text and to send
  it to `/decide`. Features alone collide often, so a useful training pack
  needs that opt-in.
- Each line has `source: production`, or `source: test` under a test runner.
  Under pytest with no `DOTTIE_TRACE_DIR`, nothing is written at all.
- A write never raises. A full disk does not stop a route.

## Training loop (runs on the GPU host)

```bash
scout router status                                   # trace files, stamps, current authority
scout router pack  --out ~/packs/router-001           # traces -> strict jev records
scout router train --pack ~/packs/router-001          # dry-run: validates, torch-free
scout router train --pack ~/packs/router-001 --go --out ~/ckpt/router-001   # GPU host
scout router eval  --pack ~/packs/router-001 --checkpoint ~/ckpt/router-001 # writes eval_summary.json
scout router promote ~/ckpt/router-001 --i-have-reviewed --by <you>        # human stamp
python apps/jev-v0/serve_decide.py --checkpoint ~/ckpt/router-001 --port 8770  # serve it as the sidecar
```

- **pack** reads only `source: production` rows and refuses test rows. Labels
  come from what was observed. `tier` is the routed tier when the run
  succeeded there, one tier up when it failed or escalated there, and an
  operator correction (`scout harness correct`) always wins. `action` is
  execute, escalate or halt. `safe` and `severity` come from node outcomes.
  Routes with no outcome, partial `--max-nodes` runs and injected test
  failures are skipped. Records are validated by
  `apps/jev-v0/decision_io.py`. Duplicates are dropped, and records with
  conflicting labels are dropped on both sides. Whole goals go to the holdout
  until it holds at least 20% of rows. Provenance goes to `provenance.jsonl`.
  `MANIFEST.json` records sha256 hashes and `consent.champion: false`. This is
  the same pattern as `apps/arxiviq-factory`'s curate stage.
- **train** runs `apps/jev-v0/train_pointer_lora.py` on the pack's
  `train.jsonl`. It is a dry run unless you pass `--go`.
- **eval** scores the checkpoint's `tier` answers against the heuristic's
  recorded tier on the holdout, as an `EvalBundle`. The bundle includes a
  paired-bootstrap CI, per-tier slice floors and a safety regression count:
  runs that needed a human but were routed cheaper. It also checks the cost
  ratio (`--approved-cost-ratio`, default 1.5), data integrity (re-hashed
  files, no goal on both sides of the split) and anti-synthetic. `gate_passed`
  is true only when every gate passes and `promotion_decision` has nothing
  left to hold except the canary and the approval. Eval never stamps.
- **promote** refuses without `--i-have-reviewed`. It also refuses unless
  `gate_passed` is true and the artifact's bytes still match the ones that
  were evaluated.

`--predictions <jsonl>` lets eval score precomputed `{id, tier}` answers, for
example ones produced on another host. The source is recorded in
`eval_summary.json` as `predictions_source`.

## Ports

- **dottie-os**, the local sidecar that serves System One on your machine or
  tailnet, owns `:8770`. Point the router at it with
  `DOTTIE_OS_URL=http://127.0.0.1:8770`.
- The jev-v0 dev server (`apps/jev-v0/serve_decide.py`) defaults to `:8771`,
  so both can run on one box. Without `--checkpoint` it answers
  `mode: "untrained"`.
