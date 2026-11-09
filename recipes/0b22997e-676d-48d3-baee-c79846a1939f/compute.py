"""רכבת קלה: מקטעי מסילה קיימים (Ministry of Transport GIS layer, צוות חצב).

One row per track segment of the operating light-rail network (today the
Jerusalem Red Line and the Gush Dan Red Line with its Kiryat Arye branch):
line, section, sub-section, city (AUTHORITY), metropolitan area, street,
the service lines that run on it (MAIN_LINE + ADD_LINES), opening year,
operator and managing company, travel direction, vertical level (street,
underground, elevated), placement in the right of way, one- or two-way
track, what the segment starts and ends at (station, signalised junction,
track split, ...), functional type and its length in metres (ITM).

Two inputs:
  - `main`: the datastore attribute table. Every chart, KPI, table and
    insight reads it.
  - `geo`: the uploaded shapefile (`map: true`), one row per segment with
    its line as WGS84 GeoJSON in `__geometry`. It drives the map only.

Most track is one-way: each travel direction is its own segment, so the
track length is roughly twice the route length. The page says so, and the
route estimate (one-way km / 2 + two-way km) is labelled approximate.

Insight rules each return a Hebrew sentence or None when the premise does
not hold. Every number comes from the data.
"""
import itertools
import json

import pandas as pd
from govlib import fmt, geo

UNKNOWN = "לא צוין"
OTHER = "אחר"
TOP_STREETS = 12
CHUNK_POINTS = 400          # a longer line is split into pieces of this many points
SIMPLIFY_M = (0.0, 1.5, 3.0, 6.0, 12.0)
MAP_BUDGET = 240_000        # rendered characters of all map islands together

# Known vertical levels, in display order; an unknown one is appended.
LEVELS = ["מפלס הרחוב", "תת קרקע", "מעל מפלס הרחוב"]
LEVEL_UNDER = "תת קרקע"
LEVEL_ABOVE = "מעל מפלס הרחוב"
LEVEL_STREET = "מפלס הרחוב"

# Compass directions in radar order (clockwise from north); codes as stored.
DIRS = [("צפון", "צפון"), ("צ-מז", "צפון-מזרח"), ("מזרח", "מזרח"), ("דר-מז", "דרום-מזרח"),
        ("דרום", "דרום"), ("דר-מע", "דרום-מערב"), ("מערב", "מערב"), ("צ-מע", "צפון-מערב")]
AXES = [("מזרח-מערב", ("מזרח", "מערב")), ("צפון-דרום", ("צפון", "דרום")),
        ("צפון-מזרח לדרום-מערב", ("צ-מז", "דר-מע")), ("צפון-מערב לדרום-מזרח", ("צ-מע", "דר-מז"))]

LEN_BINS = [(0, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, None)]

TWO_WAY = "דו כיוונית"


def _km(m):
    return fmt.num_he(m / 1000, 1)


def _pct(x):
    return fmt.pct(x, 1)


def _s(v):
    s = " ".join(str(v).replace('""', '"').split())
    return s


def _metro_he(m):
    return f"מטרופולין {m}" if m != UNKNOWN else UNKNOWN


def _street_he(s):
    if s.isdigit():
        return f"קוד רחוב {s}"
    return s


def _rank_dict(d):
    """dict name -> value, as names ordered value-desc then name."""
    return [k for k, _ in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].map(_s)
    df["m"] = pd.to_numeric(df["Shape_Length"].str.replace(",", "", regex=False), errors="coerce")
    df["year"] = pd.to_numeric(df["YEAROPEN"], errors="coerce")
    for c in ("RAILNAME", "AUTHORITY", "METROPOLIN", "STREET", "VLEVEL", "WLOCATION",
              "DIR_TYPE", "OPERATFIRM", "MANAGFIRM", "MAIN_LINE", "START_", "END", "FUNCTYPE"):
        df[c] = df[c].where(df[c] != "", UNKNOWN)
    df["sect"] = df["RAILNAME"] + "|" + df["SECTID"]
    df = df.sort_values(["RAILNAME", "SECTID", "SUBSECID", "DIRECTION", "STREET", "m", "DATA"],
                        kind="mergesort").reset_index(drop=True)
    return df


def _sum_by(df, col):
    return {k: float(v) for k, v in df.groupby(col)["m"].sum().items()}


def _levels(df):
    present = set(df["VLEVEL"])
    return [lv for lv in LEVELS if lv in present] + sorted(present - set(LEVELS))


def _date(s):
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return None if pd.isna(d) else d


# ── insights ─────────────────────────────────────────────────────────────


