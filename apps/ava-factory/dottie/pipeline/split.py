"""Deterministic, hash-stable train/val/test assignment.

The split must be a pure function of ``doc_id`` alone — no RNG, no counters, no
dependence on arrival order or shard boundaries. This is what makes the whole
pipeline reproducible and, more importantly, keeps val/test *clean across
reruns*: a doc always lands in the same split, so re-curating the corpus can
never silently move a held-out doc into train.

The bucket is derived from the first 32 bits of ``sha1(doc_id)`` scaled to
[0, 1), then placed by cumulative ratio in the fixed order train, val, test.
"""

from __future__ import annotations

import hashlib

#: Fixed placement order. Ratios are applied cumulatively in this order so the
#: same fraction always maps to the same split regardless of dict iteration.
SPLIT_ORDER = ("train", "val", "test")

_UINT32_MAX = 0xFFFFFFFF


def doc_fraction(doc_id: str) -> float:
    """Stable value in [0, 1) derived from ``doc_id`` via sha1's top 32 bits."""
    h = hashlib.sha1(doc_id.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / _UINT32_MAX


def assign_split(doc_id: str, ratios: dict[str, float]) -> str:
    """Assign ``doc_id`` to "train" | "val" | "test", deterministically.

    ``ratios`` maps split name -> fraction (need not sum to exactly 1; it is
    normalized over whatever of {train, val, test} are present). Placement is by
    cumulative ratio in :data:`SPLIT_ORDER`. The last split in order is the
    catch-all so floating-point drift can never leave a doc unassigned.
    """
    present = [(s, float(ratios[s])) for s in SPLIT_ORDER if s in ratios and ratios[s] > 0]
    if not present:
        raise ValueError(f"no positive split ratios in {ratios!r}")
    total = sum(w for _, w in present)
    frac = doc_fraction(doc_id)
    cumulative = 0.0
    for i, (split, w) in enumerate(present):
        cumulative += w / total
        # Last split is the catch-all: guards against frac == the final boundary
        # due to floating-point rounding.
        if frac < cumulative or i == len(present) - 1:
            return split
    return present[-1][0]  # unreachable
