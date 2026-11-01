"""מטרו - קווים במטרופולין ירושלים (משרד התחבורה, צוות חצב).

A small GIS line layer: one feature per planned metro line or extension
(`LINE_NAME` X_1, X_2, X_Extension1, X_Extension2 in the 2026 file), with a
target `YEAR` (2050), the layer's own length in metres (`Shape_Leng`, ITM)
and `LENGT`, the same length rounded to whole km.

The only input is the uploaded shapefile (a `map: true` input: the refresh
downloads it on every run and hands compute one row per feature, attributes
as strings plus `__geometry`, WGS84 GeoJSON). The datastore CSV is the same
attribute table without the geometry, so it is not read. Everything the page
says about the network's shape is measured from the geometry here: route
length versus the recorded length, the straight-line distance between a
line's ends, the layer's extent, which features meet end to end (an
extension continuing a line), where two lines cross, and how close the
others come.

Growth: the layer is replaced in place when the plan changes. More features
flow through (per-line charts are capped at TOP_LINES + "אחר"), a feature is
an extension when its name says so ("ext", any case), an unknown name falls
back to "קטע <LINE_ID>", and new target years are listed, not assumed. The
pairwise geometry is O(features² × vertices²); fine for a layer of tens of
lines, and PAIR_LIMIT stops it from running away on a much bigger upload.
"""
import json
import math
import re

import pandas as pd

TOP_LINES = 12           # bars on the per-line charts before an "אחר" bucket
LEAD_SHARE = 0.30        # the longest line is called out from this share of the network
ROUND_GAP_KM = 0.3       # rounded-vs-measured gap worth a note
ATTACH_M = 50.0          # end points this close count as one junction
CLOSE_M = 1_500.0        # two lines that come this close are called out as running close
WIND_RATIO = 1.2         # route length / straight distance worth calling winding
LENGTH_OK = (0.8, 1.25)  # recorded/measured ratio inside which the recorded length is trusted
CHUNK_BYTES = 40_000     # each GeoJSON island stays well under 50KB
CHUNK_POINTS = 1_500     # a longer line is split into pieces of this many points
PAIR_ROWS = 20           # rows in the junctions table
PAIR_LIMIT = 60          # features beyond which pairwise geometry is skipped
R_EARTH = 6_371_000.0

MAIN_RX = re.compile(r"^x[_ ]?(\d+)$", re.IGNORECASE)
EXT_RX = re.compile(r"ext\D*(\d*)$", re.IGNORECASE)
KIND_ORDER = ["touch", "cross", "close", "far"]
KIND_HE = {"touch": "נפגשים בקצה", "cross": "חוצים זה את זה", "close": "עוברים בסמוך",
           "far": "אינם נפגשים"}
AXES = ["צפון-דרום", "דרום-מערב לצפון-מזרח", "מערב-מזרח", "צפון-מערב לדרום-מזרח"]


def _km(m):
    return f"{m / 1000:,.1f}"


def _m(m):
    return f"{m:,.0f}"


def _pct(x):
    return f"{x * 100:.0f}%"


def _clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def _num(s):
    return pd.to_numeric(_clean(s).replace(",", ""), errors="coerce")


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


# ── geometry helpers ─────────────────────────────────────────────────────


def _hav(a, b):
    (x1, y1), (x2, y2) = a[:2], b[:2]
    p1, p2 = math.radians(y1), math.radians(y2)
    dp, dl = p2 - p1, math.radians(x2 - x1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(min(1.0, h)))


def _length(pts):
    return sum(_hav(a, b) for a, b in zip(pts, pts[1:]))


def _parts_of(geom):
    if not isinstance(geom, dict):
        return []
    if geom.get("type") == "LineString":
        parts = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiLineString":
        parts = geom.get("coordinates") or []
    else:
        return []
    return [[[float(p[0]), float(p[1])] for p in part] for part in parts if len(part) >= 2]


