"""סנקציות על פי חוק כפיית ציות: בתי הדין הרבניים.

The resource is a pivot table: one row per sanction type (צו הגבלה), one
column per year (2008, 2009, ...), cells = number of sanctions of that type
the rabbinical courts issued that year, blank = none. A "Grand Total" row
closes the table; it is dropped and every total is recomputed from the type
rows. The earliest years carry a generic "סנקציה" row (type not recorded).

Growth: a new year arrives as a new column. Year columns are detected by
name (a four-digit year), so the page follows them without a recipe change;
trailing year columns with no numbers yet are ignored. New sanction types
flow through the keyword grouping, with an "אחר" fallback group.

Provisional latest year: the table has no months, so a year column published
mid-year can't be detected exactly. Heuristic: the latest year is treated as
provisional when its total is below PARTIAL_RATIO x the median of the three
previous years' totals (needs >= 4 years). A provisional year is still drawn
in the year-based charts and tables (labelled "(חלקית?)", with a note), and it
counts in the all-years totals, but every year-over-year comparison (trend,
peak, 5-year periods, change KPI, latest-year KPIs, dumbbell, latest mix,
riser, breadth) and the yearly average use the last non-provisional year.
"""
import re

import pandas as pd

LABEL_COL = "סנקציות/שנת נתינת הסנקציות"
YEAR_RE = re.compile(r"^\s*((?:19|20)\d{2})\s*$")

G_CIVIL = "הגבלות אזרחיות"
G_PRISON = "הגבלות על אסיר כלוא"
G_ISO = "הכנסה לבידוד"
G_UNCL = "ללא פירוט סוג"
G_OTHER = "אחר"
GROUP_ORDER = [G_CIVIL, G_PRISON, G_ISO, G_UNCL, G_OTHER]
CIVIL_KEYS = ("נהיגה", "דרכון", "יציאה", "בנק", "כהונה", "מקצוע", "עיסוק", "גמלה", "רישיון")

NOTES = "סנקציות על פי חוק כפיית ציות בין השנים 2008 ל-2024"

TOP_TYPES = 14
TOP_HEAT = 15
TOP_MIX = 7
TOP_CHANGE = 12
MAX_CIVIL_LINES = 8
PARTIAL_RATIO = 0.5


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _signed_pct(x):
    s = f"{abs(x) * 100:.1f}%"
    if round(abs(x) * 1000) == 0:
        return "0.0%"
    return ("+" if x > 0 else "−") + s


