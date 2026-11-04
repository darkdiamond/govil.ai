"""חבורות קרקע: Israel's soil-association map (Dan & Raz, 1:250,000, 1970),
read from the ministry's uploaded shapefile (a `map: true` input). One
feature per mapped polygon: CODE (the map unit, e.g. "A2"), DESCRIPTIO (the
unit's soil association in words), SHAPE_Area (m², ITM) and SHAPE_Leng
(perimeter, m), plus the polygon itself (`__geometry`, WGS84).

The page reads the soil names out of each description: the unit's primary
soil is the first known soil name it lists (soil associations are named
dominant component first), and the number of distinct soil names gives
single-soil units vs associations. The soil-name list maps known Hebrew
soil terms to a family label; a description with none of them falls into
"אחר", so a new unit always flows through.

Order-independent: rows are sorted by a total key first and float sums use
math.fsum. Nothing here is personal data.
"""
import itertools
import json
import math
import re

import pandas as pd
from govlib import fmt, frame, geo

TOP_SOILS = 10          # soil families shown by name (rest → "אחר")
TOP_UNITS = 15          # bars on the largest-units chart
BAND_DEG = 0.25         # latitude band height for the north-south chart
MIN_BAND_KM2 = 100.0    # a band needs this much mapped area for the north/south insight
SIZE_EDGES = [1, 5, 10, 50, 100]          # polygon-size bins, km²
SMALL_KM2 = 5.0                           # "small polygon" threshold for the fragmentation insight
LEAD_RATIO = 1.15       # leader must beat the runner-up by this factor to be called "the most common"
FRAG_MIN_POLYS = 10     # a unit needs this many polygons for the fragmentation insight
CONC_TOP = 5            # units in the concentration insight
CONC_MIN_UNITS = 10
SLOPE_MIN_KM2 = 100.0   # slope-annotated area needed for the slope insight
COMPACT_MIN_POLYS = 10  # polygons a soil family needs for the compactness chart
COMPACT_RATIO = 0.8     # least-compact family vs overall median, for the insight
MAP_BUDGET = 480_000    # target characters of all map islands
MAP_TOLS = (5, 10, 20, 40, 80, 150, 300, 600)   # simplification ladder, 1e-5° units (~1 m)
OTHER = frame.OTHER

# Known soil terms → family label. Order matters only for equal start
# positions (longer first); the earliest match in a description wins.
SOIL_TERMS = [
    ("קרקעות קולוביות-אלוביות", "קרקעות קולוביות-אלוביות"),
    ("קרקעות קולוביות- אלוביות", "קרקעות קולוביות-אלוביות"),
    ("קרקע קולובית-אלובית", "קרקעות קולוביות-אלוביות"),
    ("קרקעות חומות כהות", "קרקעות חומות כהות"),
    ("קרקעות חומות בהירות", "קרקעות חומות בהירות"),
    ("קרקעות אלוביות", "אלוביום וקרקעות אלוביות"),
    ("קרקעות אורגאניות", "קרקעות אורגניות"),
    ("סלעים חשופים", "סלעים חשופים"),
    ("טרה רוסה", "טרה רוסה"),
    ("פרה-רנדזינה", "פרה-רנדזינה"),
    ("רנדזינה", "רנדזינה"),
    ("פרוטוגרומוסול", "גרומוסול"),
    ("גרומוסול", "גרומוסול"),
    ("סירוזיום", "סירוזיום"),
    ("ליתוסול", "ליתוסול"),
    ("רגוסול", "רגוסול"),
    ("אלוביום", "אלוביום וקרקעות אלוביות"),
    ("סולונצ'ק", "סולונצ'ק"),
    ("קרסנוזיום", "קרסנוזיום"),
    ("חמרה", "חמרה"),
    ("סיין", "סיין"),
    ("נזז", "נזז"),
    ("חול", "חול"),
    ("לס", "לס"),
    ("רג", "רג"),
    ("גלי", "גלי"),
]
_TERM_RES = [(re.compile(r"(?<![א-ת])ו?" + re.escape(t) + r"(?![א-ת])"), lab) for t, lab in SOIL_TERMS]
_LETTERS = re.compile(r"^[A-Za-z]+")
_SLOPE = re.compile(r"(\d+)\s*%|%\s*(\d+)")


# ── parsing ──────────────────────────────────────────────────────────────


