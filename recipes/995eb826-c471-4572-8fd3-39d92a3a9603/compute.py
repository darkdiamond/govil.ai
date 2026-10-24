"""אנטנות סלולריות פעילות — active cellular transmission sites (Cellcom,
Pelephone, PHI) with permits, technology and the maximum measured radiation
as a % of the health threshold.

"Now" is the latest permit/inspection date in the data. Permit dates are the
CURRENT permit (they are renewed), so the permit-year chart shows renewal
activity, not when antennas were first built — the page says so.
"""
import re

import pandas as pd

TOP_JURIS = 15
OTHER = "אחר"
RAD_COL = "תוצאה מירבית ב% ביחס לסף הבריאות"
RAD_BINS = [(0, 0, "0"), (0.0001, 1, "עד 1%"), (1.0001, 5, "1%–5%"), (5.0001, 10, "5%–10%"),
            (10.0001, 20, "10%–20%"), (20.0001, 1000, "מעל 20%")]
RAD_HIGH = 10                 # "% of the threshold" above which a site is called out
PERMIT_FROM = 2016            # operating permits start in 2016; earlier construction permits pooled
INSPECT_BINS = [(0, 365, "בשנה האחרונה"), (366, 730, "לפני 1–2 שנים"),
                (731, 1095, "לפני 2–3 שנים"), (1096, 100000, "לפני יותר מ-3 שנים")]
GENS = ["2", "3", "4", "5"]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _operator(name):
    return "PHI (הוט ופרטנר)" if name.startswith("PHI") else name


def _date(col):
    return pd.to_datetime(col.str.strip(), format="%d/%m/%Y", errors="coerce")


def _prepare(df):
    out = pd.DataFrame({
        "operator": df["חברה"].str.strip().map(_operator),
        "type": df["סוג אתר"].str.strip().replace("", "לא צוין"),
        "juris": df["תחום שיפוט"].str.strip().str.replace(r"\s+", " ", regex=True).replace("", "לא צוין"),
        "built": _date(df["תאריך היתר הקמה"]),
        "operating": _date(df["תאריך היתר הפעלה"]),
        "inspected": _date(df["בדיקה תקופתית אחרונה"]),
        "permit": df["היתר קרינה"].str.strip(),
        "rad": pd.to_numeric(df[RAD_COL], errors="coerce"),
        "tech": df["טכנולוגיית שידור"].str.strip(),
    })
    gens = out["tech"].map(lambda s: set(re.findall(r"[2-5]", s)))
    for g in GENS:
        out[f"g{g}"] = gens.map(lambda s, g=g: g in s)
    return out


def insight_operators(df):
    vc = _ranked(df["operator"])
    lead, n = vc.index[0], int(vc.iloc[0])
    spread = (vc.iloc[0] - vc.iloc[-1]) / len(df)
    if spread < 0.05:
        return (f"{len(vc)} החברות מחזיקות נתח דומה מהאתרים: בין {_pct(vc.iloc[-1] / len(df))} "
                f"ל-{_pct(vc.iloc[0] / len(df))}; {lead} מובילה עם {_int(n)} אתרים.")
    return f"{lead} מפעילה את מספר האתרים הגדול ביותר — {_int(n)} ({_pct(n / len(df))})."


def insight_5g(df):
    share = df["g5"].mean()
    if share == 0:
        return None
    by_op = df.groupby("operator")["g5"].mean().sort_index().sort_values(ascending=False, kind="stable")
    return (f"{_pct(share)} מהאתרים משדרים בדור 5; השיעור הגבוה ביותר אצל {by_op.index[0]} "
            f"({_pct(by_op.iloc[0])}) והנמוך ביותר אצל {by_op.index[-1]} ({_pct(by_op.iloc[-1])}).")


def insight_radiation(df):
    r = df["rad"].dropna()
    if r.empty:
        return None
    mx = float(r.max())
    high = int((r > RAD_HIGH).sum())
    head = (f"בכל האתרים התוצאה המרבית נמוכה מסף הבריאות: הגבוהה ביותר היא {mx:.1f}% מהסף"
            if mx < 100 else f"ב-{_int((r >= 100).sum())} אתרים נמדדה תוצאה בסף הבריאות או מעליו")
    return f"{head}; ב-{_int(high)} אתרים ({_pct(high / len(r))}) היא עולה על {RAD_HIGH}% מהסף."


