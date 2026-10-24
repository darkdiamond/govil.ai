"""מאגר חברות — רשם החברות: every company ever registered in Israel (~733k).

One row per company: type, status (and sub-status), incorporation date,
"violating company" flag (מפרה — typically an unpaid annual fee), last annual
report filed, registered address. Companies are businesses, but the data has
no amount to rank them by, so the page aggregates.

Memory: the frame arrives with all 29 columns as str (~0.7GB); compute slims
it to the columns it reads straight away. "Now" is the latest incorporation
date in the data; the current year is partial.
"""
import pandas as pd

GROUPS = ["פעילה", "בהליכי פירוק או מחיקה", "חוסלה", "נמחקה", "אחר"]
COHORT_FROM = 1990
SURVIVAL_YEARS = 10
TOP_TOWNS = 15
TOP_SUB = 10
MONTHS = 24
REPORT_RECENT = 2  # last report filed within this many years of "now" = up to date


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(s):
    # Registrar export: '~' stands for '"' inside abbreviations (בע~מ, ע~י, בימ~ש).
    return s.str.replace("~", '"', regex=False).str.strip()


def _group(status):
    if status == "פעילה" or status == "פעילה זמנית":
        return "פעילה"
    if "מחוק" in status or "נגרעה" in status:
        return "נמחקה"
    if "מחוסלת" in status or "חיסול" in status:
        return "חוסלה"
    if "פרוק" in status or "פירוק" in status or "כינוס" in status or "הליך" in status:
        return "בהליכי פירוק או מחיקה"
    return "אחר"


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _prepare(raw):
    df = pd.DataFrame({
        "type": raw["סוג תאגיד"].str.strip(),
        "status": _clean(raw["סטטוס חברה"]),
        "sub": _clean(raw["תת סטטוס"]),
        "founded": pd.to_datetime(raw["תאריך התאגדות"], format="%d/%m/%Y", errors="coerce"),
        "gov": raw["חברה ממשלתית"].str.strip() == "כן",
        "violating": raw["מפרה"].str.strip() == "מפרה",
        "report": pd.to_numeric(raw["שנה אחרונה של דוח שנתי (שהוגש)"], errors="coerce"),
        "town": raw["שם עיר"].str.strip(),
    })
    df["group"] = df["status"].map(_group)
    return df


def insight_active(df):
    act = int((df["group"] == "פעילה").sum())
    liq = int((df["group"] == "חוסלה").sum())
    struck = int((df["group"] == "נמחקה").sum())
    return (f"מתוך {_int(len(df))} חברות שנרשמו אי-פעם, {_int(act)} ({_pct(act / len(df))}) פעילות; "
            f"{_int(liq)} חוסלו ו-{_int(struck)} נמחקו מהמרשם.")


def insight_incorporations(df, now):
    y = df["founded"].dt.year
    full, prev = now.year - 1, now.year - 2
    a, b = int((y == full).sum()), int((y == prev).sum())
    if b < 100:
        return None
    ch = (a - b) / b
    trend = ("בדומה לשנה שקדמה לה" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))} לעומת {prev} ({_int(b)})")
    vc = y.value_counts()
    peak = int(vc.idxmax())
    tail = (" זו שנת השיא במאגר." if peak == full
            else f" שנת השיא: {peak} ({_int(vc.max())}).")
    return f"ב-{full} נרשמו {_int(a)} חברות חדשות — {trend}.{tail}"


def insight_ytd(df, now):
    """Year-to-date vs the same calendar window a year earlier."""
    start = pd.Timestamp(now.year, 1, 1)
    try:
        prev_end = now.replace(year=now.year - 1)
    except ValueError:
        prev_end = now.replace(year=now.year - 1, day=28)
    prev_start = pd.Timestamp(now.year - 1, 1, 1)
    a = int(((df["founded"] >= start) & (df["founded"] <= now)).sum())
    b = int(((df["founded"] >= prev_start) & (df["founded"] <= prev_end)).sum())
    if b < 100:
        return None
    ch = (a - b) / b
    word = ("כמעט ללא שינוי" if abs(ch) < 0.03
            else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))}")
    return (f"מתחילת {now.year} ועד {now.day}/{now.month} נרשמו {_int(a)} חברות, לעומת {_int(b)} "
            f"באותה תקופה אשתקד — {word}.")


