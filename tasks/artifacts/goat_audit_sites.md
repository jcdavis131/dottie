# GOAT audit — operator's standalone public repos (Carmack/Bellard rubric)

READ-ONLY static audit. No edits, installs, docker, test execution, git mutations, or network.
Scope: `vector-hoops`, `vector-pitch`, `vector-equities`, `vector-gridiron` (static game/eval sites — shipped surface is HTML/JS + JSON assets; Python pipelines regenerate assets) and `agent-eval` (an agent-eval / hillclimb harness, architecturally separate). Date: 2026-07-23.

Rubric dimensions (1–10, higher = leaner/more honest/more self-contained):
1. Dependency economy · 2. Dead code & speculative abstraction · 3. Self-containedness · 4. Test honesty · 5. Hot-path clarity · 6. Honest notes.

Exclusions applied everywhere: `.claude/worktrees/**`, `.venv` (a full 9,718-file venv lives at `vector-hoops/pipeline/.venv`), `node_modules`, `__pycache__`, `.git`, `.pytest_cache`, `.ruff_cache`.

---

## Scorecard summary

| Repo | Dep | Dead | Self | Test | Hot | Honest | Worst offense (one line) |
|---|---|---|---|---|---|---|---|
| vector-hoops | 6 | 3 | 6 | 7 | 6 | 6 | `make ci` prints "CI green ✓" while running **zero** real tests (targets non-existent `pipeline/tests`, `\|\| true` swallows failures, `sync` installs a missing `requirements.txt`) |
| vector-pitch | 6 | 4 | 7 | 8 | 8 | 4 | `dashboard.html`/`dashboard.js` "Lab" page fabricates an LLM/KV-cache/"7-8 tok/s"/48-d/92%-win stack that does not exist |
| vector-equities | 7 | 2 | 4 | 7 | 3 | 4 | shipped `assets/real_data.json` mixes fabricated (`np.random.rand(12)` skills, modulo archetypes) + hardcoded metric literals, and is irreproducible (no checkpoint committed) |
| vector-gridiron | 8 | 5 | 8 | 6 | 7 | 8 | 422 LOC of dead `promote_bias/affine_calib.py` that mutate shipped assets in place, superseded by inline logic in `train_mtnn` |
| agent-eval | 6 | 5 | 4 | 7 | 8 | 6 | `scoreboard.md` "authoritative auto-generated" rollup is stale-schema, silently drops models, and shows a HTTP-500 run as its only datum |

---

## vector-hoops

Character: the mature template all four siblings forked from, and by far the largest — provenance and test *content* are unusually honest, but it has metastasized into ~38% unreachable pipeline code, competing rebuild orchestrators, and a `make ci` that reports success while executing nothing. Counts: **109** pipeline `.py` (25,555 LOC) · **46** `assets/*.js|css` · **10** shipped HTML · **11** `test_*.py` (1,442 LOC) · **8** declared deps.

**1. Dependency economy — 6/10.** **4 of 8 declared runtime deps have zero `import`** across `pipeline/`+`scripts/`: `pandas`, `scipy`, `scikit-learn`, `tqdm` (`pyproject.toml:9-16`). `scipy`/`sklearn`/`tqdm` are pure dead weight; `pandas` is at least transitive (nba_api DataFrames). The `sklearn`/`scipy` case is the expensive lie: `build_vectors.py:1-15` promises "PCA(3) … k-means archetypes" but both are **hand-rolled on `np.linalg`** — 1 total string mention of `sklearn|scipy`, no import. No used-but-undeclared deps. CDN footprint tiny: Google Fonts (5 pages) + 1 `unpkg.com/posecode-embed` (`player-animations.html`); `mtnn-onnx.js:16` pulls onnxruntime from jsdelivr but that file is never loaded (§2).

**2. Dead code & speculative abstraction — 3/10 (worst dimension).** **52 of 109 pipeline scripts (9,602 LOC, ~38%) unreachable** from the real entrypoints (`export_assets.py`+`update_dataset.py`+`train.sh` invoke only 47), un-imported, non-test. **12 true orphans (1,358 LOC)** referenced nowhere incl. docs — and several (`build_map_lite`, `chemistry_analysis`, `deadline_analysis`, `faderfinisher_analysis`) still *produce shipped assets* with no automated regen path. **19 of 46 asset JS/CSS (2,621 LOC) loaded by NO page** (boundary-checked), including the entire legacy engine `game.js`(111)+`insight-engine.js`(22 KB) — superseded by `past-modern-game.js`; and `mtnn-full/onnx/worker.js` appear only in `sw.js`'s precache list (force-downloaded to every visitor, executed by nothing). **5+ competing "one-command rebuild" orchestrators (3,098 LOC)**: `train.sh`→`train_mtnn.py`, `Makefile:train`→`train_towers.py`, `rebuild_all.py` (250 LOC, "mirrors ./train.sh"), `train_mtnn_v6.py` stub, `retrain_universe.py`. Deletable ≈ **4,230 LOC high-confidence**, ~12,000 if research scaffolding is cut. Committed 0-byte `pipeline/build_run.log`.

