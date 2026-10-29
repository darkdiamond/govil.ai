"""רשימת מוהלים ארצית — the Chief Rabbinate's list of certified mohels.

One row per mohel: name, settlement, contact details and the month their
certification expires. There is no clock in a recipe, so "now" never appears:
every statement is about the distribution of expiry dates in the list.

Registration numbers, phones and street addresses never reach the page. Names
are used only as aggregate counts (most common first / last names).
Settlement spellings vary in the source ("באר שבע"/"באר-שבע", "תל אביב"/
"תל אביב יפו"); they are folded on a normalized key and shown under their
most common spelling.
"""
import re

import pandas as pd

TOP_CITIES = 15
TOP_NAMES = 10
HEAT_YEARS = 12
MAX_MONTH_POINTS = 120
SIZE_BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, None)]
CITY_ALIAS = {"תל אביב יפו": "תל אביב", "ישוב יצהר": "יצהר", "ישוב אדם": "אדם",
              "כפר הרוא\"ה": "כפר הרא\"ה"}
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def mon_year(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _city_display(s):
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"\s*-\s*", "-", s)
    return CITY_ALIAS.get(s, s)


def _city_key(s):
    k = re.sub(r"[\s\-–\"'״׳]", "", s)
    return k.replace("וו", "ו").replace("יי", "י")


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = pd.DataFrame({
        "last": df["lastname"].str.strip(),
        "first": df["firstname"].str.strip().str.split().str[0].fillna(""),
        "exp": pd.to_datetime(df["certificationexpiresengdate"].str.strip(),
                              errors="coerce", format="%d/%m/%Y"),
    })
    out["period"] = out["exp"].dt.to_period("M")
    raw = df["city"].map(_city_display)
    known = raw != ""
    key = raw.map(_city_key)
    variants = (pd.DataFrame({"key": key[known], "city": raw[known]})
                .groupby(["key", "city"]).size().reset_index(name="n")
                .sort_values(["key", "n", "city"], ascending=[True, False, True]))
    canon = variants.drop_duplicates("key").set_index("key")["city"]
    out["city"] = key.map(canon).where(known, "")
    out["raw_city"] = df["city"].str.strip()
    return out


def insight_cities(cities, known_total):
    if known_total < 20 or len(cities) < 3:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    share = v / known_total
    if share < 0.1:
        return None
    second, v2 = cities.index[1], int(cities.iloc[1])
    both = (v + v2) / known_total
    return (f"{top} מובילה עם {n(v)} מוהלים ({pct(share * 100)} מהרשומים שישובם ידוע); "
            f"יחד עם {second} ({n(v2)}) הן מרכזות {pct(both * 100)} מהרשימה.")


def insight_single(cities):
    if len(cities) < 5:
        return None
    ones = int((cities == 1).sum())
    share = ones / len(cities)
    if share < 0.3:
        return None
    return (f"ב-{n(ones)} מתוך {n(len(cities))} הישובים ברשימה ({pct(share * 100, 0)}) "
            f"רשום מוהל אחד בלבד.")


def insight_peak(per_year):
    if len(per_year) < 3 or per_year.sum() < 50:
        return None
    y = int(per_year.idxmax())
    v = int(per_year.max())
    share = v / per_year.sum()
    if share < 0.15:
        return None
    return (f"תוקף ההסמכה של {n(v)} מוהלים ({pct(share * 100, 0)} מהרשימה) מסתיים ב-{y}, "
            f"השנה העמוסה ביותר בלוח הפקיעות.")


def insight_month(per_month):
    if per_month.sum() < 50:
        return None
    avg = per_month.sum() / 12
    m = int(per_month.idxmax())
    v = int(per_month.max())
    if v < 1.5 * avg:
        return None
    return (f"{MONTHS_HE[m - 1]} הוא החודש שבו פג תוקף ההסמכה של הכי הרבה מוהלים: "
            f"{n(v)} ({pct(v / per_month.sum() * 100, 0)}), פי {v / avg:.1f} מהממוצע החודשי.")


