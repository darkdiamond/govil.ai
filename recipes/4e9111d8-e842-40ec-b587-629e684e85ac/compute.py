"""אנטנות סלולריות בהקמה — applications for construction permits of cellular
transmission sites (Cellcom, Pelephone, PHI), one row per application.

The file is a rolling list: it holds roughly the last year of submissions and
older rows drop out, so the first and last calendar periods are usually cut.
An edge period counts as partial when the data starts more than
EDGE_SLACK_DAYS after the period's first day (or ends more than that before
its last day); trend rules use full periods only and say so.

Each operator describes its site types in its own vocabulary ("עוקץ" vs
"עוקצים", "פנימי" vs "פריסה פנימית" ...). The raw labels are charted as-is
(sunburst) and also folded into a handful of families by keyword, with
unknown labels kept under their own name.

Operators are companies and are named. The page never lists individual
applications, reference numbers or site codes; site codes are only used to
count distinct sites, re-filed sites and mobile (COW) units.
"""
import pandas as pd

OTHER = "אחר"
TOP_JURIS = 15
EDGE_SLACK_DAYS = 3
TREND_MIN_MONTHS = 4      # full months needed for the trend rule
TREND_THRESHOLD = 0.15    # ±15% between halves → rise / fall
LEAD_GAP = 0.05           # leader ahead of #2 by ≥5% of all applications
MIX_SHIFT_PP = 0.15       # leader's share moved ≥15 points between full quarters
FAMILY_GAP_PP = 0.30      # family share gap between operators worth stating
FAMILY_MIN_OP = 20        # operators with fewer applications are not compared
REFILE_MIN = 3
COW_MIN = 3
COW_PREFIX = "COW"
BAND_KM = 25
NO_JURIS = ("חסר מעמד", "שטח ללא שיפוט")
ITM_X = (100_000, 300_000)
ITM_Y = (350_000, 800_000)
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas dayofweek
WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]  # Sunday first
# Families in display order: (name, keyword test on the raw label).
FAMILIES = [
    ("פנימי", lambda s: "פנימי" in s),
    ("על גג", lambda s: "גג" in s),
    ("עוקצים", lambda s: "עוקץ" in s or "עוקצים" in s),
    ("קרקעי", lambda s: "קרקעי" in s),
    ("תורן על מבנה", lambda s: "מבנה" in s),
]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _month_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _date_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _operator(name):
    return "PHI (הוט ופרטנר)" if name.startswith("PHI") else name


def _family(label):
    for name, test in FAMILIES:
        if test(label):
            return name
    return label or "לא צוין"


def _prepare(df):
    out = pd.DataFrame({
        "date": pd.to_datetime(df["תאריך הגשת הבקשה"].str.strip().str[:10],
                               format="%Y-%m-%d", errors="coerce"),
        "operator": df["חברה"].str.strip().map(_operator).replace("", "לא צוין"),
        "permit": df["סוג  היתר"].str.strip().replace("", "לא צוין"),
        "site": df["מספר האתר"].str.strip().str.upper(),
        "type": df["סוג המוקד"].str.strip().str.replace(r"\s+", " ", regex=True).replace("", "לא צוין"),
        "juris": (df["תחום שיפוט"].str.strip().str.replace("-", " ", regex=False)
                  .str.replace(r"\s+", " ", regex=True).replace("", "לא צוין")),
        "x": pd.to_numeric(df["X_ITM"].str.replace(",", "", regex=False), errors="coerce"),
        "y": pd.to_numeric(df["Y_ITM"].str.replace(",", "", regex=False), errors="coerce"),
    })
    out["family"] = out["type"].map(_family)
    out["valid_xy"] = out["x"].between(*ITM_X) & out["y"].between(*ITM_Y)
    return out


def _periods(dates, freq):
    """All periods spanned by the data, and which of them are complete."""
    lo, hi = dates.min(), dates.max()
    ps = list(pd.period_range(lo.to_period(freq), hi.to_period(freq), freq=freq))
    slack = pd.Timedelta(days=EDGE_SLACK_DAYS)
    full = []
    for p in ps:
        start, end = p.start_time.normalize(), p.end_time.normalize()
        full.append(not ((p == ps[0] and lo - start > slack) or (p == ps[-1] and end - hi > slack)))
    return ps, full


# ----------------------------------------------------------------- insights

