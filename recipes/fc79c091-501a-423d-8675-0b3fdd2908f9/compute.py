"""שבילי אופניים בבאר שבע: the municipality's bike-path layer, read from its map file.

Input `geo` is the WGS84 GeoJSON the municipality uploads (one LineString per
bike-path segment). Each row carries SHAPE_Leng (metres, from the GIS layer),
a reference point (lat/lon, not read: every location is measured on the
geometry instead) and `__geometry`. There are no names, types or dates, so
the page is about the network's size and shape:

- how long the segments are and how concentrated the length is;
- where the kilometres lie around the network's centre (compass sector,
  distance ring, 1 km grid), measured on every piece of every line, not on a
  single point per segment;
- how connected the network is: segments whose ends touch another segment
  (within CONNECT_M metres) are joined into continuous stretches.

The real lines are drawn with Leaflet, coloured by length band or by stretch.

Order-independent: features are sorted by (length, geometry) before anything
is numbered, and every later sort is total.
"""
import json
import math

import pandas as pd

M_PER_DEG = 111320.0
LEN_EDGES = [0, 100, 250, 500, 1000, 1500]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
TOP_N = 15
TOP_STRETCH = 12
STRETCH_COLORS = 6          # the longest stretches get their own colour on the map, the rest share one
PARETO_STEPS = 20
SHORT_M = 100
LONG_M = 1000
CONNECT_M = 15.0            # an end point this close to another segment's line counts as connected
RING_CAP = 6
NEAR_KM = 2
QUANT = 100_000             # map coordinates quantised to 1e-5 degrees (about 1 m)
CHUNK_BYTES = 30_000        # each JSON island stays well under the 40KB budget


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km1(m):
    return f"{m / 1000:,.1f}"


def num(v):
    return pd.to_numeric(str(v).replace(",", "").strip(), errors="coerce")


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


def offset_label(k, pos, neg):
    if k == 0:
        return "מרכז"
    return f"{abs(k)} ק״מ {pos if k > 0 else neg}"


def spearman(a, b):
    if len(a) < 3:
        return None
    ra = pd.Series(a).rank(method="average")
    rb = pd.Series(b).rank(method="average")
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(ra.corr(rb))


def haversine(a, b):
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, h)))


def lines_of(raw):
    try:
        geom = json.loads(raw or "null")
    except ValueError:
        return []
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
        pts = []
        for c in p:
            if isinstance(c, list) and len(c) >= 2:
                try:
                    x, y = float(c[0]), float(c[1])
                except (TypeError, ValueError):
                    continue
                if 34.0 <= x <= 36.0 and 29.0 <= y <= 34.0:
                    pts.append((x, y))
        if len(pts) >= 2:
            out.append(pts)
    return out