def insight_zero(df):
    z = int((df["rad"] == 0).sum())
    if z < 50:
        return None
    return (f"ב-{_int(z)} אתרים ({_pct(z / len(df))}) נרשמה תוצאה של 0 — לרוב משום שאין בקרבתם "
            "אזור מאוכלס ברציפות שבו נדרשת מדידה.")


def insight_juris(df):
    vc = _ranked(df["juris"])
    (a, na), (b, nb) = list(vc.items())[:2]
    return f"תחום השיפוט עם הכי הרבה אתרים הוא {a} ({_int(na)}), ואחריו {b} ({_int(nb)})."


def insight_inspected(df, ref):
    ins = df["inspected"].dropna()
    if ins.empty:
        return None
    recent = (ins > ref - pd.Timedelta(days=365)).mean()
    old = int((ins < ref - pd.Timedelta(days=1095)).sum())
    text = f"{_pct(recent)} מהאתרים עברו בדיקה תקופתית בשנה האחרונה"
    if old:
        text += f"; ב-{_int(old)} אתרים הבדיקה האחרונה נעשתה לפני יותר משלוש שנים"
    return text + "."


def insight_no_permit(df):
    n = int((df["permit"] == "אין היתר").sum())
    if n == 0:
        return None
    return f"{_int(n)} אתרים פעילים רשומים ללא היתר קרינה."


