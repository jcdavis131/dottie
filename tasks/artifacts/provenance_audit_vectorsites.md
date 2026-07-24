# Provenance audit — VECTOR-SITE model/data pipelines

READ-ONLY. Traces, per site, (1) the TRAINING DATA that feeds the embedding/MTNN model, (2) the SHIPPED ASSETS (`assets/*.json`), and (3) the DISPLAYED METRICS (dashboards/READMEs), and classifies each as REAL / FABRICATED / MIXED with exact `file:line` evidence.
Scope: `vector-hoops`, `vector-pitch`, `vector-equities`, `vector-gridiron`. Excludes `.venv`, `node_modules`, `__pycache__`, `.claude\worktrees\**`. `vector-gridiron` read-only on its `claude/*` branch. Date: 2026-07-24. Builds on `tasks/artifacts/goat_audit_sites.md`.

Operator doctrine being enforced: "ALWAYS use real and verified data sources… garbage in, garbage out."

---

## Scorecard

| site | data_source | asset_provenance | displayed_metrics_honest |
|---|---|---|---|
| vector-hoops | **REAL** (stats.nba.com + basketball-reference.com) | honest — sha256-provenanced, held-out collapse disclosed | mostly — transductive CQS strip hardcoded, but honest held-out strip shown beside it |
| vector-pitch | **REAL** (StatsBomb open-data) | honest — game vectors from real StatsBomb events | **NO** — `dashboard` fabricates an LLM/KV-cache stack + hardcoded chart numbers |
| vector-equities | **MIXED→mostly FABRICATED** for what ships | **FABRICATED** — np.random skills, modulo archetypes, hardcoded metric literals, irreproducible | **NO** — browser renders `Math.random()` as a projection table; KPIs trained on synthetic data |
| vector-gridiron | **REAL** (nflverse + FFC/MFL ADP APIs) | honest — real matrix; simulation honestly labeled | **YES** — metrics trace to real computations |

---

## vector-hoops — data REAL, assets honest, metrics mostly honest

**Training data — REAL public.** Embedding/MTNN trains on `stats.nba.com` (nba_api routed through curl_cffi) + `basketball-reference.com`:
- `pipeline/build_vectors.py:18-20` (leaguedashplayerstats Base/Advanced/Scoring, bio, tracking), `:70` `nba_http`, `:342`/`:420` nba_api endpoints; `:579` bbref contracts.
- `pipeline/fetch_draft_history.py:7,96` "stats.nba.com drafthistory via nba_api"; `fetch_honors.py:28`, `fetch_finals_mvp.py:25`, `fetch_positions.py:51` (basketball-reference).
- Skills are fetched, never invented: `build_wide_skills.py:33` "…never a fabricated grade"; `export_season_norms.py:114` "show a percentile instead of a fabricated rate."
- Only non-real ID path: `build_career_context.py:201` hash-name → synthetic `pid` for rows outside the matrix ("rare"), honestly commented. This is an ID fallback, not feature/label fabrication. The `np.random.*` in `train_mtnn.py:842,1394,1814` / `train_towers.py` are legitimate permutation/negative sampling.

**Shipped assets — honest.** `build_eval_scoreboard.py:80-81` sha256's the embedding + vectors assets; emits `computed_at` (`:228`), `tie_handling:"pessimistic"` (`:224`), and honestly reports the held-out collapse (train vs test retrieval). No `np.random`/placeholder in the shipped-asset generator.

**Displayed metrics — mostly honest, one vanity caveat.** `model.html:324-329` hardcodes a **transductive** CQS strip: `CQS 85.87`, `recall@10 1.0` (same-player — i.e. memorization), `purity@20 0.8726`, `skills R² 0.802`, `next R² 0.651`, `pos 0.998`. These are real computations but train-set/transductive framing (matches the README-headline-vs-held-out gap the GOAT audit flagged). Mitigation: **directly beside it**, `model.html:332-338` loads the honest held-out scoreboard live from `assets/eval_scoreboard.json` (`evsb-top5/top1/base5/pairs`). Hoops is the only site that ships its own disconfirming numbers.

**Fix:** relabel the `model.html:324-329` strip "TRANSDUCTIVE / train-set" and annotate `recall@10 1.0` = same-player memorization. Low priority.

---

## vector-pitch — data REAL, game honest, DASHBOARD fabricated

