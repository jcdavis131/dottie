# Solo personal project, no connection to employer, built with public/free-tier only
"""Leaks — secrets-scanning core (openswap #7: GitGuardian / TruffleHog
Enterprise).

detect-secrets/gitleaks pattern, 100% stdlib: a data-driven regex signature
pack (AWS/GitHub/GitLab/Slack/Stripe/Google/OpenAI/Anthropic/npm/SendGrid key
shapes, PEM private-key headers, JWTs) plus Shannon-entropy scoring (math +
collections.Counter) for keyword-context credentials and bare high-entropy
blobs, over three inputs: raw text, an os.walk file tree, and unified-diff
patch text. Git NEVER runs in here — the `leaks` plugin CLI feeds read-only
`git diff --cached` / `git log -p` output into scan_patch(), the same
pure-core/real-IO split as reach/prose/links. Findings use the family schema
(openswap.diagnostic) plus two extra keys: `fingerprint` (sha256 of
rule:secret — hashlib on purpose, hash() is seed-randomized across runs) and
`entropy`. Secrets are never emitted whole: messages carry redact()'s first-4
chars + length, so a findings report is itself safe to share or commit.

Precision model: specific signatures run first and claim their match span;
span-overlap suppression means one secret yields one finding under the most
specific rule (a GitHub token is never double-reported as a generic
high-entropy blob). Keyword/generic rules are entropy-gated so placeholder
values ("changeme", "aaaaaaaaaaaa") stay quiet.

Extension points:
- Signature packs as data: `extra_signatures` in the --config JSON adds org
  rules (id/pattern/severity/group/entropy) with no code edit; `disable`
  turns built-ins off (policy-as-config).
- Per-file-type entropy thresholds: `entropy_by_ext` overlays the
  base64/hex/keyword thresholds per extension (e.g. raise base64 to 5.5 for
  .ipynb so embedded blobs stop flagging).
- False-positive allowlist: allow.rules / allow.paths (posix globs) /
  allow.patterns (regex over the matched secret) / allow.fingerprints —
  fingerprints survive line moves and file renames because they hash
  rule:secret, not positions; header-shaped rules (private-key-pem) share one
  fingerprint per header text, so allowlist those by path instead.
- CI gate mode: `scout leaks scan|staged|history --fail-on <severity>`;
  openswap.summarize(diags)["by_severity"] is the stable machine contract.
- New scan surfaces: scan_lines() takes any (lineno, line) iterable — feed it
  archived logs, env dumps, or sqlite exports without touching this module.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bigbang.core import openswap

DEFAULT_CONFIG: dict[str, Any] = {
    # known false positives, four layered escape hatches (the harper doctrine:
    # a wrong finding must never block work)
    "allow": {"rules": [], "paths": [], "patterns": [], "fingerprints": []},
    # Shannon-entropy gates by charset family; keyword gates the generic
    # credential-assignment rule
    "entropy": {"base64": 4.5, "hex": 3.0, "keyword": 3.5},
    # per-extension overrides of the gates above, e.g. {".ipynb": {"base64": 5.5}}
    "entropy_by_ext": {},
    # built-in signature ids to turn off
    "disable": [],
    # org signatures: [{id, pattern, severity?, group?, entropy?, entropy_key?}]
    "extra_signatures": [],
    "max_file_kb": 1024,
    "exclude_dirs": [
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
        ".scout", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist",
        "build", ".next",
    ],
    "exclude_exts": [
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
        ".tar", ".whl", ".exe", ".dll", ".so", ".pyd", ".woff", ".woff2",
        ".ttf", ".mp3", ".mp4", ".sqlite3", ".db",
    ],
}

# Specific shapes first: order is load-bearing — the span-overlap suppression
# in scan_lines() means whichever signature matches first owns the secret.
_SPECIFIC_SIGNATURES: tuple[dict[str, Any], ...] = (
    {
        "id": "aws-access-key-id",
        "description": "AWS access key ID",
        "severity": "error",
        "pattern": r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ABIA|ACCA)[0-9A-Z]{16}\b",
    },
    {
        "id": "aws-secret-key",
        "description": "AWS secret access key near an aws keyword",
        "severity": "error",
        "group": 1,
        "entropy_key": "keyword",
        "pattern": r"(?i)\baws\w*[\w .:=\-]{0,20}?[\"']([0-9A-Za-z/+=]{40})[\"']",
    },
    {
        "id": "github-token",
        "description": "GitHub token",
        "severity": "error",
        "pattern": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{80,})\b",
    },
    {
        "id": "gitlab-pat",
        "description": "GitLab personal access token",
        "severity": "error",
        "pattern": r"\bglpat-[A-Za-z0-9\-_]{20,}\b",
    },
    {
        "id": "slack-token",
        "description": "Slack token",
        "severity": "error",
        "pattern": r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b",
    },
    {
        "id": "slack-webhook",
        "description": "Slack incoming-webhook URL",
        "severity": "error",
        "pattern": (
            r"https://hooks\.slack\.com/services/"
            r"T[0-9A-Za-z]+/B[0-9A-Za-z]+/[0-9A-Za-z]+"
        ),
    },
    {
        "id": "stripe-live-key",
        "description": "Stripe live key",
        "severity": "error",
        "pattern": r"\b[sr]k_live_[0-9A-Za-z]{16,}\b",
    },
    {
        "id": "google-api-key",
        "description": "Google API key",
        "severity": "error",
        "pattern": r"\bAIza[0-9A-Za-z\-_]{35}\b",
    },
    {
        "id": "openai-key",
        "description": "OpenAI API key",
        "severity": "error",
        "pattern": r"\bsk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}\b",
    },
    {
        "id": "anthropic-key",
        "description": "Anthropic API key",
        "severity": "error",
        "pattern": r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b",
    },
    {
        "id": "npm-token",
        "description": "npm access token",
        "severity": "error",
        "pattern": r"\bnpm_[A-Za-z0-9]{36}\b",
    },
    {
        "id": "sendgrid-key",
        "description": "SendGrid API key",
        "severity": "error",
        "pattern": r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b",
    },
    {
        "id": "private-key-pem",
        "description": "PEM private-key header",
        "severity": "error",
        "pattern": r"-----BEGIN [A-Z0-9 ]*?PRIVATE KEY[A-Z ]*-----",
    },
    {
        "id": "jwt",
        "description": "JSON Web Token",
        "severity": "warning",
        "pattern": r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
    },
)

# Catch-alls last: they only see spans no specific signature claimed.
_GENERIC_SIGNATURES: tuple[dict[str, Any], ...] = (
    {
        "id": "generic-api-key",
        "description": "assignment to a credential-named key",
        "severity": "warning",
        "group": 1,
        "entropy_key": "keyword",
        "pattern": (
            r"(?i)\b(?:api[_\-]?key|apikey|secret|token|passwd|password"
            r"|credential|access[_\-]?key|client[_\-]?secret)\b"
            r"[^=:\n]{0,24}?[:=]\s*[\"']?([A-Za-z0-9+/=_\-]{10,80})"
        ),
    },
    {
        "id": "high-entropy",
        "description": "high-entropy base64-charset string",
        "severity": "suggestion",
        "entropy_key": "base64",
        "pattern": r"[A-Za-z0-9+/=]{32,}",
    },
    {
        "id": "high-entropy-hex",
        "description": "high-entropy hex string",
        "severity": "info",
        "entropy_key": "hex",
        "pattern": r"\b[0-9a-fA-F]{32,}\b",
    },
)

_ALLOW_KEYS = {"rules", "paths", "patterns", "fingerprints"}


def shannon_entropy(s: str) -> float:
    """Bits per character over the string's own frequency table."""
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def redact(secret: str, *, keep: int = 4) -> str:
    """First `keep` chars + length — enough to locate, never enough to use."""
    return f"{secret[:keep]}…({len(secret)} chars)"


