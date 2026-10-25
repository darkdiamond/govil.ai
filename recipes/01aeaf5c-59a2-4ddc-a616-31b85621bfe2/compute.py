"""חברות בפרוק מרצון בהליך מזורז — Companies Registrar.

A rolling snapshot, refreshed daily: a company enters when the Registrar
approves its fast-track voluntary-winding-up request and leaves once it is
dissolved (approval + a fixed objection window). So the file always spans
roughly one window of approvals; months that started before the window are
already thinned out, and "trend" only means something inside the window.

"Now" is the latest approval date in the file — never the wall clock.
Rows whose expected dissolution date already precedes that date are
"stragglers" (still listed past their window); they are kept in every
count but excluded from the weekly timeline (which they would stretch
back by months) and listed by name in their own table.
"""
import pandas as pd

TOP_CITIES = 12
NEXT_UP = 15
STRAGGLERS_MAX = 15
MAX_WEEKS = 20          # above this the timeline switches to months
SOON_DAYS = 30
PACE_WEEKS = 4
DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
STATUS_ORDER = ["פעילה", "בפרוק מרצון", "מחוקה"]
FAST_TRACK = "בפרוק מרצון בהליך מזורז"
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_short(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def clean_name(s):
    # The registry export writes gershayim/quotes as "~" (בע~מ).
    return " ".join(s.replace("~", "״").split())


def sunday_dow(ts_series):
    """0 = Sunday … 6 = Saturday."""
    return (ts_series.dt.dayofweek + 1) % 7


def _prepare(df):
    out = pd.DataFrame({
        "num": df["מספר חברה"].str.strip(),
        "name": df["שם חברה"].map(clean_name),
        "en": df["שם באנגלית"].str.strip(),
        "status": df["סטטוס חברה"].str.strip().replace("", "לא ידוע"),
        "sub": df["תת סטטוס"].str.strip(),
        "approved": pd.to_datetime(df["אישור בקשת הפירוק"].str.strip(),
                                   format="%d/%m/%Y", errors="coerce"),
        "expected": pd.to_datetime(df["מועד החיסול הצפוי"].str.strip(),
                                   format="%d/%m/%Y", errors="coerce"),
        "violator": df["מפרה"].str.strip() != "",
        "city": df["שם עיר"].str.strip().replace("", "לא צוין"),
        "street": df["שם רחוב"].str.strip(),
        "co": df["אצל"].str.strip(),
    })
    # Extra registry flags carried next to the fast-track sub-status.
    out["flags"] = out["sub"].map(
        lambda s: sorted({p.strip() for p in s.split(";") if p.strip() and p.strip() != FAST_TRACK}))
    # Company numbers are allocated in sequence: the 3-digit prefix is a
    # coarse registration-era band (higher = registered later).
    pre = out["num"].str[:3]
    out["series"] = pre.where(pre.str.fullmatch(r"\d{3}"), "אחר")
    return out


# ---------------------------------------------------------------- insights

def insight_window(gaps):
    g = gaps.dropna()
    if g.empty:
        return None
    mode = int(g.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0])
    share = (g == mode).mean()
    if share < 0.9:
        return None
    every = "בכל החברות" if share == 1 else f"ב-{n((g == mode).sum())} מתוך {n(len(g))} החברות ({pct(share * 100)})"
    return (f"{every} מועד החיסול הצפוי נקבע {mode} ימים בדיוק לאחר אישור הבקשה — "
            f"זה פרק הזמן שבו נושים ובעלי עניין יכולים להגיש התנגדות לפני שהחברה תחוסל.")


def insight_soon(df, ref):
    fut = df[df["expected"] >= ref]
    if fut.empty:
        return None
    soon = fut[fut["expected"] < ref + pd.Timedelta(days=SOON_DAYS)]
    if soon.empty:
        return None
    first = fut["expected"].min()
    first_n = int((fut["expected"] == first).sum())
    first_txt = "הראשונה בתור" if first_n == 1 else f"הראשונות בתור — {n(first_n)} חברות —"
    return (f"{n(len(soon))} חברות צפויות להתחסל ב-{SOON_DAYS} הימים שאחרי {d_he(ref)} אם לא תוגש "
            f"התנגדות; {first_txt} ב-{d_he(first)}.")