**Training data — REAL public.** `pipeline/build_vectors.py:1,13-14,51` StatsBomb open-data (`raw.githubusercontent.com/statsbomb/open-data`), World Cup 2018+2022; `build_features.py:1,7` expanded StatsBomb corpus; `:278` real `statsbomb_xg`. `build_difficulty.py:5,29,309` repeatedly labels its output "MODEL ESTIMATE, not measured telemetry." `game.js:56` `Math.random()` is only a user-ref id generator.

**Shipped assets — honest.** `assets/vectors.json` + `pitch_mtnn_embeddings*.json` are real StatsBomb-derived embeddings.

**Displayed metrics — FABRICATED (the `dashboard`).** In a repo whose identity is documented honesty, the Lab page lies:
- **Non-existent LLM stack:** `dashboard.html:34` "KV cache 8× compression … 7-8 tok/s", `:37` "KV 8× → fixed 18MB". No LLM/tokens/KV-cache anywhere in the repo.
- **Copy-pasted-from-hoops numbers, false for pitch:** `:36,53,73,84` "48-d L2" (pitch ships 16-d), `:36` "17 families" (pitch has 3 families / 16 features).
- **"92% match wins"** `:19,27,47,88,90` — actually the `WIN_SIMILARITY` cosine **threshold** in `game.js`, not a win rate.
- **Hardcoded/synthetic charts** in `assets/dashboard.js`: `:51` "drift ↓18% after Procrustes" (drawn, not computed), `:66` "MAE 4.268 → 3.8" (a hoops number), `:68` "555→128→48 L2 527K params", `:74` `passes=[1,0,1,1,1,1,1,0,1,1,1] // 9/11` (fake eval bars); `:47-50` era chart is a `Math.sin()` synthetic curve.

**Fix:** delete the KV-cache/tok-s/LLM lines (`dashboard.html:34,37`); correct 48-d→16-d and 17→3 families (`:36,53,73,84`); relabel "92% win" → "92% cosine-match threshold" (`:19,27,88,90`); delete or recompute the hardcoded `dashboard.js` chart numbers (`:51,66,68,74`). Game + Python pipeline need no change.

---

## vector-equities — data MIXED→mostly FABRICATED, assets FABRICATED, metrics FABRICATED (worst site)

Two divergent stacks both ship into the one page.

**(A) KPI-card stack = SYNTHETIC.** `pipeline/rebuild_all.py:17-24` runs `build_demo_v3.py --companies 1200` → `train_mtnn.py:669` → `pipeline/data/mtnn_report.json` → `index.html:118-121` KPI card (purity@20 / sector / recall@10 / towers / d). `build_demo_v3.py:43-77` is **fully synthetic** — `np.random.choice`/`normal` for sectors, archetypes, sector/archetype bias, macro, noise. So the headline quality metrics on a finance site are computed from **1,200 fabricated companies**.

**(B) Career/"real" stack = MIXED + irreproducible.** `build_real_v6_towers_real.py:1-5` uses real GPR/EPU CSVs + yfinance commodities but self-admits "Industry tower: synthetic but conditioned on real … shocks"; `build_real.py:629,634` injects `np.random` placeholders for `div_yield`/`inst_pct` even in the "real" builder. Feeds `model_career` → `export_v6_real_assets.py` → `assets/real_data.json` (the plotted points/embeddings).

