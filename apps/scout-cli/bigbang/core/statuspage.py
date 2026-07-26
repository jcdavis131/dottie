# Solo personal project, no connection to employer, built with public/free-tier only
"""Statuspage — static status page core (openswap #18: StatusPage.io / Atlassian).

The paid enemy is a hosted page you pay to publish and a wire protocol you pay
to feed. This adapter deletes both halves: the page is one self-contained HTML
file rendered from ledgers that ALREADY exist on this box, and there is no feed
at all because this adapter collects NOTHING. Every number on the page was
recorded by uptime (#2), certmon (#9) or heartbeat (#6); statuspage only reads.

Read-only is architectural, not a promise: open_readonly() hands back a sqlite
connection opened with `mode=ro`, so INSERT/UPDATE/CREATE against the shared
monitoring ledger physically fail (sqlite raises "attempt to write a readonly
database"). A future edit to this module cannot quietly start collecting, and
the page can never contend for the write lock that uptime's probe loop holds.

Provenance honesty is the other invariant, and it is why this module is bigger
than a template renderer:
- Services are derived from what was RECORDED (`SELECT DISTINCT target FROM
  checks`), never from uptime.DEFAULT_TARGETS. Listing configured-but-never-
  probed services would imply coverage that does not exist.
- A source counts as `present` only when its table exists AND holds a row. A
  `certs` table created by a certmon run that recorded nothing is not evidence
  of certificate monitoring.
- An absent ledger renders the no-data state (overall "no_data", uptime_pct
  None, an explicit "nothing was recorded on this box" block). It never
  degrades into a green board, and it is not an error — a status page whose
  data source vanished must SAY so, which is exactly when a page matters most.
- Staleness counts against the roll-up: a green board built from three-day-old
  checks is a lie, so a service whose newest check is older than stale_after_s
  is flagged and drags `overall` down to degraded.
- Grace periods are deliberately NOT guessed for heartbeat rows. Those live in
  heartbeat's JSON config; this page reports the ledger's own confirmed hb:
  state plus the age of the last beat, and calls nothing "late" on authority
  it does not have.

Substrate reuse (no reinvented SQL): board()/rollup()/list_incidents()/
recent_events() from #2, board() from #9 — the read contracts those modules
document for exactly this consumer — plus heartbeat.NS so a daemon named like a
service can never be reported as one.

Extension points:
- Window and staleness budgets are parameters (window_hours, stale_after_s):
  feed them from the CLI or a JSON overlay, don't tune code.
- render_html() takes the snapshot dict, not a connection, so any producer of
  that shape (a merged multi-box snapshot, a fixture) can be rendered.
- to_diagnostics() maps the page onto the family schema (down=error,
  degraded/stale/no-ledger=warning, unknown=info), so openswap.summarize() and
  `--fail-on` gate on a status page exactly like prose findings.
"""

from __future__ import annotations

import html
import sqlite3
import time
from pathlib import Path
from typing import Any

from bigbang.core import certmon, heartbeat, openswap, uptime

# the SHARED monitoring ledger (#2) — read-only here, owned by uptime
LEDGER_REL = uptime.DB_REL
PAGE_REL = Path(".scout") / "status.html"

OVERALL_OPERATIONAL = "operational"
OVERALL_DEGRADED = "degraded"
OVERALL_OUTAGE = "outage"
OVERALL_NO_DATA = "no_data"

STATE_UNKNOWN = "unknown"

DEFAULT_WINDOW_HOURS = 24.0
# newest check older than this and the row is not evidence of anything current
DEFAULT_STALE_AFTER_S = 3600.0
DEFAULT_EVENTS = 10

# worst-first: a status page puts problems at the top, not in alphabetical order
_SERVICE_RANK = {
    uptime.STATE_DOWN: 0,
    uptime.STATE_DEGRADED: 1,
    STATE_UNKNOWN: 2,
    uptime.STATE_UP: 3,
}

