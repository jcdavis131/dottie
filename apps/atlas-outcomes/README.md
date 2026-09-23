# atlas-outcomes: System One place decisions labelled by what happened next

A `jev-decision-schema-1.0.0` pack for place decisions on the eye.jcamd.com
Atlas. Each record is one USGS streamgage at the end of day t: its flow and how
that flow ranks against the gauge's own history, the upstream gauge, the
construct stack it sits in (county, HUC-8, NWS office, state, as the Atlas
strata rail names them), which layers are active there (the streamflow
condition class, a flood-type warning in effect), and recent NWS warning
activity. The three questions are answered by **recorded futures**: the next
day's flow and the NWS warnings actually issued afterwards. No teacher and no
template writes a label.

Provenance tier **`outcome-real`** (factory/datasets.json): the rows may train
System One candidates and are evaluated on a time-split holdout. The pack is
`consent.champion=false`. Nothing here trains, promotes or serves.

## At a glance (pack `atlas-outcomes-1`, harvest end 2026-09-22)

| | |
|---|---|
| Gauges | 60 in 19 states, 25 NWS offices; 25 with a paired upstream gauge |
| Sources | 626,718 gauge-days of daily flow (1995-10 -> 2026-09-22); 37,383 warning polygons (FL 16,467, FA 7,112, FF 13,804), 2015 -> 2026-09-23 |
| Candidate gauge-days | 247,295 (2015-01-01 -> 2026-09-21) |
| Train | 79,491 rows, 2015-01-01 -> 2025-09-20 (226,290 after weights) |
| Holdout | 20,921 rows, 2025-09-22 -> 2026-09-21, natural distribution |

Class balance (raw rate in the pack / natural rate after `sample_weight`):

| Question | Train | Holdout |
|---|---|---|
| `high_next` | 23,368 positives, 29.4% / 10.3% | 999 positives, 4.8% |
| `warn_next` | 2,131 positives, 2.7% / 0.94% | 190 positives, 0.91% |
| `flow_change` (falls >20 / 5-20 / within 5 / rises 5-20 / >20) | 9,639 / 23,807 / 26,177 / 9,284 / 10,584 | 1,531 / 5,976 / 8,364 / 2,716 / 2,334 |

The holdout year was drier than the train decade (4.8% vs 10.3% of days
above p90), which is part of what a time split is for.

Baselines on the holdout (`BASELINE.json`):

| Question | Metric | Climatology | Persistence | Logistic (stdlib) |
|---|---|---|---|---|
| `high_next` | AUC / accuracy / Brier | 0.730 / 0.952 / 0.0498 | 0.874 / 0.977 / 0.0228 | **0.982** / 0.980 / **0.0157** |
| `warn_next` | AUC / accuracy / Brier | 0.697 / 0.991 / 0.0089 | 0.533 / 0.983 / 0.0167 | **0.831** / 0.991 / **0.0089** |
| `flow_change` | accuracy / multi-class Brier / MAE of E[level] | 0.435 / 0.692 / 0.819 | **0.500** / 0.999 / 0.783 | 0.465 / **0.667** / **0.743** |


## Stages

```bash
python3 apps/atlas-outcomes/run.py harvest [--end YYYY-MM-DD] [--refresh]  # network: USGS + IEM -> sources/*.jsonl.gz
python3 apps/atlas-outcomes/run.py features       # every candidate gauge-day -> data/features/ (inspection only)
python3 apps/atlas-outcomes/run.py curate         # offline: sources/ -> data/packs/atlas-outcomes-1/ + PACK_MANIFEST.json + sample/
python3 apps/atlas-outcomes/run.py baseline       # offline: CPU baselines on the holdout -> BASELINE.json
python3 apps/atlas-outcomes/run.py baseline --score preds.jsonl   # a candidate's holdout answers on the same metrics
python3 apps/atlas-outcomes/run.py train-command  # prints the GPU-host jev-v0 command; runs nothing
```

Stdlib only; the network goes through `curl`, throttled per host (1 s gap,
retries on 429/5xx). Raw responses are cached gzipped under `data/raw/`
(gitignored, like all of `data/`), so a rerun of `harvest` costs nothing.
`sources/` holds the committed, compact snapshots (gzip with a fixed mtime), and
`curate` rebuilds the pack from them offline, byte for byte (CI checks this).

