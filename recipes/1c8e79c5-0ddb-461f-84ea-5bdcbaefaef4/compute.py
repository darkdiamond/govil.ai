"""הודעות יצרני הרכב RECALL — safety recall notices filed with the Ministry
of Transport, one row per recall campaign.

The data carries a recall YEAR but no date, so the latest year in the data
is treated as still in progress: trend rules compare the last two COMPLETE
years and only quote the latest year as "so far". "Now" is always the data,
never the clock.
"""
import pandas as pd

OTHER = "אחר"
SOFTWARE = "עדכון תוכנה"
SAFETY = "תקלה סידרתית בטיחותית"
TOP_MAKERS = 15
TOP_IMPORTERS = 10
TOP_MODELS = 15
HEAT_YEARS = 10
TABLE_YEARS = 20           # rows in the yearly table fallback
VINTAGE_FROM = 1995        # first production year on the vintage-exposure chart
VINTAGE_MIN_SPANS = 50     # fewer valid build spans → no vintage insight
TREND_MIN_YEARLY = 30      # years with fewer recalls are too thin to compare
BUILD_YEAR_FLOOR = 1980    # BUILD_BEGIN_A carries 1970-01-01 placeholders

SPAN_BINS = [(0, 1, "עד שנה"), (1, 2, "1–2 שנים"), (2, 4, "2–4 שנים"),
             (4, 8, "4–8 שנים"), (8, 200, "8 שנים ומעלה")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _prepare(df):
    out = df.copy()
    out["year"] = pd.to_numeric(out["SHNAT_RECALL"], errors="coerce")
    out = out.dropna(subset=["year"])
    out["year"] = out["year"].astype(int)
    for c in ["TOZAR_TEUR", "SUG_RECALL", "SUG_TAKALA", "OFEN_TIKUN", "YEVUAN_TEUR", "TKINA_EU"]:
        out[c] = out[c].str.strip()
    out["maker"] = out["TOZAR_TEUR"].replace("", "לא צוין")
    out["fault"] = out["SUG_TAKALA"].replace("", OTHER)
    out["fix"] = out["OFEN_TIKUN"].replace("", "לא צוין")
    out["importer"] = out["YEVUAN_TEUR"].replace("", "לא צוין")
    model = out["DEGEM"].str.strip()
    out["model"] = (out["maker"] + " " + model).where(model != "")
    b = pd.to_datetime(out["BUILD_BEGIN_A"], errors="coerce")
    e = pd.to_datetime(out["BUILD_END_A"], errors="coerce")
    ok = b.notna() & e.notna() & (b.dt.year >= BUILD_YEAR_FLOOR) & (e >= b)
    out["span_years"] = ((e - b).dt.days / 365.25).where(ok)
    out["build_from"] = b.dt.year.where(ok)
    out["build_to"] = e.dt.year.where(ok)
    return out.reset_index(drop=True)


def _ranked(series):
    """value_counts with a deterministic tie-break (count desc, name asc)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _complete_years(yearly):
    """All years except the latest (assumed in progress), with enough volume."""
    years = list(yearly.index)
    if len(years) < 2:
        return []
    return [y for y in years[:-1] if yearly[y] >= TREND_MIN_YEARLY]


def insight_trend(yearly):
    full = _complete_years(yearly)
    if len(full) < 2:
        return None
    y0, y1 = full[-2], full[-1]
    v0, v1 = int(yearly[y0]), int(yearly[y1])
    change = (v1 - v0) / v0
    if abs(change) < 0.05:
        return f"ב-{y1} נרשמו {_int(v1)} הודעות ריקול — כמעט ללא שינוי לעומת {y0} ({_int(v0)})."
    word = "עלייה" if change > 0 else "ירידה"
    return (f"ב-{y1} נרשמו {_int(v1)} הודעות ריקול — {word} של {_pct(abs(change))} "
            f"לעומת {y0} ({_int(v0)}).")


def insight_so_far(yearly):
    full = _complete_years(yearly)
    if not full:
        return None
    last_y = int(yearly.index[-1])
    prev_y = full[-1]
    v, vp = int(yearly[last_y]), int(yearly[prev_y])
    if v >= vp:
        return (f"ב-{last_y} (נתונים עד מועד העדכון האחרון) כבר נרשמו {_int(v)} הודעות — "
                f"יותר מכל שנת {prev_y} ({_int(vp)}).")
    return (f"ב-{last_y} נרשמו עד כה {_int(v)} הודעות, {_pct(v / vp)} מסך ההודעות "
            f"בכל שנת {prev_y} ({_int(vp)}).")


def insight_top_fault(df):
    named = _ranked(df.loc[df["fault"] != OTHER, "fault"])
    if named.empty:
        return None
    name, v = named.index[0], int(named.iloc[0])
    share = v / len(df)
    if share < 0.1:
        return None
    second = named.index[1] if len(named) > 1 else None
    tail = f", לפני {second} ({_int(named.iloc[1])})" if second else ""
    return (f"מבין סוגי התקלות המוגדרים, {name} היא הנפוצה ביותר — {_int(v)} הודעות "
            f"({_pct(share)} מכלל ההודעות){tail}.")


def insight_software(df, yearly):
    full = _complete_years(yearly)
    if len(full) < 6:
        return None
    y1, y0 = full[-1], full[-6]
    share = lambda y: (df.loc[df["year"] == y, "fix"] == SOFTWARE).mean()
    s0, s1 = share(y0), share(y1)
    diff = s1 - s0
    if abs(diff) < 0.03:
        return (f"שיעור הריקולים שמתוקנים בעדכון תוכנה יציב: {_pct(s1)} ב-{y1} "
                f"לעומת {_pct(s0)} ב-{y0}.")
    word = "עלה" if diff > 0 else "ירד"
    return (f"שיעור הריקולים שמתוקנים בעדכון תוכנה {word} מ-{_pct(s0)} ב-{y0} "
            f"ל-{_pct(s1)} ב-{y1}.")


def insight_top_maker(df):
    makers = _ranked(df["maker"])
    name, v = makers.index[0], int(makers.iloc[0])
    share = v / len(df)
    if share < 0.08:
        return None
    return (f"{name} מוביל את מספר הודעות הריקול עם {_int(v)} הודעות "
            f"({_pct(share, 1)}), ואחריו {makers.index[1]} ({_int(makers.iloc[1])}).")


def insight_importer(df):
    imp = _ranked(df["importer"])
    top3 = int(imp.head(3).sum())
    share = top3 / len(df)
    if share < 0.3:
        return None
    return (f"שלוש היבואניות המובילות — {imp.index[0]}, {imp.index[1]} ו{imp.index[2]} — "
            f"אחראיות ל-{_pct(share)} מהודעות הריקול.")


def insight_span(df):
    s = df["span_years"].dropna()
    if len(s) < 50:
        return None
    med = float(s.median())
    long_share = float((s >= 4).mean())
    return (f"ריקול טיפוסי חל על רכבים שיוצרו לאורך כ-{med:.1f} שנים (חציון), "
            f"וב-{_pct(long_share)} מההודעות טווח הייצור המושפע ארוך מ-4 שנים.")


def insight_top_model(df):
    models = _ranked(df["model"].dropna())
    if models.empty or int(models.iloc[0]) < 10:
        return None
    name, v = models.index[0], int(models.iloc[0])
    tail = (f", ואחריו {models.index[1]} ({_int(models.iloc[1])})"
            if len(models) > 1 else "")
    return f"הדגם עם מספר הודעות הריקול הגבוה ביותר הוא {name} — {_int(v)} הודעות{tail}."


def _vintage(df, last_year):
    """Recalls covering each production year (a recall counts for every
    year inside its affected build span)."""
    spans = df[["build_from", "build_to"]].dropna().astype(int)
    years = list(range(VINTAGE_FROM, last_year + 1))
    counts = [int(((spans["build_from"] <= y) & (spans["build_to"] >= y)).sum()) for y in years]
    return years, counts, len(spans)


def insight_vintage(years, counts, n_spans):
    if n_spans < VINTAGE_MIN_SPANS or not counts or max(counts) == 0:
        return None
    peak_i = max(range(len(counts)), key=lambda i: (counts[i], -years[i]))
    return (f"רכבים משנת הייצור {years[peak_i]} מושפעים מהמספר הגדול ביותר של הודעות "
            f"ריקול — {_int(counts[peak_i])} הודעות שטווח הייצור שלהן כולל את השנה הזו.")


def compute(frames):
    df = _prepare(frames["recalls"])
    total = len(df)
    yearly = df.groupby("year").size().sort_index()
    y_min, y_max = int(yearly.index.min()), int(yearly.index.max())
    full = _complete_years(yearly)

    # Charts ------------------------------------------------------------
    types = _ranked(df["SUG_RECALL"]).index.tolist()
    by_year_type = df.groupby(["year", "SUG_RECALL"]).size()
    years_chart = {
        "x": [str(y) for y in yearly.index],
        "series": [{"name": t, "data": [int(by_year_type.get((y, t), 0)) for y in yearly.index]}
                   for t in types],
        "partial_index": len(yearly) - 1,
    }

    faults = _ranked(df["fault"])
    faults_named = faults[faults.index != OTHER]
    faults_chart = {"names": list(faults_named.index) + ([OTHER] if OTHER in faults.index else []),
                    "values": [int(v) for v in faults_named] +
                              ([int(faults[OTHER])] if OTHER in faults.index else [])}

    heat_years = list(yearly.index[-HEAT_YEARS:])
    # "אחר" is the largest bucket every year and would saturate the colour
    # scale; it's left out (and the note says so).
    heat_cats = [c for c in faults.index if c != OTHER]
    by_fault_year = df.groupby(["fault", "year"]).size()
    heat_cells = []
    for xi, y in enumerate(heat_years):
        tot = int(yearly[y])
        for yi, cat in enumerate(heat_cats):
            v = int(by_fault_year.get((cat, y), 0))
            heat_cells.append([xi, yi, round(v / tot * 100, 1) if tot else 0, v])
    heat = {"years": [str(y) for y in heat_years], "cats": heat_cats, "cells": heat_cells,
            "max": max((c[2] for c in heat_cells), default=0)}

    makers = _ranked(df["maker"])
    top = makers.head(TOP_MAKERS)
    rest = int(makers.iloc[TOP_MAKERS:].sum())
    makers_chart = {"names": list(top.index) + (["יצרנים אחרים"] if rest else []),
                    "values": [int(v) for v in top] + ([rest] if rest else [])}

    fixes = _ranked(df["fix"])
    fix_years = [y for y in yearly.index if yearly[y] >= TREND_MIN_YEARLY]
    by_fix_year = df.groupby(["year", "fix"]).size()
    fix_chart = {
        "x": [str(y) for y in fix_years],
        "series": [{"name": f,
                    "data": [round(by_fix_year.get((y, f), 0) / yearly[y] * 100, 1) for y in fix_years]}
                   for f in fixes.index],
    }

    imp = _ranked(df["importer"])
    imp_top = imp.head(TOP_IMPORTERS)
    imp_rest = int(imp.iloc[TOP_IMPORTERS:].sum())
    importers_chart = {"names": list(imp_top.index) + (["יבואנים אחרים"] if imp_rest else []),
                       "values": [int(v) for v in imp_top] + ([imp_rest] if imp_rest else [])}

    spans = df["span_years"].dropna()
    span_chart = {"names": [lbl for _, _, lbl in SPAN_BINS],
                  "values": [int(((spans >= lo) & (spans < hi)).sum()) for lo, hi, _ in SPAN_BINS]}
    span_excluded = total - len(spans)

    models = _ranked(df["model"].dropna()).head(TOP_MODELS)
    models_chart = {"names": list(models.index), "values": [int(v) for v in models]}

    # Vintage runs to the last production year any recall covers, capped at
    # the year after the latest recall year (model years run ahead).
    max_build = df["build_to"].max()
    last_vintage = int(min(max_build, y_max + 1)) if pd.notna(max_build) else y_max
    v_years, v_counts, n_spans = _vintage(df, last_vintage)
    vintage_chart = {"x": [str(y) for y in v_years], "y": v_counts}

    # Tables -----------------------------------------------------------
    def rows(series):
        return [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in series.items()]

    t_years = [{"year": str(y), "count": _int(yearly[y]),
                "safety": _int(by_year_type.get((y, SAFETY), 0))}
               for y in list(yearly.index)[-TABLE_YEARS:]]
    t_faults = rows(faults)
    t_makers = rows(makers.head(TOP_MAKERS))
    t_models = rows(models)
    t_importers = rows(imp.head(TOP_IMPORTERS))
    t_span = [{"name": n, "count": _int(v), "share": _pct(v / max(len(spans), 1), 1)}
              for n, v in zip(span_chart["names"], span_chart["values"])]
    t_fix = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in fixes.items()]
    cats = _ranked(df["TKINA_EU"].replace("", "לא צוין"))
    t_cats = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in cats.items()]
    t_types = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
               for n, v in _ranked(df["SUG_RECALL"]).items()]

    # Insights ----------------------------------------------------------
    rules = [
        ("trend", insight_trend(yearly)),
        ("so_far", insight_so_far(yearly)),
        ("top_fault", insight_top_fault(df)),
        ("software", insight_software(df, yearly)),
        ("top_maker", insight_top_maker(df)),
        ("importers", insight_importer(df)),
        ("span", insight_span(df)),
        ("top_model", insight_top_model(df)),
        ("vintage", insight_vintage(v_years, v_counts, n_spans)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    safety_share = float((df["SUG_RECALL"] == SAFETY).mean())
    last_full = full[-1] if full else None
    kpis = {
        "total": {"value": total, "display": _int(total)},
        "makers": {"value": int(makers.size), "display": _int(makers.size)},
        "last_full": {"value": None if last_full is None else int(yearly[last_full]),
                      "display": "—" if last_full is None else _int(yearly[last_full]),
                      "label": "" if last_full is None else f"הודעות ב-{last_full}"},
        "safety": {"value": safety_share, "display": _pct(safety_share)},
    }

    labels = {
        "lede": (f"{_int(total)} הודעות ריקול של יצרני רכב ויבואנים בשנים {y_min}–{y_max}, "
                 f"ב-{_int(makers.size)} יצרנים וב-{_int(imp.size)} יבואנים. כל הודעה מתארת "
                 f"תקלה, את הדגמים ושנות הייצור המושפעים ואת אופן התיקון."),
        "years_note": (f"מספר ההודעות לפי שנת הריקול, לפי סוג ההודעה. {y_max} היא השנה "
                       f"האחרונה במאגר והנתונים בה עשויים להיות חלקיים."),
        "years_aria": (f"תרשים עמודות מוערמות: מספר הודעות הריקול לפי שנה, {y_min} עד {y_max}, "
                       f"לפי סוג ההודעה."),
        "faults_aria": f"תרשים עמודות אופקי: מספר ההודעות לפי סוג התקלה, {len(faults_chart['names'])} סוגים.",
        "heat_aria": (f"מפת חום: שיעור כל סוג תקלה מתוך ההודעות בכל שנה, "
                      f"{heat_years[0]} עד {heat_years[-1]}."),
        "heat_note": (f"אחוז ההודעות מכל סוג תקלה בכל שנה ({heat_years[0]}–{heat_years[-1]}). "
                      f"מאפשר לראות שינוי בתמהיל גם כשהיקף ההודעות משתנה. הקטגוריה "
                      f"\"{OTHER}\" אינה מוצגת כדי שלא תאפיל על השאר."),
        "makers_aria": f"תרשים עמודות אופקי: {len(top)} היצרנים עם מספר ההודעות הגבוה ביותר.",
        "makers_note": (f"{len(top)} היצרנים המובילים; שאר {_int(makers.size - len(top))} "
                        f"היצרנים מקובצים יחד." if rest else "כל היצרנים במאגר."),
        "fix_aria": (f"גרף קווים: שיעור כל אופן תיקון מתוך ההודעות בכל שנה, "
                     f"{fix_years[0] if fix_years else y_min} עד {fix_years[-1] if fix_years else y_max}."),
        "fix_note": (f"באחוזים מההודעות בכל שנה. מוצגות שנים עם {TREND_MIN_YEARLY} הודעות לפחות."),
        "importers_aria": f"תרשים עמודות אופקי: {len(imp_top)} היבואנים עם מספר ההודעות הגבוה ביותר.",
        "span_aria": "תרשים עמודות: מספר ההודעות לפי אורך תקופת הייצור המושפעת.",
        "span_note": (f"משך הזמן בין תחילת לסוף טווח הייצור המושפע. לא נכללו "
                      f"{_int(span_excluded)} הודעות עם תאריכי ייצור חסרים או לא תקינים."
                      if span_excluded else "משך הזמן בין תחילת לסוף טווח הייצור המושפע."),
        "fix_table_caption": "מספר ההודעות לפי אופן התיקון.",
        "cat_table_caption": "מספר ההודעות לפי קטגוריית רכב אירופית.",
        "type_table_caption": "מספר ההודעות לפי סוג ההודעה.",
        "years_table_caption": (f"מספר ההודעות ומתוכן תקלות סדרתיות בטיחותיות, "
                                f"{len(t_years)} השנים האחרונות."),
        "faults_table_caption": "מספר ההודעות לפי סוג התקלה.",
        "makers_table_caption": f"{len(t_makers)} היצרנים עם מספר ההודעות הגבוה ביותר.",
        "importers_table_caption": f"{len(t_importers)} היבואנים עם מספר ההודעות הגבוה ביותר.",
        "span_table_caption": "מספר ההודעות לפי אורך תקופת הייצור המושפעת.",
        "models_aria": f"תרשים עמודות אופקי: {len(models)} הדגמים עם מספר הודעות הריקול הגבוה ביותר.",
        "models_table_caption": f"{len(t_models)} הדגמים עם מספר הודעות הריקול הגבוה ביותר.",
        "models_note": (f"יצרן ודגם כפי שנרשמו בהודעה. דגם אחד יכול להופיע בכמה הודעות "
                        f"לאורך השנים ({_int(df['model'].nunique())} צירופי יצרן-דגם במאגר)."),
        "vintage_aria": (f"תרשים עמודות: מספר הודעות הריקול שחלות על רכבים מכל שנת ייצור, "
                         f"{v_years[0]} עד {v_years[-1]}."),
        "vintage_note": (f"כל הודעה נספרת בכל שנות הייצור שבטווח המושפע שלה ({_int(n_spans)} "
                         f"הודעות עם טווח ייצור תקין). שנות ייצור אחרונות עשויות לגדול "
                         f"כשיתפרסמו הודעות נוספות."),
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} הודעות ריקול בטיחותי של יצרני רכב, {y_min}–{y_max}: "
                           f"סוג התקלה, הדגמים ושנות הייצור המושפעים, היבואן ואופן התיקון."),
            "dataset_kind": "registry",
            "suggested_tags": ["ריקול", "בטיחות רכב", "יבואני רכב", "תחבורה"],
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "years": years_chart,
            "faults": faults_chart,
            "heat": heat,
            "makers": makers_chart,
            "fix": fix_chart,
            "importers": importers_chart,
            "span": span_chart,
            "models": models_chart,
            "vintage": vintage_chart,
        },
        "tables": {"fix": t_fix, "cats": t_cats, "types": t_types, "years": t_years,
                   "faults": t_faults, "makers": t_makers, "models": t_models,
                   "importers": t_importers, "span": t_span},
        "insights": insights,
        "labels": labels,
    }
