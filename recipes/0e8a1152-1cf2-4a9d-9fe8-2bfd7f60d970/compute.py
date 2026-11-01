"""מבנים לשימור בבאר שבע: four layers, each read from its uploaded map file
(`map: true` inputs, GeoJSON-ITM): buildings (polygons), compounds
(מתחמים, polygons), fences (גדרות, lines) and heritage elements (points:
wells and similar). The refresh downloads each file on every run and hands
compute one row per feature, its properties as strings plus `__geometry`
(WGS84 GeoJSON). The datastore CSVs are attribute twins of the same layers
(the elements CSV's datastore is empty) and are not read.

Everything on the page is aggregate or geometry: counts per preservation
grade, era bucket, footprint band, distance from the layer's median centre,
survey-card coverage, compound areas, buildings and elements that fall
inside a compound (point in polygon on each building's centroid), fence
lengths. The map ships every feature's real outline, delta-encoded at
~1 m (1e-5 degree) and split into JSON islands under CHUNK_BYTES.

Order-independent: every list is sorted on a total key, sums use fsum over
sorted values. The assets are public heritage sites, not people.
"""
import json
import math
import re

import numpy as np
import pandas as pd

STD_ORDER = ["א", "ב1", "ב2", "ג", "ד", "טנטטיבי", "ללא", ""]
ERAS = ["1900-1918", "1918-1935", "1935-1945", "מאוחר מ-1945"]
AREA_EDGES = [0, 50, 100, 200, 500, 2000]
DIST_EDGES = [0, 250, 500, 1000, 2000]
FENCE_EDGES = [0, 10, 25, 50, 100]
DECLARED_RE = re.compile(r"(הוכרז|מוכרז)")
WELL_RE = re.compile(r"באר|בור מים")
CHUNK_BYTES = 40_000   # each GeoJSON island stays well under the 50KB block cap
SCALE = 100_000        # page coordinates in 1e-5 degree (~1 m) integer steps
TOP_CX = 12


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def std_label(s):
    s = (s or "").strip()
    if s == "":
        return "לא צוינה"
    if s == "ללא":
        return "ללא דרגה"
    if s == "טנטטיבי":
        return "טנטטיבי"
    return f"דרגה {s}"


def std_key(s):
    s = (s or "").strip()
    return (STD_ORDER.index(s), s) if s in STD_ORDER else (len(STD_ORDER), s)


def num(series):
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def era_of(y):
    s = str(y).strip().replace("--", "-")
    for e in ERAS:
        if s.startswith(e):
            return e
    return None


def band_labels(edges):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {fmt(edges[1])}")
        elif i + 1 < len(edges):
            out.append(f"{fmt(lo)} עד {fmt(edges[i + 1])}")
        else:
            out.append(f"מעל {fmt(lo)}")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


def stack_series(df, band_col, nbands, std_col="std", top=5):
    """stds (ordered) x bands counts; stds beyond `top` merge into 'אחר'."""
    counts = df.groupby(std_col).size()
    order = sorted(counts.index, key=std_key)
    keep = order[:top]
    names, series = [], []
    for s in keep:
        sub = df[df[std_col] == s]
        names.append(std_label(s))
        series.append([int((sub[band_col] == b).sum()) for b in range(nbands)])
    rest = [s for s in order if s not in keep]
    if rest:
        sub = df[df[std_col].isin(rest)]
        names.append("אחר")
        series.append([int((sub[band_col] == b).sum()) for b in range(nbands)])
    return names, series


# ── geometry ─────────────────────────────────────────────────────────────


def _geom(raw):
    try:
        g = json.loads(raw or "null")
    except ValueError:
        return None
    return g if isinstance(g, dict) else None


def _polygons(g):
    """A (Multi)Polygon as a list of polygons, each a list of rings."""
    if not g:
        return []
    if g.get("type") == "Polygon":
        polys = [g.get("coordinates") or []]
    elif g.get("type") == "MultiPolygon":
        polys = g.get("coordinates") or []
    else:
        return []
    out = []
    for p in polys:
        rings = [[(float(pt[0]), float(pt[1])) for pt in r] for r in p if len(r) >= 3]
        if rings:
            out.append(rings)
    return out


def _lines(g):
    if not g:
        return []
    if g.get("type") == "LineString":
        parts = [g.get("coordinates") or []]
    elif g.get("type") == "MultiLineString":
        parts = g.get("coordinates") or []
    else:
        return []
    return [[(float(pt[0]), float(pt[1])) for pt in p] for p in parts if len(p) >= 2]


