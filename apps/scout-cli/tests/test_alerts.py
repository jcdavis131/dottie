"""Alerts — openswap #19 (PagerDuty/Opsgenie -> local severity rules + dedup
windows over the shared uptime/certmon/heartbeat ledger). Pure-logic core tests
+ the dedup/collapse contracts + the "silence is never health" invariant + the
real senders at their monkeypatched boundary + the subprocess envelope.

Offline and deterministic by construction: ledgers are seeded through the owning
plugins' OWN writers (uptime.run_pass with canned probe dicts, heartbeat.beat/
sweep, certmon.run_pass with a getpeercert()-shaped fake), every `now`/`ts` is
explicit, and the dispatch boundary is injected — no test opens a socket. The
two things these tests refuse to allow are a router that pages twice for one
problem, and a router whose broken channel looks like a quiet night.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import alerts, certmon, heartbeat, openswap, uptime

ROOT = Path(__file__).resolve().parents[1]

# fixed base epoch (2025-10-09Z); every other timestamp derives from it
T0 = 1_760_000_000.0
DAY = 86400.0

UP = {"http": 200, "latency_ms": 40.0, "error": None, "body_head": ""}
DOWN = {"http": None, "latency_ms": 0.0, "error": "TimeoutError: x", "body_head": ""}
TARGETS = {"zeta": {"url": "https://www.bhenre.com"}}


# ---- fixtures: every ledger row is written by its owning plugin --------------


def _scripted(seq):
    """Probe fake replaying canned results in order (the offline invariant)."""
    it = iter(seq)

    def probe(url, cfg):
        return next(it)

    return probe


def _seed_uptime(path, *, targets=None, script=None, start=T0, step=60.0):
    """Real ledger written by uptime's OWN pipeline; returns the last ts."""
    targets = TARGETS if targets is None else targets
    script = [[DOWN]] if script is None else script
    conn = uptime.open_ledger(path)
    ts = start
    for observations in script:
        uptime.run_pass(conn, targets, _scripted(observations), ts=ts)
        ts += step
    conn.close()
    return ts - step


def _seed_stale_daemon(path, *, beat_ts=T0, sweep_now=T0 + 600.0, grace_s=60.0):
    """One confirmed-stale daemon — heartbeat writes BOTH an alert event AND an
    open incident, which is the double-page fixture this router must collapse."""
    conn = heartbeat.open_registry(path)
    heartbeat.beat(conn, "trainer", ts=beat_ts, note="training step loop")
    heartbeat.sweep(
        conn, {"trainer": {"kind": "beat", "grace_s": grace_s}}, now=sweep_now
    )
    conn.close()


def _cert(host, *, not_after="Aug  1 00:00:00 2027 GMT"):
    return {
        "subject": ((("commonName", host),),),
        "issuer": ((("commonName", "Example CA"),),),
        "notBefore": "Jan  1 00:00:00 2020 GMT",
        "notAfter": not_after,
        "subjectAltName": (("DNS", host),),
    }


def _seed_cert_finding(path, host="www.bhenre.com", *, ts=T0):
    """certmon records a warning (no HSTS) -> a kind='cert' event on the timeline."""
    conn = certmon.open_cert_ledger(path)
    certmon.run_pass(
        conn,
        [host],
        lambda h: {
            "cert": _cert(h),
            "protocol": "TLSv1.3",
            "hsts": False,
            "error": None,
            "verified": True,
        },
        now=ts,
    )
    conn.close()


def _event(path, *, kind, message, target=None, ts=T0):
    conn = uptime.open_ledger(path)
    uptime.record_event(conn, kind=kind, message=message, target=target, ts=ts)
    conn.close()


def _recorder(*, fail=(), boom=(), detail="delivered"):
    """The injected dispatch boundary: records calls, fabricates outcomes."""
    calls = []

    def dispatch(name, cfg, alert):
        calls.append({"channel": name, "kind": cfg["kind"], "alert": alert})
        if name in boom:
            raise RuntimeError(f"{name} exploded")
        if name in fail:
            return {"ok": False, "detail": f"{name} refused"}
        return {"ok": True, "detail": detail}

    dispatch.calls = calls
    return dispatch


