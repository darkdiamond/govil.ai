"""איתור קורסים מאושרים למוסדות - חיילים משוחררים — Ministry of Labor.

A registry of course offerings approved for the discharged-soldiers grant:
one row per (institution branch, course) with the branch's city, street
address, ministry district and contact details. No dates — the file is a
daily snapshot of what is approved now.

Unit of analysis is an *offering*: a distinct (institution, city, address,
course) tuple. The source repeats some rows verbatim; those are removed and
the count is disclosed. Course names are whitespace-folded (and the
"אוויר"/"אויר" spelling unified) before comparing; each is shown under its
most common spelling.

Course fields are assigned by ordered keyword rules on the course name, with
"אחר" as the fallback, so new courses always flow through.

Institutions are named (they are businesses / colleges in a commercial
capacity). Telephone and e-mail never reach the page — they stay in the
explorer under it.
"""
import math
import re

import pandas as pd

TOP_CITIES = 15
TOP_COURSES = 15
TOP_INST = 15
OTHER = "אחר"
LRI, PDI = "⁦", "⁩"

# Ordered: first match wins. Keywords are matched case-insensitively as
# substrings of the course name.
DOMAINS = [
    ("יופי וטיפוח", ["קוסמטיקה", "איפור", "שיער", "ספרות", "תסרוקות", "פאה"]),
    ("עיצוב, מדיה והפקה", ["עיצוב", "גרפי", "גרפיקה", "אנימציה", "הפקה", "מיקס",
                           "דיג'י", "סאונד", "sound", "הגברת", "טלוויזיה", "טלויזיה",
                           "צילום", "קריאייטיב", "משחקים", "מוזיקלית", "גמולוגיה",
                           "צורפות", "תכשיטים", "סטיילינג", "מעצב"]),
    ("שיווק דיגיטלי ומסחר", ["שיווק", "קמפיינים", "קידום אתרים", "תוכן שיווקי",
                             "מסחר אלקטרוני", "קופירייטינג", "מדיה חברתית"]),
    ("תוכנה, סייבר ומחשוב", ["סייבר", "תוכנה", "תכנות", "חדירות", "פיתוח", "devops", " ai",
                             "ענן", "רשתות תקשורת", "ccna", "data", " bi", "full stack",
                             "front end", "help desk", "cisco", " soc", "מחשבים",
                             "סיילספורס", "salesforce", "erp", "אבטחת מידע", "embedded"]),
    ("חשבונאות, ניהול ועסקים", ["חשבונות", "חשב שכר", "בודק שכר", "מלאי ורכש",
                              "לוגיסטיקה", "יבוא יצוא", "מינהל עסקי", "ביטוח",
                              "יזמות", "הבטחת איכות", "שמאות רכוש"]),
    ("תחבורה ורכב", ["נהיגה", "נהג", "רכב", "אוטובוס", "תעבורה", "הובלה", "הסעות",
                     "הסעת", "מוסך", "אוטוטק", "צמיג", "גרירה", "חומרים מסוכנים",
                     "טכוגרף", "תאונות", "מייסטר", "שילדאי", "תחבורה", "קצב\"ת",
                     "קציני בטיחות"]),
    ("חשמל, קירור וגז", ["חשמל", "קירור", "מעלי", "גז", "פוטו-וולטאי", "מתח נמוך",
                         "קררים"]),
    ("בנייה ותשתיות", ["מנהל עבודה", "בניין", "בנייה", "איטום", "עגורן", "שרברבות",
                       "נגישות מבנים", "מדידה", "בדק בית", "ארכיאולוגיים", "פוליאתילן",
                       "מנעולנות", "עוזר למנהל עבודה"]),
    ("תעשייה, ייצור ותיקון", ["ריתוך", "cnc", "חריטה", "כרסום", "תי\"בם", "מסגרות",
                              "cmm", "מדידות ובקרת", "תעשייה", "אלקטרוניקה", "תפירה",
                              "נגרות", "סלולאר", "מפעיל מערכת"]),
    ("בטיחות, הצלה ואבטחה", ["בטיחות", "הצלה", "מיגון", "אבטחת מטענים"]),
    ("קולינריה ואירוח", ["בישול", "טבחות", "קונדיטאות", "אפייה", "מוזגות",
                         "מלונאות", "bakery", "אירועים"]),
    ("חינוך, טיפול וגיל רך", ["ינקות", "מעון", "משפחתונים", "גיל הרך", "סייעות",
                              "זקנים", "קשיש", "מוגבלות", "שפת הסימנים", "הוראת",
                              "מורשה לנגישות השירות"]),
]
DOMAIN_ORDER = [d for d, _ in DOMAINS] + [OTHER]
SIZE_BINS = [(1, 1), (2, 4), (5, 9), (10, 19), (20, 49), (50, None)]
SUPPLY_BINS = [(1, 1), (2, 4), (5, 9), (10, 19), (20, None)]
LORENZ_MARKS = [1, 5, 10, 25, 50, 100]


