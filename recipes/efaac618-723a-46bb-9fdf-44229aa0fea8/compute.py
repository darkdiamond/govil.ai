"""מתקני משחקים בבאר שבע: one row per playground, with a count per equipment type.

Ten numeric columns count units of a known equipment type (combined
structures A/B/C and special, swings, slides, carousels, spring riders,
zip line, "עלה ורד" seesaws); `other` is free text naming extra equipment;
`shadowing` (יש / אי, a truncated "אין") and `surface` describe the site;
`Name` + WGS84 `lat`/`lon` place it.

The XLSX resource is read: the CSV twin's datastore was loaded with broken
multi-line quoting (rows shift columns), and the ITM twins hold the same
rows in another projection.

Everything is aggregated: equipment totals and reach, units per playground,
surface and shade mixes, a type co-occurrence matrix, a compass-sector
geography from the median centre, and keyword counts over `other` for the
equipment the fixed columns don't cover.

Order-independent: every ranking is a total sort with name / coordinate
tie-breaks.
"""
import math
import re

import pandas as pd

TYPES = [
    ("Swing", "נדנדות"),
    ("slid", "מגלשות"),
    ("spring", "מתקני קפיץ"),
    ("roserose", "עלה ורד"),
    ("combined1", "משולב א׳"),
    ("combined2", "משולב ב׳"),
    ("combined3", "משולב ג׳"),
    ("SpecialCom", "משולב מיוחד"),
    ("carrousel", "קרוסלות"),
    ("omega", "אומגה"),
]
MAX_UNITS = 30          # a per-type count above this is treated as a data-entry error
UNIT_BINS = [(0, 0), (1, 2), (3, 4), (5, 6), (7, 9), (10, 14), (15, None)]
TOP_N = 15
MAX_INSIGHTS = 7
INSIGHT_PRIORITY = ["shade", "types", "surf_shade", "concentration", "sector_shade", "extras", "surface",
                    "zero", "rare", "sector", "names"]
M_PER_DEG = 111320.0
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
DIST_EDGES = [0, 1000, 2000, 3000, 4000, 5000]
NO_SURFACE = "לא צוין"
SHADE_ORDER = ["יש הצללה", "אין הצללה", "לא צוין"]
# extra equipment named in the free-text `other` column: label -> regex
KEYWORDS = [
    ("קן לציפור", r"קן\s*(?:ל)?ציפור"),
    ("מתקני טיפוס", r"טיפוס"),
    ("שיווי משקל", r"שו?ו?י\s*משקל"),
    ("בית בובות", r"בית\s*בובות"),
    ("סביבון", r"סביבון"),
    ("פירמידת חבלים", r"פ[יי]?רמידת|פרמידת|פרמידה|פירמידה"),
    ("ערסל", r"ערסל"),
    ("מתקני כושר", r"כושר|מתח|כפיפות|מקבילי|גל רץ|הגה כ"),
    ("אופניים", r"אופניים"),
    ("פטריות", r"פטרי|פיטרי"),
    ("נענוע", r"נענוע|נאנוע"),
]


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def bin_label(lo, hi):
    if hi is None:
        return f"{lo}+"
    if lo == hi:
        return f"{lo}"
    return f"{lo}-{hi}"


def shade_of(v):
    v = (v or "").strip()
    if v.startswith("יש"):
        return SHADE_ORDER[0]
    if v.startswith("אי"):
        return SHADE_ORDER[1]
    return SHADE_ORDER[2]


