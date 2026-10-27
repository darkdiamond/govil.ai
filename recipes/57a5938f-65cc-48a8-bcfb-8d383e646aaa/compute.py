"""פחים טמונים בבאר שבע — one row per underground waste bin: container make
("Type"), neighbourhood label and a WGS84 point.  The page is about WHICH
makes the city uses, WHERE they sit (per neighbourhood, make mix per
neighbourhood), HOW the bins group (nearest-neighbour spacing, multi-bin
sites) and how concentrated each make is on the map.

The CSV, XLSX and ITM resources are twins of one table; only the CSV is read.
Order-independent: integer counts, medians and sorted aggregates only.
"""
import math

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
UNKNOWN = "לא צוין"
OTHER = "אחר"
LETTER_HOODS = set("א ב ג ד ה ו ז ח ט י יא יב יג יד טו".split())
TOP_HOODS = 12
MIX_HOODS = 10
MIX_TYPES = 4          # makes shown individually in the mix chart (rest = אחר)
MAX_TYPES = 8
MIN_HOOD = 30          # bins a neighbourhood needs for the mix insights
NN_BIN_M = 10
NN_BINS = 10           # last bin open-ended
SITE_M = 15            # bins closer than this share a "site"
SITE_BINS = [(1, 1), (2, 2), (3, 3), (4, None)]
MIN_SPREAD = 10
LEAD_SHARE = 0.30
LEAD_MARGIN = 0.10
HOOD_LEAD_SHARE = 0.12
HOOD_TYPE_SHARE = 0.60
HOOD_TYPE_DELTA = 0.20
UNIFORM_SHARE = 0.90
SPREAD_RATIO = 1.3
UNKNOWN_MIN_SHARE = 0.005


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _hood_label(raw):
    return f"שכונה {raw}" if raw in LETTER_HOODS else raw


def _prepare(df):
    out = df.copy()
    out["type"] = out["Type"].str.strip().replace("", UNKNOWN)
    raw = out["neighborho"].str.strip()
    key = raw.map(lambda s: " ".join(sorted(s.split())))
    # one display form per token-set: the lexicographically smallest raw spelling
    disp = raw.groupby(key).min()
    out["hood"] = key.map(disp).replace("", UNKNOWN).map(
        lambda s: s if s == UNKNOWN else _hood_label(s))
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out = out.sort_values(["type", "hood", "latf", "lonf"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _xy_km(df, lat0):
    k = math.cos(math.radians(lat0))
    x = np.radians(df["lonf"].to_numpy()) * R_KM * k
    y = np.radians(df["latf"].to_numpy()) * R_KM
    return x, y


def _nearest_and_sites(x, y):
    """Nearest-other-point distance in metres for each (unique) point, and the
    size of the connected site (links shorter than SITE_M) it belongs to."""
    n = len(x)
    nn = np.full(n, np.inf)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for s in range(0, n, 500):
        e = min(n, s + 500)
        d = np.hypot(x[s:e, None] - x[None, :], y[s:e, None] - y[None, :]) * 1000
        d[np.arange(e - s), np.arange(s, e)] = np.inf
        nn[s:e] = d.min(axis=1)
        ii, jj = np.nonzero(d < SITE_M)
        for a, b in zip(ii.tolist(), jj.tolist()):
            ra, rb = find(a + s), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(n)])
    sizes = pd.Series(roots).value_counts()
    return nn, sizes


def _top_other(ranked, top):
    head = ranked.head(top)
    rest = int(ranked.iloc[top:].sum())
    names = list(head.index) + ([OTHER] if rest else [])
    vals = [int(v) for v in head] + ([rest] if rest else [])
    return names, vals


# --- insights ---------------------------------------------------------------

def insight_type_leader(types, total):
    known = types.drop(labels=[UNKNOWN], errors="ignore")
    if len(known) < 2:
        return None
    a, b = known.iloc[0], known.iloc[1]
    if a / total < LEAD_SHARE or (a - b) / total < LEAD_MARGIN:
        return None
    return (f"הסוג {known.index[0]} הוא הנפוץ ביותר עם {_int(a)} פחים "
            f"({_pct(a / total, 1)} מהמאגר), לעומת {_int(b)} בסוג {known.index[1]}.")


def insight_hood_lead(hoods, total):
    known = hoods.drop(labels=[UNKNOWN], errors="ignore")
    if len(known) < 3:
        return None
    a = known.iloc[0]
    if a / total < HOOD_LEAD_SHARE:
        return None
    top3 = int(known.iloc[:3].sum())
    return (f"{known.index[0]} היא השכונה עם הכי הרבה פחים טמונים: {_int(a)} "
            f"({_pct(a / total, 1)} מהמאגר). שלוש השכונות המובילות ({', '.join(known.index[:3])}) "
            f"מחזיקות יחד {_pct(top3 / total)} מהפחים.")


