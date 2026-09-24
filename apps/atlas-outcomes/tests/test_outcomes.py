"""Offline tests for atlas-outcomes: no network, a small synthetic two-gauge corpus.

    python3 -m unittest discover -s apps/atlas-outcomes/tests -v

The fixture's flows and warnings are made up here to exercise the code; they
never reach sources/ or a pack.
"""

from __future__ import annotations

import copy
import json
import math
import random
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from atlas_outcomes import SCHEMA_ID
from atlas_outcomes.baseline import auc, fit_logistic, noul_metrics, predict
from atlas_outcomes.curate import (
    assemble,
    assign_split,
    is_easy_negative,
    load_validator,
    split_dates,
)
from atlas_outcomes.features import (
    DAY_S,
    Corpus,
    build_rows,
    change_bucket,
    decision_ts,
    doy_index,
    flow_class,
    site_history,
)
from atlas_outcomes.geo import polygons_contain
from atlas_outcomes.harvest import dense, normalize_warning, parse_dv
from atlas_outcomes.records import render_state, to_record

START = date(2008, 1, 1)
END = date(2015, 6, 30)
ROW_START = date(2015, 1, 1)


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def synthetic_flow(seed: int, n: int) -> list[float | None]:
    rng = random.Random(seed)
    out: list[float | None] = []
    for i in range(n):
        season = 1.0 + 0.6 * math.sin(2 * math.pi * i / 365.25)
        out.append(round(1000 * season * math.exp(rng.gauss(0, 0.35)), 1))
    out[100] = None  # a gap the service did not report
    return out


def square(lon: float, lat: float, r: float = 0.05) -> list:
    return [[[[lon - r, lat - r], [lon + r, lat - r], [lon + r, lat + r], [lon - r, lat + r], [lon - r, lat - r]]]]


GAUGE_A = {"site": "00000001", "name": "TEST RIVER AT UPPER", "lat": 39.0, "lon": -77.0, "state": "MD",
           "county_ugc": "MDC001", "county": "Allegany", "wfo": "LWX", "huc8": "02070002", "drainage_sq_mi": 500.0,
           "tz": "EST", "upstream": None}
GAUGE_B = {**GAUGE_A, "site": "00000002", "name": "TEST RIVER AT LOWER", "lat": 38.5, "lon": -76.5, "upstream": "00000001"}


def fixture_corpus() -> Corpus:
    n = (END - START).days + 1
    flows = [{"site": g["site"], "start": START.isoformat(), "cfs": synthetic_flow(k, n)} for k, g in enumerate((GAUGE_A, GAUGE_B))]
    t = decision_ts(date(2015, 3, 10), "EST")
    warnings = [
        # over gauge B, issued one hour after the end of 2015-03-10, in effect 12 h
        {"wfo": "LWX", "phenomena": "FL", "significance": "W", "eventid": 1, "year": 2015, "issue": _iso(t + 3600),
         "expire": _iso(t + 13 * 3600), "product_id": "p1", "ugcs": ["MDC001"], "polygons": square(-76.5, 38.5)},
        # same office, far from both gauges: office activity, never coverage
        {"wfo": "LWX", "phenomena": "FA", "significance": "W", "eventid": 2, "year": 2015, "issue": _iso(t - 2 * DAY_S),
         "expire": _iso(t - DAY_S), "product_id": "p2", "ugcs": ["VAC001"], "polygons": square(-80.0, 37.0)},
    ]
    return Corpus([GAUGE_A, GAUGE_B], flows, warnings, (END + timedelta(days=2)).isoformat())


