"""דרכים (באר שבע): the city's road-edge line layer (asphalt edge, kerb stones,
road edge), one row per mapped line segment with its length in metres
(Shape_Leng) and one WGS84 reference point.  The four resources (CSV, XLSX and
the same two with ITM coordinates) are twins of one table; only the WGS84 CSV
is read.

Every line has a single reference point, so the spatial views attribute a
segment's whole length to the place of that point.  Lengths are summed as
integer millimetres so the totals do not depend on row order.
"""
import math

import numpy as np
import pandas as pd

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
TOP_LONG = 300
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


def _int(n):
    return f"{int(round(n)):,}"


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


def _direction(dx, dy):
    brg = (90 - math.degrees(math.atan2(dy, dx))) % 360
    return SECTORS[int((brg + 22.5) // 45) % 8]


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
    if n_long == 0:
        return None
    return (f"{_int(n_long)} מקטעים ארוכים מ-{_int(LONG_M)} מטר מכילים "
            f"{_km(mm_long):,.1f} ק״מ ({_pct(mm_long / mm_total)} מהאורך). נקודת הייחוס של הארוך "
            f"שבהם ({top['len'] / 1000:.1f} ק״מ) נמצאת {top['dir_txt']}.")


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
    return (f"הכי הרבה קווי דרך נמצאים בכיוון {a['name']} מהמרכז: {_km(a['mm']):,.0f} ק״מ "
            f"({_pct(a['mm'] / total)}), מול {_km(low['mm']):,.0f} ק״מ בלבד בכיוון {low['name']}.")


def insight_cell(top_cell, cell_km):
    if top_cell is None:
        return None
    return (f"המשבצת הצפופה ביותר ({cell_km:.1f} על {cell_km:.1f} ק״מ) נמצאת "
            f"{top_cell['label']} מהמרכז, עם {top_cell['km']:,.1f} ק״מ קווים "
            f"({_int(top_cell['dens'])} ק״מ לקמ״ר, בלי המקטעים הארוכים).")


def insight_dup(n_dup, mm_dup, n):
    if n == 0 or n_dup / n < DUP_MIN_SHARE:
        return None
    return (f"{_int(n_dup)} שורות ({_pct(n_dup / n, 2)}) הן כפילות מלאה של שורה אחרת: "
            f"אותו אורך ואותה נקודה. הן מוסיפות {_km(mm_dup):,.1f} ק״מ לסכום האורכים.")


def compute(frames):
    df, n_bad = _prepare(frames["main"])
    n = len(df)
    mm_total = int(df["mm"].sum())
    med_m = float(df["len"].median())

    # --- length buckets: share of segments vs share of length
    b_names, b_n, b_km, b_ns, b_ks, t_len = [], [], [], [], [], []
    for i, lo in enumerate(LEN_EDGES):
        hi = LEN_EDGES[i + 1] if i + 1 < len(LEN_EDGES) else None
        m = (df["len"] >= lo) & ((df["len"] < hi) if hi is not None else True)
        cnt = int(m.sum())
        mm = int(df.loc[m, "mm"].sum())
        name = _bucket_name(lo, hi)
        b_names.append(name)
        b_n.append(cnt)
        b_km.append(round(_km(mm), 1))
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
        k = max(1, int(math.ceil(n * p / 100)))
        lorenz.append((p, float(cum[k - 1]) / mm_total))
    lorenz_chart = {"x": [p for p, _ in lorenz], "y": [round(s * 100, 1) for _, s in lorenz]}
    t_lorenz = [{"name": f"{p}%", "share": _pct(s)} for p, s in lorenz]

    # --- geometry around the median point
    lat0 = float(df["latf"].median())
    lon0 = float(df["lonf"].median())
    kx = KM_PER_DEG * math.cos(math.radians(lat0))
    dx = (df["lonf"] - lon0) * kx
    dy = (df["latf"] - lat0) * KM_PER_DEG
    dist = np.hypot(dx, dy)

    # --- grid heatmap (km of line per cell)
    x_km = (df["lonf"] - df["lonf"].min()) * kx
    y_km = (df["latf"] - df["latf"].min()) * KM_PER_DEG
    span = max(float(x_km.max()), float(y_km.max()), 0.01)
    cell = BASE_CELL_KM * max(1, math.ceil(span / BASE_CELL_KM / MAX_COLS))
    cx = (x_km // cell).astype(int)
    cy = (y_km // cell).astype(int)
    local = df["len"] < cell * 1000
    n_cross = int((~local).sum())
    mm_cross = int(df.loc[~local, "mm"].sum())
    cells = (pd.DataFrame({"x": cx, "y": cy, "mm": df["mm"]})[local]
             .groupby(["x", "y"]).agg(mm=("mm", "sum"), c=("mm", "size")).reset_index())
    nx, ny = int(cx.max()) + 1, int(cy.max()) + 1
    grid_chart = {
        "x": [f"{i * cell:.1f}" for i in range(nx)],
        "y": [f"{j * cell:.1f}" for j in range(ny)],
        "data": [[int(r.x), int(r.y), round(_km(r.mm), 1), int(r.c)] for r in cells.itertuples()],
        "max": round(_km(int(cells["mm"].max())), 1),
    }

    # --- densest cells, labelled by direction and distance from the centre
    x0 = (lon0 - float(df["lonf"].min())) * kx
    y0 = (lat0 - float(df["latf"].min())) * KM_PER_DEG
    area = cell * cell
    tc = cells.sort_values(["mm", "x", "y"], ascending=[False, True, True]).head(TOP_CELLS)
    top_cells = []
    for r in tc.itertuples():
        ccx = (r.x + 0.5) * cell - x0
        ccy = (r.y + 0.5) * cell - y0
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

    # --- rings: km of line, density per km², median segment length
    ring_idx = np.minimum((dist // RING_KM).astype(int), MAX_RINGS)
    rings = []
    for k in range(MAX_RINGS + 1):
        m = ring_idx == k
        cnt = int(m.sum())
        mm = int(df.loc[m, "mm"].sum())
        if k < MAX_RINGS:
            name = f"{k * RING_KM}-{(k + 1) * RING_KM}"
            ar = math.pi * (((k + 1) * RING_KM) ** 2 - (k * RING_KM) ** 2)
        else:
            name = f"‎{k * RING_KM}+"
            ar = None
        rings.append({"name": name, "count": cnt, "km": _km(mm),
                      "dens": (_km(mm) / ar) if ar else None,
                      "med": float(df.loc[m, "len"].median()) if cnt else 0.0})
    while len(rings) > 2 and rings[-1]["count"] == 0:
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
    sec = []
    for i, name in enumerate(SECTORS):
        m = sidx == i
        sec.append({"i": i, "name": name, "count": int(m.sum()), "mm": int(df.loc[m, "mm"].sum())})
    sec_chart = {"names": [s["name"] for s in sec], "values": [round(_km(s["mm"]), 1) for s in sec]}
    t_sec = [{"name": s["name"], "count": _int(s["count"]), "km": f"{_km(s['mm']):,.1f}",
              "share": _pct(s["mm"] / mm_total)} for s in sec]

    # --- the longest segments as a skeleton of the main roads
    lg = df.assign(dist=dist, dx=dx, dy=dy).sort_values(
        ["mm", "raw_lat", "raw_lon"], ascending=[False, True, True])
    lg_top = lg.head(TOP_LONG)
    long_chart = {"data": [[round(float(lo), 5), round(float(la), 5), round(float(ln))]
                           for lo, la, ln in zip(lg_top["lonf"], lg_top["latf"], lg_top["len"])],
                  "max": round(float(lg_top["len"].max())) if len(lg_top) else 0}
    first = lg.iloc[0]
    d0 = float(first["dist"])
    top_long = {"len": float(first["len"]),
                "dir_txt": ("במרכז העיר" if d0 < RING_KM / 2 else
                            f"ב{_direction(float(first['dx']), float(first['dy']))} "
                            f"במרחק {d0:.1f} ק״מ מהמרכז")}
    long_m = df["len"] >= LONG_M
    n_long = int(long_m.sum())
    mm_long = int(df.loc[long_m, "mm"].sum())

    # --- quality
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

    ring_first = rings[0]
    labels = {
        "lede": (f"שכבת הדרכים של עיריית באר שבע: {_int(n)} מקטעי קו של קצה אספלט, אבני שפה "
                 f"וקצה דרך, באורך כולל של כ-{total_km:,.0f} ק״מ. זה אורך הקווים הממופים ולא "
                 f"אורך הכבישים: לכל רחוב יש כמה קווים מקבילים (שני צדי האספלט, שתי שורות אבני "
                 f"שפה). המקטע החציוני ארוך {med_m:,.1f} מטר."),
        "geo_note": ("לכל מקטע יש נקודת ייחוס אחת, ולכן התרשימים המרחביים משייכים את כל אורך "
                     "המקטע למקום של הנקודה הזו. המרכז הוא נקודת החציון של כל הנקודות."),
        "len_note": "כמה מהמקטעים וכמה מהאורך נמצאים בכל טווח אורך (במטרים). רוב המקטעים קצרים, אבל רוב האורך נמצא במקטעים הארוכים.",
        "len_aria": f"תרשים עמודות: שיעור המקטעים מול שיעור האורך ב-{_int(len(b_names))} טווחי אורך.",
        "len_caption": "מקטעים ואורך לפי טווח אורך המקטע.",
        "lorenz_note": "העקומה מראה כמה מהאורך הכולל נמצא במקטעים הארוכים ביותר: הנקודה על הציר האופקי היא שיעור המקטעים, מהארוך לקצר.",
        "lorenz_aria": f"תרשים קו: שיעור האורך המצטבר לפי שיעור המקטעים הארוכים, {_int(len(lorenz))} נקודות.",
        "lorenz_caption": "שיעור האורך שבמקטעים הארוכים ביותר.",
        "grid_note": (f"ק״מ קווים בכל משבצת של {cell:.1f} ק״מ; הצירים מציגים מרחק בק״מ מהפינה "
                      f"הדרום-מערבית של השכבה. {_int(n_cross)} מקטעים ארוכים מ-{_int(cell * 1000)} "
                      f"מטר ({_pct(mm_cross / mm_total)} מהאורך) אינם נכללים כאן ובדירוג המשבצות, "
                      f"כי הם חוצים כמה משבצות; הם מוצגים בתרשים המקטעים הארוכים."),
        "grid_aria": f"מפת חום: ק״מ קווים בכל משבצת, {_int(len(cells))} משבצות.",
        "cells_note": (f"{_int(len(top_cells))} המשבצות ({cell:.1f} על {cell:.1f} ק״מ) עם הכי הרבה "
                       f"קווים, לפי כיוון ומרחק מהמרכז; הערך הוא ק״מ קווים לקמ״ר."),
        "cells_aria": (f"תרשים עמודות אופקיות: {_int(len(top_cells))} המשבצות הצפופות, "
                       f"המובילה עם {top_cells[0]['dens']:,.1f} ק״מ לקמ״ר." if top_cells else
                       "תרשים עמודות אופקיות: המשבצות הצפופות."),
        "cells_caption": "המשבצות עם הכי הרבה ק״מ קווים.",
        "ring_note": (f"אורך הקווים וצפיפותם (ק״מ לקמ״ר) לפי מרחק מהמרכז, בטבעות של "
                      f"{_int(RING_KM)} ק״מ; הטבעת האחרונה פתוחה ולכן אין לה צפיפות."),
        "ring_aria": (f"תרשים עמודות וקו: ק״מ קווים וצפיפות לפי {_int(len(rings))} טבעות מרחק, "
                      f"מ-{ring_first['km']:,.0f} ק״מ בטבעת הפנימית."),
        "ring_caption": "אורך, צפיפות ואורך חציוני לפי מרחק מהמרכז.",
        "med_note": "האורך החציוני של מקטע בכל טבעת מרחק. מקטעים קצרים מעידים על רשת צפופה של צמתים, פינות ומפרצים.",
        "med_aria": f"תרשים עמודות: אורך מקטע חציוני (מטר) לפי {_int(len(rings))} טבעות מרחק.",
        "sec_note": "ק״מ קווים בכל אחד משמונת הכיוונים סביב המרכז.",
        "sec_aria": "תרשים רדאר: ק״מ קווים לפי כיוון מהמרכז.",
        "sec_caption": "אורך הקווים לפי כיוון מהמרכז.",
        "long_note": (f"{_int(len(lg_top))} המקטעים הארוכים ביותר, לפי נקודת הייחוס שלהם; גודל "
                      f"העיגול לפי האורך. יחד הם משרטטים את הצירים הראשיים."),
        "long_aria": f"תרשים פיזור גאוגרפי: {_int(len(lg_top))} המקטעים הארוכים לפי מיקום ואורך.",
        "qual_note": ("בדיקות על השורות: מקטעים קצרים מאוד (שאריות חיתוך), שורות שחוזרות בדיוק, "
                      "שורות עם אותה נקודה ואורך שונה, ושורות שנשמטו מהניתוח (אורך או מיקום לא תקינים)."),
        "qual_aria": f"תרשים עמודות אופקיות: {_int(len(qual))} בדיקות איכות על השורות.",
        "qual_caption": "בדיקות איכות לפי מספר שורות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"שכבת הדרכים של באר שבע: {_int(n)} מקטעי קצה אספלט, אבני שפה וקצה דרך, "
                           f"כ-{total_km:,.0f} ק״מ קווים. צפיפות לפי אזור, אורכי מקטעים ואיכות."),
            "dataset_kind": "map",
            "suggested_tags": ["באר שבע", "דרכים", "תשתיות", "מיפוי", "תחבורה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["82a30a97-01b0-4281-854c-c7931f3445c0",
                            "727e865d-25b1-43ce-9dcb-af297851f87b",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "001c72e3-cead-42ac-ac5c-17287aabf285",
                            "3c6d4061-41bf-4403-82e9-c8fae5df04dd"],
        },
        "kpis": kpis,
        "charts": {"len": len_chart, "lorenz": lorenz_chart, "grid": grid_chart,
                   "cells": cells_chart, "ring": ring_chart, "sec": sec_chart,
                   "long": long_chart, "qual": qual_chart},
        "tables": {"len": t_len, "lorenz": t_lorenz, "cells": t_cells, "ring": t_ring,
                   "sec": t_sec, "qual": t_qual},
        "insights": insights,
        "labels": labels,
    }
