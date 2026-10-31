"""Light-rail depots (maintenance and operation yards), existing and planned.

The only input is the dataset's shapefile (a `map: true` input): one row per
depot polygon with its attributes as strings plus `__geometry` (WGS84
GeoJSON). The page draws the real polygons, places each depot in a
metropolitan area by where it lies, and keeps the attribute analysis (status,
area, size, shape, record vintage). Every number on the page is computed
here; insight rules return None when their premise doesn't hold.
"""
import json
import math
import re

import pandas as pd

# Known statuses, ordered along the delivery pipeline. Unknown statuses
# flow through after these, alphabetically.
STATUS_ORDER = ["קיים", "בביצוע", "מתוכנן"]
STATUS_COLOR = {"קיים": "#0b3668", "בביצוע": "#0068f5", "מתוכנן": "#9fc3f8"}
OTHER_COLOR = "#6c757d"
STATUS_PLURAL = {"קיים": "קיימים", "מתוכנן": "מתוכננים"}
NO_LINE = "ללא קו בשם"
LINE_RE = re.compile(r"קו\s+([^\s\-–]+)")
# Metropolitan areas a depot is placed in: the nearest anchor within
# METRO_RADIUS_KM of the depot's centroid, else OTHER_METRO. Anchors are city
# centres; new depots anywhere else still flow through as OTHER_METRO.
METROS = [
    ("ירושלים", 31.778, 35.215),
    ("גוש דן", 32.075, 34.800),
    ("חיפה", 32.800, 35.000),
    ("באר שבע", 31.252, 34.791),
]
METRO_RADIUS_KM = 35.0
OTHER_METRO = "אזור אחר"
# Size bands in dunams (lower bound inclusive).
BANDS = [(0, 25), (25, 50), (50, 100), (100, None)]
MAX_ROWS = 40          # chart/table cap; the registry holds a dozen today
CHUNK_BYTES = 40_000   # each GeoJSON island stays well under 50KB
CHUNK_POINTS = 1_500   # a longer ring is split into pieces of this many points
EARTH_R = 6_371_000.0


def _f1(v):
    return f"{v:,.1f}"


def _pct(v):
    return f"{v * 100:.0f}%"


def _ym(v):
    v = int(v)
    return f"{v % 100:02d}/{v // 100}"


def _in_depots(k):
    return "במתחם אחד" if k == 1 else f"ב-{k:,} מתחמים"


def _n_depots(k):
    return "מתחם אחד" if k == 1 else f"{k:,} מתחמים"


def _status_key(s):
    return (STATUS_ORDER.index(s), "") if s in STATUS_ORDER else (len(STATUS_ORDER), s)


def _metro_key(m):
    names = [a[0] for a in METROS]
    return (names.index(m), "") if m in names else (len(names), m)


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


# ---------------------------------------------------------------- geometry

def _rings(geom):
    """Outer rings of a Polygon / MultiPolygon as [[lon, lat], ...] lists."""
    if not isinstance(geom, dict):
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c and len(c[0]) >= 3 else []
    if t == "MultiPolygon":
        return [p[0] for p in c if p and len(p[0]) >= 3]
    return []


def _ring_centroid(ring):
    """Area-weighted centroid (lon, lat) and planar area of one ring."""
    a = cx = cy = 0.0
    for (x0, y0, *_), (x1, y1, *_) in zip(ring, ring[1:] + ring[:1]):
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    if abs(a) < 1e-15:
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)), 0.0
    return (cx / (3 * a), cy / (3 * a)), abs(a) / 2


def _centroid(rings):
    pts = [_ring_centroid(r) for r in rings]
    w = sum(a for _, a in pts)
    if w <= 0:
        return pts[0][0]
    return (sum(c[0] * a for c, a in pts) / w, sum(c[1] * a for c, a in pts) / w)


def _hav_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h)) / 1000


def _perimeter_m(rings):
    return sum(_hav_km(a[1], a[0], b[1], b[0]) * 1000
               for r in rings for a, b in zip(r, r[1:] + r[:1]))


