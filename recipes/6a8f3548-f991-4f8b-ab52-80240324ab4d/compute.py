"""רשימת שוחטים ובודקים — the Chief Rabbinate's list of approved shochtim and
bodkim: one row per person-role (first name, last name, role, landline,
mobile). There is no locality, licence number or validity date in the file.

Searchers want to check whether a given shochet/bodek is on the list, so the
page leads with the lookup. The analysis is by role, and by where the contact
numbers point: an international dialing prefix marks a number abroad (the
list includes teams working overseas, mostly in South America), and an
Israeli landline area code gives a coarse region. Phone numbers themselves are
never shown on the page; only aggregate counts derived from them.

Growth: the publisher replaces the file with a new snapshot. New roles and
new countries flow through (role order is by count; countries are top-N +
"אחר"). Every sort has a full tie-break so shuffled rows give the same model.
"""
import re

import pandas as pd

ABROAD = "חו״ל"
ISRAEL = "ישראל"
UNKNOWN = "לא מזוהה"
GROUPS = [ISRAEL, ABROAD, UNKNOWN]

# International calling codes -> country (Hebrew). Longest prefix wins.
COUNTRY_CODES = {
    "1": "ארה״ב וקנדה", "7": "רוסיה", "20": "מצרים", "27": "דרום אפריקה",
    "30": "יוון", "31": "הולנד", "32": "בלגיה", "33": "צרפת", "34": "ספרד",
    "36": "הונגריה", "39": "איטליה", "40": "רומניה", "41": "שווייץ",
    "43": "אוסטריה", "44": "בריטניה", "45": "דנמרק", "46": "שוודיה",
    "47": "נורווגיה", "48": "פולין", "49": "גרמניה", "51": "פרו",
    "52": "מקסיקו", "54": "ארגנטינה", "55": "ברזיל", "56": "צ׳ילה",
    "57": "קולומביה", "58": "ונצואלה", "61": "אוסטרליה", "64": "ניו זילנד",
    "90": "טורקיה", "212": "מרוקו", "213": "אלג׳יריה", "216": "תוניסיה",
    "351": "פורטוגל", "353": "אירלנד", "359": "בולגריה", "370": "ליטא",
    "371": "לטביה", "372": "אסטוניה", "373": "מולדובה", "375": "בלארוס",
    "380": "אוקראינה", "381": "סרביה", "420": "צ׳כיה", "421": "סלובקיה",
    "502": "גואטמלה", "506": "קוסטה ריקה", "507": "פנמה", "591": "בוליביה",
    "593": "אקוודור", "595": "פרגוואי", "598": "אורוגוואי",
}
ISRAEL_CODE = "972"

# Israeli landline area codes -> coarse region.
AREA_CODES = {
    "02": "ירושלים והסביבה",
    "03": "תל אביב וגוש דן",
    "04": "חיפה והצפון",
    "08": "השפלה והדרום",
    "09": "השרון",
}
NO_AREA = "ללא קידומת אזורית"

# Fixed glossary for the role names the Rabbinate uses; unknown roles get none.
ROLE_NOTES = {
    "שוחט": "מבצע את השחיטה עצמה",
    "בודק סכינים": "בודק את סכין השחיטה (החלף) לפני השחיטה ואחריה",
    "בודק פנים": "בודק את הריאות בתוך גוף הבהמה לאחר השחיטה",
    "בודק חוץ": "בודק את הריאות לאחר הוצאתן מהגוף",
    "מנקר": "מסיר את החלב והגידים האסורים באכילה (ניקור)",
    "ראש צוות": "מנהל את צוות השחיטה והכשרות במשחטה",
}

TOP_COUNTRIES = 8
TOP_SURNAMES = 10
MIN_ROLE_ABROAD = 20      # roles with fewer records are not ranked by share abroad
MIN_SURNAME_INSIGHT = 5
SUMMARY_MAX = 155

RELATED = [
    "b72acc9a-6512-4849-9529-3ce73370bff2",
    "f312eda5-27bc-4619-8917-8072a12f14ce",
    "1a49cbba-3722-4a67-9c20-9895697d0373",
]


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _pct(part, whole):
    return round(part * 100.0 / whole, 1) if whole else 0.0


def _p(v):
    return f"{v:.1f}%"


def _n(n, one, many):
    """Count phrase that reads correctly for 1."""
    return one if n == 1 else f"{n:,} {many}"


