"""Map geometry for pages that draw shapes from the model.

The page side is `GovMap.islands` + `GovMap.ring` in
frontend/scripts/gov-map.js; the two ends share this format:

  - coordinates are integers in 1/`scale` degrees (SCALE = 1e5, ~1 m);
  - a ring is a flat list [dx0, dy0, dx1, dy1, ...] of deltas, x = lon and
    y = lat, where the first delta is from the map's `origin` (an integer
    [x, y] the recipe puts in the model next to `scale`) and each next one
    from the previous point. Every ring restarts from the origin, so rings
    decode independently;
  - feature lists go to the page as JSON islands,
    `<script type="application/json" id="<prefix>-<n>">{{ chunk | tojson }}</script>`,
    one per chunk from `pack`, so no <script> block passes check.py's
    INLINE-DATA cap.

Map inputs (`map: true` in recipe.json) are already WGS84 [lon, lat] when
compute() sees them (geo_snapshot.py reprojects ITM), so nothing here
converts projections.
"""
import json
import math

SCALE = 100_000
EARTH_RADIUS_KM = 6371.0088          # IUGG mean radius
# check.py's INLINE-DATA cap is 51,200 characters per <script> block.
# The default leaves room for the island's own markup and a margin.
ISLAND_BUDGET = 45_000


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def quantize(points, scale: int = SCALE) -> list:
    """[(lon, lat), ...] floats → [(x, y), ...] integers, dropping a point
    equal to the one before it."""
    out = []
    for lon, lat in points:
        p = (int(round(float(lon) * scale)), int(round(float(lat) * scale)))
        if not out or p != out[-1]:
            out.append(p)
    return out


def _seg_dist(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points: list, tol: float, *, ring: bool = True) -> list:
    """Douglas-Peucker, distance to the segment, `tol` in the points' own
    units (1 unit of a quantized point is 1e-5°, ~1.1 m north-south). Keeps
    the first and last point. A ring that would drop below 4 points (a line
    below 2) comes back unsimplified."""
    floor = 4 if ring else 2
    if tol <= 0 or len(points) <= floor:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = _seg_dist(points[k], points[i], points[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    out = [p for p, k in zip(points, keep) if k]
    return out if len(out) >= floor else list(points)


def origin(lons, lats, scale: int = SCALE) -> list:
    """An integer origin at the south-west corner of the points, for
    `encode`. Small deltas from it keep the islands short."""
    return [int(math.floor(min(lons) * scale)), int(math.floor(min(lats) * scale))]


def encode(rings, origin_xy, *, scale: int = SCALE, tol: float = 0.0, ring: bool = True) -> list:
    """Rings (or lines) of (lon, lat) floats → flat integer delta lists
    from `origin_xy`, quantized and simplified by `tol` (see `simplify`)."""
    ox, oy = origin_xy
    out = []
    for r in rings:
        flat, px, py = [], ox, oy
        for x, y in simplify(quantize(r, scale), tol, ring=ring):
            flat += [x - px, y - py]
            px, py = x, y
        out.append(flat)
    return out


def rendered_len(obj) -> int:
    """Characters `obj` takes once a template writes it with `| tojson`
    (recipe.py's json.dumps policy plus Jinja's htmlsafe escapes)."""
    s = json.dumps(obj, ensure_ascii=False, sort_keys=False)
    return len(s) + 5 * sum(s.count(c) for c in "<>&'")


def pack(items: list, budget: int = ISLAND_BUDGET) -> list:
    """Split `items` into consecutive chunks whose rendered JSON arrays stay
    within `budget` characters. An item too large for any chunk raises:
    simplify harder or drop it, the page can't carry it."""
    chunks, cur, size = [], [], 2          # "[" + "]"
    for it in items:
        n = rendered_len(it)
        if n + 2 > budget:
            raise ValueError(f"map item renders to {n} chars, over the {budget} island budget")
        extra = n + (2 if cur else 0)      # ", " between items
        if cur and size + extra > budget:
            chunks.append(cur)
            cur, size, extra = [], 2, n
        cur.append(it)
        size += extra
    if cur:
        chunks.append(cur)
    return chunks