def insight_size(total_m, n, metro_m, metros):
    if len(metros) < 2:
        return (f"רשת הרכבת הקלה הקיימת במאגר כוללת {_km(total_m)} ק״מ מסילה "
                f"ב-{n:,} מקטעים, כולם ב{_metro_he(metros[0])}.")
    parts = [f"ב{_metro_he(m)} {_km(metro_m[m])} ק״מ" for m in metros]
    return (f"רשת הרכבת הקלה הקיימת במאגר כוללת {_km(total_m)} ק״מ מסילה ב-{n:,} מקטעים: "
            f"{fmt.join_he(parts)}.")


def insight_one_way(df, total_m):
    if total_m <= 0:
        return None
    two = float(df.loc[df["DIR_TYPE"] == TWO_WAY, "m"].sum())
    one = total_m - two
    share = one / total_m
    if share < 0.8:
        return None
    route = one / 2 + two
    return (f"{_pct(share)} מאורך המסילה חד-כיווני, מסילה נפרדת לכל כיוון נסיעה, ולכן אורך התוואי "
            f"עצמו קטן בערך בחצי: כ-{_km(route)} ק״מ (אומדן: מחצית המסילה החד-כיוונית ועוד המסילה הדו-כיוונית).")


def insight_underground(df, metros, metro_m):
    rows = []
    for m in metros:
        sub = df[df["METROPOLIN"] == m]
        u = float(sub.loc[sub["VLEVEL"] == LEVEL_UNDER, "m"].sum())
        rows.append((m, u, u / metro_m[m] if metro_m[m] > 0 else 0.0, sub))
    rows.sort(key=lambda r: (-r[2], r[0]))
    top_m, top_u, top_share, sub = rows[0]
    if top_share < 0.1:
        return None
    by_city = _sum_by(sub[sub["VLEVEL"] == LEVEL_UNDER], "AUTHORITY")
    cities = _rank_dict(by_city)[:3]
    text = (f"{_pct(top_share)} ממסילות {_metro_he(top_m)} עוברות מתחת לקרקע ({_km(top_u)} ק״מ), "
            f"ב{fmt.join_he(cities)}")
    none = [r[0] for r in rows[1:] if r[1] == 0]
    if none:
        text += f"; ב{fmt.join_he([_metro_he(m) for m in none])} אין מסילה תת-קרקעית במאגר"
    return text + "."


def insight_elevated(df, total_m):
    sub = df[df["VLEVEL"] == LEVEL_ABOVE]
    above = float(sub["m"].sum())
    if above <= 0 or total_m <= 0:
        return None
    streets = [_street_he(s) for s in _rank_dict(_sum_by(sub, "STREET"))[:3]]
    metros = sorted(set(sub["METROPOLIN"]))
    where = f"כולם ב{_metro_he(metros[0])}" if len(metros) == 1 else f"ב-{len(metros):,} מטרופולינים"
    return (f"{_km(above)} ק״מ מסילה ({_pct(above / total_m)}) עוברים מעל מפלס הרחוב, {where}: "
            f"ב{fmt.join_he(streets)}.")


def insight_latest_year(df, total_m):
    y = df.dropna(subset=["year"])
    years = sorted({int(v) for v in y["year"]})
    if len(years) < 2 or total_m <= 0:
        return None
    last = years[-1]
    sub = y[y["year"] == last]
    km = float(sub["m"].sum())
    by_line = _sum_by(sub, "RAILNAME")
    lines = _rank_dict(by_line)
    lead = lines[0]
    if by_line[lead] >= km * 0.999:
        where = f"כולם ב{lead}"
    elif by_line[lead] / km >= 0.6:
        where = f"רובם ב{lead}"
    else:
        where = f"ב-{len(lines):,} קווים"
    return (f"{_km(km)} ק״מ מסילה ({_pct(km / total_m)} מהרשת) רשומים במאגר עם שנת הפתיחה המאוחרת ביותר, "
            f"{last}, {where}.")


def insight_city(city_m, total_m):
    if len(city_m) < 2 or total_m <= 0:
        return None
    order = _rank_dict(city_m)
    a, b = order[0], order[1]
    if city_m[a] <= city_m[b] * 1.1:
        return None
    return (f"{a} מובילה באורך המסילה עם {_km(city_m[a])} ק״מ ({_pct(city_m[a] / total_m)} מהרשת); "
            f"אחריה {b} עם {_km(city_m[b])} ק״מ, מתוך {len(order):,} רשויות שהרכבת עוברת בהן.")