def classify_number(raw):
    """('IL', area) | ('F', country) | ('U', None) | None for an empty value."""
    s = _clean(raw)
    first = re.split(r"[/,;]", s)[0] if s else ""
    d = re.sub(r"\D", "", first)
    if not d:
        return None
    if re.fullmatch(r"0[23489]\d{7}", d) or re.fullmatch(r"0[57]\d{8}", d):
        return ("IL", d[:2])
    intl = None
    if first.strip().startswith("+"):
        intl = d
    else:
        m = re.match(r"^01[2-9](\d{9,})$", d)
        if m:
            intl = m.group(1)
        elif d.startswith("00") and len(d) >= 10:
            intl = d[2:]
    if intl is None and len(d) >= 11:
        intl = d
    if intl:
        if intl.startswith(ISRAEL_CODE):
            return ("IL", None)
        for k in (3, 2, 1):
            if intl[:k] in COUNTRY_CODES:
                return ("F", COUNTRY_CODES[intl[:k]])
    return ("U", None)


def _locate(phone, cell):
    """(group, country_or_None, region_or_None) for one record."""
    p, c = classify_number(phone), classify_number(cell)
    foreign = [x[1] for x in (p, c) if x and x[0] == "F"]
    if foreign:
        return ABROAD, foreign[0], None
    if any(x and x[0] == "IL" for x in (p, c)):
        if p and p[0] == "IL" and p[1] in AREA_CODES:
            return ISRAEL, None, AREA_CODES[p[1]]
        return ISRAEL, None, NO_AREA
    return UNKNOWN, None, None


def _prepare(df):
    d = pd.DataFrame({
        "first": df["firsname"].map(_clean),
        "last": df["lastname"].map(_clean),
        "role": df["job"].map(_clean),
        "phone": df["phone"].map(_clean),
        "cell": df["cellphone"].map(_clean),
    })
    d = d[(d["first"] != "") | (d["last"] != "")].copy()
    d.loc[d["role"] == "", "role"] = "לא צוין"
    loc = [_locate(p, c) for p, c in zip(d["phone"], d["cell"])]
    d["group"] = [x[0] for x in loc]
    d["country"] = [x[1] for x in loc]
    d["region"] = [x[2] for x in loc]
    d["has_phone"] = d["phone"].map(lambda s: classify_number(s) is not None)
    d["has_cell"] = d["cell"].map(lambda s: classify_number(s) is not None)
    return d.reset_index(drop=True)


def _counts(series):
    vc = series.value_counts()
    items = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(k, int(v)) for k, v in items]


# ---------------------------------------------------------------- insights

def insight_leader(roles, total):
    if len(roles) < 2:
        return None
    (lead, ln), (_, sn) = roles[0], roles[1]
    if ln <= sn:
        return None
    last, lastn = roles[-1]
    s = (f"{lead} הוא התפקיד הנפוץ ביותר ברשימה: {ln:,} רשומות "
         f"({_p(_pct(ln, total))}),")
    if ln >= 2 * lastn:
        s += f" פי {ln / lastn:.1f} מהתפקיד הנדיר ביותר, {last} ({lastn:,})."
    else:
        s += f" ואחריו {roles[1][0]} ({sn:,})."
    return s


def insight_ratio(roles):
    rd = dict(roles)
    shochet = rd.get("שוחט", 0)
    checkers = sum(n for r, n in roles if r.startswith("בודק"))
    if shochet == 0 or checkers == 0:
        return None
    ratio = checkers / shochet
    if ratio < 1.5:
        return None
    return (f"על כל שוחט ברשימה רשומים כ-{ratio:.1f} בודקים "
            f"({checkers:,} בודקי סכינים, פנים וחוץ לעומת "
            f"{_n(shochet, 'שוחט אחד', 'שוחטים')}): השחיטה עצמה נעשית בידי מעטים, "
            f"והבדיקה דורשת צוות גדול בהרבה.")


def insight_abroad(d, countries):
    total = len(d)
    n = int((d["group"] == ABROAD).sum())
    if n == 0 or not countries:
        return None
    lead, ln = countries[0]
    nc = len(countries)
    s = (f"{_n(n, 'רשומה אחת', 'רשומות')} ({_p(_pct(n, total))}) כוללות מספר טלפון "
         f"בחו״ל, " + ("במדינה אחת" if nc == 1 else f"ב-{nc:,} מדינות"))
    if nc > 1:
        s += f"; {lead} מובילה עם {ln:,}"
    else:
        s += f" ({lead})"
    s += ". ככל הנראה אלה צוותים הפועלים במשחטות בחו״ל תחת השגחת הרבנות."
    return s


