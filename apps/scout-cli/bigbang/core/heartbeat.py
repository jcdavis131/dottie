# Solo personal project, no connection to employer, built with public/free-tier only
"""Heartbeat — dead-man's-switch registry core (openswap #6: Healthchecks.io/Cronitor).

Healthchecks pattern inverted to fully local: instead of daemons pinging a SaaS
that notices silence, daemons beat into the shared monitoring ledger (#2 uptime's
sqlite file — open_registry() wraps uptime.open_ledger(), adding one `beats`
table) or simply touch a file, and a watcher sweep compares last-beat
timestamps / file mtimes against per-daemon grace periods from JSON config.
Silence past grace opens an incident and writes an alert record. This attacks
the org's two documented failure modes directly: trainer "done" vs crash (the
container exits quietly when tokens run out) and watches dying with sessions.

Everything here is deterministic and offline: `now` and `ts` are injectable,
the only I/O is sqlite via the shared ledger plus os.stat mtime reads for
file-kind daemons. The optional loopback HTTP check-in socket lives in the
plugin CLI; route_request() here is the socket-free routing brain.

Substrate reuse (no parallel store): sweeps write observations into the #2
`checks` table and drive uptime.apply_state() with damping=1 — the grace
period IS the damping, so a confirmed transition is immediate — which manages
the shared `state` and `incidents` tables for free. Ledger keys are namespaced
"hb:<daemon>" so a daemon named like an uptime target can never clobber its
probe state. Status map: ok->up, late->degraded, stale->down; a configured
daemon that has never beaten stays out of the state machine entirely (visible
as "never"/unknown, no false incident on day one).

Extension points:
- Alert-router dispatch: sweep() records events kind="alert" (on ok/late ->
  stale transitions) and kind="recovery" (on the way back) in the shared
  events table; a router polls `uptime.recent_events(conn)` and fans out.
- Status-page liveness rows: board() is read-only (no state-machine writes)
  and returns the same shape family status pages consume; to_diagnostics()
  maps stale=error, late=warning, never=info onto the openswap schema so
  openswap.summarize() gates on heartbeats exactly like prose findings.
- Expected-cadence profiles: pure config — an `expected_interval_s` below
  `grace_s` in the daemons JSON yields the "late" early warning (Cronitor's
  schedule check) with zero code; DEFAULT_DAEMONS carries the org profiles
  (trainer, research loop, factory checkpointer, watch re-arm).
- HTTP check-ins: route_request() serves GET /beat/<daemon> for processes
  that prefer HTTP; the plugin binds it to loopback via http.server.
- File heartbeats: kind="file" daemons need no imports at all — any process
  that can `touch` a path participates; the sweep reads its mtime.
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any

from bigbang.core import openswap, uptime

STATUS_OK = "ok"
STATUS_LATE = "late"
STATUS_STALE = "stale"
STATUS_NEVER = "never"
STATUSES = (STATUS_OK, STATUS_LATE, STATUS_STALE, STATUS_NEVER)

# ledger-key namespace: keeps "hb:ollama" from clobbering uptime target "ollama"
# in the shared state/incidents/checks/events tables
NS = "hb:"

DEFAULT_GRACE_S = 3600.0
_DAEMON_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_STATE_OF = {
    STATUS_OK: uptime.STATE_UP,
    STATUS_LATE: uptime.STATE_DEGRADED,
    STATUS_STALE: uptime.STATE_DOWN,
}

# The org daemons: expected-cadence profiles as pure config (overlay via
# load_daemons). Grace periods are deliberately loose defaults — tighten per
# machine in a JSON overlay, don't tune code.
DEFAULT_DAEMONS: dict[str, dict[str, Any]] = {
    # trainer "done" vs crash: the container exits quietly when mini.yaml
    # tokens run out — a beat per logged step makes the silence visible
    "trainer": {"grace_s": 3600.0, "note": "training step loop"},
    "research-loop": {"grace_s": 7200.0, "note": "forever-daemon experiment cycle"},
    "factory-checkpointer": {"grace_s": 7200.0, "note": "checkpoint ratchet banking"},
    # watches die with sessions: beat when the TaskList watch is re-verified
    "watch-rearm": {"grace_s": 86400.0, "note": "session watch re-arm"},
}


def valid_daemon(name: str) -> bool:
    """Registry hygiene: names are lowercase [a-z0-9][a-z0-9._-]{0,63}."""
    return isinstance(name, str) and bool(_DAEMON_RE.match(name))


def load_daemons(path: str | None = None) -> dict[str, dict[str, Any]]:
    """DEFAULT_DAEMONS overlaid with an optional JSON file.

    Merge semantics mirror uptime.load_targets: dicts merge key-by-key, scalars
    replace, and a bare `false` (or {"enabled": false}) drops the daemon.
    kind is "beat" (registry row) or "file" (mtime of `path`); grace_s and the
    optional expected_interval_s are positive seconds. Raises ValueError /
    OSError / json errors for the CLI to convert into a fail_agent envelope.
    """
    daemons = copy.deepcopy(DEFAULT_DAEMONS)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("daemons file must be a JSON object of {name: config}")
        for name, cfg in raw.items():
            if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
                daemons.pop(name, None)
                continue
            if not isinstance(cfg, dict):
                raise ValueError(f"daemon {name!r}: config must be an object or false")
            daemons.setdefault(name, {}).update(cfg)
    for name, cfg in daemons.items():
        if not valid_daemon(name):
            raise ValueError(f"daemon name {name!r}: must match {_DAEMON_RE.pattern}")
        kind = cfg.setdefault("kind", "beat")
        if kind not in ("beat", "file"):
            raise ValueError(f"daemon {name!r}: kind must be 'beat' or 'file'")
        if kind == "file" and not (
            isinstance(cfg.get("path"), str) and cfg["path"].strip()
        ):
            raise ValueError(f"daemon {name!r}: kind 'file' needs a 'path'")
        for key in ("grace_s", "expected_interval_s"):
            v = cfg.get(key, DEFAULT_GRACE_S if key == "grace_s" else None)
            if key == "grace_s":
                cfg[key] = v
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise ValueError(f"daemon {name!r}: {key} must be positive seconds")
    return daemons


# ---- registry ---------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS beats(
    daemon TEXT PRIMARY KEY,
    first_ts REAL NOT NULL,
    last_ts REAL NOT NULL,
    count INTEGER NOT NULL,
    note TEXT
);
"""


