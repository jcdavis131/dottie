# Vector Gridiron

**Live: https://vector-gridiron.vercel.app**

Your fantasy football season on rails. The Vector Hoops / Vector Pitch player-
embedding idea, retargeted to the NFL and driven by a **multi-task neural net
(MTNN)** trained on a holistic player + team + matchup + conditions feature set.
Sync your ESPN or Sleeper league and get model-backed **draft**, **start/sit**,
**waiver**, and **trade** calls — plus a **next-game** prediction for every
player under its real weather/Vegas/matchup context. Static, zero-tracking, free.

4,183 player-seasons (2016–**2025**); an **MTNN v2** multi-tower net on a
masked multi-family feature matrix (form, usage, opportunity/EP, role/depth,
NGS, PFR advanced, matchup, Vegas/weather, defense, pedigree, …). Projects both
the upcoming **season** (draft board) and the upcoming **week** (in-season).
Honest temporal split, held-out 2025 — must beat last-4 and season-to-date
baselines. Weekly fantasy is high-variance; we ship floor/ceiling, not fantasy.

## The layers

### 1. Data — `pipeline/nfl_data.py` + `build_features.py`
`nfl_data.py` is a cached, resumable loader for free nflverse (+ ffopportunity) feeds:
`stats_player_week`, `snap_counts`, `players.csv`, Lee Sharpe's `games.csv`
(home/away, rest, roof/weather, **Vegas implied points**), **depth charts**,
**Next Gen Stats** (separation, RYOE, CPOE, …), **PFR advanced** (pressure,
yards-before-contact, drops), **ffopportunity expected fantasy points**
(CC-BY-SA — cite ffverse), draft/combine pedigree, and injuries through **2024**
(the nflverse injury source died after 2024 — 2025+ availability uses roster
status / depth only; the `availability` family is masked). See
`docs/DATA_SOURCES_DEEP.md`.

`build_features.py` joins them into a **leakage-safe masked family matrix**
(`pipeline/data/train_matrix.npz` + `feature_manifest.json`).
`build_vectors.py` still emits the transparent σ-profile space (`vectors.json`).

```
python pipeline/build_vectors.py     # profiles / archetypes / grades (+2025)
python pipeline/build_features.py    # multi-family matrix + masks
python pipeline/feature_inspect.py   # coverage / corr report
```

### 2. The MTNN — `pipeline/train_mtnn.py` (v2)
**Multi-tower residual encoders** (one per feature family) with missingness
masks → **gated fusion** + season embedding → L2-normalized player embedding →
multi-task heads (PPR fantasy points + component yards/rec/TDs + usage
reconstruction + position + pedigree aux). Trained train ≤2023 / val 2024 /
**test 2025**. Promotion gates in `pipeline/verify_accuracy.py`. Architecture:
`docs/MTNN_ARCHITECTURE.md`. One model, three artifacts:
- `nextgame.json` — upcoming week under **real** matchup / weather / Vegas
- `projections.json` — upcoming **season** under neutral conditions (+ rookies)
- `embedding.json` — learned map coords + comps

**Rookies** (no prior NFL stats) keep a separate **draft-capital model**
(round/pick + position + age). `train_models.py` is a thin wrapper that calls
`train_mtnn.main()`.

```
python pipeline/train_mtnn.py        # builds features if needed, trains, exports
python pipeline/verify_accuracy.py   # promotion gates
```

### 2b. Consensus ADP — `pipeline/build_adp.py`
Pulls average draft position from **a variety of free sources** (Fantasy
Football Calculator PPR + Half-PPR, MyFantasyLeague), joins them on the same
name+position key, and averages to a consensus ADP + spread + per-source
breakdown → `assets/adp.json`. The board flags **draft-day value** = the model's
positional rank vs the market's positional ADP rank (VALUE = model likes him
more than the room at his position; REACH = the opposite).

```
python pipeline/build_adp.py         # -> assets/adp.json (a few seconds)
```

