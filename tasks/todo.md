# TODO — the Dottie site (Guide / Hub / Monitor)

Vision: `apps/bluehenre/SPEC.md`. Phased plan: `tasks/dottie_site_plan.md`.
One product, three faces, differentiated by provenance-honesty by construction,
built additively on the bluehenre console. Static-first (local == Vercel); the
public deploy is the operator's gated step.

## Done (2026-07-24)
- [x] SPEC of record rewritten to the three-face vision; `SPEC_dottie_site.md`
      consolidated into `apps/bluehenre/SPEC.md`.
- [x] README (root + bluehenre) + root SPEC realigned to the vision.
- [x] Old open-world-game framing removed: the campus/NPC/persona metaphor is
      gone from the console code — functional team labels (training/data/
      curation/ops/serving/research/services) replace the campus buildings; the
      dead `persona`/`action` game-character fields deleted; `/api/npc-chat`
      renamed `/api/assistant-chat` (server + Vercel fn + both front-ends).
      Contract suite green (76/76); JS syntax-clean. NOT deployed.

## Now — Phase 1: HUB Artifact Registry (first slice, additive/static)
- [x] `apps/bluehenre/scripts/build_hub_registry.mjs` — read-only exporter:
      corpus_proposals card frontmatter + audit sidecars + data-file sha256 →
      `public/hub_registry.json` (2 datasets: gridiron_forecast_rows=REAL,
      repair_transcripts=HONEST-SYNTHETIC). Deterministic, no network.
- [x] `parseHubRegistry(doc)` in `twin.mjs` + 9 contract-test rows (badge from
      classification, UNCLASSIFIED fallback never-guessed, integrity/sha, bad-shape
      guards). Suite 76→85 green.
- [x] `renderHubRegistry()` card in `org.html`/`org.mjs` — "Hub — Datasets" wide
      card with REAL/HONEST-SYNTHETIC/PLACEHOLDER/UNCLASSIFIED badges (colored),
      per-dataset stats/integrity/tags/summary, card links to the public repo
      blob (link-guarded). Fetches the static `/hub_registry.json` once at init.
- [x] Gate: contract suite green (85); `parseHubRegistry` verified end-to-end
      against the real `hub_registry.json`; server serves it (200); all edited JS
      `node --check` clean. NOTE: live *visual* render not yet confirmed (Chrome
      extension was disconnected) — confirm on deploy or next browser session.
- [ ] **Operator: deploy** — `cd apps/bluehenre && vercel deploy --prod --yes`
      → re-alias www.bhenre.com → update `data/last_good_deployment.txt`. This
      is the first visible face of the realigned vision.

**Phase 1 (Hub Artifact Registry) is code-complete — pending the operator deploy.**

## Phase 2: GUIDE digest + agent tiles
- [x] `nextActions(live, fleetRows)` in `twin.mjs` (ranks alerts + research queue
      + fleet health critical→high→normal; steer command where unambiguous) + 7
      contract tests (suite → 92).
- [x] `renderGuide()` — ranked next-action list in the assistant card, each
      steer-carrying action reusing the copy+open-STEER write path. On BOTH the
      org console (`org.mjs`) AND the mobile terminal view (`console.mjs`/
      `index.html`) — the operator's phone is the primary steering surface.
      Visual render unconfirmed (Chrome extension down); endpoints serve 200.
- [ ] Agent-activity tiles (research loop / fleet / trainer) — deferred; the
      digest is the higher-value half and shipped first.

## Then — Phase 3: MONITOR runtrack readout
- [ ] Bridge `runtrack` (scout-cli openswap, pure-sqlite) to the live
      trainer/research metrics + the ledger.
- [ ] Monitor card: live training curve(s), research experiments/promotions, fleet
      stats, run comparison. Real-measured; stale/offline honest.

## External data expansion (operator directive — validated sources)
- [x] Rejected the shadow library (library.memoryoftheworld.org); SOP updated to
      forbid shadow-library sources. `external_book_sources.md`.
- [x] **DOAB/OAPEN open-access books piloted** — `pull_oapen_books.py` (read-only,
      `dc.rights`-gated: CC-BY/SA/CC0 only, ND + NC + unlicensed excluded). Sample:
      10 CC-BY scholarly books, license-verified + sha256-pinned, HF-standard card,
      auto-rendered in the Hub registry (now 3 datasets). Excluded 29/39 by license.