def n(v):
    return f"{int(v):,}"


def med(v):
    v = float(v)
    return f"{int(v):,}" if v == int(v) else f"{v:.1f}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _clean(s):
    return s.map(lambda x: re.sub(r"\s+", " ", str(x)).strip())


def _course_key(s):
    return s.replace("אוויר", "אויר")


def _domain(name):
    low = " " + name.lower()
    for d, kws in DOMAINS:
        for k in kws:
            if k in low:
                return d
    return OTHER


def _bins(values, bins):
    rows = []
    for lo, hi in bins:
        m = values >= lo
        if hi is not None:
            m &= values <= hi
        label = f"{lo} ומעלה" if hi is None else (str(lo) if lo == hi else f"{lo} עד {hi}")
        rows.append((label, int(m.sum())))
    return rows


def _counts(s):
    """value_counts with a total, deterministic order: count desc, key asc."""
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + names[-1]


def _prepare(df):
    out = pd.DataFrame({
        "institution": _clean(df["institution"]),
        "city": _clean(df["city"]),
        "address": _clean(df["address"]),
        "course_raw": _clean(df["course"]),
        "district": _clean(df["district"]),
    })
    keep = (out["institution"] != "") & (out["course_raw"] != "")
    raw = df.loc[keep.values, ["institution", "city", "address", "course"]]
    exact = int(raw.duplicated().sum())
    out = out[keep]
    out["district"] = out["district"].replace("", "לא צוין")
    out["city"] = out["city"].replace("", "לא צוין")
    out["ckey"] = out["course_raw"].map(_course_key)
    raw_n = len(out)
    out = out.drop_duplicates(["institution", "city", "address", "ckey"])
    dups = raw_n - len(out)
    # Display spelling per course key: most common variant, ties by name.
    var = (out.groupby(["ckey", "course_raw"]).size().reset_index(name="k")
           .sort_values(["ckey", "k", "course_raw"], ascending=[True, False, True]))
    canon = var.drop_duplicates("ckey").set_index("ckey")["course_raw"]
    out["course"] = out["ckey"].map(canon)
    out["domain"] = out["course"].map(_domain)
    return out.reset_index(drop=True), dups, raw_n, exact


# ---------------------------------------------------------------- insights

def insight_district(dist, total):
    if len(dist) < 2 or total == 0:
        return None
    (d1, v1), (d2, v2) = list(dist.items())[:2]
    s1 = v1 / total
    if s1 < 0.3 or v1 <= v2:
        return None
    dl, vl = dist.index[-1], int(dist.iloc[-1])
    tail = (f"; ב{dl} — {n(vl)} בלבד ({pct(vl / total * 100)})" if len(dist) > 2 else "")
    return (f"{d1} מוביל עם {n(v1)} הצעות קורס "
            f"({pct(s1 * 100)}), ואחריו {d2} עם {n(v2)} ({pct(v2 / total * 100)}){tail}.")