def encode(pts):
    """Flat [x0, y0, dx1, dy1, ...] in 1e-5 degree integers (lon, lat)."""
    q = [(round(x * QUANT), round(y * QUANT)) for x, y in pts]
    flat = [q[0][0], q[0][1]]
    for (a, b), (x, y) in zip(q, q[1:]):
        flat += [x - a, y - b]
    return flat


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def stretches(segs, tol):
    """Union segments whose end point lies within `tol` metres of another
    segment's line (pieces bucketed on a tol-sized grid, local metres)."""
    par = list(range(len(segs)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    grid = {}
    for si, s in enumerate(segs):
        for part in s["xy"]:
            for a, b in zip(part, part[1:]):
                gx0, gx1 = sorted((int(a[0] // tol), int(b[0] // tol)))
                gy0, gy1 = sorted((int(a[1] // tol), int(b[1] // tol)))
                if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > 2500:
                    # a very long straight piece: index it along its length instead of its whole box
                    steps = int(math.hypot(b[0] - a[0], b[1] - a[1]) // tol) + 1
                    keys = {(int((a[0] + (b[0] - a[0]) * t / steps) // tol) + ox,
                             int((a[1] + (b[1] - a[1]) * t / steps) // tol) + oy)
                            for t in range(steps + 1) for ox in (-1, 0, 1) for oy in (-1, 0, 1)}
                else:
                    keys = [(gx, gy) for gx in range(gx0, gx1 + 1) for gy in range(gy0, gy1 + 1)]
                for k in keys:
                    grid.setdefault(k, []).append((si, a, b))
    for si, s in enumerate(segs):
        for part in s["xy"]:
            for e in (part[0], part[-1]):
                cx, cy = int(e[0] // tol), int(e[1] // tol)
                for gx in (cx - 1, cx, cx + 1):
                    for gy in (cy - 1, cy, cy + 1):
                        for sj, a, b in grid.get((gx, gy), ()):
                            if sj != si and find(sj) != find(si) and seg_dist(e, a, b) <= tol:
                                par[find(si)] = find(sj)
    groups = {}
    for i in range(len(segs)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def compute(frames):
    raw = frames["geo"]
    n_raw = len(raw)

    # ---- one record per feature: declared length, geometry, measured length ----
    recs = []
    for r in raw.to_dict("records"):
        g = r.get("__geometry") or ""
        parts = lines_of(g)
        geo_m = sum(haversine(a, b) for p in parts for a, b in zip(p, p[1:]))
        declared = num(r.get("SHAPE_Leng", ""))
        ok = bool(pd.notna(declared) and declared > 0)
        recs.append({"len": float(declared) if ok else geo_m, "geo_m": geo_m, "parts": parts,
                     "gkey": g, "declared_ok": ok})
    segs = [s for s in recs if s["len"] > 0]
    n_badlen = n_raw - len(segs)
    n_measured = sum(1 for s in segs if not s["declared_ok"])
    segs.sort(key=lambda s: (-s["len"], s["gkey"]))
    for i, s in enumerate(segs):
        s["rank"] = i + 1
    n_seg = len(segs)
    total_m = sum(s["len"] for s in segs)

    geo = [s for s in segs if s["parts"]]
    n_geo = len(geo)
    n_badgeo = n_seg - n_geo

    # ---- local metric frame around the network centre (median of segment midpoints) ----
    def midpoint(parts):
        tot = sum(haversine(a, b) for p in parts for a, b in zip(p, p[1:]))
        half, acc = tot / 2, 0.0
        for p in parts:
            for a, b in zip(p, p[1:]):
                d = haversine(a, b)
                if acc + d >= half and d > 0:
                    t = (half - acc) / d
                    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                acc += d
        return parts[0][0]

    for s in geo:
        s["mid"] = midpoint(s["parts"])
    lo0 = float(pd.Series([s["mid"][0] for s in geo]).median())
    la0 = float(pd.Series([s["mid"][1] for s in geo]).median())
    coslat = math.cos(math.radians(la0))

    def to_xy(pt):
        return ((pt[0] - lo0) * M_PER_DEG * coslat, (pt[1] - la0) * M_PER_DEG)

    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)

    pieces = []     # (x, y, metres, seg rank) at each piece's midpoint, scaled to the declared length
    for s in geo:
        s["xy"] = [[to_xy(pt) for pt in p] for p in s["parts"]]
        mx, my = to_xy(s["mid"])
        s["d"] = math.hypot(mx, my)
        s["sec"] = sector(mx, my)
        scale = s["len"] / s["geo_m"] if s["geo_m"] > 0 else 1.0
        for p in s["xy"]:
            for a, b in zip(p, p[1:]):
                m = math.hypot(b[0] - a[0], b[1] - a[1])
                if m > 0:
                    pieces.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, m * scale, s["rank"]))
    pieces.sort(key=lambda p: (p[3], p[0], p[1], p[2]))
    geo_m_total = sum(p[2] for p in pieces)

    charts, tables = {}, {}

    # ---- length bands: count + km ----
    for s in segs:
        s["lb"] = band_index(s["len"], LEN_EDGES)
    bl = band_labels(LEN_EDGES, "מ׳")
    b_cnt = [sum(1 for s in segs if s["lb"] == i) for i in range(len(LEN_EDGES))]
    b_m = [sum(s["len"] for s in segs if s["lb"] == i) for i in range(len(LEN_EDGES))]
    charts["bands"] = {"names": bl, "count": b_cnt, "km": [round(m / 1000, 2) for m in b_m]}
    tables["bands"] = {"headers": ["אורך הקטע", "קטעים", "ק״מ", "שיעור מהאורך"],
                       "rows": [[l, fmt(c), km1(m), pct(m / total_m)] for l, c, m in zip(bl, b_cnt, b_m)]}

    # ---- pareto ----
    cum, acc = [], 0.0
    for s in segs:
        acc += s["len"]
        cum.append(acc)
    px, py, prow = [], [], []
    for st in range(1, PARETO_STEPS + 1):
        frac = st / PARETO_STEPS
        k = max(1, int(math.ceil(frac * n_seg)))
        share = cum[k - 1] / total_m
        px.append(round(frac * 100, 1))
        py.append(round(share * 100, 1))
        prow.append([f"{frac * 100:.0f}%", fmt(k), pct(share)])
    charts["pareto"] = {"x": px, "y": py}
    tables["pareto"] = {"headers": ["הקטעים הארוכים ביותר", "מספר קטעים", "שיעור מאורך הרשת"], "rows": prow}

    def top_share(frac):
        k = max(1, int(math.ceil(frac * n_seg)))
        return k, cum[k - 1] / total_m

    k20, s20 = top_share(0.2)
    k50, s50 = top_share(0.5)

    def where_of(s):
        if not s["parts"]:
            return "ללא מיקום"
        return f"{SECTORS[s['sec']]}, {km1(s['d'])} ק״מ מהמרכז"

    # ---- connected stretches ----
    comps = []
    for gidx in stretches(geo, CONNECT_M):
        members = sorted((geo[i] for i in gidx), key=lambda s: s["rank"])
        comps.append({"m": sum(s["len"] for s in members), "n": len(members),
                      "first": members[0]["rank"], "members": members})
    comps.sort(key=lambda c: (-c["m"], c["first"]))
    for ci, c in enumerate(comps):
        c["id"] = ci + 1
        for s in c["members"]:
            s["comp"] = ci
            s["comp_m"] = c["m"]
            s["comp_n"] = c["n"]
    n_comp = len(comps)
    n_single = sum(1 for c in comps if c["n"] == 1)
    n_joined_segs = sum(c["n"] for c in comps if c["n"] > 1)
    big = comps[0]
    top_c = comps[:TOP_STRETCH]
    charts["stretches"] = {"names": [f"רצף #{c['id']} · " + ("קטע אחד" if c["n"] == 1 else f"{fmt(c['n'])} קטעים")
                                     for c in top_c],
                           "values": [round(c["m"] / 1000, 2) for c in top_c]}
    tables["stretches"] = {
        "headers": ["רצף", "קטעים ברצף", "ק״מ", "שיעור מהרשת", "הקטע הארוך ברצף, ביחס למרכז"],
        "rows": [[f"#{c['id']}", fmt(c["n"]), km1(c["m"]), pct(c["m"] / total_m), where_of(c["members"][0])]
                 for c in top_c]}
    top_c_m = sum(c["m"] for c in top_c)

    # ---- longest segments ----
    top = segs[:TOP_N]
    tnames, tvals, trows = [], [], []
    for s in top:
        tnames.append(f"#{s['rank']} · {where_of(s)}")
        tvals.append(int(round(s["len"])))
        trows.append([f"#{s['rank']}", where_of(s), fmt(s["len"]), pct(s["len"] / total_m)])
    charts["longest"] = {"names": tnames, "values": tvals}
    tables["longest"] = {"headers": ["דירוג", "מיקום אמצע הקטע ביחס למרכז", "אורך (מ׳)", "שיעור מהרשת"],
                         "rows": trows}

    # ---- sectors: km of line pieces per compass sector ----
    s_m = [0.0] * len(SECTORS)
    s_segs = [set() for _ in SECTORS]
    for x, y, m, rk in pieces:
        i = sector(x, y)
        s_m[i] += m
        s_segs[i].add(rk)
    s_cnt = [len(v) for v in s_segs]
    charts["sectors"] = {"names": SECTORS, "km": [round(m / 1000, 2) for m in s_m], "count": s_cnt}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "קטעים שעוברים בכיוון", "ק״מ", "שיעור מהאורך"],
                         "rows": [[sname, fmt(c), km1(m), pct(m / geo_m_total)]
                                  for sname, c, m in zip(SECTORS, s_cnt, s_m)]}

    # ---- distance rings (1 km), by line pieces ----
    max_d = max(math.hypot(x, y) for x, y, _, _ in pieces)
    n_rings = min(int(max_d // 1000) + 1, RING_CAP)
    rl = [f"עד {fmt(1)} ק״מ"] if n_rings == 1 else band_labels(list(range(n_rings)), "ק״מ")
    r_m = [0.0] * n_rings
    for x, y, m, _ in pieces:
        r_m[min(int(math.hypot(x, y) // 1000), n_rings - 1)] += m
    r_cnt = [0] * n_rings
    r_len = [0.0] * n_rings
    for s in geo:
        k = min(int(s["d"] // 1000), n_rings - 1)
        r_cnt[k] += 1
        r_len[k] += s["len"]
    r_avg = [round(m / c) if c else 0 for m, c in zip(r_len, r_cnt)]
    charts["rings"] = {"names": rl, "km": [round(m / 1000, 2) for m in r_m], "avg": r_avg}
    tables["rings"] = {"headers": ["מרחק מהמרכז", "ק״מ שבילים", "קטעים (לפי אמצע הקטע)", "אורך קטע ממוצע (מ׳)"],
                       "rows": [[l, km1(m), fmt(c), fmt(a)] for l, m, c, a in zip(rl, r_m, r_cnt, r_avg)]}
    within = sum(m for x, y, m, _ in pieces if math.hypot(x, y) < NEAR_KM * 1000)

    # ---- grid heatmap (km per cell, by line pieces) ----
    xs_all = [p[0] for p in pieces]
    ys_all = [p[1] for p in pieces]
    span = max(max(xs_all) - min(xs_all), max(ys_all) - min(ys_all))
    cell = 1000.0 * max(1, int(math.ceil(span / 1000.0 / 14.0)))
    acc_cells = {}
    for x, y, m, rk in pieces:
        k = (int(round(x / cell)), int(round(y / cell)))
        d = acc_cells.setdefault(k, [0.0, set()])
        d[0] += m
        d[1].add(rk)
    gxs = [k[0] for k in acc_cells]
    gys = [k[1] for k in acc_cells]
    xr = list(range(min(gxs), max(gxs) + 1))
    yr = list(range(min(gys), max(gys) + 1))
    ck = int(cell / 1000)
    cells = [[xr.index(k[0]), yr.index(k[1]), round(v[0] / 1000, 2), len(v[1])]
             for k, v in sorted(acc_cells.items())]
    charts["grid"] = {"x": [offset_label(k * ck, "מזרחה", "מערבה") for k in xr],
                      "y": [offset_label(k * ck, "צפונה", "דרומה") for k in yr],
                      "cells": cells, "max": max(c[2] for c in cells)}
    n_cells = len(cells)
    top_cell = max(cells, key=lambda c: (c[2], -c[0], -c[1]))

    # ---- scatter: segment length vs distance of its midpoint ----
    charts["scatter"] = {"points": sorted([round(s["d"] / 1000, 2), int(round(s["len"]))] for s in geo)}
    rho = spearman([s["d"] for s in geo], [s["len"] for s in geo])

    # ---- map: real lines, delta-encoded, chunked into JSON islands ----
    # [band, colour slot, length m, rank, stretch #, stretch km, stretch segments, flat coords]
    feats = []
    for s in geo:
        for p in s["parts"]:
            feats.append([s["lb"], min(s["comp"], STRETCH_COLORS), int(round(s["len"])), s["rank"],
                          s["comp"] + 1, round(s["comp_m"] / 1000, 2), s["comp_n"], encode(p)])
    feats.sort(key=lambda f: (f[3], f[7]))
    chunks, cur, cur_b = [], [], 2
    for f in feats:
        b = len(json.dumps(f, separators=(",", ":"))) + 1
        if cur and cur_b + b > CHUNK_BYTES:
            chunks.append(cur)
            cur, cur_b = [], 2
        cur.append(f)
        cur_b += b
    if cur:
        chunks.append(cur)
    allx = [x for s in geo for p in s["parts"] for x, _ in p]
    ally = [y for s in geo for p in s["parts"] for _, y in p]
    bounds = [[round(min(ally), 5), round(min(allx), 5)], [round(max(ally), 5), round(max(allx), 5)]]
    comp_legend = [{"name": f"רצף #{c['id']}", "km": km1(c["m"])} for c in comps[:STRETCH_COLORS]]
    if n_comp > STRETCH_COLORS:
        rest = sum(c["m"] for c in comps[STRETCH_COLORS:])
        comp_legend.append({"name": f"{fmt(n_comp - STRETCH_COLORS)} רצפים נוספים", "km": km1(rest)})
    charts["map"] = {"chunks": chunks, "bounds": bounds,
                     "bands": [{"name": l, "km": km1(m)} for l, m in zip(bl, b_m)],
                     "comps": comp_legend, "band_names": bl, "colored": STRETCH_COLORS}

    # ---- stats ----
    med_len = float(pd.Series([s["len"] for s in segs]).median())
    mean_len = total_m / n_seg
    n_short = sum(1 for s in segs if s["len"] < SHORT_M)
    m_short = sum(s["len"] for s in segs if s["len"] < SHORT_M)
    n_long = sum(1 for s in segs if s["len"] >= LONG_M)
    m_long = sum(s["len"] for s in segs if s["len"] >= LONG_M)
    ns_span = (max(ally) - min(ally)) * M_PER_DEG
    ew_span = (max(allx) - min(allx)) * M_PER_DEG * coslat

    # ---------- insights ----------
    insights = []
    if n_comp >= 2 and n_geo >= 5:
        insights.append({"id": "connect", "text_he": (
            f"{fmt(n_geo)} הקטעים מתחברים ל־{fmt(n_comp)} רצפים נפרדים "
            f"(קצוות במרחק של עד {fmt(CONNECT_M)} מ׳ מקטע אחר נחשבים מחוברים). "
            f"הרצף הרציף הארוך ביותר משתרע על {km1(big['m'])} ק״מ ({pct(big['m'] / total_m)} מהרשת)"
            + (f", ו־{fmt(n_single)} קטעים אינם נוגעים באף קטע אחר." if n_single >= 2 else "."))})

    if n_seg >= 10 and s20 >= 0.35:
        insights.append({"id": "pareto", "text_he": (
            f"האורך מרוכז בקטעים הארוכים: {fmt(k20)} הקטעים הארוכים ביותר (חמישית מהקטעים) מהווים "
            f"{pct(s20)} מאורך הרשת, ומחצית הקטעים הארוכה יותר מכסה {pct(s50)} ממנו.")})

    if n_long >= 1 and n_seg >= 5:
        insights.append({"id": "long", "text_he": (
            f"{fmt(n_long)} קטעים ארוכים מ־{fmt(LONG_M)} מ׳ ({pct(n_long / n_seg)} מהקטעים) מכסים "
            f"{km1(m_long)} ק״מ, {pct(m_long / total_m)} מאורך הרשת כולה.")})

    if n_short >= 3:
        insights.append({"id": "short", "text_he": (
            f"{fmt(n_short)} קטעים קצרים מ־{fmt(SHORT_M)} מ׳ ({pct(n_short / n_seg)} מהקטעים) מסתכמים "
            f"ב־{fmt(m_short)} מ׳ בלבד ({pct(m_short / total_m)} מאורך הרשת).")})

    first = segs[0]
    if n_seg >= 3 and first["len"] >= 2 * med_len:
        where = (f", באזור ה{SECTORS[first['sec']]} כ־{km1(first['d'])} ק״מ ממרכז הרשת"
                 if first["parts"] else "")
        insights.append({"id": "longest", "text_he": (
            f"הקטע הארוך ביותר משתרע על {fmt(first['len'])} מ׳{where}: "
            f"פי {first['len'] / med_len:.1f} מאורך הקטע החציוני ({fmt(med_len)} מ׳).")})

    if n_geo >= 8:
        ts = max(range(len(SECTORS)), key=lambda i: (s_m[i], -i))
        low = min(range(len(SECTORS)), key=lambda i: (s_m[i], i))
        if s_m[ts] / geo_m_total >= 0.2:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון עם הכי הרבה שבילים ביחס למרכז הרשת הוא {SECTORS[ts]}: {km1(s_m[ts])} ק״מ "
                f"({pct(s_m[ts] / geo_m_total)} מהאורך), לעומת {km1(s_m[low])} ק״מ בלבד בכיוון {SECTORS[low]}.")})

    if n_geo >= 8:
        insights.append({"id": "extent", "text_he": (
            f"השבילים פרושים על כ־{km1(ns_span)} ק״מ מצפון לדרום ועל כ־{km1(ew_span)} ק״מ ממזרח למערב; "
            f"{pct(within / geo_m_total)} מאורכם עובר בטווח של עד {fmt(NEAR_KM)} ק״מ ממרכז הרשת.")})

    if rho is not None and n_geo >= 10:
        if rho >= 0.3:
            txt = (f"ככל שהקטע רחוק יותר ממרכז הרשת הוא נוטה להיות ארוך יותר (מתאם דירוג {rho:.2f}): "
                   f"השבילים בשוליים הם קטעים רציפים יותר.")
        elif rho <= -0.3:
            txt = (f"הקטעים הקרובים למרכז הרשת נוטים להיות ארוכים יותר (מתאם דירוג שלילי של {abs(rho):.2f}), "
                   f"ובשוליים הרשת מפוצלת לקטעים קצרים יותר.")
        else:
            txt = (f"אין קשר ברור בין אורך הקטע למרחקו ממרכז הרשת (מתאם דירוג {abs(rho):.2f} בערך מוחלט, "
                   f"קרוב לאפס): קטעים ארוכים וקצרים פזורים בכל רחבי העיר.")
        insights.append({"id": "spread", "text_he": txt})

    if n_badlen or n_badgeo or n_measured:
        parts = []
        if n_badlen:
            parts.append(f"ל־{fmt(n_badlen)} רשומות אין אורך ואין קו, והן אינן נספרות")
        if n_measured:
            parts.append(f"ל־{fmt(n_measured)} קטעים אין אורך רשום, ואורכם נמדד על הקו")
        if n_badgeo:
            parts.append(f"ל־{fmt(n_badgeo)} קטעים אין קו תקין, והם אינם על המפה ובחישובי המיקום")
        insights.append({"id": "quality", "text_he": "; ".join(parts) + "."})

    # ---------- kpis ----------
    long_share = m_long / total_m
    big_share = big["m"] / total_m
    kpis = {
        "total_km": {"value": round(total_m / 1000, 1), "display": km1(total_m), "tone": "brand",
                     "label": "אורך הרשת (ק״מ)"},
        "segments": {"value": n_seg, "display": fmt(n_seg), "tone": "brand", "label": "קטעי שביל"},
        "stretches": {"value": n_comp, "display": fmt(n_comp),
                      "tone": "warn" if n_comp >= 0.5 * n_geo else "info",
                      "label": "רצפים נפרדים (קטעים מחוברים)"},
        "big_km": {"value": round(big["m"] / 1000, 1), "display": km1(big["m"]),
                   "tone": "ok" if big_share >= 0.5 else "warn" if big_share < 0.2 else "brand",
                   "label": "הרצף הרציף הארוך (ק״מ)"},
        "median": {"value": int(round(med_len)), "display": fmt(med_len), "tone": "info",
                   "label": "אורך קטע חציוני (מטרים)"},
        "long_share": {"value": round(long_share * 100, 1), "display": pct(long_share),
                       "tone": "ok" if long_share >= 0.4 else "warn" if long_share < 0.2 else "brand",
                       "label": f"מהאורך בקטעים של {fmt(LONG_M)} מ׳ ומעלה"},
    }

    summary = (
        f"מפת שבילי האופניים בבאר שבע: {fmt(n_seg)} קטעי שביל באורך {km1(total_m)} ק״מ "
        f"ב־{fmt(n_comp)} רצפים נפרדים. תוואי, אורך, מיקום וקישוריות."
    )
    lede = (
        f"שכבת שבילי האופניים של עיריית באר שבע כוללת {fmt(n_seg)} קטעים, באורך כולל של {km1(total_m)} ק״מ. "
        f"הקטע החציוני ארוך {fmt(med_len)} מ׳ והממוצע {fmt(mean_len)} מ׳"
        + (": מעט קטעים ארוכים מושכים את הממוצע מעל החציון. " if mean_len >= 1.2 * med_len else ". ")
        + "המפה מציגה את תוואי השבילים עצמם, וכל חישובי המיקום, הכיוון והקישוריות נמדדים על הקווים."
    )
    labels = {
        "lede": lede,
        "map_note": (f"תוואי {fmt(n_geo)} קטעי השביל. אפשר לצבוע לפי טווח האורך של הקטע או לפי הרצף המחובר "
                     f"שהוא שייך אליו; לחיצה על קו מציגה את פרטיו."),
        "map_aria": f"מפה אינטראקטיבית של {fmt(n_geo)} קטעי שבילי אופניים בבאר שבע",
        "stretches_note": (f"קטעים שקצה של אחד מהם נמצא במרחק של עד {fmt(CONNECT_M)} מ׳ מקטע אחר חוברו לרצף אחד. "
                           f"{fmt(n_joined_segs)} קטעים שייכים לרצפים של שני קטעים ומעלה, ו־{fmt(n_single)} עומדים לבדם. "
                           f"{fmt(len(top_c))} הרצפים הארוכים מכסים {pct(top_c_m / total_m)} מהרשת."),
        "bands_note": (f"כמה קטעים יש בכל טווח אורך (עמודות) וכמה קילומטרים הם מכסים (קו). "
                       f"{fmt(b_cnt[0])} קטעים קצרים מ־{fmt(LEN_EDGES[1])} מ׳ לעומת {fmt(b_cnt[-1])} מעל {fmt(LEN_EDGES[-1])} מ׳."),
        "pareto_note": (f"איזה חלק מאורך הרשת מכסים הקטעים הארוכים ביותר: {fmt(k20)} הקטעים הארוכים "
                        f"מכסים {pct(s20)} מהאורך. קו אלכסוני היה מעיד על קטעים באורך שווה."),
        "longest_note": (f"{fmt(len(top))} הקטעים הארוכים מתוך {fmt(n_seg)}, עם הכיוון והמרחק של אמצע הקטע ממרכז הרשת "
                         f"(החציון של אמצעי הקטעים). יחד הם {pct(sum(s['len'] for s in top) / total_m)} מהאורך."),
        "sectors_note": ("קילומטרים של שבילים בכל כיוון ביחס למרכז הרשת, לפי התוואי עצמו: "
                         "קטע שחוצה כמה כיוונים נספר בכל אחד מהם לפי חלקו."),
        "rings_note": (f"קילומטרים של שבילים בכל טבעת מרחק ממרכז הרשת (לפי התוואי), והאורך הממוצע של קטע שאמצעו בטבעת. "
                       f"{pct(within / geo_m_total)} מהאורך בטווח של עד {fmt(NEAR_KM)} ק״מ."),
        "grid_note": (f"רשת משבצות של {fmt(ck)} ק״מ סביב מרכז הרשת; הצבע הוא סך קילומטרי השבילים שעוברים במשבצת. "
                      f"שבילים עוברים ב־{fmt(n_cells)} משבצות, והעמוסה ביותר מכילה {top_cell[2]:,.1f} ק״מ."),
        "scatter_note": "כל נקודה היא קטע: מרחק אמצע הקטע ממרכז הרשת (ציר אופקי) מול אורכו (ציר אנכי).",
        "stretches_aria": "הרצפים המחוברים הארוכים ביותר בקילומטרים", "stretches_cap": "רצפים מחוברים",
        "bands_aria": "קטעים וקילומטרים לפי טווח אורך", "bands_cap": "קטעים לפי טווח אורך",
        "pareto_aria": "שיעור מצטבר מאורך הרשת לפי הקטעים הארוכים", "pareto_cap": "ריכוז האורך בקטעים הארוכים",
        "longest_aria": "הקטעים הארוכים ביותר", "longest_cap": "הקטעים הארוכים ביותר",
        "sectors_aria": "קילומטרים לפי כיוון ממרכז הרשת", "sectors_cap": "שבילים לפי כיוון",
        "rings_aria": "קילומטרים לפי מרחק ממרכז הרשת", "rings_cap": "שבילים לפי מרחק מהמרכז",
        "grid_aria": "מפת חום של קילומטרי שבילים לפי משבצת",
        "scatter_aria": "אורך הקטע מול מרחקו ממרכז הרשת",
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
    }
