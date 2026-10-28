"""תחנות תחבורה ציבורית — the Ministry of Transport's spatial lookup of every
public-transport stop (bus, service taxi, light rail, Israel Railways, cable
car): one row per stop, with its locality (settlement or regional council),
metropolitan area, station type, operator type and WGS84 coordinates.

The file is a snapshot of the current stop network, not a time series: it is
re-published with stops added, moved or retired. Every count here is of the
current snapshot; nothing is compared over time.

Localities are grouped by CityCode, not CityName: in the Judea-and-Samaria
regional councils the name field carries a per-stop suffix
("מטה בנימין-צומת …-60001"), so one council appears under dozens of names.
Each code is displayed under its most common name (ties → shortest, then
alphabetical), with a trailing "*" marker dropped.

Metropolitan codes ≤ 0 are not metropolitan areas: "לא מוגדר" (-1) is every
stop outside the four metros (Ashkelon, Hadera, Nazareth …), "לא ידוע" (-10)
is unassigned. Rows whose coordinates don't parse or fall outside Israel's
bounding box are excluded from the geographic charts only, and disclosed.

Stops are infrastructure; the StationId is the public stop code printed on
the sign. No personal data exists in the file.
"""
import math

import numpy as np
import pandas as pd

TOP_CITIES = 20
TOP_TYPES = 15
GRID = 0.025                  # density-grid cell, degrees
BAND_STEPS = [0.1, 0.2, 0.25, 0.5, 1.0]
MAX_BANDS = 20
LAT_BOX = (29.3, 33.5)
LON_BOX = (34.0, 36.0)
SMALL_LOC = 5                 # "small" locality: at most this many stops
MIN_OP = 20                   # operator needs this many stops for a mode sentence
OUTSIDE_MIN = 0.10
SIZE_BUCKETS = [(1, 1), (2, 5), (6, 20), (21, 50), (51, 100), (101, 500), (501, None)]
GRID_PIECES = [(1, 1), (2, 5), (6, 20), (21, 50), (51, 100), (101, None)]
CONC_RANKS = [1, 5, 10, 20, 50, 100]
OTHER = "אחר"
GREY = "#c3cfe7"
GREY_DARK = "#6c757d"
PALETTE = ["#0068f5", "#0b3668", "#5b9bf5", "#7a8aa6", "#2e7fd9", "#9db8e0",
           "#0053c4", "#4a6a96"]
OP_COLORS = ["#0068f5", "#0b3668", "#9db8e0", "#7a8aa6", "#5b9bf5", "#4a6a96"]
METRO_WORD = "מטרופולין"


def n(v):
    return f"{int(v):,}"


def pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def iso(label):
    """LTR isolates so numeric ranges keep their order on the RTL canvas."""
    return f"⁦{label}⁩"


def _ranked(counts):
    """value_counts → list of (key, count), count desc then key asc."""
    items = [(k, int(v)) for k, v in counts.items()]
    items.sort(key=lambda kv: (-kv[1], str(kv[0])))
    return items


def _prepare(df):
    d = pd.DataFrame({
        "sid": df["StationId"].str.strip(),
        "code": pd.to_numeric(df["CityCode"].str.strip(), errors="coerce"),
        "city_raw": df["CityName"].str.strip(),
        "mcode": pd.to_numeric(df["MetropolinCode"].str.strip(), errors="coerce"),
        "metro": df["MetropolinName"].str.strip(),
        "type": df["StationTypeName"].str.strip(),
        "op": df["StationOperatorTypeName"].str.strip(),
        "lat": pd.to_numeric(df["Lat"].str.strip(), errors="coerce"),
        "lon": pd.to_numeric(df["Long"].str.strip(), errors="coerce"),
    })
    d.loc[d["type"] == "", "type"] = "לא צוין"
    d.loc[d["op"] == "", "op"] = "לא צוין"
    d.loc[d["metro"] == "", "metro"] = "לא ידוע"
    d["mcode"] = d["mcode"].fillna(-10)
    d["code"] = d["code"].fillna(-1).astype(int)
    # canonical locality name per code
    names = (d.assign(nm=d["city_raw"].str.rstrip("*").str.strip())
             .groupby(["code", "nm"]).size().reset_index(name="c"))
    names["ln"] = names["nm"].str.len()
    names = names.sort_values(["code", "c", "ln", "nm"], ascending=[True, False, True, True],
                              kind="mergesort")
    canon = names.drop_duplicates("code").set_index("code")["nm"]
    d["city"] = d["code"].map(canon)
    d.loc[d["city"] == "", "city"] = "לא צוין"
    geo = (d["lat"].between(*LAT_BOX)) & (d["lon"].between(*LON_BOX))
    d["geo"] = geo
    return d


