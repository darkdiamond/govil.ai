"""מבנים בבאר שבע — one row per building footprint drawn by the municipality's
GIS layer: primary use, floors, entrances, apartments, non-residential units,
an optional name, footprint area/perimeter and a WGS84 centroid.

The layer is a snapshot of the city's building stock (no dates), so the page is
about composition: what the buildings are used for, how tall they are, where
the apartments sit, how big the footprints are and where the city is dense.
Exact duplicate rows are dropped (disclosed). Every aggregate is an integer
count or a rounded sum over rows sorted by every column, so the output does not
depend on row order.
"""
import math

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
RES_KEY = "מגורים"            # a use containing this word is residential
TOP_USES = 12                 # bars on the use chart, the rest become "אחר"
TOP_AREA_USES = 8             # uses on the count-vs-footprint chart
TOP_BOX_USES = 8              # uses on the footprint boxplot
MIN_BOX = 20                  # buildings a use needs for a boxplot
TOP_UNIT_USES = 10            # uses on the non-residential units chart
FLOOR_BANDS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 8), (9, 12), (13, 20), (21, None)]
APT_BANDS = [(0, 0), (1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 32), (33, 64), (65, None)]
ENT_MAX = 6                   # entrances histogram: 0..5 and "6 ומעלה"
HIGH_FLOORS = 5               # "multi-storey" threshold for the stock insight
TOWER_FLOORS = 20             # "tower" threshold
TINY_AREA = 10.0              # m², footprints this small are kiosks/shafts/garbage
GRID_STEP = 0.005             # degrees (~500 m) for the density grids
MAX_GRID = 40
STOCK_GAP_PTS = 0.10          # apartments share must beat buildings share by this
SINGLE_MIN = 0.30             # single-apartment share worth a sentence
AREA_RATIO = 1.5              # footprint share / count share worth a sentence
GAP_MIN_SHARE = 0.005


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _band_label(lo, hi, one, many):
    if hi is None:
        return f"{lo} {many} ומעלה"
    if lo == hi:
        return f"{lo} {one if lo == 1 else many}"
    return f"{lo}-{hi} {many}"


def _band_index(values, bands):
    out = np.full(len(values), -1, dtype=int)
    for i, (lo, hi) in enumerate(bands):
        m = (values >= lo) if hi is None else ((values >= lo) & (values <= hi))
        out[(out == -1) & m] = i
    return out


def _prepare(df):
    out = pd.DataFrame({
        "use": df["Used"].str.strip(),
        "name": df["Name"].str.strip(),
        "floors": _num(df["floors"]),
        "apts": _num(df["appartment"]),
        "ent": _num(df["Entrances"]),
        "nonres": _num(df["Not_reside"]),
        "area": _num(df["Shape_Area"]),
        "latf": _num(df["lat"]),
        "lonf": _num(df["lon"]),
    })
    out["use"] = out["use"].where(out["use"] != "", "ללא שימוש מוגדר")
    for c in ("floors", "apts", "ent", "nonres"):
        out[c] = out[c].fillna(0).clip(lower=0).round().astype(int)
    out["area"] = out["area"].fillna(0.0).clip(lower=0.0)
    out = out.sort_values(list(out.columns), kind="stable").reset_index(drop=True)
    n_raw = len(out)
    out = out.drop_duplicates().reset_index(drop=True)
    n_dup = n_raw - len(out)
    out["geo"] = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    out["res"] = out["use"].str.contains(RES_KEY, regex=False)
    return out, n_dup


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _grid(df, weight=None):
    lat, lon = df["latf"].to_numpy(), df["lonf"].to_numpy()
    step = GRID_STEP
    while (math.ceil((lat.max() - lat.min()) / step) + 1 > MAX_GRID
           or math.ceil((lon.max() - lon.min()) / step) + 1 > MAX_GRID):
        step *= 2
    la0, lo0 = math.floor(lat.min() / step) * step, math.floor(lon.min() / step) * step
    iy = np.floor((lat - la0) / step + 1e-9).astype(int)
    ix = np.floor((lon - lo0) / step + 1e-9).astype(int)
    ny, nx = int(iy.max()) + 1, int(ix.max()) + 1
    w = np.ones(len(lat), dtype=int) if weight is None else df[weight].to_numpy().astype(int)
    counts = np.zeros((ny, nx), dtype=int)
    np.add.at(counts, (iy, ix), w)
    xs = [f"{lo0 + i * step:.3f}" for i in range(nx)]
    ys = [f"{la0 + j * step:.3f}" for j in range(ny)]
    cells = [[i, ny - 1 - j, int(counts[j, i])] for j in range(ny) for i in range(nx) if counts[j, i]]
    best = 0
    for c in cells:
        best = max(best, c[2])
    return {"x": xs, "y": ys[::-1], "cells": cells, "max": best}, step, int((counts > 0).sum())


