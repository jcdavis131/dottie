# DEPRECATED — bhenre.com org console

**Status:** Retired as a deployed surface (2026-08-09). Do not deploy from this app.
**Doctrine and full salvage manifest:** `docs/CONSOLIDATION.md`
**Successor surface:** slasso.com (Validation Lab) — the Monitor face re-homes there as a
read-only training-progress and certification dashboard.

## What this was

The org command console served at www.bhenre.com: `public/index.html` + `org.html`,
`server.mjs`, `api/*`, `public/js/*`, `vercel.json`, and the alias-guard pin
`data/last_good_deployment.txt`. bhenre.com is retired as a surface; the operator-console
function is rebuilt elsewhere, not here.

## What was salvaged, and where it goes

Carried into the new slasso dashboard (sources stay in this directory until ported):

- `scripts/build_runs_readout.mjs` + `public/runs_readout.json` — read-only eval-runs
  exporter: bin provenance, sha256 pinning, `--check` freshness gate.
- `public/js/twin.mjs` + `twin.contract.test.mjs` + `console.mjs` (renderRuns) — pure
  parser layer, zero-dependency contract tests, honest render contract.
- `scripts/release_gate.mjs` — honesty-contract smoke: served artifacts byte-identical to
  committed; retracted numbers only beside retraction markers; honest-offline is correct.
- `SPEC.md` Pillar 3 (Monitor) + data-spine sections — requirements text for the
  dashboard spec. Pillar 1 (steer/fleet control) does not carry: no write path on the
  public certification surface.
- `public/org.html` style block — standalone parchment/serif design tokens.
- `public/training_runs.json` — training-curve readout contract (its generator lives in
  ava-factory and stays in dottie).

Relocating, not carried into slasso: `scripts/steer_poll.py` — the steer channel is
box-side org infrastructure and moves alongside whatever replaces the console.

Dropped with the surface: the amber-phosphor console skin, PWA shell, `api/`,
`server.mjs`, and the fleet-control cards.

Small text assets salvaged from the companion `bluehenre` monorepo (gate specs, queue
semantics, glossary, venture definitions) are staged in `docs/salvage/`.
