"""תחנות כיבוי והצלה בישראל: the fire stations of Israel Fire and Rescue.

The dataset publishes one full snapshot per year ("... - 2026"), each a new
resource. The input concatenates every snapshot; the page describes the
newest one (by the year in the resource name) and uses the older ones for the
station count over time and the stations added/removed between snapshots.

Coordinates moved from ITM (Geo_X/Geo_Y) to WGS84 (Geo_Lat/Geo_Lon) in the
2026 file; both are read, ITM converted here (Snyder inverse transverse
Mercator on GRS80, no datum shift: ~0.1 km off, plenty for matching stations
and nearest-station distances).

Rows that are headquarters (district HQs "מב"ת", the national commission)
are not fire stations: they are left out of every count and listed apart.
"""
import math
import re
from itertools import pairwise

import pandas as pd
from govlib import fmt, frame, geo

STATION_TYPES = {"אזורית": "תחנה אזורית", "משנה": "תחנת משנה"}
TYPE_ORDER = ["תחנה אזורית", "תחנת משנה"]
HQ_TYPES = {"מחוז", "מטה"}
DISTRICT_ALIASES = {'איו"ש': 'יו"ש'}

# Israel bounds, generous (Eilat to the Hermon).
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 29.3, 33.5, 34.2, 35.95
# Two stations of consecutive snapshots are the same station when their
# normalized names match or, failing that, they sit within this distance.
SAME_STATION_KM = 1.0

# ITM (EPSG:2039) on GRS80.
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_LAT0 = math.radians(31 + 44 / 60 + 3.817 / 3600)
_LON0 = math.radians(35 + 12 / 60 + 16.261 / 3600)
_K0 = 1.0000067
_FE, _FN = 219529.584, 626907.390


def _meridian(phi):
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    return _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                 - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                 - (35 * e6 / 3072) * math.sin(6 * phi))


def itm_to_wgs(x, y):
    e2 = _E2
    ep2 = e2 / (1 - e2)
    m = _meridian(_LAT0) + (y - _FN) / _K0
    mu = m / (_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
          + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
          + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(p1) ** 2
    t1 = math.tan(p1) ** 2
    n1 = _A / math.sqrt(1 - e2 * math.sin(p1) ** 2)
    r1 = _A * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (
        d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120
                   ) / math.cos(p1)
    return math.degrees(lat), math.degrees(lon)


def _valid(lat, lon):
    return (lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon)
            and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX)


def _coords(snap: pd.DataFrame):
    """(lat, lon) per row, None where missing/invalid, and which columns the
    snapshot's coordinates live in (for the map)."""
    cols = set(snap.columns)
    out = [None] * len(snap)
    kind = None
    if {"Geo_Lat", "Geo_Lon"} <= cols:
        lat = frame.num(snap["Geo_Lat"]).tolist()
        lon = frame.num(snap["Geo_Lon"]).tolist()
        for i, (a, b) in enumerate(zip(lat, lon)):
            if _valid(a, b):
                out[i] = (a, b)
        if any(out):
            kind = ("Geo_Lat", "Geo_Lon", "wgs84")
    if kind is None and {"Geo_X", "Geo_Y"} <= cols:
        xs = frame.num(snap["Geo_X"]).tolist()
        ys = frame.num(snap["Geo_Y"]).tolist()
        for i, (x, y) in enumerate(zip(xs, ys)):
            if math.isfinite(x) and math.isfinite(y) and 100_000 < x < 300_000 and 350_000 < y < 820_000:
                a, b = itm_to_wgs(x, y)
                if _valid(a, b):
                    out[i] = (a, b)
        if any(out):
            kind = ("Geo_Y", "Geo_X", "itm")
    return out, kind


def _norm_name(s):
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub("[\"'׳״\\-–]", " ", s)
    s = s.replace("קרית", "קריית").replace("תקווה", "תקוה")
    return " ".join(s.split())


def _is_hq(r):
    return (r["Station_Type"] in HQ_TYPES
            or r["Regional_Station"].startswith('מב"ת')
            or "נציבות" in r["Station"] or "נציבות" in r["Regional_Station"]
            or r["Station"] == "")


