"""נציגויות זרות בישראל — foreign diplomatic missions accredited to Israel
(embassies, non-resident embassies, consulates general, consulates).

Two twin files keyed by the mission code `k_ntz`: a Hebrew one (country,
mission name, status, address, phone, fax) and an English one with the
same rows translated. Hebrew names drive the page; the English country
name keys the region map and the English mission name ("... in Haifa")
gives the seat city of consulates that list no address. A few missions
appear on several rows (one per phone/fax variant); they are counted once.

Regions follow the Foreign Ministry's own division of countries into
geographic areas as it appears on the sibling dataset of Israel's
missions abroad (14f2521f), so both pages group countries identically.
Countries the map does not know fall into "אחר" and still show up.

Missions and heads of mission act publicly; office phone/fax are only
counted (completeness), never printed — the explorer under the page has them.
"""
import re

import pandas as pd

OTHER = "אחר"
NO_CITY = "לא צוינה כתובת"
UNKNOWN_CITY = "כתובת לא מזוהה"
TOP_CITIES = 7
MIN_REGION_EMB = 5          # region needs this many embassies for the share contrast
CONTRAST_PP = 20            # non-resident share gap (percentage points) worth stating
CONC_SHARE = 0.5            # top-3 cities must hold at least this share of seats

STATUS_ORDER = ["שגרירות", "שגרירות לא תושבת", "קונסוליה כללית", "קונסוליה"]
RESIDENT_EMB = "שגרירות"
NON_RES = "שגרירות לא תושבת"

REGION_ORDER = ["אירופה", "אמריקה", "אפריקה", "אסיה", "פאסיפיק"]

# English country name -> MFA region (Hebrew), as assigned in 14f2521f's Hebrew file.
# Countries absent there were placed by the same scheme. Unknown -> OTHER.
_EU, _AM, _AF, _AS, _PA = REGION_ORDER
REGION = {
    "Albania": _EU, "Andorra": _EU, "Austria": _EU, "Belarus": _EU, "Belgium": _EU,
    "Bosnia and Herzegovina": _EU, "Bulgaria": _EU, "Croatia": _EU, "Cyprus": _EU,
    "Czech Republic": _EU, "Denmark": _EU, "Estonia": _EU, "Finland": _EU, "France": _EU,
    "Germany": _EU, "Greece": _EU, "Holy See": _EU, "Hungary": _EU, "Iceland": _EU,
    "Ireland": _EU, "Italy": _EU, "Kosovo": _EU, "Latvia": _EU, "Liechtenstein": _EU,
    "Lithuania": _EU, "Luxembourg": _EU, "Malta": _EU, "Moldova": _EU, "Monaco": _EU,
    "Montenegro": _EU, "Netherlands": _EU, "North Macedonia": _EU, "Norway": _EU,
    "Poland": _EU, "Portugal": _EU, "Romania": _EU, "Russian Federation": _EU,
    "San Marino": _EU, "Serbia": _EU, "Slovak, The Republic": _EU, "Slovenia": _EU,
    "Spain": _EU, "Sweden": _EU, "Switzerland": _EU, "Turkey": _EU, "Turkmenistan": _EU,
    "Ukraine": _EU, "United Kingdom": _EU, "Kyrgyzstan": _EU, "Tajikistan": _EU,
    "Antigua and Barbuda": _AM, "Argentina": _AM, "Bahamas": _AM, "Barbados": _AM,
    "Belize": _AM, "Bolivia": _AM, "Brazil": _AM, "Canada": _AM, "Chile": _AM,
    "Colombia": _AM, "Costa Rica": _AM, "Cuba": _AM, "Dominica": _AM,
    "Dominican Republic": _AM, "Ecuador": _AM, "El Salvador": _AM, "Grenada": _AM,
    "Guatemala": _AM, "Guyana": _AM, "Haiti": _AM, "Honduras": _AM, "Jamaica": _AM,
    "Mexico": _AM, "Nicaragua": _AM, "Panama": _AM, "Paraguay": _AM, "Peru": _AM,
    "St. Kitts and Nevis": _AM, "St. Lucia": _AM, "St. Vincent - The Grenadines": _AM,
    "Suriname": _AM, "Trinidad & Tobago": _AM, "United States of America": _AM,
    "Uruguay": _AM, "Venezuela": _AM,
    "Angola": _AF, "Benin": _AF, "Botswana": _AF, "Burkina Faso": _AF, "Burundi": _AF,
    "Cameroon": _AF, "Cape Verde": _AF, "Central African Republic": _AF, "Chad": _AF,
    "Congo": _AF, "Congo (Democratic Republic)": _AF, "Cote d'Ivoire": _AF, "Egypt": _AF,
    "Equatorial Guinea": _AF, "Eswatini": _AF, "Ethiopia": _AF, "Gabon": _AF,
    "Gambia": _AF, "Ghana": _AF, "Guinea": _AF, "Guinea-Bissau": _AF, "Kenya": _AF,
    "Lesotho": _AF, "Liberia": _AF, "Madagascar": _AF, "Malawi": _AF, "Mali": _AF,
    "Mauritania": _AF, "Mauritius": _AF, "Morocco": _AF, "Mozambique": _AF,
    "Namibia": _AF, "Niger": _AF, "Nigeria": _AF, "Rwanda": _AF,
    "Sao Tome and Principe": _AF, "Senegal": _AF, "Seychelles": _AF,
    "Sierra Leone": _AF, "Somaliland": _AF, "South Africa": _AF, "South Sudan": _AF,
    "Sudan": _AF, "Togo": _AF, "Uganda": _AF, "United Republic of Tanzania": _AF,
    "Zambia": _AF, "Zimbabwe": _AF,
    "Armenia": _AS, "Azerbaijan": _AS, "Bahrain": _AS, "Bhutan": _AS, "Cambodia": _AS,
    "China": _AS, "East Timor": _AS, "Eritrea": _AS, "Georgia": _AS, "India": _AS,
    "Japan": _AS, "Jordan": _AS, "Kazakhstan": _AS, "Korea": _AS, "Laos": _AS,
    "Mongolia": _AS, "Myanmar": _AS, "Nepal": _AS, "Philippines": _AS, "Qatar": _AS,
    "Singapore": _AS, "Sri Lanka": _AS, "Taiwan": _AS, "Thailand": _AS,
    "United Arab Emirates": _AS, "Uzbekistan": _AS, "Viet Nam": _AS,
    "Australia": _PA, "Cook Islands": _PA, "Fiji": _PA, "Kiribati": _PA,
    "Marshall Islands": _PA, "Micronesia": _PA, "Nauru": _PA, "New Zealand": _PA,
    "Niue": _PA, "Papua New Guinea": _PA, "Republic Of Palau": _PA, "Samoa": _PA,
    "Solomon Islands": _PA, "Tonga": _PA, "Tuvalu": _PA, "Vanuatu": _PA,
}