def _metro_of(lon, lat):
    best = None
    for name, alat, alon in METROS:
        d = _hav_km(lat, lon, alat, alon)
        if d <= METRO_RADIUS_KM and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else OTHER_METRO


def _line_of(name):
    m = LINE_RE.search(name)
    return f"קו {m.group(1)}" if m else NO_LINE


# ---------------------------------------------------------------- prepare

def _prepare(df):
    df = df.copy()
    get = lambda c: df[c] if c in df.columns else pd.Series([""] * len(df), index=df.index)
    df["name"] = df["NAME"].astype(str).str.strip()
    df["status"] = df["STATUS"].astype(str).str.strip().replace("", "לא צוין")
    geoms = []
    for g in df["__geometry"]:
        try:
            geoms.append(_rings(json.loads(g or "null")))
        except (TypeError, ValueError):
            geoms.append([])
    df["rings"] = geoms
    df = df[df["rings"].map(len) > 0].copy()
    df["dunam"] = _num(df["DUNAM"])
    # Fall back to the attribute polygon area (m²) when DUNAM is blank.
    df["dunam"] = df["dunam"].fillna(_num(get("Shape_Area")) / 1000)
    measured = df["rings"].map(_perimeter_m)
    # Shape_Le_1 matches the drawn polygon; SHAPE_Leng is stale on one row.
    df["perim"] = _num(get("Shape_Le_1")).fillna(_num(get("SHAPE_Leng"))).fillna(measured)
    df["ym"] = _num(get("YEARMONTH"))
    df = df[(df["name"] != "") & df["dunam"].notna() & (df["dunam"] > 0)].copy()
    cents = df["rings"].map(_centroid)
    df["lon"] = [c[0] for c in cents]
    df["lat"] = [c[1] for c in cents]
    df["metro"] = [_metro_of(lo, la) for lo, la in zip(df["lon"], df["lat"])]
    df["line"] = df["name"].map(_line_of)
    df["line_m"] = [l if l == NO_LINE else (f"{l} ({m})" if m != OTHER_METRO else l)
                    for l, m in zip(df["line"], df["metro"])]
    df["compact"] = [
        (4 * math.pi * a * 1000 / p ** 2) if (p == p and p > 0) else None
        for a, p in zip(df["dunam"], df["perim"])
    ]
    df["_g"] = [json.dumps(r, separators=(",", ":")) for r in df["rings"]]
    df = df.sort_values(["dunam", "name", "status", "perim", "_g"],
                        ascending=[False, True, True, True, True], kind="stable")
    return df.reset_index(drop=True)


