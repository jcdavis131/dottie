# Solo personal project, no connection to employer, built with public/free-tier only
"""Certmon — TLS/certificate monitor core (openswap #9: SSL Labs / TrackSSL).

The paid enemies here are SaaS: SSL Labs' Server Test and TrackSSL both watch
your certificates from someone else's box. This adapter inverts that — the TLS
handshake happens locally (the plugin CLI owns the one real I/O:
`ssl.create_default_context()` + `getpeercert()`), and every deterministic
judgment lives here so the whole pipeline is unit-testable fully offline. Tests
inject a fake fetcher that returns a `getpeercert()`-shaped cert dict; nothing
in this module opens a socket.

What the core computes from one observation (a cert dict + negotiated protocol
+ optional HSTS header presence):
- days-to-expiry from `notAfter` (locale-independent parse — see parse_cert_time)
- SAN/CN host match with RFC-6125 left-label wildcard rules
- issuer-chain presence and self-signed detection (issuer vs subject DN)
- weak-protocol flags (SSLv2/SSLv3/TLSv1/TLSv1.1)

Classification (analyze/classify) — the documented severity contract:
- ERROR:   expired, expiring-soon (< 21d), host-mismatch. Extended with the two
           cert-integrity failures a serious monitor must also fail on:
           self-signed and weak-protocol (a self-signed or TLS-1.0 cert on a
           public host is as much an error as a hostname mismatch).
- WARNING: expiring (< 45d), missing-HSTS, and a missing issuer chain.
- OK:      none of the above.
Multiple reasons can co-apply; the verdict's `severity` is the worst of them.
to_diagnostics() maps non-ok verdicts onto the openswap diagnostic schema, so
openswap.summarize() and `--fail-on` gates treat cert findings exactly like
prose lint findings or uptime outages.

Substrate reuse (no parallel store): open_cert_ledger() wraps
uptime.open_ledger() and adds ONE idempotent `certs` table
(CREATE TABLE IF NOT EXISTS) — it never alters uptime's tables. Cert
observations land on the SAME monitoring timeline: record_cert() writes the
history row and, for any non-ok observation, drops a kind="cert" event via
uptime.record_event() that the status page / alert router already read.

Extension points:
- Ad-hoc / extra hosts: default_targets() derives the https hosts from
  uptime.DEFAULT_TARGETS (policy-as-config — the CLI still gates each host
  against the manifest allowlist before a handshake). Pass any host list to
  run_pass().
- Expiry budgets as config: analyze(warn_days=, error_days=) tunes the warning
  and error windows without touching code — feed them from a JSON overlay.
- Status-page / alert-router hooks: board(), cert_history(), latest_cert() and
  the shared events table are the read contract; the kind="cert" events sit on
  the same timeline as uptime incidents and heartbeat alerts.
- Native tier: there is none to prefer (SSL Labs and TrackSSL are SaaS; the
  stdlib ssl core IS the product). The plugin's detect() surfaces openssl as an
  optional local helper and ssllabs-scan as a SaaS client that is named but
  never executed — the forbidden network tier.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from bigbang.core import openswap, uptime

if TYPE_CHECKING:
    from collections.abc import Callable

SEV_OK = "ok"
SEV_WARNING = "warning"
SEV_ERROR = "error"

# expiry budgets (days); overridable per call so the windows are config, not code
EXPIRY_ERROR_DAYS = 21.0
EXPIRY_WARN_DAYS = 45.0

DEFAULT_PORT = 443

# Python's ssl.SSLSocket.version() strings for the protocols no serious host
# should still negotiate. "TLSv1" is TLS 1.0.
WEAK_PROTOCOLS = ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1")

# locale-independent month map — cert timestamps are ALWAYS English abbreviations
# ("Aug  1 23:59:59 2026 GMT"); time.strptime("%b") would honor $LC_TIME and
# mis-parse under a non-English locale, so we never use it.
_MONTHS = {
    m: i
    for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}


# ---- cert timestamp parsing -------------------------------------------------


def parse_cert_time(value: str) -> float:
    """'notAfter'/'notBefore' string -> epoch seconds (UTC), locale-independent.

    Accepts the OpenSSL/`getpeercert()` form 'Aug  1 23:59:59 2026 GMT' (note
    the double space padding single-digit days). Whitespace is collapsed via
    split(), the month is looked up in a hardcoded English map, and the time is
    assembled with calendar.timegm so the result never depends on the host's
    locale or timezone. Raises ValueError on anything that is not this shape.
    """
    if not isinstance(value, str):
        raise ValueError(f"cert time must be a string, got {type(value).__name__}")
    parts = value.split()
    # 'Aug', '1', '23:59:59', '2026', 'GMT'
    if len(parts) < 4:
        raise ValueError(f"unparseable cert time {value!r}")
    mon, day, clock, year = parts[0], parts[1], parts[2], parts[3]
    if len(parts) >= 5 and parts[4] not in ("GMT", "UTC"):
        raise ValueError(f"cert time must be GMT/UTC, got {value!r}")
    try:
        month = _MONTHS[mon]
        hh, mm, ss = (int(x) for x in clock.split(":"))
        stamp = (int(year), month, int(day), hh, mm, ss, 0, 0, 0)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unparseable cert time {value!r}: {exc}") from exc
    return float(calendar.timegm(stamp))


def not_after_seconds(cert: dict[str, Any]) -> float | None:
    """Epoch of the cert's notAfter, or None when absent/malformed."""
    raw = cert.get("notAfter")
    if not raw:
        return None
    try:
        return parse_cert_time(raw)
    except ValueError:
        return None


