"""מספרי דרכים ארציות: משרד התחבורה (צוות חצב).

One row per road segment of the national road-numbering layer (the GIS
shapefile flattened to CSV, geometry dropped): the road number (`ROADNUMBER`,
empty on ramps), the road class (`ROADCLASS`: מהירה / ראשית / אזורית /
מקומית, empty or "<Null>" on ramps), the link type (`LINKTYPE`: numbered road,
ramp, service road), a ramp code or street name (`ROADNAME`, mostly blank on
numbered roads), a numbering-change code (`NUM_CHANGE`: 0 = unchanged,
otherwise a YYYYMM or YYYYMMDD stamp) and the segment length in metres
(`LENGT_M`; `Shape_Length` is the same value).

People search "רשימת דרכים" / "כביש <n>": the page leads with a lookup
callout to the explorer, lists every one- and two-digit road and every
three-digit road with its class and length, and then shows what the layer
carries: the longest roads, class mix, how the number of digits encodes the
class, the length distribution, how the numbering space is used, link types
and recent numbering changes.

Lengths are sums of segment lengths per road number (a divided road whose two
carriageways are drawn as separate segments counts both). Exact duplicate rows
(the same segment listed twice) are dropped, and the page says so.

Growth: the layer is replaced in place. New roads, classes and link types
flow through (known classes are ordered, unknown ones are appended), the
longest-roads chart is top-N, the regional list grows only up to the
three-digit space, and numbering-change codes are bucketed by month (an
unparseable code gets its own disclosed bucket).

v2 adds the `geo` input: the uploaded shapefile (ROADNUMBERS_SHP), which the
refresh downloads on every run. It draws every segment on a Leaflet map,
coloured by class, with a road-number search, and adds a north-south view
(km per latitude band) plus two geometry insights. The map size is bounded by
chaining and simplifying lines in compute (MAP_BUDGET), so a bigger upload
only coarsens the drawing.
"""
import json
import math

import pandas as pd

TOP_N = 20                 # longest roads on the bar chart
CLASS_ORDER = ["מהירה", "ראשית", "אזורית", "מקומית"]
CLASS_LABEL = {"מהירה": "דרך מהירה", "ראשית": "דרך ראשית",
               "אזורית": "דרך אזורית", "מקומית": "דרך מקומית"}
NO_CLASS = "ללא דרגה"
CLASS_PLURAL = {"מהירה": "דרכים מהירות", "ראשית": "דרכים ראשיות",
                "אזורית": "דרכים אזוריות", "מקומית": "דרכים מקומיות"}
NUMBERED = "דרך ממוספרת"
RAMP = "רמפה"
DIGIT_LABEL = {1: "חד-ספרתיות", 2: "דו-ספרתיות", 3: "תלת-ספרתיות", 4: "ארבע ספרות"}
DIGIT_PHRASE = {1: "בנות ספרה אחת", 2: "הדו-ספרתיות", 3: "התלת-ספרתיות", 4: "בנות ארבע הספרות"}
LEN_BINS = [(0, 1, "עד 1"), (1, 2, "1-2"), (2, 5, "2-5"), (5, 10, "5-10"),
            (10, 20, "10-20"), (20, 50, "20-50"), (50, 100, "50-100"),
            (100, float("inf"), "100 ומעלה")]
ALIGN_SHARE = 0.9          # "digits encode the class" needs >= this share per length
TOP10_SHARE = 0.15         # concentration insight threshold
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(round(v)):,}"


def km(v, digits=1):
    return f"{v:,.{digits}f}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def clean(s):
    return " ".join(str(s).split())


def class_key(c):
    return (CLASS_ORDER.index(c) if c in CLASS_ORDER else len(CLASS_ORDER), c)


def class_label(c):
    return CLASS_LABEL.get(c, c if c else NO_CLASS)


def change_month(code):
    """'202305' / '20250921' -> '2023-05'; '0' / '' -> None; garbage -> '?'."""
    c = clean(code)
    if c in ("", "0"):
        return None
    if c.isdigit() and len(c) in (6, 8):
        y, m = int(c[:4]), int(c[4:6])
        if 1948 <= y <= 2200 and 1 <= m <= 12:
            return f"{y:04d}-{m:02d}"
    return "?"


def month_he(key):
    y, m = key.split("-")
    return f"{m}/{y}"


def segs_he(k):
    return "מקטע אחד" if k == 1 else f"-{n(k)} מקטעים"


def roads_he(k):
    return "דרך אחת" if k == 1 else f"-{n(k)} דרכים"


# ---------------------------------------------------------------- geometry (geo input)
# `geo` is the uploaded shapefile: one row per segment, the same attributes as
# the CSV plus `__geometry` (WGS84 GeoJSON). It drives the line map and the
# north-south views. For display, segments of the same road (and kind) that
# share an end point are chained into one line, then simplified with the
# finest tolerance whose islands fit MAP_BUDGET. Lengths are measured on the
# unsimplified geometry.

