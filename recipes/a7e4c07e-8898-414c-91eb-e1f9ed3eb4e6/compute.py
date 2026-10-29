"""סניפי הסל של ישראל: one row per branch of the Yesh / "Hasal shel Israel"
food-basket chain (format, branch/city name, street address).

Searchers want a branch near them, so the page leads with a lookup callout
and a directory grouped by district and city. Thin data (a few dozen rows)
gets few, honest charts: branches by district split by format, the format
mix, and the cities with the most branches.

City names are cleaned (whitespace, a trailing parenthetical like
"(מערב)", the תקוה/תקווה and קרית/קריית spelling variants) before counting.
Districts come from a static city -> CBS district lookup; a city missing
from it lands in "מחוז לא מסווג" and the page says so. An empty format is
shown as "לא צוין". New formats and cities flow through unchanged.

Growth: the directory table is shown in full while the chain has at most
DIRECTORY_MAX branches; above that the page keeps the per-city counts only
(the shell's explorer still searches every row).
"""
import re

import pandas as pd

SUMMARY_MAX = 155
DIRECTORY_MAX = 300
TOP_CITIES = 12
FORMAT_KPIS = 3
NO_FORMAT = "לא צוין"
NO_DISTRICT = "מחוז לא מסווג"
MIN_DISTRICT_FOR_SHARE = 6

# CBS districts (מחוזות). Judea and Samaria is its own region.
_DISTRICTS = {
    "צפון": [
        "עפולה", "בית שאן", "מגדל העמק", "מעלות תרשיחא", "מעלות", "קריית שמונה",
        "נצרת", "נוף הגליל", "טבריה", "צפת", "כרמיאל", "נהריה", "עכו", "שלומי",
        "קצרין", "יקנעם עילית", "יקנעם", "סח'נין", "שפרעם", "טמרה", "מגאר",
        "ראש פינה", "חצור הגלילית", "קריית טבעון",
    ],
    "חיפה": [
        "חיפה", "חדרה", "אור עקיבא", "דליית אל כרמל", "עספיא", "כרכור",
        "פרדס חנה כרכור", "פרדס חנה", "זכרון יעקב", "קריית אתא", "קריית ביאליק",
        "קריית מוצקין", "קריית ים", "נשר", "טירת כרמל", "בנימינה", "אום אל פחם",
        "באקה אל גרביה", "חריש", "פוריידיס", "קיסריה",
    ],
    "מרכז": [
        "כפר סבא", "לוד", "רמלה", "נתניה", "פתח תקווה", "ראש העין", "ראשון לציון",
        "רעננה", "יבנה", "אלעד", "מודיעין", "מודיעין מכבים רעות", "רחובות",
        "נס ציונה", "הוד השרון", "כפר יונה", "אבן יהודה", "שוהם",
        "יהוד", "יהוד מונוסון", "גדרה", "מזכרת בתיה", "קריית עקרון", "באר יעקב",
        "טייבה", "טירה", "כפר קאסם", "קלנסווה", "גני תקווה",
        "צור יגאל", "כוכב יאיר", "תל מונד", "קדימה צורן",
    ],
    "תל אביב": [
        "תל אביב", "תל אביב יפו", "יפו", "גבעתיים", "רמת גן", "אור יהודה",
        "בני ברק", "חולון", "בת ים", "קריית אונו", "גבעת שמואל", "אזור",
        "רמת השרון", "הרצליה",
    ],
    "ירושלים": [
        "ירושלים", "בית שמש", "מבשרת ציון", "אבו גוש", "צור הדסה",
    ],
    "דרום": [
        "אופקים", "אילת", "אשדוד", "אשקלון", "באר שבע", "נתיבות", "ערד",
        "שדרות", "גן יבנה", "קריית גת", "קריית מלאכי", "דימונה", "ירוחם",
        "מצפה רמון", "רהט", "חורה", "תל שבע", "כסייפה", "לקיה", "עומר",
        "להבים", "מיתר", "באר טוביה",
    ],
    "יהודה ושומרון": [
        "ביתר עילית", "מודיעין עילית", "אריאל", "מעלה אדומים", "אפרת",
        "קריית ארבע", "קרני שומרון", "אלפי מנשה", "אורנית", "עמנואל",
    ],
}
# Each city appears once; setdefault keeps the first listing if one slips in twice.
CITY_DISTRICT = {}
for _d, _cities in _DISTRICTS.items():
    for _c in _cities:
        CITY_DISTRICT.setdefault(_c, _d)


