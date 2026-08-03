# Solo personal project, no connection to employer, built with public/free-tier only
"""Uptime — sqlite ledger + incident state machine core (openswap #2: UptimeRobot).

Uptime Kuma pattern in pure stdlib: this module owns everything deterministic —
target config, observation classification, the flap-damped incident state
machine, and the sqlite3 ledger (checks / state / incidents / events). Real I/O
stays out: the `uptime` plugin CLI supplies the http.client/ssl probe and
injects it into run_pass() as a callable (bigbang/core/reach.py +
plugins/reach/cli.py is the pattern), so the whole pipeline is unit-testable
fully offline.

The ledger schema is the shared substrate for the rest of the monitoring
family — heartbeat (#6), cert monitor (#9), status page and alert router reuse
open_ledger()/record_event() and read the same tables instead of inventing
parallel stores.

Extension points:
- Expected-string content checks: `expect` in a target config is a substring
  the probe body must contain; a 2xx page missing it classifies degraded
  (serving, but not the content we deployed).
- Latency percentile rollups: rollup() emits p50/p95/p99/avg/max over any
  window — feed it to status pages or steer digests.
- Deploy markers: record_event(conn, kind="deploy", ...) from the smoke
  harness puts deploys on the same timeline as incidents; recent_events()
  merges per-target and global events.
- Alert-router/status-page hooks: board(), list_incidents(), rollup() and the
  events table are the read contract; downstream adapters consume the same
  sqlite file (default .scout/uptime.db, the reviewgraph location convention).
- Family gate: to_diagnostics() maps confirmed states onto the openswap
  diagnostic schema (down=error, degraded=warning), so openswap.summarize()
  treats uptime results exactly like prose lint findings.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable

STATE_UP = "up"
STATE_DEGRADED = "degraded"
STATE_DOWN = "down"
STATES = (STATE_UP, STATE_DEGRADED, STATE_DOWN)
_STATE_RANK = {s: i for i, s in enumerate(STATES)}

DEFAULT_DEGRADED_MS = 3000.0
DEFAULT_DAMPING = 2
DB_REL = Path(".scout") / "uptime.db"
SCHEMA_VERSION = "1"

# The org fleet: the same 8-site list as ava-factory scripts/publish_live_status.py
# SITES (the twin feed's source of truth), plus the bluehenre API and the local
# ollama endpoint. Targets are policy-as-config: load_targets() overlays a JSON
# file, and every host here must also appear in the plugin manifest's network
# domain allowlist (default-deny) before a probe is allowed.
DEFAULT_TARGETS: dict[str, dict[str, Any]] = {
    "hub": {"url": "https://dumbmodel.com"},
    "hoops": {"url": "https://hoops.jcamd.com"},
    "grid": {"url": "https://gridiron.dumbmodel.com"},
    "pitch": {"url": "https://pitch.jcamd.com"},
    "equi": {"url": "https://equities.jcamd.com"},
    "arcad": {"url": "https://arcade.dumbmodel.com"},
    "arxiv": {"url": "https://arxiviq.com"},
    "bhenre": {"url": "https://www.bhenre.com"},
    "bluehenre-api": {"url": "https://bluehenre-campus.vercel.app/api/twin-status"},
    # local model server answers on loopback in ~ms — a slow answer is real news
    "ollama": {"url": "http://127.0.0.1:11434/api/version", "degraded_ms": 1000.0},
}


def load_targets(path: str | None = None) -> dict[str, dict[str, Any]]:
    """DEFAULT_TARGETS overlaid with an optional JSON file.

    Merge semantics mirror prose.load_rules: dicts merge key-by-key, scalars
    replace, and a bare `false` (or {"enabled": false}) drops the target. New
    targets must carry an http(s) `url`. Raises ValueError / OSError / json
    errors for the CLI to convert into a fail_agent envelope.
    """
    targets = copy.deepcopy(DEFAULT_TARGETS)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("targets file must be a JSON object of {name: config}")
        for name, cfg in raw.items():
            if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
                targets.pop(name, None)
                continue
            if not isinstance(cfg, dict):
                raise ValueError(f"target {name!r}: config must be an object or false")
            targets.setdefault(name, {}).update(cfg)
    for name, cfg in targets.items():
        url = cfg.get("url")
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
            raise ValueError(f"target {name!r}: needs an http(s) url, got {url!r}")
    return targets


def classify(
    http_status: int | None,
    latency_ms: float | None,
    *,
    expect_ok: bool | None = None,
    degraded_ms: float = DEFAULT_DEGRADED_MS,
) -> str:
    """One observation -> up | degraded | down (pre-damping).

    <400 counts as serving (a redirect proves liveness; probes don't follow
    them); >=400 or no answer at all is down. A 2xx that misses its expected
    string or exceeds the latency budget is degraded — alive, but not the
    experience we deployed.
    """
    if http_status is None or http_status >= 400:
        return STATE_DOWN
    if expect_ok is False:
        return STATE_DEGRADED
    if latency_ms is not None and latency_ms > degraded_ms:
        return STATE_DEGRADED
    return STATE_UP


def damped_state(prev: str | None, recent: list[str], damping: int) -> str | None:
    """Confirmed state after flap damping (recent is most-recent-last).

    A transition needs `damping` consecutive identical observations; a lone
    blip (or an alternating flap) never moves the confirmed state. The very
    first observation confirms immediately — a monitor that reports nothing
    until its damping window fills is useless on day one.
    """
    if not recent:
        return prev
    if prev is None:
        return recent[-1]
    if len(recent) < damping:
        return prev
    window = recent[-damping:]
    cand = window[-1]
    if cand != prev and all(s == cand for s in window):
        return cand
    return prev


# ---- ledger -----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks(
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    url TEXT NOT NULL,
    ts REAL NOT NULL,
    state TEXT NOT NULL,
    http INTEGER,
    latency_ms REAL,
    error TEXT,
    expect_ok INTEGER
);
CREATE INDEX IF NOT EXISTS idx_checks_target_ts ON checks(target, ts);
CREATE TABLE IF NOT EXISTS state(
    target TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    since REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents(
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    state TEXT NOT NULL,
    opened_ts REAL NOT NULL,
    closed_ts REAL
);
CREATE INDEX IF NOT EXISTS idx_incidents_target ON incidents(target, opened_ts);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    target TEXT,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_ledger(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the shared monitoring ledger.

    `checks` are raw observations; `state` is the damped verdict per target;
    `incidents` are confirmed non-up spans; `events` is the shared timeline
    (deploy markers, ops notes) the whole monitoring family writes to.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_check(
    conn: sqlite3.Connection,
    *,
    target: str,
    url: str,
    ts: float,
    state: str,
    http: int | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
    expect_ok: bool | None = None,
) -> int:
    """Append one raw observation; returns the check row id."""
    cur = conn.execute(
        "INSERT INTO checks(target, url, ts, state, http, latency_ms, error, expect_ok)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            target,
            url,
            ts,
            state,
            http,
            latency_ms,
            error,
            None if expect_ok is None else int(expect_ok),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def apply_state(
    conn: sqlite3.Connection, target: str, *, ts: float, damping: int = DEFAULT_DAMPING
) -> dict[str, Any]:
    """Damp the latest observations into a confirmed state; manage incidents.

    Returns {target, state, prev, changed, incident} where incident is None or
    {"opened": id} / {"closed": id, "duration_s": s}. One incident spans a
    whole non-up period; if it worsens (degraded -> down) the open incident
    escalates in place rather than double-counting.
    """
    row = conn.execute(
        "SELECT state, since FROM state WHERE target = ?", (target,)
    ).fetchone()
    prev = row["state"] if row else None
    raw = [
        r["state"]
        for r in conn.execute(
            "SELECT state FROM checks WHERE target = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (target, max(damping, 1)),
        )
    ][::-1]
    new = damped_state(prev, raw, damping)
    out: dict[str, Any] = {
        "target": target,
        "state": new,
        "prev": prev,
        "changed": new != prev,
        "incident": None,
    }
    if new is None:
        return out
    if row is None:
        conn.execute(
            "INSERT INTO state(target, state, since, updated) VALUES(?, ?, ?, ?)",
            (target, new, ts, ts),
        )
    elif new != prev:
        conn.execute(
            "UPDATE state SET state = ?, since = ?, updated = ? WHERE target = ?",
            (new, ts, ts, target),
        )
    else:
        conn.execute("UPDATE state SET updated = ? WHERE target = ?", (ts, target))
    open_inc = conn.execute(
        "SELECT id, state, opened_ts FROM incidents"
        " WHERE target = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1",
        (target,),
    ).fetchone()
    if new == STATE_UP:
        if open_inc is not None:
            conn.execute(
                "UPDATE incidents SET closed_ts = ? WHERE id = ?", (ts, open_inc["id"])
            )
            out["incident"] = {
                "closed": int(open_inc["id"]),
                "duration_s": round(ts - open_inc["opened_ts"], 3),
            }
    elif open_inc is None:
        cur = conn.execute(
            "INSERT INTO incidents(target, state, opened_ts) VALUES(?, ?, ?)",
            (target, new, ts),
        )
        out["incident"] = {"opened": int(cur.lastrowid)}
    elif _STATE_RANK[new] > _STATE_RANK[open_inc["state"]]:
        # one incident per outage; the row records the worst state it reached
        conn.execute(
            "UPDATE incidents SET state = ? WHERE id = ?", (new, open_inc["id"])
        )
    conn.commit()
    return out


def run_pass(
    conn: sqlite3.Connection,
    targets: dict[str, dict[str, Any]],
    probe: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    ts: float | None = None,
    damping: int = DEFAULT_DAMPING,
) -> dict[str, Any]:
    """One monitoring pass: probe every target, record, damp, return results.

    `probe(url, cfg)` must return {"http": int|None, "latency_ms": float|None,
    "error": str|None, "body_head": str} — the CLI injects the real
    http.client/ssl probe; tests inject fakes (the offline invariant).
    """
    ts = time.time() if ts is None else ts
    results: list[dict[str, Any]] = []
    for name, cfg in targets.items():
        r = probe(cfg["url"], cfg)
        expect = cfg.get("expect")
        expect_ok = None if not expect else expect in (r.get("body_head") or "")
        raw = classify(
            r.get("http"),
            r.get("latency_ms"),
            expect_ok=expect_ok,
            degraded_ms=float(cfg.get("degraded_ms", DEFAULT_DEGRADED_MS)),
        )
        record_check(
            conn,
            target=name,
            url=cfg["url"],
            ts=ts,
            state=raw,
            http=r.get("http"),
            latency_ms=r.get("latency_ms"),
            error=r.get("error"),
            expect_ok=expect_ok,
        )
        tr = apply_state(conn, name, ts=ts, damping=damping)
        results.append(
            {
                "target": name,
                "url": cfg["url"],
                "observed": raw,
                "confirmed": tr["state"],
                "changed": tr["changed"],
                "incident": tr["incident"],
                "http": r.get("http"),
                "latency_ms": r.get("latency_ms"),
                "error": r.get("error"),
                "expect_ok": expect_ok,
            }
        )
    return {
        "ts": ts,
        "results": results,
        "transitions": [x for x in results if x["changed"]],
    }


# ---- reads: the status-page / alert-router contract -------------------------


def record_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    message: str,
    target: str | None = None,
    ts: float | None = None,
) -> int:
    """Drop a marker (deploy, ops note) on the shared monitoring timeline."""
    cur = conn.execute(
        "INSERT INTO events(ts, kind, target, message) VALUES(?, ?, ?, ?)",
        (time.time() if ts is None else ts, kind, target, message),
    )
    conn.commit()
    return int(cur.lastrowid)


def recent_events(
    conn: sqlite3.Connection, *, target: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first events; a target filter still includes global (NULL) rows."""
    rows = conn.execute(
        "SELECT * FROM events WHERE (? IS NULL OR target IS NULL OR target = ?)"
        " ORDER BY ts DESC, id DESC LIMIT ?",
        (target, target, limit),
    )
    return [dict(r) for r in rows]


