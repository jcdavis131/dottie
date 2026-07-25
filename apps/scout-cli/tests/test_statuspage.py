"""Statuspage — openswap #18 (StatusPage.io/Atlassian -> static HTML rendered
READ-ONLY from the shared uptime/certmon/heartbeat ledger). Pure-logic core
tests + the read-only enforcement + the no-data honesty contract + capability
detection + the subprocess envelope.

Offline and deterministic by construction: ledgers are seeded through the owning
plugins' OWN writers (uptime.run_pass with canned probe dicts, certmon.run_pass
with a fake getpeercert()-shaped fetcher, heartbeat.beat/sweep), every `now`/`ts`
is explicit, and no test opens a socket. The one thing these tests refuse to
allow is a fabricated number: several assert that an absent or stale ledger
produces NO percentage anywhere on the page.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bigbang.core import certmon, heartbeat, openswap, statuspage, uptime

ROOT = Path(__file__).resolve().parents[1]

# a fixed reference expiry; every other timestamp is derived from it so the
# whole fixture timeline is real-looking AND exact
NA = "Aug  1 00:00:00 2026 GMT"
NA_EPOCH = certmon.parse_cert_time(NA)
DAY = 86400.0
T0 = NA_EPOCH - 200 * DAY  # base epoch for seeded checks

UP = {"http": 200, "latency_ms": 50.0, "error": None, "body_head": ""}
DOWN = {"http": None, "latency_ms": 0.0, "error": "TimeoutError: x", "body_head": ""}

TARGETS = {
    "alpha": {"url": "https://dumbmodel.com"},
    "zeta": {"url": "https://www.bhenre.com"},
}
# 3 passes: alpha always up; zeta blips then confirms down under damping=2
OUTAGE_SCRIPT = [[UP, UP], [UP, DOWN], [UP, DOWN]]
LAST_TS = T0 + 120.0  # third pass
NOW = LAST_TS + 30.0


def _scripted(seq):
    """Probe fake replaying canned results in order (the offline invariant)."""
    it = iter(seq)

    def probe(url, cfg):
        return next(it)

    return probe


def _seed_uptime(path, *, targets=None, script=None, start=T0, step=60.0):
    """Write a real ledger file using uptime's OWN pipeline; returns last ts."""
    targets = TARGETS if targets is None else targets
    script = OUTAGE_SCRIPT if script is None else script
    conn = uptime.open_ledger(path)
    ts = start
    for observations in script:
        uptime.run_pass(conn, targets, _scripted(observations), ts=ts)
        ts += step
    conn.close()
    return ts - step


def _cert(host, *, not_after=NA):
    """getpeercert()-shaped dict (same fixture shape as test_certmon)."""
    return {
        "subject": ((("commonName", host),),),
        "issuer": ((("commonName", "Example CA"),),),
        "notBefore": "Jan  1 00:00:00 2020 GMT",
        "notAfter": not_after,
        "subjectAltName": (("DNS", host),),
    }


def _seed_certs(path, hosts, *, now=NOW):
    conn = certmon.open_cert_ledger(path)
    certmon.run_pass(
        conn,
        list(hosts),
        lambda h: {
            "cert": _cert(h),
            "protocol": "TLSv1.3",
            "hsts": True,
            "error": None,
            "verified": True,
        },
        now=now,
    )
    conn.close()


def _seed_beats(path, *, beat_ts=T0, sweep_now=T0 + 30.0, grace_s=60.0):
    conn = heartbeat.open_registry(path)
    heartbeat.beat(conn, "trainer", ts=beat_ts, note="training step loop")
    heartbeat.sweep(conn, {"trainer": {"kind": "beat", "grace_s": grace_s}}, now=sweep_now)
    conn.close()


def _ro(path):
    conn = statuspage.open_readonly(path)
    assert conn is not None, f"expected a readable ledger at {path}"
    return conn


# ---- read-only is enforced, not promised ------------------------------------


def test_open_readonly_returns_none_for_an_absent_ledger(tmp_path):
    assert statuspage.open_readonly(tmp_path / "nothing.db") is None


