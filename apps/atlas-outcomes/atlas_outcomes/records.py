"""Render a feature row as a strict jev-decision-schema-1.0.0 record.

The state is what a place decision on eye.jcamd.com sees at the end of day t:
the gauge, its construct stack (county, HUC-8, NWS office, state, named as the
Atlas strata rail names them) with the layers active there (the streamflow
condition class, whether a flood-type warning polygon is in effect over the
gauge), the flow and its recent change, the upstream gauge, and recent
warning activity. It never carries t+1's flow, the next day's warnings or any
label; tests/test_outcomes.py checks that.

Three questions per record, all answered by what happened next:

  high_next      noul   tomorrow's mean flow above the stated p90 threshold
  warn_next      noul   a flood-type warning polygon over the gauge issued in the next 24 h
  flow_change    score  tomorrow's change in five ordered levels
"""

from __future__ import annotations

from typing import Any

from . import SCHEMA_ID
from .common import stable_id
from .features import CHANGE_LEVELS, flow_class


def _cfs(x: float) -> str:
    return f"{x:,.0f} cfs" if x >= 10 else f"{x:g} cfs"


def _pct(x: float | None) -> str:
    return "not reported" if x is None else f"{x:+.1f}%"


def construct_stack(g: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    """Smallest construct first, like the Atlas strata rail; the layers active at the gauge."""
    return {
        "constructs": [
            {"kind": "County", "id": g["county_ugc"], "name": f"{g['county']}, {g['state']}"},
            {"kind": "HUC-8", "id": g["huc8"]},
            {"kind": "NWS office", "id": g["wfo"]},
            {"kind": "State", "id": g["state"]},
        ],
        "layers": {
            "water": f"streamflow {flow_class(f['pct_date'])} for the date",
            "nws-alert": "flood-type warning in effect over the gauge" if f["warn_active"] else "no flood-type warning over the gauge",
            **({"upstream water": f"streamflow {flow_class(f.get('up_pct_date'))} for the date"} if f.get("up_site") else {}),
        },
    }


def render_state(g: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    f = row["features"]
    state: dict[str, Any] = {
        "place": {
            "gauge": f"USGS {g['site']}",
            "name": g["name"],
            "drainage_area": "not published" if g.get("drainage_sq_mi") is None else f"{g['drainage_sq_mi']:,.0f} sq mi",
        },
        "as_of": f"end of day {row['date']} local time ({f['season']})",
        **construct_stack(g, f),
        "flow": {
            "today": _cfs(f["flow"]),
            "percentile_for_the_date": f["pct_date"],
            "percentile_of_all_prior_days": f["pct_all"],
            "change_vs_1_day_ago": _pct(f["chg1"]),
            "change_vs_3_days_ago": _pct(f["chg3"]),
            "change_vs_7_days_ago": _pct(f["chg7"]),
        },
        "warnings": {
            "flood_type_warnings_over_gauge_last_30_days": f["warn_gauge_30d"],
            "flood_type_warnings_by_office_last_7_days": f["warn_wfo_7d"],
            "flood_type_warnings_by_office_last_24_hours": f["warn_wfo_1d"],
        },
    }
    if f.get("up_site"):
        state["upstream"] = {
            "gauge": f"USGS {f['up_site']}",
            "name": f["up_name"],
            "percentile_for_the_date": f["up_pct_date"],
            "change_vs_1_day_ago": _pct(f["up_chg1"]),
            "change_vs_3_days_ago": _pct(f["up_chg3"]),
        }
    else:
        state["upstream"] = "no paired upstream gauge"
    return state


def questions(row: dict[str, Any]) -> dict[str, Any]:
    p90 = row["features"]["p90"]
    return {
        "high_next": {
            "type": "noul",
            "instructions": f"Will tomorrow's mean daily flow at this gauge be above {_cfs(p90)}, the 90th percentile of every prior day on its record?",
        },
        "warn_next": {
            "type": "noul",
            "instructions": "Will the National Weather Service issue a flood, areal flood or flash flood warning whose polygon covers this gauge within the next 24 hours?",
        },
        "flow_change": {
            "type": "score",
            "instructions": "How will tomorrow's mean daily flow at this gauge compare with today's?",
            "criteria": list(CHANGE_LEVELS),
        },
    }


def labels(row: dict[str, Any]) -> dict[str, Any]:
    lab = row["labels"]
    return {
        "high_next": {"type": "noul", "noul": 1.0 if lab["high_next"] else 0.0},
        "warn_next": {"type": "noul", "noul": 1.0 if lab["warn_next"] else 0.0},
        "flow_change": {"type": "score", "score": float(lab["change_bucket"])},
    }


def record_id(row: dict[str, Any]) -> str:
    return f"atlas-{row['site']}-{row['date']}-{stable_id(row['site'], row['date'], n=6)}"


def to_record(g: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "id": record_id(row),
        "state": render_state(g, row),
        "questions": questions(row),
        "labels": labels(row),
    }
