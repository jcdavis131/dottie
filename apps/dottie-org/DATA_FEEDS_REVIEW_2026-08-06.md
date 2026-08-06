# Data-feeds review — ALL feeds, every repo (2026-08-06)

Three parallel read-only reviewers swept every data feed on this box: (1)
equities/realty/guard, (2) pitch/hoops/gridiron/tennis/golf, (3) dottie
factory corpus + telemetry + bluehenre twin. Findings verified with file:line
citations; fixes were applied same-day in unclaimed lanes and are marked ✅.

## Feed health at a glance

| feed | source | freshness | coverage | silent-failure risk |
|---|---|---|---|---|
| equities market_history | yfinance 10y daily | Jul 30 (7d stale) | 504 tickers, spot-parse clean | was HIGH → ✅ fixes below |
| equities SEC (4 caches) | EDGAR (compliant UA) | Jul 30–Aug 4 | 497–500 of 503 | medium: 3 CIKs missing silently → ✅ now counted |
| pitch StatsBomb | github open-data | Jul 10 | 2,430 rows / 11 ctx — exact | low (0 failed matches); all-ones mask flagged |
| hoops NBA/BBRef | nba_api + scrape | Jul 5–8, vectors Jul 30 | 12,966 players — exact | medium: aux feeds join `or []` |
| gridiron nflverse | release CSVs, **weekly auto-refresh** | Aug 4 | 49,860×85, 145 files | **HIGH: labels zero-fill** (Scout's lane, flagged) |
| realty BIS | bulk CSV, keyless | Aug 4 | 2,275×18, 94.3% observed | LOW — cleanest repo; fails closed |
| tennis | planned only | first commit | empty by design | n/a — the *design* is the best in the fleet |
| golf | none | stub | zero | n/a |
| factory OAPEN books | REST, license-gated | Jul 24 | 48 books (CC-BY/-SA) | **dead feed**: no consumer, manifest says 25 |
| factory telemetry | jsonl + live status | live (gist Aug 6) | 5,242 rows, 99.3% schema-less | was HIGH → ✅ staleness guard fixed |
| bluehenre twin | gist chain, 10-min cron | **verified live end-to-end** | — | low: handlers honestly return offline |

## Fixed same-day ✅

- **equities `tune_fwd_dd_head.py --real` always used synthetic data** — the
  candidate list omitted the only bundle with labels; and `--real` with no
  labels now exits 2 instead of substituting fabricated numbers (`919b188`).
- **equities loud-absence trio** — label-less bundle warns at load; corrupt
  summaries counted and named; universe fallback announces itself (`919b188`).
- **dottie telemetry staleness guard dead from birth** —
  `datetime.now(datetime.timezone.utc)` AttributeError swallowed since the
  line was written; stale status served as fresh forever. Fixed + 3 tests +
  mutation-checked (`7af5e05`).
- **pitch game page had no StatsBomb attribution** — required by the data
  license; footer fixed (`a206185` in vector-pitch).

## Open findings by owner

**Scout's lanes (flagged, not touched):**
1. gridiron `nfl_data.py:200-207` `num()` zero-fills missing keys INCLUDING
   the Y labels (`build_features.py:213-219`) — an upstream column rename
   silently zeroes all targets; NaN assert blind to it. Worst finding of the
   review; same class that ate equities' labels.
2. gridiron fabricated Vegas/weather defaults (44.0 total / 0 spread / 68°F)
   with no per-row mask (`build_features.py:176-189`).
3. gridiron `fetch_bytes` caches any non-404 bytes — a 200-status error page
   becomes a cached "CSV" (`nfl_data.py:77-95`).
4. hoops aux feeds: corrupt cache → `None` → `or []` → season silently
   stripped to masked NaN (`build_vectors.py:287-290, 760-769`); triple
   `return {}` loaders for hustle/form (`:489-496, :519-529`).

**Operator decisions (parked in HANDOFF):**
5. `telemetry.py:614-761` canonical-lock hardcodes 500,034 tokens + gdrive id
   + manifest sha and overwrites `last_expansion`/`updated` — fabricated
   freshness contradicting the publisher's "never invented" contract. Whether
   it is scaffolding to delete or a contract to honor is the operator's call.
6. ast_pairs untracked mining (16.7% of corpus is model-written code) — the
   fork recorded 2026-08-05 stands; growth resumes when the research loop
   restarts (frozen since Aug 2 03:54).
7. OAPEN books: 74 MB license-gated corpus with NO consumer and a manifest
   describing 25 of its 48 books; partial pulls exit 0
   (`pull_oapen_books.py:187-190`). Wire it in or archive it.
8. equities `train_matrix_real.npz` has 33 dead columns (ownership,
   disclosure_text, sector_context, most of management_neo) while README
   advertises those towers — the bundle predates the Aug-4 comp/officer
   caches; a rebuild would light them up. Also the shared
   `feature_manifest.json` now describes v5 (labels) while sitting next to
   real.npz (no labels) — per-bundle manifests would end the ambiguity.
9. vector-guard contract drift: `produced_by` names a builder that writes a
   different bundle; "sha256:" value is md5-length. Guard's daily validate is
   otherwise the only thing that caught the dead columns — keep feeding it.
10. telemetry jsonl mixed schema: `state_store.export_telemetry` appends
    schema-less rows (99.3% of file) that break aggregation and trip the
    canonical fallback; rotation truncates to 1,000 lines at 5 MB.

**Design worth copying fleet-wide:** vector-tennis's planned acquisition
(SHA-256 rights ledger, fails closed, pinned sources, `.part` + atomic
rename, frozen temporal splits) and vector-realty's fail-closed builders are
the standard the rest of the feeds should converge on. The single cheapest
fleet-wide guard: **an anti-vacuity label check at every bundle build** —
labels non-degenerate (not all-zero, not all-NaN, variance floor) — would
have caught the equities loss, would catch gridiron rename-zeroing, and costs
one assert per builder.
