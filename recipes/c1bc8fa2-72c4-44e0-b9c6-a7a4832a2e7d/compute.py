"""אשפוזיות לגמילה מסמים ומאלכוהול: Ministry of Health directory of licensed
addiction-treatment facilities.

One row per facility (~100): settlement (+ CBS settlement code), address
parts, facility code and name, phones/fax/email, the facility manager, an
ownership type and a facility type. Despite the title, three facility types
are listed: medical inpatient detox (code 15, "אשפוזית"), combined
residential frameworks (code 16: therapeutic communities, emergency intake
units) and ambulatory clinics (code 37, the majority). The file is a full
snapshot republished in place, so the page is a snapshot too.

Districts are not in the data: they come from a fixed map of CBS settlement
codes to the official districts, with a disclosed "לא ממופה" bucket for any
new settlement. Facility focus (youth, women, dual diagnosis, ...) is read
from the facility NAME only, and the page says so.

Managers are named in a professional capacity (medical/clinical directors).
Phones, emails and street addresses are not printed; contact columns feed a
completeness chart only. The shell's explorer under the page has them all.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_CITIES = 15
TOP_MANAGERS = 10
MAX_RES_ROWS = 60
UNMAPPED = "לא ממופה"
UNKNOWN_OWNER = "לא צוין"
OTHER_CITIES = "יישובים אחרים"

# Facility type codes: order and friendly labels. Unknown codes fall back to
# the raw institute_type_name and sort after these.
TYPE_INFO = {
    "15": ("אשפוזיות לגמילה", "אשפוזית לגמילה (רפואית)"),
    "16": ("מסגרות משולבות", "מסגרת משולבת: קהילה טיפולית וקליטה"),
    "37": ("מרפאות אמבולטוריות", "מרפאה אמבולטורית"),
}
TYPE_ORDER = ["15", "16", "37"]
TYPE_DESC = {
    "15": "אשפוזית לגמילה רפואית (גמילה גופנית בשהייה קצרה)",
    "16": "מסגרת משולבת (קהילה טיפולית, יחידת קליטת חירום ושיקום בשהייה)",
    "37": "מרפאה אמבולטורית (טיפול ללא לינה, כולל טיפול תרופתי ממושך)",
}
INPATIENT = "15"
RESIDENTIAL = {"15", "16"}
AMBULATORY = "37"

# Official districts by CBS settlement code (cities in the register as of
# authoring). A new settlement shows up as UNMAPPED, disclosed on the page.
DISTRICT_ORDER = ["ירושלים", "הצפון", "חיפה", "המרכז", "תל אביב", "הדרום", "יהודה והשומרון"]
CITY_DISTRICT = {
    "3000": "ירושלים", "2610": "ירושלים", "566": "ירושלים",
    "1154": "הצפון", "6700": "הצפון", "7300": "הצפון", "7700": "הצפון", "874": "הצפון",
    "497": "הצפון", "7600": "הצפון",
    "4000": "חיפה", "1167": "חיפה", "2710": "חיפה", "6500": "חיפה", "6800": "חיפה",
    "9600": "חיפה", "327": "חיפה", "6000": "חיפה",
    "168": "המרכז", "182": "המרכז", "2530": "המרכז", "2720": "המרכז", "2730": "המרכז",
    "418": "המרכז", "469": "המרכז", "587": "המרכז", "7000": "המרכז", "6900": "המרכז",
    "7400": "המרכז", "7900": "המרכז", "8300": "המרכז", "8500": "המרכז", "8700": "המרכז",
    "9400": "המרכז", "9700": "המרכז",
    "5000": "תל אביב", "6100": "תל אביב", "6200": "תל אביב", "6600": "תל אביב",
    "8600": "תל אביב",
    "2600": "הדרום", "2630": "הדרום", "70": "הדרום", "7100": "הדרום", "9000": "הדרום",
}

KUPA_RE = re.compile(r"קופת חולים|שירותי בריאות כללית|מכבי|מאוחדת|לאומית")

# Focus read from the facility name. A facility can match several or none.
FOCUS = [
    ("youth", "נוער וצעירים", re.compile(r"נוער|צעירים")),
    ("women", "נשים", re.compile(r"נשים")),
    ("dual", "תחלואה כפולה או משולשת", re.compile(r"תחלואה\s*(?:כפולה|משולשת)")),
    ("maint", "טיפול תרופתי ממושך", re.compile(r"תרופתי")),
    ("pain", "משככי כאבים", re.compile(r"משככי\s*כאבים")),
    ("alcohol", "אלכוהול", re.compile(r"אלכוהול")),
    ("community", "קהילה טיפולית", re.compile(r"קהיל")),
    ("intake", "קליטת חירום", re.compile(r"קלט")),
]

CONTACT = [
    ("phone", "טלפון תקין"),
    ("phone2", "טלפון נוסף"),
    ("email", "דוא״ל"),
    ("street", "רחוב ומספר בית"),
    ("zip", "מיקוד"),
    ("fax", "פקס"),
]

COUNT_WORDS = {1: "אחת", 2: "שתי", 3: "שלוש", 4: "ארבע", 5: "חמש", 6: "שש", 7: "שבע",
               8: "שמונה", 9: "תשע", 10: "עשר"}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def norm(s):
    return re.sub(r"\s+", " ", str(s).strip())


def ranked(s):
    """Counts sorted desc by value, ties by label (total order)."""
    s = s.sort_index(kind="stable")
    return s.sort_values(ascending=False, kind="stable")


def list_he(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    last = items[-1]
    joiner = " ו-" if not re.match(r"[֐-׿]", last[:1]) else " ו"
    return ", ".join(items[:-1]) + joiner + last


def facilities_word(k):
    return "מסגרת אחת" if k == 1 else f"{n(k)} מסגרות"


def phone_ok(p):
    d = re.sub(r"\D", "", p)
    return len(d) >= 9


# ---------------------------------------------------------------- insights

def insight_types(type_counts, labels_pl, total):
    if len(type_counts) < 2 or total == 0:
        return None
    lead = type_counts.index[0]
    lv = int(type_counts.iloc[0])
    if lv == int(type_counts.iloc[1]):
        return None
    s = (f"למרות שם המאגר, הסוג הנפוץ בו הוא {labels_pl[lead]}: {n(lv)} מתוך {n(total)} "
         f"({pct(lv / total * 100)})") if lead != INPATIENT else (
         f"הסוג הנפוץ במאגר הוא {labels_pl[lead]}: {n(lv)} מתוך {n(total)} ({pct(lv / total * 100)})")
    inp = int(type_counts.get(INPATIENT, 0))
    if lead != INPATIENT and inp:
        s += f". אשפוזיות לגמילה רפואית הן {n(inp)} בלבד ({pct(inp / total * 100)})"
    return s + "."


def insight_kupot(df):
    k = df[df["kupa"]]
    if len(k) < 2:
        return None
    n_kupot = k["owner"].nunique()
    amb = int((k["type"] == AMBULATORY).sum())
    s = f"{n(n_kupot)} קופות החולים מפעילות יחד {n(len(k))} מסגרות"
    if amb == len(k) and not k["type"].isin(RESIDENTIAL).any():
        s += ", וכולן מרפאות אמבולטוריות: אף אשפוזית או מסגרת שהייה במאגר אינה בבעלות קופת חולים"
    elif amb:
        s += f", מהן {n(amb)} מרפאות אמבולטוריות"
    return s + "."


def insight_residential_owner(df):
    r = df[df["type"].isin(RESIDENTIAL)]
    if len(r) < 5:
        return None
    oc = ranked(r["owner"].value_counts())
    if len(oc) < 2:
        return f"כל {n(len(r))} מסגרות השהייה (אשפוזיות ומסגרות משולבות) הן בבעלות מסוג {oc.index[0]}."
    a, va = oc.index[0], int(oc.iloc[0])
    b, vb = oc.index[1], int(oc.iloc[1])
    rest = len(r) - va - vb
    s = (f"מבין {n(len(r))} מסגרות השהייה (אשפוזיות ומסגרות משולבות), {n(va)} בבעלות מסוג {a} "
         f"ו-{n(vb)} בבעלות מסוג {b}")
    if rest:
        s += f"; {facilities_word(rest)} בבעלות אחרת"
    return s + "."


def insight_district(dist_counts, inp_by_dist, res_by_dist, total, n_unmapped):
    known = dist_counts.drop(UNMAPPED, errors="ignore")
    if len(known) < 2:
        return None
    a, va = known.index[0], int(known.iloc[0])
    if va == int(known.iloc[1]):
        return None
    s = f"מחוז {a} מוביל במספר המסגרות: {n(va)} ({pct(va / total * 100)})"
    none = [d for d in known.index if inp_by_dist.get(d, 0) == 0]
    if none and len(none) < len(known):
        if len(none) == 1:
            d = none[0]
            what = ("אף אשפוזית לגמילה ואף מסגרת שהייה אחרת" if res_by_dist.get(d, 0) == 0
                    else "אף אשפוזית לגמילה רפואית")
            s += f". במחוז {d} אין {what}, אף שרשומות בו {facilities_word(int(known[d]))}"
        else:
            s += f". במחוזות {list_he(none)} אין אף אשפוזית לגמילה רפואית"
    if n_unmapped:
        s += f" ({facilities_word(n_unmapped)} ביישוב שלא שויך למחוז)"
    return s + "."


def insight_cities(city_counts, total):
    if len(city_counts) < 5:
        return None
    a, va = city_counts.index[0], int(city_counts.iloc[0])
    ties = [c for c, v in city_counts.items() if int(v) == va]
    single = int((city_counts == 1).sum())
    if len(ties) == 1:
        lead = f"{a} בראש עם {facilities_word(va)}"
    else:
        lead = f"{list_he(ties)} בראש עם {facilities_word(va)} כל אחד"
    return (f"המסגרות פרוסות ב-{n(len(city_counts))} יישובים; {lead}. "
            f"ב-{n(single)} יישובים ({pct(single / len(city_counts) * 100, 0)} מהיישובים) "
            f"יש מסגרת אחת בלבד.")


def insight_focus(focus_counts, total):
    have = {k: v for k, v in focus_counts.items() if v > 0}
    if not have:
        return None
    parts = []
    for key, lab in (("women", "לנשים"), ("youth", "לנוער ולצעירים")):
        v = focus_counts.get(key, 0)
        if v:
            parts.append(f"{facilities_word(v)} {lab}")
    if not parts:
        return None
    dual = focus_counts.get("dual", 0)
    small = sum(focus_counts.get(k, 0) for k in ("women", "youth")) < 0.1 * total
    s = "לפי שמות המסגרות, " + ("רק " if small else "") + list_he(parts) + f" מתוך {n(total)}"
    if dual:
        s += f"; {facilities_word(dual)} מציינות טיפול בתחלואה כפולה או משולשת"
    return s + "."


def insight_managers(mgr_counts, total):
    if mgr_counts.empty:
        return None
    multi = mgr_counts[mgr_counts >= 2]
    if multi.empty:
        return None
    a, va = multi.index[0], int(multi.iloc[0])
    ties = [m for m, v in multi.items() if int(v) == va]
    covered = int(multi.sum())
    s = (f"{n(total)} המסגרות מנוהלות בידי {n(len(mgr_counts))} מנהלים; {n(len(multi))} מהם רשומים "
         f"כמנהלים של יותר ממסגרת אחת (יחד {n(covered)} מסגרות)")
    if len(ties) == 1:
        s += f". {a} רשום כמנהל של {facilities_word(va)}"
    return s + "."


def insight_phone(bad, total):
    if bad == 0:
        return None
    if bad == 1:
        return "למסגרת אחת במאגר לא רשום מספר טלפון ראשי תקין (השדה ריק או קצר ממספר טלפון מלא)."
    w = f"ל{COUNT_WORDS[bad]}" if bad in COUNT_WORDS else f"ל-{n(bad)}"
    return (f"{w} מסגרות במאגר ({pct(bad / total * 100)}) לא רשום מספר טלפון ראשי תקין "
            f"(השדה ריק או קצר ממספר טלפון מלא).")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["main"]
    total = len(raw)

    tcode = raw["institute_type_code"].map(norm)
    tname = raw["institute_type_name"].map(norm)
    df = pd.DataFrame({
        "code": raw["institute_code"].map(norm).values,
        "name": raw["institute_name"].map(norm).values,
        "city": raw["city"].map(norm).replace("", "לא צוין").values,
        "city_code": raw["cityCode"].map(norm).str.replace(r"\.0$", "", regex=True).values,
        "type": tcode.where(tcode != "", tname).values,
        "type_raw": tname.values,
        "owner": raw["ownershipDesc"].map(norm).replace("", UNKNOWN_OWNER).values,
        "manager": raw["manager"].map(norm).values,
        "phone": raw["phone"].map(norm).values,
        "phone2": raw["phone2"].map(norm).values,
        "fax": raw["fax"].map(norm).values,
        "email": raw["email"].map(norm).values,
        "street": raw["street"].map(norm).values,
        "bnum": raw["Building_num"].map(norm).values,
        "zip": raw["Zip_code"].map(norm).values,
    })
    df["district"] = df["city_code"].map(lambda c: CITY_DISTRICT.get(c, UNMAPPED))
    df["kupa"] = df["owner"].map(lambda o: bool(KUPA_RE.search(o)))

    # ---- types (known codes in fixed order, unknown after by count)
    raw_name_of = {}
    for c, nm in sorted(zip(df["type"], df["type_raw"])):
        raw_name_of.setdefault(c, nm or c)
    present = list(ranked(df["type"].value_counts()).index)
    types = [t for t in TYPE_ORDER if t in present] + [t for t in present if t not in TYPE_ORDER]
    labels_pl = {t: TYPE_INFO[t][0] if t in TYPE_INFO else raw_name_of.get(t, t) for t in types}
    labels_sg = {t: TYPE_INFO[t][1] if t in TYPE_INFO else raw_name_of.get(t, t) for t in types}
    type_counts = ranked(df["type"].value_counts())
    n_inp = int(type_counts.get(INPATIENT, 0))
    n_res = int(df["type"].isin(RESIDENTIAL).sum())

    # ---- ownership × type
    owner_counts = ranked(df["owner"].value_counts())
    owners = list(owner_counts.index)
    ot = df.groupby(["owner", "type"]).size()
    n_kupa = int(df["kupa"].sum())

    # ---- districts
    dist_counts_raw = df["district"].value_counts()
    districts = [d for d in DISTRICT_ORDER if d in dist_counts_raw.index]
    n_unmapped = int(dist_counts_raw.get(UNMAPPED, 0))
    districts_all = districts + ([UNMAPPED] if n_unmapped else [])
    dist_counts = ranked(dist_counts_raw)
    dt = df.groupby(["district", "type"]).size()
    inp_by_dist = {d: int(dt.get((d, INPATIENT), 0)) for d in districts_all}
    res_by_dist = {d: int(sum(dt.get((d, t), 0) for t in RESIDENTIAL)) for d in districts_all}
    no_inp = [d for d in districts if inp_by_dist.get(d, 0) == 0]

    # ---- cities
    city_counts = ranked(df["city"].value_counts())
    top_c = list(city_counts.index[:TOP_CITIES])
    other_c = int(city_counts.iloc[TOP_CITIES:].sum()) if len(city_counts) > TOP_CITIES else 0
    n_other_c = max(len(city_counts) - TOP_CITIES, 0)
    ct = df.groupby(["city", "type"]).size()

    # ---- focus
    focus_counts = {k: int(df["name"].str.contains(rx).sum()) for k, _, rx in FOCUS}
    focus_rows = [(k, lab, focus_counts[k]) for k, lab, _ in FOCUS]
    focus_rows = sorted(focus_rows, key=lambda r: (-r[2], [f[0] for f in FOCUS].index(r[0])))
    focus_rows = [r for r in focus_rows if r[2] > 0]
    any_focus = int(pd.concat([df["name"].str.contains(rx) for _, _, rx in FOCUS], axis=1).any(axis=1).sum())

    # ---- managers
    mgr = df[df["manager"] != ""]
    mgr_counts = ranked(mgr["manager"].value_counts())
    multi = mgr_counts[mgr_counts >= 2]
    top_m = multi.head(TOP_MANAGERS)
    mt = mgr.groupby(["manager", "type"]).size()

    # ---- contact completeness
    has = {
        "phone": df["phone"].map(phone_ok),
        "phone2": df["phone2"].map(phone_ok),
        "email": df["email"].str.contains("@", regex=False),
        "street": (df["street"] != "") & (df["bnum"] != ""),
        "zip": df["zip"].str.replace(r"\D", "", regex=True).str.len() >= 5,
        "fax": df["fax"].map(phone_ok),
    }
    contact = [{"key": k, "name": lab, "k": int(has[k].sum()),
                "share": round(float(has[k].mean()) * 100, 1) if total else 0.0} for k, lab in CONTACT]
    bad_phone = total - int(has["phone"].sum())

    # ---- residential directory (type 15 + 16), by district then city then name
    res = df[df["type"].isin(RESIDENTIAL)].copy()
    dorder = {d: i for i, d in enumerate(districts_all)}
    torder = {t: i for i, t in enumerate(types)}
    res["_d"] = res["district"].map(dorder)
    res["_t"] = res["type"].map(torder)
    res = res.sort_values(["_t", "_d", "city", "name", "code"], kind="stable")
    res_rows = [{"name": r["name"], "city": r["city"], "district": r["district"],
                 "type": labels_sg[r["type"]], "owner": r["owner"]}
                for _, r in res.head(MAX_RES_ROWS).iterrows()]
    res_more = max(len(res) - MAX_RES_ROWS, 0)

    # ---------------------------------------------------------------- charts
    type_colors = ["#0b3668", "#5b8fd6", "#0068f5", "#9fb7d9", "#c3cfe7"]
    charts = {
        "types": {"items": [{"name": labels_pl[t], "value": int(type_counts.get(t, 0))} for t in types]},
        "owners": {"names": owners,
                   "series": [{"name": labels_pl[t], "data": [int(ot.get((o, t), 0)) for o in owners]}
                              for t in types]},
        "districts": {"names": districts_all,
                      "series": [{"name": labels_pl[t], "data": [int(dt.get((d, t), 0)) for d in districts_all]}
                                 for t in types]},
        "cities": {"names": top_c,
                   "series": [{"name": labels_pl[t], "data": [int(ct.get((c, t), 0)) for c in top_c]}
                              for t in types]},
        "focus": {"names": [r[1] for r in focus_rows], "values": [r[2] for r in focus_rows]},
        "managers": {"names": list(top_m.index),
                     "series": [{"name": labels_pl[t], "data": [int(mt.get((m, t), 0)) for m in top_m.index]}
                                for t in types]},
        "contact": {"names": [c["name"] for c in contact], "values": [c["share"] for c in contact]},
        "colors": type_colors[:len(types)],
    }

    # ---------------------------------------------------------------- insights
    rules = [
        ("types", insight_types(type_counts, labels_pl, total)),
        ("kupot", insight_kupot(df)),
        ("residential_owner", insight_residential_owner(df)),
        ("district", insight_district(dist_counts, inp_by_dist, res_by_dist, total, n_unmapped)),
        ("cities", insight_cities(city_counts, total)),
        ("focus", insight_focus(focus_counts, total)),
        ("managers", insight_managers(mgr_counts, total)),
        ("phone", insight_phone(bad_phone, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------------------------------------------------------- KPIs
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "inpatient": {"value": n_inp, "display": n(n_inp), "tone": "info"},
        "cities": {"value": int(len(city_counts)), "display": n(len(city_counts)), "tone": "brand"},
        "no_inp": {"value": len(no_inp), "display": n(len(no_inp)),
                   "tone": "warn" if no_inp else "ok"},
    }

    lead_owner = owners[0] if owners else ""
    type_txt = list_he([f"{n(type_counts.get(t, 0))} {labels_pl[t]}" for t in types])
    lead_dist = dist_counts.drop(UNMAPPED, errors="ignore")
    lead_d = lead_dist.index[0] if len(lead_dist) else ""
    lead_city = city_counts.index[0] if len(city_counts) else ""
    focus_lead = focus_rows[0] if focus_rows else None
    contact_low = sorted(contact, key=lambda c: (c["share"], c["key"]))[0]
    labels = {
        "lede": (f"מאגר משרד הבריאות של מסגרות הטיפול בהתמכרויות לסמים ולאלכוהול: {n(total)} מסגרות "
                 f"ב-{n(len(city_counts))} יישובים. לצד האשפוזיות לגמילה גופנית הוא כולל גם מרכזי גמילה "
                 f"ומרפאות לטיפול בהתמכרויות: {type_txt}. סוג הבעלות הנפוץ: {lead_owner} "
                 f"({facilities_word(int(owner_counts.iloc[0]) if len(owner_counts) else 0)}). "
                 f"מספרי טלפון וכתובות מלאות מופיעים בטבלת הנתונים שבתחתית העמוד."),
        "lookup_title": "איתור אשפוזית או מרפאת גמילה לפי יישוב או שם ←",
        "lookup_sub": "חיפוש חי בכל רשומות המאגר: שם המסגרת, יישוב, כתובת, טלפון, דוא״ל ומנהל",
        "total_kpi": "מסגרות טיפול וגמילה במאגר",
        "inp_kpi": f"אשפוזיות לגמילה רפואית ({pct(n_inp / total * 100 if total else 0)} מהמסגרות)",
        "cities_kpi": f"יישובים עם מסגרת אחת לפחות (ב-{n(len(districts))} מחוזות)",
        "no_inp_kpi": ("מחוזות ללא אשפוזית לגמילה רפואית" + (f" ({list_he(no_inp)})" if no_inp else "")),
        "types_note": (f"{n(len(types))} סוגי מסגרות: " + "; ".join(TYPE_DESC.get(t, labels_sg[t]) for t in types)
                       + (f". {labels_pl[type_counts.index[0]]} הן הרוב: {n(type_counts.iloc[0])} מסגרות."
                          if int(type_counts.iloc[0]) * 2 > total else ".")),
        "types_aria": (f"תרשים טבעת: מסגרות לפי סוג; {labels_pl[type_counts.index[0]]} "
                       f"{n(type_counts.iloc[0])}, אשפוזיות לגמילה {n(n_inp)}."),
        "types_caption": "מסגרות לפי סוג.",
        "owners_note": (f"סוג הבעלות על כל מסגרת, בחלוקה לסוג המסגרת. קופות החולים מפעילות {facilities_word(n_kupa)}."),
        "owners_aria": (f"גרף עמודות מוערמות אופקי: מסגרות לפי בעלות וסוג; {lead_owner} בראש עם "
                        f"{n(owner_counts.iloc[0]) if len(owner_counts) else 0}."),
        "owners_caption": "מסגרות לפי סוג בעלות וסוג מסגרת.",
        "districts_note": ("מספר המסגרות בכל מחוז לפי סוג. המחוז נגזר מקוד היישוב."
                           + (f" {facilities_word(n_unmapped)} ביישוב שעדיין לא שויך למחוז מוצגות בנפרד."
                              if n_unmapped else "")),
        "districts_aria": f"גרף עמודות מוערמות אופקי: מסגרות לפי מחוז וסוג; מחוז {lead_d} בראש.",
        "districts_caption": "מסגרות לפי מחוז וסוג.",
        "cities_note": (f"היישובים עם מספר המסגרות הגדול ביותר, בחלוקה לסוג."
                        + (f" {n(n_other_c)} יישובים נוספים ({facilities_word(other_c)}) מופיעים בשורה האחרונה בטבלה."
                           if other_c else "")),
        "cities_aria": (f"גרף עמודות מוערמות אופקי: יישובים לפי מספר מסגרות; {lead_city} בראש עם "
                        f"{n(city_counts.iloc[0]) if len(city_counts) else 0}."),
        "cities_caption": "מסגרות לפי יישוב וסוג.",
        "focus_note": (f"מסגרות שבשמן מופיעה אוכלוסייה או תחום טיפול מסוים. הסיווג נקרא מהשם בלבד: מסגרת "
                       f"יכולה להופיע בכמה קטגוריות, ו-{n(total - any_focus)} מסגרות אינן מציינות תחום בשמן."),
        "focus_aria": (f"תרשים עמודות אופקי: מסגרות לפי תחום הטיפול שבשמן; {focus_lead[1]} בראש עם {n(focus_lead[2])}."
                       if focus_lead else "תרשים עמודות אופקי: מסגרות לפי תחום הטיפול שבשמן."),
        "focus_caption": "מסגרות לפי תחום הטיפול המופיע בשמן.",
        "managers_note": (f"מנהלים הרשומים כמנהלים של יותר ממסגרת אחת, בחלוקה לסוג המסגרת "
                          f"({n(len(multi))} מנהלים כאלה מתוך {n(len(mgr_counts))})."),
        "managers_aria": (f"גרף עמודות מוערמות אופקי: מנהלים לפי מספר המסגרות שבניהולם; {top_m.index[0]} בראש עם "
                          f"{n(top_m.iloc[0])}." if len(top_m) else "גרף עמודות: מנהלים של כמה מסגרות."),
        "managers_caption": "מנהלים של יותר ממסגרת אחת.",
        "contact_note": (f"איזה חלק מהמסגרות כולל כל פרט קשר במאגר. הפרט החסר ביותר: {contact_low['name']} "
                         f"({contact_low['share']:.1f}%). הפרטים עצמם מופיעים בטבלת הנתונים שבתחתית העמוד."),
        "contact_aria": (f"תרשים עמודות אופקי: שיעור המסגרות עם כל פרט קשר; {contact_low['name']} הנמוך ביותר, "
                         f"{contact_low['share']:.1f}%."),
        "contact_caption": "שיעור המסגרות עם כל פרט קשר.",
        "res_note": (f"{n(len(res))} מסגרות השהייה במאגר (אשפוזיות לגמילה ומסגרות משולבות), לפי סוג, מחוז ויישוב."
                     + (f" מוצגות {n(MAX_RES_ROWS)} הראשונות; השאר בטבלת הנתונים שבתחתית העמוד." if res_more else "")),
    }

    tables = {
        "types": [{"name": labels_sg[t], "count": n(type_counts.get(t, 0)),
                   "share": f"{type_counts.get(t, 0) / total * 100:.1f}%" if total else "0.0%"} for t in types],
        "type_cols": [labels_pl[t] for t in types],
        "owners": [{"name": o, "vals": [n(ot.get((o, t), 0)) for t in types], "total": n(owner_counts[o])}
                   for o in owners],
        "districts": [{"name": d, "vals": [n(dt.get((d, t), 0)) for t in types],
                       "total": n(dist_counts_raw[d])} for d in districts_all],
        "cities": ([{"name": c, "vals": [n(ct.get((c, t), 0)) for t in types], "total": n(city_counts[c])}
                    for c in top_c]
                   + ([{"name": f"{OTHER_CITIES} ({n(n_other_c)})",
                        "vals": [n(sum(int(ct.get((c, t), 0)) for c in city_counts.index[TOP_CITIES:]))
                                 for t in types], "total": n(other_c)}] if other_c else [])),
        "focus": [{"name": r[1], "count": n(r[2])} for r in focus_rows],
        "managers": [{"name": m, "vals": [n(mt.get((m, t), 0)) for t in types], "total": n(v)}
                     for m, v in top_m.items()],
        "contact": [{"name": c["name"], "k": n(c["k"]), "share": f"{c['share']:.1f}%"} for c in contact],
        "residential": res_rows,
    }

    return {
        "agent_data": {
            "summary_he": (f"איתור אשפוזית לגמילה או מרפאה לטיפול בהתמכרויות לפי יישוב ושם: {n(total)} מסגרות "
                           f"ב-{n(len(city_counts))} יישובים, מהן {n(n_inp)} אשפוזיות לגמילה רפואית."),
            "dataset_kind": "registry",
            "related_ids": ["b08ed183-2c26-490f-aa13-f1a7529c3aca",
                            "5c8651bc-5288-4d46-a3f5-2ebfbe5c9615",
                            "b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65"],
            "suggested_tags": ["גמילה מסמים", "גמילה מאלכוהול", "טיפול בהתמכרויות", "אשפוזיות",
                               "מרפאות", "משרד הבריאות"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_focus": bool(focus_rows), "has_managers": bool(len(top_m)),
                  "has_res": bool(res_rows)},
    }