def insight_services(df):
    shared = df[df["ADD_LINES"] != ""]
    if shared.empty:
        return None
    best = None
    for m, sub in shared.groupby("METROPOLIN"):
        tot = float(df.loc[df["METROPOLIN"] == m, "m"].sum())
        km = float(sub["m"].sum())
        if tot > 0 and (best is None or (km / tot, m) > (best[2], best[0])):
            best = (m, km, km / tot, sub)
    m, km, share, sub = best
    if share < 0.2:
        return None
    combos = {}
    for (main, add), g in sub.groupby(["MAIN_LINE", "ADD_LINES"]):
        combos[_services_label(main, add)] = float(g["m"].sum())
    top = _rank_dict(combos)[0]
    return (f"ב{_metro_he(m)} {_km(km)} ק״מ מסילה ({_pct(share)}) משמשים יותר מקו שירות אחד; "
            f"הצירוף הנפוץ ביותר הוא {top} ({_km(combos[top])} ק״מ).")


def insight_placement(df, metros, metro_m):
    if len(metros) < 2:
        return None
    shares = {}
    for (m, w), g in df.groupby(["METROPOLIN", "WLOCATION"]):
        if metro_m.get(m, 0) > 0:
            shares[(m, w)] = float(g["m"].sum()) / metro_m[m]
    best = None
    for w in sorted({k[1] for k in shares} - {UNKNOWN}):
        vals = sorted(((shares.get((m, w), 0.0), m) for m in metros), reverse=True)
        gap = vals[0][0] - vals[-1][0]
        if best is None or gap > best[0]:
            best = (gap, w, vals[0], vals[-1])
    if best is None or best[0] < 0.25:
        return None
    _, w, (hi, hm), (lo, lm) = best
    tail = (f"ואילו ב{_metro_he(lm)} אין מסילה כזו" if lo == 0
            else f"לעומת {_pct(lo)} ב{_metro_he(lm)}")
    return f"{_pct(hi)} ממסילות {_metro_he(hm)} ממוקמות {_place_phrase(w)}, {tail}."


def insight_axis(df, metros):
    out = []
    for m in metros:
        sub = df[df["METROPOLIN"] == m]
        tot = float(sub["m"].sum())
        if tot <= 0:
            continue
        ax = {name: float(sub.loc[sub["DIRECTION"].isin(codes), "m"].sum()) for name, codes in AXES}
        top = _rank_dict(ax)[0]
        share = ax[top] / tot
        if share >= 0.4:
            out.append((share, m, top))
    if not out:
        return None
    out.sort(key=lambda r: (-r[0], r[1]))
    share, m, top = out[0]
    return f"המסילות ב{_metro_he(m)} נמתחות בעיקר בציר {top}: {_pct(share)} מאורכן."


def _place_phrase(w):
    if w.startswith("ב"):
        return w
    return f"ב{w}"


def _services_label(main, add):
    main = main if main != UNKNOWN else ""
    lines = [x.strip() for x in [main] + add.split(",") if x.strip()]
    return " + ".join(lines) if lines else UNKNOWN


# ── map (geo input) ──────────────────────────────────────────────────────


def _haversine_m(a, b):
    return geo.haversine_km(a[1], a[0], b[1], b[0]) * 1000


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
    for p in parts:
        pts = [(float(c[0]), float(c[1])) for c in p if isinstance(c, list) and len(c) >= 2]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _bounds(parts_list):
    xs = [x for parts in parts_list for p in parts for x, _ in p]
    ys = [y for parts in parts_list for p in parts for _, y in p]
    if not xs:
        return None
    return [[round(min(ys), 5), round(min(xs), 5)], [round(max(ys), 5), round(max(xs), 5)]]


