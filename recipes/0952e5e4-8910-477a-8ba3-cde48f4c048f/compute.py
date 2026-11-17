"""Pharmacies licensed to sell medical cannabis (Ministry of Health).

One row per pharmacy: name, home-delivery flag (filled only for part of the
list), street, city, free-text notes and a Google Maps link. The page shows
where the pharmacies are (cities, concentration), who runs them (chains vs
independents) and what the list says about home delivery.
"""
import re

import pandas as pd
from govlib import fmt, frame

TOP_CITIES = 15
TOP_SP_CITIES = 10
LIST_CAP = 20
UNSTATED = "לא צוין"
INDEPENDENT = "עצמאיים ורשתות קטנות"

# Known chains, matched on the start of the pharmacy name after a leading
# "בית מרקחת" / "בית המרקחת" is stripped. Anything else falls through to
# INDEPENDENT, so a new chain shows up there until added.
CHAINS = [
    ("סופר פארם", ("סופר פארם", "סופר-פארם", "סופרפארם")),
    ("ביפארם", ("ביפארם", "בי פארם", "בי-פארם")),
    ("גבעול", ("גבעול",)),
    ("לאון פארם", ("לאון פארם",)),
    ("פנופארם", ("פנופארם", "פנו-פארם", "פנו פארם")),
    ("מדי פלוס", ("מדי פלוס",)),
]
# Brands written as a Latin token anywhere in the name ("Be משמר השרון",
# "עין שמר Be"): Be is Shufersal's pharmacy brand.
TOKEN_CHAINS = [("Be (שופרסל)", re.compile(r"(?<![A-Za-z])Be(?![A-Za-z])"))]
_GENERIC_PREFIX = re.compile(r"^(?:בית המרקחת|בית מרקחת|בי\"מ)\s+")

# Locality spellings folded to one name (applied after hyphens become spaces
# and "קרית" becomes "קריית"): geresh and yud/vav variants, renamed towns,
# a town listed by its short or long name. Neighbourhoods stay as listed.
CITY_ALIASES = {
    "סחנין": "סח'נין",
    "עוספייה": "עוספיה",
    "עספיא": "עוספיה",
    "קלאנסוה": "קלנסווה",
    "נצרת עלית": "נוף הגליל",
    "נצרת עילית": "נוף הגליל",
    "כפר יפיע": "יפיע",
    "טבעון": "קריית טבעון",
    "קדימה": "קדימה צורן",
    "כרכור": "פרדס חנה כרכור",
    "פרדס חנה": "פרדס חנה כרכור",
    "מעלות": "מעלות תרשיחא",
    "בני עייש": 'בני עי"ש',
    'גני טל בני עי"ש': 'בני עי"ש',
    "מודיעין": "מודיעין מכבים רעות",
}
LEAD_CHAIN = CHAINS[0][0]

# Count buckets for "how many pharmacies does a city have".
BUCKETS = [(1, 1, "בית מרקחת אחד"), (2, 2, "שניים"), (3, 5, "3 עד 5"),
           (6, 10, "6 עד 10"), (11, 20, "11 עד 20"), (21, None, "21 ומעלה")]

_INVISIBLE = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_DELIVERY_NOTE = re.compile(r"משלוח")
# "אין משלוחים", "ללא משלוח", "אין אפשרות למשלוחים": a negation up to two
# words before the delivery word.
_DELIVERY_NEG = re.compile(r"(?<!\S)(?:אין|ללא|לא|בלי)\s+(?:\S+\s+){0,2}\S*משלוח")
_MALL = re.compile(r"קניון")


def _clean(series: pd.Series) -> pd.Series:
    return frame.clean_series(series.fillna("").astype(str).str.replace(_INVISIBLE, "", regex=True))


def _city(s: str) -> str:
    s = frame.clean(s.replace("-", " "))
    s = re.sub(r"(?<!\S)קרית(?!\S)", "קריית", s)
    s = CITY_ALIASES.get(s, s)
    return s or UNSTATED


