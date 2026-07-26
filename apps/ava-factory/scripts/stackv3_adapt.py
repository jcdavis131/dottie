#!/usr/bin/env python3
"""HuggingFaceCode/stack-v3-train → training text, with a PER-FILE licence gate.

Solo personal project, no connection to employer, built with public/free-tier only

Why this needs its own adapter rather than a `text_field` in sources.yaml:
stack-v3 rows are **repositories**, not files. One row is
``{repo_path, repo_id, commit_id, github_metadata, num_files, files: [...]}``
and every element of ``files`` carries its own ``content``, ``language``,
``is_vendor``, ``license_type`` and ``detected_licenses`` (a LIST). There is no
single string field holding training text.

The licence subtlety that makes the per-file gate mandatory: the dataset is
published under ``odc-by``, but that is the licence of the **collection**. The
individual source files carry whatever licence their authors chose, which is
exactly why the schema ships ``detected_licenses`` per file. Gating only on the
dataset-level tag would train on files whose own terms forbid it — the same
mistake ``pull_oapen_books.py::gate_rights`` had to learn, where reading only the
first licence value admitted a work that was CC-BY *and* ND.

``gate_license`` is imported, never re-implemented. A second copy of a licence
allowlist is the drifting-constant bug class that has already produced real bugs
in this repo.

Adapter contract (``dottie/datagen/adapters.py``): a pure function
``rec -> {text, ...} | None``. No network. One row in, one text out — so the
permitted files of a repo are concatenated with path headers, which also
preserves the repo-level context that is the whole point of stack-v3's
repo-grouped layout. A row whose files are ALL rejected returns ``None``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_DD = Path(__file__).resolve().parent / "dataset_discovery.py"


def _load_gate():
    """Import gate_license from dataset_discovery without duplicating it.

    dataset_discovery.py is a script, so a plain import only works when
    ``scripts/`` happens to be on sys.path. Load it by path instead, so this
    keeps working from any cwd and after this module moves into
    ``dottie/datagen/``.
    """
    spec = importlib.util.spec_from_file_location("_dd_license_gate", _DD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.gate_license


gate_license = _load_gate()

# Vendored third-party trees are duplicated across thousands of repos. Training
# on them buys nothing and inflates near-duplicate mass, which the curator then
# has to spend effort removing.
DROP_VENDORED = True

# A file with no detectable licence is NOT permissively licensed. Same rule as
# the dataset gate: unverified is not permissive.
REQUIRE_DETECTED_LICENCE = True

MIN_FILE_CHARS = 32


def _file_licence_values(f: dict):
    """Every licence this file asserts. Prefers the per-file list."""
    detected = f.get("detected_licenses")
    if detected:
        return detected
    single = f.get("license_type")
    return [single] if single else []


def keep_file(f: dict) -> tuple[bool, str]:
    """(keep, reason). Reason is returned for auditability, not just logging."""
    if not isinstance(f, dict):
        return False, "not a record"
    if DROP_VENDORED and f.get("is_vendor"):
        return False, "vendored"
    content = f.get("content")
    if not isinstance(content, str) or len(content.strip()) < MIN_FILE_CHARS:
        return False, "empty or too short"
    values = _file_licence_values(f)
    if not values:
        if REQUIRE_DETECTED_LICENCE:
            return False, "no detected licence — unverified is not permissive"
        return True, "no licence required"
    ok, reason = gate_license(values)
    return (True, reason) if ok else (False, reason)


def adapt_record(rec: dict) -> dict | None:
    """One stack-v3 repo row -> one training text, or None if nothing survives."""
    if not isinstance(rec, dict):
        return None
    files = rec.get("files")
    if not isinstance(files, list):
        return None
    repo = str(rec.get("repo_path") or "").strip()
    kept, dropped = [], 0
    for f in files:
        ok, _reason = keep_file(f)
        if not ok:
            dropped += 1
            continue
        path = str(f.get("file_path") or "").strip()
        kept.append(
            f"# {path}\n{f['content'].rstrip()}" if path else f["content"].rstrip()
        )
    if not kept:
        return None
    header = f"# repository: {repo}\n" if repo else ""
    return {
        "text": header + "\n\n".join(kept),
        "_task_type": "automatic",
        # Provenance travels with the record: how many files were refused is part
        # of what this row IS, and a downstream reader should not have to guess.
        "_stackv3_files_kept": len(kept),
        "_stackv3_files_dropped": dropped,
    }
