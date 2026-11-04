"""גינות כלבים בבאר שבע: the city's polygon layer of fenced dog parks.

Read from the uploaded GeoJSON map file (one feature per park: name,
SHAPE_Leng perimeter in metres, SHAPE_Area in square metres, a WGS84
centroid, and the real outline as __geometry).  The page draws the outlines
on a Leaflet map (a dot per park at city zoom, the fence outline once zoomed
in) and covers size (ranking, size bands, concentration), shape (area vs
perimeter, Polsby-Popper compactness 4*pi*A/P^2: 1 is a circle, a square is
about 0.79; end-to-end span measured on the outline) and geography (compass
sector and distance from the median centre, nearest neighbouring park).

Area and perimeter come from the file's SHAPE_* attributes; a feature that
lacks them falls back to the value measured on its outline (disclosed).
The centre of each park is computed from its outline, so a future upload
without lat/lon columns still places it.  The datastore CSV and XLSX are
the same 27 rows without the outlines and are not read.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name and coordinates.
"""
import itertools
import json
import math

import pandas as pd

M_PER_DEG = 111320.0
AREA_EDGES = [0, 400, 700, 1000, 1500]
DIST_EDGES = [0, 1000, 2000, 3000, 4000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
RANK_CAP = 30
NN_TOP = 20
LIST_CAP = 200
TOP_K = 5
CHUNK_BYTES = 40_000   # each geometry island stays well under 50KB
SPAN_POINTS = 400      # vertices sampled per park for the end-to-end span


def fmt(n):
    return f"{round(n):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def band_labels(edges, unit):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {fmt(edges[1])} {unit}")
        elif i + 1 < len(edges):
            out.append(f"{fmt(lo)} עד {fmt(edges[i + 1])} {unit}")
        else:
            out.append(f"מעל {fmt(lo)} {unit}")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


# ── geometry ─────────────────────────────────────────────────────────────


def _polys(raw):
    """Polygon / MultiPolygon as a list of polygons (lists of rings of
    [lon, lat]); anything else (or junk) as []."""
    try:
        g = json.loads(raw or "null")
    except (TypeError, ValueError):
        return []
    if not isinstance(g, dict):
        return []
    if g.get("type") == "Polygon":
        polys = [g.get("coordinates") or []]
    elif g.get("type") == "MultiPolygon":
        polys = g.get("coordinates") or []
    else:
        return []
    out = []
    for p in polys:
        rings = []
        for r in p or []:
            pts = []
            for pt in r or []:
                try:
                    x, y = float(pt[0]), float(pt[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if math.isfinite(x) and math.isfinite(y):
                    pts.append((x, y))
            if len(pts) >= 3:
                rings.append(pts)
        if rings:
            out.append(rings)
    return out


def _measure(polys):
    """(area m², perimeter m, centroid lat, centroid lon, span m) of a park's
    outline, on a local equirectangular projection (parks are tens of metres
    across, so the error is far below the data's precision)."""
    pts = [pt for p in polys for r in p for pt in r]
    if not pts:
        return None
    lat0 = sum(y for _, y in pts) / len(pts)
    lon0 = sum(x for x, _ in pts) / len(pts)
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    ky = M_PER_DEG

    def xy(pt):
        return ((pt[0] - lon0) * kx, (pt[1] - lat0) * ky)

    area = per = cx = cy = 0.0
    for p in polys:
        for k, r in enumerate(p):
            q = [xy(pt) for pt in r]
            if q[0] != q[-1]:
                q.append(q[0])
            a = sx = sy = 0.0
            for (x1, y1), (x2, y2) in itertools.pairwise(q):
                cr = x1 * y2 - x2 * y1
                a += cr
                sx += (x1 + x2) * cr
                sy += (y1 + y2) * cr
                per += math.hypot(x2 - x1, y2 - y1)
            a /= 2.0
            sign = 1.0 if k == 0 else -1.0   # holes subtract
            area += sign * abs(a)
            if a != 0:
                cx += sign * abs(a) * (sx / (6.0 * a))
                cy += sign * abs(a) * (sy / (6.0 * a))
    if area > 0:
        cx, cy = cx / area, cy / area
    else:
        cx = sum(xy(pt)[0] for pt in pts) / len(pts)
        cy = sum(xy(pt)[1] for pt in pts) / len(pts)
    q = sorted({xy(pt) for pt in pts})
    if len(q) > SPAN_POINTS:
        step = len(q) / SPAN_POINTS
        q = [q[int(i * step)] for i in range(SPAN_POINTS)]
    span = 0.0
    for i in range(len(q)):
        for j in range(i + 1, len(q)):
            d = math.hypot(q[i][0] - q[j][0], q[i][1] - q[j][1])
            span = max(span, d)
    return (max(area, 0.0), per, lat0 + cy / ky, lon0 + cx / kx, span)


def _map_model(geo, nn_map, band_names):
    """Outlines as compact [park index, polygons] pairs chunked into JSON
    islands under CHUNK_BYTES, plus per-park popup facts and centres."""
    parks, feats = [], []
    order = geo.sort_values(["name", "kla", "klo", "kar"], kind="mergesort").reset_index(drop=True)
    for i, r in order.iterrows():
        nn = nn_map.get((r["name"], r["kla"], r["klo"]))
        parks.append({
            "name": r["name"],
            "band": int(band_index(r["area"], AREA_EDGES)),
            "area": fmt(r["area"]),
            "per": fmt(r["per"]) if r["per"] > 0 else "",
            "span": fmt(r["span"]) if r["span"] > 0 else "",
            "nn": f"{nn[0]} ({fmt(nn[1])} מ׳)" if nn else "",
            "c": [round(float(r["la"]), 6), round(float(r["lo"]), 6)],
        })
        polys = [[[[round(x, 6), round(y, 6)] for x, y in ring] for ring in p] for p in r["polys"]]
        feats.append([int(i), polys])
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
    lats = [pt[1] for f in feats for p in f[1] for ring in p for pt in ring]
    lons = [pt[0] for f in feats for p in f[1] for ring in p for pt in ring]
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]] if lats else None
    return {"chunks": chunks, "parks": parks, "bands": band_names, "bounds": bounds}