# ---------------------------------------------------------------- insights

def insight_residential(n_res, total, apts_res, apts_all):
    if total == 0 or n_res == 0 or apts_all == 0:
        return None
    return (f"{_pct(n_res / total)} מהמבנים ({_int(n_res)} מתוך {_int(total)}) משמשים למגורים, "
            f"ובהם {_int(apts_res)} דירות, {_pct(apts_res / apts_all)} מכלל הדירות הרשומות בשכבה.")


def insight_low_rise(floor_rows, total):
    low = sum(r["n"] for r in floor_rows if r["lo"] in (1, 2) and r["hi"] in (1, 2))
    if total == 0 or low / total < 0.5:
        return None
    return (f"העיר נמוכה ברובה: {_pct(low / total)} מהמבנים ({_int(low)}) הם בני קומה אחת או שתיים.")


def insight_stock(res_b, res_high, apts_res, apts_high):
    if res_b == 0 or apts_res == 0:
        return None
    sb, sa = res_high / res_b, apts_high / apts_res
    if sa - sb < STOCK_GAP_PTS:
        return None
    return (f"מבני המגורים בני {_int(HIGH_FLOORS)} קומות ומעלה הם רק {_pct(sb)} ממבני המגורים "
            f"({_int(res_high)}), אבל בהם {_pct(sa)} מהדירות ({_int(apts_high)}).")


def insight_single(res_b, single):
    if res_b == 0 or single / res_b < SINGLE_MIN:
        return None
    return (f"{_pct(single / res_b)} ממבני המגורים ({_int(single)}) הם בתים עם דירה אחת בלבד.")


def insight_area_gap(area_rows):
    cand = [r for r in area_rows if r["cnt_share"] > 0 and r["area_share"] >= 0.02]
    if not cand:
        return None
    best = sorted(cand, key=lambda r: (-r["area_share"] / r["cnt_share"], r["name"]))[0]
    if best["area_share"] / best["cnt_share"] < AREA_RATIO:
        return None
    return (f"מבנים בשימוש {best['name']} הם {_pct(best['cnt_share'], 1)} מהמבנים, אבל תופסים "
            f"{_pct(best['area_share'], 1)} משטח התכסית הבנוי בעיר: מבנים גדולים בהרבה מהממוצע.")


def insight_tallest(df):
    if df.empty:
        return None
    top = int(df["floors"].max())
    tall = df[df["floors"] == top]
    towers = int((df["floors"] >= TOWER_FLOORS).sum())
    if top < 3:
        return None
    uses = _ranked(tall["use"])
    head = (f"המבנה הגבוה ביותר בשכבה הוא בן {_int(top)} קומות (שימוש: {uses.index[0]})")
    if towers >= 2:
        return head + f", ובעיר {_int(towers)} מבנים בני {_int(TOWER_FLOORS)} קומות ומעלה."
    return head + "."


