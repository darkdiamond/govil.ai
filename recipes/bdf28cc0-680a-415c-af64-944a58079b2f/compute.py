"""דרכים (באר שבע): the city's road-edge line layer (asphalt edge, kerb stones,
road edge).

Two inputs:
  - `main`: the WGS84 CSV, one row per mapped line segment with its length in
    metres (Shape_Leng) and one reference point (lat/lon). It drives the
    length analysis, the KPIs and the row-quality checks. Its three twins
    (XLSX, and the same two with ITM coordinates) are not read.
  - `geo`: the uploaded shapefile (`map: true`), one row per feature with
    Shape_Leng and the real line geometry. It drives every spatial view: each
    segment's Shape_Leng is spread along its own line (pieces between
    vertices, long pieces subdivided), so density, rings and compass sectors
    follow where the road edge actually runs, not one reference point. The
    Leaflet map draws a density grid and the longest segments' real lines.

Lengths are summed as integer millimetres so totals do not depend on row
order; feature order is never relied on (explicit, total sorts).
"""
import json
import math

import numpy as np
import pandas as pd
from govlib import geo

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
KM_PER_DEG = 111.195
# length buckets in metres: [lo, hi); the last is open-ended
LEN_EDGES = [0, 1, 5, 10, 25, 50, 100, 250, 500, 1000]
LORENZ_PCTS = [1, 2, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100]
BASE_CELL_KM = 0.5
MAX_COLS = 24
RING_KM = 1
MAX_RINGS = 6
TOP_CELLS = 10
LONG_M = 1000
TINY_M = 1
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
HEAD_PCT = 10
HEAD_MIN_SHARE = 0.3
TINY_MIN_SHARE = 0.02
CORE_DROP = 0.5
SECTOR_LEAD_RATIO = 1.15
DUP_MIN_SHARE = 0.001
DUP_WARN_SHARE = 0.005
# orientation: line direction folded to 0-180 degrees, in bins of this width
ORIENT_BIN = 10  # bins centred on 0, 10, ... so axis-snapped pieces sit mid-bin
ORIENT_MIN_KM = 0.01  # only pieces this long: coordinates are rounded to ~1 m
ORIENT_LEAD = 1.5  # top bin share vs an even split, for the insight
SUB_KM = 0.1  # pieces between vertices longer than this are subdivided
# map: the longest segments drawn as real lines
LONG_MAX = 400
LINE_TOL = 3  # Douglas-Peucker tolerance for drawn lines, in 1e-5 degree units (~3 m)
LINE_BUDGET = 150_000  # rendered characters of line JSON across all islands
PIECE_MAX_PTS = 2000  # a longer line part is split (sharing end points) so no item outgrows an island


def _int(n):
    return f"{round(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _km(mm):
    return mm / 1_000_000


def _bucket_name(lo, hi):
    return f"{lo:,}-{hi:,}" if hi is not None else f"‎{lo:,}+"


def _prepare(df):
    out = pd.DataFrame({
        "raw_len": df["Shape_Leng"].str.strip(),
        "raw_lat": df["lat"].str.strip(),
        "raw_lon": df["lon"].str.strip(),
    })
    out["len"] = pd.to_numeric(out["raw_len"].str.replace(",", "", regex=False), errors="coerce")
    out["latf"] = pd.to_numeric(out["raw_lat"], errors="coerce")
    out["lonf"] = pd.to_numeric(out["raw_lon"], errors="coerce")
    ok = (out["len"] > 0) & out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["mm"] = (out["len"] * 1000).round().astype("int64")
    return out, n_bad


def _parts(geom_str):
    """The line parts of one feature's geometry, or [] when unusable."""
    try:
        g = json.loads(geom_str)
    except (TypeError, ValueError):
        return []
    if not isinstance(g, dict):
        return []
    t, c = g.get("type"), g.get("coordinates") or []
    parts = c if t == "MultiLineString" else ([c] if t == "LineString" else [])
    out = []
    for part in parts:
        pts = []
        for p in part or []:
            try:
                x, y = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                return []
            if not (LON_RANGE[0] <= x <= LON_RANGE[1] and LAT_RANGE[0] <= y <= LAT_RANGE[1]):
                return []
            pts.append((x, y))
        if pts:
            out.append(pts)
    return out