def insight_role_abroad(d):
    g = d.groupby("role", sort=True)
    rows = []
    for role, sub in g:
        if len(sub) < MIN_ROLE_ABROAD:
            continue
        k = int((sub["group"] == ABROAD).sum())
        rows.append((_pct(k, len(sub)), k, len(sub), role))
    rows = [r for r in rows if r[1] > 0]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: (-r[0], r[3]))
    top, low = rows[0], rows[-1]
    if top[0] - low[0] < 5:
        return None
    return (f"השיעור הגבוה ביותר של מספרים בחו״ל הוא בתפקיד {top[3]}: "
            f"{_p(top[0])} ({top[1]:,} מתוך {top[2]:,}), לעומת {_p(low[0])} "
            f"בתפקיד {low[3]} (תפקידים עם {MIN_ROLE_ABROAD} רשומות לפחות).")


def insight_region(regions):
    named = [(r, n) for r, n in regions if r != NO_AREA]
    if len(named) < 2:
        return None
    tot = sum(n for _, n in named)
    (lead, ln), (sec, sn) = named[0], named[1]
    if ln <= sn:
        return None
    return (f"מבין {tot:,} הרשומות עם טלפון קווי בישראל, הקידומת הנפוצה היא של "
            f"{lead}: {ln:,} ({_p(_pct(ln, tot))}), ואחריה {sec} ({sn:,}).")


def insight_contact(d):
    total = len(d)
    none_ = int((~d["has_phone"] & ~d["has_cell"]).sum())
    both = int((d["has_phone"] & d["has_cell"]).sum())
    if total == 0:
        return None
    s = f"ב-{both:,} רשומות ({_p(_pct(both, total))}) מופיעים גם טלפון קווי וגם נייד"
    if none_ > 0:
        s += "; " + ("ברשומה אחת" if none_ == 1 else f"ב-{none_:,} רשומות") + " אין מספר טלפון כלל."
    else:
        s += "; לכל רשומה יש לפחות מספר טלפון אחד."
    return s


def insight_dups(d):
    k = int(d.duplicated(["first", "last", "role", "phone", "cell"]).sum())
    if k == 0:
        return None
    return (f"{_n(k, 'רשומה אחת מופיעה', 'רשומות מופיעות')} ברשימה פעמיים בדיוק "
            f"(אותו שם, תפקיד וטלפונים); הספירות בעמוד כוללות אותן כפי שפורסמו.")