class _Plane:
    """Local equirectangular projection (metres) around the layer's centre:
    plenty for a ~20 km metro layer, and it keeps segment maths simple."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = math.radians(1) * R_EARTH * math.cos(math.radians(lat0))
        self.ky = math.radians(1) * R_EARTH

    def xy(self, p):
        return ((p[0] - self.lon0) * self.kx, (p[1] - self.lat0) * self.ky)

    def lonlat(self, q):
        return [round(self.lon0 + q[0] / self.kx, 5), round(self.lat0 + q[1] / self.ky, 5)]


def _seg_point(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    c = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - c[0], p[1] - c[1]), c, t


def _intersect(a, b, c, d):
    """Intersection of segments ab and cd: (point, t on ab, u on cd) or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if den == 0:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (a[0] + t * r[0], a[1] + t * r[1]), t, u
    return None


def _polyline(plane, parts):
    """Projected vertices and the cumulative distance (m) at each, per part."""
    out, run = [], 0.0
    for part in parts:
        xy = [plane.xy(p) for p in part]
        cum = [run]
        for a, b in zip(xy, xy[1:]):
            run += math.hypot(b[0] - a[0], b[1] - a[1])
            cum.append(run)
        out.append((xy, cum))
    return out


def _closest(pa, pb):
    """Closest approach of two projected polylines: (dist, point, along_a, along_b)."""
    best = None
    for A, B, swap in ((pa, pb, False), (pb, pa, True)):
        for xy, cum in A:
            for i, p in enumerate(xy):
                for xy2, cum2 in B:
                    for j in range(len(xy2) - 1):
                        d, c, t = _seg_point(p, xy2[j], xy2[j + 1])
                        own, other = cum[i], cum2[j] + t * (cum2[j + 1] - cum2[j])
                        cand = (d, c, other, own) if swap else (d, c, own, other)
                        if best is None or cand[0] < best[0] - 1e-6:
                            best = cand
    return best


def _crossings(pa, pb):
    hits = []
    for xy, cum in pa:
        for i in range(len(xy) - 1):
            for xy2, cum2 in pb:
                for j in range(len(xy2) - 1):
                    r = _intersect(xy[i], xy[i + 1], xy2[j], xy2[j + 1])
                    if r:
                        q, t, u = r
                        hits.append((q, cum[i] + t * (cum[i + 1] - cum[i]),
                                     cum2[j] + u * (cum2[j + 1] - cum2[j])))
    hits.sort(key=lambda h: (round(h[1], 3), round(h[2], 3)))
    out = []  # a crossing on a shared vertex is hit twice: collapse near-duplicates
    for h in hits:
        if not out or math.hypot(h[0][0] - out[-1][0][0], h[0][1] - out[-1][0][1]) > ATTACH_M:
            out.append(h)
    return out


