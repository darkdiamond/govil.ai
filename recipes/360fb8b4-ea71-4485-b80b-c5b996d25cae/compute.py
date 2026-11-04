"""CVFR flight routes (נתיבי טיסה): the national network of VFR corridors.

The only geometry is the uploaded shapefile (a `map: true` input). Today it
holds ONE feature: a single polygon whose outer ring is the envelope of the
whole network and whose 84 inner rings (holes) are the airspace cells the
corridors enclose. The corridors themselves are the polygon's area.

Everything is measured from the geometry (WGS84 from the refresh):

- areas on the sinusoidal (equal-area) projection, shoelace per ring, holes
  subtracted; it agrees with the layer's own ITM Shape_Area within 0.1%;
- the corridor area per latitude band by clipping every ring to the band
  (Sutherland-Hodgman against two parallels, valid for concave rings);
- the boundary length by haversine; an average corridor width estimate as
  2 x area / boundary (a buffered line of width w and length L has area ~wL
  and boundary ~2L).

Growth: several features or a MultiPolygon are summed polygon by polygon
(overlapping features would be counted twice; the layer has never had any).
A layer of lines or points has no corridor area and fails the refresh, so a
human looks at the new shape.
"""
import itertools
import json
import math

import pandas as pd
from govlib import fmt, geo

R_KM = 6371.0088
BAND_DEG = 0.25              # latitude band height (~28 km)
MAX_BANDS = 20               # wider bands if the network ever spans more
TOP_CELLS = 10
CELL_EDGES = [10, 50, 200, 1000]   # km², cell-size buckets
ENC_TOL = 1.5                # geo.encode tolerance (~1.5 m)

# Reference places for band labels (fixed geography, not data): a band is
# named after the places whose latitude falls inside it.
PLACES = [
    ("אילת", 29.557), ("יטבתה", 29.897), ("מצפה רמון", 30.610),
    ("ירוחם", 30.988), ("דימונה", 31.069), ("באר שבע", 31.252),
    ("קריית גת", 31.610), ("ירושלים", 31.778), ("אשדוד", 31.804),
    ("תל אביב", 32.085), ("נתניה", 32.329), ("חדרה", 32.437),
    ("עפולה", 32.608), ("חיפה", 32.794), ("טבריה", 32.795),
    ("נהריה", 33.008), ("קריית שמונה", 33.208),
]
SOUTH_REF = ("באר שבע", 31.252)


def _xy(lon, lat):
    """Sinusoidal projection, km: equal-area, so the shoelace gives km²."""
    return (R_KM * math.radians(lon) * math.cos(math.radians(lat)), R_KM * math.radians(lat))


def _area(ring):
    if len(ring) < 3:
        return 0.0
    pts = [_xy(x, y) for x, y in ring]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _centroid_lat(ring):
    pts = [_xy(x, y) for x, y in ring]
    a = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cy += (y1 + y2) * c
    if a == 0:
        return sum(y for _, y in ring) / len(ring)
    return math.degrees(cy / (3 * a) / R_KM)


def _clip(ring, lat, keep_above):
    """Sutherland-Hodgman against one parallel."""
    out = []
    n = len(ring)
    for i in range(n):
        p, q = ring[i], ring[(i + 1) % n]
        pin = p[1] >= lat if keep_above else p[1] <= lat
        qin = q[1] >= lat if keep_above else q[1] <= lat
        if pin:
            out.append(p)
        if pin != qin:
            t = (lat - p[1]) / (q[1] - p[1])
            out.append((p[0] + t * (q[0] - p[0]), lat))
    return out


def _band_area(ring, lo, hi):
    r = _clip(ring, lo, True)
    if len(r) >= 3:
        r = _clip(r, hi, False)
    return _area(r) if len(r) >= 3 else 0.0


def _ring_len(ring):
    return sum(geo.haversine_km(a[1], a[0], b[1], b[0]) for a, b in itertools.pairwise(ring))


