#!/usr/bin/env python3
"""Render a registry-ready research brief from the LongCat insights spec.

WHY: the Applied Research registry needs a mechanical digest of
docs/LONGCAT2_INSIGHTS_SPEC.md — title, verbatim TL;DR, BUILD-NOW /
SPECED-DEFERRED marker counts, H2 heading inventory — plus whatever
orchestrator report evidence exists on disk at generation time. Everything is
quoted or counted from the sources; nothing is paraphrased or invented, and an
absent evidence directory is stated as a measured fact (the exporters-skip,
never-invent precedent from build_runs_readout.mjs).

Called by the playbook engine (scripts/business/playbook.py), which resolves
inputs and injects the timestamp:

    uv run python scripts/business/playbook.py run research \\
        --artifact research-brief

Contract: generate(inputs, params, generated_at) -> {"research_brief.md": text}.
Raises FileNotFoundError when the required spec input is absent; the engine
maps that to status "skipped-missing-input". Pure over the given paths:
read-only, deterministic, no network. Loaded standalone by file path — stdlib
only, no package imports.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

PROVENANCE: dict = {
    "classification": "REAL",
    "method": (
        "Mechanical extraction (quote or count, no paraphrase) from the "
        "committed insights spec plus verbatim key/number listing of any "
        "orchestrator report JSON present at generation time."
    ),
}

_ORCH_DIR = "apps/ava-factory/reports/orchestrator/"


def _sha256(path: Path) -> str:
    """Hex sha256 of a file's bytes (small local helper; modules stay standalone)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_root() -> Path:
    """Repo root: DOTTIE_ROOT override, else three levels above this module."""
    override = os.environ.get("DOTTIE_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def _rel(path: Path) -> str:
    """Repo-relative posix path when possible; absolute posix otherwise."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_repo_root()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _extract_title(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    return "(no H1 title present in spec)"


def _extract_tldr(lines: list[str]) -> list[str]:
    """Verbatim lines between the TL;DR heading and the next H2 or rule."""
    block: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() == "## TL;DR":
            in_block = True
            continue
        if in_block and (line.startswith("## ") or line.startswith("---")):
            break
        if in_block:
            block.append(line)
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    return block


def _load_reports(
    paths: list[Path],
) -> tuple[list[tuple[Path, dict]], list[Path]]:
    """Parse each report defensively; unparseable files are skipped, not filled."""
    parsed: list[tuple[Path, dict]] = []
    skipped: list[Path] = []
    for path in sorted(paths):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            skipped.append(path)
            continue
        parsed.append((path, data))
    return parsed, skipped


def _report_lines(path: Path, data: object) -> list[str]:
    """Filename plus top-level keys and numeric fields, values verbatim."""
    lines = [f"- `{path.name}`"]
    if not isinstance(data, dict):
        lines.append(f"  - top-level JSON type: {type(data).__name__} (not an object)")
        return lines
    keys = ", ".join(sorted(data)) if data else "(none)"
    lines.append(f"  - top-level keys: {keys}")
    numerics = {
        k: v
        for k, v in data.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if numerics:
        rendered = ", ".join(f"{k}={json.dumps(numerics[k])}" for k in sorted(numerics))
        lines.append(f"  - numeric fields (verbatim): {rendered}")
    else:
        lines.append("  - numeric fields (verbatim): (none present)")
    return lines


def _frontmatter(generated_at: str, sources: list[tuple[str, str]]) -> list[str]:
    lines = [
        "---",
        "generated_by: scripts/business/generators/research_brief.py",
        f"generated_at: {json.dumps(generated_at)}",
        "classification: REAL",
        "method: >-",
        "  Mechanical extraction (quote or count, no paraphrase) from the committed",
        "  insights spec plus verbatim key/number listing of any orchestrator report",
        "  JSON present at generation time.",
        "measured: true",
        "sources:",
    ]
    for rel_path, digest in sources:
        lines.append(f"  - path: {json.dumps(rel_path)}")
        lines.append(f"    sha256: {json.dumps(digest)}")
    lines.append("---")
    return lines


def generate(
    inputs: dict[str, list[Path]],
    params: dict[str, object],
    generated_at: str,
) -> dict[str, str]:
    """Build research_brief.md from the spec and any orchestrator reports."""
    spec_paths = inputs.get("spec") or []
    if not spec_paths:
        raise FileNotFoundError("spec file absent")
    spec_path = spec_paths[0]
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_lines = spec_text.splitlines()

    title = _extract_title(spec_lines)
    tldr = _extract_tldr(spec_lines)
    build_now = spec_text.count("**BUILD-NOW**")
    deferred = spec_text.count("**SPECED-DEFERRED**")
    headings = [line[3:].strip() for line in spec_lines if line.startswith("## ")]

    reports, skipped = _load_reports(inputs.get("orchestrator_reports") or [])
    sources = [(_rel(spec_path), _sha256(spec_path))]
    sources += [(_rel(p), _sha256(p)) for p, _ in reports]

    out: list[str] = []
    out += _frontmatter(generated_at, sources)
    out += ["", f"# {title}", ""]
    out.append(
        f"This brief indexes the committed specification titled “{title}”. "
        f"The specification marks {build_now} item(s) BUILD-NOW and {deferred} "
        f"item(s) SPECED-DEFERRED across {len(headings)} H2 section(s). The TL;DR "
        "below is reproduced verbatim from the source; counts are computed "
        "mechanically and no claim is paraphrased or added."
    )
    out += ["", "## Spec inventory", ""]
    out.append(f"- BUILD-NOW markers: {build_now}")
    out.append(f"- SPECED-DEFERRED markers: {deferred}")
    out.append("- H2 headings (verbatim):")
    for heading in headings:
        out.append(f"  - {heading}")
    out += ["", "### TL;DR (verbatim from source)", ""]
    out += tldr if tldr else ["(no TL;DR section present in spec)"]
    out += ["", "## Orchestrator evidence", ""]
    if not reports and not skipped:
        out.append(
            f"0 orchestrator reports were present under {_ORCH_DIR} "
            "at generation time."
        )
    else:
        for path, data in reports:
            out += _report_lines(path, data)
    if skipped:
        names = ", ".join(f"`{p.name}`" for p in skipped)
        out += ["", f"Sources skipped (unparseable JSON, not cited): {names}"]
    out += ["", "## Citations", ""]
    for rel_path, digest in sources:
        out.append(f"- `{rel_path}` — sha256 `{digest}`")
    out.append("")
    return {"research_brief.md": "\n".join(out)}