def _start_end_word(a, b):
    """Which end the line's start is, in compass words ("המערבי", ...)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return "המערבי" if dx > 0 else "המזרחי"
    return "הדרומי" if dy > 0 else "הצפוני"


def _axis(a, b):
    """The axis a line runs along, from the bearing between its two ends."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return None
    brg = math.degrees(math.atan2(dx, dy)) % 180.0  # 0 = north-south
    return AXES[int(((brg + 22.5) % 180.0) // 45.0)]


# ── rows ─────────────────────────────────────────────────────────────────


def _name_he(raw, lid):
    m = MAIN_RX.match(raw)
    if m:
        return f"קו {int(m.group(1))}", False
    if re.search(r"ext", raw, re.IGNORECASE):
        m = EXT_RX.search(raw)
        num = m.group(1) if m else ""
        return (f"שלוחה {int(num)}" if num else f"שלוחה {lid}"), True
    return f"קטע {lid}", False


def _prepare(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            geom = json.loads(r.get("__geometry") or "null")
        except ValueError:
            geom = None
        parts = _parts_of(geom)
        if not parts:
            continue
        lid = _num(r.get("LINE_ID", ""))
        lid = int(lid) if not pd.isna(lid) else None
        raw = _clean(r.get("LINE_NAME", ""))
        if lid is None and not raw:
            continue
        measured = sum(_length(p) for p in parts)
        rec = _num(r.get("Shape_Leng", ""))
        lengt = _num(r.get("LENGT", ""))
        year = _num(r.get("YEAR", ""))
        rec_ok = (not pd.isna(rec) and measured > 0
                  and LENGTH_OK[0] <= float(rec) / measured <= LENGTH_OK[1])
        name, ext = _name_he(raw, lid if lid is not None else raw)
        rows.append({
            "lid": lid, "raw": raw or "-", "name": name, "ext": ext,
            "year": int(year) if not pd.isna(year) else None,
            "measured": measured,
            "rec": float(rec) if not pd.isna(rec) else None,
            "lengt": float(lengt) if not pd.isna(lengt) else None,
            "m": float(rec) if rec_ok else measured,
            "parts": parts, "start": parts[0][0], "end": parts[-1][-1],
        })
    # Total order, so shuffled input gives the same model.
    rows.sort(key=lambda s: (s["ext"], s["lid"] if s["lid"] is not None else 10 ** 9,
                             s["raw"], -s["measured"], s["start"], s["end"]))
    seen = {}
    for s in rows:
        seen[s["name"]] = seen.get(s["name"], 0) + 1
    for s in rows:
        if seen[s["name"]] > 1:
            s["name"] = f"{s['name']} ({s['raw']})"
    return rows


def _features(rows, colors_idx, parent, bounds):
    feats = []
    for i, s in enumerate(rows):
        for part in s["parts"]:
            for a in range(0, len(part) - 1, CHUNK_POINTS):
                feats.append([i, [[round(x, 5), round(y, 5)] for x, y in part[a:a + CHUNK_POINTS + 1]]])
    chunks, cur, size = [], [], 0
    for f in feats:
        n = len(json.dumps(f, separators=(",", ":")))
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    meta = [{"name": s["name"], "color": colors_idx[i], "dash": s["ext"],
             "year": str(s["year"]) if s["year"] is not None else "-", "km": _km(s["m"]),
             "parent": rows[parent[i]]["name"] if parent.get(i) is not None else ""}
            for i, s in enumerate(rows)]
    return {"chunks": chunks, "segs": meta, "bounds": bounds}


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rows = _prepare(frames["geo"])
    if not rows:
        raise ValueError("no usable line features in the map file")
    n = len(rows)
    total = sum(s["m"] for s in rows)
    mains = [i for i, s in enumerate(rows) if not s["ext"]]
    exts = [i for i, s in enumerate(rows) if s["ext"]]
    years = sorted({s["year"] for s in rows if s["year"] is not None})

    allpts = [p for s in rows for part in s["parts"] for p in part]
    lon_min, lon_max = min(p[0] for p in allpts), max(p[0] for p in allpts)
    lat_min, lat_max = min(p[1] for p in allpts), max(p[1] for p in allpts)
    lat_c = (lat_min + lat_max) / 2
    plane = _Plane((lon_min + lon_max) / 2, lat_c)
    width_m = _hav([lon_min, lat_c], [lon_max, lat_c])
    height_m = _hav([plane.lon0, lat_min], [plane.lon0, lat_max])
    poly = [_polyline(plane, s["parts"]) for s in rows]
    for s in rows:
        s["straight"] = _hav(s["start"], s["end"])
        s["ratio"] = s["measured"] / s["straight"] if s["straight"] > 0 else None
        s["axis"] = _axis(plane.xy(s["start"]), plane.xy(s["end"]))
        s["from"] = _start_end_word(plane.xy(s["start"]), plane.xy(s["end"]))

    def at(i, along):
        return f"כ-{_km(along)} ק\"מ מהקצה {rows[i]['from']} של {rows[i]['name']}"

    # ── how the features meet ──
    def ends(i):
        return [("start", rows[i]["start"]), ("end", rows[i]["end"])]

    pairs = []
    if n <= PAIR_LIMIT:
        for i in range(n):
            for j in range(i + 1, n):
                touch = min(((_hav(pa, pb), ea, eb, pa) for ea, pa in ends(i) for eb, pb in ends(j)),
                            key=lambda t: (t[0], t[1], t[2]))
                if touch[0] <= ATTACH_M:
                    pairs.append({"i": i, "j": j, "kind": "touch", "dist": touch[0],
                                  "end_i": touch[1], "end_j": touch[2]})
                    continue
                crosses = _crossings(poly[i], poly[j])
                if crosses:
                    q, ai, aj = crosses[0]
                    pairs.append({"i": i, "j": j, "kind": "cross", "dist": 0.0,
                                  "point": plane.lonlat(q), "along_i": ai, "along_j": aj,
                                  "n_cross": len(crosses)})
                    continue
                d, c, ai, aj = _closest(poly[i], poly[j])
                pairs.append({"i": i, "j": j, "kind": "close" if d <= CLOSE_M else "far",
                              "dist": d, "point": plane.lonlat(c), "along_i": ai, "along_j": aj})

    # An extension's parent: the main line it meets end to end.
    parent = {}
    for e in exts:
        cands = sorted((p["dist"], rows[m_]["name"], m_) for p in pairs if p["kind"] == "touch"
                       for m_ in mains if {p["i"], p["j"]} == {e, m_})
        parent[e] = cands[0][2] if cands else None

    # Colours: one per main line; an extension takes its parent's (drawn dashed).
    colors_idx, k = {}, 0
    for i in range(n):
        if not rows[i]["ext"] or parent.get(i) is None:
            colors_idx[i] = k
            k += 1
    for i in exts:
        if parent.get(i) is not None:
            colors_idx[i] = colors_idx[parent[i]]

    # Junctions: crossings, and end points shared by 3+ features (a fork).
    clusters = []
    for i in range(n):
        for _, pt in ends(i):
            for c in clusters:
                if _hav(c["pt"], pt) <= ATTACH_M:
                    if i not in c["ids"]:
                        c["ids"].append(i)
                    break
            else:
                clusters.append({"pt": pt, "ids": [i]})
    forks = [c for c in clusters if len(c["ids"]) >= 3]
    markers = []
    for p in pairs:
        if p["kind"] == "cross":
            markers.append({"pt": p["point"], "kind": "חציה",
                            "text": f"{rows[p['i']]['name']} חוצה את {rows[p['j']]['name']}"})
    for c in forks:
        markers.append({"pt": [round(c["pt"][0], 5), round(c["pt"][1], 5)], "kind": "פיצול",
                        "text": "נקודת המפגש של " + join_he(rows[i]["name"] for i in sorted(c["ids"]))})
    markers.sort(key=lambda m_: (m_["kind"], m_["pt"], m_["text"]))

    map_model = _features(rows, colors_idx, parent, [[lat_min, lon_min], [lat_max, lon_max]])
    map_model["markers"] = markers

    # Line systems: each main line with the extensions that continue it.
    systems = []
    for mi in mains:
        kids = sorted((e for e in exts if parent.get(e) == mi), key=lambda e: (-rows[e]["m"], rows[e]["name"]))
        systems.append({"name": rows[mi]["name"], "main": rows[mi]["m"], "kids": kids,
                        "m": rows[mi]["m"] + sum(rows[e]["m"] for e in kids)})
    for e in exts:
        if parent.get(e) is None:
            systems.append({"name": rows[e]["name"], "main": rows[e]["m"], "kids": [], "m": rows[e]["m"]})
    systems.sort(key=lambda s: (-s["m"], s["name"]))
    sys_shown = systems[:TOP_LINES]
    max_kids = max((len(s["kids"]) for s in sys_shown), default=0)

    # ── charts ──
    by_len = sorted(range(n), key=lambda i: (-rows[i]["m"], rows[i]["name"]))
    shown, rest = by_len[:TOP_LINES], by_len[TOP_LINES:]
    rest_m = sum(rows[i]["m"] for i in rest)
    chart_len = {
        "names": [rows[i]["name"] for i in shown] + ([f"אחר ({len(rest):,})"] if rest else []),
        "km": [round(rows[i]["m"] / 1000, 2) for i in shown] + ([round(rest_m / 1000, 2)] if rest else []),
        "color": [colors_idx[i] for i in shown] + ([-1] if rest else []),
        "ext": [rows[i]["ext"] for i in shown] + ([False] if rest else []),
        "share": [round(rows[i]["m"] / total * 100, 1) for i in shown] + ([round(rest_m / total * 100, 1)] if rest else []),
    }
    chart_sys = {
        "names": [s["name"] for s in sys_shown],
        "main": [round(s["main"] / 1000, 2) for s in sys_shown],
        "kids": [[round(rows[s["kids"][q]]["m"] / 1000, 2) if q < len(s["kids"]) else 0 for s in sys_shown]
                 for q in range(max_kids)],
        "kid_names": [[rows[s["kids"][q]]["name"] if q < len(s["kids"]) else "" for s in sys_shown]
                      for q in range(max_kids)],
        "total": [round(s["m"] / 1000, 2) for s in sys_shown],
    }
    shape_rows = [i for i in by_len if rows[i]["ratio"] is not None][:TOP_LINES]
    chart_shape = {
        "names": [rows[i]["name"] for i in shape_rows],
        "route": [round(rows[i]["measured"] / 1000, 2) for i in shape_rows],
        "straight": [round(rows[i]["straight"] / 1000, 2) for i in shape_rows],
        "ratio": [round(rows[i]["ratio"], 2) for i in shape_rows],
    }

    # ── tables ──
    t_len = [{
        "name": rows[i]["name"], "code": rows[i]["raw"],
        "id": str(rows[i]["lid"]) if rows[i]["lid"] is not None else "-",
        "kind": ("שלוחה" + (f" של {rows[parent[i]]['name']}" if parent.get(i) is not None else ""))
        if rows[i]["ext"] else "קו ראשי",
        "rec": f"{rows[i]['rec']:,.0f}" if rows[i]["rec"] is not None else "-",
        "measured": _m(rows[i]["measured"]),
        "lengt": f"{rows[i]['lengt']:,.0f}" if rows[i]["lengt"] is not None else "-",
        "share": _pct(rows[i]["m"] / total),
        "year": str(rows[i]["year"]) if rows[i]["year"] is not None else "-",
    } for i in by_len]
    t_sys = [{"name": s["name"], "main": _km(s["main"]),
              "kids": join_he(f"{rows[e]['name']} ({_km(rows[e]['m'])})" for e in s["kids"]) or "-",
              "total": _km(s["m"])} for s in sys_shown]
    t_shape = [{"name": rows[i]["name"], "route": _km(rows[i]["measured"]),
                "straight": _km(rows[i]["straight"]), "ratio": f"{rows[i]['ratio']:.2f}",
                "axis": rows[i]["axis"] or "-"} for i in shape_rows]
    pairs_sorted = sorted(pairs, key=lambda p: (KIND_ORDER.index(p["kind"]), p["dist"],
                                               rows[p["i"]]["name"], rows[p["j"]]["name"]))
    t_pairs = []
    for p in pairs_sorted[:PAIR_ROWS]:
        a, b = rows[p["i"]], rows[p["j"]]
        if p["kind"] == "touch":
            where = (f"{'תחילת' if p['end_i'] == 'start' else 'סוף'} {a['name']}, "
                     f"{'תחילת' if p['end_j'] == 'start' else 'סוף'} {b['name']}")
        else:
            where = f"{at(p['i'], p['along_i'])}, {at(p['j'], p['along_j'])}"
        t_pairs.append({"pair": f"{a['name']} ו{b['name']}", "kind": KIND_HE[p["kind"]],
                        "dist": "0" if p["kind"] == "cross" else _m(p["dist"]), "where": where})

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_longest():
        if n < 2:
            return None
        a, b = rows[by_len[0]], rows[by_len[1]]
        share = a["m"] / total
        if share < LEAD_SHARE or round(a["m"], -2) == round(b["m"], -2):
            return None
        return (f"{a['name']} הוא הקטע הארוך בשכבה: {_km(a['m'])} ק\"מ, כ-{_pct(share)} מאורך הרשת. "
                f"אחריו {b['name']} עם {_km(b['m'])} ק\"מ.")
    add("longest", ins_longest())

    def ins_fork():
        for c in sorted(forks, key=lambda c: sorted(c["ids"])):
            ids = sorted(c["ids"])
            m_ = [i for i in ids if not rows[i]["ext"]]
            e_ = [i for i in ids if rows[i]["ext"]]
            if len(m_) != 1 or len(e_) < 2:
                continue
            base = rows[m_[0]]
            sysm = base["m"] + sum(rows[i]["m"] for i in e_)
            return (f"{base['name']} מסתיים בנקודת פיצול שממנה יוצאות {len(e_):,} שלוחות "
                    f"({join_he(rows[i]['name'] for i in e_)}). יחד הן מאריכות את הקו "
                    f"מ-{_km(base['m'])} ל-{_km(sysm)} ק\"מ.")
        lone = [e for e in exts if parent.get(e) is not None]
        if lone:
            e = lone[0]
            return (f"{rows[e]['name']} ממשיכה את {rows[parent[e]]['name']} מקצהו "
                    f"ומוסיפה לו {_km(rows[e]['m'])} ק\"מ.")
        return None
    add("fork", ins_fork())

    def ins_cross():
        cs = [p for p in pairs if p["kind"] == "cross"]
        if not cs:
            return None
        p = cs[0]
        a, b = rows[p["i"]], rows[p["j"]]
        times = f" {p['n_cross']:,} פעמים" if p["n_cross"] > 1 else ""
        first = "החציה הראשונה" if p["n_cross"] > 1 else "נקודת החציה"
        text = (f"{a['name']} ו{b['name']} חוצים זה את זה{times}. {first} נמצאת "
                f"{at(p['i'], p['along_i'])} ו{at(p['j'], p['along_j'])}.")
        if len(cs) > 1:
            text += f" בשכבה {len(cs):,} זוגות קטעים שחוצים זה את זה."
        return text
    add("cross", ins_cross())

    def ins_close():
        cs = sorted((p for p in pairs if p["kind"] == "close"), key=lambda p: (p["dist"], p["i"], p["j"]))
        if not cs:
            return None
        p = cs[0]
        return (f"{rows[p['i']]['name']} ו{rows[p['j']]['name']} אינם נפגשים, אך מתקרבים "
                f"עד כ-{_m(round(p['dist'], -1))} מטר זה מזה.")
    add("close", ins_close())

    def ins_extent():
        if n < 2:
            return None
        axes = [(rows[i]["name"], rows[i]["axis"]) for i in mains if rows[i]["axis"]]
        ax_txt = ""
        if 2 <= len(axes) <= 3 and len({a for _, a in axes}) == len(axes):
            ax_txt = " " + join_he(f"{nm} נמתח בציר {ax}" for nm, ax in axes) + "."
        return (f"הרשת משתרעת על פני כ-{_km(width_m)} ק\"מ ממערב למזרח וכ-{_km(height_m)} ק\"מ "
                f"מדרום לצפון.{ax_txt}")
    add("extent", ins_extent())

    def ins_winding():
        cand = [i for i in mains if rows[i]["ratio"] is not None]
        if not cand:
            return None
        s = rows[max(cand, key=lambda i: (rows[i]["ratio"], rows[i]["name"]))]
        if s["ratio"] < WIND_RATIO:
            return None
        return (f"התוואים אינם ישרים: {s['name']} עובר {_km(s['measured'])} ק\"מ בין קצוות "
                f"שהמרחק ביניהם בקו אווירי {_km(s['straight'])} ק\"מ, ארוך ממנו ב-{_pct(s['ratio'] - 1)}.")
    add("winding", ins_winding())

    def ins_rounding():
        if any(s["lengt"] is None for s in rows):
            return None
        lsum = sum(s["lengt"] for s in rows)
        if abs(total / 1000 - lsum) < ROUND_GAP_KM:
            return None
        return (f"שדה האורך המעוגל בשכבה מסתכם ב-{lsum:,.0f} ק\"מ, אך אורך התוואים "
                f"הוא {_km(total)} ק\"מ; העמוד מציג את האורך המלא.")
    add("rounding", ins_rounding())

    def ins_horizon():
        if not years:
            return None
        if len(years) == 1:
            all_txt = "שני הקטעים" if n == 2 else f"כל {n:,} הקטעים"
            return (f"{all_txt} מסומנים לשנת היעד {years[0]}: זהו מצב מתוכנן, "
                    "ולא תיאור של קווים פעילים או בביצוע.")
        parts = [f"{_km(sum(s['m'] for s in rows if s['year'] == y))} ק\"מ לשנת {y}" for y in years]
        return "הקטעים מתחלקים לפי שנת יעד: " + join_he(parts) + "."
    add("horizon", ins_horizon())

    diffs = [abs(s["rec"] - s["measured"]) / s["measured"] for s in rows
             if s["rec"] is not None and s["measured"] > 0]
    max_diff = max(diffs) if diffs else None

    # ── KPIs ──
    in_fork = lambda p: any(p["i"] in c["ids"] and p["j"] in c["ids"] for c in forks)  # noqa: E731
    n_junc = (sum(1 for p in pairs if p["kind"] == "cross") + len(forks)
              + sum(1 for p in pairs if p["kind"] == "touch" and not in_fork(p)))
    year_disp = str(years[0]) if len(years) == 1 else (f"{years[0]}–{years[-1]}" if years else "-")
    kpis = {
        "lines": {"value": len(mains), "display": f"{len(mains):,}", "tone": "brand"},
        "exts": {"value": len(exts), "display": f"{len(exts):,}", "tone": "brand"},
        "length": {"value": round(total / 1000, 1), "display": _km(total), "tone": "brand"},
        "junctions": {"value": n_junc, "display": f"{n_junc:,}", "tone": "info"},
        "year": {"value": years[-1] if years else None, "display": year_disp, "tone": "info"},
    }
    kpi_order = (["lines", "exts"] if exts else ["lines"]) + ["length"] + (
        ["junctions"] if pairs else []) + ["year"]

    lead = rows[by_len[0]]
    year_txt = (f" לשנת היעד {years[0]}" if len(years) == 1
                else (f" לשנים {years[0]}-{years[-1]}" if years else ""))
    struct = ("קו ראשי אחד" if len(mains) == 1 else f"{len(mains):,} קווים ראשיים") + (
        ("" if not exts else (" ושלוחה אחת" if len(exts) == 1 else f" ו-{len(exts):,} שלוחות")))
    if max_diff is None:
        diff_txt = ""
    elif max_diff < 0.01:
        diff_txt = f" האורך הרשום בשכבה תואם את האורך הנמדד מהתוואי (פער מרבי {max_diff * 100:.1f}%)."
    else:
        diff_txt = f" בין האורך הרשום בשכבה לאורך הנמדד מהתוואי יש פער של עד {max_diff * 100:.1f}%."
    if len(markers) > 1:
        mk_txt = f"עיגולים מסמנים {len(markers):,} נקודות מפגש. "
    elif markers:
        mk_txt = "עיגול מסמן את נקודת המפגש. "
    else:
        mk_txt = ""
    labels = {
        "lede": (f"שכבת ה-GIS של משרד התחבורה משרטטת את תוואי המטרו המתוכנן במטרופולין ירושלים{year_txt}: "
                 f"{struct}, באורך כולל של {_km(total)} ק\"מ. "
                 f"הארוך שבהם הוא {lead['name']} ({_km(lead['m'])} ק\"מ). "
                 "זהו מצב תכנוני ולא לוח זמנים לביצוע."),
        "kpi_lines": "קווי מטרו ראשיים",
        "kpi_exts": "שלוחות",
        "kpi_length": "אורך כולל (ק\"מ)",
        "kpi_junctions": "נקודות מפגש בין קטעים",
        "kpi_year": "שנת היעד בתכנון",
        "map_lede": (f"תוואי {n:,} הקטעים על המפה, בצבע לכל קו ראשי; שלוחה מסומנת בקו מקווקו בצבע הקו שהיא ממשיכה. "
                     + mk_txt + "לחיצה על קו מציגה את שמו ואורכו."),
        "map_aria": f"מפת תוואי {n:,} קטעי המטרו המתוכננים במטרופולין ירושלים",
        "len_lede": (f"אורך כל קטע בק\"מ. {lead['name']} מוביל עם {_km(lead['m'])} ק\"מ." + diff_txt
                     + (f" מוצגים {TOP_LINES:,} הארוכים; השאר תחת \"אחר\"." if rest else "")),
        "len_aria": f"גרף עמודות אופקי: אורך {n:,} קטעי המטרו בק\"מ, הארוך ביותר {lead['name']}",
        "len_caption": "אורך כל קטע: רשום בשכבה, נמדד מהתוואי ומעוגל",
        "sys_lede": ("כל קו ראשי יחד עם השלוחות שממשיכות אותו מקצהו: "
                     + join_he(f"{s['name']} {_km(s['m'])} ק\"מ" for s in sys_shown) + "."),
        "sys_aria": "גרף עמודות מוערמות: אורך כל קו ראשי ושלוחותיו בק\"מ",
        "sys_caption": "אורך כל קו ראשי ושלוחותיו",
        "shape_lede": ("אורך התוואי לעומת המרחק בקו אווירי בין שני קצותיו. "
                       "ככל שהיחס גבוה יותר, התוואי מתפתל יותר בדרכו בין הקצוות."),
        "shape_aria": "גרף עמודות: אורך התוואי מול המרחק בקו אווירי לכל קטע",
        "shape_caption": "אורך התוואי, מרחק בקו אווירי, היחס ביניהם וציר הקטע",
        "pairs_lede": (f"לכל זוג קטעים: האם הם נפגשים בקצה, חוצים זה את זה, או מה המרחק הקטן ביותר ביניהם "
                       f"(עד {_m(CLOSE_M)} מטר נחשב סמוך)."),
        "pairs_caption": "יחסי המפגש בין קטעי המטרו",
    }

    summary = (f"מפת קווי המטרו המתוכננים בירושלים: {struct}, {_km(total)} ק\"מ"
               + (f" לשנת {years[-1]}" if years else "")
               + ". תוואי, אורכים ונקודות מפגש בין הקווים.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "מטרופולין ירושלים",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {"map": map_model, "len": chart_len, "sys": chart_sys, "shape": chart_shape},
        "tables": {"len": t_len, "sys": t_sys, "shape": t_shape, "pairs": t_pairs},
        "flags": {"sys": any(s["kids"] for s in systems), "shape": bool(shape_rows),
                  "pairs": bool(t_pairs)},
        "insights": insights,
        "labels": labels,
        "links": {
            "jlm2050": "/datasets/5ecf0587-21e6-411a-8f04-9f4f44a43956/",
            "jlm2040": "/datasets/068ff53c-ad54-4848-8a29-bd9b178d9174/",
            "lrt": "/datasets/b65ae5cf-8aab-4b8e-ae08-de941368fff0/",
            "tlv_metro": "/datasets/f10f7f97-7a1a-4516-9549-3f7025af5768/",
        },
    }
