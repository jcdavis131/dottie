"""Stage 2: features per (gauge, day t), from what was known at the end of day t.

The decision time of a row is T = the end of local (standard) day t, in UTC:
the moment day t's mean flow exists. Everything in a row's features comes
from data dated at or before t, or from warnings issued at or before T:

  flow           the day's mean flow (cfs)
  pct_date       percentile of that flow among the gauge's own flows on the
                 same day of year (+- 7 days) in prior years. Only days at
                 least DOY_LAG_DAYS before t enter, so the current event does
                 not rank against itself. Day-of-year aware, like USGS
                 WaterWatch and the eye.jcamd.com streamflow condition.
  pct_all, p90   percentile of the flow among, and the 90th percentile of,
                 every prior day on record (strictly before t)
  chg1/3/7       percent change against t-1, t-3, t-7
  up_*           the upstream gauge's pct_date, chg1 and chg3 on day t, where a pair exists
  warn_active    an NWS flood-type warning polygon covering the gauge in effect at T
  warn_gauge_30d warnings covering the gauge issued in (T - 30 d, T]
  warn_wfo_7d/1d warnings (any polygon) issued by the gauge's NWS office in (T - 7 d, T] / (T - 24 h, T]
  season, month  calendar

Labels are recorded futures, never inputs:

  high_next      mean flow on t+1 > the threshold shown in the question (p90, 3 significant figures)
  warn_next      a flood-type warning polygon covering the gauge is issued in (T, T + 24 h]
  change_bucket  the change from t to t+1 in five buckets (CHANGE_LEVELS)

`python3 run.py features` writes every candidate row (before curation) to
data/features/features.jsonl.gz with a stats file, for inspection.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .common import DATA, SOURCES, read_jsonl, write_jsonl
from .gauges import TZ_HOURS
from .geo import polygons_bbox, polygons_contain

ROW_START = date(2015, 1, 1)
DOY_WINDOW = 7
DOY_LAG_DAYS = 8
# At least five prior years of same-season days before a row is emitted.
MIN_DOY_HISTORY = 5 * (2 * DOY_WINDOW + 1)
MIN_ALL_HISTORY = 5 * 365
DAY_S = 86400
ACTIVE_LOOKBACK_S = 20 * DAY_S
CHANGE_EDGES = (-20.0, -5.0, 5.0, 20.0)
CHANGE_LEVELS = [
    "falls more than 20%",
    "falls 5% to 20%",
    "within 5% either way",
    "rises 5% to 20%",
    "rises more than 20%",
]
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"}


def doy_index(d: date) -> int:
    """0..364; Feb 29 shares Feb 28's bin so every calendar day keeps its bin across years."""
    y = d.timetuple().tm_yday
    leap = d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)
    if leap and y > 59:
        y -= 1
    return y - 1


def sig3(x: float) -> float:
    """Round to three significant figures (the threshold as the question states it)."""
    if x <= 0:
        return 0.0
    digits = 2 - math.floor(math.log10(x))
    return float(round(x, digits))


def pct_change(now: float | None, then: float | None) -> float | None:
    if now is None or then is None:
        return None
    if then == 0:
        return 0.0 if now == 0 else None
    return round((now / then - 1.0) * 100.0, 1)


def change_bucket(today: float, tomorrow: float) -> int:
    if today == 0:
        return 2 if tomorrow == 0 else 4
    return bucket_of_change((tomorrow / today - 1.0) * 100.0)


def bucket_of_change(c: float) -> int:
    """Percent change -> level index: < -20, [-20, -5), [-5, 5], (5, 20], > 20."""
    c = round(c, 6)  # 95 / 100 - 1 is not exactly -5% in floating point
    for i, edge in enumerate(CHANGE_EDGES):
        if (c < edge) if i < 2 else (c <= edge):
            return i
    return 4


def flow_class(pct: float | None) -> str:
    """The USGS WaterWatch classes the eye.jcamd.com streamflow condition uses."""
    if pct is None:
        return "not rated"
    if pct < 10:
        return "much below normal"
    if pct < 25:
        return "below normal"
    if pct <= 75:
        return "normal"
    if pct <= 90:
        return "above normal"
    return "much above normal"


def _rank_pct(sorted_vals: list[float], x: float) -> tuple[int, int]:
    lo = bisect.bisect_left(sorted_vals, x)
    hi = bisect.bisect_right(sorted_vals, x)
    return lo, hi - lo