def _district(d):
    d = d.replace("״", '"')
    return DISTRICT_ALIASES.get(d, d) or "לא צוין"


def _type_label(t):
    return STATION_TYPES.get(t, t or "לא צוין")


def _snapshot(df, year):
    snap = df[df["year"] == year].copy()
    coords, kind = _coords(snap)
    snap["lat"] = [c[0] if c else None for c in coords]
    snap["lon"] = [c[1] if c else None for c in coords]
    snap["hq"] = snap.apply(_is_hq, axis=1)
    snap["district"] = snap["District"].map(_district)
    snap["type"] = snap["Station_Type"].map(_type_label)
    snap["name"] = snap["Station"].where(snap["Station"] != "", snap["Regional_Station"])
    snap = snap.sort_values(["district", "Regional_Station", "name", "Address", "Location"],
                            kind="stable").reset_index(drop=True)
    return snap, kind


def _diff(prev, cur):
    """Stations added / removed between two snapshots (names), matched by
    normalized name, then by the nearest unmatched station within 1 km."""
    p = prev[~prev["hq"]]
    c = cur[~cur["hq"]]
    pn = set(p["name"].map(_norm_name))
    cn = set(c["name"].map(_norm_name))
    removed = [r for _, r in p.iterrows() if _norm_name(r["name"]) not in cn]
    removed.sort(key=lambda r: r["name"])
    new = [r for _, r in c.iterrows() if _norm_name(r["name"]) not in pn]
    new.sort(key=lambda r: r["name"])
    added = []
    for q in new:
        best = None
        if pd.notna(q["lat"]):
            for i, r in enumerate(removed):
                if pd.isna(r["lat"]):
                    continue
                d = geo.haversine_km(q["lat"], q["lon"], r["lat"], r["lon"])
                if d <= SAME_STATION_KM and (best is None or d < best[0]):
                    best = (d, i)
        if best is None:
            added.append(q["name"])
        else:
            removed.pop(best[1])
    return sorted(set(added)), sorted({r["name"] for r in removed})


def _city_name(addresses):
    """The locality name the addresses share at their end ('... 1 חיפה')."""
    toks = [a.replace(",", " ").split() for a in addresses]
    common = []
    for parts in zip(*[t[::-1] for t in toks]):
        if len(set(parts)) != 1 or any(ch.isdigit() for ch in parts[0]):
            break
        common.append(parts[0])
    return " ".join(common[::-1])


def _iso_districts(iso):
    counts = frame.ranked(pd.Series([r["district"] for r in iso]))
    parts = [f"{fmt.int_he(v)} במחוז {k}" for k, v in counts.items()]
    return f"לפי מחוז: {fmt.join_he(parts)}."


def _counts_line(names, one, many):
    if not names:
        return None
    if len(names) == 1:
        return f"{one} ({names[0]})"
    if len(names) <= 5:
        return f"{many.format(n=len(names))} ({fmt.join_he(names)})"
    return many.format(n=len(names))


