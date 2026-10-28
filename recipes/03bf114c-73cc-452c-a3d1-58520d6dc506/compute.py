"""צווי נגישות — accessibility orders issued by the Commission for Equal Rights
of Persons with Disabilities.

One row per defect found in an inspection case; a case ("מספר תיק בקרה") is
one order to one obligated party. Exact duplicate rows are dropped. "~" in the
source stands for a quote mark (בע~מ = בע"מ). The obligated parties are public
bodies and businesses, sole traders included, and are named. "Now" = the
latest order date in the data — the page states it, since the register can
stop being updated while the file keeps being re-published.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
TOP_N = 12
TOP_DEBTORS = 10
DEFECT_BUCKETS = [(1, 2, "ליקוי אחד"), (2, 4, "2–3"), (4, 8, "4–7"), (8, 16, "8–15"),
                  (16, 41, "16–40"), (41, 100000, "מעל 40")]
LAG_BUCKETS = [(0, 91, "עד שלושה חודשים"), (91, 181, "3–6 חודשים"), (181, 366, "חצי שנה–שנה"),
               (366, 731, "שנה–שנתיים"), (731, 100000, "מעל שנתיים")]
CATEGORY_ORDER = ["רשות מקומית", "עמותה / חל״צ", "חברה", "גוף ממשלתי", "אחר / עוסק"]
CATEGORY_TO = {"רשות מקומית": "לרשויות מקומיות", "עמותה / חל״צ": "לעמותות ולחברות לתועלת הציבור",
               "חברה": "לחברות", "גוף ממשלתי": "לגופים ממשלתיים", "אחר / עוסק": "לעוסקים ולגורמים אחרים"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _txt(s):
    return s.str.replace("~", "\"", regex=False).str.replace(r"\s+", " ", regex=True).str.strip()


def _category(name, cities=frozenset()):
    """Local authorities include religious councils (מ. ד.) and municipalities
    listed by their bare city name."""
    n = name.replace("״", "\"")
    if n.startswith(("עירית", "עיריית", "מ. מ.", "מ.מ.", "מ. א.", "מ.א.", "מ. ד.", "מועצה", "איגוד ערים")) \
            or n in cities:
        return "רשות מקומית"
    if any(k in n for k in ("חל\"צ", "ע\"ר", "עמותה", "עמותת")):
        return "עמותה / חל״צ"
    if "בע\"מ" in n or "בעמ" in n:
        return "חברה"
    if n.startswith(("משרד", "רשות", "מדינת ישראל")):
        return "גוף ממשלתי"
    return "אחר / עוסק"


def _prepare(df):
    df = df.drop_duplicates()
    out = pd.DataFrame({
        "case": df["מספר תיק בקרה"].str.strip(),
        "debtor": _txt(df["גורם חייב"]),
        "ordered": pd.to_datetime(df["תאריך  משלוח צו"], format="%d/%m/%Y", errors="coerce"),
        "doc": _txt(df["סוג מסמך"]),
        "etype": _txt(df["סוג ישות מפוקחת"]).str.replace(r"\s+V$", "", regex=True),
        "inspected": pd.to_datetime(df["תאריך ושעת פיקוח"].str.slice(0, 10), format="%d/%m/%Y", errors="coerce"),
        "city": _txt(df["ישוב"]).str.replace(r"\s*-\s*", "-", regex=True),
        "component": _txt(df["רכיב נגישות לקוי"]).str.replace(r"^\(\S\)\s*", "", regex=True),
    })
    out = out[out["case"] != ""]
    return out.sort_values(["case", "ordered", "doc", "component"], kind="stable").reset_index(drop=True)


def _cases(df):
    """One row per case: first order date, its debtor/type/city, defect count."""
    g = df.groupby("case", sort=True)
    cases = pd.DataFrame({
        "ordered": g["ordered"].min(),
        "inspected": g["inspected"].min(),
        "debtor": g["debtor"].first(),
        "etype": g["etype"].first(),
        "city": g["city"].agg(lambda s: next((v for v in s if v), "")),
        "doc": g["doc"].agg(lambda s: next((v for v in s if not v.startswith(("הארכה", "מכתב"))), s.iloc[0])),
        "defects": g.size(),
        "extended": g["doc"].agg(lambda s: s.str.contains("הארכה").any()),
    })
    cities = frozenset(c for c in df["city"].unique() if c)
    cases["category"] = cases["debtor"].map(lambda d: _category(d, cities))
    return cases


def _top(series, n, other):
    vc = series.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    return list(top.index) + ([other] if rest else []), [int(v) for v in top] + ([rest] if rest else [])


def _rows(names, values, total):
    return [{"name": a, "n": _int(b), "share": f"{b / total * 100:.1f}" if total else "0"}
            for a, b in zip(names, values)]


def compute(frames):
    df = _prepare(frames["orders"])
    cases = _cases(df)
    n_cases, n_def = len(cases), len(df)
    anchor = cases["ordered"].max()
    y = cases["ordered"].dt.year
    years = list(range(int(y.min()), int(anchor.year) + 1))
    per_year = y.value_counts()

    # Orders + defects per year
    def_year = df.groupby(df["case"].map(cases["ordered"].dt.year)).size()
    yearly = {"x": [str(v) for v in years], "cases": [int(per_year.get(v, 0)) for v in years],
              "defects": [int(def_year.get(v, 0)) for v in years]}
    year_rows = [{"year": str(v), "n": _int(per_year.get(v, 0)), "d": _int(def_year.get(v, 0))} for v in years]

    # Categories, entity types, components, cities, debtors
    cat = cases["category"].value_counts()
    cat_names = [c for c in CATEGORY_ORDER if c in cat.index]
    cat_chart = {"names": cat_names, "values": [int(cat[c]) for c in cat_names]}
    et_names, et_vals = _top(cases["etype"], TOP_N, "סוגים אחרים")
    comp_names, comp_vals = _top(df["component"][df["component"] != ""], TOP_N + 3, "רכיבים אחרים")
    city_names, city_vals = _top(cases["city"][cases["city"] != ""], TOP_N, "יישובים אחרים")
    debt = cases.groupby("debtor").agg(n=("defects", "size"), d=("defects", "sum"))
    debt = debt.sort_index().sort_values(["n", "d"], ascending=False, kind="stable").head(TOP_DEBTORS)
    debtors = {"names": list(debt.index), "cases": [int(v) for v in debt["n"]], "defects": [int(v) for v in debt["d"]]}
    biz = cases[cases["category"].isin(["חברה", "אחר / עוסק"])].groupby("debtor").agg(
        n=("defects", "size"), d=("defects", "sum"))
    biz = biz.sort_index().sort_values(["n", "d"], ascending=False, kind="stable").head(TOP_DEBTORS)
    biz_chart = {"names": list(biz.index), "cases": [int(v) for v in biz["n"]], "defects": [int(v) for v in biz["d"]]}

    # Defects per case + inspection→order lag
    defects_per_case = {"names": [b[2] for b in DEFECT_BUCKETS],
                        "values": [int(((cases["defects"] >= lo) & (cases["defects"] < hi)).sum())
                                   for lo, hi, _ in DEFECT_BUCKETS]}
    lagged = cases[cases["inspected"].notna() & (cases["ordered"] >= cases["inspected"])]
    lag_days = (lagged["ordered"] - lagged["inspected"]).dt.days
    lag = {"names": [b[2] for b in LAG_BUCKETS],
           "values": [int(((lag_days >= lo) & (lag_days < hi)).sum()) for lo, hi, _ in LAG_BUCKETS]}

    # Component mix by category (heatmap, % of the category's defects)
    df["category"] = df["case"].map(cases["category"])
    comp_top = [c for c in comp_names if c != "רכיבים אחרים"][:10]
    cells = []
    for ci, c in enumerate(cat_names):
        sub = df[df["category"] == c]
        for ki, k in enumerate(comp_top):
            cells.append([ki, ci, round(float((sub["component"] == k).mean()) * 100, 1), int(len(sub))])
    heat = {"components": comp_top, "categories": cat_names, "cells": cells}

    # Insights ------------------------------------------------------------
    def ins_latest():
        return (f"הצו האחרון במאגר נשלח ב-{d_he(anchor)}; בסך הכול {_int(n_cases)} צווים "
                f"עם {_int(n_def)} ליקויי נגישות מ-{years[0]}.")

    def ins_peak():
        full = [v for v in years if v < anchor.year]
        if len(full) < 3:
            return None
        peak = max(full, key=lambda v: (per_year.get(v, 0), -v))
        last = full[-1]
        if peak == last:
            return f"{last} הייתה השנה עם הכי הרבה צווים ({_int(per_year.get(last, 0))})."
        return (f"השיא היה ב-{peak} עם {_int(per_year.get(peak, 0))} צווים; ב-{last} נשלחו "
                f"{_int(per_year.get(last, 0))}.")

    def ins_category():
        if len(cat) < 2:
            return None
        top = cat.sort_index().sort_values(ascending=False, kind="stable")
        return (f"{_pct(top.iloc[0] / n_cases)} מהצווים הופנו {CATEGORY_TO[top.index[0]]}, "
                f"ו-{_pct(top.iloc[1] / n_cases)} {CATEGORY_TO[top.index[1]]}.")

    def ins_component():
        comp = df["component"][df["component"] != ""].value_counts().sort_index().sort_values(ascending=False, kind="stable")
        if len(comp) < 3:
            return None
        return (f"הליקוי הנפוץ ביותר: {comp.index[0]} ({_int(comp.iloc[0])} פעמים), ואחריו "
                f"{comp.index[1]} ו{comp.index[2]}.")

    def ins_debtor():
        if debt.empty:
            return None
        name = debt.index[0]
        return (f"הגורם עם הכי הרבה צווים: {name} — {_int(debt['n'].iloc[0])} צווים ו-"
                f"{_int(debt['d'].iloc[0])} ליקויים.")

    def ins_defects():
        med = float(cases["defects"].median())
        big = int((cases["defects"] > 40).sum())
        tail = f"; ב-{_int(big)} צווים נמצאו יותר מארבעים ליקויים" if big else ""
        return f"חציון הליקויים בצו הוא {med:.0f}{tail}."

    def ins_lag():
        if len(lag_days) < 50:
            return None
        return (f"חציון הזמן מהפיקוח ועד משלוח הצו: {lag_days.median():.0f} ימים "
                f"(על פי {_int(len(lag_days))} צווים עם תאריך פיקוח).")

    def ins_extended():
        ext = int(cases["extended"].sum())
        if ext < 10:
            return None
        return f"{_int(ext)} צווים ({_pct(ext / n_cases)}) קיבלו הארכת מועד ליישום."

    rules = [("latest", ins_latest()), ("peak", ins_peak()), ("category", ins_category()),
             ("component", ins_component()), ("debtor", ins_debtor()), ("defects", ins_defects()),
             ("lag", ins_lag()), ("extended", ins_extended())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    return {
        "agent_data": {
            "summary_he": (f"{_int(n_cases)} צווי נגישות שהוציאה נציבות שוויון זכויות לאנשים עם מוגבלות "
                           f"מ-{years[0]} ועד {d_he(anchor)}, עם {_int(n_def)} ליקויים: מי, איפה ומה לא היה נגיש."),
            "dataset_kind": "registry",
            "suggested_tags": ["נגישות", "אנשים עם מוגבלות", "אכיפה", "רשויות מקומיות"],
            "related_ids": ["49f21b3f-3ffc-43d1-b8c8-d9abad2ace9a"],
            "temporal_coverage": f"{cases['ordered'].min().strftime('%Y-%m-%d')}/{anchor.strftime('%Y-%m-%d')}",
        },
        "kpis": {
            "cases": {"value": n_cases, "display": _int(n_cases), "tone": "brand"},
            "defects": {"value": n_def, "display": _int(n_def), "tone": "brand"},
            "debtors": {"value": int(cases["debtor"].nunique()),
                        "display": _int(cases["debtor"].nunique()), "tone": "brand"},
            # The data's own "as of" date — context, not a good/bad state.
            "latest": {"value": anchor.strftime("%Y-%m-%d"),
                       "display": f"{anchor.day}.{anchor.month}.{anchor.year}", "tone": "info"},
        },
        "charts": {"yearly": yearly, "category": cat_chart,
                   "etype": {"names": et_names, "values": et_vals},
                   "component": {"names": comp_names, "values": comp_vals},
                   "city": {"names": city_names, "values": city_vals},
                   "debtors": debtors, "biz": biz_chart, "defects": defects_per_case, "lag": lag, "heat": heat},
        "tables": {
            "years": year_rows,
            "category": _rows(cat_chart["names"], cat_chart["values"], n_cases),
            "etype": _rows(et_names, et_vals, n_cases),
            "component": _rows(comp_names, comp_vals, int(sum(comp_vals))),
            "city": _rows(city_names, city_vals, int(sum(city_vals))),
            "debtors": [{"name": a, "n": _int(b), "d": _int(c)} for a, b, c in
                        zip(debtors["names"], debtors["cases"], debtors["defects"])],
            "biz": [{"name": a, "n": _int(b), "d": _int(c)} for a, b, c in
                    zip(biz_chart["names"], biz_chart["cases"], biz_chart["defects"])],
            "defects": _rows(defects_per_case["names"], defects_per_case["values"], n_cases),
            "lag": _rows(lag["names"], lag["values"], len(lag_days)),
        },
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n_cases)} צווי נגישות ל-{_int(cases['debtor'].nunique())} גורמים, "
                     f"מ-{d_he(cases['ordered'].min())} ועד {d_he(anchor)}. כל צו מפרט ליקויים שנמצאו בפיקוח; "
                     f"{_int(n_def)} ליקויים בסך הכול."),
            "yearly_note": f"לפי שנת משלוח הצו הראשון בתיק. הצו האחרון במאגר נשלח ב-{d_he(anchor)}.",
            "category_note": "סיווג לפי שם הגורם החייב: רשות מקומית, עמותה או חברה לתועלת הציבור, חברה, גוף ממשלתי, או אחר (כולל עוסקים).",
            "city_note": f"צווים לפי יישוב המקום שנבדק ({_int((cases['city'] != '').sum())} צווים עם יישוב).",
            "lag_note": f"ימים מתאריך הפיקוח ועד משלוח הצו ({_int(len(lag_days))} צווים).",
            "yearly_aria": f"עמודות וקו: צווים וליקויים לפי שנה, {years[0]} עד {anchor.year}.",
            "category_aria": "עמודות: צווים לפי סוג הגורם החייב.",
            "etype_aria": "עמודות אופקיות: צווים לפי סוג המקום שנבדק.",
            "component_aria": "עמודות אופקיות: רכיבי הנגישות הלקויים הנפוצים.",
            "city_aria": "עמודות אופקיות: צווים לפי יישוב.",
            "debtors_aria": f"עמודות אופקיות: {TOP_DEBTORS} הגורמים עם הכי הרבה צווים.",
            "biz_aria": f"עמודות אופקיות: {TOP_DEBTORS} החברות והעוסקים עם הכי הרבה צווים וליקויים.",
            "defects_aria": "עמודות: צווים לפי מספר הליקויים בצו.",
            "lag_aria": "עמודות: צווים לפי הזמן מהפיקוח ועד משלוח הצו.",
            "heat_aria": "מפת חום: שיעור כל רכיב לקוי מתוך ליקויי כל סוג גורם.",
        },
    }
