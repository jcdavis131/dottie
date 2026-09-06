# Consolidation — one monorepo, fewer surfaces

**Status:** Adopted 2026-08-09
**Salvage snapshot:** `bluehenre` @ `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
**Staged copies:** `docs/salvage/`

## Doctrine

1. **dottie is the primary development monorepo.** All new platform, pipeline, and site
   work lands here.
2. **The Blue Hen RE monorepo (github.com/jcdavis131/bluehen, workspace codename
   `bluehenre`) is deprecated.** It is wound down as a codebase per the salvage manifest below. Winding
   down the codebase is distinct from deprecating live properties: several sites it
   deployed stay live from their existing Vercel deploys (see "What stays").
3. **The standalone GitHub repos are frozen mirrors, not sources of truth.**
   `scout-cli`, `ava-skills`, `ava-open-harness`, and `personal-graphify` mirror
   dottie's `apps/scout-cli`, `packages/ava-skills`, `packages/ava-open-harness`, and
   `packages/personal-graphify`; `ava-agi-factory-v6-4` mirrors `apps/ava-factory`.
   **As of 2026-09-05 the first four (plus `bluehen` and `agent-lasso`) carry an ARCHIVED
   banner, their crons are disabled, their stale PRs are closed, and each has a
   deprecation PR whose merge is followed by the GitHub "Archive" click.** Hand-syncing
   drifted in both directions twice; if a standalone package is wanted again, publish it
   from dottie with a one-way script. `ava-agi-factory-v6-4` is parked, not archived
   (plan §2). `acne` is a real standalone package and stays active.
4. **bhenre.com is retired as a surface.** That covers the org command console served
   from dottie `apps/bluehenre` (www.bhenre.com) and, in `bluehenre`, the storefront
   (bhenre.com), Simulation Lab (signals.bhenre.com), the planned Data Refinery
   (data.bhenre.com, never fully shipped), and the commerce service behind the storefront.
5. **slasso.com (Validation Lab) becomes the harness + training-progress surface.** The
   Monitor face — training curves, eval-run comparison, gate panel, promotion queue,
   published scorecards — re-homes onto slasso in service of RAG certification. It is
   read-only, static-first, and provenance-honest: numbers render only from committed
   sources, unmeasured renders as unmeasured, stale is history not telemetry, and no
   write path exists on the public surface.

## What stays (untouched by this consolidation)

| Property | Site (in `bluehenre`) | Vercel project | Disposition |
|---|---|---|---|
| arxiviq.com | `apps/sites/research` | arxiv-exam-app | Stays live from existing deploy |
| dumbmodel.com | `apps/sites/dumbmodel` | dumbmodel | Stays live from existing deploy |
| jcamd.com | — (repurposed) | — | Operator personal site since 2026-07-04; not a fleet surface |
| training.jcamd.com | `apps/sites/observatory` | training-console | Under the jcamd domain, spared with it |
| slasso.com | `apps/sites/validation` | who-e (live domain attachment; fleet registry's legacy pointer names agent-lasso) | Serves 404 today; **destination** of the new dashboard, not a deprecation target |

## Deprecation scope (precise)

Deprecated = bhenre.com web surfaces only:

- **dottie `apps/bluehenre`** in its entirety as a deployed site — the org command console
  at www.bhenre.com (`public/index.html` + `org.html`, `server.mjs`, `api/*`,
  `public/js/*`, `vercel.json`, the alias-guard pin `data/last_good_deployment.txt`).
  Its salvageable exporters, gates, and parsers carry into the new slasso dashboard per
  the manifest; `scripts/steer_poll.py` relocates box-side (the steer channel is org
  infrastructure, not a bhenre.com feature, and must not be wired into slasso).
  See `apps/bluehenre/DEPRECATED.md`.
- **In `bluehenre`:** `apps/sites/storefront` (bhenre.com, Vercel "frontend"),
  `apps/sites/simulation` (signals.bhenre.com, Vercel "finance-lab"), the planned
  `apps/sites/refinery` (data.bhenre.com, Spec 0018), and `services/commerce`.
- **The `bluehenre` monorepo as a codebase** is wound down, with salvage per the manifest
  below.

## Salvage manifest

Verdicts: **salvage-now** (carry this consolidation), **salvage-later** (listed, ported
when the dependent dottie capability exists), **drop** (dies with the deprecated surface).
Small text assets marked (staged) are physically copied under `docs/salvage/`.

### Salvage-now — from `bluehenre`

| Asset | Source | Destination | Notes |
|---|---|---|---|
| Spec 0008 — eval gates + fail-closed doctrine (staged) | `specs/0008-eval-harness-and-gates.md` | `docs/salvage/spec-0008-eval-harness-and-gates.md` | The gates the dashboard renders: erank > 8.0, nDCG@10 >= 0.35, sufficientEvalPairs >= 8 (fails closed, no demo substitution — REV-905), MRL fails closed when unmeasured |
| Spec 0012 — promotion pipeline semantics (staged) | `specs/0012-synthetic-org-divisions-and-handoffs.md` §2/§4/§6/§8 | `docs/salvage/spec-0012-operating-loop-excerpts.md` | Ledger stage decoder, Research->BD queue-entry contract, BD->Execution charter contract, stall rules, slasso ownership; RACI/agent material superseded by `COORDINATION.md` |
| Glossary decoder ring (staged) | `memory/glossary.md` | `docs/salvage/glossary.md` | Needed to read every other salvaged artifact; retired-method terms trimmed |
| Site context notes (staged) | `memory/projects/slasso.md`, `memory/projects/arxiviq.md` | `docs/salvage/context-*.md` | Surviving sites' identity; `memory/projects/bluehenre.md` + `memory/people/` superseded by dottie context — dropped |
| fleet.json venture definitions (staged) | `config/fleet.json` (validation lines 164-201; dumbmodel; research) | `docs/salvage/fleet-ventures-extract.md` | slasso product framing verbatim, incl. normative dataConsent line; dumbmodel confirms the certification funnel |
| Validation Queue schema + seeds (staged) | `content/fleet/bd/queue.json` | `docs/salvage/bd-queue.json` | Queue-entry shape the promotion-queue card renders; one seed carries a null gate — honest fixture |
| Scorecards docs-as-data pages | `apps/sites/validation/app/scorecards/page.tsx`, `[slug]/page.tsx` (+ example scorecard fixture) | Port into the slasso dashboard | ~310 lines: YAML-frontmatter markdown scorecards, verdict badges, empty-state copy; strip `@synthaembed/*` imports |
| Work-queue CLI + queue pattern | `scripts/pick_task.py` (+ `config/work_queue.json` shape) | dottie `scripts/` (adapt paths; feed `tasks/todo.md`) | 279 lines, stdlib-only: list/claim/done/blockers/render with blocker gating and claim stamps |
| Multi-agent session conventions (staged, patterns) | `docs/wiki/SESSION_BOOT.md` | `docs/salvage/conventions-excerpt.md` -> merge into `COORDINATION.md` | One-claim rule; bucket-1/2/3 edit classification; unattended agents bucket-1 only |
| Evidence-ledger discipline (staged, pattern) | `EVIDENCE.md` (normative header only) | `docs/salvage/conventions-excerpt.md` | Claims advance only Hypothesis -> Measured (reproducible command + date) or Rejected; measurement content itself is dead |
| DROP/VERIFY review pattern (staged, pattern) | `SCIENCE_REVIEW.md` | `docs/salvage/conventions-excerpt.md` | DROP never appears in copy; VERIFY requires a primary source before load-bearing use |

### Salvage-now — from dottie `apps/bluehenre` (already in this repo; carry into the slasso dashboard)

| Asset | Source | Destination | Notes |
|---|---|---|---|
| Eval-runs exporter + readout schema | `apps/bluehenre/scripts/build_runs_readout.mjs` + `public/runs_readout.json` | slasso dashboard app | Read-only exporter recomputes from committed reports; bins provenance (DISJOINT honest vs CONTAMINATED retracted), source_path + sha256short, unmeasured skipped never filled, `--check` freshness gate |
| Pure parsers + contract tests + run renderer | `apps/bluehenre/public/js/twin.mjs`, `twin.contract.test.mjs`, `console.mjs` (renderRuns) | slasso dashboard parser layer + test suite | Zero-dependency contract tests as the only suite; honest render contract incl. empty state and retraction labels |
| Release gate — honesty-contract smoke | `apps/bluehenre/scripts/release_gate.mjs` | slasso dashboard deploy gate | Served artifact byte-identical to committed; retracted numbers only beside retraction markers; honest-offline is correct behavior |
| Monitor face requirements | `apps/bluehenre/SPEC.md` (Pillar 3, lines 80-131; data-spine 174-179) | Requirements text for the slasso dashboard spec | Curves/experiments/promotions/run-comparison; "stale = history not telemetry"; Pillar 1 (steer) does NOT carry — no write path on the public surface |
| Fleet design tokens, standalone | `apps/bluehenre/public/org.html` (style block) | slasso dashboard stylesheet | Package-free parchment/serif token set matching slasso's look; the amber-CRT skin does not carry |
| Training-curve readout contract | `apps/bluehenre/public/training_runs.json` (generator `build_training_runs.py` stays in dottie) | Dashboard training-progress card contract | Trainer-event-segmented legs, honest restart-fragment drops stated in the artifact, lm_first/last/min, decimated curves |

### Salvage-later

| Asset | Source | Revisit when | Notes |
|---|---|---|---|
| Certify funnel copy + form shape | `bluehenre` `apps/sites/validation/app/certify/`, `components/CertifyForm.tsx`, `app/api/certify/` | dottie has a certification intake backend | Copy encodes the paid-run product; routes depend on monorepo core-api plumbing that is not moving |
| eval-harness package (executable Spec 0008) | `bluehenre` `packages/eval-harness/` | Real certification runs are executed | nDCG@10, effective rank, `gates.compute_gates`; coupled to retired-method checkpoint loading; not needed for the read-only dashboard |
| Steer channel poller | dottie `apps/bluehenre/scripts/steer_poll.py` | The console's successor exists | Box-side org infrastructure; relocation is a move, not a copy; never wired into slasso |

### Drop

| Asset | Source | Why |
|---|---|---|
| Amber-phosphor console skin, PWA shell, console cards | dottie `apps/bluehenre/public/index.html`, `manifest.json`, `api/`, `server.mjs` | bhenre-branded operator-console identity; off-voice and off-purpose for an enterprise certification dashboard |
| Storefront, Simulation Lab, Data Refinery, commerce stack + specs | `bluehenre` `apps/sites/storefront`, `apps/sites/simulation`, `services/commerce`, specs 0013/0021/0022 monetization line | These are the deprecated bhenre.com surfaces; Refinery never fully shipped |
| slasso Overworld/Verdict game layer | `bluehenre` `apps/sites/validation/app/overworld/`, `app/verdict/` | Coupled to monorepo packages and the rank-engine backend; orthogonal to the certification dashboard and off the enterprise measured voice. Deliberately not inventoried further — out of dashboard scope, not an oversight. The live slasso deploy keeps serving it until the site is reworked |
| Retired training-method stack | `bluehenre` `packages/asn-engine`, `scripts/autoresearch_*`, `WHITEPAPER.md`, trainer specs 0003/0005/0009/0011 | Superseded by dottie's training stack (ava-factory, runtrack, GRPO pipeline); the method's surgery variant was formally rejected (0/4 fleet). Its deploy-gate lesson survives via Spec 0008, not via the method code |

## Successor surface — slasso.com dashboard (summary)

The dashboard the manifest feeds: five read-only cards — training progress (per-leg curves
from `training_runs.json`), eval-run comparison (readout with bin provenance and sha256
pinning), gate panel (Spec 0008, fail-closed), promotion queue (`bd-queue.json` shape,
Spec 0012 stages pilot -> charter -> deploy), and published scorecards (docs-as-data with
verdict badges). Non-negotiables: committed sources only; unmeasured renders as unmeasured;
retracted values appear only beside retraction markers; exporter `--check` wired into
pre-deploy; release-gate smoke on production; customer eval sets under NDA with scorecards
published only with clearance; strictly no write path; static-first so localhost matches
the deploy.