def not_before_seconds(cert: dict[str, Any]) -> float | None:
    """Epoch of the cert's notBefore, or None when absent/malformed."""
    raw = cert.get("notBefore")
    if not raw:
        return None
    try:
        return parse_cert_time(raw)
    except ValueError:
        return None


def days_until(not_after: float | None, now: float) -> float | None:
    """Signed days from `now` to `not_after` (negative == already expired)."""
    if not_after is None:
        return None
    return round((not_after - now) / 86400.0, 2)


# ---- host / SAN matching ----------------------------------------------------


def _flatten_dn(dn: Any) -> list[tuple[str, str]]:
    """getpeercert()'s nested RDN structure -> a flat [(key, value), ...]."""
    out: list[tuple[str, str]] = []
    for rdn in dn or ():
        for pair in rdn or ():
            if isinstance(pair, (tuple, list)) and len(pair) == 2:
                out.append((str(pair[0]), str(pair[1])))
    return out


def cert_names(cert: dict[str, Any]) -> tuple[list[str], str | None]:
    """(SAN dNSName list, subject CN) — the identities a cert asserts.

    Tolerant of malformed SAN entries (a getpeercert() dict is attacker-adjacent
    data): anything that is not a 2-tuple typed "DNS" is simply skipped rather
    than crashing the unpack.
    """
    san = [
        str(entry[1])
        for entry in cert.get("subjectAltName", ()) or ()
        if isinstance(entry, (tuple, list))
        and len(entry) == 2
        and str(entry[0]).upper() == "DNS"
    ]
    cn = None
    for key, value in _flatten_dn(cert.get("subject")):
        if key in ("commonName", "CN"):
            cn = value
            break
    return san, cn


def _label_match(pattern: str, host: str) -> bool:
    """One SAN/CN pattern vs one host — exact, or a single left-label wildcard.

    RFC 6125: a wildcard is only valid as the entire leftmost label and matches
    exactly one label — '*.example.com' matches 'a.example.com' but NOT the bare
    'example.com' (no left label) nor 'a.b.example.com' (two labels). Wildcards
    anywhere else are rejected outright rather than guessed at.
    """
    pattern = pattern.strip().rstrip(".").lower()
    host = host.strip().rstrip(".").lower()
    if not pattern or not host:
        return False
    if "*" not in pattern:
        return pattern == host
    if not pattern.startswith("*.") or "*" in pattern[2:]:
        return False  # wildcard must be the whole leftmost label, and only there
    suffix = pattern[1:]  # '.example.com'
    if not host.endswith(suffix):
        return False
    left = host[: -len(suffix)]
    return bool(left) and "." not in left


def host_matches(host: str, cert: dict[str, Any]) -> bool:
    """True if `host` is covered by the cert's SANs (CN only when SAN absent).

    Modern verification ignores CN when a SAN is present, so we do too: the CN
    fallback fires only for (legacy) certs with no subjectAltName at all.
    """
    san, cn = cert_names(cert)
    candidates = san if san else ([cn] if cn else [])
    return any(_label_match(p, host) for p in candidates)


