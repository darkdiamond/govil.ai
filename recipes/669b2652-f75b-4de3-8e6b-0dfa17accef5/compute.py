"""מאגר שמאי מקרקעין — Ministry of Justice, real-estate appraisers.

Three independent tables, no shared key between them:

* ``register`` — the current list of licensed appraisers (~3.2k): name,
  licence number, file number, city (city is ~88% empty). No dates.
* ``exams`` — one row per exam attempt (~94k, anonymous): exam subject,
  sitting date, the candidate's academic institution (or a background
  category such as "תואר מאושר"), and the score (empty = no score).
* ``exempt`` — one row per exam exemption granted on the basis of academic
  studies (~4.9k, anonymous): exam subject, date, institution.

Exams and exemptions share the subject and institution vocabulary, so the
page compares them per subject; the register stands on its own.

"Now" is the latest exam sitting in the data, never the wall clock; that
year is partial unless the sitting falls late in December. A score of 60 and
above counts as a pass (the pass mark; the score histogram's spike at 60 is
the data's own evidence). Scores outside 0–100 are treated as invalid.

Licence/file numbers are individual identifiers and never reach the page;
names are used only in aggregate (most common surnames).
"""
import re

import pandas as pd

PASS = 60
NO_INST = "לא צוין"
CATEGORY_INST = {NO_INST, "אחר", "תואר מאושר", "רישיון מאושר"}
SURNAME_PREFIX = {"בן", "אבו", "אבן", "בית", "דה", "די", "ון", "פון", "אל"}
TOP_INST = 12
TOP_EX_INST = 12
TOP_NAMES = 15
TOP_HEAT = 30
INST_MIN = 1000
EXAM_MIN = 500
YEAR_MIN = 100
CURRENT_GAP = 2
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
C_PASS, C_FAIL, C_NONE = "#0068f5", "#dc3545", "#6c757d"
C_CUR, C_OLD = "#0068f5", "#9fb4d3"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _clean(s):
    return s.str.replace("~", "״", regex=False).str.replace(r"\s+", " ", regex=True).str.strip()


def _fold_names(names):
    """Map a truncated subject name onto its one-character-longer twin."""
    uniq = sorted(set(names))
    out = {}
    for a in uniq:
        longer = [b for b in uniq if len(b) == len(a) + 1 and b.startswith(a)]
        out[a] = longer[0] if longer else a
    return out


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _surname(name):
    t = name.split()
    if not t:
        return ""
    if len(t) >= 3 and t[0] in SURNAME_PREFIX:
        return t[0] + " " + t[1]
    return t[0]


def _prepare_exams(df, fold):
    subj = _clean(df["תיאור הבחינה"])
    out = pd.DataFrame({
        "date": pd.to_datetime(df["תאריך הבחינה"].str.strip(), errors="coerce", format="%d/%m/%Y"),
        "inst": _clean(df["מוסד לימודי"]).replace("", NO_INST),
    })
    out["subj"] = subj.map(fold)
    raw = pd.to_numeric(df["ציון"].str.strip(), errors="coerce")
    out["invalid"] = raw.notna() & ((raw < 0) | (raw > 100))
    out["score"] = raw.where(~out["invalid"])
    out["scored"] = out["score"].notna()
    out["passed"] = out["score"] >= PASS
    out = out.dropna(subset=["date"])
    out["year"] = out["date"].dt.year.astype(int)
    return out


def _prepare_exempt(df, fold):
    subj = _clean(df["תיאור הבחינה"])
    out = pd.DataFrame({
        "date": pd.to_datetime(df["תאריך הבחינה"].str.strip(), errors="coerce", format="%d/%m/%Y"),
        "inst": _clean(df["מוסד לימודי"]).replace("", NO_INST),
    })
    out["subj"] = subj.map(fold)
    out["year"] = out["date"].dt.year
    return out


def _rate(p, s):
    return p / s * 100 if s else None


# ---------------------------------------------------------------- insights

