"""Locate Spec-06 harness artifacts for the /evals dashboard.

Harness runs write ``reports/eval_{preset}_base.{json,md}`` (and optionally a
nano-vs-mini compare MD). The compose ``ava_reports`` volume historically held
only a nano smoke ``branch_eval_results_real.json``, so the live /evals page
never saw mini. Resolution order prefers the current ``AVA_PRESET`` rung, then
named mini/nano artifacts, then the legacy filenames — searching both the
reports volume and an optional host bind at ``/host_reports``.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


def report_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("AVA_HOST_REPORTS_DIR", "AVA_REPORTS_DIR"):
        raw = os.environ.get(key)
        if raw:
            p = Path(raw)
            if p.is_dir() and p not in roots:
                roots.append(p)
    # Bare-metal / tests: repo-local reports/
    fallback = Path(__file__).resolve().parent.parent / "reports"
    if fallback.is_dir() and fallback not in roots:
        roots.append(fallback)
    return roots


def _first_existing(
    names: list[str], *, roots: list[Path] | None = None
) -> Path | None:
    for root in roots or report_roots():
        for name in names:
            path = root / name
            if path.is_file():
                return path
    return None


def resolve_eval_json(
    *, preset: str | None = None, source: str | None = None
) -> Path | None:
    """Pick the JSON artifact to serve on ``/jspace/eval_branch``.

    ``source`` may be a stem (``eval_mini_base``), a filename, or ``legacy``.
    """
    preset = (preset or os.environ.get("AVA_PRESET") or "").strip()
    if source:
        src = source.strip()
        if src in ("legacy", "branch_eval_results_real"):
            return _first_existing(["branch_eval_results_real.json"])
        name = src if src.endswith(".json") else f"{src}.json"
        return _first_existing([name])

    names: list[str] = []
    if preset:
        names.append(f"eval_{preset}_base.json")
    # Prefer the scale-ladder rung currently shipping results.
    for stem in ("eval_mini_base", "eval_nano_base"):
        names.append(f"{stem}.json")
    names.append("branch_eval_results_real.json")
    return _first_existing(_dedupe(names))


def resolve_eval_md(
    *, preset: str | None = None, source: str | None = None
) -> Path | None:
    preset = (preset or os.environ.get("AVA_PRESET") or "").strip()
    if source:
        src = source.strip()
        if src in ("legacy", "REPORT_REAL"):
            return _first_existing(["REPORT_REAL.md"])
        name = src if src.endswith(".md") else f"{src}.md"
        return _first_existing([name])

    names: list[str] = []
    if preset:
        names.append(f"eval_{preset}_base.md")
    for stem in ("eval_mini_base", "eval_nano_base"):
        names.append(f"{stem}.md")
    names.append("REPORT_REAL.md")
    return _first_existing(_dedupe(names))


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_compare_md() -> Path | None:
    return _first_existing(
        [
            "eval_nano_vs_mini_2026-07-18.md",
            "eval_nano_vs_mini.md",
        ]
    )


def list_eval_jsons() -> list[dict[str, Any]]:
    found: dict[str, Path] = {}
    for root in report_roots():
        for path in sorted(root.glob("eval_*_base.json")) + sorted(
            root.glob("branch_eval_results_real.json")
        ):
            found.setdefault(path.name, path)
    out: list[dict[str, Any]] = []
    for name, path in found.items():
        meta: dict[str, Any] = {}
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            meta = blob.get("meta") or {}
        except Exception:
            pass
        out.append(
            {
                "name": name,
                "stem": path.stem,
                "path": str(path),
                "preset": meta.get("preset"),
                "base_ckpt": meta.get("base_ckpt"),
                "wall_s": meta.get("wall_s"),
            }
        )
    return out


def sanitize_jsonable(obj: Any) -> Any:
    """Replace NaN/Inf so ``json.dumps(..., allow_nan=False)`` succeeds."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_jsonable(v) for v in obj]
    return obj


def load_eval_json(path: Path) -> dict[str, Any]:
    """Load harness JSON; coerce NaN/Inf (non-standard JSON) to null."""
    text = path.read_text(encoding="utf-8")
    try:
        blob = json.loads(text)
    except json.JSONDecodeError:
        scrubbed = (
            text.replace(": NaN", ": null")
            .replace(": Infinity", ": null")
            .replace(": -Infinity", ": null")
        )
        blob = json.loads(scrubbed)
    # CPython's json.loads accepts NaN/Infinity by default; normalize for API.
    return sanitize_jsonable(blob)
