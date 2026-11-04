"""Road accidents by municipal authority (תאונות דרכים לפי רשות מוניציפלית).

One row = one locality polygon (a city, a local council, a locality inside a
regional council, or a regional council's open area, "שטח כללי"), with the
accidents, casualties and vehicles counted inside it over the CBS window
(five years up to YEARMONTH). Rows roll up to MUNICIPAL (the authority or
the unincorporated area).

The `geo` input is the same layer as a zipped shapefile. It is read only for
its polygons: each authority's area-weighted centroid places it on a bubble
map. Feature order is not guaranteed, so per-feature centroids are sorted
before they are summed.
"""
import json
import math

import pandas as pd
from govlib import fmt, frame, geo

COUNT_COLS = [
    "SUMACCIDEN", "DEAD", "SEVER_INJ", "SLIGH_INJ", "PEDESTRINJ", "ELECTRIC_INJ",
    "INJ0_19", "INJ20_64", "INJ65_", "INJTOTAL", "MOTORCYCLE", "TRUCK",
    "BICYCLE", "SCOOTERS", "PRIVATE", "VEHICLE",
]
TOP_N = 15
SMALL_N = 10
MIN_RATE_ACC = 200      # accidents an authority needs before its rates are ranked
MIN_SHARE_INJ = 500     # injured an authority needs before its victim shares are ranked
MIN_SCATTER_ACC = 50
MIN_DISTRICT_ACC = 1000
MAX_TYPES = 6
CITY_TYPE = "עירייה"
REGIONAL_TYPE = "מועצה אזורית"
OPEN_AREA = "שטח כללי"
UNKNOWN_NAME = "ללא שם רשות"
SEV_BINS = [5, 8, 12]   # killed + seriously injured per 100 accidents: map colour classes


def _plural(n, one, many):
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def _rate(num, den, per):
    return (num / den * per) if den else 0.0


def _r1(v):
    return float(f"{v:.1f}")


def _mode_label(rows, col):
    """Most common non-empty value (ties by value), or ''."""
    vals = rows[col][rows[col] != ""]
    if vals.empty:
        return ""
    counts = frame.ranked(vals)
    return str(counts.index[0])


def _sorted(df, col, ascending=False):
    return df.sort_values("name", kind="stable").sort_values(col, ascending=ascending, kind="stable")


def _centroids(g):
    """{municode: (lat, lon)} from polygon features, area-weighted."""
    parts = []
    for code, raw in zip(g["MUNICODE"].tolist(), g["__geometry"].tolist()):
        key = _code(code)
        if key is None:
            continue
        try:
            gj = json.loads(raw)
        except (TypeError, ValueError):
            continue
        t = gj.get("type") if isinstance(gj, dict) else None
        polys = (gj.get("coordinates") or []) if t in ("Polygon", "MultiPolygon") else []
        if t == "Polygon":
            polys = [polys]
        for poly in polys:
            if not poly:
                continue
            ring = poly[0]
            a = cx = cy = 0.0
            for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
                cr = x0 * y1 - x1 * y0
                a += cr
                cx += (x0 + x1) * cr
                cy += (y0 + y1) * cr
            if abs(a) < 1e-12:
                continue
            parts.append((key, round(abs(a) / 2, 10), round(cx / (3 * a), 7), round(cy / (3 * a), 7)))
    parts.sort()
    out = {}
    for key, a, x, y in parts:
        s = out.setdefault(key, [0.0, 0.0, 0.0])
        s[0] += a
        s[1] += a * x
        s[2] += a * y
    return {k: (round(v[2] / v[0], 4), round(v[1] / v[0], 4)) for k, v in out.items() if v[0] > 0}


def _in(name):
    """'ב' + name, reworded for an unincorporated area ('ללא שיפוט - אזור X')."""
    pre = "ללא שיפוט - אזור "
    if name.startswith(pre):
        return f"באזור {name[len(pre):]} (שטח ללא שיפוט)"
    return f"ב{name}"


def _code(v):
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    return int(f) if math.isfinite(f) else None