def insight_overall(ex, first_year, ref):
    sc = int(ex["scored"].sum())
    if sc < 1000:
        return None
    ps = int(ex["passed"].sum())
    fail = 1 - ps / sc
    tail = ("; כמעט מחצית מהניגשויות מסתיימות בכישלון" if 0.4 <= fail <= 0.5 else
            ("; יותר ממחצית מהניגשויות מסתיימות בכישלון" if fail > 0.5 else ""))
    return (f"מ-{first_year} ועד {d_he(ref)} נרשמו {n(len(ex))} ניגשויות לבחינות השמאות; "
            f"מתוך {n(sc)} שקיבלו ציון, {pct(ps / sc * 100)} עברו (ציון {PASS} ומעלה){tail}.")


def insight_bunching(hist):
    at, below = hist.get(PASS, 0), hist.get(PASS - 1, 0)
    if at < 100 or at < 5 * max(below, 1):
        return None
    mode = int(max(hist.items(), key=lambda kv: (kv[1], -kv[0]))[0])
    lead = (f"{PASS} — ציון המעבר — הוא הציון הנפוץ ביותר במאגר"
            if mode == PASS else f"ציון המעבר {PASS} בולט בהתפלגות")
    ratio = at / below if below else None
    tail = (f"פי {ratio:.0f} יותר" if ratio else "בעוד שאיש לא קיבל")
    return (f"{lead}: {n(at)} ניגשויות הסתיימו בדיוק בציון {PASS}, לעומת {n(below)} בלבד "
            f"בציון {PASS - 1} ({tail}).")


def insight_trend(per_year, last_full):
    if last_full not in per_year.index or (last_full - 1) not in per_year.index:
        return None
    cur, prev = per_year.loc[last_full], per_year.loc[last_full - 1]
    if cur["scored"] < YEAR_MIN or prev["scored"] < YEAR_MIN:
        return None
    r1, r0 = cur["passed"] / cur["scored"] * 100, prev["passed"] / prev["scored"] * 100
    d = r1 - r0
    if round(d) == 0:
        chg = f"ללא שינוי לעומת {last_full - 1} ({pct(r0)})"
    else:
        chg = (f"{'עלייה' if d > 0 else 'ירידה'} של {abs(d):.0f} נקודות אחוז לעומת "
               f"{last_full - 1} ({pct(r0)})")
    return (f"ב-{last_full} עברו {pct(r1)} מהניגשויות שקיבלו ציון ({n(cur['passed'])} מתוך "
            f"{n(cur['scored'])}) — {chg}.")


def insight_ytd(ex, ref, partial):
    if not partial:
        return None
    y = ref.year
    md = (ex["date"].dt.month * 100 + ex["date"].dt.day) <= (ref.month * 100 + ref.day)
    cur = ex[(ex["year"] == y) & ex["scored"]]
    prev = ex[(ex["year"] == y - 1) & md & ex["scored"]]
    if len(cur) < 300 or len(prev) < 300:
        return None
    r1, r0 = cur["passed"].mean() * 100, prev["passed"].mean() * 100
    d = r1 - r0
    if round(d) == 0:
        chg = f"ללא שינוי לעומת התקופה המקבילה ב-{y - 1} ({pct(r0)})"
    else:
        chg = (f"{'גבוה' if d > 0 else 'נמוך'} ב-{abs(d):.0f} נקודות אחוז מבתקופה המקבילה "
               f"ב-{y - 1} ({pct(r0)})")
    return (f"מתחילת {y} ועד {d_he(ref)} עברו {pct(r1)} מ-{n(len(cur))} הניגשויות שקיבלו ציון — "
            f"{chg}.")


def insight_subjects(subj_tbl):
    cur = subj_tbl[subj_tbl["current"] & (subj_tbl["scored"] >= EXAM_MIN)]
    if len(cur) < 3:
        return None
    lo, hi = cur.iloc[-1], cur.iloc[0]
    if hi["rate"] - lo["rate"] < 10:
        return None
    return (f"הבחינה הקשה ביותר בתוכנית הנוכחית היא \"{lo.name}\": רק {pct(lo['rate'])} מהניגשויות "
            f"הסתיימו במעבר; הקלה ביותר היא \"{hi.name}\" עם {pct(hi['rate'])} מעבר "
            f"(מתוך בחינות עם {n(EXAM_MIN)} ציונים לפחות).")


