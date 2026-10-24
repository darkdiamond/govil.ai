"""כלי רכב עם תג חניה לנכה — vehicles currently authorised to carry a
disabled-parking tag, one row per tag, with the tag's issue date and type.

Licence plates are never shown: only aggregates. The issue date is that of
the CURRENT tag — tags are renewed, so most rows are recent renewals, not
new beneficiaries; the page says so. "Now" is the latest issue date in the
data. Tag types are reported by the codes the register uses (1, 2) since the
dataset does not name them.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]   # pandas Monday=0
DAY_ORDER = [6, 0, 1, 2, 3, 4, 5]                                       # Sunday first
FIRST_YEAR = 2019            # earlier issue years hold a handful of rows; pooled
RECENT_DAYS = 90
AGE_BINS = [(0, 182, "עד חצי שנה"), (183, 365, "חצי שנה–שנה"), (366, 730, "1–2 שנים"),
            (731, 1095, "2–3 שנים"), (1096, 100000, "יותר מ-3 שנים")]
PLATE_LABELS = {"short": "עד 6 ספרות", "7": "7 ספרות", "8": "8 ספרות"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _m_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _prepare(df):
    plate = df["MISPAR RECHEV"].str.strip()
    digits = plate.str.len()
    out = pd.DataFrame({
        "plate": plate,
        "date": pd.to_datetime(df["TAARICH HAFAKAT TAG"].str.strip(), format="%Y%m%d", errors="coerce"),
        "type": df["SUG TAV"].str.strip().replace("", "לא צוין"),
        "plate_fmt": digits.map(lambda n: "8" if n == 8 else "7" if n == 7 else "short"),
    })
    return out.dropna(subset=["date"]).reset_index(drop=True)


def insight_volume(df, vehicles, ref):
    last_year = df[df["date"] > ref - pd.Timedelta(days=365)]
    return (f"במאגר {_int(len(df))} תגי חניה לנכה על {_int(vehicles)} כלי רכב; "
            f"{_pct(len(last_year) / len(df))} מהתגים הונפקו בשנה שקדמה ל-{_d_he(ref)}.")


def insight_month_yoy(df, ref):
    """Last COMPLETE month vs the same month a year earlier."""
    last_full = (ref.to_period("M") - 1)
    prev = last_full - 12
    m = df["date"].dt.to_period("M").value_counts()
    a, b = int(m.get(last_full, 0)), int(m.get(prev, 0))
    if b < 100:
        return None
    ch = (a - b) / b
    if abs(ch) < 0.05:
        return f"ב{_m_he(last_full)} הונפקו {_int(a)} תגים — כמעט כמו ב{_m_he(prev)} ({_int(b)})."
    word = "יותר" if ch > 0 else "פחות"
    return (f"ב{_m_he(last_full)} הונפקו {_int(a)} תגים — {_pct(abs(ch), 0)} {word} "
            f"מאשר ב{_m_he(prev)} ({_int(b)}).")


def insight_type(df):
    vc = df["type"].value_counts()
    if len(vc) < 2:
        return None
    t2 = vc.drop(vc.index[0])
    main = vc.index[0]
    return (f"{_pct(vc.iloc[0] / len(df))} מהתגים הם מסוג {main}; "
            f"{_int(t2.sum())} תגים ({_pct(t2.sum() / len(df))}) מסוגים אחרים.")


def insight_weekday(df):
    wd = df["date"].dt.dayofweek.value_counts()
    workdays = wd.reindex([6, 0, 1, 2, 3]).fillna(0)
    if workdays.sum() == 0:
        return None
    top, low = int(workdays.idxmax()), int(workdays.idxmin())
    if top == low:
        return None
    return (f"יום {DAYS_HE[top]} הוא היום העמוס ביותר בהנפקת תגים ({_int(workdays[top])} תגים), "
            f"ויום {DAYS_HE[low]} השקט ביותר מבין ימי העבודה ({_int(workdays[low])}).")


def insight_plates(df):
    share8 = (df["plate_fmt"] == "8").mean()
    if share8 == 0:
        return None
    return (f"ל-{_pct(share8)} מכלי הרכב עם תג יש מספר רישוי בן 8 ספרות — "
            "כלומר רכב שנרשם בשנים האחרונות.")


def insight_multi(df, vehicles):
    extra = len(df) - vehicles
    if extra <= 0:
        return None
    multi = int((df["plate"].value_counts() > 1).sum())
    return f"{_int(multi)} כלי רכב מופיעים במאגר עם יותר מתג אחד."


def compute(frames):
    df = _prepare(frames["tags"])
    ref = df["date"].max()
    vehicles = int(df["plate"].nunique())

    # Monthly issues (FIRST_YEAR+), line; yearly table incl. pooled earlier years.
    recent = df[df["date"].dt.year >= FIRST_YEAR]
    monthly = recent["date"].dt.to_period("M").value_counts().sort_index()
    months = pd.period_range(monthly.index.min(), ref.to_period("M"), freq="M")
    monthly = monthly.reindex(months, fill_value=0)
    m_chart = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index],
               "y": [int(v) for v in monthly],
               "partial_index": len(monthly) - 1}

    yr = df["date"].dt.year.where(df["date"].dt.year >= FIRST_YEAR, FIRST_YEAR - 1)
    by_year = pd.crosstab(yr, df["type"]).sort_index()
    types = list(by_year.columns)
    y_labels = [f"עד {FIRST_YEAR - 1}" if y == FIRST_YEAR - 1 else str(y) for y in by_year.index]
    y_chart = {"x": y_labels,
               "series": [{"name": f"סוג {t}", "data": [int(v) for v in by_year[t]]} for t in types]}
    t_years = [{"year": lab, "total": _int(row.sum()),
                "cells": [_int(row[t]) for t in types]}
               for lab, (_, row) in zip(y_labels, by_year.iterrows())]

    # Last RECENT_DAYS days, daily.
    days = pd.date_range(ref - pd.Timedelta(days=RECENT_DAYS - 1), ref, freq="D")
    daily = df["date"].value_counts().reindex(days, fill_value=0)
    d_chart = {"x": [d.strftime("%Y-%m-%d") for d in days], "y": [int(v) for v in daily]}

    # Weekday profile.
    wd = df["date"].dt.dayofweek.value_counts().reindex(DAY_ORDER, fill_value=0)
    w_chart = {"names": [DAYS_HE[d] for d in DAY_ORDER], "values": [int(v) for v in wd]}
    t_week = [{"name": n, "count": _int(v), "share": f"{v / len(df) * 100:.1f}"}
              for n, v in zip(w_chart["names"], w_chart["values"])]

    # Tag age (days since issue).
    age = (ref - df["date"]).dt.days
    a_counts = []
    for lo, hi, label in AGE_BINS:
        a_counts.append((label, int(age.between(lo, hi).sum())))
    a_chart = {"names": [a for a, _ in a_counts], "values": [b for _, b in a_counts]}
    t_age = [{"name": a, "count": _int(b), "share": f"{b / len(df) * 100:.1f}"} for a, b in a_counts]

    # Plate format (aggregate only).
    pf = df.drop_duplicates("plate")["plate_fmt"].value_counts()
    p_names = [PLATE_LABELS[k] for k in ("short", "7", "8")]
    p_vals = [int(pf.get(k, 0)) for k in ("short", "7", "8")]
    t_plate = [{"name": a, "count": _int(b), "share": f"{b / vehicles * 100:.1f}"}
               for a, b in zip(p_names, p_vals)]

    # Month-of-year × year heatmap (FIRST_YEAR+).
    hm = recent.groupby([recent["date"].dt.year, recent["date"].dt.month]).size()
    h_years = sorted(recent["date"].dt.year.unique().tolist())
    cells = [[h_years.index(int(y)), int(mo) - 1, int(v)] for (y, mo), v in hm.items()]
    heat = {"years": [str(y) for y in h_years], "months": MONTHS_HE, "cells": cells,
            "max": int(hm.max()) if len(hm) else 0}

    last_30 = int((df["date"] > ref - pd.Timedelta(days=30)).sum())
    rules = [
        ("volume", insight_volume(df, vehicles, ref)),
        ("month_yoy", insight_month_yoy(df, ref)),
        ("type", insight_type(df)),
        ("weekday", insight_weekday(df)),
        ("plates", insight_plates(df.drop_duplicates("plate"))),
        ("multi", insight_multi(df, vehicles)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    return {
        "agent_data": {
            "summary_he": (f"{_int(vehicles)} כלי רכב מורשים לשאת תג חניה לנכה ({_int(len(df))} תגים), "
                           f"נכון ל-{_d_he(ref)}, עם תאריך הפקת התג וסוגו."),
            "dataset_kind": "timeseries",
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
            ],
            "suggested_tags": ["נגישות", "תג נכה", "חניה", "כלי רכב", "תחבורה"],
            "temporal_coverage": f"{df['date'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
        },
        "kpis": {
            "vehicles": {"value": vehicles, "display": _int(vehicles)},
            "tags": {"value": len(df), "display": _int(len(df))},
            "last_30": {"value": last_30, "display": _int(last_30),
                        "label": "תגים שהונפקו ב-30 הימים האחרונים"},
            "as_of": {"value": ref.strftime("%Y-%m-%d"), "display": _d_he(ref)},
        },
        "charts": {
            "monthly": m_chart,
            "yearly": y_chart,
            "daily": d_chart,
            "weekday": w_chart,
            "age": a_chart,
            "plates": {"names": p_names, "values": p_vals},
            "heat": heat,
        },
        "tables": {
            "types": [f"סוג {t}" for t in types],
            "years": t_years,
            "weekday": t_week,
            "age": t_age,
            "plates": t_plate,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(len(df))} תגי חניה לנכה תקפים, על {_int(vehicles)} כלי רכב. "
                     f"תאריך ההנפקה הוא של התג הנוכחי — תגים מחודשים מעת לעת, ולכן רוב התגים "
                     f"הונפקו לאחרונה. ב-30 הימים שעד {_d_he(ref)} הונפקו {_int(last_30)} תגים."),
            "monthly_aria": f"גרף קו: תגים לפי חודש הנפקה, {FIRST_YEAR} עד {_m_he(ref)}.",
            "monthly_note": (f"החודש האחרון ({_m_he(ref)}) חלקי. הנפקות מלפני {FIRST_YEAR} "
                             "מעטות ואינן מוצגות בגרף."),
            "yearly_aria": "תרשים עמודות: תגים לפי שנת הנפקה וסוג תג.",
            "daily_aria": f"תרשים עמודות: תגים שהונפקו בכל יום ב-{RECENT_DAYS} הימים האחרונים.",
            "weekday_aria": "תרשים עמודות: תגים לפי יום בשבוע של ההנפקה.",
            "age_aria": "תרשים עמודות: ותק התגים הנוכחיים מאז הנפקתם.",
            "plates_aria": "תרשים עמודות: כלי רכב עם תג לפי אורך מספר הרישוי.",
            "plates_note": ("מספרי רישוי בני 8 ספרות ניתנים לכלי רכב שנרשמו בשנים האחרונות; "
                            "מספר הרישוי עצמו אינו מוצג."),
            "heat_aria": f"מפת חום: תגים לפי חודש ושנת הנפקה, {FIRST_YEAR} ואילך.",
        },
    }
