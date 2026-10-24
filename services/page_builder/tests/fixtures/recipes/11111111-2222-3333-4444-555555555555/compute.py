"""Monthly events per district — reference recipe (tests + authoring example).

Every number on the page comes from here. Insight rules each return a
sentence or None; a rule whose premise no longer holds in the data drops
out rather than asserting something false.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _prepare(df):
    df = df.copy()
    df["year"] = pd.to_numeric(df["שנה"], errors="coerce")
    df["month"] = pd.to_numeric(df["חודש"], errors="coerce")
    df["n"] = pd.to_numeric(df["מספר אירועים"].str.replace(",", ""), errors="coerce")
    df["district"] = df["מחוז"].str.strip()
    df = df.dropna(subset=["year", "month", "n"])
    df = df[df["district"] != ""]
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    return df


def insight_trend(yearly):
    """Direction of the last full-year change; wording follows the sign."""
    if len(yearly) < 2:
        return None
    (y0, v0), (y1, v1) = list(yearly.items())[-2:]
    if v0 == 0:
        return None
    change = (v1 - v0) / v0
    if abs(change) < 0.02:
        return f"מספר האירועים ב-{y1} ({_int(v1)}) נותר כמעט ללא שינוי לעומת {y0}."
    word = "עלייה" if change > 0 else "ירידה"
    return (f"ב-{y1} נרשמו {_int(v1)} אירועים — {word} של "
            f"{abs(change) * 100:.1f}% לעומת {y0} ({_int(v0)}).")


def insight_top_district(by_district, total):
    if by_district.empty or total == 0:
        return None
    name, v = by_district.index[0], by_district.iloc[0]
    share = v / total
    if share < 0.2:
        return None  # no district stands out — don't claim one does
    return f"מחוז {name} מוביל עם {_int(v)} אירועים, {share * 100:.1f}% מכלל האירועים."


def insight_peak_month(by_month):
    if by_month.empty:
        return None
    m = int(by_month.idxmax())
    return f"החודש העמוס ביותר לאורך כל השנים הוא {MONTHS_HE[m - 1]}."


def compute(frames):
    df = _prepare(frames["events"])
    total = int(df["n"].sum())
    # Explicit sorts everywhere: the model must not depend on row order.
    yearly = df.groupby("year")["n"].sum().sort_index()
    # Ties broken by name (sort_index first, then a STABLE value sort).
    by_district = (df.groupby("district")["n"].sum()
                   .sort_index().sort_values(ascending=False, kind="stable"))
    by_month = df.groupby("month")["n"].sum().sort_index()
    y_min, y_max = int(yearly.index.min()), int(yearly.index.max())

    rules = [
        ("trend", insight_trend(yearly)),
        ("top_district", insight_top_district(by_district, total)),
        ("peak_month", insight_peak_month(by_month)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    return {
        "agent_data": {
            "summary_he": (f"מספר האירועים החודשי לפי מחוז, {y_min}–{y_max}: "
                           f"{_int(total)} אירועים ב-{by_district.size} מחוזות."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["אירועים", "מחוזות"],
            "temporal_coverage": f"{y_min}/{y_max}",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total)},
            "years": {"value": [y_min, y_max], "display": f"{y_min}–{y_max}"},
            "districts": {"value": int(by_district.size), "display": _int(by_district.size)},
        },
        "charts": {
            "yearly": {"x": [str(y) for y in yearly.index], "y": [int(v) for v in yearly]},
            "districts": {"names": list(by_district.index),
                          "values": [int(v) for v in by_district]},
        },
        "insights": insights,
        "labels": {
            "yearly_aria": (f"גרף קו: מספר האירועים לפי שנה, {y_min} עד {y_max}. "
                            f"השיא ב-{int(yearly.idxmax())} עם {_int(yearly.max())} אירועים."),
            "districts_aria": f"תרשים עמודות: מספר האירועים ב-{by_district.size} מחוזות.",
        },
    }
