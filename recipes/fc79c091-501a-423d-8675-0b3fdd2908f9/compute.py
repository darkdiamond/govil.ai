"""שבילי אופניים בבאר שבע: one segment layer (length in metres + a WGS84 point).

Each row is one bike-path segment: SHAPE_Leng (metres, from the GIS layer)
and a reference point (lat/lon).  There are no names, types or dates, so the
page is about the network's size and shape: how long the segments are, how
concentrated the length is in a few long corridors, and where the kilometres
lie relative to the median centre of the segments (compass sector, distance
ring, 1 km grid).  The other three resources are format / projection twins
(XLSX, ITM) and are not read.

Order-independent: every sort is total (length, then coordinates).
"""
import math

import pandas as pd

M_PER_DEG = 111320.0
LEN_EDGES = [0, 100, 250, 500, 1000, 1500]
RING_KM = 1.0
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
TOP_N = 15
PARETO_STEPS = 20
SHORT_M = 100
LONG_M = 1000


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km1(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


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
    n = len(a)
    if n < 3:
        return None
    ra = pd.Series(a).rank(method="average")
    rb = pd.Series(b).rank(method="average")
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(ra.corr(rb))


def compute(frames):
    raw = frames["segments"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "len": num(raw["SHAPE_Leng"]),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df = df[df["len"].notna() & (df["len"] > 0)].copy()
    n_badlen = n_raw - len(df)
    n_seg = len(df)
    total_m = float(df["len"].sum())

    df = df.sort_values(["len", "la", "lo"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
    df["rank"] = range(1, n_seg + 1)

    geo = df[df["la"].between(29, 34) & df["lo"].between(34, 36)].copy().reset_index(drop=True)
    n_geo = len(geo)
    n_badgeo = n_seg - n_geo
    geo_m = float(geo["len"].sum())
    la0 = float(geo["la"].median())
    lo0 = float(geo["lo"].median())
    coslat = math.cos(math.radians(la0))
    geo["y"] = (geo["la"] - la0) * M_PER_DEG
    geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
    geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5

    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)
    geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]

    charts, tables = {}, {}

    # ---- length bands: count + km ----
    df["lb"] = df["len"].map(lambda v: band_index(v, LEN_EDGES))
    bl = band_labels(LEN_EDGES, "מ׳")
    b_cnt = [int((df["lb"] == i).sum()) for i in range(len(LEN_EDGES))]
    b_m = [float(df.loc[df["lb"] == i, "len"].sum()) for i in range(len(LEN_EDGES))]
    charts["bands"] = {"names": bl, "count": b_cnt, "km": [round(m / 1000, 2) for m in b_m]}
    tables["bands"] = {"headers": ["אורך הקטע", "קטעים", "ק״מ", "שיעור מהאורך"],
                       "rows": [[l, fmt(c), km1(m), pct(m / total_m)] for l, c, m in zip(bl, b_cnt, b_m)]}

    # ---- pareto: cumulative share of length by top x% of segments ----
    cum = df["len"].cumsum().tolist()
    px, py, prow = [], [], []
    for s in range(1, PARETO_STEPS + 1):
        frac = s / PARETO_STEPS
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

    # ---- longest segments ----
    gi = geo.set_index("rank")
    top = df.head(TOP_N)
    tnames, tvals, trows = [], [], []
    for _, r in top.iterrows():
        rk = int(r["rank"])
        if rk in gi.index:
            g = gi.loc[rk]
            where = f"{SECTORS[int(g['sec'])]}, {km1(g['d'])} ק״מ מהמרכז"
        else:
            where = "ללא מיקום"
        tnames.append(f"#{rk} · {where}")
        tvals.append(int(round(r["len"])))
        trows.append([f"#{rk}", where, fmt(r["len"]), pct(r["len"] / total_m)])
    charts["longest"] = {"names": tnames, "values": tvals}
    tables["longest"] = {"headers": ["דירוג", "מיקום ביחס למרכז", "אורך (מ׳)", "שיעור מהרשת"], "rows": trows}

    # ---- sectors ----
    s_cnt = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    s_m = [float(geo.loc[geo["sec"] == i, "len"].sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "km": [round(m / 1000, 2) for m in s_m], "count": s_cnt}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "קטעים", "ק״מ", "שיעור מהאורך"],
                         "rows": [[s, fmt(c), km1(m), pct(m / geo_m)] for s, c, m in zip(SECTORS, s_cnt, s_m)]}

    # ---- distance rings (1 km) ----
    max_ring = int(geo["d"].max() // (RING_KM * 1000))
    ring_cap = 6
    geo["ring"] = (geo["d"] // (RING_KM * 1000)).astype(int).clip(upper=ring_cap - 1)
    n_rings = min(max_ring + 1, ring_cap)
    edges = [i * RING_KM * 1000 for i in range(n_rings)]
    if n_rings == 1:
        rl = [f"עד {fmt(RING_KM)} ק״מ"]
    else:
        rl = band_labels([int(e / 1000) for e in edges], "ק״מ")
    r_cnt = [int((geo["ring"] == i).sum()) for i in range(n_rings)]
    r_m = [float(geo.loc[geo["ring"] == i, "len"].sum()) for i in range(n_rings)]
    r_avg = [round(m / c) if c else 0 for m, c in zip(r_m, r_cnt)]
    charts["rings"] = {"names": rl, "km": [round(m / 1000, 2) for m in r_m], "avg": r_avg}
    tables["rings"] = {"headers": ["מרחק מהמרכז", "קטעים", "ק״מ", "אורך ממוצע (מ׳)"],
                       "rows": [[l, fmt(c), km1(m), fmt(a)] for l, c, m, a in zip(rl, r_cnt, r_m, r_avg)]}

    # ---- grid heatmap (km per cell) ----
    span = max(float(geo["x"].max() - geo["x"].min()), float(geo["y"].max() - geo["y"].min()))
    cell = 1000.0 * max(1, int(math.ceil(span / 1000.0 / 14.0)))
    geo["gx"] = (geo["x"] / cell).round().astype(int)
    geo["gy"] = (geo["y"] / cell).round().astype(int)
    xs = list(range(int(geo["gx"].min()), int(geo["gx"].max()) + 1))
    ys = list(range(int(geo["gy"].min()), int(geo["gy"].max()) + 1))
    ck = int(cell / 1000)
    xl = [offset_label(k * ck, "מזרחה", "מערבה") for k in xs]
    yl = [offset_label(k * ck, "צפונה", "דרומה") for k in ys]
    agg = geo.groupby(["gx", "gy"]).agg(m=("len", "sum"), n=("len", "size")).reset_index()
    agg = agg.sort_values(["gx", "gy"], kind="mergesort")
    cells = [[xs.index(int(r.gx)), ys.index(int(r.gy)), round(float(r.m) / 1000, 2), int(r.n)]
             for r in agg.itertuples()]
    charts["grid"] = {"x": xl, "y": yl, "cells": cells,
                      "max": max(c[2] for c in cells) if cells else 0}
    n_cells = len(cells)
    top_cell = max(cells, key=lambda c: (c[2], -c[0], -c[1])) if cells else None

    # ---- scatter: length vs distance ----
    pts = geo.sort_values(["d", "len"], kind="mergesort")
    charts["scatter"] = {"points": [[round(d / 1000, 2), int(round(l))] for d, l in zip(pts["d"], pts["len"])]}
    rho = spearman(geo["d"].tolist(), geo["len"].tolist())

    # ---- stats ----
    med_len = float(df["len"].median())
    mean_len = total_m / n_seg
    n_short = int((df["len"] < SHORT_M).sum())
    m_short = float(df.loc[df["len"] < SHORT_M, "len"].sum())
    n_long = int((df["len"] >= LONG_M).sum())
    m_long = float(df.loc[df["len"] >= LONG_M, "len"].sum())
    ns_span = float(geo["y"].max() - geo["y"].min())
    ew_span = float(geo["x"].max() - geo["x"].min())
    within2 = float(geo.loc[geo["d"] < 2000, "len"].sum())

    # ---------- insights ----------
    insights = []
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

    first = df.iloc[0]
    if n_seg >= 3 and float(first["len"]) >= 2 * med_len:
        rk = int(first["rank"])
        where = ""
        if rk in gi.index:
            g = gi.loc[rk]
            where = f", באזור ה{SECTORS[int(g['sec'])]} כ־{km1(g['d'])} ק״מ ממרכז הרשת"
        insights.append({"id": "longest", "text_he": (
            f"הקטע הארוך ביותר משתרע על {fmt(first['len'])} מ׳{where}: "
            f"פי {float(first['len']) / med_len:.1f} מאורך הקטע החציוני ({fmt(med_len)} מ׳).")})

    if n_geo >= 8:
        ts = max(range(len(SECTORS)), key=lambda i: (s_m[i], -i))
        low = min(range(len(SECTORS)), key=lambda i: (s_m[i], i))
        if s_m[ts] / geo_m >= 0.2:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון עם הכי הרבה שבילים ביחס למרכז הרשת הוא {SECTORS[ts]}: {km1(s_m[ts])} ק״מ "
                f"({pct(s_m[ts] / geo_m)} מהאורך), לעומת {km1(s_m[low])} ק״מ בלבד בכיוון {SECTORS[low]}.")})

    if n_geo >= 8:
        share2 = within2 / geo_m
        insights.append({"id": "extent", "text_he": (
            f"הרשת פרושה על כ־{km1(ns_span)} ק״מ מצפון לדרום ועל כ־{km1(ew_span)} ק״מ ממזרח למערב; "
            f"{pct(share2)} מאורך השבילים נמצא בטווח של עד {fmt(2)} ק״מ ממרכז הרשת.")})

    if rho is not None and n_geo >= 10:
        if rho >= 0.3:
            txt = (f"ככל שהקטע רחוק יותר ממרכז הרשת הוא נוטה להיות ארוך יותר (מתאם דירוג {rho:.2f}): "
                   f"השבילים בשוליים הם קטעים רציפים יותר.")
        elif rho <= -0.3:
            txt = (f"הקטעים הקרובים למרכז הרשת נוטים להיות ארוכים יותר (מתאם דירוג שלילי של {abs(rho):.2f}), "
                   f"ובשוליים הרשת מפוצלת לקטעים קצרים יותר.")
        else:
            txt = (f"אין קשר ברור בין אורך הקטע למרחקו ממרכז הרשת (מתאם דירוג קרוב לאפס, {abs(rho):.2f} בערך מוחלט): "
                   f"קטעים ארוכים וקצרים פזורים בכל רחבי העיר.")
        insights.append({"id": "spread", "text_he": txt})

    if n_badlen or n_badgeo:
        parts = []
        if n_badlen:
            parts.append(f"ל־{fmt(n_badlen)} רשומות אין אורך תקין והן אינן נספרות")
        if n_badgeo:
            parts.append(f"ל־{fmt(n_badgeo)} קטעים אין מיקום תקין והם אינם נכללים בחישובי המיקום")
        insights.append({"id": "quality", "text_he": "; ".join(parts) + "."})

    # ---------- kpis ----------
    long_share = m_long / total_m
    kpis = {
        "total_km": {"value": round(total_m / 1000, 1), "display": km1(total_m), "tone": "brand",
                     "label": "אורך הרשת (ק״מ)"},
        "segments": {"value": n_seg, "display": fmt(n_seg), "tone": "brand", "label": "קטעי שביל"},
        "median": {"value": int(round(med_len)), "display": fmt(med_len), "tone": "info",
                   "label": "אורך קטע חציוני (מטרים)"},
        "long_share": {"value": round(long_share * 100, 1), "display": pct(long_share),
                       "tone": "ok" if long_share >= 0.4 else "warn" if long_share < 0.2 else "brand",
                       "label": f"מהאורך בקטעים של {fmt(LONG_M)} מ׳ ומעלה"},
    }

    summary = (
        f"מפת שבילי האופניים בבאר שבע: {fmt(n_seg)} קטעי שביל באורך כולל של {km1(total_m)} ק״מ, "
        f"לפי אורך ומיקום בעיר."
    )
    lede = (
        f"שכבת שבילי האופניים של עיריית באר שבע כוללת {fmt(n_seg)} קטעים, באורך כולל של {km1(total_m)} ק״מ. "
        f"הקטע החציוני ארוך {fmt(med_len)} מ׳ והממוצע {fmt(mean_len)} מ׳"
        + (": מעט קטעים ארוכים מושכים את הממוצע מעל החציון. " if mean_len >= 1.2 * med_len else ". ")
        + "לכל קטע יש נקודת מיקום, וממנה מחושבת פריסת הרשת סביב מרכז הקטעים."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא נקודת המיקום של קטע שביל; לחיצה מציגה את אורך הקטע במטרים.",
        "bands_note": (f"כמה קטעים יש בכל טווח אורך (עמודות) וכמה קילומטרים הם מכסים (קו). "
                       f"{fmt(b_cnt[0])} קטעים קצרים מ־{fmt(LEN_EDGES[1])} מ׳ לעומת {fmt(b_cnt[-1])} מעל {fmt(LEN_EDGES[-1])} מ׳."),
        "pareto_note": (f"איזה חלק מאורך הרשת מכסים הקטעים הארוכים ביותר: {fmt(k20)} הקטעים הארוכים "
                        f"מכסים {pct(s20)} מהאורך. קו אלכסוני היה מעיד על קטעים באורך שווה."),
        "longest_note": (f"{fmt(min(TOP_N, n_seg))} הקטעים הארוכים מתוך {fmt(n_seg)}, עם הכיוון והמרחק ממרכז הרשת "
                         f"(החציון של נקודות הקטעים). יחד הם {pct(float(top['len'].sum()) / total_m)} מהאורך."),
        "sectors_note": "קילומטרים של שבילים בכל כיוון ביחס למרכז הרשת.",
        "rings_note": (f"קילומטרים של שבילים בכל טבעת מרחק ממרכז הרשת, והאורך הממוצע של קטע בטבעת. "
                       f"{pct(within2 / geo_m)} מהאורך בטווח של עד {fmt(2)} ק״מ."),
        "grid_note": (f"רשת משבצות של {fmt(ck)} ק״מ סביב מרכז הקטעים; הצבע הוא סך קילומטרי השבילים במשבצת "
                      f"(לפי נקודת המיקום של כל קטע). שבילים נמצאים ב־{fmt(n_cells)} משבצות."
                      + (f" המשבצת העמוסה ביותר מכילה {top_cell[2]:,.1f} ק״מ." if top_cell else "")),
        "scatter_note": "כל נקודה היא קטע: מרחקו ממרכז הרשת (ציר אופקי) מול אורכו (ציר אנכי).",
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
            "suggested_tags": ["שבילי אופניים", "תחבורה", "תשתיות", "באר שבע"],
            "related_ids": [
                "bdf28cc0-680a-415c-af64-944a58079b2f",
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "b795e2e0-491e-4040-877e-f3681917f8be",
                "001c72e3-cead-42ac-ac5c-17287aabf285",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
