"""Industrial zones of the Industrial Zones Administration (Ministry of Economy).

One row per industrial zone: name, district, marketed land (available /
occupied, square metres), whether the zone is open to marketing, a contact,
an optional website / description, sample factory lists by size class, and
the zone boundary as WKT in ITM (EPSG:2039).

Land figures are lot areas reported by the administration, in m², shown in
dunams (1 dunam = 1,000 m²). The boundary polygon is a separate, larger
measure (it includes roads and public land); its area is computed here with
the shoelace formula in ITM metres (a conformal grid, error well under 1%).

The map shows simplified outlines converted to WGS84 with an inline
Transverse Mercator inverse (GRS80, ITM parameters) plus a 3-parameter shift
to WGS84 (a few metres; far below what the outline simplification removes).
The simplification tolerance doubles until the whole map fits a fixed vertex
budget, so new or more detailed zones keep the map's script block small.
"""
import math
import re

import pandas as pd

DUNAM = 1000.0
TOP_LAND = 20
TOP_AREA = 15
TOP_FACT = 15
MAP_VERTEX_BUDGET = 1500
MIN_RING_M2 = 2000.0
NEARLY_FULL = 0.95
OPEN_WORDS = {"TRUE", "true", "True", "1", "כן"}
UNKNOWN_DEV = "יזם לא ידוע"

# --- ITM (EPSG:2039) -> WGS84 -------------------------------------------------
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_K0 = 1.0000067
_LAT0 = math.radians(31.7343936111111)
_LON0 = math.radians(35.2045169444444)
_FE = 219529.584
_FN = 626907.39
_DX, _DY, _DZ = -24.0024, -17.1032, -17.8444  # Israel 1993 -> WGS84
_WGS_A = 6378137.0
_WGS_F = 1 / 298.257223563


def _meridian_arc(phi):
    e2 = _E2
    e4, e6 = e2 * e2, e2 * e2 * e2
    return _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                 - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                 - (35 * e6 / 3072) * math.sin(6 * phi))


_M0 = _meridian_arc(_LAT0)