def insight_hood_type(df, types, total):
    best = None
    overall = types / total
    for hood, g in df.groupby("hood", sort=True):
        if hood == UNKNOWN or len(g) < MIN_HOOD:
            continue
        shares = g["type"].value_counts() / len(g)
        for t, s in sorted(shares.items()):
            if t == UNKNOWN:
                continue
            delta = s - float(overall.get(t, 0))
            if s >= HOOD_TYPE_SHARE and delta >= HOOD_TYPE_DELTA:
                cand = (-delta, hood, t, s, len(g))
                if best is None or cand < best:
                    best = cand
    if not best:
        return None
    _, hood, t, s, n = best
    return (f"ב{hood} {_pct(s)} מ-{_int(n)} הפחים הם מסוג {t}, לעומת "
            f"{_pct(float(overall[t]))} בכל העיר.")


def insight_uniform(df):
    big = [h for h, g in df.groupby("hood", sort=True) if h != UNKNOWN and len(g) >= MIN_HOOD]
    if len(big) < 3:
        return None
    uni = []
    for h in big:
        g = df[df["hood"] == h]
        if g["type"].value_counts().iloc[0] / len(g) >= UNIFORM_SHARE:
            uni.append(h)
    if not uni:
        return None
    return (f"ב-{_int(len(uni))} מתוך {_int(len(big))} השכונות הגדולות (לפחות {_int(MIN_HOOD)} פחים) "
            f"סוג אחד מהווה לפחות {_pct(UNIFORM_SHARE)} מהפחים — השכונה כמעט אחידה "
            f"מבחינת סוג.")


def insight_nearest(nn):
    near = float((nn <= 25).mean())
    return (f"המרחק החציוני בין פח טמון לפח הקרוב אליו הוא {_int(round(float(np.median(nn))))} מטרים; "
            f"ל-{_pct(near)} מהנקודות יש פח נוסף ברדיוס של {_int(25)} מטרים.")


def insight_sites(sizes, n_points):
    multi = sizes[sizes >= 2]
    if multi.empty:
        return None
    in_multi = int(multi.sum())
    return (f"{_int(len(multi))} אתרים כוללים כמה פחים צמודים (במרחק של עד {_int(SITE_M)} מטרים זה מזה), "
            f"ובהם {_pct(in_multi / n_points)} מהנקודות; האתר הגדול ביותר כולל {_int(int(multi.max()))} פחים.")


def insight_spread(spread):
    if len(spread) < 2:
        return None
    s = sorted(spread, key=lambda r: (r["radius_m"], r["name"]))
    lo, hi = s[0], s[-1]
    if lo["radius_m"] <= 0 or hi["radius_m"] < SPREAD_RATIO * lo["radius_m"]:
        return None
    return (f"הפחים מסוג {lo['name']} מרוכזים יותר: חצי מהם נמצאים עד {_int(lo['radius_m'])} מטרים "
            f"ממרכזם, לעומת {_int(hi['radius_m'])} מטרים בסוג {hi['name']}.")


def insight_unknown(df, total):
    n = int(((df["hood"] == UNKNOWN) | (df["type"] == UNKNOWN)).sum())
    if n / total < UNKNOWN_MIN_SHARE:
        return None
    nh = int((df["hood"] == UNKNOWN).sum())
    nt = int((df["type"] == UNKNOWN).sum())
    return (f"{_int(n)} רשומות ({_pct(n / total, 1)}) חסרות שכונה או סוג — {_int(nh)} בלי שכונה "
            f"ו-{_int(nt)} בלי סוג.")


def insight_extent(ns_km, ew_km):
    return f"הפחים פרוסים על פני {ns_km:.1f} ק״מ מצפון לדרום ו-{ew_km:.1f} ק״מ ממערב למזרח."


