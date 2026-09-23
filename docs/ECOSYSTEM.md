# The Dottie ecosystem (pointer + history)

**The normative description of Dottie is now [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)**
(2026-09-23): the four planes, the runtime topology, every service and port,
the `decide` contract, which knowledge is on the decision path, the learning
loop, the measured speed budget, the rules and the retirement decisions.
Routing details are in [`docs/ROUTER.md`](ROUTER.md).

This page used to be the "normative map" (2026-08-09 to 2026-09-11). Parts of
it described things that do not run today, so it is kept only as history. The
full previous text is in git history (`git log -p -- docs/ECOSYSTEM.md`).

## What was aspirational, and what is true now

| This page said (2026-08-09) | True as of 2026-09-23 |
|---|---|
| "Every arrow is code that exists and runs today" | The nightly Routine (09:00 UTC retrain) is not in this repo, and the loop's router decisions come from the MoMA-lite heuristic. The measured loop is `ARCHITECTURE.md` "The learning loop" |
| slasso.com / harness-api `/api/route` "serving the current champion" | harness-api serves the deterministic MoMA-lite heuristic (vendored from `dottie_loop.backends`); no learned router is deployed anywhere |
| Router = "learned MLP + heuristics" | One router, `dottie_loop.router`: heuristic authoritative; the MLP and System One are advisory until a gated, human-stamped artifact exists (none does) |
| Seven repos with the harness at the center | One monorepo (`jcdavis131/dottie`); the decision plane is jarvisd |

## History (kept because other documents cite these sections)

## Why real failures matter: the label ceiling

The promotion gate requires the champion to strictly beat both a frequency
prior and the routing heuristic on measured hold-out data. When every label is
"the tier the heuristic executed" (behavior labels), the heuristic scores 1.0
by construction and the gate is structurally locked. That lock is honest — and
it is also the P1 item the plan targets. Three label sources break it:

1. **`measured-outcome`** — a run whose executed tier failed and escalated is
   labeled with the ladder's escalation target: the harness's own measured
   signal that the routed tier was insufficient.
2. **`operator-corrected`** — `data/orchestration/label_corrections.jsonl`;
   corrections are ground truth, so an invalid correction fails mining loudly
   rather than training silently.
3. **`measured-behavior`** — the existing default, still the bulk of the corpus.

The dashboard's Label sources panel and `corpus_meta.json`'s
`measured_holdout_by_label_tier` make progress against the ceiling visible:
the gate's champion-vs-heuristic comparison becomes meaningful exactly when
the non-behavior count in the measured hold-out exceeds zero.

## Provenance doctrine (short form)

A record is **measured** only when latency, tokens, and status are all
actually measured; executors that make no model calls record token cost 0 as a
measured fact; simulated data is labeled simulated everywhere it appears;
split buckets come from sha256 of the split key, never `hash()`. Dashboards
derive every number from committed sources and render UNMEASURED rather than a
plausible zero.

## Honest status (2026-08-10)

- 1,563-record corpus; 729 measured; champion `orch-mlp-v1-v4` at 97.2% val /
  87.7% on the 57-record measured hold-out
  (`apps/ava-factory/reports/orchestrator/eval_report.json`).
- Gate: **not passed** — champion 87.7% vs heuristic 89.3% (freq-prior 21.1%)
  on the measured hold-out; the heuristic is 1.0 on behavior labels by
  construction (the ceiling described above). This is reported as-is on the
  dashboard.
- Meta-MCP now has a real external downstream live: `mcp.deepwiki.com`
  (free, no-auth, read-only GitHub-repo documentation Q&A), registered in the
  `harness` namespace alongside `self` and `acne`. Wiring it surfaced and
  fixed two real client transport defects (streamable-HTTP tuple unpacking,
  transport-selection ordering) — the strongest kind of evidence the flywheel
  argument predicts: real integration use finds what testing alone doesn't.
- The full nightly cycle (collect → mine → train → gate → sync → dashboard)
  is now one fail-closed command, `apps/ava-factory/scripts/flywheel_cycle.py`,
  driven by the 09:00 UTC Routine. Proven live: exit 0 in 39s, gate evaluated
  honestly, weights untouched on a not-promoted cycle.
- Operator corrections queue is live on the dashboard: the ten most recent
  measured runs with a ready-to-run `scout harness correct` command per row —
  the fastest path to non-behavior labels in the measured hold-out.
- CI: full pipeline green on GitHub runners as of `cc01c6c`.
- Next unlock: operator-reviewed corrections via the dashboard queue, plus
  organic accumulation of real MCP action failures (now including external
  downstream traffic), then let the nightly Routine and the gate do their
  jobs.

## The spec as code (2026-09-11)

The Dottie Full Ecosystem Specification v1.0 became `packages/dottie-loop`
(`dottie_loop`): contracts and gates as stdlib-only, fail-closed code with tests
named after the spec's acceptance IDs. The review that led there is
`docs/DOTTIE_ECOSYSTEM_REVIEW_2026-09-10.md`.