SIMPLIFY_M = (10.0, 20.0, 35.0, 50.0, 80.0, 120.0, 200.0, 400.0)
MAP_BUDGET = 200_000
QUANT = 100_000            # 1e-5 degree integers (about 1 m)
CHUNK_BYTES = 34_000       # compact size; tojson's spacing adds ~20%, islands stay under 50KB
CHUNK_POINTS = 1_500       # a longer line is split into pieces of this many points
BAND_WIDTHS = (10, 20, 25, 50, 100)   # latitude band widths, in 0.01 degrees
MAX_BANDS = 20
KM_PER_DEG_LAT = 111.2
CLASS_COLOR = {"מהירה": "#0b3668", "ראשית": "#0068f5", "אזורית": "#198754",
               "מקומית": "#f59f00"}
CLASS_WEIGHT = {"מהירה": 4, "ראשית": 3.5, "אזורית": 2.5, "מקומית": 1.8}
OTHER_COLORS = ["#0dcaf0", "#0053c4", "#c3cfe7"]
RAMP_COLOR = "#6c757d"
RAMP_LABEL = "רמפות"
EXTENT_SHARE = 0.5         # "a road crosses the country" needs >= this share of the N-S span


def _haversine_m(a, b):
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, h)))


def _lines_of(geom):
    if not isinstance(geom, dict):
        return []
    if geom.get("type") == "LineString":
        parts = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiLineString":
        parts = geom.get("coordinates") or []
    else:
        return []
    out = []
    for part in parts:
        pts = tuple((float(c[0]), float(c[1])) for c in part
                    if isinstance(c, list) and len(c) >= 2)
        if len(pts) >= 2:
            out.append(pts)
    return out


def _simplify(pts, tol_m):
    """Douglas-Peucker on a local metric projection; keeps both end points."""
    if len(pts) < 3:
        return list(pts)
    k = math.cos(math.radians(pts[0][1]))
    m = [(x * 111_320 * k, y * 110_574) for x, y in pts]
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = m[a]
        dx, dy = m[b][0] - ax, m[b][1] - ay
        ll = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = m[i][0] - ax, m[i][1] - ay
            t = 0.0 if ll == 0 else max(0.0, min(1.0, (px * dx + py * dy) / ll))
            d = math.hypot(px - t * dx, py - t * dy)
            if d > best:
                best, bi = d, i
        if bi > 0 and best > tol_m:
            keep.add(bi)
            stack.append((a, bi))
            stack.append((bi, b))
    return [pts[i] for i in sorted(keep)]


def _encode(pts):
    """Flat [x0, y0, dx1, dy1, ...] in 1e-5 degree integers (lon, lat)."""
    q = [(round(x * QUANT), round(y * QUANT)) for x, y in pts]
    flat = [q[0][0], q[0][1]]
    for (a, b), (x, y) in zip(q, q[1:]):
        flat += [x - a, y - b]
    return flat


def _chain(lines):
    """Join lines that share an end point into longer lines. Deterministic:
    the lines are sorted first and the lowest-ranked free neighbour wins."""
    lines = sorted(set(lines))
    used = [False] * len(lines)
    ends = {}
    for i, ln in enumerate(lines):
        ends.setdefault(ln[0], []).append(i)
        ends.setdefault(ln[-1], []).append(i)
    out = []
    for i in range(len(lines)):
        if used[i]:
            continue
        used[i] = True
        cur = list(lines[i])
        for at_end in (True, False):
            while True:
                pt = cur[-1] if at_end else cur[0]
                free = [j for j in ends.get(pt, []) if not used[j]]
                if not free:
                    break
                j = min(free)
                used[j] = True
                ln = lines[j]
                if at_end:
                    cur += list(ln[1:]) if ln[0] == pt else list(ln[::-1][1:])
                else:
                    cur = (list(ln[:-1]) if ln[-1] == pt else list(ln[::-1][:-1])) + cur
        out.append(cur)
    return out


def _bounds(lines):
    xs = [x for ln in lines for x, _ in ln]
    ys = [y for ln in lines for _, y in ln]
    if not xs:
        return None
    return [[round(min(ys), 5), round(min(xs), 5)], [round(max(ys), 5), round(max(xs), 5)]]


def _deg(v, width):
    return f"{v:.1f}" if round(width * 100) % 10 == 0 else f"{v:.2f}"