def _itm_to_grs80(x, y):
    e2 = _E2
    ep2 = e2 / (1 - e2)
    m = _M0 + (y - _FN) / _K0
    mu = m / (_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = ep2 * c * c
    t1 = t * t
    n1 = _A / math.sqrt(1 - e2 * s * s)
    r1 = _A * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = phi1 - (n1 * t / r1) * (
        d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / c
    return lat, lon


def _shift(lat, lon):
    s, c = math.sin(lat), math.cos(lat)
    n = _A / math.sqrt(1 - _E2 * s * s)
    X = n * c * math.cos(lon) + _DX
    Y = n * c * math.sin(lon) + _DY
    Z = n * (1 - _E2) * s + _DZ
    e2 = _WGS_F * (2 - _WGS_F)
    p = math.hypot(X, Y)
    lat2 = math.atan2(Z, p * (1 - e2))
    for _ in range(5):
        s2 = math.sin(lat2)
        n2 = _WGS_A / math.sqrt(1 - e2 * s2 * s2)
        lat2 = math.atan2(Z + e2 * n2 * s2, p)
    return math.degrees(lat2), math.degrees(math.atan2(Y, X))


def itm_to_wgs84(x, y):
    lat, lon = _itm_to_grs80(x, y)
    return _shift(lat, lon)


# --- WKT -----------------------------------------------------------------------
def _parse_ring(txt):
    pts = []
    for p in txt.split(","):
        parts = p.split()
        if len(parts) < 2:
            continue
        try:
            pts.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return pts


def parse_wkt(w):
    """POLYGON / MULTIPOLYGON -> list of polygons, each [outer, *holes]."""
    w = (w or "").strip()
    head = w.split("(", 1)[0].strip().upper()
    if head not in ("POLYGON", "MULTIPOLYGON") or "(" not in w:
        return []
    body = w[w.index("("):]
    if head == "POLYGON":
        polys_txt = [body.strip()[1:-1]]
    else:
        inner = body.strip()[1:-1]
        polys_txt = re.split(r"\)\s*\)\s*,\s*\(\s*\(", inner)
    polys = []
    for pt in polys_txt:
        pt = pt.strip().lstrip("(").rstrip(")")
        rings = [_parse_ring(r) for r in re.split(r"\)\s*,\s*\(", pt)]
        rings = [r for r in rings if len(r) >= 3]
        if rings:
            polys.append(rings)
    return polys


def _signed_area(r):
    s = 0.0
    n = len(r)
    for i in range(n):
        x1, y1 = r[i]
        x2, y2 = r[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2


def _centroid(r):
    a = _signed_area(r)
    if a == 0:
        return None
    cx = cy = 0.0
    n = len(r)
    for i in range(n):
        x1, y1 = r[i]
        x2, y2 = r[(i + 1) % n]
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    return cx / (6 * a), cy / (6 * a), abs(a)


def geom_stats(polys):
    area = 0.0
    wx = wy = wsum = 0.0
    for poly in polys:
        outer = abs(_signed_area(poly[0]))
        holes = sum(abs(_signed_area(h)) for h in poly[1:])
        area += max(outer - holes, 0.0)
        c = _centroid(poly[0])
        if c:
            wx += c[0] * c[2]
            wy += c[1] * c[2]
            wsum += c[2]
    cen = (wx / wsum, wy / wsum) if wsum > 0 else None
    return area, cen


def _dp(pts, tol):
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        den = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for k in range(i + 1, j):
            x0, y0 = pts[k]
            if den == 0:
                dist = math.hypot(x0 - x1, y0 - y1)
            else:
                dist = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / den
            if dist > best:
                best, idx = dist, k
        if idx >= 0 and best > tol:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [p for p, k in zip(pts, keep) if k]


def _simplify_outers(polys, tol):
    out = []
    for poly in polys:
        outer = poly[0]
        if abs(_signed_area(outer)) < MIN_RING_M2:
            continue
        ring = outer if outer[0] != outer[-1] else outer[:-1]
        s = _dp(ring + [ring[0]], tol)[:-1]
        if len(s) >= 3:
            out.append(s)
    return out


# --- helpers ---------------------------------------------------------------------
def _int(v):
    return f"{int(round(v)):,}"


def _dun(v):
    return f"{v / DUNAM:,.0f}"


def _pct(v):
    return f"{v * 100:.1f}%"


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _num(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(",", "").str.strip(),
                         errors="coerce").fillna(0.0).clip(lower=0)


def _entries(txt):
    txt = str(txt or "")
    if not txt.strip():
        return []
    parts = re.split(r"<br\s*/?>|\n", txt)
    out = []
    for p in parts:
        p = re.sub(r"<[^>]+>", "", p)
        p = _norm(p)
        if p and p != UNKNOWN_DEV:
            out.append(p)
    return out


def _join_names(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " ו" + names[-1]


def _prepare(df):
    d = pd.DataFrame({
        "zid": pd.to_numeric(df["alina_id"], errors="coerce"),
        "name": df["alina_name"].map(_norm),
        "district": df["district"].map(_norm),
        "avail": _num(df["available_space"]).values,
        "occ": _num(df["occupied_space"]).values,
        "open": df["open_to_market"].map(lambda v: _norm(v) in OPEN_WORDS),
        "website": df["website"].map(lambda v: bool(_norm(v))),
        "desc": df["alina_description"].map(lambda v: bool(_norm(re.sub(r"<[^>]+>", "", str(v))))),
        "phone": df["contact_phone"].map(lambda v: bool(_norm(v))),
        "email": df["contact_email"].map(lambda v: bool(_norm(v))),
        "contact": df["contact_name"].map(lambda v: bool(_norm(v))),
        "small": df["small_factories"].map(_entries),
        "medium": df["medium_factories"].map(_entries),
        "big": df["big_factories"].map(_entries),
        "geom": df["geom"],
    })
    d = d[d["name"] != ""].copy()
    d.loc[d["district"] == "", "district"] = "לא צוין"
    d["zid"] = d["zid"].fillna(-1)
    d = d.sort_values(["name", "zid"], kind="stable").reset_index(drop=True)
    d["total"] = d["avail"] + d["occ"]
    d["n_small"] = d["small"].map(len)
    d["n_medium"] = d["medium"].map(len)
    d["n_big"] = d["big"].map(len)
    d["n_fact"] = d["n_small"] + d["n_medium"] + d["n_big"]
    polys = d["geom"].map(parse_wkt)
    stats = polys.map(geom_stats)
    d["polys"] = polys
    d["area"] = stats.map(lambda s: s[0])
    d["cen"] = stats.map(lambda s: s[1])
    return d


# --- insights -----------------------------------------------------------------
def insight_avail_leader(land, tot_avail):
    if tot_avail <= 0 or land.empty:
        return None
    top = land.sort_values(["avail", "name"], ascending=[False, True], kind="stable").iloc[0]
    share = top["avail"] / tot_avail
    if share < 0.25:
        return None
    return (f"באזור {top['name']} לבדו נמצאים {_dun(top['avail'])} דונם פנויים, "
            f"{_pct(share)} מכל השטח הפנוי במאגר.")


def insight_occupancy(land):
    if len(land) < 3:
        return None
    tot = land["total"].sum()
    occ = land["occ"].sum()
    if tot <= 0:
        return None
    full = land[land["occ"] / land["total"] >= NEARLY_FULL].sort_values("name", kind="stable")
    base = (f"באזורים שמדווחים על שטחים, {_pct(occ / tot)} מהשטח המשווק כבר תפוס "
            f"({_dun(occ)} מתוך {_dun(tot)} דונם)")
    if len(full) >= 2:
        names = list(full["name"])
        shown = names[:4]
        rest = len(names) - len(shown)
        tail = f" ועוד {rest}" if rest > 0 else ""
        return (base + f". ב-{len(full)} אזורים התפוסה מגיעה ל-{NEARLY_FULL * 100:.0f}% "
                f"ומעלה: {', '.join(shown)}{tail}.")
    return base + "."


def insight_no_data(d):
    nod = d[d["total"] <= 0]
    if len(nod) < 2:
        return None
    closed = int((~nod["open"]).sum())
    s = f"ל-{len(nod)} מתוך {len(d)} האזורים אין נתוני שטחים פנויים ותפוסים"
    if closed > 0:
        s += f"; {closed} מהם אינם פתוחים לשיווק"
    return s + "."


def insight_closed_district(dist):
    dist = dist[dist["zones"] >= 3].copy()
    if dist.empty:
        return None
    dist["closed"] = dist["zones"] - dist["open"]
    dist["cshare"] = dist["closed"] / dist["zones"]
    dist = dist.sort_values(["cshare", "zones", "name"], ascending=[False, False, True], kind="stable")
    if len(dist) < 2:
        return None
    top, nxt = dist.iloc[0], dist.iloc[1]
    if top["cshare"] < 0.5:
        return None
    # strict max (integer cross-multiplication, no float ties)
    if int(top["closed"]) * int(nxt["zones"]) <= int(nxt["closed"]) * int(top["zones"]):
        return None
    return (f"במחוז {top['name']} {int(top['closed'])} מתוך {int(top['zones'])} האזורים "
            f"אינם פתוחים לשיווק, השיעור הגבוה בין המחוזות עם 3 אזורים לפחות.")


def insight_top_district(dist, n_zones, tot_avail):
    if dist.empty or n_zones == 0:
        return None
    top = dist.iloc[0]
    if len(dist) > 1 and dist.iloc[1]["zones"] == top["zones"]:
        return None
    s = f"מחוז {top['name']} מרכז {int(top['zones'])} מתוך {n_zones} אזורי התעשייה"
    if tot_avail > 0:
        s += f" ו-{_pct(top['avail'] / tot_avail)} מהשטח הפנוי ({_dun(top['avail'])} דונם)"
    return s + "."


def insight_biggest(d):
    a = d[d["area"] > 0].sort_values(["area", "name"], ascending=[False, True], kind="stable")
    if len(a) < 3:
        return None
    top, med = a.iloc[0], a["area"].median()
    if med <= 0:
        return None
    ratio = top["area"] / med
    if ratio < 2:
        return None
    return (f"האזור הגדול במאגר לפי קו המתאר הוא {top['name']}: {_dun(top['area'])} דונם, "
            f"פי {ratio:.1f} מהחציון ({_dun(med)} דונם).")


def insight_factories(d):
    f = d[d["n_fact"] > 0].sort_values(["n_fact", "name"], ascending=[False, True], kind="stable")
    if len(f) < 2:
        return None
    top = f.iloc[0]
    return (f"ל-{len(f)} אזורים מצורפת רשימת מפעלים לדוגמה; הארוכה שבהן היא של {top['name']} "
            f"עם {_int(top['n_fact'])} עסקים (גדולים: {_int(top['n_big'])}, "
            f"בינוניים: {_int(top['n_medium'])}, קטנים: {_int(top['n_small'])}).")


# --- compute ---------------------------------------------------------------------
def compute(frames):
    d = _prepare(frames["zones"])
    n = len(d)
    land = d[d["total"] > 0].copy()
    tot_avail = float(land["avail"].sum())
    tot_occ = float(land["occ"].sum())
    tot_land = tot_avail + tot_occ
    n_open = int(d["open"].sum())
    tot_area = float(d["area"].sum())

    # land per zone (stacked)
    ls = land.sort_values(["total", "name"], ascending=[False, True], kind="stable")
    top = ls.head(TOP_LAND)
    rest = ls.iloc[TOP_LAND:]
    l_names = list(top["name"])
    l_av = [round(v / DUNAM, 1) for v in top["avail"]]
    l_oc = [round(v / DUNAM, 1) for v in top["occ"]]
    if len(rest):
        l_names.append(f"אחר ({len(rest)} אזורים)")
        l_av.append(round(rest["avail"].sum() / DUNAM, 1))
        l_oc.append(round(rest["occ"].sum() / DUNAM, 1))
    chart_land = {"names": l_names, "avail": l_av, "occ": l_oc,
                  "total": [round(a + o, 1) for a, o in zip(l_av, l_oc)]}

    # available share per zone
    land["ashare"] = land["avail"] / land["total"]
    sh = land.sort_values(["ashare", "total", "name"], ascending=[False, False, True], kind="stable")
    sh_top = sh.head(TOP_LAND)
    chart_share = {"names": list(sh_top["name"]),
                   "values": [round(v * 100, 1) for v in sh_top["ashare"]],
                   "avail": [round(v / DUNAM, 1) for v in sh_top["avail"]],
                   "nearly_full": [bool(1 - v >= NEARLY_FULL) for v in sh_top["ashare"]],
                   "capped": len(sh) > TOP_LAND, "n": int(len(sh))}

    # districts
    g = d.groupby("district")
    dist = pd.DataFrame({
        "zones": g.size(),
        "open": g["open"].sum(),
        "avail": g["avail"].sum(),
        "occ": g["occ"].sum(),
        "area": g["area"].sum(),
    }).reset_index().rename(columns={"district": "name"})
    dist = dist.sort_values(["zones", "avail", "name"], ascending=[False, False, True], kind="stable")
    chart_dist = {"names": list(dist["name"]),
                  "open": [int(v) for v in dist["open"]],
                  "closed": [int(z - o) for z, o in zip(dist["zones"], dist["open"])],
                  "zones": [int(v) for v in dist["zones"]],
                  "avail": [round(v / DUNAM, 1) for v in dist["avail"]],
                  "occ": [round(v / DUNAM, 1) for v in dist["occ"]],
                  "area": [round(v / DUNAM, 1) for v in dist["area"]]}

    # mapped area
    ar = d[d["area"] > 0].sort_values(["area", "name"], ascending=[False, True], kind="stable")
    ar_top = ar.head(TOP_AREA)
    chart_area = {"names": list(ar_top["name"]),
                  "values": [round(v / DUNAM, 1) for v in ar_top["area"]],
                  "open": [bool(v) for v in ar_top["open"]],
                  "capped": len(ar) > TOP_AREA, "n": int(len(ar))}

    # land vs mapped area scatter (zones with both)
    both = d[(d["area"] > 0) & (d["total"] > 0)].sort_values("name", kind="stable")
    chart_scatter = {"points": [[round(a / DUNAM, 1), round(t / DUNAM, 1), nm,
                                 round(av / t * 100, 1)]
                                for a, t, nm, av in zip(both["area"], both["total"],
                                                        both["name"], both["avail"])]}

    # factories
    fz = d[d["n_fact"] > 0].sort_values(["n_fact", "name"], ascending=[False, True], kind="stable")
    fz_top = fz.head(TOP_FACT)
    chart_fact = {"names": list(fz_top["name"]),
                  "small": [int(v) for v in fz_top["n_small"]],
                  "medium": [int(v) for v in fz_top["n_medium"]],
                  "big": [int(v) for v in fz_top["n_big"]],
                  "total": [int(v) for v in fz_top["n_fact"]],
                  "capped": len(fz) > TOP_FACT}
    bigz = d[d["n_big"] > 0].sort_values(["n_big", "name"], ascending=[False, True], kind="stable")
    big_rows = [{"zone": z, "district": ds, "names": "; ".join(sorted(b))}
                for z, ds, b in zip(bigz["name"], bigz["district"], bigz["big"])]

    # completeness
    comp_fields = [
        ("איש קשר", "contact"), ("דואר אלקטרוני", "email"), ("טלפון", "phone"),
        ("נתוני שטחים", None), ("אתר אינטרנט", "website"), ("תיאור האזור", "desc"),
        ("רשימת מפעלים", None),
    ]
    comp_names, comp_vals = [], []
    for label, col in comp_fields:
        if col:
            v = int(d[col].sum())
        elif label == "נתוני שטחים":
            v = int((d["total"] > 0).sum())
        else:
            v = int((d["n_fact"] > 0).sum())
        comp_names.append(label)
        comp_vals.append(v)
    order = sorted(range(len(comp_names)), key=lambda i: (-comp_vals[i], i))
    chart_comp = {"names": [comp_names[i] for i in order], "values": [comp_vals[i] for i in order]}

    # map
    zones_map = d[d["cen"].notna()].sort_values(["zid", "name"], kind="stable")
    tol = 10.0
    while True:
        shapes = [_simplify_outers(p, tol) for p in zones_map["polys"]]
        nv = sum(len(r) for s in shapes for r in s)
        if nv <= MAP_VERTEX_BUDGET or tol > 5000:
            break
        tol *= 2
    feats = []
    for (_, r), shp in zip(zones_map.iterrows(), shapes):
        lat, lon = itm_to_wgs84(*r["cen"])
        rings = [[[round(a, 4), round(b, 4)] for a, b in (itm_to_wgs84(x, y) for x, y in ring)]
                 for ring in shp]
        feats.append({"name": r["name"], "district": r["district"], "open": bool(r["open"]),
                      "c": [round(lat, 4), round(lon, 4)], "rings": rings,
                      "avail": _dun(r["avail"]) if r["total"] > 0 else "",
                      "occ": _dun(r["occ"]) if r["total"] > 0 else "",
                      "area": _dun(r["area"])})
    chart_map = {"zones": feats, "tol": int(tol)}

    # KPIs
    occ_rate = tot_occ / tot_land if tot_land > 0 else 0.0
    n_nodata = int((d["total"] <= 0).sum())
    kpis = {
        "zones": {"value": n, "display": _int(n), "tone": "brand"},
        "open": {"value": n_open, "display": _int(n_open),
                 "tone": "ok" if n and n_open / n >= 0.5 else "warn"},
        "avail": {"value": round(tot_avail / DUNAM), "display": _dun(tot_avail), "tone": "brand"},
        "occ_rate": {"value": round(occ_rate * 100, 1), "display": _pct(occ_rate),
                     "tone": "warn" if occ_rate >= 0.85 else "info"},
        "area": {"value": round(tot_area / 1e6, 1), "display": f"{tot_area / 1e6:,.1f}", "tone": "brand"},
        "nodata": {"value": n_nodata, "display": _int(n_nodata),
                   "tone": "warn" if n_nodata > 0 else "ok"},
    }

    rules = [
        ("avail_leader", insight_avail_leader(land, tot_avail)),
        ("occupancy", insight_occupancy(land)),
        ("top_district", insight_top_district(dist, n, tot_avail)),
        ("closed_district", insight_closed_district(dist)),
        ("no_data", insight_no_data(d)),
        ("biggest", insight_biggest(d)),
        ("factories", insight_factories(d)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lead_land = ls.iloc[0]["name"] if len(ls) else ""
    top_dist = dist.iloc[0]["name"] if len(dist) else ""
    lede = (f"המאגר מפרט {_int(n)} אזורי תעשייה שבטיפול המנהל לאזורי תעשייה במשרד הכלכלה "
            f"והתעשייה, ב-{len(dist)} מחוזות. {_int(n_open)} מהם פתוחים לשיווק, וב-{len(land)} "
            f"אזורים מדווחים שטחי מגרשים: {_dun(tot_avail)} דונם פנויים ו-{_dun(tot_occ)} דונם תפוסים.")
    if lead_land:
        lede += f" האזור עם השטח המשווק הגדול ביותר הוא {lead_land}."

    summary = (f"איתור אזורי תעשייה ואנשי קשר לפי שם או מחוז: {_int(n)} אזורים, "
               f"{_int(n_open)} פתוחים לשיווק, {_dun(tot_avail)} דונם מגרשים פנויים.")

    labels = {
        "lede": lede,
        "zones_kpi": "אזורי תעשייה במאגר",
        "open_kpi": "אזורים פתוחים לשיווק",
        "avail_kpi": "שטח מגרשים פנוי (דונם)",
        "occ_rate_kpi": "שיעור התפוסה מהשטח המשווק",
        "area_kpi": "שטח כולל לפי קווי המתאר (קמ״ר)",
        "nodata_kpi": "אזורים ללא נתוני שטחים",
        "map_note": (f"קווי המתאר של {len(feats)} אזורים, בכחול אזורים פתוחים לשיווק ובאפור "
                     f"אזורים שאינם פתוחים. הקווים מפושטים לתצוגה (סטייה של עד {int(tol)} מ׳ בערך), "
                     f"וחלקות קטנות מ-{int(MIN_RING_M2 / DUNAM)} דונם הושמטו מהציור. לחיצה על אזור מציגה את פרטיו."),
        "map_aria": (f"מפה אינטראקטיבית של {len(feats)} אזורי תעשייה וקווי המתאר שלהם. "
                     f"גרסה נגישה: ראו טבלאות ועיון בנתונים למטה."),
        "land_note": (f"שטח המגרשים הפנוי והתפוס בכל אזור, בדונם, ב-{len(land)} האזורים שמדווחים עליו"
                      + (f" ({TOP_LAND} הגדולים, והיתר מקובצים תחת אחר)." if len(rest) else ".")),
        "land_aria": (f"גרף עמודות מוערמות: שטח פנוי ותפוס בדונם לפי אזור תעשייה. "
                      f"הגדול ביותר: {lead_land}." if lead_land else "גרף עמודות מוערמות: שטח פנוי ותפוס לפי אזור."),
        "share_note": (f"איזה חלק מהשטח המשווק עדיין פנוי בכל אזור. אדום מסמן אזור שתפוס ב-"
                       f"{NEARLY_FULL * 100:.0f}% ומעלה (כמעט מלא)."
                       + (f" מוצגים {TOP_LAND} האזורים עם השיעור הפנוי הגבוה מתוך {len(sh)}." if len(sh) > TOP_LAND else "")),
        "share_aria": (f"גרף עמודות: אחוז השטח הפנוי לפי אזור. הגבוה ביותר: {chart_share['names'][0]} "
                       f"עם {chart_share['values'][0]:.1f}%." if chart_share["names"] else "גרף עמודות: אחוז השטח הפנוי לפי אזור."),
        "dist_note": "מספר האזורים בכל מחוז, לפי מצב השיווק, ושטחי המגרשים בדונם.",
        "dist_aria": (f"גרף עמודות מוערמות: אזורי תעשייה לפי מחוז ומצב שיווק. המחוז המוביל: {top_dist}."
                      if top_dist else "גרף עמודות: אזורי תעשייה לפי מחוז."),
        "dist_land_aria": "גרף עמודות מוערמות: שטח פנוי ותפוס בדונם לפי מחוז.",
        "area_note": ("שטח האזור לפי קו המתאר שבמאגר, בדונם. קו המתאר כולל גם דרכים ושטחים ציבוריים, "
                      "ולכן הוא גדול מסך המגרשים המשווקים."
                      + (f" מוצגים {TOP_AREA} הגדולים מתוך {len(ar)}." if len(ar) > TOP_AREA else "")),
        "area_aria": (f"גרף עמודות: שטח אזורי התעשייה לפי קו המתאר. הגדול ביותר: {chart_area['names'][0]} "
                      f"עם {chart_area['values'][0]:,.0f} דונם." if chart_area["names"] else "גרף עמודות: שטח האזורים."),
        "scatter_note": (f"כל נקודה היא אזור ({len(both)} אזורים עם קו מתאר ונתוני שטחים): שטח קו המתאר "
                         f"מול סך המגרשים המשווקים, בדונם. בריחוף מוצג גם שיעור השטח הפנוי."),
        "scatter_aria": "גרף פיזור: שטח קו המתאר מול שטח המגרשים המשווקים לפי אזור תעשייה.",
        "fact_note": (f"מספר המפעלים והעסקים ברשימות לדוגמה שהמנהל צירף לכל אזור, לפי גודל. "
                      f"אלה דוגמאות ולא מצבת מפעלים מלאה; רשומות \"{UNKNOWN_DEV}\" לא נספרו."
                      + (f" מוצגים {TOP_FACT} האזורים עם הרשימות הארוכות." if chart_fact["capped"] else "")),
        "fact_aria": (f"גרף עמודות מוערמות: מפעלים לדוגמה לפי אזור וגודל. הרשימה הארוכה: "
                      f"{chart_fact['names'][0]}." if chart_fact["names"] else "גרף עמודות: מפעלים לדוגמה לפי אזור."),
        "big_note": "המפעלים הגדולים שמופיעים ברשימות לדוגמה, לפי אזור.",
        "comp_note": f"בכמה מתוך {_int(n)} האזורים מופיע כל סוג מידע במאגר.",
        "comp_aria": (f"גרף עמודות: מספר האזורים שבהם מופיע כל שדה מידע, מתוך {_int(n)}."),
    }

    flags = {"has_land": len(land) > 0, "has_fact": len(fz) > 0, "has_big": len(big_rows) > 0,
             "has_area": len(ar) > 0, "has_scatter": len(both) >= 3, "has_map": len(feats) > 0}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["אזורי תעשייה", "תעשייה", "קרקע למפעלים", "עדיפות לאומית", "מחוזות"],
            "related_ids": ["bd731d1b-aab6-4a13-a4a3-e3102a320fd4",
                            "3d71fe33-b239-4ed9-b6ef-950c8fcc54bc",
                            "8694e2a8-2f9b-416b-a30f-cb9cda4dde4b"],
            "spatial_coverage": "מחוזות: " + ", ".join(sorted(dist["name"])),
        },
        "kpis": kpis,
        "charts": {"land": chart_land, "share": chart_share, "dist": chart_dist,
                   "area": chart_area, "scatter": chart_scatter, "fact": chart_fact,
                   "comp": chart_comp, "map": chart_map},
        "tables": {"big": big_rows},
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