def _geo(gdf):
    """Features of the map file with their line parts, sorted by
    (length desc, geometry) so every later step is order-independent."""
    raw_len = gdf["Shape_Leng"].str.strip()
    sl = pd.to_numeric(raw_len.str.replace(",", "", regex=False), errors="coerce")
    feats, n_zero, n_badgeom = [], 0, 0
    for s, v in zip(gdf["__geometry"].tolist(), sl.tolist()):
        if not (v > 0):
            n_zero += 1
            continue
        parts = _parts(s)
        if not parts:
            n_badgeom += 1
            continue
        feats.append((round(v * 1000), s, parts))
    feats.sort(key=lambda f: (-f[0], f[1]))
    return feats, n_zero, n_badgeom


def _direction(dx, dy):
    brg = (90 - math.degrees(math.atan2(dy, dx))) % 360
    return SECTORS[int((brg + 22.5) // 45) % 8]


def _wmedian(values, weights):
    order = np.lexsort((weights, values))
    cum = np.cumsum(weights[order])
    k = int(np.searchsorted(cum, cum[-1] / 2))
    return float(values[order][min(k, len(order) - 1)])


def _orient_name(mid):
    if mid < 22.5 or mid >= 157.5:
        return "צפון-דרום"
    if mid < 67.5:
        return "צפון-מזרח לדרום-מערב"
    if mid < 112.5:
        return "מזרח-מערב"
    return "צפון-מערב לדרום-מזרח"


def insight_head(lorenz):
    share = dict(lorenz).get(HEAD_PCT)
    if share is None or share < HEAD_MIN_SHARE:
        return None
    half = next((p for p, s in lorenz if s >= 0.5), None)
    txt = (f"האורך מרוכז במקטעים הארוכים: {_int(HEAD_PCT)}% מהמקטעים הארוכים ביותר "
           f"מכילים {_pct(share)} מכלל אורך הקווים")
    if half is not None and half < 50:
        txt += f", ומחצית האורך נמצאת ב-{_int(half)}% מהמקטעים בלבד"
    return txt + "."


def insight_tiny(n_tiny, mm_tiny, n, mm_total):
    if n == 0 or n_tiny / n < TINY_MIN_SHARE:
        return None
    return (f"{_int(n_tiny)} מקטעים ({_pct(n_tiny / n)}) קצרים ממטר אחד, אבל יחד הם "
            f"רק {_km(mm_tiny):,.1f} ק״מ ({_pct(mm_tiny / mm_total, 2)} מהאורך), ככל הנראה שאריות "
            f"חיתוך של קווים בצמתים ובפינות.")


def insight_long(n_long, mm_long, mm_total, top):
    if n_long == 0 or top is None:
        return None
    return (f"{_int(n_long)} מקטעים ארוכים מ-{_int(LONG_M)} מטר מכילים "
            f"{_km(mm_long):,.1f} ק״מ ({_pct(mm_long / mm_total)} מהאורך). מרכז הארוך שבהם "
            f"({top['len'] / 1000:.1f} ק״מ) נמצא {top['dir_txt']}.")


def insight_core(rings):
    closed = [r for r in rings if r["dens"] is not None]
    if len(closed) < 3 or closed[0]["dens"] <= 0:
        return None
    core = closed[0]["dens"]
    j = next((i for i, r in enumerate(closed) if i > 0 and r["dens"] < core * CORE_DROP), None)
    if j is None:
        return None
    inner = [r["dens"] for r in closed[:j]]
    drop = closed[j]
    span = (f"בקילומטר הראשון ({core:,.1f} ק״מ קווים לקמ״ר)" if j == 1 else
            f"ב-{_int(j * RING_KM)} הקילומטרים הראשונים ({min(inner):,.1f} עד {max(inner):,.1f} "
            f"ק״מ קווים לקמ״ר)")
    return (f"רשת הדרכים צפופה {span}, ויורדת ל-{drop['dens']:,.1f} בטבעת "
            f"{drop['name']} ק״מ מהמרכז.")


def insight_sector(sec):
    srt = sorted(sec, key=lambda r: (-r["mm"], r["i"]))
    a, b = srt[0], srt[1]
    total = sum(r["mm"] for r in sec)
    if total == 0 or b["mm"] == 0 or a["mm"] / b["mm"] < SECTOR_LEAD_RATIO:
        return None
    low = srt[-1]
    return (f"הכי הרבה קווי דרך עוברים בכיוון {a['name']} מהמרכז: {_km(a['mm']):,.0f} ק״מ "
            f"({_pct(a['mm'] / total)}), מול {_km(low['mm']):,.0f} ק״מ בלבד בכיוון {low['name']}.")


def insight_cell(top_cell, cell_km):
    if top_cell is None:
        return None
    return (f"המשבצת הצפופה ביותר ({cell_km:.1f} על {cell_km:.1f} ק״מ) נמצאת "
            f"{top_cell['label']} מהמרכז, עם {top_cell['km']:,.1f} ק״מ קווים "
            f"({_int(top_cell['dens'])} ק״מ לקמ״ר).")


def insight_orient(bins, total):
    if total <= 0 or len(bins) < 4:
        return None
    even = 1 / len(bins)
    srt = sorted(bins, key=lambda b: (-b["mm"], b["lo"]))
    top = srt[0]
    share = top["mm"] / total
    if share < even * ORIENT_LEAD:
        return None
    txt = (f"הכיוון הנפוץ של קווי הדרך הוא סביב {top['lo']} מעלות מהצפון "
           f"({top['axis']}): {_pct(share)} מהאורך, פי {share / even:.1f} מחלוקה שווה בין הכיוונים")
    perp_lo = (top["lo"] + 90) % 180
    perp = next((b for b in bins if b["lo"] == perp_lo), None)
    if perp is not None and perp in srt[1:3]:
        txt += (f". גם הכיוון הניצב לו (סביב {perp['lo']} מעלות) בולט, עם "
                f"{_pct(perp['mm'] / total)}: סימן לרשת רחובות מאונכת")
    return txt + "."


def insight_dup(n_dup, mm_dup, n):
    if n == 0 or n_dup / n < DUP_MIN_SHARE:
        return None
    return (f"{_int(n_dup)} שורות ({_pct(n_dup / n, 2)}) הן כפילות מלאה של שורה אחרת: "
            f"אותו אורך ואותה נקודה. הן מוסיפות {_km(mm_dup):,.1f} ק״מ לסכום האורכים.")


def _spatial(feats):
    """Spread each feature's length along its line. Returns per-piece arrays
    (x, y in degrees, mm, direction or nan) and per-feature representative
    points (length-weighted mean of piece midpoints)."""
    xs, ys, pid, fid = [], [], [], []
    p = 0
    for i, (_, _, parts) in enumerate(feats):
        for part in parts:
            for x, y in part:
                xs.append(x)
                ys.append(y)
                pid.append(p)
                fid.append(i)
            p += 1
    xs = np.array(xs)
    ys = np.array(ys)
    pid = np.array(pid)
    fid = np.array(fid)
    nf = len(feats)
    mm_f = np.array([f[0] for f in feats], dtype="int64")
    lat_ref = float(np.median(ys))
    kx = KM_PER_DEG * math.cos(math.radians(lat_ref))

    same = pid[:-1] == pid[1:]
    x0, y0 = xs[:-1][same], ys[:-1][same]
    x1, y1 = xs[1:][same], ys[1:][same]
    pf = fid[:-1][same]
    dxk = (x1 - x0) * kx
    dyk = (y1 - y0) * KM_PER_DEG
    plen = np.hypot(dxk, dyk)
    flen = np.bincount(pf, weights=plen, minlength=nf)

    # subdivide long pieces so one never spans much more than SUB_KM
    nsub = np.maximum(1, np.ceil(plen / SUB_KM)).astype(int)
    rep = np.repeat(np.arange(len(plen)), nsub)
    starts = np.repeat(np.cumsum(nsub) - nsub, nsub)
    k = np.arange(len(rep)) - starts
    t = (k + 0.5) / nsub[rep]
    sx = x0[rep] + (x1[rep] - x0[rep]) * t
    sy = y0[rep] + (y1[rep] - y0[rep]) * t
    sf = pf[rep]
    slen = plen[rep] / nsub[rep]
    safe = np.where(flen > 0, flen, 1.0)
    smm = np.where(flen[sf] > 0, np.round(mm_f[sf] * slen / safe[sf]), 0).astype("int64")
    ang = np.degrees(np.arctan2(dxk, dyk)) % 180
    brg = np.where(plen >= ORIENT_MIN_KM, ang, np.nan)[rep]

    # features with no length in the geometry (collapsed by rounding): one
    # point at their first vertex carries their whole length
    first = np.full(nf, -1)
    first[fid[::-1]] = np.arange(len(fid))[::-1]
    zero = np.where(flen <= 0)[0]
    px = np.concatenate([sx, xs[first[zero]]])
    py = np.concatenate([sy, ys[first[zero]]])
    pm = np.concatenate([smm, mm_f[zero]])
    pb = np.concatenate([brg, np.full(len(zero), np.nan)])

    mxp = (x0 + x1) / 2
    myp = (y0 + y1) / 2
    rx = np.bincount(pf, weights=plen * mxp, minlength=nf) / safe
    ry = np.bincount(pf, weights=plen * myp, minlength=nf) / safe
    rx = np.where(flen > 0, rx, xs[first])
    ry = np.where(flen > 0, ry, ys[first])
    return {"x": px, "y": py, "mm": pm, "brg": pb, "rx": rx, "ry": ry, "kx": kx,
            "mm_f": mm_f, "xmin": float(xs.min()), "ymin": float(ys.min()),
            "xmax": float(xs.max()), "ymax": float(ys.max())}


def _lines(feats):
    """The longest segments as simplified, delta-encoded lines (govlib.geo),
    packed into JSON islands. One item per line part (or piece of a long one):
    [rank, length m, flat deltas from `origin`]."""
    cand = feats[:LONG_MAX]
    org = geo.origin([x for f in cand for part in f[2] for x, _ in part],
                     [y for f in cand for part in f[2] for _, y in part]) if cand else [0, 0]
    entries, used, n_drawn = [], 0, 0
    for rank, (mm, _, parts) in enumerate(cand, start=1):
        split = [part[a:a + PIECE_MAX_PTS + 1] for part in parts
                 for a in range(0, max(1, len(part) - 1), PIECE_MAX_PTS)]
        pieces = [[rank, round(mm / 1000), flat]
                  for flat in geo.encode(split, org, tol=LINE_TOL, ring=False) if len(flat) >= 4]
        size = sum(geo.rendered_len(e) + 2 for e in pieces)
        if used + size > LINE_BUDGET:
            break
        used += size
        n_drawn += 1
        entries.extend(pieces)
    return geo.pack(entries), n_drawn, org


def compute(frames):
    df, n_bad = _prepare(frames["main"])
    n = len(df)
    mm_total = int(df["mm"].sum())
    med_m = float(df["len"].median())

    # --- length buckets: share of segments vs share of length
    b_names, b_ns, b_ks, t_len = [], [], [], []
    for i, lo in enumerate(LEN_EDGES):
        hi = LEN_EDGES[i + 1] if i + 1 < len(LEN_EDGES) else None
        m = (df["len"] >= lo) & ((df["len"] < hi) if hi is not None else True)
        cnt = int(m.sum())
        mm = int(df.loc[m, "mm"].sum())
        name = _bucket_name(lo, hi)
        b_names.append(name)
        b_ns.append(round(cnt / n * 100, 2))
        b_ks.append(round(mm / mm_total * 100, 2))
        t_len.append({"name": name, "count": _int(cnt), "seg_share": _pct(cnt / n),
                      "km": f"{_km(mm):,.1f}", "len_share": _pct(mm / mm_total)})
    len_chart = {"names": b_names, "seg": b_ns, "len": b_ks}

    # --- Lorenz: share of length held by the longest p% of segments
    mm_sorted = np.sort(df["mm"].to_numpy())[::-1]
    cum = np.cumsum(mm_sorted)
    lorenz = []
    for p in LORENZ_PCTS:
        k = max(1, math.ceil(n * p / 100))
        lorenz.append((p, float(cum[k - 1]) / mm_total))
    lorenz_chart = {"x": [p for p, _ in lorenz], "y": [round(s * 100, 1) for _, s in lorenz]}
    t_lorenz = [{"name": f"{p}%", "share": _pct(s)} for p, s in lorenz]

    # --- the map file: real geometry for every spatial view
    feats, n_geo_zero, n_geo_bad = _geo(frames["geo"])
    n_geo = len(feats)
    sp = _spatial(feats)
    kx = sp["kx"]
    gx_mm = sp["mm"]
    g_total = int(gx_mm.sum())
    cx0 = _wmedian(sp["x"], gx_mm)
    cy0 = _wmedian(sp["y"], gx_mm)
    dx = (sp["x"] - cx0) * kx
    dy = (sp["y"] - cy0) * KM_PER_DEG
    dist = np.hypot(dx, dy)
    rdx = (sp["rx"] - cx0) * kx
    rdy = (sp["ry"] - cy0) * KM_PER_DEG
    rdist = np.hypot(rdx, rdy)
    flen_m = sp["mm_f"] / 1000

    # --- grid (km of line per cell), from the pieces of every line
    span = max((sp["xmax"] - sp["xmin"]) * kx, (sp["ymax"] - sp["ymin"]) * KM_PER_DEG, 0.01)
    cell = BASE_CELL_KM * max(1, math.ceil(span / BASE_CELL_KM / MAX_COLS))
    gx = ((sp["x"] - sp["xmin"]) * kx // cell).astype(int)
    gy = ((sp["y"] - sp["ymin"]) * KM_PER_DEG // cell).astype(int)
    fx = ((sp["rx"] - sp["xmin"]) * kx // cell).astype(int)
    fy = ((sp["ry"] - sp["ymin"]) * KM_PER_DEG // cell).astype(int)
    cells = (pd.DataFrame({"x": gx, "y": gy, "mm": gx_mm}).groupby(["x", "y"])["mm"].sum()
             .reset_index())
    cnt_cells = pd.DataFrame({"x": fx, "y": fy}).groupby(["x", "y"]).size().rename("c").reset_index()
    cells = cells.merge(cnt_cells, on=["x", "y"], how="left").fillna({"c": 0})
    cells = cells[cells["mm"] > 0].sort_values(["x", "y"]).reset_index(drop=True)
    area = cell * cell
    map_cells = [[int(r.x), int(r.y), round(_km(r.mm), 2), int(r.c)] for r in cells.itertuples()]
    map_meta = {
        "x0": round(sp["xmin"], 6), "y0": round(sp["ymin"], 6),
        "dx": round(cell / kx, 7), "dy": round(cell / KM_PER_DEG, 7),
        "max": round(_km(int(cells["mm"].max())), 2) if len(cells) else 0,
        "bounds": [[round(sp["ymin"], 5), round(sp["xmin"], 5)],
                   [round(sp["ymax"], 5), round(sp["xmax"], 5)]],
        "area": round(area, 4),
    }

    # --- densest cells, labelled by direction and distance from the centre
    cxk = (cx0 - sp["xmin"]) * kx
    cyk = (cy0 - sp["ymin"]) * KM_PER_DEG
    tc = cells.sort_values(["mm", "x", "y"], ascending=[False, True, True]).head(TOP_CELLS)
    top_cells = []
    for r in tc.itertuples():
        ccx = (r.x + 0.5) * cell - cxk
        ccy = (r.y + 0.5) * cell - cyk
        d = math.hypot(ccx, ccy)
        label = "במרכז" if d < cell else f"{_direction(ccx, ccy)}, {d:.1f} ק״מ"
        km = _km(r.mm)
        top_cells.append({"label": label, "km": km, "dens": km / area, "count": int(r.c)})
    cells_chart = {"names": [c["label"] for c in top_cells],
                   "values": [round(c["dens"], 1) for c in top_cells]}
    t_cells = [{"rank": i + 1, "name": c["label"], "km": f"{c['km']:,.1f}",
                "dens": f"{c['dens']:,.1f}", "count": _int(c["count"])}
               for i, c in enumerate(top_cells)]
    top_cell = None
    if top_cells:
        tc0 = top_cells[0]
        top_cell = dict(tc0, label=("במרכז העיר" if tc0["label"] == "במרכז" else
                                    "ב" + tc0["label"].replace(", ", " במרחק ")))

    # --- rings: km of line and density from the pieces; count and median
    # segment length from each segment's representative point
    ring_idx = np.minimum((dist // RING_KM).astype(int), MAX_RINGS)
    rring = np.minimum((rdist // RING_KM).astype(int), MAX_RINGS)
    rings = []
    for k in range(MAX_RINGS + 1):
        mm = int(gx_mm[ring_idx == k].sum())
        fm = rring == k
        cnt = int(fm.sum())
        if k < MAX_RINGS:
            name = f"{k * RING_KM}-{(k + 1) * RING_KM}"
            ar = math.pi * (((k + 1) * RING_KM) ** 2 - (k * RING_KM) ** 2)
        else:
            name = f"‎{k * RING_KM}+"
            ar = None
        rings.append({"name": name, "count": cnt, "mm": mm, "km": _km(mm),
                      "dens": (_km(mm) / ar) if ar else None,
                      "med": float(np.median(flen_m[fm])) if cnt else 0.0})
    while len(rings) > 2 and rings[-1]["mm"] == 0 and rings[-1]["count"] == 0:
        rings.pop()
    ring_chart = {"names": [r["name"] for r in rings],
                  "km": [round(r["km"], 1) for r in rings],
                  "dens": [round(r["dens"], 1) if r["dens"] is not None else None for r in rings],
                  "med": [round(r["med"], 1) for r in rings]}
    t_ring = [{"name": r["name"], "count": _int(r["count"]), "km": f"{r['km']:,.1f}",
               "dens": f"{r['dens']:,.1f}" if r["dens"] is not None else "לא רלוונטי",
               "med": f"{r['med']:,.1f}"} for r in rings]

    # --- compass sectors around the centre
    brg = (90 - np.degrees(np.arctan2(dy, dx))) % 360
    sidx = (((brg + 22.5) // 45).astype(int)) % 8
    rbrg = (90 - np.degrees(np.arctan2(rdy, rdx))) % 360
    ridx = (((rbrg + 22.5) // 45).astype(int)) % 8
    sec = []
    for i, name in enumerate(SECTORS):
        sec.append({"i": i, "name": name, "count": int((ridx == i).sum()),
                    "mm": int(gx_mm[sidx == i].sum())})
    sec_chart = {"names": [s["name"] for s in sec], "values": [round(_km(s["mm"]), 1) for s in sec]}
    t_sec = [{"name": s["name"], "count": _int(s["count"]), "km": f"{_km(s['mm']):,.1f}",
              "share": _pct(s["mm"] / g_total)} for s in sec]

    # --- orientation of the lines (direction folded to 0-180 degrees)
    ob = sp["brg"]
    has = ~np.isnan(ob)
    nb = 180 // ORIENT_BIN
    oidx = ((np.nan_to_num(ob) + ORIENT_BIN / 2) // ORIENT_BIN).astype(int) % nb
    o_total = int(gx_mm[has].sum())
    obins = []
    for i in range(nb):
        mm = int(gx_mm[has & (oidx == i)].sum())
        obins.append({"lo": i * ORIENT_BIN, "mm": mm, "axis": _orient_name(i * ORIENT_BIN)})
    orient_chart = {"names": [f"{b['lo']}°" for b in obins],
                    "values": [round(_km(b["mm"]), 1) for b in obins]}
    t_orient = [{"name": f"{b['lo']}", "axis": b["axis"], "km": f"{_km(b['mm']):,.1f}",
                 "share": _pct(b["mm"] / o_total) if o_total else _pct(0)} for b in obins]

    # --- the longest segments, drawn as real lines on the map
    chunks, n_drawn, line_origin = _lines(feats)
    mm_drawn = int(sum(f[0] for f in feats[:n_drawn]))
    top_long = None
    if feats:
        d0 = float(rdist[0])
        top_long = {"len": feats[0][0] / 1000,
                    "dir_txt": ("במרכז העיר" if d0 < RING_KM / 2 else
                                f"ב{_direction(float(rdx[0]), float(rdy[0]))}, "
                                f"{d0:.1f} ק״מ מהמרכז")}
    long_m = df["len"] >= LONG_M
    n_long = int(long_m.sum())
    mm_long = int(df.loc[long_m, "mm"].sum())

    # --- quality (rows of the table)
    dup = df.duplicated(["raw_len", "raw_lat", "raw_lon"])
    n_dup = int(dup.sum())
    mm_dup = int(df.loc[dup, "mm"].sum())
    same_pt = df.duplicated(["raw_lat", "raw_lon"], keep=False) & ~df.duplicated(
        ["raw_len", "raw_lat", "raw_lon"], keep=False)
    n_same_pt = int(same_pt.sum())
    tiny = df["len"] < TINY_M
    n_tiny = int(tiny.sum())
    mm_tiny = int(df.loc[tiny, "mm"].sum())
    micro = int((df["len"] < 0.1).sum())
    qual = [("קצר ממטר", n_tiny), ("קצר מעשרה סנטימטר", micro), ("כפילות מלאה", n_dup),
            ("נקודה משותפת, אורך שונה", n_same_pt), ("נשמטו (לא תקין)", n_bad)]
    qual_chart = {"names": [a for a, _ in qual], "values": [b for _, b in qual]}
    t_qual = [{"name": a, "count": _int(b), "share": _pct(b / (n + n_bad), 2)} for a, b in qual]

    # --- insights
    cands = [
        ("head", insight_head(lorenz)),
        ("tiny", insight_tiny(n_tiny, mm_tiny, n, mm_total)),
        ("long", insight_long(n_long, mm_long, mm_total, top_long)),
        ("core", insight_core(rings)),
        ("sector", insight_sector(sec)),
        ("cell", insight_cell(top_cell, cell)),
        ("orient", insight_orient(obins, o_total)),
        ("dup", insight_dup(n_dup, mm_dup, n)),
    ]
    insights = [{"id": i, "text_he": x} for i, x in cands if x]

    total_km = _km(mm_total)
    kpis = {
        "segments": {"value": n, "display": _int(n), "tone": "brand",
                     "label": "מקטעי קו ממופים"},
        "km": {"value": round(total_km, 1), "display": f"{total_km:,.0f}", "tone": "brand",
               "label": "אורך כולל של הקווים (ק״מ)"},
        "median": {"value": round(med_m, 1), "display": f"{med_m:,.1f}", "tone": "info",
                   "label": "אורך חציוני למקטע (מטר)"},
        "dups": {"value": n_dup, "display": _int(n_dup),
                 "tone": "warn" if n and n_dup / n >= DUP_WARN_SHARE else "ok",
                 "label": "שורות כפולות במלואן"},
    }

    dropped_geo = n_geo_zero + n_geo_bad
    geo_drop_txt = (f" {_int(dropped_geo)} קווים באורך אפס או בלי קואורדינטות תקינות לא נכללו."
                    if dropped_geo else "")
    ring_first = rings[0]
    sec_lead = max(sec, key=lambda s: (s["mm"], -s["i"]))
    labels = {
        "lede": (f"שכבת הדרכים של עיריית באר שבע: {_int(n)} מקטעי קו של קצה אספלט, אבני שפה "
                 f"וקצה דרך, באורך כולל של כ-{total_km:,.0f} ק״מ. זה אורך הקווים הממופים ולא "
                 f"אורך הכבישים: לכל רחוב יש כמה קווים מקבילים (שני צדי האספלט, שתי שורות אבני "
                 f"שפה). המקטע החציוני ארוך {med_m:,.1f} מטר."),
        "geo_note": (f"התרשימים המרחביים מבוססים על קובץ המפה ({_int(n_geo)} קווים): אורך כל "
                     f"מקטע מתחלק לאורך הקו שלו, כך שקו ארוך נספר בכל האזורים שהוא עובר בהם. "
                     f"המרכז הוא נקודת החציון של אורך הקווים.{geo_drop_txt}"),
        "map_note": (f"כל משבצת ({cell:.1f} על {cell:.1f} ק״מ) צבועה לפי ק״מ הקווים שעוברים בה, "
                     f"עד {map_meta['max']:,.1f} ק״מ במשבצת הצפופה. מעליהן מצוירים "
                     f"{_int(n_drawn)} המקטעים הארוכים ביותר בקו האמיתי שלהם "
                     f"({_km(mm_drawn):,.0f} ק״מ, {_pct(mm_drawn / g_total if g_total else 0)} "
                     f"מהאורך). לחיצה על קו או על משבצת מציגה את הנתונים שלהם."),
        "map_aria": (f"מפת באר שבע: צפיפות קווי הדרך ב-{_int(len(map_cells))} משבצות "
                     f"ו-{_int(n_drawn)} המקטעים הארוכים ביותר."),
        "len_note": "כמה מהמקטעים וכמה מהאורך נמצאים בכל טווח אורך (במטרים). רוב המקטעים קצרים, אבל רוב האורך נמצא במקטעים הארוכים.",
        "len_aria": f"תרשים עמודות: שיעור המקטעים מול שיעור האורך ב-{_int(len(b_names))} טווחי אורך.",
        "len_caption": "מקטעים ואורך לפי טווח אורך המקטע.",
        "lorenz_note": "העקומה מראה כמה מהאורך הכולל נמצא במקטעים הארוכים ביותר: הנקודה על הציר האופקי היא שיעור המקטעים, מהארוך לקצר.",
        "lorenz_aria": f"תרשים קו: שיעור האורך המצטבר לפי שיעור המקטעים הארוכים, {_int(len(lorenz))} נקודות.",
        "lorenz_caption": "שיעור האורך שבמקטעים הארוכים ביותר.",
        "cells_note": (f"{_int(len(top_cells))} המשבצות ({cell:.1f} על {cell:.1f} ק״מ) עם הכי הרבה "
                       f"קווים, לפי כיוון ומרחק מהמרכז; הערך הוא ק״מ קווים לקמ״ר. עמודת המקטעים "
                       f"סופרת מקטעים שמרכזם במשבצת."),
        "cells_aria": (f"תרשים עמודות אופקיות: {_int(len(top_cells))} המשבצות הצפופות, "
                       f"המובילה עם {top_cells[0]['dens']:,.1f} ק״מ לקמ״ר." if top_cells else
                       "תרשים עמודות אופקיות: המשבצות הצפופות."),
        "cells_caption": "המשבצות עם הכי הרבה ק״מ קווים.",
        "ring_note": (f"אורך הקווים וצפיפותם (ק״מ לקמ״ר) לפי מרחק מהמרכז, בטבעות של "
                      f"{_int(RING_KM)} ק״מ; הטבעת האחרונה פתוחה ולכן אין לה צפיפות."),
        "ring_aria": (f"תרשים עמודות וקו: ק״מ קווים וצפיפות לפי {_int(len(rings))} טבעות מרחק, "
                      f"מ-{ring_first['km']:,.0f} ק״מ בטבעת הפנימית."),
        "ring_caption": "אורך, צפיפות ואורך חציוני לפי מרחק מהמרכז.",
        "med_note": "האורך החציוני של מקטע בכל טבעת מרחק (לפי מרכז המקטע). מקטעים קצרים מעידים על רשת צפופה של צמתים, פינות ומפרצים.",
        "med_aria": f"תרשים עמודות: אורך מקטע חציוני (מטר) לפי {_int(len(rings))} טבעות מרחק.",
        "sec_note": "ק״מ קווים בכל אחד משמונת הכיוונים סביב המרכז.",
        "sec_aria": f"תרשים רדאר: ק״מ קווים לפי כיוון מהמרכז, הכי הרבה בכיוון {sec_lead['name']}.",
        "sec_caption": "אורך הקווים לפי כיוון מהמרכז.",
        "orient_note": (f"לאיזה כיוון פונים קווי הדרך עצמם: אורך הקווים לפי זווית הקו מהצפון, "
                        f"בטווחים של {_int(ORIENT_BIN)} מעלות סביב כל ערך (קו מצפון לדרום הוא אפס "
                        f"מעלות, קו ממזרח למערב הוא {_int(90)} מעלות). נספרים רק קטעים בין קודקודים "
                        f"שארוכים מ-{_int(ORIENT_MIN_KM * 1000)} מטר ({_pct(o_total / g_total if g_total else 0)} "
                        f"מהאורך), כי בקטעים קצרים יותר עיגול הקואורדינטות מעוות את הזווית."),
        "orient_aria": f"תרשים עמודות: ק״מ קווים לפי כיוון הקו, {_int(len(obins))} טווחי זווית.",
        "orient_caption": "אורך הקווים לפי כיוון הקו.",
        "qual_note": ("בדיקות על השורות: מקטעים קצרים מאוד (שאריות חיתוך), שורות שחוזרות בדיוק, "
                      "שורות עם אותה נקודה ואורך שונה, ושורות שנשמטו מהניתוח (אורך או מיקום לא תקינים)."),
        "qual_aria": f"תרשים עמודות אופקיות: {_int(len(qual))} בדיקות איכות על השורות.",
        "qual_caption": "בדיקות איכות לפי מספר שורות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"מפת שכבת הדרכים של באר שבע: {_int(n)} מקטעי קצה אספלט, אבני שפה וקצה "
                           f"דרך, כ-{total_km:,.0f} ק״מ קווים. צפיפות לפי אזור, כיווני רחובות ואיכות."),
            "dataset_kind": "map",
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": {"len": len_chart, "lorenz": lorenz_chart, "cells": cells_chart,
                   "ring": ring_chart, "sec": sec_chart, "orient": orient_chart,
                   "qual": qual_chart,
                   "map": {"cells": map_cells, "meta": map_meta, "chunks": chunks,
                           "origin": line_origin, "scale": geo.SCALE}},
        "tables": {"len": t_len, "lorenz": t_lorenz, "cells": t_cells, "ring": t_ring,
                   "sec": t_sec, "orient": t_orient, "qual": t_qual},
        "insights": insights,
        "labels": labels,
    }