def insight_density(grid, step_m, cells_n, total):
    if cells_n < 5 or grid["max"] == 0:
        return None
    return (f"בריבוע הצפוף ביותר של כ-{_int(step_m)} מטרים יש {_int(grid['max'])} מבנים, "
            f"לעומת ממוצע של {_int(total / cells_n)} מבנים בריבוע בנוי.")


def insight_units(df):
    units = int(df["nonres"].sum())
    if units == 0:
        return None
    mixed = int((df["res"] & (df["nonres"] > 0)).sum())
    by_use = df.groupby("use")["nonres"].sum()
    by_use = by_use[by_use > 0].sort_index().sort_values(ascending=False, kind="stable")
    lead, lead_n = by_use.index[0], int(by_use.iloc[0])
    s = (f"בשכבה רשומות {_int(units)} יחידות שאינן למגורים; הכי הרבה ({_int(lead_n)}, "
         f"{_pct(lead_n / units)}) במבנים בשימוש {lead}")
    if mixed:
        s += f", ו-{_int(mixed)} מבני מגורים כוללים גם יחידות כאלה"
    return s + "."


def insight_entrances(df):
    multi = int((df["ent"] >= 2).sum())
    if multi == 0 or len(df) == 0:
        return None
    mx = int(df["ent"].max())
    return (f"ל-{_int(multi)} מבנים ({_pct(multi / len(df), 1)}) יש שתי כניסות או יותר, "
            f"ובמבנה עם הכי הרבה כניסות רשומות {_int(mx)}.")


def insight_named(df):
    named = int((df["name"] != "").sum())
    if named == 0 or len(df) == 0:
        return None
    nonres = df[~df["res"]]
    share_nr = (nonres["name"] != "").sum() / len(nonres) if len(nonres) else 0
    lead = "רק " if named / len(df) < 0.5 else ""
    return (f"{lead}{_int(named)} מבנים ({_pct(named / len(df), 1)}) נושאים שם; בקרב המבנים שאינם למגורים השיעור {_pct(share_nr)}.")


