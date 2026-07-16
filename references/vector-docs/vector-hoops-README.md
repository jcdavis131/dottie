# Vector Hoops

Daily NBA chimera puzzle over an era-honest player embedding space.
12,392 player-seasons (1996-2026), per-100-possession, z-scored within
season; PCA(3) map; 8 auto-named archetypes. Static, zero backend, free.

> **Picking up in-progress work?** Start at **[`docs/HANDOFF.md`](docs/HANDOFF.md)** —
> current branch state, the four dormant data tracks and how to activate
> them, verification commands, and open follow-ups.

## Name the Player (`fingerprint.html`, `docs/ARENA.md`)

The 9th daily mode, reachable from `/play`'s tab bar and the mode grid on
`/`. One anonymized player-season shown as pure model output — MTNN
constellation position, archetype pull, 12-skill DNA, no name/team/year —
six guesses, warmth scored by true 48-d cosine. `pipeline/build_arena.py`
repacks committed assets (vectors/skills/mtnn_map/mtnn_heads/
mtnn_embeddings/mtnn_meta/player_meta) into a phone-sized bundle
(`assets/arena/`); `pipeline/test_arena.py` gates every rebuild, wired
into `pipeline/update_dataset.py`. Not to be confused with `/arena`, the
3D chibi-court tour (`assets/arena.css`, Three.js) — different feature,
similar name, worth a rename if it causes confusion.

## Skills Lens (`skills.html`, `docs/SKILLS_LENS.md`)

Every charted player-season graded 0-99 on twelve skills — fixed linear
composites of the era-z contract, percentile within season pool, badges
at 90+. `pipeline/build_skills.py` emits `assets/skills.json` (grades,
order-aligned with vectors.json), `assets/skill_probe.json` (weights +
pooled quantile knots so the client grades the fused daily chimera), and
MTNN training targets. `pipeline/test_skills.py` gates every rebuild;
`pipeline/update_dataset.py` is the growth loop (fetch best-effort →
rebuild → gate → ledger at `pipeline/cache/dataset_ledger.json`).
`train_mtnn.py` (v4) adds a per-skill tower bank on the fused embedding
with held-out per-skill R² in `mtnn_report.json` — research lane only;
the site ships the transparent composites.

Two dormant data tracks extend the MTNN with distinct tower families,
each cache-ready and gated on a committed fixture until one operator
fetch on a non-datacenter IP (stats.nba.com blocks this environment):

- **Pedigree (Track H)** — draft slot, entry expectations, team-fit
  prior + `pedigree_expectation` head. Activate: `bash
  pipeline/operator_fetch_pedigree.sh`.
- **Playoffs (Track I)** — postseason as a distinct regime:
  playoff-vs-regular-season deltas (minutes, usage, scoring, efficiency)
  + team wins/rounds + `playoff_riser` head, plus a transparent Playoff
  Lens (RS vs PO splits + riser/fader) on `skills.html`. Activate: `bash
  pipeline/operator_fetch_playoffs.sh`.
- **Wide skills (Track J)** — post / transition / motor as masked skills
  (2015-16+) from synergy + hustle feeds; Skills Lens bars + MTNN
  skill-tower targets (per-skill mask matrix). Activate: `bash
  pipeline/operator_fetch_wide_skills.sh`.

The Skills Lens also carries a **Steals of the Draft** board (draft
expectation vs actual peak skill grade) that lights up with the Track H
draft data.

## OKF LLM-Wiki (`knowledge/`)

One interlinked, machine-editable markdown page per charted player
(2,293), plus archetype and position hubs. Two-layer contract: an AUTO
block regenerated from the data, and a CURATED layer below the marker
that humans/LLM agents extend and the generator never touches. Nearest-
neighbor wikilinks make the graph walkable; the game's reveal card links
each chimera component to its dossier. Contract: `knowledge/OKF.md`.

- `python pipeline/build_wiki.py` — idempotent regeneration

## Enrichment (`pipeline/enrich_vectors.py`)

Adds to `assets/vectors.json` without touching the game contract:

- `proj` — exact affine recovery of the build-time PCA+minmax map, so
  the client projects the fused Chimera vector into the 3D map honestly
- `axes` — PC1/PC2/PC3 interpretations verified against feature
  correlations (paint vs perimeter / scoring load / ball in hand)
- `p` + `positions` — per-season PG/SG/SF/PF/C from Basketball-Reference
  (`pipeline/fetch_positions.py`, 99.7% coverage), coloring the 3D map

## Data pipeline (v2)

`python pipeline/build_vectors.py` builds two artifacts:

- `assets/vectors.json` — the frozen 14-dim game contract (+ optional
  `sal` salary-z per player where payroll coverage exists)
- `pipeline/data/train_matrix.npz` + `feature_manifest.json` — the wide
  matrix: Base + Advanced + shot-mix (Scoring) + bio + player-tracking
  (2013-14+, masked before) + salary, all era z-scored with missing
  masks, grouped into tower families

Sources: stats.nba.com (leaguedashplayerstats Base/Advanced/Scoring,
leaguedashplayerbiostats, leaguedashptstats), basketball-reference
current contracts, and an optional `pipeline/cache/salaries_history.csv`
drop-in (name,season,salary) for full 1996+ payroll history.

Every season/endpoint response is cached under `pipeline/cache/`;
stats.nba.com throttles hard, so re-running resumes where it left off.
`--offline` rebuilds from cache only.

Cleaning: dedupe on (PLAYER_ID, season), NaN -> season mean with masks,
attempt-weighted empirical-Bayes shrinkage of FG3%/FT%/FG%, z-clip ±4.

## Embedding v2 (multi-tower net)

`python pipeline/train_towers.py` (torch) trains per-family MLP towers
(volume / playmaking / rebounding / defense / efficiency / shot-mix /
tracking / bio / market) fused into a 32-dim contrastive embedding
(InfoNCE; positives = same player in adjacent seasons + augmented
views; auxiliary salary-regression head). Outputs
`pipeline/data/embedding_v2.npz` + `tower_report.json` with a
same-player-next-season recall@10 sanity metric. The game keeps the
transparent 14-dim profile until v2 demonstrably beats it — promotion
is a deliberate, separate step.