def test_open_readonly_physically_rejects_every_write(tmp_path):
    """The architectural half of 'collects nothing': sqlite refuses the writes."""
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    conn = _ro(db)
    # reads still work, so this is a real connection, not a stub
    assert conn.execute("SELECT COUNT(*) AS n FROM checks").fetchone()["n"] == 6
    for sql in (
        "INSERT INTO checks(target, url, ts, state) VALUES('x', 'u', 1.0, 'up')",
        "UPDATE state SET state = 'up'",
        "DELETE FROM checks",
        "CREATE TABLE statuspage_notes(a)",
    ):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(sql)


def test_readonly_path_survives_spaces_in_the_directory(tmp_path):
    """Windows-safe URI construction (as_uri percent-encodes) — not POSIX luck."""
    d = tmp_path / "my status dir"
    d.mkdir()
    db = d / "uptime.db"
    _seed_uptime(db)
    assert _ro(db).execute("SELECT COUNT(*) AS n FROM checks").fetchone()["n"] == 6


# ---- provenance: a table is not evidence ------------------------------------


def test_sources_require_rows_not_just_tables(tmp_path):
    db = tmp_path / "uptime.db"
    uptime.open_ledger(db).close()  # schema created, nothing recorded
    src = statuspage.sources(_ro(db), db)
    assert src["ledger"]["present"] is True and src["ledger"]["mode"] == "ro"
    assert src["uptime"]["table_present"] is True
    assert src["uptime"]["rows"] == 0 and src["uptime"]["present"] is False
    # certmon/heartbeat never ran here: their tables do not even exist
    assert src["certmon"]["table_present"] is False
    assert src["heartbeat"]["table_present"] is False
    # an empty certs table (certmon linked but recorded nothing) is still not
    # evidence of certificate monitoring
    certmon.open_cert_ledger(db).close()
    src2 = statuspage.sources(_ro(db), db)
    assert src2["certmon"]["table_present"] is True
    assert src2["certmon"]["rows"] == 0 and src2["certmon"]["present"] is False


def test_sources_absent_ledger_reports_every_source_missing(tmp_path):
    db = tmp_path / "nothing.db"
    src = statuspage.sources(None, db)
    assert src["ledger"]["present"] is False and src["ledger"]["size_bytes"] is None
    for name in ("uptime", "certmon", "heartbeat"):
        assert src[name]["present"] is False and src[name]["rows"] == 0
        assert src[name]["newest_ts"] is None


