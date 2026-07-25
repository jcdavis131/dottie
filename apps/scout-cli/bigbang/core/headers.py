# Solo personal project, no connection to employer, built with public/free-tier only
"""Headers — secure-header + exposed-surface audit core (openswap #22: Detectify
/ Burp Suite Pro's surface pane).

The paid enemies scan your site from someone else's box and mail you a PDF.
This adapter inverts that: one plain response (the `headers` plugin CLI owns the
single real I/O — a urllib GET) is judged HERE, deterministically, so the whole
pipeline is unit-testable fully offline. Nothing in this module opens a socket,
writes outside the store it is handed, or shells out.

What the core judges from one observation (status + response headers + body):
- Content-Security-Policy: presence, enforced vs Report-Only, script-src via the
  browser's own default-src fallback, 'unsafe-inline'/'unsafe-eval', wildcard and
  scheme-wide script sources, duplicate conflicting policies, frame-ancestors and
  object-src hygiene.
- Strict-Transport-Security: max-age parse, max-age=0 (an explicit FORGET),
  short windows, includeSubDomains, preload.
- X-Frame-Options (including the dead ALLOW-FROM form, and CSP frame-ancestors
  as the modern substitute), X-Content-Type-Options, Referrer-Policy,
  Permissions-Policy, Access-Control-Allow-Origin (wildcard, and the invalid
  wildcard+credentials combination), Server/X-Powered-By version disclosure.
- Set-Cookie flags per cookie: Secure, HttpOnly, SameSite (including SameSite=
  None without Secure) and the __Secure-/__Host- name-prefix contracts.
- Exposed surface from the body: directory-listing signatures (Apache/nginx
  "Index of /", Tomcat, IIS) and mixed content — http:// subresources on an
  https page, split active (script/style/frame/form) vs passive (img/media).

The severity contract is DATA, not prose: RULES maps every code this module can
emit to (severity, remedy), config["severity"] overrides any of them, and
config["ignore_rules"] drops codes a site has decided not to care about. So a
policy change is a JSON edit, never a code edit. `grade()` collapses the reason
list to securityheaders.com-style A+..F and deliberately ignores info-level
disclosure notes.

Honesty rules that are load-bearing here:
- An UNREACHABLE url gets grade None, never a fabricated "F" — there were no
  headers to grade.
- Mixed content and directory listing need a BODY. When one is not available
  (the offline store path), the verdict says so in `checks_skipped` and those
  checks emit nothing; silence is never reported as a pass.
- audit_rows() reads pages.headers from the #3 seo crawl store, which persists
  headers as a JSON OBJECT — repeated Set-Cookie headers collapse to the last
  one there, so cookie findings from the store can UNDERCOUNT. `run_pass` (live)
  is fed a list of header pairs and sees every one. Both paths say which they got
  via `body_available` / `checks_skipped` and the caveat the CLI surfaces.

Substrate reuse (no parallel store): open_headers_store() wraps seo.open_store()
and adds ONE idempotent `header_scans` table — same .scout/seo.db, same pages
rows the crawler already wrote, which is exactly the extension point the seo core
documents ("audit CSP/HSTS from the store, zero refetches"). It never alters
seo's tables.

Extension points:
- Thresholds/severities/ignores as config: load_config(path) overlays JSON.
- More surface probes: probe_urls() builds the directory-listing probe set from
  config["dir_probe_paths"]; add paths without touching code.
- Trend reporting: header_scans + scan_history()/board() are the read contract.
- Native tier: none is a superset (Detectify is SaaS, Burp Pro is a paid GUI);
  the plugin's detect() reports tier=fallback as the steady state.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

from bigbang.core import openswap, seo

if TYPE_CHECKING:
    from collections.abc import Callable

USER_AGENT = "scout-headers"

SEV_OK = "ok"
SEV_ERROR = "error"
SEV_WARNING = "warning"
SEV_SUGGESTION = "suggestion"
SEV_INFO = "info"

# 180 days: the HSTS preload floor. Anything shorter is a token gesture, since a
# visitor's protection expires before they are likely to return.
HSTS_MIN_AGE = 15_552_000

DEFAULT_CONFIG: dict[str, Any] = {
    "hsts_min_age": HSTS_MIN_AGE,
    "require_hsts_preload": False,
    "require_permissions_policy": True,
    # opt-in extra GETs for `scan --dirs`; paths only, joined onto the origin
    "dir_probe_paths": ["/assets/", "/static/", "/images/", "/css/", "/js/", "/uploads/"],
    "ignore_rules": [],
    "severity": {},
}

# The severity contract, as data. code -> (default severity, remedy).
RULES: dict[str, tuple[str, str]] = {
    # transport
    "unreachable": (
        SEV_ERROR,
        "the URL did not answer — fix reachability before reading anything into a grade",
    ),
    "no-https": (SEV_ERROR, "serve over TLS and redirect http:// to https://"),
    "http-upgraded": (SEV_INFO, "no action — the plain-http request redirected to https"),
    "graded-non-2xx": (
        SEV_INFO,
        "the graded response was not 2xx; error pages often omit the app's headers",
    ),
    # content security policy
    "csp-missing": (
        SEV_WARNING,
        "add Content-Security-Policy: default-src 'self' and tighten from there",
    ),
    "csp-report-only": (
        SEV_WARNING,
        "promote the tested policy from Content-Security-Policy-Report-Only to "
        "Content-Security-Policy — Report-Only enforces nothing",
    ),
    "csp-no-script-src": (
        SEV_WARNING,
        "add script-src (or default-src) so script loading is actually restricted",
    ),
    "csp-unsafe-inline": (
        SEV_ERROR,
        "drop 'unsafe-inline' from script-src — use a nonce or hash for inline scripts",
    ),
    "csp-unsafe-eval": (SEV_WARNING, "drop 'unsafe-eval' from script-src"),
    "csp-wildcard-script": (
        SEV_WARNING,
        "replace the wildcard/scheme-wide script source with explicit origins",
    ),
    "csp-duplicate": (
        SEV_WARNING,
        "send exactly one Content-Security-Policy header — browsers enforce the "
        "intersection of conflicting policies, which is rarely what was meant",
    ),
    "csp-no-frame-ancestors": (
        SEV_SUGGESTION,
        "add frame-ancestors 'none' (or your embedders) — the modern X-Frame-Options",
    ),
    "csp-no-object-src": (
        SEV_SUGGESTION,
        "add object-src 'none' to kill legacy plugin embedding",
    ),
    # strict transport security
    "hsts-missing": (
        SEV_WARNING,
        "add Strict-Transport-Security: max-age=15552000; includeSubDomains",
    ),
    "hsts-no-max-age": (
        SEV_WARNING,
        "add a max-age directive — browsers ignore an HSTS header without one",
    ),
    "hsts-disabled": (
        SEV_ERROR,
        "max-age=0 tells browsers to FORGET HSTS for this host — set a real max-age",
    ),
    "hsts-short": (SEV_WARNING, "raise max-age to at least the configured floor"),
    "hsts-no-subdomains": (
        SEV_SUGGESTION,
        "add includeSubDomains once every subdomain is https",
    ),
    "hsts-no-preload": (SEV_SUGGESTION, "add preload and submit the domain"),
    # framing / sniffing / referrer / permissions
    "xfo-missing": (SEV_WARNING, "add X-Frame-Options: DENY or CSP frame-ancestors"),
    "xfo-allow-from": (
        SEV_WARNING,
        "ALLOW-FROM is ignored by every modern browser — use CSP frame-ancestors",
    ),
    "xfo-invalid": (SEV_WARNING, "X-Frame-Options accepts only DENY or SAMEORIGIN"),
    "xcto-missing": (SEV_WARNING, "add X-Content-Type-Options: nosniff"),
    "xcto-invalid": (SEV_WARNING, "the only valid X-Content-Type-Options value is nosniff"),
    "referrer-missing": (
        SEV_WARNING,
        "add Referrer-Policy: strict-origin-when-cross-origin",
    ),
    "referrer-weak": (
        SEV_WARNING,
        "unsafe-url / no-referrer-when-downgrade leak full URLs — prefer "
        "strict-origin-when-cross-origin",
    ),
    "permissions-policy-missing": (
        SEV_SUGGESTION,
        "add Permissions-Policy denying the APIs this page never uses",
    ),
    # cross-origin exposure / fingerprint
    "cors-wildcard": (
        SEV_SUGGESTION,
        "Access-Control-Allow-Origin: * exposes the response to every origin — "
        "name the origins you mean",
    ),
    "cors-wildcard-credentials": (
        SEV_ERROR,
        "ACAO: * with Access-Control-Allow-Credentials: true is invalid and unsafe",
    ),
    "server-banner": (
        SEV_INFO,
        "strip version numbers from Server / X-Powered-By to shrink the fingerprint",
    ),
    # cookies
    "cookie-insecure": (
        SEV_ERROR,
        "add the Secure attribute — without it the cookie can ride a plaintext request",
    ),
    "cookie-no-httponly": (SEV_WARNING, "add HttpOnly so script cannot read the cookie"),
    "cookie-no-samesite": (SEV_WARNING, "add SameSite=Lax (or Strict) to blunt CSRF"),
    "cookie-samesite-none-insecure": (SEV_ERROR, "SameSite=None requires Secure"),
    "cookie-prefix-violation": (
        SEV_ERROR,
        "honor the name-prefix contract: __Secure- needs Secure; __Host- needs "
        "Secure, Path=/ and no Domain",
    ),
    # exposed surface
    "directory-listing": (
        SEV_ERROR,
        "disable autoindex / directory browsing for this path",
    ),
    "mixed-content-active": (
        SEV_ERROR,
        "load scripts/styles/frames over https — browsers block or upgrade them anyway",
    ),
    "mixed-content-passive": (
        SEV_WARNING,
        "serve images/media over https to avoid the degraded-lock warning",
    ),
}

WEAK_REFERRER = ("unsafe-url", "no-referrer-when-downgrade")
VALID_XFO = ("DENY", "SAMEORIGIN")
# script sources that are wildcards in practice, not real origins
WILDCARD_SOURCES = ("*", "http:", "https:", "data:")


# ---- config -----------------------------------------------------------------


def load_config(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG overlaid with an optional JSON file (policy-as-config).

    Merge semantics mirror seo.load_config: dicts merge key-by-key, scalars and
    lists replace. Unknown keys and bad shapes raise ValueError for the CLI to
    turn into a fail_agent envelope — a typo'd rule name must never silently
    disable a check.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config file must be a JSON object")
        for key, val in raw.items():
            if key not in cfg:
                raise ValueError(f"unknown config key {key!r} (known: {sorted(cfg)})")
            if isinstance(cfg[key], dict):
                if not isinstance(val, dict):
                    raise ValueError(f"config {key!r}: must be an object")
                cfg[key].update(val)
            else:
                cfg[key] = val
    age = cfg["hsts_min_age"]
    if not (isinstance(age, int) and not isinstance(age, bool) and age >= 0):
        raise ValueError(f"config 'hsts_min_age': needs a non-negative int, got {age!r}")
    for key in ("ignore_rules", "dir_probe_paths"):
        if not (isinstance(cfg[key], list) and all(isinstance(x, str) for x in cfg[key])):
            raise ValueError(f"config {key!r}: must be a list of strings")
    for code in cfg["ignore_rules"]:
        if code not in RULES:
            raise ValueError(f"config 'ignore_rules': unknown rule {code!r}")
    for code, sev in cfg["severity"].items():
        if code not in RULES:
            raise ValueError(f"config 'severity': unknown rule {code!r}")
        if sev not in openswap.SEVERITIES:
            raise ValueError(f"config 'severity' for {code!r}: bad severity {sev!r}")
    return cfg


# ---- header normalization ---------------------------------------------------


def normalize_headers(headers: Any) -> dict[str, list[str]]:
    """Response headers -> {lowercase name: [value, ...]}, repeats preserved.

    Accepts every shape this family produces or stores: a list of (name, value)
    pairs (what the CLI captures from urllib, so REPEATED Set-Cookie headers
    survive), a plain dict (what the seo crawl store persists — repeats already
    collapsed there), or a dict of lists. Anything else yields {} rather than
    raising: response headers are attacker-adjacent data.
    """
    out: dict[str, list[str]] = {}
    if isinstance(headers, dict):
        items: list[tuple[Any, Any]] = list(headers.items())
    elif isinstance(headers, (list, tuple)):
        items = [
            (p[0], p[1])
            for p in headers
            if isinstance(p, (list, tuple)) and len(p) == 2
        ]
    else:
        return out
    for name, value in items:
        key = str(name).strip().lower()
        if not key:
            continue
        vals = value if isinstance(value, (list, tuple)) else [value]
        for v in vals:
            out.setdefault(key, []).append(str(v).strip())
    return out


def header_value(hmap: dict[str, list[str]], name: str) -> str | None:
    """The first value of a header, or None. First wins like a browser."""
    vals = hmap.get(name.lower()) or []
    return vals[0] if vals else None


# ---- Content-Security-Policy ------------------------------------------------


def parse_csp(value: str) -> dict[str, list[str]]:
    """"default-src 'self'; script-src a b" -> {"default-src": ["'self'"], ...}.

    A repeated directive inside ONE policy is ignored after the first, which is
    what the CSP spec says browsers must do.
    """
    out: dict[str, list[str]] = {}
    for chunk in (value or "").split(";"):
        parts = chunk.split()
        if not parts:
            continue
        name = parts[0].lower()
        if name in out:
            continue
        out[name] = parts[1:]
    return out


def effective_sources(csp: dict[str, list[str]], directive: str) -> list[str] | None:
    """A fetch directive's sources, falling back to default-src as browsers do.

    None means "nothing constrains this directive" — the caller decides whether
    that is a finding. Only fetch directives fall back; frame-ancestors never
    does, so callers read it out of `csp` directly.
    """
    if directive in csp:
        return csp[directive]
    if "default-src" in csp:
        return csp["default-src"]
    return None


def _csp_reasons(hmap: dict[str, list[str]]) -> list[dict[str, Any]]:
    enforced = header_value(hmap, "content-security-policy")
    if not enforced:
        code = (
            "csp-report-only"
            if header_value(hmap, "content-security-policy-report-only")
            else "csp-missing"
        )
        return [_r(code, "no enforced Content-Security-Policy")]
    reasons: list[dict[str, Any]] = []
    policies = hmap.get("content-security-policy") or []
    if len(set(policies)) > 1:
        reasons.append(
            _r("csp-duplicate", f"{len(policies)} differing CSP headers on one response")
        )
    csp = parse_csp(enforced)
    script = effective_sources(csp, "script-src")
    if script is None:
        reasons.append(_r("csp-no-script-src", "CSP sets neither script-src nor default-src"))
    else:
        low = [s.lower() for s in script]
        if "'unsafe-inline'" in low:
            reasons.append(_r("csp-unsafe-inline", "script-src allows 'unsafe-inline'"))
        if "'unsafe-eval'" in low:
            reasons.append(_r("csp-unsafe-eval", "script-src allows 'unsafe-eval'"))
        wide = [s for s in low if s in WILDCARD_SOURCES]
        if wide:
            reasons.append(
                _r("csp-wildcard-script", f"script-src allows {', '.join(wide)}")
            )
    if "frame-ancestors" not in csp:
        reasons.append(_r("csp-no-frame-ancestors", "CSP has no frame-ancestors directive"))
    obj = effective_sources(csp, "object-src")
    if obj is None or [s.lower() for s in obj] != ["'none'"]:
        reasons.append(_r("csp-no-object-src", "object-src is not 'none'"))
    return reasons


# ---- Strict-Transport-Security ----------------------------------------------

_MAX_AGE_RE = re.compile(r"max-age\s*=\s*\"?(\d+)\"?", re.IGNORECASE)


def parse_hsts(value: str) -> dict[str, Any]:
    """Strict-Transport-Security value -> {max_age, include_subdomains, preload}.

    max_age is None when the directive is absent or unparseable — which is the
    same thing to a browser (it ignores the header) but must stay
    distinguishable from max-age=0 (an explicit instruction to forget HSTS).
    """
    text = value or ""
    match = _MAX_AGE_RE.search(text)
    tokens = [t.strip().lower() for t in text.split(";")]
    return {
        "max_age": int(match.group(1)) if match else None,
        "include_subdomains": "includesubdomains" in tokens,
        "preload": "preload" in tokens,
    }


def _hsts_reasons(hmap: dict[str, list[str]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = header_value(hmap, "strict-transport-security")
    if not raw:
        # deliberately the same severity certmon gives its missing-hsts reason:
        # one family, one opinion about the same header
        return [_r("hsts-missing", "no Strict-Transport-Security header")]
    hsts = parse_hsts(raw)
    reasons: list[dict[str, Any]] = []
    age = hsts["max_age"]
    floor = cfg["hsts_min_age"]
    if age is None:
        reasons.append(_r("hsts-no-max-age", f"HSTS header has no max-age: {raw!r}"))
    elif age == 0:
        reasons.append(_r("hsts-disabled", "max-age=0 disables HSTS for this host"))
    elif age < floor:
        reasons.append(_r("hsts-short", f"max-age={age} is under the {floor} floor"))
    if not hsts["include_subdomains"]:
        reasons.append(_r("hsts-no-subdomains", "HSTS omits includeSubDomains"))
    if cfg["require_hsts_preload"] and not hsts["preload"]:
        reasons.append(_r("hsts-no-preload", "HSTS omits preload"))
    return reasons


# ---- the remaining single-header checks -------------------------------------


def _framing_reasons(
    hmap: dict[str, list[str]], csp: dict[str, list[str]]
) -> list[dict[str, Any]]:
    xfo = header_value(hmap, "x-frame-options")
    reasons: list[dict[str, Any]] = []
    if xfo is None:
        if "frame-ancestors" not in csp:
            reasons.append(_r("xfo-missing", "no X-Frame-Options and no CSP frame-ancestors"))
        return reasons
    value = xfo.strip().upper()
    if value.startswith("ALLOW-FROM"):
        reasons.append(_r("xfo-allow-from", f"X-Frame-Options: {xfo} is a dead form"))
    elif value not in VALID_XFO:
        reasons.append(_r("xfo-invalid", f"X-Frame-Options: {xfo!r} is not DENY/SAMEORIGIN"))
    return reasons


def _misc_header_reasons(
    hmap: dict[str, list[str]], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    xcto = header_value(hmap, "x-content-type-options")
    if xcto is None:
        reasons.append(_r("xcto-missing", "no X-Content-Type-Options header"))
    elif xcto.strip().lower() != "nosniff":
        reasons.append(_r("xcto-invalid", f"X-Content-Type-Options: {xcto!r}"))
    ref = header_value(hmap, "referrer-policy")
    if ref is None:
        reasons.append(_r("referrer-missing", "no Referrer-Policy header"))
    else:
        # a policy list is evaluated left to right; any weak token can apply
        tokens = [t.strip().lower() for t in ref.split(",")]
        weak = [t for t in tokens if t in WEAK_REFERRER]
        if weak:
            reasons.append(_r("referrer-weak", f"Referrer-Policy: {', '.join(weak)}"))
    if cfg["require_permissions_policy"] and not (
        header_value(hmap, "permissions-policy") or header_value(hmap, "feature-policy")
    ):
        reasons.append(_r("permissions-policy-missing", "no Permissions-Policy header"))
    acao = header_value(hmap, "access-control-allow-origin")
    if acao and acao.strip() == "*":
        creds = (header_value(hmap, "access-control-allow-credentials") or "").lower()
        code = "cors-wildcard-credentials" if creds == "true" else "cors-wildcard"
        reasons.append(_r(code, "Access-Control-Allow-Origin: *"))
    for name in ("server", "x-powered-by"):
        value = header_value(hmap, name)
        if value and re.search(r"\d", value):
            reasons.append(_r("server-banner", f"{name}: {value}"))
    return reasons


# ---- cookies ----------------------------------------------------------------


def parse_cookie(value: str) -> dict[str, Any]:
    """One Set-Cookie value -> {name, secure, httponly, samesite, path, domain}.

    Attribute names are case-insensitive per RFC 6265; the cookie NAME is not,
    which matters for the __Secure-/__Host- prefix contracts.
    """
    parts = [p.strip() for p in (value or "").split(";")]
    name = parts[0].split("=", 1)[0].strip() if parts and "=" in parts[0] else ""
    attrs: dict[str, Any] = {}
    for part in parts[1:]:
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            attrs[key.strip().lower()] = val.strip()
        else:
            attrs[part.lower()] = True
    return {
        "name": name,
        "secure": "secure" in attrs,
        "httponly": "httponly" in attrs,
        "samesite": attrs.get("samesite") or None,
        "path": attrs.get("path"),
        "domain": attrs.get("domain"),
    }


def _prefix_violation(cookie: dict[str, Any]) -> str | None:
    """__Secure-/__Host- prefix contract (RFC 6265bis) — None when honored."""
    name = cookie["name"]
    if name.startswith("__Host-"):
        if not (cookie["secure"] and cookie["path"] == "/" and not cookie["domain"]):
            return "__Host- requires Secure, Path=/ and no Domain"
    elif name.startswith("__Secure-") and not cookie["secure"]:
        return "__Secure- requires Secure"
    return None


def _cookie_reasons(
    hmap: dict[str, list[str]], *, https: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(reasons, parsed cookies) — one reason set per cookie, named in the message."""
    reasons: list[dict[str, Any]] = []
    cookies: list[dict[str, Any]] = []
    for raw in hmap.get("set-cookie") or []:
        cookie = parse_cookie(raw)
        cookies.append(cookie)
        label = cookie["name"] or "(unnamed)"
        samesite = (cookie["samesite"] or "").lower()
        if https and not cookie["secure"]:
            reasons.append(_r("cookie-insecure", f"cookie {label} has no Secure"))
        if not cookie["httponly"]:
            reasons.append(_r("cookie-no-httponly", f"cookie {label} has no HttpOnly"))
        if not samesite:
            reasons.append(_r("cookie-no-samesite", f"cookie {label} has no SameSite"))
        elif samesite == "none" and not cookie["secure"]:
            reasons.append(
                _r("cookie-samesite-none-insecure", f"cookie {label} is SameSite=None")
            )
        why = _prefix_violation(cookie)
        if why:
            reasons.append(_r("cookie-prefix-violation", f"cookie {label}: {why}"))
    return reasons, cookies