def compute(frames):
    df = _prepare(frames["sites"])
    n = len(df)
    ref = max(df["built"].max(), df["operating"].max(), df["inspected"].max())

    ops = _ranked(df["operator"])
    o_chart = {"names": list(ops.index), "values": [int(v) for v in ops]}
    t_ops = [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in ops.items()]

    types = list(_ranked(df["type"]).index)
    ot = pd.crosstab(df["type"], df["operator"]).reindex(index=types, columns=list(ops.index), fill_value=0)
    t_chart = {"names": types,
               "series": [{"name": o, "data": [int(v) for v in ot[o]]} for o in ot.columns]}
    t_types = [{"name": t, "total": _int(ot.loc[t].sum()), "cells": [_int(ot.loc[t, o]) for o in ot.columns]}
               for t in types]

    gen_by_op = {o: [round(float(df.loc[df["operator"] == o, f"g{g}"].mean() * 100), 1) for g in GENS]
                 for o in ops.index}
    g_chart = {"x": [f"דור {g}" for g in GENS],
               "series": [{"name": o, "data": v} for o, v in gen_by_op.items()]}
    t_gen = [{"name": f"דור {g}", "cells": [f"{gen_by_op[o][i]:.1f}" for o in ops.index],
              "all": f"{df[f'g{g}'].mean() * 100:.1f}"} for i, g in enumerate(GENS)]

    jv = _ranked(df["juris"])
    j_names, j_vals = list(jv.head(TOP_JURIS).index), [int(v) for v in jv.head(TOP_JURIS)]
    rest = int(jv.iloc[TOP_JURIS:].sum())
    if rest:
        j_names.append(OTHER)
        j_vals.append(rest)
    t_juris = [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in zip(j_names, j_vals)]

    def rad_bucket(v):
        for lo, hi, lab in RAD_BINS:
            if lo <= v <= hi:
                return lab
        return None

    rb = df["rad"].dropna().map(rad_bucket).value_counts().reindex([b[2] for b in RAD_BINS], fill_value=0)
    r_chart = {"names": list(rb.index), "values": [int(v) for v in rb]}
    t_rad = [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in rb.items()]

    measured = df[df["rad"] > 0]
    rt = (measured.groupby("type")["rad"].agg(["median", "max", "size"])
          .reindex([t for t in types if t in set(measured["type"])]))
    rt_chart = {"names": list(rt.index), "median": [round(float(v), 2) for v in rt["median"]],
                "max": [round(float(v), 2) for v in rt["max"]]}
    t_rad_type = [{"name": t, "median": f"{r['median']:.2f}", "max": f"{r['max']:.2f}", "n": _int(r["size"])}
                  for t, r in rt.iterrows()]

    by = df["built"].dt.year
    by = by.where(by >= PERMIT_FROM, PERMIT_FROM - 1)
    oy = df["operating"].dt.year
    years = sorted(set(by.dropna().astype(int)) | set(oy.dropna().astype(int)))
    bc, oc = by.value_counts(), oy.value_counts()
    p_labels = [f"עד {PERMIT_FROM - 1}" if y == PERMIT_FROM - 1 else str(y) for y in years]
    p_chart = {"x": p_labels,
               "series": [{"name": "היתר הקמה", "data": [int(bc.get(y, 0)) for y in years]},
                          {"name": "היתר הפעלה", "data": [int(oc.get(y, 0)) for y in years]}]}
    t_permits = [{"name": lab, "built": _int(bc.get(y, 0)), "operating": _int(oc.get(y, 0))}
                 for lab, y in zip(p_labels, years)]

    age = (ref - df["inspected"]).dt.days
    ib = []
    for lo, hi, lab in INSPECT_BINS:
        ib.append((lab, int(age.between(lo, hi).sum())))
    missing = int(df["inspected"].isna().sum())
    if missing:
        ib.append(("לא נרשמה בדיקה", missing))
    i_chart = {"names": [a for a, _ in ib], "values": [b for _, b in ib]}
    t_inspect = [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in ib]

    rules = [
        ("operators", insight_operators(df)),
        ("g5", insight_5g(df)),
        ("radiation", insight_radiation(df)),
        ("zero", insight_zero(df)),
        ("juris", insight_juris(df)),
        ("inspected", insight_inspected(df, ref)),
        ("no_permit", insight_no_permit(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    g5 = int(df["g5"].sum())
    med = float(measured["rad"].median()) if len(measured) else 0.0

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} אתרי שידור סלולריים פעילים של סלקום, פלאפון ו-PHI, נכון ל-"
                           f"{_d_he(ref)}: מיקום, סוג אתר, טכנולוגיה, היתרים ותוצאת הקרינה המרבית "
                           "ביחס לסף הבריאות."),
            "dataset_kind": "map",
            "related_ids": [],
            "suggested_tags": ["אנטנות סלולריות", "קרינה", "תקשורת", "דור 5", "סביבה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "sites": {"value": n, "display": _int(n)},
            "g5": {"value": g5, "display": _pct(g5 / n)},
            "median_rad": {"value": med, "display": f"{med:.2f}%"},
            "juris": {"value": int(df["juris"].nunique()), "display": _int(df["juris"].nunique())},
        },
        "charts": {
            "operators": o_chart,
            "types": t_chart,
            "gens": g_chart,
            "juris": {"names": j_names, "values": j_vals},
            "rad": r_chart,
            "rad_type": rt_chart,
            "permits": p_chart,
            "inspect": i_chart,
        },
        "tables": {
            "operators": t_ops,
            "op_names": list(ops.index),
            "types": t_types,
            "gens": t_gen,
            "juris": t_juris,
            "rad": t_rad,
            "rad_type": t_rad_type,
            "permits": t_permits,
            "inspect": t_inspect,
        },
        "insights": insights,
        "labels": {
            "lede": (f"מאגר המשרד להגנת הסביבה מונה {_int(n)} אתרי שידור סלולריים פעילים ב-"
                     f"{_int(df['juris'].nunique())} תחומי שיפוט. לכל אתר נרשמו היתר הקמה, היתר הפעלה, "
                     f"בדיקה תקופתית ותוצאת הקרינה המרבית שנמדדה, באחוזים מסף הבריאות. "
                     f"העדכון האחרון במאגר: {_d_he(ref)}."),
            "map_note": "כל אתר מסומן במיקומו; לחיצה על נקודה מציגה את החברה, סוג האתר והטכנולוגיה.",
            "operators_aria": "תרשים עמודות: אתרים לפי חברה מפעילה.",
            "types_aria": "תרשים עמודות: אתרים לפי סוג אתר וחברה.",
            "gens_aria": "תרשים עמודות: שיעור האתרים המשדרים בכל דור טכנולוגי, לפי חברה.",
            "juris_aria": f"תרשים עמודות: {TOP_JURIS} תחומי השיפוט עם הכי הרבה אתרים.",
            "rad_aria": "תרשים עמודות: אתרים לפי התוצאה המרבית באחוזים מסף הבריאות.",
            "rad_note": ("תוצאה של 0 נרשמת לרוב כשאין סביב האתר אזור מאוכלס ברציפות. "
                         "כל הערכים הם אחוזים מסף הבריאות."),
            "rad_type_aria": "תרשים עמודות: חציון ומקסימום התוצאה המרבית לפי סוג אתר.",
            "permits_aria": "תרשים עמודות: היתרי הקמה והפעלה לפי שנה.",
            "permits_note": ("ההיתרים מתחדשים, ולכן השנה היא של ההיתר הנוכחי — לא של הקמת האנטנה "
                             f"לראשונה. היתרי הקמה מלפני {PERMIT_FROM} מקובצים יחד."),
            "inspect_aria": "תרשים עמודות: אתרים לפי מועד הבדיקה התקופתית האחרונה.",
        },
    }
