# Solo personal project, no connection to employer, built with public/free-tier only
"""Alerts — alert routing core (openswap #19: PagerDuty / Opsgenie).

The paid enemy is a hosted router: you already own the monitoring, you pay a
SaaS to look at it and decide who gets woken up. That decision is pure logic
over data this box already has, so it moves here. uptime (#2) writes the
`incidents` state machine, heartbeat (#6) writes kind="alert"/"recovery"
events, certmon (#9) writes kind="cert" events — all into ONE sqlite ledger.
This module reads that ledger, applies severity rules from JSON config, damps
repeats with per-rule dedup windows, and hands the survivors to an injected
`dispatch` callable. The only real I/O (smtplib, urllib) lives in the plugin
CLI, exactly like uptime's probe and certmon's handshake, so the whole routing
brain is unit-testable with no socket in sight.

The invariant that shapes everything here: A ROUTER'S FAILURE MODE IS SILENCE,
so silence is never allowed to look like health.
- Out of the box the channels carry NO endpoint, and that is deliberate: a
  first `route` reports every alert `failed` with "channel not configured"
  and raises `alerts:undeliverable`. A default that quietly recorded pages to
  sqlite and notified nobody would be indistinguishable from a working router.
- A failed dispatch does NOT start the dedup clock (only sent/partial/recorded
  do), so a broken SMTP retries next pass instead of being suppressed for the
  window. `DEDUP_STATUSES` is that rule, in one place.
- A dry run writes NOTHING — no ledger row, no dispatch — so a rehearsal can
  never silence the real page that follows it.
- A ledger signal with no matching rule is reported as `unrouted` (an info
  diagnostic), not dropped. Kinds that must NOT page (deploy markers, ops
  notes) are declared with `route: false`: known-and-ignored is a config
  statement, never an accident of an empty ruleset.

Dedup is fingerprinted on (target, severity) and NOT on the message text. This
is the bug that makes naive routers useless: heartbeat's alert message embeds
the current age ("trainer stale — 612.0s since beat"), so a message-keyed
fingerprint changes every sweep and dedup never fires. Fingerprinting the pair
also collapses the DOUBLE page heartbeat would otherwise cause — one confirmed
stale daemon writes both an `alert` event and an open `incident` — into a
single page whose `also` list carries the other signals.

`dedup_s` does double duty on purpose: it suppresses flapping AND it is the
re-notify cadence, because an incident that is still open when the window
lapses fires again. That nag is most of what a pager subscription buys.

Deliberately out of scope (scope honesty, not an oversight): on-call rotations,
escalation chains and acknowledgements. Those exist to route around humans who
are asleep or unavailable — this box has one operator, and a rotation of one is
a cron job. Suppression windows and the alert ledger cover the rest.

Substrate reuse (no parallel store): open_alert_ledger() wraps
uptime.open_ledger() and adds ONE idempotent `alerts` table. This module never
writes uptime's tables — notably not `events`. A router that logged its own
notifications onto the timeline it reads would alert on its own alerts; the
loop is closed by not writing there at all, rather than by hoping no rule
matches.

Extension points:
- Rules and channels are pure config: load_config() overlays a JSON file onto
  DEFAULT_RULES/DEFAULT_CHANNELS with the family's merge semantics (dicts merge
  key-by-key, `false` drops an entry), so severities, channel fan-out and
  windows are tuned per box without touching code.
- New channel kinds: add the kind to CHANNEL_KINDS plus a sender in the plugin's
  _SENDERS map — the test that asserts those two sets are equal is what keeps a
  half-added kind from silently dropping pages.
- Any signal source: candidates() reads incidents + events. A new producer that
  writes kind="<x>" events on the shared timeline is routable by adding an
  `event:<x>` rule — no code change.
- Family gate: to_diagnostics() maps the pass onto the openswap schema
  (fired=the alert's own severity, undeliverable=error, unrouted=info) so
  openswap.summarize() and `--fail-on` treat a routing pass exactly like prose
  findings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap, uptime

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

# the SHARED monitoring ledger (#2) — owned by uptime, extended with one table
LEDGER_REL = uptime.DB_REL

SIGNAL_INCIDENT = "incident"
SIGNAL_EVENT = "event"

STATUS_SENT = "sent"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_RECORDED = "recorded"  # a rule with channels: [] — ledger only, by config
STATUS_SUPPRESSED = "suppressed"
STATUS_DRY_RUN = "dry-run"

# Which outcomes start the dedup clock. `failed` is absent on purpose so a
# broken channel retries next pass; `partial` is present because re-paging the
# channel that DID work is worse than losing a retry on the one that did not
# (the failure is still in the ledger and in the diagnostics).
DEDUP_STATUSES = (STATUS_SENT, STATUS_PARTIAL, STATUS_RECORDED)

CHANNEL_KINDS = ("email", "webhook")

DEFAULT_LOOKBACK_S = 3600.0
DEFAULT_DEDUP_S = 1800.0
DEFAULT_TIMEOUT_S = 10.0

# Read cap per source per pass. 200 simultaneously-open incidents (or 200 events
# inside one lookback window) is already a catastrophe, and paging on the newest
# 200 of them beats an unbounded read of a ledger that has been collecting for a
# year — the cap is stated here rather than hidden in a call.
_READ_LIMIT = 200

# Severity + fan-out + window per ledger signal. Policy-as-config: overlay a
# JSON file, don't tune code. Channels are NAMED here even though they ship
# unconfigured — see the module docstring on why an undeliverable default is
# the honest one.
DEFAULT_RULES: dict[str, dict[str, Any]] = {
    # an OPEN incident is the page-worthy signal; #2's state machine already
    # damped the flap, and dedup_s below is the re-notify cadence
    "incident:down": {
        "severity": "error",
        "channels": ["webhook", "email"],
        "dedup_s": 1800.0,
    },
    "incident:degraded": {
        "severity": "warning",
        "channels": ["webhook"],
        "dedup_s": 3600.0,
    },
    # heartbeat (#6) writes kind="alert" when a daemon goes confirmed-stale
    "event:alert": {
        "severity": "error",
        "channels": ["webhook", "email"],
        "dedup_s": 1800.0,
    },
    # certmon (#9) writes kind="cert" for every non-ok cert observation. Certs
    # are read through those events rather than through a second pass over the
    # `certs` table — two reads of one problem is two pages.
    "event:cert": {"severity": "warning", "channels": ["email"], "dedup_s": 86400.0},
    "event:recovery": {"severity": "info", "channels": ["webhook"], "dedup_s": 900.0},
    # known and deliberately never paged: deploy markers and ops notes belong on
    # the timeline the status page renders, not on a pager at 3am
    "event:deploy": {"route": False},
    "event:note": {"route": False},
}

DEFAULT_CHANNELS: dict[str, dict[str, Any]] = {
    "webhook": {"kind": "webhook", "url": None, "timeout_s": DEFAULT_TIMEOUT_S},
    "email": {
        "kind": "email",
        "host": None,
        "port": 25,
        "from": None,
        "to": [],
        "starttls": False,
        "user": None,
        # env var holding the SMTP password; it must ALSO be named in the
        # plugin manifest's secrets allowlist (default-deny) to be read
        "password_env": None,
        "timeout_s": DEFAULT_TIMEOUT_S,
    },
}


# ---- config -----------------------------------------------------------------


def _merge(dst: dict[str, Any], src: Any, label: str) -> None:
    """Family merge semantics: dicts merge key-by-key, `false` drops an entry."""
    if not isinstance(src, dict):
        raise ValueError(f"config '{label}s' section must be a JSON object")
    for name, cfg in src.items():
        if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
            dst.pop(name, None)
            continue
        if not isinstance(cfg, dict):
            raise ValueError(f"{label} {name!r}: config must be an object or false")
        dst.setdefault(name, {}).update(cfg)


def _positive(cfg: dict[str, Any], key: str, label: str, default: float) -> float:
    v = cfg.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise ValueError(f"{label}: {key} must be positive seconds, got {v!r}")
    cfg[key] = float(v)
    return float(v)


def _validate_rule(rid: str, cfg: dict[str, Any], channels: dict[str, Any]) -> None:
    cfg["route"] = bool(cfg.get("route", True))
    if not cfg["route"]:
        return  # known-and-ignored: nothing else to check, nothing will be sent
    sev = cfg.setdefault("severity", "warning")
    if sev not in openswap.SEVERITIES:
        raise ValueError(
            f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)},"
            f" got {sev!r}"
        )
    names = cfg.setdefault("channels", [])
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise ValueError(f"rule {rid!r}: channels must be a list of channel names")
    for n in names:
        # a rule aimed at a channel that does not exist would drop pages in
        # silence, so it is a hard config error rather than a runtime shrug
        if n not in channels:
            raise ValueError(
                f"rule {rid!r}: unknown channel {n!r} (have {sorted(channels)}) —"
                " define it under 'channels' or drop it from this rule"
            )
    _positive(cfg, "dedup_s", f"rule {rid!r}", DEFAULT_DEDUP_S)


def _validate_channel(name: str, cfg: dict[str, Any]) -> None:
    kind = cfg.get("kind")
    if kind not in CHANNEL_KINDS:
        raise ValueError(
            f"channel {name!r}: kind must be one of {'|'.join(CHANNEL_KINDS)},"
            f" got {kind!r}"
        )
    _positive(cfg, "timeout_s", f"channel {name!r}", DEFAULT_TIMEOUT_S)
    if kind == "webhook":
        url = cfg.get("url")
        # http(s) only, checked HERE so the sender never has to defend against a
        # file:/// or gopher:// "webhook" (same guard as uptime.load_targets)
        if url is not None and not (
            isinstance(url, str) and url.startswith(("http://", "https://"))
        ):
            raise ValueError(f"channel {name!r}: url must be http(s), got {url!r}")
    if kind == "email":
        to = cfg.setdefault("to", [])
        if not isinstance(to, list) or any(not isinstance(a, str) for a in to):
            raise ValueError(f"channel {name!r}: 'to' must be a list of addresses")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """DEFAULT_RULES/DEFAULT_CHANNELS overlaid with an optional JSON file.

    Shape: {"rules": {id: {...}}, "channels": {name: {...}}}. Merge semantics
    mirror uptime.load_targets / heartbeat.load_daemons — dicts merge key-by-key,
    scalars replace, a bare `false` (or {"enabled": false}) drops the entry.
    Raises ValueError / OSError / json errors for the CLI to convert into a
    fail_agent envelope; an unknown top-level section is an error rather than a
    silently ignored typo that would leave the operator's rules unapplied.
    """
    cfg: dict[str, Any] = {
        "rules": copy.deepcopy(DEFAULT_RULES),
        "channels": copy.deepcopy(DEFAULT_CHANNELS),
    }
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("alerts config must be a JSON object")
        unknown = sorted(set(raw) - {"rules", "channels"})
        if unknown:
            raise ValueError(
                f"unknown config section(s) {unknown} — expected 'rules'/'channels'"
            )
        _merge(cfg["channels"], raw.get("channels", {}), "channel")
        _merge(cfg["rules"], raw.get("rules", {}), "rule")
    for name, ch in cfg["channels"].items():
        _validate_channel(name, ch)
    for rid, rule in cfg["rules"].items():
        _validate_rule(rid, rule, cfg["channels"])
    return cfg


def channel_ready(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Is this channel actually deliverable? (unconfigured is a FAILURE, not a skip)"""
    kind = cfg.get("kind")
    if kind == "webhook":
        if not cfg.get("url"):
            return False, "channel not configured: webhook has no url"
        return True, "ok"
    missing = [k for k in ("host", "from") if not cfg.get(k)]
    if not cfg.get("to"):
        missing.append("to")
    if missing:
        return False, f"channel not configured: email missing {missing}"
    return True, "ok"