def insight_quality(n_dup, n_tiny, n_zero, total):
    parts = []
    if n_dup:
        parts.append("שורה כפולה אחת הוסרה" if n_dup == 1 else f"{_int(n_dup)} שורות כפולות הוסרו")
    if n_tiny / max(total, 1) >= GAP_MIN_SHARE:
        parts.append(f"{_int(n_tiny)} מבנים עם תכסית קטנה מ-{_int(TINY_AREA)} מ\"ר (מחסנים, תאים ופירים)")
    if n_zero:
        parts.append(f"{_int(n_zero)} מבנים רשומים עם אפס קומות")
    if not parts:
        return None
    return "הערות על הנתונים: " + "; ".join(parts) + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    df, n_dup = _prepare(frames["buildings"])
    total = len(df)
    res = df[df["res"]]
    n_res = len(res)
    apts_all = int(df["apts"].sum())
    apts_res = int(res["apts"].sum())
    area_all = float(df["area"].sum())

    # ---- uses
    uses = _ranked(df["use"])
    top = uses.head(TOP_USES)
    rest = int(uses.iloc[TOP_USES:].sum())
    u_names = list(top.index) + (["שימושים אחרים"] if rest else [])
    u_vals = [int(v) for v in top] + ([rest] if rest else [])
    t_use = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(u_names, u_vals)]

    # ---- count share vs footprint share
    agg = df.groupby("use").agg(n=("area", "size"), area=("area", "sum"),
                                floors=("floors", "mean"), units=("nonres", "sum"))
    agg = agg.sort_index().sort_values("n", ascending=False, kind="stable")
    area_rows = [{"name": u, "cnt_share": r["n"] / total, "area_share": r["area"] / area_all if area_all else 0,
                  "n": int(r["n"]), "area": float(r["area"])} for u, r in agg.head(TOP_AREA_USES).iterrows()]
    area_chart = {"names": [r["name"] for r in area_rows],
                  "cnt": [round(r["cnt_share"] * 100, 1) for r in area_rows],
                  "area": [round(r["area_share"] * 100, 1) for r in area_rows]}
    t_area = [{"name": r["name"], "n": _int(r["n"]), "area": _int(r["area"] / 1000),
               "cnt_share": _pct(r["cnt_share"], 1), "area_share": _pct(r["area_share"], 1)} for r in area_rows]

    # ---- floors
    fidx = _band_index(df["floors"].to_numpy(), FLOOR_BANDS)
    resm = df["res"].to_numpy()
    aptv = df["apts"].to_numpy()
    floor_rows = []
    for i, (lo, hi) in enumerate(FLOOR_BANDS):
        m = fidx == i
        n = int(m.sum())
        if n == 0 and (lo == 0 or hi is None):
            continue
        floor_rows.append({"lo": lo, "hi": hi, "name": _band_label(lo, hi, "קומה", "קומות"), "n": n,
                           "res": int((m & resm).sum()), "other": int((m & ~resm).sum()),
                           "apts": int(aptv[m].sum())})
    floors_chart = {"names": [r["name"] for r in floor_rows], "res": [r["res"] for r in floor_rows],
                    "other": [r["other"] for r in floor_rows]}
    t_floors = [{"name": r["name"], "n": _int(r["n"]), "res": _int(r["res"]), "other": _int(r["other"]),
                 "share": _pct(r["n"] / total, 1)} for r in floor_rows]

    # ---- where the apartments are (residential buildings, by floor band)
    rf = _band_index(res["floors"].to_numpy(), FLOOR_BANDS)
    ra = res["apts"].to_numpy()
    stock_rows = []
    for i, (lo, hi) in enumerate(FLOOR_BANDS):
        m = rf == i
        b, a = int(m.sum()), int(ra[m].sum())
        if b == 0:
            continue
        stock_rows.append({"name": _band_label(lo, hi, "קומה", "קומות"), "b": b, "a": a,
                           "bs": b / n_res if n_res else 0, "as": a / apts_res if apts_res else 0})
    stock_chart = {"names": [r["name"] for r in stock_rows],
                   "b": [round(r["bs"] * 100, 1) for r in stock_rows],
                   "a": [round(r["as"] * 100, 1) for r in stock_rows]}
    t_stock = [{"name": r["name"], "b": _int(r["b"]), "a": _int(r["a"]), "bs": _pct(r["bs"], 1),
                "as": _pct(r["as"], 1), "avg": f"{r['a'] / r['b']:.1f}"} for r in stock_rows]
    high = res["floors"] >= HIGH_FLOORS
    res_high, apts_high = int(high.sum()), int(res.loc[high, "apts"].sum())

    # ---- apartments per residential building
    aidx = _band_index(ra, APT_BANDS)
    apt_rows = []
    for i, (lo, hi) in enumerate(APT_BANDS):
        m = aidx == i
        n = int(m.sum())
        if n == 0 and lo == 0:
            continue
        apt_rows.append({"name": _band_label(lo, hi, "דירה", "דירות"), "n": n, "a": int(ra[m].sum())})
    apt_chart = {"names": [r["name"] for r in apt_rows], "values": [r["n"] for r in apt_rows]}
    t_apts = [{"name": r["name"], "n": _int(r["n"]), "share": _pct(r["n"] / n_res if n_res else 0, 1),
               "a": _int(r["a"])} for r in apt_rows]
    single = int((ra == 1).sum())
    med_apts = int(np.median(ra)) if n_res else 0

    # ---- footprint distribution by use (boxplot, 5th-95th percentiles)
    box_rows = []
    for u, r in agg.iterrows():
        if len(box_rows) >= TOP_BOX_USES:
            break
        if r["n"] < MIN_BOX:
            continue
        v = np.sort(df.loc[df["use"] == u, "area"].to_numpy())
        p = [float(np.percentile(v, q)) for q in (5, 25, 50, 75, 95)]
        box_rows.append({"name": u, "p": [round(x, 1) for x in p], "n": int(r["n"])})
    box_chart = {"names": [r["name"] for r in box_rows], "data": [r["p"] for r in box_rows]}
    t_box = [{"name": r["name"], "n": _int(r["n"]), "q1": _int(r["p"][1]), "med": _int(r["p"][2]),
              "q3": _int(r["p"][3])} for r in box_rows]
    med_area = float(np.median(df["area"].to_numpy())) if total else 0.0

    # ---- entrances
    ev = np.minimum(df["ent"].to_numpy(), ENT_MAX)
    ent_names, ent_vals = [], []
    for k in range(ENT_MAX + 1):
        c = int((ev == k).sum())
        if c == 0 and k in (0, ENT_MAX):
            continue
        if k == ENT_MAX:
            ent_names.append(f"{k} כניסות ומעלה")
        elif k == 1:
            ent_names.append("כניסה אחת")
        elif k == 0:
            ent_names.append("ללא כניסה רשומה")
        else:
            ent_names.append(f"{k} כניסות")
        ent_vals.append(c)
    t_ent = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(ent_names, ent_vals)]
    multi_res = res[res["ent"] >= 1]
    apt_per_ent = (multi_res["apts"].sum() / multi_res["ent"].sum()) if len(multi_res) else 0

    # ---- non-residential units by use
    units = agg[agg["units"] > 0]["units"].sort_index().sort_values(ascending=False, kind="stable")
    tu = units.head(TOP_UNIT_USES)
    urest = int(units.iloc[TOP_UNIT_USES:].sum())
    un_names = list(tu.index) + (["שימושים אחרים"] if urest else [])
    un_vals = [int(v) for v in tu] + ([urest] if urest else [])
    units_all = int(df["nonres"].sum())
    t_units = [{"name": n, "count": _int(v), "share": _pct(v / units_all, 1)} for n, v in zip(un_names, un_vals)]

    # ---- density grids
    geo = df[df["geo"]]
    n_nogeo = total - len(geo)
    if len(geo):
        g_b, step, cells_n = _grid(geo)
        g_a, _, _ = _grid(geo, "apts")
    else:
        g_b = g_a = {"x": [], "y": [], "cells": [], "max": 0}
        step, cells_n = GRID_STEP, 0
    step_m = int(round(step * 111320 / 50.0) * 50)

    # ---- data notes
    n_tiny = int((df["area"] < TINY_AREA).sum())
    n_zero = int((df["floors"] == 0).sum())
    n_nonres_apts = int(((~df["res"]) & (df["apts"] > 0)).sum())
    quality = [("שורות כפולות שהוסרו", n_dup), (f"תכסית קטנה מ-{_int(TINY_AREA)} מ\"ר", n_tiny),
               ("אפס קומות", n_zero), ("מבנה שאינו למגורים עם דירות", n_nonres_apts),
               ("בלי קואורדינטות תקינות", n_nogeo)]
    quality = sorted([r for r in quality if r[1] > 0], key=lambda r: (-r[1], r[0]))
    quality_chart = {"names": [n for n, _ in quality], "values": [v for _, v in quality]}
    t_quality = [{"name": n, "count": _int(v)} for n, v in quality]

    rules = [
        ("residential", insight_residential(n_res, total, apts_res, apts_all)),
        ("stock", insight_stock(n_res, res_high, apts_res, apts_high)),
        ("low-rise", insight_low_rise(floor_rows, total)),
        ("single", insight_single(n_res, single)),
        ("area-gap", insight_area_gap(area_rows)),
        ("tallest", insight_tallest(df)),
        ("units", insight_units(df)),
        ("density", insight_density(g_b, step_m, cells_n, len(geo))),
        ("entrances", insight_entrances(df)),
        ("named", insight_named(df)),
        ("quality", insight_quality(n_dup, n_tiny, n_zero, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    max_floors = int(df["floors"].max()) if total else 0
    res_share = n_res / total if total else 0
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand", "label": "מבנים בשכבה"},
        "apts": {"value": apts_all, "display": _int(apts_all), "tone": "brand", "label": "דירות רשומות"},
        "res-share": {"value": res_share, "display": _pct(res_share, 1), "tone": "info",
                      "label": "מהמבנים משמשים למגורים"},
        "tallest": {"value": max_floors, "display": _int(max_floors), "tone": "info",
                    "label": "קומות במבנה הגבוה ביותר"},
        "footprint": {"value": area_all, "display": _int(area_all / 1000), "tone": "brand",
                      "label": "שטח תכסית בנוי (אלפי מ\"ר)"},
    }

    dup_note = (" שורה כפולה אחת הוסרה מהספירה." if n_dup == 1
                else f" {_int(n_dup)} שורות כפולות הוסרו מהספירה." if n_dup else "")
    labels = {
        "lede": (f"שכבת המבנים של עיריית באר שבע: {_int(total)} מבנים ברחבי העיר, לכל אחד שימוש עיקרי, "
                 f"מספר קומות, כניסות ודירות, שטח תכסית ונקודה על המפה. בסך הכול {_int(apts_all)} דירות "
                 f"ו-{_int(units_all)} יחידות שאינן למגורים. התיחום אינדיקטיבי ואינו מחליף מדידה.{dup_note}"),
        "lookup_sub": "חיפוש חי בכל רשומות השכבה: שימוש עיקרי, שם המבנה, קומות, כניסות ודירות",
        "map_note": (f"כל המבנים על המפה לפי נקודת המרכז שלהם. לחצו על אשכול כדי להתקרב, ועל סמן כדי לראות "
                     f"שימוש, קומות ודירות."),
        "use_note": (f"מספר המבנים לפי השימוש העיקרי. {_int(len(uses))} סוגי שימוש שונים בשכבה; "
                     f"{_int(len(top))} הנפוצים מוצגים, והשאר מקובצים."),
        "use_aria": f"תרשים עמודות אופקי: מבנים לפי שימוש עיקרי, {len(u_names)} קבוצות.",
        "use_caption": "מספר המבנים לפי שימוש עיקרי.",
        "area_note": (f"לכל אחד מ-{_int(len(area_rows))} השימושים הנפוצים: חלקו במספר המבנים לעומת חלקו "
                      f"בשטח התכסית הבנוי. פער גדול מעיד על מבנים גדולים או קטנים מהממוצע."),
        "area_aria": f"תרשים עמודות כפול: שיעור מהמבנים ושיעור משטח התכסית ב-{len(area_rows)} שימושים.",
        "area_caption": "מבנים ושטח תכסית לפי שימוש.",
        "floors_note": (f"מספר המבנים לפי מספר הקומות, בחלוקה למבני מגורים ולשאר. "
                        f"הגובה הממוצע {df['floors'].mean():.1f} קומות." if total else ""),
        "floors_aria": f"תרשים עמודות מוערם: מבנים לפי מספר קומות, {len(floor_rows)} קבוצות.",
        "floors_caption": "מבנים לפי מספר קומות, מגורים ואחר.",
        "stock_note": (f"איפה גרים: בכל קבוצת גובה, החלק שלה ממבני המגורים לעומת החלק שלה מהדירות. "
                       f"{_int(n_res)} מבני מגורים, {_int(apts_res)} דירות."),
        "stock_aria": f"תרשים עמודות כפול: שיעור ממבני המגורים ושיעור מהדירות לפי גובה, {len(stock_rows)} קבוצות.",
        "stock_caption": "מבני מגורים ודירות לפי מספר קומות.",
        "apts_note": (f"כמה דירות יש בכל מבנה מגורים. החציון הוא {_int(med_apts)} "
                      f"{'דירה' if med_apts == 1 else 'דירות'} למבנה."),
        "apts_aria": f"תרשים עמודות: מבני מגורים לפי מספר דירות, {len(apt_rows)} קבוצות.",
        "apts_caption": "מבני מגורים לפי מספר הדירות במבנה.",
        "box_note": (f"פיזור שטח התכסית (מ\"ר) בשימושים עם {_int(MIN_BOX)} מבנים ומעלה: הקופסה מהרבעון "
                     f"התחתון לעליון, הקו בחציון, והשפמים מהאחוזון החמישי עד התשעים וחמישה. "
                     f"חציון כל המבנים {_int(med_area)} מ\"ר."),
        "box_aria": f"תרשים קופסה: שטח תכסית לפי שימוש, {len(box_rows)} שימושים.",
        "box_caption": "רבעוני שטח התכסית לפי שימוש, במ\"ר.",
        "ent_note": (f"מספר הכניסות הרשום לכל מבנה. במבני המגורים יש בממוצע {apt_per_ent:.1f} "
                     f"דירות לכניסה."),
        "ent_aria": f"תרשים עמודות: מבנים לפי מספר כניסות, {len(ent_names)} קבוצות.",
        "ent_caption": "מבנים לפי מספר כניסות.",
        "units_note": (f"יחידות שאינן למגורים (חנויות, משרדים ושירותים) לפי השימוש העיקרי של המבנה. "
                       f"סך הכול {_int(units_all)} יחידות."),
        "units_aria": f"תרשים עמודות אופקי: יחידות שאינן למגורים לפי שימוש, {len(un_names)} קבוצות.",
        "units_caption": "יחידות שאינן למגורים לפי שימוש המבנה.",
        "density_note": (f"מפת חום של מספר המבנים בריבועים של כ-{_int(step_m)} מטרים. הצפון למעלה; "
                         f"הכהים צפופים יותר."),
        "density_aria": f"מפת חום: מבנים ב-{_int(cells_n)} ריבועים.",
        "housing_note": (f"אותה רשת, הפעם לפי מספר הדירות בכל ריבוע: כאן רואים איפה מתגוררים, "
                         f"לא רק איפה בנוי. בריבוע הצפוף ביותר {_int(g_a['max'])} דירות."),
        "housing_aria": f"מפת חום: דירות ב-{_int(cells_n)} ריבועים.",
        "quality_note": "רשומות חריגות בשכבה. ככל שהעמודה קצרה, הנתונים נקיים יותר.",
        "quality_aria": f"תרשים עמודות אופקי: {len(quality)} סוגי חריגות.",
        "quality_caption": "מספר הרשומות לפי סוג החריגה.",
    }

    return {
        "agent_data": {
            "summary_he": (f"איתור מבנים בבאר שבע לפי שימוש, קומות ודירות: {_int(total)} מבנים "
                           f"ו-{_int(apts_all)} דירות על מפה, עם גובה, תכסית וצפיפות."),
            "dataset_kind": "map",
            "suggested_tags": ["מבנים", "באר שבע", "תכנון עיר", "דיור", "שימושי קרקע", "GIS"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                            "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "5944b454-751c-4604-94d6-e676d7d34612"],
        },
        "kpis": kpis,
        "charts": {"use": {"names": u_names, "values": u_vals}, "area": area_chart,
                   "floors": floors_chart, "stock": stock_chart, "apts": apt_chart,
                   "box": box_chart, "ent": {"names": ent_names, "values": ent_vals},
                   "units": {"names": un_names, "values": un_vals},
                   "density": g_b, "housing": g_a, "quality": quality_chart},
        "tables": {"use": t_use, "area": t_area, "floors": t_floors, "stock": t_stock,
                   "apts": t_apts, "box": t_box, "ent": t_ent, "units": t_units,
                   "quality": t_quality},
        "insights": insights,
        "has_units": bool(un_vals),
        "has_box": bool(box_rows),
        "has_density": bool(g_b["cells"]),
        "labels": labels,
    }