def compute(frames):
    raw = frames["main"].copy()
    n = len(raw)
    df = pd.DataFrame({
        "name": raw["Name"].astype(str).str.strip(),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
        "shade": raw["shadowing"].map(shade_of),
        "surface": raw["surface"].astype(str).str.strip().replace("", NO_SURFACE),
        "other": raw["other"].astype(str).str.strip(),
    })
    n_outlier = 0
    for col, _ in TYPES:
        v = num(raw[col]).fillna(0)
        v = v.where(v >= 0, 0)
        bad = v > MAX_UNITS
        n_outlier += int(bad.sum())
        df[col] = v.where(~bad, 0).round().astype(int)
    cols = [c for c, _ in TYPES]
    lab = dict(TYPES)
    df["units"] = df[cols].sum(axis=1)
    df["kinds"] = (df[cols] > 0).sum(axis=1)
    df["label"] = df["name"].where(df["name"] != "", "ללא שם")
    df = df.sort_values(["name", "la", "lo", "units"], kind="mergesort", na_position="last").reset_index(drop=True)

    total_units = int(df["units"].sum())
    n_noname = int((df["name"] == "").sum())
    named = df[df["name"] != ""]
    n_dupname = int(named["name"].duplicated(keep=False).sum())
    n_zero = int((df["units"] == 0).sum())
    n_zero_other = int(((df["units"] == 0) & (df["other"] != "")).sum())
    med_units = float(df["units"].median())
    n_special = int((df["SpecialCom"] > 0).sum())

    charts, tables = {}, {}

    # equipment totals and reach
    eq = []
    for c in cols:
        eq.append((lab[c], int(df[c].sum()), int((df[c] > 0).sum())))
    eq.sort(key=lambda t: (-t[1], -t[2], t[0]))
    charts["types"] = {"names": [e[0] for e in eq], "units": [e[1] for e in eq], "sites": [e[2] for e in eq]}
    tables["types"] = {"headers": ["סוג מתקן", "יחידות", "גני משחקים שבהם הוא קיים", "שיעור מהגנים"],
                       "rows": [[e[0], fmt(e[1]), fmt(e[2]), pct(e[2] / n)] for e in eq]}
    reach = sorted(eq, key=lambda t: (-t[2], -t[1], t[0]))

    # units per playground
    bl, bv = [], []
    for lo, hi in UNIT_BINS:
        m = df["units"] >= lo
        if hi is not None:
            m &= df["units"] <= hi
        bl.append(bin_label(lo, hi))
        bv.append(int(m.sum()))
    charts["units"] = {"names": bl, "values": bv}
    tables["units"] = {"headers": ["יחידות מתקן בגן", "גני משחקים", "שיעור"],
                       "rows": [[l, fmt(v), pct(v / n)] for l, v in zip(bl, bv)]}

    # variety: number of distinct equipment types
    kmax = int(df["kinds"].max()) if n else 0
    kl = [str(k) for k in range(0, kmax + 1)]
    kv = [int((df["kinds"] == k).sum()) for k in range(0, kmax + 1)]
    charts["kinds"] = {"names": kl, "values": kv}
    tables["kinds"] = {"headers": ["סוגי מתקנים שונים בגן", "גני משחקים"],
                       "rows": [[l, fmt(v)] for l, v in zip(kl, kv)]}
    med_kinds = float(df["kinds"].median())

    # top playgrounds by units
    top = df.sort_values(["units", "kinds", "name", "la", "lo"], ascending=[False, False, True, True, True],
                         kind="mergesort").head(TOP_N)
    charts["top"] = {"names": top["label"].tolist(), "values": [int(v) for v in top["units"]]}
    tables["top"] = {"headers": ["גן משחקים", "יחידות מתקן", "סוגים שונים", "משטח"],
                     "rows": [[a, fmt(b), fmt(c), d] for a, b, c, d in
                              zip(top["label"], top["units"], top["kinds"], top["surface"])]}
    top_decile = max(1, int(math.ceil(n * 0.1)))
    top_share = (float(df["units"].sort_values(ascending=False, kind="mergesort").head(top_decile).sum()) / total_units
                 if total_units else 0.0)

    # surface x shade
    surf = df.groupby("surface").size().reset_index(name="c")
    surf = surf.sort_values(["c", "surface"], ascending=[False, True], kind="mergesort")
    surf_names = [s for s in surf["surface"] if s != NO_SURFACE] + ([NO_SURFACE] if NO_SURFACE in set(surf["surface"]) else [])
    surf_counts = {s: int(c) for s, c in zip(surf["surface"], surf["c"])}
    shade_counts = {s: int((df["shade"] == s).sum()) for s in SHADE_ORDER}
    charts["surface"] = {"names": surf_names, "values": [surf_counts[s] for s in surf_names]}
    tables["surface"] = {"headers": ["סוג משטח", "גני משחקים", "שיעור"],
                         "rows": [[s, fmt(surf_counts[s]), pct(surf_counts[s] / n)] for s in surf_names]}
    charts["shade"] = {"names": SHADE_ORDER, "values": [shade_counts[s] for s in SHADE_ORDER]}
    ss = []
    srows = []
    for s in surf_names:
        sub = df[df["surface"] == s]
        vals = [int((sub["shade"] == k).sum()) for k in SHADE_ORDER]
        ss.append(vals)
        known = vals[0] + vals[1]
        srows.append([s, fmt(vals[0]), fmt(vals[1]), fmt(vals[2]), pct(vals[0] / known) if known else "-"])
    charts["surf_shade"] = {"names": surf_names, "series": SHADE_ORDER,
                            "values": [[ss[i][j] for i in range(len(surf_names))] for j in range(len(SHADE_ORDER))]}
    tables["surf_shade"] = {"headers": ["סוג משטח", "יש הצללה", "אין הצללה", "לא צוין", "שיעור מוצל (מתוך הידוע)"],
                            "rows": srows}
    tables["shade"] = {"headers": ["הצללה", "גני משחקים", "שיעור"],
                       "rows": [[s, fmt(shade_counts[s]), pct(shade_counts[s] / n)] for s in SHADE_ORDER]}

    # average units by surface (sites with a known surface)
    avg_rows = []
    for s in surf_names:
        sub = df[df["surface"] == s]
        avg_rows.append((s, float(sub["units"].mean()), len(sub)))
    charts["surf_avg"] = {"names": [r[0] for r in avg_rows], "values": [round(r[1], 1) for r in avg_rows]}
    tables["surf_avg"] = {"headers": ["סוג משטח", "ממוצע יחידות לגן", "גני משחקים"],
                          "rows": [[r[0], f"{r[1]:.1f}", fmt(r[2])] for r in avg_rows]}

    # co-occurrence of equipment types (share of sites with row-type that also have col-type)
    order = [e[0] for e in reach]
    inv = {v: k for k, v in lab.items()}
    cells, crow = [], []
    for i, a in enumerate(order):
        ha = df[inv[a]] > 0
        na = int(ha.sum())
        row = [a]
        for j, b in enumerate(order):
            both = int((ha & (df[inv[b]] > 0)).sum())
            share = round(100.0 * both / na, 1) if na else 0.0
            cells.append([j, i, share, both])
            row.append(f"{share:.0f}%" if na else "-")
        crow.append(row)
    charts["cooc"] = {"names": order, "cells": cells}
    tables["cooc"] = {"headers": ["כשיש…"] + order, "rows": crow}

    # geography
    geo = df[df["la"].between(29, 34) & df["lo"].between(34, 36)].copy().reset_index(drop=True)
    n_geo = len(geo)
    n_badgeo = n - n_geo
    has_geo = n_geo >= 5
    if has_geo:
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
        sec_rows, sec_sites, sec_units, sec_shade = [], [], [], []
        for i, s in enumerate(SECTORS):
            sub = geo[geo["sec"] == i]
            k = int((sub["shade"] != SHADE_ORDER[2]).sum())
            yes = int((sub["shade"] == SHADE_ORDER[0]).sum())
            sh = (yes / k) if k else None
            sec_sites.append(len(sub))
            sec_units.append(int(sub["units"].sum()))
            sec_shade.append(round(sh * 100, 1) if sh is not None else None)
            sec_rows.append([s, fmt(len(sub)), fmt(int(sub["units"].sum())), pct(sh) if sh is not None else "-"])
        charts["sectors"] = {"names": SECTORS, "sites": sec_sites, "units": sec_units, "shade": sec_shade}
        tables["sectors"] = {"headers": ["כיוון מהמרכז", "גני משחקים", "יחידות מתקן", "שיעור מוצל (מתוך הידוע)"],
                             "rows": sec_rows}
        geo["db"] = [max(i for i, e in enumerate(DIST_EDGES) if v >= e) for v in geo["d"]]
        dl = []
        for i, lo in enumerate(DIST_EDGES):
            if i + 1 < len(DIST_EDGES):
                dl.append(f"{lo / 1000:g}-{DIST_EDGES[i + 1] / 1000:g} ק״מ")
            else:
                dl.append(f"מעל {lo / 1000:g} ק״מ")
        dv = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
        charts["dist"] = {"names": dl, "values": dv}
        tables["dist"] = {"headers": ["מרחק ממרכז הגנים", "גני משחקים", "שיעור"],
                          "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dv)]}
        med_d = float(geo["d"].median())
    else:
        charts["sectors"] = {"names": [], "sites": [], "units": [], "shade": []}
        tables["sectors"] = {"headers": [], "rows": []}
        charts["dist"] = {"names": [], "values": []}
        tables["dist"] = {"headers": [], "rows": []}
        med_d = 0.0

    # free-text extras
    with_other = df[df["other"] != ""]
    n_other = len(with_other)
    kw = []
    for name, rx in KEYWORDS:
        c = int(with_other["other"].str.contains(rx, regex=True).sum())
        if c > 0:
            kw.append((name, c))
    kw.sort(key=lambda t: (-t[1], t[0]))
    has_kw = len(kw) >= 2
    charts["extras"] = {"names": [k[0] for k in kw], "values": [k[1] for k in kw]}
    tables["extras"] = {"headers": ["מתקן נוסף (מתוך התיאור החופשי)", "גני משחקים שמזכירים אותו"],
                        "rows": [[k[0], fmt(k[1])] for k in kw]}

    # ---------- insights ----------
    insights = []
    known = shade_counts[SHADE_ORDER[0]] + shade_counts[SHADE_ORDER[1]]
    shade_share = shade_counts[SHADE_ORDER[0]] / known if known else None
    if shade_share is not None and known >= 10:
        if shade_share >= 0.6:
            head = f"רוב גני המשחקים מוצלים: {fmt(shade_counts[SHADE_ORDER[0]])} מתוך {fmt(known)} שמצב ההצללה שלהם ידוע ({pct(shade_share)})"
        elif shade_share <= 0.4:
            head = f"רוב גני המשחקים אינם מוצלים: רק {fmt(shade_counts[SHADE_ORDER[0]])} מתוך {fmt(known)} שמצב ההצללה שלהם ידוע מוצלים ({pct(shade_share)})"
        else:
            head = f"כמחצית מגני המשחקים מוצלים: {fmt(shade_counts[SHADE_ORDER[0]])} מתוך {fmt(known)} שמצב ההצללה שלהם ידוע ({pct(shade_share)})"
        tail = (f"; אצל {fmt(shade_counts[SHADE_ORDER[2]])} גנים ההצללה לא צוינה." if shade_counts[SHADE_ORDER[2]] else ".")
        insights.append({"id": "shade", "text_he": head + tail})

    if total_units > 0:
        e0 = eq[0]
        r0 = reach[0]
        txt = (f"סוג המתקן הנפוץ ביותר הוא {e0[0]}: {fmt(e0[1])} יחידות, {pct(e0[1] / total_units)} מכל "
               f"{fmt(total_units)} יחידות המתקן שנספרו.")
        if r0[0] != e0[0]:
            txt += f" לעומת זאת, הסוג שנמצא במספר הגנים הגדול ביותר הוא {r0[0]} ({fmt(r0[2])} גנים, {pct(r0[2] / n)})."
        else:
            txt += f" הסוג הזה נמצא גם במספר הגנים הגדול ביותר: {fmt(r0[2])} גנים ({pct(r0[2] / n)})."
        insights.append({"id": "types", "text_he": txt})
        rare = [e for e in reach if e[2] > 0 and e[2] / n < 0.05]
        if rare:
            rr = rare[-1]
            insights.append({"id": "rare", "text_he": (
                f"סוג המתקן הנדיר ביותר הוא {rr[0]}, שנמצא רק ב־{fmt(rr[2])} גני משחקים מתוך {fmt(n)}.")})

    if total_units > 0 and n >= 20 and top_share >= 0.2:
        t0 = top.iloc[0]
        insights.append({"id": "concentration", "text_he": (
            f"ב־{fmt(top_decile)} הגנים המאובזרים ביותר (העשירון העליון) מרוכזות {pct(top_share)} מיחידות המתקן. "
            f"הגדול שבהם, ״{t0['label']}״, כולל {fmt(t0['units'])} יחידות מ־{fmt(t0['kinds'])} סוגים, "
            f"לעומת חציון של {med_units:g} יחידות לגן.")})

    if len(surf_names) >= 2:
        s0 = [s for s in surf_names if s != NO_SURFACE]
        if s0:
            lead = s0[0]
            share = surf_counts[lead] / n
            if share >= 0.3:
                txt = f"המשטח הנפוץ הוא {lead}: {fmt(surf_counts[lead])} גני משחקים ({pct(share)})"
                if len(s0) >= 2:
                    txt += f", ואחריו {s0[1]} ({fmt(surf_counts[s0[1]])})"
                txt += "."
                insights.append({"id": "surface", "text_he": txt})
        best, worst = None, None
        for s, vals in zip(surf_names, ss):
            if s == NO_SURFACE:
                continue
            k = vals[0] + vals[1]
            if k < 8:
                continue
            r = vals[0] / k
            if best is None or (r, s) > (best[0], best[1]):
                best = (r, s, k)
            if worst is None or (r, s) < (worst[0], worst[1]):
                worst = (r, s, k)
        if best and worst and best[1] != worst[1] and best[0] - worst[0] >= 0.15:
            insights.append({"id": "surf_shade", "text_he": (
                f"ההצללה תלויה בסוג המשטח: {pct(best[0])} מהגנים על {best[1]} מוצלים, לעומת {pct(worst[0])} "
                f"בלבד מהגנים על {worst[1]} (מתוך גנים שמצב ההצללה שלהם ידוע).")})

    if has_geo:
        cand = [(sec_shade[i], SECTORS[i], sec_sites[i]) for i in range(len(SECTORS))
                if sec_shade[i] is not None and sec_sites[i] >= 10]
        if len(cand) >= 2:
            hi = max(cand, key=lambda t: (t[0], t[1]))
            lo = min(cand, key=lambda t: (t[0], t[1]))
            if hi[0] - lo[0] >= 15:
                insights.append({"id": "sector_shade", "text_he": (
                    f"פער גאוגרפי בהצללה: בגנים שמ{hi[1]} למרכז הפריסה {hi[0]:.1f}% מוצלים, ובגנים שמ{lo[1]} למרכז "
                    f"{lo[0]:.1f}% בלבד (כיוונים עם {fmt(10)} גנים לפחות, מתוך הגנים שמצב ההצללה שלהם ידוע).")})
        top_s = max(range(len(SECTORS)), key=lambda i: (sec_sites[i], -i))
        if sec_sites[top_s] / n_geo >= 0.18:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון הצפוף ביותר בגני משחקים ביחס למרכז הפריסה הוא {SECTORS[top_s]}: {fmt(sec_sites[top_s])} "
                f"גנים ({pct(sec_sites[top_s] / n_geo)}). המרחק החציוני של גן ממרכז הפריסה הוא {med_d / 1000:,.1f} ק״מ.")})

    if n_zero > 0:
        txt = f"ב־{fmt(n_zero)} גני משחקים לא נספר אף מתקן מהסוגים הקבועים"
        if n_zero_other:
            txt += f"; אצל {fmt(n_zero_other)} מהם המתקנים מתוארים רק בשדה החופשי"
        insights.append({"id": "zero", "text_he": txt + "."})

    if has_kw:
        k0 = kw[0]
        insights.append({"id": "extras", "text_he": (
            f"ב־{fmt(n_other)} גנים ({pct(n_other / n)}) יש תיאור חופשי של מתקנים נוספים. הנפוץ שבהם הוא "
            f"{k0[0]}, שמוזכר ב־{fmt(k0[1])} גנים.")})

    if n_noname or n_dupname:
        parts = []
        if n_noname:
            parts.append(f"ל־{fmt(n_noname)} גני משחקים אין שם במאגר")
        if n_dupname:
            parts.append(f"{fmt(n_dupname)} רשומות חולקות שם עם רשומה אחרת")
        insights.append({"id": "names", "text_he": "; ".join(parts) + ". מיקום כל הגנים מופיע במפה."})

    if n_outlier or n_badgeo:
        parts = []
        if n_outlier:
            what = "ספירת מתקן חריגה אחת" if n_outlier == 1 else f"{fmt(n_outlier)} ספירות מתקן חריגות"
            verb = "לא נכללה" if n_outlier == 1 else "לא נכללו"
            parts.append(f"{what} (מעל {fmt(MAX_UNITS)} יחידות מסוג אחד) {verb} בסיכומים")
        if n_badgeo:
            parts.append(f"ל־{fmt(n_badgeo)} רשומות אין קואורדינטות תקינות")
        insights.append({"id": "quality", "text_he": "; ".join(parts) + "."})

    # keep the page to a readable list: highest-priority findings first, the
    # data-quality disclosure always kept
    rank = {k: i for i, k in enumerate(INSIGHT_PRIORITY)}
    qual = [i for i in insights if i["id"] == "quality"]
    rest = sorted([i for i in insights if i["id"] != "quality"], key=lambda i: rank[i["id"]])
    insights = rest[:MAX_INSIGHTS] + qual

    # ---------- kpis ----------
    kpis = {
        "sites": {"value": n, "display": fmt(n), "tone": "brand", "label": "גני משחקים במאגר"},
        "units": {"value": total_units, "display": fmt(total_units), "tone": "brand",
                  "label": "יחידות מתקן שנספרו (עשרה סוגים)"},
        "shade": {"value": round(shade_share * 100, 1) if shade_share is not None else None,
                  "display": pct(shade_share) if shade_share is not None else "-",
                  "tone": ("ok" if shade_share is not None and shade_share >= 0.7 else
                           "warn" if shade_share is not None and shade_share >= 0.4 else "danger"),
                  "label": "גנים מוצלים (מתוך מצב הצללה ידוע)"},
        "median": {"value": med_units, "display": f"{med_units:g}", "tone": "info",
                   "label": "חציון יחידות מתקן לגן"},
    }

    ls = surf_names[0] if surf_names else ""
    summary = (
        f"מפת {fmt(n)} גני המשחקים בבאר שבע: איתור גן לפי שם, סוגי מתקנים, משטח והצללה. "
        + (f"{pct(shade_share)} מהגנים מוצלים." if shade_share is not None else "")
    )
    lede = (
        f"מאגר מתקני המשחקים של עיריית באר שבע ממפה {fmt(n)} גני משחקים ציבוריים, ובהם {fmt(total_units)} יחידות "
        f"מתקן מעשרה סוגים קבועים (נדנדות, מגלשות, מתקני קפיץ, מתקנים משולבים ועוד), לצד סוג המשטח והאם הגן מוצל. "
        f"בגן חציוני יש {med_units:g} יחידות מ־{med_kinds:g} סוגים שונים."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא גן משחקים; לחיצה מציגה את שמו, סוג המשטח וההצללה.",
        "types_note": f"כמה יחידות מכל סוג נספרו בכל {fmt(n)} הגנים, ובכמה גנים כל סוג קיים.",
        "units_note": f"כמה יחידות מתקן (מהסוגים הקבועים) יש בכל גן; החציון {med_units:g}.",
        "kinds_note": f"כמה סוגי מתקנים שונים יש בכל גן; החציון {med_kinds:g}.",
        "top_note": f"{fmt(min(TOP_N, n))} הגנים עם מספר יחידות המתקן הגדול ביותר.",
        "surface_note": "סוג המשטח שעליו מוצבים המתקנים, ובאיזה שיעור מכל משטח יש הצללה.",
        "shade_note": "מצב ההצללה בגנים (השדה במקור: יש או אין).",
        "surf_avg_note": "ממוצע יחידות המתקן לגן לפי סוג המשטח.",
        "cooc_note": "בכל שורה: מתוך הגנים שיש בהם סוג המתקן, באיזה שיעור יש גם את סוג העמודה.",
        "sectors_note": "גני המשחקים ויחידות המתקן לפי כיוון ממרכז הפריסה (חציון הקואורדינטות), עם שיעור הגנים המוצלים בכל כיוון.",
        "dist_note": f"מרחק כל גן ממרכז הפריסה; החציון {med_d / 1000:,.1f} ק״מ.",
        "extras_note": (f"מתקנים שמופיעים רק בתיאור החופשי, בכמה מתוך {fmt(n_other)} הגנים שיש להם תיאור כזה "
                        "הם מוזכרים (גן יכול להזכיר כמה)."),
        "types_aria": "יחידות מתקן וגני משחקים לפי סוג מתקן", "types_cap": "סוגי המתקנים",
        "units_aria": "גני משחקים לפי מספר יחידות המתקן", "units_cap": "גני משחקים לפי מספר יחידות",
        "kinds_aria": "גני משחקים לפי מספר סוגי המתקנים", "kinds_cap": "גני משחקים לפי מגוון",
        "top_aria": "הגנים המאובזרים ביותר", "top_cap": "הגנים המאובזרים ביותר",
        "surface_aria": "גני משחקים לפי סוג משטח והצללה", "surface_cap": "משטח והצללה",
        "shade_aria": "גני משחקים לפי מצב הצללה", "shade_cap": "מצב הצללה",
        "surf_avg_aria": "ממוצע יחידות מתקן לפי סוג משטח", "surf_avg_cap": "ממוצע יחידות לפי משטח",
        "cooc_aria": "מפת חום של הופעה משותפת של סוגי מתקנים", "cooc_cap": "הופעה משותפת של סוגי מתקנים",
        "sectors_aria": "גני משחקים לפי כיוון מהמרכז", "sectors_cap": "גני משחקים לפי כיוון",
        "dist_aria": "גני משחקים לפי מרחק מהמרכז", "dist_cap": "גני משחקים לפי מרחק",
        "extras_aria": "מתקנים נוספים מתוך התיאור החופשי", "extras_cap": "מתקנים נוספים",
        "max_units": fmt(MAX_UNITS),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מתקני משחקים", "גני שעשועים", "ילדים", "מרחב ציבורי", "באר שבע"],
            "related_ids": [
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "b795e2e0-491e-4040-877e-f3681917f8be",
                "5944b454-751c-4604-94d6-e676d7d34612",
                "7edbd028-9704-440c-a1b6-a0ed566081bc",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"geo": has_geo, "extras": has_kw},
    }