- [ ] Scale OAPEN (`--full` + higher `--target`), then the operator lands the
      `sources.yaml` entry (frozen config). Decon note: OAPEN can't overlap the
      CURRENT held-out (not a generator); `HELDOUT_SEED` disjointness applies
      automatically once registered — a raw-text 13-gram cross-check needs the
      box-side tokenizer. See the card's Decontamination section.
- [ ] Future clean expansions: broaden Gutenberg, Standard Ebooks, PMC-OA, Wikisource.

## Adversarial code review (2026-07-24) — findings addressed
- [x] **License-gate false-positive FIXED** (pull_oapen_books.py) — the gate read
      only the FIRST `dc.rights`; a book carrying CC-BY *and* an ND license would
      have been wrongly included. Now `gate_rights()` evaluates ALL values,
      most-restrictive wins, ANY ND/unverifiable value excludes. 9 edge-case tests.
- [x] **Exporter latent parser bugs FIXED + regression-tested** (build_hub_registry
      .mjs): `num_bytes:` between name/num_examples broke splits (rows null +
      inflated n_fields); nested struct sub-fields inflated n_fields; flow-style
      lists dropped; frontmatter needed a trailing newline. Parser helpers now
      exported + `build_hub_registry.test.mjs` (9 tests). Real registry byte-identical.
- [ ] Deferred (latent, no current card hits them): multiple-config `dataset_info`
      (sums across configs) + quoted/glob `path:` values. Fix when a card needs them.

## Gated / dependency-blocked (Phase 4)
- [ ] **HF publish** (Hub ↔ real HuggingFace) — BLOCKED on `HF_TOKEN` rotation
      (provenance audit #6). Show an honest "mirror: awaiting token rotation"
      until rotated; then wire the authed push (operator runs the token step).
- [ ] **Engine ReAct trace** (Guide chat) — needs the factory hub `/assistant` to
      expose a stable `steps[]`; verify the engine field first, pass through
      `server.mjs` verbatim.
- [x] **Model cards — data layer DONE**: `model_cards/ava_mini_tool_final/README.md`
      (HF-standard model card, classification REAL) with the honest **2,268** ppl
      AND the **retracted 275.95/4103 carried explicitly** (the anti-fabrication
      differentiator). Exporter scans `model_cards/` → registry `models[]`;
      `parseHubRegistry` returns models with badge + arch + eval. Suite 92→97,
      exporter test 9. Registry now {datasets:3, models:1}.
  - [x] Model cards UI — the Hub card ("Hub — Artifacts") now renders Datasets +
        Models sections: model badge, arch line, honest eval, and the RETRACTED
        number as a distinct rust-colored "do not cite" note (the differentiator,
        visible). org console. Suite 97; classes verified; pixels unconfirmed
        (Chrome extension down).
  - [ ] Vector MTNN model cards (gridiron/hoops/pitch/equities) — needs cross-repo
        eval sourcing; same card pattern.
- [x] **Mobile Hub parity** — the phone terminal view now has a HUB//ARTIFACTS card
      (datasets + models, provenance-badged in the amber palette, retracted number
      named). Reuses the tested `parseHubRegistry`; loaded once, not polled. Suite 97.

## Operator calls (from the provenance audit — deliberately not auto-done)
- [ ] Rotate the previously-committed `HF_TOKEN` and place the new value in the
      gitignored `apps/ava-factory/.env` (I cannot write the secret).
- [ ] #7 baseline-provenance gate in `evaluate.py` (code defers it to operator).
- [ ] Equities checkpoint for real asset regen (KPI card + skills radar still
      synthetic-flagged); ~66% synthetic curriculum mix; stale config labels
      (frozen path); dead `train_1b_deepspeed.py` path.

## Notes / follow-ups
- `org.html` still links "terminal view" → `bluehenre-campus.vercel.app` (the
  deployed Vercel project's own subdomain; renaming the project is operator infra
  and would move the alias — left as-is).
- Each public deploy: `vercel deploy --prod --yes` → re-alias www.bhenre.com →
  update `apps/bluehenre/data/last_good_deployment.txt` (alias-guard pin).