**3. Self-containedness — 6/10.** Client assets all present (`export_assets.py:299-317` self-reports N/N present); the core daily game runs client-side. **NOT pure static** — 4 Vercel serverless fns back live features (`api/{ip,leaderboard,team-locks,telemetry}.js`; `leaderboard.js:223`, `past-modern-game.js:458 fetch('/api/ip')`), contradicting README:6 "Static site, no backend" (game degrades gracefully; leaderboard/telemetry need the backend). Broken documented setup: `Makefile:4 sync` installs `pipeline/requirements.txt` — **file does not exist** (deps only in `pyproject.toml`).

**4. Test honesty — 7/10.** No mocks, no network, no skips across all 11 files (`grep mock|monkeypatch|patch` = 0; network = 0; `skip|xfail` = 0). Content genuinely behavioral: `test_skills.py:47-118` asserts grade bounds, per-season era-honest means ∈[42,58], probe round-trip ≤1pt, face validity (Curry 2015-16 shooting≥95). **But 10 of 11 `test_*.py` are gate scripts, not pytest** (a `main()`+`sys.exit(1)`, **0 `def test_`, 0 bare `assert`**); only `test_mtnn_validation.py` has real pytest funcs (5). So README's `pytest pipeline/ -q` collects **5 tests and silently runs none of the invariant gates** — those fire only via direct `python pipeline/test_skills.py` subprocess calls inside `export_assets.py`. Honest content, dishonest discovery.

**5. Hot-path clarity — 6/10.** `export_assets.py` build path is linear and readable — one `main()`, sequential `run(name,cmd,required=)`, ends writing a `manifest.json` with scrupulous provenance labeling (`:274-296` marks figures TRANSDUCTIVE, keeps back-compat keys under "honest names above"). Live in-browser loop is `past-modern-game.js` (35 KB) with sane `if(window.VHMtnn)` progressive enhancement, no optimization theater. Ding: **naming drift muddies the trace** — `build_vectors.py:12` and `train_mtnn.py` headers describe a `game.js`/`InsightEngine` loop that is dead; a reader tracing "the game loop" lands on dead files.

**6. Honest notes — 6/10.** 0 TODO/FIXME/XXX/HACK anywhere. Provenance unusually good where it counts: `eval_scoreboard.json` carries sha256 of embedding+vectors assets, `computed_at`, `tie_handling:"pessimistic"`, and *honestly reports the held-out collapse* (test top1 0.1633/top5 0.3633 vs train 0.277/0.5399 — memorization not hidden); `train.sh:14-19` openly documents the prior v5 "recall@10=1.0 was memorization." Contradictions: README:14 headlines "0.977 recall@10, 0.6717 purity@20" (transductive framing) while the committed held-out scoreboard shows test top5=0.3633; README:6 "no backend" vs 4 `api/*`; `train_mtnn.py:1` docstring "MTNN v4" while repo ships v5; `build_vectors.py:12` cites dead `game.js`.

**Worst offense:** the `Makefile` prints a green check over nothing. `ci: offline test` → `@echo "CI green ✓ — offline fixtures, no external network"`, but `test`→`eval`→`python3 -m pytest pipeline/tests -q || true` targets **`pipeline/tests/` which does not exist** (tests are `pipeline/test_*.py` at top level), `sync` installs a **missing `pipeline/requirements.txt`**, and every failure is swallowed by `|| true`. `make ci` runs no real tests and reports success — the one interface a maintainer trusts most.

**Top-3 fixes:**
1. Drop unused `scipy`/`scikit-learn`/`tqdm` from `pyproject.toml:9-16` (reconsider `pandas` — transitive via nba_api). Gate: `grep -rEl '^\s*(import|from) (scipy|sklearn|tqdm)' pipeline/*.py scripts/*.py` → empty.
2. Delete the 19 unreferenced asset JS (2,621 LOC) and remove `mtnn-full/onnx/worker.js` from the `sw.js` precache. Gate (pre-delete safety): for each basename, `grep -rlE "[\"'/]NAME\.js[?\"']" *.html` → empty before removing.
3. Fix the lying Makefile: repoint `eval` at `pipeline` (not `pipeline/tests`), drop `|| true`, and add `pipeline/requirements.txt` or repoint `sync` at `pip install -e .[dev]`. Gate: `test -d pipeline/tests || echo BROKEN-eval; test -f pipeline/requirements.txt || echo BROKEN-sync` → both silent after fix.

---

## vector-pitch

Character: the Python core and `game.js` are provenance-honest and self-contained; the "Lab" dashboard is a fabricated marketing layer that contradicts the code, and a whole MTNN sub-pipeline is orphaned from the shipped game.

