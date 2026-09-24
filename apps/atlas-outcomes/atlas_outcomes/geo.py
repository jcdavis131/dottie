"""Point-in-polygon for warning polygons (lon/lat, even-odd rule, holes honoured)."""

from __future__ import annotations

Ring = list[list[float]]
Polygon = list[Ring]


def ring_contains(ring: Ring, x: float, y: float) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygons_bbox(polys: list[Polygon]) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def polygons_contain(polys: list[Polygon], lon: float, lat: float) -> bool:
    for poly in polys:
        if poly and ring_contains(poly[0], lon, lat) and not any(ring_contains(h, lon, lat) for h in poly[1:]):
            return True
    return False