def insight_surname(surnames, total):
    if not surnames:
        return None
    lead, ln = surnames[0]
    if ln < MIN_SURNAME_INSIGHT:
        return None
    if len(surnames) > 1 and surnames[1][1] == ln:
        return None
    s = f"שם המשפחה הנפוץ ברשימה הוא {lead}, עם {ln:,} רשומות"
    if len(surnames) > 1:
        s += f"; אחריו {surnames[1][0]} ({surnames[1][1]:,})"
    return s + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    d = _prepare(frames["main"])
    total = len(d)

    roles = _counts(d["role"])
    role_names = [r for r, _ in roles]

    grp_counts = {g: int((d["group"] == g).sum()) for g in GROUPS}
    groups = [(g, grp_counts[g]) for g in GROUPS if grp_counts[g] > 0]

    countries = _counts(d.loc[d["group"] == ABROAD, "country"])
    c_top = countries[:TOP_COUNTRIES]
    c_rest = sum(n for _, n in countries[TOP_COUNTRIES:])
    country_chart = [(c, n) for c, n in c_top]
    if c_rest:
        country_chart.append(("אחר", c_rest))
    abroad_n = grp_counts[ABROAD]

    regions = _counts(d.loc[d["group"] == ISRAEL, "region"])
    regions = [x for x in regions if x[0] != NO_AREA] + [x for x in regions if x[0] == NO_AREA]
    israel_n = grp_counts[ISRAEL]

    surnames = _counts(d.loc[d["last"] != "", "last"])
    s_top = [(s, n) for s, n in surnames[:TOP_SURNAMES] if n >= 2]
    distinct_last = len(surnames)

    # role x group (share of each role's records)
    mix_rows = []
    series = {g: {"name": g, "count": [], "share": []} for g in GROUPS}
    for r, n in roles:
        sub = d[d["role"] == r]
        cells = []
        for g in GROUPS:
            k = int((sub["group"] == g).sum())
            series[g]["count"].append(k)
            series[g]["share"].append(_pct(k, n))
            cells.append(f"{k:,} ({_p(_pct(k, n))})")
        mix_rows.append({"name": r, "cells": cells, "total": f"{n:,}"})
    mix_series = [series[g] for g in GROUPS if grp_counts[g] > 0]
    mix_cells_idx = [i for i, g in enumerate(GROUPS) if grp_counts[g] > 0]
    for row in mix_rows:
        row["cells"] = [row["cells"][i] for i in mix_cells_idx]

    insights = []
    for iid, txt in [
        ("leader", insight_leader(roles, total)),
        ("ratio", insight_ratio(roles)),
        ("abroad", insight_abroad(d, countries)),
        ("role_abroad", insight_role_abroad(d)),
        ("region", insight_region(regions)),
        ("contact", insight_contact(d)),
        ("surname", insight_surname(surnames, total)),
        ("dups", insight_dups(d)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    rd = dict(roles)
    shochet_n = rd.get("שוחט", 0)
    lead_role, lead_n = roles[0] if roles else ("", 0)

    # summary_he: lookup task first, then numbers; trimmed to fit.
    head = "איתור שוחט, בודק או מנקר מוסמך של הרבנות הראשית לפי שם ותפקיד"
    parts = [f"{total:,} רשומות"]
    if lead_role:
        parts.append(f"מהן {lead_n:,} בתפקיד {lead_role}")
    if shochet_n and lead_role != "שוחט":
        parts.append("שוחט אחד" if shochet_n == 1 else f"{shochet_n:,} שוחטים")
    summary = f"{head}: " + ", ".join(parts) + "."
    while len(summary) > SUMMARY_MAX and len(parts) > 1:
        parts.pop()
        summary = f"{head}: " + ", ".join(parts) + "."

    countries_display = len(countries)
    abroad_share = _pct(abroad_n, total)

    lede = (f"הרבנות הראשית לישראל מפרסמת את רשימת השוחטים והבודקים המאושרים על ידה: "
            f"{total:,} רשומות ב-{_n(len(roles), 'תפקיד אחד', 'תפקידים')} "
            f"({', '.join(role_names)}). לכל רשומה יש שם פרטי, שם משפחה, תפקיד ומספרי טלפון; "
            f"אין ברשימה יישוב, מספר תעודה או תוקף הסמכה. כדי לבדוק אם שוחט או בודק כשרות "
            f"מופיע ברשימת המוסמכים, חפשו את שמו בחיפוש שמתחת לניתוח.")

    role_rows = [{"name": r, "count": f"{n:,}", "share": _p(_pct(n, total)),
                  "note": ROLE_NOTES.get(r, "")} for r, n in roles]

    labels = {
        "lede": lede,
        "search_fields": "שם פרטי, שם משפחה ותפקיד (" + ", ".join(role_names) + ")",
        "total_kpi": "רשומות ברשימה",
        "roles_kpi": "תפקידים",
        "abroad_kpi": "רשומות עם טלפון בחו״ל",
        "countries_kpi": "מדינות בחו״ל לפי קידומת",
        "job_note": (f"התפקיד {lead_role} מהווה {_p(_pct(lead_n, total))} מהרשומות. "
                     f"תפקיד אחד לכל רשומה; אדם בכמה תפקידים מופיע בכמה רשומות.")
                    if lead_role else "",
        "job_aria": (f"גרף עמודות: מספר הרשומות לפי תפקיד. התפקיד {lead_role} מוביל עם "
                     f"{lead_n:,} רשומות מתוך {total:,}.") if lead_role else "גרף עמודות לפי תפקיד",
        "job_caption": "מספר הרשומות לפי תפקיד, שיעור מכלל הרשימה והסבר קצר",
        "loc_note": (f"סיווג לפי קידומת החיוג של מספרי הטלפון (לא כתובת): {israel_n:,} רשומות "
                     f"עם מספר ישראלי בלבד, {abroad_n:,} עם מספר בחו״ל, "
                     f"ו-{grp_counts[UNKNOWN]:,} שמספריהן חסרים או אינם ניתנים לזיהוי."),
        "loc_aria": (f"גרף טבעת: רשומות לפי מיקום מספר הטלפון. {abroad_n:,} רשומות "
                     f"({_p(abroad_share)}) עם מספר בחו״ל."),
        "loc_caption": "רשומות לפי מיקום מספר הטלפון (ישראל, חו״ל, לא מזוהה)",
        "country_note": (f"{abroad_n:,} רשומות עם מספר טלפון בחו״ל, לפי קוד המדינה בקידומת"
                         + (f"; מוצגות {TOP_COUNTRIES} המדינות המובילות והשאר תחת אחר."
                            if c_rest else ".")),
        "country_aria": (f"גרף עמודות: רשומות עם טלפון בחו״ל לפי מדינה. "
                         f"{countries[0][0]} מובילה עם {countries[0][1]:,}.") if countries else "",
        "country_caption": "רשומות עם מספר טלפון בחו״ל לפי מדינה",
        "region_aria": (f"גרף עמודות: רשומות עם מספר ישראלי לפי אזור הקידומת. "
                        f"{regions[0][0]}: {regions[0][1]:,}.") if regions else "",
        "region_caption": "רשומות עם מספר ישראלי לפי אזור הקידומת הקווית",
        "mix_note": "לכל תפקיד: איזה חלק מהרשומות כולל מספר טלפון בחו״ל.",
        "mix_aria": "גרף עמודות מוערמות: התפלגות מיקום מספר הטלפון בכל תפקיד, באחוזים.",
        "mix_caption": "מיקום מספר הטלפון לפי תפקיד: מספר רשומות ושיעור מהתפקיד",
        "surname_note": (f"{distinct_last:,} שמות משפחה שונים ברשימה; "
                         f"מוצגים הנפוצים ביותר (שניים או יותר)."),
        "surname_aria": (f"גרף עמודות: שמות המשפחה הנפוצים ברשימה. {s_top[0][0]} מוביל עם "
                         f"{s_top[0][1]:,} רשומות.") if s_top else "",
        "surname_caption": "שמות המשפחה הנפוצים ברשימה ומספר הרשומות",
    }
    labels["region_note"] = (f"{israel_n:,} הרשומות עם מספר ישראלי, לפי קידומת הטלפון הקווי ("
                             + ", ".join(AREA_CODES) + f"). רשומה עם נייד בלבד או מספר ארצי "
                             f"נספרת תחת {NO_AREA}.")

    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "roles": {"value": len(roles), "display": f"{len(roles):,}", "tone": "brand"},
        "abroad": {"value": abroad_share, "display": _p(abroad_share),
                   "tone": "info" if abroad_n else "brand"},
        "countries": {"value": countries_display, "display": f"{countries_display:,}",
                      "tone": "info" if countries_display else "brand"},
    }

    charts = {
        "job": {"names": role_names, "values": [n for _, n in roles],
                "share": [_pct(n, total) for _, n in roles]},
        "loc": {"items": [{"name": g, "value": n} for g, n in groups]},
        "country": {"names": [c for c, _ in country_chart],
                    "values": [n for _, n in country_chart]},
        "region": {"names": [r for r, _ in regions], "values": [n for _, n in regions]},
        "mix": {"names": role_names, "series": mix_series},
        "surname": {"names": [s for s, _ in s_top], "values": [n for _, n in s_top]},
    }

    tables = {
        "roles": role_rows,
        "loc": [{"name": g, "count": f"{n:,}", "share": _p(_pct(n, total))} for g, n in groups],
        "country": [{"name": c, "count": f"{n:,}", "share": _p(_pct(n, abroad_n))}
                    for c, n in country_chart],
        "region": [{"name": r, "count": f"{n:,}", "share": _p(_pct(n, israel_n))}
                   for r, n in regions],
        "mix": mix_rows,
        "mix_heads": [s["name"] for s in mix_series],
        "surname": [{"name": s, "count": f"{n:,}"} for s, n in s_top],
    }

    flags = {
        "country": bool(countries),
        "region": len(regions) >= 2,
        "mix": abroad_n > 0 and len(roles) >= 2,
        "surname": len(s_top) >= 3,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["כשרות", "שחיטה", "שוחטים", "בודקי כשרות", "רבנות"],
            "related_ids": RELATED,
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "labels": labels,
        "insights": insights,
    }
