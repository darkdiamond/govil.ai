"""מעונות יום בבאר שבע — one row per daycare (up to age 3): name, operator,
neighbourhood and a WGS84 point.  The page shows WHO runs the daycares
(private vs organisations/chains), WHERE they are (per neighbourhood,
operator mix per neighbourhood, distance from the city-wide centre) and how
densely they are spaced.

The CSV, XLSX and ITM resources are twins of one table; only the CSV is read.
The source truncates operator / neighbourhood / address to 8 characters; the
page says so.  Street addresses are not shown (truncated, and some daycares
are run from private homes).
Order-independent: integer counts, medians and sorted aggregates only.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
UNKNOWN = "לא צוין"
OTHER = "אחר"
PRIVATE = "פרטי"
NO_OPERATOR = {"", "אין", "0", "-"}
HOOD_FULL = {"נווה מנח": "נווה מנחם", "נווה עופ": "נווה עופר", "עיר עתיק": "עיר עתיקה"}
TOP_OPS = 10
TOP_HOODS = 12
MIX_HOODS = 8
MIX_OPS = 4
MIN_HOOD = 8
MIN_DELTA = 0.20
MIN_ORG_SHARE = 0.05
CENTRE_KM = 1.0
CENTRE_BINS = 8       # last bin open-ended
NN_M = 100
NN_BINS = 8           # last bin open-ended
NEAR_M = 250
TRUNC_LEN = 8
TRUNC_MIN_SHARE = 0.05


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _hood_label(raw):
    s = " ".join(raw.split())
    if not s:
        return UNKNOWN
    m = re.fullmatch(r"(?:שכונה\s+)?([א-ת]{1,2})['׳]?", s)
    if m:
        return f"שכונה {m.group(1)}'"
    if len(s) == TRUNC_LEN and s in HOOD_FULL:
        return HOOD_FULL[s]
    return s


def _prepare(df):
    out = df.copy()
    op = out["operator"].str.strip()
    out["op"] = op.where(~op.isin(NO_OPERATOR), UNKNOWN)
    out["hood"] = out["neighbor"].map(_hood_label)
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["priv"] = out["op"] == PRIVATE
    out = out.sort_values(["op", "hood", "latf", "lonf", "name"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _xy_km(lat, lon, lat0):
    k = math.cos(math.radians(lat0))
    return (np.radians(lon) * R_KM * k, np.radians(lat) * R_KM)


def _top_other(ranked, top):
    head = ranked.head(top)
    rest = int(ranked.iloc[top:].sum())
    names = list(head.index) + ([OTHER] if rest else [])
    vals = [int(v) for v in head] + ([rest] if rest else [])
    return names, vals


def _hist(values, width, nbins, unit_fmt):
    b = np.minimum((values // width).astype(int), nbins - 1)
    counts = [int((b == i).sum()) for i in range(nbins)]
    names = [unit_fmt(i * width, (i + 1) * width) for i in range(nbins - 1)]
    names.append(f"מעל {_fmt_num((nbins - 1) * width)}")
    return names, counts


def _fmt_num(v):
    return f"{v:g}" if isinstance(v, float) else _int(v)


# --- insights ---------------------------------------------------------------

def insight_private_share(df, total):
    known = df[df["op"] != UNKNOWN]
    if len(known) < 10:
        return None
    n = int(known["priv"].sum())
    return (f"{_int(n)} מתוך {_int(len(known))} המעונות עם מפעיל מוכר ({_pct(n / len(known))}) "
            f"מסומנים כפרטיים; היתר מופעלים על ידי עמותות, רשתות וארגונים.")


def insight_org_leader(orgs):
    if len(orgs) < 2:
        return None
    total = int(orgs.sum())
    a, b = orgs.iloc[0], orgs.iloc[1]
    if a / total < MIN_ORG_SHARE or a == b:
        return None
    return (f"בין המעונות שאינם פרטיים המפעיל הגדול הוא {orgs.index[0]} עם {_int(a)} מעונות "
            f"({_pct(a / total)} מהם), לפני {orgs.index[1]} עם {_int(b)}.")


def insight_org_concentration(orgs):
    if len(orgs) < 5:
        return None
    total = int(orgs.sum())
    top3 = int(orgs.iloc[:3].sum())
    return (f"שלושת המפעילים הגדולים שאינם פרטיים ({', '.join(orgs.index[:3])}) מפעילים יחד "
            f"{_int(top3)} מעונות, {_pct(top3 / total)} מהמעונות הלא-פרטיים, "
            f"מתוך {_int(len(orgs))} מפעילים שונים.")


def insight_hood_lead(hoods, total):
    known = hoods.drop(labels=[UNKNOWN], errors="ignore")
    if len(known) < 3:
        return None
    a = known.iloc[0]
    top3 = int(known.iloc[:3].sum())
    return (f"{known.index[0]} מובילה במספר המעונות: {_int(a)} ({_pct(a / total)} מהמאגר). "
            f"שלוש השכונות המובילות ({', '.join(known.index[:3])}) מחזיקות יחד {_pct(top3 / total)}.")


def insight_hood_private(df):
    known = df[df["op"] != UNKNOWN]
    if len(known) < 10:
        return None
    overall = float(known["priv"].mean())
    best = None
    for hood, g in known.groupby("hood", sort=True):
        if hood == UNKNOWN or len(g) < MIN_HOOD:
            continue
        s = float(g["priv"].mean())
        delta = s - overall
        if abs(delta) >= MIN_DELTA:
            cand = (-abs(delta), hood, s, len(g))
            if best is None or cand < best:
                best = cand
    if not best:
        return None
    _, hood, s, n = best
    word = "גבוה" if s > overall else "נמוך"
    return (f"ב{hood} שיעור המעונות הפרטיים {word} מהממוצע: {_pct(s)} מ-{_int(n)} מעונות, "
            f"לעומת {_pct(overall)} בכל העיר.")


def insight_reach(df):
    known = df[(df["op"] != UNKNOWN) & (df["hood"] != UNKNOWN) & (~df["priv"])]
    if known.empty:
        return None
    reach = known.groupby("op")["hood"].nunique()
    reach = reach.sort_index().sort_values(ascending=False, kind="stable")
    if len(reach) < 2 or reach.iloc[0] < 3 or reach.iloc[0] == reach.iloc[1]:
        return None
    n = int(reach.iloc[0])
    cnt = int((known["op"] == reach.index[0]).sum())
    return (f"{reach.index[0]} היא המפעיל הלא-פרטי עם הפריסה הרחבה ביותר: "
            f"{_int(cnt)} מעונות ב-{_int(n)} שכונות שונות.")


def insight_centre(d_centre, total):
    near = float((d_centre <= 2.0).mean())
    return (f"{_pct(near)} מהמעונות נמצאים ברדיוס של {_int(2)} ק״מ מהמרכז הגיאוגרפי של המאגר; "
            f"החציון הוא {np.median(d_centre):.1f} ק״מ.")


def insight_nearest(nn):
    near = float((nn <= NEAR_M).mean())
    return (f"המרחק החציוני ממעון למעון הקרוב אליו הוא {_int(round(float(np.median(nn))))} מטרים; "
            f"ל-{_pct(near)} מהמעונות יש מעון נוסף ברדיוס של {_int(NEAR_M)} מטרים.")


def insight_extent(ns_km, ew_km):
    return f"המעונות פרוסים על פני {ns_km:.1f} ק״מ מצפון לדרום ו-{ew_km:.1f} ק״מ ממערב למזרח."


def insight_truncated(df):
    n = int(((df["neighbor"].str.strip().str.len() == TRUNC_LEN) |
             (df["operator"].str.strip().str.len() == TRUNC_LEN)).sum())
    if n / len(df) < TRUNC_MIN_SHARE:
        return None
    return (f"במאגר שמות השכונה והמפעיל קטועים ל-{_int(TRUNC_LEN)} תווים, ולכן {_int(n)} רשומות "
            f"מציגות ערך חלקי; הסיכומים מקבצים לפי הערך כפי שהוא רשום.")


def compute(frames):
    df, n_bad = _prepare(frames["daycares"])
    total = len(df)
    ops = _ranked(df["op"])
    hoods = _ranked(df["hood"])
    orgs = _ranked(df.loc[(df["op"] != UNKNOWN) & (~df["priv"]), "op"])
    lat0 = float((df["latf"].min() + df["latf"].max()) / 2)

    onames, ovals = _top_other(ops, TOP_OPS)
    t_op = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(onames, ovals)]
    hnames, hvals = _top_other(hoods, TOP_HOODS)
    t_hood = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(hnames, hvals)]

    # mix: biggest neighbourhoods x top operators (shares of the neighbourhood)
    mix_hoods = [h for h in hoods.index if h != UNKNOWN][:MIX_HOODS]
    mix_ops = [o for o in ops.index if o != UNKNOWN][:MIX_OPS]
    sub = df[df["hood"].isin(mix_hoods)]
    hood_n = sub["hood"].value_counts()
    ct = pd.crosstab(sub["hood"], sub["op"])
    mix_series = []
    for o in mix_ops + [OTHER]:
        if o == OTHER:
            cols = [c for c in ct.columns if c not in mix_ops]
            vals = ct[cols].sum(axis=1) if cols else pd.Series(0, index=ct.index)
            if int(vals.sum()) == 0:
                continue
        else:
            vals = ct[o]
        mix_series.append({"name": o if o != OTHER else "מפעילים אחרים",
                           "data": [round(float(vals.get(h, 0)) / float(hood_n[h]) * 100, 1)
                                    for h in mix_hoods]})
    mix = {"names": mix_hoods, "series": mix_series}
    t_mix = [{"name": h, "count": _int(hood_n[h]),
              "cells": [_pct(s["data"][i] / 100, 1) for s in mix_series]}
             for i, h in enumerate(mix_hoods)]

    # spatial
    x, y = _xy_km(df["latf"].to_numpy(), df["lonf"].to_numpy(), lat0)
    d_centre = np.hypot(x - np.median(x), y - np.median(y))
    cnames, ccounts = _hist(d_centre, CENTRE_KM, CENTRE_BINS,
                            lambda a, b: f"עד {_fmt_num(b)}")
    centre = {"names": cnames, "values": ccounts}
    t_centre = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in zip(cnames, ccounts)]

    uniq = df.drop_duplicates(subset=["latf", "lonf"]).sort_values(["latf", "lonf"], kind="stable")
    n_dup = total - len(uniq)
    ux, uy = _xy_km(uniq["latf"].to_numpy(), uniq["lonf"].to_numpy(), lat0)
    nn = np.full(len(ux), np.inf)
    for s in range(0, len(ux), 500):
        e = min(len(ux), s + 500)
        d = np.hypot(ux[s:e, None] - ux[None, :], uy[s:e, None] - uy[None, :]) * 1000
        d[np.arange(e - s), np.arange(s, e)] = np.inf
        nn[s:e] = d.min(axis=1)
    finite = nn[np.isfinite(nn)]
    if len(finite):
        nnames, ncounts = _hist(finite, NN_M, NN_BINS, lambda a, b: f"עד {_int(b)}")
        t_nn = [{"name": n, "count": _int(v), "share": _pct(v / len(finite), 1)}
                for n, v in zip(nnames, ncounts)]
    else:
        nnames, ncounts, t_nn = [], [], []
    nearest = {"names": nnames, "values": ncounts}

    ns_km = float((df["latf"].max() - df["latf"].min()) * math.radians(1) * R_KM)
    ew_km = float(x.max() - x.min())

    rules = [
        ("private_share", insight_private_share(df, total)),
        ("org_leader", insight_org_leader(orgs)),
        ("org_concentration", insight_org_concentration(orgs)),
        ("hood_lead", insight_hood_lead(hoods, total)),
        ("hood_private", insight_hood_private(df)),
        ("reach", insight_reach(df)),
        ("centre", insight_centre(d_centre, total) if total > 1 else None),
        ("nearest", insight_nearest(finite) if len(finite) else None),
        ("extent", insight_extent(ns_km, ew_km) if total > 1 else None),
        ("truncated", insight_truncated(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    known_ops = df[df["op"] != UNKNOWN]
    priv_share = float(known_ops["priv"].mean()) if len(known_ops) else 0.0
    n_hoods = int((hoods.index != UNKNOWN).sum())
    n_ops = int((ops.index != UNKNOWN).sum())
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand", "label": "מעונות יום במאגר"},
        "private": {"value": priv_share, "display": _pct(priv_share), "tone": "info",
                    "label": "מהמעונות פרטיים (מבין אלה עם מפעיל מוכר)"},
        "operators": {"value": n_ops, "display": _int(n_ops), "tone": "brand",
                      "label": "מפעילים שונים כולל פרטי"},
        "hoods": {"value": n_hoods, "display": _int(n_hoods), "tone": "brand",
                  "label": "שכונות ואזורים"},
    }

    notes = []
    if n_bad:
        notes.append(f"{_int(n_bad)} רשומות בלי קואורדינטות תקינות לא נכללו.")
    if n_dup:
        notes.append(f"{_int(n_dup)} רשומות חולקות נקודה זהה עם מעון אחר; הן נספרות בסיכומים "
                     f"ולא בחישובי המרחק לשכן.")
    labels = {
        "lede": (f"{_int(total)} מעונות יום בבאר שבע לילדים עד גיל 3, עם שם, מפעיל, שכונה ונקודת מיקום. "
                 f"אפשר לראות כאן מי מפעיל אותם, איך הם מתחלקים בין השכונות ואיפה הם מתרכזים. "
                 + " ".join(notes)).strip(),
        "map_note": (f"{_int(total)} המעונות על המפה. לחצו על סמן כדי לראות שם, מפעיל ושכונה; "
                     f"לחצו על אשכול כדי להתקרב."),
        "op_note": (f"מספר המעונות לפי מפעיל, כפי שהוא רשום במאגר"
                    + (f"; {_int(TOP_OPS)} הגדולים, והשאר מקובצים." if len(ops) > TOP_OPS else ".")),
        "op_aria": f"תרשים עמודות אופקי: מעונות לפי מפעיל, {len(onames)} קבוצות.",
        "op_caption": "מספר המעונות לפי מפעיל.",
        "hood_note": (f"מספר המעונות בכל שכונה"
                      + (f"; {_int(TOP_HOODS)} הגדולות, והשאר מקובצות." if len(hoods) > TOP_HOODS else ".")),
        "hood_aria": f"תרשים עמודות אופקי: מעונות לפי שכונה, {len(hnames)} קבוצות.",
        "hood_caption": "מספר המעונות לפי שכונה.",
        "mix_note": (f"הרכב המפעילים ב-{_int(len(mix_hoods))} השכונות עם הכי הרבה מעונות, באחוזים "
                     f"מהמעונות בשכונה."),
        "mix_aria": f"תרשים עמודות אופקי מוערם 100%: הרכב המפעילים ב-{len(mix_hoods)} שכונות.",
        "mix_caption": "אחוז המעונות של כל מפעיל בכל שכונה.",
        "centre_note": (f"מרחק קו אווירי מכל מעון למרכז המאגר (נקודת החציון של כל הקואורדינטות), "
                        f"בקבוצות של {_fmt_num(CENTRE_KM)} ק״מ."),
        "centre_aria": f"תרשים עמודות: התפלגות המרחק מהמרכז, {len(cnames)} קבוצות.",
        "centre_caption": "מספר המעונות לפי המרחק מהמרכז (ק״מ).",
        "nearest_note": (f"מרחק קו אווירי מכל מעון למעון הקרוב אליו, בקבוצות של {_int(NN_M)} מטרים."),
        "nearest_aria": f"תרשים עמודות: התפלגות המרחק למעון הקרוב ביותר, {len(nnames)} קבוצות.",
        "nearest_caption": "מספר המעונות לפי המרחק למעון הקרוב ביותר (מטרים).",
    }

    lead = orgs.index[0] if len(orgs) else None
    summary = (f"{_int(total)} מעונות יום בבאר שבע ב-{_int(n_hoods)} שכונות ואזורים; "
               f"{_pct(priv_share)} מהם פרטיים"
               + (f" והמפעיל הלא-פרטי הגדול הוא {lead}" if lead else "") + ", עם מפה של כל המעונות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מעונות יום", "גיל הרך", "באר שבע", "חינוך", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                            "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                            "82a30a97-01b0-4281-854c-c7931f3445c0"],
        },
        "kpis": kpis,
        "charts": {"op": {"names": onames, "values": ovals},
                   "hood": {"names": hnames, "values": hvals},
                   "mix": mix, "centre": centre, "nearest": nearest},
        "tables": {"op": t_op, "hood": t_hood, "mix": t_mix, "centre": t_centre, "nearest": t_nn},
        "mix_headers": [s["name"] for s in mix_series],
        "insights": insights,
        "has_mix": bool(mix_hoods and mix_series),
        "has_nearest": bool(len(finite)),
        "labels": labels,
    }
