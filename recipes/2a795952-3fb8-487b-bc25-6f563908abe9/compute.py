"""Interchange codes on Israel's interurban road network (משרד התחבורה, צוות חצב).

Read from the uploaded shapefile (a `map` input): one row per interchange
point, the same attribute columns as the datastore CSV plus `__geometry`
(a WGS84 GeoJSON Point). The datastore table has no coordinates, so the map,
the north-south profile and every distance on the page come from the file.

One row per interchange: a two-letter code, a name, a type (מחלף, מחלפון,
פיצול, מחלף מערכתי, ...), up to three connecting road numbers (0 = none) and
the traffic authority responsible for it. The layer is a "current state"
snapshot, so there is no time axis: the page is about the network's shape
(where the interchanges are, which roads carry the most, who runs them, how
roads meet, how far apart they sit).

Every number on the page comes from here. Each insight rule returns a
sentence or None when its premise doesn't hold in the data.
"""
import json
import math

import numpy as np
import pandas as pd

ROAD_COLS = ["ROAD1", "ROAD2", "ROAD3"]
MISSING = "לא צוין"
OTHER = "אחר"

TOP_AUTH = 9        # authorities shown before an "אחר" bucket
TOP_ROADS = 15      # roads in the ranking chart
DIR_ROADS = 8       # roads that get an interchange list
DIR_ROWS = 80       # cap per road list
JUNCTION_ROWS = 60  # cap on the system-interchange / split directory
JUNCTION_TYPES = ("מחלף מערכתי", "פיצול")
MAP_TYPES = 6       # types with their own map colour; the rest share "אחר"

CHUNK_BYTES = 40_000   # each map JSON island stays well under 50KB
SPACING_MIN = 5        # located interchanges a road needs for the spacing chart
SPACING_ROADS = 15     # roads in the spacing chart
LAT_STEP = 0.25        # degrees per north-south band (coarsened if the span grows)
LAT_MAX_BANDS = 20
NN_EDGES = [0.5, 1, 2, 3, 5, 10]   # nearest-interchange distance bins, km (upper edges)
EARTH_KM = 6371.0
DEG_KM = math.pi * EARTH_KM / 180  # km per degree of latitude

# Israeli road numbering: 1-2 digits = national/main road, 3 = regional,
# 4 = local/access road. Ordered from the highest class down.
CLASSES = [("ראשי", "כביש ראשי (ספרה או שתיים)"),
           ("אזורי", "כביש אזורי (שלוש ספרות)"),
           ("מקומי", "כביש מקומי (ארבע ספרות)")]


def _int(n):
    return f"{int(n):,}"


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "0.0%"


def _km(v):
    return f"{v:,.1f}"


def _road_class(r):
    k = len(str(r))
    if k <= 2:
        return "ראשי"
    if k == 3:
        return "אזורי"
    return "מקומי"


def _point(g):
    """(lon, lat) from a GeoJSON Point string, or None."""
    try:
        geom = json.loads(g or "null")
    except ValueError:
        return None
    if not isinstance(geom, dict):
        return None
    c = geom.get("coordinates")
    if geom.get("type") == "MultiPoint" and isinstance(c, list) and c:
        c = c[0]
    elif geom.get("type") != "Point":
        return None
    try:
        lon, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or (lon == 0 and lat == 0):
        return None
    return lon, lat


def _prepare(df):
    df = df.copy()
    for c in ["MIHCODE", "MIHNAME", "MIHTYPE", "TRAFAUTH"]:
        # The CSV export doubles quotes (צה""ל); undo it if it ever shows here.
        df[c] = df[c].astype(str).str.strip().str.replace('""', '"', regex=False)
    df["type"] = df["MIHTYPE"].where(df["MIHTYPE"] != "", MISSING)
    df["auth"] = df["TRAFAUTH"].where(df["TRAFAUTH"] != "", MISSING)
    for c in ROAD_COLS:
        v = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
        df[c] = v.fillna(0).round().astype(int)
    # Distinct positive road numbers per interchange, in ROAD1..3 order.
    roads = []
    for r1, r2, r3 in zip(df["ROAD1"], df["ROAD2"], df["ROAD3"]):
        seen = []
        for r in (r1, r2, r3):
            if r > 0 and r not in seen:
                seen.append(r)
        roads.append(seen)
    df["roads"] = roads
    df["n_roads"] = df["roads"].map(len)
    pts = [_point(g) for g in df["__geometry"]]
    df["lon"] = [p[0] if p else np.nan for p in pts]
    df["lat"] = [p[1] if p else np.nan for p in pts]
    df = df[(df["MIHNAME"] != "") | (df["MIHCODE"] != "")]
    return df.sort_values(["MIHCODE", "MIHNAME", "lat", "lon"], kind="stable",
                          na_position="last").reset_index(drop=True)


