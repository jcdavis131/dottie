"""Links — openswap #4 (Ahrefs broken-link / Dr. Link Check -> crawl-store
verification + polite external probes + offline docs checker). Pure-logic core
tests + capability-detection fallback + the subprocess envelope. Offline and
deterministic by construction: probes, clocks, and sleeps are injected fakes,
and no test opens a socket."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import links, openswap, seo

ROOT = Path(__file__).resolve().parents[1]


def _row(url, *, status=200, depth=1, facts=None, redirects=None, error=None,
         final_url=None):
    """One seo.site_rows()-shaped row (the store contract this adapter rides)."""
    return {"url": url, "status": status, "depth": depth, "facts": facts,
            "redirects": redirects or [], "error": error,
            "final_url": final_url or url}


def _facts(internal=(), external=()):
    return {"links": {"internal": list(internal), "external": list(external)}}


def _survey_rows():
    root_links = ["https://s.t/ok", "https://s.t/gone", "https://s.t/moved",
                  "https://s.t/later", "https://s.t/down"]
    return [
        _row("https://s.t/", depth=0,
             facts=_facts(internal=root_links,
                          external=["https://ext.example/a"])),
        _row("https://s.t/ok",
             facts=_facts(internal=["https://s.t/"],
                          external=["https://ext.example/a"])),
        _row("https://s.t/gone", status=404),
        _row("https://s.t/moved",
             redirects=[{"code": 301, "to": "https://s.t/new"}],
             final_url="https://s.t/new"),
        _row("https://s.t/down", status=None, error="TimeoutError: x"),
        _row("https://s.t/island", depth=2, facts=_facts()),
    ]


class _FakeTime:
    """Clock that only advances when sleep is called — politeness becomes
    a pure assertion on the recorded sleeps."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, d):
        self.sleeps.append(round(d, 6))
        self.t += d


def _fake_probe(script):
    """script: {(url, method): [result, ...]} popped left to right; the last
    entry repeats (offline invariant — no socket is ever opened)."""
    calls = []

    def probe(url, method):
        calls.append((url, method))
        seq = script[(url, method)]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return probe, calls


def _cfg(**over):
    cfg = dict(links.DEFAULT_CONFIG)
    cfg.update(over)
    return cfg


# ---- internal survey rides the crawl results --------------------------------


def test_link_survey_states_graph_and_orphans():
    survey = links.link_survey(
        _survey_rows(), frontier={"https://s.t/later": "pending"}
    )
    st = {u: r["state"] for u, r in survey["internal"].items()}
    assert st == {
        "https://s.t/": "ok",
        "https://s.t/ok": "ok",
        "https://s.t/gone": "broken",
        "https://s.t/moved": "redirect",
        "https://s.t/later": "uncrawled",
        "https://s.t/down": "unreachable",
    }
    assert survey["internal"]["https://s.t/gone"]["detail"] == "http 404"
    assert survey["internal"]["https://s.t/moved"]["detail"] == "-> https://s.t/new"
    assert survey["internal"]["https://s.t/later"]["detail"] == "pending"
    # facts-bearing pages are the graph nodes; adjacency is sorted
    assert set(survey["graph"]) == {
        "https://s.t/", "https://s.t/ok", "https://s.t/island"
    }
    assert survey["graph"]["https://s.t/ok"] == ["https://s.t/"]
    # external refs aggregate across pages
    assert survey["external"]["https://ext.example/a"]["refs"] == [
        "https://s.t/", "https://s.t/ok"
    ]
    # depth>0, zero inbound links -> orphan; the seed never is
    assert survey["orphans"] == ["https://s.t/island"]


def test_survey_rides_the_real_seo_store():
    page = ('<html><head><title>a fixture title long enough for the window'
            '</title></head><body><a href="/missing">m</a></body></html>')
    fetch_pages = {"https://s.t/": page}

    def fetch(url):
        body = fetch_pages.get(url)
        status = 200 if body else 404
        return {"status": status, "final_url": url, "redirects": [],
                "content_type": "text/html", "headers": {},
                "body": body or "nope", "error": None}

    conn = seo.open_store(":memory:")
    seo.crawl(conn, "https://s.t/", fetch, ts=1.0)
    survey = links.link_survey(seo.site_rows(conn, "https://s.t/"))
    rec = survey["internal"]["https://s.t/missing"]
    assert rec["state"] == "broken" and rec["refs"] == ["https://s.t/"]