# ---- exposed surface: directory listing + mixed content ---------------------

# Server-generated index pages announce themselves. Each pattern is a signature
# of the server that produced it, so the finding names what to turn off.
DIR_LISTING_SIGNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("index-of", re.compile(r"<(?:title|h1)>\s*index of\s*/", re.IGNORECASE)),
    ("tomcat", re.compile(r"directory listing for\s*/", re.IGNORECASE)),
    ("iis", re.compile(r"\[to parent directory\]", re.IGNORECASE)),
)


def directory_listing(body: str | None) -> str | None:
    """The directory-listing flavor this body is, or None. None on no body."""
    if not body:
        return None
    for flavor, pattern in DIR_LISTING_SIGNS:
        if pattern.search(body):
            return flavor
    return None


# tag -> (url attribute, active). Active subresources execute or style the page,
# so http:// versions are blocked/upgraded by browsers and are a real error;
# passive ones only degrade the lock icon.
SUBRESOURCE_TAGS: dict[str, tuple[str, bool]] = {
    "script": ("src", True),
    "iframe": ("src", True),
    "embed": ("src", True),
    "object": ("data", True),
    "form": ("action", True),
    "img": ("src", False),
    "audio": ("src", False),
    "video": ("src", False),
    "source": ("src", False),
    "track": ("src", False),
}
# <link> is split by rel: stylesheets/preloads are active, icons are passive
ACTIVE_LINK_RELS = frozenset({"stylesheet", "preload", "modulepreload", "import"})