def insight_median(periods):
    if len(periods) < 50:
        return None
    s = periods.sort_values(kind="stable").reset_index(drop=True)
    med = s.iloc[len(s) // 2]
    return (f"תוקף ההסמכה החציוני ברשימה מסתיים ב{mon_year(med)}; הטווח כולו נע מ{mon_year(s.iloc[0])} "
            f"עד {mon_year(s.iloc[-1])}.")


def insight_merged(raw_n, canon_n):
    d = raw_n - canon_n
    if d <= 0:
        return None
    return (f"בשמות הישובים במקור יש {n(d)} כתיבים חלופיים של אותו ישוב (מקף, רווח או כתיב "
            f"מלא/חסר); בדף הם אוחדו, ולכן ספירת הישובים נמוכה ב-{n(d)} מספירת הכתיבים הגולמיים.")


def _timeline(periods):
    """Valid-certificate step curve: for each point, how many expire at/after it."""
    lo, hi = periods.min(), periods.max()
    span = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    step = 1 if span <= MAX_MONTH_POINTS else (3 if span <= MAX_MONTH_POINTS * 3 else 12)
    pts = list(pd.period_range(lo, hi, freq="M"))[::step]
    ords = periods.map(lambda p: p.ordinal).to_numpy()
    return pts, [int((ords >= p.ordinal).sum()) for p in pts], step


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    dated = df.dropna(subset=["exp"])
    undated = total - len(dated)
    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])

    by_year = dated.groupby(dated["exp"].dt.year).size()
    years = list(range(int(by_year.index.min()), int(by_year.index.max()) + 1))
    by_year = by_year.reindex(years, fill_value=0)
    by_year.index = by_year.index.astype(int)
    per_month = dated.groupby(dated["exp"].dt.month).size().reindex(range(1, 13), fill_value=0)

    pts, valid, step = _timeline(dated["period"])
    valid_x = [f"{p.month:02d}/{p.year}" for p in pts]

    hy = years[-HEAT_YEARS:]
    hm = dated.groupby([dated["exp"].dt.year, dated["exp"].dt.month]).size()
    cells = [[m - 1, yi, int(hm.get((y, m), 0))] for yi, y in enumerate(hy) for m in range(1, 13)]

    top_c = list(cities.head(TOP_CITIES).index)
    rest = int(cities.iloc[TOP_CITIES:].sum()) if len(cities) > TOP_CITIES else 0

    size_rows = []
    for lo, hi in SIZE_BUCKETS:
        m = cities >= lo
        if hi is not None:
            m &= cities <= hi
        label = (f"{lo}+" if hi is None else (str(lo) if lo == hi else f"{lo} עד {hi}"))
        size_rows.append((label, int(m.sum()), int(cities[m].sum())))

    surnames = _sorted_counts(df.loc[df["last"] != "", "last"])
    firsts = _sorted_counts(df.loc[df["first"] != "", "first"])

    charts = {
        "year": {"x": [str(y) for y in years], "values": [int(v) for v in by_year.values]},
        "month": {"x": MONTHS_SHORT, "values": [int(v) for v in per_month.values]},
        "valid": {"x": valid_x, "values": valid},
        "heat": {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "cities": {"names": top_c, "values": [int(cities[c]) for c in top_c]},
        "citysize": {"names": [r[0] for r in size_rows], "cities": [r[1] for r in size_rows],
                     "mohels": [r[2] for r in size_rows]},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
        "firsts": {"names": list(firsts.head(TOP_NAMES).index),
                   "values": [int(v) for v in firsts.head(TOP_NAMES).values]},
    }

    raw_n = int(known["raw_city"].nunique())
    rules = [
        ("cities", insight_cities(cities, len(known))),
        ("single", insight_single(cities)),
        ("peak", insight_peak(by_year)),
        ("month", insight_month(per_month)),
        ("median", insight_median(dated["period"])),
        ("merged", insight_merged(raw_n, int(cities.size))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    peak_y = int(by_year.idxmax())
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
        "top_city": {"value": int(cities.iloc[0]), "display": n(cities.iloc[0]), "tone": "info"},
        "peak": {"value": int(by_year.max()), "display": n(by_year.max()), "tone": "brand"},
    }
    first_p, last_p = dated["period"].min(), dated["period"].max()
    undated_txt = f" {n(undated)} רשומות ללא תאריך תוקף אינן נכללות בגרפי התוקף." if undated else ""
    unk_city = total - len(known)
    unk_txt = f" {n(unk_city)} רשומות ללא ישוב אינן נכללות בגרפי הישובים." if unk_city else ""
    labels = {
        "lede": (f"רשימת המוהלים המוסמכים שהרבנות הראשית לישראל ממליצה עליהם: {n(total)} מוהלים "
                 f"ב-{n(cities.size)} ישובים. תוקף ההסמכה נע מ{mon_year(first_p)} עד {mon_year(last_p)}."),
        "top_kpi": f"מוהלים ב{cities.index[0]}, הישוב המוביל",
        "peak_kpi": f"הסמכות שתוקפן מסתיים ב-{peak_y}, שנת הפקיעה העמוסה",
        "year_note": "מספר המוהלים שתוקף ההסמכה שלהם מסתיים בכל שנה קלנדרית." + undated_txt,
        "year_aria": (f"תרשים עמודות: הסמכות לפי שנת תוקף, {years[0]} עד {years[-1]}; "
                      f"שיא ב-{peak_y} עם {n(by_year.max())}."),
        "year_caption": "מספר מוהלים לפי שנת סיום תוקף ההסמכה.",
        "month_note": ("פקיעות לפי חודש בשנה, בסיכום כל השנים ברשימה. שנות הקצה (הראשונה והאחרונה) "
                       "אינן מכסות את כל החודשים, ולכן הפער קטן מעט."),
        "month_aria": f"תרשים עמודות: הסמכות לפי חודש קלנדרי; שיא ב{MONTHS_HE[int(per_month.idxmax()) - 1]}.",
        "month_caption": "מספר מוהלים לפי חודש סיום התוקף.",
        "valid_note": ("כמה מוהלים ברשימה תוקף ההסמכה שלהם נמשך לפחות עד כל חודש. העקומה יורדת "
                       "ככל שהתוקפים מסתיימים, אלא אם מתווספים מוהלים חדשים או מתחדשות הסמכות."
                       + (" הנקודות מסוכמות לרבעונים." if step == 3 else (" הנקודות מסוכמות לשנים." if step == 12 else ""))),
        "valid_aria": (f"גרף מדרגות: מוהלים שהסמכתם בתוקף לפחות עד כל חודש, מ{mon_year(first_p)} "
                       f"עד {mon_year(last_p)}; מ-{n(valid[0])} ירידה ל-{n(valid[-1])}."),
        "heat_note": f"מספר ההסמכות שפוקעות בכל חודש, {hy[0]} עד {hy[-1]}.",
        "heat_aria": f"מפת חום: הסמכות שפוקעות לפי חודש ושנה, {hy[0]} עד {hy[-1]}.",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר המוהלים הגדול ביותר"
                        + (f"; {n(rest)} מוהלים נוספים פזורים ב-{n(cities.size - TOP_CITIES)} ישובים אחרים." if rest else ".")
                        + " איות שמות הישובים במקור אוחד." + unk_txt),
        "cities_aria": (f"תרשים עמודות אופקי: הישובים עם הכי הרבה מוהלים; {top_c[0]} בראש עם "
                        f"{n(cities.iloc[0])}."),
        "cities_caption": f"מוהלים לפי ישוב ({TOP_CITIES} המובילים).",
        "citysize_note": ("כמה ישובים יש בכל קבוצת גודל, לפי מספר המוהלים הרשומים בישוב, "
                          "וכמה מוהלים יושבים בהם."),
        "citysize_aria": "תרשים עמודות: מספר ישובים לפי מספר המוהלים הרשומים בהם.",
        "citysize_caption": "ישובים ומוהלים לפי גודל קבוצת הישוב.",
        "surnames_note": f"{TOP_NAMES} שמות המשפחה הנפוצים ברשימה (ספירה מצטברת בלבד).",
        "surnames_aria": f"תרשים עמודות אופקי: שמות המשפחה הנפוצים; {surnames.index[0]} בראש.",
        "surnames_caption": "מספר מוהלים לפי שם משפחה.",
        "firsts_note": f"{TOP_NAMES} השמות הפרטיים (השם הראשון) הנפוצים ברשימה.",
        "firsts_aria": f"תרשים עמודות אופקי: שמות פרטיים נפוצים; {firsts.index[0]} בראש.",
        "firsts_caption": "מספר מוהלים לפי שם פרטי ראשון.",
    }
    tables = {
        "year": [{"name": str(y), "count": n(v)} for y, v in by_year.items()],
        "month": [{"name": MONTHS_HE[m - 1], "count": n(v)} for m, v in per_month.items()],
        "cities": [{"name": c, "count": n(cities[c]),
                    "share": f"{cities[c] / len(known) * 100:.1f}%"} for c in top_c],
        "citysize": [{"name": a, "cities": n(b), "mohels": n(c)} for a, b, c in size_rows],
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in firsts.head(TOP_NAMES).items()],
    }
    return {
        "agent_data": {
            "summary_he": (f"רשימת המוהלים המוסמכים של הרבנות הראשית: {n(total)} מוהלים ב-{n(cities.size)} יישובים, "
                           f"עם תוקף ההסמכה. איתור מוהל לפי שם או יישוב."),
            "dataset_kind": "registry",
            "related_ids": ["6a8f3548-f991-4f8b-ab52-80240324ab4d",
                            "f312eda5-27bc-4619-8917-8072a12f14ce"],
            "suggested_tags": ["מוהלים", "ברית מילה", "רבנות ראשית", "הסמכה", "רשימה ארצית"],
            "temporal_coverage": f"{first_p}/{last_p}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