def _clean_name(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def classify(name):
    n = name
    if n in ("סנקציה", "סנקציות"):
        return G_UNCL
    if "בידוד" in n and "הכנסה" in n:
        return G_ISO
    if any(k in n for k in ("אסיר", "בכלא", "שחרור")):
        return G_PRISON
    if any(k in n for k in CIVIL_KEYS):
        return G_CIVIL
    return G_OTHER


def _is_total_row(name):
    low = name.lower()
    return low in ("grand total", "total") or name.startswith("סה\"כ") or name.startswith("סה״כ") \
        or name.startswith("סך הכל") or name.startswith("סך הכול")


def _matrix(df):
    year_cols = []
    for c in df.columns:
        m = YEAR_RE.match(str(c))
        if m:
            year_cols.append((int(m.group(1)), c))
    year_cols.sort()
    names = df[LABEL_COL].map(_clean_name)
    data = {}
    for y, c in year_cols:
        s = df[c].astype(str).str.replace(",", "", regex=False).str.strip()
        data[y] = pd.to_numeric(s, errors="coerce").fillna(0)
    m = pd.DataFrame(data)
    m.index = names.values
    keep = [(nm != "") and not _is_total_row(nm) for nm in m.index]
    m = m[keep]
    m = m.groupby(level=0).sum()
    m = m.sort_index()
    # Drop leading/trailing year columns that hold no numbers yet.
    col_tot = m.sum(axis=0)
    nz = [y for y in m.columns if col_tot[y] > 0]
    if nz:
        m = m[[y for y in m.columns if nz[0] <= y <= nz[-1]]]
    m = m[m.sum(axis=1) > 0]
    return m.round().astype(int)


def _short(name, n=34):
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- insights

def insight_trend(yearly):
    if len(yearly) < 2:
        return None
    y0, y1 = yearly.index[-2], yearly.index[-1]
    v0, v1 = yearly.iloc[-2], yearly.iloc[-1]
    if v0 == 0:
        return None
    ch = (v1 - v0) / v0
    if abs(ch) < 0.03:
        return (f"ב-{y1} ניתנו {_int(v1)} סנקציות, כמעט ללא שינוי לעומת {y0} ({_int(v0)}).")
    word = "עלייה" if ch > 0 else "ירידה"
    return (f"ב-{y1} ניתנו {_int(v1)} סנקציות, {word} של {_pct(abs(ch))} "
            f"לעומת {y0} ({_int(v0)}).")


def insight_peak(yearly):
    if len(yearly) < 3:
        return None
    peak_y = int(yearly.idxmax())
    peak_v = int(yearly.max())
    y1 = int(yearly.index[-1])
    v1 = int(yearly.iloc[-1])
    if peak_y == y1:
        return (f"{y1} היא שנת השיא בנתונים, עם {_int(v1)} סנקציות, "
                f"יותר מכל שנה קודמת מאז {int(yearly.index[0])}.")
    gap = (peak_v - v1) / peak_v
    return (f"שנת השיא היא {peak_y}, עם {_int(peak_v)} סנקציות. "
            f"ב-{y1} ניתנו {_int(v1)}, {_pct(gap)} פחות מהשיא.")


def insight_periods(yearly):
    n = len(yearly)
    if n < 10:
        return None
    last = yearly.iloc[-5:]
    prev = yearly.iloc[-10:-5]
    a, b = prev.mean(), last.mean()
    if a == 0:
        return None
    ch = (b - a) / a
    ys = (f"{int(last.index[0])}-{int(last.index[-1])}", f"{int(prev.index[0])}-{int(prev.index[-1])}")
    if abs(ch) < 0.05:
        return (f"בממוצע ניתנו {b:,.0f} סנקציות בשנה ב-{ys[0]}, "
                f"בדומה לחמש השנים שלפני כן ({ys[1]}: {a:,.0f} בשנה).")
    word = "יותר" if ch > 0 else "פחות"
    return (f"בחמש השנים {ys[0]} ניתנו בממוצע {b:,.0f} סנקציות בשנה, "
            f"{_pct(abs(ch))} {word} מאשר ב-{ys[1]} ({a:,.0f} בשנה).")


def insight_leader(by_type, total):
    if len(by_type) < 2 or total == 0:
        return None
    n1, v1 = by_type.index[0], int(by_type.iloc[0])
    n2, v2 = by_type.index[1], int(by_type.iloc[1])
    if v1 / total < 0.1:
        return None
    return (f"הסנקציה הנפוצה ביותר היא \"{n1}\": {_int(v1)} צווים, "
            f"{_pct(v1 / total)} מכלל הסנקציות. אחריה \"{n2}\" עם {_int(v2)}.")


def insight_civil(group_tot):
    classified = sum(v for g, v in group_tot.items() if g != G_UNCL)
    civ = group_tot.get(G_CIVIL, 0)
    if classified == 0 or civ / classified < 0.5:
        return None
    pr = group_tot.get(G_PRISON, 0) + group_tot.get(G_ISO, 0)
    tail = ""
    if pr > 0:
        tail = (f" הגבלות על אסירים כלואים ובידוד מהווים {_pct(pr / classified)} "
                f"({_int(pr)} צווים).")
    return (f"רוב הסנקציות שסוגן מפורט הן הגבלות אזרחיות על מי שאינו כלוא "
            f"(כגון רישיון נהיגה, דרכון, יציאה מהארץ וחשבון בנק): "
            f"{_int(civ)} צווים, {_pct(civ / classified)}.{tail}")


def insight_new_prison(first_year, groups, m):
    """Waves of new prisoner restrictions: years where >=3 prison types first appear."""
    pr = [t for t in first_year.index if groups[t] == G_PRISON]
    if not pr:
        return None
    fy = first_year[pr].astype(int)
    counts = fy.value_counts().sort_index()
    waves = [(int(y), int(k)) for y, k in counts.items() if k >= 3 and int(y) != int(m.columns[0])]
    if not waves:
        return None
    y_last = waves[-1][0]
    names = sorted([t for t in pr if int(fy[t]) == y_last],
                   key=lambda t: (-int(m.loc[t].sum()), t))
    ex = ", ".join(f"\"{t}\"" for t in names[:2])
    if len(waves) == 1:
        y, k = waves[0]
        return (f"ב-{y} הופיעו לראשונה {k} סוגים חדשים של הגבלות על אסירים כלואים, "
                f"ביניהם {ex}.")
    parts = [f"{k} סוגים ב-{y}" for y, k in waves]
    lst = ", ".join(parts[:-1]) + " ו-" + parts[-1]
    return (f"הגבלות על אסירים כלואים נוספו בגלים: {lst}. "
            f"בגל האחרון נוספו, בין השאר, {ex}.")


def insight_riser(m):
    if m.shape[1] < 2:
        return None
    y0, y1 = m.columns[-2], m.columns[-1]
    best = None
    for t in sorted(m.index):
        a, b = int(m.loc[t, y0]), int(m.loc[t, y1])
        inc = b - a
        if inc < 3 or (a > 0 and inc / a < 0.5):
            continue
        if best is None or inc > best[1]:
            best = (t, inc, a, b)
    if best is None:
        return None
    t, inc, a, b = best
    if a == 0:
        return f"הסנקציה \"{t}\" ניתנה ב-{y1} {_int(b)} פעמים, אחרי שב-{y0} לא ניתנה כלל."
    return (f"הזינוק הבולט ב-{y1}: הסנקציה \"{t}\" ניתנה {_int(b)} פעמים, "
            f"לעומת {_int(a)} ב-{y0}.")


def insight_uncl(m, groups):
    rows = [t for t in m.index if groups[t] == G_UNCL]
    if not rows:
        return None
    s = m.loc[rows].sum(axis=0)
    ys = [int(y) for y in s.index if s[y] > 0]
    if not ys:
        return None
    tot = int(s.sum())
    span = f"ב-{ys[0]}" if ys[0] == ys[-1] else f"בשנים {ys[0]}-{ys[-1]}"
    return (f"{span} נרשמו {_int(tot)} סנקציות ללא פירוט סוג ההגבלה, "
            f"ולכן הפילוח לפי סוג מלא רק מהשנים שאחריהן.")


def insight_breadth(n_used):
    if len(n_used) < 3:
        return None
    y1 = int(n_used.index[-1])
    v1 = int(n_used.iloc[-1])
    mx = int(n_used.max())
    my = int(n_used.idxmax())
    if v1 == mx:
        return f"ב-{y1} הופעלו {v1} סוגי סנקציות שונים, המגוון הרחב ביותר בנתונים."
    return (f"ב-{y1} הופעלו {v1} סוגי סנקציות שונים, לעומת {mx} בשיא המגוון ({my}).")


# ---------------------------------------------------------------- compute

def compute(frames):
    m = _matrix(frames["main"])
    years = [int(y) for y in m.columns]
    types = list(m.index)
    groups = {t: classify(t) for t in types}
    yearly = m.sum(axis=0)
    yearly.index = years
    m.columns = years
    total = int(yearly.sum())
    y_min, y_max = years[0], years[-1]

    # Provisional latest year (see module docstring).
    prov = False
    if len(years) >= 4:
        med = float(yearly.iloc[-4:-1].median())
        if med > 0 and float(yearly.iloc[-1]) < PARTIAL_RATIO * med:
            prov = True
    yc = yearly.iloc[:-1] if prov else yearly
    mc = m[list(yc.index)]
    n_used_c = (mc > 0).sum(axis=0)
    ys = [str(y) for y in years]
    if prov:
        ys[-1] = f"{years[-1]} (חלקית?)"

    by_type = m.sum(axis=1).sort_index().sort_values(ascending=False, kind="stable")
    first_year = (m > 0).idxmax(axis=1)
    n_used = (m > 0).sum(axis=0)
    present_groups = [g for g in GROUP_ORDER if any(groups[t] == g for t in types)]
    gy = {g: m.loc[[t for t in types if groups[t] == g]].sum(axis=0) for g in present_groups}
    group_tot = {g: int(gy[g].sum()) for g in present_groups}

    y1 = int(yc.index[-1])
    y0 = int(yc.index[-2]) if len(yc) >= 2 else None
    v1 = int(yearly[y1])
    v0 = int(yearly[y0]) if y0 is not None else 0

    # 1. yearly totals
    peak_y = int(yc.idxmax())
    avg = float(yc.mean())
    chart_yearly = {"x": ys, "y": [int(v) for v in yearly], "peak": years.index(peak_y),
                    "avg": round(avg, 1), "prov": (len(years) - 1) if prov else -1}

    # 2. groups per year
    chart_groups = {"x": ys, "series": [{"name": g, "data": [int(gy[g][y]) for y in years]}
                                        for g in present_groups]}
    table_groups = [{"year": ys[i], "vals": [_int(gy[g][y]) for g in present_groups],
                     "total": _int(yearly[y])} for i, y in enumerate(years)]

    # 3. ranking by type (top-N + other)
    top = by_type.iloc[:TOP_TYPES]
    rest = by_type.iloc[TOP_TYPES:]
    t_names = list(top.index)
    t_vals = [int(v) for v in top]
    t_groups = [groups[t] for t in t_names]
    if len(rest):
        t_names.append(f"סוגים אחרים ({len(rest)})")
        t_vals.append(int(rest.sum()))
        t_groups.append("")
    chart_types = {"names": t_names, "values": t_vals, "groups": t_groups,
                   "other": bool(len(rest))}
    table_types = [{"name": t, "group": groups[t], "total": _int(by_type[t]),
                    "share": _pct(by_type[t] / total) if total else "0.0%",
                    "first": str(int(first_year[t]))} for t in by_type.index]

    # 4. heatmap type x year (top-N + other)
    heat_top = list(by_type.index[:TOP_HEAT])
    heat_rows = [(t, m.loc[t]) for t in heat_top]
    heat_rest = list(by_type.index[TOP_HEAT:])
    if heat_rest:
        heat_rows.append((f"סוגים אחרים ({len(heat_rest)})", m.loc[heat_rest].sum(axis=0)))
    cells = []
    for yi, (_, row) in enumerate(heat_rows):
        for xi, y in enumerate(years):
            cells.append([xi, yi, int(row[y])])
    chart_heat = {"x": ys, "y": [n for n, _ in heat_rows], "cells": cells,
                  "max": int(max([c[2] for c in cells] or [1]))}

    # 5. civil types over time
    civ_types = [t for t in by_type.index if groups[t] == G_CIVIL]
    civ_shown = civ_types[:MAX_CIVIL_LINES]
    chart_civil = {"x": ys, "series": [{"name": t, "data": [int(m.loc[t, y]) for y in years]}
                                       for t in civ_shown]}
    civil_capped = len(civ_types) > len(civ_shown)

    # 6. breadth: distinct types used + new types per year
    new_per_year = first_year.value_counts()
    chart_breadth = {"x": ys, "used": [int(n_used[y]) for y in years],
                     "new": [int(new_per_year.get(y, 0)) for y in years]}

    # 7. latest vs previous per type (dumbbell)
    change_rows = []
    if y0 is not None:
        d = pd.DataFrame({"a": m[y0], "b": m[y1]})
        d = d[(d["a"] > 0) | (d["b"] > 0)]
        d["diff"] = d["b"] - d["a"]
        d["absd"] = d["diff"].abs()
        d = d.sort_index().sort_values(["absd", "b"], ascending=[False, False], kind="stable")
        n_change_all = len(d)
        d = d.iloc[:TOP_CHANGE]
        d = d.sort_values(["diff", "b"], ascending=[False, False], kind="stable")
        for t, r in d.iterrows():
            change_rows.append({"name": t, "a": int(r["a"]), "b": int(r["b"]),
                                "diff": int(r["diff"])})
    else:
        n_change_all = 0
    chart_change = {"names": [r["name"] for r in change_rows],
                    "a": [r["a"] for r in change_rows], "b": [r["b"] for r in change_rows],
                    "y0": str(y0) if y0 is not None else "", "y1": str(y1)}
    table_change = [{"name": r["name"], "a": _int(r["a"]), "b": _int(r["b"]),
                     "diff": (("+" if r["diff"] > 0 else ("−" if r["diff"] < 0 else ""))
                              + _int(abs(r["diff"])))} for r in change_rows]

    # 8. latest-year mix
    lat = m[y1][m[y1] > 0].sort_index().sort_values(ascending=False, kind="stable")
    mix_top = lat.iloc[:TOP_MIX]
    mix_rest = lat.iloc[TOP_MIX:]
    mix = [{"name": t, "value": int(v)} for t, v in mix_top.items()]
    if len(mix_rest):
        mix.append({"name": f"סוגים אחרים ({len(mix_rest)})", "value": int(mix_rest.sum())})
    table_mix = [{"name": r["name"], "value": _int(r["value"]),
                  "share": _pct(r["value"] / v1) if v1 else "0.0%"} for r in mix]

    # ------------------------------------------------------------ insights
    rules = [
        ("trend", insight_trend(yc)),
        ("peak", insight_peak(yc)),
        ("periods", insight_periods(yc)),
        ("leader", insight_leader(by_type, total)),
        ("civil", insight_civil(group_tot)),
        ("new_prison", insight_new_prison(first_year, groups, m)),
        ("riser", insight_riser(mc)),
        ("uncl", insight_uncl(m, groups)),
        ("breadth", insight_breadth(n_used_c)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ------------------------------------------------------------ KPIs
    if y0 is not None and v0 > 0:
        ch = (v1 - v0) / v0
        ch_disp = _signed_pct(ch)
        ch_tone = "info" if abs(ch) >= 0.03 else "brand"
        ch_label = f"שינוי ב-{y1} לעומת {y0}"
    else:
        ch = 0.0
        ch_disp = "0.0%"
        ch_tone = "brand"
        ch_label = f"שינוי ב-{y1} (אין שנה קודמת להשוואה)"
    n_types = len(types) - (1 if any(groups[t] == G_UNCL for t in types) else 0)

    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "latest": {"value": v1, "display": _int(v1), "tone": "brand"},
        "change": {"value": round(ch, 4), "display": ch_disp, "tone": ch_tone},
        "types": {"value": int(n_used[y1]), "display": _int(n_used[y1]), "tone": "brand"},
    }

    top_name = by_type.index[0]
    summary = (f"צווי הגבלה שבתי הדין הרבניים הטילו לפי חוק כפיית ציות, "
               f"{y_min}-{y_max}: {_int(total)} סנקציות ב-{n_types} סוגים, לפי סוג ושנה.")
    if len(summary) > 155:
        summary = (f"סנקציות לפי חוק כפיית ציות, {y_min}-{y_max}: "
                   f"{_int(total)} צווי הגבלה ב-{n_types} סוגים, לפי סוג ושנה.")

    g_list = ", ".join(f"{g}: {_int(group_tot[g])}" for g in present_groups)
    labels = {
        "lede": (f"צווי ההגבלה (סנקציות) שבתי הדין הרבניים הטילו לפי חוק כפיית ציות. הטבלה מונה כמה צווים מכל סוג ניתנו "
                 f"בכל שנה: {_int(total)} סנקציות בשנים {y_min}-{y_max}, ב-{n_types} סוגי הגבלה, "
                 f"מרישיון נהיגה ודרכון ועד הגבלות על אסירים כלואים. המספרים סופרים צווים, "
                 f"לא אנשים: אדם אחד יכול לקבל כמה סנקציות."),
        "total_kpi": f"סך הסנקציות שניתנו, {y_min}-{y_max}",
        "latest_kpi": f"סנקציות שניתנו ב-{y1}",
        "change_kpi": ch_label,
        "types_kpi": f"סוגי סנקציות שהופעלו ב-{y1}",
        "yearly_note": (f"שנת השיא: {peak_y} עם {_int(yearly[peak_y])} סנקציות. "
                        f"ממוצע שנתי: {avg:,.0f} (הקו המקווקו)."),
        "prov_note": ((f"נתוני {y_max} ({_int(yearly[y_max])} סנקציות) נמוכים בהרבה מהשנים הקודמות "
                       f"ונראים חלקיים, ולכן ההשוואות בעמוד מבוססות על {y1}, השנה המלאה האחרונה.")
                      if prov else ""),
        "yearly_aria": (f"גרף עמודות: מספר הסנקציות לפי שנה, {y_min} עד {y_max}. "
                        f"השיא ב-{peak_y} עם {_int(yearly[peak_y])} סנקציות; ב-{y1} ניתנו {_int(v1)}."),
        "groups_note": (f"חלוקת הסנקציות ל-{len(present_groups)} קבוצות לפי תוכן ההגבלה ({g_list}). "
                        f"הקבוצה נקבעת לפי שם הסנקציה."),
        "groups_aria": (f"תרשים עמודות מוערמות: סנקציות לפי קבוצת הגבלה ושנה, {y_min} עד {y_max}. "
                        f"{g_list}."),
        "types_note": (f"סך הצווים מכל סוג בכל השנים. המוביל: \"{top_name}\" עם "
                       f"{_int(by_type.iloc[0])} ({_pct(by_type.iloc[0] / total)})."
                       + (f" מוצגים {TOP_TYPES} הסוגים הנפוצים, והשאר מקובצים יחד; הטבלה מפרטת את כולם."
                          if len(rest) else "")),
        "types_aria": (f"תרשים עמודות אופקי: סך הסנקציות לפי סוג, {y_min} עד {y_max}. "
                       f"המוביל: {top_name} עם {_int(by_type.iloc[0])}."),
        "heat_note": ("כל תא מראה כמה צווים מסוג מסוים ניתנו בשנה מסוימת; כהה יותר = יותר צווים. "
                      + (f"מוצגים {TOP_HEAT} הסוגים הנפוצים והשאר בשורה אחת."
                         if heat_rest else "")),
        "heat_aria": (f"מפת חום: מספר הסנקציות לפי סוג ושנה, {len(heat_rows)} שורות ו-{len(years)} שנים. "
                      f"התא הגבוה ביותר: {chart_heat['max']} צווים."),
        "civil_note": ("ההגבלות האזרחיות לאורך השנים, כל סוג בקו נפרד. לחיצה על שם במקרא מסתירה או מציגה אותו."
                       + (f" מוצגים {MAX_CIVIL_LINES} הסוגים הנפוצים מתוך {len(civ_types)}."
                          if civil_capped else "")),
        "civil_aria": (f"גרף קווים: הגבלות אזרחיות לפי סוג ושנה, {len(civ_shown)} סוגים, "
                       f"{y_min} עד {y_max}."),
        "breadth_note": (f"כמה סוגי סנקציות שונים הופעלו בכל שנה, וכמה מהם הופיעו בה לראשונה. "
                         f"ב-{y1} הופעלו {int(n_used[y1])} סוגים."),
        "breadth_aria": (f"תרשים עמודות: מספר סוגי הסנקציות שהופעלו בכל שנה, {y_min} עד {y_max}; "
                         f"שיא של {int(n_used.max())} סוגים ב-{int(n_used.idxmax())}."),
        "change_note": ((f"כל שורה מחברת את מספר הצווים מסוג מסוים ב-{y0} (עיגול בהיר) וב-{y1} (עיגול כהה). "
                         + (f"מוצגים {len(change_rows)} הסוגים שהשתנו הכי הרבה מתוך {n_change_all}."
                            if n_change_all > len(change_rows) else ""))
                        if y0 is not None else ""),
        "change_aria": (f"תרשים משקולות: סנקציות לפי סוג, {y0} לעומת {y1}." if y0 is not None else ""),
        "mix_note": (f"ההרכב של {_int(v1)} הסנקציות שניתנו ב-{y1}"
                     + (f"; {TOP_MIX} הסוגים הנפוצים והשאר יחד." if len(mix_rest) else ".")),
        "mix_aria": (f"תרשים טבעת: הרכב הסנקציות ב-{y1} לפי סוג. המוביל: "
                     f"{mix[0]['name'] if mix else ''}."),
        "y0": str(y0) if y0 is not None else "",
        "y1": str(y1),
        "notes": NOTES,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": chart_yearly,
            "groups": chart_groups,
            "types": chart_types,
            "heat": chart_heat,
            "civil": chart_civil,
            "breadth": chart_breadth,
            "change": chart_change,
            "mix": mix,
        },
        "tables": {
            "groups": table_groups,
            "group_names": present_groups,
            "types": table_types,
            "change": table_change,
            "mix": table_mix,
        },
        "flags": {
            "change": bool(change_rows),
            "civil": bool(civ_shown),
        },
        "insights": insights,
        "labels": labels,
    }
