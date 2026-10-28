"""מקלטים בעיר באר שבע — one row per public shelter: code ("ד/12") and WGS84
point.  The code is a prefix (an area/series letter group) and a running
number.  Everything the page says is derived from those two things: how the
shelters split by prefix, how complete each numbering run is, how the points
are spread over the city and how far each shelter is from its nearest
neighbour.

Order-independent: counts, medians and exact (sorted / fsum-free integer)
aggregates only.  Shelter codes are asset identifiers, not personal data.
"""
import math
import re

import numpy as np
import pandas as pd

CODE_RE = re.compile(r"^\s*(.+?)\s*/\s*(\d+)\s*$")
LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
TOP_PREFIXES = 12          # bars on the prefix chart (rest = "אחר")
MIN_RUN = 5                # shelters a prefix needs for numbering / spread charts
RUN_ROWS = 12              # prefixes on the numbering / spread charts
BIN_M = 25                 # nearest-neighbour histogram bin width (metres)
BIN_COUNT = 10             # last bin is open-ended
CLOSE_M = 15               # "practically adjacent" shelters
BAND_STEP = 0.01           # degrees per band (~1 km); widened if the span grows
MAX_BANDS = 14
LEAD_MARGIN = 0.10         # leader must beat the runner-up by this share of all
TOP3_SHARE = 0.5
GAP_MIN_SHARE = 0.03       # missing numbers must be this share of the span
ISOLATED_RATIO = 3         # farthest-shelter distance vs median
SPREAD_RATIO = 2           # widest vs tightest prefix radius
R_KM = 6371.0088


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = df.copy()
    out["name"] = out["name"].str.strip()
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = (out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
          & (out["name"] != ""))
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    m = out["name"].str.extract(CODE_RE)
    out["prefix"] = m[0]
    out["num"] = pd.to_numeric(m[1], errors="coerce")
    out["parsed"] = out["prefix"].notna()
    out["prefix"] = out["prefix"].fillna("ללא קידומת")
    out = out.sort_values(["prefix", "num", "name", "latf", "lonf"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _xy_km(df):
    lat0 = (df["latf"].min() + df["latf"].max()) / 2
    k = math.cos(math.radians(lat0))
    x = np.radians(df["lonf"].to_numpy()) * R_KM * k
    y = np.radians(df["latf"].to_numpy()) * R_KM
    return x, y


def _nearest_m(x, y):
    """Distance in metres from each point to its nearest other point."""
    n = len(x)
    out = np.full(n, np.inf)
    if n < 2:
        return out
    for s in range(0, n, 500):
        e = min(n, s + 500)
        d = np.hypot(x[s:e, None] - x[None, :], y[s:e, None] - y[None, :])
        d[np.arange(e - s), np.arange(s, e)] = np.inf
        out[s:e] = d.min(axis=1)
    return out * 1000


def _bands(values, step_deg_idx_scale=100):
    """Counts per equal-width degree band. Returns [(label, count)] in
    ascending coordinate order."""
    idx = np.floor(np.asarray(values) * step_deg_idx_scale + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    res = []
    for a in range(lo, hi + 1, w):
        c = int(((idx >= a) & (idx < a + w)).sum())
        res.append((f"{a / step_deg_idx_scale:.2f}-{(a + w) / step_deg_idx_scale:.2f}", c))
    return res


def _runs(df):
    """Per prefix with enough shelters: present numbers, span (max number),
    missing = span - present (numbering assumed to start at 1)."""
    p = df[df["parsed"]]
    rows = []
    for pre, g in p.groupby("prefix", sort=True):
        present = int(g["num"].nunique())
        span = int(g["num"].max())
        rows.append({"prefix": pre, "count": int(len(g)), "present": present,
                     "span": span, "missing": max(0, span - present)})
    return rows


def insight_leader(prefixes, total):
    if len(prefixes) < 2:
        return None
    a, b = prefixes.iloc[0], prefixes.iloc[1]
    if (a - b) / total < LEAD_MARGIN:
        return None
    return (f"הקידומת {prefixes.index[0]} מובילה עם {_int(a)} מקלטים "
            f"({_pct(a / total, 1)} מהמאגר), לעומת {_int(b)} בקידומת {prefixes.index[1]}.")


def insight_concentration(prefixes, total):
    if len(prefixes) < 4:
        return None
    top = prefixes.iloc[:3]
    share = int(top.sum()) / total
    if share < TOP3_SHARE:
        return None
    names = ", ".join(top.index)
    return (f"שלוש הקידומות הגדולות ({names}) מכילות {_pct(share)} מכל המקלטים, "
            f"מתוך {_int(len(prefixes))} קידומות.")


def insight_gaps(runs):
    miss = [r for r in runs if r["missing"] > 0 and r["count"] >= MIN_RUN]
    tot_span = sum(r["span"] for r in runs)
    tot_miss = sum(r["missing"] for r in runs)
    if not tot_span or tot_miss / tot_span < GAP_MIN_SHARE or not miss:
        return None
    worst = sorted(miss, key=lambda r: (-r["missing"], r["prefix"]))[0]
    return (f"ברצפי הקודים חסרים {_int(tot_miss)} מספרים מתוך {_int(tot_span)} "
            f"({_pct(tot_miss / tot_span, 1)}); הפער הגדול ביותר בקידומת {worst['prefix']}, "
            f"שבה הקוד הגבוה הוא {_int(worst['span'])} ורשומים {_int(worst['present'])} מקלטים. "
            f"ההנחה היא שהמספור מתחיל ב-1.")


def insight_nearest(nn, total):
    near = float((nn <= 100).mean())
    return (f"מרחק חציוני של {_int(round(float(np.median(nn))))} מטרים בין מקלט למקלט הקרוב אליו; "
            f"ל-{_pct(near)} מהמקלטים יש מקלט נוסף ברדיוס של {_int(100)} מטרים.")


def insight_close(df, nn):
    n = int((nn < CLOSE_M).sum())
    if n == 0:
        return None
    return (f"{_int(n)} מקלטים נמצאים במרחק של פחות מ-{_int(CLOSE_M)} מטרים ממקלט אחר, "
            f"כלומר כמעט באותה נקודה במפה.")


def insight_isolated(df, nn):
    med = float(np.median(nn))
    i = int(np.argmax(nn))
    if med <= 0 or nn[i] < ISOLATED_RATIO * med:
        return None
    return (f"המקלט {df['name'].iloc[i]} הוא המבודד ביותר: המקלט הקרוב אליו נמצא "
            f"במרחק של {_int(round(float(nn[i])))} מטרים, פי {nn[i] / med:.1f} מהחציון.")


def insight_extent(ns_km, ew_km):
    return (f"המקלטים פרוסים על פני {ns_km:.1f} ק״מ מצפון לדרום ו-{ew_km:.1f} ק״מ ממערב למזרח.")


def insight_compact(spread):
    if len(spread) < 3:
        return None
    s = sorted(spread, key=lambda r: (r["radius_m"], r["prefix"]))
    lo, hi = s[0], s[-1]
    if lo["radius_m"] <= 0 or hi["radius_m"] < SPREAD_RATIO * lo["radius_m"]:
        return None
    return (f"הקידומת {lo['prefix']} צפופה ביותר: חצי ממקלטיה נמצאים עד {_int(lo['radius_m'])} "
            f"מטרים ממרכזה, לעומת {_int(hi['radius_m'])} מטרים בקידומת {hi['prefix']}.")


def compute(frames):
    df, n_bad = _prepare(frames["shelters"])
    total = len(df)
    prefixes = _ranked(df["prefix"])
    x, y = _xy_km(df)
    nn = _nearest_m(x, y)
    finite = nn[np.isfinite(nn)]
    median_nn = float(np.median(finite)) if len(finite) else 0.0

    # prefix chart (top N + other)
    top = prefixes.head(TOP_PREFIXES)
    rest = int(prefixes.iloc[TOP_PREFIXES:].sum())
    pnames = list(top.index) + (["אחרות"] if rest else [])
    pvals = [int(v) for v in top] + ([rest] if rest else [])
    t_prefix = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in zip(pnames, pvals)]

    # numbering runs
    runs = _runs(df)
    big = sorted([r for r in runs if r["count"] >= MIN_RUN],
                 key=lambda r: (-r["span"], r["prefix"]))[:RUN_ROWS]
    numbering = {"names": [r["prefix"] for r in big],
                 "present": [r["present"] for r in big],
                 "missing": [r["missing"] for r in big]}
    t_numbering = [{"name": r["prefix"], "present": _int(r["present"]),
                    "span": _int(r["span"]), "missing": _int(r["missing"])} for r in big]
    tot_span = sum(r["span"] for r in runs)
    tot_present = sum(r["present"] for r in runs)

    # nearest-neighbour histogram
    if len(finite):
        b = np.minimum((finite // BIN_M).astype(int), BIN_COUNT - 1)
        counts = [int((b == i).sum()) for i in range(BIN_COUNT)]
        edges = [f"{i * BIN_M}-{(i + 1) * BIN_M}" for i in range(BIN_COUNT - 1)]
        edges.append(f"מעל {(BIN_COUNT - 1) * BIN_M}")
    else:
        counts, edges = [], []
    nearest = {"names": edges, "values": counts}
    t_nearest = [{"name": n, "count": _int(v), "share": _pct(v / len(finite), 1)}
                 for n, v in zip(edges, counts)] if len(finite) else []

    # spread per prefix: median distance of its shelters from their median point
    spread = []
    for pre, g in df[df["parsed"]].groupby("prefix", sort=True):
        if len(g) < MIN_RUN:
            continue
        # same projection origin for all prefixes
        gx = np.radians(g["lonf"].to_numpy()) * R_KM * math.cos(
            math.radians((df["latf"].min() + df["latf"].max()) / 2))
        gy = np.radians(g["latf"].to_numpy()) * R_KM
        d = np.hypot(gx - np.median(gx), gy - np.median(gy)) * 1000
        spread.append({"prefix": pre, "count": int(len(g)),
                       "radius_m": int(round(float(np.median(d))))})
    spread = sorted(spread, key=lambda r: (-r["count"], r["prefix"]))[:RUN_ROWS]
    spread_chart = {"names": [r["prefix"] for r in spread],
                    "values": [r["radius_m"] for r in spread]}
    t_spread = [{"name": r["prefix"], "count": _int(r["count"]),
                 "radius": _int(r["radius_m"])} for r in spread]

    # bands (north first / west first)
    lat_b = _bands(df["latf"].to_numpy())[::-1]
    lon_b = _bands(df["lonf"].to_numpy())
    lat_chart = {"names": [a for a, _ in lat_b], "values": [c for _, c in lat_b]}
    lon_chart = {"names": [a for a, _ in lon_b], "values": [c for _, c in lon_b]}
    t_lat = [{"name": a, "count": _int(c), "share": _pct(c / total, 1)} for a, c in lat_b]
    t_lon = [{"name": a, "count": _int(c), "share": _pct(c / total, 1)} for a, c in lon_b]

    ns_km = float((df["latf"].max() - df["latf"].min()) * math.radians(1) * R_KM)
    ew_km = float(x.max() - x.min())

    rules = [
        ("leader", insight_leader(prefixes, total)),
        ("concentration", insight_concentration(prefixes, total)),
        ("gaps", insight_gaps(runs)),
        ("nearest", insight_nearest(finite, total) if len(finite) else None),
        ("close", insight_close(df, nn) if len(finite) else None),
        ("isolated", insight_isolated(df, nn) if len(finite) else None),
        ("extent", insight_extent(ns_km, ew_km) if total > 1 else None),
        ("compact", insight_compact(spread)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    completeness = tot_present / tot_span if tot_span else 0
    comp_tone = "ok" if completeness >= 0.95 else "info" if completeness >= 0.85 else "warn"
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "מקלטים במאגר"},
        "prefixes": {"value": int(prefixes.size), "display": _int(prefixes.size),
                     "tone": "brand", "label": "קידומות קוד"},
        "nearest": {"value": median_nn, "display": _int(round(median_nn)), "tone": "brand",
                    "label": "מרחק חציוני למקלט הקרוב ביותר (מטרים)"},
        "completeness": {"value": completeness, "display": _pct(completeness),
                         "tone": comp_tone if tot_span else "brand",
                         "label": "מהמספרים ברצפי הקודים מופיעים במאגר"},
    }

    bad_note = (f" {_int(n_bad)} רשומות בלי שם או בלי קואורדינטות תקינות לא נכללו."
                if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} מקלטים ציבוריים בבאר שבע עם קוד מקלט ונקודת מיקום. "
                 f"הקוד בנוי מקידומת ומספר (למשל {df['name'].iloc[0]}), ומהם אפשר לראות איך המקלטים "
                 f"מתחלקים בין הקידומות, כמה צפופים הם ואיפה בעיר הם נמצאים.{bad_note}"),
        "map_note": (f"{_int(total)} המקלטים על המפה. לחצו על סמן כדי לראות את קוד המקלט; "
                     f"לחצו על אשכול כדי להתקרב."),
        "prefix_note": (f"מספר המקלטים בכל קידומת של קוד המקלט"
                        + (f"; {_int(TOP_PREFIXES)} הגדולות, והשאר מקובצות." if rest else ".")),
        "prefix_aria": f"תרשים עמודות אופקי: מספר המקלטים לפי קידומת קוד, {len(pnames)} קבוצות.",
        "prefix_caption": "מספר המקלטים בכל קידומת קוד.",
        "numbering_note": ("מספרים שמופיעים ברצף הקוד לעומת מספרים שחסרים עד המספר הגבוה ביותר "
                           "בקידומת. מספר חסר יכול להעיד על מקלט שהוסר או שלא סומן. "
                           "ההנחה היא שהמספור מתחיל ב-1."),
        "numbering_aria": (f"תרשים עמודות אופקי מוערם: מספרים קיימים וחסרים בכל אחת מ-"
                           f"{len(big)} הקידומות הגדולות."),
        "numbering_caption": "מספרים קיימים וחסרים לפי קידומת.",
        "nearest_note": (f"מרחק קו אווירי מכל מקלט למקלט הקרוב אליו, בקבוצות של {_int(BIN_M)} מטרים."),
        "nearest_aria": f"תרשים עמודות: התפלגות המרחק למקלט הקרוב ביותר, {len(edges)} קבוצות.",
        "nearest_caption": "מספר המקלטים לפי המרחק למקלט הקרוב ביותר (מטרים).",
        "spread_note": ("חציון המרחק של מקלטי כל קידומת ממרכז הקידומת — ככל שהערך נמוך, "
                        "הקידומת מרוכזת באזור קטן יותר."),
        "spread_aria": f"תרשים עמודות אופקי: רדיוס הפיזור במטרים של {len(spread)} קידומות.",
        "spread_caption": "רדיוס הפיזור (חציון, במטרים) לפי קידומת.",
        "lat_note": "מספר המקלטים בכל רצועת קו רוחב, מהצפון (למעלה) לדרום.",
        "lat_aria": f"תרשים עמודות אופקי: מקלטים לפי {len(lat_b)} רצועות קו רוחב.",
        "lat_caption": "מספר המקלטים לפי רצועת קו רוחב, מצפון לדרום.",
        "lon_note": "מספר המקלטים בכל רצועת קו אורך, ממערב (למעלה) למזרח.",
        "lon_aria": f"תרשים עמודות אופקי: מקלטים לפי {len(lon_b)} רצועות קו אורך.",
        "lon_caption": "מספר המקלטים לפי רצועת קו אורך, ממערב למזרח.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} מקלטים בבאר שבע ב-{_int(prefixes.size)} קידומות קוד, "
                           f"עם מרחק חציוני של {_int(round(median_nn))} מטרים למקלט הקרוב ביותר "
                           f"ומפה של כל נקודות המקלט."),
            "dataset_kind": "map",
            "suggested_tags": ["מקלטים", "באר שבע", "ביטחון ותשתיות", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["566c2420-1b00-4813-8a75-c6d8750c5ec8",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "b795e2e0-491e-4040-877e-f3681917f8be"],
        },
        "kpis": kpis,
        "charts": {"prefix": {"names": pnames, "values": pvals},
                   "numbering": numbering, "nearest": nearest,
                   "spread": spread_chart, "lat": lat_chart, "lon": lon_chart},
        "tables": {"prefix": t_prefix, "numbering": t_numbering, "nearest": t_nearest,
                   "spread": t_spread, "lat": t_lat, "lon": t_lon},
        "insights": insights,
        "has_numbering": bool(big),
        "has_spread": bool(spread),
        "has_nearest": bool(len(finite)),
        "labels": labels,
    }
