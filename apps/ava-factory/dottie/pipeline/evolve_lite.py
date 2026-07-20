"""DataEvolve-lite + BLISS-lite helpers for the demand channel.

Full DataEvolve evolves curation strategies across generations. Full BLISS is a
bilevel mixture optimizer. These lite helpers give Ava a closed-loop toehold:

* ``evolve_shard_score`` — quality × yield × deficit pressure for a packed shard
* ``apply_evolve_boosts`` — map top-scoring sources into ``boost_task_types``
* ``bliss_lite_effort_nudge`` — tilt phase effort toward largest deficits when
  lm_trend is rising (proxy for dynamic mixture preference)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def evolve_shard_score(
    *,
    docs_kept: int,
    docs_read: int,
    tokens: int,
    phase_deficit: int = 0,
) -> float:
    """Higher is better. Rejected/empty shards score near zero."""
    if docs_read <= 0 or tokens <= 0:
        return 0.0
    yield_ratio = docs_kept / float(docs_read)
    pressure = 1.0 + max(0, phase_deficit) / 1e8
    return float(yield_ratio * math.log1p(tokens) * pressure)


def apply_evolve_boosts(
    base_boosts: Mapping[str, float],
    *,
    source_scores: Mapping[str, float],
    top_k: int = 3,
    boost: float = 1.25,
) -> dict[str, float]:
    """Upweight high-scoring sources as task-type-ish boost keys.

    Collectors that understand ``boost_task_types`` already; we reuse that map
    with source names as keys so ``apply_demand_weights`` can prefer them when
    wired. Unknown keys are harmless no-ops for collectors that only look at
    automatic/deliberate/safety/temporal.
    """
    out = dict(base_boosts)
    ranked = sorted(source_scores.items(), key=lambda kv: kv[1], reverse=True)
    for name, score in ranked[:top_k]:
        if score <= 0:
            continue
        out[name] = max(float(out.get(name, 1.0)), boost)
    return out


def bliss_lite_effort_nudge(
    efforts: Sequence[float],
    deficits: Sequence[int],
    *,
    lm_trend: float | None,
    strength: float = 0.35,
) -> list[float]:
    """Concentrate effort on the largest-deficit phase when lm_loss is rising.

    When lm_trend is None or ≤0, returns efforts unchanged (maintain mixture).
    Effort is often already deficit-proportional; sharpening the peak is the
    remaining degree of freedom.
    """
    if not efforts or lm_trend is None or lm_trend <= 0:
        return list(efforts)
    n = min(len(efforts), len(deficits))
    out = [float(efforts[i]) for i in range(n)]
    i_max = max(range(n), key=lambda i: int(deficits[i]))
    # Steal ``strength`` mass from others into the neediest phase.
    steal = 0.0
    for i in range(n):
        if i == i_max:
            continue
        take = out[i] * strength
        out[i] -= take
        steal += take
    out[i_max] += steal
    s = sum(out) or 1.0
    return [round(x / s, 4) for x in out]