**1. Dependency economy — 6/10.** `pyproject.toml:9-14` declares numpy/pandas/scikit-learn/torch. Actual imports across `pipeline/`: numpy ×4, torch ×1 (`train_mtnn.py`), **pandas 0, sklearn 0**. sklearn is provably replaceable — already replaced: `build_vectors.py:471` hand-rolls PCA via `np.linalg.svd`, `:475-485` hand-rolls k-means. CDN tags in `index.html`+`dashboard.html`: **0** (favicon is inline `data:` URI); fully self-contained front end.

**2. Dead code & speculative abstraction — 4/10.** No build entrypoint (no Makefile/script). `build_features.py` (370) + `train_mtnn.py` (806) = **1,176 LOC MTNN track fetched by zero shipped JS** — `game.js:22-23` loads only `vectors.json` + `difficulty_calibration.json`. The embeddings ship anyway: `assets/pitch_mtnn_embeddings.json` (804 KB) + `_pre_con.json` (798 KB) ≈ **1.6 MB never requested by any page**. Orphan `assets/site-nav.js` (44 LOC, brands "VECTORHOOPS", 7 of 8 routes 404). `train_mtnn.py:175 split_by_family` defined, never called. Speculative hooks in `game.js`: `projectVector` (`:1130`) reads `DATA.proj` never emitted → always null; weighted-pick path (`:209-220`) never fires. `vercel.json:5-7` rewrites `/model→/model.html` — file absent. Deletable ≈ **1,250 LOC + 1.6 MB assets**.

**3. Self-containedness — 7/10.** Site as pure static: yes — `game.js` fetches only local `assets/*.json` (both present), telemetry POST failures swallowed (`:67`), 0 external asset requests. Pipeline mixed: `build_difficulty.py` fully offline; `build_vectors.py` needs StatsBomb but `pipeline/cache/` holds 2,339 cached files (resumable). Two README-omitted gotchas: `build_features.py:32` bare `from build_vectors import …` needs cwd=`pipeline/`; `train_mtnn.py:568` default `--matrix train_matrix.npz` + manifest **do not exist** (ships `tm_*` variants) → `python pipeline/train_mtnn.py` fails out of the box.

**4. Test honesty — 8/10.** `tests/test_difficulty.py` — 13 tests (`pytest --collect-only` exit 0), 189 LOC, no network. Behavior-heavy: RNG parity vs game.js from node-recorded fixtures (`:38-59`), monotonicity, 6 rotation-gate tests with exact expected outcomes (`:115-149`), shipped-artifact schema cross-check (`:159-189`). No skips/mocks/tautologies. Cap: only `build_difficulty.py` is tested; `build_vectors`/`build_features`/`train_mtnn` (73% of pipeline LOC) have zero tests.

**5. Hot-path clarity — 8/10.** `game.js` (1,506 LOC) is a procedural IIFE, no framework, clean sections (RNG → target builders → zone math → canvas → SVG → 3D map → init); no god-function (largest `renderMap` ~46 LOC). `cosineSim`/`dot` are plain loops, zero unmeasured cleverness. One messy spot: `renderHints` (`:983-1021`) tangled innerHTML rebuild. `build_vectors.main()` long (~210 LOC) but strictly sequential.

**6. Honest notes — 4/10.** Python/core honesty is exemplary (`build_difficulty.py:29-38` repeatedly flags "MODEL ESTIMATE, not measured telemetry"; `train_mtnn.py:6-7` "falsifiable, not asserted") — which indicts the dashboard. `dashboard.html`/`dashboard.js` contradict the code: "92% match wins" (`:19,27,88`) is actually `WIN_SIMILARITY` cosine **threshold** (`game.js:26`); "48-d L2" (`:53,73,84`) — default `d_emb=24`, shipped game is 16-d PCA; "17 families" (`:36`) — pitch has 3 families/16 features (copy-paste from hoops); "KV cache 8× … 7-8 tok/s" (`:34,37`) — **no LLM/tokens/KV cache anywhere in repo**; fabricated "MAE 4.268→3.8", "527K params", "drift ↓18%" charts. `api/telemetry.js:1` header says "Vector Hoops"; its `ALLOWED` set rejects the `vp-chimera-*` events game.js emits.