def insight_leader(df, ops):
    n = len(df)
    lead, v = ops.index[0], int(ops.iloc[0])
    if len(ops) < 2:
        return f"כל {_int(n)} הבקשות במאגר הוגשו על ידי {lead}."
    second, v2 = ops.index[1], int(ops.iloc[1])
    tail = [f"{o} ({_int(c)})" for o, c in list(ops.items())[1:]]
    rest = tail[0] if len(tail) == 1 else ", ".join(tail[:-1]) + f" ו{tail[-1]}"
    if (v - v2) / n < LEAD_GAP:
        return (f"{lead} ו{second} מגישות כמעט אותו מספר בקשות — {_int(v)} ו-{_int(v2)} "
                f"מתוך {_int(n)}.")
    return (f"{lead} מגישה הכי הרבה בקשות להקמת אתרים: {_int(v)} מתוך {_int(n)} "
            f"({_pct(v / n)}), ואחריה {rest}.")


def insight_trend(months, full, counts):
    fm = [m for m, f in zip(months, full) if f]
    if len(fm) < TREND_MIN_MONTHS:
        return None
    h = len(fm) // 2
    old, new = fm[:h], fm[-h:]
    a = sum(counts.get(m, 0) for m in old) / h
    b = sum(counts.get(m, 0) for m in new) / h
    if a == 0:
        return None
    ch = b / a - 1
    span_old = f"{_month_he(old[0])}–{_month_he(old[-1])}"
    span_new = f"{_month_he(new[0])}–{_month_he(new[-1])}"
    note = " (בחישוב רק חודשים מלאים)" if not all(full) else ""
    if abs(ch) < TREND_THRESHOLD:
        return (f"קצב ההגשה יציב: כ-{a:.0f} בקשות בחודש ב{span_old} וכ-{b:.0f} ב{span_new}{note}.")
    word = "עלה" if ch > 0 else "ירד"
    return (f"קצב ההגשה {word}: ממוצע של {a:.1f} בקשות בחודש ב{span_old}, לעומת {b:.1f} "
            f"ב{span_new} — {'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch), 0)}{note}.")


def insight_peak(months, full, counts):
    fm = [m for m, f in zip(months, full) if f]
    if len(fm) < 3:
        return None
    best = sorted(fm, key=lambda m: (-counts.get(m, 0), m))[0]
    v = counts.get(best, 0)
    avg = sum(counts.get(m, 0) for m in fm) / len(fm)
    if v < avg * 1.3:
        return None
    return (f"החודש העמוס ביותר היה {_month_he(best)}, עם {_int(v)} בקשות — "
            f"פי {v / avg:.1f} מהממוצע החודשי ({avg:.1f}).")


def insight_mix_shift(df, quarters, qfull, lead):
    fq = [q for q, f in zip(quarters, qfull) if f]
    if len(fq) < 2:
        return None
    q = df["date"].dt.to_period("Q")
    first, last = fq[0], fq[-1]
    s1 = (df.loc[q == first, "operator"] == lead).mean()
    s2 = (df.loc[q == last, "operator"] == lead).mean()
    if pd.isna(s1) or pd.isna(s2) or abs(s2 - s1) < MIX_SHIFT_PP:
        return None
    word = "עלה" if s2 > s1 else "ירד"
    return (f"חלקה של {lead} בבקשות {word} מ-{_pct(s1, 0)} ברבעון {first.quarter} של {first.year} "
            f"ל-{_pct(s2, 0)} ברבעון {last.quarter} של {last.year} (רבעונים מלאים).")


def insight_family(df, ops):
    big = [o for o in ops.index if ops[o] >= FAMILY_MIN_OP]
    if len(big) < 2:
        return None
    share = pd.crosstab(df["operator"], df["family"], normalize="index")
    best = None
    for fam in sorted(share.columns):
        vals = sorted(((float(share.loc[o, fam]), o) for o in big), key=lambda t: (-t[0], t[1]))
        gap = vals[0][0] - vals[-1][0]
        if gap >= FAMILY_GAP_PP and (best is None or gap > best[0]):
            best = (gap, fam, vals)
    if best is None:
        return None
    _, fam, vals = best
    parts = [f"{_pct(s, 0)} אצל {o}" for s, o in vals[1:]]
    others = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" ו-{parts[-1]}"
    return (f"כל חברה בונה אחרת: {_pct(vals[0][0], 0)} מהבקשות של {vals[0][1]} הן למוקד "
            f"מסוג '{fam}', לעומת {others}.")


