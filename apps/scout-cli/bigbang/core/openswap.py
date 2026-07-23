# Solo personal project, no connection to employer, built with public/free-tier only
"""Openswap family base — shared contract for paid-SaaS replacement adapters.

Every openswap adapter (prose = Grammarly Premium, ...) shares three invariants,
and later adapters import them from here instead of re-implementing:

[A] detect_local_capability — probe PATH for the native open-source binary,
    confirm health/version with a cheap read-only subcommand, and return a
    capability report {tier, native: {binary, found, path, version, probe_cmd,
    probe_output}, ...}.
[B] best_available_tier — native binary when present (fastest, fullest) ->
    pure-stdlib fallback core (degraded but working; must self-describe its
    reduced scope via `fallback_scope`) -> explicit "unavailable" with an
    install hint. NEVER a silent no-op and NEVER a network/SaaS fallback tier:
    the privacy guarantee is architectural (zero network calls), so it stays
    falsifiable rather than a ToS promise.
[C] normalized diagnostics — every tier emits the same schema
    {path, line, col, rule, severity, message, suggestion, source} so callers
    never branch on which tier produced a finding.

This module does PURE logic plus local subprocess probing only. No network,
no filesystem writes.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

TIER_NATIVE = "native"
TIER_FALLBACK = "fallback"
TIER_UNAVAILABLE = "unavailable"

SEVERITIES = ("error", "warning", "suggestion", "info")
_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def severity_rank(severity: str) -> int:
    """Lower is more severe; unknown severities sort last."""
    return _SEVERITY_RANK.get(severity, len(SEVERITIES))


def diagnostic(
    *,
    path: str,
    line: int,
    rule: str,
    message: str,
    col: int = 1,
    severity: str = "warning",
    suggestion: str | None = None,
    source: str = "core",
) -> dict[str, Any]:
    """One finding in the family-wide normalized schema."""
    if severity not in _SEVERITY_RANK:
        severity = "warning"
    return {
        "path": path,
        "line": int(line),
        "col": int(col),
        "rule": rule,
        "severity": severity,
        "message": message,
        "suggestion": suggestion,
        "source": source,
    }


def sort_diagnostics(diags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable order: file, position, then severity, then rule id."""
    return sorted(
        diags,
        key=lambda d: (
            d.get("path", ""),
            d.get("line", 0),
            d.get("col", 0),
            severity_rank(d.get("severity", "warning")),
            d.get("rule", ""),
        ),
    )


def summarize(diags: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by severity/rule — the stable contract for pre-publish gates."""
    by_severity = {s: 0 for s in SEVERITIES}
    by_rule: dict[str, int] = {}
    files: set[str] = set()
    for d in diags:
        sev = d.get("severity", "warning")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        rule = d.get("rule", "?")
        by_rule[rule] = by_rule.get(rule, 0) + 1
        files.add(d.get("path", "?"))
    return {
        "total": len(diags),
        "by_severity": by_severity,
        "by_rule": dict(sorted(by_rule.items())),
        "files": sorted(files),
    }


def probe_binary(
    binary: str,
    *,
    probe_args: tuple[str, ...] = ("--version",),
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Probe PATH for a local binary; version confirmation is best-effort.

    `found` means "on PATH" — a failing version probe must not demote a real
    install to the fallback tier (the probe flag may drift across releases),
    so the failure is only recorded in `probe_output`.
    """
    path = shutil.which(binary)
    report: dict[str, Any] = {
        "binary": binary,
        "found": path is not None,
        "path": path,
        "version": None,
        "probe_cmd": None,
        "probe_output": None,
    }
    if path is None:
        return report
    report["probe_cmd"] = " ".join([binary, *probe_args])
    try:
        r = subprocess.run(
            [path, *probe_args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        first = ((r.stdout or r.stderr or "").strip().splitlines() or [""])[0]
        report["probe_output"] = first
        if r.returncode == 0 and first:
            report["version"] = first
    except Exception as e:
        report["probe_output"] = f"{type(e).__name__}: {e}"
    return report


def capability_report(
    adapter: str,
    *,
    native: dict[str, Any],
    extras: dict[str, dict[str, Any]] | None = None,
    fallback_scope: str | None = None,
    install_hint: str | None = None,
) -> dict[str, Any]:
    """Resolve the execution tier from a native probe + a declared fallback."""
    if native.get("found"):
        tier = TIER_NATIVE
    elif fallback_scope:
        tier = TIER_FALLBACK
    else:
        tier = TIER_UNAVAILABLE
    report: dict[str, Any] = {"adapter": adapter, "tier": tier, "native": native}
    if extras:
        report["extras"] = extras
    if tier == TIER_FALLBACK:
        report["fallback_scope"] = fallback_scope
    if tier != TIER_NATIVE and install_hint:
        report["install_hint"] = install_hint
    return report