# ---- ledger -----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    fingerprint TEXT NOT NULL,
    rule TEXT NOT NULL,
    signal TEXT NOT NULL,
    severity TEXT NOT NULL,
    target TEXT,
    message TEXT NOT NULL,
    channels TEXT NOT NULL,
    status TEXT NOT NULL,
    delivered INTEGER NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint_ts ON alerts(fingerprint, ts);
"""


def open_alert_ledger(path: str | Path) -> sqlite3.Connection:
    """The shared monitoring ledger (#2) plus the router's own `alerts` table.

    One extra table, created idempotently; uptime's tables are read, never
    written. The `alerts` table is the DELIVERY record — only dispatched
    outcomes land there. Suppressed passes are deliberately not rows: the
    decision is derivable from the last delivery plus `dedup_s`, and logging one
    row per cron tick would multiply the ledger by the cron cadence.
    """
    conn = uptime.open_ledger(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def fingerprint(target: str | None, severity: str) -> str:
    """The dedup key: (target, severity). Deliberately NOT the message.

    heartbeat's alert text embeds the current age of the silence, so a
    message-keyed fingerprint would change on every sweep and dedup would never
    fire once — the exact failure that makes a flapping check spam. Pairing
    target with severity also collapses the two signals one confirmed-stale
    daemon produces (an `alert` event AND an open `incident`) into a single
    page, while leaving a recovery (info) free to notify immediately.
    """
    raw = f"{target if target is not None else '*'}|{severity}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def record_alert(conn: sqlite3.Connection, alert: dict[str, Any], *, ts: float) -> int:
    """Append one delivery record; returns the row id.

    `delivered` materializes the DEDUP_STATUSES predicate at WRITE time, which is
    what lets last_dispatch_ts() stay a single static, indexable query instead of
    an interpolated IN-list (statuspage's auditable-SQL rule). Historical rows
    keep the verdict they were written with, which is the honest behaviour if the
    tuple is ever tuned.
    """
    detail = json.dumps(
        {"channels": alert.get("results") or {}, "also": alert.get("also") or []},
        default=str,
    )
    cur = conn.execute(
        "INSERT INTO alerts(ts, fingerprint, rule, signal, severity, target, message,"
        " channels, status, delivered, detail)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ts,
            alert["fingerprint"],
            alert["rule"],
            alert["signal"],
            alert["severity"],
            alert.get("target"),
            alert["message"],
            json.dumps(alert.get("channels") or []),
            alert["status"],
            int(alert["status"] in DEDUP_STATUSES),
            detail,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def last_dispatch_ts(conn: sqlite3.Connection, fp: str) -> float | None:
    """When this fingerprint was last actually DELIVERED (see DEDUP_STATUSES)."""
    row = conn.execute(
        "SELECT MAX(ts) AS ts FROM alerts WHERE fingerprint = ? AND delivered = 1",
        (fp,),
    ).fetchone()
    return None if row is None or row["ts"] is None else float(row["ts"])


def suppressed(now: float, last_ts: float | None, dedup_s: float) -> bool:
    """Inside the dedup window? A never-delivered fingerprint is never suppressed.

    The window is inclusive of its own edge (age == dedup_s still suppresses) so
    a cron running exactly at the cadence cannot double-page on rounding.
    """
    if last_ts is None:
        return False
    return (now - float(last_ts)) <= float(dedup_s)


# ---- signals: what the ledger says is wrong ---------------------------------


def _iso(ts: float | None) -> str:
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(float(ts)))


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = max(0.0, float(seconds))
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def _candidate(
    rid: str, rule: dict[str, Any], *, signal: str, target: str | None,
    ts: float, message: str, key: str,
) -> dict[str, Any]:
    sev = rule["severity"]
    return {
        "signal": signal,
        "rule": rid,
        "severity": sev,
        "target": target,
        "ts": ts,
        "message": message,
        "key": key,
        "channels": list(rule.get("channels") or []),
        "dedup_s": float(rule.get("dedup_s", DEFAULT_DEDUP_S)),
        "fingerprint": fingerprint(target, sev),
    }


def candidates(
    conn: sqlite3.Connection,
    rules: dict[str, dict[str, Any]],
    *,
    now: float,
    lookback_s: float = DEFAULT_LOOKBACK_S,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(routable, unrouted) signals read out of the shared ledger.

    Two reads, both through #2's documented contract:
    - `uptime.list_incidents(open_only=True)` — an OPEN incident is current news
      no matter how old it is, so lookback deliberately does not apply to it.
      An outage that has been open for three days must keep paging.
    - `uptime.recent_events()` inside the lookback window — an event is a point
      in time, and a router that starts up must not replay last week.
    Signals whose rule says `route: false` vanish here (known-and-ignored);
    signals with NO rule at all come back as `unrouted` so the gap is visible.
    """
    routable: list[dict[str, Any]] = []
    unrouted: list[dict[str, Any]] = []

    def resolve(rid: str, **kw: Any) -> None:
        rule = rules.get(rid)
        if rule is None:
            unrouted.append(
                {"rule": rid, "target": kw["target"], "ts": kw["ts"],
                 "message": kw["message"], "reason": "no rule matches this signal"}
            )
            return
        if not rule.get("route", True):
            return
        routable.append(_candidate(rid, rule, **kw))

    for inc in uptime.list_incidents(conn, open_only=True, limit=_READ_LIMIT):
        opened = float(inc["opened_ts"])
        resolve(
            f"{SIGNAL_INCIDENT}:{inc['state']}",
            signal=SIGNAL_INCIDENT,
            target=inc["target"],
            ts=opened,
            message=(
                f"{inc['target']} {inc['state']} since {_iso(opened)}"
                f" — open {_dur(now - opened)}"
            ),
            key=f"incident:{inc['id']}",
        )
    for ev in uptime.recent_events(conn, limit=_READ_LIMIT):
        ts = float(ev["ts"])
        if ts < now - float(lookback_s):
            continue
        resolve(
            f"{SIGNAL_EVENT}:{ev['kind']}",
            signal=SIGNAL_EVENT,
            target=ev["target"],
            ts=ts,
            message=str(ev["message"]),
            key=f"event:{ev['id']}",
        )
    return routable, unrouted


def collapse(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One page per fingerprint: worst-then-newest wins, the rest ride along.

    The winner's rule supplies the channels and the window; the messages it
    absorbed are kept in `also` so collapsing never loses information — that is
    what makes it better than paging twice for one broken daemon.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in sorted(
        cands,
        key=lambda c: (openswap.severity_rank(c["severity"]), -c["ts"], c["rule"]),
    ):
        groups.setdefault(c["fingerprint"], []).append(c)
    out: list[dict[str, Any]] = []
    for group in groups.values():
        primary = dict(group[0])
        primary["also"] = [g["message"] for g in group[1:]]
        primary["collapsed"] = len(group) - 1
        out.append(primary)
    out.sort(
        key=lambda a: (
            openswap.severity_rank(a["severity"]),
            a["target"] or "",
            a["rule"],
        )
    )
    return out


# ---- the wire format (what a channel actually carries) ----------------------


def wire_payload(alert: dict[str, Any]) -> dict[str, Any]:
    """The webhook body / the machine view of one page. Stable by contract."""
    return {
        "source": "scout-alerts",
        "openswap": "#19",
        "ts": alert.get("ts"),
        "iso": _iso(alert.get("ts")),
        "severity": alert["severity"],
        "rule": alert["rule"],
        "signal": alert["signal"],
        "target": alert.get("target"),
        "message": alert["message"],
        "also": list(alert.get("also") or []),
        "fingerprint": alert["fingerprint"],
        "dedup_s": alert.get("dedup_s"),
    }


def email_subject(alert: dict[str, Any]) -> str:
    """Severity and target first — the two things a phone notification shows."""
    where = alert.get("target") or "fleet"
    head = alert["message"].splitlines()[0][:120]
    return f"[{alert['severity']}] {where} — {head}"


def email_body(alert: dict[str, Any]) -> str:
    """Plain text, provenance included: which rule fired and why it is not spam."""
    lines = [
        alert["message"],
        "",
        f"severity : {alert['severity']}",
        f"target   : {alert.get('target') or '-'}",
        f"rule     : {alert['rule']} ({alert['signal']})",
        f"observed : {_iso(alert.get('ts'))}",
        f"dedup    : {alert.get('dedup_s')}s per (target, severity)",
        f"fpr      : {alert['fingerprint']}",
    ]
    also = list(alert.get("also") or [])
    if also:
        lines += ["", f"also on this target ({len(also)} collapsed):"]
        lines += [f"  - {m}" for m in also]
    lines += [
        "",
        "Routed locally by scout alerts (openswap #19 — PagerDuty replaced by a"
        " cron job reading the box's own sqlite ledger). No SaaS saw this.",
    ]
    return "\n".join(lines)


# ---- dispatch ---------------------------------------------------------------


def dispatch_channels(
    alert: dict[str, Any],
    channels: dict[str, dict[str, Any]],
    dispatch: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fan one alert out; {channel: {ok, detail}}. Never raises, never skips.

    An unconfigured channel is a FAILED delivery with a reason, not a silent
    skip, and an exception from the injected sender is caught per channel so one
    dead webhook cannot stop the email that would have woken someone up.
    """
    results: dict[str, dict[str, Any]] = {}
    for name in alert.get("channels") or []:
        cfg = channels.get(name)
        if cfg is None:  # load_config rejects this; defended for injected configs
            results[name] = {"ok": False, "detail": f"unknown channel {name!r}"}
            continue
        ready, reason = channel_ready(cfg)
        if not ready:
            results[name] = {"ok": False, "detail": reason}
            continue
        try:
            r = dispatch(name, cfg, alert)
            results[name] = {"ok": bool(r.get("ok")), "detail": str(r.get("detail"))}
        except Exception as e:  # a sender's crash is a delivery failure, not ours
            results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return results


def outcome_status(channels: list[str], results: dict[str, dict[str, Any]]) -> str:
    """sent / partial / failed — or `recorded` when the rule names no channel.

    `recorded` is a real configured outcome ("log it, don't page me"), so it is
    reported as itself rather than dressed up as `sent`.
    """
    if not channels:
        return STATUS_RECORDED
    oks = sum(1 for r in results.values() if r.get("ok"))
    if oks == len(channels):
        return STATUS_SENT
    return STATUS_PARTIAL if oks else STATUS_FAILED


def send_one(
    conn: sqlite3.Connection,
    alert: dict[str, Any],
    channels: dict[str, dict[str, Any]],
    dispatch: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
    *,
    ts: float,
    record: bool = True,
) -> dict[str, Any]:
    """Deliver one alert and (by default) write its delivery record."""
    results = dispatch_channels(alert, channels, dispatch)
    out = dict(alert)
    out["results"] = results
    out["status"] = outcome_status(out.get("channels") or [], results)
    out["dispatched_ts"] = ts
    if record:
        out["alert_id"] = record_alert(conn, out, ts=ts)
    return out


def probe_alert(
    *, severity: str = "info", channels: list[str], ts: float, note: str | None = None
) -> dict[str, Any]:
    """A synthetic page for proving the channels work BEFORE an outage needs them.

    Carries the sentinel target `alerts:test` so it can never share a fingerprint
    with a real signal, and therefore can never start (or consume) a real
    alert's dedup window.
    """
    target = "alerts:test"
    return {
        "signal": "test",
        "rule": "alerts:test",
        "severity": severity,
        "target": target,
        "ts": ts,
        "message": note or f"test alert from scout alerts at {_iso(ts)}",
        "key": "test",
        "channels": list(channels),
        "dedup_s": 0.0,
        "fingerprint": fingerprint(target, severity),
        "also": [],
        "collapsed": 0,
    }


# ---- the routing pass -------------------------------------------------------


def route(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    dispatch: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
    *,
    now: float | None = None,
    lookback_s: float = DEFAULT_LOOKBACK_S,
    min_severity: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One routing pass: read the ledger, decide, dedup, dispatch, record.

    `dispatch(channel_name, channel_cfg, alert) -> {"ok": bool, "detail": str}`
    is injected — the CLI passes smtplib/urllib senders, tests pass a recorder
    (the offline invariant). With dry_run the pass touches NOTHING: no dispatch
    and no ledger row, so a rehearsal cannot start a dedup window and silence
    the real page behind it.
    """
    now = time.time() if now is None else float(now)
    routable, unrouted = candidates(
        conn, config["rules"], now=now, lookback_s=lookback_s
    )
    planned = collapse(routable)
    gate = None if min_severity is None else openswap.severity_rank(min_severity)
    out: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for alert in planned:
        if gate is not None and openswap.severity_rank(alert["severity"]) > gate:
            filtered.append({k: alert[k] for k in ("rule", "target", "severity")})
            continue
        last = last_dispatch_ts(conn, alert["fingerprint"])
        alert["last_dispatch_ts"] = last
        if suppressed(now, last, alert["dedup_s"]):
            alert["status"] = STATUS_SUPPRESSED
            alert["results"] = {}
            alert["retry_in_s"] = round(float(alert["dedup_s"]) - (now - last), 3)
            out.append(alert)
            continue
        if dry_run:
            alert["status"] = STATUS_DRY_RUN
            alert["results"] = {}
            out.append(alert)
            continue
        out.append(
            send_one(conn, alert, config["channels"], dispatch, ts=now)
        )
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in out:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        by_severity[a["severity"]] = by_severity.get(a["severity"], 0) + 1
    return {
        "ts": now,
        "lookback_s": float(lookback_s),
        "min_severity": min_severity,
        "dry_run": bool(dry_run),
        "alerts": out,
        "unrouted": unrouted,
        "filtered": filtered,
        "counts": {
            "candidates": len(routable),
            "planned": len(planned),
            "collapsed": sum(int(a.get("collapsed") or 0) for a in planned),
            "by_status": by_status,
            "by_severity": by_severity,
            "unrouted": len(unrouted),
        },
    }


# ---- reads: the operator's view ---------------------------------------------


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["channels"] = json.loads(d["channels"] or "[]")
    d["delivered"] = bool(d.get("delivered"))
    detail = json.loads(d.pop("detail", None) or "{}")
    d["results"] = detail.get("channels") or {}
    d["also"] = detail.get("also") or []
    return d


def history(
    conn: sqlite3.Connection, *, fingerprint: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first delivery records, optionally for one fingerprint."""
    rows = conn.execute(
        "SELECT * FROM alerts WHERE (? IS NULL OR fingerprint = ?)"
        " ORDER BY ts DESC, id DESC LIMIT ?",
        (fingerprint, fingerprint, limit),
    )
    return [_decode(r) for r in rows]


def board(
    conn: sqlite3.Connection,
    rules: dict[str, dict[str, Any]],
    *,
    now: float | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Per-fingerprint state: last delivery, and whether it is muted right now.

    This is the answer to "why did I not get paged?" — the window in effect and
    the seconds left on it, computed from the ledger plus the live rules rather
    than from a cached countdown that could drift out of date.
    """
    now = time.time() if now is None else float(now)
    out: list[dict[str, Any]] = []
    for grp in conn.execute(
        "SELECT fingerprint, COUNT(*) AS alerts, MAX(ts) AS newest_ts FROM alerts"
        " GROUP BY fingerprint ORDER BY newest_ts DESC LIMIT ?",
        (limit,),
    ):
        fp = grp["fingerprint"]
        last = conn.execute(
            "SELECT * FROM alerts WHERE fingerprint = ? ORDER BY ts DESC, id DESC"
            " LIMIT 1",
            (fp,),
        ).fetchone()
        delivered = last_dispatch_ts(conn, fp)
        dedup_s = float((rules.get(last["rule"]) or {}).get("dedup_s", DEFAULT_DEDUP_S))
        muted = suppressed(now, delivered, dedup_s)
        out.append(
            {
                "fingerprint": fp,
                "alerts": int(grp["alerts"]),
                "rule": last["rule"],
                "severity": last["severity"],
                "target": last["target"],
                "last_status": last["status"],
                "last_ts": float(last["ts"]),
                "last_delivered_ts": delivered,
                "dedup_s": dedup_s,
                "suppressed": muted,
                "retry_in_s": (
                    round(dedup_s - (now - delivered), 3) if muted else 0.0
                ),
            }
        )
    return out


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    # certmon/heartbeat may never have run on this box; a local 3-line check
    # beats importing another adapter's module just to reuse one query
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def source_summary(
    conn: sqlite3.Connection, *, now: float, lookback_s: float = DEFAULT_LOOKBACK_S
) -> dict[str, Any]:
    """What the router can actually see — provenance before paging.

    Reported per producing plugin so "no pages" can be told apart from "no
    signal reached me": an empty `certs`/`beats` table means certmon/heartbeat
    never recorded here, which is a monitoring gap, not quiet good news.
    """
    since = now - float(lookback_s)
    open_inc = conn.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE closed_ts IS NULL"
    ).fetchone()["n"]
    ev = conn.execute(
        "SELECT COUNT(*) AS n, MAX(ts) AS newest FROM events WHERE ts >= ?", (since,)
    ).fetchone()
    kinds = {
        r["kind"]: int(r["n"])
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM events WHERE ts >= ? GROUP BY kind",
            (since,),
        )
    }
    out: dict[str, Any] = {
        "uptime": {"plugin": "uptime", "openswap": "#2", "open_incidents": int(open_inc)},
        "events": {
            "window_s": float(lookback_s),
            "rows": int(ev["n"] or 0),
            "newest_ts": ev["newest"],
            "by_kind": dict(sorted(kinds.items())),
        },
    }
    # every count query is a STATIC string (no interpolated table name) so the
    # read path stays auditable — the same rule statuspage's sources() follows
    for name, plugin, rank, table, query in (
        ("certmon", "certmon", "#9", "certs", "SELECT COUNT(*) AS n FROM certs"),
        ("heartbeat", "heartbeat", "#6", "beats", "SELECT COUNT(*) AS n FROM beats"),
    ):
        entry: dict[str, Any] = {
            "plugin": plugin, "openswap": rank, "table": table,
            "table_present": False, "rows": 0,
        }
        if _has_table(conn, table):
            entry["table_present"] = True
            entry["rows"] = int(conn.execute(query).fetchone()["n"])
        entry["present"] = entry["rows"] > 0
        out[name] = entry
    return out


# ---- family diagnostics -----------------------------------------------------


def to_diagnostics(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a routing pass onto the family diagnostic schema.

    Three findings, and the second is the one that makes this adapter honest:
    - `alerts:fired` carries the alert's OWN severity, so `--fail-on error`
      exits nonzero exactly when something paged at error.
    - `alerts:undeliverable` is always an ERROR, even when the fleet is green:
      a router that cannot reach its channels is itself the outage.
    - `alerts:unrouted` (info) surfaces ledger signals no rule covers, so a
      monitoring gap is visible instead of being swallowed.
    Suppressed alerts emit nothing — the operator was already told.
    """
    diags: list[dict[str, Any]] = []
    for a in result.get("alerts", []):
        where = a.get("target") or "alerts:router"
        if a["status"] in (STATUS_FAILED, STATUS_PARTIAL):
            broken = {
                n: r.get("detail")
                for n, r in (a.get("results") or {}).items()
                if not r.get("ok")
            }
            diags.append(
                openswap.diagnostic(
                    path=where,
                    line=0,
                    col=0,
                    rule="alerts:undeliverable",
                    severity="error",
                    message=(
                        f"{a['severity']} alert for {where} was not delivered"
                        f" ({a['status']}): {broken}"
                    ),
                    suggestion="configure the channel or fix its endpoint,"
                    " then re-run `scout alerts route` (a failed send is retried)",
                )
            )
        elif a["status"] != STATUS_SUPPRESSED:
            diags.append(
                openswap.diagnostic(
                    path=where,
                    line=0,
                    col=0,
                    rule="alerts:fired",
                    severity=a["severity"],
                    message=f"{a['status']}: {a['message']}",
                )
            )
    for u in result.get("unrouted", []):
        diags.append(
            openswap.diagnostic(
                path=u.get("target") or "alerts:router",
                line=0,
                col=0,
                rule="alerts:unrouted",
                severity="info",
                message=f"no rule for signal {u['rule']} — {u['message']}",
                suggestion=f"add a rule {u['rule']!r} (or route: false) to the config",
            )
        )
    return openswap.sort_diagnostics(diags)
