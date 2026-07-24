"""Certmon — openswap #9 (SSL Labs/TrackSSL -> stdlib ssl handshake + expiry/
host/chain analysis on the shared uptime ledger). Pure-logic core tests +
classify edge cases + ledger substrate reuse + capability-detection fallback +
the subprocess envelope. Offline and deterministic by construction: the TLS
fetcher is an injected fake returning getpeercert()-shaped dicts, `now` is
explicit everywhere, and no test opens a socket."""

from __future__ import annotations

import calendar
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import certmon, openswap, uptime

ROOT = Path(__file__).resolve().parents[1]

# a fixed reference expiry; `now` is derived from it so days-to-expiry is exact
NA = "Aug  1 00:00:00 2026 GMT"
NA_EPOCH = certmon.parse_cert_time(NA)
DAY = 86400.0


def _cert(
    *,
    not_after=NA,
    host="example.com",
    sans=None,
    issuer_cn="Example CA",
    not_before="Jan  1 00:00:00 2020 GMT",
):
    """A getpeercert()-shaped dict. sans=None defaults to [host]; sans=[] forces
    the CN-only (legacy, no-SAN) case; issuer_cn=None forces a chainless cert."""
    subject = ((("commonName", host),),)
    issuer = ((("commonName", issuer_cn),),) if issuer_cn else ()
    dns = [host] if sans is None else sans
    san = tuple(("DNS", s) for s in dns)
    cert = {
        "subject": subject,
        "issuer": issuer,
        "notBefore": not_before,
        "notAfter": not_after,
        "subjectAltName": san,
    }
    return cert


def _obs(cert=None, *, protocol="TLSv1.3", hsts=True, error=None, verified=True):
    return {
        "cert": cert,
        "protocol": protocol,
        "hsts": hsts,
        "error": error,
        "verified": verified,
    }


def _mem():
    return certmon.open_cert_ledger(":memory:")


# ---- cert timestamp parsing (locale-independent) ----------------------------


def test_parse_cert_time_locale_independent():
    # double-space single-digit day and calendar.timegm agreement
    assert certmon.parse_cert_time("Aug  1 23:59:59 2026 GMT") == float(
        calendar.timegm((2026, 8, 1, 23, 59, 59, 0, 0, 0))
    )
    # single-space form parses identically (split() collapses whitespace)
    assert certmon.parse_cert_time("Jan 5 00:00:00 2030 GMT") == float(
        calendar.timegm((2030, 1, 5, 0, 0, 0, 0, 0, 0))
    )


def test_parse_cert_time_rejects_junk():
    for bad in ("not a date", "Aug 1 2026", "Xyz  1 00:00:00 2026 GMT",
                "Aug  1 00:00:00 2026 PST", 12345):
        with pytest.raises(ValueError):
            certmon.parse_cert_time(bad)


def test_not_after_seconds_tolerates_missing_and_malformed():
    assert certmon.not_after_seconds(_cert()) == NA_EPOCH
    assert certmon.not_after_seconds({"subject": ()}) is None  # no notAfter
    assert certmon.not_after_seconds({"notAfter": "garbage"}) is None
    assert certmon.days_until(None, NA_EPOCH) is None
    assert certmon.days_until(NA_EPOCH, NA_EPOCH - 45 * DAY) == 45.0


# ---- host / SAN matching ----------------------------------------------------


def test_host_matches_exact_wildcard_and_cn_fallback():
    c = _cert(host="example.com", sans=["example.com", "www.example.com"])
    assert certmon.host_matches("www.example.com", c) is True
    assert certmon.host_matches("EXAMPLE.COM", c) is True  # case-insensitive
    assert certmon.host_matches("api.example.com", c) is False
    wild = _cert(sans=["*.example.com"])
    assert certmon.host_matches("a.example.com", wild) is True
    assert certmon.host_matches("example.com", wild) is False  # no left label
    assert certmon.host_matches("a.b.example.com", wild) is False  # two labels
    assert certmon.host_matches("a.evil.com", _cert(sans=["*.example.com"])) is False
    # CN is honored ONLY when no SAN is present
    cn_only = _cert(host="legacy.example.com", sans=[])
    assert certmon.host_matches("legacy.example.com", cn_only) is True
    san_wins = _cert(host="cn.example.com", sans=["other.example.com"])
    assert certmon.host_matches("cn.example.com", san_wins) is False