def _open(ring):
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _polygons(df):
    """[(outer, [holes...]), ...] over every feature, in a total order."""
    polys = []
    for raw in df["__geometry"].tolist():
        try:
            g = json.loads(raw or "null")
        except ValueError:
            continue
        if not isinstance(g, dict):
            continue
        if g.get("type") == "Polygon":
            parts = [g.get("coordinates") or []]
        elif g.get("type") == "MultiPolygon":
            parts = g.get("coordinates") or []
        else:
            continue
        for rings in parts:
            rings = [_open(r) for r in rings if len(r) >= 4]
            if rings:
                polys.append((rings[0], rings[1:]))
    polys.sort(key=lambda p: (min(y for _, y in p[0]), min(x for x, _ in p[0]), len(p[0]), len(p[1])))
    return polys


def _yearmonth(df):
    vals = pd.to_numeric(df.get("YEARMONTH", pd.Series(dtype=str)), errors="coerce").dropna()
    vals = [int(v) for v in vals if 190001 <= v <= 299912 and 1 <= int(v) % 100 <= 12]
    return max(vals) if vals else None


def _band_label(lo, hi):
    names = [n for n, lat in PLACES if lo <= lat < hi]
    rng = f"{lo:.2f}°-{hi:.2f}°"
    return f"{rng} (בגובה {fmt.join_he(names)})" if names else rng


def _num(v, d=0):
    return f"{v:,.{d}f}"


# ── insights ─────────────────────────────────────────────────────────────


def insight_size(area, boundary, ns_km, lat0, lat1):
    return (f"מסדרונות הטיסה משתרעים על {_num(area)} קמ״ר, וקו המתאר שלהם (כולל שולי התאים הסגורים) "
            f"באורך {_num(boundary)} ק״מ. הרשת נמתחת לאורך כ-{_num(ns_km)} ק״מ מצפון לדרום, "
            f"מקו רוחב {lat0:.2f}° עד {lat1:.2f}°.")


def insight_width(area, boundary):
    if boundary <= 0 or area <= 0:
        return None
    w = 2 * area / boundary
    return (f"רוחב ממוצע משוער של מסדרון: כ-{w:.1f} ק״מ (פעמיים השטח חלקי קו המתאר), "
            f"כלומר כ-{_num(boundary / 2)} ק״מ של נתיבים.")


def insight_band(bands, area):
    ranked = sorted(bands, key=lambda b: (-b["area"], b["lo"]))
    if len(ranked) < 2 or area <= 0 or ranked[0]["area"] <= ranked[1]["area"] * 1.1:
        return None
    b = ranked[0]
    return (f"הרצועה עם שטח המסדרונות הגדול ביותר היא {b['label']}: {_num(b['area'])} קמ״ר, "
            f"{fmt.pct(b['area'] / area)} משטח הרשת כולה.")


def insight_south(polys, area):
    name, lat = SOUTH_REF
    south = sum(_band_area(o, -90, lat) - sum(_band_area(h, -90, lat) for h in hs) for o, hs in polys)
    share = south / area if area > 0 else 0
    if not 0.02 <= share <= 0.98:
        return None
    return (f"{fmt.pct(share)} משטח המסדרונות ({_num(south)} קמ״ר) נמצא דרומית לקו הרוחב של {name}, "
            f"ו-{fmt.pct(1 - share)} צפונית לו.")


def insight_envelope(envelope, area):
    if envelope <= 0 or area <= 0 or area >= envelope:
        return None
    return (f"בתוך המעטפת החיצונית של הרשת ({_num(envelope)} קמ״ר) המסדרונות עצמם תופסים "
            f"{fmt.pct(area / envelope)}; השאר הוא תאים סגורים בין הנתיבים.")


def insight_cells(cells, small_edge):
    if len(cells) < 3:
        return None
    small = [c for c in cells if c["area"] < small_edge]
    big = max(cells, key=lambda c: (c["area"], -c["lat"]))
    if not small:
        return None
    return (f"הנתיבים סוגרים ביניהם {len(cells):,} תאים. {len(small):,} מהם קטנים מ-{small_edge:,} קמ״ר, "
            f"והגדול ביותר ({_num(big['area'])} קמ״ר) נמצא ברצועה {big['band']}.")


