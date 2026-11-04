"""Food laboratories list (Ministry of Health): a small directory.

One row per laboratory. The page is lookup-first: a directory of every lab
(name, city, address, phone, manager, what it tests), plus two small views
the data supports: test-type combinations (split by government / other
labs) and labs per city. Emails are read only for their domain (a gov.il
domain marks a government lab); fax and the near-empty district column are
not shown.
"""
import re

import pandas as pd
from govlib import fmt, frame

DIRECTORY_CAP = 60          # cards on the page; the shell's explorer holds the rest
CITY_TOP = 9                # city chart: top N + "אחר"
MULTI_SITE = "כמה אתרים"
NO_CITY = "לא צוין"
UNKNOWN_TYPE = "לא צוין"
GOV = "ממשלתיות"
OTHER_KIND = "אחרות"

_SPLIT_TYPES = re.compile(r"\s*[,/;\n]\s*")
_PHONE_TOKEN = re.compile(r"\*?\d[\d\-]*\d|\*\d+")
_GOV_DOMAIN = re.compile(r"@([\w.\-]+\.)?gov\.il$", re.IGNORECASE)


def _labs(n: int) -> str:
    return "מעבדה אחת" if n == 1 else f"{n:,} מעבדות"


def _cities(n: int) -> str:
    return "יישוב אחד" if n == 1 else f"{n:,} יישובים"


def _in_cities(n: int) -> str:
    return "ביישוב אחד" if n == 1 else f"ב-{n:,} יישובים"


def _city(address: str) -> str:
    a = frame.clean(address)
    if not a:
        return NO_CITY
    if ":" in a:  # "site A: … site B: …", several branches in one cell
        return MULTI_SITE
    if "," in a:
        c = a.rsplit(",", 1)[1].strip()
        return c or NO_CITY
    return a if len(a.split()) <= 3 else MULTI_SITE


def _types(raw: str) -> list[str]:
    toks = [t for t in (frame.clean(x) for x in _SPLIT_TYPES.split(raw or "")) if t]
    out = sorted(set(toks))
    return out or [UNKNOWN_TYPE]


def _combo(types: list[str]) -> str:
    if len(types) == 1:
        return types[0] if types[0] == UNKNOWN_TYPE else f"{types[0]} בלבד"
    return fmt.join_he(types)


def _phones(raw: str) -> str:
    s = (raw or "").replace("\xa0", " ")
    toks = []
    for t in _PHONE_TOKEN.findall(s):
        if t not in toks:
            toks.append(t)
    return ", ".join(toks)


def _is_gov(email: str, name: str) -> bool:
    e = frame.clean(email)
    return bool(_GOV_DOMAIN.search(e)) or "משרד הבריאות" in name