def insight_violating(df):
    act = df[df["group"] == "פעילה"]
    v = int(act["violating"].sum())
    return (f"{_pct(v / len(act))} מהחברות הפעילות ({_int(v)}) מסומנות במרשם כ'חברה מפרה' — "
            f"חברה שלא שילמה אגרה שנתית או לא הגישה דוח שנתי.")


def insight_reports(df, now):
    act = df[df["group"] == "פעילה"]
    recent = int((act["report"] >= now.year - REPORT_RECENT + 1).sum())
    none = int(act["report"].isna().sum())
    return (f"ל-{_pct(recent / len(act))} מהחברות הפעילות יש דוח שנתי מ-{now.year - REPORT_RECENT + 1} "
            f"ואילך; ל-{_pct(none / len(act))} לא רשום דוח שנתי כלל.")


def insight_survival(df, now):
    cohort = now.year - 1 - SURVIVAL_YEARS
    c = df[df["founded"].dt.year == cohort]
    if len(c) < 500:
        return None
    alive = (c["group"] == "פעילה").mean()
    return (f"מבין {_int(len(c))} החברות שנרשמו ב-{cohort}, {_pct(alive)} עדיין פעילות כעבור "
            f"{SURVIVAL_YEARS} שנים.")


def insight_town(df):
    a = df[(df["group"] == "פעילה") & (df["town"] != "")]
    vc = _vc(a["town"])
    return (f"{vc.index[0]} היא כתובתן הרשומה של {_pct(vc.iloc[0] / len(a))} מהחברות הפעילות שיש "
            f"להן כתובת ({_int(vc.iloc[0])}); אחריה {vc.index[1]} ({_pct(vc.iloc[1] / len(a))}).")