class _SubresourceParser(HTMLParser):
    """Tolerant single-pass collector of every subresource URL a page pulls in."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "link":
            rels = (a.get("rel") or "").lower().split()
            spec: tuple[str, bool] | None = ("href", bool(ACTIVE_LINK_RELS & set(rels)))
        else:
            spec = SUBRESOURCE_TAGS.get(tag)
        if spec is None:
            return
        attr, active = spec
        raw = (a.get(attr) or "").strip()
        if not raw:
            return
        line, _off = self.getpos()
        self.found.append({"tag": tag, "attr": attr, "raw": raw, "active": active, "line": line})

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)


def subresources(body: str | None, base_url: str) -> list[dict[str, Any]]:
    """Every subresource the page loads, URLs resolved against `base_url`.

    Protocol-relative "//cdn/x.js" resolves against the page scheme (so it is
    NOT mixed content on an https page), and non-fetch schemes (data:, mailto:,
    javascript:, fragments) are dropped — they load nothing over the network.
    """
    if not body:
        return []
    parser = _SubresourceParser()
    try:
        parser.feed(body)
        parser.close()
    except Exception:
        pass  # tolerant by contract: malformed soup must not kill an audit
    out: list[dict[str, Any]] = []
    for item in parser.found:
        raw = item["raw"]
        if raw.startswith("#") or urlsplit(raw).scheme in ("data", "mailto", "javascript"):
            continue
        url = urljoin(base_url, raw)
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        out.append({**item, "url": url})
    return out


def mixed_content(page_url: str, body: str | None) -> list[dict[str, Any]]:
    """http:// subresources on an https page. Empty for http pages (all plaintext)."""
    if urlsplit(page_url).scheme != "https":
        return []
    return [s for s in subresources(body, page_url) if urlsplit(s["url"]).scheme == "http"]