def geo_section(df):
    """Map model, latitude-band chart, labels and geometry insights."""
    recs = {}
    for r in df.to_dict("records"):
        num = pd.to_numeric(clean(r.get("ROADNUMBER", "")), errors="coerce")
        rn = int(num) if not pd.isna(num) and num > 0 else 0
        cls = clean(r.get("ROADCLASS", ""))
        cls = "" if cls == "<Null>" else cls
        lt = clean(r.get("LINKTYPE", ""))
        if lt == RAMP:
            kind = RAMP_LABEL
        elif lt == NUMBERED and rn > 0:
            kind = cls or NO_CLASS
        else:
            kind = lt or "לא צוין"
        try:
            geom = json.loads(r.get("__geometry") or "null")
        except ValueError:
            geom = None
        lines = tuple(_lines_of(geom))
        recs[(kind, rn, cls, lines)] = (kind, rn, cls, lines)   # exact duplicates count once
    feats = [v for v in recs.values() if v[3]]
    missing = len(recs) - len(feats)

    road_kinds = sorted({k for k, rn, _, _ in feats if rn > 0 and k != RAMP_LABEL}, key=class_key)
    other = sorted({k for k, rn, _, _ in feats if k not in road_kinds and k != RAMP_LABEL})
    kinds = road_kinds + other + ([RAMP_LABEL] if any(f[0] == RAMP_LABEL for f in feats) else [])
    extra = iter(OTHER_COLORS * 4)
    colors, weights = [], []
    for k in kinds:
        if k == RAMP_LABEL:
            colors.append(RAMP_COLOR)
            weights.append(1.5)
        else:
            colors.append(CLASS_COLOR.get(k) or next(extra, RAMP_COLOR))
            weights.append(CLASS_WEIGHT.get(k, 2))

    groups = {}
    for k, rn, _, lines in feats:
        groups.setdefault((kinds.index(k), rn), []).extend(lines)
    chained = {key: _chain(v) for key, v in sorted(groups.items())}

    used_tol = SIMPLIFY_M[-1]
    for tol in SIMPLIFY_M:
        items = []
        for (ki, rn), lines in chained.items():
            for ln in lines:
                simp = _simplify(ln, tol)
                for a in range(0, len(simp) - 1, CHUNK_POINTS):
                    items.append([ki, rn, _encode(simp[a:a + CHUNK_POINTS + 1])])
        chunks, cur, size, total = [], [], 0, 0
        for it in items:
            nb = len(json.dumps(it, separators=(",", ":"))) + 1
            if cur and size + nb > CHUNK_BYTES:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(it)
            size += nb
            total += nb
        if cur:
            chunks.append(cur)
        used_tol = tol
        if total <= MAP_BUDGET:
            break

    # lengths on the unsimplified geometry (numbered roads only)
    per_road = {}
    pieces = []
    for k, rn, _, lines in feats:
        if rn <= 0 or k == RAMP_LABEL:
            continue
        lo_hi = per_road.setdefault(rn, [90.0, -90.0])
        for ln in lines:
            for a, b in zip(ln, ln[1:]):
                pieces.append(((a[1] + b[1]) / 2, _haversine_m(a, b), k))
            ys = [y for _, y in ln]
            lo_hi[0], lo_hi[1] = min(lo_hi[0], min(ys)), max(lo_hi[1], max(ys))
    total_m = sum(p[1] for p in pieces)

    acc, width = {}, BAND_WIDTHS[-1] / 100
    for w in BAND_WIDTHS:
        acc = {}
        for lat, m, k in pieces:
            key = math.floor(lat * 100 / w)
            d = acc.setdefault(key, {})
            d[k] = d.get(k, 0.0) + m
        width = w / 100
        if len(acc) <= MAX_BANDS:
            break
    bands = []
    for key in sorted(acc, reverse=True):       # north first
        lo = key * width
        bands.append({"lo": lo, "hi": lo + width, "by": acc[key], "m": sum(acc[key].values())})
    band_names = [f"{_deg(b['lo'], width)} עד {_deg(b['hi'], width)}" for b in bands]
    lat_chart = {
        "names": band_names,
        "series": [{"name": class_label(k) if k in CLASS_ORDER else k,
                    "color": colors[kinds.index(k)],
                    "data": [round(b["by"].get(k, 0.0) / 1000, 1) for b in bands]}
                   for k in road_kinds + other if any(k in b["by"] for b in bands)],
    }
    lat_table = [{"name": band_names[i], "km": km(b["m"] / 1000),
                  "share": pct(b["m"] / total_m if total_m else 0)} for i, b in enumerate(bands)]

    insights = []
    # extent: the road that spans most of the network's north-south range
    if per_road and len(per_road) >= 2:
        net_lo = min(v[0] for v in per_road.values())
        net_hi = max(v[1] for v in per_road.values())
        span_net = (net_hi - net_lo) * KM_PER_DEG_LAT
        rn_x, (lo_x, hi_x) = sorted(per_road.items(), key=lambda kv: (kv[1][0] - kv[1][1], kv[0]))[0]
        span_x = (hi_x - lo_x) * KM_PER_DEG_LAT
        if span_net > 0 and span_x / span_net >= EXTENT_SHARE:
            insights.append(("extent",
                f"על המפה, כביש {rn_x} נפרש על פני כ-{n(span_x)} ק\"מ מצפון לדרום, "
                f"{pct(span_x / span_net, 0)} ממרחק הצפון-דרום של כל רשת הדרכים הממוספרות "
                f"(כ-{n(span_net)} ק\"מ)."))
    # concentration in the north: where half the road length lies
    if total_m > 0 and len(bands) >= 3:
        pts = sorted(pieces, key=lambda p: (-p[0], p[1], p[2]))
        run, med = 0.0, None
        for lat, m, _ in pts:
            run += m
            if run >= total_m / 2:
                med = lat
                break
        lat_hi = max(p[0] for p in pieces)
        lat_lo = min(p[0] for p in pieces)
        if med is not None and lat_hi > lat_lo:
            north_part = (lat_hi - med) / (lat_hi - lat_lo)
            if north_part <= 0.4:
                insights.append(("north",
                    f"חצי מאורך הדרכים הממוספרות ({km(total_m / 2000, 0)} ק\"מ) עובר בחלק הצפוני "
                    f"של הארץ, מצפון לקו רוחב {med:.2f}°, שהוא רק {pct(north_part, 0)} ממרחק "
                    f"הצפון-דרום של הרשת."))

    model = {
        "chunks": chunks, "kinds": [class_label(k) if k in CLASS_ORDER else k for k in kinds],
        "colors": colors, "weights": weights, "ramp": kinds.index(RAMP_LABEL) if RAMP_LABEL in kinds else -1,
        "bounds": _bounds([ln for f in feats for ln in f[3]]),
    }
    n_kind = {k: 0 for k in kinds}
    for k, rn, _, _ in feats:
        n_kind[k] += 1
    legend = [{"name": model["kinds"][i], "color": colors[i], "segs": n(n_kind[k])}
              for i, k in enumerate(kinds)]
    lead_band = max(bands, key=lambda b: (b["m"], b["lo"])) if bands else None
    labels = {
        "map_note": (f"{n(len(feats))} מקטעים מצוירים כקווים, בצבע לפי דרגת הדרך; רמפות במחלפים "
                     "באפור דק. הקלידו מספר כביש כדי להדגיש אותו ולהתמקד בו, או לחצו על קו כדי "
                     f"לראות את מספרו ודרגתו. לתצוגה הקווים פושטו (סטייה של עד כ-{n(used_tol)} מ׳)."
                     + ("" if not missing else " מקטע אחד ללא קו בקובץ אינו מצויר." if missing == 1
                        else f" {n(missing)} מקטעים ללא קו בקובץ אינם מצוירים.")),
        "map_aria": (f"מפה אינטראקטיבית של {n(len(feats))} מקטעי דרכים ארציות, קווים בצבע לפי דרגת "
                     "הדרך. גרסה נגישה: רשימת הכבישים בעמוד וטבלת הנתונים מתחתיו."),
        "lat_note": (f"אורך הדרכים הממוספרות לפי רצועות קו רוחב של {_deg(width, width)} מעלות "
                     f"(כ-{n(width * KM_PER_DEG_LAT)} ק\"מ), מצפון לדרום, מחולק לפי דרגת הדרך. "
                     "האורך נמדד על קווי המפה."
                     + (f" הרצועה הצפופה: {_deg(lead_band['lo'], width)} עד "
                        f"{_deg(lead_band['hi'], width)} ({km(lead_band['m'] / 1000, 0)} ק\"מ)."
                        if lead_band else "")),
        "lat_aria": ("גרף עמודות אופקי מוערם: ק\"מ של דרכים ממוספרות לפי רצועת קו רוחב, מצפון "
                     "לדרום, לפי דרגת דרך."
                     + (f" הצפופה ביותר: {_deg(lead_band['lo'], width)} עד "
                        f"{_deg(lead_band['hi'], width)}." if lead_band else "")),
        "lat_caption": "ק\"מ של דרכים ממוספרות לפי רצועת קו רוחב, מצפון לדרום",
    }
    return {"map": model, "legend": legend, "lat": lat_chart, "lat_table": lat_table,
            "labels": labels, "insights": insights, "has_map": bool(feats),
            "has_lat": len(bands) >= 2}


