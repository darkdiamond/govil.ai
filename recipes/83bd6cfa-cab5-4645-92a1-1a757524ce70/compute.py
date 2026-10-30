"""ספריית מילוני נתונים: טרמינולוגיית נתוני עסק (מערך הדיגיטל הלאומי).

The library is one "central record" (the fields a business record carries,
grouped by category, some linked to a code list) plus ~23 code lists
(dictionaries). Every number on the page is computed here from the files;
insight rules return a sentence or None when their premise does not hold.
"""
import re

import pandas as pd

# input name -> (Hebrew label, code col, Hebrew name col, English col, description col)
# English/description may be None when the file has no such column.
DICTS = [
    ("localities", "יישובים בישראל", "Code", "Name_Hebrew", None, None),
    ("streets", "רחובות", "Code", "Name_Hebrew", "Name_English", "Decription_Hebrew"),
    ("branches", "ענפים כלכליים", "Code", "Name_Hebrew", None, None),
    ("countries", "ארצות", "קוד לפי תקן ישראלי", "שם בעברית", "שם באנגלית", "הערות"),
    ("authorities", "רשויות מקומיות", "Code", "Name_Hebrew", None, "Description_Hebrew"),
    ("legal_status_detailed", "סטטוס משפטי מפורט", "Code", "Name_Hebrew", "Name_Enflish", "Description_Hebrew"),
    ("org_subdomains", "תתי תחומי פעילות ארגונים", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("sectors", "סקטורים מוסדיים", "Code", "Name_Hebrew", None, None),
    ("taxpayer_activity", "אופי פעילות נישום", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("audiences", "קהלי יעד", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("legal_entities", "סוגי ישויות משפטיות", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("org_domains", "תחומי פעילות ארגונים", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("legal_substatus", "תת סטטוס משפטי", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("legal_status", "סטטוסים משפטיים", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("ownership", "סוגי בעלות", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("activity_mode", "אופי פעילות עסק", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("activity_regions", "אזורי פעילות ארגוניים", "Code", "Name_HE", "Name_EN", "Description_HE"),
    ("business_types", "סוגי עסקים", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("tax_status", "סטטוסי מס", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("site_kind", "אופי אתרי פעילות", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("districts", "מחוזות בישראל", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("size_turnover", "גודל עסק לפי מחזור שנתי", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
    ("size_employees", "גודל עסק לפי מועסקים בשכר", "Code", "Name_Hebrew", "Name_English", "Description_Hebrew"),
]
BROWSER_MAX = 30          # dictionaries this small are listed in full on the page
TOP_STREETS = 15
TOP_COUNCILS = 12
TOP_SPLITS = 10
STREET_LOCALITY_CODE = "9000"   # CBS street code for "the locality itself" (no street)

# Israeli economic-branch classification (2011): 2-digit division -> section.
# Israel-specific divisions: 04 animal husbandry, 34 diamonds, 83 local administration.
# Fixed code mapping (with an "אחר" fallback for unknown divisions).
ISIC_SECTIONS = [
    (1, 4, "חקלאות, ייעור ודיג"), (5, 9, "כרייה וחציבה"), (10, 34, "תעשייה"),
    (35, 35, "חשמל, גז וקיטור"), (36, 39, "מים, ביוב ופסולת"), (41, 43, "בינוי"),
    (45, 47, "מסחר סיטוני וקמעוני"), (49, 53, "תחבורה, אחסנה ודואר"),
    (55, 56, "אירוח ושירותי אוכל"), (58, 63, "מידע ותקשורת"), (64, 66, "פיננסים וביטוח"),
    (68, 68, "נדל״ן"), (69, 75, "שירותים מקצועיים, מדעיים וטכניים"),
    (77, 82, "שירותי ניהול ותמיכה"), (83, 84, "מינהל ציבורי"), (85, 85, "חינוך"),
    (86, 88, "בריאות ורווחה"), (90, 93, "אמנות, בידור ופנאי"), (94, 96, "שירותים אחרים"),
    (97, 98, "משקי בית כמעסיקים"), (99, 99, "גופים חוץ-מדינתיים"),
]
# Institutional sectors (SNA): first two digits of the 6-digit code.
SNA_SECTORS = {
    "11": "תאגידים לא פיננסיים", "12": "תאגידים פיננסיים", "13": "ממשלה כללית",
    "14": "משקי בית", "15": "מלכ״רים המשרתים משקי בית", "99": "גופים חוץ-מדינתיים",
}
SETTLEMENT_GROUPS = [
    ("קיבוצים", "קיבוצים"), ("מושבים שיתופיים", "מושבים שיתופיים"), ("מושבים", "מושבים"),
    ("קהילתיים", "יישובים קהילתיים"), ("מוסדיים", "יישובים מוסדיים"),
    ("לא יהודיים", "יישובים לא יהודיים"), ("יהודיים", "יישובים יהודיים"),
    ("מוקד תעסוקה", "מוקדי תעסוקה"),
]
INDEPENDENT = {"עירייה", "מועצה מקומית"}
CODE_RE = re.compile(r"^-?\d+$")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _clean(s):
    return s.astype(str).str.replace(" ", " ").str.strip()


def _rank(series):
    """Counts sorted desc, ties broken by name (total order)."""
    s = series.sort_index()
    return s.sort_values(ascending=False, kind="stable")


def _dict_rows(df, code, he):
    """Rows that are real dictionary values: a numeric code and a Hebrew name
    (drops blank padding rows and repeated header rows)."""
    c = _clean(df[code])
    h = _clean(df[he])
    return df[c.str.match(CODE_RE) & (h != "")]


def _settlement_group(form):
    for needle, group in SETTLEMENT_GROUPS:
        if needle in form:
            return group
    return "אחר"


def _isic_section(code):
    c = code.lstrip("-")
    if not c.isdigit() or len(c) > 4:
        return "אחר"
    div = int(c.zfill(4)[:2])
    for lo, hi, name in ISIC_SECTIONS:
        if lo <= div <= hi:
            return name
    return "אחר"


# ---------------------------------------------------------------- insights
def insight_record(rec_total, linked, by_cat_linked):
    if rec_total == 0 or linked == 0:
        return None
    best = None
    for cat, (n, k) in by_cat_linked.items():
        if n >= 5 and (best is None or k / n > best[2] or (k / n == best[2] and n > best[1])):
            best = (cat, n, k / n, k)
    text = (f"{_int(linked)} מתוך {_int(rec_total)} השדות ברשומה המרכזית ({_pct(linked / rec_total)}) "
            "מקושרים למילון ערכים, והשאר שדות חופשיים.")
    if best and best[2] >= 0.5:
        text += f" בקטגוריה \"{best[0]}\" {_int(best[3])} מתוך {_int(best[1])} השדות מקושרים למילון."
    return text


def insight_concentration(sizes):
    total = sum(v for _, v in sizes)
    if total == 0 or len(sizes) < 3:
        return None
    name, top = sizes[0]
    share = top / total
    if share < 0.5:
        return None
    small = sum(1 for _, v in sizes if v <= BROWSER_MAX)
    return (f"המילון \"{name}\" לבדו מחזיק {_int(top)} ערכים, {_pct(share)} מכל {_int(total)} הערכים בספרייה. "
            f"{_int(small)} מתוך {_int(len(sizes))} המילונים קצרים, עם {_int(BROWSER_MAX)} ערכים לכל היותר.")


def insight_bilingual(quality):
    no_en = [q["name"] for q in quality if q["en_share"] is None or q["en_share"] < 0.5]
    if not no_en:
        return None
    names = ", ".join(no_en[:5]) + (" ועוד" if len(no_en) > 5 else "")
    return (f"ב-{_int(len(no_en))} מתוך {_int(len(quality))} המילונים אין שם באנגלית לרוב הערכים "
            f"או שאין להם עמודת שם באנגלית כלל: {names}.")


def insight_localities(n_loc, by_district, regional_share, n_councils):
    if n_loc == 0 or by_district.empty:
        return None
    d, v = by_district.index[0], int(by_district.iloc[0])
    if v / n_loc < 0.2:
        return None
    return (f"מילון היישובים מונה {_int(n_loc)} יישובים. מחוז {d} מוביל עם {_int(v)} ({_pct(v / n_loc)}), "
            f"ו-{_pct(regional_share)} מהיישובים שייכים לאחת מ-{_int(n_councils)} מועצות אזוריות.")


def insight_streets(top_names, n_rows, n_unique, n_once):
    if top_names.empty or n_rows == 0:
        return None
    name, v = top_names.index[0], int(top_names.iloc[0])
    if v < 10:
        return None
    second = top_names.index[1] if len(top_names) > 1 else None
    tail = f", ואחריו \"{second}\" ({_int(top_names.iloc[1])})" if second else ""
    return (f"שם הרחוב הנפוץ ביותר במילון הוא \"{name}\" ({_int(v)} רשומות){tail}. "
            f"מתוך {_int(n_unique)} שמות רחוב שונים, {_int(n_once)} ({_pct(n_once / n_unique)}) מופיעים פעם אחת בלבד "
            "(לא כולל רשומות היישוב עצמו, קוד רחוב "
            f"{STREET_LOCALITY_CODE}).")


def insight_continents(cont_rows):
    best = None
    for r in cont_rows:
        diff = r["admin"] - r["geo"]
        if best is None or abs(diff) > abs(best[1]):
            best = (r["name"], diff, r["admin"], r["geo"])
    if best is None or abs(best[1]) < 5:
        return None
    word = "יותר" if best[1] > 0 else "פחות"
    return (f"במילון הארצות יש שתי חלוקות ליבשות: ביבשת הנושאת, {best[0]} כוללת {_int(best[2])} ארצות, "
            f"{_int(abs(best[1]))} {word} מאשר בחלוקה הגיאוגרפית ({_int(best[3])}).")


def insight_splits(splits, n_countries):
    if splits.empty:
        return None
    name, v = splits.index[0], int(splits.iloc[0])
    if v < 3:
        return None
    return (f"{_int(int(splits.sum()))} ארצות במילון רשומות כיורשות של ישות שהתפצלה. "
            f"הגדולה שבהן היא {name}, שממנה נוצרו {_int(v)} ארצות.")


def insight_branches(sections, n_codes):
    if sections.empty or n_codes == 0:
        return None
    name, v = sections.index[0], int(sections.iloc[0])
    if v / n_codes < 0.2:
        return None
    return (f"מילון הענפים הכלכליים כולל {_int(n_codes)} ענפים. חטיבת \"{name}\" לבדה מחזיקה {_int(v)} מהם "
            f"({_pct(v / n_codes)}), יותר מכל חטיבה אחרת.")


def insight_status(status_rows):
    rows = [r for r in status_rows if r["subs"] > 0]
    if len(rows) < 2:
        return None
    best = max(rows, key=lambda r: (r["subs"], -r["order"]))
    empty = sum(1 for r in status_rows if r["subs"] == 0)
    return (f"הסטטוס המשפטי \"{best['name']}\" מפוצל ל-{_int(best['subs'])} תתי-סטטוסים, יותר מכל סטטוס אחר; "
            f"ל-{_int(empty)} סטטוסים אין תת-סטטוס כלל (השיוך לפי ספרת המאות של קוד תת-הסטטוס).")


# ---------------------------------------------------------------- compute
def compute(frames):
    # --- central record ---------------------------------------------------
    rec = frames["record"].copy()
    rec["cat"] = _clean(rec["Category"])
    rec["name"] = _clean(rec["Name_Hebrew"])
    rec = rec[rec["name"] != ""]
    rec.loc[rec["cat"] == "", "cat"] = "ללא קטגוריה"
    rec["linked"] = _clean(rec["Codelist"]) != ""
    rec["idref"] = _clean(rec["התייחסות לסוג מזהה העסק"])
    rec["has_desc"] = _clean(rec["Description_Hebrew"]) != ""
    rec_total = len(rec)
    linked = int(rec["linked"].sum())
    cat_n = _rank(rec.groupby("cat").size())
    cat_k = rec.groupby("cat")["linked"].sum()
    cats = list(cat_n.index)
    chart_record = {
        "names": cats,
        "linked": [int(cat_k.get(c, 0)) for c in cats],
        "free": [int(cat_n[c] - cat_k.get(c, 0)) for c in cats],
    }
    by_cat_linked = {c: (int(cat_n[c]), int(cat_k.get(c, 0))) for c in cats}
    idr = rec[rec["idref"] != ""]
    idref = _rank(idr.groupby("idref").size())
    chart_idref = {"names": list(idref.index), "values": [int(v) for v in idref.values]}
    desc_share = rec["has_desc"].mean() if rec_total else 0.0

    # --- dictionary sizes and bilingual quality ---------------------------
    quality = []
    cleaned = {}
    for key, label, code, he, en, desc in DICTS:
        d = _dict_rows(frames[key], code, he)
        cleaned[key] = d
        n = len(d)
        en_share = None if en is None or n == 0 else float((_clean(d[en]) != "").mean())
        desc_share_d = None if desc is None or n == 0 else float((_clean(d[desc]) != "").mean())
        quality.append({"key": key, "name": label, "n": n, "en_share": en_share, "desc_share": desc_share_d})
    quality.sort(key=lambda q: (-q["n"], q["name"]))
    sizes = [(q["name"], q["n"]) for q in quality]
    total_values = sum(v for _, v in sizes)
    n_dicts = sum(1 for _, v in sizes if v > 0)
    chart_dicts = {"names": [q["name"] for q in quality], "values": [q["n"] for q in quality]}
    qual_pct = lambda x: None if x is None else round(x * 100, 1)
    chart_quality = {
        "names": [q["name"] for q in quality],
        "en": [qual_pct(q["en_share"]) for q in quality],
        "desc": [qual_pct(q["desc_share"]) for q in quality],
    }
    fmt_share = lambda x: "אין עמודה" if x is None else _pct(x, 0)
    table_dicts = [{"name": q["name"], "n": _int(q["n"]), "en": fmt_share(q["en_share"]),
                    "desc": fmt_share(q["desc_share"])} for q in quality]
    no_en = sum(1 for q in quality if q["en_share"] is None or q["en_share"] < 0.5)

    # --- localities -------------------------------------------------------
    loc = cleaned["localities"].copy()
    loc["district"] = _clean(loc["District"]).replace("", "לא צוין")
    loc["group"] = _clean(loc["צורת יישוב"]).map(_settlement_group)
    loc["status"] = _clean(loc["מעמד מוניציפלי"])
    loc["cluster"] = _clean(loc["אשכול רשויות מקומיות"]).replace("", "לא צוין")
    n_loc = len(loc)
    by_district = _rank(loc.groupby("district").size())
    group_tot = _rank(loc.groupby("group").size())
    groups = [g for g in group_tot.index if g != "אחר"] + (["אחר"] if "אחר" in group_tot.index else [])
    ct = loc.groupby(["district", "group"]).size()
    chart_loc = {
        "names": list(by_district.index),
        "series": [{"name": g, "data": [int(ct.get((d, g), 0)) for d in by_district.index]} for g in groups],
    }
    table_loc = [{"name": d, "n": _int(by_district[d]),
                  "cells": [_int(ct.get((d, g), 0)) for g in groups]} for d in by_district.index]
    regional = loc[(loc["status"] != "") & (~loc["status"].isin(INDEPENDENT))]
    councils = _rank(regional.groupby("status").size())
    n_councils = len(councils)
    regional_share = len(regional) / n_loc if n_loc else 0.0
    top_c = councils.head(TOP_COUNCILS)
    chart_councils = {"names": list(top_c.index), "values": [int(v) for v in top_c.values]}
    clusters = _rank(loc.groupby("cluster").size())
    chart_clusters = {"names": list(clusters.index), "values": [int(v) for v in clusters.values]}

    # --- local authorities ------------------------------------------------
    auth = cleaned["authorities"].copy()
    auth["type"] = _clean(auth["Description_Hebrew"]).replace("", "לא צוין")
    auth_types = _rank(auth.groupby("type").size())
    chart_auth = {"names": list(auth_types.index), "values": [int(v) for v in auth_types.values]}
    n_auth = len(auth)

    # --- streets ----------------------------------------------------------
    st = cleaned["streets"].copy()
    st["code"] = _clean(st["Code"])
    st["name"] = _clean(st["Name_Hebrew"])
    n_street_rows = len(st)
    loc_rows = int((st["code"] == STREET_LOCALITY_CODE).sum())
    real = st[st["code"] != STREET_LOCALITY_CODE]
    name_counts = _rank(real.groupby("name").size())
    n_unique_streets = len(name_counts)
    n_once = int((name_counts == 1).sum())
    top_st = name_counts.head(TOP_STREETS)
    chart_streets = {"names": list(top_st.index), "values": [int(v) for v in top_st.values]}

    # --- countries --------------------------------------------------------
    co = cleaned["countries"].copy()
    co["admin"] = _clean(co["שם יבשת"])
    co["geo"] = _clean(co["שם יבשת גיאוגרפי"])
    co["split"] = _clean(co["שם פיצול רשות האוכלוסין"])
    co["year"] = pd.to_numeric(_clean(co["שנת שינוי ברשות האוכלוסין"]), errors="coerce")
    n_countries = len(co)
    adm = co[co["admin"] != ""].groupby("admin").size()
    geo = co[co["geo"] != ""].groupby("geo").size()
    cont_names = sorted(set(adm.index) | set(geo.index),
                        key=lambda c: (-(int(adm.get(c, 0)) + int(geo.get(c, 0))), c))
    cont_rows = [{"name": c, "admin": int(adm.get(c, 0)), "geo": int(geo.get(c, 0))} for c in cont_names]
    n_cont_diff = sum(1 for r in cont_rows if r["admin"] != r["geo"])
    chart_cont = {"names": cont_names, "admin": [r["admin"] for r in cont_rows], "geo": [r["geo"] for r in cont_rows]}
    splits = _rank(co[co["split"] != ""].groupby("split").size())
    top_sp = splits.head(TOP_SPLITS)
    split_years = {}
    for s in top_sp.index:
        ys = co.loc[(co["split"] == s), "year"].dropna()
        split_years[s] = (f"{int(ys.min())}" if ys.min() == ys.max() else f"{int(ys.min())}-{int(ys.max())}") if len(ys) else ""
    chart_splits = {"names": list(top_sp.index), "values": [int(v) for v in top_sp.values]}
    table_splits = [{"name": s, "n": _int(top_sp[s]), "years": split_years[s] or "לא צוין"} for s in top_sp.index]
    n_changed = int(co["year"].notna().sum())

    # --- economic branches ------------------------------------------------
    br = cleaned["branches"].copy()
    br["section"] = _clean(br["Code"]).map(_isic_section)
    n_branches = len(br)
    order = {name: i for i, (_, _, name) in enumerate(ISIC_SECTIONS)}
    sec_counts = br.groupby("section").size()
    sec_names = sorted(sec_counts.index, key=lambda s: (order.get(s, 999), s))
    chart_branches = {"names": sec_names, "values": [int(sec_counts[s]) for s in sec_names]}
    sections_ranked = _rank(sec_counts)

    # --- institutional sectors --------------------------------------------
    se = cleaned["sectors"].copy()
    se["top"] = _clean(se["Code"]).map(lambda c: SNA_SECTORS.get(c[:2], "אחר") if len(c) == 6 else "אחר")
    sna_order = {v: i for i, v in enumerate(SNA_SECTORS.values())}
    se_counts = se.groupby("top").size()
    se_names = sorted(se_counts.index, key=lambda s: (sna_order.get(s, 999), s))
    chart_sectors = {"names": se_names, "values": [int(se_counts[s]) for s in se_names]}

    # --- legal status -> sub-status ---------------------------------------
    ls = cleaned["legal_status"].copy()
    ls["code"] = pd.to_numeric(_clean(ls["Code"]), errors="coerce")
    ls["name"] = _clean(ls["Name_Hebrew"])
    ls = ls.dropna(subset=["code"]).sort_values(["code", "name"], kind="stable")
    sub = cleaned["legal_substatus"].copy()
    sub["code"] = pd.to_numeric(_clean(sub["Code"]), errors="coerce")
    sub = sub.dropna(subset=["code"])
    sub["parent"] = (sub["code"] // 100).where(sub["code"] >= 100)
    parent_counts = sub.groupby("parent").size()
    status_rows = []
    for i, r in enumerate(ls.itertuples()):
        status_rows.append({"name": r.name, "subs": int(parent_counts.get(r.code, 0)), "order": i})
    chart_status = {"names": [r["name"] for r in status_rows], "values": [r["subs"] for r in status_rows]}
    known = set(ls["code"])
    orphan_subs = int(sub["parent"].notna().sum() - sub["parent"].isin(known).sum())

    # --- small dictionaries browser ---------------------------------------
    browser = []
    for key, label, code, he, en, desc in DICTS:
        d = cleaned[key]
        if len(d) == 0 or len(d) > BROWSER_MAX:
            continue
        d = d.assign(_c=pd.to_numeric(_clean(d[code]), errors="coerce"), _h=_clean(d[he]))
        d = d.sort_values(["_c", "_h"], kind="stable")
        rows = [{"code": str(c).strip(), "he": h,
                 "en": (str(e).strip() if en else "")}
                for c, h, e in zip(d[code], d["_h"], d[en] if en else [""] * len(d))]
        browser.append({"name": label, "n": len(rows), "rows": rows, "has_en": en is not None})
    browser.sort(key=lambda b: (b["n"], b["name"]))

    # --- insights ---------------------------------------------------------
    rules = [
        ("record", insight_record(rec_total, linked, by_cat_linked)),
        ("concentration", insight_concentration(sizes)),
        ("bilingual", insight_bilingual(quality)),
        ("localities", insight_localities(n_loc, by_district, regional_share, n_councils)),
        ("streets", insight_streets(name_counts, n_street_rows, n_unique_streets, n_once)),
        ("continents", insight_continents(cont_rows)),
        ("splits", insight_splits(splits, n_countries)),
        ("branches", insight_branches(sections_ranked, n_branches)),
        ("status", insight_status(status_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "dicts": {"value": n_dicts, "display": _int(n_dicts), "tone": "brand"},
        "values": {"value": total_values, "display": _int(total_values), "tone": "brand"},
        "fields": {"value": rec_total, "display": _int(rec_total), "tone": "brand"},
        "linked": {"value": round(linked / rec_total * 100, 1) if rec_total else 0,
                   "display": _pct(linked / rec_total) if rec_total else "0.0%", "tone": "info"},
        "no_en": {"value": no_en, "display": _int(no_en), "tone": "warn" if no_en else "ok"},
        "categories": {"value": len(cats), "display": _int(len(cats)), "tone": "brand"},
    }

    top_cat = cats[0] if cats else ""
    top_idref = chart_idref["names"][0] if chart_idref["names"] else ""
    biggest = sizes[0] if sizes else ("", 0)
    smallest = sizes[-1] if sizes else ("", 0)
    top_br = sections_ranked.index[0] if len(sections_ranked) else ""
    top_auth = auth_types.index[0] if len(auth_types) else ""
    top_cont = cont_rows[0]["name"] if cont_rows else ""
    top_se = _rank(se_counts).index[0] if len(se_counts) else ""

    labels = {
        "lede": (f"ספריית המילונים של מערך הדיגיטל הלאומי מגדירה שפה אחידה לנתוני עסק: רשומה מרכזית של "
                 f"{_int(rec_total)} שדות ב-{_int(len(cats))} קטגוריות, ו-{_int(n_dicts)} מילוני קוד "
                 f"(code lists) עם {_int(total_values)} ערכים, מיישובים ורחובות ועד סטטוסים משפטיים, ענפים כלכליים וגודל עסק. "
                 "העמוד מנתח את מבנה הספרייה ואת תוכן המילונים; כל ערך וקוד זמינים לחיפוש בעיון בנתונים שבתחתית העמוד."),
        "record_lede": (f"הרשומה המרכזית מפרטת אילו שדות מתארים עסק. הקטגוריה הגדולה היא \"{top_cat}\" "
                        f"({_int(cat_n[top_cat]) if top_cat else 0} שדות). {_int(linked)} שדות מקבלים את ערכיהם ממילון, "
                        f"ול-{_pct(desc_share, 0)} מהשדות יש הסבר מילולי."),
        "record_aria": (f"גרף עמודות מוערמות: שדות הרשומה המרכזית לפי קטגוריה, מקושרים למילון מול שדות חופשיים. "
                        f"הקטגוריה הגדולה: {top_cat}."),
        "idref_lede": (f"{_int(len(idr))} שדות מציינים לאיזה סוג מזהה הם שייכים (מזהה ישות משפטית, תיק מס הכנסה וכו'). "
                       f"הנפוץ: {top_idref}."),
        "idref_aria": f"גרף עמודות: שדות הרשומה לפי סוג מזהה העסק שאליו הם מתייחסים. הנפוץ: {top_idref}.",
        "dicts_lede": (f"גודל המילונים שונה מאוד: מ-{_int(smallest[1])} ערכים במילון \"{smallest[0]}\" ועד {_int(biggest[1])} במילון \"{biggest[0]}\". "
                       "הציר לוגריתמי כדי שגם המילונים הקטנים ייראו."),
        "dicts_aria": f"גרף עמודות אופקי בציר לוגריתמי: מספר הערכים בכל מילון. הגדול: {biggest[0]} עם {_int(biggest[1])} ערכים.",
        "quality_lede": (f"לכל מילון נבדק איזה חלק מהערכים כולל שם באנגלית והסבר בעברית. "
                         f"ב-{_int(no_en)} מילונים אין שם באנגלית לרוב הערכים או שאין עמודה כזו כלל (מוצג כאפס)."),
        "quality_aria": f"גרף עמודות אופקי: שיעור הערכים עם שם באנגלית ועם הסבר בכל מילון. {_int(no_en)} מילונים ללא אנגלית לרוב הערכים.",
        "loc_lede": (f"{_int(n_loc)} יישובים לפי מחוז וצורת יישוב (קיבוצים, מושבים, יישובים קהילתיים, עירוניים ועוד, "
                     "בקיבוץ של צורות היישוב לקבוצות). "
                     f"הקבוצה הגדולה: {group_tot.index[0] if len(group_tot) else ''} ({_int(group_tot.iloc[0]) if len(group_tot) else 0} יישובים)."),
        "loc_aria": (f"גרף עמודות מוערמות: מספר היישובים בכל מחוז לפי קבוצת צורת יישוב. "
                     f"המוביל: {by_district.index[0] if len(by_district) else ''} עם {_int(by_district.iloc[0]) if len(by_district) else 0}."),
        "councils_lede": (f"{_int(len(regional))} יישובים ({_pct(regional_share)}) שייכים ל-{_int(n_councils)} מועצות אזוריות; "
                          f"השאר עיריות ומועצות מקומיות. מוצגות {_int(len(top_c))} המועצות עם הכי הרבה יישובים."),
        "councils_aria": (f"גרף עמודות אופקי: המועצות האזוריות עם מספר היישובים הרב ביותר. "
                          f"המובילה: {top_c.index[0] if len(top_c) else ''}."),
        "clusters_lede": (f"שיוך היישובים לאשכולות רשויות מקומיות. "
                          f"{_int(clusters.get('ללא שיוך לאשכול', 0))} יישובים אינם משויכים לאשכול."),
        "clusters_aria": f"גרף עמודות אופקי: מספר היישובים בכל אשכול רשויות מקומיות. הגדול: {clusters.index[0] if len(clusters) else ''}.",
        "auth_lede": f"מילון הרשויות המקומיות כולל {_int(n_auth)} רשויות לפי סוג. הסוג הנפוץ: {top_auth}.",
        "auth_aria": f"גרף עוגה: {_int(n_auth)} רשויות מקומיות לפי סוג. הנפוץ: {top_auth}.",
        "streets_lede": (f"מילון הרחובות מונה {_int(n_street_rows)} רשומות; {_int(loc_rows)} מהן בקוד {STREET_LOCALITY_CODE}, "
                         "המייצג את היישוב עצמו ולא רחוב, ולכן אינן נספרות כאן. "
                         f"{_int(n_unique_streets)} שמות רחוב שונים; השם הנפוץ חוזר {_int(top_st.iloc[0]) if len(top_st) else 0} פעמים."),
        "streets_aria": (f"גרף עמודות אופקי: {_int(len(top_st))} שמות הרחוב הנפוצים במילון. "
                         f"הנפוץ: {top_st.index[0] if len(top_st) else ''}."),
        "cont_lede": (f"{_int(n_countries)} ארצות וטריטוריות. כל ארץ משויכת ליבשת פעמיים: ביבשת הנושאת (החלוקה המנהלית) "
                      "וביבשת הגיאוגרפית. "
                      + (f"מספר הארצות שונה בין החלוקות ב-{_int(n_cont_diff)} מתוך {_int(len(cont_rows))} היבשות."
                         if n_cont_diff else "שתי החלוקות זהות בספירה לפי יבשת.")),
        "cont_aria": f"גרף עמודות מקובצות: מספר הארצות בכל יבשת לפי שתי החלוקות. הגדולה: {top_cont}.",
        "splits_lede": (f"{_int(int(splits.sum()))} ארצות רשומות כיורשות של ישות שהתפצלה, ול-{_int(n_changed)} ארצות "
                        "רשומה שנת שינוי ברשות האוכלוסין."),
        "splits_aria": f"גרף עמודות אופקי: מספר הארצות שנוצרו מכל ישות שהתפצלה. המובילה: {top_sp.index[0] if len(top_sp) else ''}.",
        "branches_lede": (f"{_int(n_branches)} ענפים כלכליים, מקובצים לפי שתי הספרות הראשונות של הקוד לחטיבות הסיווג. "
                          f"החטיבה המפורטת ביותר: \"{top_br}\"."),
        "branches_aria": f"גרף עמודות אופקי: מספר הענפים בכל חטיבה של הסיווג הכלכלי. המובילה: {top_br}.",
        "sectors_lede": (f"{_int(len(se))} סקטורים מוסדיים, מקובצים לפי שתי הספרות הראשונות של הקוד. "
                         f"הסקטור המפורט ביותר: \"{top_se}\" ({_int(se_counts.get(top_se, 0))} קודים)."),
        "sectors_aria": f"גרף עמודות אופקי: מספר הקודים בכל סקטור מוסדי ראשי. המוביל: {top_se}.",
        "status_lede": ("כל תת-סטטוס משפטי משויך לסטטוס לפי ספרת המאות של הקוד שלו. "
                        + (f"{_int(orphan_subs)} תתי-סטטוסים לא מתאימים לאף סטטוס. " if orphan_subs else "")
                        + "סטטוסים בלי תת-סטטוס מוצגים באפס."),
        "status_aria": "גרף עמודות אופקי: מספר תתי-הסטטוסים לכל סטטוס משפטי.",
        "browser_lede": (f"{_int(len(browser))} המילונים הקצרים (עד {_int(BROWSER_MAX)} ערכים) במלואם, לפי קוד. "
                         "המילונים הגדולים זמינים לחיפוש בעיון בנתונים."),
    }

    summary = (f"איתור קוד או ערך במילוני נתוני עסק: {_int(n_dicts)} מילונים עם {_int(total_values)} ערכים "
               f"ורשומה מרכזית של {_int(rec_total)} שדות, לפי קוד, שם בעברית או באנגלית.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מילון", "טרמינולוגיה", "עסקים", "מילוני קוד", "סטנדרטיזציה", "מטא-נתונים"],
            "related_ids": [
                "e9b65317-9e73-4189-b30f-004759afd070",
                "d4a897f6-84bf-4560-9f28-7757bf8a0619",
                "069357eb-bcc9-466c-a515-ce6d0a81462f",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "record": chart_record, "idref": chart_idref, "dicts": chart_dicts, "quality": chart_quality,
            "loc": chart_loc, "councils": chart_councils, "clusters": chart_clusters, "auth": chart_auth,
            "streets": chart_streets, "cont": chart_cont, "splits": chart_splits,
            "branches": chart_branches, "sectors": chart_sectors, "status": chart_status,
        },
        "tables": {
            "dicts": table_dicts, "loc": table_loc, "loc_groups": groups, "splits": table_splits,
        },
        "browser": browser,
        "insights": insights,
        "labels": labels,
    }