| Source | Endpoint | What it gives |
|---|---|---|
| USGS site service | `waterservices.usgs.gov/nwis/site` | name, lat/lon, county, HUC, drainage area, time zone |
| IEM UGC table | `mesonet.agron.iastate.edu/api/1/nws/ugcs.json` | county UGC -> NWS office (WFO) and county name |
| USGS daily values | `waterservices.usgs.gov/nwis/dv` (00060, statistic 00003) | mean daily discharge, 1995-10-01 -> `--end` |
| IEM VTEC polygons | `mesonet.agron.iastate.edu/api/1/vtec/sbw_interval.geojson` | flood (FL), areal flood (FA) and flash flood (FF) warning polygons at issuance, every gauge office, 2015 -> `--end` |

`sources/gauges.jsonl.gz` (one row per gauge), `sources/flows.jsonl.gz` (per
gauge a start date and a dense daily cfs array, null where the service
reported nothing), `sources/warnings.jsonl.gz` (one row per warning polygon,
rings rounded to 1e-4 degrees) and `sources/harvest_stats.json`.

The 60 gauges (`atlas_outcomes/gauges.py`) span 19 states and the NWS offices
that cover them, with upstream -> downstream pairs on the Potomac,
Susquehanna, Delaware, Ohio, Mississippi, Missouri, Iowa/Cedar, Trinity,
Brazos, Guadalupe, Neuse, Cape Fear, Russian, Snoqualmie/Snohomish and Skagit.

## Features (what the state holds)

The decision time of a row is **T = the end of local standard day t**, in
UTC: the moment day t's mean flow exists. Every feature is dated at or before
t, or is a warning issued at or before T (`atlas_outcomes/features.py`):