def compute(frames):
    raw = frames["main"].copy()
    cols = ["ROADNUMBER", "ROADCLASS", "LINKTYPE", "NUM_CHANGE", "LENGT_M", "ROADNAME"]
    for c in cols:
        raw[c] = raw[c].map(clean)
    total_rows = len(raw)
    df = raw.drop_duplicates(subset=cols).copy()
    dup_rows = total_rows - len(df)
    df["L"] = pd.to_numeric(df["LENGT_M"].str.replace(",", "", regex=False), errors="coerce")
    df = df[df["L"].notna() & (df["L"] >= 0)].copy()
    df["cls"] = df["ROADCLASS"].where(~df["ROADCLASS"].isin(["", "<Null>"]), "")
    df["num"] = pd.to_numeric(df["ROADNUMBER"], errors="coerce")
    seg_total = len(df)
    km_total = df["L"].sum() / 1000

    # ---- link types ---------------------------------------------------
    lt = (df.assign(lt=df["LINKTYPE"].replace("", "לא צוין"))
            .groupby("lt").agg(segs=("L", "size"), m=("L", "sum")).reset_index())
    lt = lt.sort_values(["segs", "lt"], ascending=[False, True])
    link = {"names": lt["lt"].tolist(), "segs": [int(v) for v in lt["segs"]],
            "km": [round(v / 1000, 1) for v in lt["m"]]}
    ramps = df[df["LINKTYPE"] == RAMP]
    ramp_segs, ramp_km = len(ramps), ramps["L"].sum() / 1000

    # ---- numbered roads -----------------------------------------------
    r = df[(df["LINKTYPE"] == NUMBERED) & df["num"].notna() & (df["num"] > 0)].copy()
    r["rn"] = r["num"].astype(int)
    r["dig"] = r["rn"].astype(str).str.len()
    per_cls = (r.groupby(["rn", "cls"])["L"].sum().reset_index()
                 .sort_values(["rn", "L", "cls"], ascending=[True, False, True]))
    main_cls = per_cls.drop_duplicates("rn").set_index("rn")["cls"]
    roads = r.groupby("rn").agg(m=("L", "sum"), segs=("L", "size"),
                                ncls=("cls", "nunique"), dig=("dig", "first"))
    roads["cls"] = main_cls
    roads["km"] = roads["m"] / 1000
    roads = roads.reset_index()
    n_roads = len(roads)
    road_km = roads["km"].sum()

    # longest roads
    top = roads.sort_values(["km", "rn"], ascending=[False, True]).head(TOP_N)
    classes = sorted(set(roads["cls"]), key=class_key)
    top_chart = {
        "names": [f"כביש {v}" for v in top["rn"]],
        "km": [round(v, 1) for v in top["km"]],
        "cls": [class_label(c) for c in top["cls"]],
        "classes": [class_label(c) for c in classes],
    }
    top_table = [{"name": f"כביש {a.rn}", "cls": class_label(a.cls), "km": km(a.km),
                  "segs": n(a.segs)} for a in top.itertuples()]

    # by class (main class of each road; km by segment class)
    seg_cls = r.groupby("cls")["L"].sum() / 1000
    road_cls = roads.groupby("cls").size()
    cls_rows = [{"key": c, "name": class_label(c), "roads": int(road_cls.get(c, 0)),
                 "km": float(seg_cls.get(c, 0.0))} for c in classes]
    class_chart = {"names": [x["name"] for x in cls_rows],
                   "roads": [x["roads"] for x in cls_rows],
                   "km": [round(x["km"], 1) for x in cls_rows]}
    class_table = [{"name": x["name"], "roads": n(x["roads"]), "km": km(x["km"]),
                    "share": pct(x["km"] / road_km if road_km else 0)} for x in cls_rows]

    # digits x class
    digs = sorted(set(roads["dig"]))
    ct = roads.groupby(["dig", "cls"]).size()
    digit_chart = {
        "names": [DIGIT_LABEL.get(d, f"{d} ספרות") for d in digs],
        "series": [{"name": class_label(c), "data": [int(ct.get((d, c), 0)) for d in digs]}
                   for c in classes],
    }
    digit_table = []
    align = []
    for d in digs:
        sub = roads[roads["dig"] == d]
        counts = sub.groupby("cls").size().reset_index(name="k")
        counts["o"] = counts["cls"].map(lambda c: class_key(c))
        counts = counts.sort_values(["k", "o"], ascending=[False, True])
        lead_c, lead_k = counts.iloc[0]["cls"], int(counts.iloc[0]["k"])
        digit_table.append({"name": DIGIT_LABEL.get(d, f"{d} ספרות"), "roads": n(len(sub)),
                            "km": km(sub["km"].sum()), "lead": class_label(lead_c),
                            "share": pct(lead_k / len(sub))})
        align.append((d, lead_c, lead_k, len(sub)))

    # length distribution
    hist = []
    for lo, hi, lab in LEN_BINS:
        hist.append(int(((roads["km"] >= lo) & (roads["km"] < hi)).sum()))
    keep = list(range(len(hist)))
    len_chart = {"names": [LEN_BINS[i][2] for i in keep], "roads": [hist[i] for i in keep]}
    len_table = [{"name": LEN_BINS[i][2], "roads": n(hist[i]),
                  "share": pct(hist[i] / n_roads if n_roads else 0)} for i in keep]
    median_km = float(roads["km"].median()) if n_roads else 0.0

    # numbering space: leading digit x number of digits
    roads["lead"] = roads["rn"].astype(str).str[0].astype(int)
    space = roads.groupby(["dig", "lead"]).size()
    cells = []
    for yi, d in enumerate(digs):
        for xi, ld in enumerate(range(1, 10)):
            cells.append([xi, yi, int(space.get((d, ld), 0))])
    space_chart = {"x": [str(i) for i in range(1, 10)],
                   "y": [DIGIT_LABEL.get(d, f"{d} ספרות") for d in digs],
                   "cells": cells, "max": max([c[2] for c in cells] + [1])}
    space_table = [{"name": DIGIT_LABEL.get(d, f"{d} ספרות"),
                    "cells": [n(space.get((d, ld), 0)) for ld in range(1, 10)]} for d in digs]

    # road lists (1-2 digits shown open; 3 digits collapsed)
    def road_rows(sub):
        sub = sub.sort_values("rn")
        return [{"num": int(a.rn), "cls": class_label(a.cls), "km": km(a.km),
                 "segs": n(a.segs), "mixed": bool(a.ncls > 1)} for a in sub.itertuples()]
    main_list = road_rows(roads[roads["dig"] <= 2])
    regional_list = road_rows(roads[roads["dig"] == 3])
    local_count = int((roads["dig"] >= 4).sum())
    mixed = roads[roads["ncls"] > 1].sort_values("rn")

    # ---- numbering changes ----------------------------------------------
    df["chg"] = df["NUM_CHANGE"].map(change_month)
    ch = df[df["chg"].notna()].copy()
    ch_valid = ch[ch["chg"] != "?"]
    months = sorted(set(ch_valid["chg"]))
    bad_codes = int((ch["chg"] == "?").sum())
    def roads_in(sub):
        v = pd.to_numeric(sub["ROADNUMBER"], errors="coerce")
        return int(v[v > 0].nunique())
    change_chart = {"names": [month_he(m) for m in months],
                    "segs": [int((ch_valid["chg"] == m).sum()) for m in months],
                    "roads": [roads_in(ch_valid[ch_valid["chg"] == m]) for m in months]}
    change_table = [{"name": change_chart["names"][i], "segs": n(change_chart["segs"][i]),
                     "roads": n(change_chart["roads"][i])} for i in range(len(months))]
    if bad_codes:
        change_table.append({"name": "קוד שאינו תאריך", "segs": n(bad_codes),
                             "roads": n(roads_in(ch[ch["chg"] == "?"]))})
    ch_segs, ch_roads = len(ch), roads_in(ch)

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if n_roads:
        lead = top.iloc[0]
        add("longest", f"כביש {int(lead.rn)} הוא הארוך ברשת: {km(lead.km)} ק\"מ של מקטעים "
            f"({class_label(lead.cls)}), {pct(lead.km / road_km)} מאורך כל הדרכים הממוספרות. "
            f"אחריו כביש {int(top.iloc[1].rn)} ({km(top.iloc[1].km)} ק\"מ) וכביש "
            f"{int(top.iloc[2].rn)} ({km(top.iloc[2].km)} ק\"מ)." if len(top) >= 3 else None)

    good = [a for a in align if a[3] >= 5 and a[2] / a[3] >= ALIGN_SHARE and a[1]]
    big = [a for a in align if a[0] >= 3 and a[3] >= 5]
    if big and all(a in good for a in big):
        parts = [f"{pct(a[2] / a[3], 0)} מהדרכים {DIGIT_PHRASE.get(a[0], f"בנות {a[0]} ספרות")} הן "
                 f"{CLASS_PLURAL.get(a[1], class_label(a[1]))}" for a in big]
        add("digits", "מספר הספרות מסגיר את דרגת הדרך: " + " ו-".join(parts) + ".")

    top10 = roads.sort_values(["km", "rn"], ascending=[False, True]).head(10)
    s10 = top10["km"].sum() / road_km if road_km else 0
    if n_roads >= 50 and s10 >= TOP10_SHARE:
        add("concentration", f"עשרת הכבישים הארוכים מחזיקים {pct(s10)} מאורך הרשת הממוספרת "
            f"({km(top10['km'].sum(), 0)} מתוך {km(road_km, 0)} ק\"מ), אף שהם פחות מ-"
            f"{pct(10 / n_roads)} מ-{n(n_roads)} הדרכים.")

    if n_roads >= 20:
        sh = roads[roads["km"] < 1]
        short = len(sh)
        loc_share = (sh["cls"] == "מקומית").mean() if short else 0
        add("median", f"החציון: {km(median_km)} ק\"מ לדרך. {n(short)} דרכים "
            f"({pct(short / n_roads)}) קצרות מקילומטר"
            + (f", {pct(loc_share, 0)} מהן דרכים מקומיות." if loc_share >= 0.5 else "."))

    if seg_total and ramp_segs / seg_total >= 0.1:
        add("ramps", f"{n(ramp_segs)} מתוך {n(seg_total)} המקטעים ({pct(ramp_segs / seg_total)}) "
            f"הם רמפות של מחלפים, באורך כולל של {km(ramp_km, 0)} ק\"מ. לרמפות אין מספר דרך.")

    if len(mixed) >= 2:
        ex = ", ".join(str(int(v)) for v in mixed["rn"].head(4))
        add("mixed", f"{n(len(mixed))} דרכים משנות דרגה לאורכן, למשל כבישים {ex}: "
            "מקטעים שונים של אותו כביש מסווגים בדרגות שונות.")

    geo = geo_section(frames["geo"])
    for iid, text in geo["insights"]:
        add(iid, text)

    if ch_segs >= 5 and months:
        last = months[-1]
        last_segs = int((ch_valid["chg"] == last).sum())
        last_roads = roads_in(ch_valid[ch_valid["chg"] == last])
        busiest = max(months, key=lambda m: (int((ch_valid["chg"] == m).sum()), m))
        busiest_segs = int((ch_valid["chg"] == busiest).sum())
        txt = (f"{n(ch_segs)} מקטעים ב-{n(ch_roads)} דרכים מסומנים בשינוי מספור. "
               f"העדכון האחרון ({month_he(last)}) נגע ב{segs_he(last_segs)} ב{roads_he(last_roads)}")
        if busiest != last:
            txt += f", והגדול ביותר ({month_he(busiest)}) ב-{n(busiest_segs)} מקטעים"
        add("changes", txt + ".")

    # ---- KPIs, labels -----------------------------------------------------
    kpis = {
        "roads": {"value": n_roads, "display": n(n_roads), "tone": "brand"},
        "km": {"value": round(road_km, 1), "display": km(road_km, 0), "tone": "brand"},
        "ramps": {"value": ramp_segs, "display": n(ramp_segs), "tone": "brand"},
        "changes": {"value": ch_segs, "display": n(ch_segs), "tone": "info" if ch_segs else "brand"},
    }
    lead_txt = (f"כביש {int(top.iloc[0].rn)} ({km(top.iloc[0].km, 0)} ק\"מ)" if n_roads else "")
    labels = {
        "lede": (f"רשימת מספרי הדרכים הארציות שקבע המפקח הארצי על התעבורה: {n(n_roads)} כבישים "
                 f"ממוספרים באורך מקטעים כולל של {km(road_km, 0)} ק\"מ, מכבישים ראשיים חד- ודו-ספרתיים "
                 f"ועד דרכים מקומיות בנות ארבע ספרות, ועוד {n(ramp_segs)} מקטעי רמפה. "
                 f"הארוך ביותר: {lead_txt}. לכל דרך מופיעים דרגתה (מהירה, ראשית, אזורית או מקומית) "
                 "ואורכה, וגם מקטעים שמספרם שונה לאחרונה. מפת הדרכים מציגה כל כביש לפי דרגתו, "
                 "עם חיפוש לפי מספר כביש."),
        "roads_kpi": "כבישים ממוספרים",
        "km_kpi": "ק\"מ מקטעים בדרכים ממוספרות",
        "ramps_kpi": "מקטעי רמפה במחלפים",
        "changes_kpi": "מקטעים עם שינוי מספור",
        "main_note": (f"{n(len(main_list))} הכבישים בעלי ספרה אחת או שתיים, לפי מספר. האורך הוא סכום "
                      "אורכי המקטעים של הדרך; בדרך מחולקת שני מסלוליה עשויים להיספר בנפרד. "
                      "הדרגה היא זו של רוב אורך הדרך."),
        "main_caption": "רשימת הכבישים החד- והדו-ספרתיים: דרגה, אורך ומספר מקטעים",
        "reg_summary": f"הצג את {n(len(regional_list))} הכבישים התלת-ספרתיים (דרכים אזוריות)",
        "reg_caption": "רשימת הכבישים התלת-ספרתיים: דרגה, אורך ומספר מקטעים",
        "local_note": (f"{n(local_count)} הדרכים המקומיות בנות ארבע הספרות מופיעות בחיפוש "
                       "שמתחת לעמוד (חיפוש לפי מספר הדרך)."),
        "top_note": (f"{len(top)} הכבישים הארוכים לפי סכום אורכי המקטעים, צבועים לפי דרגת רוב אורכם. "
                     f"{lead_txt} מוביל."),
        "top_aria": (f"גרף עמודות אופקי: {len(top)} הכבישים הארוכים בישראל לפי אורך מקטעים. "
                     f"המוביל {lead_txt}."),
        "top_caption": f"{len(top)} הכבישים הארוכים לפי אורך מקטעים",
        "class_note": " ".join(
            f"{x['name']}: {n(x['roads'])} כבישים, {km(x['km'], 0)} ק\"מ." for x in cls_rows),
        "class_aria": ("גרף עמודות: מספר הכבישים ואורך המקטעים לפי דרגת דרך. "
                       + " ".join(f"{x['name']} {km(x['km'], 0)} ק\"מ." for x in cls_rows)),
        "class_caption": "כבישים ואורך מקטעים לפי דרגת דרך",
        "digit_note": "מספר הכבישים לפי מספר הספרות במספר הדרך, מחולק לפי דרגת הדרך. "
                      + " ".join(f"{t['name']}: {t['roads']} כבישים, {t['share']} מהן {t['lead']}."
                                 for t in digit_table),
        "digit_aria": "גרף עמודות מוערמות: כבישים לפי מספר ספרות ודרגת דרך. "
                      + " ".join(f"{t['name']}: {t['roads']}." for t in digit_table),
        "digit_caption": "כבישים לפי מספר הספרות ודרגת הדרך המובילה",
        "len_note": (f"התפלגות אורך המקטעים לכל כביש (ק\"מ). החציון {km(median_km)} ק\"מ; "
                     f"{n(hist[-1])} כבישים ארוכים מ-{LEN_BINS[-1][0]} ק\"מ."),
        "len_aria": (f"היסטוגרמה: {n(n_roads)} כבישים לפי טווח אורך בק\"מ. "
                     f"החציון {km(median_km)} ק\"מ."),
        "len_caption": "כבישים לפי טווח אורך (ק\"מ)",
        "space_note": ("כמה מספרי דרך תפוסים לפי הספרה הראשונה ומספר הספרות. כל משבצת סופרת "
                       "כבישים, למשל כבישים תלת-ספרתיים שמתחילים בספרה מסוימת."),
        "space_aria": (f"מפת חום: {n(n_roads)} מספרי דרך לפי ספרה ראשונה ומספר ספרות. "
                       f"התא הצפוף ביותר מכיל {n(space_chart['max'])} כבישים."),
        "space_caption": "כבישים לפי ספרה ראשונה (עמודות) ומספר ספרות (שורות)",
        "link_note": " ".join(f"{a}: {n(b)} מקטעים, {km(c, 0)} ק\"מ."
                              for a, b, c in zip(link["names"], link["segs"], link["km"])),
        "link_aria": ("גרף עמודות: מקטעים לפי סוג קישור. "
                      + " ".join(f"{a} {n(b)}." for a, b in zip(link["names"], link["segs"]))),
        "link_caption": "מקטעים ואורך לפי סוג קישור",
        "change_note": (f"מקטעים שסומנו בקוד שינוי מספור, לפי חודש השינוי ({n(ch_segs)} מקטעים ב-"
                        f"{n(ch_roads)} דרכים)."
                        + (f" {n(bad_codes)} מקטעים נושאים קוד שאינו תאריך תקין ומופיעים בטבלה בלבד."
                           if bad_codes else "")),
        "change_aria": (f"גרף עמודות: מקטעים עם שינוי מספור לפי חודש, {n(len(months))} חודשים. "
                        + (f"האחרון {month_he(months[-1])}." if months else "")),
        "change_caption": "מקטעים ודרכים עם שינוי מספור לפי חודש",
        "method": (f"המאגר כולל {n(total_rows)} מקטעים"
                   + (f"; {n(dup_rows)} שורות כפולות זהות הוסרו מהחישוב" if dup_rows else "")
                   + ". שכבת ה-GIS המלאה (קבצי SHP ו-KMZ) זמינה להורדה מתחת לעמוד."),
    }

    labels.update(geo["labels"])
    flags = {"changes": bool(months), "regional": bool(regional_list),
             "mixed_any": bool(len(mixed)), "map": geo["has_map"], "lat": geo["has_lat"]}

    return {
        "agent_data": {
            "summary_he": (f"רשימת מספרי הדרכים הארציות ומפה: איתור כביש לפי מספר, דרגה ואורך. "
                           f"{n(n_roads)} כבישים ממוספרים, {km(road_km, 0)} ק\"מ, "
                           f"הארוך כביש {int(top.iloc[0].rn)}." if n_roads else
                           "רשימת מספרי הדרכים הארציות ומפה: איתור כביש לפי מספר, דרגה ואורך."),
            "dataset_kind": "map",
            "spatial_coverage": "ארצי",
        },
        "kpis": kpis,
        "charts": {"top": top_chart, "cls": class_chart, "digits": digit_chart,
                   "len": len_chart, "space": space_chart, "link": link,
                   "change": change_chart, "map": geo["map"], "lat": geo["lat"]},
        "tables": {"top": top_table, "cls": class_table, "digits": digit_table,
                   "len": len_table, "space": space_table, "space_x": space_chart["x"],
                   "link": [{"name": a, "segs": n(b), "km": km(c)} for a, b, c in
                            zip(link["names"], link["segs"], link["km"])],
                   "change": change_table, "main": main_list, "regional": regional_list,
                   "legend": geo["legend"], "lat": geo["lat_table"]},
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