def _soils(desc: str) -> list:
    """Distinct soil family labels in order of first appearance."""
    hits = []
    for rx, lab in _TERM_RES:
        for m in rx.finditer(desc):
            hits.append((m.start(), -len(m.group(0)), lab))
    hits.sort()
    out = []
    for _, _, lab in hits:
        if lab not in out:
            out.append(lab)
    return out


def _polys(geom: dict) -> list:
    t = geom.get("type")
    if t == "Polygon":
        return [geom.get("coordinates") or []]
    if t == "MultiPolygon":
        return geom.get("coordinates") or []
    return []


def _ring_xy(ring, lat0):
    kx = 111_320.0 * math.cos(math.radians(lat0))
    return [(float(p[0]) * kx, float(p[1]) * 110_574.0) for p in ring]


def _ring_area_centroid(ring, lat0):
    """Signed-free planar area (m²) and centroid (lon, lat) of one ring."""
    pts = _ring_xy(ring, lat0)
    if len(pts) < 3:
        return 0.0, None
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if a == 0:
        return 0.0, None
    kx = 111_320.0 * math.cos(math.radians(lat0))
    return abs(a) / 2, (cx / (3 * a) / kx, cy / (3 * a) / 110_574.0)


def _geom_info(raw: str):
    """(rings per polygon, geometry area m², centroid lon, centroid lat)."""
    try:
        g = json.loads(raw) if raw else None
    except ValueError:
        g = None
    if not isinstance(g, dict):
        return [], float("nan"), float("nan"), float("nan")
    polys = [[r for r in p if len(r) >= 4] for p in _polys(g)]
    polys = [p for p in polys if p]
    lats = [float(pt[1]) for p in polys for pt in p[0]]
    if not lats:
        return [], float("nan"), float("nan"), float("nan")
    lat0 = (min(lats) + max(lats)) / 2
    parts, total = [], 0.0
    for p in polys:
        a, c = _ring_area_centroid(p[0], lat0)
        holes = math.fsum(_ring_area_centroid(h, lat0)[0] for h in p[1:])
        if c is not None:
            parts.append((a, c))
        total += max(0.0, a - holes)
    if parts and math.fsum(a for a, _ in parts) > 0:
        w = math.fsum(a for a, _ in parts)
        lon = math.fsum(a * c[0] for a, c in parts) / w
        lat = math.fsum(a * c[1] for a, c in parts) / w
    else:
        lon = math.fsum(float(pt[0]) for p in polys for pt in p[0]) / len(lats)
        lat = sum(lats) / len(lats)
    return polys, total, lon, lat