def _config_file(tmp_path, doc, name="alerts.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _wired(tmp_path, **overlay):
    """Config with BOTH channels configured (loopback endpoints, never dialed)."""
    doc = {
        "channels": {
            "webhook": {"url": "http://127.0.0.1:9099/hook"},
            "email": {"host": "127.0.0.1", "from": "scout@box", "to": ["ops@box"]},
        }
    }
    for section, entries in overlay.items():
        doc.setdefault(section, {})
        for name, cfg in entries.items():
            if isinstance(cfg, dict) and isinstance(doc[section].get(name), dict):
                doc[section][name].update(cfg)
            else:
                doc[section][name] = cfg
    return alerts.load_config(_config_file(tmp_path, doc))


def _open(path):
    return alerts.open_alert_ledger(path)


def _rows(path):
    conn = _open(path)
    n = conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
    conn.close()
    return int(n)


# ---- config: policy-as-config, and a typo is never silently ignored ----------


def test_default_rules_cover_every_producer_and_declare_the_ignored_kinds():
    cfg = alerts.load_config()
    rules = cfg["rules"]
    # one rule per signal the monitoring family actually writes
    assert set(rules) == {
        "incident:down",
        "incident:degraded",
        "event:alert",
        "event:cert",
        "event:recovery",
        "event:deploy",
        "event:note",
    }
    assert rules["incident:down"]["severity"] == "error"
    assert rules["incident:degraded"]["severity"] == "warning"
    assert rules["event:alert"]["severity"] == "error"
    assert rules["event:cert"]["severity"] == "warning"
    assert rules["event:recovery"]["severity"] == "info"
    # deploy markers and ops notes are KNOWN and deliberately never paged
    assert rules["event:deploy"]["route"] is False
    assert rules["event:note"]["route"] is False
    assert "severity" not in rules["event:deploy"]
    for rid, rule in rules.items():
        assert isinstance(rule["route"], bool), rid  # normalized on every rule
        if rule["route"]:
            assert rule["dedup_s"] > 0, rid
            # a rule may never aim at a channel that does not exist
            assert set(rule["channels"]) <= set(cfg["channels"]), rid


def test_default_channels_ship_undeliverable_on_purpose():
    """The headline invariant: an unwired router must not look like a quiet night."""
    cfg = alerts.load_config()
    assert sorted(cfg["channels"]) == ["email", "webhook"]
    for name, ch in cfg["channels"].items():
        ready, why = alerts.channel_ready(ch)
        assert ready is False, name
        assert "not configured" in why
    # ...yet the rules still NAME them, so the first route reports the failure
    assert alerts.DEFAULT_RULES["incident:down"]["channels"] == ["webhook", "email"]


def test_overlay_merges_key_by_key_and_false_drops_an_entry(tmp_path):
    cfg = alerts.load_config(
        _config_file(
            tmp_path,
            {
                "rules": {
                    "incident:down": {"dedup_s": 60},
                    "event:recovery": False,
                    "event:cert": {"enabled": False},
                    "event:quota": {"severity": "warning", "channels": []},
                },
                "channels": {"webhook": {"url": "https://hooks.example.com/x"}},
            },
        )
    )
    down = cfg["rules"]["incident:down"]
    assert down["dedup_s"] == 60.0  # scalar replaced
    assert down["severity"] == "error"  # untouched keys survive the merge
    assert down["channels"] == ["webhook", "email"]
    assert "event:recovery" not in cfg["rules"]  # bare false drops
    assert "event:cert" not in cfg["rules"]  # {"enabled": false} drops
    assert cfg["rules"]["event:quota"]["route"] is True  # a NEW rule is routable
    assert cfg["rules"]["event:quota"]["dedup_s"] == alerts.DEFAULT_DEDUP_S
    ch = cfg["channels"]["webhook"]
    assert ch["url"] == "https://hooks.example.com/x"
    assert ch["kind"] == "webhook" and ch["timeout_s"] == alerts.DEFAULT_TIMEOUT_S


def test_loaded_config_never_mutates_the_module_defaults(tmp_path):
    cfg = alerts.load_config()
    cfg["rules"]["incident:down"]["channels"].append("pigeon")
    cfg["channels"]["email"]["host"] = "leaked"
    fresh = alerts.load_config()
    assert fresh["rules"]["incident:down"]["channels"] == ["webhook", "email"]
    assert fresh["channels"]["email"]["host"] is None
    assert alerts.DEFAULT_RULES["incident:down"]["channels"] == ["webhook", "email"]


def test_config_typos_are_errors_not_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match="unknown config section"):
        alerts.load_config(_config_file(tmp_path, {"rulez": {}}))
    with pytest.raises(ValueError, match="must be a JSON object"):
        alerts.load_config(_config_file(tmp_path, ["nope"]))
    with pytest.raises(json.JSONDecodeError):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        alerts.load_config(p)
    with pytest.raises(OSError):
        alerts.load_config(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("rule", "match"),
    [
        ({"severity": "critical", "channels": []}, "severity must be one of"),
        ({"channels": ["pigeon"]}, "unknown channel"),
        ({"channels": "webhook"}, "channels must be a list"),
        ({"dedup_s": 0}, "dedup_s must be positive"),
        ({"dedup_s": True}, "dedup_s must be positive"),
        ({"dedup_s": "soon"}, "dedup_s must be positive"),
        ("not-an-object", "must be an object or false"),
    ],
)
def test_rule_validation_refuses_a_config_that_would_drop_pages(tmp_path, rule, match):
    with pytest.raises(ValueError, match=match):
        alerts.load_config(_config_file(tmp_path, {"rules": {"incident:down": rule}}))


@pytest.mark.parametrize(
    ("channel", "match"),
    [
        ({"kind": "carrier-pigeon"}, "kind must be one of"),
        ({"kind": "webhook", "url": "file:///etc/passwd"}, "url must be http"),
        ({"kind": "webhook", "url": 7}, "url must be http"),
        ({"kind": "email", "to": "ops@box"}, "'to' must be a list"),
        ({"kind": "email", "timeout_s": -1}, "timeout_s must be positive"),
    ],
)
def test_channel_validation_refuses_an_undialable_endpoint(tmp_path, channel, match):
    with pytest.raises(ValueError, match=match):
        alerts.load_config(_config_file(tmp_path, {"channels": {"c": channel}}))


def test_dropping_a_channel_a_rule_still_names_is_a_hard_error(tmp_path):
    """Silently keeping the rule would page nobody and report success."""
    with pytest.raises(ValueError, match="unknown channel 'email'"):
        alerts.load_config(_config_file(tmp_path, {"channels": {"email": False}}))


def test_channel_ready_names_exactly_what_is_missing(tmp_path):
    cfg = alerts.load_config()
    assert alerts.channel_ready(cfg["channels"]["webhook"]) == (
        False,
        "channel not configured: webhook has no url",
    )
    email = dict(cfg["channels"]["email"], host="127.0.0.1")
    ready, why = alerts.channel_ready(email)
    assert ready is False and "from" in why and "to" in why and "host" not in why
    wired = _wired(tmp_path)["channels"]
    assert alerts.channel_ready(wired["webhook"]) == (True, "ok")
    assert alerts.channel_ready(wired["email"]) == (True, "ok")


# ---- the dedup key ----------------------------------------------------------


def test_fingerprint_is_target_and_severity_only():
    fp = alerts.fingerprint("zeta", "error")
    assert fp == alerts.fingerprint("zeta", "error")  # stable
    assert len(fp) == 16 and int(fp, 16) >= 0  # hex digest, not a raw string
    assert fp != alerts.fingerprint("zeta", "warning")  # severity matters
    assert fp != alerts.fingerprint("alpha", "error")  # target matters
    assert alerts.fingerprint(None, "info") == alerts.fingerprint(None, "info")
    assert alerts.fingerprint(None, "info") != alerts.fingerprint("zeta", "info")


# ---- signals: what the ledger says is wrong ---------------------------------


def test_an_open_incident_is_a_candidate_and_a_closed_one_is_not(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    conn = _open(db)
    routable, unrouted = alerts.candidates(
        conn, alerts.DEFAULT_RULES, now=T0 + 300.0
    )
    assert unrouted == []
    assert len(routable) == 1
    c = routable[0]
    assert c["signal"] == "incident" and c["rule"] == "incident:down"
    assert c["severity"] == "error" and c["target"] == "zeta"
    assert c["channels"] == ["webhook", "email"] and c["dedup_s"] == 1800.0
    assert c["ts"] == T0 and c["key"] == "incident:1"
    assert "zeta down since 2025-10-09" in c["message"]
    assert "open 5m" in c["message"]  # the nag needs to say how long
    assert c["fingerprint"] == alerts.fingerprint("zeta", "error")
    conn.close()
    # recovery closes it -> nothing left to page about
    _seed_uptime(db, script=[[UP], [UP]], start=T0 + 60.0)
    conn = _open(db)
    assert alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 300.0)[0] == []
    conn.close()