def test_diagnostics_are_actionable_and_family_shaped():
    survey = links.link_survey(
        _survey_rows(), frontier={"https://s.t/later": "pending"}
    )
    ext = {
        "https://ext.example/a": {"state": "broken", "status": 410,
                                  "method": "GET", "detail": "http 410",
                                  "attempts": 2},
        "https://ext.example/b": {"state": "unverified", "status": None,
                                  "method": None, "detail": "off", "attempts": 0},
    }
    diags = links.to_diagnostics(survey, ext)
    rules = {d["rule"] for d in diags}
    # ok/unverified stay counts, not noise
    assert rules == {
        "links:internal-broken", "links:internal-redirect",
        "links:internal-uncrawled", "links:internal-unreachable",
        "links:external-broken", "links:orphan-page",
    }
    by_rule = {d["rule"]: d for d in diags}
    assert by_rule["links:internal-broken"]["severity"] == "error"
    assert by_rule["links:internal-broken"]["path"] == "https://s.t/"
    assert "1 referring page" in by_rule["links:internal-broken"]["message"]
    assert by_rule["links:external-broken"]["message"].startswith(
        "https://ext.example/a http 410"
    )
    for d in diags:
        assert set(d) == {"path", "line", "col", "rule", "severity", "message",
                          "suggestion", "source"}
        assert d["severity"] in openswap.SEVERITIES
    counts = links.state_counts(survey, ext)
    assert counts["internal"] == {"broken": 1, "ok": 2, "redirect": 1,
                                  "unreachable": 1, "uncrawled": 1}
    assert counts["external"] == {"broken": 1, "unverified": 1}


# ---- external verification: HEAD-then-GET under politeness ------------------


def test_verify_external_head_then_get_fallback():
    t = _FakeTime()
    probe, calls = _fake_probe({
        ("https://a.x/1", "HEAD"): [{"status": 405, "error": None}],
        ("https://a.x/1", "GET"): [{"status": 200, "error": None}],
        ("https://b.x/2", "HEAD"): [{"status": 200, "error": None}],
        ("https://c.x/3", "HEAD"): [{"status": 404, "error": None}],
        ("https://c.x/3", "GET"): [{"status": 404, "error": None}],
    })
    out = links.verify_external(
        ["https://a.x/1", "https://b.x/2", "https://c.x/3"], probe,
        config=_cfg(per_domain_delay_s=0.0), sleep=t.sleep, clock=t.clock,
    )
    # HEAD lied (405) -> GET is the authority
    assert out["https://a.x/1"] == {"state": "ok", "status": 200,
                                    "method": "GET", "detail": None, "attempts": 2}
    # a clean HEAD answer never spends a GET
    assert out["https://b.x/2"]["method"] == "HEAD"
    assert ("https://b.x/2", "GET") not in calls
    # a plain 4xx is an answer — no retries burned
    assert out["https://c.x/3"] == {"state": "broken", "status": 404,
                                    "method": "GET", "detail": "http 404",
                                    "attempts": 2}
    assert t.sleeps == []


def test_verify_external_retries_backoff_and_transport_errors():
    t = _FakeTime()
    boom = {"status": None, "error": "URLError: dns"}
    probe, _calls = _fake_probe({
        ("https://d.x/", "HEAD"): [{"status": 503, "error": None},
                                   {"status": 200, "error": None}],
        ("https://d.x/", "GET"): [{"status": 503, "error": None}],
        ("https://e.x/", "HEAD"): [boom],
        ("https://e.x/", "GET"): [boom],
    })
    out = links.verify_external(
        ["https://d.x/", "https://e.x/"], probe,
        config=_cfg(per_domain_delay_s=0.0, retry_attempts=2,
                    retry_backoff_s=0.25),
        sleep=t.sleep, clock=t.clock,
    )
    # 503 retried with doubling backoff, then the 200 wins
    assert out["https://d.x/"]["state"] == "ok"
    assert out["https://d.x/"]["attempts"] == 3
    # transport failure exhausts retries -> unreachable, error class visible
    assert out["https://e.x/"] == {"state": "unreachable", "status": None,
                                   "method": "GET", "detail": "URLError: dns",
                                   "attempts": 6}
    assert t.sleeps == [0.25, 0.25, 0.5]