def recent_checks(
    conn: sqlite3.Connection, target: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first raw observations for one target."""
    rows = conn.execute(
        "SELECT * FROM checks WHERE target = ? ORDER BY ts DESC, id DESC LIMIT ?",
        (target, limit),
    )
    return [dict(r) for r in rows]


def list_incidents(
    conn: sqlite3.Connection,
    *,
    target: str | None = None,
    open_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Incidents newest-first, each with duration_s (None while still open)."""
    rows = conn.execute(
        "SELECT * FROM incidents WHERE (? IS NULL OR target = ?)"
        " AND (? = 0 OR closed_ts IS NULL)"
        " ORDER BY opened_ts DESC, id DESC LIMIT ?",
        (target, target, int(open_only), limit),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["duration_s"] = (
            None
            if d["closed_ts"] is None
            else round(d["closed_ts"] - d["opened_ts"], 3)
        )
        out.append(d)
    return out


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (deterministic); None when there is no data."""
    if not values:
        return None
    vs = sorted(values)
    k = max(1, ceil((p / 100.0) * len(vs)))
    return vs[min(k, len(vs)) - 1]


def rollup(
    conn: sqlite3.Connection, target: str, *, since: float | None = None
) -> dict[str, Any]:
    """Availability + latency percentiles for one target over a window.

    up_pct counts raw observations (pre-damping) so a flappy target scores
    honestly; latencies come from answered probes only (http NOT NULL).

    `latency.n` IS THE SAMPLE SIZE THE PERCENTILES CAME FROM, and it is not
    `checks`. A probe that times out records no latency, so failures drop out of
    the distribution entirely — which means latency looks BEST exactly when a
    target is most broken. Measured on a synthetic window of 98 timeouts and 2
    fast successes:

        checks 100   up_pct 2.0   latency p50/p95/p99/avg/max all 12.0 ms

    Every one of those percentiles came from 2 samples, and before `n` existed
    nothing in the payload said so — while statuspage.services() publishes
    `checks` and `latency` side by side on the page. That row read "100 checks,
    p99 12 ms" for a service that was down 98% of the window.

    The percentiles are not wrong; they answer "how fast were the responses we
    got", not "how fast was this target". `n` is what lets a reader tell the two
    apart, and it is the same discipline statuspage already applies to
    availability, where an empty window prints an em dash rather than a
    fabricated 100%.
    """
    rows = conn.execute(
        "SELECT state, http, latency_ms FROM checks WHERE target = ? AND ts >= ?",
        (target, 0.0 if since is None else since),
    ).fetchall()
    total = len(rows)
    lat = [
        float(r["latency_ms"])
        for r in rows
        if r["http"] is not None and r["latency_ms"] is not None
    ]
    up = sum(1 for r in rows if r["state"] == STATE_UP)
    return {
        "target": target,
        "checks": total,
        "up_pct": None if total == 0 else round(100.0 * up / total, 2),
        "latency": {
            # answered probes only — see the docstring; this is NOT `checks`
            "n": len(lat),
            "p50": percentile(lat, 50),
            "p95": percentile(lat, 95),
            "p99": percentile(lat, 99),
            "avg": None if not lat else round(sum(lat) / len(lat), 1),
            "max": None if not lat else max(lat),
        },
    }


def board(
    conn: sqlite3.Connection, targets: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Current confirmed state per configured target (the status-page contract)."""
    out = []
    for name, cfg in targets.items():
        st = conn.execute(
            "SELECT state, since, updated FROM state WHERE target = ?", (name,)
        ).fetchone()
        last = conn.execute(
            "SELECT ts, state, http, latency_ms, error FROM checks"
            " WHERE target = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (name,),
        ).fetchone()
        open_inc = conn.execute(
            "SELECT id, state, opened_ts FROM incidents"
            " WHERE target = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1",
            (name,),
        ).fetchone()
        out.append(
            {
                "target": name,
                "url": cfg.get("url"),
                "state": st["state"] if st else "unknown",
                "since": st["since"] if st else None,
                "last_check": dict(last) if last else None,
                "open_incident": dict(open_inc) if open_inc else None,
            }
        )
    return out


_SEVERITY_OF = {STATE_DOWN: "error", STATE_DEGRADED: "warning"}


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map non-up confirmed states onto the family diagnostic schema.

    down=error, degraded=warning; up targets emit nothing. line/col carry no
    meaning for a URL and stay 0. This is what lets openswap.summarize() and
    fail-style gates treat uptime results exactly like prose findings.
    """
    diags = []
    for r in results:
        sev = _SEVERITY_OF.get(r.get("confirmed"))
        if sev is None:
            continue
        if r.get("expect_ok") is False:
            detail = "expected content missing"
        elif r.get("error"):
            detail = r["error"]
        elif r.get("http") is not None:
            detail = f"http {r['http']} in {r.get('latency_ms')}ms"
        else:
            detail = "no answer"
        diags.append(
            openswap.diagnostic(
                path=r.get("url") or r["target"],
                line=0,
                col=0,
                rule=f"uptime:{r['confirmed']}",
                severity=sev,
                message=f"{r['target']} {r['confirmed']} — {detail}",
            )
        )
    return openswap.sort_diagnostics(diags)