def compute(frames):
    raw = frames["geo"].copy().reset_index(drop=True)
    n_raw = len(raw)
    polys = [_polys(g) for g in raw["__geometry"]]
    meas = [_measure(p) for p in polys]
    a_attr = num(raw["SHAPE_Area"])
    p_attr = num(raw["SHAPE_Leng"])
    # a feature with no outline can still be placed by the file's own centroid
    la_attr = num(raw["lat"]) if "lat" in raw.columns else pd.Series([float("nan")] * n_raw)
    lo_attr = num(raw["lon"]) if "lon" in raw.columns else pd.Series([float("nan")] * n_raw)
    area, per, la, lo, span, a_fb, p_fb = [], [], [], [], [], [], []
    for i, m in enumerate(meas):
        a, p = a_attr.iloc[i], p_attr.iloc[i]
        a_fb.append(bool(not (a > 0) and m and m[0] > 0))
        p_fb.append(bool(not (p > 0) and m and m[1] > 0))
        if a_fb[-1]:
            a = m[0]
        if p_fb[-1]:
            p = m[1]
        area.append(a)
        per.append(p)
        la.append(m[2] if m else la_attr.iloc[i])
        lo.append(m[3] if m else lo_attr.iloc[i])
        span.append(m[4] if m else 0.0)
    df = pd.DataFrame({
        "name": raw["name"].astype(str).str.strip(),
        "per": pd.to_numeric(pd.Series(per), errors="coerce"),
        "area": pd.to_numeric(pd.Series(area), errors="coerce"),
        "la": pd.to_numeric(pd.Series(la), errors="coerce"),
        "lo": pd.to_numeric(pd.Series(lo), errors="coerce"),
        "span": pd.to_numeric(pd.Series(span), errors="coerce").fillna(0.0),
    })
    df["polys"] = polys
    df["a_fb"] = a_fb
    df["p_fb"] = p_fb
    df["kla"] = df["la"].round(5)
    df["klo"] = df["lo"].round(5)
    df["kar"] = df["area"].round(2)
    uniq = df.drop_duplicates(subset=["name", "kla", "klo", "kar"]).copy()
    n_dup = n_raw - len(uniq)
    uniq = uniq.sort_values(["name", "kla", "klo", "kar"], kind="mergesort", na_position="last").reset_index(drop=True)
    n_parks = len(uniq)
    n_names = int(uniq["name"].nunique())
    n_area_fb = int(uniq["a_fb"].sum())
    n_per_fb = int(uniq["p_fb"].sum())

    # ---------- size ----------
    sz = uniq[uniq["area"] > 0].copy()
    n_sz = len(sz)
    n_noarea = n_parks - n_sz
    total_area = float(sz["area"].sum())
    med_area = float(sz["area"].median())
    mean_area = float(sz["area"].mean())
    by_area = sz.sort_values(["area", "name", "kla", "klo"], ascending=[False, True, True, True], kind="mergesort").reset_index(drop=True)

    charts, tables = {}, {}

    top = by_area.head(RANK_CAP)
    charts["area"] = {"names": top["name"].tolist(), "values": [round(v) for v in top["area"]],
                      "median": round(med_area)}
    tables["area"] = {"headers": ["גינה", "שטח (מ״ר)", "שיעור מהשטח הכולל"],
                      "rows": [[a, fmt(b), pct(b / total_area)] for a, b in zip(top["name"], top["area"])]}
    rank_more = max(0, n_sz - RANK_CAP)

    sz["ab"] = sz["area"].map(lambda v: band_index(v, AREA_EDGES))
    bl = band_labels(AREA_EDGES, "מ״ר")
    bcnt = [int((sz["ab"] == i).sum()) for i in range(len(AREA_EDGES))]
    bsum = [float(sz.loc[sz["ab"] == i, "area"].sum()) for i in range(len(AREA_EDGES))]
    charts["bands"] = {"names": bl, "counts": bcnt,
                       "shares": [round(v / total_area * 100, 1) for v in bsum]}
    tables["bands"] = {"headers": ["גודל", "גינות", "שטח (מ״ר)", "שיעור מהשטח"],
                       "rows": [[l, fmt(c), fmt(s), pct(s / total_area)] for l, c, s in zip(bl, bcnt, bsum)]}

    cum = by_area["area"].cumsum() / total_area
    charts["pareto"] = {"ranks": list(range(1, n_sz + 1)), "cum": [round(float(v) * 100, 1) for v in cum],
                        "names": by_area["name"].tolist(), "even": [round((i + 1) / n_sz * 100, 1) for i in range(n_sz)]}
    k = min(TOP_K, n_sz)
    topk_share = float(cum.iloc[k - 1]) if n_sz else 0.0
    half_at = int((cum < 0.5).sum()) + 1
    steps = sorted(set([i for i in range(TOP_K, n_sz + 1, TOP_K)] + [1, n_sz]))
    tables["pareto"] = {"headers": ["מספר הגינות הגדולות", "שיעור מצטבר מהשטח"],
                        "rows": [[fmt(i), pct(float(cum.iloc[i - 1]))] for i in steps]}

    # ---------- shape ----------
    shp = sz[sz["per"] > 0].copy()
    shp["cmp"] = 4 * math.pi * shp["area"] / (shp["per"] ** 2)
    shp = shp.sort_values(["name", "kla", "klo"], kind="mergesort").reset_index(drop=True)
    charts["shape"] = {"points": [[round(float(p), 1), round(float(a), 1), round(float(c), 2), n]
                                  for p, a, c, n in zip(shp["per"], shp["area"], shp["cmp"], shp["name"])],
                       "cmin": round(float(shp["cmp"].min()), 2) if len(shp) else 0,
                       "cmax": round(float(shp["cmp"].max()), 2) if len(shp) else 1}
    has_shape = len(shp) >= 3
    med_cmp = float(shp["cmp"].median()) if len(shp) else 0.0
    total_per = float(shp["per"].sum())

    # ---------- geography ----------
    geo = sz[sz["la"].between(29, 34) & sz["lo"].between(34, 36)].copy().reset_index(drop=True)
    n_geo = len(geo)
    n_bad_geo = n_sz - n_geo
    la0 = float(geo["la"].median())
    lo0 = float(geo["lo"].median())
    coslat = math.cos(math.radians(la0))
    geo["y"] = (geo["la"] - la0) * M_PER_DEG
    geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
    geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5

    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)
    geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]

    xs, ys, names = geo["x"].tolist(), geo["y"].tolist(), geo["name"].tolist()
    nn_d, nn_name = [], []
    for i in range(n_geo):
        best = None
        for j in range(n_geo):
            if i == j:
                continue
            cand = (math.hypot(xs[i] - xs[j], ys[i] - ys[j]), names[j], j)
            if best is None or cand < best:
                best = cand
        nn_d.append(best[0] if best else None)
        nn_name.append(best[1] if best else "")
    geo["nn"] = nn_d
    geo["nn_name"] = nn_name
    has_nn = n_geo >= 2

    scnt = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    ssum = [float(geo.loc[geo["sec"] == i, "area"].sum()) for i in range(len(SECTORS))]
    geo_area = float(geo["area"].sum())
    charts["sectors"] = {"names": SECTORS, "counts": scnt, "areas": [round(v) for v in ssum]}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "גינות", "שטח (מ״ר)"],
                         "rows": [[s, fmt(c), fmt(a)] for s, c, a in zip(SECTORS, scnt, ssum)]}

    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES, "מ׳")
    dcnt = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    dsum = [float(geo.loc[geo["db"] == i, "area"].sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "counts": dcnt, "areas": [round(v) for v in dsum]}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "גינות", "שטח (מ״ר)"],
                      "rows": [[l, fmt(c), fmt(a)] for l, c, a in zip(dl, dcnt, dsum)]}
    med_d = float(geo["d"].median()) if n_geo else 0.0
    within_2k = int((geo["d"] < 2000).sum())

    nn_sorted = geo.sort_values(["nn", "name", "kla", "klo"], ascending=[False, True, True, True], kind="mergesort") if has_nn else geo
    ntop = nn_sorted.head(NN_TOP)
    charts["nn"] = {"names": ntop["name"].tolist(), "values": [round(v) for v in ntop["nn"]] if has_nn else []}
    tables["nn"] = {"headers": ["גינה", "הגינה הקרובה", "מרחק (מ׳)"],
                    "rows": [[a, b, fmt(c)] for a, b, c in zip(ntop["name"], ntop["nn_name"], ntop["nn"])] if has_nn else []}
    nn_more = max(0, n_geo - NN_TOP)
    med_nn = float(geo["nn"].median()) if has_nn else 0.0

    # ---------- full list ----------
    cmp_map = {(r["name"], r["kla"], r["klo"]): r["cmp"] for _, r in shp.iterrows()}
    nn_map = ({(r["name"], r["kla"], r["klo"]): (r["nn_name"], r["nn"]) for _, r in geo.iterrows()}
              if has_nn else {})
    rows = []
    for _, r in by_area.head(LIST_CAP).iterrows():
        key = (r["name"], r["kla"], r["klo"])
        c = cmp_map.get(key)
        nn = nn_map.get(key)
        rows.append([r["name"], fmt(r["area"]), fmt(r["per"]) if r["per"] > 0 else "",
                     fmt(r["span"]) if r["span"] > 0 else "",
                     f"{c:.2f}" if c is not None else "",
                     f"{nn[0]} ({fmt(nn[1])} מ׳)" if nn else ""])
    tables["list"] = {"headers": ["גינה", "שטח (מ״ר)", "היקף (מ׳)", "אורך מקצה לקצה (מ׳)", "מדד קומפקטיות",
                                  "הגינה הקרובה"], "rows": rows}

    # ---------- map ----------
    band_names = band_labels(AREA_EDGES, "מ״ר")
    mapm = _map_model(geo, nn_map, band_names)
    n_drawn = sum(1 for p in geo["polys"] if p)
    has_map = n_geo >= 1 and mapm["bounds"] is not None

    # ---------- span (measured on the outline) ----------
    sp = sz[sz["span"] > 0].sort_values(["span", "name", "kla", "klo"], ascending=[False, True, True, True],
                                        kind="mergesort").reset_index(drop=True)
    med_span = float(sp["span"].median()) if len(sp) else 0.0

    # ---------- insights ----------
    insights = []
    if n_sz >= 2:
        big, small = by_area.iloc[0], by_area.iloc[-1]
        ratio = float(big["area"]) / float(small["area"])
        insights.append({"id": "size", "text_he": (
            f"הגינה הגדולה ביותר היא ״{big['name']}״, {fmt(big['area'])} מ״ר, והקטנה ביותר היא ״{small['name']}״, "
            f"{fmt(small['area'])} מ״ר: פער של פי {ratio:.1f}.")})
        insights.append({"id": "median", "text_he": (
            f"השטח החציוני של גינת כלבים בעיר הוא {fmt(med_area)} מ״ר והממוצע {fmt(mean_area)} מ״ר. "
            f"יחד הגינות משתרעות על {fmt(total_area)} מ״ר (כ־{total_area / 1000:,.1f} דונם).")})

    if n_sz >= 2 * TOP_K:
        even = k / n_sz
        if topk_share >= even * 1.3:
            insights.append({"id": "concentration", "text_he": (
                f"{fmt(k)} הגינות הגדולות ({pct(k / n_sz)} מהגינות) מחזיקות {pct(topk_share)} מהשטח הכולל, "
                f"ומחצית השטח מצטברת כבר ב־{fmt(half_at)} הגינות הגדולות מתוך {fmt(n_sz)}.")})
        else:
            insights.append({"id": "concentration", "text_he": (
                f"השטח מתחלק באופן אחיד יחסית: {fmt(k)} הגינות הגדולות מחזיקות {pct(topk_share)} מהשטח הכולל, "
                f"ומחצית השטח מצטברת רק ב־{fmt(half_at)} הגינות הגדולות מתוך {fmt(n_sz)}.")})

    if has_shape:
        lo_c = shp.sort_values(["cmp", "name", "kla", "klo"], kind="mergesort").iloc[0]
        hi_c = shp.sort_values(["cmp", "name", "kla", "klo"], ascending=[False, True, True, True], kind="mergesort").iloc[0]
        if float(hi_c["cmp"]) - float(lo_c["cmp"]) >= 0.15:
            insights.append({"id": "shape", "text_he": (
                f"מדד הקומפקטיות (1 הוא עיגול, ריבוע מקבל כ־{math.pi / 4:.2f}) נע בין {float(lo_c['cmp']):.2f} ב״{lo_c['name']}״, "
                f"הגינה המוארכת ביותר, ל־{float(hi_c['cmp']):.2f} ב״{hi_c['name']}״; החציון {med_cmp:.2f}.")})
        insights.append({"id": "fence", "text_he": (
            f"ההיקף הכולל של {fmt(len(shp))} הגינות הוא כ־{km(total_per)} ק״מ, כלומר כ־{fmt(total_per / len(shp))} מ׳ "
            f"של גבול בממוצע לגינה.")})

    if len(sp) >= 3:
        lng = sp.iloc[0]
        if float(lng["span"]) >= med_span * 1.3:
            insights.append({"id": "span", "text_he": (
                f"״{lng['name']}״ היא הגינה המתוחה ביותר: {fmt(lng['span'])} מ׳ מקצה לקצה לפי קווי הגדר במפה, "
                f"לעומת {fmt(med_span)} מ׳ בגינה החציונית.")})
        else:
            insights.append({"id": "span", "text_he": (
                f"לפי קווי הגדר במפה, גינת כלבים חציונית משתרעת על {fmt(med_span)} מ׳ מקצה לקצה, "
                f"והארוכה ביותר (״{lng['name']}״) על {fmt(lng['span'])} מ׳.")})

    if has_nn and n_geo >= 3:
        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            partner = nn_sorted.iloc[1]
            mutual = (partner["name"] == iso["nn_name"] and partner["nn_name"] == iso["name"]
                      and abs(float(partner["nn"]) - float(iso["nn"])) < 1)
            if mutual:
                a, b = sorted([iso["name"], iso["nn_name"]])
                txt = (f"״{a}״ ו״{b}״ הן הצמד המבודד ביותר: כל אחת מהן היא הגינה הקרובה לשנייה, במרחק {fmt(iso['nn'])} מ׳, "
                       f"פי {ratio:.1f} מהמרחק החציוני לגינה הקרובה ({fmt(med_nn)} מ׳).")
            else:
                txt = (f"הגינה המבודדת ביותר היא ״{iso['name']}״: גינת הכלבים הקרובה אליה (״{iso['nn_name']}״) נמצאת "
                       f"במרחק {fmt(iso['nn'])} מ׳, פי {ratio:.1f} מהמרחק החציוני לגינה הקרובה ({fmt(med_nn)} מ׳).")
            insights.append({"id": "isolated", "text_he": txt})
        close = geo.sort_values(["nn", "name", "kla", "klo"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 600:
            a, b = sorted([close["name"], close["nn_name"]])
            insights.append({"id": "closest", "text_he": (
                f"הזוג הצמוד ביותר הוא ״{a}״ ו״{b}״, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זו מזו.")})

    if n_geo >= 5:
        ext = (f"הפריסה משתרעת על כ־{km(float(geo['y'].max() - geo['y'].min()))} ק״מ מצפון לדרום "
               f"ועל כ־{km(float(geo['x'].max() - geo['x'].min()))} ק״מ ממזרח למערב.")
        top_s = max(range(len(SECTORS)), key=lambda i: (ssum[i], -i))
        share_s = ssum[top_s] / geo_area if geo_area else 0.0
        if share_s >= 0.25:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון עם שטח הגינות הגדול ביותר ממרכז הגינות הוא {SECTORS[top_s]}: {fmt(scnt[top_s])} גינות "
                f"ו־{fmt(ssum[top_s])} מ״ר ({pct(share_s)} מהשטח). " + ext)})
        else:
            insights.append({"id": "sector", "text_he": (
                f"אין כיוון דומיננטי: בכל כיוון ממרכז הגינות יש לכל היותר {pct(share_s)} משטח הגינות. " + ext)})
        insights.append({"id": "centre", "text_he": (
            f"{fmt(within_2k)} מתוך {fmt(n_geo)} הגינות ({pct(within_2k / n_geo)}) נמצאות עד {fmt(2000)} מ׳ ממרכז החציון "
            f"של הגינות; המרחק החציוני ממנו {fmt(med_d)} מ׳.")})

    if n_dup > 0:
        insights.append({"id": "dups", "text_he": (
            f"הקובץ מכיל {fmt(n_raw)} רשומות, אך רק {fmt(n_parks)} גינות שונות: {fmt(n_dup)} רשומות הן כפילויות מלאות "
            f"ואינן נספרות פעמיים.")})
    if n_names < n_parks:
        insights.append({"id": "names", "text_he": (
            f"יש {fmt(n_parks)} גינות אך רק {fmt(n_names)} שמות שונים: חלק מהשמות משמשים ליותר מגינה אחת.")})
    if n_area_fb or n_per_fb:
        insights.append({"id": "measured", "text_he": (
            f"ל־{fmt(max(n_area_fb, n_per_fb))} גינות חסרים בקובץ נתוני השטח או ההיקף, והם נמדדו כאן ישירות מקווי הגדר במפה.")})
    if n_noarea or n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_noarea)} גינות אין שטח תקין ול־{fmt(n_bad_geo)} נוספות אין מיקום תקין; הן אינן נכללות בחישובים הרלוונטיים.")})

    # ---------- kpis ----------
    kpis = {
        "parks": {"value": n_parks, "display": fmt(n_parks), "tone": "brand", "label": "גינות כלבים בעיר"},
        "area": {"value": round(total_area), "display": fmt(total_area), "tone": "brand",
                 "label": "שטח כולל (מ״ר)"},
        "median": {"value": round(med_area), "display": fmt(med_area), "tone": "info",
                   "label": "שטח חציוני לגינה (מ״ר)"},
        "nn": {"value": round(med_nn), "display": fmt(med_nn), "tone": "info",
               "label": "מרחק חציוני לגינה הקרובה (מטרים)"},
    }

    summary = (
        f"איתור גינות כלבים בבאר שבע על מפה ולפי שם: {fmt(n_parks)} גינות לשחרור כלבים, "
        f"{fmt(total_area)} מ״ר בסך הכול, חציון {fmt(med_area)} מ״ר לגינה."
    )
    lede = (
        f"עיריית באר שבע מפרסמת את שטחי הגינות לשחרור כלבים (פינות כלבים) ברחבי העיר: {fmt(n_parks)} גינות מגודרות "
        f"עם שם, קו גדר על המפה, שטח והיקף. השטח הכולל {fmt(total_area)} מ״ר, הגינה החציונית {fmt(med_area)} מ״ר, "
        f"ובחציון גינת הכלבים הקרובה הבאה נמצאת {fmt(med_nn)} מ׳ משם."
    )
    labels = {
        "lede": lede,
        "map_note": (f"קווי הגדר של {fmt(n_drawn)} גינות הכלבים כפי שהם מופיעים בקובץ המפה של העירייה, בצבע לפי גודל. "
                     f"במבט על העיר כולה כל גינה מסומנת בעיגול; בהתקרבות מופיע קו הגדר. לחיצה פותחת את שם הגינה, השטח, "
                     f"ההיקף והגינה הקרובה."),
        "map_aria": "מפת גינות הכלבים בבאר שבע",
        "pop_area": "שטח (מ״ר)", "pop_per": "היקף (מ׳)", "pop_span": "אורך מקצה לקצה (מ׳)", "pop_nn": "הגינה הקרובה",
        "area_note": (f"כל הגינות לפי שטח, מהגדולה לקטנה; הקו המקווקו מסמן את החציון ({fmt(med_area)} מ״ר)."
                      + (f" מוצגות {fmt(RANK_CAP)} הגדולות מתוך {fmt(n_sz)}." if rank_more else "")),
        "bands_note": f"כמה גינות בכל קבוצת גודל, ואיזה חלק מהשטח הכולל ({fmt(total_area)} מ״ר) כל קבוצה מחזיקה.",
        "pareto_note": (f"השיעור המצטבר מהשטח הכולל כשמסדרים את הגינות מהגדולה לקטנה, לעומת חלוקה שווה; "
                        f"{fmt(k)} הגדולות מחזיקות {pct(topk_share)}."),
        "shape_note": (f"כל נקודה היא גינה: היקף מול שטח, והצבע לפי מדד הקומפקטיות (1 הוא עיגול). "
                       f"גינה מוארכת או בעלת צורה מפותלת נמצאת נמוך ומימין; החציון {med_cmp:.2f}."),
        "sectors_note": "מספר הגינות ושטחן בכל כיוון ביחס למרכז החציון של הגינות.",
        "dist_note": f"מספר הגינות ושטחן לפי מרחק ממרכז החציון של הגינות; המרחק החציוני {fmt(med_d)} מ׳.",
        "nn_note": (f"המרחק בקו אווירי מכל גינה לגינת הכלבים הקרובה אליה, מהמבודדת לצפופה; החציון {fmt(med_nn)} מ׳."
                    + (f" מוצגות {fmt(NN_TOP)} הגינות המבודדות ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "list_note": (f"כל {fmt(n_sz)} הגינות לפי שטח, עם ההיקף, האורך מקצה לקצה, מדד הקומפקטיות והגינה הקרובה."
                      if n_sz <= LIST_CAP else f"{fmt(LIST_CAP)} הגינות הגדולות; הרשימה המלאה בטבלת הנתונים."),
        "area_aria": "גינות כלבים לפי שטח", "area_cap": "גינות כלבים לפי שטח",
        "bands_aria": "גינות לפי קבוצת גודל", "bands_cap": "גינות לפי קבוצת גודל",
        "pareto_aria": "שיעור מצטבר מהשטח לפי גינות מהגדולה לקטנה", "pareto_cap": "ריכוז השטח בגינות הגדולות",
        "shape_aria": "היקף מול שטח לכל גינה",
        "sectors_aria": "גינות ושטח לפי כיוון מהמרכז", "sectors_cap": "גינות ושטח לפי כיוון מהמרכז",
        "dist_aria": "גינות לפי מרחק ממרכז הגינות", "dist_cap": "גינות לפי מרחק ממרכז הגינות",
        "nn_aria": "מרחק כל גינה לגינה הקרובה אליה", "nn_cap": "מרחק לגינה הקרובה",
        "list_cap": "רשימת גינות הכלבים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "map": mapm,
        "flags": {"nn": has_nn, "shape": has_shape, "pareto": n_sz >= 2 * TOP_K, "map": has_map},
    }
