"""Stage 1: harvest gauges, daily flow and NWS flood-warning polygons.

  USGS site service      site metadata (name, lat/lon, county, HUC, drainage area, time zone)
  IEM /api/1/nws/ugcs    county UGC -> NWS office (WFO) and county name, per state
  USGS NWIS daily values mean daily discharge (00060), 1995-10-01 -> --end
  IEM /api/1/vtec/sbw_interval
                         storm-based (polygon) warnings issued in each gauge WFO,
                         flood (FL), areal flood (FA) and flash flood (FF), 2015 -> --end

Raw responses are cached gzipped under data/raw (gitignored), so a rerun costs
nothing; the normalized, compact snapshots go to sources/ and are committed:

  sources/gauges.jsonl.gz    one row per gauge
  sources/flows.jsonl.gz     one row per gauge: start date and a dense cfs array (null = no value)
  sources/warnings.jsonl.gz  one row per warning polygon at issuance (NEW), rings rounded to 1e-4 deg
  sources/harvest_stats.json counts, the window, and the endpoints

A gauge or office that fails contributes nothing and is listed in the stats;
nothing is filled in.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .common import SOURCES, HttpError, cached_get, stable_id, write_jsonl
from .gauges import COUNTY_UGC_OVERRIDE, GAUGES, STATE_USPS

FLOW_START = "1995-10-01"
WARN_START_YEAR = 2015
DEFAULT_END = "2026-09-22"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/?format=rdb&siteOutput=expanded&sites={sites}"
DV_URL = "https://waterservices.usgs.gov/nwis/dv/?format=json&sites={site}&parameterCd=00060&statCd=00003&startDT={start}&endDT={end}"
UGC_URL = "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.json?state={state}"
SBW_URL = "https://mesonet.agron.iastate.edu/api/1/vtec/sbw_interval.geojson?begints={b}T00:00Z&endts={e}T00:00Z&wfo={wfo}&only_new=true&{ph}"
# The endpoint takes at most two phenomena per call.
PH_GROUPS = ("ph=FL&ph=FA", "ph=FF")
FLOOD_PHENOMENA = {"FL", "FA", "FF"}


def parse_rdb(text: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"), strict=False)) for ln in lines[2:]]


def parse_dv(payload: dict[str, Any]) -> dict[str, float | None]:
    """date -> mean daily cfs from a NWIS dv JSON answer; the longest method series wins; no-data sentinels are None."""
    series = (payload.get("value") or {}).get("timeSeries") or []
    best: list[dict[str, Any]] = []
    nodata = None
    for ts in series:
        nodata = (ts.get("variable") or {}).get("noDataValue", nodata)
        for block in ts.get("values") or []:
            vals = block.get("value") or []
            if len(vals) > len(best):
                best = vals
    out: dict[str, float | None] = {}
    for v in best:
        day = str(v.get("dateTime", ""))[:10]
        try:
            x = float(v.get("value"))
        except (TypeError, ValueError):
            x = None
        if x is not None and (x < 0 or (nodata is not None and x == float(nodata))):
            x = None
        if day:
            out[day] = x
    return out


def dense(values: dict[str, float | None]) -> tuple[str, list[float | None]]:
    """(start date, contiguous daily array) with None for days the service did not report."""
    if not values:
        return "", []
    days = sorted(values)
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    out: list[float | None] = []
    d = d0
    while d <= d1:
        x = values.get(d.isoformat())
        out.append(None if x is None else (round(x, 2) if x != int(x) else int(x)))
        d += timedelta(days=1)
    return d0.isoformat(), out


def _round_ring(ring: list[list[float]]) -> list[list[float]]:
    return [[round(float(x), 4), round(float(y), 4)] for x, y, *_ in ring]


def normalize_geometry(geom: dict[str, Any] | None) -> list[list[list[list[float]]]]:
    """GeoJSON Polygon/MultiPolygon -> a list of polygons, each [outer ring, holes...]."""
    if not geom:
        return []
    if geom.get("type") == "Polygon":
        return [[_round_ring(r) for r in geom["coordinates"]]]
    if geom.get("type") == "MultiPolygon":
        return [[_round_ring(r) for r in poly] for poly in geom["coordinates"]]
    return []


def normalize_warning(feature: dict[str, Any]) -> dict[str, Any] | None:
    p = feature.get("properties") or {}
    if p.get("phenomena") not in FLOOD_PHENOMENA or p.get("significance") != "W":
        return None
    polys = normalize_geometry(feature.get("geometry"))
    if not polys or not p.get("utc_issue") or not p.get("utc_expire"):
        return None
    return {
        "wfo": p.get("wfo"),
        "phenomena": p["phenomena"],
        "significance": "W",
        "eventid": int(p.get("eventid") or 0),
        "year": int(p.get("year") or str(p["utc_issue"])[:4]),
        "issue": p["utc_issue"],
        "expire": p["utc_expire"],
        "product_id": p.get("product_id"),
        "ugcs": sorted(u.strip() for u in str(p.get("ugclist") or "").split(",") if u.strip()),
        "polygons": polys,
    }


def harvest(end: str = DEFAULT_END, refresh: bool = False) -> dict[str, Any]:
    stats: dict[str, Any] = {"end": end, "flow_start": FLOW_START, "warn_start_year": WARN_START_YEAR, "failed": [],
                             "endpoints": [SITE_URL, DV_URL, UGC_URL, SBW_URL]}
    sites = sorted(GAUGES)
    meta = {r["site_no"]: r for r in parse_rdb(cached_get(SITE_URL.format(sites=",".join(sites)), f"site/expanded_{stable_id(*sites)}", refresh=refresh).decode("utf-8"))}
    ugc: dict[str, dict[str, str]] = {}
    for fips, usps in sorted(STATE_USPS.items()):
        try:
            rows = json.loads(cached_get(UGC_URL.format(state=usps), f"ugc/{usps}", refresh=refresh, host_gap_s=1.0))["data"]
        except (HttpError, OSError, ValueError, KeyError) as e:
            stats["failed"].append({"ugc": usps, "error": str(e)[:120]})
            continue
        for r in rows:
            ugc[r["ugc"]] = {"wfo": r["wfo"], "name": r["name"], "state": fips}

    gauges: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []
    for site in sites:
        m = meta.get(site)
        if not m:
            stats["failed"].append({"site": site, "error": "not in the site service"})
            continue
        usps = STATE_USPS.get(m["state_cd"], "")
        county_ugc = COUNTY_UGC_OVERRIDE.get(site, f"{usps}C{m['county_cd']}")
        u = ugc.get(county_ugc)
        if not u:
            stats["failed"].append({"site": site, "error": f"no UGC {county_ugc}"})
            continue
        try:
            payload = json.loads(cached_get(DV_URL.format(site=site, start=FLOW_START, end=end), f"dv/{site}_{FLOW_START}_{end}", refresh=refresh, host_gap_s=1.0))
        except (HttpError, OSError, ValueError) as e:
            stats["failed"].append({"site": site, "error": str(e)[:120]})
            continue
        start, cfs = dense(parse_dv(payload))
        if not cfs:
            stats["failed"].append({"site": site, "error": "no daily values"})
            continue
        drain = m.get("drain_area_va", "").strip()
        gauges.append({
            "site": site,
            "name": m["station_nm"].strip(),
            "lat": round(float(m["dec_lat_va"]), 5),
            "lon": round(float(m["dec_long_va"]), 5),
            "state": usps,
            "county_ugc": county_ugc,
            "county": u["name"],
            "wfo": u["wfo"],
            "huc8": m["huc_cd"][:8],
            "drainage_sq_mi": float(drain) if drain else None,
            "tz": m["tz_cd"],
            "upstream": GAUGES[site],
        })
        flows.append({"site": site, "start": start, "cfs": cfs})

    wfos = sorted({g["wfo"] for g in gauges})
    end_d = date.fromisoformat(end)
    warnings: dict[tuple, dict[str, Any]] = {}
    for wfo in wfos:
        for year in range(WARN_START_YEAR, end_d.year + 1):
            b = f"{year}-01-01"
            e = min(date(year + 1, 1, 1), end_d + timedelta(days=2)).isoformat()
            for ph in PH_GROUPS:
                tag = ph.replace("ph=", "").replace("&", "")
                try:
                    body = cached_get(SBW_URL.format(b=b, e=e, wfo=wfo, ph=ph), f"sbw/{wfo}_{year}_{tag}_{e}", refresh=refresh, host_gap_s=1.0)
                    feats = json.loads(body).get("features") or []
                except (HttpError, OSError, ValueError) as err:
                    stats["failed"].append({"wfo": wfo, "year": year, "ph": tag, "error": str(err)[:120]})
                    continue
                for f in feats:
                    w = normalize_warning(f)
                    if w:
                        warnings[(w["wfo"], w["phenomena"], w["year"], w["eventid"], w["product_id"])] = w
    rows = sorted(warnings.values(), key=lambda w: (w["issue"], w["wfo"], w["phenomena"], w["eventid"], w["product_id"] or ""))

    SOURCES.mkdir(parents=True, exist_ok=True)
    write_jsonl(SOURCES / "gauges.jsonl.gz", gauges)
    write_jsonl(SOURCES / "flows.jsonl.gz", flows)
    write_jsonl(SOURCES / "warnings.jsonl.gz", rows)
    stats.update({
        "gauges": len(gauges),
        "paired": sum(1 for g in gauges if g["upstream"]),
        "wfos": wfos,
        "flow_days": sum(sum(1 for x in f["cfs"] if x is not None) for f in flows),
        "warnings": len(rows),
        "warnings_by_phenomena": {p: sum(1 for w in rows if w["phenomena"] == p) for p in sorted(FLOOD_PHENOMENA)},
        "harvested_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    (SOURCES / "harvest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", default=DEFAULT_END, help="last day of flow and warnings to fetch (YYYY-MM-DD)")
    ap.add_argument("--refresh", action="store_true", help="ignore the data/raw cache")
    args = ap.parse_args(argv)
    s = harvest(args.end, args.refresh)
    print(json.dumps({k: s[k] for k in ("gauges", "paired", "wfos", "flow_days", "warnings", "warnings_by_phenomena", "failed")}, indent=2))
    return 0 if s["gauges"] else 1