def compute(frames: dict[str, pd.DataFrame]) -> dict:
    df = frames["main"].copy()
    for c in ["lab_name", "address", "phone", "email", "manager", "test_material", "test_type"]:
        df[c] = frame.clean_series(df[c])
    df = df[df["lab_name"] != ""].copy()

    df["city"] = df["address"].map(_city)
    df["types"] = df["test_type"].map(_types)
    df["combo"] = df["types"].map(_combo)
    df["gov"] = [_is_gov(e, n) for e, n in zip(df["email"], df["lab_name"])]
    df["phones"] = df["phone"].map(_phones)
    df = df.sort_values(["lab_name", "address", "phones", "manager", "test_type"], kind="stable")

    n = len(df)
    n_gov = int(df["gov"].sum())
    n_oth = n - n_gov

    # --- test types -------------------------------------------------------
    type_counts = frame.ranked(df["types"].explode())
    type_counts = type_counts[type_counts.index != UNKNOWN_TYPE]
    multi = df[df["types"].map(len) >= 2]
    n_multi = len(multi)
    combo_counts = frame.ranked(df["combo"])
    # order: more types first, then count desc, then name
    combo_order = sorted(
        combo_counts.index,
        key=lambda c: (-len(df.loc[df["combo"] == c, "types"].iloc[0]), -int(combo_counts[c]), c),
    )
    gov_by_combo = [int(((df["combo"] == c) & df["gov"]).sum()) for c in combo_order]
    oth_by_combo = [int(((df["combo"] == c) & ~df["gov"]).sum()) for c in combo_order]
    combo_chart = {
        "names": combo_order,
        "series": [
            {"name": f"מעבדות {GOV}", "data": gov_by_combo},
            {"name": f"מעבדות {OTHER_KIND}", "data": oth_by_combo},
        ],
    }
    combo_table = [
        {"name": c, "gov": g, "oth": o, "total": g + o}
        for c, g, o in zip(combo_order, gov_by_combo, oth_by_combo)
    ]

    # --- cities -----------------------------------------------------------
    named = df[~df["city"].isin([MULTI_SITE, NO_CITY])]
    city_counts = frame.ranked(named["city"])
    n_cities = len(city_counts)
    labels, values = frame.top_other(city_counts, CITY_TOP)
    for extra in (MULTI_SITE, NO_CITY):
        k = int((df["city"] == extra).sum())
        if k:
            labels.append(extra)
            values.append(k)
    city_chart = {"names": labels, "values": values}
    city_table = [{"name": a, "count": b} for a, b in zip(labels, values)]
    n_multi_site = int((df["city"] == MULTI_SITE).sum())

    # --- directory --------------------------------------------------------
    order = df.assign(
        _m=df["city"].isin([MULTI_SITE, NO_CITY]).astype(int)
    ).sort_values(["_m", "city", "lab_name", "address"], kind="stable")
    directory = [
        {
            "name": r.lab_name,
            "city": r.city,
            "address": r.address,
            "phones": r.phones,
            "manager": r.manager,
            "types": list(r.types),
            "kind": "מעבדה ממשלתית" if r.gov else "",
        }
        for r in order.head(DIRECTORY_CAP).itertuples()
    ]
    capped = n > DIRECTORY_CAP

    # --- materials --------------------------------------------------------
    mat = frame.ranked(df.loc[df["test_material"] != "", "test_material"])

    # --- insights ---------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_both():
        if n < 2 or n_multi == 0:
            return None
        share = n_multi / n
        if n_multi == n:
            return f"כל {_labs(n)} ברשימה מבצעות יותר מסוג בדיקה אחד ({fmt.join_he(type_counts.index)})."
        verb = "מבצעת" if n_multi == 1 else "מבצעות"
        return (f"{_labs(n_multi)} מתוך {n:,} ({fmt.int_he(share * 100)}%) {verb} יותר מסוג בדיקה אחד, "
                f"והשאר מתמחות בסוג אחד בלבד.")

    def ins_types():
        if len(type_counts) < 2:
            return None
        parts = [f"{t}: {_labs(int(v))}" for t, v in type_counts.items()]
        return "מספר המעבדות לפי סוג בדיקה (מעבדה יכולה להופיע ביותר מסוג אחד): " + "; ".join(parts) + "."

    def ins_rare():
        singles = [c for c in combo_order if len(df.loc[df["combo"] == c, "types"].iloc[0]) == 1
                   and c != UNKNOWN_TYPE and int(combo_counts[c]) == 1]
        if not singles or n < 3:
            return None
        c = singles[0]
        name = df.loc[df["combo"] == c, "lab_name"].iloc[0]
        return f"רק מעבדה אחת ברשימה מבצעת {c}: {name}."

    def ins_gov():
        if n_gov == 0 or n_oth == 0:
            return None
        g_multi = int((df["gov"] & (df["types"].map(len) >= 2)).sum())
        o_multi = int((~df["gov"] & (df["types"].map(len) >= 2)).sum())
        lead = (f"{_labs(n_gov)} ברשימה {'היא מעבדה ממשלתית' if n_gov == 1 else 'הן מעבדות ממשלתיות'} "
                f"(כתובת דוא\"ל בדומיין gov.il או מעבדת משרד הבריאות)")
        if n_gov >= 2 and n_oth >= 2 and g_multi != o_multi:
            return (f"{lead}; {g_multi:,} מהן מבצעות יותר מסוג בדיקה אחד, "
                    f"לעומת {o_multi:,} מתוך {n_oth:,} המעבדות האחרות.")
        return lead + "."

    def ins_city():
        if n_cities < 2:
            return None
        top_c, top_v = city_counts.index[0], int(city_counts.iloc[0])
        second = int(city_counts.iloc[1])
        if top_v < 2 or top_v == second:
            ties = [c for c, v in city_counts.items() if v == top_v]
            if top_v >= 2 and len(ties) <= 3:
                return f"{fmt.join_he(ties)} מובילות, עם {_labs(top_v)} בכל אחת, מתוך {_cities(n_cities)} ברשימה."
            return None
        others2 = [c for c, v in city_counts.items() if v >= 2 and c != top_c]
        s = f"{top_c} מובילה עם {_labs(top_v)} מתוך {n:,}"
        if others2:
            s += f"; גם ב{fmt.join_he(others2)} יש יותר ממעבדה אחת"
        tail = ""
        if n_multi_site:
            tail = f" {_labs(n_multi_site)} רשומה עם כמה אתרים בכתובת אחת." if n_multi_site == 1 \
                else f" {_labs(n_multi_site)} רשומות עם כמה אתרים בכתובת אחת."
        return s + "." + tail

    add("both", ins_both())
    add("types", ins_types())
    add("gov", ins_gov())
    add("city", ins_city())
    add("rare", ins_rare())

    # --- text -------------------------------------------------------------
    top_type = type_counts.index[0] if len(type_counts) else ""
    if len(mat) == 1:
        mat_txt = f"כל המעבדות ברשימה רשומות לבדיקת {mat.index[0]}."
    elif len(mat) > 1:
        mat_txt = "חומרי הבדיקה ברשימה: " + "; ".join(f"{k} ({int(v):,})" for k, v in mat.items()) + "."
    else:
        mat_txt = ""
    city_part = _in_cities(n_cities) if n_cities else ""
    if n_multi_site == 1:
        multi_site_part = " (מעבדה אחת מהן רשומה עם כמה אתרים)"
    elif n_multi_site:
        multi_site_part = f" ({n_multi_site:,} מהן רשומות עם כמה אתרים)"
    else:
        multi_site_part = ""
    lede = (f"רשימת מעבדות המזון שמפרסם משרד הבריאות כוללת {_labs(n)} לבדיקות מזון {city_part}"
            f"{multi_site_part}. לכל מעבדה מופיעים כתובת, טלפון, מנהל/ת המעבדה וסוגי הבדיקות שהיא מבצעת"
            f" ({fmt.join_he(type_counts.index)}). {mat_txt}").replace("  ", " ").strip()

    summary = (f"איתור מעבדה לבדיקת מזון לפי שם, יישוב או סוג בדיקה: {_labs(n)} "
               f"{city_part}".strip())
    if n_multi and n_multi < n:
        summary += f", {n_multi:,} מהן מבצעות יותר מסוג בדיקה אחד."
    else:
        summary += "."
    if len(summary) > 155:
        summary = f"איתור מעבדה לבדיקת מזון לפי שם, יישוב או סוג בדיקה: {_labs(n)} ברשימת משרד הבריאות."

    combo_lead = combo_order[0] if combo_order else ""
    labels_out = {
        "lede": lede,
        "total_kpi": "מעבדות ברשימה",
        "multi_kpi": "מבצעות יותר מסוג בדיקה אחד",
        "gov_kpi": "מעבדות ממשלתיות",
        "cities_kpi": "יישובים (לפי הכתובת)",
        "combo_note": (f"צירופי סוגי הבדיקות של כל מעבדה, מפוצלים לפי מעבדות ממשלתיות (כתובת דוא\"ל בדומיין gov.il "
                       f"או מעבדת משרד הבריאות) ומעבדות אחרות. הצירוף הנפוץ: {combo_lead}."
                       if combo_lead else ""),
        "combo_aria": ("גרף עמודות אופקי מוערם: מעבדות לפי צירוף סוגי בדיקה, "
                       + "; ".join(f"{r['name']} {r['total']}" for r in combo_table) + "."),
        "combo_caption": "מעבדות לפי צירוף סוגי בדיקה וסוג מעבדה",
        "city_note": ("מספר המעבדות בכל יישוב, לפי היישוב שבסוף הכתובת. "
                      + (f"מעבדה שכתובתה כוללת כמה אתרים מוצגת כ\"{MULTI_SITE}\"." if n_multi_site else "")
                      + (f" מוצגים {CITY_TOP} היישובים המובילים והשאר תחת \"{frame.OTHER}\"."
                         if frame.OTHER in labels else "")).strip(),
        "city_aria": ("גרף עמודות אופקי: מעבדות לפי יישוב, "
                      + "; ".join(f"{a} {b}" for a, b in zip(labels, values)) + "."),
        "city_caption": "מעבדות לפי יישוב",
        "dir_note": (f"{_labs(n)}, לפי יישוב ושם המעבדה."
                     + (f" מוצגות {DIRECTORY_CAP:,} הראשונות; כל הרשומות זמינות בחיפוש שלמטה." if capped else "")),
        "top_type": top_type,
    }

    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "multi": {"value": n_multi, "display": f"{n_multi:,}", "tone": "brand"},
        "gov": {"value": n_gov, "display": f"{n_gov:,}", "tone": "brand"},
        "cities": {"value": n_cities, "display": f"{n_cities:,}", "tone": "brand"},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"combo": combo_chart, "city": city_chart},
        "tables": {"combo": combo_table, "city": city_table},
        "directory": directory,
        "insights": insights,
        "labels": labels_out,
    }