# ---- chain / self-signed / protocol -----------------------------------------


def _dn_key(dn: Any) -> frozenset[tuple[str, str]]:
    return frozenset(_flatten_dn(dn))


def is_self_signed(cert: dict[str, Any]) -> bool:
    """subject == issuer (both present) -> the cert signs itself, no CA above."""
    subject = _dn_key(cert.get("subject"))
    issuer = _dn_key(cert.get("issuer"))
    return bool(subject) and bool(issuer) and subject == issuer


def has_chain(cert: dict[str, Any]) -> bool:
    """A distinct issuer is present (i.e. a CA above the leaf) and not self-signed."""
    issuer = _dn_key(cert.get("issuer"))
    return bool(issuer) and not is_self_signed(cert)


def is_weak_protocol(protocol: str | None) -> bool:
    """True for SSLv2/SSLv3/TLSv1/TLSv1.1; None/unknown is not treated as weak."""
    return protocol in WEAK_PROTOCOLS


# ---- the verdict ------------------------------------------------------------


def _reason(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def analyze(
    host: str,
    observation: dict[str, Any],
    *,
    now: float,
    warn_days: float = EXPIRY_WARN_DAYS,
    error_days: float = EXPIRY_ERROR_DAYS,
) -> dict[str, Any]:
    """One cert observation -> the normalized certmon verdict (see module doc).

    `observation` is what the injected fetcher returns:
    {"cert": <getpeercert() dict or None>, "protocol": str|None,
     "hsts": bool|None, "error": str|None, "verified": bool|None}. A None/empty
    cert (with an optional handshake error) is an "unreachable" error rather
    than a crash — a monitor that silently drops the hosts it cannot reach is
    the failure mode this whole family exists to kill.
    """
    cert = observation.get("cert")
    protocol = observation.get("protocol")
    hsts = observation.get("hsts")
    err = observation.get("error")
    reachable = isinstance(cert, dict) and bool(cert)

    verdict: dict[str, Any] = {
        "host": host,
        "reachable": reachable,
        "not_before": None,
        "not_after": None,
        "days_to_expiry": None,
        "host_match": None,
        "self_signed": None,
        "has_chain": None,
        "weak_protocol": is_weak_protocol(protocol),
        "protocol": protocol,
        "hsts": hsts,
        "verified": observation.get("verified"),
        "error": err,
        "reasons": [],
    }
    reasons: list[dict[str, str]] = []

    if not reachable:
        reasons.append(
            _reason("unreachable", SEV_ERROR, err or "no certificate retrieved")
        )
        verdict["reasons"] = reasons
        verdict["severity"] = SEV_ERROR
        return verdict

    not_after = not_after_seconds(cert)
    verdict["not_before"] = not_before_seconds(cert)
    verdict["not_after"] = not_after
    days = days_until(not_after, now)
    verdict["days_to_expiry"] = days
    match = host_matches(host, cert)
    verdict["host_match"] = match
    selfsigned = is_self_signed(cert)
    verdict["self_signed"] = selfsigned
    chain = has_chain(cert)
    verdict["has_chain"] = chain

    # expiry
    if days is None:
        reasons.append(
            _reason("bad-cert", SEV_ERROR, "certificate has no valid notAfter")
        )
    elif days < 0:
        reasons.append(_reason("expired", SEV_ERROR, f"expired {abs(days)}d ago"))
    elif days < error_days:
        reasons.append(
            _reason(
                "expiring-soon", SEV_ERROR, f"expires in {days}d (< {error_days:g})"
            )
        )
    elif days < warn_days:
        reasons.append(
            _reason("expiring", SEV_WARNING, f"expires in {days}d (< {warn_days:g})")
        )

    # identity
    if not match:
        san, cn = cert_names(cert)
        offered = ", ".join(san or ([cn] if cn else [])) or "(no SAN/CN)"
        reasons.append(
            _reason("host-mismatch", SEV_ERROR, f"{host} not in cert names [{offered}]")
        )

    # chain integrity
    if selfsigned:
        reasons.append(_reason("self-signed", SEV_ERROR, "certificate is self-signed"))
    elif not chain:
        reasons.append(_reason("no-chain", SEV_WARNING, "issuer chain missing"))

    # protocol strength
    if verdict["weak_protocol"]:
        reasons.append(
            _reason("weak-protocol", SEV_ERROR, f"negotiated weak {protocol}")
        )

    # transport hardening
    if hsts is False:
        reasons.append(
            _reason("missing-hsts", SEV_WARNING, "no Strict-Transport-Security header")
        )

    verdict["reasons"] = reasons
    verdict["severity"] = _worst_severity(reasons)
    return verdict


def _worst_severity(reasons: list[dict[str, str]]) -> str:
    """error beats warning beats ok (uses the family severity ranking)."""
    worst = SEV_OK
    for r in reasons:
        if openswap.severity_rank(r["severity"]) < openswap.severity_rank(worst):
            worst = r["severity"]
    return worst


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map non-ok verdicts onto the family diagnostic schema.

    One diagnostic per problem host, tagged with its worst reason code; ok
    hosts emit nothing. line/col carry no meaning for a host and stay 0. This
    is what lets openswap.summarize() and `--fail-on` gates treat cert findings
    exactly like prose lint findings.
    """
    diags = []
    for r in results:
        sev = r.get("severity")
        if sev not in (SEV_ERROR, SEV_WARNING):
            continue
        reasons = sorted(
            r.get("reasons", []),
            key=lambda x: openswap.severity_rank(x["severity"]),
        )
        primary = reasons[0]["code"] if reasons else sev
        message = "; ".join(x["message"] for x in reasons) or sev
        diags.append(
            openswap.diagnostic(
                path=f"https://{r['host']}",
                line=0,
                col=0,
                rule=f"certmon:{primary}",
                severity=sev,
                message=f"{r['host']} — {message}",
            )
        )
    return openswap.sort_diagnostics(diags)


# ---- targets ----------------------------------------------------------------


def default_targets() -> list[str]:
    """The https hosts of the monitored fleet, derived from uptime.DEFAULT_TARGETS.

    Same host list as uptime (the twin feed's source of truth), https only —
    the loopback ollama endpoint is http and has no cert to watch, so it drops
    out. Deriving instead of duplicating means the two adapters can never
    disagree about what the fleet is.
    """
    hosts: list[str] = []
    seen: set[str] = set()
    for cfg in uptime.DEFAULT_TARGETS.values():
        url = cfg.get("url", "")
        if not url.startswith("https://"):
            continue
        host = urlsplit(url).hostname
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts


# ---- ledger (shared uptime substrate + one idempotent certs table) ----------

_CERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS certs(
    id INTEGER PRIMARY KEY,
    host TEXT NOT NULL,
    ts REAL NOT NULL,
    not_before REAL,
    not_after REAL,
    days_to_expiry REAL,
    host_match INTEGER,
    self_signed INTEGER,
    has_chain INTEGER,
    weak_protocol INTEGER,
    protocol TEXT,
    hsts INTEGER,
    verified INTEGER,
    severity TEXT NOT NULL,
    reasons TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_certs_host_ts ON certs(host, ts);
"""


def open_cert_ledger(path: str | Path) -> sqlite3.Connection:
    """The shared monitoring ledger (#2) plus one idempotent `certs` table.

    Wraps uptime.open_ledger (same sqlite file, same checks/state/incidents/
    events tables) and adds `certs` via CREATE TABLE IF NOT EXISTS. It NEVER
    alters uptime's tables — cert history is additive, and calling this twice on
    the same file is a no-op, so uptime and certmon can share one .scout/uptime.db.
    """
    conn = uptime.open_ledger(path)
    conn.executescript(_CERT_SCHEMA)
    conn.commit()
    return conn


def _i(flag: Any) -> int | None:
    return None if flag is None else int(bool(flag))


def record_cert(
    conn: sqlite3.Connection, verdict: dict[str, Any], *, ts: float | None = None
) -> int:
    """Append one cert observation to `certs`; non-ok ones also hit the timeline.

    The history row is always written. When the verdict is not ok, a
    kind="cert" event is dropped on the SHARED events timeline via
    uptime.record_event, so cert problems correlate with uptime incidents and
    heartbeat alerts in one place. Returns the certs row id.
    """
    ts = time.time() if ts is None else float(ts)
    codes = [r["code"] for r in verdict.get("reasons", [])]
    cur = conn.execute(
        "INSERT INTO certs(host, ts, not_before, not_after, days_to_expiry,"
        " host_match, self_signed, has_chain, weak_protocol, protocol, hsts,"
        " verified, severity, reasons, error)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            verdict["host"],
            ts,
            verdict.get("not_before"),
            verdict.get("not_after"),
            verdict.get("days_to_expiry"),
            _i(verdict.get("host_match")),
            _i(verdict.get("self_signed")),
            _i(verdict.get("has_chain")),
            _i(verdict.get("weak_protocol")),
            verdict.get("protocol"),
            _i(verdict.get("hsts")),
            _i(verdict.get("verified")),
            verdict.get("severity", SEV_OK),
            json.dumps(codes) if codes else None,
            verdict.get("error"),
        ),
    )
    conn.commit()
    if verdict.get("severity", SEV_OK) != SEV_OK:
        detail = "; ".join(r["message"] for r in verdict.get("reasons", []))
        uptime.record_event(
            conn,
            kind="cert",
            message=f"{verdict['host']} {verdict['severity']} — {detail}",
            target=verdict["host"],
            ts=ts,
        )
    return int(cur.lastrowid)


def run_pass(
    conn: sqlite3.Connection,
    targets: list[str],
    fetch: Callable[[str], dict[str, Any]],
    *,
    now: float | None = None,
    record: bool = True,
    warn_days: float = EXPIRY_WARN_DAYS,
    error_days: float = EXPIRY_ERROR_DAYS,
) -> dict[str, Any]:
    """One monitoring pass: handshake every host, analyze, record, report.

    `fetch(host)` must return the observation dict analyze() expects — the CLI
    injects the real ssl handshake fetcher; tests inject fakes (the offline
    invariant). With record=False the certs table is left untouched (probe-and-
    report only).
    """
    now = time.time() if now is None else float(now)
    results: list[dict[str, Any]] = []
    for host in targets:
        obs = fetch(host)
        verdict = analyze(
            host, obs, now=now, warn_days=warn_days, error_days=error_days
        )
        if record:
            record_cert(conn, verdict, ts=now)
        results.append(verdict)
    return {
        "ts": now,
        "results": results,
        "problems": [r for r in results if r.get("severity", SEV_OK) != SEV_OK],
    }


# ---- reads: the status-page / alert-router contract -------------------------


def latest_cert(conn: sqlite3.Connection, host: str) -> dict[str, Any] | None:
    """The most recent cert observation for one host, or None."""
    row = conn.execute(
        "SELECT * FROM certs WHERE host = ? ORDER BY ts DESC, id DESC LIMIT 1",
        (host,),
    ).fetchone()
    return dict(row) if row else None


def cert_history(
    conn: sqlite3.Connection, host: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first cert observations for one host."""
    rows = conn.execute(
        "SELECT * FROM certs WHERE host = ? ORDER BY ts DESC, id DESC LIMIT ?",
        (host, limit),
    )
    return [dict(r) for r in rows]


def board(
    conn: sqlite3.Connection, hosts: list[str], *, now: float | None = None
) -> list[dict[str, Any]]:
    """Current cert posture per host from the ledger (read-only, no handshakes).

    days_to_expiry is recomputed against `now` from the stored notAfter so the
    board stays fresh between passes; the stored severity/flags are carried as
    observed. A host with no observation yet reads status "unknown".
    """
    now = time.time() if now is None else float(now)
    out = []
    for host in hosts:
        last = latest_cert(conn, host)
        if last is None:
            out.append({"host": host, "status": "unknown", "last": None})
            continue
        out.append(
            {
                "host": host,
                "status": last["severity"],
                "last_ts": last["ts"],
                "not_after": last["not_after"],
                "days_to_expiry": days_until(last["not_after"], now),
                "protocol": last["protocol"],
                "self_signed": last["self_signed"],
                "host_match": last["host_match"],
                "hsts": last["hsts"],
                "reasons": json.loads(last["reasons"]) if last["reasons"] else [],
                "last": last,
            }
        )
    return out