def compute(frames):
    df = frames["main"].copy()
    for c in ["MUNICIPAL", "CITY", "MUNITYPE", "DISTRICT", "MUNICODE", "YEARMONTH"]:
        df[c] = frame.clean_series(df[c])
    for c in COUNT_COLS + ["AreaSQKM"]:
        df[c] = frame.num(df[c]).fillna(0.0)
    df.loc[df["MUNICIPAL"] == "", "MUNICIPAL"] = UNKNOWN_NAME

    tot = {c: float(df[c].sum()) for c in COUNT_COLS}
    acc_all, dead_all, sev_all = tot["SUMACCIDEN"], tot["DEAD"], tot["SEVER_INJ"]
    inj_all = tot["INJTOTAL"]
    nat_sev = _rate(dead_all + sev_all, acc_all, 100)
    nat_dead = _rate(dead_all, acc_all, 1000)

    ym = pd.to_numeric(df["YEARMONTH"], errors="coerce").dropna()
    ym = ym[(ym % 100 >= 1) & (ym % 100 <= 12)]
    as_of = fmt.MONTHS_HE[int(ym.max()) % 100 - 1] + " " + str(int(ym.max()) // 100) if len(ym) else ""

    # ---- authority roll-up ---------------------------------------------------
    rows = []
    for name, g in df.groupby("MUNICIPAL", sort=True):
        r = {c: float(g[c].sum()) for c in COUNT_COLS}
        r["name"] = name
        r["area"] = float(g["AreaSQKM"].sum())
        t = _mode_label(g, "MUNITYPE")
        dist = _mode_label(g, "DISTRICT")
        r["type"] = t or name          # an area outside every type/district shows under its own name
        r["district"] = dist or name
        r["code"] = _code(_mode_label(g, "MUNICODE"))
        r["n_rows"] = len(g)
        rows.append(r)
    m = pd.DataFrame(rows)
    m["sev"] = [_rate(a + b, c, 100) for a, b, c in zip(m.DEAD, m.SEVER_INJ, m.SUMACCIDEN)]
    m["dead1000"] = [_rate(a, c, 1000) for a, c in zip(m.DEAD, m.SUMACCIDEN)]
    m["dens"] = [(a / s) if s > 0 else 0.0 for a, s in zip(m.SUMACCIDEN, m.area)]
    n_auth = len(m)

    def tbl_rank(sub, cols):
        out = []
        for i, r in enumerate(sub.itertuples(index=False), 1):
            out.append([str(i), r.name] + [f(r) for f in cols])
        return out

    # top by accidents
    top_acc = _sorted(m, "SUMACCIDEN").head(TOP_N)
    # top by deaths
    top_dead = _sorted(m, "DEAD").head(TOP_N)
    top_dead = top_dead[top_dead.DEAD > 0]
    # severity and density, authorities with enough accidents
    big = m[m.SUMACCIDEN >= MIN_RATE_ACC]
    top_sev = _sorted(big, "sev").head(TOP_N)
    top_dens = _sorted(big[big.area > 0], "dens").head(TOP_N)

    # ---- types / districts ---------------------------------------------------
    def group(col):
        out = []
        for key, g in m.groupby(col, sort=True):
            acc, dead, sev = g.SUMACCIDEN.sum(), g.DEAD.sum(), g.SEVER_INJ.sum()
            out.append({
                "name": key, "n": len(g), "acc": float(acc), "dead": float(dead), "severe": float(sev),
                "inj": float(g.INJTOTAL.sum()), "area": float(g.area.sum()),
                "ped": float(g.PEDESTRINJ.sum()), "elec": float(g.ELECTRIC_INJ.sum()),
                "veh": {c: float(g[c].sum()) for c in ["PRIVATE", "MOTORCYCLE", "TRUCK", "BICYCLE", "SCOOTERS", "VEHICLE"]},
                "sev": _rate(dead + sev, acc, 100), "dead1000": _rate(dead, acc, 1000),
            })
        out.sort(key=lambda x: (-x["acc"], x["name"]))
        return out

    types_all = group("type")
    types = types_all[:MAX_TYPES]
    if len(types_all) > MAX_TYPES:
        rest = types_all[MAX_TYPES:]
        agg = {"name": frame.OTHER, "n": sum(x["n"] for x in rest)}
        for k in ["acc", "dead", "severe", "inj", "area", "ped", "elec"]:
            agg[k] = sum(x[k] for x in rest)
        agg["veh"] = {c: sum(x["veh"][c] for x in rest) for c in rest[0]["veh"]}
        agg["sev"] = _rate(agg["dead"] + agg["severe"], agg["acc"], 100)
        agg["dead1000"] = _rate(agg["dead"], agg["acc"], 1000)
        types.append(agg)
    districts = group("district")

    # ---- regional councils: open area vs localities --------------------------
    rc = df[df["MUNITYPE"] == REGIONAL_TYPE]
    is_open = rc["CITY"].str.startswith(OPEN_AREA)
    open_sec = None
    if is_open.any() and (~is_open).any() and rc["SUMACCIDEN"].sum() > 0:
        def part(sub):
            return {"acc": float(sub.SUMACCIDEN.sum()), "dead": float(sub.DEAD.sum()),
                    "severe": float(sub.SEVER_INJ.sum()), "area": float(sub.AreaSQKM.sum()),
                    "inj": float(sub.INJTOTAL.sum())}
        po, pl = part(rc[is_open]), part(rc[~is_open])
        tot_rc = {k: po[k] + pl[k] for k in po}
        share = {k: (po[k] / tot_rc[k] if tot_rc[k] else 0.0) for k in po}
        open_sec = {"open": po, "loc": pl, "share": share,
                    "n_councils": int(rc["MUNICIPAL"].nunique())}

    # ---- victims -----------------------------------------------------------
    age_known = tot["INJ0_19"] + tot["INJ20_64"] + tot["INJ65_"]
    age_unknown = max(inj_all - age_known, 0.0)
    age_labels = ["גילאי 0-19", "גילאי 20-64", "גיל 65 ומעלה"]
    age_vals = [tot["INJ0_19"], tot["INJ20_64"], tot["INJ65_"]]
    if age_unknown > 0:
        age_labels.append("גיל לא ידוע")
        age_vals.append(age_unknown)

    veh_keys = [("PRIVATE", "רכב פרטי"), ("MOTORCYCLE", "אופנוע"), ("TRUCK", "משאית מעל 3.5 טון"),
                ("BICYCLE", "אופניים"), ("SCOOTERS", "קורקינט")]

    def vmix(v):
        total = v["VEHICLE"]
        vals = [v[k] for k, _ in veh_keys]
        other = max(total - sum(vals), 0.0)
        base = sum(vals) + other
        return [(_r1(x / base * 100) if base else 0.0) for x in vals + [other]], vals + [other]

    eligible = m[m.INJTOTAL >= MIN_SHARE_INJ].copy()
    shares = {}
    for key, col in [("ped", "PEDESTRINJ"), ("elec", "ELECTRIC_INJ"), ("kids", "INJ0_19"), ("seniors", "INJ65_")]:
        eligible[key] = eligible[col] / eligible.INJTOTAL
        sub = _sorted(eligible, key).head(SMALL_N)
        shares[key] = {
            "names": sub["name"].tolist(),
            "vals": [_r1(v * 100) for v in sub[key]],
            "counts": [int(v) for v in sub[col]],
            "nat": _r1(_rate(tot[col], inj_all, 100)),
        }

    # ---- map ---------------------------------------------------------------
    cent = _centroids(frames["geo"]) if "geo" in frames else {}
    pts = []
    for r in _sorted(m, "SUMACCIDEN").itertuples(index=False):
        if r.code is None or r.code not in cent or r.SUMACCIDEN <= 0:
            continue
        lat, lon = cent[r.code]
        if r.SUMACCIDEN < MIN_SCATTER_ACC:
            cls = 0
        else:
            cls = 1 + sum(1 for b in SEV_BINS if r.sev >= b)
        pts.append([lat, lon, r.name, int(r.SUMACCIDEN), int(r.DEAD), int(r.SEVER_INJ), _r1(r.sev), cls])
    map_chunks = geo.pack(pts) if pts else []
    if pts:
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
    else:
        bounds = []
    lo, mid, hi = SEV_BINS
    sev_classes = [
        f"פחות מ-{MIN_SCATTER_ACC} תאונות (ללא דירוג)",
        f"פחות מ-{lo}",
        f"{lo}-{mid}",
        f"{mid}-{hi}",
        f"{hi} ומעלה",
    ]

    # ---- scatter -----------------------------------------------------------
    sc = m[(m.SUMACCIDEN >= MIN_SCATTER_ACC) & (m.area > 0)]
    type_names = [t["name"] for t in types if t["name"] != frame.OTHER]
    scatter = []
    for i, tn in enumerate(type_names + ([frame.OTHER] if len(types_all) > MAX_TYPES else [])):
        if tn == frame.OTHER:
            sub = sc[~sc["type"].isin(type_names)]
        else:
            sub = sc[sc["type"] == tn]
        sub = _sorted(sub, "SUMACCIDEN")
        pts_s = [[_r1(r.dens) if r.dens >= 1 else float(f"{r.dens:.2f}"), _r1(r.sev), int(r.SUMACCIDEN), r.name]
                 for r in sub.itertuples(index=False)]
        if pts_s:
            scatter.append({"name": tn, "data": pts_s})

    # ---- insights ----------------------------------------------------------
    insights = []
    tmap = {t["name"]: t for t in types_all}

    city, regional = tmap.get(CITY_TYPE), tmap.get(REGIONAL_TYPE)
    if city and regional and city["dead1000"] > 0 and regional["acc"] >= MIN_RATE_ACC:
        ratio = regional["dead1000"] / city["dead1000"]
        if ratio >= 1.5:
            insights.append({"id": "rural_deadly", "text_he": (
                f"תאונה במועצה אזורית קטלנית בהרבה מתאונה בעיר: במועצות האזוריות נהרגו "
                f"{fmt.num_he(regional['dead1000'])} בני אדם לכל 1,000 תאונות, פי {fmt.num_he(ratio)} "
                f"מבעיריות ({fmt.num_he(city['dead1000'])}), אף שבעיריות אירעו "
                f"{fmt.pct(city['acc'] / acc_all)} מהתאונות.")})

    if open_sec:
        s = open_sec["share"]
        gap = s["dead"] - s["acc"]
        if gap >= 0.03:
            insights.append({"id": "open_area", "text_he": (
                f"בשטחים הפתוחים של המועצות האזוריות, מחוץ ליישובים, אירעו {fmt.pct(s['acc'])} "
                f"מהתאונות במועצות, אך נהרגו בהם {fmt.pct(s['dead'])} מההרוגים במועצות "
                f"({fmt.int_he(open_sec['open']['dead'])} מתוך {fmt.int_he(open_sec['open']['dead'] + open_sec['loc']['dead'])}).")})
        elif gap <= -0.03:
            insights.append({"id": "open_area", "text_he": (
                f"בשטחים הפתוחים של המועצות האזוריות אירעו {fmt.pct(s['acc'])} מהתאונות במועצות "
                f"ונהרגו בהם רק {fmt.pct(s['dead'])} מההרוגים במועצות.")})

    if n_auth >= 5 and acc_all > 0:
        t5 = _sorted(m, "SUMACCIDEN").head(5)
        lead = t5.iloc[0]
        insights.append({"id": "concentration", "text_he": (
            f"חמש הרשויות עם מספר התאונות הגבוה ביותר ({fmt.join_he(t5["name"].tolist())}) מרכזות "
            f"{fmt.pct(t5.SUMACCIDEN.sum() / acc_all)} מכלל התאונות במאגר; {lead['name']} לבדה "
            f"{fmt.pct(lead.SUMACCIDEN / acc_all)} ({fmt.int_he(lead.SUMACCIDEN)} תאונות).")})

    if len(top_sev) and nat_sev > 0:
        r = top_sev.iloc[0]
        ratio = r.sev / nat_sev
        if ratio >= 1.5:
            insights.append({"id": "most_severe", "text_he": (
                f"החומרה הגבוהה ביותר נמדדה {_in(r['name'])}: {fmt.num_he(r.sev)} הרוגים ופצועים קשה לכל "
                f"100 תאונות, פי {fmt.num_he(ratio)} מהממוצע הארצי ({fmt.num_he(nat_sev)}). "
                f"הדירוג כולל רק רשויות עם {fmt.int_he(MIN_RATE_ACC)} תאונות לפחות.")})

    if len(top_dens) >= 2:
        a, b = top_dens.iloc[0], top_dens.iloc[1]
        insights.append({"id": "density", "text_he": (
            f"{a['name']} היא הרשות הצפופה ביותר בתאונות: {fmt.num_he(a.dens)} תאונות לקמ״ר, "
            f"לפני {b['name']} ({fmt.num_he(b.dens)}). הממוצע הארצי הוא "
            f"{fmt.num_he(acc_all / m.area.sum() if m.area.sum() else 0)} תאונות לקמ״ר.")})

    ped = shares["ped"]
    if ped["names"] and ped["nat"] > 0 and ped["vals"][0] >= 1.5 * ped["nat"]:
        insights.append({"id": "pedestrians", "text_he": (
            f"{_in(ped['names'][0])} הולכי רגל הם {fmt.pct_of(ped['vals'][0])} מהנפגעים, "
            f"לעומת {fmt.pct_of(ped['nat'])} בכלל המאגר (מבין רשויות עם {fmt.int_he(MIN_SHARE_INJ)} נפגעים לפחות).")})

    if tot["ELECTRIC_INJ"] > 0 and acc_all > 0:
        e = _sorted(m, "ELECTRIC_INJ").iloc[0]
        es, as_ = e.ELECTRIC_INJ / tot["ELECTRIC_INJ"], e.SUMACCIDEN / acc_all
        if es >= 1.2 * as_ and es >= 0.1:
            insights.append({"id": "electric", "text_he": (
                f"{e['name']} מרכזת {fmt.pct(es)} מנפגעי הדו-גלגלי החשמלי (אופניים וקורקינטים) במאגר, "
                f"{fmt.int_he(e.ELECTRIC_INJ)} נפגעים, לעומת {fmt.pct(as_)} מכלל התאונות.")})

    dsel = [x for x in districts if x["acc"] >= MIN_DISTRICT_ACC]
    if len(dsel) >= 3:
        ds = sorted(dsel, key=lambda x: (-x["sev"], x["name"]))
        hi_d, lo_d = ds[0], ds[-1]
        if lo_d["sev"] > 0 and hi_d["sev"] / lo_d["sev"] >= 1.5:
            insights.append({"id": "district", "text_he": (
                f"בין המחוזות, החומרה הגבוהה ביותר היא {_in(hi_d['name'])}: {fmt.num_he(hi_d['sev'])} הרוגים "
                f"ופצועים קשה לכל 100 תאונות, לעומת {fmt.num_he(lo_d['sev'])} {_in(lo_d['name'])}.")})

    # ---- KPIs --------------------------------------------------------------
    kpis = {
        "acc": {"value": int(acc_all), "display": fmt.int_he(acc_all), "tone": "brand"},
        "inj": {"value": int(inj_all), "display": fmt.int_he(inj_all), "tone": "brand"},
        "dead": {"value": int(dead_all), "display": fmt.int_he(dead_all), "tone": "danger" if dead_all > 0 else "brand"},
        "severe": {"value": int(sev_all), "display": fmt.int_he(sev_all), "tone": "warn" if sev_all > 0 else "brand"},
        "dead1000": {"value": _r1(nat_dead), "display": fmt.num_he(nat_dead), "tone": "info"},
        "auth": {"value": n_auth, "display": fmt.int_he(n_auth), "tone": "brand"},
    }

    # ---- charts + tables -----------------------------------------------------
    charts = {
        "top_acc": {"names": top_acc["name"].tolist(), "acc": [int(v) for v in top_acc.SUMACCIDEN],
                    "ds": [int(a + b) for a, b in zip(top_acc.DEAD, top_acc.SEVER_INJ)]},
        "top_dead": {"names": top_dead["name"].tolist(), "dead": [int(v) for v in top_dead.DEAD],
                     "acc": [int(v) for v in top_dead.SUMACCIDEN]},
        "sev": {"names": top_sev["name"].tolist(), "vals": [_r1(v) for v in top_sev.sev],
                "acc": [int(v) for v in top_sev.SUMACCIDEN], "nat": _r1(nat_sev)},
        "dens": {"names": top_dens["name"].tolist(), "vals": [_r1(v) for v in top_dens.dens],
                 "acc": [int(v) for v in top_dens.SUMACCIDEN]},
        "types": {"names": [t["name"] for t in types],
                  "acc_share": [_r1(_rate(t["acc"], acc_all, 100)) for t in types],
                  "dead_share": [_r1(_rate(t["dead"], dead_all, 100)) for t in types],
                  "dead1000": [_r1(t["dead1000"]) for t in types]},
        "districts": {"names": [d["name"] for d in districts], "acc": [int(d["acc"]) for d in districts],
                      "sev": [_r1(d["sev"]) for d in districts]},
        "injsev": {"labels": ["פצועים קל", "פצועים קשה", "הרוגים"],
                   "vals": [int(tot["SLIGH_INJ"]), int(sev_all), int(dead_all)]},
        "age": {"labels": age_labels, "vals": [int(v) for v in age_vals]},
        "roles": {"names": [t["name"] for t in types],
                  "ped": [_r1(_rate(t["ped"], t["inj"], 100)) for t in types],
                  "elec": [_r1(_rate(t["elec"], t["inj"], 100)) for t in types]},
        "vehmix": {"cats": [t["name"] for t in types] + ["כלל המאגר"],
                   "series": [lbl for _, lbl in veh_keys] + ["אחר"]},
        "shares": shares,
        "scatter": scatter,
        "map": {"chunks": map_chunks, "bounds": bounds, "classes": sev_classes},
    }
    mix_rows = [vmix(t["veh"]) for t in types] + [vmix({k: tot[k] for k in ["PRIVATE", "MOTORCYCLE", "TRUCK", "BICYCLE", "SCOOTERS", "VEHICLE"]})]
    charts["vehmix"]["data"] = [[row[0][j] for row in mix_rows] for j in range(len(veh_keys) + 1)]
    if open_sec:
        s = open_sec["share"]
        charts["open"] = {"metrics": ["שטח", "תאונות", "פצועים קשה", "הרוגים"],
                          "open": [_r1(s[k] * 100) for k in ["area", "acc", "severe", "dead"]],
                          "loc": [_r1((1 - s[k]) * 100) for k in ["area", "acc", "severe", "dead"]]}

    tables = {
        "top_acc": tbl_rank(top_acc, [lambda r: r.type, lambda r: fmt.int_he(r.SUMACCIDEN),
                                      lambda r: fmt.int_he(r.DEAD), lambda r: fmt.int_he(r.SEVER_INJ)]),
        "top_dead": tbl_rank(top_dead, [lambda r: fmt.int_he(r.DEAD), lambda r: fmt.int_he(r.SUMACCIDEN),
                                        lambda r: fmt.num_he(r.dead1000)]),
        "sev": tbl_rank(top_sev, [lambda r: r.type, lambda r: fmt.num_he(r.sev), lambda r: fmt.int_he(r.SUMACCIDEN)]),
        "dens": tbl_rank(top_dens, [lambda r: fmt.num_he(r.dens), lambda r: fmt.int_he(r.SUMACCIDEN),
                                    lambda r: fmt.num_he(r.area)]),
        "types": [[t["name"], fmt.int_he(t["n"]), fmt.int_he(t["acc"]), fmt.int_he(t["dead"]),
                   fmt.num_he(t["sev"]), fmt.num_he(t["dead1000"])] for t in types],
        "districts": [[d["name"], fmt.int_he(d["acc"]), fmt.int_he(d["dead"]), fmt.num_he(d["sev"]),
                       fmt.num_he(d["acc"] / d["area"] if d["area"] else 0)] for d in districts],
        "age": [[lbl, fmt.int_he(v), fmt.pct(v / inj_all if inj_all else 0)] for lbl, v in zip(age_labels, age_vals)],
        "injsev": [[lbl, fmt.int_he(v), fmt.pct(v / inj_all if inj_all else 0)]
                   for lbl, v in zip(["פצועים קל", "פצועים קשה", "הרוגים"], [tot["SLIGH_INJ"], sev_all, dead_all])],
        "roles": [[t["name"], fmt.int_he(t["ped"]), fmt.pct(t["ped"] / t["inj"] if t["inj"] else 0),
                   fmt.int_he(t["elec"]), fmt.pct(t["elec"] / t["inj"] if t["inj"] else 0)] for t in types],
        "vehmix": [[cat] + [fmt.pct_of(row[0][j]) for j in range(len(veh_keys) + 1)]
                   for cat, row in zip(charts["vehmix"]["cats"], mix_rows)],
        "shares": {k: [[n, fmt.pct_of(v), fmt.int_he(c)] for n, v, c in zip(s["names"], s["vals"], s["counts"])]
                   for k, s in shares.items()},
    }
    if open_sec:
        o, l_ = open_sec["open"], open_sec["loc"]
        tables["open"] = [
            ["שטח (קמ״ר)", fmt.int_he(o["area"]), fmt.int_he(l_["area"]), fmt.pct(open_sec["share"]["area"])],
            ["תאונות", fmt.int_he(o["acc"]), fmt.int_he(l_["acc"]), fmt.pct(open_sec["share"]["acc"])],
            ["פצועים קשה", fmt.int_he(o["severe"]), fmt.int_he(l_["severe"]), fmt.pct(open_sec["share"]["severe"])],
            ["הרוגים", fmt.int_he(o["dead"]), fmt.int_he(l_["dead"]), fmt.pct(open_sec["share"]["dead"])],
        ]

    outside_rows = top_dead[~top_dead["name"].isin(set(top_acc["name"]))]
    outside = outside_rows["name"].tolist()
    deadlier = bool(len(outside_rows)) and bool((outside_rows["dead1000"] > nat_dead).all())
    dead_outside = (f" {_plural(len(outside), 'רשות אחת', 'רשויות')} ברשימה אינן בין {fmt.int_he(TOP_N)} המובילות במספר התאונות"
                    f" ({(', '.join(outside[:3]) + ' ועוד') if len(outside) > 3 else fmt.join_he(outside)})"
                    + (": בכולן שיעור ההרוגים לתאונה גבוה מהממוצע הארצי." if deadlier else ".")
                    if outside else "")
    scatter_trend = ""
    if len(sc) >= 10:
        rho = pd.Series([math.log10(v) for v in sc.dens]).rank().corr(pd.Series(list(sc.sev)).rank())
        if rho <= -0.3:
            scatter_trend = " ככל שהרשות צפופה יותר בתאונות, התאונות בה קלות יותר בממוצע."
        elif rho >= 0.3:
            scatter_trend = " ככל שהרשות צפופה יותר בתאונות, התאונות בה חמורות יותר בממוצע."

    # ---- labels --------------------------------------------------------------
    period = f"נכון ל{as_of}" if as_of else "לפי העדכון האחרון"
    ta = top_acc.iloc[0] if len(top_acc) else None
    td = top_dead.iloc[0] if len(top_dead) else None
    big_type = types[0] if types else None
    labels = {
        "period": period,
        "col_sev": "הרוגים ופצועים קשה לכל 100 תאונות",
        "col_dead1000": "הרוגים לכל 1,000 תאונות",
        "sev_unit": "לכל 100 תאונות",
        "share_titles": {"ped": "הולכי רגל מכלל הנפגעים", "elec": "נפגעי דו-גלגלי חשמלי מכלל הנפגעים",
                         "kids": "נפגעים בגילאי 0-19 מכלל הנפגעים", "seniors": "נפגעים בגיל 65 ומעלה מכלל הנפגעים"},
        "map_legend": "הרוגים ופצועים קשה לכל 100 תאונות:",
        "acc_kpi": f"תאונות דרכים עם נפגעים ({period})",
        "auth_kpi": "רשויות מקומיות ואזורים ללא שיפוט",
        "dead1000_kpi": "הרוגים לכל 1,000 תאונות",
        "lookup_note": f"חיפוש חי בכל {_plural(len(df), 'רשומה אחת', 'רשומות')} המאגר: שם רשות מקומית, שם יישוב, מחוז וסוג רשות",
        "top_acc_lede": (f"{ta['name']} מובילה עם {fmt.int_he(ta.SUMACCIDEN)} תאונות, "
                         f"{fmt.pct(ta.SUMACCIDEN / acc_all)} מכלל התאונות. העמודה הכהה: הרוגים ופצועים קשה."
                         if ta is not None and acc_all else ""),
        "top_acc_aria": (f"גרף עמודות אופקי: {fmt.int_he(len(top_acc))} הרשויות עם מספר התאונות הגבוה ביותר. "
                         f"בראש {ta['name']} עם {fmt.int_he(ta.SUMACCIDEN)} תאונות." if ta is not None else "גרף עמודות"),
        "top_dead_lede": (f"{td['name']} מובילה עם {fmt.int_he(td.DEAD)} הרוגים." + dead_outside if td is not None else ""),
        "top_dead_aria": (f"גרף עמודות אופקי: {fmt.int_he(len(top_dead))} הרשויות עם מספר ההרוגים הגבוה ביותר. "
                          f"בראש {td['name']} עם {fmt.int_he(td.DEAD)} הרוגים." if td is not None else "גרף עמודות"),
        "sev_lede": (f"הרוגים ופצועים קשה לכל 100 תאונות, ברשויות עם {fmt.int_he(MIN_RATE_ACC)} תאונות לפחות "
                     f"({_plural(len(big), 'רשות אחת', 'רשויות')}). הממוצע הארצי: {fmt.num_he(nat_sev)}. "
                     f"הקו האדום מסמן אותו."),
        "sev_aria": (f"גרף עמודות אופקי: הרשויות עם שיעור ההרוגים והפצועים קשה הגבוה ביותר לכל 100 תאונות. "
                     f"בראש {top_sev.iloc[0]['name']} עם {fmt.num_he(top_sev.iloc[0].sev)}." if len(top_sev) else "גרף עמודות"),
        "dens_lede": (f"תאונות לקמ״ר בשטח הרשות, ברשויות עם {fmt.int_he(MIN_RATE_ACC)} תאונות לפחות. "
                      f"הממוצע הארצי: {fmt.num_he(acc_all / m.area.sum() if m.area.sum() else 0)} תאונות לקמ״ר."),
        "dens_aria": (f"גרף עמודות אופקי: הרשויות עם צפיפות התאונות הגבוהה ביותר לקמ״ר. "
                      f"בראש {top_dens.iloc[0]['name']} עם {fmt.num_he(top_dens.iloc[0].dens)}." if len(top_dens) else "גרף עמודות"),
        "scatter_lede": (f"כל נקודה היא רשות ({_plural(len(sc), 'רשות אחת', 'רשויות')} עם {fmt.int_he(MIN_SCATTER_ACC)} תאונות לפחות). "
                         f"ציר אופקי: תאונות לקמ״ר (סולם לוגריתמי); ציר אנכי: הרוגים ופצועים קשה לכל 100 תאונות; "
                         f"גודל הנקודה: מספר התאונות." + scatter_trend),
        "scatter_aria": "גרף פיזור: צפיפות התאונות מול חומרתן בכל רשות, לפי סוג רשות.",
        "types_lede": (f"נתח כל סוג רשות מהתאונות ומההרוגים. {big_type['name']}: {fmt.pct(big_type['acc'] / acc_all)} מהתאונות "
                       f"ו-{fmt.pct(big_type['dead'] / dead_all if dead_all else 0)} מההרוגים." if big_type and acc_all else ""),
        "types_aria": "גרף עמודות: נתח התאונות ונתח ההרוגים לפי סוג רשות.",
        "districts_lede": ("מספר התאונות בכל מחוז (עמודות) ושיעור ההרוגים והפצועים קשה לכל 100 תאונות (קו). "
                           "כל רשות משויכת למחוז של רוב יישוביה; שטח מחוץ למחוזות משרד הפנים מוצג בשמו."),
        "districts_aria": (f"גרף עמודות וקו: תאונות ושיעור חומרה לפי מחוז. הכי הרבה תאונות ב{districts[0]['name']}."
                           if districts else "גרף עמודות"),
        "age_lede": (f"{fmt.int_he(inj_all)} נפגעים בסך הכול. "
                     + (f"גילם של {fmt.int_he(age_unknown)} מהם ({fmt.pct(age_unknown / inj_all)}) לא ידוע." if age_unknown > 0 and inj_all else "")),
        "age_aria": (f"תרשים טבעת: נפגעים לפי קבוצת גיל. {fmt.pct(tot['INJ20_64'] / inj_all if inj_all else 0)} בגילאי 20-64."),
        "injsev_aria": (f"גרף עמודות: נפגעים לפי חומרת הפגיעה. {fmt.int_he(tot['SLIGH_INJ'])} פצועים קל, "
                        f"{fmt.int_he(sev_all)} פצועים קשה ו-{fmt.int_he(dead_all)} הרוגים."),
        "roles_lede": (f"שיעור הולכי הרגל ורוכבי הדו-גלגלי החשמלי מכלל הנפגעים, לפי סוג רשות. "
                       f"בכלל המאגר: {fmt.pct_of(shares['ped']['nat'])} הולכי רגל ו-{fmt.pct_of(shares['elec']['nat'])} רוכבי דו-גלגלי חשמלי."),
        "roles_aria": "גרף עמודות: שיעור הולכי הרגל ונפגעי הדו-גלגלי החשמלי מהנפגעים לפי סוג רשות.",
        "vehmix_lede": "כלי הרכב המעורבים בתאונות לפי סוג, באחוזים מכלל כלי הרכב המעורבים בכל סוג רשות.",
        "vehmix_aria": "גרף עמודות מוערמות: תמהיל כלי הרכב המעורבים בתאונות לפי סוג רשות.",
        "shares_lede": f"עשר הרשויות המובילות בכל מדד, מבין רשויות עם {fmt.int_he(MIN_SHARE_INJ)} נפגעים לפחות ({_plural(len(eligible), 'רשות אחת', 'רשויות')}). הקו האדום: שיעור כלל המאגר.",
        "map_lede": (f"כל עיגול הוא רשות, במרכז שטחה. גודל העיגול: מספר התאונות; צבע: הרוגים ופצועים קשה לכל 100 תאונות "
                     f"(רשויות עם פחות מ-{fmt.int_he(MIN_SCATTER_ACC)} תאונות באפור). "
                     f"{_plural(len(pts), 'רשות אחת', 'רשויות')} על המפה."),
        "map_aria": "מפה אינטראקטיבית של תאונות הדרכים לפי רשות. גרסה נגישה: ראו את הדירוגים והטבלאות בעמוד.",
    }
    for key, title in [("ped", "הולכי רגל"), ("elec", "דו-גלגלי חשמלי"), ("kids", "גילאי 0-19"), ("seniors", "גיל 65 ומעלה")]:
        s = shares[key]
        labels[f"{key}_aria"] = (f"גרף עמודות אופקי: הרשויות עם השיעור הגבוה ביותר של נפגעים מקבוצת {title}. "
                                 f"בראש {s['names'][0]} עם {fmt.pct_of(s['vals'][0])}." if s["names"] else "גרף עמודות")
    if open_sec:
        s = open_sec["share"]
        labels["open_lede"] = (f"ב{_plural(open_sec['n_councils'], 'מועצה אזורית אחת', 'מועצות אזוריות')}, השטח הפתוח "
                               f"(\"שטח כללי\", מחוץ ליישובים) הוא {fmt.pct(s['area'])} מהשטח. "
                               f"נתחו מהתאונות {fmt.pct(s['acc'])}, ומההרוגים {fmt.pct(s['dead'])}.")
        labels["open_aria"] = (f"גרף עמודות מוערמות: חלוקת השטח, התאונות, הפצועים קשה וההרוגים במועצות האזוריות "
                               f"בין השטח הפתוח ליישובים. בשטח הפתוח {fmt.pct(s['dead'])} מההרוגים.")

    summary = (f"נתוני תאונות דרכים לפי רשות מקומית ויישוב: {fmt.int_he(acc_all)} תאונות, "
               f"{fmt.int_he(dead_all)} הרוגים ו-{fmt.int_he(sev_all)} פצועים קשה, {period}. "
               f"דירוג הרשויות לפי היקף, חומרה וצפיפות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "spatial_coverage": f"ישראל, {_plural(n_auth, 'רשות אחת', 'רשויות')}",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"open": open_sec is not None, "map": bool(pts), "scatter": bool(scatter),
                  "sev": len(top_sev) > 0, "dens": len(top_dens) > 0, "dead": len(top_dead) > 0,
                  "shares": len(eligible) > 0},
    }
