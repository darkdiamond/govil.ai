"""מצלמות אבטחה באר-שבע — one row per camera point: WGS84 position plus
optional free-text place name, street address, reported number of cameras at
the site and a viewing angle.  Most rows carry only coordinates, so the page
is about WHERE the points are (density grid, distance from the centre,
nearest-neighbour spacing, map) and HOW MUCH is documented (field fill rates,
place types, lens counts, angles).

The CSV, XLSX and ITM resources are twins of one table; only the CSV is read.
Order-independent: integer counts, medians and sorted aggregates only.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
LENS_RE = re.compile(r"^\s*(\d+)")
BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 6), (7, 10), (11, 20)]  # last = over 20
TOP_SITES = 10
MIN_SITE_POINTS = 2
MAX_BANDS = 16
RING_KM = 1
MAX_RINGS = 8
NN_BIN_M = 25
NN_BINS = 10
SMALL_NN_M = 50
LEAD_SHARE = 0.30
LEAD_MARGIN = 0.05
BIG_SITE_RATIO = 3
GRID_MIN_SHARE = 0.08
MIN_LENS_SITES = 10
MIN_ANGLES = 10

# (label, regex) applied in order to "location address"; first match wins.
TYPE_RULES = [
    ("צמתים", re.compile(r"צומת")),
    ("גשרים", re.compile(r"גשר")),
    ("חינוך ונוער", re.compile(r"בית ספר|מקיף|מעון|תיכון|אולפנה|נוער|גנון")),
    ("פארקים, כיכרות ומגרשים",
     re.compile(r"פארק|כיכר|מזרק|אמפי|שצ\"פ|מגרש|סקייט|איצטדיון|(?<!\S)גן(?!\S)|רחבת")),
    ("מוסדות עירייה וחירום",
     re.compile(r"עירי|מחלקת|לשכה|מחסן|אגף|מכון|שירות|קצין|שיטור|חרום|חרום|אפסנאות")),
    ("מרכזי קהילה ותרבות", re.compile(r"מתנ\"ס|מרכז|מוזיאון|תאטרון|היכל|שוק|בית ")),
]
OTHER_TYPE = "אחר"
NO_NAME = "ללא שם או כתובת"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _prepare(df):
    out = df.copy()
    for c in ("location", "address", "amount", "angle"):
        out[c] = out[c].str.strip()
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    xf = pd.to_numeric(out["X"].str.strip(), errors="coerce").fillna(0)
    yf = pd.to_numeric(out["Y"].str.strip(), errors="coerce").fillna(0)
    out["itm_missing"] = (xf == 0) & (yf == 0)
    out["lens"] = pd.to_numeric(out["amount"].str.extract(LENS_RE)[0], errors="coerce")
    out["angf"] = pd.to_numeric(out["angle"], errors="coerce")
    out["has_loc"] = out["location"] != ""
    out["has_addr"] = out["address"] != ""
    out["named"] = out["has_loc"] | out["has_addr"]

    def kind(row):
        text = f"{row['location']} {row['address']}".strip()
        if not text:
            return NO_NAME
        for label, rx in TYPE_RULES:
            if rx.search(text):
                return label
        return OTHER_TYPE

    out["kind"] = [kind(r) for r in out[["location", "address"]].to_dict("records")]
    out = out.sort_values(["latf", "lonf", "location", "address", "amount", "angle"],
                          kind="stable")
    return out.reset_index(drop=True), n_bad


def _bands(values, scale=100):
    """Equal-width bands on an index axis; returns (lo_index, width, count)."""
    idx = np.floor(np.asarray(values) * scale + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    return idx, lo, hi, w


def _label(a, w, scale=100):
    return f"{a / scale:.2f}"


def _nearest_m(x, y):
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


def insight_names(df):
    total = len(df)
    named = int(df["named"].sum())
    if not total:
        return None
    return (f"ל-{_int(named)} מתוך {_int(total)} נקודות ({_pct(named / total, 1)}) יש שם מיקום או כתובת; "
            f"{_int(total - named)} נקודות מופיעות במאגר עם קואורדינטות בלבד.")


def insight_types(kinds):
    if len(kinds) < 2:
        return None
    tot = sum(v for _, v in kinds)
    (a, av), (b, bv) = kinds[0], kinds[1]
    if av / tot < LEAD_SHARE or (av - bv) / tot < LEAD_MARGIN:
        return None
    return (f"מבין הנקודות עם שם או כתובת, הסוג הנפוץ ביותר הוא ״{a}״: {_int(av)} נקודות "
            f"({_pct(av / tot, 1)}), לעומת {_int(bv)} ב״{b}״.")


def insight_sites(sites):
    if not sites or sites[0][1] < 3:
        return None
    name, n = sites[0]
    ties = sum(1 for _, v in sites if v == n)
    multi = sum(1 for _, v in sites if v >= MIN_SITE_POINTS)
    lead = (f"המספר הגבוה ביותר של נקודות תחת אותו שם הוא {_int(n)}, ב-{_int(ties)} שמות "
            f"(למשל ״{name}״)" if ties > 1 else
            f"באתר ״{name}״ יש {_int(n)} נקודות מצלמה נפרדות, הכי הרבה מכל שם במאגר")
    return f"{lead}; בסך הכול {_int(multi)} שמות מופיעים ביותר מנקודה אחת."


def insight_lenses(df):
    s = df["lens"].dropna()
    if len(s) < MIN_LENS_SITES:
        return None
    med = float(s.median())
    mx = int(s.max())
    top = df[df["lens"] == mx]
    tail = ""
    if len(top) == 1 and top["location"].iloc[0] and mx >= BIG_SITE_RATIO * max(med, 1):
        tail = f", והגדול ביותר הוא ״{top['location'].iloc[0]}״ עם {_int(mx)}"
    return (f"ב-{_int(len(s))} נקודות מדווח מספר המצלמות באתר, בסך {_int(s.sum())} מצלמות; "
            f"החציון הוא {med:g} מצלמות לנקודה{tail}.")


def insight_angle(df):
    s = df["angf"].dropna()
    if len(s) < MIN_ANGLES:
        return None
    vc = s.astype(int).value_counts()
    vc = vc.sort_index().sort_values(ascending=False, kind="stable")
    v, n = int(vc.index[0]), int(vc.iloc[0])
    if n / len(s) < 0.5:
        return None
    return (f"בנקודות שבהן מצוינת זווית ({_int(len(s))}), הערך {v} מופיע ב-{_int(n)} "
            f"({_pct(n / len(s), 1)}); {_int(len(vc) - 1)} ערכים נוספים מופיעים בשאר.")


def insight_center(dist_km, within, total):
    if total < 20:
        return None
    share = within / total
    return (f"{_pct(share, 1)} מהנקודות ({_int(within)}) נמצאות בטווח {_int(RING_KM)} ק״מ "
            f"ממרכז הפריסה; הנקודה הרחוקה ביותר במרחק {float(np.max(dist_km)):.1f} ק״מ ממנו.")


def insight_grid(top_cell, total, cell_km):
    n, lat_l, lon_l = top_cell
    if n / total < GRID_MIN_SHARE:
        return None
    return (f"תא הצפיפות הגבוה ביותר (קו רוחב {lat_l}, קו אורך {lon_l}) מכיל {_int(n)} נקודות, "
            f"{_pct(n / total, 1)} מכלל הנקודות.")


def insight_nearest(nn):
    near = float((nn <= SMALL_NN_M).mean())
    return (f"המרחק החציוני בין נקודה לנקודה הקרובה אליה הוא {_int(round(float(np.median(nn))))} "
            f"מטרים; ל-{_pct(near)} מהנקודות יש נקודה אחרת במרחק של עד {_int(SMALL_NN_M)} מטרים.")


def insight_colocated(df):
    g = df.groupby(["lat", "lon"], sort=True).size()
    n_pts = int(g[g > 1].sum())
    if not n_pts:
        return None
    return (f"{_int(n_pts)} נקודות חולקות קואורדינטות זהות עם נקודה אחרת "
            f"({_int(int((g > 1).sum()))} מיקומים), כלומר כמה מצלמות רשומות באותו מקום בדיוק.")


def insight_itm(df):
    n = int(df["itm_missing"].sum())
    if not n:
        return None
    return (f"ב-{_int(n)} נקודות ({_pct(n / len(df), 1)}) הקואורדינטות בשדות X ו-Y הן אפס, "
            f"בעוד שקו הרוחב וקו האורך תקינים; המפה והניתוח משתמשים בקווי הרוחב והאורך.")


def compute(frames):
    df, n_bad = _prepare(frames["cameras"])
    total = len(df)
    named = int(df["named"].sum())

    # --- fill rates
    fields = [("שם מיקום", int(df["has_loc"].sum())), ("כתובת", int(df["has_addr"].sum())),
              ("מספר מצלמות", int(df["lens"].notna().sum())),
              ("זווית", int(df["angf"].notna().sum()))]
    fields_chart = {"names": [n for n, _ in fields], "values": [v for _, v in fields],
                    "pct": [round(v / total * 100, 1) for _, v in fields]}
    t_fields = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in fields]

    # --- place types
    kc = df["kind"].value_counts()
    kinds_all = sorted(kc.items(), key=lambda kv: (-kv[1], kv[0]))
    kinds_named = [(k, int(v)) for k, v in kinds_all if k != NO_NAME]
    # "other" / unnamed go last on the chart regardless of size
    order = [kv for kv in kinds_all if kv[0] not in (OTHER_TYPE, NO_NAME)]
    order += [kv for kv in kinds_all if kv[0] == OTHER_TYPE]
    order += [kv for kv in kinds_all if kv[0] == NO_NAME]
    types_chart = {"names": [k for k, _ in order], "values": [int(v) for _, v in order]}
    t_types = [{"name": k, "count": _int(v), "share": _pct(v / total, 1)} for k, v in order]

    # --- repeated named sites
    sv = df[df["has_loc"]].groupby("location").size()
    sites = sorted(((k, int(v)) for k, v in sv.items()), key=lambda kv: (-kv[1], kv[0]))
    top_sites = [s for s in sites if s[1] >= MIN_SITE_POINTS][:TOP_SITES]
    sites_chart = {"names": [k for k, _ in top_sites], "values": [v for _, v in top_sites]}
    t_sites = [{"name": k, "count": _int(v)} for k, v in top_sites]

    # --- lens distribution
    lens = df["lens"].dropna().astype(int)
    lb_names, lb_vals = [], []
    for lo, hi in BUCKETS:
        lb_names.append(str(lo) if lo == hi else f"{lo}-{hi}")
        lb_vals.append(int(((lens >= lo) & (lens <= hi)).sum()))
    over = BUCKETS[-1][1]
    lb_names.append(f"\u200e{over + 1}+")
    lb_vals.append(int((lens > over).sum()))
    lens_chart = {"names": lb_names, "values": lb_vals}
    t_lens = [{"name": n, "count": _int(v), "share": _pct(v / len(lens), 1)}
              for n, v in zip(lb_names, lb_vals)] if len(lens) else []
    lens_total = int(lens.sum())

    # --- angles
    ang = df["angf"].dropna().astype(int)
    avc = sorted(((int(k), int(v)) for k, v in ang.value_counts().items()), key=lambda kv: kv[0])
    angle_chart = {"names": [f"{k}°" for k, _ in avc], "values": [v for _, v in avc]}
    t_angle = [{"name": f"{k}°", "count": _int(v), "share": _pct(v / len(ang), 1)} for k, v in avc]

    # --- geometry (km, equirectangular around the data's own mid-latitude)
    lat0 = (df["latf"].min() + df["latf"].max()) / 2
    k = math.cos(math.radians(lat0))
    x = np.radians(df["lonf"].to_numpy()) * R_KM * k
    y = np.radians(df["latf"].to_numpy()) * R_KM
    cx, cy = float(np.median(x)), float(np.median(y))
    dist = np.hypot(x - cx, y - cy)
    nn = _nearest_m(x, y)
    finite = nn[np.isfinite(nn)]
    median_nn = float(np.median(finite)) if len(finite) else 0.0

    # radial rings
    rb = np.minimum((dist // RING_KM).astype(int), MAX_RINGS - 1)
    rcounts = [int((rb == i).sum()) for i in range(MAX_RINGS)]
    last = max([i for i, c in enumerate(rcounts) if c] or [0])
    rcounts = rcounts[: last + 1]
    rnames = [f"עד {(i + 1) * RING_KM}" for i in range(len(rcounts))]
    if last == MAX_RINGS - 1:
        rnames[-1] = f"מעל {(MAX_RINGS - 1) * RING_KM}"
    radial_chart = {"names": rnames, "values": rcounts}
    t_radial = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in zip(rnames, rcounts)]
    within = int((dist < RING_KM).sum())

    # nearest-neighbour histogram
    if len(finite):
        nb = np.minimum((finite // NN_BIN_M).astype(int), NN_BINS - 1)
        ncounts = [int((nb == i).sum()) for i in range(NN_BINS)]
        nnames = [f"עד {(i + 1) * NN_BIN_M}" for i in range(NN_BINS - 1)]
        nnames.append(f"מעל {(NN_BINS - 1) * NN_BIN_M}")
    else:
        ncounts, nnames = [], []
    nearest_chart = {"names": nnames, "values": ncounts}
    t_nearest = [{"name": n, "count": _int(v), "share": _pct(v / len(finite), 1)}
                 for n, v in zip(nnames, ncounts)] if len(finite) else []

    # density grid
    ila, la_lo, la_hi, la_w = _bands(df["latf"].to_numpy())
    ilo, lo_lo, lo_hi, lo_w = _bands(df["lonf"].to_numpy())
    la_starts = list(range(la_lo, la_hi + 1, la_w))
    lo_starts = list(range(lo_lo, lo_hi + 1, lo_w))
    ya = (ila - la_lo) // la_w
    xa = (ilo - lo_lo) // lo_w
    cells = {}
    for xi, yi in zip(xa.tolist(), ya.tolist()):
        cells[(xi, yi)] = cells.get((xi, yi), 0) + 1
    heat = sorted([[xi, yi, c] for (xi, yi), c in cells.items()])
    best = sorted(cells.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][0]))[0]
    top_cell = (best[1], _label(la_starts[best[0][1]], la_w), _label(lo_starts[best[0][0]], lo_w))
    grid_chart = {"x": [_label(a, lo_w) for a in lo_starts],
                  "y": [_label(a, la_w) for a in la_starts],
                  "data": heat, "max": max(c for _, _, c in heat)}
    cell_km = la_w * 0.01 * math.radians(1) * R_KM

    ns_km = float((df["latf"].max() - df["latf"].min()) * math.radians(1) * R_KM)
    ew_km = float(x.max() - x.min())

    rules = [
        ("names", insight_names(df)),
        ("types", insight_types(kinds_named)),
        ("sites", insight_sites(sites)),
        ("lenses", insight_lenses(df)),
        ("angle", insight_angle(df)),
        ("center", insight_center(dist, within, total)),
        ("grid", insight_grid(top_cell, total, cell_km)),
        ("nearest", insight_nearest(finite) if len(finite) else None),
        ("colocated", insight_colocated(df)),
        ("itm", insight_itm(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    named_share = named / total
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "נקודות מצלמה במאגר"},
        "named": {"value": named_share, "display": _pct(named_share, 1),
                  "tone": "ok" if named_share >= 0.75 else "info" if named_share >= 0.5 else "warn",
                  "label": "מהנקודות עם שם או כתובת"},
        "lenses": {"value": lens_total, "display": _int(lens_total), "tone": "brand",
                   "label": f"מצלמות שדווחו ב-{_int(len(lens))} נקודות"},
        "nearest": {"value": median_nn, "display": _int(round(median_nn)), "tone": "brand",
                    "label": "מרחק חציוני לנקודה הקרובה ביותר (מטרים)"},
    }

    bad_note = (f" {_int(n_bad)} רשומות בלי קואורדינטות תקינות לא נכללו." if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} נקודות מצלמת אבטחה של עיריית באר שבע, כל אחת עם קו רוחב וקו אורך. "
                 f"רק {_pct(named_share, 1)} מהן מתועדות בשם או בכתובת, ולכן העמוד מתמקד בפריסה "
                 f"במרחב: איפה הנקודות צפופות, כמה רחוק הן ממרכז הפריסה, ומה ידוע על האתרים "
                 f"שבהם יש תיעוד.{bad_note}"),
        "map_note": (f"{_int(total)} הנקודות על המפה. לחצו על סמן כדי לראות את הפרטים הידועים עליו; "
                     f"לחצו על אשכול כדי להתקרב."),
        "fields_note": "אחוז הנקודות שבהן כל שדה תיאורי מלא. שדות ריקים אינם שגיאה: הם פשוט לא תועדו.",
        "fields_aria": "תרשים עמודות אופקי: אחוז הנקודות עם שם, כתובת, מספר מצלמות וזווית.",
        "fields_caption": "מספר ואחוז הנקודות שבהן השדה מלא.",
        "types_note": ("סיווג הנקודות לפי מילות מפתח בשם המיקום או בכתובת (צומת, גשר, בית ספר, "
                       "פארק ועוד). נקודה בלי שם נספרת בנפרד, ושמות שלא מתאימים לאף סוג נספרים כ״אחר״."),
        "types_aria": f"תרשים עמודות אופקי: מספר הנקודות לפי סוג מקום, {len(order)} קבוצות.",
        "types_caption": "מספר הנקודות לפי סוג מקום.",
        "sites_note": "שמות מיקום שמופיעים ביותר מנקודה אחת — אתרים עם כמה מצלמות נפרדות.",
        "sites_aria": f"תרשים עמודות אופקי: {len(top_sites)} האתרים עם הכי הרבה נקודות מצלמה.",
        "sites_caption": "האתרים עם מספר הנקודות הגבוה ביותר.",
        "lenses_note": (f"בנקודות שבהן מדווח מספר המצלמות באתר ({_int(len(lens))} נקודות). "
                        f"ערכים כמו ״3 מצל׳׳ נקראים כמספר 3."),
        "lenses_aria": f"תרשים עמודות: התפלגות מספר המצלמות באתר, {len(lb_names)} קבוצות.",
        "lenses_caption": "מספר הנקודות לפי מספר המצלמות שדווח באתר.",
        "angle_note": f"ערכי הזווית בשדה angle, בנקודות שבהן הוא מלא ({_int(len(ang))} נקודות).",
        "angle_aria": f"תרשים עמודות: התפלגות הזוויות, {len(avc)} ערכים.",
        "angle_caption": "מספר הנקודות לפי ערך הזווית.",
        "grid_note": (f"צפיפות הנקודות בתאי רשת לפי קו רוחב (למעלה צפון) וקו אורך (שמאל מערב). "
                      f"הצבע מציין את מספר הנקודות בתא; התא מכסה כ-{cell_km:.1f} ק״מ בצד."),
        "grid_aria": "מפת חום: מספר הנקודות בתאי רשת של קו רוחב וקו אורך.",
        "radial_note": (f"מרחק קו אווירי מכל נקודה למרכז הפריסה (חציון קווי הרוחב והאורך), "
                        f"בטבעות של {_int(RING_KM)} ק״מ. הפריסה משתרעת על {ns_km:.1f} ק״מ מצפון לדרום "
                        f"ועל {ew_km:.1f} ק״מ ממערב למזרח."),
        "radial_aria": f"תרשים עמודות: מספר הנקודות לפי מרחק מהמרכז בק״מ, {len(rnames)} טבעות.",
        "radial_caption": "מספר הנקודות לפי מרחק מהמרכז (ק״מ).",
        "nearest_note": f"מרחק קו אווירי מכל נקודה לנקודה הקרובה אליה, בקבוצות של {_int(NN_BIN_M)} מטרים.",
        "nearest_aria": f"תרשים עמודות: התפלגות המרחק לנקודה הקרובה ביותר, {len(nnames)} קבוצות.",
        "nearest_caption": "מספר הנקודות לפי המרחק לנקודה הקרובה ביותר (מטרים).",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} נקודות מצלמת אבטחה בבאר שבע; {_pct(named_share, 1)} מהן עם "
                           f"שם או כתובת, ו-{_pct(within / total, 1)} בטווח {_int(RING_KM)} ק״מ "
                           f"ממרכז הפריסה. מפה, צפיפות לפי אזור ופירוט האתרים המתועדים."),
            "dataset_kind": "map",
            "suggested_tags": ["מצלמות אבטחה", "באר שבע", "ביטחון ותשתיות", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["566c2420-1b00-4813-8a75-c6d8750c5ec8",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "023b7883-3599-4cb7-adef-1a76ea051cf0",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "3c6d4061-41bf-4403-82e9-c8fae5df04dd"],
        },
        "kpis": kpis,
        "charts": {"fields": fields_chart, "types": types_chart, "sites": sites_chart,
                   "lenses": lens_chart, "angle": angle_chart, "grid": grid_chart,
                   "radial": radial_chart, "nearest": nearest_chart},
        "tables": {"fields": t_fields, "types": t_types, "sites": t_sites, "lenses": t_lens,
                   "angle": t_angle, "radial": t_radial, "nearest": t_nearest},
        "insights": insights,
        "has_sites": bool(top_sites),
        "has_lenses": bool(len(lens)),
        "has_angle": bool(len(ang)),
        "has_nearest": bool(len(finite)),
        "labels": labels,
    }
