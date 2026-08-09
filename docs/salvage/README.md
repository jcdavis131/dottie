# docs/salvage — staged copies from the deprecated Blue Hen RE monorepo

Physical copies of the small, text-shaped salvage-now assets from the Blue Hen RE
monorepo (`bluehenre`, github.com/jcdavis131/henington-homes), staged here before that
repo winds down. Doctrine and the full salvage manifest: `docs/CONSOLIDATION.md`.

All copies were taken at source commit `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55`
(2026-08-03) on 2026-08-09. Each file carries its own provenance header stating the exact
source path and what was edited or trimmed; nothing is silently modified.

| File | Source path (in `bluehenre`) | What it is |
|---|---|---|
| `spec-0008-eval-harness-and-gates.md` | `specs/0008-eval-harness-and-gates.md` | Deploy-gate definitions + fail-closed doctrine the slasso dashboard renders |
| `spec-0012-operating-loop-excerpts.md` | `specs/0012-synthetic-org-divisions-and-handoffs.md` §2/§4/§6/§8 | Promotion-pipeline semantics: closed loop, queue/charter contracts, ledger stages, stall rules |
| `glossary.md` | `memory/glossary.md` | Decoder ring for reading the other salvaged artifacts (trimmed of retired-method terms) |
| `fleet-ventures-extract.md` | `config/fleet.json` (validation / dumbmodel / research blocks) | Venture definitions for the surviving sites, incl. the normative slasso dataConsent line |
| `bd-queue.json` | `content/fleet/bd/queue.json` | Validation Queue schema + two seed candidates (one null gate — honest fixture) |
| `context-slasso.md` | `memory/projects/slasso.md` | slasso.com site identity and lineage |
| `context-arxiviq.md` | `memory/projects/arxiviq.md` | arxiviq.com site identity |
| `conventions-excerpt.md` | `docs/wiki/SESSION_BOOT.md`, `EVIDENCE.md`, `SCIENCE_REVIEW.md` | Claim discipline, evidence-ledger rule, DROP/VERIFY review pattern (patterns only) |

Salvage-now items **not** physically copied here (code, ported at implementation time from
the pinned commit — see the manifest in `docs/CONSOLIDATION.md` for each destination):
`scripts/pick_task.py`, the scorecards docs-as-data pages under
`apps/sites/validation/app/scorecards/`, and the dottie-side `apps/bluehenre` exporters,
parsers, gate scripts, design tokens, and readout schemas — the latter already live in
this repo and carry over when the slasso dashboard is built.
