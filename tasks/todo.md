<!-- SUPERSEDED 2026-07-26. Its 15 open items were extracted into the root
     TODO.md along with TODOS.md's 126. Kept for its completed history and context.
     Do not add new open items here — add them to TODO.md. -->

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
- [x] **DEPLOYED (2026-07-24, operator: "deploy")** — `vercel deploy --prod`
      (deployment `bluehenre-campus-6p50gidtm…`) → aliased www.bhenre.com → pin
      updated. Pre-deploy gate was green (100 + 9 + fresh). LIVE-verified:
      org.html 200, `/hub_registry.json` 200 serving all 14 artifacts (model eval
      2268, retracted note present). The realigned Dottie site is live.

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

## NOW — Production workflow (2026-07-25): deployed ≠ productionised

Plan of record: **`tasks/production_workflow.md`**. The site is deployed and
answering (measured 2026-07-25: `/org.html` 200 in 0.14 s, `/hub_registry.json`
200, `/` → 307 as configured). What is missing is not features — it is the
release discipline that makes a deploy repeatable and a regression loud.

The gap, from this board's own words: Phase 1 shipped with *"live visual render
not yet confirmed"* and Phase 2 with *"visual render unconfirmed"*. **Two
features are in production that nobody has verified render.** Pre-deploy is
three commands a human must remember (README:64); post-deploy is nothing; the
alias-guard pin is hand-edited, so it records intent rather than verification.

Pipeline: `G0 SOURCE → G1 PRE → G2 BUILD → G3 SMOKE → G4 PROMOTE → G5 WATCH`.
The load-bearing change is **G3 before G4** — smoke the deployment URL *before*
the alias moves, so a bad build never becomes www.bhenre.com and rollback is
"don't move the alias" instead of "deploy again under pressure".

- [x] **S1 `release_gate.mjs --pre`** — the README's three commands as one
      exit-coded command (contract suite + exporter test + registry freshness +
      JS syntax across the shipped modules).
- [x] **S2 `release_gate.mjs --post <url>`** — the smoke, asserting the
      **honesty contract** rather than liveness. This app's promise is
      provenance-honesty, so `{source:"offline", reply:"…withheld"}` is CORRECT
      production behaviour; a liveness smoke would fail on it and get disabled
      within a week. Asserts instead: served registry byte-identical to the
      committed one · every assistant reply stamped from `{dottie, offline}` ·
      the retracted **275.95** appears only beside a retraction marker, never as
      a live metric · an offline reply is well-formed and carries no fabricated
      number.
- [x] **S3** wired into `bluehenre-checks`: `release_gate.test.mjs` (48 assertions)
      + `release_gate.mjs --pre`. The G3 smoke is deliberately NOT in CI — it
      needs a deployed URL, and CI must not fail because www.bhenre.com is down.

### 🔴 THE GATE'S FIRST RUN FOUND A LIVE PROVENANCE DEFECT

`--post https://www.bhenre.com` fails **today**, on 4 fields, and it is not a
false positive:

```
.datasets[1].data_files[0].bytes    served=633553  committed=633505   (+48)
.datasets[1].data_files[0].sha256   served=79fee2…  committed=5f2a0c…
.research[3].integrity.bytes        served=2380    committed=2344     (+36)
.research[3].integrity.sha256       served=23d62d…  committed=32de55…
```

`research[3]` is **`ledger_retroflag`**, and 2380-vs-2344 is the exact file and
byte pair from the `.gitattributes` line-ending incident. The deltas are pure
CRLF↔LF: **production is serving sha256 integrity hashes computed on CRLF copies
while the repo now holds LF.** The Hub card advertises "integrity (sha256
cross-check)", so bhenre.com is currently displaying integrity hashes that do not
match their source files — a provenance violation of exactly the kind
`build_hub_registry.mjs --check` prevents locally. `--check` passes; the
*deployment* predates the fix. Every count matches (18 artifacts, 3/5/10), which
is why nothing caught it: the drift is four fields deep.

- [ ] **Fix = redeploy** (G2, the operator's gated step per the plan — I did not
      deploy). After deploying, `--post` must go green before the alias moves.

- [ ] **S4** G4 writes `data/last_good_deployment.txt` (pin becomes an output of
      a passed gate, not a hand-edited input); deploy runbook becomes gate-driven.
- [ ] **S7** G5 watch loop — scheduled liveness + freshness probe. Stale WARNS,
      never fails: stale is a documented honest state, and a gate that fires on a
      legitimate state gets disabled (the `lint.yml` permanently-red lesson).