def test_lookback_bounds_events_but_never_an_open_incident(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)  # incident opens at T0
    _event(db, kind="alert", message="trainer stale", target="hb:trainer", ts=T0)
    conn = _open(db)
    now = T0 + 10 * DAY  # both signals are ancient
    fresh = alerts.candidates(conn, alerts.DEFAULT_RULES, now=now, lookback_s=3600.0)[0]
    rules_hit = {c["rule"] for c in fresh}
    # the event fell out of the window; the still-open outage did NOT
    assert rules_hit == {"incident:down"}
    assert "open 10.0d" in fresh[0]["message"]
    wide = alerts.candidates(
        conn, alerts.DEFAULT_RULES, now=now, lookback_s=11 * DAY
    )[0]
    assert {c["rule"] for c in wide} == {"incident:down", "event:alert"}
    conn.close()


def test_deploy_markers_and_notes_page_nobody_and_raise_no_noise(tmp_path):
    db = tmp_path / "uptime.db"
    _event(db, kind="deploy", message="bhenre 4009c52", target="zeta", ts=T0)
    _event(db, kind="note", message="clocks at 780MHz", ts=T0)
    conn = _open(db)
    routable, unrouted = alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 10.0)
    conn.close()
    # route: false means known-and-ignored: no page AND no unrouted finding
    assert routable == [] and unrouted == []


def test_a_signal_with_no_rule_is_reported_not_dropped(tmp_path):
    db = tmp_path / "uptime.db"
    _event(db, kind="quota", message="gpu hours 92% used", target="ava", ts=T0)
    conn = _open(db)
    routable, unrouted = alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 10.0)
    conn.close()
    assert routable == []
    assert len(unrouted) == 1
    assert unrouted[0]["rule"] == "event:quota" and unrouted[0]["target"] == "ava"
    assert "no rule matches" in unrouted[0]["reason"]
    assert unrouted[0]["message"] == "gpu hours 92% used"


def test_certmon_findings_route_as_warnings_to_the_email_channel(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_cert_finding(db, ts=T0)
    conn = _open(db)
    routable, unrouted = alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 5.0)
    conn.close()
    assert unrouted == [] and len(routable) == 1
    c = routable[0]
    assert c["rule"] == "event:cert" and c["severity"] == "warning"
    assert c["target"] == "www.bhenre.com" and c["channels"] == ["email"]
    assert c["dedup_s"] == 86400.0  # a cert problem is daily news, not hourly
    assert "Strict-Transport-Security" in c["message"]


# ---- collapse: one problem, one page ----------------------------------------


def test_one_stale_daemon_pages_once_even_though_it_writes_two_signals(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_stale_daemon(db)  # writes kind="alert" AND opens an incident
    conn = _open(db)
    routable, _ = alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 700.0)
    conn.close()
    # two genuine ledger signals for one broken daemon...
    assert sorted(c["rule"] for c in routable) == ["event:alert", "incident:down"]
    assert len({c["fingerprint"] for c in routable}) == 1
    planned = alerts.collapse(routable)
    # ...collapsed into exactly one page that still carries both messages
    assert len(planned) == 1
    page = planned[0]
    assert page["rule"] == "event:alert" and page["collapsed"] == 1
    assert len(page["also"]) == 1 and "down since" in page["also"][0]
    assert page["target"] == "hb:trainer" and page["severity"] == "error"
    assert page["channels"] == ["webhook", "email"]  # the winner's fan-out


def test_collapse_keeps_the_worst_severity_and_separates_other_severities():
    def cand(rule, severity, target, ts, message):
        return {
            "signal": "event",
            "rule": rule,
            "severity": severity,
            "target": target,
            "ts": ts,
            "message": message,
            "key": rule,
            "channels": [rule],
            "dedup_s": 60.0,
            "fingerprint": alerts.fingerprint(target, severity),
        }

    out = alerts.collapse(
        [
            cand("event:cert", "warning", "zeta", T0, "cert warn"),
            cand("event:alert", "error", "zeta", T0, "hard down"),
            cand("event:recovery", "info", "zeta", T0, "back up"),
            cand("event:alert", "error", "zeta", T0 + 5.0, "still down"),
        ]
    )
    assert [a["severity"] for a in out] == ["error", "warning", "info"]  # worst first
    assert out[0]["message"] == "still down" and out[0]["collapsed"] == 1
    assert out[0]["also"] == ["hard down"]  # newest of the pair leads
    assert out[0]["channels"] == ["event:alert"]
    assert out[1]["collapsed"] == 0 and out[1]["also"] == []
    assert out[2]["message"] == "back up"  # a recovery is never swallowed


def test_two_flapping_messages_in_one_pass_are_one_page(tmp_path):
    """The message carries a changing age; fingerprinting it would defeat dedup."""
    db = tmp_path / "uptime.db"
    _event(db, kind="alert", message="trainer stale — 600.0s since beat",
           target="hb:trainer", ts=T0)
    _event(db, kind="alert", message="trainer stale — 1200.0s since beat",
           target="hb:trainer", ts=T0 + 600.0)
    conn = _open(db)
    routable, _ = alerts.candidates(conn, alerts.DEFAULT_RULES, now=T0 + 700.0)
    conn.close()
    assert len({c["message"] for c in routable}) == 2  # the texts really do differ
    planned = alerts.collapse(routable)
    assert len(planned) == 1 and planned[0]["collapsed"] == 1
    assert "1200.0s" in planned[0]["message"]  # newest leads


# ---- suppression windows ----------------------------------------------------


def test_suppressed_window_is_inclusive_and_never_suppresses_a_first_page():
    assert alerts.suppressed(T0, None, 1800.0) is False  # never delivered
    assert alerts.suppressed(T0 + 1.0, T0, 1800.0) is True
    assert alerts.suppressed(T0 + 1800.0, T0, 1800.0) is True  # edge still muted
    assert alerts.suppressed(T0 + 1800.1, T0, 1800.0) is False  # the nag fires
    assert alerts.suppressed(T0, T0, 0.5) is True


