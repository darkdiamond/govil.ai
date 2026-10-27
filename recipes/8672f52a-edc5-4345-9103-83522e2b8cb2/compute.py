"""מלווי עולים (פרוייקטורים) ברשויות המקומיות — registry of immigrant-absorption
escorts: locality / regional council, ministry service area, languages, and
which contact channels exist.

Only aggregates reach the page: no individual is named and no phone number or
e-mail address is shown (presence and e-mail domain type only). One row is one
projector. Languages are a comma-separated list per row and are exploded.
"""
import re

import pandas as pd

UNKNOWN = "לא צוין"
TOP_PLACES = 14
TOP_AREAS = 12
TOP_LANGS = 12
TOP_COMBOS = 10
HEAT_AREAS = 10
HEAT_LANGS = 6
PERSONAL_DOMAINS = {"gmail.com", "walla.co.il", "walla.com", "hotmail.com",
                    "yahoo.com", "outlook.com", "icloud.com", "012.net.il"}
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _clean(s):
    return re.sub(r"\s+", " ", s.strip())


def _area(s):
    s = _clean(s)
    s = re.sub(r"\s*\((מרחב|סניף)\)\s*$", "", s)
    return s or UNKNOWN


def _langs(s):
    parts = [_clean(p) for p in re.split(r"[,،;/]", s)]
    return sorted({p for p in parts if p})


def _digits(s):
    return bool(re.search(r"\d", s))


def _counts(series):
    vc = series.value_counts()
    return sorted(vc.items(), key=lambda kv: (-int(kv[1]), kv[0]))


def _top_other(items, k, other="אחר"):
    head = items[:k]
    rest = sum(int(c) for _, c in items[k:])
    if rest:
        head = head + [(other, rest)]
    return head


def _bar(items):
    return {"x": [str(k) for k, _ in items], "y": [int(c) for _, c in items]}


def _rows(items, total):
    return [{"name": str(k), "count": n(c), "share": pct(int(c) / total * 100)}
            for k, c in items]


