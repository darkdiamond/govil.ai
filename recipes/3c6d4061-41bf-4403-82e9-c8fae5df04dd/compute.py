"""שכבת שטח השיפוט המוניציפלי: the City of Be'er Sheva's municipal
jurisdiction layer. Read from the uploaded WGS84 GeoJSON (a `map` input):
one row per polygon with its attributes (area code and name, committee
name, SHAPE_Leng perimeter and SHAPE_Area area in ITM metres, a recorded
centre point) plus `__geometry`, the boundary itself.

Today the layer is one polygon, the whole city, so the page is a fact card
plus the drawn boundary: area, perimeter, north-south and east-west extent,
how compact the boundary is, and two consistency checks of the published
attributes against the drawn geometry (area, centre point). Everything is
computed from the rows, so the wording follows if the layer is split into
several units (committees, annexed areas): totals, the largest unit and a
per-unit table switch on from the data.
"""
import itertools
import json
import math
import re

import pandas as pd

TABLE_CAP = 20
SUMMARY_MAX = 155
CHUNK_BYTES = 40_000     # each geometry island stays well under 50KB
CHUNK_POINTS = 1_500     # a longer ring is split into pieces of this many points
AREA_MATCH = 0.01        # drawn vs recorded area within 1% = "matches"
CENTER_MATCH_M = 100     # recorded centre within 100 m of the drawn centroid = "matches"
# Israel's bounding box (WGS84): geometry outside it is a bad row.
LAT_RANGE = (29.3, 33.5)
LON_RANGE = (34.2, 35.9)
# GRS80 ellipsoid (the datum of ITM): local radii for a planar projection
# that is accurate to well under 0.1% over a city.
A_AX = 6_378_137.0
E2 = 0.00669438002290


def _clean(s):
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()


def _num(v):
    x = pd.to_numeric(_clean(v).replace(",", ""), errors="coerce")
    return None if pd.isna(x) else float(x)


def _code(v):
    """'9000' / '9000.0' -> '9000'; anything else stays as published."""
    s = _clean(v)
    m = re.fullmatch(r"(\d+)(?:\.0+)?", s)
    return m.group(1) if m else s


def _km2(m2):
    return f"{m2 / 1e6:,.1f}"


def _km(m):
    return f"{m / 1000:,.1f}"


def _dunam(m2):
    return f"{m2 / 1000:,.0f}"


def _coord(v):
    return f"{v:.3f}°"


def _polygons(geom):
    """Polygon / MultiPolygon -> list of polygons, each a list of rings of
    [lon, lat] points (rings with fewer than 4 points dropped)."""
    if not isinstance(geom, dict):
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    polys = [c] if t == "Polygon" else c if t == "MultiPolygon" else []
    out = []
    for poly in polys:
        rings = [[[float(p[0]), float(p[1])] for p in r] for r in poly if len(r) >= 4]
        if rings:
            out.append(rings)
    return out


class _Proj:
    """Local planar projection (metres) around a reference latitude."""

    def __init__(self, lat0, lon0):
        phi = math.radians(lat0)
        w = 1 - E2 * math.sin(phi) ** 2
        self.my = A_AX * (1 - E2) / w ** 1.5            # meridional radius
        self.nx = A_AX / math.sqrt(w) * math.cos(phi)   # prime vertical × cos φ
        self.lat0, self.lon0 = lat0, lon0

    def xy(self, p):
        return (math.radians(p[0] - self.lon0) * self.nx,
                math.radians(p[1] - self.lat0) * self.my)

    def lonlat(self, x, y):
        return (self.lon0 + math.degrees(x / self.nx), self.lat0 + math.degrees(y / self.my))


def _ring_stats(xy):
    a = cx = cy = per = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(xy):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
        per += math.hypot(x2 - x1, y2 - y1)
    return a / 2, cx / 6, cy / 6, per


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def _measure(polys, proj):
    """Drawn area (outer rings minus holes), perimeter (every ring), area-
    weighted centroid, convex-hull area and longest chord, in metres."""
    area = cx = cy = per = 0.0
    pts = []
    for poly in polys:
        for k, ring in enumerate(poly):
            xy = [proj.xy(p) for p in ring]
            a, rx, ry, rp = _ring_stats(xy)
            sign = 1 if k == 0 else -1
            # Orientation-free: the outer ring adds, holes subtract.
            area += sign * abs(a)
            cx += sign * (rx if a >= 0 else -rx)
            cy += sign * (ry if a >= 0 else -ry)
            per += rp
            if k == 0:
                pts.extend(xy)
    hull = _hull(pts)
    hull_area = abs(_ring_stats(hull + hull[:1])[0]) if len(hull) >= 3 else 0.0
    chord = 0.0
    for i in range(len(hull)):
        for j in range(i + 1, len(hull)):
            chord = max(chord, math.hypot(hull[i][0] - hull[j][0], hull[i][1] - hull[j][1]))
    centroid = proj.lonlat(cx / area, cy / area) if area > 0 else None
    return {"area": area, "perim": per, "centroid": centroid,
            "hull_area": hull_area, "chord": chord}


