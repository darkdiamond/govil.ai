"""שכבות GIS של משרד הבינוי והשיכון: three of the ministry's four uploaded
layers, each read from its zipped shapefile (`map: true` inputs, ITM):

- `hoods`: שיקום שכונות, the neighbourhood-renewal areas (polygons) with
  their settlement, ministry district code, and three undocumented code
  fields (TYPE "סוג", ACTIVITY "פעילות", EMERGENCY "חירום"). The codes are
  shown as codes: the files define no labels for them.
- `reno`: שיקום שכונות, שיפוץ מבנים, one footprint polygon per apartment
  building in the renovation programme, with its status (renovated / needs
  renovation), apartments, public-housing apartments, floors, entrances and
  the date of its last renovation (the DOCX legend's field meanings).
- `districts`: the ministry's five districts (polygons).

The fourth layer (מחיר למשתכן, gis_dira.zip) is a zip of zips the map reader
can't open; the page says so in fixed copy. The DOCX legend is documentation.

Joins: a renovation building belongs to the neighbourhood whose ID equals its
PROJECT_ID; a neighbourhood with a district code the districts layer lacks
(code 0, regional councils) is placed in a district by its centroid (point in
polygon), and the page says how many were placed that way.

Order-independent: every list is sorted on a total key; sums over sorted
values. Buildings are public housing blocks, not people.
"""
import json
import math
import re

import pandas as pd
from govlib import fmt, geo

TOP_PROJECTS = 15
TOP_SETTLEMENTS = 12
TOP_STREETS = 10
DISTRICT_NAMES = {"ירוש": "ירושלים"}       # the layer truncates names to 4 letters
DONE_WORDS = ("שופץ",)
TODO_WORDS = ("צריך", "לשפץ")
AREA_EDGES = [0, 250, 500, 1000, 2500, 10000, 50000]    # dunam
WHOLE_RE = re.compile(r"^כל\s")    # "כל העיר", "כל הישוב", "כל המושבים": the area is the whole settlement
APT_EDGES = [0, 10, 16, 24, 32, 48]
PUB_EDGES = [0, 0.0001, 0.25, 0.5, 0.75]       # share of public-housing apartments
HOOD_TOL = 10       # 1e-5 degree units, ~10 m
DIST_TOL = 40       # ~400 m: district outlines are drawn at national zoom
LAT_RANGE = (29.3, 33.5)
LON_RANGE = (34.2, 35.95)


def n_he(v):
    return fmt.int_he(v)


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def code(v):
    """'2', '2.0' → '2'; anything else stripped as is."""
    s = str(v).strip()
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else s


def code_key(c):
    try:
        return (0, float(c), c)
    except ValueError:
        return (1, 0.0, c)


def band_labels(edges, unit=""):
    out = []
    for i, lo in enumerate(edges):
        if i + 1 < len(edges):
            out.append(f"{n_he(lo)}-{n_he(edges[i + 1])}{unit}")
        else:
            out.append(f"{n_he(lo)}+{unit}")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


# ── geometry ─────────────────────────────────────────────────────────────


def _polygons(raw):
    try:
        g = json.loads(raw or "null")
    except ValueError:
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
        rings = [[(float(pt[0]), float(pt[1])) for pt in r] for r in p if len(r) >= 4]
        if rings:
            out.append(rings)
    return out