def insight_batch(per_day, total):
    if len(per_day) < 10:
        return None
    top_day = per_day.sort_index().sort_values(ascending=False, kind="stable").index[0]
    top = int(per_day[top_day])
    med = float(per_day.median())
    if med <= 0 or top < 2 * med:
        return None
    return (f"האישורים ניתנים במנות: ביום העמוס ביותר, {d_he(top_day)}, אושרו {n(top)} בקשות "
            f"({pct(top / total * 100)} מהרשימה), לעומת חציון של {med:g} בקשות ביום אישור.")


def insight_pace(weekly, partial_last):
    """Last PACE_WEEKS full weeks vs the PACE_WEEKS before them."""
    w = weekly.iloc[:-1] if partial_last else weekly
    if len(w) < 2 * PACE_WEEKS:
        return None
    recent = int(w.iloc[-PACE_WEEKS:].sum())
    prev = int(w.iloc[-2 * PACE_WEEKS:-PACE_WEEKS].sum())
    if prev == 0:
        return None
    chg = recent / prev - 1
    note = " (לא כולל השבוע האחרון, החלקי)" if partial_last else ""
    idle = int((w.iloc[-2 * PACE_WEEKS:] == 0).sum())
    tail = ""
    if idle:
        tail = (f" בתקופה זו {'היה שבוע אחד' if idle == 1 else f'היו {idle} שבועות'} "
                f"ללא אישורים כלל.")
    if abs(chg) < 0.15:
        return (f"קצב האישורים יציב: {n(recent)} בקשות ב-{PACE_WEEKS} השבועות המלאים האחרונים{note}, "
                f"לעומת {n(prev)} ב-{PACE_WEEKS} השבועות שלפניהם.{tail}")
    word = "עלה" if chg > 0 else "ירד"
    return (f"קצב האישורים {word}: {n(recent)} בקשות ב-{PACE_WEEKS} השבועות המלאים האחרונים{note}, "
            f"לעומת {n(prev)} ב-{PACE_WEEKS} השבועות שלפניהם ({pct(abs(chg) * 100, 0)} "
            f"{'יותר' if chg > 0 else 'פחות'}).{tail}")


def insight_cities(cities, total, n_cities):
    known = cities.drop("לא צוין", errors="ignore")
    if known.empty:
        return None
    name, v = known.index[0], int(known.iloc[0])
    if v / total < 0.1:
        return None
    top5 = known.head(5).sum() / total
    return (f"{name} מובילה עם {n(v)} חברות ({pct(v / total * 100)}); חמש הערים המובילות "
            f"מרכזות {pct(top5 * 100)} מהרשימה, הפרושה על פני {n(n_cities)} ערים ויישובים.")


