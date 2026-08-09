#!/usr/bin/env python3
"""Render a change-log entry from read-only git history.

WHY: the ops venture needs a committed record of what changed since the base
ref, derived from history itself rather than hand-written notes. This module
is the schema's sole sanctioned subprocess exception: it may invoke read-only
`git` (merge-base, rev-parse, log) and nothing else. Subject lines only (%s)
are rendered — never bodies or trailers, which keeps attribution trailers and
tool names out of the artifact per the naming policy — and a subject that
itself contains a known assistant or model brand token is withheld rather
than edited. Branch names are never printed; the artifact cites SHAs only.

Called by the playbook engine (scripts/business/playbook.py), which injects
the timestamp (this artifact declares zero file inputs):

    uv run python scripts/business/playbook.py run ops --artifact changelog

Contract: generate(inputs, params, generated_at) -> {"changelog_entry.md":
text}. params: {"base_ref": "main"} (default "main"), optional "repo_root".
If the base ref does not resolve, the artifact degrades to the 20 most recent
commits and states that as a measured fact. If git itself is unavailable,
raises FileNotFoundError("git history unavailable"); the engine maps that to
status "skipped-missing-input". Idempotency: the rendered text embeds the
HEAD sha, so an unchanged repository regenerates byte-identical content and
the engine reports "unchanged". Loaded standalone by file path — stdlib only,
no package imports.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_METHOD = (
    "Commit subject lines listed verbatim from read-only git history between "
    "the merge base and HEAD; subjects matching the naming policy are withheld."
)

# Naming-policy denylist: a subject containing one of these assistant/model
# brand tokens is withheld from the artifact rather than edited. The tokens
# appear here only so emitted text never carries them.
_BRAND_TOKENS = (
    "anthropic",
    "claude",
    "opus",
    "sonnet",
    "haiku",
    "gpt",
    "chatgpt",
    "openai",
    "copilot",
    "gemini",
    "bard",
    "llama",
    "mistral",
    "deepseek",
    "qwen",
    "grok",
)
_BRAND_RE = re.compile(
    r"\b(" + "|".join(_BRAND_TOKENS) + r")\b", flags=re.IGNORECASE
)
_LOG_FORMAT = "%H%x09%ad%x09%s"


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    """Run a read-only git command; OSError becomes FileNotFoundError."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise FileNotFoundError("git history unavailable") from exc


def _commit_lines(log_stdout: str) -> list[str]:
    """One rendered bullet per log line: '- <short-sha> (<date>) <subject>'."""
    lines: list[str] = []
    for raw in log_stdout.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, date, subject = parts
        if _BRAND_RE.search(subject):
            lines.append(f"- {sha[:7]} ({date}) (subject withheld: naming policy)")
        else:
            lines.append(f"- {sha[:7]} ({date}) {subject}")
    return lines


def generate(
    inputs: dict[str, list[Path]],
    params: dict[str, object],
    generated_at: str,
) -> dict[str, str]:
    """Build changelog_entry.md from read-only git history."""
    base_ref = str(params.get("base_ref") or "main")
    cwd = str(params.get("repo_root") or Path.cwd())

    head = _git(cwd, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise FileNotFoundError("git history unavailable")
    head_sha = head.stdout.strip()

    merge_base = _git(cwd, "merge-base", "HEAD", base_ref)
    fallback = merge_base.returncode != 0
    if fallback:
        log = _git(
            cwd, "log", "-n", "20", "--no-decorate",
            f"--format={_LOG_FORMAT}", "--date=short",
        )
        base_sha = None
    else:
        base_sha = merge_base.stdout.strip()
        log = _git(
            cwd, "log", "--no-decorate", f"--format={_LOG_FORMAT}",
            "--date=short", f"{base_sha}..HEAD",
        )
    if log.returncode != 0:
        raise FileNotFoundError("git history unavailable")
    commits = _commit_lines(log.stdout)

    out = [
        "---",
        "generated_by: scripts/business/generators/changelog.py",
        f"generated_at: {json.dumps(generated_at)}",
        "classification: REAL",
        f"method: {json.dumps(_METHOD)}",
        "measured: true",
        "sources:",
    ]
    if base_sha is not None:
        out.append(f"  - ref: {json.dumps(f'merge-base {base_ref}..HEAD')}")
        out.append(f"    sha: {json.dumps(base_sha)}")
    out.append('  - ref: "HEAD"')
    out.append(f"    sha: {json.dumps(head_sha)}")
    out += ["---", "", "# Change log", ""]
    if fallback:
        out.append(
            f"base ref {base_ref} not found; showing the 20 most recent commits"
        )
        out.append("")
    if commits:
        out += commits
    else:
        out.append("No commits are present after the merge base.")
    out.append("")
    return {"changelog_entry.md": "\n".join(out)}