@dataclass
class SiteHistory:
    """Per-day percentiles for one gauge, each computed only from days before it."""

    start: date
    cfs: list[float | None]
    pct_date: list[float | None] = field(default_factory=list)
    pct_all: list[float | None] = field(default_factory=list)
    p90: list[float | None] = field(default_factory=list)

    def index(self, d: date) -> int | None:
        i = (d - self.start).days
        return i if 0 <= i < len(self.cfs) else None

    def value(self, d: date) -> float | None:
        i = self.index(d)
        return None if i is None else self.cfs[i]


def site_history(start: date, cfs: list[float | None]) -> SiteHistory:
    """Walk the record once. Day i's statistics see days < i (all-days) and days <= i - DOY_LAG_DAYS (day of year)."""
    h = SiteHistory(start, cfs)
    all_sorted: list[float] = []
    bins: list[list[float]] = [[] for _ in range(365)]
    for i, x in enumerate(cfs):
        d = start + timedelta(days=i)
        lag = i - DOY_LAG_DAYS
        if lag >= 0 and cfs[lag] is not None:
            bisect.insort(bins[doy_index(start + timedelta(days=lag))], cfs[lag])
        pd = pa = q = None
        if x is not None:
            k = doy_index(d)
            less = eq = n = 0
            for off in range(-DOY_WINDOW, DOY_WINDOW + 1):
                b = bins[(k + off) % 365]
                lo, e = _rank_pct(b, x)
                less += lo
                eq += e
                n += len(b)
            if n >= MIN_DOY_HISTORY:
                pd = round(100.0 * (less + 0.5 * eq) / n, 1)
            if len(all_sorted) >= MIN_ALL_HISTORY:
                lo, e = _rank_pct(all_sorted, x)
                pa = round(100.0 * (lo + 0.5 * e) / len(all_sorted), 1)
                q = all_sorted[round(0.9 * (len(all_sorted) - 1))]
        h.pct_date.append(pd)
        h.pct_all.append(pa)
        h.p90.append(q)
        if x is not None:
            bisect.insort(all_sorted, x)
    return h


def iso_ts(s: str) -> int:
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp())


def decision_ts(d: date, tz: str) -> int:
    """T: the end of local standard day d, as UTC epoch seconds."""
    midnight = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1, hours=TZ_HOURS.get(tz, 5))
    return int(midnight.timestamp())


@dataclass
class WarningIndex:
    """Warnings covering each gauge (issue, expire) and issue times per office, all sorted."""

    covering: dict[str, list[tuple[int, int]]]
    by_wfo: dict[str, list[int]]
    last_ts: int

    @classmethod
    def build(cls, gauges: list[dict[str, Any]], warnings: list[dict[str, Any]], last_ts: int) -> WarningIndex:
        covering: dict[str, list[tuple[int, int]]] = {g["site"]: [] for g in gauges}
        by_wfo: dict[str, list[int]] = {}
        for w in warnings:
            t0, t1 = iso_ts(w["issue"]), iso_ts(w["expire"])
            by_wfo.setdefault(w["wfo"], []).append(t0)
            x0, y0, x1, y1 = polygons_bbox(w["polygons"])
            for g in gauges:
                if x0 <= g["lon"] <= x1 and y0 <= g["lat"] <= y1 and polygons_contain(w["polygons"], g["lon"], g["lat"]):
                    covering[g["site"]].append((t0, t1))
        for v in covering.values():
            v.sort()
        for v in by_wfo.values():
            v.sort()
        return cls(covering, by_wfo, last_ts)

    def features(self, site: str, wfo: str, t: int) -> dict[str, Any]:
        cov = self.covering.get(site, [])
        hi = bisect.bisect_right(cov, (t, 1 << 62))
        lo30 = bisect.bisect_right(cov, (t - 30 * DAY_S, 1 << 62))
        lo_act = bisect.bisect_right(cov, (t - ACTIVE_LOOKBACK_S, 1 << 62))
        issues = self.by_wfo.get(wfo, [])
        end = bisect.bisect_right(issues, t)
        return {
            "warn_active": any(e > t for _, e in cov[lo_act:hi]),
            "warn_gauge_30d": hi - lo30,
            "warn_wfo_7d": end - bisect.bisect_right(issues, t - 7 * DAY_S),
            "warn_wfo_1d": end - bisect.bisect_right(issues, t - DAY_S),
        }

    def issued_after(self, site: str, t: int, horizon_s: int = DAY_S) -> bool | None:
        """A covering warning issued in (t, t + horizon]; None when that window runs past the harvest."""
        if t + horizon_s > self.last_ts:
            return None
        cov = self.covering.get(site, [])
        i = bisect.bisect_right(cov, (t, 1 << 62))
        return i < len(cov) and cov[i][0] <= t + horizon_s