**Shipped assets — FABRICATED per-company signals + hardcoded metric literals.** `export_v6_real_assets.py`:
- `:214` `skills = (np.random.rand(12) * 60 + 20).tolist()` — per-company "skill grades" are random noise (or, `:210`, copied from a prior run's random values).
- `:211,215` `archetype = ARCHETYPE_NAMES[i % len(...)]` — cyclic **modulo**, not the model's archetype head (`:199-200` comment admits "fallback cycle").
- `:263-267` hardcoded metric literals baked into shipped JSON: `val_recall 0.882`, `purity 0.6586`, `sector_acc 0.5535`, `cqs 0.6347`; `:264` `test_recall = ckpt.get("ic", 0.5066)`. Copied into `manifest.json` at `:299-303`.
- Irreproducible: **0 `.pt` committed** (`git ls-files | grep .pt` = 0) → `:54 raise SystemExit("No checkpoint found")` on clean checkout; `assets/real_data.json` is a frozen artifact that cannot be regenerated.

**Displayed metrics — FABRICATED in the browser.** `index.html:291-294`: the "Next FY Projection vs Actual (z-scored)" table renders `actual/pred/err` from **`Math.random()`**, captioned `:76` "Projection based on current year embedding and historical transitions." Pure noise presented as model output on a finance site. The Skills Radar (`:66-67`, `drawRadar` `:297`) plots the `np.random` skills.
Positive: `index.html:140` honestly discloses S&P500-expansion rows carry "sector-centroid+noise placeholder embeddings" and "not investment advice."

**Fix:**
1. **Delete** `index.html:291-294` `Math.random()` next-FY table (or wire to real held-out career-model predictions).
2. **Remove** `export_v6_real_assets.py:214` random skills + `:211,215` modulo archetypes — compute real skill percentiles and use the model archetype head; **delete** hardcoded literals `:263-267,264` and read them from the checkpoint/eval report.
3. **Stop** training the shipped KPI card on `build_demo_v3` synthetic — retrain `mtnn_report.json` on `train_matrix_real.npz`, or relabel the KPIs "SYNTHETIC DEMO — not real data."
4. **Commit** `mtnn_career_v6_best.pt` (or relabel `real_data.json` "frozen / irreproducible").

---

## vector-gridiron — REAL end-to-end

**Training data — REAL public.** `pipeline/nfl_data.py:29,33` nflverse GitHub releases + `nfldata/games.csv`; `build_vectors.py:18-20` `player_stats_<season>.csv`; `build_features.py:26` imports `nfl_data`; `build_rz.py:115`/`build_opportunity.py` nflverse play-by-play parquet; `build_adp.py:71,83,92` ADP from `fantasyfootballcalculator.com` + `api.myfantasyleague.com`. `train_mtnn.py:15,33` requires `train_matrix.npz` from `build_features` (real). No `np.random` in the train/asset path.

**Shipped assets — honest.** `mtnn_report.json` from `train_mtnn` on the real matrix. `build_lookback.py:120` `mock_draft` is a VOR-ordered draft **simulation**, honestly labeled `:472` "Seeded from real NFL results via VOR-ordered mock drafts; the grading + narrative engine is source-agnostic and accepts a real league's draft history." `composite_score.py:33-36` `BASELINE mae 4.296 / cqs 63.16` is traceable (GOAT: == README == hillclimb tables). `verify_accuracy.py` is a real gate.

**Displayed metrics — honest.** `index.html` has no hardcoded metric literals (grep clean). Minor pre-existing smell (GOAT): `verify_accuracy.py` G6 greps the README for substrings (presence, not truth).

**Fix:** none for data/asset provenance. Optional: fix the G6 self-referential check.

---

## Worst fabrications (ranked — data feeding a model or shown publicly as real)

1. **equities `index.html:291-294`** — `Math.random()` rendered as "Next FY Projection vs Actual" on a **finance** site, captioned as a model projection. A live, public, pure-noise lie.
2. **equities `export_v6_real_assets.py:214 / :211,215 / :263-267`** — `np.random.rand(12)` skill grades + modulo archetypes + hardcoded metric literals baked into shipped `real_data.json`/`manifest.json`, irreproducible (no checkpoint). Fabricated per-company signals + fake quality numbers on a finance site.
3. **equities `rebuild_all.py` + `build_demo_v3.py`** — the headline KPI card (`index.html:118-121`) is trained on **1,200 fully-synthetic `np.random` companies** (`mtnn_report.json`). Fabricated training data feeding a public metric.
4. **pitch `dashboard.html` / `dashboard.js`** — fabricated LLM/KV-cache/"7-8 tok/s" stack + hardcoded chart numbers (MAE 4.268→3.8, 527K params, 48-d, drift 18%, 9/11 pass bars) + "92% win" that is a cosine threshold. Public marketing lies (does not feed a model; the game itself is honest).
5. **hoops `model.html:324-329`** — hardcoded transductive CQS strip (`recall@10 1.0` = memorization, `purity 0.8726`). Real numbers, transductive framing; mitigated by the honest held-out strip shown beside it. Mildest.

The common enabling condition (per GOAT cross-repo map): template **scaffolding** was copy-pasted between forks, and the fabrications entered exactly at those copy-paste seams (pitch's hoops-residue dashboard, equities' hoops-port demo stack). The real data pipelines (hoops NBA, pitch StatsBomb, gridiron nflverse) are honest; equities is where real data was never wired to what ships.