def test_self_signed_and_chain():
    assert certmon.is_self_signed(_cert(host="x", issuer_cn="x")) is True
    assert certmon.has_chain(_cert(host="x", issuer_cn="x")) is False
    ca = _cert(host="x", issuer_cn="Some CA")
    assert certmon.is_self_signed(ca) is False and certmon.has_chain(ca) is True
    chainless = _cert(host="x", issuer_cn=None)
    assert certmon.is_self_signed(chainless) is False
    assert certmon.has_chain(chainless) is False  # no issuer info at all


def test_weak_protocol():
    for weak in ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1"):
        assert certmon.is_weak_protocol(weak) is True
    for strong in ("TLSv1.2", "TLSv1.3", None, "unknown"):
        assert certmon.is_weak_protocol(strong) is False


# ---- the classify matrix ----------------------------------------------------


def test_analyze_healthy_is_ok():
    v = certmon.analyze("example.com", _obs(_cert()), now=NA_EPOCH - 60 * DAY)
    assert v["severity"] == "ok" and v["reasons"] == []
    assert v["reachable"] is True and v["host_match"] is True
    assert v["has_chain"] is True and v["self_signed"] is False
    assert v["days_to_expiry"] == 60.0


def test_analyze_expiry_windows():
    warn = certmon.analyze("example.com", _obs(_cert()), now=NA_EPOCH - 30 * DAY)
    assert warn["severity"] == "warning"
    assert [r["code"] for r in warn["reasons"]] == ["expiring"]
    soon = certmon.analyze("example.com", _obs(_cert()), now=NA_EPOCH - 10 * DAY)
    assert soon["severity"] == "error"
    assert [r["code"] for r in soon["reasons"]] == ["expiring-soon"]
    dead = certmon.analyze("example.com", _obs(_cert()), now=NA_EPOCH + 5 * DAY)
    assert dead["severity"] == "error"
    assert [r["code"] for r in dead["reasons"]] == ["expired"]
    # thresholds are config: a wider error window pulls a 30-day cert into error
    tuned = certmon.analyze(
        "example.com", _obs(_cert()), now=NA_EPOCH - 30 * DAY, error_days=40
    )
    assert [r["code"] for r in tuned["reasons"]] == ["expiring-soon"]


def test_analyze_identity_and_integrity_errors():
    now = NA_EPOCH - 60 * DAY
    mism = certmon.analyze("evil.com", _obs(_cert(host="example.com")), now=now)
    assert mism["severity"] == "error"
    assert [r["code"] for r in mism["reasons"]] == ["host-mismatch"]
    ss = certmon.analyze("x.com", _obs(_cert(host="x.com", issuer_cn="x.com")), now=now)
    assert [r["code"] for r in ss["reasons"]] == ["self-signed"]
    assert ss["severity"] == "error"
    weak = certmon.analyze(
        "example.com", _obs(_cert(), protocol="TLSv1"), now=now
    )
    assert [r["code"] for r in weak["reasons"]] == ["weak-protocol"]
    assert weak["severity"] == "error"


def test_analyze_warning_conditions():
    now = NA_EPOCH - 60 * DAY
    no_hsts = certmon.analyze("example.com", _obs(_cert(), hsts=False), now=now)
    assert [r["code"] for r in no_hsts["reasons"]] == ["missing-hsts"]
    assert no_hsts["severity"] == "warning"
    # hsts unknown (None) is NOT a warning — we only flag a confirmed absence
    unknown = certmon.analyze("example.com", _obs(_cert(), hsts=None), now=now)
    assert unknown["severity"] == "ok"
    chainless = certmon.analyze(
        "example.com", _obs(_cert(issuer_cn=None)), now=now
    )
    assert [r["code"] for r in chainless["reasons"]] == ["no-chain"]
    assert chainless["severity"] == "warning"