@dataclass
class Corpus:
    gauges: list[dict[str, Any]]
    flows: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    warnings_through: str  # last day (UTC, exclusive) the warning harvest covers

    @classmethod
    def load(cls) -> Corpus:
        stats = json.loads((SOURCES / "harvest_stats.json").read_text(encoding="utf-8"))
        end = date.fromisoformat(stats["end"]) + timedelta(days=2)
        return cls(read_jsonl(SOURCES / "gauges.jsonl.gz"), read_jsonl(SOURCES / "flows.jsonl.gz"),
                   read_jsonl(SOURCES / "warnings.jsonl.gz"), end.isoformat())


def build_rows(corpus: Corpus, row_start: date = ROW_START) -> list[dict[str, Any]]:
    """Every (gauge, day) with a full feature set and all three labels observed."""
    hist = {f["site"]: site_history(date.fromisoformat(f["start"]), f["cfs"]) for f in corpus.flows}
    gauges = [g for g in corpus.gauges if g["site"] in hist]
    last_ts = iso_ts(corpus.warnings_through + "T00:00:00")
    widx = WarningIndex.build(gauges, corpus.warnings, last_ts)
    names = {g["site"]: g for g in gauges}
    rows: list[dict[str, Any]] = []
    for g in gauges:
        h = hist[g["site"]]
        up = hist.get(g["upstream"] or "")
        for i in range(len(h.cfs) - 1):
            d = h.start + timedelta(days=i)
            if d < row_start:
                continue
            x, nxt = h.cfs[i], h.cfs[i + 1]
            if x is None or nxt is None or h.pct_date[i] is None or h.p90[i] is None:
                continue
            t = decision_ts(d, g["tz"])
            warn_next = widx.issued_after(g["site"], t)
            if warn_next is None:
                continue
            threshold = sig3(h.p90[i])
            feats: dict[str, Any] = {
                "flow": x,
                "pct_date": h.pct_date[i],
                "pct_all": h.pct_all[i],
                "p90": threshold,
                "chg1": pct_change(x, h.cfs[i - 1] if i >= 1 else None),
                "chg3": pct_change(x, h.cfs[i - 3] if i >= 3 else None),
                "chg7": pct_change(x, h.cfs[i - 7] if i >= 7 else None),
                "month": d.month,
                "doy": doy_index(d),
                "season": SEASONS[d.month],
                **widx.features(g["site"], g["wfo"], t),
            }
            if up is not None:
                j = up.index(d)
                ux = up.value(d)
                feats["up_site"] = g["upstream"]
                feats["up_name"] = names.get(g["upstream"], {}).get("name", g["upstream"])
                feats["up_pct_date"] = up.pct_date[j] if j is not None else None
                feats["up_chg1"] = pct_change(ux, up.value(d - timedelta(days=1)))
                feats["up_chg3"] = pct_change(ux, up.value(d - timedelta(days=3)))
            rows.append({
                "site": g["site"],
                "date": d.isoformat(),
                "decision_utc": datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%MZ"),
                "features": feats,
                "labels": {
                    "high_next": nxt > threshold,
                    "warn_next": warn_next,
                    "change_bucket": change_bucket(x, nxt),
                },
                "next_flow": nxt,
            })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args(argv)
    rows = build_rows(Corpus.load())
    out = DATA / "features"
    write_jsonl(out / "features.jsonl.gz", rows)
    stats = {
        "rows": len(rows),
        "gauges": len({r["site"] for r in rows}),
        "first_day": min(r["date"] for r in rows),
        "last_day": max(r["date"] for r in rows),
        "high_next_rate": round(sum(r["labels"]["high_next"] for r in rows) / len(rows), 4),
        "warn_next_rate": round(sum(r["labels"]["warn_next"] for r in rows) / len(rows), 4),
        "change_buckets": dict(sorted(Counter(r["labels"]["change_bucket"] for r in rows).items())),
    }
    (out / "features_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0