- [ ] **OPERATOR FORK — the assistant has no brain in production, and no amount
      of code changes that.** `api/assistant-chat.mjs` returns `source:"offline"`
      unless `DOTTIE_CHAT_URL` is set, and it is unset in prod because the box is
      deliberately unexposed. The deterministic `nextActions` digest already
      ships real guidance engine-free (right call, it works), but *conversation*
      does not exist for a visitor. Three genuinely different products:
      (1) **tunnel to the box** — cheapest `[dottie]`, but puts a 16 GB laptop
      with a live trainer, flaky Docker and documented memory pressure on a
      public site's critical path; (2) **hosted model API as a second tier**
      grounded in the published gist — `[dottie]` → `[claude]` → `[offline]`,
      always-on, box unexposed, honesty preserved by extending the stamp set;
      (3) **serve the org's own checkpoint** — most faithful to the mission and
      the largest build. Not exclusive: (2) can be the fallback tier for (3).
      Whichever is picked ships **dormant + honest** until the operator supplies
      the credential, exactly as the HF mirror does — entering credentials is
      the operator's own action per SPEC.

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
- [x] **OAPEN OAI-PMH harvester BUILT** (operator: "green light… larger OAPEN pull").
      `apps/dottie/scripts/pull_oapen_oai.py` — harvests the FULL ~57k-record catalog
      via OAI-PMH `dim` (uncaps the ~600 REST-search ceiling), which carries per-record
      license (CC URL) + language; filters English + training-safe CC (reuses the vetted
      gate), fetches `.pdf.txt` per handle, dedups by content sha, writes incrementally
      (checkpoint-safe). Yield ~1.1% CC-BY-English (most records are non-English or
      non-CC-licensed). A 100-book harvest is running; the full corpus is gitignored.
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
  - [x] **Vector MTNN model cards DONE** (operator: "vector model cards for each MTNN").
        4 cards, each honestly classified + flagged: gridiron REAL (walk-forward weekly
        Spearman **0.6899**, beats baselines, backtest-of-method caveat), hoops REAL
        (held-out retrieval test top-5 **0.3633**), equities **PLACEHOLDER** (sector
        purity 0.1742 but 2,200/4,941 rows are placeholder embeddings — contamination
        carried), and the **Universal MTNN REAL** (see below). Hub: 5 models now.
        (gridiron eval IS the trained MTNN v2 — `assets/eval_backtest.json` `model` block
        + overall 0.6899 — correcting the earlier "baselines only" read. pitch has no
        standalone eval artifact but is covered by the unified trunk; golf/tennis have
        no trained MTNN eval yet.)
  - [x] **Universal MTNN TRAINED — Stage 1 + market + cultural-text** (operator:
        "start training…" → "green light all optional next steps"). Stage 1
        (`train_unified.py --epochs 60`) → `--market` ($/prestige heads) →
        `--cultural-text` (Wikipedia MiniLM). 20,721 players in a shared 64-dim
        space across hoops/gridiron/pitch. G1 non-inferiority PASS every stage; G3
        cross-sport silhouette rises **0.7095 → 0.7424 → 0.7639** (the enrichment
        heads add real cross-sport structure). G2 sport-invariance DEFERRED and
        worsens (0.717→0.891) as sport-correlated signal is added — Stage 2
        (`train_stage2.py`, encoder unfreeze) is the structural fix (ckpt exists,
        not retrained/eval'd here — eval can't load its structure). Universal MTNN
        card updated to REAL with the full honest progression; Hub eval now 0.7639.
- [x] **Mobile Hub parity** — the phone terminal view now has a HUB//ARTIFACTS card
      (datasets + models, provenance-badged in the amber palette, retracted number
      named). Reuses the tested `parseHubRegistry`; loaded once, not polled. Suite 97.
- [x] **Research facet — Hub trinity COMPLETE** (datasets + models + research). Curated
      `research_reports.json` (10 of the org's committed reports); the exporter verifies
      each file exists + sha256-pins it (no phantom reports); `parseHubRegistry` exposes
      `research[]`; rendered as a Research section on org + mobile (type chip + sha).
      Registry now {datasets:3, models:1, research:10, count:14}. Suite 97→100.
- [x] **Registry freshness guard** — `build_hub_registry.mjs --check` fails if the
      committed `hub_registry.json` no longer matches the cards (a stale registry =
      the Hub rendering data that doesn't match its source = a provenance violation).
      Pre-deploy verification sequence documented in the bluehenre README. Verified:
      fresh→0, mutated→1, byte-identical refactor. `--check` normalizes CRLF/LF so it
      is correct on a Windows checkout too.
- [x] **CI enforces the site guarantees** — new `bluehenre-checks` job in ci.yml runs
      the twin contract suite + exporter regression test + registry `--check` +
      JS syntax on every push/PR. A stale registry or broken parser now fails CI
      (the provenance guarantees are automated, not just documented). Zero-dep bare-node.

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
