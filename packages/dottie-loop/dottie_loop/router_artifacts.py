"""Promotion stamps: the human half of "authoritative".

A learned router answer (orchestrator MLP or System One) is authoritative
only when ALL hold:

1. its artifact says ``gate_passed: true`` (computed by ``scout router eval``
   through :func:`dottie_loop.evaluation.promotion_decision`);
2. a human spot-checked its training labels: ``scout router spotcheck``
   samples N labels (default 20) into ``<artifact>.spotcheck.json`` beside
   the artifact, the human marks each ``ok`` or ``bad``, and at most
   :data:`SPOTCHECK_MAX_BAD` of them may be bad; and
3. a human ran ``scout router promote --i-have-reviewed <artifact>``, which
   refuses without (2) and writes a stamp here keyed by the artifact's
   identity hash.

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
SPOTCHECK_SCHEMA = "dottie-router-spotcheck-1"
SPOTCHECK_N = 20
#: Largest share of spot-checked labels a human may mark bad before promotion is refused.
SPOTCHECK_MAX_BAD = 0.10
MARKS = ("ok", "bad")


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
    spot = check_spotcheck(artifact, identity)
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
        "spotcheck": {"path": str(spotcheck_path(artifact)), "reviewer": spot["reviewer"], "n": len(spot["items"]),
                      "bad": sum(1 for it in spot["items"] if it["mark"] == "bad")},
    }
    out = stamp_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{identity}.json").write_text(json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stamp


# --- the human spot-check -----------------------------------------------------------------


def spotcheck_path(artifact: Path) -> Path:
    """``<artifact>.spotcheck.json`` beside the artifact (outside a checkpoint dir, so its identity is unchanged)."""
    artifact = Path(artifact)
    return artifact.with_name(artifact.name + ".spotcheck.json")


def spotcheck_sample(pack_dir: Path, artifact: Path, *, n: int = SPOTCHECK_N, seed: int = 0) -> dict[str, Any]:
    """Sample ``n`` labelled rows of the pack into an unmarked spot-check sheet beside ``artifact``."""
    import random

    pack_dir = Path(pack_dir)
    metas = {}
    recs = []
    try:
        for line in (pack_dir / "provenance.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = json.loads(line)
                metas[m["id"]] = m
        for name in ("train.jsonl", "holdout.jsonl", "holdout_benchmark.jsonl"):
            p = pack_dir / name
            if p.is_file():
                recs += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError, KeyError) as exc:
        raise InvalidInputError(f"pack unreadable for a spot-check: {exc}", field="pack") from exc
    if n < 1 or not recs:
        raise InvalidInputError("nothing to spot-check (need n >= 1 and a non-empty pack)", field="n")
    picked = random.Random(seed).sample(recs, min(n, len(recs)))
    items = []
    for rec in picked:
        meta = metas.get(rec["id"], {})
        labels = rec.get("labels") or {}
        items.append({
            "id": rec["id"],
            "split": meta.get("split"),
            "provenance": meta.get("provenance"),
            "goal_text": rec["state"].get("goal_text") or meta.get("bench_text"),
            "goal_sha256": meta.get("goal_sha256"),
            "tier": (labels.get("tier") or {}).get("choice"),
            "action": (labels.get("action") or {}).get("choice"),
            "label_source": meta.get("label_source"),
            "heuristic_tier": meta.get("heuristic_tier"),
            "mark": None,
        })
    sheet = {
        "schema": SPOTCHECK_SCHEMA,
        "artifact": str(Path(artifact).resolve()),
        "artifact_sha256": artifact_identity(artifact),
        "pack": str(pack_dir.resolve()),
        "seed": seed,
        "items": items,
        "reviewer": None,
        "created_at": now_iso(),
        "marked_at": None,
        "instructions": "mark each item ok (the tier label is right for that goal) or bad; "
                        "then `scout router spotcheck --mark <id>=ok|bad ... --by <name>` or edit `mark` here",
    }
    _write_sheet(artifact, sheet)
    return sheet


def _write_sheet(artifact: Path, sheet: dict[str, Any]) -> None:
    spotcheck_path(artifact).write_text(json.dumps(sheet, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_spotcheck(artifact: Path) -> dict[str, Any]:
    path = spotcheck_path(artifact)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyDeniedError(f"no spot-check at {path}: run `scout router spotcheck` and mark it ({exc})",
                                field="spotcheck") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SPOTCHECK_SCHEMA or not isinstance(doc.get("items"), list):
        raise PolicyDeniedError(f"{path} is not a {SPOTCHECK_SCHEMA} sheet", field="spotcheck")
    return doc


def spotcheck_mark(artifact: Path, marks: dict[str, str], *, reviewer: str) -> dict[str, Any]:
    """Record a human's ok/bad marks on the sheet. Unknown ids or marks are refused."""
    if not reviewer.strip():
        raise InvalidInputError("reviewer must be named", field="reviewer")
    sheet = load_spotcheck(artifact)
    ids = {it["id"] for it in sheet["items"]}
    bad = sorted(set(marks) - ids)
    if bad:
        raise InvalidInputError(f"not on the sheet: {bad[:5]}", field="marks")
    wrong = sorted(v for v in marks.values() if v not in MARKS)
    if wrong:
        raise InvalidInputError(f"marks must be one of {MARKS}; got {wrong[:5]}", field="marks")
    for it in sheet["items"]:
        if it["id"] in marks:
            it["mark"] = marks[it["id"]]
    sheet["reviewer"] = reviewer.strip()
    sheet["marked_at"] = now_iso()
    _write_sheet(artifact, sheet)
    return sheet


def check_spotcheck(artifact: Path, identity: str) -> dict[str, Any]:
    """The marked sheet for these exact bytes, or PolicyDeniedError saying what is missing."""
    sheet = load_spotcheck(artifact)
    if sheet.get("artifact_sha256") != identity:
        raise PolicyDeniedError("the spot-check names different artifact bytes; sample and mark it again",
                                field="spotcheck")
    items = sheet["items"]
    unmarked = [it["id"] for it in items if it.get("mark") not in MARKS]
    if not items or unmarked:
        raise PolicyDeniedError(f"spot-check incomplete: {len(unmarked)} of {len(items)} labels unmarked",
                                field="spotcheck")
    if not str(sheet.get("reviewer") or "").strip():
        raise PolicyDeniedError("spot-check has no named reviewer", field="spotcheck")
    n_bad = sum(1 for it in items if it["mark"] == "bad")
    if n_bad > SPOTCHECK_MAX_BAD * len(items):
        raise PolicyDeniedError(f"spot-check found {n_bad}/{len(items)} bad labels (> {SPOTCHECK_MAX_BAD:.0%}); "
                                "fix the labels and re-pack", field="spotcheck")
    return sheet