# (source, owning plugin, openswap rank, table, static count query)
_SOURCE_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "uptime",
        "uptime",
        "#2",
        "checks",
        "SELECT COUNT(*) AS n, MAX(ts) AS newest FROM checks",
    ),
    (
        "certmon",
        "certmon",
        "#9",
        "certs",
        "SELECT COUNT(*) AS n, MAX(ts) AS newest FROM certs",
    ),
    (
        "heartbeat",
        "heartbeat",
        "#6",
        "beats",
        "SELECT COUNT(*) AS n, MAX(last_ts) AS newest FROM beats",
    ),
)


# ---- read-only access -------------------------------------------------------


def open_readonly(path: str | Path) -> sqlite3.Connection | None:
    """Open the shared monitoring ledger READ-ONLY, or None when it is absent.

    `mode=ro` is the enforcement half of "this adapter collects nothing": the
    returned connection rejects every write at the sqlite layer, so statuspage
    cannot create tables, cannot record, and cannot take the write lock away
    from uptime's probe loop. A missing file returns None rather than raising —
    that is the no-data state the page renders honestly, not a failure.
    """
    p = Path(path)
    if not p.exists():
        return None
    # as_uri() gives the absolute, percent-encoded form sqlite's URI parser
    # wants on Windows too (file:///C:/...), so paths with spaces still open.
    conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_present(conn: sqlite3.Connection, name: str) -> bool:
    """Does this ledger carry that table? (certmon/heartbeat may never have run.)"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def sources(
    conn: sqlite3.Connection | None, path: str | Path | None = None
) -> dict[str, Any]:
    """Which ledgers this page can actually see — the provenance surface.

    `present` requires the table to exist AND hold at least one row: an empty
    table proves the owning plugin was linked, not that it ever observed
    anything, and the page must not imply otherwise. Every count query here is
    a static string (no interpolated table names) so the read path stays
    auditable.
    """
    p = None if path is None else Path(path)
    ledger: dict[str, Any] = {
        "path": None if p is None else str(p),
        "present": conn is not None,
        "size_bytes": None,
        "mode": "ro",
    }
    if p is not None and p.exists():
        ledger["size_bytes"] = p.stat().st_size
    out: dict[str, Any] = {"ledger": ledger}
    for name, plugin, rank, table, query in _SOURCE_SPECS:
        entry: dict[str, Any] = {
            "plugin": plugin,
            "openswap": rank,
            "table": table,
            "table_present": False,
            "rows": 0,
            "newest_ts": None,
            "present": False,
        }
        if conn is not None and table_present(conn, table):
            row = conn.execute(query).fetchone()
            entry["table_present"] = True
            entry["rows"] = int(row["n"] or 0)
            entry["newest_ts"] = row["newest"]
            entry["present"] = entry["rows"] > 0
        out[name] = entry
    return out


# ---- services ---------------------------------------------------------------


def ledger_targets(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """{target: {"url": newest url}} for every SERVICE recorded in the ledger.

    Derived from `checks`, never from uptime.DEFAULT_TARGETS — the page reports
    what was measured, not what someone configured. heartbeat's
    "hb:"-namespaced rows are excluded here and surfaced as daemons instead, so
    a daemon can never be presented as a monitored service.
    """
    if not table_present(conn, "checks"):
        return {}
    out: dict[str, dict[str, Any]] = {}
    names = [
        r["target"]
        for r in conn.execute("SELECT DISTINCT target FROM checks ORDER BY target")
    ]
    for name in names:
        if name.startswith(heartbeat.NS):
            continue
        last = conn.execute(
            "SELECT url FROM checks WHERE target = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (name,),
        ).fetchone()
        out[name] = {"url": None if last is None else last["url"]}
    return out


def window_states(
    conn: sqlite3.Connection, target: str, *, since: float
) -> dict[str, int]:
    """Raw observation counts by state in the window — keeps degraded visible.

    up_pct alone hides the difference between "served slowly 40 times" and
    "was hard down 40 times"; both dent the same percentage.
    """
    rows = conn.execute(
        "SELECT state, COUNT(*) AS n FROM checks WHERE target = ? AND ts >= ?"
        " GROUP BY state",
        (target, since),
    )
    return {r["state"]: int(r["n"]) for r in rows}


def service_rows(
    conn: sqlite3.Connection,
    *,
    now: float,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> list[dict[str, Any]]:
    """Per-service page rows: current state, window uptime, last incident.

    uptime.board() supplies the confirmed state / last check / open incident,
    uptime.rollup() the availability + latency percentiles (raw observations,
    so a flappy service scores honestly), uptime.list_incidents() the most
    recent incident whether it is open or closed. `uptime_pct` stays None when
    the window holds no checks — the page prints an em dash there rather than
    a fabricated 100%.
    """
    targets = ledger_targets(conn)
    if not targets:
        return []
    since = now - window_hours * 3600.0
    rows = uptime.board(conn, targets)
    for row in rows:
        roll = uptime.rollup(conn, row["target"], since=since)
        last = row.get("last_check") or {}
        last_ts = last.get("ts")
        age = None if last_ts is None else round(max(0.0, now - float(last_ts)), 3)
        incidents = uptime.list_incidents(conn, target=row["target"], limit=1)
        row.update(
            uptime_pct=roll["up_pct"],
            checks=roll["checks"],
            latency=roll["latency"],
            window_states=window_states(conn, row["target"], since=since),
            age_s=age,
            stale=bool(age is not None and age > stale_after_s),
            last_incident=incidents[0] if incidents else None,
        )
    rows.sort(key=lambda r: (_SERVICE_RANK.get(r["state"], 9), r["target"]))
    return rows


def overall_status(services: list[dict[str, Any]]) -> str:
    """Worst-of roll-up over the service rows.

    No services at all is no_data, never "operational" (an empty page is not a
    healthy one). Staleness and unknown states count against: if we cannot
    vouch for a row's freshness we do not claim the fleet is fine.
    """
    if not services:
        return OVERALL_NO_DATA
    states = {s.get("state") for s in services}
    if uptime.STATE_DOWN in states:
        return OVERALL_OUTAGE
    if states == {STATE_UNKNOWN}:
        return OVERALL_NO_DATA
    if uptime.STATE_DEGRADED in states or STATE_UNKNOWN in states:
        return OVERALL_DEGRADED
    if any(s.get("stale") for s in services):
        return OVERALL_DEGRADED
    return OVERALL_OPERATIONAL


# ---- certificates + daemons (present only when those plugins have run) ------


def cert_rows(conn: sqlite3.Connection, *, now: float) -> list[dict[str, Any]]:
    """Cert posture per host, straight from certmon's documented board()."""
    if not table_present(conn, "certs"):
        return []
    hosts = [
        r["host"] for r in conn.execute("SELECT DISTINCT host FROM certs ORDER BY host")
    ]
    rows = certmon.board(conn, hosts, now=now)
    for row in rows:
        # the page needs the posture, not certmon's whole history row
        row.pop("last", None)
    return rows