def insight_juris(df, jv):
    n = len(df)
    (a, na) = jv.index[0], int(jv.iloc[0])
    if na / n < 0.05:
        return None
    text = f"{a} מובילה עם {_int(na)} בקשות ({_pct(na / n)})"
    if len(jv) > 1:
        text += f", ואחריה {jv.index[1]} ({_int(jv.iloc[1])})"
    top5 = int(jv.iloc[:5].sum())
    return text + (f"; חמשת תחומי השיפוט המובילים מרכזים {_pct(top5 / n, 0)} מהבקשות, "
                   f"מתוך {_int(len(jv))} תחומי שיפוט.")


def insight_refile(df):
    s = df.loc[df["site"] != "", "site"].value_counts()
    rep = s[s > 1]
    if len(rep) < REFILE_MIN:
        return None
    return (f"{_int(len(rep))} אתרים מופיעים ביותר מבקשה אחת (בסך הכול {_int(rep.sum())} בקשות) — "
            f"אותו מספר אתר הוגש שוב בתאריך אחר.")


def insight_cow(df):
    cow = df[df["site"].str.startswith(COW_PREFIX)]
    if len(cow) < COW_MIN:
        return None
    ops = _ranked(cow["operator"])
    who = ops.index[0] if len(ops) == 1 else "החברות"
    return (f"{_int(len(cow))} בקשות הן לאתרים ניידים (מספר אתר שמתחיל ב-{COW_PREFIX}) של {who}, "
            f"ב-{_int(cow['site'].nunique())} אתרים שונים.")


def insight_no_juris(df):
    m = df["juris"].isin(NO_JURIS)
    if int(m.sum()) < 3:
        return None
    return (f"{_int(m.sum())} בקשות הן לאתרים מחוץ לתחום שיפוט של רשות מקומית "
            f"(רשומים כ'{NO_JURIS[0]}' או '{NO_JURIS[1]}').")


def insight_weekday(df):
    wd = df["date"].dt.dayofweek.value_counts()
    weekend = int(wd.get(4, 0) + wd.get(5, 0))
    if len(df) < 50 or weekend / len(df) > 0.02:
        return None
    best = sorted(WEEK_ORDER, key=lambda d: (-int(wd.get(d, 0)), WEEK_ORDER.index(d)))[0]
    we = ("אף בקשה לא הוגשה בשישי או בשבת" if weekend == 0 else
          "רק בקשה אחת הוגשה בשישי או בשבת" if weekend == 1 else
          f"רק {_int(weekend)} בקשות הוגשו בשישי או בשבת")
    return (f"הבקשות מוגשות בימי חול — {we}; היום העמוס הוא יום "
            f"{WEEKDAYS_HE[best]} ({_int(wd.get(best, 0))} בקשות).")


# ------------------------------------------------------------------ compute