**Worst offense:** the "Lab" dashboard — in a repo whose whole identity is documented honesty, this is the one surface that lies (LLM/KV-cache stack that doesn't exist, 48-d embedding never produced, 92% "win rate" that is a similarity threshold, invented chart numbers).

**Top-3 fixes:**
1. Drop unused `pandas`+`scikit-learn` from `pyproject.toml:9-14`. Gate: `rg -n "pandas|sklearn" pipeline/` → expect 0.
2. Delete orphan `assets/site-nav.js`; fix dangling `/model` rewrite. Gate: `rg -n "site-nav" index.html dashboard.html` → 0; `ls model.html` → missing.
3. Reconcile every dashboard claim with code. Gate: `rg -n "tok/s|48-d|17 families|92%|KV|4.268|527K" dashboard.html assets/dashboard.js`.

---

## vector-equities

Character: a `vector-hoops` port (basketball → equities) that sprawled into ~48% dead code across parallel versioned generators, ships fabricated per-company data on a finance site, and is irreproducible from a clean checkout. Pipeline = 15,692 LOC across 57 `.py` files; site = 1 `index.html` + committed JSON.

**Live-vs-dead map (core finding):** three "entrypoints" point at three divergent chains, and two parallel MTNN stacks both ship into the one page. Career stack (`feature_spec`→`dataset_career`→`model_career`→`train_career_mtnn_v6`→`export_v6_real_assets` ⇒ `assets/real_data.json`, the plotted points). Demo/hoops-port stack (`model.py`+`train_mtnn.py`+`composite_score.py`, wired by `rebuild_all.py:18-24` on synthetic `build_demo_v3` ⇒ `mtnn_report.json`, the KPI card at `index.html:118,121`). README quickstart (`README:19-27`) references a third path incl. `pipeline/regen_assets.py` — **file does not exist**.

**1. Dependency economy — 7/10.** `index.html`: **0 CDN** (1 `<script type=module>` `:84`, 0 `<link>`, 0 external hosts) — fully self-hosted. Declared-unused: `pyarrow` (`pyproject.toml:14`) — 0 imports/parquet usage. Used-undeclared: `scipy` (`eval_v6_real.py:130`, rides transitively on sklearn) and `yfinance` (`build_real.py:230`). Core deps justified (numpy 28 files, torch 12; pandas narrow at 4).

**2. Dead code & version proliferation — 2/10 (headline).** **~7,500 LOC high-confidence dead / 15,692 ≈ 48%** (up to ~56% incl. orphaned research/eval), **~25 dead files**. Method: 0 cross-references (grep across `*.py/*.md/*.html`), neither documented entrypoint nor producer of a committed asset. `build_real` family: 7 variants, 1 live (`build_real_v6_towers_real.py`) — dead siblings ≈ **4,682 LOC**. `parse_def14a` ×5 (v3 live), `build_demo` ×3 (v3), `fetch_submissions` ×3, `score_trades` ×2 (both 0-ref), `tune_entry_head` ×2, `train_career_mtnn` non-v6 (640 LOC dead). **`towers_v6/` subpackage (5 files, 368 LOC) is dead** — imported only by the dead `build_real_v6_towers.py`; its funcs are `synthetic_*` (`industry_gdelt.py:99` TODO "for now return synthetic"). `dataset_career_v6.py` = broken shim (wrong import path); `mtnn_validation.py` imported by nobody.

**3. Self-containedness — 4/10 (split).** Static serve: excellent — all consumed assets committed, `index.html` fetches only `./assets/…` + `./pipeline/data/…`, 0 CDN, works offline. Pipeline reproducibility: broken — **no `.pt` checkpoint committed** (`git ls-files` → 0 `.pt`), no `train_matrix_v6.npz` ⇒ `export_v6_real_assets.py:54` raises `SystemExit("No checkpoint found")` on clean checkout; `load_bundle` silently falls back to the v4-era matrix. Upstream needs SEC EDGAR + yfinance + GPR/EPU/BDRY CSVs (uncommitted); README's `regen_assets.py` missing.

**4. Test honesty — 7/10 (honest but narrow).** `pytest --collect-only` ⇒ **8 tests, all in `tests/test_eval_sector_coherence.py`** (pipeline testpath = 0). Genuinely behavioral: purity==1.0 on separated clusters (`:46`), near-chance on shuffled labels (`:55`), silhouette>0.5 (`:76`); no network, not tautological. Target `eval_sector_coherence.py` is pure numpy with an honest closed-form random-assignment baseline (`:116`) and self-discloses the TF-IDF baseline is "not computable from the repo" (`:23`). Deductions: 2 tests hard-require committed artifacts (assert-fail not skip); the 15k-LOC model/train/build layer is untested; `mtnn_validation.py:37` ships `"tower_spread_mean": 0.5, # placeholder`.

**5. Hot-path clarity — 3/10.** Three entrypoints, three chains, zero convergence — no single orchestrator reproduces `real_data.json`. KPIs and points come from different models (card = demo stack `mtnn_report.json` `:121`; map = career stack `real_data.json` `:144`). Silent version resolution: `load_bundle` 4-way matrix fallback + 3-way checkpoint fallback. The in-browser JS is fine (one linear inline module: fetch 3 JSON → render); the **Python build layer is the soup**.

**6. Honest notes — 4/10.** **Fabricated shipped data** on a claims-making finance site: `export_v6_real_assets.py:214-215` fills per-company "skill grades" with `np.random.rand(12)*60+20` and archetypes by `i % len` (cyclic modulo). Hardcoded metric literals baked into shipped JSON: `val_recall 0.882, purity 0.6586, sector_acc 0.5535, cqs 0.6347` (`:263-266`); `test_recall = ckpt.get("ic", 0.5066)`. Count inconsistency: `pyproject:4` "20 towers / IC 0.549" vs `README:8` "17 family towers" vs `index.html:83` "S&P 500 (503)" vs `README:8` "283 tickers". POSITIVE (rare): `index.html:140`/`README:42` honestly disclose S&P500-expansion rows carry "sector-centroid+noise placeholder embeddings" and "not investment advice." Markers: 1 TODO total, header typo `mtnn_validation.py:2` "mirors".

**Worst offense:** the shipped `assets/real_data.json` mixes fabricated (`np.random.rand(12)` skills, modulo archetypes) and hardcoded (`cqs 0.6347`, `val_recall 0.882`) values while being irreproducible (no checkpoint committed → `SystemExit` at `export_v6_real_assets.py:54`). Fabricated per-company signals + hardcoded quality numbers + no reproducible provenance, on a finance site. The ~48%-dead version sprawl is the enabling condition — nobody can tell which generator is authoritative.

**Top-3 fixes:**
1. Delete the 0-reference dead set (~7,500 LOC / 25 files: `build_real{,_v2,_v4_exec,_v5_career,_v6_towers,_from_summary}.py`, `train_career_mtnn.py`, `score_trades{,_v2}.py`, `tune_*`, `dataset_career_v6.py`, `mtnn_validation.py`, `towers_v6/`). Gate (pre): `grep -rIl "build_real_v5_career\|train_career_mtnn\b\|score_trades\|tune_entry_head\|towers_v6\|dataset_career_v6\|mtnn_validation" pipeline README.md docs` shows only self/docs; (post): `python -m pytest --collect-only -q` still 8.
2. Fix the README reproducibility lie (replace missing `regen_assets.py` with the real `export_v6_real_assets.py` entrypoint + note the required checkpoint). Gate: `grep -n "regen_assets" README.md` returns empty after fix.
3. Strip fabrication from the asset generator (remove random-skill + modulo-archetype fallbacks and hardcoded metric literals). Gate: `grep -nE "np.random.rand\(12\)|ARCHETYPE_NAMES\[i % |0\.882|0\.6586|0\.5535|0\.6347" pipeline/export_v6_real_assets.py` returns nothing.

---

## vector-gridiron

Git state (read-only): branch `claude/model-training-workflow-plan-n5vep5`; dirty tree = 7 modified `assets/*.json` (rebuilt artifacts, uncommitted → committed assets lag working tree) + 1 untracked `pipeline/refresh.log` (not gitignored). Treated strictly read-only.

**1. Dependency economy — 8/10.** No manifest of any kind (no pyproject/requirements/setup/package.json) — 3 real deps unpinned for a weekly-retraining ML repo. But third-party surface is tiny: only numpy/torch/pyarrow across 4,979 pipeline LOC (`pyarrow` lazily imported inside a function, `build_features.py:38`). `nfl_data.py` networking is pure stdlib (urllib/csv/gzip — no pandas/requests). Front end: `index.html` has exactly 1 local `<script>` (`:454`), 1 local stylesheet, inline-SVG favicon — **zero CDN**.

**2. Dead code & speculative abstraction — 5/10.** `promote_bias_calib.py` (204) + `promote_affine_calib.py` (218) = **422 LOC, zero runtime callers**; logic duplicated inline in `train_mtnn.main` (`:600-676`, `:817-839`). `train_models.py` (21) is a pure re-export wrapper of `train_mtnn.main()` — `refresh.py` calls `train_mtnn` directly. Parked feature branches gated by `False` flags (`build_features.py:36-41`: `HILL_CLIMB_FEATURES`/`EWMA_FEATURES`/`EWMA_SPAN5`) gate 8+ never-run branches. Dev orphans: `family_ablation.py` (107), `feature_inspect.py` (71). Deletable ≈ **443 LOC** at zero behavior change; ~770 with parked branches + dev tools.

**3. Self-containedness — 8/10.** Site runs from committed static assets (`app.js:96-102,2726` fetches 7 local JSON; all core boards work with no backend). Not purely static (correctly documented): one serverless fn `api/espn.js`, browser-direct Sleeper public API, `sleepercdn.com` images — dynamic surface confined to league-sync. Pipeline not offline from clean checkout: `nfl_data.py` fetches nflverse; `pipeline/cache/` gitignored; `--offline` needs pre-warmed cache (README honest).

**4. Test honesty — 6/10.** No pytest suite (`find test_*.py` = none; collect-only = 0). "Tests" = `verify_accuracy.py` + 4 `.mjs`. `verify_accuracy.py` is a real gate (~45 checks incl. behavioral: model MAE < baselines `:55-58`, CQS ≥ 50 `:100`, backtest Spearman ≥ 0.30 `:147,149`, all 6 positions `:128`; nonzero exit on fail, no network). Weaknesses: verifies already-built JSON not model code; G6 (`:82-94`) is self-referential — greps the README for substrings, enforcing words are *present* not claims *true*.

**5. Hot-path clarity — 7/10.** `refresh.py` (112) clean & linear (invalidate → build_vectors → train → backtest → adp → kdst → lookback → deploy, non-core stages try/except non-fatal). `build_features.py` (1,006) decomposed (~25 fns) but two big hot loops `assemble_row` (~197) + `build` (~224). `train_mtnn.py` (1,048) is the density hot-spot: `main()` ~580 lines with many nested closures. Browser: single `requestAnimationFrame` canvas loop; no unmeasured perf claims. `app.js` is a 144 KB / ~241-fn flat monolith.

**6. Honest notes — 8/10.** TODO/FIXME/XXX/HACK ≈ 0 real (only `XXXX` in an ESPN-cookie example). Provenance consistent: README MAE 4.296 / CQS 63.16 == `composite_score.py:33-36` BASELINE == hillclimb tables; parked flags carry measured labels. Minor stale: `composite_score.py:15` "~4.26 MAE" vs BASELINE 4.296; `refresh.py:4` docstring says "train_models projects…" but calls `train_mtnn.main()` directly.

**Worst offense:** `promote_bias_calib.py` + `promote_affine_calib.py` — 422 LOC of dead code with zero callers that **mutate shipped production assets in place** (`nextgame.json`/`projections.json`/`mtnn_report.json`); identical calibration already inline in `train_mtnn.main`. Dead *and* dangerous (out-of-band run rewrites deployed artifacts off a stale checkpoint).

**Top-3 fixes:**
1. Delete `promote_bias_calib.py`, `promote_affine_calib.py`, `train_models.py` (−443 LOC). Gate: `grep -rnE "promote_bias_calib|promote_affine_calib|import train_models" pipeline README.md tasks docs` → no runtime hits; then `python pipeline/verify_accuracy.py` still `0 failure(s)`.
2. Add pinned `requirements.txt` (numpy/torch/pyarrow). Gate: `grep -rhoE "import (numpy|torch|pyarrow|pandas|requests|scipy|sklearn)" pipeline/*.py | grep -oE "…" | sort -u` → exactly those 3.
3. Fix stale notes + gitignore the log. Gate: `grep -n "4\.26\|train_models" pipeline/composite_score.py pipeline/refresh.py`; `git check-ignore pipeline/refresh.log`.

---

## agent-eval

Architecturally separate from the vector-* sites — an agent-eval / ReAct-hillclimb harness (no build_vectors/composite_score/train_mtnn). Shares only the operator, not the code shape. Load-bearing external dep: a `sys.path` hack to sibling repo `../AgenticOS` (`run_eval.py:33-34`).

**1. Dependency economy — 6/10.** No dependency manifest of any kind. Exactly one third-party import: `yaml` (PyYAML) at `run_eval.py:25` / `test_task_specs.py:13`, undeclared. The eval cannot import without `../AgenticOS` on disk (undeclared, invisible to packaging). Core is genuinely lean: `judge.py`/`trajectory.py` are zero-third-party (stdlib only); no HTML/CDN.

**2. Dead code & speculative abstraction — 5/10.** `judge.py` (85) + `test_judge.py` (63) = ~148 LOC with **zero runtime consumers** (`run_eval.py` imports `match_trajectory`, never the judge) — self-labeled "Dottie-judge ready", built ahead of a consumer that doesn't exist. `export_sft_corpus.py` (122) dead-in-practice (only named in docstrings); its only viable input makes `result_to_transcript` return None → zero documents producible today. `trajectory.py` "unordered" mode (`:94-117`, incl. greedy-bipartite) used by no task (all 8 specs use subset/superset). Deletable ≈ 148 LOC now / ~270 LOC with export path (13–24% of 1,113 script LOC).

**3. Self-containedness — 4/10.** Does NOT run from a clean checkout — coding tasks call `reset_repo` → `git checkout baseline`/`git clean` against `../agent-eval-scratch` (`run_eval.py:58-60,115`), which is neither vendored nor bootstrap-documented. Every scoring run needs a live Ollama server + `../AgenticOS`; `ava_claw_run.py` further needs Docker + `../ava-agi` + a checkpoint volume. Honesty credit: README/`plan-hillclimb.md` are candid about Ollama/VRAM/ava-agi; the gap is the *undocumented* scratch git repo.

**4. Test honesty — 7/10 (weighted).** `test_trajectory.py` ~23 behavioral assertions over the pure matcher (no network/mocks). `test_judge.py` tests parsing/prompt/end-to-end with a fake `complete()` — high-quality tests of a module nothing wires in. `test_task_specs.py` parses all 8 specs, gates tool names, and **source-greps `run_eval.py` to pin the presence-not-truthiness guard** (`:95-96`) — unusually honest. Caveat: these run assertions at import time (not `test_` functions), so they are `python scripts/test_x.py` scripts, not pytest-collectable. **Real wins = zero**: the judge never runs in any eval; the number-producing hot path (`score_task`+`write_scoreboard`) has no test; the sole `scoreboard.md` row (`ava:nano-chat 0/1`) is an HTTP-500 errored run, honestly scored FAIL.

**5. Hot-path clarity — 8/10.** `run_eval.py` main loop (`:223-275`) flat and linear; `score_task` (`:105-175`) a clean sequence; `match_trajectory` (`:71-137`) a flat 4-mode if-ladder with early-return diagnostics. Event schema matches the harness exactly (`harness.py:375` ↔ `run_eval.py:81,117,139`). No unmeasured micro-opts.

**6. Honest notes — 6/10.** TODO/FIXME/XXX/HACK in code = 0. Comments exemplary (`run_eval.py:128-134` explains presence-not-truthiness; `export_sft_corpus.py` admits "untested against a real success"). But `scoreboard.md` lies three ways: (a) header "do not hand-edit" yet stale-schema (missing the `trajectory` column `run_eval.py:206` emits); (b) `write_scoreboard` tables only the current invocation's models (`:178-220,272`), so a partial `--model ava:nano-chat` run silently erased `qwen2.5:1.5b` despite `results/qwen2.5_1.5b.json` retaining 8 rows; (c) README "Scored 0/6" is stale vs the live artifact.

**Worst offense:** `scoreboard.md` — the "authoritative, auto-generated, do-not-edit" rollup is the least trustworthy file in the repo: stale-schema, silently model-dropping, and shows an HTTP-500 errored run as its sole datum. It contradicts both the code that generates it and the `results/` directory beside it.

**Top-3 fixes:**
1. Make the rollup read all `results/*.json`, not just the current run. Gate: `grep -c '^| ava\|^| qwen' scoreboard.md` should equal distinct models in `results/` (today 1 vs 2).
2. Declare deps: add `requirements.txt` (PyYAML); make the `sys.path.insert` fail loudly when `../AgenticOS`/scratch absent. Gate: `python -c "import yaml"` + `python -c "import sys;sys.path.insert(0,'../AgenticOS');import harness"` exit 0.
3. Resolve the 148 LOC of unwired judge — wire into a real rubric or move under `future/`. Gate: `grep -rn "import judge\|from judge" scripts/*.py` returns a runtime consumer.

---

## CROSS-REPO DRIFT MAP (the four vector siblings)

The four vector repos are **self-acknowledged forks of one template**, and they say so in their own headers — this is the opposite of hidden drift:
- `vector-pitch/pipeline/build_vectors.py:2`: "Soccer sibling of Vector Hoops … same shape, same philosophy."
- `vector-gridiron/pipeline/build_vectors.py`: "Football sibling of Vector Hoops / Vector Pitch — same shape, same philosophy."
- `vector-equities/pipeline/train_mtnn.py:2`: "cloned from vector-hoops train_mtnn.py v4 Phase B."
- `vector-equities/pipeline/composite_score.py:2`: "mirrors vector-hoops/pipeline/composite_score.py."

### Shared-shape files and how far they diverged

**`build_vectors.py` — the most genuinely-shared shape (the one honest template).** Same 4-step recipe verbatim in all three that have it: per-X rate (per-100-poss / per-90 / per-game) → z-score *within context* (season/tournament) → PCA(3) map + k-means(K=8) named archetypes → one static `assets/vectors.json` the game serves with zero backend.
| repo | lines | def/class | normalization axis |
|---|---|---|---|
| hoops | 950 | 19 | per-100-poss, within-season |
| pitch | 551 | 12 | per-90, within-tournament |
| gridiron | 320 | 6 | per-game, within-season |
| equities | absent | — | (uses a different `build_real_v6*` data model) |
Divergence here is **scale-by-domain, not rot**: same skeleton, sized to the sport's data complexity. equities dropping it entirely is the honest signal that the template does not fit a non–time-series-of-athletes domain.

**`train_mtnn.py` — four independently-evolved forks (v1/v2/v4).** Same ancestral architecture recognizable in every header (residual family towers + masks → gated fusion → L2 embedding → multi-task heads), but each is a different generation with domain-specific heads.
| repo | lines | def/class | version | domain heads |
|---|---|---|---|---|
| hoops | 1,959 | 62 | v4 | archetype/position/skills/next-profile/salary/pedigree |
| gridiron | 1,048 | 30 | v2 | fpts_ppr + yards/rec/TD + usage + position + pedigree |
| pitch | 806 | 26 | v1 | archetype CE + 16-d profile recon (vs PCA baseline) |
| equities | 675 | 19 | "cloned v4 Phase B" | InfoNCE + archetype + sector + market + valuation |

Quantified overlap (top-level `def` names): **only 3 functions are common to all four** (`family_slices`, `main`, `split_by_family`). Pairwise: hoops∩equities share **13** (`info_nce`, `recall_at_k`, `batch_views`, `embed_all`, `masked_scalar_mse`, `season_index`, …) — equities kept hoops' training-loop/metrics half but rewrote the model class. hoops∩pitch, hoops∩gridiron, pitch∩gridiron each share only **6** — the `nn.Module` skeleton (`__init__`, `encode`, `forward`, `family_slices`, `main`, `split_by_family`) — pitch and gridiron kept the model half and rewrote the training loop. **Different halves were preserved by different forks** — the fingerprint of independent divergence, not a maintained shared core. (`split_by_family` is even dead in pitch — inherited, never called.)

**`composite_score.py` — a shared 15-line promote skeleton wrapped around per-domain math.**
| repo | lines | scale | components | `should_promote` gate |
|---|---|---|---|---|
| hoops | 271 | [0,100] | 10 (recall/purity/…) | CQS+0.5 AND recall/purity floors AND population-validation collapse flags |
| gridiron | 174 | [0,100] | 6 (mae/rmse/r2/bias/pos/cover) | CQS+0.5 AND MAE≤base+0.05 |
| equities | 110 | **[0,1]** | 5 (recall/purity/next_r2/sector/market) | CQS+0.005 AND recall≥0.75 |
| pitch | absent | — | — | — |
The `_clip01` + `WEIGHTS` dict + `component_scores`/`composite_quality`/`should_promote(cqs_delta=0.5)` skeleton is real and near-identical between **hoops and gridiron**. Two divergences are genuine rot: (a) **equities is a hand-rewrite that claims to "mirror hoops" but shares almost no code** — different [0,1] scale, no `WEIGHTS` dict, no `_clip01`, and a **dead `sigmoid` at line 22** (all real sigmoid use is `torch.sigmoid` in other files); (b) **gridiron bolts three unrelated K/DST roster helpers** (`kdst_rows_for_board`, `merge_kdst_into_players`, `walk_forward_mae`, `:102-174`) onto the scoring module — a cohesion smell, wrong file.

**`game.js` — no longer a shared shape at all (opposite architectures).**
| repo | lines | shape |
|---|---|---|
| hoops | 111 | thin **facade** (`window.VHGame` → `InsightEngine`/`VHMtnn`) — **but DEAD**: no page loads it; the live loop is `past-modern-game.js` (35 KB), and `game.js`'s only downstream `insight-engine.js` is dead too |
| pitch | 1,506 | self-contained **monolith** — "Zero deps, zero build", RNG/modes/difficulty gate all inline (live) |
| equities / gridiron | none | not guessing games (equities = insider-trading board; gridiron = fantasy cockpit `app.js`) |
Hoops refactored logic *out* of `game.js` then abandoned even the facade (both `game.js` and `insight-engine.js` are now dead code superseded by `past-modern-game.js`); pitch kept everything *in* one live monolith. The two "same-named" files share no shape — and hoops' copy isn't even shipped. Nothing to extract.

### Template residue that leaked as lies (the real cross-repo cost)
Copy-pasting the *scaffolding* — not the algorithms — is what actually rotted:
- **equities `vercel.json`** rewrites `/model→/model.html`, `/trends→/trends.html` and redirects `/dashboard`, but equities ships **only `index.html`** — all three targets 404. The routes are hoops residue (they resolve in hoops) copied into a repo that never built the pages.
- **pitch `dashboard.html`/`api/telemetry.js`** carry hoops-template numbers/branding ("17 families", "48-d", "KV cache", "7-8 tok/s", header "Vector Hoops") that are false in pitch — the copy-paste is exactly where the lies entered (see pitch worst-offense).
- **Governance itself drifted**: hoops has 3 CI workflows + 9 pre-commit hooks + 8 declared deps; pitch/equities have lint-only + leaner deps; **gridiron (the dirty branch) has NO pyproject, NO pre-commit, NO CI** — undeclared deps entirely. Each sibling inherited less scaffolding than the last.

### DRIFT VERDICT — keep four small self-contained copies (do NOT build a framework)

Argued, not defaulted. A shared `vector-core` package would have to abstract over: three different rate normalizations, four different head-sets and metrics (recall@10/purity vs MAE/RMSE regression vs sector/market), four independently-rewritten training loops that already preserved *different halves* of the ancestor, and one domain (equities) that had to drop `build_vectors` entirely. The genuinely-common code is small: the `build_vectors` 4-step recipe (already trivially re-derivable per sport) and a ~15-line `should_promote(new_cqs, base_cqs, delta)` gate that itself differs (recall/purity floors vs MAE floor vs population-validation). Extracting that saves maybe ~200 LOC while adding a config-driven indirection layer over four domains that keep needing to diverge — the textbook speculative-abstraction trap Bellard warns against. The divergence is **mostly intentional (domain-driven), not rot.**

**What to actually do** (targeted, not a framework): (1) stop copy-pasting *scaffolding* — delete equities' dead `vercel.json` routes and pitch's hoops-residue dashboard numbers; these are the only cross-repo defects that cause real harm (404s, published lies). (2) Fix equities' "mirrors hoops" comment + dead `sigmoid`, and move gridiron's K/DST helpers out of `composite_score.py`. (3) Leave the four `train_mtnn.py`/`build_vectors.py` copies alone — they are correctly four small honest programs, not one leaky abstraction.