def daemon_rows(conn: sqlite3.Connection, *, now: float) -> list[dict[str, Any]]:
    """Heartbeat liveness from the ledger, with no invented grace periods.

    Grace and expected-cadence budgets live in heartbeat's JSON config, which
    this page deliberately does not read: guessing them would let the page call
    a daemon "late" on authority it does not have. What the ledger itself knows
    is reported — the hb:-namespaced confirmed state, the beat count, and how
    long ago the last beat landed.
    """
    if not table_present(conn, "beats"):
        return []
    out: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT daemon, first_ts, last_ts, count, note FROM beats ORDER BY daemon"
    ):
        key = heartbeat.NS + r["daemon"]
        st = conn.execute(
            "SELECT state, since FROM state WHERE target = ?", (key,)
        ).fetchone()
        open_inc = conn.execute(
            "SELECT id, state, opened_ts FROM incidents"
            " WHERE target = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1",
            (key,),
        ).fetchone()
        last_ts = None if r["last_ts"] is None else float(r["last_ts"])
        out.append(
            {
                "daemon": r["daemon"],
                "note": r["note"],
                "beats": int(r["count"]),
                "first_ts": r["first_ts"],
                "last_ts": last_ts,
                "age_s": (
                    None if last_ts is None else round(max(0.0, now - last_ts), 3)
                ),
                "state": st["state"] if st else STATE_UNKNOWN,
                "since": st["since"] if st else None,
                "open_incident": dict(open_inc) if open_inc else None,
            }
        )
    return out