class TestNoLeak(unittest.TestCase):
    def test_history_ignores_the_future(self):
        n = 9 * 365
        cfs = synthetic_flow(3, n)
        h = site_history(START, cfs)
        k = 8 * 365
        future = cfs[: k + 1] + [x * 50 if x is not None else None for x in cfs[k + 1 :]]
        h2 = site_history(START, future)
        self.assertEqual(h.pct_date[: k + 1], h2.pct_date[: k + 1])
        self.assertEqual(h.pct_all[: k + 1], h2.pct_all[: k + 1])
        self.assertEqual(h.p90[: k + 1], h2.p90[: k + 1])
        self.assertIsNotNone(h.pct_date[k])

    def test_p90_is_strictly_before_t(self):
        n = 6 * 365
        cfs = [100.0] * n
        k = n - 10
        cfs[k] = 1e6  # a record flood on day k cannot raise its own threshold
        h = site_history(START, cfs)
        self.assertEqual(h.p90[k], 100.0)
        self.assertEqual(h.pct_all[k], 100.0)

    def test_rows_ignore_future_flows_and_warnings(self):
        corpus = fixture_corpus()
        rows = {(r["site"], r["date"]): r for r in build_rows(corpus, ROW_START)}
        cut = date(2015, 3, 5)
        later = copy.deepcopy(corpus)
        for f in later.flows:
            i0 = (cut - START).days + 1
            f["cfs"] = f["cfs"][:i0] + [None if x is None else x * 7 for x in f["cfs"][i0:]]
        t_cut = decision_ts(cut, "EST")
        later.warnings.append({"wfo": "LWX", "phenomena": "FF", "significance": "W", "eventid": 9, "year": 2015,
                               "issue": _iso(t_cut + 60), "expire": _iso(t_cut + DAY_S), "product_id": "p9",
                               "ugcs": [], "polygons": square(-77.0, 39.0)})
        rows2 = {(r["site"], r["date"]): r for r in build_rows(later, ROW_START)}
        checked = 0
        for key, r in rows.items():
            if date.fromisoformat(key[1]) <= cut:
                self.assertEqual(r["features"], rows2[key]["features"], key)
                checked += 1
        self.assertGreater(checked, 50)
        # ...while the label of the cut day itself does see the future
        self.assertTrue(rows2[("00000001", cut.isoformat())]["labels"]["warn_next"])
        self.assertFalse(rows[("00000001", cut.isoformat())]["labels"]["warn_next"])

    def test_state_never_carries_the_answer(self):
        corpus = fixture_corpus()
        rows = build_rows(corpus, ROW_START)
        for r in rows[:40]:
            flipped = copy.deepcopy(r)
            flipped["labels"] = {"high_next": not r["labels"]["high_next"], "warn_next": not r["labels"]["warn_next"],
                                 "change_bucket": (r["labels"]["change_bucket"] + 2) % 5}
            flipped["next_flow"] = r["next_flow"] * 3 + 1
            self.assertEqual(render_state(GAUGE_A, r), render_state(GAUGE_A, flipped))
            text = json.dumps(render_state(GAUGE_A, r))
            for word in ("high_next", "warn_next", "next_flow", "tomorrow"):
                self.assertNotIn(word, text)


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.rows = {(r["site"], r["date"]): r for r in build_rows(fixture_corpus(), ROW_START)}

    def test_warning_label_window(self):
        b = "00000002"
        self.assertTrue(self.rows[(b, "2015-03-10")]["labels"]["warn_next"])  # issued T + 1 h
        self.assertFalse(self.rows[(b, "2015-03-09")]["labels"]["warn_next"])  # T(03-09) + 24 h = T(03-10) < issue
        self.assertFalse(self.rows[(b, "2015-03-11")]["labels"]["warn_next"])
        self.assertFalse(self.rows[("00000001", "2015-03-10")]["labels"]["warn_next"])  # polygon is not over gauge A
        f = self.rows[(b, "2015-03-11")]["features"]
        self.assertEqual(f["warn_gauge_30d"], 1)
        self.assertFalse(f["warn_active"])  # expired 12 h after issue, before T(03-11)
        self.assertEqual(self.rows[(b, "2015-03-10")]["features"]["warn_wfo_7d"], 1)  # the far FA warning only
        self.assertEqual(self.rows[(b, "2015-03-11")]["features"]["warn_wfo_7d"], 2)

    def test_high_flow_label_is_next_day_over_stated_threshold(self):
        corpus = fixture_corpus()
        rows = self.rows
        for (site, d), r in rows.items():
            f = next(x for x in corpus.flows if x["site"] == site)
            nxt = f["cfs"][(date.fromisoformat(d) - START).days + 1]
            self.assertEqual(r["next_flow"], nxt)
            self.assertEqual(r["labels"]["high_next"], nxt > r["features"]["p90"])
            self.assertEqual(r["labels"]["change_bucket"], change_bucket(r["features"]["flow"], nxt))
        self.assertTrue(any(r["labels"]["high_next"] for r in rows.values()))

    def test_change_buckets_and_classes(self):
        self.assertEqual([change_bucket(100, x) for x in (70, 80, 90, 95, 100, 105, 110, 120, 130)], [0, 1, 1, 2, 2, 2, 3, 3, 4])
        self.assertEqual(change_bucket(0, 0), 2)
        self.assertEqual(change_bucket(0, 5), 4)
        self.assertEqual([flow_class(p) for p in (5, 20, 50, 80, 95, None)],
                         ["much below normal", "below normal", "normal", "above normal", "much above normal", "not rated"])
        self.assertEqual(doy_index(date(2016, 3, 1)), doy_index(date(2015, 3, 1)))

    def test_upstream_features_come_from_the_upstream_gauge(self):
        r = self.rows[("00000002", "2015-02-01")]
        self.assertEqual(r["features"]["up_site"], "00000001")
        self.assertEqual(r["features"]["up_pct_date"], self.rows[("00000001", "2015-02-01")]["features"]["pct_date"])
        self.assertNotIn("up_site", self.rows[("00000001", "2015-02-01")]["features"])


