"""
Era-honest normalization: per-season z-score (hoops 1996-2026), per-90 tournament-z (pitch),
per-ticker FY median-impute + z-score (equities), nflverse next-game.

No decorator math — every method recomputable from public source data.
"""
import math
def zscore_within_group(values, group_keys):
    # values: list[float], group_keys: list[str] (season id / tournament id / ticker)
    from collections import defaultdict
    groups = defaultdict(list)
    for k,v in zip(group_keys, values):
        groups[k].append(v)
    stats = {k: (sum(v)/len(v), math.sqrt(sum((x - sum(v)/len(v))**2 for x in v)/max(1,len(v)-1)) or 1.0) for k,v in groups.items()}
    return [(v - stats[k][0])/(stats[k][1] or 1.0) for k,v in zip(group_keys, values)]

def per90(x, minutes):
    return (x / (minutes or 1)) * 90 if minutes else 0.0