def _surface_reasons(url: str, body: str | None) -> tuple[list[dict[str, Any]], Any, list]:
    """(reasons, directory-listing flavor, mixed-content items) for one body."""
    reasons: list[dict[str, Any]] = []
    flavor = directory_listing(body)
    if flavor:
        reasons.append(_r("directory-listing", f"server-generated index page ({flavor})"))
    mixed = mixed_content(url, body)
    for active, code in ((True, "mixed-content-active"), (False, "mixed-content-passive")):
        hits = [m for m in mixed if m["active"] is active]
        if not hits:
            continue
        shown = ", ".join(f"<{h['tag']}> {h['url']}" for h in hits[:3])
        more = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
        reasons.append(_r(code, f"{len(hits)} http:// subresource(s): {shown}{more}", line=hits[0]["line"]))
    return reasons, flavor, mixed


# ---- the verdict ------------------------------------------------------------


def _r(code: str, message: str, line: int = 0) -> dict[str, Any]:
    """A raw finding. Severity/remedy are attached later, from RULES + config."""
    return {"code": code, "message": message, "line": int(line)}


def _finalize(reasons: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach severity + remedy from RULES (config may override), drop ignored.

    One place decides severity for every check, so `severity` overrides and
    `ignore_rules` cannot be honored by some checks and forgotten by others.
    """
    ignore = set(cfg.get("ignore_rules") or ())
    overrides = cfg.get("severity") or {}
    out: list[dict[str, Any]] = []
    for reason in reasons:
        code = reason["code"]
        if code in ignore:
            continue
        severity, remedy = RULES[code]
        out.append({**reason, "severity": overrides.get(code, severity), "remedy": remedy})
    return out


def worst_severity(reasons: list[dict[str, Any]]) -> str:
    """error > warning > suggestion > info > ok (family severity ranking)."""
    worst = SEV_OK
    for reason in reasons:
        if openswap.severity_rank(reason["severity"]) < openswap.severity_rank(worst):
            worst = reason["severity"]
    return worst


def grade(reasons: list[dict[str, Any]]) -> str:
    """securityheaders.com-style A+..F from the finalized reasons.

    Error-dominated by design: three errors is an F, one caps the page at D. With
    no errors the warning count decides, and a pile of missing headers can still
    reach D on its own (five is a page with no security headers at all) so a
    warning-only site is never flattered by the letter. Suggestions cost only the
    plus, and INFO findings never move the grade — a version banner is worth
    reporting but is not a header failure. The letter is a headline: the reason
    list, not the grade, is the actionable output, and `--fail-on` reads
    severities, never grades. Deterministic and total, so grades are comparable
    across scans and across sites.
    """
    errors = sum(1 for r in reasons if r["severity"] == SEV_ERROR)
    warnings = sum(1 for r in reasons if r["severity"] == SEV_WARNING)
    suggestions = sum(1 for r in reasons if r["severity"] == SEV_SUGGESTION)
    if errors >= 3:
        return "F"
    if errors == 2:
        return "E"
    if errors == 1 or warnings >= 5:
        return "D"
    if warnings >= 3:
        return "C"
    if warnings:
        return "B"
    return "A" if suggestions else "A+"


def analyze(
    url: str, observation: dict[str, Any], *, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One response -> the normalized headers verdict (see the module doc).

    `observation` is what the injected fetcher returns:
    {"status": int|None, "final_url": str|None, "headers": <pairs|dict>,
     "body": str|None, "error": str|None}. body=None means "no body available"
     (the offline store path) and is NOT the same as "" — the body-dependent
     checks are then skipped and named in `checks_skipped` instead of quietly
     passing. An unreachable URL yields the unreachable error and grade None.
    """
    cfg = config or DEFAULT_CONFIG
    status = observation.get("status")
    final_url = observation.get("final_url") or url
    body = observation.get("body")
    hmap = normalize_headers(observation.get("headers"))
    https = urlsplit(final_url).scheme == "https"
    verdict: dict[str, Any] = {
        "url": url,
        "final_url": final_url,
        "status": status,
        "https": https,
        "reachable": status is not None,
        "error": observation.get("error"),
        "headers_seen": sorted(hmap),
        "body_available": body is not None,
        "checks_skipped": [] if body is not None else ["mixed-content", "directory-listing"],
        "cookies": [],
        "mixed_content": [],
        "directory_listing": None,
        "grade": None,
    }
    if status is None:
        verdict["reasons"] = _finalize(
            [_r("unreachable", observation.get("error") or "no response")], cfg
        )
        verdict["severity"] = worst_severity(verdict["reasons"])
        return verdict  # grade stays None: there were no headers to grade

    raw: list[dict[str, Any]] = []
    if not https:
        raw.append(_r("no-https", f"final URL is not https: {final_url}"))
    elif urlsplit(url).scheme == "http":
        raw.append(_r("http-upgraded", f"plain-http request redirected to {final_url}"))
    if isinstance(status, int) and status >= 400:
        raw.append(_r("graded-non-2xx", f"graded an HTTP {status} response"))
    raw.extend(_csp_reasons(hmap))
    if https:
        # HSTS is meaningless over plaintext; no-https already carries that story
        raw.extend(_hsts_reasons(hmap, cfg))
    csp = parse_csp(header_value(hmap, "content-security-policy") or "")
    raw.extend(_framing_reasons(hmap, csp))
    raw.extend(_misc_header_reasons(hmap, cfg))
    cookie_reasons, cookies = _cookie_reasons(hmap, https=https)
    raw.extend(cookie_reasons)
    surface, flavor, mixed = _surface_reasons(final_url, body)
    raw.extend(surface)
    verdict["cookies"] = cookies
    verdict["directory_listing"] = flavor
    verdict["mixed_content"] = mixed
    verdict["reasons"] = _finalize(raw, cfg)
    verdict["severity"] = worst_severity(verdict["reasons"])
    verdict["grade"] = grade(verdict["reasons"])
    return verdict


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map every finding onto the family diagnostic schema — one per REASON.

    Deliberately finer-grained than certmon's one-per-host: a page can miss six
    headers and each is separately actionable, so summarize().by_rule becomes a
    real report ("14 pages missing X-Content-Type-Options") and `--fail-on`
    still behaves identically because it only reads severities.
    """
    diags = []
    for result in results:
        for reason in result.get("reasons", []):
            diags.append(
                openswap.diagnostic(
                    path=result.get("final_url") or result["url"],
                    line=reason.get("line", 0),
                    col=0,
                    rule=f"headers:{reason['code']}",
                    severity=reason["severity"],
                    message=f"{result['url']} — {reason['message']}",
                    suggestion=reason.get("remedy"),
                )
            )
    return openswap.sort_diagnostics(diags)


# ---- targets ----------------------------------------------------------------


def default_sites() -> dict[str, str]:
    """The named public fleet, derived from seo.DEFAULT_SITES (never duplicated).

    Same sites the crawler knows, so `headers scan bhenre` and `headers audit
    bhenre` can never disagree with `seo crawl bhenre` about what "bhenre" is.
    """
    return dict(seo.DEFAULT_SITES)


def probe_urls(start_url: str, paths: list[str] | None = None) -> list[str]:
    """The directory-listing probe set for one origin: start URL + config paths.

    Order-stable and de-duplicated so a probe pass is reproducible, and every
    URL is same-origin with the start URL by construction (urljoin of a rooted
    path), which keeps the CLI's allowlist check meaningful.
    """
    start = seo.site_key(start_url)
    out = [start]
    for path in paths or []:
        candidate = urljoin(start, path if path.startswith("/") else f"/{path}")
        if candidate not in out:
            out.append(candidate)
    return out


# ---- store (shared seo crawl substrate + one idempotent scans table) --------

_SCAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS header_scans(
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    ts REAL NOT NULL,
    final_url TEXT,
    status INTEGER,
    https INTEGER,
    grade TEXT,
    severity TEXT NOT NULL,
    codes TEXT,
    cookies INTEGER NOT NULL DEFAULT 0,
    mixed_active INTEGER NOT NULL DEFAULT 0,
    mixed_passive INTEGER NOT NULL DEFAULT 0,
    dir_listing TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_header_scans_url_ts ON header_scans(url, ts);
"""


def open_headers_store(path: str | Path) -> sqlite3.Connection:
    """The shared #3 crawl store plus one idempotent `header_scans` table.

    Wraps seo.open_store (same sqlite file, same frontier/pages/meta tables) and
    adds `header_scans` via CREATE TABLE IF NOT EXISTS. It NEVER alters seo's
    tables, so `seo crawl` and `headers scan` share one .scout/seo.db and the
    offline audit reads the very rows the crawler wrote.
    """
    conn = seo.open_store(path)
    conn.executescript(_SCAN_SCHEMA)
    conn.commit()
    return conn


def record_scan(
    conn: sqlite3.Connection, verdict: dict[str, Any], *, ts: float | None = None
) -> int:
    """Append one scan observation to `header_scans`; returns the row id."""
    ts = time.time() if ts is None else float(ts)
    codes = [r["code"] for r in verdict.get("reasons", [])]
    mixed = verdict.get("mixed_content") or []
    cur = conn.execute(
        "INSERT INTO header_scans(url, ts, final_url, status, https, grade, severity,"
        " codes, cookies, mixed_active, mixed_passive, dir_listing, error)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            verdict["url"],
            ts,
            verdict.get("final_url"),
            verdict.get("status"),
            int(bool(verdict.get("https"))),
            verdict.get("grade"),
            verdict.get("severity", SEV_OK),
            json.dumps(codes) if codes else None,
            len(verdict.get("cookies") or []),
            sum(1 for m in mixed if m["active"]),
            sum(1 for m in mixed if not m["active"]),
            verdict.get("directory_listing"),
            verdict.get("error"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def run_pass(
    conn: sqlite3.Connection,
    urls: list[str],
    fetch: Callable[[str], dict[str, Any]],
    *,
    now: float | None = None,
    record: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One scan pass: fetch every URL, analyze, record, report.

    `fetch(url)` must return the observation dict analyze() expects — the CLI
    injects the real urllib fetcher; tests inject fakes (the offline invariant).
    With record=False the store is left untouched (probe-and-report only).
    """
    now = time.time() if now is None else float(now)
    results = [analyze(u, fetch(u), config=config) for u in urls]
    if record:
        for verdict in results:
            record_scan(conn, verdict, ts=now)
    return {
        "ts": now,
        "results": results,
        "problems": [r for r in results if r.get("severity", SEV_OK) != SEV_OK],
    }


def audit_rows(
    conn: sqlite3.Connection, site: str, *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Audit the STORED crawl for one site — zero refetches, zero network.

    Reads pages.headers written by `seo crawl`, so this is the cheap fleet-wide
    sweep. Two honest limits, both visible in every verdict: there is no body in
    the store (mixed content and directory listing land in `checks_skipped`), and
    seo persists headers as a JSON object, so repeated Set-Cookie headers
    collapsed to the last one before this function ever saw them — cookie
    findings here can undercount. `scan` sees both.
    """
    out: list[dict[str, Any]] = []
    for row in seo.site_rows(conn, site):
        observation = {
            "status": row["status"],
            "final_url": row["final_url"] or row["url"],
            "headers": row["headers"],
            "body": None,
            "error": row["error"],
        }
        out.append(analyze(row["url"], observation, config=config))
    return out


# ---- reads: the trend / board contract --------------------------------------


def latest_scan(conn: sqlite3.Connection, url: str) -> dict[str, Any] | None:
    """The most recent scan of one URL, or None."""
    row = conn.execute(
        "SELECT * FROM header_scans WHERE url = ? ORDER BY ts DESC, id DESC LIMIT 1",
        (url,),
    ).fetchone()
    return dict(row) if row else None


def scanned_urls(conn: sqlite3.Connection, *, prefix: str | None = None) -> list[str]:
    """Every URL with at least one recorded scan, most-recently-scanned first.

    `prefix` narrows the board to one origin without a second table: the store is
    shared with the crawler, so "which URLs have I audited for this site" is a
    prefix question, not a foreign key.
    """
    rows = conn.execute(
        "SELECT url, MAX(ts) AS newest FROM header_scans GROUP BY url"
        " ORDER BY newest DESC, url"
    )
    urls = [r["url"] for r in rows]
    if prefix:
        urls = [u for u in urls if u.startswith(prefix)]
    return urls


def scan_history(
    conn: sqlite3.Connection, url: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Newest-first scan observations for one URL."""
    rows = conn.execute(
        "SELECT * FROM header_scans WHERE url = ? ORDER BY ts DESC, id DESC LIMIT ?",
        (url, limit),
    )
    return [dict(r) for r in rows]


def board(conn: sqlite3.Connection, urls: list[str]) -> list[dict[str, Any]]:
    """Latest grade per URL from the store (read-only, no network).

    A URL with no scan yet reads grade "unknown" rather than being dropped: a
    posture board that silently omits what it never measured is the failure mode
    this family exists to kill.
    """
    out = []
    for url in urls:
        last = latest_scan(conn, url)
        if last is None:
            out.append({"url": url, "grade": "unknown", "severity": "unknown", "last": None})
            continue
        out.append(
            {
                "url": url,
                "grade": last["grade"],
                "severity": last["severity"],
                "last_ts": last["ts"],
                "status": last["status"],
                "codes": json.loads(last["codes"]) if last["codes"] else [],
                "last": last,
            }
        )
    return out
