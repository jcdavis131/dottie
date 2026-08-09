#!/usr/bin/env python3
"""Render an HF-style dataset card from the orchestration corpus metadata.

WHY: the corpus metadata file (apps/ava-factory/data/orchestration/
corpus_meta.json) records what the orchestration corpus contains, but nothing
renders it as a reviewable card. This generator emits a card modeled on the
tasks/artifacts/corpus_proposals README pattern: YAML frontmatter carrying the
house provenance block plus the provenance_classification field that
build_hub_registry.mjs reads, a per-source provenance table, and an audit
section hashing the metadata file itself (the audit-sidecar pattern). Values
come only from the file — an absent key renders as "(not recorded)", never a
guess (data_provenance_SOP.md).

Called by the playbook engine (scripts/business/playbook.py), which resolves
inputs and injects the timestamp:

    uv run python scripts/business/playbook.py run research \\
        --artifact dataset-card

Contract: generate(inputs, params, generated_at) -> {"dataset_card.md": text}.
Raises FileNotFoundError when the metadata file is absent or unparseable; the
engine maps that to status "skipped-missing-input". Pure over the given paths:
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
        "Per-source table rendered from the committed corpus metadata JSON; "
        "absent keys render as '(not recorded)' and no value is invented."
    ),
}

_NOT_RECORDED = "(not recorded)"


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


def _field(record: dict, *keys: str) -> str:
    """First present key's value as text; '(not recorded)' when none exist."""
    for key in keys:
        if key in record and record[key] is not None:
            return str(record[key])
    return _NOT_RECORDED


def _records(meta: object) -> list[dict]:
    """Tolerate the three observed shapes without guessing at others.

    A dict with a "sources" list, a dict with a "sources" mapping of
    name -> record (the shape build_orchestration_corpus.py writes; the key
    becomes the record's name), or a top-level list of source records. Only
    dict entries are renderable rows; anything else contributes no row.
    """
    if isinstance(meta, dict):
        raw = meta.get("sources", [])
    elif isinstance(meta, list):
        raw = meta
    else:
        raw = []
    if isinstance(raw, dict):
        raw = [
            {"name": key, **value}
            for key, value in raw.items()
            if isinstance(value, dict)
        ]
    if not isinstance(raw, list):
        raw = []
    return [entry for entry in raw if isinstance(entry, dict)]


def generate(
    inputs: dict[str, list[Path]],
    params: dict[str, object],
    generated_at: str,
) -> dict[str, str]:
    """Build dataset_card.md from corpus_meta.json."""
    meta_paths = inputs.get("corpus_meta") or []
    if not meta_paths:
        raise FileNotFoundError("corpus_meta.json absent")
    meta_path = meta_paths[0]
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FileNotFoundError(
            f"corpus_meta.json unparseable as JSON: {meta_path.name}"
        ) from exc

    records = _records(meta)
    top = meta if isinstance(meta, dict) else {}
    pretty_name = _field(top, "name", "id")
    license_value = _field(top, "license")
    meta_rel = _rel(meta_path)
    meta_sha = _sha256(meta_path)

    licensed = sum(1 for r in records if _field(r, "license") != _NOT_RECORDED)
    with_rows = sum(
        1
        for r in records
        if _field(r, "rows", "count", "n", "n_records") != _NOT_RECORDED
    )
    with_checksum = sum(
        1 for r in records if _field(r, "sha256", "checksum") != _NOT_RECORDED
    )

    out: list[str] = [
        "---",
        f"pretty_name: {json.dumps(pretty_name)}",
        f"license: {json.dumps(license_value)}",
        "tags:",
        "- dottie",
        "- orchestration",
        "- dataset-card",
        "provenance_classification: REAL",
        "generated_by: scripts/business/generators/dataset_card.py",
        f"generated_at: {json.dumps(generated_at)}",
        "classification: REAL",
        "method: >-",
        "  Per-source table rendered from the committed corpus metadata JSON;",
        "  absent keys render as '(not recorded)' and no value is invented.",
        "measured: true",
        "sources:",
        f"  - path: {json.dumps(meta_rel)}",
        f"    sha256: {json.dumps(meta_sha)}",
        "---",
        "",
        f"# {pretty_name}",
        "",
        "## Dataset Summary",
        "",
        (
            f"The metadata file declares {len(records)} source record(s). "
            f"{licensed} of {len(records)} record a license, {with_rows} of "
            f"{len(records)} record a row count, and {with_checksum} of "
            f"{len(records)} record a checksum. All values below are rendered "
            "verbatim from the metadata file; absent keys are shown as "
            f"“{_NOT_RECORDED}”."
        ),
        "",
        "## Source provenance",
        "",
        "| Source | Path | License | Rows | Checksum | Classification |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        cells = [
            _field(record, "name", "id"),
            _field(record, "path", "file", "dir", "dirname"),
            _field(record, "license"),
            _field(record, "rows", "count", "n", "n_records"),
            _field(record, "sha256", "checksum"),
            _field(record, "classification"),
        ]
        out.append("| " + " | ".join(cells) + " |")
    if not records:
        out.append("| (no source records present in metadata) | | | | | |")
    counts = top.get("counts") if isinstance(top.get("counts"), dict) else None
    if counts:
        out += [
            "",
            "## Recorded counts",
            "",
            (
                "Copied verbatim from the metadata file's `counts` block; "
                "nothing is recomputed."
            ),
            "",
        ]
        for key in sorted(counts):
            value = counts[key]
            if isinstance(value, dict):
                inner = ", ".join(
                    f"{k}: {value[k]}" for k in sorted(value)
                )
                out.append(f"- {key} — {inner}")
            else:
                out.append(f"- {key}: {value}")
    out += [
        "",
        "## Audit",
        "",
        f"- generated_at: {generated_at}",
        f"- source file: `{meta_rel}`",
        f"- source_sha256: `{meta_sha}`",
        "",
    ]
    return {"dataset_card.md": "\n".join(out)}