def test_analyze_multiple_reasons_worst_severity_wins():
    v = certmon.analyze(
        "example.com",
        _obs(_cert(not_after="Jan  1 00:00:00 2020 GMT"), protocol="TLSv1", hsts=False),
        now=NA_EPOCH,
    )
    codes = {r["code"] for r in v["reasons"]}
    assert {"expired", "weak-protocol", "missing-hsts"} <= codes
    assert v["severity"] == "error"  # error beats the co-occurring warning


# ---- unreachable + adversarial inputs ---------------------------------------


def test_analyze_unreachable_and_malformed_never_crash():
    down = certmon.analyze(
        "example.com", _obs(None, error="TimeoutError: x"), now=NA_EPOCH
    )
    assert down["reachable"] is False and down["severity"] == "error"
    assert [r["code"] for r in down["reasons"]] == ["unreachable"]
    assert certmon.analyze("example.com", _obs({}), now=NA_EPOCH)["severity"] == "error"
    # a cert dict with no notAfter is malformed -> bad-cert error, not a crash
    bad = certmon.analyze(
        "example.com", _obs({"subject": ((("commonName", "example.com"),),),
                             "issuer": ((("commonName", "CA"),),),
                             "subjectAltName": (("DNS", "example.com"),)}),
        now=NA_EPOCH,
    )
    assert any(r["code"] == "bad-cert" for r in bad["reasons"])
    # hostile shapes: IP-only SAN, empty subject/issuer, weird pair arity
    weird = {
        "subject": (),
        "issuer": (),
        "notAfter": NA,
        "subjectAltName": (("IP Address", "1.2.3.4"), ("DNS",)),
    }
    v = certmon.analyze("example.com", _obs(weird), now=NA_EPOCH - 60 * DAY)
    assert v["host_match"] is False  # no usable DNS/CN name
    assert v["severity"] == "error"  # host-mismatch (+ no-chain), no exception


# ---- family schema + targets ------------------------------------------------


def test_to_diagnostics_normalize_into_family_schema():
    now = NA_EPOCH - 60 * DAY
    results = [
        certmon.analyze("ok.com", _obs(_cert(host="ok.com")), now=now),
        certmon.analyze("evil.com", _obs(_cert(host="good.com")), now=now),
        certmon.analyze("warn.com", _obs(_cert(host="warn.com"), hsts=False), now=now),
    ]
    diags = certmon.to_diagnostics(results)
    assert len(diags) == 2  # the ok host emits nothing
    by_rule = {d["rule"]: d for d in diags}
    assert "certmon:host-mismatch" in by_rule
    assert by_rule["certmon:host-mismatch"]["severity"] == "error"
    assert by_rule["certmon:host-mismatch"]["path"] == "https://evil.com"
    assert by_rule["certmon:missing-hsts"]["severity"] == "warning"
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 1
    assert summary["by_severity"]["warning"] == 1


def test_default_targets_are_https_hosts_of_the_fleet():
    targets = certmon.default_targets()
    assert "127.0.0.1" not in targets  # ollama is http/loopback — no cert
    assert "dumbmodel.com" in targets and "www.bhenre.com" in targets
    assert "bluehenre-campus.vercel.app" in targets
    # exactly the https hosts of uptime.DEFAULT_TARGETS, de-duplicated
    expected = []
    for cfg in uptime.DEFAULT_TARGETS.values():
        if cfg["url"].startswith("https://"):
            from urllib.parse import urlsplit

            h = urlsplit(cfg["url"]).hostname
            if h not in expected:
                expected.append(h)
    assert targets == expected


# ---- ledger: shared uptime substrate, idempotent certs table ----------------


def _tables(conn):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_ledger_reuses_uptime_tables_and_adds_certs():
    conn = _mem()
    tabs = _tables(conn)
    # uptime's substrate is present AND functional (no parallel store)
    assert {"checks", "state", "incidents", "events", "meta", "certs"} <= tabs
    uptime.record_check(conn, target="hub", url="u", ts=1.0, state="up", http=200)
    assert uptime.recent_checks(conn, "hub")[0]["http"] == 200  # uptime unbroken