def insight_institutions(inst_tbl):
    real = inst_tbl[~inst_tbl.index.isin(CATEGORY_INST) & (inst_tbl["scored"] >= INST_MIN)]
    if len(real) < 3:
        return None
    real = real.sort_values(["rate", "scored"], ascending=[False, False], kind="stable")
    hi, lo = real.iloc[0], real.iloc[-1]
    if hi["rate"] - lo["rate"] < 10:
        return None
    return (f"בין מוסדות הלימוד עם {n(INST_MIN)} ציונים לפחות, שיעור המעבר הגבוה ביותר הוא של "
            f"בוגרי {hi.name} ({pct(hi['rate'])}) והנמוך ביותר של בוגרי {lo.name} "
            f"({pct(lo['rate'])}).")


def insight_exempt(exm, subj_att):
    if len(exm) < 100:
        return None
    by = _sorted_counts(exm["subj"])
    top, v = by.index[0], int(by.iloc[0])
    att = int(subj_att.get(top, 0))
    s = (f"נרשמו {n(len(exm))} פטורים מבחינה בזכות לימודים אקדמיים; המובילה היא \"{top}\" עם "
         f"{n(v)} פטורים ({pct(v / len(exm) * 100)})")
    if att:
        s += f", לעומת {n(att)} ניגשויות לאותה בחינה"
    return s + "."


def insight_noscore(per_year, last_full, total_none, total):
    if total == 0 or total_none == 0:
        return None
    base = total_none / total
    s = f"ל-{n(total_none)} ניגשויות ({pct(base * 100)}) אין ציון במאגר"
    if last_full in per_year.index and per_year.loc[last_full, "n"] >= YEAR_MIN:
        r = per_year.loc[last_full, "none"] / per_year.loc[last_full, "n"]
        if r >= 1.25 * base:
            s += f"; ב-{last_full} שיעורן עלה ל-{pct(r * 100)}"
    return s + " — הן נספרות בניגשויות אך לא בשיעור המעבר."


def insight_season(month_counts):
    tot = month_counts.sum()
    if tot < 1000:
        return None
    top = month_counts.sort_index().sort_values(ascending=False, kind="stable").head(3)
    sh = top.sum() / tot
    if sh < 0.4:
        return None
    names = [MONTHS_HE[m - 1] for m in top.index]
    return (f"הבחינות מרוכזות במועדים קבועים: {names[0]}, {names[1]} ו{names[2]} לבדם "
            f"מרכזים {pct(sh * 100, 0)} מכלל הניגשויות.")


def insight_register(surnames, total):
    if len(surnames) < 2 or total == 0:
        return None
    (a, va), (b, vb) = list(surnames.items())[:2]
    if va < 1.3 * vb:
        return None
    return (f"במרשם {n(total)} שמאי מקרקעין בעלי רישיון; שם המשפחה הנפוץ ביניהם הוא {a} "
            f"({n(va)} שמאים, {pct(va / total * 100)}), ואחריו {b} ({n(vb)}).")


