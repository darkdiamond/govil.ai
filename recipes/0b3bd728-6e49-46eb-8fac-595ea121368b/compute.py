"""מתחמי מרכזים מסחריים, באר שבע: one small polygon layer of commercial,
employment and civic areas, read from the uploaded WGS84 GeoJSON map file
(one row per polygon: name, type, area and perimeter attributes, plus the
real polygon geometry in ``__geometry``).

The type column (``remarks``) spells the same class several ways ("מרכזי מסחר
מאורגן" / "מרכז מסחרי מאורגן", "מסחר מוטה רחוב" / "מסחר מלווה רחוב"), so known
spellings are folded into one display type; an unknown spelling flows through
as its own type.  Each type also belongs to a broad family (commerce,
employment, institutions) with a fallback family for new types.

Everything is computed from the polygons: count and area per type, the
largest areas, size bands, shape compactness (4*pi*A/P^2), the distance of
each polygon's centroid from the median centre of all areas, and the extent
of the mapped layer.  Area / perimeter come from the GIS attributes
(SHAPE_Area / SHAPE_Leng, metres in ITM) and fall back to the geometry when
an attribute is missing; centroids come from the geometry and fall back to
the lat/lon attributes.  The polygons themselves go to the page as compact
[feature index, rings] pairs in JSON islands under CHUNK_BYTES.

Order-independent: every sort has a full tie-break (value, name, geometry).
"""
import json
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
TOP_N = 15
LIST_CAP = 200
TYPE_CAP = 10
SIZE_EDGES = [0, 5, 20, 100, 500]          # dunams
DIST_EDGES = [0, 1000, 2000, 3000, 4000]   # metres

# Known spellings -> display type.  Keys are whitespace-collapsed raw values.
TYPE_CANON = {
    "מרכזי מסחר שכונתיים": "מרכז מסחרי שכונתי",
    "מרכז מסחרי שכונתי": "מרכז מסחרי שכונתי",
    "מרכזי מסחר מאורגן": "מרכז מסחרי מאורגן",
    "מרכז מסחרי מאורגן": "מרכז מסחרי מאורגן",
    "מרכז מסחר מאורגן": "מרכז מסחרי מאורגן",
    "מסחר מוטה רחוב": "מסחר לאורך רחוב",
    "מסחר מלווה רחוב": "מסחר לאורך רחוב",
    "אזור תעשייה": "אזור תעשייה",
    "אזורי תעשייה": "אזור תעשייה",
    "אזור תעשיה": "אזור תעשייה",
}
FAMILY = {
    "מרכז מסחרי שכונתי": "מסחר",
    "מרכז מסחרי מאורגן": "מסחר",
    "מסחר לאורך רחוב": "מסחר",
    "שוק": "מסחר",
    "אזור תעשייה": "תעשייה ותעסוקה",
    "פארק הייטק": "תעשייה ותעסוקה",
    "אוניברסיטה": "מוסדות ומרכזים עירוניים",
    "בית חולים": "מוסדות ומרכזים עירוניים",
    "מרכז אזרחי": "מוסדות ומרכזים עירוניים",
    "עיר עתיקה": "מוסדות ומרכזים עירוניים",
}
FAMILY_ORDER = ["מסחר", "תעשייה ותעסוקה", "מוסדות ומרכזים עירוניים", "אחר"]
UNTYPED = "לא מסווג"
WS = re.compile(r"\s+")
CHUNK_BYTES = 40000     # JSON island budget (each <script> block < 50KB)
FAMILY_COLOR = {"מסחר": 0, "תעשייה ותעסוקה": 1, "מוסדות ומרכזים עירוניים": 2, "אחר": 6}


def fmt(n):
    return f"{round(n):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def dun(m2):
    """m² -> dunams, display string."""
    v = m2 / 1000.0
    return f"{v:,.1f}" if v < 100 else fmt(v)


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def clean(s):
    return WS.sub(" ", str(s or "")).strip()


def canon_type(raw):
    r = clean(raw)
    if r == "":
        return UNTYPED
    return TYPE_CANON.get(r, r)