def test_verify_external_allowlist_rate_limit_and_budget():
    t = _FakeTime()
    ok200 = {"status": 200, "error": None}
    probe, calls = _fake_probe({
        ("https://h.x/1", "HEAD"): [ok200],
        ("https://h.x/2", "HEAD"): [ok200],
        ("https://h.x/3", "HEAD"): [ok200],
    })
    out = links.verify_external(
        ["https://cdn.trusted/lib.js", "https://sub.cdn.trusted/x",
         "https://h.x/1", "https://h.x/2", "https://h.x/3"],
        probe,
        config=_cfg(external_allow=["cdn.trusted"], per_domain_delay_s=3.0,
                    budget_s=2.0),
        sleep=t.sleep, clock=t.clock,
    )
    # exact host and dot-suffix both trust without a probe
    assert out["https://cdn.trusted/lib.js"]["state"] == "allowlisted"
    assert out["https://sub.cdn.trusted/x"]["state"] == "allowlisted"
    # second same-host probe waited the per-domain floor
    assert t.sleeps == [3.0]
    # after 3s of wall clock the 2s budget is spent — no probe for /3
    assert out["https://h.x/3"]["state"] == "unverified"
    assert "budget" in out["https://h.x/3"]["detail"]
    assert ("https://h.x/3", "HEAD") not in calls
    assert len(calls) == 2


# ---- config is policy-as-config ---------------------------------------------


def test_load_config_overlay_and_rejects(tmp_path):
    overlay = tmp_path / "links.json"
    overlay.write_text(
        json.dumps({"external_allow": ["cdn.trusted"], "budget_s": 5}),
        encoding="utf-8",
    )
    cfg = links.load_config(str(overlay))
    assert cfg["external_allow"] == ["cdn.trusted"]
    assert cfg["budget_s"] == 5
    assert cfg["retry_attempts"] == links.DEFAULT_CONFIG["retry_attempts"]
    bad = (
        "[1]",
        '{"nope": 1}',
        '{"external_allow": "cdn.trusted"}',
        '{"retry_attempts": 1.5}',
        '{"retry_attempts": true}',
        '{"budget_s": -1}',
        '{"per_domain_delay_s": "fast"}',
    )
    for raw in bad:
        f = tmp_path / "bad.json"
        f.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            links.load_config(str(f))


# ---- local docs: href/src + anchors, fully offline --------------------------


def test_parse_doc_html_refs_and_ids():
    html = (
        '<html><body><div id="top"></div><a name="legacy"></a>'
        '<a href="page.html#sec">p</a>\n<img src="art.png">'
        '<script src="app.js"></script><link href="style.css">'
        "</body></html>"
    )
    doc = links.parse_doc(html, ".html")
    assert doc["ids"] == {"top", "legacy"}
    targets = {(r["target"], r["tag"]) for r in doc["refs"]}
    assert targets == {("page.html#sec", "a"), ("art.png", "img"),
                       ("app.js", "script"), ("style.css", "link")}
    img = next(r for r in doc["refs"] if r["tag"] == "img")
    assert img["line"] == 2 and img["col"] >= 1


def test_parse_doc_markdown_slugs_and_refs():
    md = (
        "# Hello, World!\n"
        "## Hello, World!\n"
        "[a](other.md#hello-world) ![i](img.png)\n"
        "[ref]: target.md\n"
        '<a id="raw-anchor"></a>\n'
    )
    doc = links.parse_doc(md, ".md")
    # duplicate headings suffix -1 the GitHub way; embedded HTML ids count
    assert doc["ids"] == {"hello-world", "hello-world-1", "raw-anchor"}
    targets = [r["target"] for r in doc["refs"]]
    assert targets == ["other.md#hello-world", "img.png", "target.md"]
    assert [r["line"] for r in doc["refs"]] == [3, 3, 4]
    assert links.anchor_slug("A  B") == "a--b"
    assert links.anchor_slug("Under_score kept") == "under_score-kept"