def _offers_delivery(note: str) -> bool:
    return bool(_DELIVERY_NOTE.search(note)) and not _DELIVERY_NEG.search(note)


def _chain(name: str) -> str:
    base = _GENERIC_PREFIX.sub("", name)
    for label, prefixes in CHAINS:
        if any(base.startswith(p) for p in prefixes):
            return label
    for label, pat in TOKEN_CHAINS:
        if pat.search(name):
            return label
    return INDEPENDENT


def _share(a, b) -> float:
    return a / b if b else 0.0


def compute(frames: dict) -> dict:
    df = frames["main"]
    name = _clean(df["pharmacy_name"])
    street = _clean(df["pharmacy_street"])
    city = _clean(df["pharmacy_city"]).map(_city)
    notes = _clean(df["pharmacy_notes"])
    deliv_raw = _clean(df["pharmacy_delivery"])
    deliv = deliv_raw.map(lambda v: "כן" if v == "כן" else ("לא" if v == "לא" else UNSTATED))
    chain = name.map(_chain)

    total = len(df)
    t = fmt.int_he

    # ---- cities -------------------------------------------------------
    city_counts = frame.ranked(city[city != UNSTATED])
    n_cities = len(city_counts)
    no_city = int((city == UNSTATED).sum())
    OTHER_CITIES = "שאר היישובים"
    c_labels, c_values = frame.top_other(city_counts, TOP_CITIES, other=OTHER_CITIES)
    cities_tbl = [[lab, t(v), fmt.pct(_share(v, total))] for lab, v in zip(c_labels, c_values)]

    top5 = int(city_counts.iloc[:5].sum()) if n_cities else 0
    top5_share = _share(top5, total)
    single = int((city_counts == 1).sum())

    # buckets
    b_labels, b_cities, b_pharm = [], [], []
    for lo, hi, lab in BUCKETS:
        m = (city_counts >= lo) & ((city_counts <= hi) if hi is not None else True)
        b_labels.append(lab)
        b_cities.append(int(m.sum()))
        b_pharm.append(int(city_counts[m].sum()))
    spread_tbl = [[lab, t(c), t(p)] for lab, c, p in zip(b_labels, b_cities, b_pharm)]

    # ---- chains -------------------------------------------------------
    chain_counts = frame.ranked(chain)
    named = chain_counts.drop(INDEPENDENT, errors="ignore")
    ch_labels = [str(k) for k in named.index] + ([INDEPENDENT] if INDEPENDENT in chain_counts.index else [])
    ch_values = [int(chain_counts[k]) for k in ch_labels]
    chains_tbl = [[lab, t(v), fmt.pct(_share(v, total))] for lab, v in zip(ch_labels, ch_values)]
    lead_n = int(chain_counts.get(LEAD_CHAIN, 0))
    lead_share = _share(lead_n, total)
    indep_n = int(chain_counts.get(INDEPENDENT, 0))

    # lead chain inside the biggest cities
    sp_cities = [str(c) for c in city_counts.index[:TOP_SP_CITIES]]
    sp_in, sp_out, sp_tbl, sp_rates = [], [], [], []
    for c in sp_cities:
        m = city == c
        a = int((m & (chain == LEAD_CHAIN)).sum())
        b = int(m.sum()) - a
        sp_in.append(a)
        sp_out.append(b)
        sp_rates.append((c, a, a + b))
        sp_tbl.append([c, t(a), t(b), fmt.pct(_share(a, a + b), 0)])

    # ---- delivery -----------------------------------------------------
    # Mutually exclusive buckets: the field says yes; the field doesn't say
    # yes but a note offers delivery; the field says no (and no note offers);
    # nothing stated.
    note_deliv = notes.map(_offers_delivery)
    bucket = pd.Series(UNSTATED, index=deliv.index)
    bucket[deliv == "לא"] = "לא"
    bucket[note_deliv & (deliv != "כן")] = "הערה"
    bucket[deliv == "כן"] = "כן"
    d_order = ["כן", "הערה", "לא", UNSTATED]
    d_counts = {k: int((bucket == k).sum()) for k in d_order}
    d_values = [d_counts[k] for k in d_order]
    d_labels = ["משלוח לפי שדה המשלוח", "משלוח לפי ההערות", "ללא משלוח", "לא צוין ברשימה"]
    delivery_tbl = [[lab, t(v), fmt.pct(_share(v, total))] for lab, v in zip(d_labels, d_values)]
    stated = int((deliv != UNSTATED).sum())
    offers = bucket.isin(["כן", "הערה"])
    offers_n = int(offers.sum())
    note_only = d_counts["הערה"]
    contra = int((note_deliv & (deliv == "לא")).sum())
    unstated_n = int((deliv == UNSTATED).sum())
    deliv_rows = pd.DataFrame({"name": name, "city": city, "notes": notes, "ok": offers})
    deliv_rows = deliv_rows[deliv_rows["ok"]].sort_values(["city", "name", "notes"], kind="stable")
    deliv_list = [[r.name or UNSTATED, r.city, r.notes or "–"] for r in deliv_rows.head(LIST_CAP).itertuples()]
    deliv_more = max(0, len(deliv_rows) - LIST_CAP)

    mall_n = int((name.str.contains(_MALL) | street.str.contains(_MALL) | notes.str.contains(_MALL)).sum())
    notes_n = int((notes != "").sum())
    no_name = int((name == "").sum())

    # ---- insights -----------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_lead_city():
        if n_cities < 2:
            return None
        c1, v1 = str(city_counts.index[0]), int(city_counts.iloc[0])
        v2 = int(city_counts.iloc[1])
        if v1 < 2 or v1 == v2:
            return None
        c2 = str(city_counts.index[1])
        return (f"{c1} מובילה ברשימה עם {t(v1)} בתי מרקחת המורשים למכור קנביס רפואי "
                f"({fmt.pct(_share(v1, total))} מהרשימה), לפני {c2} עם {t(v2)}.")
    add("lead_city", ins_lead_city())

    def ins_concentration():
        if n_cities < 10:
            return None
        return (f"בתי המרקחת פזורים ב-{t(n_cities)} יישובים, אבל חמשת היישובים הגדולים ברשימה "
                f"מרכזים {fmt.pct(top5_share)} מהם. ב-{t(single)} יישובים יש בית מרקחת מורשה אחד בלבד.")
    add("concentration", ins_concentration())

    def ins_lead_chain():
        if lead_share < 0.1:
            return None
        return (f"{LEAD_CHAIN} היא הרשת הגדולה ברשימה: {t(lead_n)} סניפים מתוך {t(total)} "
                f"({fmt.pct(lead_share)}). {t(indep_n)} בתי מרקחת ({fmt.pct(_share(indep_n, total))}) "
                f"אינם שייכים לאחת הרשתות המוכרות.")
    add("lead_chain", ins_lead_chain())

    def ins_sp_city():
        rows = [(c, a, n) for c, a, n in sp_rates if n >= 5]
        if len(rows) < 3 or lead_n == 0:
            return None
        hi = min(rows, key=lambda r: (-_share(r[1], r[2]), r[0]))
        lo = min(rows, key=lambda r: (_share(r[1], r[2]), r[0]))
        if _share(hi[1], hi[2]) - _share(lo[1], lo[2]) < 0.2:
            return None
        if lo[1] == 0:
            low = f"ואילו ב{lo[0]} אין אף סניף שלה בין {t(lo[2])} בתי המרקחת המורשים."
        else:
            low = (f"ואילו ב{lo[0]} רק {t(lo[1])} מתוך {t(lo[2])} "
                   f"({fmt.pct(_share(lo[1], lo[2]), 0)}).")
        return (f"משקלה של {LEAD_CHAIN} משתנה בין הערים: ב{hi[0]} {t(hi[1])} מתוך {t(hi[2])} בתי המרקחת "
                f"המורשים הם סניפים שלה ({fmt.pct(_share(hi[1], hi[2]), 0)}), {low}")
    add("sp_city", ins_sp_city())

    def ins_delivery():
        if offers_n == 0:
            return None
        extra = f" ({t(note_only)} מהם רק בהערות)" if note_only else ""
        clash = (f" אצל {t(contra)} מבין אלה שמציינים משלוח רק בהערות, שדה המשלוח עצמו מסומן 'לא'; "
                 "הם נספרים כאן כמציעי משלוח ולא כללא משלוח.") if contra else ""
        miss = (f" שדה המשלוח ריק אצל {t(unstated_n)} בתי מרקחת "
                f"({fmt.pct(_share(unstated_n, total))}), כך שהתמונה חלקית.") if unstated_n else ""
        return (f"רק {t(offers_n)} בתי מרקחת ברשימה מציינים משלוח של קנביס רפואי לבית המטופל{extra}, "
                f"ו-{t(d_counts['לא'])} מסומנים כללא משלוח.{clash}{miss}")
    add("delivery", ins_delivery())

    def ins_mall():
        if mall_n < 3:
            return None
        return (f"{t(mall_n)} בתי מרקחת ({fmt.pct(_share(mall_n, total))}) מזכירים קניון בשם, בכתובת "
                f"או בהערות, כלומר נמצאים במרכז קניות.")
    add("mall", ins_mall())

    # ---- KPIs + labels -----------------------------------------------
    kpis = {
        "total": {"value": total, "display": t(total), "tone": "brand"},
        "cities": {"value": n_cities, "display": t(n_cities), "tone": "brand"},
        "lead_share": {"value": round(lead_share * 100, 1), "display": fmt.pct(lead_share), "tone": "info"},
        "top5": {"value": round(top5_share * 100, 1), "display": fmt.pct(top5_share),
                 "tone": "warn" if top5_share >= 0.4 else "brand"},
    }

    top_city = str(city_counts.index[0]) if n_cities else ""
    lede = (f"משרד הבריאות מפרסם את רשימת בתי המרקחת שבהם מטופלים בעלי רישיון יכולים לרכוש מוצרי קנביס רפואי. "
            f"ברשימה {t(total)} בתי מרקחת ב-{t(n_cities)} יישובים"
            + (f", והמספר הגדול ביותר נמצא ב{top_city}" if top_city else "") + ". "
            "העמוד מציג איפה הם נמצאים, אילו רשתות מפעילות אותם ומה הרשימה אומרת על משלוחים עד הבית.")

    labels = {
        "lede": lede,
        "total_kpi": "בתי מרקחת מורשים למכירת קנביס רפואי",
        "cities_kpi": "יישובים עם בית מרקחת מורשה",
        "lead_kpi": f"מבתי המרקחת הם סניפי {LEAD_CHAIN}",
        "top5_kpi": "מבתי המרקחת נמצאים בחמשת היישובים המובילים",
        "cities_note": (f"{TOP_CITIES} היישובים עם הכי הרבה בתי מרקחת מורשים; כל השאר מקובצים יחד. "
                        + (f"{t(no_city)} רשומות בלי יישוב לא נכללו. " if no_city else "")
                        + "כתיב היישובים אוחד (קרית/קריית, מקף, גרש, יו\"ד וו\"ו כפולות, שמות ישנים כמו נצרת עלית); "
                        "שכונות ואזורי תעשייה מופיעים כפי שנרשמו."),
        "cities_aria": f"מספר בתי המרקחת המורשים לפי יישוב, {TOP_CITIES} המובילים",
        "spread_note": (f"כמה יישובים יש בכל קבוצת גודל, וכמה בתי מרקחת יש בהם יחד. "
                        f"{t(single)} יישובים נשענים על בית מרקחת מורשה אחד."),
        "spread_aria": "התפלגות היישובים לפי מספר בתי המרקחת המורשים בהם",
        "chains_note": (f"שיוך לרשת לפי תחילת שם בית המרקחת. {LEAD_CHAIN} מפעילה {t(lead_n)} סניפים; "
                        f"בתי מרקחת ששמם אינו פותח בשם של רשת מוכרת נספרים כעצמאיים או כרשתות קטנות."),
        "chains_aria": "בתי המרקחת המורשים לפי רשת",
        "sp_note": f"בכל אחד מ-{len(sp_cities)} היישובים הגדולים: כמה מבתי המרקחת המורשים הם סניפי {LEAD_CHAIN} וכמה לא.",
        "sp_aria": f"סניפי {LEAD_CHAIN} מול בתי מרקחת אחרים ביישובים הגדולים",
        "delivery_note": (f"שדה המשלוח ברשימה מולא עבור {t(stated)} בתי מרקחת בלבד. "
                          f"{t(offers_n)} מציינים משלוח עד הבית, בשדה המשלוח או בהערות; "
                          "בית מרקחת שההערה שלו מציינת משלוח נספר בקבוצת ההערות גם כששדה המשלוח ריק או מסומן 'לא'. "
                          "כל בית מרקחת נספר בקבוצה אחת בלבד."),
        "delivery_aria": "בתי המרקחת המורשים לפי מידע על משלוח לבית המטופל",
        "deliv_list_summary": (f"בתי המרקחת שמציינים משלוח עד הבית ({t(offers_n)})"
                               + (f", {LIST_CAP} הראשונים לפי יישוב" if deliv_more else "")),
        "quality_note": (f"הרשימה מתעדכנת מעת לעת ונבדקה כפי שפורסמה: {t(notes_n)} רשומות כוללות הערה חופשית "
                         f"(מיקום או משלוחים), {t(no_name)} בלי שם בית מרקחת ו-{t(no_city)} בלי יישוב."),
        "lookup_sub": "חיפוש חי בכל רשומות המאגר: שם בית המרקחת, רחוב, יישוב והערות",
    }

    summary = (f"{t(total)} בתי מרקחת ב-{t(n_cities)} יישובים מורשים למכור קנביס רפואי למטופלים בעלי רישיון; "
               f"{LEAD_CHAIN} מפעילה {fmt.pct(lead_share)} מהם"
               + (f", ו{top_city} מובילה במספר בתי המרקחת" if top_city else "") + ".")
    desc = (f"איתור בית מרקחת שמוכר קנביס רפואי לפי עיר או שם: {t(total)} בתי מרקחת מורשים "
            f"ב-{t(n_cities)} יישובים, עם רשתות ומשלוחים עד הבית.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "בתי מרקחת שמוכרים קנביס רפואי: רשימה לפי עיר",
                "description": desc,
                "name": "בתי מרקחת המורשים למכור קנביס רפואי",
                "alternate_names": [
                    "בתי מרקחת קנאביס רפואי",
                    "רשימת בתי מרקחת לקנביס רפואי",
                    "בתי מרקחת עם רישיון לקנביס",
                    "איפה קונים קנביס רפואי",
                ],
            },
        },
        "kpis": kpis,
        "charts": {
            "cities": {"names": c_labels, "values": c_values, "other": OTHER_CITIES},
            "spread": {"names": b_labels, "cities": b_cities, "pharm": b_pharm},
            "chains": {"names": ch_labels, "values": ch_values, "other": INDEPENDENT},
            "sp": {"names": sp_cities, "in": sp_in, "out": sp_out, "chain": LEAD_CHAIN},
            "delivery": {"names": d_labels, "values": d_values},
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "cities": cities_tbl,
            "spread": spread_tbl,
            "chains": chains_tbl,
            "sp": sp_tbl,
            "delivery": delivery_tbl,
            "deliv_list": deliv_list,
        },
        "flags": {
            "sp": len(sp_cities) >= 3 and lead_n > 0,
            "deliv_list": bool(deliv_list),
        },
    }