def short_name(name):
    """Drop a leading type prefix ("מרכזי מסחר מאורגן - קניון אביה" -> "קניון אביה")."""
    parts = name.split(" - ", 1)
    if len(parts) == 2 and parts[1].strip() and (parts[0].startswith("מרכז") or parts[0].startswith("אזור")):
        return parts[1].strip()
    return name


def band_labels(edges, unit, scale=1.0):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {fmt(edges[1] / scale)} {unit}")
        elif i + 1 < len(edges):
            out.append(f"{fmt(lo / scale)} עד {fmt(edges[i + 1] / scale)} {unit}")
        else:
            out.append(f"מעל {fmt(lo / scale)} {unit}")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


# ---------- geometry ----------

def _polys(geom):
    """List of polygons (each a list of rings of [lon, lat]) from a GeoJSON geometry."""
    if not isinstance(geom, dict):
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon" and c:
        return [c]
    if t == "MultiPolygon" and c:
        return [p for p in c if p]
    if t == "GeometryCollection":
        return [p for g in geom.get("geometries") or [] for p in _polys(g)]
    return []


def _ring_stats(ring, la0):
    """Planar (local equirectangular) signed area m², perimeter m, centroid sums."""
    kx = M_PER_DEG * math.cos(math.radians(la0))
    pts = [(float(p[0]) * kx, float(p[1]) * M_PER_DEG) for p in ring if len(p) >= 2]
    if len(pts) < 3:
        return 0.0, 0.0, 0.0, 0.0
    a2 = cx = cy = per = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cr = x1 * y2 - x2 * y1
        a2 += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
        per += math.hypot(x2 - x1, y2 - y1)
    return a2 / 2.0, per, cx / 6.0, cy / 6.0


def geo_stats(polys):
    """(area m², perimeter m, centroid lat, centroid lon) or Nones."""
    pts = [p for poly in polys for ring in poly for p in ring if len(p) >= 2]
    if not pts:
        return None, None, None, None
    la0 = sum(float(p[1]) for p in pts) / len(pts)
    kx = M_PER_DEG * math.cos(math.radians(la0))
    area = per = sx = sy = 0.0
    for poly in polys:
        for k, ring in enumerate(poly):
            a, p, cx, cy = _ring_stats(ring, la0)
            sign = 1.0 if k == 0 else -1.0       # holes subtract
            area += sign * abs(a)
            if a:
                f = sign * abs(a) / a
                sx += f * cx
                sy += f * cy
            per += p
    if area <= 0:
        return None, per or None, None, None
    return area, per, (sy / area) / M_PER_DEG, (sx / area) / kx


def _thin(ring, budget):
    """Keep every k-th vertex (and the closing one) so the ring fits the budget."""
    n = len(json.dumps(ring, separators=(",", ":")))
    if n <= budget or len(ring) <= 8:
        return ring
    k = math.ceil(n / float(budget))
    out = ring[:-1:k] + [ring[-1]]
    return out if len(out) >= 4 else ring


def map_features(df):
    """Polygons as [feature index, rings] in islands < CHUNK_BYTES, plus meta."""
    feats = []
    for i, polys in enumerate(df["polys"]):
        for poly in polys:
            rings = [[[round(float(p[0]), 6), round(float(p[1]), 6)] for p in ring if len(p) >= 2]
                     for ring in poly]
            rings = [_thin(r, CHUNK_BYTES // 2) for r in rings if len(r) >= 4]
            if rings:
                feats.append([i, rings])
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
    lons = [p[0] for f in feats for r in f[1] for p in r]
    lats = [p[1] for f in feats for r in f[1] for p in r]
    meta = [{"name": nm, "type": t, "fam": FAMILY_COLOR.get(fm, 6), "area": dun(a)}
            for nm, t, fm, a in zip(df["name"], df["type"], df["family"], df["area"])]
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]] if feats else None
    return {"chunks": chunks, "feats": meta, "bounds": bounds, "n": len(feats)}