def insight_violators(df):
    total = len(df)
    v = int(df["violator"].sum())
    if total == 0 or v == 0:
        return None
    s = f"{n(v)} חברות ({pct(v / total * 100)}) מסומנות במרשם כ״מפרה״"
    ser = df[df["series"] != "אחר"]
    if not ser.empty:
        cut = sorted(ser["series"].unique())
        if len(cut) >= 4:
            mid = cut[len(cut) // 2]
            old = ser[ser["series"] < mid]
            new = ser[ser["series"] >= mid]
            if len(old) >= 30 and len(new) >= 30:
                so, sn = old["violator"].mean(), new["violator"].mean()
                old_rng = f"{cut[0]}–{max(old['series'])}"
                new_rng = f"{mid}–{cut[-1]}"
                if so - sn >= 0.05:
                    s += (f"; השיעור גבוה יותר בחברות הוותיקות (סדרות מספר {old_rng}: "
                          f"{pct(so * 100)}) מאשר בצעירות (סדרות {new_rng}: {pct(sn * 100)})")
                elif sn - so >= 0.05:
                    s += (f"; השיעור גבוה דווקא בחברות הצעירות (סדרות מספר {new_rng}: "
                          f"{pct(sn * 100)}) לעומת הוותיקות (סדרות {old_rng}: {pct(so * 100)})")
    return s + "."


def insight_stragglers(strag):
    k = len(strag)
    if k == 0:
        return None
    deleted = int(strag["flags"].map(lambda f: "מחוסלת עקב מחיקה" in f).sum())
    s = (f"{n(k)} חברות עדיין מופיעות ברשימה אף שמועד החיסול הצפוי שלהן כבר חלף "
         f"(המוקדם שבהם: {d_he(strag['expected'].min())})")
    if deleted:
        s += f"; {n(deleted)} מהן מסומנות גם ״מחוסלת עקב מחיקה״"
    return s + "."


def insight_status(status, total):
    active = int(status.get("פעילה", 0))
    if total == 0 or active / total < 0.5:
        return None
    rest = [(k, int(v)) for k, v in status.items() if k != "פעילה" and v > 0]
    tail = "; ".join(f"{n(v)} במעמד ״{k}״" for k, v in rest)
    return (f"{pct(active / total * 100)} מהחברות ברשימה עדיין במעמד ״פעילה״ — הבקשה אושרה אך "
            f"החיסול טרם הושלם" + (f"; {tail}" if tail else "") + ".")


# ------------------------------------------------------------------ helpers

def _top(counts, k):
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def compute(frames):
    df = _prepare(frames["main"])
    df = df[df["approved"].notna()].copy()
    total = len(df)
    ref = df["approved"].max()
    df["gap"] = (df["expected"] - df["approved"]).dt.days

    strag = df[df["expected"].notna() & (df["expected"] < ref)]
    core = df[~df.index.isin(strag.index)]

    # ---- timeline: weeks starting Sunday (months if the window ever grows)
    week_start = core["approved"] - pd.to_timedelta(sunday_dow(core["approved"]), unit="D")
    weeks = pd.date_range(week_start.min(), week_start.max(), freq="7D")
    weekly = week_start.value_counts().reindex(weeks, fill_value=0).sort_index()
    ref_dow = int((ref.dayofweek + 1) % 7)
    partial_last = ref_dow < 4          # latest approval before Thursday
    by_month = len(weekly) > MAX_WEEKS
    if by_month:
        per = core["approved"].dt.to_period("M")
        months = pd.period_range(per.min(), per.max(), freq="M")
        tl = per.value_counts().reindex(months, fill_value=0).sort_index()
        tl_labels = [f"{MONTHS_HE[p.month - 1]} {p.year}" for p in tl.index]
        tl_partial = not (ref + pd.Timedelta(days=1)).is_month_start
    else:
        tl = weekly
        tl_labels = [f"{d.day}.{d.month}" for d in tl.index]
        tl_partial = partial_last
    tl_vals = [int(v) for v in tl.values]
    peak_i = max(range(len(tl_vals)), key=lambda i: (tl_vals[i], -i)) if tl_vals else 0
    timeline = {"x": tl_labels, "y": tl_vals, "peak": peak_i,
                "partial": len(tl_vals) - 1 if tl_partial else -1}
    if by_month:
        tl_table = [{"label": tl_labels[i], "count": n(v)} for i, v in enumerate(tl_vals)]
    else:
        tl_table = [{"label": f"{d_short(d)}–{d_short(d + pd.Timedelta(days=6))}", "count": n(v)}
                    for d, v in zip(tl.index, tl_vals)]
    if tl_partial and tl_table:
        tl_table[-1]["label"] += " (חלקי)"

    # ---- weekday + week×weekday heatmap
    dow = sunday_dow(df["approved"])
    dow_counts = dow.value_counts()
    days_shown = [d for d in range(7) if d < 5 or dow_counts.get(d, 0) > 0]
    dow_vals = [int(dow_counts.get(d, 0)) for d in days_shown]
    core_dow = sunday_dow(core["approved"])
    heat_cells, heat_rows = [], []
    if not by_month:
        grid = pd.crosstab(week_start, core_dow).reindex(index=weeks, columns=days_shown, fill_value=0)
        for yi, (wk, row) in enumerate(grid.iterrows()):
            for xi, d in enumerate(days_shown):
                heat_cells.append([xi, yi, int(row[d])])
            heat_rows.append({"week": d_short(wk), "cells": [n(row[d]) for d in days_shown]})
    heat = {"x": [DAYS_HE[d] for d in days_shown],
            "y": [f"{d.day}.{d.month}" for d in weeks] if not by_month else [],
            "cells": heat_cells, "max": max([c[2] for c in heat_cells] or [1])}

    # ---- cities
    cities = df["city"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    n_cities = int((cities.index != "לא צוין").sum())
    c_names, c_vals = _top(cities, TOP_CITIES)

    # ---- status
    st = df["status"].value_counts()
    st_names = [s for s in STATUS_ORDER if s in st.index] + sorted(s for s in st.index if s not in STATUS_ORDER)
    st_vals = [int(st[s]) for s in st_names]
    flag_counts = pd.Series([f for lst in df["flags"] for f in lst], dtype=str).value_counts()
    flag_counts = flag_counts.sort_index().sort_values(ascending=False, kind="stable")
    status_series = pd.Series(st_vals, index=st_names)

    # ---- company-number series × violator share
    ser = df.groupby("series").agg(count=("num", "size"), viol=("violator", "sum")).sort_index()
    series_chart = {
        "x": list(ser.index),
        "count": [int(v) for v in ser["count"]],
        "share": [round(float(v / c * 100), 1) for v, c in zip(ser["viol"], ser["count"])],
    }

    # ---- profile flags
    profile_rows = [
        ("מסומנות ״מפרה״", int(df["violator"].sum())),
        ("רשומות גם בשם לועזי", int((df["en"] != "").sum())),
        ("כתובת ״אצל״ (צד שלישי)", int((df["co"] != "").sum())),
        ("כתובת ללא שם רחוב", int((df["street"] == "").sum())),
    ]
    profile = {"names": [k for k, _ in profile_rows],
               "values": [round(v / total * 100, 1) for _, v in profile_rows]}

    # ---- named tables
    nxt = (core[core["expected"].notna()]
           .sort_values(["expected", "approved", "num"], kind="stable").head(NEXT_UP))
    next_rows = [{"name": r["name"], "num": r["num"], "city": r["city"],
                  "approved": d_short(r["approved"]), "expected": d_short(r["expected"]),
                  "violator": "כן" if r["violator"] else "—"} for _, r in nxt.iterrows()]
    strag_sorted = strag.sort_values(["expected", "num"], kind="stable")
    strag_rows = [{"name": r["name"], "num": r["num"], "approved": d_short(r["approved"]),
                   "expected": d_short(r["expected"]), "status": r["status"],
                   "flags": "; ".join(r["flags"])}
                  for _, r in strag_sorted.head(STRAGGLERS_MAX).iterrows()]

    # ---- KPIs
    per_day = df.groupby(df["approved"]).size()
    fut = df[df["expected"] >= ref]
    soon = int((fut["expected"] < ref + pd.Timedelta(days=SOON_DAYS)).sum())
    last30 = int((df["approved"] > ref - pd.Timedelta(days=SOON_DAYS)).sum())
    viol_share = df["violator"].mean() * 100 if total else 0.0
    gap_mode = (int(df["gap"].dropna().value_counts().sort_index()
                    .sort_values(ascending=False, kind="stable").index[0])
                if df["gap"].notna().any() else None)
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "last30": {"value": last30, "display": n(last30), "tone": "info"},
        "soon": {"value": soon, "display": n(soon), "tone": "warn" if soon else "brand"},
        "violators": {"value": round(viol_share, 1), "display": f"{viol_share:.1f}%",
                      "tone": "warn" if viol_share >= 20 else "brand"},
    }

    rules = [
        ("window", insight_window(df["gap"])),
        ("soon", insight_soon(df, ref)),
        ("pace", insight_pace(weekly, partial_last)),
        ("batch", insight_batch(per_day, total)),
        ("cities", insight_cities(cities, total, n_cities)),
        ("violators", insight_violators(df)),
        ("status", insight_status(status_series, total)),
        ("stragglers", insight_stragglers(strag)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    first_core = core["approved"].min()
    gap_txt = f"{gap_mode} ימים" if gap_mode is not None else "פרק זמן קבוע"
    unit = "חודש" if by_month else "שבוע"
    peak_label = tl_table[peak_i]["label"] if tl_table else ""
    flags_txt = "; ".join(f"{k} — {n(v)}" for k, v in flag_counts.items())
    top_dow = days_shown[max(range(len(dow_vals)), key=lambda i: (dow_vals[i], -i))] if dow_vals else 0
    labels = {
        "lede": (f"רשימת החברות שבקשתן לפירוק מרצון בהליך מזורז אושרה על ידי רשם החברות וטרם חוסלו: "
                 f"{n(total)} חברות פרטיות ישראליות. אם לא תוגש התנגדות, כל חברה תחוסל {gap_txt} "
                 f"לאחר אישור הבקשה, ואז היא יוצאת מהרשימה — לכן הרשימה מכסה בעיקר את האישורים "
                 f"שבין {d_he(first_core)} ל-{d_he(ref)} (האישור האחרון במאגר)."),
        "ref_kpi": f"אושרו ב-{SOON_DAYS} הימים האחרונים (עד {d_short(ref)})",
        "soon_kpi": f"צפויות להתחסל ב-{SOON_DAYS} הימים הבאים",
        "total_kpi": "חברות ברשימה",
        "viol_kpi": "מהחברות מסומנות ״מפרה״",
        "tl_note": (f"בקשות שאושרו בכל {unit} (שבוע = ראשון עד שבת). הרשימה כוללת רק חברות שטרם "
                    f"חוסלו, ולכן אין בה אישורים ותיקים מחלון ההתנגדות."
                    + (f" לא כולל {n(len(strag))} חברות שמועד החיסול שלהן כבר חלף (ראו טבלה בהמשך)."
                       if len(strag) else "")
                    + (f" ה{unit} האחרון חלקי — עד {d_he(ref)}." if tl_partial else "")
                    + (f" שיא: {peak_label}, {n(tl_vals[peak_i])} בקשות." if tl_vals else "")),
        "tl_aria": (f"גרף עמודות: בקשות פירוק מזורז שאושרו בכל {unit}, מ-{d_he(first_core)} עד {d_he(ref)}. "
                    + (f"שיא של {n(tl_vals[peak_i])} בקשות ב{unit} {peak_label}." if tl_vals else "")),
        "tl_caption": f"מספר הבקשות שאושרו בכל {unit}.",
        "tl_col": "חודש" if by_month else "שבוע",
        "dow_note": (f"כל החברות ברשימה לפי יום האישור בשבוע. היום העמוס: יום {DAYS_HE[top_dow]}."),
        "dow_aria": f"גרף עמודות: בקשות שאושרו לפי יום בשבוע. היום העמוס ביותר: יום {DAYS_HE[top_dow]}.",
        "dow_caption": "מספר הבקשות שאושרו לפי יום בשבוע.",
        "heat_aria": "מפת חום: מספר האישורים לפי שבוע ויום בשבוע — מראה ימי אישור מרוכזים.",
        "heat_caption": "מספר האישורים בכל שבוע (שורה) ויום בשבוע (עמודה).",
        "cities_aria": (f"תרשים עמודות: {TOP_CITIES} הערים עם מספר החברות הגבוה ברשימה. "
                        f"מובילה: {c_names[0]} עם {n(c_vals[0])} חברות." if c_names else "תרשים ערים."),
        "cities_caption": f"מספר החברות לפי עיר הכתובת הרשומה ({TOP_CITIES} המובילות ואחר).",
        "cities_note": f"לפי עיר הכתובת הרשומה של החברה. {n(n_cities)} ערים ויישובים ברשימה.",
        "status_aria": (f"תרשים עמודות: חברות לפי מעמד במרשם. {st_names[0]}: {n(st_vals[0])}."
                        if st_names else "תרשים מעמד."),
        "status_caption": "מספר החברות לפי מעמד במרשם.",
        "status_note": ("מעמד החברה במרשם בזמן הפרסום. כל החברות נושאות את תת-הסטטוס ״בפרוק מרצון "
                        "בהליך מזורז״" + (f"; סימונים נוספים: {flags_txt}." if flags_txt else ".")),
        "series_aria": ("גרף משולב: מספר החברות לפי סדרת מספר החברה (עמודות) ושיעור החברות המסומנות "
                        "״מפרה״ בכל סדרה (קו)."),
        "series_caption": "מספר החברות ושיעור המסומנות ״מפרה״ לפי סדרת מספר החברה.",
        "profile_aria": "תרשים עמודות: שיעור החברות ברשימה בעלות כל מאפיין רישומי.",
        "profile_caption": "שיעור החברות בעלות כל מאפיין, מתוך כלל הרשימה.",
        "next_caption": f"{NEXT_UP} החברות שמועד החיסול הצפוי שלהן הקרוב ביותר, החל מ-{d_short(ref)}.",
        "next_note": (f"החברות הבאות בתור לחיסול (מ-{d_he(ref)} והלאה), אם לא תוגש התנגדות עד המועד."),
        "strag_caption": "חברות שמועד החיסול הצפוי שלהן חלף והן עדיין ברשימה.",
        "strag_note": (f"{n(len(strag))} חברות שמועד החיסול הצפוי שלהן קודם ל-{d_he(ref)} ועדיין מופיעות ברשימה"
                       + (f" (מוצגות {STRAGGLERS_MAX} הראשונות)." if len(strag) > STRAGGLERS_MAX else ".")),
    }

    tables = {
        "timeline": tl_table,
        "dow": [{"day": DAYS_HE[d], "count": n(v)} for d, v in zip(days_shown, dow_vals)],
        "heat": heat_rows,
        "cities": [{"name": k, "count": n(v)} for k, v in zip(c_names, c_vals)],
        "status": [{"name": k, "count": n(v)} for k, v in zip(st_names, st_vals)],
        "series": [{"series": x, "count": n(c), "share": f"{s:.1f}%"}
                   for x, c, s in zip(series_chart["x"], series_chart["count"], series_chart["share"])],
        "profile": [{"name": k, "count": n(v), "share": f"{v / total * 100:.1f}%"} for k, v in profile_rows],
        "next": next_rows,
        "stragglers": strag_rows,
    }

    charts = {
        "timeline": timeline,
        "dow": {"names": [DAYS_HE[d] for d in days_shown], "values": dow_vals},
        "heat": heat,
        "cities": {"names": c_names, "values": c_vals},
        "status": {"names": st_names, "values": st_vals},
        "series": series_chart,
        "profile": profile,
    }

    return {
        "agent_data": {
            "summary_he": (f"{n(total)} חברות פרטיות שבקשתן לפירוק מרצון בהליך מזורז אושרה וטרם חוסלו; "
                           f"{n(soon)} צפויות להתחסל ב-{SOON_DAYS} הימים הבאים אם לא תוגש התנגדות. "
                           f"נכון לאישור האחרון, {d_he(ref)}."),
            "dataset_kind": "registry",
            "related_ids": ["3111ae54-790a-4d02-9750-d51e1134b405",
                            "6d8bf87d-bd13-4df6-9846-d449f407b318"],
            "suggested_tags": ["פירוק חברות", "פירוק מרצון", "רשם החברות", "חיסול", "הליך מזורז"],
            "temporal_coverage": f"{df['approved'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"heat": bool(heat_cells), "stragglers": bool(strag_rows)},
    }