def compute(frames):
    raw = frames["stations"].fillna("").copy()
    for col in raw.columns:
        raw[col] = frame.clean_series(raw[col])
    raw["year"] = raw["_resource_name"].str.extract(r"((?:19|20)\d\d)", expand=False)
    raw = raw[raw["year"].notna()].copy()
    if raw.empty:
        raise ValueError("no resource name carries a snapshot year")
    raw["year"] = raw["year"].astype(int)
    # One resource per year (the last by name, if a year was uploaded twice).
    per_year = raw.groupby("year")["_resource_name"].max()
    raw = raw[raw["_resource_name"] == raw["year"].map(per_year)]
    years = sorted(int(y) for y in per_year.index)
    latest_year = years[-1]

    snaps = {}
    kinds = {}
    for y in years:
        sub = raw[raw["year"] == y]
        # A snapshot only carries the columns its own file had.
        present = [c for c in sub.columns if (sub[c] != "").any() or c in (
            "District", "Regional_Station", "Station", "Station_Type", "Address", "Location")]
        snaps[y], kinds[y] = _snapshot(sub[present], y)
    cur = snaps[latest_year]
    st = cur[~cur["hq"]].copy()
    hq = cur[cur["hq"]].copy()
    n = len(st)
    if n == 0:
        raise ValueError("the latest snapshot lists no stations")

    # ── types × districts ─────────────────────────────────────────────
    dist_counts = frame.ranked(st["district"])
    districts = [str(d) for d in dist_counts.index]
    types = [t for t in TYPE_ORDER if t in set(st["type"])] + sorted(
        t for t in set(st["type"]) if t not in TYPE_ORDER)
    ct = pd.crosstab(st["district"], st["type"]).reindex(index=districts, columns=types, fill_value=0)
    type_counts = {t: int(ct[t].sum()) for t in types}
    n_regional = type_counts.get("תחנה אזורית", 0)
    n_sub = type_counts.get("תחנת משנה", 0)

    # ── regional commands ─────────────────────────────────────────────
    reg = []
    for name, g in st.groupby("Regional_Station", sort=True):
        if not name:
            continue
        reg.append({
            "name": str(name),
            "count": len(g),
            "district": str(frame.ranked(g["district"]).index[0]),
            "stations": sorted(set(g["name"])),
        })
    reg.sort(key=lambda r: (-r["count"], r["name"]))
    reg_top = reg[:12]

    # ── localities (City_Code) ────────────────────────────────────────
    city_flag = False
    city_rows, n_cities, n_no_code = [], 0, 0
    if "City_Code" in st.columns:
        coded = st[st["City_Code"] != ""]
        n_no_code = n - len(coded)
        if len(coded) >= n / 2:
            n_cities = coded["City_Code"].nunique()
            for code, g in coded.groupby("City_Code", sort=True):
                if len(g) < 2:
                    continue
                cname = _city_name(sorted(g["Address"]))
                city_rows.append((cname or f"סמל יישוב {code}", len(g), sorted(set(g["name"]))))
            city_rows.sort(key=lambda r: (-r[1], r[0]))
            city_flag = len(city_rows) >= 2

    # ── nearest station ──────────────────────────────────────────────
    pts = st[st["lat"].notna()].sort_values(["name", "Address"], kind="stable")
    plist = list(zip(pts["name"], pts["district"], pts["lat"], pts["lon"]))
    nn = []
    if len(plist) >= 3:
        for i, (nm, dist, la, lo) in enumerate(plist):
            best = None
            for j, (nm2, _d2, la2, lo2) in enumerate(plist):
                if i == j:
                    continue
                d = geo.haversine_km(la, lo, la2, lo2)
                if best is None or (d, nm2) < best:
                    best = (d, nm2)
            nn.append({"name": nm, "district": dist, "km": best[0], "nearest": best[1]})
    nn_flag = len(nn) >= 3
    n_no_geo = n - len(plist)
    nn_df = pd.DataFrame(nn) if nn_flag else pd.DataFrame(columns=["name", "district", "km", "nearest"])
    med_all = float(nn_df["km"].median()) if nn_flag else None
    nn_dist = []
    if nn_flag:
        for d, g in nn_df.groupby("district", sort=True):
            nn_dist.append((str(d), float(g["km"].median()), len(g), float(g["km"].max())))
        nn_dist.sort(key=lambda r: (r[1], r[0]))
    iso = sorted(nn, key=lambda r: (-round(r["km"], 6), r["name"]))[:10]

    # ── history across snapshots ─────────────────────────────────────
    hist_years = years
    hist_dist = list(districts)
    for y in hist_years:
        for d in sorted(set(snaps[y].loc[~snaps[y]["hq"], "district"])):
            if d not in hist_dist:
                hist_dist.append(d)
    hist = {}
    for y in hist_years:
        s = snaps[y][~snaps[y]["hq"]]
        hist[y] = s["district"].value_counts().to_dict()
    hist_total = [int(sum(hist[y].values())) for y in hist_years]
    hist_series = [{"name": d, "data": [int(hist[y].get(d, 0)) for y in hist_years]} for d in hist_dist]

    diffs = []
    for a, b in pairwise(hist_years):
        added, removed = _diff(snaps[a], snaps[b])
        diffs.append({"from": a, "to": b, "added": added, "removed": removed,
                      "n_from": hist_total[hist_years.index(a)], "n_to": hist_total[hist_years.index(b)]})

    # ── phones ───────────────────────────────────────────────────────
    emergency = ""
    if "EmergencyPhoneNumber" in cur.columns:
        v = cur.loc[cur["EmergencyPhoneNumber"] != "", "EmergencyPhoneNumber"]
        if len(v):
            emergency = str(frame.ranked(v).index[0])
    service = ""
    v = cur.loc[cur["PhoneNumber"] != "", "PhoneNumber"] if "PhoneNumber" in cur.columns else pd.Series([], dtype=str)
    if len(v):
        service = str(frame.ranked(v).index[0])
        if service == emergency:
            service = ""

    # ── map ──────────────────────────────────────────────────────────
    kind = kinds[latest_year]
    map_model = None
    if kind:
        map_model = {"resource_name": str(cur["_resource_name"].iloc[0]),
                     "lat_field": kind[0], "lng_field": kind[1], "projection": kind[2]}

    # ── KPIs ─────────────────────────────────────────────────────────
    ly = str(latest_year)
    kpis = {
        "total": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "regional": {"value": n_regional, "display": fmt.int_he(n_regional), "tone": "brand"},
        "sub": {"value": n_sub, "display": fmt.int_he(n_sub), "tone": "brand"},
        "districts": {"value": len(districts), "display": fmt.int_he(len(districts)), "tone": "brand"},
    }
    labels = {}
    flags = {"city": city_flag, "nn": nn_flag, "history": len(hist_years) >= 2,
             "map": map_model is not None, "emergency": bool(emergency), "hq": len(hq) > 0}
    if city_flag:
        kpis["cities"] = {"value": n_cities, "display": fmt.int_he(n_cities), "tone": "brand"}
    if len(hist_years) >= 2:
        prev = hist_years[-2]
        delta = hist_total[-1] - hist_total[-2]
        disp = ("+" if delta > 0 else fmt.MINUS if delta < 0 else "") + fmt.int_he(abs(delta))
        kpis["delta"] = {"value": delta, "display": disp,
                         "tone": "ok" if delta > 0 else "danger" if delta < 0 else "brand"}
        labels["kpi_delta"] = f"שינוי במספר התחנות מאז {prev}"
    if nn_flag:
        kpis["nn"] = {"value": round(med_all, 1), "display": fmt.num_he(med_all), "tone": "info"}
    if emergency:
        kpis["emergency"] = {"value": emergency, "display": emergency, "tone": "danger"}

    # ── insights ─────────────────────────────────────────────────────
    insights = []

    lead = dist_counts.iloc[0]
    if len(dist_counts) >= 2 and dist_counts.iloc[1] < lead:
        second = dist_counts.index[1]
        insights.append({"id": "lead_district", "text_he": (
            f"מחוז {dist_counts.index[0]} מחזיק את מספר התחנות הגדול ביותר: {fmt.int_he(lead)} מתוך "
            f"{fmt.int_he(n)} ({fmt.pct(lead / n)}), לפני מחוז {second} עם {fmt.int_he(dist_counts.iloc[1])}.")})

    if n_regional and n_sub / n > 0.5:
        insights.append({"id": "sub_share", "text_he": (
            f"רוב התחנות הן תחנות משנה: {fmt.int_he(n_sub)} מתוך {fmt.int_he(n)} ({fmt.pct(n_sub / n)}), "
            f"לצד {fmt.int_he(n_regional)} תחנות אזוריות; בממוצע {fmt.num_he(n_sub / n_regional)} "
            "תחנות משנה לכל תחנה אזורית.")})

    if reg and (len(reg) == 1 or reg[0]["count"] > reg[1]["count"]):
        r0 = reg[0]
        insights.append({"id": "top_regional", "text_he": (
            f"התחנה האזורית {r0['name']} (מחוז {r0['district']}) אחראית על הרשת הגדולה ביותר: "
            f"{fmt.int_he(r0['count'])} תחנות כולל התחנה עצמה, מתוך {fmt.int_he(len(reg))} תחנות אזוריות ברשימה.")})

    if city_flag and city_rows[0][1] > city_rows[1][1]:
        c0, c1 = city_rows[0], city_rows[1]
        ties = [c[0] for c in city_rows[1:] if c[1] == c1[1]]
        tail = (f"אחריה {fmt.join_he(ties)} עם {fmt.int_he(c1[1])} כל אחת" if len(ties) > 1
                else f"אחריה {c1[0]} עם {fmt.int_he(c1[1])}")
        insights.append({"id": "top_city", "text_he": (
            f"{c0[0]} היא היישוב עם הכי הרבה תחנות כיבוי: {fmt.int_he(c0[1])}; {tail}.")})

    if nn_flag:
        big = [r for r in nn_dist if r[2] >= 3]
        if len(big) >= 2 and big[-1][1] >= 1.5 * big[0][1] and big[0][1] > 0:
            lo, hi = big[0], big[-1]
            insights.append({"id": "density", "text_he": (
                f"הפריסה הצפופה ביותר במחוז {lo[0]} והדלילה ביותר במחוז {hi[0]}: במחוז {lo[0]} המרחק החציוני מתחנה לתחנה הקרובה "
                f"אליה הוא {fmt.num_he(lo[1])} ק״מ, ובמחוז {hi[0]} {fmt.num_he(hi[1])} ק״מ, "
                f"פי {fmt.num_he(hi[1] / lo[1])}.")})
        top = iso[0]
        if med_all and top["km"] >= 2 * med_all:
            insights.append({"id": "isolated", "text_he": (
                f"התחנה המרוחקת ביותר מתחנה אחרת היא {top['name']} (מחוז {top['district']}): "
                f"{fmt.num_he(top['km'])} ק״מ בקו אווירי עד התחנה הקרובה אליה, {top['nearest']}, "
                f"לעומת חציון ארצי של {fmt.num_he(med_all)} ק״מ.")})

    if len(hist_years) >= 2:
        first, last = hist_total[0], hist_total[-1]
        delta = last - first
        if abs(delta) >= 2:
            verb = "עלה" if delta > 0 else "ירד"
            insights.append({"id": "growth", "text_he": (
                f"מספר התחנות {verb} מ-{fmt.int_he(first)} בתמונת המצב של {hist_years[0]} "
                f"ל-{fmt.int_he(last)} ב-{latest_year} ({'+' if delta > 0 else fmt.MINUS}{fmt.int_he(abs(delta))}).")})
        else:
            insights.append({"id": "growth", "text_he": (
                f"מספר התחנות כמעט לא השתנה: {fmt.int_he(first)} בתמונת המצב של {hist_years[0]} "
                f"ו-{fmt.int_he(last)} ב-{latest_year}.")})
        d = diffs[-1]
        parts = [p for p in (
            _counts_line(d["added"], "נוספה תחנה אחת", "נוספו {n} תחנות"),
            _counts_line(d["removed"], "ירדה מהרשימה תחנה אחת", "ירדו מהרשימה {n} תחנות"),
        ) if p]
        if parts:
            insights.append({"id": "recent", "text_he": (
                f"בין {d['from']} ל-{d['to']} {' ו'.join(parts)}.")})

    # ── text ─────────────────────────────────────────────────────────
    phone_txt = ""
    if emergency:
        phone_txt = f" בשעת חירום חייגו {emergency}" + (f"; מוקד השירות: {service}." if service else ".")
    hq_txt = (f" ברשימה גם {fmt.int_he(len(hq))} מטות (מטות מחוז ונציבות כבאות והצלה), שאינם נספרים כתחנות."
              if len(hq) else "")
    lede = (f"תמונת המצב של {latest_year} מונה {fmt.int_he(n)} תחנות כיבוי והצלה ב-{fmt.int_he(len(districts))} "
            f"מחוזות: {fmt.int_he(n_regional)} תחנות אזוריות ו-{fmt.int_he(n_sub)} תחנות משנה הכפופות להן."
            f"{hq_txt} המפה והמדריך שלמטה מציגים את כתובת כל תחנה; "
            f"קובצי השנים הקודמות ({fmt.join_he([str(y) for y in hist_years[:-1]])}) משמשים להשוואה לאורך זמן."
            if len(hist_years) >= 2 else
            f"תמונת המצב של {latest_year} מונה {fmt.int_he(n)} תחנות כיבוי והצלה ב-{fmt.int_he(len(districts))} "
            f"מחוזות: {fmt.int_he(n_regional)} תחנות אזוריות ו-{fmt.int_he(n_sub)} תחנות משנה.{hq_txt}")
    lede += phone_txt

    summary = (f"{fmt.int_he(n)} תחנות כיבוי והצלה של כבאות והצלה לישראל ({latest_year}) ב-{fmt.int_he(len(districts))} "
               f"מחוזות, עם כתובות, מפה, פריסה לפי מחוז ויישוב ומרחק לתחנה הקרובה.")
    desc = (f"איתור תחנת כיבוי אש קרובה לפי יישוב, שם או כתובת: {fmt.int_he(n)} תחנות כבאות והצלה "
            f"ב-{fmt.int_he(len(districts))} מחוזות, על מפה ועם כתובת מלאה.")
    if emergency:
        desc += f" חירום: {emergency}."

    labels.update({
        "lede": lede,
        "kpi_total": f"תחנות כיבוי והצלה ({ly})",
        "kpi_regional": "תחנות אזוריות",
        "kpi_sub": "תחנות משנה",
        "kpi_districts": "מחוזות",
        "kpi_cities": "יישובים עם תחנה (לפי סמל יישוב)",
        "kpi_nn": "מרחק חציוני לתחנה הקרובה (ק״מ)",
        "kpi_emergency": "מספר החירום של כבאות והצלה",
        "map_note": (f"כל התחנות והמטות בתמונת המצב של {latest_year}. לחיצה על נקודה מציגה את שם התחנה, "
                     "התחנה האזורית שאליה היא שייכת והכתובת."),
        "dist_note": (f"מחוז {districts[0]} מוביל עם {fmt.int_he(int(dist_counts.iloc[0]))} תחנות"
                      + (f", ומחוז {districts[-1]} סוגר עם {fmt.int_he(int(dist_counts.iloc[-1]))}."
                         if len(districts) > 1 else ".")
                      + " כל מחוז בנוי מתחנות אזוריות ותחנות משנה הכפופות להן."),
        "dist_aria": (f"גרף עמודות מוערמות: תחנות כיבוי לפי מחוז וסוג תחנה ב-{latest_year}. "
                      f"מחוז {districts[0]} מוביל עם {fmt.int_he(int(dist_counts.iloc[0]))} תחנות."),
        "dist_caption": f"תחנות כיבוי לפי מחוז וסוג תחנה, {latest_year}",
        "reg_note": (f"{fmt.int_he(len(reg))} תחנות אזוריות, כל אחת עם תחנות המשנה שלה. "
                     f"הגדולה: {reg[0]['name']} עם {fmt.int_he(reg[0]['count'])} תחנות"
                     + (f". בגרף {fmt.int_he(len(reg_top))} הגדולות; הטבלה מפרטת את כולן ואת שמות התחנות."
                        if len(reg) > len(reg_top) else "; הטבלה מפרטת את שמות התחנות.")) if reg else "",
        "reg_aria": (f"גרף עמודות אופקי: מספר התחנות בכל תחנה אזורית. הגדולה {reg[0]['name']} "
                     f"עם {fmt.int_he(reg[0]['count'])} תחנות.") if reg else "",
        "reg_caption": "תחנות אזוריות והתחנות הכפופות להן",
    })
    if city_flag:
        labels.update({
            "city_note": (f"התחנות פרושות ב-{fmt.int_he(n_cities)} יישובים לפי סמל היישוב"
                          + (f"; עוד {fmt.int_he(n_no_code)} תחנות ממוקמות בצמתים, באזורי תעשייה או "
                             "במועצות אזוריות ללא סמל יישוב" if n_no_code else "")
                          + f". {fmt.int_he(len(city_rows))} יישובים מחזיקים יותר מתחנה אחת."),
            "city_aria": (f"גרף עמודות אופקי: יישובים עם יותר מתחנת כיבוי אחת. {city_rows[0][0]} מובילה "
                          f"עם {fmt.int_he(city_rows[0][1])} תחנות."),
            "city_caption": "יישובים עם יותר מתחנת כיבוי אחת",
        })
    if nn_flag:
        labels.update({
            "nn_note": (f"לכל תחנה חושב המרחק בקו אווירי לתחנה הקרובה אליה (בכל הארץ, לא רק באותו מחוז), "
                        f"והגרף מציג את החציון בכל מחוז. החציון הארצי: {fmt.num_he(med_all)} ק״מ."
                        + (f" {fmt.int_he(n_no_geo)} תחנות ללא קואורדינטות תקינות לא נכללו." if n_no_geo else "")),
            "nn_aria": (f"גרף עמודות: מרחק חציוני בק״מ לתחנה הקרובה לפי מחוז. הנמוך במחוז {nn_dist[0][0]} "
                        f"({fmt.num_he(nn_dist[0][1])} ק״מ), הגבוה במחוז {nn_dist[-1][0]} ({fmt.num_he(nn_dist[-1][1])} ק״מ)."),
            "nn_caption": "מרחק לתחנה הקרובה לפי מחוז (ק״מ)",
            "iso_note": (f"{fmt.int_he(len(iso))} התחנות שהמרחק מהן לתחנה הבאה הוא הגדול ביותר. "
                         + _iso_districts(iso)),
            "iso_aria": (f"גרף עמודות אופקי: התחנות המרוחקות ביותר מתחנה אחרת. {iso[0]['name']} "
                         f"במרחק {fmt.num_he(iso[0]['km'])} ק״מ."),
            "iso_caption": "התחנות המרוחקות ביותר מתחנה אחרת",
        })
    if len(hist_years) >= 2:
        labels.update({
            "hist_note": (f"תמונות המצב שפורסמו: {fmt.join_he([str(y) for y in hist_years])}. "
                          f"מ-{fmt.int_he(hist_total[0])} תחנות ב-{hist_years[0]} ל-{fmt.int_he(hist_total[-1])} "
                          f"ב-{latest_year}. מטות אינם נספרים."),
            "hist_aria": (f"גרף עמודות מוערמות: מספר התחנות בכל תמונת מצב לפי מחוז, {hist_years[0]} עד "
                          f"{latest_year}. מ-{fmt.int_he(hist_total[0])} ל-{fmt.int_he(hist_total[-1])} תחנות."),
            "hist_caption": "מספר התחנות בכל תמונת מצב לפי מחוז",
            "diff_note": ("תחנות שנוספו או ירדו מהרשימה בין כל שתי תמונות מצב. תחנה נחשבת לאותה תחנה כששמה זהה "
                          "(בהתעלמות מסוגריים, גרשיים ומקפים), או כשתחנה בשם חדש נמצאת במרחק של עד "
                          f"{fmt.num_he(SAME_STATION_KM)} ק״מ מתחנה שירדה מהרשימה באותה תקופה."),
            "diff_caption": "תחנות שנוספו וירדו בין תמונות המצב",
        })
    labels["dir_note"] = (f"כל {fmt.int_he(n)} התחנות בתמונת המצב של {latest_year}, לפי מחוז: שם, סוג, "
                          "התחנה האזורית והכתובת. לחצו על מחוז כדי לפתוח את הרשימה.")

    # ── tables ───────────────────────────────────────────────────────
    tables = {
        "dist_cols": ["מחוז", "סך הכל", *types],
        "dist": [[d, fmt.int_he(int(dist_counts[d])), *[fmt.int_he(int(ct.loc[d, t])) for t in types]]
                 for d in districts],
        "reg": [[r["name"], r["district"], fmt.int_he(r["count"]), ", ".join(r["stations"])]
                for r in reg],
    }
    if city_flag:
        tables["city"] = [[c[0], fmt.int_he(c[1]), ", ".join(c[2])] for c in city_rows]
    if nn_flag:
        tables["nn"] = [[d, fmt.num_he(m), fmt.num_he(mx), fmt.int_he(k)] for d, m, k, mx in nn_dist]
        tables["iso"] = [[r["name"], r["district"], fmt.num_he(r["km"]), r["nearest"]] for r in iso]
    if len(hist_years) >= 2:
        tables["hist_cols"] = ["שנה", "סך הכל", *hist_dist]
        tables["hist"] = [[str(y), fmt.int_he(hist_total[i]), *[fmt.int_he(s["data"][i]) for s in hist_series]]
                          for i, y in enumerate(hist_years)]
        tables["diff"] = [[f"{d['from']} עד {d['to']}", f"{fmt.int_he(d['n_from'])} ← {fmt.int_he(d['n_to'])}",
                           ", ".join(d["added"]) or "–", ", ".join(d["removed"]) or "–"]
                          for d in reversed(diffs)]

    directory = []
    for d in districts:
        g = st[st["district"] == d].copy()
        g["t_ord"] = g["type"].map(lambda t: TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER))
        g = g.sort_values(["Regional_Station", "t_ord", "name", "Address"], kind="stable")
        directory.append({"district": f"מחוז {d}", "count": fmt.int_he(len(g)), "rows": [
            [r["name"], r["type"], r["Regional_Station"] or "–", r["Address"] or "–", r["Location"] or "–"]
            for _, r in g.iterrows()]})
    if len(hq):
        g = hq.sort_values(["district", "name", "Address"], kind="stable")
        directory.append({"district": "מטות ומפקדות", "count": fmt.int_he(len(g)), "rows": [
            [r["Regional_Station"] or r["name"], "מטה ארצי" if r["Station_Type"] == "מטה" else "מטה מחוז",
             r["district"], r["Address"] or "–", r["Location"] or "–"]
            for _, r in g.iterrows()]})

    charts = {
        "dist": {"labels": districts, "total": [int(dist_counts[d]) for d in districts],
                 "series": [{"name": t, "data": [int(ct.loc[d, t]) for d in districts]} for t in types]},
        "reg": {"labels": [r["name"] for r in reg_top], "values": [r["count"] for r in reg_top],
                "district": [r["district"] for r in reg_top]},
    }
    if city_flag:
        top_c = city_rows[:12]
        charts["city"] = {"labels": [c[0] for c in top_c], "values": [c[1] for c in top_c]}
    if nn_flag:
        charts["nn"] = {"labels": [r[0] for r in nn_dist], "values": [round(r[1], 1) for r in nn_dist],
                        "n": [r[2] for r in nn_dist], "national": round(med_all, 1)}
        charts["iso"] = {"labels": [r["name"] for r in iso], "values": [round(r["km"], 1) for r in iso],
                         "nearest": [r["nearest"] for r in iso], "district": [r["district"] for r in iso]}
    if len(hist_years) >= 2:
        charts["hist"] = {"years": [str(y) for y in hist_years], "total": hist_total, "series": hist_series}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "temporal_coverage": f"{hist_years[0]}/{latest_year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "תחנות כיבוי אש בישראל: כתובות ומפה לפי יישוב",
                "description": desc,
                "name": "תחנות כיבוי והצלה בישראל",
                "alternate_names": ["תחנות כיבוי", "תחנות כיבוי אש", "תחנות כבאות והצלה",
                                    "רשימת תחנות כיבוי אש", "מפת תחנות כיבוי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "directory": directory,
        "flags": flags,
        "map": map_model,
        "latest_year": ly,
    }
