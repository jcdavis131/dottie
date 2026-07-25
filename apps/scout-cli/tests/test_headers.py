"""Headers — openswap #22 (Detectify / Burp Suite Pro (surface) -> stdlib GET +
CSP/HSTS/cookie/mixed-content analysis on the shared seo crawl store). Pure-logic
core tests + the grade table + the exposed-surface parsers + store substrate
reuse + capability detection + the subprocess envelope.

Offline and deterministic by construction: every observation is a hand-built
response dict, the fetcher is always an injected fake, `now` is explicit
wherever it is recorded, and no test opens a socket. Each assertion is written to
FAIL if the check it covers were deleted — the rule codes, severities and grades
are the product, so they are asserted by value, not by "truthiness"."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import headers, openswap, seo

ROOT = Path(__file__).resolve().parents[1]

URL = "https://example.com/"
HTTP_URL = "http://example.com/"

# A response that should score a clean A+ — every check's happy path at once.
CLEAN: list[list[str]] = [
    ["Content-Security-Policy",
     "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"],
    ["Strict-Transport-Security", "max-age=31536000; includeSubDomains"],
    ["X-Frame-Options", "DENY"],
    ["X-Content-Type-Options", "nosniff"],
    ["Referrer-Policy", "strict-origin-when-cross-origin"],
    ["Permissions-Policy", "geolocation=()"],
]


# Three independent ERRORS at once — the F fixture (unsafe CSP, forgotten HSTS,
# a cookie with no Secure).
NASTY: list[list[str]] = [
    ["Content-Security-Policy", "script-src 'unsafe-inline'"],
    ["Strict-Transport-Security", "max-age=0"],
    ["Set-Cookie", "sid=1"],
]


def _obs(*, status=200, final_url=URL, headers_=None, body="", error=None):
    """One response observation in the shape analyze() consumes."""
    return {
        "status": status,
        "final_url": final_url,
        "headers": CLEAN if headers_ is None else headers_,
        "body": body,
        "error": error,
    }


def _with(*extra, drop=()):
    """CLEAN minus the named headers, plus `extra` pairs."""
    lower = {d.lower() for d in drop}
    return [p for p in CLEAN if p[0].lower() not in lower] + [list(e) for e in extra]


def _codes(verdict):
    return [r["code"] for r in verdict["reasons"]]


def _sev(verdict, code):
    return next(r["severity"] for r in verdict["reasons"] if r["code"] == code)


def _mem():
    return headers.open_headers_store(":memory:")


# ---- header normalization ---------------------------------------------------


def test_normalize_headers_accepts_pairs_dicts_and_dict_of_lists():
    pairs = headers.normalize_headers([["Content-Type", " text/html "], ("Set-Cookie", "a=1")])
    assert pairs == {"content-type": ["text/html"], "set-cookie": ["a=1"]}
    assert headers.normalize_headers({"X-Frame-Options": "DENY"}) == {
        "x-frame-options": ["DENY"]
    }
    assert headers.normalize_headers({"Set-Cookie": ["a=1", "b=2"]}) == {
        "set-cookie": ["a=1", "b=2"]
    }


def test_normalize_headers_preserves_repeats_and_survives_junk():
    hmap = headers.normalize_headers(
        [["Set-Cookie", "a=1"], ["set-cookie", "b=2"], ["SET-COOKIE", "c=3"]]
    )
    assert hmap["set-cookie"] == ["a=1", "b=2", "c=3"]  # repeats are the point
    assert headers.normalize_headers([["", "x"], ["  ", "y"]]) == {}  # nameless dropped
    assert headers.normalize_headers([("only-one",), "junk", 7]) == {}
    for junk in (None, "a string", 42):
        assert headers.normalize_headers(junk) == {}


def test_header_value_takes_the_first_and_none_when_absent():
    hmap = headers.normalize_headers([["X-Test", "one"], ["x-test", "two"]])
    assert headers.header_value(hmap, "X-TEST") == "one"
    assert headers.header_value(hmap, "x-missing") is None


# ---- CSP parsing ------------------------------------------------------------


def test_parse_csp_splits_directives_and_keeps_the_first_duplicate():
    csp = headers.parse_csp("default-src 'self'; SCRIPT-SRC a b ; script-src c")
    assert csp["default-src"] == ["'self'"]
    assert csp["script-src"] == ["a", "b"]  # spec: later duplicate is ignored
    assert headers.parse_csp("") == {}
    assert headers.parse_csp(";;  ;") == {}
    assert headers.parse_csp("upgrade-insecure-requests") == {
        "upgrade-insecure-requests": []
    }


def test_effective_sources_falls_back_to_default_src():
    csp = headers.parse_csp("default-src 'self'; img-src *")
    assert headers.effective_sources(csp, "img-src") == ["*"]
    assert headers.effective_sources(csp, "script-src") == ["'self'"]  # fallback
    assert headers.effective_sources(headers.parse_csp("img-src *"), "script-src") is None


# ---- HSTS parsing -----------------------------------------------------------


def test_parse_hsts_reads_max_age_and_flags_case_insensitively():
    h = headers.parse_hsts("max-age=31536000; includeSubDomains; preload")
    assert h == {"max_age": 31536000, "include_subdomains": True, "preload": True}
    assert headers.parse_hsts('MAX-AGE = "600" ; INCLUDESUBDOMAINS')["max_age"] == 600
    assert headers.parse_hsts("max-age=600")["include_subdomains"] is False
    assert headers.parse_hsts("max-age=0")["max_age"] == 0  # never confused with absent
    for junk in ("", "includeSubDomains", "max-age=abc"):
        assert headers.parse_hsts(junk)["max_age"] is None


# ---- cookie parsing ---------------------------------------------------------


def test_parse_cookie_reads_name_flags_and_attributes():
    c = headers.parse_cookie("sid=abc; Path=/; Secure; HttpOnly; SameSite=Lax")
    assert c["name"] == "sid" and c["path"] == "/"
    assert c["secure"] is True and c["httponly"] is True and c["samesite"] == "Lax"
    lower = headers.parse_cookie("sid=abc; secure; httponly; samesite=none")
    assert lower["secure"] is True and lower["httponly"] is True
    assert lower["samesite"] == "none"  # attribute names are case-insensitive
    bare = headers.parse_cookie("sid=abc")
    assert bare["secure"] is False and bare["httponly"] is False
    assert bare["samesite"] is None and bare["domain"] is None
    assert headers.parse_cookie("=; Secure")["name"] == ""
    assert headers.parse_cookie("__Host-x=1; Domain=example.com")["domain"] == (
        "example.com"
    )


# ---- exposed surface: directory listing -------------------------------------


def test_directory_listing_recognizes_each_server_flavor():
    assert headers.directory_listing("<html><title>Index of /assets</title>") == "index-of"
    assert headers.directory_listing("<h1>Index of /pub/</h1>") == "index-of"
    assert headers.directory_listing("<h1>Directory Listing For /docs</h1>") == "tomcat"
    assert headers.directory_listing("<a href='/'>[To Parent Directory]</a>") == "iis"
    assert headers.directory_listing("<html><title>Home</title><h1>Welcome</h1>") is None
    assert headers.directory_listing("") is None
    assert headers.directory_listing(None) is None  # no body != a clean body


# ---- exposed surface: subresources / mixed content --------------------------

MIXED_BODY = """<html><head>
<link rel="stylesheet" href="http://cdn.example.com/a.css">
<link rel="icon" href="http://cdn.example.com/favicon.ico">
<script src="http://cdn.example.com/a.js"></script>
<script src="https://cdn.example.com/safe.js"></script>
<script src="//cdn.example.com/proto-relative.js"></script>
</head><body>
<img src="http://cdn.example.com/a.png">
<img src="/local.png">
<iframe src="http://cdn.example.com/frame.html"></iframe>
<script src="data:text/javascript,1"></script>
<a href="http://plain.example.com/page">a link is not a subresource</a>
</body></html>"""


def test_subresources_resolves_and_classifies_active_vs_passive():
    found = headers.subresources(MIXED_BODY, URL)
    by_url = {f["url"]: f for f in found}
    assert by_url["http://cdn.example.com/a.css"]["active"] is True  # rel=stylesheet
    assert by_url["http://cdn.example.com/favicon.ico"]["active"] is False  # rel=icon
    assert by_url["http://cdn.example.com/a.js"]["active"] is True
    assert by_url["http://cdn.example.com/a.png"]["active"] is False
    assert by_url["http://cdn.example.com/frame.html"]["active"] is True
    # protocol-relative inherits the page scheme; relative resolves against it
    assert "https://cdn.example.com/proto-relative.js" in by_url
    assert "https://example.com/local.png" in by_url
    # non-fetch schemes and plain anchors are not subresources
    assert not [f for f in found if f["url"].startswith("data:")]
    assert "http://plain.example.com/page" not in by_url
    assert headers.subresources(None, URL) == []
    assert all(f["line"] >= 1 for f in found)  # positions come from the parser


def test_mixed_content_only_for_https_pages_and_only_http_subresources():
    mixed = headers.mixed_content(URL, MIXED_BODY)
    urls = {m["url"] for m in mixed}
    assert urls == {
        "http://cdn.example.com/a.css",
        "http://cdn.example.com/favicon.ico",
        "http://cdn.example.com/a.js",
        "http://cdn.example.com/a.png",
        "http://cdn.example.com/frame.html",
    }
    assert sum(1 for m in mixed if m["active"]) == 3  # css + js + iframe
    assert sum(1 for m in mixed if not m["active"]) == 2  # favicon + img
    # an http page is entirely plaintext — "mixed" is not the finding there
    assert headers.mixed_content(HTTP_URL, MIXED_BODY) == []
    assert headers.mixed_content(URL, None) == []


def test_form_action_and_object_data_count_as_active_surface():
    body = '<form action="http://example.com/post"></form><object data="http://x/y.swf">'
    mixed = headers.mixed_content(URL, body)
    assert [m["attr"] for m in mixed] == ["action", "data"]
    assert all(m["active"] for m in mixed)


# ---- analyze: the clean baseline --------------------------------------------


def test_analyze_clean_response_is_ok_and_a_plus():
    v = headers.analyze(URL, _obs())
    assert v["reasons"] == []
    assert v["severity"] == "ok" and v["grade"] == "A+"
    assert v["https"] is True and v["reachable"] is True and v["status"] == 200
    assert v["checks_skipped"] == [] and v["body_available"] is True
    assert "content-security-policy" in v["headers_seen"]


# ---- analyze: CSP -----------------------------------------------------------


def test_analyze_csp_missing_and_report_only():
    missing = headers.analyze(URL, _obs(headers_=_with(drop=["Content-Security-Policy"])))
    assert "csp-missing" in _codes(missing)
    assert _sev(missing, "csp-missing") == "warning"
    ro = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Content-Security-Policy-Report-Only", "default-src 'self'"],
            drop=["Content-Security-Policy"],
        )),
    )
    assert "csp-report-only" in _codes(ro) and "csp-missing" not in _codes(ro)


def test_analyze_csp_unsafe_sources_and_wildcards():
    unsafe = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Content-Security-Policy",
             "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' *; "
             "object-src 'none'; frame-ancestors 'none'"],
            drop=["Content-Security-Policy"],
        )),
    )
    codes = _codes(unsafe)
    assert "csp-unsafe-inline" in codes and _sev(unsafe, "csp-unsafe-inline") == "error"
    assert "csp-unsafe-eval" in codes and _sev(unsafe, "csp-unsafe-eval") == "warning"
    assert "csp-wildcard-script" in codes
    assert unsafe["severity"] == "error" and unsafe["grade"] == "D"


def test_analyze_csp_inherits_script_restrictions_from_default_src():
    inherited = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Content-Security-Policy",
             "default-src 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'"],
            drop=["Content-Security-Policy"],
        )),
    )
    # no script-src at all, but default-src carries it — a browser would too
    assert "csp-unsafe-inline" in _codes(inherited)
    assert "csp-no-script-src" not in _codes(inherited)
    naked = headers.analyze(
        URL,
        _obs(headers_=_with(["Content-Security-Policy", "img-src *"],
                            drop=["Content-Security-Policy"])),
    )
    assert "csp-no-script-src" in _codes(naked)


def test_analyze_csp_hygiene_suggestions_and_duplicate_policies():
    thin = headers.analyze(
        URL,
        _obs(headers_=_with(["Content-Security-Policy", "default-src 'self'"],
                            drop=["Content-Security-Policy"])),
    )
    assert "csp-no-frame-ancestors" in _codes(thin)  # default-src never fills this in
    assert "csp-no-object-src" in _codes(thin)
    assert _sev(thin, "csp-no-object-src") == "suggestion"
    dupes = headers.analyze(
        URL,
        _obs(headers_=CLEAN + [["Content-Security-Policy", "default-src 'none'"]]),
    )
    assert "csp-duplicate" in _codes(dupes)
    same = headers.analyze(URL, _obs(headers_=CLEAN + [list(CLEAN[0])]))
    assert "csp-duplicate" not in _codes(same)  # identical repeats are harmless


# ---- analyze: HSTS ----------------------------------------------------------


def test_analyze_hsts_windows_and_flags():
    absent = headers.analyze(URL, _obs(headers_=_with(drop=["Strict-Transport-Security"])))
    assert "hsts-missing" in _codes(absent)
    assert _sev(absent, "hsts-missing") == "warning"  # same opinion as certmon's
    zero = headers.analyze(
        URL,
        _obs(headers_=_with(["Strict-Transport-Security", "max-age=0"],
                            drop=["Strict-Transport-Security"])),
    )
    assert "hsts-disabled" in _codes(zero) and _sev(zero, "hsts-disabled") == "error"
    short = headers.analyze(
        URL,
        _obs(headers_=_with(["Strict-Transport-Security", "max-age=600; includeSubDomains"],
                            drop=["Strict-Transport-Security"])),
    )
    assert "hsts-short" in _codes(short) and "hsts-no-subdomains" not in _codes(short)
    bare = headers.analyze(
        URL,
        _obs(headers_=_with(["Strict-Transport-Security", "max-age=31536000"],
                            drop=["Strict-Transport-Security"])),
    )
    assert _codes(bare) == ["hsts-no-subdomains"]
    broken = headers.analyze(
        URL,
        _obs(headers_=_with(["Strict-Transport-Security", "includeSubDomains"],
                            drop=["Strict-Transport-Security"])),
    )
    assert "hsts-no-max-age" in _codes(broken)


def test_analyze_hsts_floor_and_preload_are_config():
    obs = _obs(headers_=_with(
        ["Strict-Transport-Security", "max-age=600; includeSubDomains"],
        drop=["Strict-Transport-Security"],
    ))
    lenient = headers.load_config()
    lenient["hsts_min_age"] = 100
    assert "hsts-short" not in _codes(headers.analyze(URL, obs, config=lenient))
    strict = headers.load_config()
    strict["require_hsts_preload"] = True
    assert "hsts-no-preload" in _codes(headers.analyze(URL, obs, config=strict))
    assert "hsts-no-preload" not in _codes(headers.analyze(URL, obs))  # off by default


def test_analyze_skips_hsts_entirely_on_a_plaintext_response():
    v = headers.analyze(
        HTTP_URL,
        _obs(final_url=HTTP_URL, headers_=_with(drop=["Strict-Transport-Security"])),
    )
    assert "no-https" in _codes(v) and _sev(v, "no-https") == "error"
    # HSTS is meaningless over plaintext, so it is not double-reported
    assert not [c for c in _codes(v) if c.startswith("hsts-")]


# ---- analyze: framing, sniffing, referrer, permissions, CORS, banner --------


def test_analyze_framing_uses_csp_frame_ancestors_as_the_substitute():
    no_xfo = headers.analyze(URL, _obs(headers_=_with(drop=["X-Frame-Options"])))
    assert "xfo-missing" not in _codes(no_xfo)  # frame-ancestors 'none' covers it
    neither = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Content-Security-Policy", "default-src 'self'; object-src 'none'"],
            drop=["X-Frame-Options", "Content-Security-Policy"],
        )),
    )
    assert "xfo-missing" in _codes(neither)
    allow_from = headers.analyze(
        URL,
        _obs(headers_=_with(["X-Frame-Options", "ALLOW-FROM https://friend.example"],
                            drop=["X-Frame-Options"])),
    )
    assert "xfo-allow-from" in _codes(allow_from)
    junk = headers.analyze(
        URL, _obs(headers_=_with(["X-Frame-Options", "nope"], drop=["X-Frame-Options"]))
    )
    assert "xfo-invalid" in _codes(junk)
    same_origin = headers.analyze(
        URL,
        _obs(headers_=_with(["X-Frame-Options", "sameorigin"], drop=["X-Frame-Options"])),
    )
    assert not [c for c in _codes(same_origin) if c.startswith("xfo-")]


def test_analyze_nosniff_and_referrer_policy():
    absent = headers.analyze(URL, _obs(headers_=_with(drop=["X-Content-Type-Options"])))
    assert "xcto-missing" in _codes(absent)
    wrong = headers.analyze(
        URL,
        _obs(headers_=_with(["X-Content-Type-Options", "sniff"],
                            drop=["X-Content-Type-Options"])),
    )
    assert "xcto-invalid" in _codes(wrong)
    no_ref = headers.analyze(URL, _obs(headers_=_with(drop=["Referrer-Policy"])))
    assert "referrer-missing" in _codes(no_ref)
    weak = headers.analyze(
        URL,
        _obs(headers_=_with(["Referrer-Policy", "no-referrer-when-downgrade, unsafe-url"],
                            drop=["Referrer-Policy"])),
    )
    assert "referrer-weak" in _codes(weak)
    ok_list = headers.analyze(
        URL,
        _obs(headers_=_with(["Referrer-Policy", "no-referrer, strict-origin"],
                            drop=["Referrer-Policy"])),
    )
    assert not [c for c in _codes(ok_list) if c.startswith("referrer-")]


def test_analyze_permissions_policy_accepts_the_legacy_header_and_is_config():
    absent = headers.analyze(URL, _obs(headers_=_with(drop=["Permissions-Policy"])))
    assert _codes(absent) == ["permissions-policy-missing"]
    assert _sev(absent, "permissions-policy-missing") == "suggestion"
    legacy = headers.analyze(
        URL,
        _obs(headers_=_with(["Feature-Policy", "geolocation 'none'"],
                            drop=["Permissions-Policy"])),
    )
    assert _codes(legacy) == []
    off = headers.load_config()
    off["require_permissions_policy"] = False
    assert headers.analyze(URL, _obs(headers_=_with(drop=["Permissions-Policy"])),
                           config=off)["reasons"] == []


def test_analyze_cors_wildcard_escalates_with_credentials():
    wild = headers.analyze(URL, _obs(headers_=_with(["Access-Control-Allow-Origin", "*"])))
    assert _codes(wild) == ["cors-wildcard"]
    assert _sev(wild, "cors-wildcard") == "suggestion"
    creds = headers.analyze(
        URL,
        _obs(headers_=_with(["Access-Control-Allow-Origin", "*"],
                            ["Access-Control-Allow-Credentials", "true"])),
    )
    assert _codes(creds) == ["cors-wildcard-credentials"]
    assert creds["severity"] == "error"
    named = headers.analyze(
        URL, _obs(headers_=_with(["Access-Control-Allow-Origin", "https://friend.example"]))
    )
    assert _codes(named) == []


def test_analyze_flags_version_banners_as_info_only():
    v = headers.analyze(
        URL, _obs(headers_=_with(["Server", "nginx/1.25.3"], ["X-Powered-By", "PHP/8.2"]))
    )
    assert _codes(v) == ["server-banner", "server-banner"]
    assert v["severity"] == "info"
    assert v["grade"] == "A+"  # a banner is worth saying, not a header failure
    quiet = headers.analyze(URL, _obs(headers_=_with(["Server", "nginx"])))
    assert _codes(quiet) == []  # no version, no fingerprint finding


# ---- analyze: cookies -------------------------------------------------------


def test_analyze_grades_every_cookie_not_just_the_last():
    v = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Set-Cookie", "sid=1; Secure; HttpOnly; SameSite=Lax"],
            ["Set-Cookie", "tracker=2"],
        )),
    )
    codes = _codes(v)
    assert codes.count("cookie-insecure") == 1  # only the second cookie
    assert "cookie-no-httponly" in codes and "cookie-no-samesite" in codes
    assert [c["name"] for c in v["cookies"]] == ["sid", "tracker"]
    assert v["cookies"][0]["secure"] is True and v["cookies"][1]["secure"] is False
    assert any("tracker" in r["message"] for r in v["reasons"])


def test_analyze_cookie_secure_is_only_required_over_https():
    plain = headers.analyze(
        HTTP_URL,
        _obs(final_url=HTTP_URL,
             headers_=_with(["Set-Cookie", "sid=1; HttpOnly; SameSite=Lax"])),
    )
    # the transport itself is the finding; Secure would not save this cookie
    assert "cookie-insecure" not in _codes(plain)
    assert "no-https" in _codes(plain)


def test_analyze_samesite_none_requires_secure():
    bad = headers.analyze(
        URL,
        _obs(headers_=_with(["Set-Cookie", "sid=1; HttpOnly; SameSite=None"])),
    )
    assert "cookie-samesite-none-insecure" in _codes(bad)
    assert "cookie-no-samesite" not in _codes(bad)  # it IS set, just wrongly
    good = headers.analyze(
        URL,
        _obs(headers_=_with(["Set-Cookie", "sid=1; Secure; HttpOnly; SameSite=None"])),
    )
    assert _codes(good) == []


def test_analyze_enforces_cookie_name_prefix_contracts():
    host_ok = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Set-Cookie", "__Host-sid=1; Secure; HttpOnly; SameSite=Lax; Path=/"])),
    )
    assert _codes(host_ok) == []
    host_bad = headers.analyze(
        URL,
        _obs(headers_=_with(
            ["Set-Cookie",
             "__Host-sid=1; Secure; HttpOnly; SameSite=Lax; Path=/; Domain=example.com"])),
    )
    assert _codes(host_bad) == ["cookie-prefix-violation"]
    assert host_bad["severity"] == "error"
    secure_bad = headers.analyze(
        HTTP_URL,
        _obs(final_url=HTTP_URL,
             headers_=_with(["Set-Cookie", "__Secure-sid=1; HttpOnly; SameSite=Lax"])),
    )
    assert "cookie-prefix-violation" in _codes(secure_bad)


# ---- analyze: surface + transport + honesty ---------------------------------


def test_analyze_reports_directory_listing_and_mixed_content_from_the_body():
    v = headers.analyze(URL, _obs(body=MIXED_BODY))
    codes = _codes(v)
    assert "mixed-content-active" in codes and _sev(v, "mixed-content-active") == "error"
    assert "mixed-content-passive" in codes
    assert len(v["mixed_content"]) == 5
    active = next(r for r in v["reasons"] if r["code"] == "mixed-content-active")
    assert active["message"].startswith("3 http:// subresource(s)")
    assert active["line"] >= 1  # points at the markup
    listing = headers.analyze(URL, _obs(body="<title>Index of /assets</title>"))
    assert "directory-listing" in _codes(listing)
    assert listing["directory_listing"] == "index-of"
    assert listing["severity"] == "error"


def test_analyze_without_a_body_skips_body_checks_instead_of_passing_them():
    v = headers.analyze(URL, _obs(body=None))
    assert v["body_available"] is False
    assert v["checks_skipped"] == ["mixed-content", "directory-listing"]
    assert not [c for c in _codes(v) if c.startswith("mixed-content")]
    assert v["directory_listing"] is None
    # an EMPTY body is a real observation, not a missing one
    assert headers.analyze(URL, _obs(body=""))["checks_skipped"] == []


def test_analyze_unreachable_has_no_grade_and_one_reason():
    v = headers.analyze(URL, _obs(status=None, error="TimeoutError: x", body=None))
    assert v["reachable"] is False and v["severity"] == "error"
    assert _codes(v) == ["unreachable"]
    assert v["grade"] is None  # never a fabricated F — there were no headers
    assert "TimeoutError" in v["reasons"][0]["message"]


def test_analyze_notes_a_non_2xx_grade_and_an_http_to_https_upgrade():
    err = headers.analyze(URL, _obs(status=503))
    assert _codes(err) == ["graded-non-2xx"]
    assert err["severity"] == "info" and err["grade"] == "A+"
    upgraded = headers.analyze(HTTP_URL, _obs(final_url=URL))
    assert _codes(upgraded) == ["http-upgraded"]
    assert "no-https" not in _codes(upgraded)  # the redirect fixed it
    assert upgraded["https"] is True


def test_analyze_missing_everything_names_every_missing_header():
    v = headers.analyze(HTTP_URL, _obs(final_url=HTTP_URL, headers_=[]))
    codes = set(_codes(v))
    assert {"no-https", "csp-missing", "xfo-missing", "xcto-missing",
            "referrer-missing", "permissions-policy-missing"} <= codes
    assert "hsts-missing" not in codes  # plaintext: no-https is the finding
    assert v["severity"] == "error"
    assert v["grade"] == "D"  # one error caps it; the reason list is the payload
    https_naked = headers.analyze(URL, _obs(headers_=[]))
    assert "hsts-missing" in _codes(https_naked)  # over TLS it IS a finding
    assert https_naked["severity"] == "warning"
    assert https_naked["grade"] == "D"  # five missing headers, no error, still D


def test_analyze_three_independent_errors_is_an_f():
    v = headers.analyze(URL, _obs(headers_=NASTY))
    assert {"csp-unsafe-inline", "hsts-disabled", "cookie-insecure"} <= set(_codes(v))
    assert v["severity"] == "error" and v["grade"] == "F"


# ---- severity/grade contract + config ---------------------------------------


def test_every_rule_code_the_core_emits_has_a_severity_and_a_remedy():
    assert len(headers.RULES) >= 30
    for code, (severity, remedy) in headers.RULES.items():
        assert severity in openswap.SEVERITIES, code
        assert isinstance(remedy, str) and len(remedy) > 15, code


def test_grade_table_is_total_and_ignores_info():
    def reasons(**counts):
        out = []
        for severity, n in counts.items():
            out.extend({"code": "x", "severity": severity} for _ in range(n))
        return out

    assert headers.grade([]) == "A+"
    assert headers.grade(reasons(info=5)) == "A+"  # disclosure notes never grade
    assert headers.grade(reasons(suggestion=1)) == "A"
    assert headers.grade(reasons(warning=1)) == "B"
    assert headers.grade(reasons(warning=2, suggestion=9)) == "B"
    assert headers.grade(reasons(warning=3)) == "C"
    assert headers.grade(reasons(warning=4)) == "C"
    assert headers.grade(reasons(warning=5)) == "D"  # no errors, no headers either
    assert headers.grade(reasons(error=1)) == "D"
    assert headers.grade(reasons(error=1, warning=9)) == "D"
    assert headers.grade(reasons(error=2)) == "E"
    assert headers.grade(reasons(error=3)) == "F"
    assert headers.grade(reasons(error=17)) == "F"
    # monotone: adding a finding never improves the letter
    ladder = ["A+", "A", "B", "C", "D", "E", "F"]
    grades = [
        headers.grade(g)
        for g in ([], reasons(suggestion=1), reasons(warning=1), reasons(warning=3),
                  reasons(error=1), reasons(error=2), reasons(error=3))
    ]
    assert grades == ladder


def test_worst_severity_ranks_the_family_scale():
    assert headers.worst_severity([]) == "ok"
    assert headers.worst_severity([{"severity": "info"}]) == "info"
    assert headers.worst_severity([{"severity": "suggestion"}, {"severity": "info"}]) == (
        "suggestion"
    )
    assert headers.worst_severity(
        [{"severity": "warning"}, {"severity": "error"}, {"severity": "info"}]
    ) == "error"


def test_config_can_ignore_a_rule_and_override_a_severity(tmp_path):
    cfg_file = tmp_path / "headers.json"
    cfg_file.write_text(
        json.dumps({
            "ignore_rules": ["permissions-policy-missing"],
            "severity": {"csp-missing": "error"},
        }),
        encoding="utf-8",
    )
    cfg = headers.load_config(str(cfg_file))
    obs = _obs(headers_=_with(drop=["Permissions-Policy", "Content-Security-Policy"]))
    v = headers.analyze(URL, obs, config=cfg)
    assert "permissions-policy-missing" not in _codes(v)  # suppressed by config
    assert _sev(v, "csp-missing") == "error"  # promoted by config
    assert v["severity"] == "error" and v["grade"] == "D"
    # the same observation under defaults is a warning-only B
    base = headers.analyze(URL, obs)
    assert _sev(base, "csp-missing") == "warning" and base["grade"] == "B"


def test_load_config_defaults_and_rejects_typos(tmp_path):
    cfg = headers.load_config()
    assert cfg["hsts_min_age"] == headers.HSTS_MIN_AGE == 15_552_000
    assert cfg["require_permissions_policy"] is True
    assert cfg["ignore_rules"] == [] and cfg["severity"] == {}
    assert "/assets/" in cfg["dir_probe_paths"]
    cfg["ignore_rules"].append("mutated")
    assert headers.load_config()["ignore_rules"] == []  # deep-copied, never shared

    def write(payload):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return str(p)

    for payload in (
        {"hsts_minage": 1},                       # unknown key
        {"hsts_min_age": -1},                     # bad value
        {"hsts_min_age": "long"},                 # bad type
        {"ignore_rules": ["no-such-rule"]},       # typo'd rule silently disabling
        {"ignore_rules": "csp-missing"},          # wrong shape
        {"severity": {"csp-missing": "critical"}},  # not a family severity
        {"severity": {"nope": "error"}},          # unknown rule
        {"severity": ["csp-missing"]},            # wrong shape
        {"dir_probe_paths": [1, 2]},              # wrong element type
    ):
        with pytest.raises(ValueError):
            headers.load_config(write(payload))
    with pytest.raises(ValueError):
        headers.load_config(write(["not", "an", "object"]))


# ---- family diagnostics schema ----------------------------------------------


def test_to_diagnostics_emits_one_finding_per_reason_with_a_remedy():
    results = [
        headers.analyze(URL, _obs()),  # clean: contributes nothing
        headers.analyze(
            "https://example.com/b",
            _obs(final_url="https://example.com/b",
                 headers_=_with(drop=["X-Content-Type-Options", "Referrer-Policy"])),
        ),
    ]
    diags = headers.to_diagnostics(results)
    rules = [d["rule"] for d in diags]
    assert rules == ["headers:referrer-missing", "headers:xcto-missing"]
    assert all(d["path"] == "https://example.com/b" for d in diags)
    assert all(d["severity"] == "warning" for d in diags)
    assert all(d["suggestion"] for d in diags)  # every finding carries a fix
    assert "example.com/b" in diags[0]["message"]
    summary = openswap.summarize(diags)
    assert summary["total"] == 2
    assert summary["by_severity"]["warning"] == 2
    assert summary["by_rule"] == {"headers:referrer-missing": 1, "headers:xcto-missing": 1}


def test_to_diagnostics_counts_the_same_rule_across_pages():
    results = [
        headers.analyze(f"https://example.com/{n}",
                        _obs(final_url=f"https://example.com/{n}",
                             headers_=_with(drop=["X-Content-Type-Options"])))
        for n in range(3)
    ]
    summary = openswap.summarize(headers.to_diagnostics(results))
    assert summary["by_rule"]["headers:xcto-missing"] == 3
    assert len(summary["files"]) == 3


# ---- targets ----------------------------------------------------------------


def test_default_sites_derive_from_the_seo_fleet_and_are_a_copy():
    sites = headers.default_sites()
    assert sites == seo.DEFAULT_SITES
    assert sites["bhenre"] == "https://www.bhenre.com"
    sites["evil"] = "https://evil.example.com"
    assert "evil" not in seo.DEFAULT_SITES  # mutating the copy cannot widen seo


def test_probe_urls_are_same_origin_rooted_and_deduplicated():
    urls = headers.probe_urls("https://example.com", ["/assets/", "static/", "/assets/"])
    assert urls == [
        "https://example.com/",
        "https://example.com/assets/",
        "https://example.com/static/",
    ]
    assert headers.probe_urls("https://example.com/deep/page?a=1#frag") == [
        "https://example.com/deep/page?a=1"
    ]
    assert headers.probe_urls(URL, []) == [URL]


# ---- store: shared seo substrate, idempotent scans table --------------------


def _tables(conn):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_store_reuses_the_seo_crawl_tables_and_adds_header_scans():
    conn = _mem()
    assert {"frontier", "pages", "meta", "header_scans"} <= _tables(conn)
    # the crawler's substrate stays functional (no parallel store, no shadowing)
    assert conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()["value"] == seo.SCHEMA_VERSION


def test_open_headers_store_is_idempotent(tmp_path):
    db = tmp_path / "seo.db"
    conn = headers.open_headers_store(db)
    rid = headers.record_scan(conn, headers.analyze(URL, _obs()), ts=100.0)
    conn.close()
    conn2 = headers.open_headers_store(db)  # same file, no error, rows survive
    assert "header_scans" in _tables(conn2)
    assert headers.latest_scan(conn2, URL)["id"] == rid


def test_record_scan_persists_grade_codes_and_surface_counts():
    conn = _mem()
    verdict = headers.analyze(
        URL, _obs(headers_=_with(["Set-Cookie", "sid=1"]), body=MIXED_BODY)
    )
    headers.record_scan(conn, verdict, ts=100.0)
    row = headers.latest_scan(conn, URL)
    assert row["ts"] == 100.0 and row["status"] == 200 and row["https"] == 1
    assert row["grade"] == verdict["grade"] and row["severity"] == "error"
    assert set(json.loads(row["codes"])) == set(_codes(verdict))
    assert row["cookies"] == 1
    assert row["mixed_active"] == 3 and row["mixed_passive"] == 2
    assert row["dir_listing"] is None


def test_record_scan_keeps_an_unreachable_observation(tmp_path):
    conn = headers.open_headers_store(tmp_path / "seo.db")
    dead = headers.analyze(URL, _obs(status=None, error="socket.gaierror: nope", body=None))
    headers.record_scan(conn, dead, ts=7.0)
    row = headers.latest_scan(conn, URL)
    assert row["status"] is None and row["grade"] is None
    assert row["severity"] == "error" and "gaierror" in row["error"]


def test_run_pass_records_every_url_and_reports_problems():
    conn = _mem()
    canned = {
        URL: _obs(),
        "https://example.com/bad": _obs(
            final_url="https://example.com/bad", headers_=NASTY
        ),
    }
    res = headers.run_pass(conn, list(canned), lambda u: canned[u], now=100.0)
    sevs = {r["url"]: r["severity"] for r in res["results"]}
    assert sevs == {URL: "ok", "https://example.com/bad": "error"}
    assert [p["url"] for p in res["problems"]] == ["https://example.com/bad"]
    assert res["ts"] == 100.0
    assert len(headers.scan_history(conn, URL)) == 1
    assert headers.latest_scan(conn, "https://example.com/bad")["grade"] == "F"


def test_run_pass_without_record_leaves_the_store_untouched():
    conn = _mem()
    headers.run_pass(conn, [URL], lambda _u: _obs(), now=100.0, record=False)
    assert headers.scan_history(conn, URL) == []
    assert headers.latest_scan(conn, URL) is None


def test_run_pass_honors_the_injected_config():
    conn = _mem()
    cfg = headers.load_config()
    cfg["severity"] = {"permissions-policy-missing": "error"}
    obs = _obs(headers_=_with(drop=["Permissions-Policy"]))
    res = headers.run_pass(conn, [URL], lambda _u: obs, now=1.0, record=False, config=cfg)
    assert res["results"][0]["severity"] == "error"
    assert res["problems"]  # the override reached the verdict, not just the config


def test_history_is_newest_first_and_limited():
    conn = _mem()
    for i, ts in enumerate((10.0, 20.0, 30.0)):
        headers.record_scan(conn, headers.analyze(URL, _obs(status=200 + i)), ts=ts)
    hist = headers.scan_history(conn, URL, limit=2)
    assert [h["ts"] for h in hist] == [30.0, 20.0]
    assert headers.latest_scan(conn, URL)["ts"] == 30.0
    assert len(headers.scan_history(conn, URL)) == 3


def test_scanned_urls_orders_by_recency_and_filters_by_origin():
    conn = _mem()
    headers.record_scan(conn, headers.analyze(URL, _obs()), ts=10.0)
    other = "https://other.example.com/"
    headers.record_scan(conn, headers.analyze(other, _obs(final_url=other)), ts=30.0)
    deep = "https://example.com/assets/"
    headers.record_scan(conn, headers.analyze(deep, _obs(final_url=deep)), ts=20.0)
    assert headers.scanned_urls(conn) == [other, deep, URL]
    assert headers.scanned_urls(conn, prefix="https://example.com/") == [deep, URL]
    assert headers.scanned_urls(conn, prefix="https://nothing/") == []


def test_board_reports_unknown_for_never_scanned_urls():
    conn = _mem()
    headers.record_scan(conn, headers.analyze(URL, _obs()), ts=10.0)
    rows = {b["url"]: b for b in headers.board(conn, [URL, "https://never.example/"])}
    assert rows[URL]["grade"] == "A+" and rows[URL]["severity"] == "ok"
    assert rows[URL]["last_ts"] == 10.0 and rows[URL]["codes"] == []
    # a board that silently dropped what it never measured would be the bug
    assert rows["https://never.example/"]["grade"] == "unknown"
    assert rows["https://never.example/"]["last"] is None


# ---- offline audit over the crawl store the crawler filled ------------------


def _crawl_one(conn, url, response_headers, *, body="<html><title>t</title></html>"):
    """Write a real pages row by running seo.crawl with an injected fetcher."""
    def fetch(u):
        return {
            "status": 200,
            "final_url": u,
            "redirects": [],
            "content_type": "text/html",
            "headers": response_headers,
            "body": body,
            "error": None,
        }

    return seo.crawl(conn, url, fetch, max_pages=1, max_depth=0)


def test_audit_rows_reads_the_crawlers_own_pages_rows():
    conn = _mem()
    _crawl_one(conn, URL, {"Server": "nginx/1.25.3"})
    results = headers.audit_rows(conn, seo.site_key(URL))
    assert len(results) == 1
    v = results[0]
    assert v["url"] == URL and v["status"] == 200
    assert "csp-missing" in _codes(v) and "hsts-missing" in _codes(v)
    assert "server-banner" in _codes(v)
    assert v["grade"] == "D"
    # no body in the store: the body checks are declared skipped, never passed
    assert v["body_available"] is False
    assert v["checks_skipped"] == ["mixed-content", "directory-listing"]
    assert headers.audit_rows(conn, "https://never-crawled.example/") == []


def test_audit_rows_sees_headers_the_crawler_stored_and_honors_config():
    conn = _mem()
    _crawl_one(conn, URL, {p[0]: p[1] for p in CLEAN})
    clean = headers.audit_rows(conn, seo.site_key(URL))[0]
    assert clean["reasons"] == [] and clean["grade"] == "A+"
    cfg = headers.load_config()
    cfg["severity"] = {"csp-no-object-src": "error"}
    cfg["ignore_rules"] = ["csp-no-frame-ancestors"]
    conn2 = _mem()
    _crawl_one(conn2, URL, {"Content-Security-Policy": "default-src 'self'",
                            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                            "X-Frame-Options": "DENY",
                            "X-Content-Type-Options": "nosniff",
                            "Referrer-Policy": "strict-origin",
                            "Permissions-Policy": "geolocation=()"})
    tuned = headers.audit_rows(conn2, seo.site_key(URL), config=cfg)[0]
    assert _codes(tuned) == ["csp-no-object-src"]
    assert tuned["severity"] == "error"


# ---- capability detection + manifest ----------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.headers import cli as headers_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = headers_cli._capability()
    assert cap["adapter"] == "headers"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["binary"] == "shcheck"
    assert cap["extras"]["curl"]["found"] is False
    assert cap["extras"]["nuclei"]["found"] is False  # surfaced, never executed


def test_manifest_is_default_deny_on_the_seo_fleet():
    from bigbang.core import policy

    mf = policy.load_manifest(ROOT / "bigbang" / "plugins" / "headers")
    assert mf["name"] == "headers"
    assert policy.check_permission(mf, "network", "https://www.bhenre.com/")[0] is True
    assert policy.check_permission(mf, "network", "https://evil.example.com/")[0] is False
    # the classic bypass shapes stay denied (host match, never substring)
    assert policy.check_permission(
        mf, "network", "https://evil.com/bhenre.com"
    )[0] is False
    assert policy.check_permission(mf, "fs_write", ".scout/seo.db")[0] is True
    assert policy.check_permission(mf, "secret", "GITHUB_TOKEN")[0] is False


def test_the_scan_fetcher_refuses_to_leave_the_start_host(monkeypatch):
    from bigbang.plugins.headers import cli as headers_cli

    seen: list[str] = []
    monkeypatch.setattr(
        headers_cli, "_fetch", lambda u, **_k: seen.append(u) or _obs(final_url=u)
    )
    fetch = headers_cli._polite_fetcher(
        named=False, host="example.com", timeout=1.0, delay=0.0
    )
    assert fetch("https://example.com/assets/")["status"] == 200
    with pytest.raises(RuntimeError, match=r"tried to leave example\.com"):
        fetch("https://evil.example.com/")
    assert seen == ["https://example.com/assets/"]  # the off-host URL never fetched


def test_scan_report_shape_summarizes_grades(monkeypatch):
    from bigbang.plugins.headers import cli as headers_cli

    results = [
        headers.analyze(URL, _obs()),
        headers.analyze("https://example.com/b",
                        _obs(final_url="https://example.com/b", headers_=NASTY)),
    ]
    payload = headers_cli._report(results, extra={"db": None})
    assert payload["urls"] == 2
    assert payload["by_grade"] == {"A+": 1, "F": 1}
    assert [p["url"] for p in payload["problems"]] == ["https://example.com/b"]
    assert payload["summary"]["total"] == len(payload["diagnostics"]) > 0
    assert payload["db"] is None


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


def test_cli_headers_hello_envelope():
    r = _cli(["headers", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert data["data"]["rules"] == len(headers.RULES)
    assert "example" in data


def test_cli_headers_sites_publishes_the_rule_table():
    r = _cli(["headers", "sites"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["sites"]["bhenre"] == "https://www.bhenre.com"
    assert data["rules"]["csp-unsafe-inline"]["severity"] == "error"
    assert data["rules"]["csp-unsafe-inline"]["remedy"]
    assert len(data["rules"]) == len(headers.RULES)


def test_cli_headers_status_without_a_store_fails_actionably(tmp_path):
    r = _cli(["headers", "status", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no crawl store" in data["error"]
    assert "example" in data


def test_cli_headers_audit_unknown_site_is_refused(tmp_path):
    r = _cli(["headers", "audit", "nosuchsite", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "unknown site" in data["error"]
    assert "bhenre" in data["error"]  # the answer is in the failure


def test_cli_headers_audit_empty_store_says_crawl_first(tmp_path):
    db = tmp_path / "seo.db"
    headers.open_headers_store(db).close()
    r = _cli(["headers", "audit", "bhenre", "--db", str(db)])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no crawled pages" in data["error"]
    assert "seo crawl" in data["example"]


def test_cli_headers_audit_reports_the_store_caveats_and_gates(tmp_path):
    db = tmp_path / "seo.db"
    conn = headers.open_headers_store(db)
    _crawl_one(conn, seo.DEFAULT_SITES["bhenre"], {"Server": "nginx/1.25.3"})
    conn.close()
    r = _cli(["headers", "audit", "bhenre", "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["network_calls"] == 0
    assert data["urls"] == 1 and data["by_grade"] == {"D": 1}
    assert any("undercount" in c for c in data["caveats"])
    assert any("SKIPPED" in c for c in data["caveats"])
    assert data["results"][0]["checks_skipped"] == ["mixed-content", "directory-listing"]
    gated = _cli(["headers", "audit", "bhenre", "--db", str(db), "--fail-on", "warning"])
    assert gated.returncode == 1  # findings at/above warning exist -> nonzero exit
    clean_gate = _cli(["headers", "audit", "bhenre", "--db", str(db), "--fail-on", "nope"])
    assert clean_gate.returncode == 1
    assert "--fail-on must be one of" in json.loads(clean_gate.stdout)["error"]


def test_cli_headers_status_board_reads_a_recorded_scan(tmp_path):
    db = tmp_path / "seo.db"
    conn = headers.open_headers_store(db)
    headers.record_scan(conn, headers.analyze(URL, _obs()), ts=100.0)
    conn.close()
    r = _cli(["headers", "status", "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["scanned"] == 1
    assert data["board"][0]["url"] == URL and data["board"][0]["grade"] == "A+"
    hist = _cli(["headers", "status", "--db", str(db), "--url", URL])
    assert hist.returncode == 0
    assert json.loads(hist.stdout)["data"]["history"][0]["ts"] == 100.0
    missing = _cli(["headers", "status", "--db", str(db), "--url", "https://nope/"])
    assert missing.returncode == 1
    assert "no scans recorded" in json.loads(missing.stdout)["error"]


def test_cli_headers_scan_adhoc_url_is_policy_gated_offline(tmp_path):
    # BIGBANG_POLICY_FILE -> a fresh tmp file: the default user allowlist is
    # loopback-only, so an off-fleet URL is DENIED before any socket opens.
    r = _cli(
        ["headers", "scan", "--url", "https://not-allowed.example.com/"],
        env={"BIGBANG_POLICY_FILE": str(tmp_path / "policy.yaml")},
    )
    assert r.returncode == 1
    assert "denied" in (r.stdout + r.stderr).lower()


def test_cli_headers_scan_requires_exactly_one_target(tmp_path):
    both = _cli(["headers", "scan", "bhenre", "--url", "https://example.com/"])
    assert both.returncode == 1
    assert "site name OR --url" in json.loads(both.stdout)["error"]
    neither = _cli(["headers", "scan"])
    assert neither.returncode == 1
    assert "site name OR --url" in json.loads(neither.stdout)["error"]