def test_check_files_docs_tree(tmp_path):
    (tmp_path / "b.md").write_text("# Section One\n", encoding="utf-8")
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "logo.png").write_bytes(b"png")
    a = tmp_path / "a.md"
    a.write_text(
        "# Local Heading\n"
        "[ok](b.md#section-one)\n"
        "[missing](nope.md)\n"
        "[dup](nope.md)\n"
        "[badfrag](b.md#zzz)\n"
        "[self](#local-heading)\n"
        "[badself](#zzz-local)\n"
        "[ext](https://ext.example/x)\n"
        "[mail](mailto:a@b.c)\n"
        "[root](/img/logo.png)\n",
        encoding="utf-8",
    )
    # b.md is NOT in the file set: cross-file fragments parse it on demand
    diags, stats = links.check_files([a])
    by_rule = {}
    for d in diags:
        by_rule.setdefault(d["rule"], []).append(d)
    assert len(by_rule["links:file-missing"]) == 1  # duplicate target collapsed
    assert "nope.md" in by_rule["links:file-missing"][0]["message"]
    assert by_rule["links:file-missing"][0]["line"] == 3
    frag_msgs = sorted(d["message"] for d in by_rule["links:fragment-missing"])
    assert len(frag_msgs) == 2  # cross-file #zzz and same-file #zzz-local
    assert any("#zzz not in b.md" in m for m in frag_msgs)
    assert stats == {"files": 1, "external_refs": 1, "skipped_schemes": 1,
                     "root_relative_skipped": 1, "checked_refs": 6}
    # with --root the root-absolute ref resolves and passes
    diags2, stats2 = links.check_files([a], root=tmp_path)
    assert stats2["root_relative_skipped"] == 0
    assert {d["rule"] for d in diags2} == {"links:file-missing",
                                           "links:fragment-missing"}
    for d in diags2:
        assert set(d) == {"path", "line", "col", "rule", "severity", "message",
                          "suggestion", "source"}


# ---- the diffable status store ----------------------------------------------


def _mini_survey(internal, external=None):
    return {"internal": internal, "external": external or {}, "graph": {},
            "orphans": []}


def _rec(state, refs=("https://s.t/",), status=None, detail=None):
    return {"state": state, "status": status, "detail": detail,
            "refs": list(refs)}


def test_record_run_and_diff_runs():
    conn = links.open_store(":memory:")
    with pytest.raises(ValueError):
        links.diff_runs(conn, "https://s.t/")
    run1 = links.record_run(
        conn, "https://s.t/",
        _mini_survey(
            {"u1": _rec("ok", status=200), "u2": _rec("broken", detail="http 404")},
            {"e1": _rec("?")},
        ),
        {"e1": {"state": "unreachable", "status": None, "method": "GET",
                "detail": "URLError: dns", "attempts": 6}},
        ts=1.0,
    )
    run2 = links.record_run(
        conn, "https://s.t/",
        _mini_survey(
            {"u1": _rec("broken", detail="http 500"), "u2": _rec("ok", status=200),
             "u3": _rec("broken", detail="http 404")},
        ),
        ts=2.0,
    )
    assert [r["id"] for r in links.runs_for(conn, "https://s.t/")] == [run1, run2]
    d = links.diff_runs(conn, "https://s.t/")  # defaults to the latest two
    assert d["run_a"] == run1 and d["run_b"] == run2
    assert d["new_broken"] == ["u1"]
    assert d["fixed"] == ["u2"]
    assert d["appeared_broken"] == ["u3"] and d["added"] == ["u3"]
    assert d["removed"] == ["e1"] and d["still_broken"] == []
    # an external link with no verification result records as unverified
    row = conn.execute(
        "SELECT state, kind FROM link_status WHERE run_id = ? AND url = 'u3'",
        (run2,),
    ).fetchone()
    assert row["state"] == "broken" and row["kind"] == "internal"
    with pytest.raises(ValueError):
        links.diff_runs(conn, "https://s.t/", run_a=run1, run_b=99)


# ---- family schema + detection ----------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.links import cli as links_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = links_cli._capability()
    assert cap["adapter"] == "links"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "never executed" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "linkchecker"
    assert cap["extras"]["lychee"]["found"] is False


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


def test_cli_links_hello_envelope():
    r = _cli(["links", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_links_files_is_offline_and_gates(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("[gone](missing.md)\n", encoding="utf-8")
    r = _cli(["links", "files", str(doc), "--fail-on", "error"])
    assert r.returncode == 1  # file-missing is an error and the gate is armed
    data = json.loads(r.stdout)
    assert data["ok"] is True  # the report itself still emits
    rules = {d["rule"] for d in data["data"]["diagnostics"]}
    assert rules == {"links:file-missing"}
    assert data["data"]["stats"]["files"] == 1
    assert data["data"]["summary"]["by_severity"]["error"] == 1


def test_cli_links_check_without_store_fails_actionably(tmp_path):
    r = _cli(["links", "check", "bhenre", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no seo crawl store" in data["error"]
    assert "example" in data