def _point(g):
    if g and g.get("type") == "Point":
        c = g.get("coordinates") or []
        if len(c) >= 2:
            return float(c[0]), float(c[1])
    return None


def _ring_area_centroid(ring, kx, ky):
    """Signed planar area (m²) and centroid (degrees) of a ring."""
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
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, (sum(xs) / len(xs), sum(ys) / len(ys))
    return a, (x0 + cx / (6 * a) / kx, y0 + cy / (6 * a) / ky)


def _area_centroid(polys, kx, ky):
    """Total area (outer rings minus holes, m²) and area-weighted centroid."""
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


def _line_len(parts, kx, ky):
    m = 0.0
    for p in parts:
        for (x1, y1), (x2, y2) in zip(p, p[1:]):
            m += math.hypot((x2 - x1) * kx, (y2 - y1) * ky)
    return m


def _in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
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


def _bbox(polys):
    xs = [p[0] for rings in polys for p in rings[0]]
    ys = [p[1] for rings in polys for p in rings[0]]
    return min(xs), min(ys), max(xs), max(ys)


def _enc(pts, ox, oy, closed):
    """A ring/line as a flat delta list of 1e-5 degree integers from the origin."""
    q = [(int(round(x * SCALE)) - ox, int(round(y * SCALE)) - oy) for x, y in pts]
    if closed and len(q) > 1 and q[0] == q[-1]:
        q = q[:-1]
    flat, px, py = [], 0, 0
    for x, y in q:
        if flat and x == px and y == py:
            continue
        flat += [x - px, y - py]
        px, py = x, y
    return flat


