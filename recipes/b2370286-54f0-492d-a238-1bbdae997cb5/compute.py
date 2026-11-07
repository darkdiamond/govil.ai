"""קרקעות מזוהמות — the Ministry of Environmental Protection's register of
sites with (potential) soil contamination.

One row per site: activity type, soil-status classification, soil-gas and
groundwater status, treatment, investigation dates and the date the row was
last updated. "Now" is the latest update date in the data, never the clock.

v4 (2026-11-05): the ministry's upload of 2026-11-05 dropped the `matzav`
(administrative stage) column with no replacement, so the stage chart, the
"in remediation" KPI, the pipeline insight and the stage popup field are gone;
the heatmap now crosses activity with the soil-status classification
(`legend`). The same upload writes missing values as "(חסר)" instead of an
empty cell, and spells "חשד לזיהום" as "חדש לזיהום" in `stat_zih`; both are
normalised in `_prepare`.

There is no city column: the town is derived from the free-text address. A
"root" is an address value with no digits that does not itself begin with a
shorter such value + space (that would be "town street"); each address is
assigned the longest root it starts with. Towns written twice ("X X") are
collapsed to X. An address of the form "<place>  <number>" (two spaces: the
street part is empty) also contributes <place> as a root.
"""
import re

import pandas as pd

MISSING = "(חסר)"
STATUS_ORDER = ["היתכנות לזיהום קרקע", "בחקירה/ בשיקום", "סיים שיקום או אין סיכון", MISSING]
ENV_ORDER = ["אין זיהום", "חשד לזיהום", "בחקירה", "בטיפול", "סיום טיפול"]
ENV_ACTIVE = {"חשד לזיהום", "בחקירה", "בטיפול"}
# Known misspellings in the source, mapped to the value the other column uses.
ENV_ALIASES = {"חדש לזיהום": "חשד לזיהום"}
DRISHA_ORDER = ["כן", "לא", "לא ידוע"]
# `sug` values that are not a treatment method (no decision / no treatment).
NON_METHODS = {"טרם הוחלט", "אין צורך בטיפול", "לא נדרש", "לא בוצע טיפול", "אחר"}
TOP_ACT = 12
TOP_CITIES = 15
TOP_TREAT = 10
HEAT_ACTS = 8
UPDATE_MONTHS = 24
WINDOW_DAYS = 30


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _towns(addr):
    raw = addr.str.strip()
    a = raw.str.replace(r"\s+", " ", regex=True)
    bare = {v for v in a if v and not re.search(r"\d", v)}
    for v in raw:
        m = re.match(r"^(\D+?)\s{2,}\d+$", v)
        if m and not m.group(1).startswith("לא ידוע"):
            bare.add(re.sub(r"\s+", " ", m.group(1)).strip())
    bare = sorted(bare)
    roots = [v for v in bare if not any(v.startswith(w + " ") for w in bare if w != v)]
    roots.sort(key=lambda s: (-len(s), s))

    def town(s):
        for r in roots:
            if s == r or s.startswith(r + " "):
                t = r.split(" ")
                h = len(t) // 2
                if len(t) % 2 == 0 and t[:h] == t[h:]:
                    return " ".join(t[:h])
                return r
        return ""

    return a.map(town)


def _ordered_counts(s, order):
    vc = s[s != ""].value_counts()
    known = [k for k in order if k in vc.index]
    extra = sorted(k for k in vc.index if k not in order)
    return [(k, int(vc[k])) for k in known + extra]


def _top(vc, n, other="אחר (שאר)"):
    vc = vc.sort_index().sort_values(ascending=False, kind="stable")
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _blank_missing(s):
    s = s.str.strip()
    return s.where(s != MISSING, "")


def _prepare(df):
    out = pd.DataFrame({
        "status": df["legend"].str.strip(),
        "activity": _blank_missing(df["peeilut"]),
        "gas": _blank_missing(df["stat_gas"]).replace(ENV_ALIASES),
        "water": _blank_missing(df["stat_zih"]).replace(ENV_ALIASES),
        "treat": _blank_missing(df["sug"]),
        "drisha": _blank_missing(df["drisha"]),
        "updated": pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce"),
        "begin": pd.to_datetime(df["d_begin"], format="%d/%m/%Y", errors="coerce"),
        "end": pd.to_datetime(df["d_end"], format="%d/%m/%Y", errors="coerce"),
    })
    out["town"] = _towns(df["address"])
    return out


def _methods(df):
    m = df.loc[df["treat"] != "", "treat"].str.split(";").explode().str.strip()
    return m[m != ""]