| Feature | Definition |
|---|---|
| flow today | mean daily cfs on t |
| percentile for the date | rank of today's flow among the gauge's own flows within +-7 days of the same day of year, from days at least 8 days before t (so an event does not rank against itself); at least five years of such days |
| percentile of all prior days | rank among every day on record strictly before t |
| change vs 1/3/7 days ago | percent change |
| upstream | the paired upstream gauge's percentile for the date and 1/3-day change on day t |
| construct stack | County, HUC-8, NWS office, State (smallest first, the Atlas strata rail's kind names) |
| layers | `water`: the USGS WaterWatch class of today's flow (much below / below / normal / above / much above normal, the eye.jcamd.com streamflow condition); `nws-alert`: whether a flood-type warning polygon covering the gauge is in effect at T; `upstream water` where paired |
| warnings | polygons over the gauge issued in the last 30 days; polygons issued by the gauge's office in the last 7 days and 24 hours |

## Questions and labels (recorded futures)

| Question | Type | Label |
|---|---|---|
| `high_next` | noul | mean flow on t+1 above the threshold stated in the question: the gauge's 90th percentile over every day before t, to three significant figures |
| `warn_next` | noul | an NWS FL, FA or FF warning whose polygon contains the gauge is issued in (T, T + 24 h] |
| `flow_change` | score, 5 levels | t -> t+1 change: falls > 20%, falls 5-20%, within 5%, rises 5-20%, rises > 20% |

The state never carries its own answer: `render_state` is a function of the
features alone (tests flip every label and the next-day flow and check the
state does not move).

## Curation

- **Time split.** Holdout = the latest 365 decision days; the day before it is
  an embargo (its label window reaches into the holdout); train = everything
  earlier. No gauge-day is in both, and every train label window closes before
  the holdout starts.
- **Downsampled easy negatives (train only).** A row with both noul labels
  false, flow under the 90th percentile for the date and of all days (not
  "much above normal"), and no
  warning over the gauge in 30 days is kept with probability 0.10 (a seeded
  hash of site and date) and carries `sample_weight` 10 in `provenance.jsonl`,
  so weighted counts give back the natural rates. The holdout keeps the
  natural distribution so its metrics mean what they say.
- **Validate** every record with the frozen `apps/jev-v0/decision_io.validate_record`;
  decontaminate with the dottie-os bench regex; drop duplicates and both sides
  of any conflicting duplicate. Rejects are counted by reason in the manifest.
- **Shuffle** train with the seed: the jev-v0 trainer walks its file in order.

`data/packs/atlas-outcomes-1/`: `train.jsonl`, `holdout.jsonl` (strict jev
records: `schema, id, state, questions, labels` only), `provenance.jsonl` (per
id: site, date, decision time, office, split, easy-negative flag,
sample_weight, provenance tier, label sources, consent) and `MANIFEST.json`
(copied here as `PACK_MANIFEST.json`: counts, class balance raw and weighted,
rejects, split dates, sha256 of every file and source snapshot).
`sample/pack_sample.jsonl` has a few rows per (split, label) combination.

## Baselines

`baseline` fits on train (weighted) and scores the holdout (unweighted):

- **climatology**: the gauge's rate (or level distribution) for the calendar
  month in train, shrunk towards the gauge's overall rate;
- **persistence**: today carried forward (flow above the threshold today; a
  warning in effect over the gauge at T; today's 1-day change level);
- **logistic**: stdlib ridge logistic regression by IRLS on 17 numeric
  features (one-vs-rest for `flow_change`).

Noul: AUC, accuracy at 0.5, Brier. Score: accuracy of the most likely level,
multi-class Brier, mean absolute error of the expected level. The committed
`BASELINE.json` is the bar a System One candidate has to clear on the same
holdout.

## Training (GPU host, not run here)

`python3 apps/atlas-outcomes/run.py train-command` prints the exact commands.
Today it prints:

```bash
# GPU host, from the repo root. Not run here.
# pack atlas-outcomes-1: 79491 train rows x 3 questions = 238473 steps (one pass)
pip install -r apps/jev-v0/requirements-jev-v0.txt   # plus the host CUDA torch wheel
python3 apps/atlas-outcomes/run.py curate   # rebuilds apps/atlas-outcomes/data/packs/atlas-outcomes-1/ offline from sources/
python apps/jev-v0/train_pointer_lora.py --dry-run --fixtures apps/atlas-outcomes/data/packs/atlas-outcomes-1/train.jsonl
python apps/jev-v0/train_pointer_lora.py --go --fixtures apps/atlas-outcomes/data/packs/atlas-outcomes-1/train.jsonl --out apps/jev-v0/runs/atlas-outcomes-1 --steps 238473
python apps/jev-v0/serve_decide.py --checkpoint apps/jev-v0/runs/atlas-outcomes-1 --port 8771
```

`--steps` defaults to one pass over every question of every train record
(the trainer takes one question per step). Evaluate by serving the checkpoint
(`serve_decide.py --checkpoint`), answering `holdout.jsonl`, and scoring the
answers with `run.py baseline --score`. Promotion is the usual human stamp;
nothing here promotes.

The jev-v0 trainer has no per-example weights: it sees the pack's raw rates
(29% / 2.7% positives), not the natural ones. Compare a candidate on the
holdout's AUC and Brier, where the baselines are, not on train loss.

## Judgment calls and limits

- **Revised values.** USGS daily values are fetched as they stand today
  (approved or provisional), not as they were published at t. Revisions are
  usually small, but they are information the decision maker at t did not
  have exactly.
- **Standard time.** T uses the gauge's local standard time all year; daily
  values follow local time, so during daylight time T is an hour late for
  the warning windows.
- **Polygons, not counties.** "Covers the gauge" is point-in-polygon on the
  warning's polygon at issuance. Extensions and polygon updates (CON/EXT) are
  not harvested, so `warnings in effect at T` uses the issuance expiry. Only
  the offices that contain a gauge are harvested; a neighbouring office's
  polygon over a border gauge would be missed.
- **Connecticut** replaced its counties with planning regions in 2022; the NWS
  UGC still uses the legacy county, so `01184000` maps to Hartford (`CTC003`).
- **Holdout at the natural rate.** Positives are rare in the holdout; read
  AUC and Brier together, not accuracy alone.

## Tests

```bash
python3 -m unittest discover -s apps/atlas-outcomes/tests -v
```

Offline, on a synthetic two-gauge fixture built in the test (never written to
`sources/`): features ignore every flow and warning after t; p90 and
percentiles are strictly before t; the warning label window (T, T + 24 h] and
the polygon test; next-day labels match the stated threshold; the time split
has an embargo and no straddle; downsampling touches train only and sets the
weights; every record validates with jev-v0 and has exactly the five keys;
parsers and the baseline maths.