def compute(frames):
    df, n_bad = _prepare(frames["bins"])
    total = len(df)
    types = _ranked(df["type"])
    hoods = _ranked(df["hood"])
    lat0 = (df["latf"].min() + df["latf"].max()) / 2

    # type chart
    tnames, tvals = _top_other(types, MAX_TYPES)
    t_type = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
              for n, v in zip(tnames, tvals)]

    # hood chart
    hnames, hvals = _top_other(hoods, TOP_HOODS)
    t_hood = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
              for n, v in zip(hnames, hvals)]

    # mix: top neighbourhoods x top types (rest grouped), shares of the hood
    mix_hoods = [h for h in hoods.index if h != UNKNOWN][:MIX_HOODS]
    mix_types = [t for t in types.index if t != UNKNOWN][:MIX_TYPES]
    sub = df[df["hood"].isin(mix_hoods)]
    hood_n = sub["hood"].value_counts()
    ct = pd.crosstab(sub["hood"], sub["type"])
    mix_series, mix_rows = [], {h: [] for h in mix_hoods}
    for t in mix_types + [OTHER]:
        if t == OTHER:
            cols = [c for c in ct.columns if c not in mix_types]
            vals = ct[cols].sum(axis=1) if cols else pd.Series(0, index=ct.index)
            if int(vals.sum()) == 0:
                continue
        else:
            vals = ct[t]
        data = [round(float(vals.get(h, 0)) / float(hood_n[h]) * 100, 1) for h in mix_hoods]
        mix_series.append({"name": t if t != OTHER else "אחר / לא צוין", "data": data})
    mix = {"names": mix_hoods, "series": mix_series}
    t_mix = [{"name": h, "count": _int(hood_n[h]),
              "cells": [_pct(s["data"][i] / 100, 1) for s in mix_series]}
             for i, h in enumerate(mix_hoods)]

    # spatial: unique points
    uniq = df.drop_duplicates(subset=["latf", "lonf"]).sort_values(
        ["latf", "lonf"], kind="stable").reset_index(drop=True)
    n_dup = total - len(uniq)
    ux, uy = _xy_km(uniq, lat0)
    nn, sizes = _nearest_and_sites(ux, uy)
    finite = nn[np.isfinite(nn)]
    median_nn = float(np.median(finite)) if len(finite) else 0.0

    if len(finite):
        b = np.minimum((finite // NN_BIN_M).astype(int), NN_BINS - 1)
        counts = [int((b == i).sum()) for i in range(NN_BINS)]
        edges = [f"עד {(i + 1) * NN_BIN_M}" for i in range(NN_BINS - 1)]
        edges.append(f"מעל {(NN_BINS - 1) * NN_BIN_M}")
    else:
        counts, edges = [], []
    nearest = {"names": edges, "values": counts}
    t_nearest = [{"name": n, "count": _int(v), "share": _pct(v / len(finite), 1)}
                 for n, v in zip(edges, counts)] if len(finite) else []

    # sites by number of bins within SITE_M of each other
    site_names, site_vals = [], []
    for lo, hi in SITE_BINS:
        if hi is None:
            c = int((sizes >= lo).sum())
            site_names.append(f"{_int(lo)} או יותר")
        else:
            c = int(((sizes >= lo) & (sizes <= hi)).sum())
            site_names.append(_int(lo))
        site_vals.append(c)
    sites = {"names": site_names, "values": site_vals}
    t_sites = [{"name": n, "count": _int(v)} for n, v in zip(site_names, site_vals)]

    # spread per type: median distance from the type's median point
    x, y = _xy_km(df, lat0)
    spread = []
    for t, idx in sorted(df.groupby("type", sort=True).indices.items()):
        if t == UNKNOWN or len(idx) < MIN_SPREAD:
            continue
        gx, gy = x[idx], y[idx]
        d = np.hypot(gx - np.median(gx), gy - np.median(gy)) * 1000
        spread.append({"name": t, "count": int(len(idx)),
                       "radius_m": int(round(float(np.median(d))))})
    spread = sorted(spread, key=lambda r: (-r["count"], r["name"]))
    spread_chart = {"names": [r["name"] for r in spread],
                    "values": [r["radius_m"] for r in spread]}
    t_spread = [{"name": r["name"], "count": _int(r["count"]), "radius": _int(r["radius_m"])}
                for r in spread]

    ns_km = float((df["latf"].max() - df["latf"].min()) * math.radians(1) * R_KM)
    ew_km = float(x.max() - x.min())

    rules = [
        ("type_leader", insight_type_leader(types, total)),
        ("hood_lead", insight_hood_lead(hoods, total)),
        ("hood_type", insight_hood_type(df, types, total)),
        ("uniform", insight_uniform(df)),
        ("nearest", insight_nearest(finite) if len(finite) else None),
        ("sites", insight_sites(sizes, len(uniq))),
        ("spread", insight_spread(spread)),
        ("unknown", insight_unknown(df, total)),
        ("extent", insight_extent(ns_km, ew_km) if total > 1 else None),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    known_share = float(((df["hood"] != UNKNOWN) & (df["type"] != UNKNOWN)).mean())
    known_tone = "ok" if known_share >= 0.98 else "info" if known_share >= 0.90 else "warn"
    known_types = types.drop(labels=[UNKNOWN], errors="ignore")
    lead_name = known_types.index[0] if len(known_types) else UNKNOWN
    lead_share = float(known_types.iloc[0]) / total if len(known_types) else 0.0
    n_hoods = int((hoods.index != UNKNOWN).sum())
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "פחים טמונים במאגר"},
        "hoods": {"value": n_hoods, "display": _int(n_hoods), "tone": "brand",
                  "label": "שכונות ואזורים"},
        "leader": {"value": lead_share, "display": _pct(lead_share),
                   "tone": "brand", "label": f"מהפחים הם מסוג {lead_name}"},
        "known": {"value": known_share, "display": _pct(known_share, 1), "tone": known_tone,
                  "label": "מהרשומות עם שכונה וסוג מלאים"},
    }

    notes = []
    if n_bad:
        notes.append(f"{_int(n_bad)} רשומות בלי קואורדינטות תקינות לא נכללו.")
    if n_dup:
        notes.append(f"{_int(n_dup)} רשומות חולקות נקודה זהה עם רשומה אחרת; הן נספרות בסיכומים "
                     f"ולא בחישובי המרחק.")
    labels = {
        "lede": (f"{_int(total)} פחי אשפה טמונים בבאר שבע, עם סוג המיכל, שכונה ונקודת מיקום. "
                 f"אפשר לראות כאן אילו סוגים נפוצים, איך הם מתחלקים בין השכונות ואיפה הם מקובצים. "
                 + " ".join(notes)).strip(),
        "map_note": (f"{_int(total)} הפחים על המפה. לחצו על סמן כדי לראות סוג ושכונה; "
                     f"לחצו על אשכול כדי להתקרב."),
        "type_note": "מספר הפחים לפי סוג המיכל (שם היצרן או הספק כפי שרשום במאגר).",
        "type_aria": f"תרשים עמודות אופקי: פחים לפי סוג, {len(tnames)} קבוצות.",
        "type_caption": "מספר הפחים הטמונים לפי סוג.",
        "hood_note": (f"מספר הפחים בכל שכונה"
                      + (f"; {_int(TOP_HOODS)} הגדולות, והשאר מקובצות." if len(hoods) > TOP_HOODS else ".")),
        "hood_aria": f"תרשים עמודות אופקי: פחים לפי שכונה, {len(hnames)} קבוצות.",
        "hood_caption": "מספר הפחים הטמונים לפי שכונה.",
        "mix_note": (f"הרכב הסוגים בכל אחת מ-{_int(len(mix_hoods))} השכונות הגדולות, באחוזים "
                     f"מהפחים בשכונה."),
        "mix_aria": f"תרשים עמודות אופקי מוערם 100%: הרכב הסוגים ב-{len(mix_hoods)} שכונות.",
        "mix_caption": "אחוז הפחים מכל סוג בכל שכונה.",
        "nearest_note": (f"מרחק קו אווירי מכל נקודה לפח הקרוב אליה, בקבוצות של {_int(NN_BIN_M)} מטרים."),
        "nearest_aria": f"תרשים עמודות: התפלגות המרחק לפח הקרוב ביותר, {len(edges)} קבוצות.",
        "nearest_caption": "מספר הנקודות לפי המרחק לפח הקרוב ביותר (מטרים).",
        "sites_note": (f"אתר הוא קבוצת פחים במרחק של עד {_int(SITE_M)} מטרים זה מזה. "
                       f"התרשים סופר כמה אתרים יש לפי מספר הפחים בהם."),
        "sites_aria": f"תרשים עמודות: מספר האתרים לפי מספר הפחים באתר, {len(site_names)} קבוצות.",
        "sites_caption": "מספר האתרים לפי מספר הפחים באתר.",
        "spread_note": ("חציון המרחק של פחי כל סוג ממרכז הסוג — ככל שהערך נמוך, "
                        "הסוג מרוכז באזור קטן יותר בעיר."),
        "spread_aria": f"תרשים עמודות אופקי: רדיוס הפיזור במטרים של {len(spread)} סוגים.",
        "spread_caption": "רדיוס הפיזור (חציון, במטרים) לפי סוג.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} פחי אשפה טמונים בבאר שבע ב-{_int(n_hoods)} שכונות ואזורים; "
                           f"הסוג הנפוץ הוא {lead_name} ({_pct(lead_share)}), עם מפה של כל הנקודות."),
            "dataset_kind": "map",
            "suggested_tags": ["פחי אשפה", "פינוי אשפה", "באר שבע", "ניקיון", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["566c2420-1b00-4813-8a75-c6d8750c5ec8",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "82a30a97-01b0-4281-854c-c7931f3445c0"],
        },
        "kpis": kpis,
        "charts": {"type": {"names": tnames, "values": tvals},
                   "hood": {"names": hnames, "values": hvals},
                   "mix": mix, "nearest": nearest, "sites": sites,
                   "spread": spread_chart},
        "tables": {"type": t_type, "hood": t_hood, "mix": t_mix, "nearest": t_nearest,
                   "sites": t_sites, "spread": t_spread},
        "mix_headers": [s["name"] for s in mix_series],
        "insights": insights,
        "has_mix": bool(mix_hoods and mix_series),
        "has_nearest": bool(len(finite)),
        "has_sites": bool(sum(site_vals)),
        "has_spread": bool(spread),
        "labels": labels,
    }