def insight_cities(cities, total):
    if len(cities) < 3 or total == 0:
        return None
    (c1, v1), (c2, v2) = list(cities.items())[:2]
    both = (v1 + v2) / total
    if both < 0.15:
        return None
    return (f"{c1} ו{c2} לבדן מרכזות {pct(both * 100)} מכל ההצעות "
            f"({n(v1)} ו-{n(v2)} בהתאמה), מתוך {n(len(cities))} ישובים שבהם יש קורס מאושר.")


def insight_domain(dom, total):
    known = dom.drop(OTHER, errors="ignore")
    if len(known) < 2 or total == 0:
        return None
    (a, va), (b, vb) = list(known.items())[:2]
    if va / total < 0.12:
        return None
    return (f"התחום הגדול ביותר הוא {a}, עם {n(va)} הצעות ({pct(va / total * 100)}), "
            f"ואחריו {b} ({n(vb)}, {pct(vb / total * 100)}) — לפי סיווג שם הקורס לתחומים.")


def insight_special(mix, dist, dom, total):
    best = None
    for d in dist.index:
        dt = int(dist[d])
        for g in dom.index:
            if g == OTHER:
                continue
            c = int(mix.get((d, g), 0))
            if c < 10 or dt == 0:
                continue
            sd, sn = c / dt, dom[g] / total
            r = sd / sn if sn else 0
            key = (r, c, d, g)
            if best is None or key[:2] > best[:2] or (key[:2] == best[:2] and (d, g) < best[2:]):
                best = key
    if best is None or best[0] < 1.5:
        return None
    r, c, d, g = best
    return (f"ב{d} בולט במיוחד תחום {g}: {pct(c / int(dist[d]) * 100)} מההצעות במחוז "
            f"({n(c)}), לעומת {pct(dom[g] / total * 100)} בכלל הארץ — פי "
            f"{LRI}{r:.1f}{PDI} משקלו הארצי.")


def insight_breadth(dist_courses, n_courses):
    if len(dist_courses) < 2 or n_courses == 0:
        return None
    d = dist_courses.index[-1]
    v = int(dist_courses.iloc[-1])
    top_d, top_v = dist_courses.index[0], int(dist_courses.iloc[0])
    if v / n_courses > 0.6:
        return None
    return (f"מגוון הקורסים אינו שווה בין המחוזות: ב{d} מוצעים {n(v)} קורסים שונים בלבד "
            f"מתוך {n(n_courses)} במאגר ({pct(v / n_courses * 100, 0)}), לעומת {n(top_v)} "
            f"ב{top_d}.")


def insight_reach(reach, supply_one, n_courses, n_districts):
    if n_courses == 0 or n_districts < 2:
        return None
    one = int((reach == 1).sum())
    allx = int((reach == n_districts).sum())
    if one / n_courses < 0.25:
        return None
    s = (f"{n(one)} קורסים ({pct(one / n_courses * 100, 0)}) מוצעים במחוז אחד בלבד, "
         f"ו-{n(supply_one)} מהם בידי מוסד יחיד בכל הארץ")
    if allx:
        s += f"; רק {n(allx)} קורסים זמינים בכל {n(n_districts)} המחוזות"
    return s + "."


def insight_concentration(inst, total):
    if len(inst) < 20 or total == 0:
        return None
    top10 = int(inst.head(10).sum())
    sh = top10 / total
    if sh < 0.15:
        return None
    single = int((inst == 1).sum())
    return (f"עשרת המוסדות הגדולים מציעים {pct(sh * 100)} מכלל ההצעות; בראשם "
            f"{inst.index[0]} עם {n(inst.iloc[0])} קורסים. מנגד, {n(single)} מתוך "
            f"{n(len(inst))} המוסדות ({pct(single / len(inst) * 100, 0)}) מציעים קורס אחד בלבד, "
            f"והחציון הוא {med(inst.median())} קורסים למוסד.")