def _load(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame({
        "code": frame.clean_series(df["CODE"]),
        "desc": frame.clean_series(df["DESCRIPTIO"]),
        "area_src": frame.num(df["SHAPE_Area"]),
        "perim": frame.num(df["SHAPE_Leng"]),
        "graw": df["__geometry"].fillna("").astype(str),
    })
    d = d.sort_values(["code", "desc", "area_src", "perim", "graw"], kind="stable",
                      na_position="last").reset_index(drop=True)
    info = [_geom_info(s) for s in d["graw"]]
    d["polys"] = [i[0] for i in info]
    d["area_geo"] = [i[1] for i in info]
    d["lon"] = [i[2] for i in info]
    d["lat"] = [i[3] for i in info]
    area = d["area_src"].where(d["area_src"] > 0, d["area_geo"])
    d["km2"] = area / 1e6
    d = d[d["km2"].notna() & (d["km2"] > 0)].reset_index(drop=True)
    d["code"] = d["code"].where(d["code"] != "", "ללא קוד")
    soils = [_soils(s) for s in d["desc"]]
    d["soil"] = [s[0] if s else OTHER for s in soils]
    d["n_soils"] = [len(s) for s in soils]
    d["letter"] = [(_LETTERS.match(c).group(0).upper() if _LETTERS.match(c) else OTHER) for c in d["code"]]
    slope = []
    for s in d["desc"]:
        if "שיפוע" not in s:
            slope.append("")
        else:
            slope.append("steep" if "ויותר" in s else "moderate")
    d["slope"] = slope
    return d


# ── helpers ──────────────────────────────────────────────────────────────


def _r1(v):
    return round(float(v), 1)


def _wpct(vals, weights, q):
    pairs = sorted(zip(vals, weights))
    tot = math.fsum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * tot:
            return v
    return pairs[-1][0]


def _ranked_sum(d, key, val="km2"):
    """Sum of `val` per `key`, largest first, ties by key."""
    g = d.groupby(key, sort=True)[val].apply(lambda s: math.fsum(s.tolist()))
    return g.sort_values(ascending=False, kind="stable")


def _unit_desc(d):
    """Each code's description: the most common one, ties by text."""
    c = d.groupby(["code", "desc"]).size().reset_index(name="n")
    c = c.sort_values(["code", "n", "desc"], ascending=[True, False, True], kind="stable")
    return dict(zip(c.drop_duplicates("code")["code"], c.drop_duplicates("code")["desc"]))


# ── sections ─────────────────────────────────────────────────────────────


def _soil_order(d):
    s = _ranked_sum(d, "soil")
    named = [k for k in s.index if k != OTHER][:TOP_SOILS]
    has_other = any(k not in named for k in s.index)
    return named + ([OTHER] if has_other else [])


def _soil_chart(d, order, total):
    sk = d["soil"].where(d["soil"].isin(order), OTHER)
    rows = []
    for name in order:
        m = sk == name
        km = math.fsum(d.loc[m, "km2"].tolist())
        rows.append({"name": name, "km2": _r1(km), "share": km / total if total else 0.0,
                     "polys": int(m.sum()), "units": int(d.loc[m, "code"].nunique())})
    return rows, sk


def _treemap(d, udesc):
    letters = _ranked_sum(d, "letter")
    units = d.groupby(["letter", "code"], sort=True)["km2"].apply(lambda s: math.fsum(s.tolist()))
    polys = d.groupby("code", sort=True).size()
    tree, table = [], []
    for L in letters.index:
        u = units.loc[L].sort_values(ascending=False, kind="stable")
        kids = [{"name": c, "value": _r1(v), "desc": udesc.get(c, ""), "n": int(polys.loc[c])}
                for c, v in u.items()]
        tree.append({"name": L, "value": _r1(letters.loc[L]), "children": kids})
        table.append([L, len(kids), fmt.int_he(int(polys.loc[u.index].sum())),
                      fmt.int_he(letters.loc[L]), u.index[0]])
    return tree, table


def _units(d, udesc, total):
    s = _ranked_sum(d, "code")
    polys = d.groupby("code", sort=True).size()
    top = s.iloc[:TOP_UNITS]
    chart = {"codes": list(top.index), "km2": [_r1(v) for v in top],
             "desc": [udesc.get(c, "") for c in top.index],
             "n": [int(polys.loc[c]) for c in top.index]}
    table = [[c, udesc.get(c, "") or "ללא תיאור", fmt.int_he(v), fmt.pct(v / total), fmt.int_he(polys.loc[c])]
             for c, v in top.items()]
    return s, polys, chart, table


def _bands(d, order, sk):
    b = (d["lat"] // BAND_DEG).astype("Int64")
    d = d.assign(band=b, sk=sk)
    d = d[d["band"].notna()]
    if d.empty:
        return None
    lo, hi = int(d["band"].min()), int(d["band"].max())
    ids = list(range(hi, lo - 1, -1))          # north first
    labels = [f"{i * BAND_DEG:.2f}-{(i + 1) * BAND_DEG:.2f}" for i in ids]
    series = []
    for name in order:
        vals = []
        for i in ids:
            m = (d["band"] == i) & (d["sk"] == name)
            vals.append(_r1(math.fsum(d.loc[m, "km2"].tolist())))
        series.append({"name": name, "data": vals})
    totals, leads, table = [], [], []
    for j, i in enumerate(ids):
        t = math.fsum(d.loc[d["band"] == i, "km2"].tolist())
        totals.append(t)
        sub = d[d["band"] == i]
        if sub.empty:
            leads.append(None)
            table.append([labels[j], "0", "", ""])
            continue
        ls = _ranked_sum(sub, "soil")
        leads.append((ls.index[0], ls.iloc[0] / t))
        table.append([labels[j], fmt.int_he(t), ls.index[0], fmt.pct(ls.iloc[0] / t)])
    return {"labels": labels, "series": series, "totals": totals, "leads": leads, "table": table}


def _lat_range(d, order):
    rows = []
    for name in order:
        if name == OTHER:
            continue
        sub = d[d["soil"] == name]
        if sub.empty or sub["lat"].isna().all():
            continue
        sub = sub[sub["lat"].notna()]
        lat, w = sub["lat"].tolist(), sub["km2"].tolist()
        rows.append({"name": name, "p10": round(_wpct(lat, w, 0.1), 2),
                     "p50": round(_wpct(lat, w, 0.5), 2), "p90": round(_wpct(lat, w, 0.9), 2)})
    rows.sort(key=lambda r: (-r["p50"], r["name"]))
    return rows


def _sizes(d, total):
    edges = [0] + SIZE_EDGES + [math.inf]
    labels = []
    for a, b in itertools.pairwise(edges):
        if a == 0:
            labels.append(f"עד {b}")
        elif b == math.inf:
            labels.append(f"{a} ומעלה")
        else:
            labels.append(f"{a}-{b}")
    cnt, share, km = [], [], []
    for a, b in itertools.pairwise(edges):
        m = (d["km2"] >= a) & (d["km2"] < b)
        cnt.append(int(m.sum()))
        k = math.fsum(d.loc[m, "km2"].tolist())
        km.append(k)
        share.append(round(k / total * 100, 1) if total else 0.0)
    table = [[lab, fmt.int_he(c), fmt.int_he(k), fmt.pct_of(s)] for lab, c, k, s in zip(labels, cnt, km, share)]
    return {"labels": labels, "count": cnt, "share": share}, table


def _assoc(d, total):
    cats = [("קרקע אחת", 1, 1), ("שתי קרקעות", 2, 2), ("שלוש קרקעות ומעלה", 3, 99)]
    names, km, units = [], [], []
    for name, a, b in cats:
        m = (d["n_soils"] >= a) & (d["n_soils"] <= b)
        if not m.any():
            continue
        names.append(name)
        km.append(_r1(math.fsum(d.loc[m, "km2"].tolist())))
        units.append(int(d.loc[m, "code"].nunique()))
    table = [[n, fmt.int_he(k), fmt.pct(k / total) if total else "0%", fmt.int_he(u)]
             for n, k, u in zip(names, km, units)]
    return {"names": names, "km2": km, "units": units}, table


def _slope(d):
    s = d[d["slope"] != ""]
    if s.empty:
        return None
    m = _SLOPE.search(" ".join(sorted(set(s["desc"]))))
    thr = (m.group(1) or m.group(2)) if m else None
    order = list(_ranked_sum(s, "soil").index)
    steep, mod = [], []
    for name in order:
        sub = s[s["soil"] == name]
        steep.append(_r1(math.fsum(sub.loc[sub["slope"] == "steep", "km2"].tolist())))
        mod.append(_r1(math.fsum(sub.loc[sub["slope"] == "moderate", "km2"].tolist())))
    tot_steep = math.fsum(s.loc[s["slope"] == "steep", "km2"].tolist())
    tot = math.fsum(s["km2"].tolist())
    table = [[n, fmt.int_he(a), fmt.int_he(b), fmt.pct(a / (a + b)) if a + b else "0%"]
             for n, a, b in zip(order, steep, mod)]
    return {"names": order, "steep": steep, "moderate": mod, "thr": thr,
            "tot": tot, "tot_steep": tot_steep, "table": table}


def _compact(d):
    c = d[(d["perim"] > 0) & d["area_src"].notna() & (d["area_src"] > 0)]
    if c.empty:
        return None
    ci = 4 * math.pi * c["area_src"] / (c["perim"] ** 2)
    c = c.assign(ci=ci.clip(upper=1.0))
    rows = []
    for name, sub in c.groupby("soil", sort=True):
        if name == OTHER or len(sub) < COMPACT_MIN_POLYS:
            continue
        rows.append({"name": name, "med": round(float(sub["ci"].median()), 3), "n": len(sub)})
    if len(rows) < 3:
        return None
    rows.sort(key=lambda r: (r["med"], r["name"]))
    return {"rows": rows, "overall": round(float(c["ci"].median()), 3)}


def _map(d, order, sk, udesc, total):
    lons, lats = [], []
    for ps in d["polys"]:
        for p in ps:
            for pt in p[0]:
                lons.append(float(pt[0]))
                lats.append(float(pt[1]))
    if not lons:
        return None
    o = geo.origin(lons, lats)
    codes = sorted(d["code"].unique().tolist())
    cidx = {c: i for i, c in enumerate(codes)}
    sidx = {s: i for i, s in enumerate(order)}
    rows = d.assign(sk=sk).sort_values(["km2", "code", "lat", "lon"], ascending=[False, True, True, True],
                                       kind="stable")
    items = list(zip(rows["sk"], rows["code"], rows["km2"], rows["polys"]))

    def build(tol):
        out, size = [], 0
        for s, c, km, ps in items:
            rings = []
            for p in ps:
                enc = geo.encode(p, o, tol=tol)
                rings.append(enc)
            f = [sidx[s], cidx[c], _r1(km) if km >= 0.1 else round(float(km), 2), rings]
            size += geo.rendered_len(f) + 2
            out.append(f)
        return out, size

    # Finest tolerance that fits the budget: size falls as the tolerance
    # grows, so binary-search the ladder (≤4 builds instead of up to 8).
    feats, tol = None, MAP_TOLS[-1]
    lo_i, hi_i = 0, len(MAP_TOLS) - 1
    while lo_i <= hi_i:
        mid = (lo_i + hi_i) // 2
        cand, size = build(MAP_TOLS[mid])
        if size <= MAP_BUDGET:
            feats, tol = cand, MAP_TOLS[mid]
            hi_i = mid - 1
        else:
            lo_i = mid + 1
    if feats is None:
        feats, _ = build(MAP_TOLS[-1])
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
    return {"chunks": geo.pack(feats), "origin": o, "scale": geo.SCALE, "tol": tol,
            "units": [[c, udesc.get(c, "")] for c in codes], "soils": order,
            "bounds": [[round(b[0], 4), round(b[1], 4)] for b in bounds]}


# ── insights ─────────────────────────────────────────────────────────────


def _ins_lead(soil_rows):
    named = [r for r in soil_rows if r["name"] != OTHER]
    if len(named) < 2:
        return None
    a, b = named[0], named[1]
    if a["km2"] < b["km2"] * LEAD_RATIO:
        return (f"שתי משפחות הקרקע הנפוצות במפה קרובות בשטחן: {a['name']} ({fmt.pct(a['share'])} מהשטח הממופה) "
                f"ו{b['name']} ({fmt.pct(b['share'])}).")
    return (f"{a['name']} היא הקרקע העיקרית הנפוצה ביותר במפה: {fmt.int_he(a['km2'])} קמ״ר, "
            f"{fmt.pct(a['share'])} מהשטח הממופה, ב-{fmt.int_he(a['polys'])} פוליגונים. "
            f"אחריה {b['name']} עם {fmt.pct(b['share'])}.")


def _ins_north_south(bands):
    if not bands:
        return None
    ok = [(lab, ld) for lab, t, ld in zip(bands["labels"], bands["totals"], bands["leads"])
          if ld and t >= MIN_BAND_KM2]
    if len(ok) < 2:
        return None
    (nl, (ns, nsh)), (sl, (ss, ssh)) = ok[0], ok[-1]
    if ns == ss:
        return (f"{ns} מובילה גם ברצועה הצפונית ביותר (קווי רוחב {nl}) וגם בדרומית ביותר ({sl}), "
                f"בכל רצועה שיש בה לפחות {fmt.int_he(MIN_BAND_KM2)} קמ״ר ממופים.")
    return (f"מצפון לדרום הקרקע מתחלפת: ברצועה הצפונית ביותר (קווי רוחב {nl}) מובילה {ns} "
            f"({fmt.pct(nsh)} משטח הרצועה), ובדרומית ביותר ({sl}) מובילה {ss} ({fmt.pct(ssh)}). "
            f"נכללות רק רצועות שיש בהן לפחות {fmt.int_he(MIN_BAND_KM2)} קמ״ר ממופים.")


def _ins_frag(d, total):
    n = len(d)
    if n < 10:
        return None
    small = d["km2"] < SMALL_KM2
    k = max(1, math.ceil(n * 0.05))
    top = sorted(d["km2"].tolist(), reverse=True)[:k]
    return (f"המפה מפוצלת: {fmt.pct(small.mean())} מהפוליגונים קטנים מ-{fmt.int_he(SMALL_KM2)} קמ״ר "
            f"ומכסים יחד רק {fmt.pct(math.fsum(d.loc[small, 'km2'].tolist()) / total)} מהשטח, "
            f"ואילו {fmt.int_he(k)} הפוליגונים הגדולים ביותר (5% מהם) מכסים "
            f"{fmt.pct(math.fsum(top) / total)}. חציון שטח פוליגון: {fmt.num_he(d['km2'].median())} קמ״ר.")


def _ins_unit_frag(polys, unit_sum, udesc):
    p = polys.sort_index().sort_values(ascending=False, kind="stable")
    c, n = p.index[0], int(p.iloc[0])
    if n < FRAG_MIN_POLYS:
        return None
    desc = udesc.get(c, "")
    what = f" ({desc})" if desc else ""
    return (f"היחידה המפוזרת ביותר היא {c}{what}: {fmt.int_he(n)} פוליגונים נפרדים, "
            f"בממוצע {fmt.num_he(unit_sum.loc[c] / n)} קמ״ר כל אחד.")


def _ins_conc(unit_sum, total):
    if len(unit_sum) < CONC_MIN_UNITS:
        return None
    top = unit_sum.iloc[:CONC_TOP]
    return (f"{CONC_TOP} היחידות הגדולות מתוך {fmt.int_he(len(unit_sum))} ({', '.join(top.index)}) "
            f"מכסות {fmt.pct(math.fsum(top.tolist()) / total)} מהשטח הממופה. "
            f"הגדולה, {top.index[0]}, לבדה {fmt.pct(top.iloc[0] / total)}.")


def _ins_slope(sl):
    if not sl or sl["tot"] < SLOPE_MIN_KM2 or not sl["thr"]:
        return None
    share = sl["tot_steep"] / sl["tot"]
    lean = "רובו" if share > 0.5 else "מיעוטו"
    return (f"ביחידות שהמפה מציינת בהן שיפוע ({fmt.int_he(sl['tot'])} קמ״ר, בעיקר {sl['names'][0]}), "
            f"{lean} על מדרונות תלולים של {sl['thr']}% שיפוע ויותר: {fmt.pct(share)} מהשטח.")


def _ins_assoc(assoc, total):
    if not assoc["names"] or not total:
        return None
    single = dict(zip(assoc["names"], assoc["km2"])).get("קרקע אחת", 0.0)
    multi = total - single
    if multi <= 0:
        return None
    return (f"רוב השטח הממופה הוא צירופי קרקעות ולא קרקע אחת: {fmt.pct(multi / total)} מהשטח ממופה ביחידות "
            f"שתיאורן מונה שתי משפחות קרקע או יותר."
            if multi / total > 0.5 else
            f"{fmt.pct(multi / total)} מהשטח ממופה ביחידות שתיאורן מונה שתי משפחות קרקע או יותר, "
            f"והשאר ביחידות של קרקע אחת.")


def _ins_compact(cp):
    if not cp:
        return None
    lo = cp["rows"][0]
    if not cp["overall"] or lo["med"] > cp["overall"] * COMPACT_RATIO:
        return None
    return (f"לפוליגונים של {lo['name']} הצורה המוארכת והמפותלת ביותר: מדד הקומפקטיות החציוני שלהם "
            f"{fmt.num_he(lo['med'], 2)}, לעומת {fmt.num_he(cp['overall'], 2)} בכלל המפה "
            f"(1 הוא עיגול מושלם).")


# ── main ─────────────────────────────────────────────────────────────────


def compute(frames: dict) -> dict:
    d = _load(frames["geo"])
    if d.empty:
        raise ValueError("no polygons with a usable area")
    total = math.fsum(d["km2"].tolist())
    udesc = _unit_desc(d)
    order = _soil_order(d)
    soil_rows, sk = _soil_chart(d, order, total)
    tree, tree_table = _treemap(d, udesc)
    unit_sum, polys, units_chart, units_table = _units(d, udesc, total)
    bands = _bands(d, order, sk)
    lat_rows = _lat_range(d, order)
    sizes, sizes_table = _sizes(d, total)
    assoc, assoc_table = _assoc(d, total)
    sl = _slope(d)
    cp = _compact(d)
    mp = _map(d, order, sk, udesc, total)

    n_poly, n_units = len(d), int(d["code"].nunique())
    named = [r for r in soil_rows if r["name"] != OTHER]
    lead = named[0] if named else soil_rows[0]

    rules = [("lead", _ins_lead(soil_rows)), ("north_south", _ins_north_south(bands)),
             ("conc", _ins_conc(unit_sum, total)), ("frag", _ins_frag(d, total)),
             ("unit_frag", _ins_unit_frag(polys, unit_sum, udesc)), ("assoc", _ins_assoc(assoc, total)),
             ("slope", _ins_slope(sl)), ("compact", _ins_compact(cp))]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    summary = (f"מפת חבורות הקרקע של ישראל בקנה מידה 1:250,000: {fmt.int_he(n_poly)} פוליגונים ב-"
               f"{fmt.int_he(n_units)} יחידות מיפוי, על פני {fmt.int_he(total)} קמ״ר. "
               f"הקרקע העיקרית הנפוצה ביותר היא {lead['name']} ({fmt.pct(lead['share'])} מהשטח).")
    seo_desc = (f"מפת סוגי הקרקע בישראל: {fmt.int_he(n_units)} יחידות קרקע ו-{fmt.int_he(n_poly)} פוליגונים "
                f"על מפה אינטראקטיבית, עם שטח כל משפחת קרקע. הנפוצה: {lead['name']} ({fmt.pct(lead['share'])}).")

    kpis = {
        "polys": {"value": n_poly, "display": fmt.int_he(n_poly), "tone": "brand"},
        "units": {"value": n_units, "display": fmt.int_he(n_units), "tone": "brand"},
        "area": {"value": round(total), "display": fmt.int_he(total), "tone": "brand"},
        "lead": {"value": round(lead["share"] * 100, 1), "display": fmt.pct(lead["share"]), "tone": "info"},
        "median": {"value": round(float(d["km2"].median()), 2), "display": fmt.num_he(d["km2"].median()),
                   "tone": "brand"},
    }

    top_band = None
    if bands:
        i = max(range(len(bands["totals"])), key=lambda j: (bands["totals"][j], -j))
        top_band = bands["labels"][i]

    labels = {
        "kpi_lead": f"משטח המפה: {lead['name']}, הקרקע העיקרית הנפוצה",
        "map_lede": (f"כל פוליגון צבוע לפי הקרקע העיקרית ביחידה שלו ({fmt.int_he(len(order))} קבוצות בצבע; "
                     f"השאר תחת \"{OTHER}\"). לחיצה על פוליגון מציגה את קוד היחידה, התיאור והשטח. "
                     + (f"קווי המתאר מפושטים לדיוק של כ-{fmt.int_he(mp['tol'])} מטרים כדי שהמפה תיטען מהר."
                        if mp else "")),
        "map_aria": (f"מפה אינטראקטיבית של {fmt.int_he(n_poly)} פוליגוני קרקע, צבועים לפי הקרקע העיקרית; "
                     f"הנפוצה {lead['name']}."),
        "soils_lede": (f"השטח הממופה לפי הקרקע העיקרית של כל יחידה (המשפחה הראשונה שהתיאור מונה). "
                       f"{fmt.int_he(len(named))} המשפחות הגדולות מוצגות בשמן"
                       + (f", והשאר מאוחדות תחת \"{OTHER}\"." if OTHER in order else ".")),
        "soils_aria": f"תרשים עמודות של השטח לפי משפחת קרקע עיקרית; מובילה {lead['name']} עם {fmt.pct(lead['share'])}.",
        "tree_lede": (f"קודי היחידות במפה מקובצים לפי האות שבראשם ({fmt.int_he(len(tree))} אותיות). "
                      f"גודל כל מלבן הוא שטח היחידה; ריחוף מציג את תיאורה."),
        "tree_aria": f"מפת עץ של {fmt.int_he(n_units)} יחידות המיפוי לפי שטח, מקובצות לפי אות הקוד.",
        "units_lede": (f"{fmt.int_he(min(TOP_UNITS, n_units))} יחידות המיפוי הגדולות לפי שטח כולל, "
                       f"עם מספר הפוליגונים שלהן."),
        "units_aria": (f"תרשים עמודות של {fmt.int_he(min(TOP_UNITS, n_units))} היחידות הגדולות; "
                       f"מובילה {unit_sum.index[0]} עם {fmt.int_he(unit_sum.iloc[0])} קמ״ר."),
        "bands_lede": (f"השטח הממופה ברצועות של {BAND_DEG} מעלות רוחב (כ-{fmt.int_he(BAND_DEG * 111)} ק״מ), "
                       f"מצפון לדרום, לפי משפחת הקרקע העיקרית. כל פוליגון משויך לרצועה של מרכזו."
                       + (f" הרצועה הממופה הגדולה: {top_band}." if top_band else "")),
        "bands_aria": "תרשים עמודות מוערמות של השטח לפי רצועת קו רוחב ומשפחת קרקע, מצפון לדרום.",
        "lat_lede": ("היכן כל משפחת קרקע נמצאת לאורך הארץ: הפס נמשך מהעשירון התחתון לעליון של קו הרוחב "
                     "(משוקלל בשטח), והנקודה היא החציון."),
        "lat_aria": "תרשים טווחים של קו הרוחב שבו נמצאת כל משפחת קרקע, מהצפונית לדרומית.",
        "sizes_lede": "כמה פוליגונים יש בכל טווח גודל (קמ״ר), ואיזה חלק מהשטח הם מכסים.",
        "sizes_aria": (f"תרשים עמודות של מספר הפוליגונים ושיעור השטח לפי טווח גודל; "
                       f"חציון {fmt.num_he(d['km2'].median())} קמ״ר."),
        "assoc_lede": "כמה משפחות קרקע מונה תיאור היחידה: קרקע אחת, או צירוף של כמה קרקעות.",
        "assoc_aria": "תרשים טבעת של השטח לפי מספר משפחות הקרקע בתיאור היחידה.",
        "slope_lede": ((f"ביחידות של קרקעות ההר המפה מבחינה בין מדרונות תלולים ({sl['thr']}% שיפוע ויותר) "
                        f"למתונים. השטח לפי הקרקע העיקרית.") if sl and sl["thr"] else
                       "ביחידות שהמפה מציינת בהן שיפוע: השטח לפי הקרקע העיקרית."),
        "slope_aria": "תרשים עמודות מוערמות של שטח במדרונות תלולים ומתונים לפי משפחת קרקע.",
        "compact_lede": (f"מדד קומפקטיות (4π·שטח/היקף²) חציוני לפוליגונים של כל משפחה: 1 הוא עיגול, "
                         f"ערך נמוך הוא צורה מוארכת או מפותלת. רק משפחות עם {COMPACT_MIN_POLYS} פוליגונים לפחות."),
        "compact_aria": "תרשים עמודות של מדד הקומפקטיות החציוני לפי משפחת קרקע.",
    }

    charts = {
        "soils": {"names": [r["name"] for r in soil_rows], "km2": [r["km2"] for r in soil_rows],
                  "share": [round(r["share"] * 100, 1) for r in soil_rows],
                  "polys": [r["polys"] for r in soil_rows]},
        "tree": tree,
        "units": units_chart,
        "bands": ({"labels": bands["labels"], "series": bands["series"]} if bands else None),
        "lat": ({"names": [r["name"] for r in lat_rows], "p10": [r["p10"] for r in lat_rows],
                 "p50": [r["p50"] for r in lat_rows], "p90": [r["p90"] for r in lat_rows]}
                if len(lat_rows) >= 2 else None),
        "sizes": sizes,
        "assoc": assoc if len(assoc["names"]) >= 2 else None,
        "slope": ({"names": sl["names"], "steep": sl["steep"], "moderate": sl["moderate"]} if sl else None),
        "compact": ({"names": [r["name"] for r in cp["rows"]], "med": [r["med"] for r in cp["rows"]],
                     "n": [r["n"] for r in cp["rows"]], "overall": cp["overall"]} if cp else None),
        "map": mp,
    }
    tables = {
        "soils": [[r["name"], fmt.int_he(r["km2"]), fmt.pct(r["share"]), fmt.int_he(r["polys"]),
                   fmt.int_he(r["units"])] for r in soil_rows],
        "tree": tree_table,
        "units": units_table,
        "bands": bands["table"] if bands else [],
        "lat": [[r["name"], f"{r['p10']:.2f}", f"{r['p50']:.2f}", f"{r['p90']:.2f}"] for r in lat_rows],
        "sizes": sizes_table,
        "assoc": assoc_table,
        "slope": sl["table"] if sl else [],
        "compact": ([[r["name"], fmt.num_he(r["med"], 2), fmt.int_he(r["n"])] for r in cp["rows"]] if cp else []),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מפת סוגי הקרקע בישראל | חבורות קרקע",
                "description": seo_desc,
                "name": "מפת חבורות הקרקע של ישראל",
                "alternate_names": ["חבורות קרקע", "מפת קרקעות ישראל", "סוגי קרקע בישראל",
                                    "מפת הקרקעות של דן ורז"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
    }