def metro_label(name, code):
    return f"{METRO_WORD} {name}" if code > 0 else name


def insight_metro(metros, total):
    real = [m for m in metros if m["code"] > 0]
    if len(real) < 2 or total == 0:
        return None
    a, b = real[0], real[1]
    if a["count"] < 1.2 * b["count"]:
        return (f"{metro_label(a['name'], 1)} ו{metro_label(b['name'], 1)} מובילים כמעט בשווה: "
                f"{n(a['count'])} ו-{n(b['count'])} תחנות.")
    ratio = a["count"] / b["count"]
    return (f"{metro_label(a['name'], 1)} מוביל עם {n(a['count'])} תחנות ({pct(a['count'] / total)} מכלל התחנות) — "
            f"פי {ratio:.1f} מ{metro_label(b['name'], 1)}, השני בגודלו ({n(b['count'])}).")


def insight_outside(d, total):
    out = d[d["mcode"] == -1]
    if total == 0 or len(out) / total < OUTSIDE_MIN:
        return None
    top = _ranked(out["city"].value_counts())[:3]
    unk = int((d["mcode"] <= -2).sum() + ((d["mcode"] == 0)).sum())
    s = (f"{pct(len(out) / total)} מהתחנות ({n(len(out))}) נמצאות מחוץ למטרופולינים "
         f"(מסומנות \"לא מוגדר\"); המובילים שם: "
         + ", ".join(f"{c} ({n(v)})" for c, v in top) + ".")
    if unk:
        s += f" עוד {n(unk)} תחנות לא שויכו כלל למטרופולין."
    return s


def insight_top_city(cities, total):
    if len(cities) < 10 or total == 0:
        return None
    top = cities[0]
    top10 = sum(c for _, c in cities[:10])
    return (f"{top[0]} היא היישוב עם מספר התחנות הגדול ביותר — {n(top[1])} ({pct(top[1] / total)}); "
            f"עשרת היישובים המובילים מרכזים יחד {pct(top10 / total)} מכלל התחנות.")


def insight_small(city_counts, total):
    m = len(city_counts)
    if m == 0:
        return None
    small = city_counts[city_counts <= SMALL_LOC]
    if len(small) / m < 0.3:
        return None
    return (f"{n(len(small))} מתוך {n(m)} היישובים והמועצות ({pct(len(small) / m)}) משרתים "
            f"ב-{SMALL_LOC} תחנות או פחות — ויחד הם מחזיקים רק {pct(small.sum() / total)} מהתחנות.")


def insight_modes(d, dominant):
    parts = []
    for op, cnt in _ranked(d.loc[d["op"] != dominant, "op"].value_counts()):
        if cnt < MIN_OP:
            continue
        sub = d[d["op"] == op]
        lead, lc = _ranked(sub["metro_lbl"].value_counts())[0]
        if lc / cnt < 0.4:
            parts.append(f"{op}: {n(cnt)} תחנות, ללא ריכוז בולט")
        else:
            parts.append(f"{op}: {n(cnt)} תחנות, {pct(lc / cnt, 0)} מהן ב{lead}")
    if not parts:
        return None
    return f"מלבד {dominant} — " + "; ".join(parts) + "."


def insight_special(d, regular):
    sp = d[d["type"] != regular]
    if sp.empty:
        return None
    t, c = _ranked(sp["type"].value_counts())[0]
    sub = sp[sp["type"] == t]
    tops = _ranked(sub["city"].value_counts())[:2]
    share = sum(v for _, v in tops) / c
    s = f"סוג התחנה המיוחד הנפוץ ביותר הוא \"{t}\" עם {n(c)} תחנות"
    if share >= 0.3:
        s += ", בעיקר ב" + " וב".join(f"{k} ({n(v)})" for k, v in tops)
    return s + "."


def insight_dense(cells, d_geo):
    if not cells:
        return None
    best = cells[0]
    lat0 = best["a"] * GRID
    km_lat = GRID * 111.32
    km_lon = GRID * 111.32 * math.cos(math.radians(lat0 + GRID / 2))
    sub = d_geo[(d_geo["ga"] == best["a"]) & (d_geo["go"] == best["o"])]
    city, cc = _ranked(sub["city"].value_counts())[0]
    where = f" ב{city}" if cc / len(sub) >= 0.5 else ""
    return (f"התא הצפוף ביותר ברשת הצפיפות (כ-{km_lat:.1f} על {km_lon:.1f} ק\"מ){where} "
            f"מכיל {n(best['v'])} תחנות.")