class TestSplitAndRecords(unittest.TestCase):
    def test_time_split_has_no_straddle(self):
        first_hold, last_train = split_dates(date(2026, 9, 21))
        self.assertEqual(first_hold, date(2025, 9, 22))
        self.assertEqual(last_train, date(2025, 9, 20))
        self.assertIsNone(assign_split("2025-09-21", first_hold, last_train))  # embargo
        self.assertEqual(assign_split("2025-09-22", first_hold, last_train), "holdout")
        self.assertEqual(assign_split("2025-09-20", first_hold, last_train), "train")

    def test_assemble_validates_splits_and_downsamples_train_only(self):
        kept, info = assemble(fixture_corpus(), easy_keep=0.25, row_start=ROW_START, holdout_days=60)
        io = load_validator()
        by_day: dict[str, set[str]] = {}
        for v in kept:
            self.assertEqual(io.validate_record(v["record"]), v["record"])
            self.assertEqual(set(v["record"]), {"schema", "id", "state", "questions", "labels"})
            self.assertEqual(v["record"]["schema"], SCHEMA_ID)
            by_day.setdefault(v["meta"]["date"], set()).add(v["meta"]["split"])
            if v["meta"]["split"] == "holdout" or not v["meta"]["easy_negative"]:
                self.assertEqual(v["meta"]["sample_weight"], 1.0)
            else:
                self.assertEqual(v["meta"]["sample_weight"], 4.0)
            self.assertEqual(v["meta"]["provenance"], "outcome-real")
        self.assertTrue(all(len(s) == 1 for s in by_day.values()))
        last_train = max(d for d, s in by_day.items() if "train" in s)
        first_hold = min(d for d, s in by_day.items() if "holdout" in s)
        self.assertGreaterEqual((date.fromisoformat(first_hold) - date.fromisoformat(last_train)).days, 2)
        self.assertIn("easy negative downsampled (train)", info["rejected"])
        hold_easy = sum(1 for v in kept if v["meta"]["split"] == "holdout" and v["meta"]["easy_negative"])
        self.assertEqual(hold_easy, info["easy_negatives"].get("holdout", 0))

    def test_easy_negative_rule(self):
        row = {"features": {"pct_date": 40.0, "pct_all": 50.0, "warn_active": False, "warn_gauge_30d": 0},
               "labels": {"high_next": False, "warn_next": False}}
        self.assertTrue(is_easy_negative(row))
        for patch in ({"labels": {"high_next": True, "warn_next": False}},
                      {"features": {**row["features"], "pct_date": 95.0}},
                      {"features": {**row["features"], "warn_gauge_30d": 1}}):
            self.assertFalse(is_easy_negative({**row, **patch}))

    def test_record_shape(self):
        r = build_rows(fixture_corpus(), ROW_START)[0]
        rec = load_validator().validate_record(to_record(GAUGE_A, r))
        self.assertEqual(rec["questions"]["high_next"]["type"], "noul")
        self.assertEqual(rec["questions"]["flow_change"]["type"], "score")
        self.assertEqual(len(rec["questions"]["flow_change"]["criteria"]), 5)
        self.assertIn(f"{r['features']['p90']:,.0f} cfs", rec["questions"]["high_next"]["instructions"])
        self.assertEqual(rec["state"]["constructs"][0]["kind"], "County")