def event_rows(
    conn: sqlite3.Connection, *, now: float, limit: int = DEFAULT_EVENTS
) -> list[dict[str, Any]]:
    """The shared timeline (deploys, ops notes, cert findings, alerts)."""
    if not table_present(conn, "events"):
        return []
    rows = uptime.recent_events(conn, limit=limit)
    for row in rows:
        ts = row.get("ts")
        row["age_s"] = None if ts is None else round(max(0.0, now - float(ts)), 3)
    return rows


# ---- the snapshot (the render contract) -------------------------------------


def snapshot(
    conn: sqlite3.Connection | None,
    *,
    path: str | Path | None = None,
    now: float | None = None,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    events: int = DEFAULT_EVENTS,
    title: str = "Status",
) -> dict[str, Any]:
    """Everything the page shows, as one JSON-able dict. conn=None is no-data.

    A None connection (absent ledger) is a first-class outcome: the snapshot
    comes back with empty sections, uptime_pct nowhere, and overall "no_data".
    Nothing here fabricates a figure it did not read.
    """
    now = time.time() if now is None else float(now)
    snap: dict[str, Any] = {
        "title": title,
        "generated_ts": now,
        "window_hours": window_hours,
        "stale_after_s": stale_after_s,
        "sources": sources(conn, path),
        "services": [],
        "certs": [],
        "daemons": [],
        "events": [],
        "collects": False,  # the family invariant, stated in the payload
    }
    if conn is not None:
        snap["services"] = service_rows(
            conn, now=now, window_hours=window_hours, stale_after_s=stale_after_s
        )
        snap["certs"] = cert_rows(conn, now=now)
        snap["daemons"] = daemon_rows(conn, now=now)
        snap["events"] = event_rows(conn, now=now, limit=events)
    by_state: dict[str, int] = {}
    for s in snap["services"]:
        by_state[s["state"]] = by_state.get(s["state"], 0) + 1
    snap["overall"] = overall_status(snap["services"])
    snap["counts"] = {
        "services": len(snap["services"]),
        "by_state": by_state,
        "stale": sum(1 for s in snap["services"] if s.get("stale")),
        "open_incidents": sum(
            1 for s in snap["services"] if s.get("open_incident") is not None
        ),
        "certs": len(snap["certs"]),
        "daemons": len(snap["daemons"]),
    }
    return snap