def insight_cities(cities, total):
    known = int(cities.sum())
    if known < 100 or known / total < 0.05:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / known < 0.2:
        return None
    return (f"רק ל-{n(known)} מהשמאים במרשם ({pct(known / total * 100)}) מצוינת עיר; מתוכם "
            f"{pct(v / known * 100, 0)} ב{top}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    reg = frames["register"]
    fold = _fold_names(set(_clean(frames["exams"]["תיאור הבחינה"]))
                       | set(_clean(frames["exempt"]["תיאור הבחינה"])))
    ex = _prepare_exams(frames["exams"], fold)
    exm = _prepare_exempt(frames["exempt"], fold)

    ref = ex["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 20)
    last_full = ref_year - 1 if partial else ref_year
    first_year = int(ex["year"].min())
    years = list(range(first_year, ref_year + 1))

    ex["none"] = ~ex["scored"]
    py = ex.groupby("year").agg(n=("subj", "size"), scored=("scored", "sum"),
                                passed=("passed", "sum"), none=("none", "sum"),
                                ssum=("score", "sum")).reindex(years, fill_value=0)
    py = py.astype({"n": int, "scored": int, "passed": int, "none": int})
    rate_y = [round(_rate(r.passed, r.scored), 1) if r.scored >= YEAR_MIN else None
              for r in py.itertuples()]
    mean_y = [round(r.ssum / r.scored, 1) if r.scored >= YEAR_MIN else None
              for r in py.itertuples()]

    # Score histogram.
    sc = ex.loc[ex["scored"], "score"].round().astype(int)
    hist = sc.value_counts().reindex(range(0, 101), fill_value=0)
    hist_d = {int(k): int(v) for k, v in hist.items()}
    median = float(sc.median()) if len(sc) else 0.0

    # Subjects.
    g = ex.groupby("subj").agg(n=("year", "size"), scored=("scored", "sum"), passed=("passed", "sum"),
                               ssum=("score", "sum"), first=("year", "min"), last=("year", "max"))
    g["rate"] = g["passed"] / g["scored"].where(g["scored"] > 0) * 100
    g["mean"] = g["ssum"] / g["scored"].where(g["scored"] > 0)
    g["current"] = g["last"] >= ref_year - CURRENT_GAP
    g = g.reset_index().sort_values(["rate", "n", "subj"], ascending=[False, False, True],
                                    kind="stable", na_position="last").set_index("subj")
    subj_tbl = g
    subj_att = g["n"]

    # Exam × year heatmap.
    heat_subj = (g.reset_index().sort_values(["n", "subj"], ascending=[False, True]).head(TOP_HEAT)
                 .sort_values(["first", "last", "subj"]).set_index("subj").index.tolist())
    hy = ex[ex["subj"].isin(heat_subj)].groupby(["subj", "year"]).size()
    cells = []
    for yi, s in enumerate(heat_subj):
        for xi, y in enumerate(years):
            v = int(hy.get((s, y), 0))
            if v:
                cells.append([xi, yi, v])

    # Calendar months.
    mc = ex.groupby(ex["date"].dt.month).size().reindex(range(1, 13), fill_value=0)

    # Institutions.
    ig = ex.groupby("inst").agg(n=("year", "size"), scored=("scored", "sum"), passed=("passed", "sum"))
    ig["rate"] = ig["passed"] / ig["scored"].where(ig["scored"] > 0) * 100
    inst_tbl = ig
    no_inst = int(ig["n"].get(NO_INST, 0))
    top_inst = (ig[ig.index != NO_INST].reset_index().sort_values(["n", "inst"], ascending=[False, True])
                .head(TOP_INST).set_index("inst"))

    # Exemptions.
    exm_y = exm.dropna(subset=["year"])
    ey = exm_y.groupby(exm_y["year"].astype(int)).size()
    e_years = list(range(int(ey.index.min()), int(ey.index.max()) + 1)) if len(ey) else []
    ey = ey.reindex(e_years, fill_value=0)
    es = _sorted_counts(exm["subj"])
    e_subj = list(es.index)
    einst = _sorted_counts(exm.loc[exm["inst"] != NO_INST, "inst"])
    e_top = list(einst.head(TOP_EX_INST).index)
    e_other = int(einst.iloc[TOP_EX_INST:].sum())
    e_noinst = int((exm["inst"] == NO_INST).sum())
    e_ref = exm_y["date"].max() if len(exm_y) else None
    e_last_full = None
    if len(ey):
        e_last_full = int(ey.index.max()) - (0 if (e_ref.month == 12 and e_ref.day >= 20) else 1)

    # Register.
    names = reg["שם שמאי"].str.replace(r"\s+", " ", regex=True).str.strip()
    total_reg = int((names != "").sum())
    surnames = _sorted_counts(names[names != ""].map(_surname))
    surnames = surnames[surnames.index != ""]
    city = reg["עיר"].str.replace(r"\s+", " ", regex=True).str.strip()
    city = city.str.replace(r"\s*-\s*", " - ", regex=True)
    cities = _sorted_counts(city[city != ""])

    charts = {
        "years": {"x": [str(y) for y in years],
                  "series": [
                      {"name": "עברו", "color": C_PASS, "data": [int(v) for v in py["passed"]]},
                      {"name": "נכשלו", "color": C_FAIL,
                       "data": [int(a - b) for a, b in zip(py["scored"], py["passed"])]},
                      {"name": "ללא ציון", "color": C_NONE, "data": [int(v) for v in py["none"]]}]},
        "rate": {"x": [str(y) for y in years], "rate": rate_y, "mean": mean_y, "pass": PASS},
        "dist": {"x": [str(i) for i in range(0, 101)], "y": [hist_d[i] for i in range(0, 101)],
                 "pass": PASS, "c_pass": C_PASS, "c_fail": C_FAIL},
        "subjects": {"names": list(g.index),
                     "rate": [None if pd.isna(v) else round(float(v), 1) for v in g["rate"]],
                     "n": [int(v) for v in g["n"]],
                     "colors": [C_CUR if c else C_OLD for c in g["current"]]},
        "heat": {"x": [str(y) for y in years], "y": heat_subj, "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "months": {"x": MONTHS_HE, "y": [int(v) for v in mc.values]},
        "inst": {"names": list(top_inst.index), "n": [int(v) for v in top_inst["n"]],
                 "rate": [None if pd.isna(v) else round(float(v), 1) for v in top_inst["rate"]]},
        "e_years": {"x": [str(y) for y in e_years], "y": [int(v) for v in ey.values]},
        "e_subj": {"names": e_subj, "exempt": [int(es[s]) for s in e_subj],
                   "att": [int(subj_att.get(s, 0)) for s in e_subj]},
        "e_inst": {"names": e_top + (["יתר המוסדות"] if e_other else []),
                   "values": [int(einst[s]) for s in e_top] + ([e_other] if e_other else [])},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
    }

    total_none = int(py["none"].sum())
    rules = [
        ("overall", insight_overall(ex, first_year, ref)),
        ("trend", insight_trend(py, last_full)),
        ("ytd", insight_ytd(ex, ref, partial)),
        ("bunching", insight_bunching(hist_d)),
        ("subjects", insight_subjects(subj_tbl)),
        ("institutions", insight_institutions(inst_tbl)),
        ("exempt", insight_exempt(exm, subj_att)),
        ("season", insight_season(mc)),
        ("noscore", insight_noscore(py, last_full, total_none, len(ex))),
        ("register", insight_register(surnames, total_reg)),
        ("cities", insight_cities(cities, total_reg)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    tot_sc = int(py["scored"].sum())
    overall = py["passed"].sum() / tot_sc * 100 if tot_sc else 0
    lf = py.loc[last_full] if last_full in py.index else None
    lf_rate = (lf["passed"] / lf["scored"] * 100) if lf is not None and lf["scored"] else 0
    rate_tone = "ok" if lf_rate >= overall + 3 else ("warn" if lf_rate <= overall - 3 else "brand")
    kpis = {
        "register": {"value": total_reg, "display": n(total_reg), "tone": "brand"},
        "attempts": {"value": len(ex), "display": n(len(ex)), "tone": "brand"},
        "rate": {"value": round(float(lf_rate), 1), "display": f"{lf_rate:.1f}%", "tone": rate_tone},
        "exempt": {"value": len(exm), "display": n(len(exm)), "tone": "info"},
    }

    invalid = int(ex["invalid"].sum())
    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    peak_rate_i = max((i for i, v in enumerate(rate_y) if v is not None), key=lambda i: (rate_y[i], -i))
    cur_n = int(g["current"].sum())
    e_partial = (f" {e_years[-1]} — שנה חלקית." if e_years and e_last_full != e_years[-1] else "")
    labels = {
        "lede": (f"המאגר של משרד המשפטים מאגד שלושה קבצים נפרדים על מקצוע שמאות המקרקעין: מרשם של "
                 f"{n(total_reg)} שמאים בעלי רישיון, {n(len(ex))} ניגשויות לבחינות הרישוי "
                 f"מ-{first_year} ועד {d_he(ref)}, ו-{n(len(exm))} פטורים מבחינה בזכות לימודים "
                 f"אקדמיים. הקבצים אינם מקושרים זה לזה — אין בהם מזהה נבחן — ולכן כל ניגשות "
                 f"נספרת בנפרד, כולל ניגשויות חוזרות. המאגר אינו מציין סף מעבר; שיעורי המעבר בעמוד "
                 f"מחושבים לפי ציון {PASS} ומעלה — סף המעבר המקובל בבחינות אלה."),
        "rate_kpi": f"שיעור המעבר ב-{last_full} (ממוצע כל השנים: {overall:.1f}%)",
        "years_note": (f"ניגשויות לבחינות בכל שנה, לפי תוצאה: עבר (ציון {PASS} ומעלה), נכשל, "
                       f"או ללא ציון במאגר.{partial_note}"),
        "years_aria": (f"גרף עמודות מוערמות: ניגשויות לבחינות השמאות לפי שנה ותוצאה, "
                       f"{first_year} עד {ref_year}."),
        "years_caption": "ניגשויות, מעברים, כישלונות ורשומות ללא ציון, לפי שנה.",
        "rate_note": (f"שיעור המעבר (ציון {PASS} ומעלה מתוך הניגשויות שקיבלו ציון) והציון הממוצע "
                      f"בכל שנה. שנים עם פחות מ-{n(YEAR_MIN)} ציונים אינן מוצגות.{partial_note}"),
        "rate_aria": (f"גרף קווים: שיעור המעבר והציון הממוצע לפי שנה; שיעור המעבר הגבוה ביותר "
                      f"ב-{years[peak_rate_i]} ({rate_y[peak_rate_i]}%)."),
        "rate_caption": "שיעור מעבר וציון ממוצע לפי שנה.",
        "dist_note": (f"מספר הניגשויות שקיבלו כל ציון, מ-0 עד 100; ציון {PASS} ומעלה בכחול. "
                      f"הציון החציוני: {median:.0f}."
                      + ((" ציון אחד מחוץ לטווח 0–100 הוצא כשגוי." if invalid == 1 else f" {n(invalid)} ציונים מחוץ לטווח 0–100 הוצאו כשגויים.") if invalid else "")),
        "dist_aria": (f"היסטוגרמה: התפלגות הציונים בבחינות השמאות, שיא בולט בציון {PASS} "
                      f"({n(hist_d[PASS])} ניגשויות)."),
        "subj_note": (f"שיעור המעבר בכל בחינה בכל השנים. בכחול — {n(cur_n)} בחינות שנערכו "
                      f"ב-{ref_year - CURRENT_GAP} ואילך (התוכנית הנוכחית); בתכלת — בחינות של "
                      f"תוכניות קודמות שהופסקו. שמות שנכתבו בקיצור במקור אוחדו."),
        "subj_aria": (f"תרשים עמודות אופקי: שיעור המעבר לפי בחינה, {g.index[0]} בראש."),
        "subj_caption": "ניגשויות, שנות קיום, שיעור מעבר וציון ממוצע לפי בחינה.",
        "heat_note": (f"מספר הניגשויות לכל בחינה בכל שנה — כאן רואים את החלפת תוכנית הבחינות: "
                      f"בחינות ותיקות נעלמות ובחינות חדשות נכנסות במקומן."),
        "heat_aria": f"מפת חום: ניגשויות לפי בחינה ושנה, {first_year} עד {ref_year}.",
        "months_note": "כלל הניגשויות בכל השנים לפי חודש הבחינה — מועדי הבחינות מרוכזים בעונות קבועות.",
        "months_aria": f"תרשים עמודות: ניגשויות לפי חודש, {MONTHS_HE[int(mc.idxmax()) - 1]} בראש.",
        "months_caption": "ניגשויות לפי חודש הבחינה.",
        "inst_note": (f"{TOP_INST} מוסדות הלימוד (או קטגוריות הרקע, כמו \"תואר מאושר\") עם מספר "
                      f"הניגשויות הגדול ביותר, ושיעור המעבר של כל אחד."
                      + (f" {n(no_inst)} ניגשויות ללא מוסד אינן נכללות." if no_inst else "")),
        "inst_aria": (f"תרשים עמודות וקו: ניגשויות ושיעור מעבר לפי מוסד לימודים, "
                      f"{top_inst.index[0]} בראש."),
        "inst_caption": "ניגשויות ושיעור מעבר לפי מוסד לימודים.",
        "e_years_note": f"פטורים מבחינות שניתנו בזכות לימודים אקדמיים, לפי שנה.{e_partial}",
        "e_years_aria": (f"תרשים עמודות: פטורים מבחינה לפי שנה, {e_years[0]} עד {e_years[-1]}."
                         if e_years else "תרשים עמודות: פטורים מבחינה לפי שנה."),
        "e_years_caption": "פטורים מבחינה לפי שנה.",
        "e_subj_note": ("פטורים לעומת ניגשויות לכל בחינה (בכל השנים). הניגשויות כוללות ניגשויות "
                        "חוזרות, ולכן היחס ביניהם אינו שיעור פטור מדויק."),
        "e_subj_aria": f"תרשים עמודות אופקי: פטורים וניגשויות לפי בחינה, {e_subj[0]} בראש.",
        "e_subj_caption": "פטורים וניגשויות לפי בחינה.",
        "e_inst_note": (f"המוסדות שלימודיהם הקנו את מרב הפטורים ({TOP_EX_INST} המובילים; השאר מקובצים תחת \"יתר המוסדות\")."
                        + (f" {n(e_noinst)} פטורים ללא מוסד אינם נכללים." if e_noinst else "")),
        "e_inst_aria": f"תרשים עמודות אופקי: פטורים לפי מוסד לימודים, {e_top[0]} בראש." if e_top else
                       "תרשים עמודות אופקי: פטורים לפי מוסד לימודים.",
        "e_inst_caption": "פטורים לפי מוסד לימודים.",
        "surnames_note": (f"{TOP_NAMES} שמות המשפחה הנפוצים במרשם השמאים בעלי הרישיון "
                          f"(המילה הראשונה בשם, או שתיים בצירופים כמו \"בן\")."),
        "surnames_aria": (f"תרשים עמודות אופקי: {TOP_NAMES} שמות המשפחה הנפוצים בקרב השמאים — "
                          f"{surnames.index[0]} בראש."),
        "surnames_caption": "מספר שמאים לפי שם משפחה.",
    }

    tables = {
        "years": [{"year": str(y), "n": n(r.n), "passed": n(r.passed), "failed": n(r.scored - r.passed),
                   "none": n(r.none)} for y, r in zip(years, py.itertuples())],
        "rate": [{"year": str(y), "rate": "—" if rv is None else f"{rv:.1f}%",
                  "mean": "—" if mv is None else f"{mv:.1f}"}
                 for y, rv, mv in zip(years, rate_y, mean_y)],
        "subjects": [{"name": s, "years": (str(int(r["first"])) if r["first"] == r["last"]
                                           else f"{int(r['first'])}–{int(r['last'])}"),
                      "n": n(r["n"]), "rate": "—" if pd.isna(r["rate"]) else f"{r['rate']:.1f}%",
                      "mean": "—" if pd.isna(r["mean"]) else f"{r['mean']:.1f}"}
                     for s, r in g.iterrows()],
        "months": [{"month": MONTHS_HE[m - 1], "n": n(mc[m])} for m in range(1, 13)],
        "inst": [{"name": s, "n": n(r["n"]), "rate": "—" if pd.isna(r["rate"]) else f"{r['rate']:.1f}%"}
                 for s, r in top_inst.iterrows()],
        "e_years": [{"year": str(y), "n": n(v)} for y, v in ey.items()],
        "e_subj": [{"name": s, "exempt": n(es[s]), "att": n(subj_att.get(s, 0))} for s in e_subj],
        "e_inst": [{"name": a, "n": n(b)} for a, b in zip(charts["e_inst"]["names"],
                                                          charts["e_inst"]["values"])],
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"שמאי מקרקעין בישראל: מרשם של {n(total_reg)} שמאים בעלי רישיון, "
                           f"{n(len(ex))} ניגשויות לבחינות הרישוי מ-{first_year} ועד {ref_year} "
                           f"(שיעור מעבר כולל {overall:.1f}%), ו-{n(len(exm))} פטורים מבחינה "
                           f"בזכות לימודים אקדמיים."),
            "dataset_kind": "registry",
            "related_ids": ["ad4e7cbf-0f86-4e8a-b159-6dd6f3a003ef",
                            "713440a1-9963-4548-a7d9-9d9c9da54f62",
                            "d08d4a17-78f6-43a5-83f9-e6465e64cd24",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
            "suggested_tags": ["שמאי מקרקעין", "רישוי מקצועי", "בחינות רישוי", "משרד המשפטים",
                               "שומת מקרקעין", "מרשמים מקצועיים"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