### 2c. Availability — byes / injuries / team changes
`build_features` uses each player's **current team** (`latest_team` from
players.csv) so offseason movers get the right opponent/Vegas context (not last
year's team), and flags them `moved`. **Bye weeks** are derived from the season
schedule in `games.csv`; **injury status** (Out/Doubtful/Questionable) comes from
the weekly `injuries` feed (in-season) and roster `status` (RES/CUT/IR). Every
projection carries `bye`, `avail`, and `moved`; Start/Sit excludes players on
bye or ruled out and lists them separately.

### 2d. Lookback league — `pipeline/build_lookback.py`
Seeds a full 12-team **best-ball PPR** fantasy season from real NFL results for
every prior season (2016–2025) → `assets/lookback_seasons.json` (the seeded DB).
Per season: a VOR-ordered position-capped snake **mock draft** (order = each
player's prior-season value-over-replacement), best-ball weekly scores → schedule
→ standings → a 6-team playoff → a champion. Each team's draft is **graded A+…F**
on the actual value it captured, with best steal / biggest bust. Then **blog-style
narratives**: a draft recap, a one-liner for every week, and a season recap
(champion, MVP, draft-grade-vs-finish). The grading + narrative functions are
**source-agnostic** — a real ESPN/Sleeper draft history grades through the same
code, which is how the realtime version works.

```
python pipeline/build_lookback.py    # -> assets/lookback_seasons.json
```

### 3. Cockpit UI — `index.html` + `assets/{gridiron.css,app.js}`
Neobrutalist dark field theme, position-coded data. Tabs: **My Team**, **Draft
Prep**, **Next Game**, **Start/Sit**, **Waivers**, **Trades**, **Lookback**, and
the **Vector Map**. When a league is connected it's **personalized**: a banner
with the league name, your team + avatar and power-ranking; **your players
starred and highlighted** across every table and on the map; a **league power
rankings** board; and each player's bye / injury / team-change badges inline.
Profiles show σ-profile, projected line, this-week prediction, comps, career arc.
A **Try demo** button and first-run **NUX** make it lovable before you connect.

### 4. League sync
- **Sleeper** — public read API, called directly from the browser. Paste your
  League ID; scoring + lineup slots auto-detected.
- **ESPN** — `api/espn.js`, a thin same-origin serverless proxy (ESPN sets no
  CORS headers and private leagues need `espn_s2` + `SWID` cookies, which the
  browser won't attach cross-site). Cookies are passed per-request and never
  stored. Works for public leagues with just League ID + season year.

Scoring format is **auto-detected** from league settings (falls back to PPR).
Credentials live only in your browser's `localStorage`.

## Methods (honesty)

Held-out **2025** next-game PPR (temporal split: train ≤2023, val 2024, test 2025).
**Promote gate = Composite Quality Score (CQS)** — a 0–100 blend of MAE (35%),
RMSE (20%), R² (15%), |bias| (10%), per-pos balance (10%), and conformal
coverage vs 0.80 (10%). MAE remains a soft floor: no promote if MAE worsens by
more than **0.05** vs the baseline. Baseline CQS **63.16** · MAE **4.296**
(val-fit bias shrink α=0.5 + per-pos affine mix=1.0 on RZ MTNN).

Diagnostic battery on the same held-out set (also in `mtnn_report.json`):
RMSE **6.07** · R² **0.422** · bias **−0.31** · per-pos MAE in report.

| | MAE | CQS | notes |
|--|-----|-----|-------|
| **MTNN + RZ + bias + affine** | **4.296** | **63.16** | val-fit calib chain |
| MTNN + RZ + bias shrink | 4.294 | 62.31 | α=0.5 |
| MTNN v2 + RZ (raw) | 4.258 | 61.25 | pre-calib reference |
| MTNN v2 (pre-RZ) | 4.268 | — | prior MAE promote |
| v1 (flat trunk) | 4.313 | — | reference |
| last-4 mean | 4.616 | — | must beat |
| season-to-date | 4.523 | — | must beat |

**K / DST:** not in the skill MTNN (QB/RB/WR/TE only). Kickers and team defenses
use season-rate models in `pipeline/build_kdst.py` → `assets/kdst.json`, baked
into `nextgame.json` / `projections.json` and merged in the UI so all six
lineup slots (QB/RB/WR/TE/K/DST) have predictions. Walk-forward season MAE is
reported under `kdst.holdout`. The MTNN `defense` family is **opponent DvP**,
not fantasy DST units.

**Floor / ceiling** on the board are **split-conformal** bands: per-position
quantile of absolute held-out residual at level 80% (coverage ≈ 0.80 on 2025
test). Wider than ±σ for QBs (~10.4 PPR), tighter for TEs (~5.3). Still not a
Bayesian CI — treat as a calibrated spread hint. Residual σ remains in
`mtnn_report.json` for diagnostics. Family ablation
(`python pipeline/family_ablation.py`) shows **usage** and **form** dominate
held-out MAE; NGS/defense/role are near-flat on 2025.

**Lookback manager grades** (when a league is connected): draft VOR letter
grades, **start/sit efficiency** (actual starter pts ÷ optimal from that week's
roster, platform scoring, latest 1–2 seasons), and **clutch** (same metric for
weeks 15–18). Standings modes: Drafting · Start/Sit · Clutch · Titles · Scoring ·
Playoffs · Career draft.

**Known gaps (do not expect miracles):**
- **Injuries 2025+** — nflverse injury feed dead after 2024; `availability`
  family is masked for those seasons; UI `avail` falls back to roster/depth.
- **NGS** — 2024 placeholders empty on nflverse; 2025 unpublished at train
  time → family coverage ~0.51 (masked when missing).
- **R²** dropped slightly vs v1 (0.42 → 0.39) while MAE improved — we promote
  on **CQS** (which includes R²) with an MAE soft floor, not MAE alone.
- **Feature expand plateau** — EWMA / soft-weight / prune trials did not beat
  raw MAE 4.258 on 2025; bias shrink raised CQS to 62.31. Next expand waits on
  new season data.

See `docs/DATA_SOURCES_DEEP.md`, `docs/MTNN_ARCHITECTURE.md`, and
`pipeline/data/mtnn_report.json`.

## Verify
```
python pipeline/verify_accuracy.py   # MTNN v2 promotion gates
node pipeline/verify_logic.mjs       # artifact sanity + UI logic
```
The UI is additionally exercised headlessly with jsdom (NUX, connect flow,
Lookback, Draft/Next-Game tabs) — see the harnesses used during development.

## Attribution
Data: [nflverse](https://nflverse.com) (stats, snaps, depth charts, NGS, PFR
advanced, injuries through 2024, draft/combine), Lee Sharpe / nfldata
`games.csv`, [ffopportunity](https://github.com/ffverse/ffopportunity) expected
fantasy points (CC-BY-SA 4.0), Fantasy Football Calculator + MyFantasyLeague
(ADP). No tracking.

## In-season use — automatic
`pipeline/refresh.py` invalidates the volatile feeds, rebuilds every artifact,
and redeploys. A Windows scheduled task (`VectorGridironWeeklyRefresh`, Tuesdays
10:00) runs it weekly — register/remove with:
```
schtasks /Create /TN VectorGridironWeeklyRefresh /SC WEEKLY /D TUE /ST 10:00 /F ^
  /TR C:\Users\jcdav\vector-gridiron\pipeline\refresh.bat
schtasks /Delete /TN VectorGridironWeeklyRefresh /F     # to stop it
```
Season rollover is automatic: `build_vectors` ranges to the current year and
`train_models` projects `(latest published season + 1)`, so the whole thing
advances the moment nflverse posts `stats_player_week_<new year>.csv` — next-game
predictions roll to the next scheduled week from `games.csv` with no code change.

## Deploy (Vercel — matches the siblings)
```
vercel deploy --prod --yes   # api/espn.js becomes a serverless function
```
Deployed at https://vector-gridiron.vercel.app (project `vector-gridiron`).
No env vars required. `assets/*.json` are committed; the `pipeline/cache/` raw
CSVs are gitignored and regenerate on demand.

## Connecting your league
- **Sleeper**: League ID is the long number in your league URL on sleeper.com.
- **ESPN public**: League ID (Settings → the `leagueId=` in the URL) + year.
- **ESPN private**: also grab `espn_s2` and `SWID` from your browser cookies
  (DevTools → Application → Cookies → fantasy.espn.com) — read-only, per-request.