def insight_dups(dups, raw_n, exact):
    if dups <= 0:
        return None
    return (f"{n(dups)} רשומות במקור ({pct(dups / raw_n * 100)}) חוזרות על אותו מוסד, כתובת "
            f"וקורס" + (f" ({n(dups - exact)} מהן נבדלות רק ברווחים או באיות)" if dups > exact else "")
            + "; הן נספרו פעם אחת בכל העמוד.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, dups, raw_n, exact = _prepare(frames["courses"])
    total = len(df)
    dist = _counts(df["district"])
    districts = list(dist.index)
    n_districts = len(districts)
    cities = _counts(df["city"])
    courses = _counts(df["course"])
    inst = _counts(df["institution"])
    dom = df["domain"].value_counts().reindex(DOMAIN_ORDER).fillna(0).astype(int)
    dom = dom[dom > 0]
    dom = pd.concat([dom.drop(OTHER, errors="ignore").sort_values(ascending=False, kind="stable"),
                     dom.reindex([OTHER]).dropna().astype(int)])
    domains = list(dom.index)
    n_courses = int(courses.size)
    n_inst = int(inst.size)

    g_d = df.groupby("district")
    d_inst = g_d["institution"].nunique()
    d_courses = g_d["course"].nunique()
    d_cities = g_d["city"].nunique()
    dist_courses = d_courses.reindex(districts)
    dist_courses = dist_courses.sort_index().sort_values(ascending=False, kind="stable")

    city_district = (df.groupby(["city", "district"]).size().reset_index(name="k")
                     .sort_values(["city", "k", "district"], ascending=[True, False, True])
                     .drop_duplicates("city").set_index("city")["district"])
    city_inst = df.groupby("city")["institution"].nunique()

    g_c = df.groupby("course")
    c_inst = g_c["institution"].nunique()
    c_reach = g_c["district"].nunique()
    c_domain = g_c["domain"].first()

    g_i = df.groupby("institution")
    i_cities = g_i["city"].nunique()
    i_city = (df.groupby(["institution", "city"]).size().reset_index(name="k")
              .sort_values(["institution", "k", "city"], ascending=[True, False, True])
              .drop_duplicates("institution").set_index("institution")["city"])
    i_domains = g_i["domain"].nunique()

    mix = df.groupby(["district", "domain"]).size()
    dom_courses = df.groupby("domain")["course"].nunique()
    dom_inst = df.groupby("domain")["institution"].nunique()

    # ---- charts
    top_c = list(cities.head(TOP_CITIES).index)
    by_inst = c_inst.sort_index().sort_values(ascending=False, kind="stable")
    top_k = list(by_inst.head(TOP_COURSES).index)
    top_i = list(inst.head(TOP_INST).index)

    treemap = []
    for d in districts:
        sub = cities[[c for c in cities.index if city_district[c] == d]]
        treemap.append({"name": d, "value": int(dist[d]),
                        "children": [{"name": c, "value": int(v)} for c, v in sub.items()]})

    heat_cells = []
    for xi, d in enumerate(districts):
        dt = int(dist[d])
        for yi, g in enumerate(domains):
            c = int(mix.get((d, g), 0))
            heat_cells.append([xi, yi, round(c / dt * 100, 1) if dt else 0, c])
    heat_max = max([c[2] for c in heat_cells] or [1])

    reach_rows = [(str(k), int((c_reach == k).sum())) for k in range(1, n_districts + 1)]
    supply_rows = _bins(c_inst, SUPPLY_BINS)
    size_rows = _bins(inst, SIZE_BINS)
    supply_one = int(((c_inst == 1) & (c_reach == 1)).sum())

    # Concentration curve over institutions ranked by size (count desc, name asc).
    cum = inst.cumsum()
    lorenz = [[0.0, 0.0]] + [[round((i + 1) / n_inst * 100, 2), round(int(v) / total * 100, 2)]
                             for i, v in enumerate(cum.values)]
    marks = [m for m in LORENZ_MARKS if m < n_inst] + [n_inst]
    lorenz_rows = [{"k": n(m), "inst_share": f"{m / n_inst * 100:.1f}%",
                    "share": f"{int(cum.iloc[m - 1]) / total * 100:.1f}%"} for m in marks]

    charts = {
        "district": {"names": districts, "values": [int(dist[d]) for d in districts],
                     "inst": [int(d_inst[d]) for d in districts],
                     "courses": [int(d_courses[d]) for d in districts],
                     "cities": [int(d_cities[d]) for d in districts]},
        "treemap": treemap,
        "cities": {"names": top_c, "values": [int(cities[c]) for c in top_c],
                   "district": [city_district[c] for c in top_c],
                   "inst": [int(city_inst[c]) for c in top_c]},
        "domains": {"names": domains, "values": [int(dom[g]) for g in domains],
                    "courses": [int(dom_courses[g]) for g in domains],
                    "inst": [int(dom_inst[g]) for g in domains]},
        "mix": {"x": districts, "y": domains, "cells": heat_cells, "max": heat_max},
        "courses": {"names": top_k, "values": [int(c_inst[k]) for k in top_k],
                    "reach": [int(c_reach[k]) for k in top_k]},
        "reach": {"names": [r[0] for r in reach_rows], "values": [r[1] for r in reach_rows]},
        "supply": {"names": [r[0] for r in supply_rows], "values": [r[1] for r in supply_rows]},
        "inst": {"names": top_i, "values": [int(inst[i]) for i in top_i],
                 "city": [i_city[i] for i in top_i]},
        "size": {"names": [r[0] for r in size_rows], "values": [r[1] for r in size_rows]},
        "lorenz": {"points": lorenz},
    }

    # ---- insights
    rules = [
        ("district", insight_district(dist, total)),
        ("cities", insight_cities(cities, total)),
        ("domain", insight_domain(dom, total)),
        ("special", insight_special(mix, dist, dom, total)),
        ("breadth", insight_breadth(dist_courses, n_courses)),
        ("reach", insight_reach(c_reach, supply_one, n_courses, n_districts)),
        ("concentration", insight_concentration(inst, total)),
        ("dups", insight_dups(dups, raw_n, exact)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    all_reach = int((c_reach == n_districts).sum())
    kpis = {
        "offerings": {"value": total, "display": n(total), "tone": "brand"},
        "courses": {"value": n_courses, "display": n(n_courses), "tone": "brand"},
        "institutions": {"value": n_inst, "display": n(n_inst), "tone": "brand"},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
        "all_reach": {"value": all_reach, "display": n(all_reach),
                      "tone": "ok" if n_courses and all_reach / n_courses >= 0.25 else "warn"},
        "dups": {"value": dups, "display": n(dups), "tone": "warn" if dups else "ok"},
    }

    other_n = int(dom.get(OTHER, 0))
    top10 = int(inst.head(10).sum())
    labels = {
        "lede": (f"רשימת הקורסים שמשרד העבודה אישר למימון במסגרת מענק ההכשרה לחיילים "
                 f"משוחררים: {n(total)} הצעות קורס — {n(n_courses)} קורסים שונים ב-{n(n_inst)} "
                 f"מוסדות, ב-{n(cities.size)} ישובים ו-{n(n_districts)} מחוזות של המשרד. "
                 f"הרשימה משקפת את הקורסים המאושרים כעת"
                 + (f"; {n(dups)} רשומות כפולות במקור הוסרו." if dups else ".")),
        "all_reach_kpi": f"קורסים המוצעים בכל {n(n_districts)} המחוזות",
        "district_note": (f"מספר הצעות הקורס בכל מחוז של משרד העבודה. {districts[0]} מוביל עם "
                          f"{n(dist.iloc[0])} הצעות ({dist.iloc[0] / total * 100:.1f}%). "
                          f"המחוז הוא המחוז המנהלי של המשרד, ולא תמיד תואם את המחוז הגאוגרפי."),
        "district_aria": (f"תרשים עמודות: הצעות קורס לפי מחוז — {districts[0]} בראש עם "
                          f"{n(dist.iloc[0])}."),
        "district_caption": "הצעות קורס, מוסדות, קורסים שונים וישובים לפי מחוז.",
        "treemap_note": (f"הטבעת הפנימית היא המחוזות, והחיצונית — הישובים בכל מחוז, בגודל יחסי למספר הצעות הקורס. "
                         f"{cities.index[0]} הוא הישוב הגדול ביותר, עם {n(cities.iloc[0])} הצעות."),
        "treemap_aria": (f"תרשים שמש: הצעות קורס ב-{n(cities.size)} ישובים, מקובצים ב-"
                         f"{n(n_districts)} מחוזות."),
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר הצעות הקורס הגדול ביותר; יחד הם מרכזים "
                        f"{cities.head(TOP_CITIES).sum() / total * 100:.1f}% מההיצע."),
        "cities_aria": (f"תרשים עמודות אופקי: {TOP_CITIES} הישובים המובילים — {cities.index[0]} "
                        f"בראש עם {n(cities.iloc[0])} הצעות."),
        "cities_caption": f"הצעות קורס ומוסדות ב-{TOP_CITIES} הישובים המובילים.",
        "domains_note": (f"הקורסים סווגו לתחומים לפי מילות מפתח בשם הקורס. {domains[0]} הוא התחום "
                         f"הגדול ביותר, עם {n(dom.iloc[0])} הצעות."
                         + (f" {n(other_n)} הצעות ({other_n / total * 100:.1f}%) לא שויכו לתחום "
                            f"וסומנו „{OTHER}”." if other_n else "")),
        "domains_aria": (f"תרשים עמודות אופקי: הצעות קורס לפי תחום — {domains[0]} בראש עם "
                         f"{n(dom.iloc[0])}."),
        "domains_caption": "הצעות קורס, קורסים שונים ומוסדות לפי תחום.",
        "mix_note": ("שיעור כל תחום מתוך הצעות הקורס במחוז (כל עמודה מסתכמת במאה אחוז). "
                     "צבע כהה יותר — משקל גבוה יותר של התחום במחוז."),
        "mix_aria": f"מפת חום: שיעור כל תחום מההצעות בכל אחד מ-{n(n_districts)} המחוזות.",
        "mix_caption": "שיעור כל תחום (באחוזים) מתוך הצעות הקורס בכל מחוז.",
        "courses_note": (f"{TOP_COURSES} הקורסים שמוצעים במספר המוסדות הגדול ביותר. "
                         f"{top_k[0]} מוצע ב-{n(c_inst[top_k[0]])} מוסדות."),
        "courses_aria": (f"תרשים עמודות אופקי: {TOP_COURSES} הקורסים הנפוצים לפי מספר המוסדות "
                         f"המציעים אותם — {top_k[0]} בראש."),
        "courses_caption": f"מספר המוסדות ומספר המחוזות שבהם מוצע כל אחד מ-{TOP_COURSES} הקורסים.",
        "reach_note": (f"בכמה מחוזות מוצע כל קורס. {n(reach_rows[0][1])} קורסים מוצעים במחוז "
                       f"אחד בלבד, ו-{n(all_reach)} בכל המחוזות."),
        "reach_aria": (f"תרשים עמודות: מספר הקורסים לפי מספר המחוזות שבהם הם מוצעים, מאחד עד "
                       f"{n(n_districts)}."),
        "reach_caption": "מספר הקורסים לפי מספר המחוזות שבהם הם מוצעים.",
        "supply_note": (f"בכמה מוסדות מוצע כל קורס. {n(supply_rows[0][1])} קורסים "
                        f"({supply_rows[0][1] / n_courses * 100:.0f}%) מוצעים במוסד אחד בלבד."),
        "supply_aria": "תרשים עמודות: מספר הקורסים לפי מספר המוסדות המציעים אותם.",
        "supply_caption": "מספר הקורסים לפי מספר המוסדות המציעים אותם.",
        "inst_note": (f"{TOP_INST} המוסדות עם מספר הקורסים המאושרים הגדול ביותר, כפי ששמם מופיע "
                      f"ברשימה (סניפים של אותה רשת רשומים לעיתים בשמות שונים)."),
        "inst_aria": (f"תרשים עמודות אופקי: {TOP_INST} המוסדות המובילים — {top_i[0]} בראש עם "
                      f"{n(inst.iloc[0])} קורסים."),
        "inst_caption": f"מספר הקורסים המאושרים ב-{TOP_INST} המוסדות המובילים.",
        "size_note": (f"כמה קורסים מאושרים יש לכל מוסד. החציון הוא {med(inst.median())} קורסים "
                      f"למוסד; {n(size_rows[0][1])} מוסדות מציעים קורס אחד בלבד."),
        "size_aria": "תרשים עמודות: מספר המוסדות לפי מספר הקורסים המאושרים שלהם.",
        "size_caption": "מספר המוסדות לפי מספר הקורסים המאושרים.",
        "lorenz_note": (f"המוסדות מסודרים מהגדול לקטן; הקו מראה איזה חלק מכלל ההצעות מרכזים "
                        f"המוסדות המובילים. עשרת הגדולים ({10 / n_inst * 100:.0f}% מהמוסדות) "
                        f"מציעים {top10 / total * 100:.1f}% מההצעות; הקו המקווקו מתאר חלוקה שווה."),
        "lorenz_aria": (f"עקומת ריכוזיות: שיעור מצטבר של הצעות הקורס לפי שיעור המוסדות, "
                        f"מ-{n(n_inst)} מוסדות."),
        "lorenz_caption": "שיעור ההצעות המצטבר שמרכזים המוסדות הגדולים.",
    }

    tables = {
        "district": [{"name": d, "count": n(dist[d]), "share": f"{dist[d] / total * 100:.1f}%",
                      "inst": n(d_inst[d]), "courses": n(d_courses[d]), "cities": n(d_cities[d])}
                     for d in districts],
        "cities": [{"name": c, "district": city_district[c], "count": n(cities[c]),
                    "inst": n(city_inst[c])} for c in top_c],
        "domains": [{"name": g, "count": n(dom[g]), "share": f"{dom[g] / total * 100:.1f}%",
                     "courses": n(dom_courses[g]), "inst": n(dom_inst[g])} for g in domains],
        "mix": [{"name": g, "vals": [f"{(mix.get((d, g), 0) / dist[d] * 100):.1f}%" for d in districts]}
                for g in domains],
        "courses": [{"name": k, "domain": c_domain[k], "inst": n(c_inst[k]), "reach": n(c_reach[k])}
                    for k in top_k],
        "reach": [{"k": k, "count": n(v)} for k, v in reach_rows],
        "supply": [{"k": k, "count": n(v)} for k, v in supply_rows],
        "inst": [{"name": i, "city": i_city[i], "cities": n(i_cities[i]), "count": n(inst[i]),
                  "domains": n(i_domains[i])} for i in top_i],
        "size": [{"k": k, "count": n(v)} for k, v in size_rows],
        "lorenz": lorenz_rows,
    }

    return {
        "agent_data": {
            "summary_he": (f"רשימת הקורסים המאושרים למימון לחיילים משוחררים: {n(total)} הצעות "
                           f"קורס — {n(n_courses)} קורסים שונים ב-{n(n_inst)} מוסדות "
                           f"וב-{n(cities.size)} ישובים, לפי מחוז, ישוב, מוסד ותחום."),
            "dataset_kind": "registry",
            "related_ids": ["e1721717-3e0a-4d6d-93b3-0129df2a57e2",
                            "c8205c2e-78df-4def-b0ec-0fcb35acffd3",
                            "f2ce5a09-7274-4a36-809e-2cb751578c06",
                            "3768866d-84e0-479f-b720-ccae0ac315d5"],
            "suggested_tags": ["חיילים משוחררים", "הכשרה מקצועית", "קורסים",
                               "מוסדות הכשרה", "תעסוקה", "משרד העבודה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