def _ws(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _city(raw):
    s = _ws(raw)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    s = s.replace("־", " ").replace("-", " ")
    s = _ws(s)
    s = re.sub(r"תקוה\b", "תקווה", s)
    s = re.sub(r"^קרית ", "קריית ", s)
    return s


def _district(city):
    if city in CITY_DISTRICT:
        return CITY_DISTRICT[city]
    return NO_DISTRICT


def _prepare(df):
    out = pd.DataFrame({
        "format": df["format"].map(_ws),
        "city": df["branch"].map(_city),
        "address": df["address"].map(_ws),
    })
    out.loc[out["format"] == "", "format"] = NO_FORMAT
    out = out[(out["city"] != "") | (out["address"] != "")]
    out.loc[out["city"] == "", "city"] = "לא צוין"
    out["district"] = out["city"].map(_district)
    return out.sort_values(["district", "city", "format", "address"],
                           kind="stable").reset_index(drop=True)


def _pct(part, whole):
    return f"{part / whole * 100:.0f}%" if whole else "0%"


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


def _counts(series):
    vc = series.value_counts()
    # total order: count desc, then name
    return sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------------------------------------------------------------- insights

def insight_spread(df, city_counts):
    n, nc = len(df), len(city_counts)
    if nc < 2:
        return None
    top_n = city_counts[0][1]
    leaders = [c for c, v in city_counts if v == top_n]
    singles = sum(1 for _, v in city_counts if v == 1)
    s = f"{n:,} הסניפים פרוסים ב-{nc:,} יישובים"
    if len(leaders) == 1:
        s += f"; בראש {leaders[0]} עם {top_n:,} סניפים"
    elif len(leaders) <= 6:
        s += f"; אף יישוב אינו מחזיק יותר מ-{top_n:,} סניפים, ו{_join(leaders)} מובילות עם {top_n:,} כל אחת"
    else:
        s += f"; אף יישוב אינו מחזיק יותר מ-{top_n:,} סניפים ({len(leaders):,} יישובים בשיא)"
    if singles:
        s += f". ב-{singles:,} יישובים ({_pct(singles, nc)}) יש סניף אחד בלבד"
    return s + "."


def insight_district(df, dist_counts):
    known = [(d, v) for d, v in dist_counts if d != NO_DISTRICT]
    if len(known) < 2:
        return None
    n = len(df)
    d0, v0 = known[0]
    if v0 == known[1][1]:
        return None
    low_v = known[-1][1]
    lows = [d for d, v in known if v == low_v]
    s = (f"מחוז {d0} מוביל עם {v0:,} סניפים ({_pct(v0, n)} מהרשת)")
    if low_v < v0 and len(lows) == 1:
        s += f", ובמחוז {lows[0]} יש {low_v:,} בלבד"
    elif low_v < v0 and len(lows) <= 3:
        s += f", ובמחוזות {_join(lows)} יש {low_v:,} בלבד בכל אחד"
    unk = sum(v for d, v in dist_counts if d == NO_DISTRICT)
    if unk:
        s += f". {unk:,} סניפים ביישובים שאינם ממופים למחוז נספרו בנפרד"
    return s + "."


def insight_formats(df, fmt_counts):
    known = [(f, v) for f, v in fmt_counts if f != NO_FORMAT]
    if not known:
        return None
    n = len(df)
    f0, v0 = known[0]
    parts = [f"{f} {v:,}" for f, v in known[1:]]
    s = f"הפורמט הנפוץ הוא {f0}: {v0:,} סניפים ({_pct(v0, n)})"
    if parts:
        s += "; אחריו " + ", ".join(parts)
    nf = sum(v for f, v in fmt_counts if f == NO_FORMAT)
    if nf:
        s += f". ל-{nf:,} סניפים לא צוין פורמט"
    return s + "."


def insight_hyper(df):
    hyper = df[df["format"] == "היפר"]
    n = len(df)
    if len(hyper) < 2 or n < 5:
        return None
    overall = len(hyper) / n
    rows = []
    for d, g in df.groupby("district", sort=True):
        if d == NO_DISTRICT or len(g) < MIN_DISTRICT_FOR_SHARE:
            continue
        h = int((g["format"] == "היפר").sum())
        rows.append((h / len(g), len(g), d, h))
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    share, size, d, h = rows[0]
    if share < overall * 1.3 or h < 3:
        return None
    return (f"סניפי ההיפר הגדולים בולטים במחוז {d}: {h:,} מתוך {size:,} סניפים "
            f"({_pct(h, size)}), לעומת {_pct(len(hyper), n)} בכלל הרשת "
            f"(מחוזות עם {MIN_DISTRICT_FOR_SHARE:,} סניפים לפחות).")


def insight_mehadrin(df):
    m = df[df["format"].str.contains("מהדרין", regex=False)]
    if m.empty:
        return None
    cities = sorted(set(m["city"]))
    fmt = sorted(set(m["format"]))[0]
    if len(cities) > 10:
        return (f"פורמט {fmt}, בכשרות מהדרין, פועל ב-{len(m):,} סניפים "
                f"ב-{len(cities):,} יישובים.")
    return (f"פורמט {fmt}, בכשרות מהדרין, פועל ב-{len(m):,} סניפים: "
            f"{_join(cities)}.")


def insight_multi(df, city_counts):
    multi = [(c, v) for c, v in city_counts if v >= 2]
    if len(multi) < 2:
        return None
    mixed = []
    for c, _ in multi:
        fm = set(df.loc[df["city"] == c, "format"]) - {NO_FORMAT}
        if len(fm) >= 2:
            mixed.append(c)
    covered = sum(v for _, v in multi)
    s = (f"{len(multi):,} יישובים מחזיקים יותר מסניף אחד ויחד {covered:,} סניפים "
         f"({_pct(covered, len(df))})")
    if mixed and len(mixed) <= 5:
        s += f"; יישובים שבהם פועלים זה לצד זה סניפים בפורמטים שונים: {_join(mixed)}"
    elif mixed:
        s += f"; ב-{len(mixed):,} מהם פועלים סניפים בפורמטים שונים"
    return s + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    n = int(len(df))
    city_counts = _counts(df["city"])
    dist_counts = _counts(df["district"])
    fmt_counts = _counts(df["format"])
    nc = len(city_counts)

    insights = [{"id": i, "text_he": t} for i, t in [
        ("spread", insight_spread(df, city_counts)),
        ("district", insight_district(df, dist_counts)),
        ("formats", insight_formats(df, fmt_counts)),
        ("hyper", insight_hyper(df)),
        ("mehadrin", insight_mehadrin(df)),
        ("multi", insight_multi(df, city_counts)),
    ] if t]

    # ---- KPIs
    kpis, kpi_labels, order = {}, {}, []

    def add(key, value, label, tone="brand"):
        kpis[key] = {"value": value, "display": f"{value:,}", "tone": tone}
        kpi_labels[key] = label
        order.append(key)

    add("total", n, "סניפים ברשימה")
    add("cities", nc, "יישובים עם סניף")
    known_d = [d for d, _ in dist_counts if d != NO_DISTRICT]
    add("districts", len(known_d), "מחוזות עם סניף")
    shown = [(f, v) for f, v in fmt_counts if f != NO_FORMAT and v >= 2][:FORMAT_KPIS]
    for i, (f, v) in enumerate(shown):
        add(f"fmt_{i}", int(v), f"סניפי {f}")
    nf = sum(v for f, v in fmt_counts if f == NO_FORMAT)
    if nf:
        add("no_format", int(nf), "סניפים ללא פורמט מוגדר", "warn")

    # ---- chart: districts x format (stacked)
    formats = [f for f, _ in fmt_counts]
    districts = [d for d, _ in dist_counts]
    by_df = df.groupby(["district", "format"]).size()
    district_chart = {
        "districts": districts,
        "formats": formats,
        "series": [[int(by_df.get((d, f), 0)) for d in districts] for f in formats],
        "totals": [int(v) for _, v in dist_counts],
    }
    district_rows = [{"name": d, "total": int(v),
                      "cells": [int(by_df.get((d, f), 0)) for f in formats]}
                     for d, v in dist_counts]

    # ---- chart: format mix
    format_chart = {"names": formats, "values": [int(v) for _, v in fmt_counts],
                    "shares": [round(v / n * 100, 1) if n else 0 for _, v in fmt_counts]}

    # ---- chart: cities with the most branches
    multi = [(c, v) for c, v in city_counts if v >= 2]
    top = multi[:TOP_CITIES]
    rest_cities = nc - len(top)
    rest_branches = n - sum(v for _, v in top)
    city_chart = {
        "names": [c for c, _ in top],
        "values": [int(v) for _, v in top],
        "rest_cities": int(rest_cities),
        "rest_branches": int(rest_branches),
    }

    # ---- directory (grouped by district in chart order, then city)
    show_dir = 0 < n <= DIRECTORY_MAX
    directory = []
    if show_dir:
        for d in districts:
            g = df[df["district"] == d]
            cities = []
            for c in sorted(set(g["city"])):
                gc = g[g["city"] == c].sort_values(["format", "address"], kind="stable")
                cities.append({
                    "city": c,
                    "branches": [{"format": r["format"], "address": r["address"] or "לא צוינה"}
                                 for _, r in gc.iterrows()],
                })
            directory.append({"district": d, "count": int(len(g)), "cities": cities})
    city_rows = [{"city": c, "district": _district(c), "n": int(v)} for c, v in city_counts]

    # ---- summary_he = meta description: lookup first
    lead = "איתור סניף של הסל של ישראל לפי עיר וכתובת"
    tail_parts = [f"{n:,} סניפים ב-{nc:,} יישובים"]
    hyper_n = dict(fmt_counts).get("היפר", 0)
    if hyper_n:
        tail_parts.append(f"מהם {hyper_n:,} סניפי היפר")
    summary = f"{lead}: {', '.join(tail_parts)}, עם הכתובת והפורמט של כל סניף."
    if len(summary) > SUMMARY_MAX:
        summary = f"{lead}: {tail_parts[0]}, עם הכתובת והפורמט של כל סניף."
    if len(summary) > SUMMARY_MAX:
        summary = f"{lead}: {tail_parts[0]}."

    top_d = known_d[0] if known_d else None
    lede = (f"רשימת סניפי רשת הסל של ישראל: {n:,} סניפים ב-{nc:,} יישובים"
            + (f" וב-{len(known_d):,} מחוזות" if known_d else "")
            + ". לכל סניף מופיעים היישוב, הכתובת והפורמט"
            + (f" ({_join([f for f in formats if f != NO_FORMAT])})" if any(f != NO_FORMAT for f in formats) else "")
            + ". "
            "הטבלה למטה מסודרת לפי מחוז ויישוב, וחיפוש חופשי בכל הרשומות זמין בעיון בנתונים.")

    unk = sum(v for d, v in dist_counts if d == NO_DISTRICT)
    district_note = (f"מספר הסניפים בכל מחוז, מפולח לפי פורמט. המחוז נקבע לפי היישוב"
                     + (f"; {unk:,} סניפים ביישובים שאינם ממופים מוצגים כ{NO_DISTRICT}." if unk else "."))
    city_note = (f"היישובים עם יותר מסניף אחד ({len(multi):,} יישובים"
                 + (f", מוצגים {len(top):,} המובילים" if len(multi) > len(top) else "")
                 + f"). ביתר {rest_cities:,} היישובים פועלים יחד {rest_branches:,} סניפים.")

    fmt_aria = ("תרשים טבעת: חלוקת הסניפים לפי פורמט. "
                + "; ".join(f"{f}: {v:,}" for f, v in fmt_counts) + ".")
    dist_aria = ("תרשים עמודות מוערמות: סניפים לפי מחוז ופורמט. "
                 + "; ".join(f"{d}: {v:,}" for d, v in dist_counts) + ".")
    city_aria = ("תרשים עמודות אופקי: היישובים עם הכי הרבה סניפים. "
                 + "; ".join(f"{c}: {v:,}" for c, v in top) + ".")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["הסל של ישראל", "סניפים", "רשתות שיווק", "סופרמרקט",
                           "קמעונאות מזון", "כתובות סניפים"],
        "related_ids": ["013bf5b9-c7ff-4282-b402-73ed20deeacc",
                        "89fbf87e-6bc0-4e26-acc7-a288c31b12a1",
                        "8694e2a8-2f9b-416b-a30f-cb9cda4dde4b"],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {"districts": district_chart, "formats": format_chart,
                   "cities": city_chart},
        "insights": insights,
        "tables": {"districts": district_rows, "directory": directory,
                   "cities": city_rows},
        "flags": {
            "show_directory": show_dir,
            "has_formats": len(formats) >= 2,
            "has_districts": len(districts) >= 2,
            "has_cities": len(top) >= 2,
        },
        "labels": {
            **{f"kpi_{k}": v for k, v in kpi_labels.items()},
            "lede": lede,
            "district_note": district_note,
            "city_note": city_note,
            "format_note": (f"כך מתחלקים {n:,} הסניפים בין פורמטי הרשת."),
            "fmt_aria": fmt_aria,
            "dist_aria": dist_aria,
            "city_aria": city_aria,
            "directory_caption": f"{n:,} סניפי הסל של ישראל לפי מחוז ויישוב: פורמט וכתובת.",
            "cities_caption": f"{nc:,} היישובים ומספר הסניפים בכל אחד.",
            "directory_note": (f"כל {n:,} הסניפים, מקובצים לפי מחוז ויישוב."),
        },
    }