def open_registry(path: str | Path):
    """The shared monitoring ledger (#2) plus the heartbeat `beats` table.

    Same sqlite file, same connection semantics — heartbeat state/incidents/
    events land in uptime's tables under NS-prefixed keys.
    """
    conn = uptime.open_ledger(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def beat(
    conn, daemon: str, *, ts: float | None = None, note: str | None = None
) -> dict[str, Any]:
    """The one-line check-in: upsert this daemon's registry row.

    Returns {daemon, ts, count, prev_ts, gap_s} — gap_s is the observed
    cadence, day-one signal even before any sweep runs. Raises ValueError on
    an invalid name (route_request depends on this to 400 junk paths).
    """
    if not valid_daemon(daemon):
        raise ValueError(f"invalid daemon name {daemon!r}")
    ts = time.time() if ts is None else float(ts)
    row = conn.execute(
        "SELECT last_ts, count FROM beats WHERE daemon = ?", (daemon,)
    ).fetchone()
    prev_ts = row["last_ts"] if row else None
    if row is None:
        conn.execute(
            "INSERT INTO beats(daemon, first_ts, last_ts, count, note)"
            " VALUES(?, ?, ?, 1, ?)",
            (daemon, ts, ts, note),
        )
        count = 1
    else:
        count = int(row["count"]) + 1
        conn.execute(
            "UPDATE beats SET last_ts = ?, count = ?, note = COALESCE(?, note)"
            " WHERE daemon = ?",
            (ts, count, note, daemon),
        )
    conn.commit()
    return {
        "daemon": daemon,
        "ts": ts,
        "count": count,
        "prev_ts": prev_ts,
        "gap_s": None if prev_ts is None else round(ts - prev_ts, 3),
    }


def last_beat(conn, daemon: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM beats WHERE daemon = ?", (daemon,)).fetchone()
    return dict(row) if row else None


def file_last_ts(path: str | Path) -> float | None:
    """mtime heartbeat for kind='file' daemons; None when the file is missing."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


# ---- staleness --------------------------------------------------------------


def status_of(
    now: float,
    last_ts: float | None,
    *,
    grace_s: float = DEFAULT_GRACE_S,
    expected_interval_s: float | None = None,
) -> dict[str, Any]:
    """Pure staleness verdict: never | ok | late | stale (+ age/overdue).

    stale is strictly past grace (age == grace still counts as alive); late is
    the early warning between an expected cadence and the grace cutoff. A
    future timestamp (clock skew, touched-ahead file) reads as age 0 — fresh.
    """
    if last_ts is None:
        return {"status": STATUS_NEVER, "age_s": None, "overdue_s": None}
    age = round(max(0.0, now - float(last_ts)), 3)
    if age > grace_s:
        return {
            "status": STATUS_STALE,
            "age_s": age,
            "overdue_s": round(age - grace_s, 3),
        }
    if expected_interval_s is not None and age > expected_interval_s:
        return {"status": STATUS_LATE, "age_s": age, "overdue_s": None}
    return {"status": STATUS_OK, "age_s": age, "overdue_s": None}


def _resolve_last_ts(conn, name: str, cfg: dict[str, Any]) -> float | None:
    if cfg.get("kind") == "file":
        return file_last_ts(cfg["path"])
    row = last_beat(conn, name)
    return row["last_ts"] if row else None


# ---- the watcher pass -------------------------------------------------------


def sweep(
    conn,
    daemons: dict[str, dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """One watcher pass: verdicts, shared state machine, alert records.

    Non-never verdicts are recorded as #2 `checks` rows (url "heartbeat:<name>",
    detail in `error`) and confirmed through uptime.apply_state with damping=1
    (grace already damps). Transitions to non-up write an "alert" event;
    transitions back to up write "recovery". never-daemons are reported but
    never enter the state machine.
    """
    now = time.time() if now is None else float(now)
    results: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for name, cfg in daemons.items():
        last_ts = _resolve_last_ts(conn, name, cfg)
        grace_s = float(cfg.get("grace_s", DEFAULT_GRACE_S))
        expected = cfg.get("expected_interval_s")
        verdict = status_of(
            now,
            last_ts,
            grace_s=grace_s,
            expected_interval_s=None if expected is None else float(expected),
        )
        status = verdict["status"]
        row: dict[str, Any] = {
            "daemon": name,
            "kind": cfg.get("kind", "beat"),
            "status": status,
            "last_ts": last_ts,
            "age_s": verdict["age_s"],
            "grace_s": grace_s,
            "overdue_s": verdict["overdue_s"],
            "state": "unknown",
            "changed": False,
            "incident": None,
        }
        if status != STATUS_NEVER:
            detail = None
            if status == STATUS_STALE:
                detail = f"stale: {verdict['age_s']}s since beat > grace {grace_s}s"
            elif status == STATUS_LATE:
                detail = f"late: {verdict['age_s']}s since beat > expected {expected}s"
            key = NS + name
            uptime.record_check(
                conn,
                target=key,
                url=f"heartbeat:{name}",
                ts=now,
                state=_STATE_OF[status],
                error=detail,
            )
            tr = uptime.apply_state(conn, key, ts=now, damping=1)
            row.update(
                state=tr["state"], changed=tr["changed"], incident=tr["incident"]
            )
            if tr["changed"] and tr["state"] != uptime.STATE_UP:
                message = f"{name} {status} — {detail}"
                uptime.record_event(
                    conn, kind="alert", message=message, target=key, ts=now
                )
                alerts.append({"daemon": name, "kind": "alert", "message": message})
            elif tr["changed"] and tr["prev"] is not None:
                # confirmed back up from a real prior state; prev=None is just
                # the first sweep of a healthy daemon — nothing recovered
                message = f"{name} recovered — beat {verdict['age_s']}s ago"
                uptime.record_event(
                    conn, kind="recovery", message=message, target=key, ts=now
                )
                alerts.append({"daemon": name, "kind": "recovery", "message": message})
        results.append(row)
    return {
        "ts": now,
        "results": results,
        "alerts": alerts,
        "transitions": [r for r in results if r["changed"]],
    }


# ---- reads: the status-page / alert-router contract -------------------------


def board(
    conn, daemons: dict[str, dict[str, Any]], *, now: float | None = None
) -> list[dict[str, Any]]:
    """Live verdict per configured daemon, read-only (no state-machine writes)."""
    now = time.time() if now is None else float(now)
    out = []
    for name, cfg in daemons.items():
        last_ts = _resolve_last_ts(conn, name, cfg)
        grace_s = float(cfg.get("grace_s", DEFAULT_GRACE_S))
        expected = cfg.get("expected_interval_s")
        verdict = status_of(
            now,
            last_ts,
            grace_s=grace_s,
            expected_interval_s=None if expected is None else float(expected),
        )
        key = NS + name
        st = conn.execute(
            "SELECT state, since FROM state WHERE target = ?", (key,)
        ).fetchone()
        open_inc = conn.execute(
            "SELECT id, state, opened_ts FROM incidents"
            " WHERE target = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1",
            (key,),
        ).fetchone()
        reg = last_beat(conn, name)
        out.append(
            {
                "daemon": name,
                "kind": cfg.get("kind", "beat"),
                "note": cfg.get("note"),
                "status": verdict["status"],
                "last_ts": last_ts,
                "age_s": verdict["age_s"],
                "grace_s": grace_s,
                "overdue_s": verdict["overdue_s"],
                "beats": None if reg is None else int(reg["count"]),
                "state": st["state"] if st else "unknown",
                "since": st["since"] if st else None,
                "open_incident": dict(open_inc) if open_inc else None,
            }
        )
    return out


_SEVERITY_OF = {STATUS_STALE: "error", STATUS_LATE: "warning", STATUS_NEVER: "info"}


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map non-ok verdicts onto the family diagnostic schema.

    stale=error, late=warning, never=info; ok daemons emit nothing. This is
    what lets openswap.summarize() and --fail-stale gates treat dead daemons
    exactly like prose findings.
    """
    diags = []
    for r in results:
        sev = _SEVERITY_OF.get(r.get("status"))
        if sev is None:
            continue
        if r["status"] == STATUS_NEVER:
            detail = "no beat ever recorded"
        else:
            detail = f"last beat {r.get('age_s')}s ago (grace {r.get('grace_s')}s)"
        diags.append(
            openswap.diagnostic(
                path=f"heartbeat:{r['daemon']}",
                line=0,
                col=0,
                rule=f"heartbeat:{r['status']}",
                severity=sev,
                message=f"{r['daemon']} {r['status']} — {detail}",
            )
        )
    return openswap.sort_diagnostics(diags)


# ---- HTTP check-in routing (socket-free; the plugin owns the socket) --------


def parse_beat_path(path: str) -> str | None:
    """'/beat/<daemon>' -> daemon (query string ignored); None otherwise."""
    path = path.split("?", 1)[0]
    if not path.startswith("/beat/"):
        return None
    name = path[len("/beat/") :]
    return name if valid_daemon(name) else None


def route_request(conn, path: str, *, now: float | None = None) -> tuple[int, dict]:
    """(http_status, json_payload) for the loopback ping endpoint.

    GET /beat/<daemon> records a beat; / reports the registry pulse. Junk
    daemon names 400 rather than polluting the registry.
    """
    bare = path.split("?", 1)[0]
    if bare in ("/", "/status"):
        n = conn.execute("SELECT COUNT(*) AS n FROM beats").fetchone()["n"]
        return 200, {"ok": True, "service": "heartbeat", "daemons_seen": int(n)}
    if bare.startswith("/beat/"):
        name = parse_beat_path(path)
        if name is None:
            return 400, {
                "ok": False,
                "error": f"invalid daemon name in {bare!r}",
                "example": "/beat/trainer",
            }
        b = beat(conn, name, ts=now)
        return 200, {"ok": True, **b}
    return 404, {
        "ok": False,
        "error": f"unknown path {bare!r}",
        "example": "/beat/<daemon>",
    }