def compute(frames):
    df = _prepare(frames["main"])
    df = df[df["date"].notna()].reset_index(drop=True)
    n = len(df)
    ops = _ranked(df["operator"])
    op_names = list(ops.index)
    lo, hi = df["date"].min(), df["date"].max()

    # Monthly, stacked by operator.
    months, mfull = _periods(df["date"], "M")
    mp = df["date"].dt.to_period("M")
    m_counts = {k: int(v) for k, v in mp.value_counts().items()}
    m_op = df.groupby([mp, "operator"]).size()
    m_labels = [f"{_month_he(m)}{'' if f else ' (חלקי)'}" for m, f in zip(months, mfull)]
    monthly = {"x": m_labels,
               "series": [{"name": o, "data": [int(m_op.get((m, o), 0)) for m in months]}
                          for o in op_names],
               "zoom": len(months) > 24}
    t_monthly = [{"name": lab, "total": _int(m_counts.get(m, 0)),
                  "cells": [_int(m_op.get((m, o), 0)) for o in op_names]}
                 for lab, m in zip(m_labels, months)]

    # Operators: applications and distinct sites.
    sites_by_op = df[df["site"] != ""].groupby("operator")["site"].nunique()
    companies = {"names": op_names,
                 "apps": [int(ops[o]) for o in op_names],
                 "sites": [int(sites_by_op.get(o, 0)) for o in op_names]}
    t_companies = [{"name": o, "apps": _int(ops[o]), "sites": _int(sites_by_op.get(o, 0)),
                    "share": f"{ops[o] / n * 100:.1f}"} for o in op_names]

    # Quarterly operator mix (100%).
    quarters, qfull = _periods(df["date"], "Q")
    qp = df["date"].dt.to_period("Q")
    q_tot = qp.value_counts()
    q_op = df.groupby([qp, "operator"]).size()
    q_labels = [f"רבעון {q.quarter} {q.year}{'' if f else ' (חלקי)'}" for q, f in zip(quarters, qfull)]

    def qshare(q, o):
        t = int(q_tot.get(q, 0))
        return round(int(q_op.get((q, o), 0)) / t * 100, 1) if t else 0

    mix = {"x": q_labels,
           "series": [{"name": o, "data": [qshare(q, o) for q in quarters],
                       "counts": [int(q_op.get((q, o), 0)) for q in quarters]} for o in op_names]}
    t_mix = [{"name": lab, "total": _int(q_tot.get(q, 0)),
              "cells": [f"{qshare(q, o):.1f}" for o in op_names]} for lab, q in zip(q_labels, quarters)]

    # Site-type families × operator.
    fam = _ranked(df["family"])
    fam_names = list(fam.index)
    f_op = df.groupby(["family", "operator"]).size()
    family = {"names": fam_names,
              "series": [{"name": o, "data": [int(f_op.get((f, o), 0)) for f in fam_names]}
                         for o in op_names]}
    t_family = [{"name": f, "total": _int(fam[f]),
                 "cells": [_int(f_op.get((f, o), 0)) for o in op_names]} for f in fam_names]

    # Raw type labels per operator (sunburst).
    t_op = df.groupby(["operator", "type"]).size()
    sun = []
    t_types = []
    for o in op_names:
        kids = sorted(((t, int(v)) for (oo, t), v in t_op.items() if oo == o),
                      key=lambda kv: (-kv[1], kv[0]))
        sun.append({"name": o, "children": [{"name": t, "value": v} for t, v in kids]})
        t_types.extend({"op": o, "name": t, "count": _int(v)} for t, v in kids)
    n_labels = int(df["type"].nunique())

    # Jurisdictions: top-N stacked by operator + other.
    jv = _ranked(df["juris"])
    j_names = list(jv.index[:TOP_JURIS])
    j_op = df.groupby(["juris", "operator"]).size()
    j_series = []
    for o in op_names:
        data = [int(j_op.get((j, o), 0)) for j in j_names]
        j_series.append({"name": o, "data": data})
    juris = {"names": j_names, "series": j_series}
    t_juris = [{"name": j, "total": _int(jv[j]), "cells": [_int(j_op.get((j, o), 0)) for o in op_names]}
               for j in j_names]
    j_rest = int(jv.iloc[TOP_JURIS:].sum())

    # North → south profile in ITM northing bands.
    g = df[df["valid_xy"]].copy()
    g["band"] = (g["y"] // (BAND_KM * 1000)).astype(int)
    bands = sorted(g["band"].unique(), reverse=True)
    b_op = g.groupby(["band", "operator"]).size()
    b_tot = g["band"].value_counts()
    b_labels = []
    t_ns = []
    for b in bands:
        top = _ranked(g.loc[g["band"] == b, "juris"]).index[:2]
        lab = " · ".join(top)
        b_labels.append(lab)
        t_ns.append({"name": lab, "total": _int(b_tot[b]),
                     "cells": [_int(b_op.get((b, o), 0)) for o in op_names]})
    ns = {"names": b_labels,
          "series": [{"name": o, "data": [int(b_op.get((b, o), 0)) for b in bands]} for o in op_names]}
    center_band = sorted(bands, key=lambda b: (-int(b_tot[b]), b))[0] if bands else None
    n_invalid = int((~df["valid_xy"]).sum())

    # Weekday of submission.
    wd = df["date"].dt.dayofweek.value_counts()
    weekday = {"names": [WEEKDAYS_HE[d] for d in WEEK_ORDER],
               "values": [int(wd.get(d, 0)) for d in WEEK_ORDER]}
    t_weekday = [{"name": WEEKDAYS_HE[d], "count": _int(wd.get(d, 0)),
                  "share": f"{wd.get(d, 0) / n * 100:.1f}"} for d in WEEK_ORDER]

    lead = op_names[0]
    rules = [
        ("leader", insight_leader(df, ops)),
        ("trend", insight_trend(months, mfull, m_counts)),
        ("peak", insight_peak(months, mfull, m_counts)),
        ("mix_shift", insight_mix_shift(df, quarters, qfull, lead)),
        ("juris", insight_juris(df, jv)),
        ("family", insight_family(df, ops)),
        ("cow", insight_cow(df)),
        ("refile", insight_refile(df)),
        ("no_juris", insight_no_juris(df)),
        ("weekday", insight_weekday(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_sites = int(df.loc[df["site"] != "", "site"].nunique())
    lead_share = ops.iloc[0] / n
    fm = [m for m, f in zip(months, mfull) if f]
    avg_full = sum(m_counts.get(m, 0) for m in fm) / len(fm) if fm else 0.0
    last_full = fm[-1] if fm else None
    last_v = m_counts.get(last_full, 0) if last_full is not None else 0
    # Neutral activity measure: highlight only a month well above the average.
    last_tone = "info" if avg_full and last_v >= avg_full * 1.15 else "brand"

    permits = _ranked(df["permit"])
    permit_txt = (f"כולן בקשות מסוג {permits.index[0]}" if len(permits) == 1 else
                  "לפי סוג ההיתר: " + ", ".join(f"{p} ({_int(v)})" for p, v in permits.items()))
    span = f"{_date_he(lo)} עד {_date_he(hi)}"
    op_list = ", ".join(op_names[:-1]) + f" ו{op_names[-1]}" if len(op_names) > 1 else op_names[0]

    center_txt = ""
    if center_band is not None:
        center_txt = (f" הרצועה העמוסה ביותר היא זו של {b_labels[bands.index(center_band)]}, "
                      f"עם {_int(b_tot[center_band])} בקשות ({_pct(b_tot[center_band] / max(len(g), 1), 0)}).")

    labels = {
        "lede": (f"המאגר מרכז {_int(n)} בקשות להיתרים להקמת אתרי שידור סלולריים שהגישו {op_list} "
                 f"למשרד להגנת הסביבה, מ-{span}. {permit_txt}. הבקשות מתייחסות ל-{_int(n_sites)} "
                 f"אתרים ב-{_int(len(jv))} תחומי שיפוט. הרשימה מתעדכנת: בקשות חדשות נוספות אליה, "
                 f"וישנות עשויות לצאת ממנה."),
        "map_note": (f"כל נקודה היא אתר שהוגשה עבורו בקשה; לחיצה על נקודה מציגה את החברה, היישוב, "
                     f"הכתובת וסוג המוקד."
                     + (f" ל-{_int(n_invalid)} בקשות רשומה נקודת ציון מחוץ לתחום ישראל." if n_invalid else "")),
        "monthly_note": (f"מספר הבקשות שהוגשו בכל חודש, לפי חברה. ממוצע של {avg_full:.1f} בקשות בחודש מלא"
                         + ("; חודשים בקצה הרשימה שאינם מכוסים במלואם מסומנים (חלקי)." if not all(mfull) else ".")),
        "monthly_aria": (f"תרשים עמודות מוערמות: בקשות להקמת אתרים לפי חודש וחברה, {len(months)} חודשים, "
                         f"ממוצע {avg_full:.1f} בקשות בחודש מלא."),
        "monthly_caption": "בקשות לפי חודש וחברה.",
        "companies_note": (f"{lead} מובילה עם {_pct(lead_share)} מהבקשות. לצד מספר הבקשות מוצג מספר "
                           f"האתרים השונים — חלק מהאתרים הוגשו יותר מפעם אחת."),
        "companies_aria": f"תרשים עמודות: בקשות ואתרים שונים לפי חברה; {lead} מובילה עם {_int(ops.iloc[0])} בקשות.",
        "companies_caption": "בקשות ואתרים שונים לפי חברה.",
        "mix_note": "חלקה של כל חברה מתוך הבקשות בכל רבעון (באחוזים); הריחוף מציג גם את מספר הבקשות.",
        "mix_aria": f"תרשים עמודות מוערמות באחוזים: תמהיל החברות לפי רבעון, {len(quarters)} רבעונים.",
        "mix_caption": "חלק כל חברה מהבקשות בכל רבעון (באחוזים).",
        "family_note": (f"סוגי המוקד קובצו למשפחות לפי מילות מפתח בתיאור (פנימי, גג, עוקץ, קרקעי, מבנה). "
                        f"המשפחה הנפוצה: {fam_names[0]} ({_int(fam.iloc[0])} בקשות)."),
        "family_aria": (f"תרשים עמודות אופקי מוערם: בקשות לפי משפחת סוג מוקד וחברה; הנפוצה {fam_names[0]} "
                        f"עם {_int(fam.iloc[0])} בקשות."),
        "family_caption": "בקשות לפי משפחת סוג מוקד וחברה.",
        "types_note": (f"כל חברה מתארת את סוג המוקד במונחים משלה — {_int(n_labels)} תיאורים שונים במאגר. "
                       f"הטבעת הפנימית היא החברה, החיצונית התיאור כפי שנרשם."),
        "types_aria": f"תרשים שמש: {_int(n_labels)} תיאורי סוג מוקד כפי שנרשמו, לפי חברה.",
        "types_caption": "סוג המוקד כפי שנרשם, לפי חברה.",
        "juris_note": (f"{len(j_names)} תחומי השיפוט עם הכי הרבה בקשות, לפי חברה"
                       + (f"; ב-{_int(len(jv) - len(j_names))} תחומי שיפוט נוספים הוגשו עוד "
                          f"{_int(j_rest)} בקשות." if j_rest else ".")),
        "juris_aria": (f"תרשים עמודות אופקי מוערם: {len(j_names)} תחומי השיפוט המובילים; {jv.index[0]} "
                       f"בראש עם {_int(jv.iloc[0])} בקשות."),
        "juris_caption": f"{len(j_names)} תחומי השיפוט עם הכי הרבה בקשות, לפי חברה.",
        "ns_note": (f"הארץ חולקה לרצועות של {BAND_KM} ק\"מ מצפון לדרום לפי נקודת הציון; כל רצועה נקראת "
                    f"על שם תחומי השיפוט הבולטים בה. רצועות ללא בקשות הושמטו.{center_txt}"),
        "ns_aria": (f"תרשים עמודות אופקי מוערם: בקשות לפי רצועות של {BAND_KM} ק\"מ מצפון לדרום, "
                    f"{len(bands)} רצועות, לפי חברה."),
        "ns_caption": f"בקשות לפי רצועה של {BAND_KM} ק\"מ מצפון לדרום, לפי חברה.",
        "weekday_note": "באיזה יום בשבוע הוגשו הבקשות.",
        "weekday_aria": (f"תרשים עמודות: בקשות לפי יום בשבוע; העמוס יום "
                         f"{WEEKDAYS_HE[sorted(WEEK_ORDER, key=lambda d: (-int(wd.get(d, 0)), WEEK_ORDER.index(d)))[0]]}."),
        "weekday_caption": "בקשות לפי יום בשבוע.",
        "last_kpi": (f"בקשות ב{_month_he(last_full)} (ממוצע חודשי: {avg_full:.1f})"
                     if last_full is not None else "בקשות בחודש האחרון"),
        "lead_kpi": f"מהבקשות הוגשו על ידי {lead}",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} בקשות להיתרי הקמה של אתרי שידור סלולריים שהגישו {op_list}, "
                           f"{_date_he(lo)} עד {_date_he(hi)}: מפה, קצב הגשה חודשי, חברות, סוגי "
                           f"מוקד ותחומי שיפוט."),
            "dataset_kind": "map",
            "related_ids": ["995eb826-c471-4572-8fd3-39d92a3a9603",
                            "04931a88-336c-4d95-8a13-9dc631c3e2d1"],
            "suggested_tags": ["אנטנות סלולריות", "קרינה", "תקשורת", "היתרי בנייה", "סביבה"],
            "temporal_coverage": f"{lo.year}/{hi.year}" if lo.year != hi.year else str(lo.year),
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "sites": {"value": n_sites, "display": _int(n_sites), "tone": "brand"},
            "lead": {"value": round(float(lead_share), 4), "display": _pct(lead_share), "tone": "brand"},
            "last": {"value": last_v, "display": _int(last_v), "tone": last_tone},
        },
        "charts": {
            "monthly": monthly,
            "companies": companies,
            "mix": mix,
            "family": family,
            "types": sun,
            "juris": juris,
            "ns": ns,
            "weekday": weekday,
        },
        "tables": {
            "op_names": op_names,
            "monthly": t_monthly,
            "monthly_big": len(t_monthly) > 20,
            "companies": t_companies,
            "mix": t_mix,
            "mix_big": len(t_mix) > 20,
            "family": t_family,
            "types": t_types,
            "types_big": len(t_types) > 30,
            "juris": t_juris,
            "ns": t_ns,
            "weekday": t_weekday,
        },
        "insights": insights,
        "labels": labels
    }