def _counts(series):
    """Value counts sorted by count desc, then name (total order)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _road_stats(df):
    rows = []
    for name, code, typ, roads in zip(df["MIHNAME"], df["MIHCODE"], df["type"], df["roads"]):
        for r in roads:
            rows.append((r, name, code, typ, tuple(x for x in roads if x != r)))
    if not rows:
        return pd.DataFrame(columns=["road", "n", "partners"]), {}
    long = pd.DataFrame(rows, columns=["road", "name", "code", "type", "others"])
    stats = []
    lists = {}
    for road, g in long.groupby("road", sort=True):
        partners = sorted({o for t in g["others"] for o in t})
        stats.append({"road": int(road), "n": len(g), "partners": len(partners)})
        lists[int(road)] = g.sort_values(["name", "code"], kind="stable")
    st = pd.DataFrame(stats).sort_values(["n", "road"], ascending=[False, True], kind="stable")
    return st.reset_index(drop=True), lists


def _pair_kind(roads):
    if len(roads) < 2:
        return None
    rank = [k for k, _ in CLASSES]
    cls = sorted((_road_class(r) for r in roads), key=rank.index)
    return f"{cls[0]} עם {cls[1]}"


# ---------------------------------------------------------------- geometry

def _dist_matrix(lon, lat):
    """Great-circle distances (km) between every pair of points."""
    lo, la = np.radians(lon), np.radians(lat)
    dla = la[:, None] - la[None, :]
    dlo = lo[:, None] - lo[None, :]
    h = np.sin(dla / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlo / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def _nearest(loc):
    """Per located interchange: km to the nearest other one, and its index.
    Ties go to the lower position (loc is in a total order)."""
    n = len(loc)
    if n < 2:
        return np.full(n, np.nan), np.full(n, -1)
    d = _dist_matrix(loc["lon"].to_numpy(), loc["lat"].to_numpy())
    np.fill_diagonal(d, np.inf)
    idx = np.argmin(d, axis=1)
    return d[np.arange(n), idx], idx


def _nn_bins(nn):
    labels, values = [], []
    lo = 0
    for hi in NN_EDGES:
        labels.append(f"עד {hi:g} ק״מ" if lo == 0 else f"{lo:g} עד {hi:g} ק״מ")
        values.append(int(((nn >= lo) & (nn < hi)).sum()))
        lo = hi
    labels.append(f"{lo:g} ק״מ ומעלה")
    values.append(int((nn >= lo).sum()))
    return labels, values


def _lat_bands(loc):
    """North-south profile: interchanges per latitude band, south first.
    Returns (bands, step) where each band is {lo, label, n, road}."""
    if loc.empty:
        return [], 0
    step = LAT_STEP
    lo = math.floor(loc["lat"].min() / step) * step
    hi = loc["lat"].max()
    while (hi - lo) / step >= LAT_MAX_BANDS:
        step *= 2
        lo = math.floor(loc["lat"].min() / step) * step
    nb = int((hi - lo) // step) + 1
    band = ((loc["lat"] - lo) // step).astype(int).clip(0, nb - 1)
    bands = []
    for b in range(nb):
        a = lo + b * step
        sub = loc[band == b]
        rc = _counts(pd.Series([r for rs in sub["roads"] for r in rs], dtype=object))
        bands.append({"lo": a, "label": f"{a:.2f}°-{a + step:.2f}°", "n": len(sub),
                      "road": f"כביש {rc.index[0]}" if len(rc) else ""})
    return bands, step


def _spacing(loc, st):
    """Straight-line extent of each road's located interchanges and the mean
    gap between them, for the busiest roads with enough points."""
    out = []
    for road in st["road"]:
        r = int(road)
        sub = loc[[r in rs for rs in loc["roads"]]]
        if len(sub) < SPACING_MIN:
            continue
        d = _dist_matrix(sub["lon"].to_numpy(), sub["lat"].to_numpy())
        ext = float(d.max())
        out.append({"road": r, "n": len(sub), "extent": ext, "gap": ext / (len(sub) - 1)})
        if len(out) >= SPACING_ROADS:
            break
    out.sort(key=lambda x: (x["gap"], x["road"]))
    return out


def _map_features(loc, type_order, auth_names):
    """Compact point features [lon, lat, type#, name, code, roads, auth#],
    chunked into islands under CHUNK_BYTES (Hebrew counted as two bytes)."""
    t_index = {t: i for i, t in enumerate(type_order)}
    a_index = {a: i for i, a in enumerate(auth_names)}
    chunks, cur, size = [], [], 0
    for lon, lat, typ, name, code, roads, auth in zip(
            loc["lon"], loc["lat"], loc["map_type"], loc["MIHNAME"], loc["MIHCODE"],
            loc["roads"], loc["auth"]):
        f = [round(float(lon), 5), round(float(lat), 5), t_index[typ], name, code,
             ", ".join(str(x) for x in roads) or MISSING, a_index[auth]]
        n = len(json.dumps(f, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- insights

def insight_types(types, total):
    if types.empty or total == 0:
        return None
    lead, n = types.index[0], int(types.iloc[0])
    if n / total < 0.4:
        return None
    s = f"{_int(n)} מתוך {_int(total)} הרשומות ({_pct(n, total)}) מסווגות כ{lead}"
    if len(types) > 1:
        t2, n2 = types.index[1], int(types.iloc[1])
        s += f", ואחריהן {t2} עם {_int(n2)} ({_pct(n2, total)})"
    return s + "."


def insight_auth(auths, total):
    named = auths.drop(labels=[MISSING], errors="ignore")
    if named.empty or total == 0:
        return None
    lead, n = named.index[0], int(named.iloc[0])
    if n / total < 0.3:
        return None
    return (f"{lead} היא רשות התמרור של {_int(n)} מחלפים ({_pct(n, total)} מהרשת). "
            f"בסך הכול רשומות {_int(len(named))} רשויות תמרור שונות.")


def insight_municipal(df, total):
    muni = df[df["auth"].str.startswith("עיריית")]
    if muni.empty or total == 0:
        return None
    by = _counts(muni["auth"])
    parts = ", ".join(f"{a} ({_int(v)})" for a, v in by.items())
    return (f"{_int(len(muni))} מחלפים ({_pct(len(muni), total)}) נמצאים באחריות רשות מקומית "
            f"ולא של חברת דרכים: {parts}.")


def insight_top_road(st):
    if len(st) < 2:
        return None
    a, b = st.iloc[0], st.iloc[1]
    if a["n"] <= b["n"]:
        return None
    s = (f"כביש {a['road']} הוא העמוס ביותר במחלפים: {_int(a['n'])} מחלפים לאורכו, "
         f"לעומת {_int(b['n'])} בכביש {b['road']}.")
    hub = st.sort_values(["partners", "n", "road"], ascending=[False, False, True],
                         kind="stable").iloc[0]
    if hub["partners"] >= 3:
        s += (f" כביש {hub['road']} מתחבר במחלפים למספר הכבישים הגדול ביותר: "
              f"{_int(hub['partners'])} כבישים ממוספרים.")
    return s


def insight_single(df, total):
    single = int((df["n_roads"] == 1).sum())
    if total == 0 or single / total < 0.1:
        return None
    return (f"ב-{_int(single)} מחלפים ({_pct(single, total)}) רשום כביש ממוספר אחד בלבד: "
            f"המחלף מחבר אותו לרחובות או לדרכים שאינם ממוספרים.")


def insight_triple(df):
    tri = df[df["n_roads"] >= 3]
    if tri.empty:
        return None
    if len(tri) == 1:
        r = tri.iloc[0]
        return f"רק מחלף אחד, {r['MIHNAME']}, מחבר שלושה כבישים ממוספרים."
    ex = tri.sort_values(["MIHNAME", "MIHCODE"], kind="stable").iloc[0]
    roads = ", ".join(str(x) for x in ex["roads"])
    return (f"{_int(len(tri))} מחלפים מחברים שלושה כבישים ממוספרים או יותר, "
            f"למשל {ex['MIHNAME']} (כבישים {roads}).")


def insight_missing(df):
    miss = df[(df["type"] == MISSING) | (df["auth"] == MISSING) | (df["n_roads"] == 0)]
    if miss.empty:
        return None
    if len(miss) == 1:
        return (f"רשומה אחת ({miss.iloc[0]['MIHNAME']}) חסרה סוג, רשות תמרור או מספר כביש; "
                f"היא נספרת בגרפים תחת \"{MISSING}\".")
    return (f"{_int(len(miss))} רשומות חסרות סוג, רשות תמרור או מספר כביש; "
            f"הן נספרות בגרפים תחת \"{MISSING}\".")


def insight_isolated(loc):
    """The interchange farthest from any other, when it stands out clearly
    (at least 5x the median nearest-neighbour distance)."""
    if len(loc) < 10:
        return None
    med = float(loc["nn"].median())
    far = loc.sort_values(["nn", "MIHNAME", "MIHCODE"], ascending=[False, True, True],
                          kind="stable").iloc[0]
    if med <= 0 or far["nn"] < 5 * med:
        return None
    other = loc.iloc[int(far["nn_idx"])]
    return (f"המחלף המבודד ביותר הוא {far['MIHNAME']}: {_km(far['nn'])} ק״מ באוויר עד המחלף הקרוב "
            f"אליו ({other['MIHNAME']}), לעומת חציון של {_km(med)} ק״מ בין מחלף לשכנו הקרוב.")


def insight_dense(loc):
    """Interchanges with a neighbour under 1 km away, when they are >= 10%."""
    if len(loc) < 10:
        return None
    close = loc[loc["nn"] < 1]
    if len(close) / len(loc) < 0.1:
        return None
    pair = loc.sort_values(["nn", "MIHNAME", "MIHCODE"], kind="stable").iloc[0]
    other = loc.iloc[int(pair["nn_idx"])]
    return (f"ל-{_int(len(close))} מחלפים ({_pct(len(close), len(loc))}) יש מחלף שכן במרחק של פחות "
            f"מקילומטר אחד באוויר. הזוג הקרוב ביותר: {pair['MIHNAME']} ו{other['MIHNAME']}, "
            f"{_km(pair['nn'])} ק״מ זה מזה.")


def insight_band(loc, bands, step):
    """Concentration: the densest pair of adjacent latitude bands, when it
    holds at least 30% of the located interchanges."""
    if len(bands) < 4 or loc.empty:
        return None
    best, bi = -1, 0
    for i in range(len(bands) - 1):
        s = bands[i]["n"] + bands[i + 1]["n"]
        if s > best:
            best, bi = s, i
    span = (loc["lat"].max() - loc["lat"].min()) * DEG_KM
    if best / len(loc) < 0.3 or span <= 0:
        return None
    lo, hi = bands[bi]["lo"], bands[bi]["lo"] + 2 * step
    sub = loc[(loc["lat"] >= lo) & (loc["lat"] < hi)]
    south = sub.sort_values(["lat", "MIHCODE"], kind="stable").iloc[0]["MIHNAME"]
    north = sub.sort_values(["lat", "MIHCODE"], ascending=[False, True], kind="stable").iloc[0]["MIHNAME"]
    return (f"{_int(best)} מחלפים ({_pct(best, len(loc))}) מרוכזים ברצועה של כ-{2 * step * DEG_KM:,.0f} "
            f"ק״מ מצפון לדרום (הדרומי שבהם: {south}, הצפוני: {north}), מתוך פריסה של "
            f"{span:,.0f} ק״מ לאורך הרשת.")


def insight_spacing(sp):
    """Densest vs sparsest road by mean straight-line gap, when they differ 2x+."""
    if len(sp) < 3:
        return None
    dense, sparse = sp[0], sp[-1]
    if dense["gap"] <= 0 or sparse["gap"] / dense["gap"] < 2:
        return None
    return (f"בכביש {dense['road']} המחלפים צפופים במיוחד: {_int(dense['n'])} מחלפים לאורך "
            f"{_km(dense['extent'])} ק״מ, כ-{_km(dense['gap'])} ק״מ בין מחלף למחלף. בכביש "
            f"{sparse['road']} המרווח הממוצע הוא {_km(sparse['gap'])} ק״מ (מרחק אווירי).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["geo"])
    total = len(df)

    types = _counts(df["type"])
    auths = _counts(df["auth"])
    st, lists = _road_stats(df)
    n_roads_served = len(st)

    # Authority x type (stacked), top authorities + אחר.
    auth_order = list(auths.index[:TOP_AUTH])
    auth_bucket = df["auth"].where(df["auth"].isin(auth_order), OTHER)
    if (auth_bucket == OTHER).any():
        auth_order.append(OTHER)
    type_order = list(types.index)
    ct = pd.crosstab(auth_bucket, df["type"]).reindex(index=auth_order, columns=type_order,
                                                     fill_value=0)
    auth_chart = {
        "names": auth_order,
        "totals": [int(ct.loc[a].sum()) for a in auth_order],
        "series": [{"name": t, "data": [int(ct.loc[a, t]) for a in auth_order]}
                   for t in type_order],
    }
    auth_table = [{"name": a, "total": _int(ct.loc[a].sum()),
                   "share": _pct(ct.loc[a].sum(), total),
                   "cells": [_int(ct.loc[a, t]) for t in type_order]} for a in auth_order]

    # Roads ranking.
    top = st.head(TOP_ROADS)
    roads_chart = {"names": [f"כביש {r}" for r in top["road"]],
                   "n": [int(v) for v in top["n"]],
                   "partners": [int(v) for v in top["partners"]]}
    roads_table = [{"name": f"כביש {r['road']}", "n": _int(r["n"]),
                    "partners": _int(r["partners"])} for _, r in top.iterrows()]

    # Number of numbered roads per interchange.
    nr = df["n_roads"].value_counts().sort_index()
    nr_labels = {0: "ללא כביש ממוספר", 1: "כביש אחד", 2: "שני כבישים", 3: "שלושה כבישים"}
    nroads_chart = {"names": [nr_labels.get(int(k), f"{int(k)} כבישים") for k in nr.index],
                    "values": [int(v) for v in nr]}
    nroads_table = [{"name": n, "count": _int(v), "share": _pct(v, total)}
                    for n, v in zip(nroads_chart["names"], nroads_chart["values"])]

    # Road classes: every road reference, and the class pair at multi-road interchanges.
    class_names = [k for k, _ in CLASSES]
    refs = pd.Series([_road_class(r) for rs in df["roads"] for r in rs], dtype=object)
    ref_counts = refs.value_counts().reindex(class_names, fill_value=0)
    n_refs = int(ref_counts.sum())
    pairs = _counts(pd.Series([p for p in df["roads"].map(_pair_kind) if p], dtype=object))
    n_multi = int(pairs.sum())
    class_chart = {"names": [lbl for _, lbl in CLASSES],
                   "values": [int(ref_counts[k]) for k in class_names]}
    class_table = [{"name": lbl, "count": _int(ref_counts[k]), "share": _pct(ref_counts[k], n_refs)}
                   for k, lbl in CLASSES]
    pair_chart = {"names": [f"{p}" for p in pairs.index], "values": [int(v) for v in pairs]}
    pair_table = [{"name": p, "count": _int(v), "share": _pct(v, n_multi)}
                  for p, v in pairs.items()]

    # Directory: system interchanges and splits.
    jx = df[df["type"].isin(JUNCTION_TYPES)].sort_values(["type", "MIHNAME", "MIHCODE"],
                                                         kind="stable")
    junctions = [{"name": r["MIHNAME"], "code": r["MIHCODE"], "type": r["type"],
                  "roads": ", ".join(str(x) for x in r["roads"]) or MISSING,
                  "auth": r["auth"]} for _, r in jx.head(JUNCTION_ROWS).iterrows()]
    n_junctions = len(jx)

    # Directory: interchanges along the busiest roads.
    road_dirs = []
    for road in st.head(DIR_ROADS)["road"]:
        g = lists[int(road)]
        rows = [{"name": r["name"], "code": r["code"], "type": r["type"],
                 "others": ", ".join(str(x) for x in r["others"]) or "ללא"}
                for _, r in g.head(DIR_ROWS).iterrows()]
        road_dirs.append({"road": int(road), "label": f"כביש {road}", "count": _int(len(g)),
                          "rows": rows, "truncated": len(g) > DIR_ROWS})

    # ---------------- geometry (located interchanges only)
    loc = df[df["lat"].notna()].reset_index(drop=True)
    n_loc = len(loc)
    n_unloc = total - n_loc
    has_geo = n_loc >= 2
    nn, nn_idx = _nearest(loc)
    loc["nn"] = nn
    loc["nn_idx"] = nn_idx

    map_types = type_order[:MAP_TYPES]
    if len(type_order) > MAP_TYPES:
        map_types = map_types + [OTHER]
    loc["map_type"] = [t if t in map_types else OTHER for t in loc["type"]]
    map_counts = [int((loc["map_type"] == t).sum()) for t in map_types]
    auth_names = sorted(set(loc["auth"]))
    chunks, bounds = [], None
    if has_geo:
        chunks = _map_features(loc, map_types, auth_names)
        bounds = [[round(float(loc["lat"].min()), 4), round(float(loc["lon"].min()), 4)],
                  [round(float(loc["lat"].max()), 4), round(float(loc["lon"].max()), 4)]]

    if has_geo:
        nn_valid = loc["nn"].to_numpy()
        nn_labels, nn_values = _nn_bins(nn_valid)
        nn_median = float(np.median(nn_valid))
        bands, lat_step = _lat_bands(loc)
        span_km = float((loc["lat"].max() - loc["lat"].min()) * DEG_KM)
        by_lat = loc.sort_values(["lat", "MIHCODE"], kind="stable")
        southmost, northmost = by_lat.iloc[0]["MIHNAME"], by_lat.iloc[-1]["MIHNAME"]
        sp = _spacing(loc, st)
    else:
        nn_labels, nn_values, nn_median = [], [], 0.0
        bands, lat_step, span_km = [], 0, 0.0
        southmost = northmost = ""
        sp = []
    spacing_chart = {"names": [f"כביש {r['road']}" for r in sp],
                     "gap": [round(r["gap"], 2) for r in sp],
                     "n": [r["n"] for r in sp],
                     "extent": [round(r["extent"], 1) for r in sp]}
    spacing_table = [{"name": f"כביש {r['road']}", "n": _int(r["n"]), "extent": _km(r["extent"]),
                      "gap": _km(r["gap"])} for r in sp]
    nn_table = [{"name": l, "count": _int(v), "share": _pct(v, n_loc)}
                for l, v in zip(nn_labels, nn_values)]
    lat_table = [{"name": b["label"], "count": _int(b["n"]), "road": b["road"] or "ללא"}
                 for b in reversed(bands)]
    lat_chart = {"names": [b["label"] for b in reversed(bands)],
                 "values": [b["n"] for b in reversed(bands)],
                 "roads": [b["road"] for b in reversed(bands)]}

    full = int(types.get("מחלף", 0))
    ramp = int(types.get("מחלפון", 0))
    lead_auth = auths.drop(labels=[MISSING], errors="ignore")
    lead_auth_name = lead_auth.index[0] if not lead_auth.empty else MISSING
    lead_auth_n = int(lead_auth.iloc[0]) if not lead_auth.empty else 0
    top_road = int(st.iloc[0]["road"]) if n_roads_served else 0
    top_road_n = int(st.iloc[0]["n"]) if n_roads_served else 0

    rules = [
        ("types", insight_types(types, total)),
        ("auth", insight_auth(auths, total)),
        ("top_road", insight_top_road(st)),
        ("band", insight_band(loc, bands, lat_step) if has_geo else None),
        ("isolated", insight_isolated(loc) if has_geo else None),
        ("dense", insight_dense(loc) if has_geo else None),
        ("spacing", insight_spacing(sp)),
        ("single", insight_single(df, total)),
        ("triple", insight_triple(df)),
        ("municipal", insight_municipal(df, total)),
        ("missing", insight_missing(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    summary = (f"איתור מחלף לפי קוד, שם או מספר כביש, ומפה של {_int(total)} המחלפים והמחלפונים "
               f"ברשת הדרכים הבין עירונית, על {_int(n_roads_served)} כבישים ממוספרים.")

    lede = (f"שכבת קודי המחלפים של משרד התחבורה מונה {_int(total)} נקודות חיבור ברשת הבין עירונית: "
            f"{_int(full)} מחלפים, {_int(ramp)} מחלפונים ועוד פיצולים, מחלפים מערכתיים וצמתים. "
            f"לכל מחלף קוד בן שתי אותיות, שם, עד שלושה כבישים מתחברים, רשות התמרור האחראית עליו "
            f"ומיקום על המפה. המחלפים פרושים על {_int(n_roads_served)} כבישים ממוספרים, והעמוס שבהם "
            f"הוא כביש {top_road} עם {_int(top_road_n)} מחלפים.")

    lead_type = types.index[0] if len(types) else MISSING
    top_hub = (st.sort_values(["partners", "n", "road"], ascending=[False, False, True],
                              kind="stable").iloc[0] if n_roads_served else None)
    peak = max(bands, key=lambda b: (b["n"], -b["lo"])) if bands else None

    labels = {
        "lede": lede,
        "total_kpi": "מחלפים ונקודות חיבור במאגר",
        "full_kpi": "מחלפים מלאים (סוג מחלף)",
        "roads_kpi": "כבישים ממוספרים עם מחלף",
        "lead_auth_kpi": f"באחריות {lead_auth_name}",
        "nn_kpi": "חציון המרחק למחלף הקרוב (ק״מ, באוויר)",
        "span_kpi": "פריסת המחלפים מצפון לדרום (ק״מ)",
        "map_lede": (f"{_int(n_loc)} המחלפים לפי המיקום בקובץ המפה, בצבע לפי סוג המחלף. "
                     f"לחיצה על נקודה מציגה את שם המחלף, הקוד, הכבישים ורשות התמרור. "
                     f"המחלף הדרומי ביותר הוא {southmost} והצפוני ביותר {northmost}."
                     + (f" {_int(n_unloc)} רשומות ללא מיקום תקין אינן מוצגות במפה ובמרחקים."
                        if n_unloc else "")),
        "map_aria": f"מפה של {_int(n_loc)} מחלפים ברשת הבין עירונית, צבועים לפי סוג המחלף.",
        "lat_note": (f"מספר המחלפים בכל רצועת רוחב גאוגרפי של {lat_step:g} מעלות "
                     f"(כ-{lat_step * DEG_KM:,.0f} ק״מ מצפון לדרום), מהצפון (למעלה) לדרום."
                     + (f" הרצועה הצפופה ביותר ({peak['label']}) מכילה {_int(peak['n'])} מחלפים, "
                        f"והכביש הנפוץ בה הוא {peak['road'] or MISSING}." if peak else "")),
        "lat_aria": (f"תרשים עמודות: מחלפים לפי רצועת רוחב גאוגרפי, מצפון לדרום, "
                     f"על פני {span_km:,.0f} ק״מ."),
        "nn_note": (f"לכל מחלף: המרחק האווירי עד המחלף הקרוב אליו. החציון הוא {_km(nn_median)} ק״מ; "
                    f"מרחקים גדולים מסמנים מחלפים בודדים באזורים דלילים."),
        "nn_aria": (f"תרשים עמודות: {_int(n_loc)} מחלפים לפי המרחק למחלף הקרוב, חציון "
                    f"{_km(nn_median)} ק״מ."),
        "spacing_note": (f"בכבישים העמוסים עם {_int(SPACING_MIN)} מחלפים לפחות: המרחק האווירי בין שני "
                         f"המחלפים הרחוקים זה מזה בכביש, חלקי מספר המרווחים ביניהם. זהו אומדן גס "
                         f"למרווח בין מחלפים, כי הכביש עצמו מתפתל וארוך יותר."),
        "spacing_aria": (f"תרשים עמודות: מרווח ממוצע בין מחלפים ב-{_int(len(sp))} כבישים"
                         + (f", מהצפוף (כביש {sp[0]['road']}) לדליל (כביש {sp[-1]['road']})."
                            if sp else ".")),
        "types_note": (f"הסוג הנפוץ הוא {lead_type} ({_int(types.iloc[0])} רשומות). מחלפון הוא מחלף חלקי "
                       f"עם מעט רמפות; פיצול ומחלף מערכתי הם נקודות מפגש בין שני כבישים בין עירוניים."),
        "types_aria": (f"תרשים עמודות: מחלפים לפי סוג. {lead_type} מוביל עם "
                       f"{_int(types.iloc[0])} מתוך {_int(total)}."),
        "auth_note": (f"{lead_auth_name} אחראית על {_int(lead_auth_n)} מחלפים ({_pct(lead_auth_n, total)}). "
                      f"העמודות מפוצלות לפי סוג המחלף."
                      + (f" מוצגות {_int(TOP_AUTH)} הרשויות הגדולות, והשאר מקובצות תחת \"{OTHER}\"."
                         if OTHER in auth_order else "")),
        "auth_aria": (f"תרשים עמודות מוערמות: מחלפים לפי רשות תמרור וסוג. {lead_auth_name} מובילה עם "
                      f"{_int(lead_auth_n)} מחלפים."),
        "roads_note": (f"{_int(len(top))} הכבישים עם מספר המחלפים הגדול ביותר, מתוך {_int(n_roads_served)}. "
                       f"מחלף נספר בכל כביש שרשום בו, כך שמחלף בין שני כבישים נספר פעמיים. "
                       f"העמודה השנייה מראה עם כמה כבישים ממוספרים שונים הכביש מתחבר."),
        "roads_aria": (f"תרשים עמודות: {_int(len(top))} הכבישים עם הכי הרבה מחלפים. כביש {top_road} מוביל עם "
                       f"{_int(top_road_n)} מחלפים"
                       + (f", וכביש {top_hub['road']} מתחבר ל-{_int(top_hub['partners'])} כבישים."
                          if top_hub is not None else ".")),
        "nroads_note": (f"כמה כבישים ממוספרים רשומים בכל מחלף. {_int((df['n_roads'] == 2).sum())} מחלפים "
                        f"({_pct((df['n_roads'] == 2).sum(), total)}) מחברים שני כבישים."),
        "nroads_aria": (f"תרשים עמודות: מחלפים לפי מספר הכבישים הממוספרים שהם מחברים, "
                        f"מתוך {_int(total)} מחלפים."),
        "class_note": (f"כל כביש שרשום במחלף, לפי דרגת הכביש (נגזרת ממספר הספרות במספרו). "
                       f"בסך הכול {_int(n_refs)} חיבורים בין מחלף לכביש."),
        "class_aria": (f"תרשים עמודות: {_int(n_refs)} חיבורי מחלף לכביש לפי דרגת הכביש. "
                       f"כבישים ראשיים: {_int(ref_counts['ראשי'])}."),
        "pair_note": (f"ב-{_int(n_multi)} המחלפים שמחברים שני כבישים או יותר: אילו דרגות כביש נפגשות. "
                      f"כשנפגשים יותר משני כבישים, מוצגות שתי הדרגות הגבוהות."),
        "pair_aria": (f"תרשים עמודות: {_int(n_multi)} מחלפים בין כמה כבישים לפי צירוף דרגות הכבישים"
                      + (f". הצירוף הנפוץ: {pairs.index[0]} ({_int(pairs.iloc[0])})." if n_multi else ".")),
        "junction_note": (f"{_int(n_junctions)} מחלפים מערכתיים ופיצולים: נקודות המפגש בין כבישים בין עירוניים"
                          + (f". מוצגים {_int(JUNCTION_ROWS)} הראשונים." if n_junctions > JUNCTION_ROWS
                             else ".")),
        "roaddir_note": (f"רשימת המחלפים לאורך {_int(len(road_dirs))} הכבישים העמוסים במחלפים, "
                         f"עם קוד המחלף והכבישים הנוספים שהוא מחבר."),
    }

    tone_lead = "info" if total and lead_auth_n / total >= 0.5 else "brand"
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "רשת הדרכים הבין עירונית בישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "full": {"value": full, "display": _int(full), "tone": "brand"},
            "roads": {"value": n_roads_served, "display": _int(n_roads_served), "tone": "brand"},
            "lead_auth": {"value": lead_auth_n, "display": _pct(lead_auth_n, total),
                          "tone": tone_lead},
            "nn": {"value": round(nn_median, 2), "display": _km(nn_median), "tone": "brand"},
            "span": {"value": round(span_km, 1), "display": f"{span_km:,.0f}", "tone": "brand"},
        },
        "charts": {
            "types": {"names": list(types.index), "values": [int(v) for v in types]},
            "auth": auth_chart,
            "roads": roads_chart,
            "nroads": nroads_chart,
            "classes": class_chart,
            "pairs": pair_chart,
            "lat": lat_chart,
            "nn": {"names": nn_labels, "values": nn_values},
            "spacing": spacing_chart,
            "map": {"chunks": chunks, "types": map_types, "counts": map_counts,
                    "auths": auth_names, "bounds": bounds},
        },
        "tables": {
            "types": [{"name": t, "count": _int(v), "share": _pct(v, total)} for t, v in types.items()],
            "type_cols": type_order,
            "auth": auth_table,
            "roads": roads_table,
            "nroads": nroads_table,
            "classes": class_table,
            "pairs": pair_table,
            "junctions": junctions,
            "road_dirs": road_dirs,
            "lat": lat_table,
            "nn": nn_table,
            "spacing": spacing_table,
            "map_types": [{"name": t, "count": _int(c)} for t, c in zip(map_types, map_counts)],
        },
        "flags": {"has_junctions": n_junctions > 0, "has_pairs": n_multi > 0,
                  "has_roads": n_roads_served > 0, "has_geo": has_geo,
                  "has_spacing": len(sp) >= 2},
        "insights": insights,
        "labels": labels,
    }
