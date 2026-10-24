"""רשימת צווי בטיחות — safety orders issued by Ministry of Labour inspectors.

One row per order (warrent_id). "Now" is the latest send_date in the data;
the trailing-12-months window ends there, so a partial current month never
skews a trend. Violation themes come from a keyword classifier over the
free-text `felony_name`; text that matches nothing lands in "אחר", so new
wording can only grow that bucket, never break the page.

Executors: the column mixes companies and private individuals. Rankings name
only entities identifiable as corporate (בע"מ / עמותה / Ltd …); the page says
so.
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

# Ordered: first match wins.
THEMES = [
    ("מעליות", r"מעלית|מעליות|דרגנוע"),
    ("בעקבות תאונה", r"תאונ"),
    ("עבודה בגובה ונפילה", r"גובה|נפיל|גידור|גודר|אזן|מעקה|פיגום|פגום|סולם|גג שביר|פתח"),
    ("ציוד הרמה ועגורנים", r"עגורן|הרמה|מנוף|מלגז|אביזר|איתות"),
    ("חשמל", r"חשמל|הארק"),
    ("מתקני לחץ וקיטור", r"קולט|קיטור|דוד|מכל|לחץ"),
    ("ציוד מגן אישי", r"קסד|ציוד מגן|מגן אישי"),
    ("אש וחומרים מסוכנים", r"אש|שריפ|דלק|נפט|חומר מסוכן|חומרים מסוכנים"),
    ("ניהול ופיקוח באתר", r"מנהל עבודה|מנהל העבודה|ממונה|עוזר בטיחות|הודיע|הודעה|מינוי|תסקיר|תכנית|תוכנית|הדרכה"),
    ("חפירות ותמיכות", r"חפיר|דיפון|תמיכ|זקפ|טפסנות"),
    ("ליקויים רבים / כללי", r"ליקוי|ליקוים|לקוי|הפסקת עבודה|כללי"),
]
OTHER = "אחר"
CORPORATE_RE = re.compile(
    r'בע"מ|בע״מ|בעמ|ע"ר|ע״ר|עמותה|\bLTD\b|Ltd|לימיטד|אל טי די|שותפות|חברה'
)
TOP_N = 12


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.0f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def theme_of(text):
    for name, rx in THEMES:
        if re.search(rx, text):
            return name
    return OTHER


NO_LAW = "לא צוין חיקוק"
SITE_BUCKETS = [(1, 1, "צו אחד"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4–5"),
                (6, 9, "6–9"), (10, None, "10 ומעלה")]
TOP_LAWS = 8
THEME_TREND_N = 5


def law_short(name):
    """'תקנות הבטיחות בעבודה (עבודות בניה)- התשמ"ח-1988' → the title before
    the Hebrew-year suffix, so amendments of one law read as one row."""
    s = (name or "").strip()
    if not s:
        return NO_LAW
    s = re.split(r"\s*-\s*(?:ה?תש|תש)", s, maxsplit=1)[0].strip(" -")
    return re.sub(r"\s*\(תיקון[^)]*\)", "", s).strip() or NO_LAW


def _prepare(df):
    out = pd.DataFrame({
        "id": df["warrent_id"].str.strip(),
        "d": pd.to_datetime(df["send_date"].str.strip(), format="%d/%m/%Y", errors="coerce"),
        "work": df["work_id"].str.strip(),
        "city": df["city_name"].str.strip(),
        "executor": df["executor_name"].str.strip(),
        "category": df["category_name"].str.strip().replace("", "לא צוין"),
        "theme": df["felony_name"].str.strip().map(theme_of),
        "law": df["law_name"].map(law_short),
    })
    out = out[out["id"] != ""].drop_duplicates("id")
    return out.sort_values(["d", "id"], kind="stable").reset_index(drop=True)


def _top(series, n=TOP_N):
    counts = series.value_counts()
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    return counts.head(n)


def insight_trend(t12, p12, last):
    if p12 == 0:
        return None
    ch = (t12 - p12) / p12
    if abs(ch) < 0.05:
        return (f"ב-12 החודשים שעד {d_he(last)} הוצאו {_int(t12)} צווי בטיחות — "
                f"כמעט ללא שינוי לעומת 12 החודשים שלפניהם ({_int(p12)}).")
    word = "עלייה" if ch > 0 else "ירידה"
    return (f"ב-12 החודשים שעד {d_he(last)} הוצאו {_int(t12)} צווי בטיחות — {word} של "
            f"{abs(ch) * 100:.0f}% לעומת 12 החודשים שלפניהם ({_int(p12)}).")


def insight_peak_year(yearly, last):
    full = yearly[yearly.index < last.year]
    if len(full) < 3:
        return None
    y = int(full.idxmax())
    return (f"השנה המלאה עם מספר הצווים הגבוה ביותר היא {y} ({_int(full.max())} צווים); "
            f"השנה הנוכחית ({last.year}) חלקית — {_int(yearly.get(last.year, 0))} צווים עד כה.")


def insight_theme(recent):
    if recent.empty:
        return None
    th = _top(recent["theme"], 3)
    name, n = th.index[0], th.iloc[0]
    share = n / len(recent)
    if share < 0.15 or name == OTHER:
        return None
    return (f"הנושא הנפוץ ביותר בצווים בשנה האחרונה: {name} — {_int(n)} צווים, "
            f"{_pct(share)} מהצווים.")


def insight_city(recent):
    if recent.empty:
        return None
    top = _top(recent.loc[recent["city"] != "", "city"], 3)
    if top.empty:
        return None
    share = top.iloc[0] / len(recent)
    if share < 0.04:
        return None
    rest = ", ".join(f"{c} ({_int(v)})" for c, v in top.iloc[1:].items())
    tail = f", ואחריה {rest}" if rest else ""
    return (f"{top.index[0]} מובילה במספר הצווים בשנה האחרונה עם {_int(top.iloc[0])} "
            f"({_pct(share)}){tail}.")


def insight_category(recent):
    if recent.empty:
        return None
    top = _top(recent["category"], 2)
    share = top.iloc[0] / len(recent)
    return f"ענף {top.index[0]} מרכז {_pct(share)} מצווי השנה האחרונה ({_int(top.iloc[0])} צווים)."


def insight_repeat_sites(df):
    sites = df.loc[df["work"] != "", "work"].value_counts()
    if sites.empty:
        return None
    rep = int((sites >= 3).sum())
    if rep == 0:
        return None
    return (f"{_int(rep)} אתרי עבודה קיבלו 3 צווים או יותר לאורך התקופה, מתוך "
            f"{_int(sites.size)} אתרים שקיבלו צו אחד לפחות.")


def insight_theme_shift(dated, last):
    """Biggest change in a named theme's share between the first and the last
    COMPLETE year (the current year is partial). Needs ≥4 complete years and
    a move of ≥3 percentage points."""
    full = dated[dated["d"].dt.year < last.year]
    years = sorted(full["d"].dt.year.unique())
    if len(years) < 4:
        return None
    y0, y1 = int(years[0]), int(years[-1])
    a = full[full["d"].dt.year == y0]["theme"].value_counts(normalize=True)
    b = full[full["d"].dt.year == y1]["theme"].value_counts(normalize=True)
    names = sorted(t for t in set(a.index) | set(b.index) if t != OTHER)
    if not names:
        return None
    best = max(names, key=lambda t: (abs(b.get(t, 0) - a.get(t, 0)), t))
    d = b.get(best, 0) - a.get(best, 0)
    if abs(d) < 0.03:
        return None
    word = "עלה" if d > 0 else "ירד"
    return (f"השינוי הבולט בנושאי הצווים: חלקם של צווי \"{best}\" {word} מ-{_pct(a.get(best, 0))} "
            f"ב-{y0} ל-{_pct(b.get(best, 0))} ב-{y1}.")


def insight_law(df):
    cited = df[df["law"] != NO_LAW]
    if len(cited) < 100:
        return None
    top = _top(cited["law"], 1)
    share = top.iloc[0] / len(cited)
    return (f"{_pct(share)} מהצווים שבהם צוין חיקוק מבוססים על {top.index[0]}; "
            f"ב-{_pct(1 - len(cited) / len(df))} מהצווים לא צוין חיקוק.")


def compute(frames):
    df = _prepare(frames["orders"])
    dated = df.dropna(subset=["d"])
    last = dated["d"].max()
    first = dated["d"].min()
    undated = int(df["d"].isna().sum())
    recent = dated[dated["d"] > last - pd.Timedelta(days=365)]
    prev = dated[(dated["d"] <= last - pd.Timedelta(days=365)) &
                 (dated["d"] > last - pd.Timedelta(days=730))]

    yearly = dated.groupby(dated["d"].dt.year).size().sort_index()
    monthly = dated.groupby(dated["d"].dt.to_period("M")).size().sort_index()
    full_months = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    monthly = monthly.reindex(full_months, fill_value=0)

    cats = list(_top(df["category"], 10).index)
    by_cat_year = dated.groupby([dated["d"].dt.year, "category"]).size()
    years = [int(y) for y in yearly.index]
    cat_year = {
        "years": [str(y) for y in years],
        "series": [{"name": c, "data": [int(by_cat_year.get((y, c), 0)) for y in years]}
                   for c in cats],
    }

    th_all = df["theme"].value_counts()
    th_recent = recent["theme"].value_counts()
    theme_order = [t for t, _ in THEMES] + [OTHER]
    theme_order = sorted(theme_order, key=lambda t: (-int(th_all.get(t, 0)), t))
    theme_order = [t for t in theme_order if th_all.get(t, 0) > 0]
    themes = {
        "names": theme_order,
        "all": [round(float(th_all.get(t, 0)) / len(df) * 100, 1) for t in theme_order],
        "recent": [round(float(th_recent.get(t, 0)) / max(len(recent), 1) * 100, 1)
                   for t in theme_order],
    }

    top_cities = _top(recent.loc[recent["city"] != "", "city"])
    cities = {"names": list(top_cities.index), "values": [int(v) for v in top_cities]}

    corp = df[df["executor"].str.contains(CORPORATE_RE)]
    top_exec = _top(corp["executor"], 10)
    executors = {"names": list(top_exec.index), "values": [int(v) for v in top_exec]}

    heat_years = years
    heat = {
        "years": [str(y) for y in heat_years],
        "months": MONTHS_HE,
        "cells": [[heat_years.index(p.year), p.month - 1, int(v)]
                  for p, v in monthly.items() if p.year in heat_years],
        "max": int(monthly.max()),
    }

    # Legal basis: top laws among orders that cite one; the rest disclosed.
    cited = df[df["law"] != NO_LAW]
    top_laws = _top(cited["law"], TOP_LAWS)
    other_laws = len(cited) - int(top_laws.sum())
    laws = {"names": list(top_laws.index) + (["חיקוקים אחרים"] if other_laws else []),
            "values": [int(v) for v in top_laws] + ([other_laws] if other_laws else [])}

    # Sector × theme: each sector's orders split by theme (% of the sector).
    sector_names = [c for c in _top(df["category"], 6).index]
    ct = pd.crosstab(df["category"], df["theme"])
    sec_theme = {
        "themes": theme_order,
        "sectors": sector_names,
        "cells": [[ti, si, round(float(ct.at[s, t]) / float(ct.loc[s].sum()) * 100, 1),
                   int(ct.at[s, t])]
                  for si, s in enumerate(sector_names) for ti, t in enumerate(theme_order)
                  if s in ct.index and t in ct.columns],
    }

    # Orders per work site, bucketed.
    per_site = df.loc[df["work"] != "", "work"].value_counts()
    site_buckets = {"names": [], "values": []}
    for lo, hi, label in SITE_BUCKETS:
        n = int(((per_site >= lo) & ((per_site <= hi) if hi else True)).sum())
        site_buckets["names"].append(label)
        site_buckets["values"].append(n)

    # Share of the leading named themes, per year (current year partial).
    named = [t for t in theme_order if t != OTHER][:THEME_TREND_N]
    ty = pd.crosstab(dated["d"].dt.year, dated["theme"], normalize="index")
    theme_year = {
        "years": [str(y) for y in years],
        "series": [{"name": t, "data": [round(float(ty.at[y, t]) * 100, 1)
                                        if t in ty.columns and y in ty.index else 0.0
                                        for y in years]} for t in named],
    }

    rules = [
        ("trend", insight_trend(len(recent), len(prev), last)),
        ("peak_year", insight_peak_year(yearly, last)),
        ("theme", insight_theme(recent)),
        ("theme_shift", insight_theme_shift(dated, last)),
        ("category", insight_category(recent)),
        ("city", insight_city(recent)),
        ("repeat_sites", insight_repeat_sites(df)),
        ("law", insight_law(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # More orders than the prior 12 months = more hazards found (caution);
    # fewer is notable but not clearly good (could be less enforcement).
    recent_tone = "brand"
    if len(prev):
        ch = (len(recent) - len(prev)) / len(prev)
        recent_tone = "warn" if ch >= 0.10 else "info" if ch <= -0.10 else "brand"
    n_sites = int(df.loc[df["work"] != "", "work"].nunique())
    n_cities = int(df.loc[df["city"] != "", "city"].nunique())
    kpis = {
        "total": {"value": len(df), "display": _int(len(df)), "tone": "brand",
                  "label": "צווי בטיחות במאגר"},
        "recent": {"value": len(recent), "display": _int(len(recent)), "tone": recent_tone,
                   "label": ("צווים ב-12 החודשים האחרונים"
                             + (f" (לעומת {_int(len(prev))} בשנה שלפניהם)" if len(prev) else ""))},
        "sites": {"value": n_sites, "display": _int(n_sites), "tone": "brand",
                  "label": "אתרי עבודה שקיבלו צו"},
        "cities": {"value": n_cities, "display": _int(n_cities), "tone": "brand",
                   "label": "יישובים"},
    }

    year_table = [{"year": str(y), "n": _int(v)} for y, v in yearly.items()]
    tables = {
        "years": year_table,
        "cat_year": {
            "cols": [s["name"] for s in cat_year["series"]],
            "rows": [{"year": y, "vals": [_int(s["data"][i]) for s in cat_year["series"]]}
                     for i, y in enumerate(cat_year["years"])],
        },
        # Percent tables carry "%" in the header, not the cells: a table of
        # yearly shares repeats values across years, which check.py's
        # PERCENT-CONFLICT rule (same "x%" near different years) rejects.
        "themes": [{"name": n, "all": a, "recent": r}
                   for n, a, r in zip(themes["names"], themes["all"], themes["recent"])],
        "cities": [{"name": n, "v": _int(v)} for n, v in zip(cities["names"], cities["values"])],
        "executors": [{"name": n, "v": _int(v)}
                      for n, v in zip(executors["names"], executors["values"])],
        "laws": [{"name": n, "v": _int(v)} for n, v in zip(laws["names"], laws["values"])],
        "site_buckets": [{"name": n, "v": _int(v)}
                         for n, v in zip(site_buckets["names"], site_buckets["values"])],
        "theme_year": {
            "cols": [f"{s['name']} (%)" for s in theme_year["series"]],
            "rows": [{"year": y, "vals": [s["data"][i] for s in theme_year["series"]]}
                     for i, y in enumerate(theme_year["years"])],
        },
    }
    y0, y1 = int(first.year), int(last.year)
    undated_note = (f" {_int(undated)} צווים ללא תאריך אינם נכללים בגרפי הזמן."
                    if undated else "")
    labels = {
        "lede": (f"{_int(len(df))} צווי בטיחות שהוציאו מפקחי העבודה מ-{d_he(first)} ועד "
                 f"{d_he(last)}, ב-{kpis['sites']['display']} אתרי עבודה "
                 f"ב-{kpis['cities']['display']} יישובים."),
        "monthly_note": "מספר הצווים בכל חודש." + undated_note,
        "monthly_aria": f"גרף קו: מספר צווי הבטיחות לפי חודש, {y0} עד {y1}.",
        "cat_aria": f"תרשים עמודות מוערמות: צווי בטיחות לפי שנה וענף, {y0} עד {y1}.",
        "themes_aria": ("תרשים עמודות אופקי: שיעור הצווים לפי נושא ההפרה, בכל התקופה "
                        "ובשנה האחרונה."),
        "cities_aria": f"תרשים עמודות אופקי: {len(cities['names'])} היישובים עם מספר הצווים "
                       "הגבוה ביותר בשנה האחרונה.",
        "exec_aria": f"תרשים עמודות אופקי: {len(executors['names'])} החברות שקיבלו הכי הרבה "
                     "צווי בטיחות.",
        "exec_note": (f"חברות ותאגידים בלבד ({_int(len(corp))} צווים מתוך {_int(len(df))}) — "
                      "מבצעים שהם אנשים פרטיים או שלא צוינו אינם מדורגים."),
        "heat_aria": f"מפת חום: מספר הצווים לפי חודש ושנה, {y0} עד {y1}.",
        "year_caption": f"מספר צווי הבטיחות לפי שנה, {y0} עד {y1}.",
        "laws_aria": (f"תרשים עמודות אופקי: {min(TOP_LAWS, len(top_laws))} החיקוקים שעליהם "
                      "מבוססים הכי הרבה צווים."),
        "laws_note": (f"החיקוק שעליו נשען הצו. ב-{_int(len(df) - len(cited))} צווים "
                      f"({_pct(1 - len(cited) / len(df))}) לא צוין חיקוק והם אינם בגרף. "
                      "תיקונים לאותו חוק מאוחדים."),
        "sec_theme_aria": (f"מפת חום: חלוקת הצווים בכל ענף לפי נושא ההפרה, באחוזים מצווי "
                           f"הענף, ב-{len(sector_names)} ענפים."),
        "sites_aria": (f"תרשים עמודות: מספר אתרי העבודה לפי כמות הצווים שקיבלו, "
                       f"{_int(per_site.size)} אתרים."),
        "theme_year_aria": (f"גרף קווים: חלקם של {len(named)} נושאי ההפרה הנפוצים מכלל "
                            f"הצווים בכל שנה, {y0} עד {y1}."),
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(len(df))} צווי בטיחות שהוטלו על אתרי עבודה בישראל "
                           f"מ-{y0} ועד {d_he(last)} — לפי שנה, ענף, נושא ההפרה ויישוב."),
            "dataset_kind": "registry",
            "suggested_tags": ["בטיחות בעבודה", "צווי בטיחות", "אכיפה", "אתרי בנייה", "מעליות"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{last.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "monthly": {"x": [str(p) for p in monthly.index], "y": [int(v) for v in monthly]},
            "cat_year": cat_year,
            "themes": themes,
            "cities": cities,
            "executors": executors,
            "heat": heat,
            "laws": laws,
            "sec_theme": sec_theme,
            "sites": site_buckets,
            "theme_year": theme_year,
        },
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