def test_sources_counts_and_newest_ts_come_from_the_ledger(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    _seed_certs(db, ["www.bhenre.com"])
    _seed_beats(db)
    src = statuspage.sources(_ro(db), db)
    # 6 service observations + the 1 hb:trainer row heartbeat's sweep writes into
    # the SAME checks table (shared substrate, one file, no parallel store)
    assert src["uptime"]["present"] is True and src["uptime"]["rows"] == 7
    assert src["uptime"]["newest_ts"] == LAST_TS
    assert src["certmon"]["rows"] == 1 and src["certmon"]["newest_ts"] == NOW
    assert src["heartbeat"]["rows"] == 1 and src["heartbeat"]["newest_ts"] == T0
    assert src["ledger"]["size_bytes"] > 0


# ---- services are what was MEASURED, not what was configured ----------------


def test_ledger_targets_ignore_config_and_exclude_heartbeat_namespace(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    _seed_beats(db)
    targets = statuspage.ledger_targets(_ro(db))
    assert sorted(targets) == ["alpha", "zeta"]
    # the 10 configured-but-unprobed fleet targets must NOT appear
    assert not set(uptime.DEFAULT_TARGETS) & set(targets)
    # heartbeat wrote hb:trainer into the same checks table; it is not a service
    assert not any(k.startswith(heartbeat.NS) for k in targets)
    assert targets["zeta"]["url"] == "https://www.bhenre.com"


def test_ledger_targets_take_the_newest_url_per_target(tmp_path):
    db = tmp_path / "uptime.db"
    conn = uptime.open_ledger(db)
    uptime.record_check(conn, target="alpha", url="https://old", ts=1.0, state="up")
    uptime.record_check(conn, target="alpha", url="https://new", ts=2.0, state="up")
    conn.close()
    assert statuspage.ledger_targets(_ro(db))["alpha"]["url"] == "https://new"


def test_service_rows_carry_window_uptime_and_last_incident(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    rows = statuspage.service_rows(_ro(db), now=NOW, window_hours=24.0)
    # worst-first ordering, not alphabetical
    assert [r["target"] for r in rows] == ["zeta", "alpha"]
    zeta, alpha = rows
    assert zeta["state"] == "down" and alpha["state"] == "up"
    assert zeta["uptime_pct"] == 33.33 and zeta["checks"] == 3
    assert alpha["uptime_pct"] == 100.0
    # the state mix keeps degraded/down visible behind the single percentage
    assert zeta["window_states"] == {"up": 1, "down": 2}
    assert zeta["latency"]["p50"] == 50.0  # answered probes only
    inc = zeta["last_incident"]
    assert inc["opened_ts"] == LAST_TS and inc["closed_ts"] is None
    assert inc["state"] == "down" and inc["duration_s"] is None
    assert alpha["last_incident"] is None
    assert zeta["age_s"] == 30.0 and zeta["stale"] is False


def test_closed_incident_is_reported_with_its_duration(tmp_path):
    db = tmp_path / "uptime.db"
    # down, down (incident opens), then up, up (it closes)
    _seed_uptime(
        db,
        targets={"zeta": {"url": "https://www.bhenre.com"}},
        script=[[DOWN], [DOWN], [UP], [UP]],
    )
    rows = statuspage.service_rows(_ro(db), now=T0 + 200.0, window_hours=24.0)
    inc = rows[0]["last_incident"]
    assert inc["opened_ts"] == T0 and inc["closed_ts"] == T0 + 180.0
    assert inc["duration_s"] == 180.0
    assert rows[0]["state"] == "up" and rows[0]["uptime_pct"] == 50.0


# ---- the anti-fabrication contract ------------------------------------------


def test_no_checks_in_window_yields_no_percentage_and_flags_stale(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db, targets={"alpha": {"url": "https://dumbmodel.com"}}, script=[[UP]])
    later = T0 + 10 * DAY
    snap = statuspage.snapshot(_ro(db), path=db, now=later, window_hours=24.0)
    row = snap["services"][0]
    assert row["state"] == "up"  # the ledger's last confirmed verdict
    assert row["checks"] == 0 and row["uptime_pct"] is None
    assert row["stale"] is True and row["age_s"] == 10 * DAY
    # a green board from 10-day-old checks is a lie the roll-up must not tell
    assert snap["overall"] == statuspage.OVERALL_DEGRADED
    page = statuspage.render_html(snap)
    assert re.search(r"\d+\.\d{2}%", page) is None
    assert "stale" in page and "—" in page


def test_snapshot_without_a_ledger_is_honest_no_data(tmp_path):
    db = tmp_path / "nothing.db"
    snap = statuspage.read_snapshot(db, now=NOW)
    assert snap["overall"] == statuspage.OVERALL_NO_DATA
    assert snap["services"] == [] and snap["certs"] == [] and snap["daemons"] == []
    assert snap["sources"]["ledger"]["present"] is False
    assert snap["counts"] == {
        "services": 0,
        "by_state": {},
        "stale": 0,
        "open_incidents": 0,
        "certs": 0,
        "daemons": 0,
    }
    page = statuspage.render_html(snap)
    assert "No monitoring ledger" in page
    assert str(db) in page  # names the file it could not find
    assert re.search(r"\d+\.\d{2}%", page) is None  # nothing invented


def test_empty_but_present_ledger_says_so_instead_of_reporting_uptime(tmp_path):
    db = tmp_path / "uptime.db"
    uptime.open_ledger(db).close()
    snap = statuspage.read_snapshot(db, now=NOW)
    assert snap["overall"] == statuspage.OVERALL_NO_DATA and snap["services"] == []
    page = statuspage.render_html(snap)
    assert "No service checks in the ledger" in page
    assert re.search(r"\d+\.\d{2}%", page) is None
    codes = [d["rule"] for d in statuspage.to_diagnostics(snap)]
    assert codes == ["statuspage:no-services"]


def test_overall_status_rollup_matrix():
    def svc(state, *, stale=False):
        return {"target": state, "state": state, "stale": stale}

    assert statuspage.overall_status([]) == statuspage.OVERALL_NO_DATA
    assert statuspage.overall_status([svc("up")]) == statuspage.OVERALL_OPERATIONAL
    assert (
        statuspage.overall_status([svc("up"), svc("degraded")])
        == statuspage.OVERALL_DEGRADED
    )
    assert (
        statuspage.overall_status([svc("degraded"), svc("down")])
        == statuspage.OVERALL_OUTAGE
    )
    assert statuspage.overall_status([svc("unknown")]) == statuspage.OVERALL_NO_DATA
    assert (
        statuspage.overall_status([svc("up"), svc("unknown")])
        == statuspage.OVERALL_DEGRADED
    )
    # freshness is part of the verdict, not decoration
    assert (
        statuspage.overall_status([svc("up", stale=True)])
        == statuspage.OVERALL_DEGRADED
    )


# ---- certs + daemons appear only when their plugin actually recorded --------


def test_cert_rows_only_exist_once_certmon_has_recorded(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    assert statuspage.cert_rows(_ro(db), now=NOW) == []
    page = statuspage.render_html(statuspage.read_snapshot(db, now=NOW))
    assert "certmon (#9) has not recorded here" in page
    _seed_certs(db, ["www.bhenre.com"])
    rows = statuspage.cert_rows(_ro(db), now=NOW)
    assert [r["host"] for r in rows] == ["www.bhenre.com"]
    assert rows[0]["status"] == "ok" and rows[0]["days_to_expiry"] == 200.0
    assert "last" not in rows[0]  # posture, not certmon's whole history row
    page2 = statuspage.render_html(statuspage.read_snapshot(db, now=NOW))
    assert "www.bhenre.com" in page2 and "200.0 d" in page2
    assert "certmon (#9) has not recorded here" not in page2


def test_daemon_rows_report_ledger_state_without_inventing_a_grace_period(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_beats(db)  # beat at T0, sweep at T0+30 with grace 60 -> ok/up
    row = statuspage.daemon_rows(_ro(db), now=T0 + 45.0)[0]
    assert row["daemon"] == "trainer" and row["beats"] == 1
    assert row["note"] == "training step loop"
    assert row["state"] == "up" and row["age_s"] == 45.0
    # grace/expected-cadence live in heartbeat config; the page must not guess
    assert "grace_s" not in row and "status" not in row and "overdue_s" not in row


def test_stale_daemon_shows_the_ledger_verdict_and_its_alert_event(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_beats(db, sweep_now=T0 + 600.0, grace_s=60.0)  # silence past grace
    conn = _ro(db)
    row = statuspage.daemon_rows(conn, now=T0 + 600.0)[0]
    assert row["state"] == "down" and row["open_incident"] is not None
    kinds = [e["kind"] for e in statuspage.event_rows(conn, now=T0 + 600.0)]
    assert "alert" in kinds
    snap = statuspage.read_snapshot(db, now=T0 + 600.0)
    page = statuspage.render_html(snap)
    assert "trainer" in page and "alert" in page
    # a daemon is never presented as a monitored service
    assert snap["services"] == []


def test_events_timeline_includes_deploy_markers(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    conn = uptime.open_ledger(db)
    uptime.record_event(
        conn, kind="deploy", message="bhenre 4009c52", target="zeta", ts=LAST_TS
    )
    conn.close()
    evs = statuspage.event_rows(_ro(db), now=NOW)
    assert evs[0]["kind"] == "deploy" and evs[0]["age_s"] == 30.0
    assert "bhenre 4009c52" in statuspage.render_html(
        statuspage.read_snapshot(db, now=NOW)
    )


# ---- rendering ---------------------------------------------------------------


def test_render_html_escapes_hostile_ledger_text(tmp_path):
    db = tmp_path / "uptime.db"
    hostile = "<script>alert(1)</script>"
    _seed_uptime(db, targets={hostile: {"url": "https://x/<img>"}}, script=[[UP]])
    conn = uptime.open_ledger(db)
    uptime.record_event(conn, kind="note", message="<b>pwn</b>", ts=T0)
    conn.close()
    page = statuspage.render_html(statuspage.read_snapshot(db, now=T0 + 10.0))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script" not in page
    assert "<b>pwn</b>" not in page and "&lt;b&gt;pwn&lt;/b&gt;" in page
    assert "&lt;img&gt;" in page and "<img" not in page


def test_render_html_is_self_contained(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    _seed_certs(db, ["www.bhenre.com"])
    _seed_beats(db)
    page = statuspage.render_html(
        statuspage.read_snapshot(db, now=NOW), title="Fleet status"
    )
    assert page.startswith("<!DOCTYPE html>") and page.rstrip().endswith("</html>")
    assert "<style>" in page  # CSS is inline
    for forbidden in ("<script", "<link", "src=", "@import", "url("):
        assert forbidden not in page, forbidden
    assert "<title>Fleet status</title>" in page and "<h1>Fleet status</h1>" in page
    # the three sections plus the provenance footer
    assert "Outage" in page and "zeta" in page and "trainer" in page
    assert "Where these numbers come from" in page
    assert "collects nothing" in page


def test_render_html_states_the_window_and_the_source_file(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    page = statuspage.render_html(
        statuspage.read_snapshot(db, now=NOW, window_hours=168.0)
    )
    assert "window 168.0h" in page and str(db) in page
    assert "uptime · 168.0h" in page


# ---- family diagnostics ------------------------------------------------------


def test_to_diagnostics_normalize_into_family_schema(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db)
    snap = statuspage.read_snapshot(db, now=NOW)
    diags = statuspage.to_diagnostics(snap)
    by_rule = {d["rule"]: d for d in diags}
    assert set(by_rule) == {"statuspage:down"}  # up services emit nothing
    assert by_rule["statuspage:down"]["severity"] == "error"
    assert by_rule["statuspage:down"]["path"] == "https://www.bhenre.com"
    assert "33.33% up in window" in by_rule["statuspage:down"]["message"]
    assert openswap.summarize(diags)["by_severity"]["error"] == 1


def test_stale_and_absent_data_are_diagnostics_too(tmp_path):
    db = tmp_path / "uptime.db"
    _seed_uptime(db, targets={"alpha": {"url": "https://dumbmodel.com"}}, script=[[UP]])
    stale = statuspage.to_diagnostics(
        statuspage.read_snapshot(db, now=T0 + 10 * DAY, window_hours=24.0)
    )
    assert [d["rule"] for d in stale] == ["statuspage:stale"]
    assert stale[0]["severity"] == "warning"
    assert "no checks in window" not in stale[0]["message"]  # staleness, not zero data
    absent = statuspage.to_diagnostics(
        statuspage.read_snapshot(tmp_path / "gone.db", now=NOW)
    )
    assert [d["rule"] for d in absent] == ["statuspage:no-ledger"]
    assert absent[0]["severity"] == "warning"
    assert openswap.summarize(absent)["by_severity"]["warning"] == 1


# ---- detection ---------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.statuspage import cli as statuspage_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = statuspage_cli._capability()
    assert cap["adapter"] == "statuspage"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "cstate"
    assert cap["extras"]["hugo"]["found"] is False
    assert cap["extras"]["statping"]["found"] is False


def _plugin_dir() -> Path:
    return ROOT / "bigbang" / "plugins" / "statuspage"


def test_manifest_denies_the_network_axis():
    from bigbang.core.policy import check_permission, load_manifest

    mf = load_manifest(_plugin_dir())
    assert mf["name"] == "statuspage"
    assert mf["capabilities"]["network"]["enabled"] is False
    assert mf["capabilities"]["secrets"]["allow"] == []
    # a page that collects nothing can reach nothing, even loopback
    allowed, reason = check_permission(mf, "network", "http://127.0.0.1:11434/x")
    assert allowed is False and "network disabled" in reason
    # the one capability it does need
    assert check_permission(mf, "fs_write", ".scout/status.html")[0] is True


def test_plugin_is_discoverable():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "statuspage" in list_plugin_names()


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_statuspage_hello_envelope():
    r = _cli(["statuspage", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True and data["data"]["collects"] is False
    assert "example" in data


def test_cli_status_and_render_over_a_seeded_ledger(tmp_path):
    db = tmp_path / "uptime.db"
    # anchor to wall-clock so the CLI's real time.time() sees fresh checks
    base = time.time() - 120.0
    _seed_uptime(db, start=base, step=60.0)
    r = _cli(["statuspage", "status", "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["read_only"] is True
    assert data["overall"] == "outage"
    assert data["services"][0]["target"] == "zeta"  # worst first
    assert {s["target"]: s["state"] for s in data["services"]} == {
        "alpha": "up",
        "zeta": "down",
    }
    assert data["services"][0]["stale"] is False
    assert data["sources"]["uptime"]["present"] is True
    assert data["sources"]["certmon"]["present"] is False
    assert data["summary"]["by_severity"]["error"] == 1

    out = tmp_path / "public" / "status.html"
    r = _cli(
        [
            "statuspage",
            "render",
            "--db",
            str(db),
            "--out",
            str(out),
            "--title",
            "Fleet status",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    rendered = json.loads(r.stdout)["data"]
    assert rendered["out"] == str(out) and rendered["bytes"] > 0
    assert rendered["ledger_present"] is True and rendered["overall"] == "outage"
    page = out.read_text(encoding="utf-8")
    assert len(page) == rendered["bytes"]
    assert "<h1>Fleet status</h1>" in page and "Outage" in page
    assert "zeta" in page and "<script" not in page

    # the gate hook fires on a confirmed outage
    r = _cli(["statuspage", "status", "--db", str(db), "--fail-on", "error"])
    assert r.returncode == 1
    assert json.loads(r.stdout)["data"]["overall"] == "outage"


def test_cli_renders_a_no_data_page_instead_of_failing(tmp_path):
    """Deliberate divergence from the family: a vanished ledger is page content."""
    db = tmp_path / "gone.db"
    out = tmp_path / "status.html"
    r = _cli(["statuspage", "render", "--db", str(db), "--out", str(out)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["ledger_present"] is False and data["overall"] == "no_data"
    page = out.read_text(encoding="utf-8")
    assert "No monitoring ledger" in page
    assert re.search(r"\d+\.\d{2}%", page) is None
    # ...but it is still gate-able, so cron notices the page went blind
    r = _cli(["statuspage", "render", "--db", str(db), "--out", str(out), "--fail-on", "warning"])
    assert r.returncode == 1
    assert json.loads(r.stdout)["data"]["summary"]["by_severity"]["warning"] == 1


def test_cli_sources_reports_provenance_on_an_absent_ledger(tmp_path):
    r = _cli(["statuspage", "sources", "--db", str(tmp_path / "gone.db")])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["collects"] is False and data["read_only"] is True
    assert data["sources"]["ledger"]["present"] is False
    assert data["sources"]["heartbeat"]["table_present"] is False


def test_cli_rejects_a_bad_window_and_an_unreadable_db(tmp_path):
    r = _cli(["statuspage", "status", "--hours", "0"])
    assert r.returncode == 1
    assert "--hours must be > 0" in json.loads(r.stdout)["error"]
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not a ledger\n" * 200, encoding="utf-8")
    r = _cli(["statuspage", "status", "--db", str(junk)])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "not a readable sqlite ledger" in data["error"]
    assert "example" in data