def compute(frames):
    df = _prepare(frames.pop("companies"))
    now = df["founded"].max()
    y = df["founded"].dt.year

    years = list(range(COHORT_FROM, now.year + 1))
    by = df[y >= COHORT_FROM].groupby([y, "group"]).size()
    groups = [g for g in GROUPS if (df["group"] == g).any()]
    founded = {"x": [str(v) for v in years],
               "series": [{"name": g, "data": [int(by.get((v, g), 0)) for v in years]} for g in groups]}

    months = pd.period_range(end=now.to_period("M"), periods=MONTHS, freq="M")
    pm = df["founded"].dt.to_period("M").value_counts()
    monthly = {"x": [str(p) for p in months], "y": [int(pm.get(p, 0)) for p in months]}

    cohort_years = list(range(COHORT_FROM, now.year))
    surv = df[y.isin(cohort_years)].groupby(y)["group"].apply(lambda s: (s == "פעילה").mean())
    survival = {"x": [str(v) for v in cohort_years],
                "y": [round(float(surv.get(v, 0)) * 100, 1) for v in cohort_years]}

    status = [(k, int(v)) for k, v in _vc(df["status"]).items()]
    types = [(k, int(v)) for k, v in _vc(df["type"]).items()]
    sub = _top(_vc(df.loc[df["sub"] != "", "sub"]), TOP_SUB)

    act = df[df["group"] == "פעילה"]
    towns = _top(_vc(act.loc[act["town"] != "", "town"]), TOP_TOWNS, "שאר היישובים")
    top_towns = [k for k, _ in towns if k != "שאר היישובים"]
    viol = {"names": top_towns,
            "values": [round(float(act.loc[act["town"] == t, "violating"].mean()) * 100, 1)
                       for t in top_towns]}

    last_full = now.year
    rep_years = list(range(last_full - 5, last_full + 1))
    rep_vc = act["report"].value_counts()
    rep_names = [str(v) for v in rep_years[::-1]] + ["מוקדם יותר", "לא הוגש"]
    rep_vals = [int(rep_vc.get(v, 0)) for v in rep_years[::-1]]
    rep_vals += [int((act["report"] < rep_years[0]).sum()), int(act["report"].isna().sum())]
    reports = {"names": rep_names, "values": rep_vals}

    rules = [
        ("active", insight_active(df)),
        ("incorporations", insight_incorporations(df, now)),
        ("ytd", insight_ytd(df, now)),
        ("violating", insight_violating(df)),
        ("reports", insight_reports(df, now)),
        ("survival", insight_survival(df, now)),
        ("town", insight_town(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    now_he = f"{now.day}/{now.month}/{now.year}"
    full = now.year - 1
    n_active = len(act)
    public = int(df["type"].str.contains("ציבורית").sum())

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"רשם החברות: {_int(len(df))} חברות שנרשמו אי-פעם בישראל, מהן "
                           f"{_int(n_active)} פעילות; סטטוס, שנת התאגדות, דיווח שנתי ומיקום. "
                           f"מעודכן עד {now_he}."),
            "dataset_kind": "registry",
            "related_ids": ["01aeaf5c-59a2-4ddc-a616-31b85621bfe2", "3111ae54-790a-4d02-9750-d51e1134b405"],
            "suggested_tags": ["רשם החברות", "חברות", "תאגידים", "עסקים"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": len(df), "display": _int(len(df))},
            "active": {"value": n_active, "display": _int(n_active)},
            "last_year": {"value": int((y == full).sum()), "display": _int((y == full).sum())},
            "public": {"value": public, "display": _int(public)},
            "gov": {"value": int(df["gov"].sum()), "display": _int(df["gov"].sum())},
        },
        "charts": {
            "founded": founded,
            "monthly": monthly,
            "survival": survival,
            "status": bar(status),
            "types": bar(types),
            "sub": bar(sub),
            "towns": bar(towns),
            "violating": viol,
            "reports": reports,
        },
        "insights": insights,
        "labels": {
            "lede": (f"{_int(len(df))} חברות שנרשמו אי-פעם ברשם החברות, מהן {_int(n_active)} פעילות. "
                     f"ההתאגדות האחרונה במאגר: {now_he}."),
            "full_year": str(full),
            "founded_aria": f"גרף עמודות מוערמות: חברות לפי שנת התאגדות ({COHORT_FROM} ואילך) ומצבן כיום.",
            "founded_note": f"חברות לפי שנת ההתאגדות, צבועות לפי מצבן היום. השנה האחרונה חלקית — עד {now_he}.",
            "monthly_aria": f"גרף עמודות: חברות חדשות בכל חודש, {MONTHS} החודשים האחרונים.",
            "survival_aria": "גרף קו: שיעור החברות שעדיין פעילות, לפי שנת ההתאגדות.",
            "survival_note": ("שיעור החברות מכל שנתון התאגדות שעדיין פעילות היום. שנתונים צעירים "
                              "טבעי שיהיו גבוהים יותר — לחברות היה פחות זמן להיסגר."),
            "status_aria": f"תרשים עמודות: {_int(len(df))} החברות לפי סטטוס ברשם.",
            "types_aria": "תרשים עמודות: החברות לפי סוג התאגיד.",
            "sub_aria": f"תרשים עמודות: תתי-הסטטוס הנפוצים, {TOP_SUB} הראשונים.",
            "sub_note": f"תת-סטטוס מתועד ל-{_int((df['sub'] != '').sum())} חברות בלבד.",
            "towns_aria": f"תרשים עמודות: {TOP_TOWNS} היישובים עם מספר החברות הפעילות הגבוה ביותר.",
            "towns_note": (f"לפי הכתובת הרשומה; ל-{_int((act['town'] == '').sum())} חברות פעילות "
                           f"אין יישוב רשום."),
            "violating_aria": "תרשים עמודות: שיעור החברות הפעילות המסומנות 'מפרה' ביישובים המובילים.",
            "reports_aria": "תרשים עמודות: החברות הפעילות לפי שנת הדוח השנתי האחרון שהוגש.",
        },
    }