def insight_mesh(bands):
    """The band where the mesh is densest (most enclosed cells)."""
    ranked = sorted(bands, key=lambda b: (-b["cells"], b["lo"]))
    if len(ranked) < 2 or ranked[0]["cells"] < 3 or ranked[0]["cells"] < ranked[1]["cells"] * 1.3:
        return None
    b = ranked[0]
    total = sum(x["cells"] for x in bands)
    return (f"רשת הנתיבים צפופה במיוחד ברצועה {b['label']}: {b['cells']:,} מתוך {total:,} התאים "
            f"הסגורים ממוקמים בה, יותר מבכל רצועה אחרת.")


def compute(frames):
    df = frames["geo"]
    polys = _polygons(df)
    if not polys:
        raise ValueError("no polygon geometry in the map file")

    envelope = sum(_area(o) for o, _ in polys)
    area = sum(_area(o) - sum(_area(h) for h in hs) for o, hs in polys)
    if area <= 0:
        raise ValueError("the corridor polygons have no area")
    boundary = sum(_ring_len(r + r[:1]) for o, hs in polys for r in [o, *hs])

    lats = [y for o, _ in polys for _, y in o]
    lons = [x for o, _ in polys for x, _ in o]
    lat0, lat1 = min(lats), max(lats)
    mid_lon = (min(lons) + max(lons)) / 2
    ns_km = geo.haversine_km(lat0, mid_lon, lat1, mid_lon)
    mid_lat = (lat0 + lat1) / 2
    ew_km = geo.haversine_km(mid_lat, min(lons), mid_lat, max(lons))

    # ── latitude bands ──
    step = BAND_DEG
    while (math.ceil(lat1 / step) - math.floor(lat0 / step)) > MAX_BANDS:
        step *= 2
    b0, b1 = math.floor(lat0 / step), math.ceil(lat1 / step)
    bands = []
    for k in range(b0, b1):
        lo, hi = round(k * step, 4), round((k + 1) * step, 4)
        a = sum(_band_area(o, lo, hi) - sum(_band_area(h, lo, hi) for h in hs) for o, hs in polys)
        bands.append({"lo": lo, "hi": hi, "label": _band_label(lo, hi), "area": max(a, 0.0), "cells": 0,
                      "buckets": [0] * (len(CELL_EDGES) + 1)})

    def band_of(lat):
        i = min(max(math.floor(lat / step) - b0, 0), len(bands) - 1)
        return bands[i]

    # ── enclosed cells (holes) ──
    cells = []
    for pi, (_, hs) in enumerate(polys):
        for ri, h in enumerate(hs, 1):
            cells.append({"area": _area(h), "lat": _centroid_lat(h), "ring": h, "pi": pi, "ri": ri})
    cells.sort(key=lambda c: (-c["area"], c["lat"], c["pi"], c["ri"]))

    def bucket(a):
        for i, e in enumerate(CELL_EDGES):
            if a < e:
                return i
        return len(CELL_EDGES)

    for c in cells:
        b = band_of(c["lat"])
        c["band"] = b["label"]
        b["cells"] += 1
        b["buckets"][bucket(c["area"])] += 1

    bucket_labels = ([f"עד {CELL_EDGES[0]:,}"]
                     + [f"{a:,}-{b:,}" for a, b in itertools.pairwise(CELL_EDGES)]
                     + [f"מעל {CELL_EDGES[-1]:,}"])
    bucket_n = [0] * len(bucket_labels)
    bucket_a = [0.0] * len(bucket_labels)
    for c in cells:
        i = bucket(c["area"])
        bucket_n[i] += 1
        bucket_a[i] += c["area"]

    ym = _yearmonth(df)

    # ── map ──
    # [0, polygon, rings] draws a polygon (outer ring + holes); [1, polygon,
    # ring, km², band] attaches a cell popup to that polygon's hole `ring`.
    o = geo.origin(lons, lats)
    items = [[0, pi, geo.encode([outer + outer[:1], *[h + h[:1] for h in hs]], o, tol=ENC_TOL)]
             for pi, (outer, hs) in enumerate(polys)]
    items += [[1, c["pi"], c["ri"], _num(c["area"], 1), c["band"]] for c in cells]
    map_model = {
        "chunks": geo.pack(items),
        "meta": {"origin": o, "scale": geo.SCALE, "area": _num(area), "cells": f"{len(cells):,}",
                 "bounds": [[lat0, min(lons)], [lat1, max(lons)]]},
    }

    # ── charts (north on top) ──
    north_first = list(reversed(bands))
    chart_bands = {
        "labels": [b["label"] for b in north_first],
        "area": [round(b["area"], 1) for b in north_first],
        "cells": [b["cells"] for b in north_first],
    }
    chart_mesh = {
        "labels": [b["label"] for b in north_first],
        "buckets": bucket_labels,
        "series": [[b["buckets"][i] for b in north_first] for i in range(len(bucket_labels))],
    }
    chart_sizes = {"labels": bucket_labels, "n": bucket_n, "area": [round(a, 1) for a in bucket_a]}
    top = cells[:TOP_CELLS]
    chart_cells = {
        "labels": [f"תא {i}" for i in range(1, len(top) + 1)],
        "bands": [c["band"] for c in top],
        "area": [round(c["area"], 1) for c in top],
    }

    tables = {
        "bands": [[b["label"], _num(b["area"], 1), fmt.pct(b["area"] / area), f"{b['cells']:,}"] for b in north_first],
        "sizes": [[lbl, f"{n:,}", _num(a, 1)] for lbl, n, a in zip(bucket_labels, bucket_n, bucket_a)],
        "cells": [[f"תא {i}", _num(c["area"], 1), c["band"]] for i, c in enumerate(top, 1)],
        "mesh": [[b["label"], *[f"{b['buckets'][i]:,}" for i in range(len(bucket_labels))], f"{b['cells']:,}"]
                 for b in north_first if b["cells"]],
    }

    rules = [
        ("size", insight_size(area, boundary, ns_km, lat0, lat1)),
        ("width", insight_width(area, boundary)),
        ("band", insight_band(bands, area)),
        ("south", insight_south(polys, area)),
        ("envelope", insight_envelope(envelope, area)),
        ("cells", insight_cells(cells, CELL_EDGES[1])),
        ("mesh", insight_mesh(bands)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    width = 2 * area / boundary if boundary > 0 else 0
    kpis = {
        "area": {"value": round(area, 1), "display": _num(area), "tone": "brand"},
        "boundary": {"value": round(boundary, 1), "display": _num(boundary), "tone": "brand"},
        "ns": {"value": round(ns_km, 1), "display": _num(ns_km), "tone": "info"},
        "width": {"value": round(width, 2), "display": f"{width:.1f}", "tone": "info"},
        "cells": {"value": len(cells), "display": f"{len(cells):,}", "tone": "brand"},
    }
    if ym:
        kpis["updated"] = {"value": ym, "display": f"{ym % 100:02d}/{ym // 100}", "tone": "brand"}

    densest = max(bands, key=lambda b: (b["area"], -b["lo"]))
    updated_he = f"{fmt.MONTHS_HE[ym % 100 - 1]} {ym // 100}" if ym else ""
    labels = {
        "lede": (f"שכבת נתיבי הטיסה (CVFR) של רשות התעופה האזרחית: מסדרונות הטיסה לכלי טיס קלים בפריסה ארצית, "
                 f"{_num(area)} קמ״ר של מסדרונות לאורך {_num(ns_km)} ק״מ מצפון לדרום ועד {_num(ew_km)} ק״מ ממזרח "
                 f"למערב, הסוגרים ביניהם {len(cells):,} תאים."
                 + (f" השכבה נכונה ל{updated_he}." if ym else "")),
        "kpi_updated": "חודש עדכון השכבה",
        "map_note": ("המסדרונות בכחול; השטחים הבהירים ביניהם הם התאים הסגורים. לחיצה על מסדרון מציגה את "
                     "נתוני הרשת, ולחיצה על תא מציגה את שטחו ואת הרצועה שבה הוא נמצא."),
        "map_aria": f"מפת מסדרונות הטיסה, {_num(area)} קמ״ר ו-{len(cells):,} תאים סגורים",
        "bands_note": (f"שטח המסדרונות בכל רצועת רוחב של {step:g}° (כ-{_num(step * 111.2)} ק״מ), מצפון לדרום. "
                       f"הרצועה הגדולה: {densest['label']}, {_num(densest['area'])} קמ״ר."),
        "bands_aria": f"שטח המסדרונות בקמ״ר בכל אחת מ-{len(bands):,} רצועות הרוחב",
        "bands_cap": "שטח המסדרונות ומספר התאים הסגורים לפי רצועת רוחב",
        "mesh_note": ("כמה תאים סגורים יש בכל רצועה, לפי גודל התא (קמ״ר). תאים קטנים רבים פירושם רשת נתיבים "
                      "צפופה; תא משויך לרצועה שבה נמצא מרכזו."),
        "mesh_aria": f"{len(cells):,} התאים הסגורים לפי רצועת רוחב וגודל",
        "mesh_cap": "מספר התאים הסגורים לפי רצועת רוחב וגודל התא בקמ״ר",
        "sizes_note": (f"התפלגות {len(cells):,} התאים לפי גודל, ומה השטח הכולל שהם מכסים. "
                       f"{bucket_n[0] + bucket_n[1]:,} תאים קטנים מ-{CELL_EDGES[1]:,} קמ״ר."),
        "sizes_aria": "מספר התאים הסגורים לפי קבוצת גודל",
        "sizes_cap": "התאים הסגורים לפי גודל: מספר תאים ושטח כולל בקמ״ר",
        "cells_note": (f"{len(top):,} התאים הגדולים ביותר בין הנתיבים, והרצועה שבה נמצא מרכז כל אחד. "
                       "התא הגדול הוא השטח הרחב ביותר בלי מסדרון טיסה בתוכו."),
        "cells_aria": f"שטח {len(top):,} התאים הסגורים הגדולים בקמ״ר",
        "cells_cap": "התאים הסגורים הגדולים: שטח בקמ״ר ורצועת רוחב",
    }

    summary = (f"מפת נתיבי הטיסה (CVFR) של רשות התעופה האזרחית: {_num(area)} קמ״ר של מסדרונות טיסה "
               f"לאורך {_num(ns_km)} ק״מ מצפון לדרום, עם {len(cells):,} תאים סגורים ביניהם.")
    inside = [n for n, lat in sorted(PLACES, key=lambda p: p[1]) if lat0 <= lat <= lat1]
    seo = {
        "title": "מפת נתיבי טיסה CVFR בישראל | רשות התעופה האזרחית",
        "description": (f"מפה אינטראקטיבית של נתיבי הטיסה (CVFR) לכלי טיס קלים: {_num(area)} קמ״ר של מסדרונות "
                        f"לאורך {_num(ns_km)} ק״מ" + (f", מ{inside[0]} ועד {inside[-1]}." if len(inside) > 1 else ".")),
        "name": "נתיבי טיסה CVFR: מפת מסדרונות הטיסה בישראל",
        "alternate_names": ["נתיבי טיסה", "נתיבי CVFR", "מסדרונות טיסה", "נתיבי טיסה VFR"],
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ארצי",
            "seo": seo,
        },
        "kpis": kpis,
        "charts": {"map": map_model, "bands": chart_bands, "mesh": chart_mesh,
                   "sizes": chart_sizes, "cells": chart_cells},
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"cells": len(cells) > 0, "bands": len(bands) > 1},
    }