def read_snapshot(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """open_readonly + snapshot in one call; an absent ledger is honest no-data."""
    conn = open_readonly(path)
    try:
        return snapshot(conn, path=path, **kwargs)
    finally:
        if conn is not None:
            conn.close()


# ---- family diagnostics -----------------------------------------------------

_SEVERITY_OF = {
    uptime.STATE_DOWN: "error",
    uptime.STATE_DEGRADED: "warning",
    STATE_UNKNOWN: "info",
}


def to_diagnostics(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Map the page onto the family diagnostic schema.

    down=error, degraded=warning, unknown=info, plus two findings only a status
    page can raise: `statuspage:stale` (the board is built from checks nobody
    refreshed) and `statuspage:no-ledger` (there is nothing to publish at all).
    Both are warnings — a page that cannot vouch for its own numbers is a real
    operational problem, not a cosmetic one.
    """
    diags: list[dict[str, Any]] = []
    ledger = snap.get("sources", {}).get("ledger", {})
    if not ledger.get("present"):
        diags.append(
            openswap.diagnostic(
                path=str(ledger.get("path") or LEDGER_REL),
                line=0,
                col=0,
                rule="statuspage:no-ledger",
                severity="warning",
                message=(
                    "no monitoring ledger — the page renders a no-data state; "
                    "run `scout uptime check` to record something to publish"
                ),
            )
        )
    elif not snap.get("services"):
        diags.append(
            openswap.diagnostic(
                path=str(ledger.get("path") or LEDGER_REL),
                line=0,
                col=0,
                rule="statuspage:no-services",
                severity="warning",
                message="ledger present but no service checks recorded in it",
            )
        )
    for s in snap.get("services", []):
        where = s.get("url") or s["target"]
        sev = _SEVERITY_OF.get(s.get("state"))
        if sev is not None:
            pct = s.get("uptime_pct")
            shown = "no checks in window" if pct is None else f"{pct}% up in window"
            diags.append(
                openswap.diagnostic(
                    path=where,
                    line=0,
                    col=0,
                    rule=f"statuspage:{s['state']}",
                    severity=sev,
                    message=f"{s['target']} {s['state']} — {shown}",
                )
            )
        if s.get("stale"):
            diags.append(
                openswap.diagnostic(
                    path=where,
                    line=0,
                    col=0,
                    rule="statuspage:stale",
                    severity="warning",
                    message=(
                        f"{s['target']} data is stale — newest check "
                        f"{s.get('age_s')}s old (budget {snap.get('stale_after_s')}s)"
                    ),
                )
            )
    return openswap.sort_diagnostics(diags)


# ---- rendering --------------------------------------------------------------

_OVERALL_TEXT = {
    OVERALL_OPERATIONAL: "All systems operational",
    OVERALL_DEGRADED: "Degraded — see the rows below",
    OVERALL_OUTAGE: "Outage — one or more services are down",
    OVERALL_NO_DATA: "No data — nothing to report from this box",
}

# timeline event kinds -> pill class (the writers are uptime/certmon/heartbeat)
_EVENT_CLASS = {
    "alert": "error",
    "cert": "warning",
    "recovery": "ok",
    "deploy": "info",
    "note": "info",
}


def _iso(ts: float | None) -> str:
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(float(ts)))


def _ago(seconds: float | None) -> str:
    """Coarse relative age. Never guesses: None renders as an em dash."""
    if seconds is None:
        return "—"
    s = max(0.0, float(seconds))
    if s < 90:
        return f"{int(s)}s ago"
    if s < 5400:
        return f"{s / 60:.0f}m ago"
    if s < 172800:
        return f"{s / 3600:.1f}h ago"
    return f"{s / 86400:.1f}d ago"


def _pct(value: float | None) -> str:
    """Availability text. None means we measured nothing, and says so."""
    return "—" if value is None else f"{float(value):.2f}%"


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "ongoing"
    s = max(0.0, float(seconds))
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    return f"{s / 3600:.1f}h"


def _incident_text(inc: dict[str, Any] | None) -> str:
    if not inc:
        return "none recorded"
    closed = inc.get("closed_ts")
    when = _iso(inc.get("opened_ts"))
    if closed is None:
        return f"{inc.get('state')} since {when} (open)"
    return f"{inc.get('state')} {when} · lasted {_dur(inc.get('duration_s'))}"


_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; margin: 1.5rem auto; max-width: 62rem;
  padding: 0 1rem; color: #1c2430; background: #fff; }
h1 { margin-bottom: .2rem; font-size: 1.5rem; }
h2 { font-size: 1.05rem; margin: 1.6rem 0 .4rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #d8dee6;
  vertical-align: top; }
th { font-size: .8em; text-transform: uppercase; letter-spacing: .03em;
  color: #55606e; }
.mono { font-family: ui-monospace, monospace; font-size: .85em; color: #55606e; }
.note { color: #55606e; font-size: .9em; }
.banner { padding: .7rem .9rem; border-radius: .5rem; color: #fff;
  font-weight: 600; margin: .6rem 0 1rem; }
.ov-operational { background: #1b6b3a; }
.ov-degraded { background: #a86500; }
.ov-outage { background: #b3261e; }
.ov-no_data { background: #4a5b70; }
.pill { padding: .1rem .45rem; border-radius: .6rem; font-size: .8em; color: #fff;
  white-space: nowrap; }
.s-up, .s-ok { background: #1b6b3a; }
.s-degraded, .s-warning, .s-late { background: #a86500; }
.s-down, .s-error, .s-stale { background: #b3261e; }
.s-unknown, .s-never, .s-info { background: #4a5b70; }
.flag { color: #a86500; font-weight: 600; }
.nodata { border: 1px solid #a86500; border-left-width: .35rem; padding: .7rem .9rem;
  border-radius: .3rem; margin: .8rem 0; }
ul { padding-left: 1.1rem; }
li { margin: .2rem 0; }
footer { margin-top: 2rem; font-size: .8em; color: #55606e; }
@media (prefers-color-scheme: dark) {
  body { background: #12161c; color: #e7ecf2; }
  th, td { border-bottom-color: #2b3440; }
  th, .mono, .note, footer { color: #9aa7b6; }
}
"""


def _services_table(snap: dict[str, Any], e: Any) -> str:
    rows = []
    for s in snap["services"]:
        ws = s.get("window_states") or {}
        mix = ", ".join(f"{k} {v}" for k, v in sorted(ws.items())) or "no checks"
        flag = ' <span class="flag">stale</span>' if s.get("stale") else ""
        rows.append(
            "<tr>"
            f"<td><b>{e(str(s['target']))}</b>"
            f'<div class="mono">{e(str(s.get("url") or "—"))}</div></td>'
            f'<td><span class="pill s-{e(str(s["state"]))}">'
            f"{e(str(s['state']))}</span>{flag}</td>"
            f"<td>{e(_pct(s.get('uptime_pct')))}"
            f'<div class="mono">{e(mix)}</div></td>'
            f"<td>{e(_ago(s.get('age_s')))}"
            f'<div class="mono">{e(_iso((s.get("last_check") or {}).get("ts")))}'
            "</div></td>"
            f'<td class="mono">{e(_incident_text(s.get("last_incident")))}</td>'
            "</tr>"
        )
    body = "\n".join(rows)
    return (
        "<table><tr><th>service</th><th>state</th>"
        f"<th>uptime · {e(str(snap['window_hours']))}h</th>"
        f"<th>last check</th><th>last incident</th></tr>\n{body}\n</table>"
    )


def _certs_table(snap: dict[str, Any], e: Any) -> str:
    rows = []
    for c in snap["certs"]:
        days = c.get("days_to_expiry")
        reasons = ", ".join(str(r) for r in (c.get("reasons") or [])) or "—"
        rows.append(
            "<tr>"
            f'<td class="mono">{e(str(c["host"]))}</td>'
            f'<td><span class="pill s-{e(str(c.get("status")))}">'
            f"{e(str(c.get('status')))}</span></td>"
            f"<td>{'—' if days is None else e(f'{float(days):.1f} d')}"
            f'<div class="mono">{e(_iso(c.get("not_after")))}</div></td>'
            f'<td class="mono">{e(str(c.get("protocol") or "—"))}</td>'
            f'<td class="mono">{e(reasons)}</td>'
            "</tr>"
        )
    return (
        "<table><tr><th>host</th><th>cert</th><th>expires</th><th>protocol</th>"
        "<th>findings</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )


def _daemons_table(snap: dict[str, Any], e: Any) -> str:
    rows = []
    for d in snap["daemons"]:
        rows.append(
            "<tr>"
            f"<td><b>{e(str(d['daemon']))}</b>"
            f'<div class="mono">{e(str(d.get("note") or "—"))}</div></td>'
            f'<td><span class="pill s-{e(str(d.get("state")))}">'
            f"{e(str(d.get('state')))}</span></td>"
            f"<td>{e(_ago(d.get('age_s')))}"
            f'<div class="mono">{e(_iso(d.get("last_ts")))}</div></td>'
            f"<td>{d['beats']}</td>"
            "</tr>"
        )
    return (
        "<table><tr><th>daemon</th><th>ledger state</th><th>last beat</th>"
        "<th>beats</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )


def _sources_table(snap: dict[str, Any], e: Any) -> str:
    rows = []
    for name, _plugin, rank, table, _q in _SOURCE_SPECS:
        src = snap["sources"].get(name, {})
        seen = "yes" if src.get("present") else "no"
        rows.append(
            "<tr>"
            f'<td class="mono">{e(name)} {e(rank)}</td>'
            f'<td class="mono">{e(table)}</td>'
            f"<td>{seen}</td>"
            f"<td>{int(src.get('rows') or 0)}</td>"
            f'<td class="mono">{e(_iso(src.get("newest_ts")))}</td>'
            "</tr>"
        )
    return (
        "<table><tr><th>source</th><th>table</th><th>has data</th><th>rows</th>"
        "<th>newest</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )


def render_html(snap: dict[str, Any], *, title: str | None = None) -> str:
    """The hosted status page, deleted: one self-contained HTML file.

    Inline CSS, zero JavaScript, zero external assets — it works from file://,
    from a static host, or pasted into an email. Every dynamic string goes
    through html.escape (service names and ledger text are operator-supplied,
    and event messages carry deploy shas and error strings).

    The no-data contract is enforced here, not just documented: with no ledger
    (or no recorded services) the page prints an explicit block naming the
    missing file, and no availability figure is emitted anywhere.
    """
    e = html.escape
    heading = title or str(snap.get("title") or "Status")
    overall = str(snap.get("overall") or OVERALL_NO_DATA)
    src = snap.get("sources", {})
    ledger = src.get("ledger", {})
    ledger_path = str(ledger.get("path") or LEDGER_REL)
    parts: list[str] = [
        f"<h1>{e(heading)}</h1>",
        f'<div class="banner ov-{e(overall)}">{e(_OVERALL_TEXT.get(overall, overall))}'
        f"</div>",
        f'<p class="note">Generated {e(_iso(snap.get("generated_ts")))} · window '
        f"{e(str(snap.get('window_hours')))}h · read-only over "
        f'<span class="mono">{e(ledger_path)}</span>. This page collects nothing: '
        "every figure was recorded by uptime (#2), certmon (#9) or heartbeat (#6) "
        "and is read back with sqlite mode=ro.</p>",
    ]

    if not ledger.get("present"):
        parts.append(
            '<div class="nodata"><b>No monitoring ledger.</b> Nothing has been '
            f'recorded at <span class="mono">{e(ledger_path)}</span> on this box, so '
            "there is no uptime to report — this page shows no percentages rather "
            'than inventing them. Run <span class="mono">scout uptime check</span> '
            "to start collecting.</div>"
        )
    elif not snap.get("services"):
        parts.append(
            '<div class="nodata"><b>No service checks in the ledger.</b> The file at '
            f'<span class="mono">{e(ledger_path)}</span> exists but holds no probe '
            "observations, so no availability is reported.</div>"
        )
    else:
        counts = snap.get("counts", {})
        parts.append("<h2>Services</h2>")
        parts.append(_services_table(snap, e))
        if counts.get("stale"):
            parts.append(
                f'<p class="note flag">{int(counts["stale"])} row(s) are stale — '
                f"newest check older than {e(str(snap.get('stale_after_s')))}s. Those "
                "states describe the past, not right now.</p>"
            )

    parts.append("<h2>Certificates</h2>")
    if snap.get("certs"):
        parts.append(_certs_table(snap, e))
    else:
        parts.append(
            '<p class="note">No certificate observations in this ledger — '
            "certmon (#9) has not recorded here.</p>"
        )

    parts.append("<h2>Daemons</h2>")
    if snap.get("daemons"):
        parts.append(_daemons_table(snap, e))
        parts.append(
            '<p class="note">States are the ledger\'s own; grace periods live in '
            "heartbeat (#6) config and are not guessed here.</p>"
        )
    else:
        parts.append(
            '<p class="note">No heartbeats in this ledger — heartbeat (#6) has not '
            "recorded here.</p>"
        )

    parts.append("<h2>Recent activity</h2>")
    if snap.get("events"):
        items = "\n".join(
            f'<li><span class="pill s-{e(_EVENT_CLASS.get(str(ev.get("kind")), "info"))}">'
            f"{e(str(ev.get('kind')))}</span> {e(str(ev.get('message') or ''))}"
            f' <span class="mono">{e(_iso(ev.get("ts")))} · {e(_ago(ev.get("age_s")))}'
            f"{'' if ev.get('target') is None else ' · ' + e(str(ev['target']))}"
            "</span></li>"
            for ev in snap["events"]
        )
        parts.append(f"<ul>\n{items}\n</ul>")
    else:
        parts.append('<p class="note">No events on the timeline yet.</p>')

    parts.append("<h2>Where these numbers come from</h2>")
    parts.append(_sources_table(snap, e))
    parts.append(
        '<footer>Static page, generated by <span class="mono">scout statuspage '
        "render</span> (openswap #18 — StatusPage.io replaced by a file). No "
        "JavaScript, no external assets, no telemetry: nothing on this page ever "
        "left the box.</footer>"
    )
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(heading)}</title>
<style>{_CSS}</style></head>
<body>
{body}
</body></html>
"""