def compute(frames):
    raw = frames["geo"]
    empty = pd.Series([""] * len(raw), index=raw.index)
    polys = []
    for g in raw["__geometry"]:
        try:
            polys.append(_polys(json.loads(g or "null")))
        except (ValueError, TypeError):
            polys.append([])
    gs = [geo_stats(p) for p in polys]
    df = pd.DataFrame({
        "name": raw["Name"].map(clean),
        "type": raw["remarks"].map(canon_type),
        "area": num(raw["SHAPE_Area"]),
        "perim": num(raw["SHAPE_Leng"]),
        "la": num(raw["lat"] if "lat" in raw.columns else empty),
        "lo": num(raw["lon"] if "lon" in raw.columns else empty),
        "g_area": [s[0] for s in gs],
        "g_perim": [s[1] for s in gs],
        "g_la": [s[2] for s in gs],
        "g_lo": [s[3] for s in gs],
        "gkey": [str(g) for g in raw["__geometry"]],
    }, index=raw.index)
    df["polys"] = polys
    # attributes first (exact, ITM metres); the geometry fills what is missing
    bad_a = df["area"].isna() | (df["area"] <= 0)
    df.loc[bad_a, "area"] = pd.to_numeric(df.loc[bad_a, "g_area"], errors="coerce")
    bad_p = df["perim"].isna() | (df["perim"] <= 0)
    df.loc[bad_p, "perim"] = pd.to_numeric(df.loc[bad_p, "g_perim"], errors="coerce")
    has_gc = pd.to_numeric(df["g_la"], errors="coerce").notna()
    df.loc[has_gc, "la"] = pd.to_numeric(df.loc[has_gc, "g_la"], errors="coerce")
    df.loc[has_gc, "lo"] = pd.to_numeric(df.loc[has_gc, "g_lo"], errors="coerce")
    n_raw = len(df)
    df = df[(df["name"] != "") & df["area"].notna() & (df["area"] > 0)].copy()
    n_bad = n_raw - len(df)
    df["family"] = df["type"].map(lambda t: FAMILY.get(t, "אחר"))
    df["short"] = df["name"].map(short_name)
    dup_short = df["short"].duplicated(keep=False)
    df.loc[dup_short, "short"] = df.loc[dup_short, "name"]
    df["compact"] = [
        (4 * math.pi * a / (p * p)) if (pd.notna(p) and p > 0) else float("nan")
        for a, p in zip(df["area"], df["perim"])
    ]
    df = df.sort_values(["area", "name", "gkey"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)

    n = len(df)
    total = float(df["area"].sum())
    total_km2 = total / 1e6

    # ---------- per type ----------
    g = df.groupby("type").agg(count=("area", "size"), area=("area", "sum"),
                               med=("area", "median"), comp=("compact", "median")).reset_index()
    g["family"] = g["type"].map(lambda t: FAMILY.get(t, "אחר"))
    g = g.sort_values(["count", "area", "type"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    if len(g) > TYPE_CAP:
        head = g.iloc[:TYPE_CAP - 1].copy()
        tail = g.iloc[TYPE_CAP - 1:]
        sub = df[df["type"].isin(tail["type"])]
        other = pd.DataFrame([{
            "type": "סוגים אחרים", "count": int(tail["count"].sum()), "area": float(tail["area"].sum()),
            "med": float(sub["area"].median()), "comp": float(sub["compact"].median()), "family": "אחר",
        }])
        g = pd.concat([head, other], ignore_index=True)
    types = list(g["type"])
    n_types = int(df["type"].nunique())

    chart_types = {"names": types, "values": [int(v) for v in g["count"]]}
    tbl_types = {"headers": ["סוג מתחם", "מספר מתחמים", "שיעור מהמתחמים"],
                 "rows": [[t, fmt(c), pct(c / n)] for t, c in zip(g["type"], g["count"])]}

    # count share vs area share
    ga = g.sort_values(["area", "type"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    chart_share = {
        "names": list(ga["type"]),
        "count_pct": [round(c / n * 100, 1) for c in ga["count"]],
        "area_pct": [round(a / total * 100, 1) for a in ga["area"]],
    }
    tbl_share = {"headers": ["סוג מתחם", "שטח (דונם)", "שיעור מהשטח", "שיעור מהמתחמים"],
                 "rows": [[t, dun(a), pct(a / total), pct(c / n)]
                          for t, a, c in zip(ga["type"], ga["area"], ga["count"])]}

    # treemap: family -> polygon
    fams = [f for f in FAMILY_ORDER if f in set(df["family"])]
    tree = []
    tbl_fam_rows = []
    for f in fams:
        sub = df[df["family"] == f]
        tree.append({"name": f, "value": round(float(sub["area"].sum()) / 1000, 1),
                     "children": [{"name": s, "value": round(float(a) / 1000, 1), "type": t}
                                  for s, a, t in zip(sub["short"], sub["area"], sub["type"])]})
        tbl_fam_rows.append([f, fmt(len(sub)), dun(sub["area"].sum()), pct(sub["area"].sum() / total)])
    tbl_fam = {"headers": ["משפחה", "מתחמים", "שטח (דונם)", "שיעור מהשטח"], "rows": tbl_fam_rows}

    # top N largest
    top = df.head(TOP_N)
    chart_top = {"names": list(top["short"]), "values": [round(a / 1000, 1) for a in top["area"]],
                 "types": list(top["type"])}
    tbl_top = {"headers": ["מתחם", "סוג", "שטח (דונם)"],
               "rows": [[s, t, dun(a)] for s, t, a in zip(top["short"], top["type"], top["area"])]}

    # size bands (dunams) stacked by family
    size_lbl = band_labels([e * 1000 for e in SIZE_EDGES], "דונם", 1000.0)
    df["size_band"] = [band_index(a / 1000.0, SIZE_EDGES) for a in df["area"]]
    size_series = [{"name": f, "data": [int(((df["family"] == f) & (df["size_band"] == i)).sum())
                                        for i in range(len(SIZE_EDGES))]} for f in fams]
    size_tot = [int((df["size_band"] == i).sum()) for i in range(len(SIZE_EDGES))]
    tbl_size = {"headers": ["גודל המתחם"] + fams + ["סה״כ"],
                "rows": [[size_lbl[i]] + [fmt(s["data"][i]) for s in size_series] + [fmt(size_tot[i])]
                         for i in range(len(SIZE_EDGES))]}

    # compactness per type (median)
    gc = g[g["comp"].notna()].sort_values(["comp", "type"], ascending=[True, True], kind="mergesort")
    chart_comp = {"names": list(gc["type"]), "values": [round(float(v), 2) for v in gc["comp"]]}
    tbl_comp = {"headers": ["סוג מתחם", "מדד קומפקטיות חציוני", "מתחמים"],
                "rows": [[t, f"{v:.2f}", fmt(c)] for t, v, c in zip(gc["type"], gc["comp"], gc["count"])]}

    # distance from median centre
    ok_geo = df["la"].between(29, 34) & df["lo"].between(34, 36)
    has_geo = int(ok_geo.sum()) >= 3
    df["dist"] = float("nan")
    dist_lbl = band_labels(DIST_EDGES, "ק״מ", 1000.0)
    chart_dist, tbl_dist = {"names": [], "series": []}, {"headers": [], "rows": []}
    far = None
    near_share = None
    if has_geo:
        c_la, c_lo = float(df.loc[ok_geo, "la"].median()), float(df.loc[ok_geo, "lo"].median())
        coslat = math.cos(math.radians(c_la))
        df.loc[ok_geo, "dist"] = [math.hypot((la - c_la) * M_PER_DEG, (lo - c_lo) * M_PER_DEG * coslat)
                                  for la, lo in zip(df.loc[ok_geo, "la"], df.loc[ok_geo, "lo"])]
        geo = df[ok_geo].copy()
        geo["dband"] = [band_index(d, DIST_EDGES) for d in geo["dist"]]
        dser = [{"name": f, "data": [int(((geo["family"] == f) & (geo["dband"] == i)).sum())
                                     for i in range(len(DIST_EDGES))]} for f in fams]
        dtot = [int((geo["dband"] == i).sum()) for i in range(len(DIST_EDGES))]
        chart_dist = {"names": dist_lbl, "series": dser}
        tbl_dist = {"headers": ["מרחק ממרכז המתחמים"] + fams + ["סה״כ"],
                    "rows": [[dist_lbl[i]] + [fmt(s["data"][i]) for s in dser] + [fmt(dtot[i])]
                             for i in range(len(DIST_EDGES))]}
        fr = geo.sort_values(["dist", "name"], ascending=[False, True], kind="mergesort").iloc[0]
        far = (fr["short"], float(fr["dist"]), fr["type"])
        near_share = (int((geo["dist"] < 2000).sum()), len(geo))

    # ---------- map (real polygons) ----------
    mp = map_features(df)
    has_map = mp["n"] >= 1 and mp["bounds"] is not None
    mp["fams"] = [{"name": f, "c": FAMILY_COLOR.get(f, 6), "count": int((df["family"] == f).sum())} for f in fams]
    extent = None
    if has_map:
        (s_la, w_lo), (n_la, e_lo) = mp["bounds"]
        mid = (s_la + n_la) / 2.0
        ns_km = (n_la - s_la) * M_PER_DEG / 1000.0
        ew_km = (e_lo - w_lo) * M_PER_DEG * math.cos(math.radians(mid)) / 1000.0
        cen = df[df["la"].notna()].copy()
        if len(cen) >= 3:
            north = cen.sort_values(["la", "name"], ascending=[False, True], kind="mergesort").iloc[0]
            south = cen.sort_values(["la", "name"], ascending=[True, True], kind="mergesort").iloc[0]
            extent = (ns_km, ew_km, north["short"], south["short"])

    # list
    lst = df.head(LIST_CAP)
    tbl_list = {"headers": ["מתחם", "סוג", "שטח (דונם)", "מרחק מהמרכז (ק״מ)"],
                "rows": [[nm, t, dun(a), (f"{d / 1000:,.1f}" if pd.notna(d) else "לא ידוע")]
                         for nm, t, a, d in zip(lst["name"], lst["type"], lst["area"], lst["dist"])]}

    # ---------- insights ----------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    lead_a = ga.iloc[0]
    if lead_a["area"] / total >= 0.3:
        add("area_leader",
            f"{lead_a['type']} תופס {pct(lead_a['area'] / total)} מכלל השטח הממופה "
            f"({dun(lead_a['area'])} דונם ב־{fmt(lead_a['count'])} מתחמים), "
            f"אף שהוא רק {pct(lead_a['count'] / n)} מהמתחמים.")

    lead_c = g.iloc[0]
    if n >= 5 and lead_c["count"] / n >= 0.25 and lead_c["type"] != lead_a["type"]:
        add("count_leader",
            f"הסוג הנפוץ ביותר הוא {lead_c['type']}: {fmt(lead_c['count'])} מתוך {fmt(n)} מתחמים "
            f"({pct(lead_c['count'] / n)}), אך הם מכסים יחד רק {pct(lead_c['area'] / total)} מהשטח.")

    big = df.iloc[0]
    if n >= 3 and big["area"] / total >= 0.15:
        add("largest",
            f"המתחם הגדול ביותר הוא {big['short']} ({big['type']}), בשטח {dun(big['area'])} דונם: "
            f"{pct(big['area'] / total)} מכל השטח הממופה.")

    small = df.iloc[-1]
    if n >= 5:
        ratio = big["area"] / small["area"]
        if ratio >= 100:
            add("spread",
                f"פערי הגודל עצומים: המתחם הקטן ביותר, {small['short']}, משתרע על {fmt(small['area'])} מ״ר בלבד, "
                f"והגדול ביותר גדול ממנו פי {fmt(ratio)}. השטח החציוני של מתחם הוא {dun(df['area'].median())} דונם.")

    gc2 = gc[gc["count"] >= 2]
    if len(gc2) >= 3:
        lo_c = gc2.iloc[0]
        hi_c = gc2.iloc[-1]
        if lo_c["comp"] < 0.35 and hi_c["comp"] - lo_c["comp"] >= 0.2:
            add("shape",
                f"{lo_c['type']} הוא הסוג המוארך ביותר (מדד קומפקטיות חציוני {lo_c['comp']:.2f}), "
                f"לעומת {hi_c['type']} הקומפקטי ביותר ({hi_c['comp']:.2f}). ההשוואה כוללת רק סוגים עם שני מתחמים לפחות.")

    if far is not None and far[1] >= 2000:
        ns, nt = near_share
        add("distance",
            f"{fmt(ns)} מתוך {fmt(nt)} המתחמים ({pct(ns / nt)}) נמצאים במרחק של פחות מ־{fmt(2)} ק״מ ממרכז המתחמים; "
            f"הרחוק ביותר הוא {far[0]} ({far[2]}), כ־{far[1] / 1000:,.1f} ק״מ מהמרכז.")

    nb = df[df["type"] == "מרכז מסחרי שכונתי"]
    org = df[df["type"] == "מרכז מסחרי מאורגן"]
    if len(nb) >= 3 and len(org) >= 3:
        mn, mo = float(nb["area"].median()), float(org["area"].median())
        if mo >= 2 * mn:
            add("nb_vs_mall",
                f"מרכז מסחרי מאורגן חציוני משתרע על {dun(mo)} דונם, פי {mo / mn:,.1f} ממרכז מסחרי שכונתי חציוני "
                f"({dun(mn)} דונם; {fmt(len(org))} ו־{fmt(len(nb))} מתחמים בהתאמה).")
        elif mn >= 2 * mo:
            add("nb_vs_mall",
                f"מרכז מסחרי שכונתי חציוני משתרע על {dun(mn)} דונם, פי {mn / mo:,.1f} ממרכז מסחרי מאורגן חציוני "
                f"({dun(mo)} דונם).")

    if extent is not None and extent[0] >= 1 and extent[2] != extent[3]:
        add("extent",
            f"המתחמים הממופים פרושים על פני כ־{extent[0]:,.1f} ק״מ מצפון לדרום וכ־{extent[1]:,.1f} ק״מ "
            f"ממערב למזרח: הצפוני ביותר הוא {extent[2]} והדרומי ביותר הוא {extent[3]}.")

    if n_bad:
        add("bad", f"{fmt(n_bad)} רשומות ללא שם או ללא שטח תקין אינן נכללות בחישובים.")

    # ---------- kpis ----------
    kpis = {
        "areas": {"value": n, "display": fmt(n), "tone": "brand", "label": "מתחמים ממופים"},
        "total": {"value": round(total_km2, 2), "display": f"{total_km2:,.1f}", "tone": "brand",
                  "label": "שטח כולל (קמ״ר)"},
        "types": {"value": n_types, "display": fmt(n_types), "tone": "info", "label": "סוגי מתחמים"},
        "median": {"value": round(float(df["area"].median()) / 1000, 1), "display": dun(df["area"].median()),
                   "tone": "brand", "label": "שטח חציוני של מתחם (דונם)"},
    }

    # ---------- labels ----------
    comm = df[df["family"] == "מסחר"]
    labels = {
        "lede": (f"המאגר של עיריית באר שבע ממפה {fmt(n)} מתחמים של מרכזי מסחר, קניונים, אזורי תעשייה ומוקדי תעסוקה "
                 f"בעיר, על פני {total_km2:,.1f} קמ״ר. {fmt(len(comm))} מהם מתחמי מסחר (מרכזים שכונתיים, קניונים, "
                 f"שוק ומסחר לאורך רחוב), והשאר אזורי תעשייה, פארק הייטק ומוסדות עירוניים גדולים."),
        "map_note": (f"גבולות {fmt(n)} המתחמים כפי שסומנו בשכבת המיפוי של העירייה, בצבע לפי משפחה. "
                     f"לחיצה על מתחם מציגה את שמו, את סוגו ואת שטחו."),
        "map_aria": f"מפה אינטראקטיבית של גבולות {fmt(n)} המתחמים בבאר שבע",
        "types_note": (f"{fmt(n_types)} סוגי מתחמים. {lead_c['type']} הוא הסוג הנפוץ ביותר, "
                       f"עם {fmt(lead_c['count'])} מתחמים."),
        "types_aria": f"תרשים עמודות: מספר המתחמים לפי סוג, {fmt(len(types))} סוגים",
        "types_cap": "מספר המתחמים לפי סוג",
        "share_note": (f"השוואה בין חלקו של כל סוג במספר המתחמים לבין חלקו בשטח. {lead_a['type']} מוביל בשטח "
                       f"עם {pct(lead_a['area'] / total)}."),
        "share_aria": "תרשים עמודות כפול: שיעור מהמתחמים ושיעור מהשטח לפי סוג מתחם",
        "share_cap": "שטח ושיעור לפי סוג מתחם",
        "tree_note": "כל מלבן הוא מתחם, וגודלו יחסי לשטחו. המתחמים מקובצים לפי משפחה: מסחר, תעשייה ותעסוקה, ומוסדות.",
        "tree_aria": f"מפת עץ של שטחי {fmt(n)} המתחמים לפי משפחה",
        "tree_cap": "שטח לפי משפחת מתחמים",
        "top_note": (f"{fmt(len(top))} המתחמים הגדולים ביותר, בדונמים. הגדול ביותר, {big['short']}, "
                     f"משתרע על {dun(big['area'])} דונם."),
        "top_aria": f"תרשים עמודות אופקי: {fmt(len(top))} המתחמים הגדולים לפי שטח בדונמים",
        "top_cap": "המתחמים הגדולים לפי שטח",
        "size_note": (f"מספר המתחמים בכל טווח גודל, לפי משפחה. "
                      f"{fmt(size_tot[0] + size_tot[1])} מתחמים קטנים מ־{fmt(SIZE_EDGES[2])} דונם."),
        "size_aria": "תרשים עמודות מוערם: מספר המתחמים לפי טווח שטח ומשפחה",
        "size_cap": "התפלגות המתחמים לפי גודל",
        "comp_note": ("מדד הקומפקטיות משווה את צורת המתחם לעיגול: ערך של אחד הוא עיגול מושלם, וערך נמוך מעיד על "
                      "מתחם מוארך או מפוצל, כמו מסחר הנפרש לאורך רחוב."),
        "comp_aria": "תרשים עמודות: מדד קומפקטיות חציוני לפי סוג מתחם",
        "comp_cap": "מדד קומפקטיות חציוני לפי סוג מתחם",
        "dist_note": ("מרחק מרכז כל מתחם מהמרכז החציוני של כל המתחמים, לפי משפחה."
                      + (f" הרחוק ביותר: {far[0]}, כ־{far[1] / 1000:,.1f} ק״מ." if far else "")),
        "dist_aria": "תרשים עמודות מוערם: מספר המתחמים לפי מרחק מהמרכז ומשפחה",
        "dist_cap": "המתחמים לפי מרחק מהמרכז",
        "list_note": f"כל {fmt(min(n, LIST_CAP))} המתחמים, מהגדול לקטן.",
        "list_cap": "רשימת המתחמים",
    }

    temporal = None
    summary = (f"מפת מרכזי המסחר, הקניונים ואזורי התעשייה בבאר שבע: {fmt(n)} מתחמים על פני "
               f"{total_km2:,.1f} קמ״ר, לפי סוג, שטח ומיקום.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "spatial_coverage": "באר שבע",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "types": chart_types,
            "share": chart_share,
            "tree": tree,
            "top": chart_top,
            "size": {"names": size_lbl, "series": size_series},
            "comp": chart_comp,
            "dist": chart_dist,
            "map": mp,
        },
        "tables": {
            "types": tbl_types, "share": tbl_share, "fam": tbl_fam, "top": tbl_top,
            "size": tbl_size, "comp": tbl_comp, "dist": tbl_dist, "list": tbl_list,
        },
        "flags": {"dist": has_geo, "comp": len(gc) >= 2, "map": has_map},
        "insights": insights,
        "labels": labels,
    }