def _ring_area_centroid(ring, kx, ky):
    a = cx = cy = 0.0
    x0, y0 = ring[0]
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        p1x, p1y = (x1 - x0) * kx, (y1 - y0) * ky
        p2x, p2y = (x2 - x0) * kx, (y2 - y0) * ky
        cr = p1x * p2y - p2x * p1y
        a += cr
        cx += (p1x + p2x) * cr
        cy += (p1y + p2y) * cr
    a /= 2.0
    if abs(a) < 1e-9:
        return 0.0, (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return a, (x0 + cx / (6 * a) / kx, y0 + cy / (6 * a) / ky)


def _area_centroid(polys):
    """Planar area (m², outer rings minus holes) and area-weighted centroid."""
    lat = polys[0][0][0][1]
    ky = 110_574.0
    kx = 111_320.0 * math.cos(math.radians(lat))
    tot = sx = sy = 0.0
    fallback = None
    for rings in polys:
        for k, r in enumerate(rings):
            a, (cx, cy) = _ring_area_centroid(r, kx, ky)
            a = abs(a) * (1 if k == 0 else -1)
            if fallback is None:
                fallback = (cx, cy)
            tot += a
            sx += a * cx
            sy += a * cy
    if tot <= 0:
        return 0.0, fallback
    return tot, (sx / tot, sy / tot)


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polys(x, y, polys):
    for rings in polys:
        if _in_ring(x, y, rings[0]) and not any(_in_ring(x, y, h) for h in rings[1:]):
            return True
    return False


def _in_israel(pt):
    return pt is not None and LON_RANGE[0] <= pt[0] <= LON_RANGE[1] and LAT_RANGE[0] <= pt[1] <= LAT_RANGE[1]


def _enc(polys, o, tol):
    out = []
    for rings in polys:
        er = []
        for r in rings:
            pts = r
            if len(pts) > 1 and geo.quantize(pts[:1]) == geo.quantize(pts[-1:]):
                pts = pts[:-1]
            er.append(geo.encode([pts], o, tol=tol)[0])
        out.append(er)
    return out


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    h = frames["hoods"].copy()
    r = frames["reno"].copy()
    d = frames["districts"].copy()

    # ---------- districts ----------
    d["polys"] = d["__geometry"].map(_polygons)
    d = d[d["polys"].map(len) > 0].copy()
    d["code"] = d["CODE"].map(code)
    d["name"] = d["NAME"].str.strip().map(lambda s: DISTRICT_NAMES.get(s, s))
    ac = d["polys"].map(_area_centroid)
    d["area"] = [s if (pd.notna(s) and s > 0) else t[0] for s, t in zip(num(d["SHAPE_STAr"]), ac)]
    order = sorted(range(len(d)), key=lambda i: (code_key(d["code"].iat[i]), d["name"].iat[i], d["area"].iat[i]))
    d = d.iloc[order].reset_index(drop=True)
    dist_codes = list(d["code"])
    dist_name = dict(zip(d["code"], d["name"]))
    dist_polys = list(d["polys"])

    def locate(pt):
        for c, polys in zip(dist_codes, dist_polys):
            if _in_polys(pt[0], pt[1], polys):
                return c
        return None

    # ---------- neighbourhoods ----------
    h["polys"] = h["__geometry"].map(_polygons)
    h = h[h["polys"].map(len) > 0].copy()
    if h.empty:
        raise ValueError("no neighbourhood polygons in the map file")
    h["id"] = h["ID"].map(code)
    h["name"] = h["NAME"].str.strip()
    h["town"] = h["SETTLEME_1"].str.strip().replace("", "לא צוין")
    h["dcode"] = h["DISTRICT_C"].map(code)
    h["type"] = h["TYPE"].map(code)
    h["act"] = h["ACTIVITY"].map(code)
    h["emg"] = h["EMERGENCY"].map(code) == "1"
    hac = h["polys"].map(_area_centroid)
    h["cxy"] = hac.map(lambda t: t[1])
    h["area"] = [s if (pd.notna(s) and s > 0) else t[0] for s, t in zip(num(h["SHAPE_STAr"]), hac)]
    h["dun"] = h["area"] / 1000
    h["whole"] = h["name"].str.match(WHOLE_RE)
    h["gkey"] = h["__geometry"].astype(str)
    h = h.sort_values(["town", "name", "id", "type", "act", "gkey"]).reset_index(drop=True)
    nh = len(h)
    spatial = [locate(p) if _in_israel(p) else None for p in h["cxy"]]
    h["dist"] = [dc if dc in dist_name else sp for dc, sp in zip(h["dcode"], spatial)]
    n_placed = int(sum(1 for dc, sp in zip(h["dcode"], spatial) if dc not in dist_name and sp is not None))
    n_nodist = int(h["dist"].isna().sum())
    h["dname"] = h["dist"].map(lambda c: dist_name.get(c, "ללא מחוז") if c is not None else "ללא מחוז")
    n_towns = int(h["town"].nunique())
    n_emg = int(h["emg"].sum())
    tot_dun = math.fsum(sorted(h["dun"].tolist()))

    # ---------- renovation buildings ----------
    r["polys"] = r["__geometry"].map(_polygons)
    r = r[r["polys"].map(len) > 0].copy()
    if r.empty:
        raise ValueError("no building polygons in the renovation layer")
    r["pid"] = r["PROJECT_ID"].map(code)
    r["proj"] = r["PROJECT_NA"].str.strip().replace("", "ללא שם")
    r["sub"] = r["SUBPROJECT"].str.strip()
    r["street"] = r["STREET_NAM"].str.strip()
    r["hn"] = r["HOUSE_NUMB"].str.strip()
    r["scode"] = r["HOUSE_STAT"].map(code)
    r["sname"] = r["HOUSE_ST_1"].str.strip()
    r["sname"] = r["sname"].where(r["sname"] != "", "סטטוס " + r["scode"])
    r["apt"] = num(r["APT"]).fillna(0).clip(lower=0)
    r["pub"] = num(r["APT_RENTED"]).fillna(0).clip(lower=0)
    r["floors"] = num(r["NUM_KOMOT"])
    r["ent"] = num(r["NUM_KNISSO"])
    r["dt"] = pd.to_datetime(r["LAST_BITSU"].str.strip(), format="%Y%m%d", errors="coerce")
    rac = r["polys"].map(_area_centroid)
    r["cxy"] = rac.map(lambda t: t[1])
    r["gkey"] = r["__geometry"].astype(str)
    r = r.sort_values(["proj", "street", "hn", "scode", "gkey"]).reset_index(drop=True)
    nr = len(r)

    def is_done(s):
        return s.strip() in DONE_WORDS

    def is_todo(s):
        return any(w in s for w in TODO_WORDS) and not is_done(s)

    statuses = sorted(r[["scode", "sname"]].drop_duplicates().itertuples(index=False),
                      key=lambda t: (0 if is_done(t[1]) else 1 if is_todo(t[1]) else 2, code_key(t[0]), t[1]))
    st_names = []
    for _, s in statuses:
        if s not in st_names:
            st_names.append(s)
    st_tone = ["ok" if is_done(s) else "warn" if is_todo(s) else "subtle" for s in st_names]
    r["st"] = r["sname"].map(st_names.index)
    done_mask = r["sname"].map(is_done)
    todo_mask = r["sname"].map(is_todo)
    n_done = int(done_mask.sum())
    n_todo = int(todo_mask.sum())
    tot_apt = round(math.fsum(sorted(r["apt"].tolist())))
    tot_pub = round(math.fsum(sorted(r["pub"].tolist())))

    hood_ids = set(h["id"])
    r["in_hood"] = r["pid"].isin(hood_ids)
    n_proj = int(r["pid"].nunique())
    n_proj_matched = int(r.loc[r["in_hood"], "pid"].nunique())
    per_hood = r.groupby("pid").size().to_dict()
    hood_act = {}
    for i_, a_ in zip(h["id"], h["act"]):
        hood_act.setdefault(i_, set()).add(a_)

    # district of each building: its neighbourhood's, else its own centroid
    hood_dist = {}
    for i_, dn in zip(h["id"], h["dname"]):
        hood_dist.setdefault(i_, dn)
    r["dname"] = [hood_dist[p] if p in hood_dist else
                  (dist_name.get(locate(c), "ללא מחוז") if _in_israel(c) and locate(c) else "ללא מחוז")
                  for p, c in zip(r["pid"], r["cxy"])]

    charts, tables = {}, {}

    # ---------- chart: neighbourhoods per district, by activity code ----------
    acts = sorted(h["act"].unique(), key=code_key)
    act_names = [f"קוד פעילות {a}" for a in acts]
    dorder = [dist_name[c] for c in dist_codes]
    if (h["dname"] == "ללא מחוז").any():
        dorder.append("ללא מחוז")
    dcount = {dn: int((h["dname"] == dn).sum()) for dn in dorder}
    dorder = [dn for dn in dorder if dcount[dn] > 0 or dn != "ללא מחוז"]
    dorder = sorted(dorder, key=lambda dn: (-dcount[dn], dorder.index(dn)))
    charts["districts"] = {
        "cats": dorder, "names": act_names,
        "series": [[int(((h["dname"] == dn) & (h["act"] == a)).sum()) for dn in dorder] for a in acts],
    }
    darea = {name: a for name, a in zip(d["name"], d["area"])}
    rows = []
    for dn in dorder:
        sub = h[h["dname"] == dn]
        rb = int((r["dname"] == dn).sum())
        rows.append([dn, n_he(len(sub)), n_he(sub["town"].nunique()), n_he(int(sub["emg"].sum())), n_he(rb),
                     n_he(darea[dn] / 1e6) if dn in darea else ""])
    tables["districts"] = {"headers": ["מחוז", "שכונות", "יישובים", "בסימון חירום", "מבנים בשכבת השיפוץ", "שטח המחוז (קמ״ר)"],
                           "rows": rows}

    # ---------- chart: settlements with most neighbourhood records ----------
    tc = h.groupby("town").agg(n=("id", "size"), dun=("dun", "sum")).reset_index()
    tc = tc.sort_values(["n", "dun", "town"], ascending=[False, False, True]).reset_index(drop=True)
    top_t = tc.head(TOP_SETTLEMENTS)
    charts["towns"] = {"names": list(top_t["town"]), "values": [int(v) for v in top_t["n"]]}
    tables["towns"] = {"headers": ["יישוב", "שכונות", "שטח (דונם)"],
                       "rows": [[t, n_he(n), n_he(a)] for t, n, a in zip(top_t["town"], top_t["n"], top_t["dun"])]}
    n_multi = int((tc["n"] >= 2).sum())

    # ---------- chart: neighbourhood area bands ----------
    h["ab"] = h["dun"].map(lambda v: band_index(v, AREA_EDGES))
    a_labels = band_labels(AREA_EDGES)
    kinds = [("שכונה או חלק מיישוב", ~h["whole"]), ("כל היישוב", h["whole"])]
    charts["areas"] = {"cats": a_labels, "names": [k for k, _ in kinds],
                       "series": [[int(((h["ab"] == b) & m_).sum()) for b in range(len(AREA_EDGES))] for _, m_ in kinds]}
    tables["areas"] = {"headers": ["שטח (דונם)"] + [k for k, _ in kinds] + ["סך הכול"],
                       "rows": [[lab] + [n_he(((h["ab"] == b) & m_).sum()) for _, m_ in kinds]
                                + [n_he((h["ab"] == b).sum())] for b, lab in enumerate(a_labels)]}
    part = h[~h["whole"]]
    whole = h[h["whole"]]
    n_whole = len(whole)
    med_part = float(part["dun"].median()) if len(part) else None
    med_whole = float(whole["dun"].median()) if len(whole) else None
    big_part = part.sort_values(["dun", "town", "name", "id"], ascending=[False, True, True, True]).iloc[0] if len(part) else None

    # ---------- chart: code fields (type x activity, emergency) ----------
    types = sorted(h["type"].unique(), key=code_key)
    type_names = [f"סוג {t}" for t in types]
    charts["codes"] = {"cats": act_names, "names": type_names,
                       "series": [[int(((h["type"] == t) & (h["act"] == a)).sum()) for a in acts] for t in types]}
    crow = []
    for a, an in zip(acts, act_names):
        sub = h[h["act"] == a]
        crow.append([an] + [n_he((sub["type"] == t).sum()) for t in types]
                    + [n_he(int(sub["emg"].sum())), n_he(len(sub))])
    tables["codes"] = {"headers": ["קוד פעילות"] + type_names + ["בסימון חירום", "סך הכול"], "rows": crow}

    # ---------- chart: renovation projects ----------
    pg = r.groupby("proj").agg(n=("st", "size"), done=("sname", lambda s: int(s.map(is_done).sum())),
                               apt=("apt", "sum"), pub=("pub", "sum")).reset_index()
    pg = pg.sort_values(["n", "done", "proj"], ascending=[False, False, True]).reset_index(drop=True)
    top_p = pg.head(TOP_PROJECTS)
    rest = pg.iloc[TOP_PROJECTS:]
    p_names = list(top_p["proj"]) + (["אחר"] if len(rest) else [])
    p_series = []
    for k, s in enumerate(st_names):
        vals = [int(((r["proj"] == p) & (r["st"] == k)).sum()) for p in top_p["proj"]]
        if len(rest):
            vals.append(int(((r["proj"].isin(set(rest["proj"]))) & (r["st"] == k)).sum()))
        p_series.append(vals)
    charts["projects"] = {"cats": p_names, "names": st_names, "series": p_series, "tones": st_tone}
    tables["projects"] = {
        "headers": ["פרויקט", "מבנים", "שופצו", "שיעור ששופץ", "דירות", "מהן בדיור הציבורי"],
        "rows": [[p, n_he(n), n_he(dn), fmt.pct(dn / n), n_he(a), n_he(pb)]
                 for p, n, dn, a, pb in zip(pg["proj"], pg["n"], pg["done"], pg["apt"], pg["pub"])],
    }
    big_p = pg[pg["n"] >= 10]
    full_p = sorted(big_p.loc[big_p["done"] == big_p["n"], "proj"].tolist())
    low_p = big_p.assign(sh=big_p["done"] / big_p["n"]).sort_values(["sh", "n", "proj"], ascending=[True, False, True])

    # ---------- chart: year of last renovation by status ----------
    yr = r[r["dt"].notna()].copy()
    yr["y"] = yr["dt"].dt.year.astype(int)
    years = list(range(int(yr["y"].min()), int(yr["y"].max()) + 1)) if len(yr) else []
    charts["years"] = {"cats": [str(y) for y in years], "names": st_names, "tones": st_tone,
                       "series": [[int(((yr["y"] == y) & (yr["st"] == k)).sum()) for y in years]
                                  for k in range(len(st_names))]}
    tables["years"] = {"headers": ["שנה"] + st_names,
                       "rows": [[str(y)] + [n_he(((yr["y"] == y) & (yr["st"] == k)).sum()) for k in range(len(st_names))]
                                for y in years]}
    has_years = len(years) >= 3
    n_nodate = nr - len(yr)

    # ---------- chart: public-housing share by status ----------
    r["pshare"] = [(p / a) if a > 0 else 0.0 for p, a in zip(r["pub"], r["apt"])]
    r["pb"] = r["pshare"].map(lambda v: band_index(v, PUB_EDGES))
    pub_labels = ["ללא דירות בדיור הציבורי", "עד 25%", "25%-50%", "50%-75%", "75% ומעלה"]
    charts["public"] = {"cats": pub_labels, "names": st_names, "tones": st_tone,
                        "series": [[int(((r["pb"] == b) & (r["st"] == k)).sum()) for b in range(len(PUB_EDGES))]
                                   for k in range(len(st_names))]}
    srow = []
    st_stats = {}
    for k, s in enumerate(st_names):
        sub = r[r["st"] == k]
        a = math.fsum(sorted(sub["apt"].tolist()))
        p = math.fsum(sorted(sub["pub"].tolist()))
        st_stats[s] = (len(sub), a, p)
        srow.append([s, n_he(len(sub)), n_he(a), n_he(p), fmt.pct(p / a) if a else "",
                     fmt.num_he(sub["apt"].mean()) if len(sub) else ""])
    tables["public"] = {"headers": ["סטטוס", "מבנים", "דירות", "בדיור הציבורי", "שיעור דיור ציבורי", "דירות בממוצע למבנה"],
                        "rows": srow}

    # ---------- chart: building size (apartments) and floors ----------
    r["abnd"] = r["apt"].map(lambda v: band_index(v, APT_EDGES))
    apt_labels = band_labels(APT_EDGES)
    charts["apts"] = {"cats": apt_labels, "names": st_names, "tones": st_tone,
                      "series": [[int(((r["abnd"] == b) & (r["st"] == k)).sum()) for b in range(len(APT_EDGES))]
                                 for k in range(len(st_names))]}
    tables["apts"] = {"headers": ["דירות במבנה"] + st_names,
                      "rows": [[lab] + [n_he(((r["abnd"] == b) & (r["st"] == k)).sum()) for k in range(len(st_names))]
                               for b, lab in enumerate(apt_labels)]}
    fl = r[r["floors"].notna()].copy()
    fl["f"] = fl["floors"].round().astype(int)
    fvals = sorted(fl["f"].unique().tolist())
    charts["floors"] = {"cats": [str(f) for f in fvals], "names": st_names, "tones": st_tone,
                        "series": [[int(((fl["f"] == f) & (fl["st"] == k)).sum()) for f in fvals]
                                   for k in range(len(st_names))]}
    frow = []
    for f in fvals:
        sub = fl[fl["f"] == f]
        ent = sub["ent"].dropna()
        frow.append([str(f), n_he(len(sub)), fmt.num_he(sub["apt"].mean()), fmt.num_he(ent.mean()) if len(ent) else ""])
    tables["floors"] = {"headers": ["קומות", "מבנים", "דירות בממוצע", "כניסות בממוצע"], "rows": frow}
    med_fl = float(fl["f"].median()) if len(fl) else None
    tot_ent = round(math.fsum(sorted(r["ent"].dropna().tolist())))

    # ---------- chart: streets ----------
    sg = r[r["street"] != ""].groupby(["street", "proj"]).agg(n=("st", "size"),
                                                              done=("sname", lambda s: int(s.map(is_done).sum())))
    sg = sg.reset_index().sort_values(["n", "done", "street", "proj"], ascending=[False, False, True, True])
    top_s = sg.head(TOP_STREETS)
    charts["streets"] = {"names": [f"{s}, {p}" for s, p in zip(top_s["street"], top_s["proj"])],
                         "done": [int(v) for v in top_s["done"]],
                         "rest": [int(n - dn) for n, dn in zip(top_s["n"], top_s["done"])]}
    tables["streets"] = {"headers": ["רחוב", "פרויקט", "מבנים", "שופצו"],
                         "rows": [[s, p, n_he(n), n_he(dn)] for s, p, n, dn in
                                  zip(top_s["street"], top_s["proj"], top_s["n"], top_s["done"])]}
    n_streets = int(r.loc[r["street"] != "", ["street", "proj"]].drop_duplicates().shape[0])

    # ---------- neighbourhood list ----------
    tables["hoods"] = {
        "headers": ["יישוב", "שכונה", "מחוז", "שטח (דונם)", "קוד פעילות", "חירום", "מבנים בשכבת השיפוץ"],
        "rows": [[t, nm, dn, n_he(a), ac_, "כן" if e else "", n_he(per_hood.get(i_, 0)) if per_hood.get(i_) else ""]
                 for t, nm, dn, a, ac_, e, i_ in zip(h["town"], h["name"], h["dname"], h["dun"], h["act"], h["emg"], h["id"])],
    }

    # ---------- map ----------
    xs, ys = [], []
    for polys in list(h["polys"]) + list(r["polys"]):
        for rings in polys:
            xs += [p[0] for p in rings[0]]
            ys += [p[1] for p in rings[0]]
    hx, hy = list(xs), list(ys)
    for polys in dist_polys:
        for rings in polys:
            xs += [p[0] for p in rings[0]]
            ys += [p[1] for p in rings[0]]
    o = geo.origin(xs, ys)
    ox, oy = o
    ai = {a: i for i, a in enumerate(acts)}
    dfeat = [[nm, n_he(a / 1e6), int((h["dname"] == nm).sum()), _enc(p, o, DIST_TOL)]
             for nm, a, p in zip(d["name"], d["area"], d["polys"])]
    hfeat = [[ai[a], nm, t, dn, n_he(dun), "כן" if e else "לא", int(per_hood.get(i_, 0)), ty, _enc(p, o, HOOD_TOL)]
             for a, nm, t, dn, dun, e, i_, ty, p in
             zip(h["act"], h["name"], h["town"], h["dname"], h["dun"], h["emg"], h["id"], h["type"], h["polys"])]
    rfeat = []
    for row in r.itertuples(index=False):
        cxp, cyp = row.cxy
        addr = f"{row.street} {row.hn}".strip()
        date = row.dt.strftime("%d.%m.%Y") if not pd.isna(row.dt) else ""
        rfeat.append([int(row.st), row.proj, row.sub, addr, int(row.apt), int(row.pub),
                      int(row.floors) if row.floors == row.floors else -1, date,
                      round(cxp * geo.SCALE) - ox, round(cyp * geo.SCALE) - oy, _enc(row.polys, o, 0)])
    map_model = {
        "d": geo.pack(dfeat), "h": geo.pack(hfeat), "r": geo.pack(rfeat),
        "meta": {"origin": o, "scale": geo.SCALE, "acts": act_names, "statuses": st_names, "tones": st_tone,
                 "bounds": [[min(hy), min(hx)], [max(hy), max(hx)]]},
    }

    # ---------- insights ----------
    insights = []
    real_d = [dn for dn in dorder if dn != "ללא מחוז"]
    if len(real_d) >= 2 and dcount[real_d[0]] > dcount[real_d[1]] and dcount[real_d[0]] >= dcount.get("ללא מחוז", 0):
        lead_d = real_d[0]
        txt = (f"מחוז {lead_d} מוביל במספר אזורי שיקום השכונות: {n_he(dcount[lead_d])} מתוך {n_he(nh)}, "
               f"ואחריו {real_d[1]} עם {n_he(dcount[real_d[1]])}")
        if n_placed:
            txt += f" ({n_he(n_placed)} שכונות ללא קוד מחוז שויכו למחוז לפי מיקומן)"
        insights.append({"id": "district_lead", "text_he": txt + "."})

    if len(tc) >= 2 and tc.at[0, "n"] > tc.at[1, "n"] and tc.at[0, "n"] >= 3:
        insights.append({"id": "town_lead", "text_he": (
            f"{tc.at[0, 'town']} היא היישוב עם הכי הרבה אזורי שיקום בשכבה: {n_he(tc.at[0, 'n'])}, "
            f"ואחריה {tc.at[1, 'town']} עם {n_he(tc.at[1, 'n'])}. בסך הכול {n_he(n_towns)} יישובים, "
            f"ב־{n_he(n_multi)} מהם יותר מאזור אחד.")})

    if nr >= 20 and n_done and n_todo:
        txt = (f"מתוך {n_he(nr)} המבנים בשכבת שיפוץ המבנים, {n_he(n_done)} ({fmt.pct(n_done / nr)}) מסומנים "
               f"״{st_names[0]}״ ו־{n_he(n_todo)} ({fmt.pct(n_todo / nr)}) עדיין ממתינים לשיפוץ")
        if len(low_p) and low_p.iloc[0]["done"] / low_p.iloc[0]["n"] < 0.5:
            lp = low_p.iloc[0]
            txt += f"; השיעור הנמוך ביותר בפרויקט {lp['proj']} ({fmt.pct(lp['done'] / lp['n'])} מתוך {n_he(lp['n'])} מבנים)"
        insights.append({"id": "status", "text_he": txt + "."})

    if len(full_p) >= 2:
        insights.append({"id": "full_projects", "text_he": (
            f"ב־{n_he(len(full_p))} פרויקטים עם לפחות עשרה מבנים כל המבנים כבר שופצו: {fmt.join_he(full_p[:5])}"
            + (" ועוד." if len(full_p) > 5 else "."))})

    done_l = [s for s in st_names if is_done(s)]
    todo_l = [s for s in st_names if is_todo(s)]
    if done_l and todo_l:
        _, ad_, pd_ = st_stats[done_l[0]]
        _, at_, pt_ = st_stats[todo_l[0]]
        if ad_ > 0 and at_ > 0:
            sd, st_ = pd_ / ad_, pt_ / at_
            if st_ >= sd * 1.5 or sd >= st_ * 1.5:
                hi_lab, lo_lab = ("הממתינים לשיפוץ", "ששופצו") if st_ > sd else ("ששופצו", "הממתינים לשיפוץ")
                insights.append({"id": "public_housing", "text_he": (
                    f"במבנים {hi_lab} שיעור הדירות בדיור הציבורי גבוה יותר: {fmt.pct(max(sd, st_))} מהדירות, "
                    f"לעומת {fmt.pct(min(sd, st_))} במבנים {lo_lab}. בכל השכבה {n_he(tot_pub)} מתוך "
                    f"{n_he(tot_apt)} דירות ({fmt.pct(tot_pub / tot_apt)}) הן בדיור הציבורי.")})

    if has_years and done_l and todo_l:
        yd = yr[yr["sname"] == done_l[0]]["y"]
        yt = yr[yr["sname"] == todo_l[0]]["y"]
        if len(yd) >= 10 and len(yt) >= 10:
            md, mt = int(yd.median()), int(yt.median())
            if md != mt:
                insights.append({"id": "years", "text_he": (
                    f"תאריך השיפוץ האחרון בשדה שונה בין הקבוצות: במבנים ששופצו השנה החציונית היא {md} "
                    f"(טווח {int(yd.min())} עד {int(yd.max())}), ובמבנים הממתינים לשיפוץ {mt} "
                    f"(טווח {int(yt.min())} עד {int(yt.max())}).")})

    if n_emg >= 3:
        em = h[h["emg"]].groupby("dname").size().reset_index(name="n")
        em = em.sort_values(["n", "dname"], ascending=[False, True]).reset_index(drop=True)
        txt = f"{n_he(n_emg)} מאזורי השיקום ({fmt.pct(n_emg / nh)}) מסומנים בשדה ״חירום״"
        if (len(em) >= 2 and em.at[0, "dname"] != "ללא מחוז" and em.at[0, "n"] > em.at[1, "n"]
                and em.at[0, "n"] / n_emg >= 0.4):
            txt += f"; {n_he(em.at[0, 'n'])} מהם במחוז {em.at[0, 'dname']}"
        insights.append({"id": "emergency", "text_he": txt + "."})

    if n_proj >= 3:
        acts_of = sorted({a for p in set(r["pid"]) for a in hood_act.get(p, set())}, key=code_key)
        txt = (f"{n_he(n_proj_matched)} מתוך {n_he(n_proj)} פרויקטי השיפוץ מתאימים לפי מספר השכונה לאזור בשכבת הגבולות")
        if len(acts_of) == 1:
            txt += f", וכולם באזורים בקוד פעילות {acts_of[0]}"
        insights.append({"id": "join", "text_he": txt + "."})

    if n_whole >= 3 and med_part is not None and len(part) >= 10:
        insights.append({"id": "whole", "text_he": (
            f"{n_he(n_whole)} מאזורי השיקום ({fmt.pct(n_whole / nh)}) מוגדרים בשם ״כל העיר״, ״כל הישוב״ או ״כל המושבים״, "
            f"וגבולם הוא גבול היישוב כולו (חציון {n_he(med_whole)} דונם). שאר {n_he(len(part))} האזורים הם שכונות, "
            f"בשטח חציוני של {n_he(med_part)} דונם; הגדול שבהם ״{big_part['name']}״ ב{big_part['town']} "
            f"({n_he(big_part['dun'])} דונם).")})

    # ---------- kpis ----------
    done_share = n_done / nr
    kpis = {
        "hoods": {"value": nh, "display": n_he(nh), "tone": "brand"},
        "towns": {"value": n_towns, "display": n_he(n_towns), "tone": "brand"},
        "buildings": {"value": nr, "display": n_he(nr), "tone": "brand"},
        "done": {"value": round(done_share * 100, 1), "display": fmt.pct(done_share),
                 "tone": "ok" if done_share >= 0.6 else "warn" if done_share < 0.4 else "brand"},
        "apts": {"value": tot_apt, "display": n_he(tot_apt), "tone": "brand"},
        "emg": {"value": n_emg, "display": n_he(n_emg), "tone": "info" if n_emg else "brand"},
    }

    lede = (
        f"שלוש שכבות מפה של משרד הבינוי והשיכון: {n_he(nh)} אזורי שיקום שכונות ב־{n_he(n_towns)} יישובים, "
        f"{n_he(nr)} מבנים בתוכנית שיפוץ המבנים ({n_he(tot_apt)} דירות, מהן {n_he(tot_pub)} בדיור הציבורי), "
        f"ו־{n_he(len(d))} מחוזות המשרד. {fmt.pct(done_share)} מהמבנים מסומנים כמבנים ששופצו."
    )
    summary = (
        f"מפת שיקום שכונות של משרד הבינוי והשיכון: {n_he(nh)} אזורי שיקום ב־{n_he(n_towns)} יישובים, "
        f"{n_he(nr)} מבנים בתוכנית שיפוץ, ומחוזות המשרד."
    )
    seo_desc = (
        f"מפת שכבות ה־GIS של משרד הבינוי והשיכון: {n_he(nh)} אזורי שיקום שכונות ב־{n_he(n_towns)} יישובים, "
        f"{n_he(nr)} מבנים בשיפוץ ומחוזות המשרד, לפי יישוב וסטטוס."
    )
    labels = {
        "lede": lede,
        "map_note": (
            f"גבולות {n_he(nh)} אזורי שיקום השכונות בצבע לפי קוד הפעילות, {n_he(nr)} מבני תוכנית השיפוץ בצבע לפי "
            f"הסטטוס, וגבולות {n_he(len(d))} המחוזות. בתצוגה רחוקה כל מבנה מוצג כנקודה, ובהתקרבות מופיע קו המתאר שלו. "
            "לחיצה על אזור או מבנה מציגה את פרטיו."
        ),
        "map_aria": (f"מפה אינטראקטיבית של {n_he(nh)} אזורי שיקום השכונות, {n_he(nr)} מבני תוכנית השיפוץ ו־{n_he(len(d))} "
                     "מחוזות משרד הבינוי והשיכון. גרסה נגישה: ראו הטבלאות למטה."),
        "districts_note": ("מספר אזורי השיקום בכל מחוז, לפי קוד הפעילות."
                           + (f" {n_he(n_placed)} אזורים ללא קוד מחוז שויכו לפי מיקום מרכזם." if n_placed else "")
                           + (f" {n_he(n_nodist)} אזורים מחוץ לגבולות המחוזות." if n_nodist else "")),
        "towns_note": f"{n_he(min(TOP_SETTLEMENTS, len(tc)))} היישובים עם הכי הרבה אזורי שיקום בשכבה, מתוך {n_he(n_towns)}.",
        "areas_note": (f"שטח כל אזור שיקום בדונם, בהפרדה בין שכונות לאזורים המוגדרים ככל היישוב; "
                       f"בסך הכול {n_he(tot_dun)} דונם."),
        "codes_note": ("שלושה שדות קוד בשכבת הגבולות: סוג, פעילות וחירום. הקובץ אינו מגדיר את משמעות הקודים, "
                       "ולכן הם מוצגים כפי שהם."),
        "projects_note": (f"מבנים בכל פרויקט שיפוץ לפי סטטוס; {n_he(min(TOP_PROJECTS, len(pg)))} הפרויקטים הגדולים"
                          + (f", והשאר ({n_he(len(rest))}) תחת ״אחר״." if len(rest) else ".")),
        "years_note": ("שנת התאריך בשדה ״תאריך אחרון ששופץ המבנה״, לפי סטטוס המבנה"
                       + (f"; {n_he(n_nodate)} מבנים בלי תאריך תקין." if n_nodate else ".")),
        "public_note": "שיעור הדירות בדיור הציבורי מתוך דירות המבנה, לפי סטטוס השיפוץ.",
        "apts_note": f"מספר הדירות בכל מבנה, לפי סטטוס; בסך הכול {n_he(tot_apt)} דירות.",
        "floors_note": ("מספר הקומות בכל מבנה, לפי סטטוס"
                        + (f"; החציון {n_he(med_fl)} קומות" if med_fl is not None else "")
                        + f", ובסך הכול {n_he(tot_ent)} כניסות."),
        "streets_note": f"הרחובות עם הכי הרבה מבנים בתוכנית, מתוך {n_he(n_streets)} צירופי רחוב ופרויקט.",
        "hoods_note": f"כל {n_he(nh)} אזורי השיקום בשכבה, לפי יישוב.",
    }
    for k, v in [
        ("districts", "גרף עמודות מוערמות: אזורי שיקום לפי מחוז וקוד פעילות"),
        ("towns", "גרף עמודות: יישובים עם הכי הרבה אזורי שיקום"),
        ("areas", "גרף עמודות מוערמות: אזורי שיקום לפי טווח שטח"),
        ("codes", "גרף עמודות מוערמות: אזורי שיקום לפי קוד פעילות וסוג"),
        ("projects", "גרף עמודות מוערמות: מבנים בכל פרויקט שיפוץ לפי סטטוס"),
        ("years", "גרף עמודות מוערמות: מבנים לפי שנת השיפוץ האחרון וסטטוס"),
        ("public", "גרף עמודות מוערמות: מבנים לפי שיעור הדיור הציבורי וסטטוס"),
        ("apts", "גרף עמודות מוערמות: מבנים לפי מספר דירות וסטטוס"),
        ("floors", "גרף עמודות מוערמות: מבנים לפי מספר קומות וסטטוס"),
        ("streets", "גרף עמודות: הרחובות עם הכי הרבה מבנים בתוכנית"),
    ]:
        labels[k + "_aria"] = v
        labels[k + "_cap"] = v.split(": ", 1)[-1]
    labels["hoods_cap"] = "רשימת אזורי שיקום השכונות"

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מפת שיקום שכונות ושכבות GIS של משרד השיכון",
                "description": seo_desc,
                "name": "שכבות GIS של משרד הבינוי והשיכון: שיקום שכונות ומחוזות",
                "alternate_names": [
                    "שכבות מידע גיאוגרפי (GIS) של משרד הבינוי והשיכון",
                    "מפת שיקום שכונות",
                    "שיקום שכונות שיפוץ מבנים",
                    "מחוזות משרד השיכון",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "map": map_model,
        "insights": insights,
        "labels": labels,
        "flags": {"years": has_years, "streets": len(top_s) >= 3, "floors": len(fvals) >= 2},
    }