def test_open_cert_ledger_is_idempotent(tmp_path):
    db = tmp_path / "uptime.db"
    conn = certmon.open_cert_ledger(db)
    v = certmon.analyze("ok.com", _obs(_cert(host="ok.com")), now=NA_EPOCH - 60 * DAY)
    rid = certmon.record_cert(conn, v, ts=100.0)
    conn.close()
    # re-open the SAME file: no error, prior rows survive, certs table intact
    conn2 = certmon.open_cert_ledger(db)
    assert "certs" in _tables(conn2)
    assert certmon.latest_cert(conn2, "ok.com")["id"] == rid


def test_record_cert_writes_history_and_events_only_on_problems():
    conn = _mem()
    now = NA_EPOCH - 60 * DAY
    ok_v = certmon.analyze("ok.com", _obs(_cert(host="ok.com")), now=now)
    certmon.record_cert(conn, ok_v, ts=now)
    assert uptime.recent_events(conn) == []  # a clean cert makes no noise
    bad_v = certmon.analyze("bad.com", _obs(_cert(host="other.com")), now=now)
    certmon.record_cert(conn, bad_v, ts=now)
    evs = uptime.recent_events(conn)
    assert len(evs) == 1 and evs[0]["kind"] == "cert" and evs[0]["target"] == "bad.com"
    row = certmon.latest_cert(conn, "bad.com")
    assert row["severity"] == "error" and json.loads(row["reasons"]) == ["host-mismatch"]
    assert row["host_match"] == 0  # bool stored as int


# ---- run_pass + reads -------------------------------------------------------


def test_run_pass_records_and_boards():
    conn = _mem()
    now = NA_EPOCH - 60 * DAY
    canned = {
        "good.com": _obs(_cert(host="good.com")),
        "dead.com": _obs(_cert(host="dead.com", not_after="Jan  1 00:00:00 2020 GMT")),
    }
    res = certmon.run_pass(conn, list(canned), lambda h: canned[h], now=now)
    sevs = {r["host"]: r["severity"] for r in res["results"]}
    assert sevs == {"good.com": "ok", "dead.com": "error"}
    assert len(res["problems"]) == 1
    assert len(certmon.cert_history(conn, "dead.com")) == 1
    # board recomputes days-to-expiry against a *later* now, unknown for unseen
    board = {b["host"]: b for b in certmon.board(conn, ["good.com", "never.com"], now=now)}
    assert board["good.com"]["days_to_expiry"] == 60.0
    assert board["good.com"]["status"] == "ok"
    assert board["never.com"]["status"] == "unknown"


def test_run_pass_no_record_leaves_ledger_empty():
    conn = _mem()
    obs = _obs(_cert(host="x.com"))
    certmon.run_pass(conn, ["x.com"], lambda h: obs, now=NA_EPOCH - 60 * DAY, record=False)
    assert certmon.cert_history(conn, "x.com") == []


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.certmon import cli as certmon_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = certmon_cli._capability()
    assert cap["adapter"] == "certmon"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "ssl-cert-check"
    assert cap["extras"]["openssl"]["found"] is False
    assert cap["extras"]["ssllabs-scan"]["found"] is False  # SaaS client, never run


# ---- the real CLI in a subprocess (offline paths only) ----------------------


def _cli(args, cwd=None, env=None):
    import os

    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
        env=e,
    )


def test_cli_certmon_hello_envelope():
    r = _cli(["certmon", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_certmon_status_without_ledger_fails_actionably(tmp_path):
    r = _cli(["certmon", "status", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no monitoring ledger" in data["error"]
    assert "example" in data


def test_cli_certmon_check_adhoc_host_is_policy_gated_offline(tmp_path):
    # BIGBANG_POLICY_FILE -> a fresh tmp file: the default user allowlist is
    # loopback-only, so an off-fleet host is DENIED before any socket opens.
    r = _cli(
        ["certmon", "check", "--host", "not-allowed.example.com"],
        env={"BIGBANG_POLICY_FILE": str(tmp_path / "policy.yaml")},
    )
    assert r.returncode == 1  # denied at the user-allowlist gate, no network
    assert "denied" in (r.stdout + r.stderr).lower()