# Lower-case English keyword -> Hebrew city. The earliest match in the text wins.
CITY_KEYS = [
    ("tel aviv", "תל אביב-יפו"), ("jaffa", "תל אביב-יפו"),
    ("ramat gan", "רמת גן"), ("herzl", "הרצליה"), ("herzel", "הרצליה"),
    ("jerusalem", "ירושלים"), ("haifa", "חיפה"), ("eilat", "אילת"),
    ("rishon", "ראשון לציון"), ("bnei brak", "בני ברק"), ("ben shemen", "בן שמן"),
    ("petah tikva", "פתח תקווה"), ("netanya", "נתניה"), ("kfar shmaryahu", "כפר שמריהו"),
    ("ra'anana", "רעננה"), ("raanana", "רעננה"), ("holon", "חולון"),
]
JERUSALEM = "ירושלים"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + names[-1]


def _city(text):
    t = text.lower()
    best = None
    for key, city in CITY_KEYS:
        i = t.find(key)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, city)
    return best[1] if best else None


def _seat(address, name_en):
    if address:
        return _city(address) or UNKNOWN_CITY
    m = re.search(r"\bin ([A-Za-z' -]+)$", name_en.strip())
    if m:
        return _city(m.group(1)) or NO_CITY
    return NO_CITY


def _prepare(he, en):
    he = he.copy()
    en = en.copy()
    for df in (he, en):
        for c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    he = he[he["k_ntz"] != ""]
    raw_rows = len(he)
    he = he.sort_values(["k_ntz", "address", "tel", "fax", "shem_ntz"], kind="stable")
    agg = he.groupby("k_ntz", sort=True).agg(
        country=("shem_mdn", "first"), name=("shem_ntz", "first"), status=("maamad", "first"),
        address=("address", "first"), tel=("tel", lambda s: (s != "").any()),
        fax=("fax", lambda s: (s != "").any()),
    ).reset_index()
    en = en[en["k_ntz"] != ""].sort_values(["k_ntz", "shem_mdn_a", "shem_ntz_a"], kind="stable")
    en = en.drop_duplicates("k_ntz")[["k_ntz", "shem_mdn_a", "shem_ntz_a"]]
    m = agg.merge(en, on="k_ntz", how="left").fillna("")
    m["has_address"] = m["address"] != ""
    m["region"] = m["shem_mdn_a"].map(REGION).fillna(OTHER)
    m["seat"] = [_seat(a, n) for a, n in zip(m["address"], m["shem_ntz_a"])]
    m.loc[m["status"] == NON_RES, "seat"] = ""
    m["status"] = m["status"].replace("", "לא צוין")
    return m, raw_rows


