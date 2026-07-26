"""SEO — openswap #3 (Screaming Frog + Semrush + Yoast -> stdlib polite crawler
+ on-page audit). Pure-logic core tests + capability-detection fallback + the
subprocess envelope. Offline and deterministic by construction: fetches are
injected fakes, robots.txt is literal text, and no test opens a socket."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import openswap, seo

ROOT = Path(__file__).resolve().parents[1]

CLEAN_PAGE = """<!doctype html>
<html><head>
<title>Scout SEO Fixture — a Clean Test Page</title>
<meta name="description" content="A deterministic fixture page for the scout \
seo adapter tests, long enough to satisfy the default description window.">
<link rel="canonical" href="https://site.test/">
<meta property="og:title" content="Scout SEO Fixture">
<meta property="og:description" content="Fixture page">
<meta property="og:image" content="https://site.test/card.png">
<meta name="twitter:card" content="summary">
</head><body>
<h1>One Clean Heading</h1>
<p>Enough words to look like a real page body for the crawler tests.</p>
<a href="/about">About</a>
<a href="/about#team">Team anchor</a>
<a href="https://ext.example/x">External</a>
<a href="mailto:x@y.z">Mail</a>
<a href="javascript:void(0)">JS</a>
<img src="ok.png" alt="described">
<script type="application/ld+json">{"@context": "https://schema.org"}</script>
</body></html>"""

BAD_PAGE = """<html><head>
<meta name="robots" content="noindex, nofollow">
</head><body>
<h1>First</h1><h1>Second</h1>
<img src="art.png">
<script type="application/ld+json">{not json}</script>
</body></html>"""


def _linked(*hrefs, title="a fixture title long enough for the window"):
    links = "".join(f'<a href="{h}">x</a>' for h in hrefs)
    return f"<html><head><title>{title}</title></head><body>{links}</body></html>"


def _fake_site(pages):
    """Fetch fake serving a dict of url -> html (offline invariant); unknown
    URLs answer 404 like a static host would."""
    calls = []

    def fetch(url):
        calls.append(url)
        body = pages.get(url)
        if body is None:
            return {
                "status": 404,
                "final_url": url,
                "redirects": [],
                "content_type": "text/html",
                "headers": {},
                "body": "nope",
                "error": None,
            }
        return {
            "status": 200,
            "final_url": url,
            "redirects": [],
            "content_type": "text/html; charset=utf-8",
            "headers": {"Server": "t"},
            "body": body,
            "error": None,
        }

    return fetch, calls


# ---- page fact extraction ---------------------------------------------------


def test_parse_page_extracts_the_audit_surface():
    facts = seo.parse_page(CLEAN_PAGE, "https://site.test/")
    assert facts["title"] == "Scout SEO Fixture — a Clean Test Page"
    assert facts["title_line"] > 0
    assert facts["description"].startswith("A deterministic fixture")
    assert facts["canonical"] == "https://site.test/"
    assert facts["noindex"] is False
    assert [h["text"] for h in facts["h1"]] == ["One Clean Heading"]
    assert {"og:title", "og:description", "og:image"} <= set(facts["og"])
    assert facts["twitter"]["twitter:card"] == "summary"
    # fragment dedupes, mailto:/javascript: drop, internal/external split by host
    assert facts["links"]["internal"] == ["https://site.test/about"]
    assert facts["links"]["external"] == ["https://ext.example/x"]
    assert facts["images"] == {"total": 1, "missing_alt": []}
    assert [b["ok"] for b in facts["json_ld"]] == [True]
    assert facts["word_count"] > 10


def test_parse_page_base_href_and_malformed_html():
    html = (
        '<html><head><base href="https://other.test/sub/"><title>t</title>'
        '</head><body><a href="page.html">x</a></body></html>'
    )
    facts = seo.parse_page(html, "https://site.test/")
    # <base> wins for resolution; the split still keys on the page URL's host
    assert facts["links"]["external"] == ["https://other.test/sub/page.html"]
    assert facts["links"]["internal"] == []
    # tag soup never raises (edge case: truncated markup mid-tag)
    soup = seo.parse_page("<title>Un<terminated <p><a href=", "https://site.test/")
    assert soup["url"] == "https://site.test/" and soup["images"]["total"] == 0
    empty = seo.parse_page("", "https://site.test/")
    assert empty["title"] is None and empty["word_count"] == 0


# ---- the audit pass ---------------------------------------------------------


def test_audit_clean_page_has_no_findings():
    facts = seo.parse_page(CLEAN_PAGE, "https://site.test/")
    assert seo.audit_page("https://site.test/", status=200, facts=facts) == []


def test_audit_flags_the_on_page_matrix():
    facts = seo.parse_page(BAD_PAGE, "https://site.test/x")
    diags = seo.audit_page("https://site.test/x", status=200, facts=facts)
    by_rule = {d["rule"]: d for d in diags}
    assert set(by_rule) == {
        "seo:title-missing",
        "seo:description-missing",
        "seo:canonical-missing",
        "seo:noindex",
        "seo:h1-multiple",
        "seo:og-incomplete",
        "seo:twitter-incomplete",
        "seo:img-alt",
        "seo:jsonld-invalid",
    }
    assert by_rule["seo:title-missing"]["severity"] == "error"
    assert by_rule["seo:jsonld-invalid"]["severity"] == "error"
    assert by_rule["seo:jsonld-invalid"]["line"] > 0  # points at the block
    assert by_rule["seo:img-alt"]["suggestion"] == "first: art.png"
    assert "2 <h1>" in by_rule["seo:h1-multiple"]["message"]


def test_audit_reachability_gates_on_page_checks():
    facts = seo.parse_page(CLEAN_PAGE, "https://site.test/")
    down = seo.audit_page(
        "https://site.test/", status=None, facts=None, error="TimeoutError: x"
    )
    assert [d["rule"] for d in down] == ["seo:unreachable"]
    assert down[0]["severity"] == "error" and "TimeoutError" in down[0]["message"]
    # an error body's markup is not the deployed content — no on-page noise
    gone = seo.audit_page("https://site.test/", status=404, facts=facts)
    assert [d["rule"] for d in gone] == ["seo:http-error"]
    one_hop = seo.audit_page(
        "https://site.test/",
        status=200,
        facts=facts,
        redirects=[{"code": 301, "to": "https://site.test/new"}],
    )
    assert [(d["rule"], d["severity"]) for d in one_hop] == [
        ("seo:redirect", "suggestion")
    ]
    chain = seo.audit_page(
        "https://site.test/",
        status=200,
        facts=facts,
        redirects=[{"code": 301, "to": "u1"}, {"code": 302, "to": "u2"}],
    )
    assert [(d["rule"], d["severity"]) for d in chain] == [
        ("seo:redirect-chain", "warning")
    ]


def test_duplicate_titles_hash_normalized():
    assert seo.title_fingerprint("My  Page") == seo.title_fingerprint("my page")
    diags = seo.duplicate_titles(
        [("u1", "My  Page"), ("u2", "my page"), ("u3", "Other"), ("u4", None)]
    )
    assert [d["path"] for d in diags] == ["u1", "u2"]
    assert all(d["rule"] == "seo:title-duplicate" for d in diags)
    assert "shared by 2 pages" in diags[0]["message"]


# ---- config is policy-as-config ---------------------------------------------


def test_load_config_overlay_changes_the_verdict(tmp_path):
    facts = seo.parse_page(_linked(title="Hi"), "https://site.test/")
    rules = {
        d["rule"] for d in seo.audit_page("https://site.test/", status=200, facts=facts)
    }
    assert "seo:title-length" in rules  # 2 chars misses the default 30-60 window
    overlay = tmp_path / "seo.json"
    overlay.write_text(json.dumps({"title": {"min": 1, "max": 60}}), encoding="utf-8")
    cfg = seo.load_config(str(overlay))
    assert cfg["title"] == {"min": 1, "max": 60}
    assert cfg["description"] == seo.DEFAULT_CONFIG["description"]  # defaults kept
    relaxed = {
        d["rule"]
        for d in seo.audit_page(
            "https://site.test/", status=200, facts=facts, config=cfg
        )
    }
    assert "seo:title-length" not in relaxed


def test_load_config_rejects_bad_shapes(tmp_path):
    bad = (
        "[1]",
        '{"nope": 1}',
        '{"title": "wide"}',
        '{"title": {"min": "x"}}',
        '{"title": {"min": 50, "max": 10}}',
        '{"og_required": "og:title"}',
    )
    for raw in bad:
        f = tmp_path / "bad.json"
        f.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            seo.load_config(str(f))


# ---- polite resumable crawl -------------------------------------------------


def test_crawl_stays_same_host_and_honors_robots():
    pages = {
        "https://site.test/": _linked(
            "/about", "/private/secret", "https://ext.example/x"
        ),
        "https://site.test/about": _linked("/"),
    }
    fetch, calls = _fake_site(pages)
    conn = seo.open_store(":memory:")
    robots = seo.robots_parser(
        "https://site.test/", "User-agent: *\nDisallow: /private"
    )
    res = seo.crawl(conn, "https://site.test/", fetch, robots=robots, ts=1.0)
    assert res["fetched"] == 2 and res["skipped_robots"] == 1
    assert res["frontier"] == {"done": 2, "skipped": 1}
    assert all("ext.example" not in c and "/private" not in c for c in calls)
    urls = [r["url"] for r in seo.site_rows(conn, "https://site.test/")]
    assert urls == ["https://site.test/", "https://site.test/about"]


def test_crawl_budget_bounds_and_frontier_resumes():
    pages = {"https://site.test/": _linked("/p1", "/p2", "/p3", "/p4")}
    for i in range(1, 5):
        pages[f"https://site.test/p{i}"] = _linked(
            title=f"page p{i} title padded to fit window"
        )
    conn = seo.open_store(":memory:")
    fetch1, _ = _fake_site(pages)
    res1 = seo.crawl(conn, "https://site.test/", fetch1, max_pages=2, ts=1.0)
    assert res1["fetched"] == 2 and res1["frontier"]["pending"] == 3
    fetch2, calls2 = _fake_site(pages)
    res2 = seo.crawl(conn, "https://site.test/", fetch2, max_pages=10, ts=2.0)
    assert res2["fetched"] == 3  # only the pending remainder
    assert res2["pages"] == 5 and res2["frontier"] == {"done": 5}
    assert "https://site.test/" not in calls2  # done rows are never refetched


def test_crawl_depth_zero_fetches_only_the_seed():
    pages = {"https://site.test/": _linked("/p1")}
    fetch, calls = _fake_site(pages)
    conn = seo.open_store(":memory:")
    res = seo.crawl(conn, "https://site.test/", fetch, max_depth=0, ts=1.0)
    assert res["fetched"] == 1 and res["frontier"] == {"done": 1}
    assert calls == ["https://site.test/"]


# ---- crawl audit + the Screaming Frog-shaped CSV ----------------------------


def test_audit_crawl_and_csv_export(tmp_path):
    about = (
        "<html><head><title>Scout SEO Fixture — a Clean Test Page</title>"
        '</head><body><h1>About</h1><a href="/missing">m</a></body></html>'
    )
    pages = {"https://site.test/": CLEAN_PAGE, "https://site.test/about": about}
    fetch, _ = _fake_site(pages)  # /missing 404s like a static host
    conn = seo.open_store(":memory:")
    seo.crawl(conn, "https://site.test/", fetch, ts=1.0)
    diags = seo.audit_crawl(conn, "https://site.test/")
    rules = {d["rule"] for d in diags}
    assert "seo:http-error" in rules and "seo:title-duplicate" in rules
    summary = openswap.summarize(diags)
    assert summary["by_rule"]["seo:title-duplicate"] == 2  # both sharers flagged
    out = tmp_path / "site.csv"
    assert seo.export_csv(conn, "https://site.test/", out) == 3
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == seo.CSV_COLUMNS
    table = {r[0]: dict(zip(seo.CSV_COLUMNS, r)) for r in rows[1:]}
    root = table["https://site.test/"]
    assert root["Status Code"] == "200" and root["Indexability"] == "Indexable"
    assert root["Title 1 Length"] == "37" and root["H1 Count"] == "1"
    missing = table["https://site.test/missing"]
    assert missing["Status Code"] == "404"
    assert missing["Indexability"] == "Non-Indexable"
    assert "seo:http-error" in missing["Issues"]
    assert "seo:title-duplicate" in table["https://site.test/about"]["Issues"]


# ---- family schema + detection ----------------------------------------------


def test_diagnostics_use_the_family_schema():
    facts = seo.parse_page(BAD_PAGE, "https://site.test/x")
    diags = seo.audit_page("https://site.test/x", status=200, facts=facts)
    for d in diags:
        assert set(d) == {
            "path",
            "line",
            "col",
            "rule",
            "severity",
            "message",
            "suggestion",
            "source",
        }
        assert d["severity"] in openswap.SEVERITIES


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.seo import cli as seo_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = seo_cli._capability()
    assert cap["adapter"] == "seo"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "seonaut"
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


def test_cli_seo_hello_envelope():
    r = _cli(["seo", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_seo_sites_default_fleet():
    r = _cli(["seo", "sites"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["data"]["count"] == 8
    assert {"hub", "bhenre"} <= set(data["data"]["sites"])


def test_cli_seo_lint_is_offline_and_gates(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>hi</p></body></html>", encoding="utf-8")
    r = _cli(["seo", "lint", str(page), "--fail-on", "error"])
    assert r.returncode == 1  # title-missing is an error and the gate is armed
    data = json.loads(r.stdout)
    assert data["ok"] is True  # the report itself still emits
    rules = {d["rule"] for d in data["data"]["diagnostics"]}
    assert "seo:title-missing" in rules
    assert data["data"]["summary"]["by_severity"]["error"] >= 1


def test_cli_seo_audit_without_store_fails_actionably(tmp_path):
    r = _cli(["seo", "audit", "bhenre", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no seo crawl store" in data["error"]
    assert "example" in data
