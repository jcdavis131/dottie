"""Provenance tiers: where a trace row came from, and what it may be used for.

Every route and outcome line carries ``provenance`` (one of :data:`TIERS`).
The router pack reads it to decide what a row may do:

=====================  ======  ============================================
tier                   weight  may
=====================  ======  ============================================
``production``         1.0     train; the primary gate holdout
``benchmark-verified`` 0.7     train candidates; only a disjoint, deduped
                               benchmark holdout in eval (never the primary)
``outcome-real``       --      recognised (recorded futures, the separate
                               Atlas track); never a router label
``teacher``            --      never trains a champion, never in gate eval
``synthetic``          --      never trains a champion, never in gate eval
=====================  ======  ============================================

A production row is real use observed by real executors. A
benchmark-verified row is a curated goal run through real executors whose
outcome an automatic verifier checked (``scout router probe``). Pre-provenance
trace lines have no ``provenance`` key; their ``source: production`` means
production.

Dedupe and decontamination key on :func:`goal_norm_sha256`, the hash of the
normalised goal (case, whitespace and punctuation folded), so a goal that is
reworded only in spacing or capitalisation cannot sit on both sides of a split.
Stdlib only.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

PRODUCTION = "production"
BENCHMARK = "benchmark-verified"
OUTCOME_REAL = "outcome-real"
TEACHER = "teacher"
SYNTHETIC = "synthetic"
TIERS = (PRODUCTION, BENCHMARK, OUTCOME_REAL, TEACHER, SYNTHETIC)

#: Loss weight per row when training. Tiers absent here never train.
WEIGHTS: dict[str, float] = {PRODUCTION: 1.0, BENCHMARK: 0.7}
#: Tiers a router pack may train on.
TRAINABLE = frozenset(WEIGHTS)
#: Tiers that may appear in a gate eval set (each in its own holdout).
EVALUABLE = frozenset({PRODUCTION, BENCHMARK})
#: Production rows a pack must hold before any gate can pass (``--min-production-rows``).
MIN_PRODUCTION_ROWS = 50

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_goal(text: str) -> str:
    """Case-, whitespace- and punctuation-folded goal text (NFKC first)."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = _PUNCT.sub(" ", t)
    return _SPACE.sub(" ", t).strip()


def goal_norm_sha256(text: str) -> str:
    """sha256 of :func:`normalize_goal`; the dedupe / decontamination key."""
    return hashlib.sha256(normalize_goal(text).encode("utf-8")).hexdigest()


def row_provenance(row: dict[str, Any]) -> str:
    """The provenance tier of a trace line. Unknown values come back as-is, so callers refuse them."""
    prov = row.get("provenance")
    if isinstance(prov, str) and prov:
        return prov
    # pre-provenance lines: source production meant real use; anything else is not trainable
    return PRODUCTION if row.get("source") == PRODUCTION else str(row.get("source") or "unknown")


def check_tier(value: str) -> str:
    """Return ``value`` when it is a known tier, else raise ValueError."""
    if value not in TIERS:
        raise ValueError(f"unknown provenance {value!r}; one of {list(TIERS)}")
    return value


def norm_key(row: dict[str, Any]) -> str | None:
    """The normalised-goal key of a joined trace row: ``goal_norm_sha256`` when recorded.

    Older lines carry only the raw ``goal_sha256``; that is the fallback key
    (exact-text dedupe only), never ``None`` when either hash exists.
    """
    feats = row.get("features") or {}
    v = feats.get("goal_norm_sha256") or row.get("goal_norm_sha256")
    if v:
        return str(v)
    if row.get("goal_text"):
        return goal_norm_sha256(str(row["goal_text"]))
    v = row.get("goal_sha256") or feats.get("goal_sha256")
    return str(v) if v else None


def eval_set_hashes(texts: list[str]) -> set[str]:
    """Normalised hashes of an external eval set's goal texts (for decontamination)."""
    return {goal_norm_sha256(t) for t in texts if t and t.strip()}
