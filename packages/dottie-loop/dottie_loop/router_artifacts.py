"""Promotion stamps: the human half of "authoritative".

A learned router answer (orchestrator MLP or System One) is authoritative
only when BOTH hold:

1. its artifact says ``gate_passed: true`` (computed by ``scout router eval``
   through :func:`dottie_loop.evaluation.promotion_decision`), and
2. a human ran ``scout router promote --i-have-reviewed <artifact>``, which
   writes a stamp here keyed by the artifact's identity hash.

Nothing in this module or anywhere else writes a stamp on its own; there is no
auto-promotion path. A stamp names the exact bytes that were reviewed, so a
retrained checkpoint at the same path is NOT stamped until someone reviews it.

Store: ``~/.dottie/router/stamps/<sha256>.json`` (``DOTTIE_ROUTER_STAMPS``
overrides). Local and gitignored by living outside the repo.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.hashing import now_iso

EVAL_SUMMARY = "eval_summary.json"


def stamp_dir() -> Path:
    env = os.environ.get("DOTTIE_ROUTER_STAMPS")
    return Path(env) if env else Path.home() / ".dottie" / "router" / "stamps"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_identity(path: Path) -> str:
    """sha256 naming an artifact's bytes.

    A file (the MLP's weights JSON) hashes as itself. A directory (a System One
    checkpoint) hashes with ``apps/jev-v0/decision_io.checkpoint_identity``,
    the same function ``serve_decide.py --checkpoint`` reports in ``/health``,
    so a served checkpoint and its stamp always agree.
    """
    path = Path(path)
    if path.is_file():
        return _file_sha256(path)
    if not path.is_dir():
        raise InvalidInputError(f"artifact not found: {path}", field="artifact")
    from dottie_loop.jev import load_decision_io

    io = load_decision_io()
    try:
        return io.checkpoint_identity(path)
    except io.SchemaError as exc:
        raise InvalidInputError(str(exc), field="artifact") from exc


def read_stamp(identity: str | None) -> dict[str, Any] | None:
    """The stamp for an artifact identity, or None. Malformed stamps count as absent."""
    if not identity or not all(c in "0123456789abcdef" for c in identity) or len(identity) != 64:
        return None
    path = stamp_dir() / f"{identity}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("artifact_sha256") != identity or doc.get("reviewed") is not True or doc.get("gate_passed") is not True:
        return None
    return doc


def is_authoritative(answer: dict[str, Any]) -> bool:
    """True only for gate_passed AND a valid human stamp on the same artifact bytes."""
    if not answer.get("available") or answer.get("tier") is None:
        return False
    if answer.get("gate_passed") is not True:
        return False
    return read_stamp(answer.get("artifact_sha256")) is not None


def load_eval_summary(artifact: Path) -> dict[str, Any]:
    """The eval summary beside (file artifact) or inside (directory artifact) an artifact."""
    artifact = Path(artifact)
    path = artifact / EVAL_SUMMARY if artifact.is_dir() else artifact.with_name(EVAL_SUMMARY)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidInputError(f"no readable {EVAL_SUMMARY} for {artifact}: {exc}", field="artifact") from exc
    if not isinstance(doc, dict):
        raise InvalidInputError(f"{path} is not a JSON object", field="artifact")
    return doc


def write_stamp(artifact: Path, *, reviewed: bool, reviewer: str, note: str = "") -> dict[str, Any]:
    """Record a human review. Refuses unless reviewed, gate_passed and the bytes match the eval."""
    if not reviewed:
        raise PolicyDeniedError("promotion needs an explicit --i-have-reviewed", field="reviewed")
    if not reviewer.strip():
        raise InvalidInputError("reviewer must be named", field="reviewer")
    summary = load_eval_summary(artifact)
    if summary.get("gate_passed") is not True:
        raise PolicyDeniedError(
            f"eval_summary.json says gate_passed={summary.get('gate_passed')!r}; only a passed gate can be stamped",
            field="gate_passed",
        )
    identity = artifact_identity(artifact)
    if summary.get("artifact_sha256") != identity:
        raise PolicyDeniedError(
            "the artifact bytes changed since eval (eval names "
            f"{summary.get('artifact_sha256')!r}, artifact is {identity}); re-run the eval",
            field="artifact_sha256",
        )
    stamp = {
        "artifact": str(Path(artifact).resolve()),
        "artifact_sha256": identity,
        "eval_summary_sha256": hashlib.sha256(json.dumps(summary, sort_keys=True).encode("utf-8")).hexdigest(),
        "gate_passed": True,
        "reviewed": True,
        "reviewer": reviewer.strip(),
        "note": note,
        "stamped_at": now_iso(),
        "promotion": summary.get("promotion"),
    }
    out = stamp_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{identity}.json").write_text(json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stamp