class TestParsersAndBaseline(unittest.TestCase):
    def test_parse_dv_and_dense(self):
        payload = {"value": {"timeSeries": [{"variable": {"noDataValue": -999999.0}, "values": [{"value": [
            {"value": "10", "dateTime": "2020-01-01T00:00:00.000"},
            {"value": "-999999", "dateTime": "2020-01-02T00:00:00.000"},
            {"value": "12.5", "dateTime": "2020-01-04T00:00:00.000"}]}]}]}}
        vals = parse_dv(payload)
        self.assertEqual(vals, {"2020-01-01": 10.0, "2020-01-02": None, "2020-01-04": 12.5})
        self.assertEqual(dense(vals), ("2020-01-01", [10, None, None, 12.5]))

    def test_normalize_warning_keeps_flood_warnings_only(self):
        feat = {"properties": {"phenomena": "FL", "significance": "W", "eventid": 3, "year": 2024, "wfo": "LWX",
                               "utc_issue": "2024-01-09T15:20:00Z", "utc_expire": "2024-01-10T03:50:00Z",
                               "ugclist": "MDC021, VAC107", "product_id": "x"},
                "geometry": {"type": "Polygon", "coordinates": [[[-77.123456, 39.1], [-77.0, 39.1], [-77.0, 39.2], [-77.123456, 39.1]]]}}
        w = normalize_warning(feat)
        self.assertEqual(w["ugcs"], ["MDC021", "VAC107"])
        self.assertEqual(w["polygons"][0][0][0], [-77.1235, 39.1])
        self.assertIsNone(normalize_warning({**feat, "properties": {**feat["properties"], "significance": "A"}}))
        self.assertIsNone(normalize_warning({**feat, "properties": {**feat["properties"], "phenomena": "SV"}}))

    def test_point_in_polygon_with_hole(self):
        outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
        polys = [[outer, hole]]
        self.assertTrue(polygons_contain(polys, 2, 2))
        self.assertFalse(polygons_contain(polys, 5, 5))
        self.assertFalse(polygons_contain(polys, 11, 5))

    def test_auc_and_logistic(self):
        self.assertEqual(auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75)
        self.assertEqual(auc([0.5, 0.5], [0, 1]), 0.5)
        rng = random.Random(0)
        xs = [rng.gauss(0, 1) for _ in range(400)]
        ys = [1.0 if x + rng.gauss(0, 0.5) > 0 else 0.0 for x in xs]
        cols = [[1.0] * 400, xs]
        beta = fit_logistic(cols, ys, [1.0] * 400)
        self.assertGreater(beta[1], 1.0)
        m = noul_metrics(predict(beta, cols), [int(y) for y in ys])
        self.assertGreater(m["auc"], 0.9)


if __name__ == "__main__":
    unittest.main()