def _inside(lon, lat, polys):
    """Even-odd point-in-polygon over every ring."""
    hit = False
    for poly in polys:
        for ring in poly:
            for (x1, y1), (x2, y2) in itertools.pairwise(ring):
                if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                    hit = not hit
    return hit


def _prepare(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            geom = json.loads(r.get("__geometry") or "null")
        except ValueError:
            geom = None
        polys = _polygons(geom)
        pts = [p for poly in polys for ring in poly for p in ring]
        if not pts:
            continue
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        if not (LAT_RANGE[0] <= min(lats) and max(lats) <= LAT_RANGE[1]
                and LON_RANGE[0] <= min(lons) and max(lons) <= LON_RANGE[1]):
            continue
        name, vaad = _clean(r.get("AREA_NAME")), _clean(r.get("VAAD_NAME"))
        rows.append({
            "code": _code(r.get("AREA_CODE")),
            "name": name,
            "vaad": vaad,
            "label": vaad or name or "ללא שם",
            "rec_area": _num(r.get("SHAPE_Area")),
            "rec_perim": _num(r.get("SHAPE_Leng")),
            "rec_lat": _num(r.get("lat")),
            "rec_lon": _num(r.get("lon")),
            "polys": polys,
            "bbox": (min(lats), min(lons), max(lats), max(lons)),
            "key": json.dumps(polys, separators=(",", ":")),
        })
    if not rows:
        return rows, None
    lat0 = (min(r["bbox"][0] for r in rows) + max(r["bbox"][2] for r in rows)) / 2
    lon0 = (min(r["bbox"][1] for r in rows) + max(r["bbox"][3] for r in rows)) / 2
    proj = _Proj(lat0, lon0)
    for r in rows:
        r.update(_measure(r["polys"], proj))
        # The layer's own area/perimeter (ITM metres) when they agree with the
        # drawn ones; a re-export in another unit falls back to the measured.
        ra, rp = r["rec_area"], r["rec_perim"]
        r["area_ok"] = bool(ra and r["area"] > 0 and 0.8 <= ra / r["area"] <= 1.25)
        r["perim_ok"] = bool(rp and r["perim"] > 0 and 0.8 <= rp / r["perim"] <= 1.25)
        r["a"] = ra if r["area_ok"] else r["area"]
        r["p"] = rp if r["perim_ok"] else r["perim"]
        lat, lon = r["rec_lat"], r["rec_lon"]
        r["center_rec"] = (lat is not None and lon is not None
                           and LAT_RANGE[0] <= lat <= LAT_RANGE[1]
                           and LON_RANGE[0] <= lon <= LON_RANGE[1])
        r["center"] = (lon, lat) if r["center_rec"] else r["centroid"]
    # Total order (verify shuffles the rows).
    rows.sort(key=lambda r: (-r["a"], -r["p"], r["code"], r["label"], r["name"], r["key"]))
    return rows, proj


def _compactness(area, perim):
    """Perimeter divided by the circumference of a circle of the same area
    (1.0 = a circle; larger = a more convoluted boundary)."""
    return perim / (2 * math.sqrt(math.pi * area))


def _dist_m(proj, a, b):
    (x1, y1), (x2, y2) = proj.xy(a), proj.xy(b)
    return math.hypot(x2 - x1, y2 - y1)


def _extent(rows, proj):
    s = min(r["bbox"][0] for r in rows)
    w = min(r["bbox"][1] for r in rows)
    n = max(r["bbox"][2] for r in rows)
    e = max(r["bbox"][3] for r in rows)
    ns = math.radians(n - s) * proj.my
    ew = math.radians(e - w) * proj.nx
    return {"ns": ns, "ew": ew, "bounds": [[round(s, 5), round(w, 5)], [round(n, 5), round(e, 5)]]}


# ---------------------------------------------------------------- insights

def insight_area(rows, owner):
    total = sum(r["a"] for r in rows)
    if len(rows) == 1:
        return (f"השכבה מתארת יחידה אחת, תחום השיפוט של {owner}, בשטח של "
                f"{_km2(total)} קמ״ר (כ-{_dunam(total)} דונם).")
    top = rows[0]
    return (f"השכבה מחולקת ל-{len(rows):,} יחידות בשטח כולל של {_km2(total)} קמ״ר "
            f"(כ-{_dunam(total)} דונם); הגדולה שבהן, {top['label']}, משתרעת על "
            f"{_km2(top['a'])} קמ״ר ({top['a'] / total * 100:.0f}% מהשטח).")


def insight_extent(rows, ext):
    who = "תחום השיפוט" if len(rows) == 1 else "השטח שבשכבה"
    s = f"מצפון לדרום משתרע {who} על {_km(ext['ns'])} ק״מ, וממזרח למערב על {_km(ext['ew'])} ק״מ"
    if len(rows) == 1 and rows[0]["chord"] > 0:
        s += f"; המרחק הארוך ביותר בין שתי נקודות על קו הגבול הוא {_km(rows[0]['chord'])} ק״מ"
    return s + "."


def insight_shape(rows):
    r = rows[0]
    ratio = _compactness(r["a"], r["p"])
    if ratio < 1.05:
        return None  # a near-circle says nothing worth a sentence
    fill = r["area"] / r["hull_area"] if r["hull_area"] > 0 else None
    circle = 2 * math.sqrt(math.pi * r["a"])
    who = "קו הגבול" if len(rows) == 1 else f"קו הגבול של {r['label']}"
    s = (f"{who} ארוך {_km(r['p'])} ק״מ, פי {ratio:.2f} מהיקפו של עיגול "
         f"באותו שטח ({_km(circle)} ק״מ)")
    if fill is not None and fill < 0.95:
        s += (f", והשטח ממלא {fill * 100:.0f}% מהמצולע הקמור הקטן ביותר שעוטף אותו "
              "(השאר הם מפרצים ושקעים בקו הגבול)")
    if ratio >= 1.3:
        s += ". זהו גבול מפותל ולא קומפקטי"
    return s + "."


def insight_check(rows):
    if not all(r["area_ok"] for r in rows):
        return None
    rec = sum(r["rec_area"] for r in rows)
    drawn = sum(r["area"] for r in rows)
    diff = (drawn - rec) / rec
    if abs(diff) <= AREA_MATCH:
        return (f"השטח שחושב מקו הגבול המצויר, {_km2(drawn)} קמ״ר, תואם את השטח הרשום "
                f"בשכבה ({_km2(rec)} קמ״ר), בסטייה של {abs(diff) * 100:.2f}% בלבד.")
    return (f"השטח שחושב מקו הגבול המצויר, {_km2(drawn)} קמ״ר, "
            f"{'גדול' if diff > 0 else 'קטן'} ב-{abs(diff) * 100:.1f}% מהשטח הרשום בשכבה "
            f"({_km2(rec)} קמ״ר): ייתכן שקו הגבול עודכן בלי לעדכן את שדה השטח.")


def insight_center(rows, proj):
    r = rows[0]
    if not r["center_rec"]:
        if r["centroid"] is None:
            return None
        lon, lat = r["centroid"]
        who = "מרכז הכובד של תחום השיפוט" if len(rows) == 1 else f"מרכז הכובד של {r['label']}"
        return (f"{who}, כפי שחושב מקו הגבול, נמצא בקו רוחב {_coord(lat)} ובקו אורך "
                f"{_coord(lon)}, והוא מסומן במפה.")
    lon, lat = r["center"]
    who = "נקודת המרכז הרשומה בשכבה" if len(rows) == 1 else f"נקודת המרכז של {r['label']}"
    s = f"{who} (קו רוחב {_coord(lat)}, קו אורך {_coord(lon)})"
    inside = _inside(lon, lat, r["polys"])
    d = _dist_m(proj, r["center"], r["centroid"]) if r["centroid"] else None
    if d is not None and d <= CENTER_MATCH_M:
        s += " מתלכדת עם מרכז הכובד של קו הגבול המצויר"
        s += " ונמצאת בתוך תחום השיפוט" if inside else ", אך נופלת מחוץ לתחום עצמו"
    elif d is not None:
        s += f" רחוקה {d:,.0f} מ׳ ממרכז הכובד של קו הגבול המצויר"
        s += " ונמצאת בתוך התחום" if inside else ", ונופלת מחוץ לתחום עצמו"
    else:
        s += " נמצאת בתוך התחום" if inside else " נופלת מחוץ לתחום"
    return s + "."


# ---------------------------------------------------------------- map

def _map(rows):
    """Geometry as [unit, polygon, ring, points] pieces chunked into islands
    under CHUNK_BYTES; a ring longer than CHUNK_POINTS is split into pieces
    that share an end point, so no single piece can outgrow an island."""
    pieces = []
    for u, r in enumerate(rows):
        for pi, poly in enumerate(r["polys"]):
            for ri, ring in enumerate(poly):
                for a in range(0, len(ring) - 1, CHUNK_POINTS):
                    pts = [[round(x, 5), round(y, 5)] for x, y in ring[a:a + CHUNK_POINTS + 1]]
                    pieces.append([u, pi, ri, pts])
    chunks, cur, size = [], [], 0
    for p in pieces:
        n = len(json.dumps(p, separators=(",", ":")))
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        chunks.append(cur)
    units = [{
        "label": r["label"], "code": r["code"], "km2": _km2(r["a"]), "km": _km(r["p"]),
        "center": [round(r["center"][1], 5), round(r["center"][0], 5)] if r["center"] else None,
    } for r in rows]
    return {"chunks": chunks, "units": units}


# ---------------------------------------------------------------- compute

def compute(frames):
    rows, proj = _prepare(frames["geo"])
    if not rows:
        raise ValueError("no valid polygon in the layer")
    n = len(rows)
    names = sorted({r["name"] for r in rows if r["name"]})
    owner = names[0] if len(names) == 1 else "העירייה"
    city = re.sub(r"^עיריית\s+", "", owner) if owner != "העירייה" else ""
    total_area = sum(r["a"] for r in rows)
    total_perim = sum(r["p"] for r in rows)
    ext = _extent(rows, proj)

    rules = [
        ("area", insight_area(rows, owner)),
        ("extent", insight_extent(rows, ext)),
        ("shape", insight_shape(rows)),
        ("check", insight_check(rows)),
        ("center", insight_center(rows, proj)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "area": {"value": round(total_area / 1e6, 1), "display": _km2(total_area), "tone": "brand"},
        "perim": {"value": round(total_perim / 1000, 1), "display": _km(total_perim), "tone": "brand"},
        "ns": {"value": round(ext["ns"] / 1000, 1), "display": _km(ext["ns"]), "tone": "brand"},
        "ew": {"value": round(ext["ew"] / 1000, 1), "display": _km(ext["ew"]), "tone": "brand"},
    }

    table = []
    for r in rows[:TABLE_CAP]:
        table.append({
            "label": r["label"],
            "code": r["code"],
            "area_km2": _km2(r["a"]),
            "dunam": _dunam(r["a"]),
            "drawn_km2": _km2(r["area"]),
            "perim_km": _km(r["p"]),
            "ratio": f"{_compactness(r['a'], r['p']):.2f}",
            "center": (f"{r['center'][1]:.5f}, {r['center'][0]:.5f}" if r["center"] else ""),
        })

    where = f"של {owner}" if city else "המוניציפלי"
    size = (f"שטח {_km2(total_area)} קמ״ר, היקף {_km(total_perim)} ק״מ" if n == 1
            else f"{n:,} יחידות בשטח {_km2(total_area)} קמ״ר")
    summary = (f"מפת גבול תחום השיפוט {where}: {size}, {_km(ext['ns'])} ק״מ מצפון "
               "לדרום. שכבת GIS להורדה ב-GeoJSON, SHP ו-CSV.")
    if len(summary) > SUMMARY_MAX:
        summary = f"מפת גבול תחום השיפוט {where}: {size}."

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "spatial_coverage": city or "באר שבע",
    }

    labels = {
        "h1_place": city,
        "kpi_area": "שטח השיפוט (קמ״ר)",
        "kpi_perim": "אורך קו הגבול (ק״מ)" if n == 1 else "סך היקפי היחידות (ק״מ)",
        "kpi_ns": "אורך מצפון לדרום (ק״מ)",
        "kpi_ew": "רוחב ממזרח למערב (ק״מ)",
        "map_lede": ("הקו הכחול הוא גבול תחום השיפוט כפי שהוא מצויר בקובץ ה-GeoJSON של השכבה, "
                     "והנקודה היא מרכז התחום. לחיצה על השטח מציגה את פרטיו."
                     if n == 1 else
                     f"{n:,} היחידות בשכבה, כל אחת בצבע משלה, כפי שהן מצוירות בקובץ "
                     "ה-GeoJSON. לחיצה על יחידה מציגה את פרטיה."),
        "map_aria": ("מפה אינטראקטיבית של גבול תחום השיפוט. גרסה נגישה: ראו את טבלת "
                     "פרטי השכבה בהמשך העמוד."),
        "table_title": "פרטי השכבה" if n == 1 else "היחידות בשכבה",
        "table_lede": ("הערכים הרשומים בטבלת המאפיינים של השכבה, מומרים ליחידות נוחות, "
                       "לצד השטח שחושב מקו הגבול המצויר."
                       if n <= TABLE_CAP else
                       f"{TABLE_CAP:,} היחידות הגדולות מתוך {n:,}, לפי שטח."),
        "table_caption": ("פרטי שכבת שטח השיפוט: " + ("יחידה אחת" if n == 1 else f"{n:,} יחידות")
                          + ", שטח, היקף, קוד אזור ונקודת מרכז."),
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"map": _map(rows), "bounds": ext["bounds"]},
        "insights": insights,
        "tables": {"units": table},
        "flags": {"single": n == 1},
        "labels": labels,
    }