def _status_order(values):
    known = [s for s in STATUS_ORDER if s in values]
    return known + sorted(v for v in values if v not in STATUS_ORDER)


def _region_order(values):
    known = [r for r in REGION_ORDER if r in values]
    return known + sorted(v for v in values if v not in REGION_ORDER)


def compute(frames):
    m, raw_rows = _prepare(frames["he"], frames["en"])
    n = len(m)
    dup_rows = raw_rows - n
    countries = int(m["country"].nunique())
    statuses = _status_order(set(m["status"]))
    sc = m["status"].value_counts()
    n_emb = int(sc.get(RESIDENT_EMB, 0))
    n_nonres = int(sc.get(NON_RES, 0))
    resident = m[m["status"] != NON_RES]
    n_res = len(resident)
    n_cons = n_res - n_emb

    # Status split.
    status_chart = {"names": statuses, "values": [int(sc.get(s, 0)) for s in statuses]}
    t_status = [{"name": s, "count": _int(sc.get(s, 0)), "share": f"{sc.get(s, 0) / n * 100:.1f}"}
                for s in statuses]

    # Region x status.
    regions = _region_order(set(m["region"]))
    rx = pd.crosstab(m["region"], m["status"]).reindex(index=regions, columns=statuses, fill_value=0)
    rc = m.groupby("region")["country"].nunique().reindex(regions, fill_value=0)
    region_chart = {"regions": regions,
                    "series": [{"name": s, "data": [int(v) for v in rx[s]]} for s in statuses]}
    t_region = []
    region_stats = []
    for r in regions:
        emb = int(rx.loc[r, RESIDENT_EMB]) if RESIDENT_EMB in rx.columns else 0
        nr = int(rx.loc[r, NON_RES]) if NON_RES in rx.columns else 0
        share = nr / (emb + nr) if emb + nr else 0.0
        region_stats.append((r, emb + nr, share))
        t_region.append({"name": r, "countries": _int(rc[r]), "total": _int(rx.loc[r].sum()),
                         "cells": [_int(rx.loc[r, s]) for s in statuses],
                         "nonres": f"{share * 100:.1f}"})

    # Seat city of resident missions (embassies + consulates).
    seats = resident["seat"].value_counts()
    seats = seats.sort_index().sort_values(ascending=False, kind="stable")
    named = seats[~seats.index.isin([NO_CITY, UNKNOWN_CITY])]
    top = list(named.index[:TOP_CITIES])
    rest_cities = [c for c in named.index if c not in top]
    city_names = top + ([OTHER] if rest_cities else [])
    unknown = [c for c in [UNKNOWN_CITY, NO_CITY] if c in seats.index]
    city_names += unknown

    def _bucket(c):
        return OTHER if c in rest_cities else c
    rs = resident.assign(bucket=resident["seat"].map(_bucket),
                         kind=resident["status"].where(resident["status"] == RESIDENT_EMB, "קונסוליה"))
    cx = pd.crosstab(rs["bucket"], rs["kind"]).reindex(index=city_names, fill_value=0)
    kinds = [k for k in [RESIDENT_EMB, "קונסוליה"] if k in cx.columns]
    kind_labels = {RESIDENT_EMB: "שגרירויות", "קונסוליה": "קונסוליות וקונסוליות כלליות"}
    city_chart = {"names": city_names,
                  "series": [{"name": kind_labels[k], "data": [int(v) for v in cx[k]]} for k in kinds]}
    t_city = [{"name": c, "total": _int(cx.loc[c].sum()), "cells": [_int(cx.loc[c, k]) for k in kinds]}
              for c in city_names]
    t_city_heads = [kind_labels[k] for k in kinds]

    # Missions seated in Jerusalem.
    jer = resident[resident["seat"] == JERUSALEM].copy()
    jer["s_ord"] = jer["status"].map({s: i for i, s in enumerate(statuses)})
    jer = jer.sort_values(["s_ord", "country", "k_ntz"], kind="stable")
    t_jer = [{"country": r.country, "status": r.status, "name": r.name} for r in jer.itertuples()]
    jer_emb = jer[jer["status"] == RESIDENT_EMB]
    jer_cons = jer[jer["status"] != RESIDENT_EMB]

    # Countries with more than one mission.
    per_c = m.groupby("country").agg(k=("k_ntz", "size"),
                                     kinds=("status", lambda s: sorted(s, key=lambda x: (statuses.index(x), x))))
    per_c = per_c.reset_index().sort_values(["k", "country"], ascending=[False, True], kind="stable")
    multi = per_c[per_c["k"] > 1]
    t_multi = []
    for r in multi.itertuples():
        cities = m[(m["country"] == r.country) & (m["seat"] != "")]
        cities = sorted(set(c for c in cities["seat"] if c not in (NO_CITY, UNKNOWN_CITY)))
        kinds_txt = ", ".join(f"{s} ({r.kinds.count(s)})" if r.kinds.count(s) > 1 else s
                              for s in dict.fromkeys(r.kinds))
        t_multi.append({"country": r.country, "count": _int(r.k), "kinds": kinds_txt,
                        "cities": ", ".join(cities) if cities else "—"})

    # Contact-detail completeness among resident missions.
    comp = [("כתובת", int(resident["has_address"].sum())), ("טלפון", int(resident["tel"].sum())),
            ("פקס", int(resident["fax"].sum()))]
    contact_chart = {"names": [c for c, _ in comp],
                     "values": [round(v / n_res * 100, 1) if n_res else 0 for _, v in comp],
                     "counts": [v for _, v in comp]}
    t_contact = [{"name": c, "count": _int(v), "share": f"{v / n_res * 100:.1f}" if n_res else "0.0"}
                 for c, v in comp]
    no_addr_res = n_res - comp[0][1]

    # ---- insights -------------------------------------------------------
    def ins_scale():
        if n == 0:
            return None
        return (f"במאגר {_int(n)} נציגויות של {_int(countries)} מדינות: {_int(n_emb)} שגרירויות תושבות, "
                f"{_int(n_cons)} קונסוליות וקונסוליות כלליות, ו-{_int(n_nonres)} שגרירויות לא תושבות "
                f"({_pct(n_nonres / n)}) — שגרירים שמכהנים מבירה אחרת ואין להם משרד בישראל.")

    def ins_concentration():
        if len(named) < 3:
            return None
        known = int(named.sum())
        top3 = named.head(3)
        share = top3.sum() / known
        if share < CONC_SHARE:
            return None
        parts = [f"{c} ({_int(v)})" for c, v in top3.items()]
        return (f"{_pct(share)} מהנציגויות התושבות שמקום מושבן ידוע יושבות בשלוש ערים: "
                f"{_join(parts)}.")

    def ins_jerusalem():
        if len(jer_emb) == 0:
            return None
        txt = (f"{_int(len(jer_emb))} שגרירויות יושבות בירושלים: {_join(jer_emb['country'])}")
        if len(jer_cons):
            txt += (f"; לצדן {_int(len(jer_cons))} קונסוליות כלליות וקונסוליות בעיר, "
                    f"ביניהן של {_join(sorted(jer_cons['country'].unique())[:4])}")
        return txt + "."

    def ins_region():
        cand = [(r, k, s) for r, k, s in region_stats if k >= MIN_REGION_EMB and r != OTHER]
        if len(cand) < 2:
            return None
        hi = max(cand, key=lambda x: (x[2], x[0]))
        lo = min(cand, key=lambda x: (x[2], x[0]))
        if (hi[2] - lo[2]) * 100 < CONTRAST_PP:
            return None
        return (f"ב{hi[0]} {_pct(hi[2], 0)} מהשגרירויות המוסמכות לישראל אינן תושבות, "
                f"לעומת {_pct(lo[2], 0)} ב{lo[0]}.")

    def ins_multi():
        if len(multi) == 0:
            return None
        lead_k = int(multi["k"].iloc[0])
        leaders = multi[multi["k"] == lead_k]["country"].tolist()
        if len(leaders) > 2:
            return f"{_int(len(multi))} מדינות מחזיקות יותר מנציגות אחת בישראל."
        lead_kinds = t_multi[0]["kinds"] if len(leaders) == 1 else None
        txt = f"{_int(len(multi))} מדינות מחזיקות יותר מנציגות אחת בישראל; "
        if len(leaders) == 1:
            txt += f"ל{leaders[0]} הכי הרבה — {_int(lead_k)} ({lead_kinds})."
        else:
            txt += f"ל{_join(leaders)} הכי הרבה — {_int(lead_k)} כל אחת."
        return txt

    def ins_contact():
        if n_res == 0 or no_addr_res == 0:
            return None
        return (f"ל-{_int(no_addr_res)} מתוך {_int(n_res)} הנציגויות התושבות לא רשומה כתובת במאגר, "
                f"ול-{_int(n_res - comp[1][1])} לא רשום טלפון.")

    rules = [("scale", ins_scale()), ("concentration", ins_concentration()),
             ("jerusalem", ins_jerusalem()), ("region", ins_region()),
             ("multi", ins_multi()), ("contact", ins_contact())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    dup_note = (f"{_int(dup_rows)} שורות במקור חוזרות על אותה נציגות (גרסאות שונות של מספר הטלפון "
                f"או הפקס) ונספרו פעם אחת." if dup_rows > 0 else "")
    other_note = ("" if OTHER not in regions else
                  f"{_int(rc[OTHER])} מדינות שאינן משויכות לאזור מופיעות תחת \"{OTHER}\".")

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} נציגויות זרות בישראל של {_int(countries)} מדינות — {_int(n_emb)} "
                           f"שגרירויות תושבות, {_int(n_cons)} קונסוליות ו-{_int(n_nonres)} שגרירויות לא "
                           f"תושבות — לפי מעמד, אזור בעולם ועיר המושב."),
            "dataset_kind": "registry",
            "related_ids": [
                "14f2521f-819a-4ea4-87e8-6811d43e4495",
                "505aa85e-a49f-4a49-aea2-4cc7b6e44e92",
                "4eaa3676-34ea-4c88-8980-dd64cba86411",
                "46577c12-8675-4464-a5ca-473ae20e3dd9",
            ],
            "suggested_tags": ["נציגויות זרות", "שגרירויות", "קונסוליות", "דיפלומטיה", "משרד החוץ"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "missions": {"value": n, "display": _int(n), "tone": "brand"},
            "countries": {"value": countries, "display": _int(countries), "tone": "brand"},
            "embassies": {"value": n_emb, "display": _int(n_emb), "tone": "brand"},
            "nonres": {"value": n_nonres, "display": _int(n_nonres), "tone": "info"},
        },
        "charts": {
            "status": status_chart,
            "region": region_chart,
            "city": city_chart,
            "contact": contact_chart,
        },
        "tables": {
            "status": t_status,
            "statuses": statuses,
            "region": t_region,
            "city": t_city,
            "city_heads": t_city_heads,
            "jerusalem": t_jer,
            "multi": t_multi,
            "contact": t_contact,
        },
        "flags": {"jerusalem": len(t_jer) > 0, "multi": len(t_multi) > 0},
        "insights": insights,
        "labels": {
            "lede": (f"רשימת הנציגויות הזרות המוסמכות לישראל, כפי שמפרסם משרד החוץ: {_int(n)} נציגויות של "
                     f"{_int(countries)} מדינות. שגרירות לא תושבת היא שגרירות שהשגריר שלה מכהן מבירה "
                     f"אחרת ואין לה משרד בישראל. {dup_note}").strip(),
            "status_aria": "תרשים עמודות: נציגויות לפי מעמד.",
            "region_aria": "תרשים עמודות מוערמות: נציגויות לפי אזור בעולם ומעמד.",
            "region_note": ("החלוקה לאזורים לפי חלוקת משרד החוץ, כמו בעמוד נציגויות ישראל בעולם. "
                            + other_note).strip(),
            "city_aria": "תרשים עמודות מוערמות: נציגויות תושבות לפי עיר המושב.",
            "city_lede": (f"{_int(n_res)} נציגויות תושבות (שגרירויות וקונסוליות) לפי העיר שבכתובתן; "
                          "לקונסוליות ללא כתובת העיר נלקחה משם הנציגות."),
            "jerusalem_lede": (f"{_int(len(jer_emb))} שגרירויות ו-{_int(len(jer_cons))} קונסוליות "
                               "שמקום מושבן בירושלים."),
            "multi_lede": f"{_int(len(t_multi))} מדינות עם יותר מנציגות אחת בישראל.",
            "contact_aria": "תרשים עמודות: שיעור הנציגויות התושבות שבמאגר רשומים להן כתובת, טלפון ופקס.",
            "contact_lede": (f"מתוך {_int(n_res)} הנציגויות התושבות — לכמה מהן רשומים פרטי קשר במאגר. "
                             "הפרטים עצמם בטבלת הנתונים שבתחתית העמוד."),
        },
    }