def compute(frames):
    d = _prepare(frames["main"])
    total = len(d)
    d["metro_lbl"] = [metro_label(m, c) for m, c in zip(d["metro"], d["mcode"])]

    # ── metros ────────────────────────────────────────────────────────────
    mg = (d.groupby(["metro", "mcode"]).agg(count=("sid", "size"), locs=("code", "nunique"))
          .reset_index())
    mg["real"] = mg["mcode"] > 0
    mg = mg.sort_values(["real", "count", "metro"], ascending=[False, False, True], kind="mergesort")
    metros = [{"name": r.metro, "code": int(r.mcode), "count": int(r.count), "locs": int(r.locs)}
              for r in mg.itertuples()]
    real_total = sum(m["count"] for m in metros if m["code"] > 0)
    pi = 0
    m_colors = []
    for m in metros:
        if m["code"] > 0:
            m_colors.append(PALETTE[pi % len(PALETTE)])
            pi += 1
        else:
            m_colors.append(GREY if m["code"] == -1 else GREY_DARK)
    color_of = {m["name"]: c for m, c in zip(metros, m_colors)}
    metro_chart = {"names": [metro_label(m["name"], m["code"]) for m in metros],
                   "values": [m["count"] for m in metros], "colors": m_colors}
    metro_table = [{"name": metro_label(m["name"], m["code"]), "count": n(m["count"]),
                    "share": pct(m["count"] / total), "locs": n(m["locs"])} for m in metros]
    metro_order = [m["name"] for m in metros]

    # ── types ─────────────────────────────────────────────────────────────
    types = _ranked(d["type"].value_counts())
    regular, reg_count = types[0]
    special = types[1:]
    if len(special) > TOP_TYPES:
        rest = sum(c for _, c in special[TOP_TYPES:])
        special = special[:TOP_TYPES] + [(OTHER, rest)]
    type_op = (d.groupby("type")["op"].agg(lambda s: _ranked(s.value_counts())[0][0]).to_dict())
    types_chart = {"names": [t for t, _ in special], "values": [c for _, c in special]}
    types_table = [{"name": t, "count": n(c), "op": type_op.get(t, "—")} for t, c in special]

    # type × metro heatmap (special types only)
    sp = d[d["type"] != regular]
    ht_types = [t for t, _ in special if t != OTHER]
    ct = pd.crosstab(sp["type"], sp["metro"])
    cells, hmax = [], 0
    heat_rows = []
    for yi, t in enumerate(ht_types):
        row = []
        for xi, m in enumerate(metro_order):
            v = int(ct.at[t, m]) if (t in ct.index and m in ct.columns) else 0
            row.append(n(v))
            if v:
                cells.append([xi, yi, v])
                hmax = max(hmax, v)
        heat_rows.append({"label": t, "cells": row})
    heat = {"x": [metro_label(m["name"], m["code"]) for m in metros], "y": ht_types,
            "cells": cells, "max": max(hmax, 1)}

    # ── operators ─────────────────────────────────────────────────────────
    ops = _ranked(d["op"].value_counts())
    dominant = ops[0][0]
    minor_ops = [o for o, _ in ops[1:]]
    opc = pd.crosstab(d["op"], d["metro"])
    ops_chart = {"names": [metro_label(m["name"], m["code"]) for m in metros],
                 "series": [{"name": o, "color": OP_COLORS[i % len(OP_COLORS)],
                             "data": [int(opc.at[o, m["name"]]) if m["name"] in opc.columns else 0
                                      for m in metros]} for i, o in enumerate(minor_ops)]}
    ops_table = [{"name": o, "count": n(c), "share": pct(c / total),
                  "cells": [n(int(opc.at[o, m["name"]]) if m["name"] in opc.columns else 0) for m in metros]}
                 for o, c in ops]
    rail_mask = d["op"].str.contains("רכבת|רכבל", regex=True)
    rail_count = int(rail_mask.sum())

    # ── localities ────────────────────────────────────────────────────────
    loc = (d.groupby("code").agg(count=("sid", "size"), city=("city", "first"), metro=("metro", "first"),
                                 mcode=("mcode", "first")).reset_index())
    loc = loc.sort_values(["count", "city", "code"], ascending=[False, True, True], kind="mergesort")
    cities = list(zip(loc["city"], loc["count"].astype(int)))
    top = loc.head(TOP_CITIES)
    top_metros = [m for m in metro_order if m in set(top["metro"])]
    cities_chart = {
        "names": top["city"].tolist(),
        "series": [{"name": metro_label(m, int(mg.loc[mg["metro"] == m, "mcode"].iloc[0])),
                    "color": color_of[m],
                    "data": [int(c) if mm == m else None for c, mm in zip(top["count"], top["metro"])]}
                   for m in top_metros],
    }
    cities_table = [{"name": r.city, "count": n(r.count), "share": pct(r.count / total),
                     "metro": metro_label(r.metro, int(r.mcode))} for r in top.itertuples()]

    counts_sorted = loc["count"].to_numpy()
    cum = np.cumsum(counts_sorted)
    conc_chart = {"y": [round(float(v) / total * 100, 1) for v in cum]}
    conc_table = [{"rank": n(k), "share": pct(cum[k - 1] / total)} for k in CONC_RANKS if k <= len(cum)]
    half_rank = int(np.searchsorted(cum, total / 2) + 1) if total else 0

    city_counts = loc["count"]
    sizes = []
    for lo, hi in SIZE_BUCKETS:
        m = (city_counts >= lo) & (city_counts <= hi) if hi else (city_counts >= lo)
        lbl = (f"{lo}" if hi == lo else (f"{lo}–{hi}" if hi else f"{lo}+"))
        sizes.append({"label": lbl, "locs": int(m.sum()), "stops": int(city_counts[m].sum())})
    n_loc_all = max(len(city_counts), 1)
    sizes_chart = {"names": [iso(s["label"]) for s in sizes],
                   "locs": [round(s["locs"] / n_loc_all * 100, 1) for s in sizes],
                   "stops": [round(s["stops"] / total * 100, 1) if total else 0 for s in sizes]}
    sizes_table = [{"label": s["label"], "locs": n(s["locs"]), "locs_share": pct(s["locs"] / n_loc_all),
                    "stops": n(s["stops"]), "share": pct(s["stops"] / total)} for s in sizes]

    # ── geography ─────────────────────────────────────────────────────────
    g = d[d["geo"]].copy()
    bad_geo = total - len(g)
    lat_min, lat_max = float(g["lat"].min()), float(g["lat"].max())
    step = next((s for s in BAND_STEPS
                 if math.floor(lat_max / s) - math.floor(lat_min / s) + 1 <= MAX_BANDS), BAND_STEPS[-1])
    g["band"] = np.floor(g["lat"] / step + 1e-9).astype(int)
    bands = list(range(int(g["band"].min()), int(g["band"].max()) + 1))
    bc = pd.crosstab(g["band"], g["metro"])
    dec = 1 if step < 1 else 0
    band_labels = [f"{b * step:.{dec}f}–{(b + 1) * step:.{dec}f}" for b in bands]
    band_prose = [f"{b * step:.{dec}f} עד {(b + 1) * step:.{dec}f}" for b in bands]
    band_series = [{"name": metro_label(m["name"], m["code"]), "color": c,
                    "data": [int(bc.at[b, m["name"]]) if (b in bc.index and m["name"] in bc.columns) else 0
                             for b in bands]}
                   for m, c in zip(metros, m_colors)]
    bands_chart = {"names": [iso(lb) for lb in band_labels], "series": band_series}
    band_tot = [sum(s["data"][i] for s in band_series) for i in range(len(bands))]
    bands_table = [{"label": lb, "count": n(t), "share": pct(t / len(g)) if len(g) else "—"}
                   for lb, t in zip(band_labels, band_tot)]
    peak_i = max(range(len(bands)), key=lambda i: (band_tot[i], -i))

    g["ga"] = np.floor(g["lat"] / GRID + 1e-9).astype(int)
    g["go"] = np.floor(g["lon"] / GRID + 1e-9).astype(int)
    gc = g.groupby(["ga", "go"]).size().reset_index(name="v")
    gc = gc.sort_values(["v", "ga", "go"], ascending=[False, True, True], kind="mergesort")
    cell_list = [{"a": int(r.ga), "o": int(r.go), "v": int(r.v)} for r in gc.itertuples()]
    a0, o0 = int(g["ga"].min()), int(g["go"].min())
    grid_cells = sorted([[c["o"] - o0, c["a"] - a0, c["v"]] for c in cell_list])
    grid_chart = {"cells": grid_cells, "a0": a0, "o0": o0, "step": GRID,
                  "na": int(g["ga"].max()) - a0 + 1, "no": int(g["go"].max()) - o0 + 1,
                  "max": cell_list[0]["v"] if cell_list else 1,
                  "pieces": [{"min": lo, "max": hi, "label": iso(f"{lo}–{hi}" if hi != lo else f"{lo}")}
                             if hi else {"min": lo, "label": iso(f"{lo}+")}
                             for lo, hi in GRID_PIECES]}

    # ── insights ──────────────────────────────────────────────────────────
    rules = [
        ("metro", insight_metro(metros, total)),
        ("outside", insight_outside(d, total)),
        ("top_city", insight_top_city(cities, total)),
        ("small", insight_small(city_counts, total)),
        ("modes", insight_modes(d, dominant)),
        ("special", insight_special(d, regular)),
        ("dense", insight_dense(cell_list, g)),
    ]
    insights = [{"id": k, "text_he": v} for k, v in rules if v]

    # ── KPIs ──────────────────────────────────────────────────────────────
    n_locs = int(d["code"].nunique())
    real_share = real_total / total if total else 0
    reg_share = reg_count / total if total else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "locs": {"value": n_locs, "display": n(n_locs), "tone": "brand"},
        "metro_share": {"value": round(real_share, 4), "display": pct(real_share), "tone": "brand"},
        "rail": {"value": rail_count, "display": n(rail_count), "tone": "info"},
    }

    lead_city = cities[0] if cities else ("—", 0)
    real_metros = [m for m in metros if m["code"] > 0]
    labels = {
        "lede": (f"המאגר משייך {n(total)} תחנות תחבורה ציבורית — אוטובוס, מוניות שירות, רכבת קלה, "
                 f"רכבת ישראל ורכבל — ל-{n(n_locs)} יישובים ומועצות אזוריות ולמטרופולין, עם מיקום מדויק לכל תחנה. "
                 f"{pct(real_share)} מהתחנות נמצאות במטרופולינים, "
                 f"ו{lead_city[0]} מובילה עם {n(lead_city[1])} תחנות. "
                 f"{pct(reg_share)} מהן מסוג \"{regular}\"."),
        "metro_share_kpi": f"מהתחנות במטרופולינים ({n(real_total)})",
        "rail_kpi": "תחנות רכבת, רכבת קלה ורכבל",
        "metro_note": (f"{metro_label(real_metros[0]['name'], 1)} לבדו מחזיק {pct(real_metros[0]['count'] / total)} מהתחנות. "
                       f"\"לא מוגדר\" הוא כל מה שמחוץ למטרופולינים — {n(sum(m['count'] for m in metros if m['code'] == -1))} תחנות."
                       if real_metros else "התפלגות התחנות לפי מטרופולין."),
        "metro_aria": (f"גרף עמודות: תחנות לפי מטרופולין. מוביל: {metro_chart['names'][0]} עם {n(metro_chart['values'][0])} תחנות."),
        "metro_caption": "מספר התחנות והיישובים לפי מטרופולין",
        "types_note": (f"{pct(reg_share)} מהתחנות ({n(reg_count)}) הן \"{regular}\" ואינן מוצגות כאן; "
                       f"הגרף מציג את {n(total - reg_count)} התחנות מהסוגים האחרים."),
        "types_aria": (f"גרף עמודות אופקי: תחנות לפי סוג, ללא \"{regular}\". "
                       + (f"הנפוץ: {special[0][0]} עם {n(special[0][1])}." if special else "")),
        "types_caption": f"תחנות לפי סוג תחנה (ללא {regular})",
        "heat_note": "איפה נמצא כל סוג תחנה מיוחד: מספר התחנות בכל צירוף של סוג ומטרופולין.",
        "heat_aria": f"מפת חום: סוגי תחנות מיוחדים לפי מטרופולין, ללא \"{regular}\".",
        "heat_caption": "תחנות לפי סוג ומטרופולין",
        "ops_note": (f"\"{dominant}\" מפעילים {pct(ops[0][1] / total)} מהתחנות; "
                     f"הגרף מציג את שאר אמצעי התחבורה לפי מטרופולין."),
        "ops_aria": f"גרף עמודות נערמות: תחנות שאינן של {dominant}, לפי סוג מפעיל ומטרופולין.",
        "ops_caption": "תחנות לפי סוג מפעיל ומטרופולין",
        "cities_note": (f"{n(TOP_CITIES)} היישובים והמועצות עם מספר התחנות הגדול ביותר, בצבע המטרופולין שלהם."),
        "cities_aria": (f"גרף עמודות אופקי: {n(TOP_CITIES)} היישובים המובילים במספר תחנות. "
                        f"מוביל: {lead_city[0]} עם {n(lead_city[1])}."),
        "cities_caption": "היישובים עם מספר התחנות הגדול ביותר",
        "conc_note": (f"חצי מכלל התחנות נמצאות ב-{n(half_rank)} היישובים הגדולים ביותר (מתוך {n(n_locs)})."),
        "conc_aria": (f"גרף קו: השיעור המצטבר של התחנות לפי דירוג היישובים. {n(half_rank)} היישובים "
                      f"המובילים מחזיקים חצי מהתחנות."),
        "conc_caption": "שיעור התחנות המצטבר ביישובים המובילים",
        "sizes_note": ("לכל קבוצת גודל: איזה חלק מהיישובים נמצא בה, ואיזה חלק מהתחנות הם מחזיקים יחד."),
        "sizes_aria": (f"גרף עמודות: יישובים ותחנות לפי מספר התחנות ביישוב. "
                       f"הקבוצה הגדולה ביותר במספר יישובים: {sizes_table[max(range(len(sizes)), key=lambda i: (sizes[i]['locs'], -i))]['label'].replace('–', ' עד ')} תחנות."),
        "sizes_caption": "יישובים ותחנות לפי מספר התחנות ביישוב",
        "bands_note": (f"פריסת התחנות מדרום לצפון ברצועות רוחב של {step:g} מעלות (כ-{step * 111.32:.0f} ק\"מ). "
                       f"הרצועה הצפופה ביותר: {band_prose[peak_i]} מעלות, עם {n(band_tot[peak_i])} תחנות."),
        "bands_aria": (f"גרף עמודות נערמות: תחנות לפי קו רוחב ומטרופולין. שיא ברצועה {band_prose[peak_i]} "
                       f"עם {n(band_tot[peak_i])} תחנות."),
        "bands_caption": "תחנות לפי רצועת קו רוחב",
        "grid_note": (f"כל ריבוע הוא תא של {GRID:g} מעלות (כ-{GRID * 111.32:.1f} ק\"מ), בצבע לפי מספר התחנות בו. "
                      f"{n(len(cell_list))} תאים מכילים לפחות תחנה אחת."
                      + (f" {n(bad_geo)} תחנות ללא קואורדינטות תקינות אינן מוצגות." if bad_geo else "")),
        "grid_aria": (f"תרשים צפיפות: {n(len(cell_list))} תאי רשת עם תחנות, עד {n(grid_chart['max'])} תחנות בתא."),
        "map_note": (f"כל {n(total)} התחנות, באשכולות; התקרבו כדי לראות תחנות בודדות ולחצו על תחנה לפרטים."),
        "map_aria": "מפה אינטראקטיבית של תחנות התחבורה הציבורית. גרסה נגישה: ראו את טבלת הנתונים וקובץ ה-CSV למטה.",
    }

    tables = {
        "metros": metro_table, "types": types_table, "heat": heat_rows, "heat_head": heat["x"],
        "ops": ops_table, "ops_head": heat["x"], "cities": cities_table, "conc": conc_table,
        "sizes": sizes_table, "bands": bands_table,
    }

    summary = (f"{n(total)} תחנות תחבורה ציבורית ב-{n(n_locs)} יישובים ומועצות, עם שיוך למטרופולין ומיקום WGS84. "
               f"{pct(real_share)} מהתחנות במטרופולינים; {lead_city[0]} מובילה עם {n(lead_city[1])} תחנות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תחבורה ציבורית", "תחנות אוטובוס", "רכבת קלה", "מטרופולינים", "גיאוגרפיה"],
            "related_ids": [
                "1e9d4542-97af-47ac-a780-f2a6b291b1f5",
                "1745d2f8-1cff-4ef6-bd57-427ac7b9addb",
                "3edcd023-f7ca-43eb-928f-6fdda479c172",
                "30cc4889-9bd7-4888-a66d-51ab39eb579a",
                "37c93c3e-e536-4abd-aedf-2813bfc74a4c",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "metros": metro_chart, "types": types_chart, "heat": heat, "ops": ops_chart,
            "cities": cities_chart, "conc": conc_chart, "sizes": sizes_chart,
            "bands": bands_chart, "grid": grid_chart,
        },
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "flags": {"ops": bool(minor_ops), "heat": bool(cells)},
    }