def compute(frames):
    df = frames["olim"]
    total = len(df)
    p = pd.DataFrame({
        "city": df["city"].map(_clean),
        "council": df["reginal_council"].map(_clean),
        "area": df["office_point_of_service"].map(_area),
        "langs": df["language"].map(_langs),
        "office": df["office_phone"].map(_digits),
        "mobile": df["mobile"].map(_digits),
        "email_dom": (df["email"].where(df["email"].str.contains("@"), df["additional_email"])
                      .str.extract(r"@([^\s>;,]+)")[0].str.lower()),
    })
    p["place"] = p["city"].where(p["city"] != "", p["council"])
    p["is_council"] = (p["city"] == "") & (p["council"] != "")
    p["place"] = p["place"].replace("", UNKNOWN)
    p["has_email"] = p["email_dom"].notna()

    # ---- places
    place_known = p[p["place"] != UNKNOWN]
    place_items = _counts(place_known["place"])
    n_places = len(place_items)
    places_top = place_items[:TOP_PLACES]
    places_rest = len(place_known) - sum(int(v) for _, v in places_top)

    # ---- areas
    area_known = p[p["area"] != UNKNOWN]
    area_items = _counts(area_known["area"])
    n_areas = len(area_items)
    areas_top = _top_other(area_items, TOP_AREAS)

    # ---- languages
    lang_rows = p[p["langs"].map(len) > 0]
    exploded = lang_rows["langs"].explode()
    lang_items = _counts(exploded)
    n_langs = len(lang_items)
    langs_top = _top_other(lang_items, TOP_LANGS)
    lang_total = len(lang_rows)
    combos = _counts(lang_rows["langs"].map(lambda l: " + ".join(l)))
    combos_top = _top_other(combos, TOP_COMBOS)
    multi = int((lang_rows["langs"].map(len) > 1).sum())
    nlang_items = _counts(lang_rows["langs"].map(len).map(str))
    nlang_items = sorted(nlang_items, key=lambda kv: int(kv[0]))

    # ---- heatmap: top areas x top languages
    h_areas = [a for a, _ in area_items[:HEAT_AREAS]]
    h_langs = [l for l, _ in lang_items[:HEAT_LANGS]]
    heat = []
    for ai, a in enumerate(h_areas):
        sub = area_known[area_known["area"] == a]["langs"]
        cnt = {}
        for ls in sub:
            for l in ls:
                cnt[l] = cnt.get(l, 0) + 1
        for li, l in enumerate(h_langs):
            heat.append([li, ai, cnt.get(l, 0)])
    heat_max = max([c for _, _, c in heat] or [1])

    # ---- contact channels
    chan = [("טלפון משרדי", int(p["office"].sum())),
            ("טלפון נייד", int(p["mobile"].sum())),
            ("דואר אלקטרוני", int(p["has_email"].sum()))]
    n_all3 = int((p["office"] & p["mobile"] & p["has_email"]).sum())
    email_rows = p[p["has_email"]]
    personal = int(email_rows["email_dom"].isin(PERSONAL_DOMAINS).sum())

    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "places": {"value": n_places, "display": n(n_places), "tone": "brand"},
        "areas": {"value": n_areas, "display": n(n_areas), "tone": "brand"},
        "langs": {"value": n_langs, "display": n(n_langs), "tone": "brand"},
    }

    # ---- insights
    insights = []
    if lang_items and lang_total:
        top_l, top_c = lang_items[0]
        share = top_c / lang_total * 100
        if share >= 25:
            second = lang_items[1] if len(lang_items) > 1 else None
            tail = f", ואחריה {second[0]} ({n(second[1])})" if second else ""
            insights.append({"id": "lang_leader", "text_he": (
                f"{top_l} היא שפת השירות הנפוצה ביותר: {n(top_c)} מתוך {n(lang_total)} "
                f"מלווים ({pct(share)}) משרתים בה{tail}.")})
    if lang_total and multi:
        insights.append({"id": "multi", "text_he": (
            f"{n(multi)} מלווים ({pct(multi / lang_total * 100)}) משרתים ביותר משפה אחת; "
            f"ברשימה {n(n_langs)} שפות שונות.")})
    if n_areas >= 3 and len(area_known):
        a3 = area_items[:3]
        s3 = sum(c for _, c in a3) / len(area_known) * 100
        names = ", ".join(a for a, _ in a3)
        insights.append({"id": "areas", "text_he": (
            f"שלושת המרחבים הגדולים ({names}) מרכזים {pct(s3)} מהמלווים ששויכו למרחב "
            f"({n(len(area_known))} מתוך {n(total)}).")})
    if n_places >= 3:
        multi_places = [(k, c) for k, c in place_items if c >= 2]
        k0, c0 = place_items[0]
        if multi_places and c0 >= 3:
            insights.append({"id": "cities", "text_he": (
                f"{k0} מובילה עם {n(c0)} מלווים; ב-{n(len(multi_places))} מתוך "
                f"{n(n_places)} יישובים ורשויות פועלים שני מלווים או יותר.")})
    n_council = int(p["is_council"].sum())
    if n_council and n_council / total >= 0.04:
        insights.append({"id": "council", "text_he": (
            f"{n(n_council)} מלווים ({pct(n_council / total * 100)}) משויכים למועצה אזורית "
            f"ולא לעיר: {n(p.loc[p['is_council'], 'place'].nunique())} מועצות שונות.")})
    if len(email_rows) >= 10 and personal / len(email_rows) >= 0.1:
        insights.append({"id": "email_domain", "text_he": (
            f"מתוך {n(len(email_rows))} כתובות הדואר האלקטרוני ברשימה, {n(personal)} "
            f"({pct(personal / len(email_rows) * 100)}) הן בדומיין של שירות דואר פרטי ולא של רשות.")})
    if total:
        lowest = min(chan, key=lambda kv: (kv[1], kv[0]))
        if lowest[1] < total:
            insights.append({"id": "contact", "text_he": (
                f"ערוץ הקשר הפחות מלא הוא {lowest[0]}: {n(lowest[1])} מתוך {n(total)} "
                f"מלווים ({pct(lowest[1] / total * 100)}); {n(n_all3)} רשומים עם שלושת הערוצים.")})

    top_lang_name = lang_items[0][0] if lang_items else ""
    labels = {
        "lede": (f"{n(total)} מלווי עולים (פרוייקטורים) ב-{n(n_places)} יישובים ורשויות, "
                 f"ב-{n(n_areas)} מרחבי שירות, בשפות: {n(n_langs)}. "
                 f"הדף מציג התפלגויות בלבד; פרטי הקשר של כל מלווה נמצאים בטבלת הנתונים שמתחת."),
        "total_kpi": "מלווי עולים ברשימה",
        "places_kpi": "יישובים ורשויות",
        "areas_kpi": "מרחבי שירות",
        "langs_kpi": "שפות שירות",
        "langs_note": f"כמה מלווים משרתים בכל שפה. מלווה דובר כמה שפות נספר בכל אחת מהן; {n(lang_total)} מלווים עם שפה רשומה.",
        "langs_aria": "תרשים עמודות: מספר מלווים לפי שפה",
        "langs_caption": "מלווים לפי שפת שירות",
        "combos_note": "צירופי השפות כפי שהם רשומים, ללא פיצול.",
        "combos_aria": "תרשים עמודות אופקיות: מלווים לפי צירוף שפות",
        "combos_caption": "מלווים לפי צירוף שפות",
        "areas_note": f"שיוך המלווים למרחבי השירות של משרד העלייה והקליטה: {n(len(area_known))} מלווים ששויכו, ב-{n(n_areas)} מרחבים.",
        "areas_aria": "תרשים עמודות אופקיות: מלווים לפי מרחב שירות",
        "areas_caption": "מלווים לפי מרחב שירות",
        "places_note": f"{n(len(places_top))} היישובים והרשויות עם הכי הרבה מלווים; הנותרים ({n(places_rest)} מלווים מתוך {n(len(place_known))} עם יישוב או מועצה) לא מוצגים.",
        "places_aria": "תרשים עמודות אופקיות: מלווים לפי יישוב או רשות",
        "places_caption": "מלווים לפי יישוב או רשות",
        "heat_note": f"אילו שפות מכוסות בכל מרחב: {n(len(h_areas))} המרחבים הגדולים מול {n(len(h_langs))} השפות הנפוצות.",
        "heat_aria": "מפת חום: מלווים לפי מרחב שירות ושפה",
        "contact_note": f"כמה מלווים רשומים עם כל ערוץ קשר, מתוך {n(total)}. מוצגת נוכחות הערוץ בלבד.",
        "contact_aria": "תרשים עמודות: מלווים לפי ערוץ קשר זמין",
        "contact_caption": "מלווים לפי ערוץ קשר רשום",
    }
    tables = {
        "langs": _rows(langs_top, lang_total or 1),
        "combos": _rows(combos_top, lang_total or 1),
        "areas": _rows(areas_top, len(area_known) or 1),
        "places": _rows(places_top, len(place_known) or 1),
        "contact": [{"name": k, "count": n(c), "share": pct(c / total * 100 if total else 0)}
                    for k, c in chan],
    }
    charts = {
        "langs": _bar(langs_top),
        "combos": _bar(combos_top),
        "areas": _bar(areas_top),
        "places": _bar(places_top),
        "contact": {"x": [k for k, _ in chan], "y": [c for _, c in chan], "total": total},
        "heat": {"x": h_langs, "y": h_areas, "data": heat, "max": heat_max},
    }
    summary = (f"רשימה של {n(total)} מלווי עולים (פרוייקטורים) ב-{n(n_places)} יישובים ורשויות, "
               f"לפי מרחב שירות ושפה; השפה הנפוצה ביותר היא {top_lang_name}.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["עולים חדשים", "קליטת עלייה", "רשויות מקומיות", "שפות", "שירות לציבור"],
            "related_ids": ["7ac97f91-54c7-48dc-ac61-2fdb687cd371"],
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": tables,
    }