def _features(df, labels):
    """Map features as [depot index, ring index, points] pieces, chunked into
    JSON islands under CHUNK_BYTES. A ring longer than CHUNK_POINTS is cut
    into pieces that share an end point; the page joins the pieces of a ring
    back into one polygon, so no single feature outgrows an island."""
    feats = []
    for i, rings in enumerate(df["rings"]):
        for ri, r in enumerate(rings):
            pts = [[round(p[0], 5), round(p[1], 5)] for p in r]
            for a in range(0, max(len(pts) - 1, 1), CHUNK_POINTS):
                feats.append([i, ri, pts[a:a + CHUNK_POINTS + 1]])
    chunks, cur, size = [], [], 0
    for f in feats:
        # sized as the template's tojson writes it (", " separators, \u escapes)
        n = len(json.dumps(f)) + 2
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    lons = [p[0] for f in feats for p in f[2]]
    lats = [p[1] for f in feats for p in f[2]]
    meta = [{"name": lab, "status": r["status"], "metro": r["metro"],
             "area": _f1(r["dunam"]), "ym": _ym(r["ym"]) if r["ym"] == r["ym"] else "",
             "c": [round(float(r["lat"]), 5), round(float(r["lon"]), 5)],
             "color": STATUS_COLOR.get(r["status"], OTHER_COLOR)}
            for (_, r), lab in zip(df.iterrows(), labels)]
    return {"chunks": chunks, "depots": meta,
            "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]]}


def _depot_label(r, dup_names):
    return f"{r['name']} ({r['status']})" if r["name"] in dup_names else r["name"]


# ---------------------------------------------------------------- insights

def insight_pipeline(by_status, total):
    planned = by_status.get("מתוכנן")
    if planned is None or total <= 0:
        return None
    share = planned["area"] / total
    if share >= 0.5:
        return (f"רוב שטח הדיפו עדיין על הנייר: {planned['count']:,} מתחמים מתוכננים "
                f"משתרעים על {_f1(planned['area'])} דונם, {_pct(share)} מכלל השטח במאגר.")
    if share >= 0.2:
        return (f"{planned['count']:,} מתחמים מתוכננים משתרעים על {_f1(planned['area'])} דונם, "
                f"{_pct(share)} מכלל השטח במאגר.")
    return None


def insight_operational(by_status, total, n):
    ex = by_status.get("קיים")
    if ex is None or total <= 0:
        return None
    share = ex["area"] / total
    word = "רק" if share < 0.34 else ""
    head = f"{word} {ex['count']:,}".strip()
    return (f"{head} מתוך {n:,} המתחמים פעילים כיום, בשטח של {_f1(ex['area'])} דונם "
            f"({_pct(share)} מהשטח).")


def insight_metro(by_metro, total, n):
    """Which metropolitan area holds most of the depot area."""
    if len(by_metro) < 2 or total <= 0:
        return None
    top, second = by_metro[0], by_metro[1]
    if top["area"] <= second["area"] * 1.1:
        return None
    share = top["area"] / total
    ex = top.get("קיים", 0.0)
    tail = (f", מהם {_f1(ex)} דונם פעילים" if ex > 0 else ", אף אחד מהם עדיין אינו פעיל")
    return (f"{_pct(share)} משטח הדיפו נמצא ב{top['metro']}: {_f1(top['area'])} דונם "
            f"{_in_depots(top['count'])} מתוך {n:,}{tail}. אחריו {second['metro']} עם "
            f"{_f1(second['area'])} דונם {_in_depots(second['count'])}.")


def insight_largest(df):
    if len(df) < 3:
        return None
    top = df.iloc[0]
    med = float(df["dunam"].median())
    if med <= 0:
        return None
    ratio = top["dunam"] / med
    if ratio < 1.5:
        return None
    return (f"המתחם הגדול ביותר הוא {top['name']} ({top['status']}, {top['metro']}), "
            f"{_f1(top['dunam'])} דונם: פי {ratio:.1f} מהחציון ({_f1(med)} דונם).")


def insight_line_lead(by_line, total):
    named = by_line[by_line["line"] != NO_LINE]
    if len(named) < 2 or total <= 0:
        return None
    top, second = named.iloc[0], named.iloc[1]
    if top["area"] <= second["area"] * 1.05:
        return None
    return (f"ל{top['line']} מוקצה השטח הגדול ביותר: {_f1(top['area'])} דונם {_in_depots(int(top['count']))} "
            f"({_pct(top['area'] / total)} מהשטח), לפני {second['line']} עם "
            f"{_f1(second['area'])} דונם. השיוך לקו נגזר משם המתחם ומיקומו.")


def insight_expansion(df):
    """A line (within one metro) with an existing depot and more depot area to come."""
    best = None
    for line, g in df[df["line"] != NO_LINE].groupby("line_m", sort=True):
        ex = g.loc[g["status"] == "קיים", "dunam"].sum()
        more = g.loc[g["status"] != "קיים", "dunam"].sum()
        if ex > 0 and more > 0:
            cand = (more / ex, line, ex, more)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    ratio, line, ex, more = best
    return (f"ב{line} פועלים היום {_f1(ex)} דונם של דיפו, ובתכנון או בביצוע עוד "
            f"{_f1(more)} דונם: תוספת של {_pct(ratio)} לשטח הקיים.")


def insight_vintage(df):
    ym = df["ym"].dropna()
    if ym.empty:
        return None
    latest = int(ym.max())
    n_latest = int((ym == latest).sum())
    if ym.nunique() < 2:
        return f"כל {len(ym):,} הרשומות עודכנו לאחרונה ב-{_ym(latest)}."
    mode = int(ym.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0])
    n_mode = int((ym == mode).sum())
    if mode == latest:
        return (f"העדכון האחרון במאגר הוא מ-{_ym(latest)} ({n_latest:,} רשומות); "
                f"שאר הרשומות ותיקות יותר.")
    newest = df[df["ym"] == latest].sort_values("name")["name"].tolist()
    who = newest[0] if len(newest) == 1 else f"{n_latest:,} מתחמים"
    return (f"{n_mode:,} מתוך {len(ym):,} הרשומות עודכנו לאחרונה ב-{_ym(mode)}; "
            f"הרשומה העדכנית ביותר ({who}) היא מ-{_ym(latest)}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["geo"])
    n = len(df)
    if n == 0:
        raise ValueError("no usable depot polygons in the map file")
    total = float(df["dunam"].sum())

    # status
    statuses = sorted(df["status"].unique(), key=_status_key)
    by_status = {}
    for s in statuses:
        g = df[df["status"] == s]
        by_status[s] = {"count": len(g), "area": float(g["dunam"].sum())}
    status_colors = [STATUS_COLOR.get(s, OTHER_COLOR) for s in statuses]

    # metropolitan area (from the polygon's location)
    by_metro = []
    for m, g in df.groupby("metro", sort=True):
        by_metro.append({"metro": m, "count": len(g), "area": float(g["dunam"].sum()),
                         **{s: float(g.loc[g["status"] == s, "dunam"].sum()) for s in statuses},
                         **{"n_" + s: int((g["status"] == s).sum()) for s in statuses}})
    by_metro.sort(key=lambda r: (r["metro"] == OTHER_METRO, -r["area"], _metro_key(r["metro"])))
    metros = [r["metro"] for r in by_metro]

    # line (parsed from the name, qualified by metro)
    rows = []
    for line, g in df.groupby("line_m", sort=True):
        rows.append({"line": line, "count": len(g), "area": float(g["dunam"].sum()),
                     **{s: float(g.loc[g["status"] == s, "dunam"].sum()) for s in statuses}})
    by_line = pd.DataFrame(rows)
    by_line["_last"] = by_line["line"] == NO_LINE
    by_line = by_line.sort_values(["_last", "area", "line"], ascending=[True, False, True],
                                  kind="stable").reset_index(drop=True)

    # depots
    dup_names = set(df["name"][df["name"].duplicated(keep=False)])
    shown = df.head(MAX_ROWS)
    capped = n > MAX_ROWS
    all_labels = [_depot_label(r, dup_names) for _, r in df.iterrows()]
    # Same name and status twice: number the repeats so labels stay distinct.
    seen = {}
    for i, lab in enumerate(all_labels):
        seen[lab] = seen.get(lab, 0) + 1
        if seen[lab] > 1:
            all_labels[i] = f"{lab} {seen[lab]}"
    depot_labels = all_labels[:MAX_ROWS]

    # size bands
    band_names, band_counts = [], {s: [] for s in statuses}
    for lo, hi in BANDS:
        name = f"{lo}-{hi} דונם" if hi else f"{lo}+ דונם"
        band_names.append(name)
        m = (df["dunam"] >= lo) & ((df["dunam"] < hi) if hi else True)
        for s in statuses:
            band_counts[s].append(int((m & (df["status"] == s)).sum()))
    band_totals = [sum(band_counts[s][i] for s in statuses) for i in range(len(BANDS))]

    # shape
    shape_pts = [[round(float(r["perim"])), round(float(r["dunam"]), 1),
                  round(float(r["compact"]), 2), lab, r["status"]]
                 for (_, r), lab in zip(shown.iterrows(), depot_labels) if r["compact"] == r["compact"]]
    shp = shown[shown["compact"].notna()]
    compact_sorted = shp.sort_values(["compact", "name", "status", "_g"], kind="stable")
    elong = compact_sorted.iloc[0] if len(compact_sorted) else None
    compact = compact_sorted.iloc[-1] if len(compact_sorted) else None

    # vintage
    ym = df["ym"].dropna().astype(int)
    vint = ym.value_counts().sort_index()
    latest_ym = int(ym.max()) if len(ym) else None

    # geographic spread
    north = df.sort_values(["lat", "name", "_g"], ascending=[False, True, True], kind="stable").iloc[0]
    south = df.sort_values(["lat", "name", "_g"], ascending=[True, True, True], kind="stable").iloc[0]
    span_km = _hav_km(float(north["lat"]), float(north["lon"]), float(south["lat"]), float(south["lon"]))

    largest = df.iloc[0]
    median = float(df["dunam"].median())
    ex_area = by_status.get("קיים", {"area": 0.0})["area"]
    ex_share = ex_area / total if total else 0.0

    rules = [
        ("pipeline", insight_pipeline(by_status, total)),
        ("operational", insight_operational(by_status, total, n)),
        ("metro", insight_metro(by_metro, total, n)),
        ("largest", insight_largest(df)),
        ("line_lead", insight_line_lead(by_line, total)),
        ("expansion", insight_expansion(df)),
        ("vintage", insight_vintage(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    status_phrase = ", ".join(
        f"{by_status[s]['count']:,} {STATUS_PLURAL.get(s, s) if by_status[s]['count'] > 1 else s}"
        for s in statuses)
    metro_phrase = ", ".join(f"{r['metro']}: {_n_depots(r['count'])}" for r in by_metro)

    status_table = [{"name": s, "count": f"{by_status[s]['count']:,}",
                     "area": _f1(by_status[s]["area"]),
                     "share": _pct(by_status[s]["area"] / total) if total else "0%",
                     "avg": _f1(by_status[s]["area"] / by_status[s]["count"])}
                    for s in statuses]

    metro_table = [{"name": r["metro"], "count": f"{r['count']:,}", "area": _f1(r["area"]),
                    "share": _pct(r["area"] / total) if total else "0%",
                    "parts": "; ".join(f"{s} {r['n_' + s]:,}" for s in statuses if r["n_" + s])}
                   for r in by_metro]

    line_table = [{"name": r["line"], "count": f"{int(r['count']):,}", "area": _f1(r["area"]),
                   "share": _pct(r["area"] / total) if total else "0%",
                   "parts": "; ".join(f"{s} {_f1(r[s])}" for s in statuses if r[s] > 0)}
                  for _, r in by_line.iterrows()]

    depot_table = [{"name": lab, "status": r["status"], "metro": r["metro"], "area": _f1(r["dunam"]),
                    "share": _pct(r["dunam"] / total) if total else "0%",
                    "perim": f"{round(float(r['perim'])):,}" if r["perim"] == r["perim"] else "",
                    "compact": f"{r['compact']:.2f}" if r["compact"] == r["compact"] else "",
                    "ym": _ym(r["ym"]) if r["ym"] == r["ym"] else ""}
                   for (_, r), lab in zip(shown.iterrows(), depot_labels)]

    cap_note = (f" מוצגים {MAX_ROWS:,} המתחמים הגדולים מתוך {n:,}." if capped else "")
    lines_named = int((by_line["line"] != NO_LINE).sum())
    no_line_n = int(by_line.loc[by_line["line"] == NO_LINE, "count"].sum())

    summary = (f"מפת מתחמי הדיפו של הרכבת הקלה: {n:,} מתחמים ({status_phrase}) "
               f"בשטח כולל של {_f1(total)} דונם, לפי שם, סטטוס ומיקום.")
    if len(summary) > 155:
        summary = (f"מפת מתחמי הדיפו של הרכבת הקלה: {n:,} מתחמים בשטח כולל של {_f1(total)} דונם, "
                   f"לפי שם, סטטוס ומיקום.")

    map_model = _features(df, all_labels)
    spread = (f"המתחמים פרושים לאורך {span_km:,.0f} ק״מ, מ{north['name']} בצפון "
              f"עד {south['name']} בדרום." if n >= 2 and span_km >= 1 else "")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל: " + ", ".join(metros),
        },
        "kpis": {
            "count": {"value": n, "display": f"{n:,}", "tone": "brand"},
            "area": {"value": round(total, 1), "display": _f1(total), "tone": "brand"},
            "ex_share": {"value": round(ex_share, 3), "display": _pct(ex_share),
                         "tone": "warn" if ex_share < 0.5 else "ok"},
            "metros": {"value": len(metros), "display": f"{len(metros):,}", "tone": "info"},
        },
        "charts": {
            "map": map_model,
            "depots": {"names": depot_labels,
                       "area": [round(float(v), 1) for v in shown["dunam"]],
                       "status": list(shown["status"]),
                       "metro": list(shown["metro"]),
                       "colors": [STATUS_COLOR.get(s, OTHER_COLOR) for s in shown["status"]],
                       "median": round(median, 1)},
            "status": {"names": statuses, "colors": status_colors,
                       "count": [by_status[s]["count"] for s in statuses],
                       "area": [round(by_status[s]["area"], 1) for s in statuses],
                       "count_share": [round(by_status[s]["count"] / n * 100, 1) for s in statuses],
                       "area_share": [round(by_status[s]["area"] / total * 100, 1) if total else 0
                                      for s in statuses]},
            "metros": {"names": metros, "statuses": statuses, "colors": status_colors,
                       "series": [[round(r[s], 1) for r in by_metro] for s in statuses],
                       "counts": [r["count"] for r in by_metro]},
            "lines": {"names": list(by_line["line"]), "statuses": statuses, "colors": status_colors,
                      "series": [[round(float(v), 1) for v in by_line[s]] for s in statuses]},
            "bands": {"names": band_names, "statuses": statuses, "colors": status_colors,
                      "series": [band_counts[s] for s in statuses]},
            "shape": {"points": shape_pts, "statuses": statuses, "colors": status_colors},
            "vintage": {"x": [_ym(v) for v in vint.index], "y": [int(c) for c in vint.values]},
        },
        "tables": {
            "status": status_table,
            "metros": metro_table,
            "lines": line_table,
            "depots": depot_table,
            "bands": [{"name": band_names[i], "total": f"{band_totals[i]:,}",
                       "parts": "; ".join(f"{s} {band_counts[s][i]:,}" for s in statuses
                                          if band_counts[s][i])}
                      for i in range(len(BANDS))],
            "vintage": [{"ym": _ym(v), "count": f"{int(c):,}"} for v, c in vint.items()],
        },
        "insights": insights,
        "status_legend": [{"name": s, "color": c} for s, c in zip(statuses, status_colors)],
        "labels": {
            "lede": (f"המאגר של משרד התחבורה ממפה {n:,} מתחמי תחזוקה ותפעול (דיפו וחניוני קרונות) "
                     f"של הרכבת הקלה, קיימים ומתוכננים, בשטח כולל של {_f1(total)} דונם. "
                     f"לכל מתחם מופיעים גבולותיו על המפה, שמו, סטטוס התכנון ({status_phrase}), "
                     f"שטחו בדונמים, היקפו ומועד העדכון האחרון."),
            "count_kpi": "מתחמי דיפו במאגר",
            "area_kpi": "שטח כולל (דונם)",
            "ex_share_kpi": "שיעור השטח במתחמים פעילים",
            "metros_kpi": "אזורי מטרופולין עם דיפו",
            "map_lede": (f"גבולות {n:,} המתחמים על המפה, בצבע לפי סטטוס. בתצוגה הארצית כל מתחם "
                         f"מסומן בעיגול; בהתקרבות מופיע הפוליגון עצמו. לחיצה מציגה את שם המתחם, "
                         f"הסטטוס והשטח. {spread}").strip(),
            "map_aria": f"מפת {n:,} מתחמי הדיפו של הרכבת הקלה, בצבע לפי סטטוס",
            "map_caption": f"רשימת {len(shown):,} המתחמים שעל המפה",
            "metros_lede": (f"השיוך לאזור נקבע לפי מיקום המתחם על המפה (המרכז הקרוב ביותר בטווח "
                            f"{METRO_RADIUS_KM:,.0f} ק״מ): {metro_phrase}."),
            "metros_aria": (f"תרשים עמודות נערמות: שטח הדיפו בדונמים לפי אזור מטרופולין וסטטוס, "
                            f"{len(metros):,} אזורים."),
            "depots_lede": (f"המתחמים מדורגים לפי שטח וצבועים לפי סטטוס. החציון עומד על "
                            f"{_f1(median)} דונם, והגדול ביותר, {largest['name']}, משתרע על "
                            f"{_f1(largest['dunam'])} דונם.{cap_note}"),
            "depots_aria": (f"תרשים עמודות: שטח {len(shown):,} מתחמי דיפו בדונמים, מהגדול "
                            f"({largest['name']}, {_f1(largest['dunam'])}) לקטן."),
            "status_lede": (f"השוואה בין חלקו של כל סטטוס במספר המתחמים ובשטח. " +
                            " ".join(f"{s}: {_n_depots(by_status[s]['count'])}, "
                                     f"{_pct(by_status[s]['area'] / total) if total else '0%'} מהשטח."
                                     for s in statuses)),
            "status_aria": (f"תרשים עמודות: שיעור המתחמים ושיעור השטח לפי סטטוס, "
                            f"{len(statuses):,} סטטוסים."),
            "lines_lede": (f"השיוך לקו נגזר מהמילה \"קו\" בשם המתחם, ולצדו האזור שבו המתחם נמצא "
                           f"(לירושלים ולגוש דן יש קווים באותם צבעים): {lines_named:,} קווים מזוהים"
                           + (f", ו-{no_line_n:,} מתחמים ששמם אינו מציין קו מופיעים בנפרד."
                              if no_line_n else ".")),
            "lines_aria": f"תרשים עמודות נערמות: שטח הדיפו בדונמים לפי קו וסטטוס, {len(by_line):,} קבוצות.",
            "bands_lede": (f"התפלגות המתחמים לפי גודל: " +
                           ", ".join(f"{band_names[i]}: {band_totals[i]:,}" for i in range(len(BANDS)))
                           + "."),
            "bands_aria": f"תרשים עמודות נערמות: מספר המתחמים בכל טווח גודל לפי סטטוס, {len(BANDS):,} טווחים.",
            "shape_lede": (
                (f"מדד הקומפקטיות (בין אפס לאחת, אחת היא עיגול מושלם) משווה שטח להיקף. "
                 f"המתחם המוארך ביותר הוא {elong['name']} ({elong['status']}, {elong['compact']:.2f}), "
                 f"והקומפקטי ביותר {compact['name']} ({compact['status']}, {compact['compact']:.2f}). "
                 f"ככל שהנקודה נמוכה יותר ביחס להיקפה, המתחם צר וארוך יותר.")
                if elong is not None else ""),
            "shape_aria": f"תרשים פיזור: שטח בדונמים מול היקף במטרים, {len(shape_pts):,} מתחמים.",
            "vintage_lede": (f"מועד העדכון האחרון של כל רשומה. הרשומה העדכנית ביותר היא מ-{_ym(latest_ym)}."
                             if latest_ym else ""),
            "vintage_aria": f"תרשים עמודות: מספר הרשומות לפי חודש העדכון האחרון, {len(vint):,} חודשים.",
        },
        "flags": {
            "shape": len(shape_pts) >= 3,
            "vintage": len(vint) >= 1,
            "lines": lines_named >= 1,
            "metros": len(metros) >= 2,
        },
    }
