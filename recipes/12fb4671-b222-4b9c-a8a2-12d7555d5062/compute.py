"""תכניות בניין עיר (תב"עות) בבאר שבע — one row per boundary part ("blue line")
of a plan: plan number, status, internal serial number, perimeter, area and a
WGS84 centroid.  A plan can have several parts, so rows != plans: the page
counts plans (distinct plan numbers) and treats rows as boundary parts.

Areas of different plans overlap (a city-wide plan contains local ones), so
the page never sums areas across plans as if they were land area.

Order-independent: rows are sorted by a total key first and float sums use
math.fsum.  Plan numbers are public plan identifiers, not personal data.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
STATUS_TOP = 4              # statuses kept separate in the stacked chart (rest = "אחר")
TOP_PLANS = 10              # bars on the largest-plans chart
MAX_BANDS = 12
AREA_EDGES = [500, 1_000, 5_000, 10_000, 50_000, 100_000, 1_000_000, 10_000_000]
PART_EDGES = [1, 2, 3, 5, 10]   # 1, 2, 3, 4-5, 6-10, 11+
COMPACT_BINS = 10
FAMILY_MIN = 5              # plans a family needs for the median-area chart
GIANT_RATIO = 100           # largest plan vs median
INFORCE_HIGH = 0.9
SMALL_M2 = 1_000
SMALL_SHARE = 0.2
LEAD_SHARE = 0.3
FRAG_SHARE = 0.03
THIN_COMPACT = 0.3
THIN_SHARE = 0.1
REGNO_GAP = 1_000           # serial-number median gap to call it a pattern
PENDING_MIN = 5
R_KM = 6371.0088

FAMILIES = [
    ("mavat", "פורמט 605"),
    ("mk", "סדרת מק"),
    ("bm", "סדרת במ"),
    ("bt", "סדרת בת"),
    ("yr", "מספר/שנה"),
    ("old", "פורמט ישן"),
    ("other", "אחר"),
]
FAM_LABEL = dict(FAMILIES)
FAM_ORDER = {k: i for i, (k, _) in enumerate(FAMILIES)}
RE_MAVAT = re.compile(r"^\d{3}-\d{4,}")
RE_YEAR = re.compile(r"^\d+/\d{4}$")
RE_OLD = re.compile(r"/0\d/\d+")


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _family(p):
    if RE_MAVAT.match(p):
        return "mavat"
    if "/מק/" in p:
        return "mk"
    if "/במ/" in p:
        return "bm"
    if "/בת/" in p:
        return "bt"
    if RE_YEAR.match(p):
        return "yr"
    if RE_OLD.search(p):
        return "old"
    return "other"


def _fsum_by(df, key, col):
    return df.groupby(key, sort=True)[col].agg(lambda s: math.fsum(sorted(s)))


def _prepare(df):
    d = pd.DataFrame({
        "plan": df["Plan"].str.strip(),
        "status": df["status"].str.strip().replace("", "לא צוין"),
        "reg": pd.to_numeric(df["Taba_Numer"].str.strip(), errors="coerce"),
        "leng": pd.to_numeric(df["SHAPE_Leng"].str.strip(), errors="coerce"),
        "area": pd.to_numeric(df["SHAPE_Area"].str.strip(), errors="coerce"),
        "lat": pd.to_numeric(df["lat"].str.strip(), errors="coerce"),
        "lon": pd.to_numeric(df["lon"].str.strip(), errors="coerce"),
    })
    n_raw = len(d)
    d = d[d["plan"] != ""].copy()
    d["fam"] = d["plan"].map(_family)
    d = d.sort_values(["plan", "reg", "area", "leng", "lat", "lon", "status"],
                      kind="stable").reset_index(drop=True)
    return d, n_raw - len(d)


def _plans(d):
    """One row per plan: parts, total boundary area, status, family, serial."""
    g = d.groupby("plan", sort=True)
    p = pd.DataFrame({
        "parts": g.size(),
        "status": g["status"].first(),
        "fam": g["fam"].first(),
        "reg": g["reg"].min(),
    })
    area_ok = d[d["area"] > 0]
    p["area"] = _fsum_by(area_ok, "plan", "area").reindex(p.index)
    return p.reset_index()


def _bands(values, scale=100):
    """Bands of 0.01 degree between the 1st and 99th percentile, open-ended
    tails.  Returns [(label, count)] ascending."""
    v = np.asarray(values, dtype=float)
    lo_i = int(np.floor(np.percentile(v, 1) * scale + 1e-9))
    hi_i = int(np.floor(np.percentile(v, 99) * scale + 1e-9))
    w = max(1, math.ceil((hi_i - lo_i + 1) / MAX_BANDS))
    idx = np.floor(v * scale + 1e-9).astype(int)
    res = []
    edges = list(range(lo_i, hi_i + 1, w))
    for k, a in enumerate(edges):
        b = a + w
        first, last = k == 0, k == len(edges) - 1
        mask = (idx < b) if first else ((idx >= a) & (idx < b))
        if last:
            mask = (idx >= a) if not first else np.ones(len(v), bool)
        c = int(mask.sum())
        if first and last:
            lab = "הכול"
        elif first:
            lab = f"מתחת ל-{b / scale:.2f}"
        elif last:
            lab = f"{a / scale:.2f} ומעלה"
        else:
            lab = f"{a / scale:.2f} עד {b / scale:.2f}"
        res.append((lab, c))
    return res


def _hist(values, edges):
    """Counts for (-inf,e0], (e0,e1], ... (e_last, inf)."""
    v = np.asarray(values, dtype=float)
    b = np.searchsorted(np.asarray(edges, dtype=float), v, side="left")
    return [int((b == i).sum()) for i in range(len(edges) + 1)]


def _edge_labels(edges, unit=""):
    out = [f"עד {_int(edges[0])}{unit}"]
    for a, b in zip(edges, edges[1:]):
        out.append(f"{_int(a)} עד {_int(b)}{unit}")
    out.append(f"מעל {_int(edges[-1])}{unit}")
    return out


def _dunam(m2):
    return m2 / 1000.0


def _area_txt(m2):
    if m2 >= 1_000_000:
        return f"{m2 / 1_000_000:.1f} ק״מ רבועים"
    return f"{_int(m2)} מ״ר"


def compute(frames):
    d, n_dropped = _prepare(frames["plans"])
    pl = _plans(d)
    n_plans = len(pl)
    n_parts = len(d)
    in_force_label = "בתוקף"
    st_counts = pl["status"].value_counts()
    st_counts = st_counts.sort_index().sort_values(ascending=False, kind="stable")
    n_force = int(st_counts.get(in_force_label, 0))
    n_dep = int(st_counts.get("בהפקדה", 0))
    n_other_status = n_plans - n_force - n_dep
    force_share = n_force / n_plans if n_plans else 0.0

    area_pl = pl[pl["area"] > 0]
    areas = area_pl["area"].to_numpy()
    median_area = float(np.median(areas)) if len(areas) else 0.0

    # ---- status x family (plans)
    top_status = list(st_counts.index[:STATUS_TOP])
    has_rest_status = len(st_counts) > STATUS_TOP
    pl["st_b"] = pl["status"].where(pl["status"].isin(top_status), "אחר")
    st_series = top_status + (["אחר"] if has_rest_status else [])
    fam_tot = pl["fam"].value_counts()
    fam_keys = sorted(fam_tot.index, key=lambda k: (-int(fam_tot[k]), FAM_ORDER.get(k, 99), k))
    fam_series = []
    for s in st_series:
        fam_series.append({"name": s, "values": [int(((pl["fam"] == k) & (pl["st_b"] == s)).sum())
                                                 for k in fam_keys]})
    fam_names = [FAM_LABEL.get(k, "אחר") for k in fam_keys]
    t_family = [{"name": fam_names[i], "total": _int(fam_tot[k]),
                 "cols": [_int(s["values"][i]) for s in fam_series],
                 "share": _pct(fam_tot[k] / n_plans, 1)} for i, k in enumerate(fam_keys)]

    # ---- plan area histogram
    area_names = _edge_labels(AREA_EDGES)
    area_vals = _hist(areas, AREA_EDGES) if len(areas) else [0] * len(area_names)
    t_area = [{"name": n, "count": _int(v), "share": _pct(v / max(1, len(areas)), 1)}
              for n, v in zip(area_names, area_vals)]

    # ---- median area by family
    fam_med = []
    for k in fam_keys:
        g = area_pl[area_pl["fam"] == k]["area"].to_numpy()
        if len(g) >= FAMILY_MIN:
            fam_med.append((FAM_LABEL.get(k, "אחר"), len(g), float(np.median(g))))
    fam_med.sort(key=lambda r: (-r[2], r[0]))
    famarea = {"names": [r[0] for r in fam_med], "values": [round(r[2], 1) for r in fam_med]}
    t_famarea = [{"name": r[0], "count": _int(r[1]), "median": _int(r[2])} for r in fam_med]

    # ---- largest plans
    big = area_pl.sort_values(["area", "plan"], ascending=[False, True], kind="stable").head(TOP_PLANS)
    top = {"names": list(big["plan"]),
           "values": [round(float(a) / 1_000_000, 2) for a in big["area"]],
           "status": list(big["status"])}
    t_top = [{"name": r.plan, "status": r.status, "area": f"{r.area / 1_000_000:.2f}",
              "parts": _int(r.parts)} for r in big.itertuples()]

    # ---- parts per plan
    pnames = ["קטע אחד", "שני קטעים", "שלושה קטעים", "ארבעה עד חמישה", "שישה עד עשרה", "יותר מעשרה"]
    pv = _hist(pl["parts"].to_numpy(), PART_EDGES)[:len(pnames)]
    # _hist buckets: <=1, 2, 3, 4-5, 6-10, >10  (edges are inclusive upper bounds)
    parts_chart = {"names": pnames, "values": pv}
    t_parts = [{"name": n, "count": _int(v), "share": _pct(v / n_plans, 1)} for n, v in zip(pnames, pv)]
    multi = int((pl["parts"] > 1).sum())
    top_parts = pl.sort_values(["parts", "plan"], ascending=[False, True], kind="stable").iloc[0]

    # ---- compactness of parts
    dd = d[(d["area"] > 0) & (d["leng"] > 0)]
    comp = 4 * math.pi * dd["area"].to_numpy() / dd["leng"].to_numpy() ** 2
    comp = np.clip(comp, 0, 0.9999)
    cb = np.floor(comp * COMPACT_BINS).astype(int)
    cn = [f"{i / COMPACT_BINS:.1f} עד {(i + 1) / COMPACT_BINS:.1f}" for i in range(COMPACT_BINS)]
    cv = [int((cb == i).sum()) for i in range(COMPACT_BINS)]
    compact_chart = {"names": cn, "values": cv}
    t_compact = [{"name": n, "count": _int(v), "share": _pct(v / max(1, len(comp)), 1)}
                 for n, v in zip(cn, cv)]
    thin_share = float((comp < THIN_COMPACT).mean()) if len(comp) else 0.0

    # ---- serial-number bands (plans, stacked in force / other)
    regs = pl[pl["reg"].notna()].copy()
    regs["band"] = (regs["reg"] // 1000).astype(int)
    b_lo, b_hi = int(regs["band"].min()), int(regs["band"].max())
    bw = max(1, math.ceil((b_hi - b_lo + 1) / MAX_BANDS * 1.0)) if (b_hi - b_lo + 1) > 20 else 1
    bands = list(range(b_lo, b_hi + 1, bw))
    reg_names, reg_force, reg_rest = [], [], []
    for a in bands:
        g = regs[(regs["band"] >= a) & (regs["band"] < a + bw)]
        reg_names.append(f"{_int(a * 1000)} עד {_int((a + bw) * 1000 - 1)}")
        f = int((g["status"] == in_force_label).sum())
        reg_force.append(f)
        reg_rest.append(int(len(g)) - f)
    regno = {"names": reg_names, "force": reg_force, "rest": reg_rest}
    t_regno = [{"name": n, "force": _int(f), "rest": _int(r)}
               for n, f, r in zip(reg_names, reg_force, reg_rest)]

    # ---- geography (parts with valid centroids)
    geo = d[d["lat"].between(*LAT_RANGE) & d["lon"].between(*LON_RANGE)]
    lat_b = _bands(geo["lat"].to_numpy())[::-1] if len(geo) else []
    lon_b = _bands(geo["lon"].to_numpy()) if len(geo) else []
    lat_chart = {"names": [a for a, _ in lat_b], "values": [c for _, c in lat_b]}
    lon_chart = {"names": [a for a, _ in lon_b], "values": [c for _, c in lon_b]}
    t_lat = [{"name": a, "count": _int(c), "share": _pct(c / len(geo), 1)} for a, c in lat_b]
    t_lon = [{"name": a, "count": _int(c), "share": _pct(c / len(geo), 1)} for a, c in lon_b]

    # ---------------------------------------------------------------- insights
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    # status
    if n_plans:
        if n_dep or n_other_status:
            add("status", f"{_int(n_force)} מתוך {_int(n_plans)} התכניות ({_pct(force_share, 1)}) "
                f"בתוקף, ו-{_int(n_plans - n_force)} נוספות בשלבי הפקדה או סטטוס אחר.")
        else:
            add("status", f"כל {_int(n_plans)} התכניות במאגר בתוקף.")

    # family leader
    if len(fam_keys) >= 2:
        k0, k1 = fam_keys[0], fam_keys[1]
        s0 = fam_tot[k0] / n_plans
        if s0 >= LEAD_SHARE:
            add("family", f"{_pct(s0)} מהתכניות ({_int(fam_tot[k0])}) ממוספרות בתבנית \"{FAM_LABEL.get(k0, 'אחר')}\", "
                f"והבאה אחריה היא \"{FAM_LABEL.get(k1, 'אחר')}\" עם {_int(fam_tot[k1])}.")

    # where the pending plans are
    if n_dep >= PENDING_MIN:
        dep = pl[pl["status"] == "בהפקדה"]["fam"].value_counts()
        dep = dep.sort_index().sort_values(ascending=False, kind="stable")
        k = dep.index[0]
        add("pending_family", f"מבין {_int(n_dep)} התכניות בהפקדה, {_int(dep.iloc[0])} "
            f"({_pct(dep.iloc[0] / n_dep)}) הן בתבנית \"{FAM_LABEL.get(k, 'אחר')}\", שבה "
            f"{_pct(dep.iloc[0] / fam_tot[k], 1)} מהתכניות עדיין בהפקדה.")

    # size
    if len(areas) >= 20:
        p90 = float(np.percentile(areas, 90))
        add("size", f"חצי מהתכניות קטנות מ-{_int(median_area)} מ״ר, ואילו 10% הגדולות ביותר "
            f"עוברות {_int(p90)} מ״ר — התפלגות מוטה מאוד כלפי תכניות קטנות.")
        small = float((areas < SMALL_M2).mean())
        if small >= SMALL_SHARE:
            add("small", f"{_pct(small)} מהתכניות ({_int((areas < SMALL_M2).sum())}) משתרעות על פחות מ-{_int(SMALL_M2)} "
                f"מ״ר — כלומר מגרש אחד או כמה מגרשים בודדים.")
        g0 = big.iloc[0]
        if median_area > 0 and g0["area"] >= GIANT_RATIO * median_area:
            add("giant", f"התכנית {g0['plan']} היא הגדולה ביותר, עם {g0['area'] / 1_000_000:.1f} ק״מ רבועים — "
                f"פי {_int(g0['area'] / median_area)} מהתכנית החציונית. תכניות כאלה מקיפות שטחים רחבים "
                f"וחופפות לתכניות מקומיות, ולכן אין לסכם את השטחים.")

    # fragmentation
    if n_plans and multi / n_plans >= FRAG_SHARE:
        add("fragmented", f"{_int(multi)} תכניות ({_pct(multi / n_plans, 1)}) מורכבות מכמה קטעי גבול נפרדים; "
            f"הרבה ביותר בתכנית {top_parts['plan']}, עם {_int(top_parts['parts'])} קטעים.")

    # thin / winding shapes
    if len(comp) >= 20 and thin_share >= THIN_SHARE:
        add("compact", f"{_pct(thin_share)} מקטעי הגבול הם מוארכים או מפותלים (מדד קומפקטיות מתחת ל-"
            f"{THIN_COMPACT:.1f}, כאשר 1 הוא עיגול מושלם) — אופייני לדרכים ולרצועות תשתית.")

    # serial number pattern
    if n_force and n_dep >= PENDING_MIN:
        m_f = float(regs[regs["status"] == in_force_label]["reg"].median())
        m_d = float(regs[regs["status"] == "בהפקדה"]["reg"].median())
        if m_d - m_f >= REGNO_GAP:
            add("regno", f"מספר התכנית הפנימי החציוני בתכניות בהפקדה הוא {_int(m_d)}, לעומת {_int(m_f)} "
                f"בתכניות בתוקף — ככל הנראה תכניות חדשות נרשמות במספרים גבוהים יותר.")

    # geographic core
    if len(geo) >= 20:
        la = np.percentile(geo["lat"], [5, 95])
        lo = np.percentile(geo["lon"], [5, 95])
        k = math.cos(math.radians(float(geo["lat"].median())))
        ns = (la[1] - la[0]) * math.radians(1) * R_KM
        ew = (lo[1] - lo[0]) * math.radians(1) * R_KM * k
        add("extent", f"90% מקטעי הגבול נמצאים בתוך מלבן של {ns:.1f} ק״מ מצפון לדרום ו-{ew:.1f} ק״מ "
            f"ממערב למזרח; הקטעים הרחוקים יותר הם בעיקר בשולי שטח השיפוט.")

    # ---------------------------------------------------------------- kpis
    kpis = {
        "plans": {"value": n_plans, "display": _int(n_plans), "tone": "brand",
                  "label": "תכניות במאגר"},
        "inforce": {"value": force_share, "display": _pct(force_share, 1),
                    "tone": "ok" if force_share >= INFORCE_HIGH else "info",
                    "label": "מהתכניות בתוקף"},
        "deposit": {"value": n_dep, "display": _int(n_dep),
                    "tone": "info" if n_dep else "brand", "label": "תכניות בהפקדה"},
        "median_area": {"value": median_area, "display": _int(median_area), "tone": "brand",
                        "label": "שטח חציוני של תכנית (מ״ר)"},
    }

    bad_note = (f" {_int(n_dropped)} רשומות בלי מספר תכנית לא נכללו." if n_dropped else "")
    labels = {
        "lede": (f"הקווים הכחולים של {_int(n_plans)} תכניות בניין עיר בבאר שבע, ב-{_int(n_parts)} קטעי גבול: "
                 f"מספר התכנית, הסטטוס שלה, שטח והיקף הגבול ומיקום מרכזו. תכנית אחת יכולה לכלול כמה קטעים. "
                 f"המאגר מכיל את רוב התכניות אך לא את כולן.{bad_note}"),
        "map_note": (f"{_int(n_parts)} קטעי הגבול על המפה, כל קטע בנקודת המרכז שלו. לחצו על סמן כדי לראות את מספר "
                     f"התכנית והסטטוס; לחצו על אשכול כדי להתקרב."),
        "family_note": ("מספר התכניות בכל תבנית ממוספרת, לפי הסטטוס. התבנית נקבעת לפי מבנה מספר התכנית, "
                        "ולכן היא מסמנת סדרת מספור ולא סוג תכנית רשמי."),
        "family_aria": f"תרשים עמודות אופקי מוערם: תכניות לפי תבנית מספור וסטטוס, {len(fam_names)} תבניות.",
        "family_caption": "מספר התכניות לפי תבנית מספור וסטטוס.",
        "area_note": ("מספר התכניות לפי השטח הכולל של קווי הגבול שלהן, במטרים רבועים. "
                      "תכנית עם כמה קטעים נספרת פעם אחת, בסכום השטחים של קטעיה."),
        "area_aria": f"תרשים עמודות אופקי: התפלגות שטח התכניות, {len(area_names)} קבוצות.",
        "area_caption": "מספר התכניות לפי שטח (מ״ר).",
        "famarea_note": (f"שטח חציוני של תכנית בכל תבנית מספור (מ״ר), בתבניות עם לפחות {_int(FAMILY_MIN)} תכניות."),
        "famarea_aria": f"תרשים עמודות אופקי: שטח חציוני לפי תבנית מספור, {len(fam_med)} תבניות.",
        "famarea_caption": "שטח חציוני של תכנית (מ״ר) ומספר התכניות בכל תבנית.",
        "top_note": ("התכניות עם שטח הגבול הגדול ביותר, בקילומטרים רבועים. התכניות הגדולות חופפות "
                     "לתכניות מקומיות, ולכן אין לסכם את השטחים."),
        "top_aria": f"תרשים עמודות אופקי: {len(top['names'])} התכניות הגדולות ביותר לפי שטח.",
        "top_caption": "התכניות הגדולות ביותר: שטח (ק״מ רבועים), סטטוס ומספר קטעים.",
        "parts_note": "כמה קטעי גבול נפרדים יש לכל תכנית.",
        "parts_aria": f"תרשים עמודות אופקי: תכניות לפי מספר קטעי גבול, {len(pnames)} קבוצות.",
        "parts_caption": "מספר התכניות לפי מספר קטעי הגבול.",
        "compact_note": ("מדד הקומפקטיות של כל קטע גבול: ארבע פעמים π כפול השטח, חלקי ריבוע ההיקף. "
                         "ערך קרוב ל-1 הוא צורה עגולה; ערך נמוך הוא צורה ארוכה, צרה או מפותלת."),
        "compact_aria": f"תרשים עמודות אופקי: קטעי גבול לפי מדד קומפקטיות, {len(cn)} קבוצות.",
        "compact_caption": "מספר קטעי הגבול לפי מדד קומפקטיות.",
        "regno_note": ("מספר התכניות לפי טווח המספר הפנימי שלהן במערכת (לא תאריך). "
                       "מספרים גבוהים נוטים להיות של תכניות מאוחרות יותר."),
        "regno_aria": f"תרשים עמודות אופקי מוערם: תכניות בתוקף ואחרות לפי {len(reg_names)} טווחי מספר פנימי.",
        "regno_caption": "מספר התכניות בתוקף ואחרות לפי טווח המספר הפנימי.",
        "lat_note": "קטעי גבול לפי רצועת קו רוחב, מהצפון (למעלה) לדרום. הקצוות כוללים את כל מה שמעבר.",
        "lat_aria": f"תרשים עמודות אופקי: קטעי גבול לפי {len(lat_b)} רצועות קו רוחב.",
        "lat_caption": "מספר קטעי הגבול לפי רצועת קו רוחב, מצפון לדרום.",
        "lon_note": "קטעי גבול לפי רצועת קו אורך, ממערב (למעלה) למזרח. הקצוות כוללים את כל מה שמעבר.",
        "lon_aria": f"תרשים עמודות אופקי: קטעי גבול לפי {len(lon_b)} רצועות קו אורך.",
        "lon_caption": "מספר קטעי הגבול לפי רצועת קו אורך, ממערב למזרח.",
    }

    return {
        "agent_data": {
            "summary_he": (f"קווי הגבול של {_int(n_plans)} תכניות בניין עיר בבאר שבע: "
                           f"{_pct(force_share, 1)} בתוקף ו-{_int(n_plans - n_force)} בהפקדה או בסטטוס אחר, "
                           f"עם שטח חציוני של {_int(median_area)} מ״ר ומפה של {_int(n_parts)} קטעי גבול."),
            "dataset_kind": "map",
            "suggested_tags": ["תכנון עיר", "תב״ע", "באר שבע", "קווים כחולים", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "727e865d-25b1-43ce-9dcb-af297851f87b",
                            "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "b795e2e0-491e-4040-877e-f3681917f8be"],
        },
        "kpis": kpis,
        "charts": {
            "family": {"names": fam_names, "series": fam_series},
            "area": {"names": area_names, "values": area_vals},
            "famarea": famarea,
            "top": top,
            "parts": parts_chart,
            "compact": compact_chart,
            "regno": regno,
            "lat": lat_chart,
            "lon": lon_chart,
        },
        "tables": {"family": t_family, "area": t_area, "famarea": t_famarea, "top": t_top,
                   "parts": t_parts, "compact": t_compact, "regno": t_regno,
                   "lat": t_lat, "lon": t_lon, "status_cols": st_series},
        "insights": insights,
        "has_famarea": bool(fam_med),
        "has_regno": bool(len(regs)),
        "has_geo": bool(len(geo)),
        "has_compact": bool(len(comp)),
        "labels": labels,
    }