def _chunks(feats):
    chunks, cur, size = [], [], 0
    for f in feats:
        # Measured as the template's `tojson` writes it (ASCII escapes, ", "
        # separators), so an island never outgrows the measurement.
        n = len(json.dumps(f)) + 2
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def _unique(names):
    """Category labels must be distinct: a repeated one gets its occurrence number."""
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def _measure_or_shape(shape, measured):
    """The layer's own SHAPE_* value (ITM metres) when it agrees with the
    measured one; a re-export in another unit falls back to the measurement."""
    has_shape = shape is not None and not pd.isna(shape)
    if has_shape and measured > 0 and 0.7 <= float(shape) / measured <= 1.4:
        return float(shape)
    if measured > 0:
        return measured
    return float(shape) if has_shape else float("nan")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    b = frames["buildings"].copy()
    el = frames["elements"].copy()
    cx = frames["complexes"].copy()
    fe = frames["fences"].copy()

    b["polys"] = b["__geometry"].map(lambda r: _polygons(_geom(r)))
    cx["polys"] = cx["__geometry"].map(lambda r: _polygons(_geom(r)))
    fe["parts"] = fe["__geometry"].map(lambda r: _lines(_geom(r)))
    el["pt"] = el["__geometry"].map(lambda r: _point(_geom(r)))
    b = b[b["polys"].map(len) > 0].copy()
    cx = cx[cx["polys"].map(len) > 0].copy()
    fe = fe[fe["parts"].map(len) > 0].copy()
    el = el[el["pt"].notna()].copy()
    if b.empty:
        raise ValueError("no building polygons in the map file")

    # A local metric frame for areas, lengths and distances.
    all_lat = sorted(polys[0][0][0][1] for polys in b["polys"])
    lat_ref = all_lat[len(all_lat) // 2]
    ky = 110_574.0
    kx = 111_320.0 * math.cos(math.radians(lat_ref))

    # ---------- buildings ----------
    b["std"] = b["standard"].str.strip()
    b["card"] = num(b["cartis"]).fillna(0).astype(int)
    b["era"] = b["year"].map(era_of)
    b["declared"] = b["year"].str.contains(DECLARED_RE)
    ac = b["polys"].map(lambda p: _area_centroid(p, kx, ky))
    b["cx"] = ac.map(lambda t: t[1][0])
    b["cy"] = ac.map(lambda t: t[1][1])
    b["area"] = [_measure_or_shape(s, t[0]) for s, t in zip(num(b["SHAPE_Area"]), ac)]
    nb = len(b)

    std_counts = b.groupby("std").size()
    std_order = sorted(std_counts.index, key=std_key)
    std_rows = []
    medians = {}
    for s in std_order:
        sub = b[b["std"] == s]
        med = float(sub["area"].median()) if sub["area"].notna().any() else None
        medians[s] = med
        std_rows.append([std_label(s), fmt(len(sub)), pct(len(sub) / nb), fmt(med) if med is not None else ""])
    charts = {}
    tables = {}
    charts["standards"] = {"names": [std_label(s) for s in std_order], "values": [int(std_counts[s]) for s in std_order]}
    tables["standards"] = {"headers": ["דרגה", "מבנים", "שיעור", "חציון שטח (מ״ר)"], "rows": std_rows}

    # era
    era_counts = [int((b["era"] == e).sum()) for e in ERAS]
    n_era = sum(era_counts)
    charts["eras"] = {"names": ERAS, "values": era_counts}
    tables["eras"] = {
        "headers": ["תקופה", "מבנים", "שיעור מהמסווגים"],
        "rows": [[e, fmt(c), pct(c / n_era) if n_era else ""] for e, c in zip(ERAS, era_counts)],
    }
    has_eras = n_era >= 20

    era_df = b[b["era"].notna()].copy()
    era_df["eb"] = era_df["era"].map(ERAS.index)
    se_names, se_series = stack_series(era_df, "eb", len(ERAS)) if len(era_df) else ([], [])
    charts["std_era"] = {"eras": ERAS, "names": se_names, "series": se_series}
    tables["std_era"] = {
        "headers": ["דרגה"] + ERAS,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(se_names, se_series)],
    }
    has_std_era = len(era_df) >= 20 and len(se_names) >= 2

    # footprint bands
    ab = b[b["area"].notna()].copy()
    ab["ab"] = ab["area"].map(lambda v: band_index(v, AREA_EDGES))
    area_labels = band_labels(AREA_EDGES)
    a_names, a_series = stack_series(ab, "ab", len(AREA_EDGES))
    charts["areas"] = {"bands": area_labels, "names": a_names, "series": a_series}
    tables["areas"] = {
        "headers": ["דרגה"] + area_labels,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(a_names, a_series)],
    }
    med_area = float(ab["area"].median())
    big = int((ab["area"] >= AREA_EDGES[-1]).sum())
    tot_b_area = math.fsum(sorted(ab["area"].tolist()))

    # survey cards
    card_rows, card_names, card_vals = [], [], []
    with_card = int((b["card"] > 0).sum())
    for s in std_order:
        sub = b[b["std"] == s]
        if len(sub) < 5:
            continue
        w = int((sub["card"] > 0).sum())
        card_names.append(std_label(s))
        card_vals.append(round(w / len(sub) * 100, 1))
        card_rows.append([std_label(s), fmt(len(sub)), fmt(w), pct(w / len(sub))])
    charts["cards"] = {"names": card_names, "values": card_vals}
    tables["cards"] = {"headers": ["דרגה", "מבנים", "עם כרטיס סקר", "שיעור"], "rows": card_rows}
    has_cards = len(card_names) >= 2
    cc = b[b["card"] > 0].groupby("card").size()
    cc = cc[cc >= 2]
    cc = cc.reset_index(name="n").sort_values(["n", "card"], ascending=[False, True]).head(10)
    charts["top_cards"] = {"names": [f"כרטיס {int(c)}" for c in cc["card"]], "values": [int(n) for n in cc["n"]]}
    tables["top_cards"] = {
        "headers": ["כרטיס סקר", "מבנים"],
        "rows": [[str(int(c)), fmt(n)] for c, n in zip(cc["card"], cc["n"])],
    }
    has_top_cards = len(cc) >= 3
    n_cards = int(b[b["card"] > 0]["card"].nunique())

    # distance from the median centre of the building centroids
    la0 = float(b["cy"].median())
    lo0 = float(b["cx"].median())
    dy = (b["cy"] - la0) * ky
    dx = (b["cx"] - lo0) * kx
    b["d"] = np.sqrt(dx * dx + dy * dy)
    b["db"] = b["d"].map(lambda v: band_index(v, DIST_EDGES))
    dist_labels = band_labels(DIST_EDGES)
    d_names, d_series = stack_series(b, "db", len(DIST_EDGES))
    charts["dist"] = {"bands": dist_labels, "names": d_names, "series": d_series}
    tables["dist"] = {
        "headers": ["דרגה"] + dist_labels,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(d_names, d_series)],
    }
    med_d = float(b["d"].median())
    within_1k = float((b["d"] < DIST_EDGES[3]).mean())

    # ---------- complexes ----------
    cx["std"] = cx["shimur"].str.strip()
    cx["name"] = cx["Taba"].str.strip()
    cx["nm"] = cx["name"].where(cx["name"] != "", "ללא שם")
    cac = cx["polys"].map(lambda p: _area_centroid(p, kx, ky))
    cx["area"] = [_measure_or_shape(s, t[0]) for s, t in zip(num(cx["SHAPE_Area"]), cac)]
    cx["bb"] = cx["polys"].map(_bbox)
    cx["gkey"] = cx["__geometry"].astype(str)
    cx = cx[cx["area"].notna()].sort_values(
        ["area", "nm", "std", "gkey"], ascending=[False, True, True, True]
    ).reset_index(drop=True)
    ncx = len(cx)
    tot_cx_area = math.fsum(sorted(cx["area"].tolist()))
    cs = cx.head(TOP_CX)
    charts["cx_top"] = {
        "names": _unique([f"{n}, {std_label(s)}" for n, s in zip(cs["nm"], cs["std"])]),
        "values": [round(a / 1000, 1) for a in cs["area"]],
    }
    tables["cx_top"] = {
        "headers": ["מתחם", "דרגה", "שטח (דונם)"],
        "rows": [[n, std_label(s), f"{a / 1000:,.1f}"] for n, s, a in zip(cs["nm"], cs["std"], cs["area"])],
    }
    cstd = sorted(cx["std"].unique(), key=std_key)
    cx_counts = [int((cx["std"] == s).sum()) for s in cstd]
    cx_area = [round(math.fsum(sorted(cx[cx["std"] == s]["area"].tolist())) / 1000, 1) for s in cstd]
    charts["cx_std"] = {"names": [std_label(s) for s in cstd], "counts": cx_counts, "areas": cx_area}
    tables["cx_std"] = {
        "headers": ["דרגה", "מתחמים", "שטח כולל (דונם)"],
        "rows": [[std_label(s), fmt(c), f"{a:,.1f}"] for s, c, a in zip(cstd, cx_counts, cx_area)],
    }
    has_cx = ncx >= 5

    cx_bb = list(cx["bb"])
    cx_polys = list(cx["polys"])

    def containing(x, y):
        return [i for i, (bb, polys) in enumerate(zip(cx_bb, cx_polys))
                if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and _in_polys(x, y, polys)]

    b["cxs"] = [containing(x, y) for x, y in zip(b["cx"], b["cy"])]
    in_cx = int((b["cxs"].map(len) > 0).sum())
    per_cx = [0] * ncx
    for lst in b["cxs"]:
        for i in lst:
            per_cx[i] += 1
    cx_nm = list(cx["nm"])
    cx_sd = list(cx["std"])
    ranked = sorted(range(ncx), key=lambda i: (-per_cx[i], cx_nm[i], i))
    ranked = [i for i in ranked if per_cx[i] > 0][:TOP_CX]
    charts["cx_bld"] = {
        "names": _unique([f"{cx_nm[i]}, {std_label(cx_sd[i])}" for i in ranked]),
        "values": [per_cx[i] for i in ranked],
    }
    tables["cx_bld"] = {
        "headers": ["מתחם", "דרגת המתחם", "מבנים לשימור בתוכו"],
        "rows": [[cx_nm[i], std_label(cx_sd[i]), fmt(per_cx[i])] for i in ranked],
    }
    has_cx_bld = has_cx and len(ranked) >= 3

    # ---------- fences ----------
    fe["std"] = fe["standard"].str.strip()
    measured = fe["parts"].map(lambda p: _line_len(p, kx, ky))
    fe["len"] = [_measure_or_shape(s, m) for s, m in zip(num(fe["SHAPE_Leng"]), measured)]
    fe["gkey"] = fe["__geometry"].astype(str)
    fe = fe[fe["len"].notna()].sort_values(["std", "len", "gkey"], ascending=[True, False, True]).copy()
    nfe = len(fe)
    tot_fe_len = math.fsum(sorted(fe["len"].tolist()))
    fstd = sorted(fe["std"].unique(), key=std_key)
    f_counts = [int((fe["std"] == s).sum()) for s in fstd]
    f_len = [round(math.fsum(sorted(fe[fe["std"] == s]["len"].tolist())) / 1000, 2) for s in fstd]
    charts["fe_std"] = {"names": [std_label(s) for s in fstd], "counts": f_counts, "km": f_len}
    tables["fe_std"] = {
        "headers": ["דרגה", "קטעי גדר", "אורך כולל (ק״מ)"],
        "rows": [[std_label(s), fmt(c), f"{k:,.2f}"] for s, c, k in zip(fstd, f_counts, f_len)],
    }
    fe["fb"] = fe["len"].map(lambda v: band_index(v, FENCE_EDGES))
    fe_labels = band_labels(FENCE_EDGES)
    fn, fs = stack_series(fe, "fb", len(FENCE_EDGES))
    charts["fe_len"] = {"bands": fe_labels, "names": fn, "series": fs}
    tables["fe_len"] = {"headers": ["דרגה"] + fe_labels, "rows": [[n] + [fmt(v) for v in s] for n, s in zip(fn, fs)]}
    has_fe = nfe >= 10
    ungraded_fe = int((fe["std"] == "").sum())

    # ---------- elements ----------
    el["std"] = el["standard"].str.strip()
    el["name"] = el["Taba"].str.strip()
    el["note"] = el["Hakama"].str.strip()
    el["k"] = el["name"].where(el["name"] != "", el["note"])
    el["x"] = el["pt"].map(lambda p: p[0])
    el["y"] = el["pt"].map(lambda p: p[1])
    el["sk"] = el["std"].map(lambda s: std_key(s)[0])
    el = el.sort_values(["sk", "std", "k", "note", "x", "y"]).copy()
    nel = len(el)
    el_std = sorted(el["std"].unique(), key=std_key)
    charts["el_std"] = {
        "names": [std_label(s) for s in el_std],
        "values": [int((el["std"] == s).sum()) for s in el_std],
    }
    tables["el_std"] = {
        "headers": ["דרגה", "אלמנטים"],
        "rows": [[std_label(s), fmt((el["std"] == s).sum())] for s in el_std],
    }
    has_el = nel >= 5
    wells = int((el["name"] + " " + el["note"]).str.contains(WELL_RE).sum())
    el_in_cx = int(sum(1 for x, y in zip(el["x"], el["y"]) if containing(x, y)))
    tables["el_list"] = {
        "headers": ["אלמנט", "דרגה", "הערה"],
        "rows": [[(k if k else "ללא שם"), std_label(s), n] for k, s, n in zip(el["k"], el["std"], el["note"])],
    }

    # layer overview
    layer_names = ["מבנים", "מתחמים", "גדרות", "אלמנטים"]
    layer_vals = [nb, ncx, nfe, nel]
    charts["layers"] = {"names": layer_names, "values": layer_vals}
    tables["layers"] = {
        "headers": ["שכבה", "פריטים"],
        "rows": [[n, fmt(v)] for n, v in zip(layer_names, layer_vals)],
    }

    # ---------- map ----------
    grades = sorted(set(b["std"]) | set(cx["std"]) | set(fe["std"]) | set(el["std"]), key=std_key)
    gi = {s: i for i, s in enumerate(grades)}
    xs, ys = [], []
    for polys in list(b["polys"]) + cx_polys:
        for rings in polys:
            xs += [p[0] for p in rings[0]]
            ys += [p[1] for p in rings[0]]
    for parts in fe["parts"]:
        for line in parts:
            xs += [p[0] for p in line]
            ys += [p[1] for p in line]
    xs += el["x"].tolist()
    ys += el["y"].tolist()
    ox = int(math.floor(min(xs) * SCALE))
    oy = int(math.floor(min(ys) * SCALE))
    year_vals = sorted({y.strip() for y in b["year"] if y.strip()})
    yi = {y: i for i, y in enumerate(year_vals)}

    bfeat = []
    for s, y, card, area, x, yy, polys in zip(b["std"], b["year"], b["card"], b["area"],
                                              b["cx"], b["cy"], b["polys"]):
        enc = [[_enc(r, ox, oy, True) for r in rings] for rings in polys]
        bfeat.append([gi[s], yi.get(y.strip(), -1), int(card),
                      int(round(area)) if not pd.isna(area) else -1,
                      int(round(x * SCALE)) - ox, int(round(yy * SCALE)) - oy, enc])
    bfeat.sort(key=lambda f: (f[0], -f[3], f[4], f[5], f[1], f[2], json.dumps(f[6])))
    cfeat = []
    for i in range(ncx):
        cfeat.append([gi[cx_sd[i]], cx_nm[i], f"{cx.at[i, 'area'] / 1000:,.1f}", per_cx[i],
                      [[_enc(r, ox, oy, True) for r in rings] for rings in cx_polys[i]]])
    ffeat = []
    for s, ln, parts in zip(fe["std"], fe["len"], fe["parts"]):
        ffeat.append([gi[s], int(round(ln)), [_enc(p, ox, oy, False) for p in parts]])
    efeat = []
    for s, k, n, x, y in zip(el["std"], el["k"], el["note"], el["x"], el["y"]):
        efeat.append([gi[s], k if k else "ללא שם", n,
                      int(round(x * SCALE)) - ox, int(round(y * SCALE)) - oy])
    map_model = {
        "b": _chunks(bfeat), "c": _chunks(cfeat), "f": _chunks(ffeat), "e": _chunks(efeat),
        "meta": {
            "origin": [ox, oy], "scale": SCALE,
            "grades": [std_label(s) for s in grades],
            "rank": [std_key(s)[0] for s in grades],
            "years": year_vals,
            "bounds": [[min(ys), min(xs)], [max(ys), max(xs)]],
            "layers": layer_names,
        },
    }

    # ---------- insights ----------
    insights = []

    lead = max(std_order, key=lambda s: (int(std_counts[s]), -std_order.index(s)))
    lead_share = int(std_counts[lead]) / nb
    others = [s for s in std_order if s != lead]
    if lead != "" and lead_share >= 0.3 and others:
        second = sorted(others, key=lambda s: (-int(std_counts[s]), std_key(s)))[0]
        insights.append({"id": "grade_leader", "text_he": (
            f"{std_label(lead)} היא הדרגה הנפוצה ביותר: {fmt(std_counts[lead])} מתוך {fmt(nb)} מבנים ({pct(lead_share)}), "
            f"ואחריה {std_label(second)} עם {fmt(std_counts[second])}.")})

    big_grades = [s for s in std_order if s != "" and int(std_counts[s]) >= 20 and medians[s] is not None]
    if len(big_grades) >= 2:
        hi = max(big_grades, key=lambda s: (medians[s], s))
        lo = min(big_grades, key=lambda s: (medians[s], s))
        if medians[lo] > 0 and medians[hi] / medians[lo] >= 1.5:
            insights.append({"id": "footprint", "text_he": (
                f"החציון של שטח המבנה בדרגות עם לפחות 20 מבנים מגיע ל־{fmt(medians[hi])} מ״ר ב{std_label(hi)} "
                f"לעומת {fmt(medians[lo])} מ״ר ב{std_label(lo)}, פי {medians[hi] / medians[lo]:.1f}.")})

    if has_eras:
        li = max(range(len(ERAS)), key=lambda i: (era_counts[i], -i))
        if era_counts[li] / n_era >= 0.3:
            insights.append({"id": "era", "text_he": (
                f"מבין {fmt(n_era)} המבנים שסווגו לתקופה, {ERAS[li]} מובילה עם {fmt(era_counts[li])} ({pct(era_counts[li] / n_era)}). "
                f"עוד {fmt(nb - n_era)} מבנים ללא תקופה ברורה בשדה.")})

    # buildings inside compounds (point in polygon on the centroid)
    if has_cx and in_cx >= 10:
        txt = f"{fmt(in_cx)} מהמבנים לשימור ({pct(in_cx / nb)}) נמצאים בתוך אחד מ־{fmt(ncx)} מתחמי השימור"
        if len(ranked) >= 2 and per_cx[ranked[0]] > per_cx[ranked[1]] and cx_nm[ranked[0]] != "ללא שם":
            txt += f"; המתחם עם הכי הרבה מבנים הוא ״{cx_nm[ranked[0]]}״ ({fmt(per_cx[ranked[0]])} מבנים)"
        insights.append({"id": "inside", "text_he": txt + "."})

    if with_card > 0:
        best = None
        for s in std_order:
            sub = b[b["std"] == s]
            if s != "" and len(sub) >= 20:
                r = float((sub["card"] > 0).mean())
                if best is None or r > best[1]:
                    best = (s, r)
        txt4 = f"{fmt(with_card)} מבנים ({pct(with_card / nb)}) משויכים לכרטיס סקר, מתוך {fmt(n_cards)} כרטיסים שונים"
        if best is not None and best[1] > 0:
            txt4 += f"; שיעור הכיסוי הגבוה ביותר ב{std_label(best[0])} ({pct(best[1])})"
        insights.append({"id": "cards", "text_he": txt4 + "."})

    if nb >= 50 and within_1k >= 0.5:
        insights.append({"id": "centre", "text_he": (
            f"המבנים מרוכזים סביב מרכז אחד: {pct(within_1k)} מהם במרחק של עד {fmt(DIST_EDGES[3])} מ׳ מהמרכז החציוני של המבנים, "
            f"והמרחק החציוני הוא {fmt(med_d)} מ׳.")})

    nd = int(b["declared"].sum())
    if nd >= 5:
        insights.append({"id": "declared", "text_he": (
            f"בשדה התקופה מצוינת הכרזה לשימור ב־{fmt(nd)} מבנים ({pct(nd / nb)}); "
            f"שאר המבנים נכללים בשכבה בלי ציון כזה.")})

    if has_cx and tot_cx_area > 0:
        share = float(cx.at[0, "area"]) / tot_cx_area
        if share >= 0.15 and cx_nm[0] != "ללא שם":
            insights.append({"id": "complex", "text_he": (
                f"המתחם הגדול ביותר הוא ״{cx_nm[0]}״ בשטח {cx.at[0, 'area'] / 1000:,.1f} דונם, "
                f"{pct(share)} מסך שטחם של {fmt(ncx)} המתחמים ({tot_cx_area / 1000:,.1f} דונם).")})

    if has_fe:
        gix = [i for i, s_ in enumerate(fstd) if s_ != ""]
        txt8 = f"שכבת הגדרות כוללת {fmt(nfe)} קטעים באורך כולל של {tot_fe_len / 1000:,.1f} ק״מ"
        if gix:
            ig = max(gix, key=lambda i: (f_len[i], -i))
            txt8 += f"; מבין הקטעים שדורגו, הארוכים ביותר ב{std_label(fstd[ig])} ({f_len[ig]:,.1f} ק״מ)"
        if ungraded_fe:
            txt8 += f"; {fmt(ungraded_fe)} קטעים ללא דרגה"
        insights.append({"id": "fences", "text_he": txt8 + "."})

    if has_el and wells / nel >= 0.5:
        txt9 = (f"{fmt(wells)} מתוך {fmt(nel)} אלמנטי השימור מתוארים (בשם או בהערה) כבאר או בור מים, "
                f"לפי הטקסט החופשי בשדות")
        if has_cx and el_in_cx >= 3:
            txt9 += f"; {fmt(el_in_cx)} מהאלמנטים נמצאים בתוך מתחם שימור"
        insights.append({"id": "wells", "text_he": txt9 + "."})

    ung = int((b["std"].isin(["", "טנטטיבי"])).sum())
    if ung / nb >= 0.03:
        n_none = int((b["std"] == "").sum())
        n_tent = int((b["std"] == "טנטטיבי").sum())
        if n_none and n_tent:
            why = f"{fmt(n_none)} בלי דרגה כלל ו־{fmt(n_tent)} בדרגה טנטטיבית"
        elif n_none:
            why = "כולם בלי דרגה כלל"
        else:
            why = "כולם בדרגה טנטטיבית"
        insights.append({"id": "ungraded", "text_he": (
            f"{fmt(ung)} מבנים ({pct(ung / nb)}) ללא דרגה סופית: {why}.")})

    # ---------- kpis ----------
    ung_tone = "warn" if ung / nb >= 0.05 else "brand"
    kpis = {
        "buildings": {"value": nb, "display": fmt(nb), "tone": "brand", "label": "מבנים לשימור"},
        "complexes": {"value": ncx, "display": fmt(ncx), "tone": "brand", "label": "מתחמי שימור"},
        "fence_km": {"value": round(tot_fe_len / 1000, 1), "display": f"{tot_fe_len / 1000:,.1f}", "tone": "brand", "label": "אורך גדרות לשימור (ק״מ)"},
        "ungraded": {"value": ung, "display": fmt(ung), "tone": ung_tone, "label": "מבנים ללא דרגה סופית"},
    }

    lede = (
        f"ארבע שכבות שימור בעיר: {fmt(nb)} מבנים, {fmt(ncx)} מתחמים, {fmt(nfe)} קטעי גדר ו־{fmt(nel)} אלמנטים. "
        f"שטח המבנה החציוני הוא {fmt(med_area)} מ״ר, ו־{fmt(big)} מבנים בשטח של מעל {fmt(AREA_EDGES[-1])} מ״ר."
    )
    summary = (
        f"מפת המבנים לשימור בבאר שבע לפי דרגת שימור: {fmt(nb)} מבנים, {fmt(ncx)} מתחמים, "
        f"{fmt(nfe)} קטעי גדר ו־{fmt(nel)} אלמנטים."
    )

    labels = {
        "lede": lede,
        "map_note": (
            f"קווי המתאר של {fmt(nb)} המבנים, {fmt(ncx)} המתחמים ו־{fmt(nfe)} קטעי הגדר, ומיקומי {fmt(nel)} האלמנטים, "
            "בצבע לפי דרגת השימור. בתצוגה רחוקה כל מבנה מוצג כנקודה, ובהתקרבות מופיע קו המתאר שלו. "
            "לחיצה על פריט מציגה את פרטיו, ובפינת המפה אפשר להציג או להסתיר כל שכבה."
        ),
        "map_aria": (
            f"מפה אינטראקטיבית של {fmt(nb)} המבנים, {fmt(ncx)} המתחמים, {fmt(nfe)} קטעי הגדר ו־{fmt(nel)} "
            "אלמנטי השימור בבאר שבע. גרסה נגישה: ראו הטבלאות והנתונים למטה."
        ),
        "layers_note": f"מספר הפריטים בכל אחת מארבע השכבות; בסך הכול {fmt(sum(layer_vals))}.",
        "standards_note": f"חלוקת {fmt(nb)} המבנים לפי דרגת השימור.",
        "eras_note": f"תקופת הבנייה כפי שמופיעה בנתונים; רק {fmt(n_era)} מתוך {fmt(nb)} המבנים סווגו לאחת מארבע התקופות.",
        "std_era_note": f"דרגות השימור בכל תקופה, עבור {fmt(n_era)} המבנים שסווגו לתקופה.",
        "areas_note": f"שטח הבסיס של כל מבנה (מ״ר), לפי דרגה; חציון {fmt(med_area)} מ״ר, ובסך הכול {tot_b_area / 1000:,.1f} דונם.",
        "cards_note": "שיעור המבנים המשויכים לכרטיס סקר בכל דרגה עם לפחות חמישה מבנים.",
        "top_cards_note": "כרטיסי סקר שאליהם משויכים לפחות שניים מהמבנים; עשרת הגדולים.",
        "dist_note": f"מרחק מרכז כל מבנה מהמרכז החציוני של {fmt(nb)} המבנים, לפי דרגה.",
        "cx_top_note": "המתחמים הגדולים ביותר לפי שטח, בדונם, עם דרגת השימור שלהם.",
        "cx_std_note": f"מספר המתחמים ושטחם הכולל לפי דרגה; סך השטח {tot_cx_area / 1000:,.1f} דונם.",
        "cx_bld_note": (
            f"כמה מבנים לשימור נמצאים בתוך כל מתחם (לפי מרכז המבנה): בסך הכול {fmt(in_cx)} מבנים בתוך מתחם. "
            "המתחמים עם הכי הרבה מבנים."
        ),
        "fe_std_note": f"אורך כולל (ק״מ) של קטעי הגדר בכל דרגה; בסך הכול {tot_fe_len / 1000:,.1f} ק״מ.",
        "fe_len_note": "התפלגות אורכי קטעי הגדר (מטרים), לפי דרגה.",
        "el_std_note": f"{fmt(nel)} אלמנטי שימור לפי דרגה; הרשימה המלאה מתחת לגרף.",
    }
    for k, v in [
        ("layers", "גרף עמודות: מספר פריטים בכל שכבת שימור"), ("standards", "גרף עמודות: מבנים לפי דרגת שימור"),
        ("eras", "גרף עמודות: מבנים לפי תקופה"), ("std_era", "גרף עמודות מוערמות: דרגות שימור לפי תקופה"),
        ("areas", "גרף עמודות מוערמות: מבנים לפי טווח שטח ודרגה"), ("cards", "גרף עמודות: שיעור כיסוי כרטיס סקר לפי דרגה"),
        ("top_cards", "גרף עמודות: כרטיסי סקר עם הכי הרבה מבנים"), ("dist", "גרף עמודות מוערמות: מבנים לפי מרחק מהמרכז"),
        ("cx_top", "גרף עמודות: המתחמים הגדולים ביותר"), ("cx_std", "גרף עמודות: מתחמים ושטחם לפי דרגה"),
        ("cx_bld", "גרף עמודות: מבנים לשימור בתוך כל מתחם"),
        ("fe_std", "גרף עמודות: אורך גדרות לפי דרגה"), ("fe_len", "גרף עמודות מוערמות: קטעי גדר לפי טווח אורך"),
        ("el_std", "גרף עמודות: אלמנטי שימור לפי דרגה"),
    ]:
        labels[k + "_aria"] = v
        labels[k + "_cap"] = v.split(": ", 1)[-1]

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "map": map_model,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {
            "eras": has_eras, "std_era": has_std_era, "cards": has_cards, "top_cards": has_top_cards,
            "cx": has_cx, "cx_bld": has_cx_bld, "fe": has_fe, "el": has_el,
        },
    }