def _map_section(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            g = json.loads(r.get("__geometry") or "null")
        except ValueError:
            g = None
        parts = _lines_of(g)
        decl = pd.to_numeric(_s(r.get("Shape_Leng", "")).replace(",", ""), errors="coerce")
        meas = sum(_haversine_m(a, b) for p in parts for a, b in itertools.pairwise(p))
        rows.append({
            "line": _s(r.get("RAILNAME", "")) or UNKNOWN,
            "sect": _s(r.get("SECTNAME", "")) or UNKNOWN,
            "street": _street_he(_s(r.get("STREET", ""))) or UNKNOWN,
            "level": _s(r.get("VLEVEL", "")) or UNKNOWN,
            "city": _s(r.get("AUTHORITY", "")) or UNKNOWN,
            "metro": _s(r.get("METROPOLIN", "")) or UNKNOWN,
            "m": float(decl) if not pd.isna(decl) and decl > 0 else meas,
            "parts": parts,
            "key": r.get("__geometry") or "",
        })
    rows.sort(key=lambda x: (x["line"], x["sect"], x["street"], x["level"], x["city"], x["m"], x["key"]))
    drawn = [x for x in rows if x["parts"]]
    if not drawn:
        return None, None
    line_m = {}
    for x in drawn:
        line_m[x["line"]] = line_m.get(x["line"], 0.0) + x["m"]
    lines = _rank_dict(line_m)
    present = {x["level"] for x in drawn}
    levels = [lv for lv in LEVELS if lv in present] + sorted(present - set(LEVELS))
    cities = sorted({x["city"] for x in drawn})
    org = geo.origin([px for x in drawn for p in x["parts"] for px, _ in p],
                     [py for x in drawn for p in x["parts"] for _, py in p])
    for tol in SIMPLIFY_M:
        tol_u = tol / 1.1
        feats = []
        for x in drawn:
            meta = [lines.index(x["line"]), levels.index(x["level"]), cities.index(x["city"]),
                    x["sect"], x["street"], _km(x["m"])]
            for p in x["parts"]:
                simp = geo.simplify(geo.quantize(p), tol_u, ring=False)
                for a in range(0, len(simp) - 1, CHUNK_POINTS):
                    piece = [(px / geo.SCALE, py / geo.SCALE) for px, py in simp[a:a + CHUNK_POINTS + 1]]
                    feats.append(meta + [geo.encode([piece], org, ring=False)[0]])
        if geo.rendered_len(feats) <= MAP_BUDGET:
            break
    chunks = geo.pack(feats)
    metros = {}
    for x in drawn:
        metros.setdefault(x["metro"], []).append(x["parts"])
    zoom = [{"name": _metro_he(m), "bounds": _bounds(metros[m])}
            for m in sorted(metros, key=lambda k: (-len(metros[k]), k))]
    legend = [{"name": ln, "km": _km(line_m[ln])} for ln in lines]
    level_legend = [{"name": lv, "dash": lv == LEVEL_UNDER, "thick": lv == LEVEL_ABOVE} for lv in levels]
    model = {"chunks": chunks, "origin": org, "scale": geo.SCALE, "lines": lines, "levels": levels,
             "cities": cities, "zoom": zoom if len(zoom) > 1 else [], "legend": legend,
             "level_legend": level_legend, "under": levels.index(LEVEL_UNDER) if LEVEL_UNDER in levels else -1,
             "above": levels.index(LEVEL_ABOVE) if LEVEL_ABOVE in levels else -1,
             "bounds": _bounds([x["parts"] for x in drawn])}
    missing = len(rows) - len(drawn)
    note = (f"{len(drawn):,} מקטעי מסילה על המפה, בצבע לפי קו. קו מקווקו מסמן מסילה תת-קרקעית"
            + (", וקו עבה מסילה מעל מפלס הרחוב" if LEVEL_ABOVE in levels else "")
            + ". לחיצה על מקטע מציגה את שם הקטע, הרחוב, הרשות, המפלס והאורך."
            + (" הכפתורים מתמקדים בכל מטרופולין." if len(zoom) > 1 else "")
            + (f" {missing:,} מקטעים ללא קו בקובץ המפה אינם מצוירים." if missing else ""))
    labels = {"map_note": note,
              "map_aria": (f"מפה אינטראקטיבית של {len(drawn):,} מקטעי מסילת הרכבת הקלה, בצבע לפי קו. "
                           "גרסה נגישה: טבלת הנתונים מתחת לעמוד.")}
    return model, labels


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"])
    bad = int(df["m"].isna().sum() + (df["m"] <= 0).sum())
    df = df[df["m"].notna() & (df["m"] > 0)].copy()
    if df.empty:
        raise ValueError("no segments with a length")
    n = len(df)
    total_m = float(df["m"].sum())

    metro_m = _sum_by(df, "METROPOLIN")
    metros = _rank_dict(metro_m)
    city_m = _sum_by(df, "AUTHORITY")
    cities = _rank_dict(city_m)
    line_m = _sum_by(df, "RAILNAME")
    lines = _rank_dict(line_m)
    levels = _levels(df)

    # ── per-line facts ──
    t_lines = []
    for ln in lines:
        sub = df[df["RAILNAME"] == ln]
        mode = lambda c, s=sub: _rank_dict(s.groupby(c)["m"].sum().to_dict())[0]
        yrs = sorted({int(v) for v in sub["year"].dropna()})
        dates = [d for d in (_date(v) for v in sub["D_UPDATE"]) if d is not None]
        services = sorted({x for v in sub["MAIN_LINE"].tolist() + sub["ADD_LINES"].tolist()
                           for x in (s.strip() for s in v.split(",")) if x and x != UNKNOWN})
        t_lines.append({
            "name": ln, "metro": _metro_he(mode("METROPOLIN")), "km": _km(line_m[ln]),
            "n": f"{len(sub):,}", "sections": f"{sub['SECTID'].nunique():,}",
            "years": " / ".join(str(y) for y in yrs) or "–",
            "operator": mode("OPERATFIRM"), "manager": mode("MANAGFIRM"),
            "services": ", ".join(services) or "–",
            "updated": max(dates).strftime("%d.%m.%Y") if dates else "–",
        })

    # ── charts ──
    def stack(cats, col, cat_col, order):
        return [{"name": o, "data": [round(float(df.loc[(df[cat_col] == c) & (df[col] == o), "m"].sum()) / 1000, 2)
                                     for c in cats]} for o in order]

    chart_lines = {"names": lines,
                   "series": stack(lines, "VLEVEL", "RAILNAME", levels)}
    chart_cities = {"names": cities, "series": stack(cities, "VLEVEL", "AUTHORITY", levels)}
    t_cities = []
    for c in cities:
        sub = df[df["AUTHORITY"] == c]
        cells = [_km(float(sub.loc[sub["VLEVEL"] == lv, "m"].sum())) for lv in levels]
        t_cities.append([c, _km(city_m[c]), _pct(city_m[c] / total_m)] + cells)

    # placement in the right of way, km per metro
    places = _rank_dict(_sum_by(df, "WLOCATION"))
    chart_place = {"names": places, "series": [
        {"name": _metro_he(m), "data": [round(float(df.loc[(df["METROPOLIN"] == m) & (df["WLOCATION"] == w), "m"].sum()) / 1000, 2)
                                        for w in places]} for m in metros]}
    t_place = [[w] + [_km(float(df.loc[(df["METROPOLIN"] == m) & (df["WLOCATION"] == w), "m"].sum())) for m in metros]
               + [_km(float(df.loc[df["WLOCATION"] == w, "m"].sum()))] for w in places]

    # service lines on the track
    df["services"] = [_services_label(a, b) for a, b in zip(df["MAIN_LINE"], df["ADD_LINES"])]
    svc_m = _sum_by(df, "services")
    svcs = _rank_dict(svc_m)
    svc_metro = {s: _metro_he(_rank_dict(_sum_by(df[df["services"] == s], "METROPOLIN"))[0]) for s in svcs}
    svc_count = {s: len([x for x in s.split(" + ") if x != UNKNOWN]) for s in svcs}
    chart_svc = {"names": svcs, "values": [round(svc_m[s] / 1000, 2) for s in svcs],
                 "multi": [svc_count[s] > 1 for s in svcs]}
    t_svc = [[s, svc_metro[s], f"{svc_count[s]:,}", _km(svc_m[s]),
              f"{int((df['services'] == s).sum()):,}"] for s in svcs]

    # opening year by line
    yd = df.dropna(subset=["year"]).copy()
    yd["y"] = yd["year"].astype(int)
    years = sorted(set(yd["y"]))

    # segment end points: what each segment starts and ends at
    ends = pd.concat([df[["METROPOLIN", "START_"]].rename(columns={"START_": "node"}),
                      df[["METROPOLIN", "END"]].rename(columns={"END": "node"})], ignore_index=True)
    node_n = ends["node"].value_counts()
    nodes = sorted(node_n.index, key=lambda k: (k == UNKNOWN, -int(node_n[k]), k))
    chart_nodes = {"names": nodes, "series": []}
    t_nodes = []
    metro_ends = {m: int((ends["METROPOLIN"] == m).sum()) for m in metros}
    for m in metros:
        chart_nodes["series"].append({"name": _metro_he(m), "data": [
            round(100 * int(((ends["METROPOLIN"] == m) & (ends["node"] == k)).sum()) / metro_ends[m], 1)
            if metro_ends[m] else 0 for k in nodes]})
    for k in nodes:
        t_nodes.append([k] + [f"{int(((ends['METROPOLIN'] == m) & (ends['node'] == k)).sum()):,}" for m in metros]
                       + [f"{int(node_n[k]):,}"])

    # directions: km per compass direction and metro (radar)
    known = [c for c, _ in DIRS]
    chart_dirs = {"indicators": [lbl for _, lbl in DIRS], "series": []}
    for m in metros:
        sub = df[df["METROPOLIN"] == m]
        chart_dirs["series"].append({"name": _metro_he(m),
                                     "value": [round(float(sub.loc[sub["DIRECTION"] == c, "m"].sum()) / 1000, 2)
                                               for c in known]})
    chart_dirs["max"] = max([v for s in chart_dirs["series"] for v in s["value"]] + [0.1])
    dir_unknown = float(df.loc[~df["DIRECTION"].isin(known), "m"].sum())
    t_dirs = [[lbl] + [_km(float(df.loc[(df["METROPOLIN"] == m) & (df["DIRECTION"] == c), "m"].sum())) for m in metros]
              for c, lbl in DIRS]

    # segment length distribution
    def bin_label(lo, hi):
        return f"{lo:,}-{hi:,}" if hi else f"{lo:,}+"
    bins = [bin_label(lo, hi) for lo, hi in LEN_BINS]
    chart_len = {"names": bins, "series": []}
    t_len = []
    for m in metros:
        mm = df.loc[df["METROPOLIN"] == m, "m"]
        chart_len["series"].append({"name": _metro_he(m), "data": [
            int(((mm >= lo) & ((mm < hi) if hi else True)).sum()) for lo, hi in LEN_BINS]})
    for i, b in enumerate(bins):
        t_len.append([b] + [f"{s['data'][i]:,}" for s in chart_len["series"]])
    medians = {m: float(df.loc[df["METROPOLIN"] == m, "m"].median()) for m in metros}

    # streets
    st = {}
    st_city = {}
    for (m, s), g in df.groupby(["METROPOLIN", "STREET"]):
        if s == UNKNOWN:
            continue
        st[(m, s)] = float(g["m"].sum())
        st_city[(m, s)] = _rank_dict(_sum_by(g, "AUTHORITY"))
    st_order = sorted(st, key=lambda k: (-st[k], k))
    top_st = st_order[:TOP_STREETS]
    chart_st = {"names": [f"{_street_he(s)} ({st_city[(m, s)][0]})" for m, s in top_st],
                "values": [round(st[k] / 1000, 2) for k in top_st]}
    t_st = [[_street_he(s), fmt.join_he(st_city[(m, s)]), _km(st[(m, s)]), _pct(st[(m, s)] / total_m)]
            for m, s in top_st]

    # track type table (direction type + functional type)
    t_track = []
    for col, title in (("DIR_TYPE", "כיווניות"), ("FUNCTYPE", "סוג תפקודי")):
        vals = _sum_by(df, col)
        for v in sorted(vals, key=lambda k: (k == UNKNOWN, -vals[k], k)):
            t_track.append([title, v, f"{int((df[col] == v).sum()):,}", _km(vals[v]), _pct(vals[v] / total_m)])

    # ── KPIs ──
    under = float(df.loc[df["VLEVEL"] == LEVEL_UNDER, "m"].sum())
    above = float(df.loc[df["VLEVEL"] == LEVEL_ABOVE, "m"].sum())
    street_lv = float(df.loc[df["VLEVEL"] == LEVEL_STREET, "m"].sum())
    n_sections = int(df["sect"].nunique())
    kpis = {
        "km": {"value": round(total_m / 1000, 1), "display": _km(total_m), "tone": "brand"},
        "segments": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "lines": {"value": len(lines), "display": f"{len(lines):,}", "tone": "brand"},
        "cities": {"value": len(cities), "display": f"{len(cities):,}", "tone": "brand"},
        "under": {"value": round(under / 1000, 1), "display": _km(under), "tone": "info"},
        "street": {"value": round(street_lv / total_m * 100, 1), "display": _pct(street_lv / total_m), "tone": "brand"},
        "sections": {"value": n_sections, "display": f"{n_sections:,}", "tone": "brand"},
    }
    kpi_labels = {
        "km": "ק״מ מסילה (כל הכיוונים)",
        "segments": "מקטעי מסילה",
        "lines": "קווים במאגר",
        "cities": "רשויות מקומיות על התוואי",
        "under": "ק״מ מסילה תת-קרקעית",
        "street": "מהמסילה במפלס הרחוב",
        "sections": "קטעים (בין תחנות וצמתים)",
    }
    kpi_order = ["km", "segments", "lines", "cities", "under", "street", "sections"]
    if len(years) >= 2:
        last = years[-1]
        lkm = float(yd.loc[yd["y"] == last, "m"].sum())
        kpis["latest"] = {"value": round(lkm / 1000, 1), "display": _km(lkm), "tone": "ok"}
        kpi_labels["latest"] = f"ק״מ עם שנת פתיחה {last}"
    else:
        kpis["latest"] = {"value": round(above / 1000, 1), "display": _km(above), "tone": "brand"}
        kpi_labels["latest"] = "ק״מ מסילה מעל מפלס הרחוב"
    kpi_order.append("latest")

    # ── insights ──
    rules = [
        ("size", insight_size(total_m, n, metro_m, metros)),
        ("one_way", insight_one_way(df, total_m)),
        ("city", insight_city(city_m, total_m)),
        ("underground", insight_underground(df, metros, metro_m)),
        ("elevated", insight_elevated(df, total_m)),
        ("placement", insight_placement(df, metros, metro_m)),
        ("services", insight_services(df)),
        ("latest", insight_latest_year(df, total_m)),
        ("axis", insight_axis(df, metros)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── map ──
    map_model, map_labels = _map_section(frames["geo"])

    # ── labels / ledes ──
    metro_names = fmt.join_he([_metro_he(m) for m in metros])
    lede = (f"מאגר משרד התחבורה ממפה את {n:,} מקטעי המסילה של הרכבת הקלה הפעילה, ב-{len(lines):,} קווים "
            f"ב{metro_names}: {_km(total_m)} ק״מ מסילה ב-{len(cities):,} רשויות מקומיות. לכל מקטע רשומים הרחוב, "
            "המפלס (רחוב, תת-קרקע או גשר), המיקום בזכות הדרך, קווי השירות, שנת הפתיחה והגורם המפעיל.")
    one_way_share = 1 - float(df.loc[df["DIR_TYPE"] == TWO_WAY, "m"].sum()) / total_m
    if one_way_share >= 0.8:
        lede += " רוב המסילה חד-כיוונית, מסילה לכל כיוון, כך שאורך המסילה כפול בקירוב מאורך התוואי."
    if bad:
        lede += f" {bad:,} מקטעים ללא אורך תקין אינם נספרים באורכים."
    top_place = places[0]
    node_gap = None
    if len(metros) >= 2:
        for k in nodes:
            a, b = (chart_nodes["series"][0]["data"][nodes.index(k)], chart_nodes["series"][1]["data"][nodes.index(k)])
            if node_gap is None or abs(a - b) > node_gap[0]:
                node_gap = (abs(a - b), k, a, b)
    top_node = nodes[0]
    top_node_share = int(node_n[top_node]) / len(ends)
    nodes_lede = (f"כל מקטע מתחיל ומסתיים בנקודה מסוג מסוים. {top_node} היא הנפוצה ביותר: "
                  f"{_pct(top_node_share)} מ-{len(ends):,} קצוות המקטעים. האחוזים מחושבים בכל מטרופולין בנפרד.")
    if node_gap and node_gap[0] >= 5:
        nodes_lede += (f" הפער הגדול ביותר בין {_metro_he(metros[0])} ל{_metro_he(metros[1])}: "
                       f"{node_gap[1]}, {fmt.num_he(node_gap[2], 1)}% לעומת {fmt.num_he(node_gap[3], 1)}%.")
    lead_line = lines[0]
    med_txt = fmt.join_he([f"{fmt.int_he(medians[m])} מ׳ ב{_metro_he(m)}" for m in metros])
    labels = {
        "lede": lede,
        "lines_lede": (f"אורך המסילה בכל קו, לפי מפלס. {lead_line} הארוך ביותר עם {_km(line_m[lead_line])} ק״מ"
                       + (f"; מתחת לקרקע עוברים {_km(under)} ק״מ ברשת כולה." if under > 0 else ".")),
        "lines_aria": f"תרשים עמודות מוערמות: ק״מ מסילה לפי קו ומפלס. הארוך ביותר: {lead_line}.",
        "lines_caption": "פרטי הקווים: מטרופולין, אורך, מקטעים, שנת פתיחה רשומה, מפעיל וחברה מנהלת",
        "cities_lede": (f"אורך המסילה בכל רשות מקומית, לפי מפלס. {cities[0]} מובילה עם {_km(city_m[cities[0]])} ק״מ"
                        f" ({_pct(city_m[cities[0]] / total_m)})."),
        "cities_aria": f"תרשים עמודות אופקיות מוערמות: ק״מ מסילה לפי רשות מקומית ומפלס. מובילה: {cities[0]}.",
        "place_lede": (f"היכן המסילה עוברת בתוך זכות הדרך, בכל מטרופולין. המיקום הנפוץ ברשת: {top_place} "
                       f"({_km(_sum_by(df, 'WLOCATION')[top_place])} ק״מ)."),
        "place_aria": f"תרשים עמודות: ק״מ מסילה לפי מיקום בזכות הדרך ומטרופולין. הנפוץ: {top_place}.",
        "svc_lede": (f"קווי השירות שנוסעים על כל מסילה (הקו הראשי ועוד הקווים הנוספים במאגר). "
                     "מסילה שמשמשת כמה קווים מסומנת בצבע כהה. "
                     f"{_km(sum(svc_m[s] for s in svcs if svc_count[s] > 1))} ק״מ משמשים יותר מקו שירות אחד."),
        "svc_aria": "תרשים עמודות אופקיות: ק״מ מסילה לפי צירוף קווי השירות שעליה.",
        "nodes_lede": nodes_lede,
        "nodes_aria": f"תרשים עמודות אופקיות: אחוז קצוות המקטעים לפי סוג נקודה ומטרופולין. הנפוצה: {top_node}.",
        "dirs_lede": ("כיוון הנסיעה של כל מקטע (שמונה כיווני מצפן), בק״מ מסילה לכל מטרופולין. "
                      "צורת המכ״ם מראה לאן התוואי נמתח."
                      + (f" {_km(dir_unknown)} ק״מ ללא כיוון מוכר אינם מוצגים." if dir_unknown > 0 else "")),
        "dirs_aria": "תרשים מכ״ם: ק״מ מסילה לפי כיוון נסיעה ומטרופולין.",
        "len_lede": (f"מספר המקטעים לפי טווח אורך במטרים. אורך חציוני של מקטע: {med_txt}; "
                     f"המקטע הארוך ביותר {fmt.int_he(df['m'].max())} מ׳."),
        "len_aria": "תרשים עמודות: מספר מקטעים לפי טווח אורך במטרים ומטרופולין.",
        "st_lede": (f"הרחובות והדרכים עם אורך המסילה הרב ביותר (סכום המקטעים בשני הכיוונים). "
                    f"בראש: {_street_he(top_st[0][1])} עם {_km(st[top_st[0]])} ק״מ.") if top_st else "",
        "st_aria": (f"תרשים עמודות אופקיות: {len(top_st):,} הרחובות עם הכי הרבה ק״מ מסילה. "
                    f"מוביל: {_street_he(top_st[0][1])}.") if top_st else "",
        "track_lede": (f"{_pct(float(df.loc[df['DIR_TYPE'] == TWO_WAY, 'm'].sum()) / total_m)} מהמסילה דו-כיוונית; "
                       f"השאר מסילה נפרדת לכל כיוון. הסוג התפקודי מבחין בין מסילה רגילה, תפעולית ובתחום תחנה."),
        "track_caption": "אורך המסילה לפי כיווניות וסוג תפקודי",
        "metro_cols": [_metro_he(m) for m in metros],
        "levels": levels,
    }
    labels.update({f"kpi_{k}": v for k, v in kpi_labels.items()})
    if map_labels:
        labels.update(map_labels)

    # ── SEO ──
    seo_desc = (f"מפת תוואי הרכבת הקלה, מקטע אחר מקטע: {_km(total_m)} ק״מ מסילה ב{metro_names}, "
                f"{_km(under)} ק״מ מתחת לקרקע. לפי קו, עיר, רחוב ומפלס.")
    summary = (f"מפת {n:,} מקטעי המסילה של הרכבת הקלה הפעילה ב{metro_names}: {_km(total_m)} ק״מ מסילה "
               f"ב-{len(lines):,} קווים וב-{len(cities):,} רשויות, מהם {_km(under)} ק״מ תת-קרקעיים.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "spatial_coverage": metro_names,
        "seo": {
            "title": "מפת הרכבת הקלה: תוואי המסילות הקיימות בישראל",
            "description": seo_desc,
            "name": "מפת מסילות הרכבת הקלה בישראל",
            "alternate_names": ["רכבת קלה מקטעי מסילה קיימים", "תוואי הרכבת הקלה",
                                "מסלול הרכבת הקלה בירושלים", "מסלול הרכבת הקלה בתל אביב",
                                "מסילות הרכבת הקלה"],
        },
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "map": map_model,
            "lines": chart_lines,
            "cities": chart_cities,
            "place": chart_place,
            "svc": chart_svc,
                        "nodes": chart_nodes,
            "dirs": chart_dirs,
            "len": chart_len,
            "streets": chart_st,
        },
        "tables": {"lines": t_lines, "cities": t_cities, "place": t_place, "svc": t_svc,
                   "nodes": t_nodes, "dirs": t_dirs, "len": t_len, "streets": t_st, "track": t_track},
        "insights": insights,
        "labels": labels,
        "flags": {"map": map_model is not None, "multi_metro": len(metros) >= 2,
                  "streets": bool(top_st)},
    }