def insight_status(df):
    n = len(df)
    vc = df["status"].value_counts()
    pot = int(vc.get("היתכנות לזיהום קרקע", 0))
    inv = int(vc.get("בחקירה/ בשיקום", 0))
    done = int(vc.get("סיים שיקום או אין סיכון", 0))
    if n == 0:
        return None
    return (f"לפי סיווג מצב הקרקע, {_pct(pot / n)} מהאתרים ({_int(pot)}) מסווגים "
            f"'היתכנות לזיהום קרקע', {_int(inv)} מסווגים 'בחקירה/ בשיקום' ו-{_int(done)} "
            f"'סיים שיקום או אין סיכון'.")


def insight_activity(df):
    known = df[(df["activity"] != "") & (df["activity"] != "אחר")]
    if len(known) < 100:
        return None
    vc = known["activity"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top, v = vc.index[0], int(vc.iloc[0])
    share = v / len(known)
    if share < 0.15:
        return None
    other = int((df["activity"] == "אחר").sum())
    return (f"מבין {_int(len(known))} האתרים שסוג פעילותם מפורט, {_pct(share)} ({_int(v)}) הם "
            f"'{top}'. עוד {_int(other)} אתרים מסווגים כ'אחר'.")


def insight_updates(df, last):
    cur = df[(df["updated"] > last - pd.Timedelta(days=WINDOW_DAYS))]
    prev = df[(df["updated"] <= last - pd.Timedelta(days=WINDOW_DAYS))
              & (df["updated"] > last - pd.Timedelta(days=2 * WINDOW_DAYS))]
    a, b = len(cur), len(prev)
    if a + b < 20:
        return None
    if b == 0 or abs(a - b) / b < 0.1:
        trend = "בדומה ל-30 הימים שקדמו להם"
    elif a > b:
        trend = f"לעומת {_int(b)} ב-30 הימים שקדמו להם"
    else:
        trend = f"לעומת {_int(b)} ב-30 הימים שקדמו להם (פחות עדכונים)"
    return (f"ב-30 הימים שעד {last.day}/{last.month}/{last.year} עודכנו {_int(a)} אתרים, {trend}.")


def insight_water(df):
    w = df[df["water"] != ""]
    g = df[df["gas"] != ""]
    if len(w) < 100 or len(g) < 100:
        return None
    wa = int(w["water"].isin(ENV_ACTIVE).sum())
    ga = int(g["gas"].isin(ENV_ACTIVE).sum())
    both = int((df["water"].isin(ENV_ACTIVE) & df["gas"].isin(ENV_ACTIVE)).sum())
    return (f"מבין האתרים עם סטטוס מי תהום ידוע, ב-{_pct(wa / len(w))} ({_int(wa)}) יש חשד, "
            f"חקירה או טיפול בזיהום מי תהום; בגזי קרקע: {_pct(ga / len(g))} ({_int(ga)}). "
            f"ב-{_int(both)} אתרים שניהם פעילים.")


def insight_town(df):
    t = df[df["town"] != ""]
    if len(t) < 100:
        return None
    vc = t["town"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top, v = vc.index[0], int(vc.iloc[0])
    top3 = int(vc.head(3).sum())
    return (f"{top} מרכזת {_int(v)} אתרים ({_pct(v / len(df))} מכלל האתרים); שלושת היישובים "
            f"המובילים ({', '.join(vc.index[:3])}) מרכזים {_pct(top3 / len(df))}.")


def insight_treat(df):
    """Share of sites still without a treatment decision, and the leading
    actual method (values that are not a method are excluded, disclosed)."""
    has = df[df["treat"] != ""]
    if len(has) < 100:
        return None
    pending = int(has["treat"].str.split(";").map(
        lambda xs: any(x.strip() == "טרם הוחלט" for x in xs)).sum())
    m = _methods(df)
    m = m[~m.isin(NON_METHODS)]
    vc = m.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    if vc.empty or int(vc.iloc[0]) < 10:
        return None
    top, v = vc.index[0], int(vc.iloc[0])
    return (f"ב-{_pct(pending / len(has))} מהאתרים שיש להם רישום טיפול ({_int(pending)}) "
            f"נרשם 'טרם הוחלט'. שיטת הטיפול בפועל הנפוצה ביותר היא '{top}' ({_int(v)} אתרים), "
            f"לא כולל ערכים שאינם שיטה (כמו 'אין צורך בטיפול' או 'אחר').")


def insight_began(df):
    b = df["begin"].dropna()
    if b.dt.year.nunique() < 5:
        return None
    vc = b.dt.year.value_counts().sort_index()
    peak = int(vc.idxmax())
    return (f"לפי מועדי תחילת הטיפול המתועדים ({_int(len(b))} אתרים), השנה עם מספר "
            f"הפתיחות הגבוה ביותר היא {peak} ({_int(vc.max())} אתרים).")


def compute(frames):
    df = _prepare(frames["sites"])
    n = len(df)
    last = df["updated"].max()

    status = _ordered_counts(df["status"], STATUS_ORDER)
    act_vc = df.loc[df["activity"] != "", "activity"].value_counts()
    activity = _top(act_vc, TOP_ACT)
    env_vals = (set(df["gas"]) | set(df["water"])) - {""}
    env_labels = [k for k in ENV_ORDER if k in env_vals]
    env_labels += sorted(env_vals - set(env_labels))
    env = {
        "labels": env_labels,
        "gas": [int((df["gas"] == k).sum()) for k in env_labels],
        "water": [int((df["water"] == k).sum()) for k in env_labels],
    }
    treat = _top(_methods(df).value_counts(), TOP_TREAT)
    drisha = _ordered_counts(df["drisha"], DRISHA_ORDER)
    town_vc = df.loc[df["town"] != "", "town"].value_counts()
    towns = _top(town_vc, TOP_CITIES, other="שאר היישובים")

    upd = df.dropna(subset=["updated"])
    months = pd.period_range(end=last.to_period("M"), periods=UPDATE_MONTHS, freq="M")
    per_m = upd["updated"].dt.to_period("M").value_counts()
    updates = {"x": [str(p) for p in months], "y": [int(per_m.get(p, 0)) for p in months]}

    by = df["begin"].dropna().dt.year.value_counts()
    ey = df["end"].dropna().dt.year.value_counts()
    yrs = sorted(set(by.index) | set(ey.index))
    years = {"x": [str(int(y)) for y in yrs],
             "begin": [int(by.get(y, 0)) for y in yrs],
             "end": [int(ey.get(y, 0)) for y in yrs]}

    # Soil-status mix within each of the most common activity types (row %).
    heat_acts = [k for k, _ in _top(act_vc, HEAT_ACTS) if k != "אחר (שאר)"]
    stl = [k for k, _ in status]
    cells, rows = [], []
    for i, a in enumerate(heat_acts):
        sub = df[df["activity"] == a]
        tot = len(sub)
        row = []
        for j, s in enumerate(stl):
            c = int((sub["status"] == s).sum())
            p = round(c / tot * 100, 1) if tot else 0.0
            row.append(f"{p:.1f}%")
            if tot and c:
                cells.append([j, i, p, c])
        rows.append({"name": a, "total": tot, "cells": row})
    heat = {"x": stl, "y": heat_acts, "cells": cells,
            "max": max((c[2] for c in cells), default=0)}

    in_inv = int((df["status"] == "בחקירה/ בשיקום").sum())
    water_known = int((df["water"] != "").sum())
    water_active = int(df["water"].isin(ENV_ACTIVE).sum())
    recent = int((df["updated"] > last - pd.Timedelta(days=WINDOW_DAYS)).sum())
    recent_prev = int(((df["updated"] <= last - pd.Timedelta(days=WINDOW_DAYS))
                       & (df["updated"] > last - pd.Timedelta(days=2 * WINDOW_DAYS))).sum())
    no_town = int((df["town"] == "").sum())
    no_gas = int((df["gas"] == "").sum())
    no_water = n - water_known
    no_drisha = int((df["drisha"] == "").sum())
    no_treat = int((df["treat"] == "").sum())

    rules = [
        ("status", insight_status(df)),
        ("activity", insight_activity(df)),
        ("water", insight_water(df)),
        ("treat", insight_treat(df)),
        ("town", insight_town(df)),
        ("updates", insight_updates(df, last)),
        ("began", insight_began(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    last_he = f"{last.day}/{last.month}/{last.year}"
    top_town = towns[0][0] if towns and towns[0][0] != "שאר היישובים" else ""

    return {
        "agent_data": {
            "summary_he": (f"מאגר האתרים עם קרקע מזוהמת או חשד לזיהום של המשרד להגנת הסביבה: "
                           f"{_int(n)} אתרים, מהם {_int(in_inv)} מסווגים בחקירה או בשיקום. "
                           f"מעודכן עד {last_he}."),
            "dataset_kind": "map",
            "temporal_coverage": f"{df['updated'].min().strftime('%Y-%m-%d')}/{last.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "קרקעות מזוהמות: מפת אתרים ואיתור לפי כתובת",
                "description": (f"איתור אתרי קרקע מזוהמת או חשודה בזיהום לפי שם, כתובת וגוש, "
                                f"על מפה: {_int(n)} אתרים, {_int(in_inv)} מהם בחקירה או בשיקום. "
                                f"עדכון אחרון {last_he}."),
                "name": "מאגר הקרקעות המזוהמות",
                "alternate_names": ["קרקעות מזוהמות", "אתרי קרקע מזוהמת",
                                    "המאגר הלאומי לקרקעות מזוהמות"],
            },
        },
        "kpis": {
            "sites": {"value": n, "display": _int(n), "tone": "brand"},
            # Open contamination cases are a caution sign; none open is good.
            "investigating": {"value": in_inv, "display": _int(in_inv),
                              "tone": "warn" if in_inv else "ok"},
            "water": {"value": water_active, "display": _int(water_active),
                      "tone": "warn" if water_active else "ok"},
            "recent": {"value": recent, "display": _int(recent), "tone": "brand"},
        },
        "charts": {
            "status": {"names": [k for k, _ in status], "values": [v for _, v in status]},
            "activity": {"names": [k for k, _ in activity], "values": [v for _, v in activity]},
            "env": env,
            "treat": {"names": [k for k, _ in treat], "values": [v for _, v in treat]},
            "drisha": {"names": [k for k, _ in drisha], "values": [v for _, v in drisha]},
            "towns": {"names": [k for k, _ in towns], "values": [v for _, v in towns]},
            "updates": updates,
            "years": years,
            "heat": heat,
        },
        "tables": {"heat": rows},
        "insights": insights,
        "labels": {
            "inv_kpi": f"מסווגים 'בחקירה/ בשיקום' ({_pct(in_inv / n)} מהאתרים)",
            "water_kpi": (f"עם חשד, חקירה או טיפול בזיהום מי תהום "
                          f"(מתוך {_int(water_known)} עם סטטוס ידוע)"),
            "recent_kpi": (f"עודכנו ב-{WINDOW_DAYS} הימים האחרונים "
                           f"(ב-{WINDOW_DAYS} הימים שקדמו: {_int(recent_prev)})"),
            "lede": (f"{_int(n)} אתרים עם קרקע מזוהמת או חשד לזיהום, לפי סוג פעילות, סיווג "
                     f"מצב הקרקע, שיטת הטיפול ומצב גזי הקרקע ומי התהום. העדכון האחרון במאגר: "
                     f"{last_he}."),
            "lookup_sub": (f"חיפוש חי בכל {_int(n)} רשומות המאגר: שם האתר, כתובת, גוש וחלקה"
                           + (f" (למשל {top_town})." if top_town else ".")),
            "as_of": last_he,
            "status_aria": f"תרשים עמודות: {_int(n)} האתרים לפי סיווג מצב הקרקע.",
            "activity_aria": f"תרשים עמודות: האתרים לפי סוג הפעילות, {len(activity)} קטגוריות.",
            "activity_note": f"ל-{_int((df['activity'] == '').sum())} אתרים לא צוין סוג פעילות והם אינם מוצגים.",
            "env_aria": "תרשים עמודות מקובצות: מצב גזי הקרקע ומי התהום באתרים.",
            "env_note": (f"מצב הזיהום בגזי הקרקע ובמי התהום. ללא סטטוס (אינם מוצגים): "
                         f"{_int(no_gas)} אתרים בגזי קרקע ו-{_int(no_water)} במי תהום."),
            "treat_aria": f"תרשים עמודות: שיטות הטיפול שנקבעו, {len(treat)} קטגוריות.",
            "treat_note": (f"באתר אחד עשויות להופיע כמה שיטות טיפול; כל שיטה נספרת בנפרד. "
                           f"ל-{_int(no_treat)} אתרים לא נרשם טיפול."),
            "drisha_aria": "תרשים עמודות: האתרים לפי שדה הדרישה במאגר.",
            "drisha_note": (f"ערכי שדה הדרישה כפי שהם מופיעים במאגר. ל-{_int(no_drisha)} "
                            f"אתרים השדה חסר והם אינם מוצגים."),
            "towns_aria": f"תרשים עמודות: {len(towns)} היישובים עם מספר האתרים הגבוה ביותר.",
            "towns_note": (f"היישוב חולץ מתוך שדה הכתובת; ל-{_int(no_town)} אתרים לא זוהה יישוב."),
            "updates_aria": f"גרף עמודות: מספר האתרים שעודכנו בכל חודש, ב-{UPDATE_MONTHS} החודשים האחרונים.",
            "updates_note": ("כל אתר נספר בחודש העדכון האחרון שלו בלבד, כך שחודשים קודמים "
                             "מציגים רק אתרים שלא עודכנו מאז."),
            "years_aria": "גרף עמודות: מספר האתרים לפי שנת תחילת הטיפול ושנת סיומו.",
            "years_note": (f"מועד תחילה מתועד ל-{_int(df['begin'].notna().sum())} אתרים ומועד "
                           f"סיום ל-{_int(df['end'].notna().sum())} בלבד."),
            "heat_aria": (f"מפת חום: התפלגות סיווג מצב הקרקע בכל אחד מ-{len(heat_acts)} "
                          f"סוגי הפעילות הנפוצים, באחוזים."),
        },
    }