def fingerprint(rule_id: str, secret: str) -> str:
    """Stable id for allowlisting one finding: sha256 over rule:secret.

    hashlib, never hash() (seed-randomized per process); hashing content
    instead of file:line means the fingerprint survives line moves and
    renames — the gitleaks .gitleaksignore weakness this avoids.
    """
    return hashlib.sha256(f"{rule_id}:{secret}".encode()).hexdigest()[:16]


def load_config(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG overlaid with an optional JSON file (prose.load_rules
    semantics: dicts merge key-by-key, lists extend deduped, scalars replace;
    unknown keys raise for fail_agent)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config file must be a JSON object")
        for key, val in raw.items():
            if key not in cfg:
                raise ValueError(f"unknown config key {key!r} (known: {sorted(cfg)})")
            base = cfg[key]
            if isinstance(base, dict) and isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(base.get(k), list) and isinstance(v, list):
                        base[k] = base[k] + [x for x in v if x not in base[k]]
                    else:
                        base[k] = v
            elif isinstance(base, list) and isinstance(val, list):
                cfg[key] = base + [x for x in val if x not in base]
            else:
                cfg[key] = val
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict[str, Any]) -> None:
    allow = cfg["allow"]
    if not isinstance(allow, dict) or set(allow) != _ALLOW_KEYS:
        raise ValueError(
            f"config 'allow': needs exactly the keys {sorted(_ALLOW_KEYS)}"
        )
    for k, v in allow.items():
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ValueError(f"config allow.{k}: must be a list of strings")
    for pat in allow["patterns"]:
        try:
            re.compile(pat)
        except re.error as e:
            raise ValueError(f"config allow.patterns {pat!r}: {e}") from None

    def _num(v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0

    if not (isinstance(cfg["entropy"], dict) and all(
        isinstance(k, str) and _num(v) for k, v in cfg["entropy"].items()
    )):
        raise ValueError("config 'entropy': must map names to numbers >= 0")
    ebe = cfg["entropy_by_ext"]
    if not (isinstance(ebe, dict) and all(
        isinstance(k, str) and isinstance(v, dict)
        and all(isinstance(k2, str) and _num(v2) for k2, v2 in v.items())
        for k, v in ebe.items()
    )):
        raise ValueError(
            "config 'entropy_by_ext': must map extensions to threshold objects"
        )
    for key in ("disable", "exclude_dirs", "exclude_exts"):
        v = cfg[key]
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ValueError(f"config {key!r}: must be a list of strings")
    n = cfg["max_file_kb"]
    if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
        raise ValueError(f"config 'max_file_kb': needs an int >= 1, got {n!r}")
    for sig in cfg["extra_signatures"]:
        if not isinstance(sig, dict):
            raise ValueError("config extra_signatures: entries must be objects")
        for req in ("id", "pattern"):
            if not isinstance(sig.get(req), str) or not sig[req]:
                raise ValueError(f"config extra_signatures: {req!r} is required")
        sev = sig.get("severity", "warning")
        if sev not in openswap.SEVERITIES:
            raise ValueError(
                f"extra signature {sig['id']!r}: severity must be one of "
                f"{'|'.join(openswap.SEVERITIES)}"
            )
        g = sig.get("group", 0)
        if not (isinstance(g, int) and not isinstance(g, bool) and g >= 0):
            raise ValueError(f"extra signature {sig['id']!r}: bad group {g!r}")


def build_signatures(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Compile the effective pack: built-in specifics, then org extras, then
    the generic catch-alls (order feeds the suppression rule); raises
    ValueError on a bad extra regex for the CLI to fail_agent."""
    cfg = config or load_config(None)
    disable = set(cfg["disable"])
    sigs: list[dict[str, Any]] = []
    ordered = (*_SPECIFIC_SIGNATURES, *cfg["extra_signatures"], *_GENERIC_SIGNATURES)
    for raw in ordered:
        if raw["id"] in disable:
            continue
        try:
            compiled = re.compile(raw["pattern"])
        except re.error as e:
            raise ValueError(f"signature {raw['id']!r}: bad regex: {e}") from None
        sigs.append({
            "id": raw["id"],
            "description": raw.get("description", raw["id"]),
            "severity": raw.get("severity", "warning"),
            "re": compiled,
            "group": int(raw.get("group", 0)),
            "entropy_key": raw.get("entropy_key"),
            "entropy": raw.get("entropy"),
        })
    return sigs


def thresholds(config: dict[str, Any], ext: str) -> dict[str, float]:
    """Entropy gates for one file type: base thresholds + per-ext overlay."""
    thr = dict(config["entropy"])
    thr.update(config["entropy_by_ext"].get((ext or "").lower(), {}))
    return thr


def _allowed(
    sig_id: str, path_posix: str, secret: str, fp: str, allow: dict[str, Any]
) -> bool:
    if sig_id in allow["rules"] or fp in allow["fingerprints"]:
        return True
    if any(fnmatch.fnmatchcase(path_posix, pat) for pat in allow["paths"]):
        return True
    return any(re.search(pat, secret) for pat in allow["patterns"])


def scan_lines(
    numbered_lines: Any,
    *,
    path: str,
    config: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan (lineno, line) pairs -> sorted family diagnostics.

    The workhorse every surface reduces to: scan_text enumerates a blob,
    scan_patch feeds added lines with their post-image line numbers, and new
    surfaces (logs, env dumps) can call it directly.
    """
    cfg = config or load_config(None)
    sigs = build_signatures(cfg) if signatures is None else signatures
    thr = thresholds(cfg, Path(path).suffix)
    allow = cfg["allow"]
    posix = Path(path).as_posix()
    findings: list[dict[str, Any]] = []
    for lineno, line in numbered_lines:
        spans: list[tuple[int, int]] = []
        for sig in sigs:
            for m in sig["re"].finditer(line):
                secret = m.group(sig["group"])
                if not secret:
                    continue
                s0, s1 = m.span(sig["group"])
                if any(a < s1 and s0 < b for a, b in spans):
                    continue
                gate = sig["entropy"]
                if gate is None and sig["entropy_key"]:
                    gate = thr.get(sig["entropy_key"])
                ent = shannon_entropy(secret)
                if gate is not None and ent < float(gate):
                    continue
                # allowlisted matches still claim their span so a catch-all
                # rule can't resurface a suppressed secret under another id
                spans.append((s0, s1))
                fp = fingerprint(sig["id"], secret)
                if _allowed(sig["id"], posix, secret, fp, allow):
                    continue
                d = openswap.diagnostic(
                    path=path, line=lineno, col=s0 + 1,
                    rule=f"leaks:{sig['id']}", severity=sig["severity"],
                    message=(
                        f"{sig['description']}: '{redact(secret)}'"
                        f" (entropy {ent:.2f})"
                    ),
                    suggestion=(
                        "rotate the credential and move it to a secret store "
                        "(scout secrets set); if a false positive, allowlist "
                        f"fingerprint {fp}"
                    ),
                )
                d["fingerprint"] = fp
                d["entropy"] = round(ent, 2)
                findings.append(d)
    return openswap.sort_diagnostics(findings)


def scan_text(
    text: str,
    *,
    path: str = "<text>",
    config: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan one blob of text; line numbers are 1-based."""
    numbered = enumerate((text or "").splitlines(), 1)
    return scan_lines(numbered, path=path, config=config, signatures=signatures)


def scan_file(
    path: str | Path,
    *,
    config: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """One file -> (diagnostics, skip_reason|None).

    Skips are explicit, never silent: excluded-ext, too-large, binary (a NUL
    in the first 8 KiB), unreadable. Text decodes with errors='replace' so a
    stray byte can't crash a sweep.
    """
    cfg = config or load_config(None)
    sigs = build_signatures(cfg) if signatures is None else signatures
    p = Path(path)
    if p.suffix.lower() in cfg["exclude_exts"]:
        return [], "excluded-ext"
    try:
        if p.stat().st_size > cfg["max_file_kb"] * 1024:
            return [], "too-large"
        data = p.read_bytes()
    except OSError:
        return [], "unreadable"
    if b"\x00" in data[:8192]:
        return [], "binary"
    text = data.decode("utf-8", errors="replace")
    return scan_text(text, path=str(p), config=cfg, signatures=sigs), None


def scan_tree(
    root: str | Path,
    *,
    config: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Walk a tree (vendor/VCS dirs pruned) -> (diagnostics, stats)."""
    cfg = config or load_config(None)
    sigs = build_signatures(cfg) if signatures is None else signatures
    exclude = set(cfg["exclude_dirs"])
    findings: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"files_scanned": 0, "skipped": {}}
    for dirpath, dirnames, filenames in os.walk(Path(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        for name in sorted(filenames):
            diags, skip = scan_file(
                Path(dirpath) / name, config=cfg, signatures=sigs
            )
            if skip:
                stats["skipped"][skip] = stats["skipped"].get(skip, 0) + 1
                continue
            stats["files_scanned"] += 1
            findings.extend(diags)
    return openswap.sort_diagnostics(findings), stats


# ---- patch text: staged diffs and read-only history -------------------------

_COMMIT_RE = re.compile(r"^commit ([0-9a-f]{7,40})\b")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_patch(text: str) -> list[dict[str, Any]]:
    """Unified-diff / `git log -p` text -> ADDED lines with post-image line
    numbers: [{path, line, content, commit|None}].

    Only additions are scanned (a secret in a removed line is already in
    history — `history` mode covers the commits that introduced it). Commit
    message lines can't leak in: a `commit` header resets the current file,
    and nothing is collected until the next +++/@@ pair. /dev/null targets
    (deletions) and binary diffs contribute nothing.
    """
    entries: list[dict[str, Any]] = []
    commit: str | None = None
    path: str | None = None
    new_line: int | None = None
    for raw in (text or "").splitlines():
        m = _COMMIT_RE.match(raw)
        if m:
            commit, path, new_line = m.group(1), None, None
            continue
        if raw.startswith("diff --git "):
            path, new_line = None, None
            continue
        if raw.startswith("+++ "):
            target = raw[4:].split("\t")[0].strip()
            if target == "/dev/null":
                path = None
            else:
                path = target[2:] if target[:2] in ("a/", "b/") else target
            new_line = None
            continue
        m = _HUNK_RE.match(raw)
        if m:
            new_line = int(m.group(1)) if path else None
            continue
        if path is None or new_line is None:
            continue
        if raw.startswith("+"):
            entries.append(
                {"path": path, "line": new_line, "content": raw[1:],
                 "commit": commit}
            )
            new_line += 1
        elif raw.startswith(("-", "\\")):
            pass  # removals and "\ No newline" markers move no new-file line
        else:
            new_line += 1  # context line (patches wider than -U0)
    return entries


def scan_patch(
    text: str,
    *,
    config: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Scan a patch's added lines -> (diagnostics, stats); findings from
    history carry a `commit` key (short sha) so the leak is attributable."""
    cfg = config or load_config(None)
    sigs = build_signatures(cfg) if signatures is None else signatures
    entries = parse_patch(text)
    groups: dict[tuple[str | None, str], list[tuple[int, str]]] = {}
    for e in entries:
        groups.setdefault((e["commit"], e["path"]), []).append(
            (e["line"], e["content"])
        )
    findings: list[dict[str, Any]] = []
    for (commit, fpath), numbered in groups.items():
        diags = scan_lines(numbered, path=fpath, config=cfg, signatures=sigs)
        if commit:
            for d in diags:
                d["commit"] = commit[:12]
        findings.extend(diags)
    stats = {
        "added_lines": len(entries),
        "files": len({e["path"] for e in entries}),
        "commits": len({e["commit"] for e in entries if e["commit"]}),
    }
    return openswap.sort_diagnostics(findings), stats
