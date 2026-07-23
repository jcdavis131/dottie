# Solo personal project, no connection to employer, built with public/free-tier only
"""Smoke — post-deploy expected-string gate core (openswap #5: Checkly).

Post-deploy smoke doctrine as a reusable adapter: a JSON manifest maps each
deployed URL to an expected string; every check polls under a bounded
retry/backoff budget until the content matches or the budget exhausts, and the
run exits nonzero with a per-URL pass/fail report. This module owns everything
deterministic — manifest parsing, the backoff schedule, attempt classification,
the retry loop (fetch/sleep/clock all injected), and the family diagnostics
mapping. Real I/O stays out: the `smoke` plugin CLI supplies the urllib fetch
(bigbang/core/uptime.py + plugins/uptime/cli.py is the pattern), so the whole
pipeline is unit-testable fully offline.

Unlike uptime's liveness probe (redirects prove liveness, never followed),
smoke asserts on the content a visitor actually receives, so the CLI fetch
follows redirects and classification demands a final 2xx.

Extension points:
- Per-site manifests: a `smoke.json` lives in each site's repo (next to its
  .vercel/ dir); the deploy wrapper runs
  `scout smoke run --manifest <site>/smoke.json` right after `vercel deploy`,
  so the gate travels with the site instead of a central config.
- Latency-threshold assertions: `max_ms` on a check fails a response that
  matches but arrives slow ("serving, but not the experience we deployed" —
  uptime's degraded doctrine); the per-attempt trail keeps every latency for
  future percentile assertions across attempts.
- Deploy markers: the CLI's --mark writes deploy + smoke-outcome events into
  the shared uptime ledger (#2) via uptime.record_event, putting deploys and
  incidents on one timeline so outages correlate with the deploy that caused
  them.
- Family gate: to_diagnostics() maps failures onto the openswap diagnostic
  schema (slow=warning, everything else=error), so openswap.summarize() treats
  smoke results exactly like prose/seo/links findings.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_ATTEMPTS = 5
DEFAULT_INITIAL_DELAY_S = 2.0
DEFAULT_MULTIPLIER = 2.0
DEFAULT_MAX_DELAY_S = 30.0
DEFAULT_BUDGET_S = 120.0
MANIFEST_REL = "smoke.json"

RULE_UNREACHABLE = "unreachable"
RULE_HTTP = "http"
RULE_EXPECT_MISS = "expect-miss"
RULE_SLOW = "slow"


def load_checks(path: str | Path) -> dict[str, dict[str, Any]]:
    """Parse a smoke manifest: JSON object, two shapes per entry.

    Minimal (the brief's literal contract) — the key IS the deployed URL:
        {"https://www.bhenre.com": "bhenre"}
    Rich — named check with a latency assertion:
        {"home": {"url": "https://...", "expect": "...", "max_ms": 1500}}
    Raises ValueError / OSError / json errors for the CLI to convert into a
    fail_agent envelope (uptime.load_targets is the pattern).
    """
    # utf-8-sig: PS 5.1 deploy wrappers (Set-Content/Out-File -Encoding utf8)
    # write BOMs; utf-8-sig also decodes plain utf-8, so tolerate both
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError(
            "smoke manifest must be a non-empty JSON object of"
            ' {url: expected-string} or {name: {"url", "expect"}}'
        )
    checks: dict[str, dict[str, Any]] = {}
    for name, cfg in raw.items():
        if isinstance(cfg, str):
            cfg = {"url": name, "expect": cfg}
        if not isinstance(cfg, dict):
            raise ValueError(
                f"check {name!r}: config must be an object or an expected string"
            )
        url = cfg.get("url")
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
            raise ValueError(f"check {name!r}: needs an http(s) url, got {url!r}")
        expect = cfg.get("expect")
        if not (isinstance(expect, str) and expect):
            raise ValueError(f"check {name!r}: needs a non-empty expected string")
        max_ms = cfg.get("max_ms")
        # bool is an int subclass; `"max_ms": true` must not pass as a number
        if max_ms is not None and (
            isinstance(max_ms, bool)
            or not isinstance(max_ms, (int, float))
            or max_ms <= 0
        ):
            raise ValueError(f"check {name!r}: max_ms must be a positive number")
        check: dict[str, Any] = {"url": url, "expect": expect}
        if max_ms is not None:
            check["max_ms"] = float(max_ms)
        checks[name] = check
    return checks


def backoff_delays(
    attempts: int,
    *,
    initial: float = DEFAULT_INITIAL_DELAY_S,
    multiplier: float = DEFAULT_MULTIPLIER,
    max_delay: float = DEFAULT_MAX_DELAY_S,
) -> list[float]:
    """Delays BETWEEN attempts (length attempts-1), geometric, capped."""
    delays: list[float] = []
    d = float(initial)
    for _ in range(max(attempts - 1, 0)):
        delays.append(round(min(d, max_delay), 3))
        d *= multiplier
    return delays


def classify_attempt(
    result: dict[str, Any], cfg: dict[str, Any]
) -> tuple[bool, str | None, str | None]:
    """One fetch result -> (ok, rule, detail); rule/detail None on pass.

    Pass demands the deployed experience end-to-end: an answer, a final 2xx
    (the fetch follows redirects), the expected string in the body head, and —
    when the check asserts one — a latency under max_ms. First failure wins;
    expect-miss outranks slow because wrong content is worse than late content.
    """
    http = result.get("http")
    if result.get("error") or http is None:
        return False, RULE_UNREACHABLE, result.get("error") or "no answer"
    if not (200 <= int(http) < 300):
        return False, RULE_HTTP, f"http {http} (need final 2xx)"
    body = result.get("body_head") or ""
    if cfg["expect"] not in body:
        return (
            False,
            RULE_EXPECT_MISS,
            f"expected {cfg['expect']!r} not in first {len(body)} chars of body",
        )
    max_ms = cfg.get("max_ms")
    lat = result.get("latency_ms")
    if max_ms is not None and lat is not None and lat > float(max_ms):
        return False, RULE_SLOW, f"{lat}ms exceeds max_ms {max_ms}"
    return True, None, None


def run_check(
    name: str,
    cfg: dict[str, Any],
    fetch: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delays: list[float] | None = None,
    budget_s: float = DEFAULT_BUDGET_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll one URL until its expected string matches or the budget exhausts.

    `fetch(url, cfg)` must return {"http": int|None, "latency_ms": float|None,
    "error": str|None, "body_head": str} — the CLI injects the real urllib
    fetch; tests inject fakes (the offline invariant). A sleep that would
    overrun budget_s is never started, so a run's wall clock stays bounded by
    budget_s plus one in-flight fetch.
    """
    attempts = max(attempts, 1)
    if delays is None:
        delays = backoff_delays(attempts)
    t0 = clock()
    trail: list[dict[str, Any]] = []
    ok_flag, rule, detail = False, RULE_UNREACHABLE, "not attempted"
    last: dict[str, Any] = {}
    budget_exhausted = False
    for i in range(attempts):
        last = fetch(cfg["url"], cfg)
        ok_flag, rule, detail = classify_attempt(last, cfg)
        trail.append(
            {
                "attempt": i + 1,
                "http": last.get("http"),
                "latency_ms": last.get("latency_ms"),
                "ok": ok_flag,
                "rule": rule,
            }
        )
        if ok_flag or i + 1 >= attempts:
            break
        delay = delays[i] if i < len(delays) else (delays[-1] if delays else 0.0)
        if (clock() - t0) + delay > budget_s:
            budget_exhausted = True
            break
        sleep(delay)
    if budget_exhausted and detail:
        detail += " (retry budget exhausted)"
    return {
        "name": name,
        "url": cfg["url"],
        "expect": cfg["expect"],
        "ok": ok_flag,
        "rule": None if ok_flag else rule,
        "detail": None if ok_flag else detail,
        "attempts_used": len(trail),
        "budget_exhausted": budget_exhausted,
        "elapsed_s": round(clock() - t0, 3),
        "http": last.get("http"),
        "latency_ms": last.get("latency_ms"),
        "error": last.get("error"),
        "trail": trail,
    }


def run_suite(
    checks: dict[str, dict[str, Any]],
    fetch: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    initial_delay: float = DEFAULT_INITIAL_DELAY_S,
    multiplier: float = DEFAULT_MULTIPLIER,
    max_delay: float = DEFAULT_MAX_DELAY_S,
    budget_s: float = DEFAULT_BUDGET_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run every check; the per-URL pass/fail report the exit gate reads."""
    delays = backoff_delays(
        attempts, initial=initial_delay, multiplier=multiplier, max_delay=max_delay
    )
    results = [
        run_check(
            name,
            cfg,
            fetch,
            attempts=attempts,
            delays=delays,
            budget_s=budget_s,
            sleep=sleep,
            clock=clock,
        )
        for name, cfg in checks.items()
    ]
    passed = sum(1 for r in results if r["ok"])
    return {
        "ok": passed == len(results),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


_SEVERITY_OF = {RULE_SLOW: "warning"}


def to_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map failed checks onto the family diagnostic schema; passes emit nothing.

    slow=warning (served the right content, late — uptime's degraded doctrine),
    everything else=error. line/col carry no meaning for a URL and stay 0.
    """
    diags = []
    for r in results:
        if r["ok"]:
            continue
        diags.append(
            openswap.diagnostic(
                path=r["url"],
                line=0,
                col=0,
                rule=f"smoke:{r['rule']}",
                severity=_SEVERITY_OF.get(r["rule"], "error"),
                message=(
                    f"{r['name']}: {r['detail']} after {r['attempts_used']}"
                    f" attempt(s) in {r['elapsed_s']}s"
                ),
            )
        )
    return openswap.sort_diagnostics(diags)