def test_route_dispatches_then_suppresses_then_nags_again(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()

    first = alerts.route(conn, cfg, d, now=T0 + 10.0)
    assert first["counts"]["candidates"] == 1 and first["counts"]["planned"] == 1
    a = first["alerts"][0]
    assert a["status"] == alerts.STATUS_SENT
    assert sorted(a["results"]) == ["email", "webhook"]
    assert all(r["ok"] is True for r in a["results"].values())
    assert a["last_dispatch_ts"] is None  # nothing had been delivered before
    assert [c["channel"] for c in d.calls] == ["webhook", "email"]
    assert d.calls[0]["kind"] == "webhook" and d.calls[1]["kind"] == "email"
    assert first["counts"]["by_status"] == {alerts.STATUS_SENT: 1}
    assert first["counts"]["by_severity"] == {"error": 1}

    second = alerts.route(conn, cfg, d, now=T0 + 20.0)
    b = second["alerts"][0]
    assert b["status"] == alerts.STATUS_SUPPRESSED
    assert b["retry_in_s"] == 1790.0 and b["last_dispatch_ts"] == T0 + 10.0
    assert b["results"] == {}
    assert len(d.calls) == 2, "a suppressed alert must not touch a channel"
    assert _rows(db) == 1, "suppression is derivable; it is not a ledger row"

    third = alerts.route(conn, cfg, d, now=T0 + 10.0 + 1800.1)
    assert third["alerts"][0]["status"] == alerts.STATUS_SENT
    assert len(d.calls) == 4  # the re-notify cadence IS the dedup window
    assert _rows(db) == 2
    conn.close()


def test_a_later_flap_with_a_new_message_is_still_suppressed(tmp_path):
    db = tmp_path / "uptime.db"
    _event(db, kind="alert", message="trainer stale — 600.0s", target="hb:trainer",
           ts=T0)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()
    assert alerts.route(conn, cfg, d, now=T0 + 5.0)["alerts"][0]["status"] == "sent"
    conn.close()
    _event(db, kind="alert", message="trainer stale — 1800.0s", target="hb:trainer",
           ts=T0 + 60.0)
    conn = _open(db)
    again = alerts.route(conn, cfg, d, now=T0 + 65.0)
    conn.close()
    assert again["alerts"][0]["status"] == alerts.STATUS_SUPPRESSED
    assert len(d.calls) == 2  # webhook+email once, not twice


def test_a_failed_delivery_does_not_start_the_dedup_clock(tmp_path):
    """A broken channel must retry next pass, not be muted for the window."""
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder(fail=("webhook", "email"))
    first = alerts.route(conn, cfg, d, now=T0 + 10.0)
    assert first["alerts"][0]["status"] == alerts.STATUS_FAILED
    assert alerts.last_dispatch_ts(conn, first["alerts"][0]["fingerprint"]) is None
    retry = alerts.route(conn, cfg, _recorder(), now=T0 + 20.0)
    assert retry["alerts"][0]["status"] == alerts.STATUS_SENT
    assert _rows(db) == 2  # both attempts are on the record
    conn.close()


def test_a_partial_delivery_does_start_the_clock(tmp_path):
    """Re-paging the channel that worked is worse than losing one retry."""
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder(fail=("webhook",))
    first = alerts.route(conn, cfg, d, now=T0 + 10.0)
    a = first["alerts"][0]
    assert a["status"] == alerts.STATUS_PARTIAL
    assert a["results"]["webhook"]["ok"] is False
    assert a["results"]["email"]["ok"] is True
    assert alerts.last_dispatch_ts(conn, a["fingerprint"]) == T0 + 10.0
    assert alerts.route(conn, cfg, d, now=T0 + 20.0)["alerts"][0]["status"] == (
        alerts.STATUS_SUPPRESSED
    )
    conn.close()


def test_a_dry_run_writes_nothing_and_cannot_silence_the_real_page(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()
    rehearsal = alerts.route(conn, cfg, d, now=T0 + 10.0, dry_run=True)
    assert rehearsal["dry_run"] is True
    assert rehearsal["alerts"][0]["status"] == alerts.STATUS_DRY_RUN
    assert rehearsal["alerts"][0]["results"] == {}
    assert d.calls == [] and _rows(db) == 0
    real = alerts.route(conn, cfg, d, now=T0 + 11.0)
    assert real["alerts"][0]["status"] == alerts.STATUS_SENT
    assert len(d.calls) == 2 and _rows(db) == 1
    conn.close()


def test_min_severity_filters_without_dispatching_or_recording(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_cert_finding(db, ts=T0)  # a warning
    _event(db, kind="recovery", message="zeta recovered", target="zeta", ts=T0)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()
    res = alerts.route(conn, cfg, d, now=T0 + 5.0, min_severity="warning")
    conn.close()
    assert [a["severity"] for a in res["alerts"]] == ["warning"]
    assert res["filtered"] == [
        {"rule": "event:recovery", "target": "zeta", "severity": "info"}
    ]
    assert [c["channel"] for c in d.calls] == ["email"]  # the cert rule's fan-out
    assert _rows(db) == 1


def test_a_rule_with_no_channels_is_recorded_not_pretend_sent(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path, rules={"incident:down": {"channels": [], "dedup_s": 300}})
    conn = _open(db)
    d = _recorder()
    res = alerts.route(conn, cfg, d, now=T0 + 10.0)
    a = res["alerts"][0]
    assert a["status"] == alerts.STATUS_RECORDED and a["results"] == {}
    assert d.calls == [], "channels: [] means log it, do not page"
    assert alerts.last_dispatch_ts(conn, a["fingerprint"]) == T0 + 10.0
    assert alerts.route(conn, cfg, d, now=T0 + 20.0)["alerts"][0]["status"] == (
        alerts.STATUS_SUPPRESSED
    )
    conn.close()


def test_an_unconfigured_channel_fails_loudly_without_calling_a_sender(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    conn = _open(db)
    d = _recorder()
    res = alerts.route(conn, alerts.load_config(), d, now=T0 + 10.0)
    conn.close()
    a = res["alerts"][0]
    assert a["status"] == alerts.STATUS_FAILED
    assert d.calls == [], "an unwired channel must never reach the sender"
    assert a["results"]["webhook"]["detail"] == (
        "channel not configured: webhook has no url"
    )
    assert a["results"]["email"]["ok"] is False


# ---- dispatch mechanics -----------------------------------------------------


def test_one_exploding_sender_cannot_stop_the_other_channel(tmp_path):
    cfg = _wired(tmp_path)
    alert = alerts.probe_alert(severity="error", channels=["webhook", "email"], ts=T0)
    d = _recorder(boom=("webhook",))
    results = alerts.dispatch_channels(alert, cfg["channels"], d)
    assert results["webhook"]["ok"] is False
    assert "RuntimeError: webhook exploded" in results["webhook"]["detail"]
    assert results["email"]["ok"] is True
    assert alerts.outcome_status(alert["channels"], results) == alerts.STATUS_PARTIAL


def test_dispatch_channels_reports_an_injected_unknown_channel(tmp_path):
    alert = alerts.probe_alert(severity="info", channels=["pigeon"], ts=T0)
    results = alerts.dispatch_channels(alert, {}, _recorder())
    assert results == {"pigeon": {"ok": False, "detail": "unknown channel 'pigeon'"}}


def test_outcome_status_matrix():
    ok = {"ok": True, "detail": "x"}
    no = {"ok": False, "detail": "x"}
    assert alerts.outcome_status([], {}) == alerts.STATUS_RECORDED
    assert alerts.outcome_status(["a"], {"a": ok}) == alerts.STATUS_SENT
    assert alerts.outcome_status(["a", "b"], {"a": ok, "b": ok}) == alerts.STATUS_SENT
    assert alerts.outcome_status(["a", "b"], {"a": ok, "b": no}) == (
        alerts.STATUS_PARTIAL
    )
    assert alerts.outcome_status(["a", "b"], {"a": no, "b": no}) == alerts.STATUS_FAILED
    # a channel that never answered at all is not a success
    assert alerts.outcome_status(["a", "b"], {"a": ok}) == alerts.STATUS_PARTIAL


def test_probe_alert_cannot_collide_with_a_real_alerts_window(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()
    drill = alerts.probe_alert(severity="error", channels=["email"], ts=T0, note="drill")
    sent = alerts.send_one(conn, drill, cfg["channels"], d, ts=T0)
    assert sent["status"] == alerts.STATUS_SENT and sent["alert_id"] == 1
    assert drill["target"] == "alerts:test" and drill["message"] == "drill"
    # the real error page for zeta is untouched by the drill's clock
    res = alerts.route(conn, cfg, d, now=T0 + 5.0)
    conn.close()
    assert res["alerts"][0]["status"] == alerts.STATUS_SENT
    assert res["alerts"][0]["fingerprint"] != drill["fingerprint"]


def test_probe_alert_default_message_names_the_time(tmp_path):
    drill = alerts.probe_alert(channels=[], ts=T0)
    assert drill["severity"] == "info" and drill["signal"] == "test"
    assert drill["rule"] == "alerts:test" and drill["also"] == []
    assert "2025-10-09" in drill["message"] and "test alert" in drill["message"]


# ---- the ledger reads -------------------------------------------------------


def test_history_decodes_the_delivery_record(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_stale_daemon(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    alerts.route(conn, cfg, _recorder(fail=("email",)), now=T0 + 700.0)
    rows = alerts.history(conn, limit=5)
    conn.close()
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == alerts.STATUS_PARTIAL and r["delivered"] is True
    assert r["channels"] == ["webhook", "email"]
    assert r["results"]["webhook"]["ok"] is True
    assert r["results"]["email"]["ok"] is False
    assert len(r["also"]) == 1  # the collapsed sibling survives in the record
    assert r["target"] == "hb:trainer" and r["severity"] == "error"
    assert r["signal"] == "event" and r["rule"] == "event:alert"
    assert r["ts"] == T0 + 700.0


def test_history_filters_by_fingerprint_newest_first(tmp_path):
    db = tmp_path / "uptime.db"
    conn = _open(db)
    fp = alerts.fingerprint("zeta", "error")
    for i, status in enumerate((alerts.STATUS_FAILED, alerts.STATUS_SENT)):
        alerts.record_alert(
            conn,
            {
                "fingerprint": fp, "rule": "incident:down", "signal": "incident",
                "severity": "error", "target": "zeta", "message": f"pass {i}",
                "channels": ["email"], "status": status, "results": {}, "also": [],
            },
            ts=T0 + i,
        )
    alerts.record_alert(
        conn,
        {
            "fingerprint": "other", "rule": "event:cert", "signal": "event",
            "severity": "warning", "target": "www.bhenre.com", "message": "cert",
            "channels": [], "status": alerts.STATUS_RECORDED, "results": {}, "also": [],
        },
        ts=T0 + 9,
    )
    assert [r["message"] for r in alerts.history(conn, fingerprint=fp)] == [
        "pass 1",
        "pass 0",
    ]
    assert len(alerts.history(conn)) == 3
    assert alerts.history(conn, limit=1)[0]["message"] == "cert"
    # only delivered statuses set the dedup clock
    assert alerts.last_dispatch_ts(conn, fp) == T0 + 1
    assert alerts.last_dispatch_ts(conn, "nope") is None
    conn.close()


def test_board_explains_why_nobody_was_paged(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path, rules={"incident:down": {"dedup_s": 600}})
    conn = _open(db)
    alerts.route(conn, cfg, _recorder(), now=T0 + 10.0)
    inside = alerts.board(conn, cfg["rules"], now=T0 + 100.0)
    assert len(inside) == 1
    row = inside[0]
    assert row["target"] == "zeta" and row["rule"] == "incident:down"
    assert row["alerts"] == 1 and row["last_status"] == alerts.STATUS_SENT
    assert row["dedup_s"] == 600.0 and row["suppressed"] is True
    assert row["retry_in_s"] == 510.0
    assert row["last_delivered_ts"] == T0 + 10.0 and row["last_ts"] == T0 + 10.0
    later = alerts.board(conn, cfg["rules"], now=T0 + 10.0 + 601.0)
    assert later[0]["suppressed"] is False and later[0]["retry_in_s"] == 0.0
    conn.close()


def test_board_never_reports_a_failed_only_fingerprint_as_muted(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    alerts.route(conn, cfg, _recorder(fail=("webhook", "email")), now=T0 + 10.0)
    row = alerts.board(conn, cfg["rules"], now=T0 + 20.0)[0]
    conn.close()
    assert row["last_status"] == alerts.STATUS_FAILED
    assert row["last_delivered_ts"] is None
    assert row["suppressed"] is False and row["retry_in_s"] == 0.0


def test_source_summary_tells_no_signal_apart_from_no_problem(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    conn = _open(db)
    src = alerts.source_summary(conn, now=T0 + 10.0)
    assert src["uptime"]["open_incidents"] == 1 and src["uptime"]["openswap"] == "#2"
    assert src["events"]["rows"] == 0 and src["events"]["by_kind"] == {}
    # certmon/heartbeat never recorded here: that is a monitoring gap, not calm
    assert src["certmon"]["table_present"] is False
    assert src["certmon"]["present"] is False and src["certmon"]["rows"] == 0
    assert src["heartbeat"]["table_present"] is False
    conn.close()
    _seed_cert_finding(db, ts=T0)
    _seed_stale_daemon(db)
    conn = _open(db)
    src2 = alerts.source_summary(conn, now=T0 + 700.0, lookback_s=3600.0)
    conn.close()
    assert src2["certmon"]["table_present"] is True and src2["certmon"]["rows"] == 1
    assert src2["heartbeat"]["present"] is True and src2["heartbeat"]["rows"] == 1
    assert src2["events"]["by_kind"] == {"alert": 1, "cert": 1}
    assert src2["events"]["rows"] == 2 and src2["events"]["newest_ts"] == T0 + 600.0
    assert src2["uptime"]["open_incidents"] == 2  # zeta + hb:trainer


def test_events_outside_the_window_are_not_counted_as_signal(tmp_path):
    db = tmp_path / "uptime.db"
    _event(db, kind="alert", message="old", target="hb:trainer", ts=T0)
    conn = _open(db)
    assert alerts.source_summary(conn, now=T0 + 10.0)["events"]["rows"] == 1
    stale = alerts.source_summary(conn, now=T0 + 10 * DAY, lookback_s=3600.0)
    conn.close()
    assert stale["events"]["rows"] == 0 and stale["events"]["newest_ts"] is None


# ---- the wire format --------------------------------------------------------


def test_wire_payload_is_the_stable_machine_view():
    alert = alerts.probe_alert(severity="error", channels=["webhook"], ts=T0, note="hi")
    alert["also"] = ["and this"]
    p = alerts.wire_payload(alert)
    assert p["source"] == "scout-alerts" and p["openswap"] == "#19"
    assert p["severity"] == "error" and p["message"] == "hi"
    assert p["target"] == "alerts:test" and p["rule"] == "alerts:test"
    assert p["also"] == ["and this"] and p["fingerprint"] == alert["fingerprint"]
    assert p["ts"] == T0 and p["iso"] == "2025-10-09 08:53:20Z"
    assert json.loads(json.dumps(p)) == p  # JSON-able by contract


def test_email_subject_and_body_carry_the_provenance():
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0,
                              note="zeta down since forever")
    alert["also"] = ["hb:trainer down since 2025-10-09"]
    subject = alerts.email_subject(alert)
    assert subject.startswith("[error] alerts:test — ")
    assert "zeta down since forever" in subject
    body = alerts.email_body(alert)
    assert "zeta down since forever" in body
    assert "severity : error" in body and "rule     : alerts:test (test)" in body
    assert f"fpr      : {alert['fingerprint']}" in body
    assert "also on this target (1 collapsed):" in body
    assert "  - hb:trainer down since 2025-10-09" in body
    assert "openswap #19" in body and "No SaaS saw this." in body
    assert "2025-10-09 08:53:20Z" in body


def test_email_subject_survives_a_multiline_message():
    alert = alerts.probe_alert(severity="info", channels=[], ts=T0,
                              note="line one\nline two")
    assert "\n" not in alerts.email_subject(alert)
    assert "line one" in alerts.email_subject(alert)
    assert "line two" in alerts.email_body(alert)


def test_email_body_omits_the_collapsed_block_when_nothing_collapsed():
    alert = alerts.probe_alert(severity="info", channels=[], ts=T0)
    assert "collapsed" not in alerts.email_body(alert)


# ---- family diagnostics -----------------------------------------------------


def test_diagnostics_map_the_pass_onto_the_family_schema(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    _seed_cert_finding(db, ts=T0)
    _event(db, kind="quota", message="gpu hours 92%", target="ava", ts=T0)
    cfg = _wired(tmp_path)
    conn = _open(db)
    res = alerts.route(conn, cfg, _recorder(), now=T0 + 10.0)
    conn.close()
    diags = alerts.to_diagnostics(res)
    by_rule = {}
    for d in diags:
        by_rule.setdefault(d["rule"], []).append(d)
    assert set(by_rule) == {"alerts:fired", "alerts:unrouted"}
    fired = {d["severity"] for d in by_rule["alerts:fired"]}
    assert fired == {"error", "warning"}  # the alert's OWN severity, not a constant
    assert all(d["line"] == 0 and d["col"] == 0 for d in diags)
    assert {d["path"] for d in by_rule["alerts:fired"]} == {"zeta", "www.bhenre.com"}
    gap = by_rule["alerts:unrouted"][0]
    assert gap["severity"] == "info" and gap["path"] == "ava"
    assert "event:quota" in gap["message"] and "route: false" in gap["suggestion"]
    summary = openswap.summarize(diags)
    assert summary["total"] == 3
    assert summary["by_severity"] == {
        "error": 1, "warning": 1, "suggestion": 0, "info": 1
    }
    assert summary["by_rule"] == {"alerts:fired": 2, "alerts:unrouted": 1}


def test_an_undeliverable_router_is_an_error_even_with_a_green_fleet(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_cert_finding(db, ts=T0)  # only a WARNING signal exists
    conn = _open(db)
    res = alerts.route(conn, alerts.load_config(), _recorder(), now=T0 + 5.0)
    conn.close()
    diags = alerts.to_diagnostics(res)
    assert [d["rule"] for d in diags] == ["alerts:undeliverable"]
    assert diags[0]["severity"] == "error"  # escalated ABOVE the alert's warning
    assert "not delivered (failed)" in diags[0]["message"]
    assert "email" in diags[0]["message"] and "not configured" in diags[0]["message"]
    assert "re-run" in diags[0]["suggestion"]
    assert openswap.summarize(diags)["by_severity"]["error"] == 1


def test_a_suppressed_alert_says_nothing_and_a_dry_run_still_reports(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _wired(tmp_path)
    conn = _open(db)
    d = _recorder()
    alerts.route(conn, cfg, d, now=T0 + 10.0)
    quiet = alerts.route(conn, cfg, d, now=T0 + 20.0)
    assert quiet["alerts"][0]["status"] == alerts.STATUS_SUPPRESSED
    assert alerts.to_diagnostics(quiet) == []  # the operator was already told
    rehearsal = alerts.route(conn, cfg, d, now=T0 + 5000.0, dry_run=True)
    conn.close()
    fired = alerts.to_diagnostics(rehearsal)
    assert [d0["rule"] for d0 in fired] == ["alerts:fired"]
    assert fired[0]["message"].startswith("dry-run: ")


# ---- the real senders, at their monkeypatched boundary ----------------------


def _cli():
    from bigbang.plugins.alerts import cli as alerts_cli

    return alerts_cli


def test_every_channel_kind_has_a_sender():
    """A kind added to the core without a sender here would drop pages silently."""
    assert set(_cli()._SENDERS) == set(alerts.CHANNEL_KINDS)


class _FakeResp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _fake_urlopen(captured, *, status=204):
    def urlopen(req, timeout=None):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "body": req.data,
                "headers": {k.lower(): v for k, v in req.header_items()},
                "timeout": timeout,
            }
        )
        return _FakeResp(status)

    return urlopen


def test_webhook_posts_the_wire_payload(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path)["channels"]["webhook"]
    alert = alerts.probe_alert(severity="error", channels=["webhook"], ts=T0, note="x")
    seen = []
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen(seen))
    r = cli._send_webhook(cfg, alert)
    assert r["ok"] is True and "http 204" in r["detail"]
    assert len(seen) == 1
    call = seen[0]
    assert call["url"] == "http://127.0.0.1:9099/hook" and call["method"] == "POST"
    assert call["headers"]["content-type"] == "application/json"
    assert call["headers"]["user-agent"] == "scout-alerts"
    assert call["timeout"] == alerts.DEFAULT_TIMEOUT_S
    assert json.loads(call["body"].decode("utf-8")) == alerts.wire_payload(alert)


def test_webhook_reports_http_and_transport_failures(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path)["channels"]["webhook"]
    alert = alerts.probe_alert(severity="info", channels=["webhook"], ts=T0)
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen([], status=500))
    assert cli._send_webhook(cfg, alert)["ok"] is False

    def boom(req, timeout=None):
        raise cli.urllib.error.HTTPError(cfg["url"], 503, "nope", None, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", boom)
    r = cli._send_webhook(cfg, alert)
    assert r["ok"] is False and "http 503" in r["detail"]

    def refused(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(cli.urllib.request, "urlopen", refused)
    r = cli._send_webhook(cfg, alert)
    assert r["ok"] is False and "OSError: connection refused" in r["detail"]


def test_a_webhook_host_outside_the_manifest_never_opens_a_socket(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path, channels={"webhook": {"url": "https://evil.example.com/x"}})
    alert = alerts.probe_alert(severity="error", channels=["webhook"], ts=T0)

    def never(req, timeout=None):
        raise AssertionError("policy-denied endpoint must not be dialed")

    monkeypatch.setattr(cli.urllib.request, "urlopen", never)
    r = cli._send_webhook(cfg["channels"]["webhook"], alert)
    assert r["ok"] is False
    assert r["detail"].startswith("policy denied:")
    assert "not in allowlist" in r["detail"]


def _fake_smtp(box, *, explode=None):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port, self.timeout = host, port, timeout
            self.starttls_called = False
            self.login_args = None
            self.sent = []
            box.append(self)
            if explode:
                raise explode

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def starttls(self):
            self.starttls_called = True

        def login(self, user, password):
            self.login_args = (user, password)

        def send_message(self, msg):
            self.sent.append(msg)

    return FakeSMTP


def test_email_hands_the_page_to_the_relay(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path, channels={"email": {"to": ["ops@box", "phone@box"]}})
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0, note="down")
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    r = cli._send_email(cfg["channels"]["email"], alert)
    assert r["ok"] is True and r["detail"] == "smtp 127.0.0.1:25 -> 2 rcpt"
    assert len(box) == 1
    smtp = box[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ("127.0.0.1", 25, 10.0)
    assert smtp.starttls_called is False and smtp.login_args is None
    msg = smtp.sent[0]
    assert msg["Subject"] == alerts.email_subject(alert)
    assert msg["From"] == "scout@box" and msg["To"] == "ops@box, phone@box"
    assert msg.get_content().strip() == alerts.email_body(alert).strip()


def test_email_reads_an_allowlisted_secret_and_starts_tls(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(
        tmp_path,
        channels={
            "email": {
                "starttls": True,
                "user": "scout",
                "password_env": "SCOUT_ALERTS_SMTP_PASSWORD",
            }
        },
    )
    monkeypatch.setenv("SCOUT_ALERTS_SMTP_PASSWORD", "hunter2")
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0)
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    assert cli._send_email(cfg["channels"]["email"], alert)["ok"] is True
    assert box[0].starttls_called is True
    assert box[0].login_args == ("scout", "hunter2")
    # the credential never rides along in the message itself
    assert "hunter2" not in alerts.email_body(alert)
    assert "hunter2" not in json.dumps(alerts.wire_payload(alert))


def test_a_secret_outside_the_manifest_allowlist_is_denied(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(
        tmp_path,
        channels={"email": {"user": "scout", "password_env": "AWS_SECRET_ACCESS_KEY"}},
    )
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-never-be-read")
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0)
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    r = cli._send_email(cfg["channels"]["email"], alert)
    assert r["ok"] is False and r["detail"].startswith("policy denied:")
    assert "AWS_SECRET_ACCESS_KEY" in r["detail"]
    assert box == [], "a denied secret must abort before the connection"


def test_an_smtp_host_outside_the_manifest_never_connects(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path, channels={"email": {"host": "smtp.sendgrid.net"}})
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0)
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    r = cli._send_email(cfg["channels"]["email"], alert)
    assert r["ok"] is False and r["detail"].startswith("policy denied:")
    assert box == []


def test_an_smtp_failure_is_a_failed_delivery_not_a_crash(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path)["channels"]["email"]
    alert = alerts.probe_alert(severity="error", channels=["email"], ts=T0)
    box = []
    monkeypatch.setattr(
        cli.smtplib, "SMTP", _fake_smtp(box, explode=TimeoutError("relay down"))
    )
    r = cli._send_email(cfg, alert)
    assert r["ok"] is False and "TimeoutError: relay down" in r["detail"]


def test_dispatch_routes_each_kind_to_its_own_sender(tmp_path, monkeypatch):
    cli = _cli()
    cfg = _wired(tmp_path)["channels"]
    alert = alerts.probe_alert(severity="info", channels=["webhook", "email"], ts=T0)
    seen, box = [], []
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen(seen))
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    assert cli._dispatch("webhook", cfg["webhook"], alert)["ok"] is True
    assert cli._dispatch("email", cfg["email"], alert)["ok"] is True
    assert len(seen) == 1 and len(box) == 1


# ---- policy + detection ------------------------------------------------------


def _plugin_dir() -> Path:
    return ROOT / "bigbang" / "plugins" / "alerts"


def test_manifest_is_default_deny_on_every_axis():
    from bigbang.core.policy import check_permission, load_manifest

    mf = load_manifest(_plugin_dir())
    assert mf["name"] == "alerts" and "openswap #19" in mf["description"]
    net = mf["capabilities"]["network"]
    assert net["enabled"] is True  # outbound delivery is the whole job
    assert "127.0.0.1" in net["domains"] and "localhost" in net["domains"]
    # no third-party pager/chat SaaS may be reachable — that would be PagerDuty
    # with extra steps
    assert not any(
        d.endswith(("pagerduty.com", "opsgenie.com", "slack.com"))
        for d in net["domains"]
    )
    assert check_permission(mf, "network", "http://127.0.0.1:9099/hook")[0] is True
    allowed, reason = check_permission(mf, "network", "https://evil.example.com/x")
    assert allowed is False and "not in allowlist" in reason
    assert check_permission(mf, "fs_write", ".scout/uptime.db")[0] is True
    # secrets are allowlisted BY NAME
    assert mf["capabilities"]["secrets"]["allow"] == ["SCOUT_ALERTS_SMTP_PASSWORD"]
    assert check_permission(mf, "secret", "SCOUT_ALERTS_SMTP_PASSWORD")[0] is True
    assert check_permission(mf, "secret", "AWS_SECRET_ACCESS_KEY")[0] is False


def test_detection_fallback_is_the_expected_steady_state(monkeypatch):
    cli = _cli()
    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = cli._capability()
    assert cap["adapter"] == "alerts" and cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "alertmanager" and cap["native"]["found"] is False
    assert cap["extras"]["pd"]["found"] is False  # the SaaS CLI, never executed
    assert cap["extras"]["amtool"]["found"] is False
    # tier is a capability report, not a dispatch switch
    assert cap["delegates"] is False
    assert "nothing to install" in cap["install_hint"]


def test_plugin_is_discoverable():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "alerts" in list_plugin_names()


# ---- the real CLI in a subprocess -------------------------------------------


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", "alerts", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_hello_envelope():
    r = _run(["hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["channel_kinds"] == ["email", "webhook"]
    assert "example" in data


def test_cli_rules_reports_an_unwired_router_as_unwired():
    r = _run(["rules"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["deliverable"] == []  # nothing is configured out of the box
    assert data["ignored"] == ["event:deploy", "event:note"]
    assert "incident:down" in data["routed"]
    assert data["channels"]["email"]["ready"] is False
    assert "not configured" in data["channels"]["webhook"]["why"]
    assert data["rules"]["incident:down"]["severity"] == "error"


def test_cli_route_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    r = _run(["route", "--db", str(db), "--dry-run"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["dry_run"] is True and data["counts"]["planned"] == 1
    assert data["alerts"][0]["status"] == "dry-run"
    assert data["alerts"][0]["target"] == "zeta"
    assert data["summary"]["by_rule"] == {"alerts:fired": 1}
    assert _rows(db) == 0


def test_cli_route_records_dedups_and_shows_it_in_status(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    cfg = _config_file(
        tmp_path, {"rules": {"incident:down": {"channels": [], "dedup_s": 3600}}}
    )
    r = _run(["route", "--db", str(db), "--config", str(cfg)])
    assert r.returncode == 0, r.stderr + r.stdout
    first = json.loads(r.stdout)["data"]
    assert first["alerts"][0]["status"] == "recorded"
    assert first["counts"]["by_status"] == {"recorded": 1}
    assert _rows(db) == 1

    r = _run(["route", "--db", str(db), "--config", str(cfg)])
    assert r.returncode == 0, r.stderr + r.stdout
    second = json.loads(r.stdout)["data"]
    assert second["alerts"][0]["status"] == "suppressed"
    assert second["alerts"][0]["retry_in_s"] > 3500.0
    assert second["diagnostics"] == []
    assert _rows(db) == 1, "a suppressed pass adds no ledger row"

    r = _run(["status", "--db", str(db), "--config", str(cfg)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["deliverable"] == []
    assert len(data["board"]) == 1
    assert data["board"][0]["suppressed"] is True
    assert data["board"][0]["target"] == "zeta"
    assert data["history"][0]["status"] == "recorded"
    assert data["history"][0]["delivered"] is True
    assert data["sources"]["uptime"]["open_incidents"] == 1
    assert data["sources"]["heartbeat"]["table_present"] is False


def test_cli_route_fails_loudly_when_no_channel_is_configured(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    r = _run(["route", "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout  # the pass itself completed
    data = json.loads(r.stdout)["data"]
    a = data["alerts"][0]
    assert a["status"] == "failed"
    assert a["results"]["webhook"]["ok"] is False
    assert "not configured" in a["results"]["email"]["detail"]
    assert [d["rule"] for d in data["diagnostics"]] == ["alerts:undeliverable"]
    assert data["summary"]["by_severity"]["error"] == 1
    # ...and the gate turns that into a nonzero exit for cron
    r = _run(["route", "--db", str(db), "--fail-on", "error"])
    assert r.returncode == 1
    assert json.loads(r.stdout)["data"]["alerts"][0]["status"] == "failed"


def test_cli_test_command_proves_the_wiring_or_exits_nonzero(tmp_path):
    db = tmp_path / "uptime.db"
    r = _run(["test", "--db", str(db), "--dry-run", "--severity", "warning"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["status"] == "dry-run" and data["channels"] == ["email", "webhook"]
    assert data["payload"]["severity"] == "warning"
    assert data["payload"]["target"] == "alerts:test"
    assert data["subject"].startswith("[warning] alerts:test")
    assert _rows(db) == 0

    r = _run(["test", "--db", str(db), "--note", "pager drill"])
    assert r.returncode == 1, "an unwired router must not report success"
    data = json.loads(r.stdout)["data"]
    assert data["status"] == "failed"
    assert data["payload"]["message"] == "pager drill"
    assert all(v["ok"] is False for v in data["results"].values())
    assert _rows(db) == 1  # the failed drill is on the record


def test_cli_rejects_bad_flags_and_bad_config(tmp_path):
    r = _run(["route", "--min-severity", "critical"])
    assert r.returncode == 1
    assert "--min-severity must be one of" in json.loads(r.stdout)["error"]
    r = _run(["route", "--lookback", "0"])
    assert r.returncode == 1
    assert "--lookback must be > 0" in json.loads(r.stdout)["error"]
    r = _run(["test", "--channel", "pigeon"])
    assert r.returncode == 1
    assert "unknown channel 'pigeon'" in json.loads(r.stdout)["error"]
    bad = _config_file(tmp_path, {"rules": {"incident:down": {"dedup_s": -5}}})
    r = _run(["rules", "--config", str(bad)])
    assert r.returncode == 1
    body = json.loads(r.stdout)
    assert "dedup_s must be positive" in body["error"] and "example" in body
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not a ledger\n" * 200, encoding="utf-8")
    r = _run(["route", "--db", str(junk)])
    assert r.returncode == 1
    assert "not a readable sqlite ledger" in json.loads(r.stdout)["error"]
