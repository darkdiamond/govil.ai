"""Person data-dictionary library (מערך הדיגיטל הלאומי): the central person
record schema plus 32 code lists (countries, localities, streets, languages,
religions, education, ...).

Every number on the page is computed here. The record schema drives the
"structure" charts; the big code lists (countries, localities, authorities,
neighbourhoods, streets, study professions) each get their own view; every
code list contributes its size to the library overview. Insight rules return
None when their premise doesn't hold.
"""
import re

import pandas as pd

# (input name, page label, the Codelist name the record schema uses for it).
# Labels are fixed copy (resource names are not part of the frames); the
# codelist names let the page tell which referenced code lists are published.
DICTS = [
    ("id_types", "סוגי אמצעי זיהוי", "אמצעי זיהוי"),
    ("countries", "ארצות", "ארצות"),
    ("gender", "מגדר", "מגדר"),
    ("localities", "יישובים בישראל", "יישובים"),
    ("place_types", "סוגי מקומות לידה ופטירה", "סוג מקום לידה ופטירה"),
    ("citizenship", "אזרחות", "אזרחות"),
    ("residency", "מעמד אדם בישראל", "מעמד אדם בישראל"),
    ("health_funds", "קופות חולים", "קופות חולים"),
    ("authorities", "רשויות מקומיות", "רשויות מקומיות"),
    ("authority_types", "סוגי רשויות מקומיות", "סוגי רשויות מקומיות"),
    ("districts", "מחוזות", "מחוזות"),
    ("subdistricts", "נפות", "נפה"),
    ("natural_regions", "אזורים טבעיים", "אזורים טבעיים"),
    ("neighborhoods", "שכונות", "שכונות"),
    ("streets", "רחובות", "רחובות"),
    ("languages", "שפות", "שפות"),
    ("pop_groups", "קבוצות אוכלוסייה", "קבוצות אוכלוסיה"),
    ("religions", "דתות", "דת"),
    ("religion_groups", "דתות מרכזיות", "דת מקובץ"),
    ("religiosity", "מידת דתיות", "סיווג דתיות"),
    ("nationalities", "לאומים", "לאום"),
    ("marital", "מצב אישי", "מצב אישי"),
    ("disability_types", "סוגי נכויות", "סוגי נכויות"),
    ("disability_bodies", "גופים המכירים בנכות", "גופי הכרה בנכות"),
    ("education_levels", "רמות השכלה", "רמות השכלה"),
    ("institutions", "מוסדות להשכלה גבוהה", "מוסדות להשכלה גבוהה"),
    ("study_fields", "תחומי לימודים", "תחומי לימודים"),
    ("professions", "מקצועות לימוד", "מקצועות לימוד"),
    ("employment", "סטטוסים תעסוקתיים", "סטטוס תעסוקתי"),
    ("income", "רמות הכנסה", "רמות הכנסה"),
    ("pets", "סוגי חיות מחמד", "סוגי חיות"),
    ("driving", "סוגי רישיונות נהיגה", "סוגי רשיונות נהיגה"),
]

# Field kind from the English column-name suffix (the schema's own convention).
KINDS = [
    ("_code", "קוד ממילון"),
    ("_flag", "דגל כן/לא"),
    ("_id", "מזהה או קוד ישות"),
    ("_date", "תאריך"),
    ("_number", "מספר"),
]
KIND_OTHER = "טקסט ושדות אחרים"

UNKNOWN_NAMES = {"לא ידוע", "ערך חסר", "Unknown", "Missing value"}

# Street-name prefixes that mark the kind of thoroughfare (abbreviated as in
# the population registry). Anything else is a plain name.
STREET_PREFIX = {
    "שכ": "שכונה או שיכון", "ש": "שכונה או שיכון", "שכונת": "שכונה או שיכון",
    "דרך": "דרך",
    "שד": "שדרה", "שדרות": "שדרה", "שדרת": "שדרה",
    "ככר": "כיכר", "כיכר": "כיכר",
    "סמ": "סמטה", "סמטת": "סמטה", "סמטה": "סמטה",
    "משעול": "משעול",
    "שביל": "שביל",
    "מבוא": "מבוא",
    "אזור": "אזור או מתחם", "מתחם": "אזור או מתחם",
}
STREET_NUMBERED = "רחוב ממוספר"
STREET_PLAIN = "שם בלבד, ללא קידומת"
LOCALITY_ROW_CODE = 9000  # the registry's "no street, locality only" entry

TOP_N = 15


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _s(series):
    return series.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def _code_rows(df):
    """Rows of a code list: a non-empty Code that isn't a repeated header."""
    if "Code" not in df.columns:
        return df.iloc[0:0]
    code = _s(df["Code"])
    return df[(code != "") & (code != "Code")]


def _mode(series):
    """Most frequent value; ties broken alphabetically."""
    return _sorted_counts(series).index[0]


def _sorted_counts(series):
    """value_counts with a total, deterministic order (count desc, label asc)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


# ── record schema ─────────────────────────────────────────────────────────

def _schema(df):
    s = pd.DataFrame({
        "he": _s(df["Name_Hebrew"]),
        "en": _s(df["Name_English"]),
        "codelist": _s(df["Codelist"]),
        "category": _s(df["Category"]).str.replace(r"\s*,\s*", ", ", regex=True),
    })
    s = s[(s["he"] != "") | (s["en"] != "")]

    def kind(en):
        e = en.lower()
        for suf, label in KINDS:
            if e.endswith(suf):
                return label
        return KIND_OTHER
    s["kind"] = s["en"].map(kind)
    s["linked"] = s["codelist"] != ""
    return s.sort_values(["category", "en", "he"], kind="stable").reset_index(drop=True)


# ── countries ─────────────────────────────────────────────────────────────

def _countries(df):
    c = pd.DataFrame({
        "name": _s(df["שם בעברית"]),
        "is_code": _s(df["קוד לפי תקן ישראלי"]),
        "piba_code": _s(df["קוד ארץ רשות האוכלוסין"]),
        "cont": _s(df["שם יבשת"]),
        "geo": _s(df["שם יבשת גיאוגרפי"]),
        "split": _s(df["שם פיצול רשות האוכלוסין"]),
        "split_year": _s(df["שנת שינוי ברשות האוכלוסין"]),
        "un2": _s(df["סמל ארץ אלפביתי 2 (UN)"]),
    })
    # The file repeats its header (Hebrew + technical names) as data rows.
    return c[c["is_code"].str.fullmatch(r"\d+")].sort_values(
        ["name", "is_code"], kind="stable").reset_index(drop=True)


# ── localities ────────────────────────────────────────────────────────────

def _settlement_group(form):
    if "לא יהודיים" in form:
        return "יישובים לא יהודיים"
    if form.startswith("קיבוצים"):
        return "קיבוצים"
    if form.startswith("מושבים"):
        return "מושבים"
    if "קהילתיים" in form:
        return "יישובים קהילתיים"
    if re.match(r"יישובים יהודיים \d", form):
        return "יישובים יהודיים עירוניים"
    return "אחר: מוסדי, כפרי או מוקד תעסוקה"


GROUP_ORDER = ["קיבוצים", "מושבים", "יישובים קהילתיים", "יישובים יהודיים עירוניים",
               "יישובים לא יהודיים", "אחר: מוסדי, כפרי או מוקד תעסוקה"]


def compute(frames):
    schema = _schema(frames["schema"])
    n_fields = len(schema)
    linked = int(schema["linked"].sum())

    # Library overview: size of every code list.
    sizes = []
    for name, label, _cl in DICTS:
        df = frames[name]
        if name == "countries":
            n = len(_countries(df))
        elif name == "neighborhoods":
            n = int(((_s(df["Code_City"]) != "") & (_s(df["Name_Neighborhood_Hebrew"]) != "")).sum())
        else:
            n = len(_code_rows(df))
        sizes.append((label, n, name))
    sizes.sort(key=lambda t: (-t[1], t[0]))
    sizes = [t for t in sizes if t[1] > 0]
    n_dicts = len(sizes)
    n_values = sum(t[1] for t in sizes)

    # "Unknown" value codes, per dictionary.
    unknown_codes = {}
    for name, label, _cl in DICTS:
        df = _code_rows(frames[name])
        if df.empty:
            continue
        mask = pd.Series(False, index=df.index)
        for col in df.columns:
            if col == "Code":
                continue
            mask |= _s(df[col]).isin(UNKNOWN_NAMES)
        codes = sorted(set(_s(df.loc[mask, "Code"])))
        if codes:
            unknown_codes[label] = codes[0]

    # Categories x linked.
    cats = (schema.groupby("category")
            .agg(total=("en", "size"), linked=("linked", "sum")).reset_index())
    cats["linked"] = cats["linked"].astype(int)
    cats = cats.sort_values(["total", "category"], ascending=[False, True], kind="stable")
    cat_rows = [{"name": r.category, "linked": int(r.linked), "free": int(r.total - r.linked),
                 "total": int(r.total)} for r in cats.itertuples()]

    kinds = _sorted_counts(schema["kind"])
    kind_rows = [{"name": k, "value": int(v), "share": _pct(v / n_fields)} for k, v in kinds.items()]

    reuse = _sorted_counts(schema.loc[schema["linked"], "codelist"])
    reuse_rows = []
    for cl, v in reuse.head(10).items():
        fields = schema.loc[schema["codelist"] == cl, "he"].tolist()
        reuse_rows.append({"name": cl, "value": int(v), "fields": ", ".join(fields)})
    n_codelists = int(reuse.size)
    published_present = {cl for (_n, _l, cl) in DICTS if any(t[2] == _n for t in sizes)}
    missing_cl = sorted(cl for cl in reuse.index if cl not in published_present)

    # Countries.
    c = _countries(frames["countries"])
    n_countries = len(c)
    conts = sorted(set(c["cont"]) | set(c["geo"]) - {""})
    conts = [x for x in conts if x]
    cont_admin = c["cont"].value_counts()
    cont_geo = c["geo"].value_counts()
    cont_order = sorted(conts, key=lambda x: (-int(cont_geo.get(x, 0)), -int(cont_admin.get(x, 0)), x))
    cont_rows = [{"name": x, "admin": int(cont_admin.get(x, 0)), "geo": int(cont_geo.get(x, 0))}
                 for x in cont_order]
    both = c[(c["cont"] != "") & (c["geo"] != "")]
    mism = both[both["cont"] != both["geo"]]
    pair = (mism.groupby(["cont", "geo"]).size().reset_index(name="n")
            .sort_values(["n", "cont", "geo"], ascending=[False, True, True], kind="stable"))

    has_piba = c["piba_code"] != ""
    has_un = c["un2"] != ""
    sys_rows = [
        {"name": "בשלוש מערכות הקוד", "value": int((has_piba & has_un).sum())},
        {"name": "תקן ישראלי ואו״ם בלבד", "value": int((~has_piba & has_un).sum())},
        {"name": "תקן ישראלי ורשות האוכלוסין בלבד", "value": int((has_piba & ~has_un).sum())},
        {"name": "תקן ישראלי בלבד", "value": int((~has_piba & ~has_un).sum())},
    ]
    sys_rows = [r for r in sys_rows if r["value"] > 0]

    # A predecessor entity with a recorded change year (the registry's own
    # "split" column also groups a few countries without a year; those are
    # regional groupings, not predecessors).
    splits = c[(c["split"] != "") & (c["split"] != c["name"]) & (c["split_year"] != "")]
    split_counts = _sorted_counts(splits["split"])
    split_rows = []
    for sp, v in split_counts.items():
        yrs = sorted(set(y for y in splits.loc[splits["split"] == sp, "split_year"] if y))
        yr = yrs[0] if len(yrs) == 1 else f"{yrs[0]}-{yrs[-1]}"
        split_rows.append({"name": sp, "value": int(v), "years": yr})

    # Localities.
    loc = frames["localities"]
    loc = loc[_s(loc["Code"]).str.fullmatch(r"\d+")]
    L = pd.DataFrame({
        "district": _s(loc["District"]).replace("", "לא צוין"),
        "group": _s(loc["צורת יישוב"]).map(_settlement_group),
        "status": _s(loc["מעמד מוניציפלי"]),
    })
    n_loc = len(L)
    dist_tot = _sorted_counts(L["district"])
    districts = list(dist_tot.index)
    groups = [g for g in GROUP_ORDER if (L["group"] == g).any()]
    ct = pd.crosstab(L["district"], L["group"])
    loc_series = [{"name": g, "data": [int(ct.at[d, g]) if g in ct.columns else 0 for d in districts]}
                  for g in groups]
    loc_rows = [{"name": d, "total": int(dist_tot[d]),
                 "cells": [int(ct.at[d, g]) if g in ct.columns else 0 for g in groups]}
                for d in districts]
    grp_tot = _sorted_counts(L["group"])

    # Authorities + regional-council membership of localities.
    au = frames["authorities"]
    au = au[_s(au["Code"]).str.fullmatch(r"\d+")]
    A = pd.DataFrame({"name": _s(au["Name_Hebrew"]), "type": _s(au["Authority_Type_Code"]),
                      "type_name": _s(au["Description_Hebrew"])})
    type_names = A[A["type_name"] != ""].groupby("type")["type_name"].agg(_mode).to_dict()
    at = _sorted_counts(A["type"])
    auth_rows = [{"name": type_names.get(t, f"סוג {t}"), "value": int(v)} for t, v in at.items()]
    n_auth = len(A)
    rc_names = set(A.loc[A["type"].map(lambda t: "אזורית" in type_names.get(t, "")), "name"])
    in_rc = L[L["status"].isin(rc_names)]
    rc_counts = _sorted_counts(in_rc["status"])
    council_rows = [{"name": k, "value": int(v)} for k, v in rc_counts.head(TOP_N).items()]

    # Neighbourhoods per city.
    nb = frames["neighborhoods"]
    N = pd.DataFrame({"city": _s(nb["Code_City"]), "city_name": _s(nb["Name_City_Hebrew"]),
                      "name": _s(nb["Name_Neighborhood_Hebrew"])})
    N = N[(N["city"] != "") & (N["name"] != "")]
    city_label = N.groupby("city")["city_name"].agg(_mode)
    nb_counts = N.groupby("city").size()
    nb_df = pd.DataFrame({"city": nb_counts.index, "n": nb_counts.values})
    nb_df["label"] = nb_df["city"].map(city_label)
    nb_df = nb_df.sort_values(["n", "label", "city"], ascending=[False, True, True], kind="stable")
    nb_rows = [{"name": r.label, "value": int(r.n)} for r in nb_df.head(TOP_N).itertuples()]
    n_nb = len(N)
    n_nb_cities = len(nb_df)

    # Streets.
    st = frames["streets"]
    S = pd.DataFrame({"code": pd.to_numeric(_s(st["Code"]), errors="coerce"),
                      "name": _s(st["Name_Hebrew"])})
    S = S[S["code"].notna() & (S["name"] != "")]
    n_streets_all = len(S)
    n_locality_rows = int((S["code"] == LOCALITY_ROW_CODE).sum())
    SS = S[S["code"] != LOCALITY_ROW_CODE]
    n_streets = len(SS)

    def street_type(name):
        parts = name.split(" ")
        first = parts[0]
        if first == "רח" and len(parts) > 1 and parts[1].isdigit():
            return STREET_NUMBERED
        return STREET_PREFIX.get(first, STREET_PLAIN)
    stypes = _sorted_counts(SS["name"].map(street_type))
    stype_rows = [{"name": k, "value": int(v), "share": _pct(v / n_streets)}
                  for k, v in stypes.items()]
    plain = SS[SS["name"].map(street_type) == STREET_PLAIN]
    top_names = _sorted_counts(plain["name"]).head(TOP_N)
    sname_rows = [{"name": k, "value": int(v)} for k, v in top_names.items()]

    # Languages: ISO 639-1 coverage.
    lg = _code_rows(frames["languages"])
    n_lang = len(lg)
    n_iso1 = int((_s(lg["Code_Iso639_1"]).str.fullmatch(r"[a-z]{2}")).sum())

    # Study professions per study field.
    sf = _code_rows(frames["study_fields"])
    field_name = dict(zip(_s(sf["Code"]), _s(sf["Name_Hebrew"]).str.strip(". ")))
    pr = _code_rows(frames["professions"])
    grp = _sorted_counts(_s(pr["Code_Group"]))
    prof_rows = [{"name": field_name.get(g, f"תחום {g}"), "value": int(v)} for g, v in grp.items()]
    prof_rows.sort(key=lambda r: (-r["value"], r["name"]))
    n_prof = len(pr)

    # Higher-education institutions by type.
    ins = _code_rows(frames["institutions"])
    itypes = _sorted_counts(_s(ins["Description_Hebrew"]).replace("", "לא צוין"))
    inst_rows = [{"name": k, "value": int(v)} for k, v in itypes.items()]
    n_inst = len(ins)

    # ── insights ──────────────────────────────────────────────────────────
    def ins_linked():
        if not n_fields:
            return None
        return (f"{_int(linked)} מתוך {_int(n_fields)} השדות ברשומת האדם ({_pct(linked / n_fields)}) "
                f"מקושרים למילון קוד אחיד; השאר שדות חופשיים כמו שמות, תאריכים, מספרי זיהוי ודגלים.")

    def ins_flags():
        f = schema[schema["kind"] == "דגל כן/לא"]
        if len(f) < 3:
            return None
        top = _sorted_counts(f["category"])
        cat, v = top.index[0], int(top.iloc[0])
        return (f"{_int(len(f))} שדות ({_pct(len(f) / n_fields)}) הם דגלי כן/לא, כמו רישום פלילי, "
                f"ניצול שואה או בעלות על דירה; הקטגוריה העשירה בהם היא {cat} עם {_int(v)} דגלים.")

    def ins_reuse():
        if reuse.empty or int(reuse.iloc[0]) < 2:
            return None
        cl, v = reuse.index[0], int(reuse.iloc[0])
        fields = schema.loc[schema["codelist"] == cl, "he"].tolist()
        multi = int((reuse >= 2).sum())
        return (f"מילון {cl} הוא המשותף ביותר: {_int(v)} שדות נשענים עליו ({', '.join(fields)}). "
                f"בסך הכול {_int(multi)} מילונים משמשים יותר משדה אחד.")

    def ins_missing():
        if not missing_cl or len(missing_cl) > 3:
            return None
        names = ", ".join(missing_cl)
        which = ("למילון אחד" if len(missing_cl) == 1
                 else f"ל-{_int(len(missing_cl))} מילונים")
        return (f"הרשומה מפנה ל-{_int(n_codelists)} מילוני קוד, אך {which} "
                f"({names}) לא פורסם קובץ בספרייה.")

    def ins_continent():
        if pair.empty or len(mism) < 5:
            return None
        p = pair.iloc[0]
        return (f"{_int(len(mism))} ארצות משויכות ב\"יבשת\" של רשות האוכלוסין ליבשת שונה מהיבשת "
                f"הגיאוגרפית שלהן; השכיח: {_int(p.n)} ארצות שגיאוגרפית ב{p.geo} מסווגות כ{p.cont}.")

    def ins_splits():
        if split_counts.empty or int(split_counts.iloc[0]) < 3:
            return None
        sp, v = split_counts.index[0], int(split_counts.iloc[0])
        yr = split_rows[0]["years"]
        return (f"מילון הארצות שומר את ההיסטוריה: {_int(v)} ארצות מסומנות כפיצול של {sp} "
                f"(שנת שינוי {yr}), ובסך הכול {_int(len(splits))} ארצות נגזרו מ-{_int(split_counts.size)} ישויות קודמות.")

    def ins_councils():
        if not n_loc or rc_counts.empty:
            return None
        share = len(in_rc) / n_loc
        if share < 0.3:
            return None
        top, v = rc_counts.index[0], int(rc_counts.iloc[0])
        return (f"{_int(len(in_rc))} מתוך {_int(n_loc)} היישובים ({_pct(share)}) שייכים ל-"
                f"{_int(rc_counts.size)} מועצות אזוריות; הגדולה במספר יישובים היא {top} עם {_int(v)}.")

    def ins_district():
        if dist_tot.empty or not n_loc:
            return None
        d, v = dist_tot.index[0], int(dist_tot.iloc[0])
        share = v / n_loc
        if share < 0.2:
            return None
        g = grp_tot.index[0]
        return (f"מחוז {d} מרכז {_int(v)} יישובים ({_pct(share)} ממילון היישובים), "
                f"והצורה הנפוצה בכל הארץ היא {g} ({_int(grp_tot.iloc[0])} יישובים).")

    def ins_streets():
        if len(top_names) < 3:
            return None
        a = list(top_names.items())[:3]
        return (f"מבין {_int(n_streets)} שמות הרחובות במילון, הנפוצים הם {a[0][0]} ({_int(a[0][1])} פעמים), "
                f"{a[1][0]} ({_int(a[1][1])}) ו{a[2][0]} ({_int(a[2][1])}); "
                f"עוד {_int(n_locality_rows)} רשומות בקוד {LOCALITY_ROW_CODE} מייצגות כתובת ברמת יישוב בלבד.")

    def ins_unknown():
        if len(unknown_codes) < 5:
            return None
        vc = pd.Series(list(unknown_codes.values())).value_counts()
        vc = vc.sort_index().sort_values(ascending=False, kind="stable")
        main, n_main = vc.index[0], int(vc.iloc[0])
        others = [f"{lbl} ({code})" for lbl, code in sorted(unknown_codes.items()) if code != main]
        if not others:
            return (f"ב-{_int(len(unknown_codes))} מילונים יש ערך \"לא ידוע\" או \"ערך חסר\", "
                    f"ובכולם הקוד אחיד: {main}.")
        return (f"ל-{_int(len(unknown_codes))} מילונים יש ערך \"לא ידוע\" או \"ערך חסר\", אך הקוד שלו "
                f"אינו אחיד: {main} ב-{_int(n_main)} מילונים, ואילו במילונים {', '.join(others[:4])} הוא שונה.")

    def ins_iso():
        if not n_lang:
            return None
        return (f"{_int(n_iso1)} מתוך {_int(n_lang)} השפות במילון ({_pct(n_iso1 / n_lang)}) "
                f"נושאות קוד ISO 639-1 דו-אותי, כך שאפשר לחבר אותן ישירות למערכות בינלאומיות.")

    rules = [
        ("linked", ins_linked()), ("flags", ins_flags()), ("reuse", ins_reuse()),
        ("missing", ins_missing()), ("continent", ins_continent()), ("splits", ins_splits()),
        ("councils", ins_councils()), ("district", ins_district()), ("streets", ins_streets()),
        ("unknown", ins_unknown()), ("iso", ins_iso()),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    biggest = sizes[0] if sizes else ("", 0, "")
    summary = (f"איתור קודים אחידים לנתוני אדם: {_int(n_countries)} ארצות, {_int(n_loc)} יישובים, "
               f"{_int(n_streets_all)} רחובות ושפות, דתות והשכלה. {_int(n_dicts)} מילונים לרשומה של "
               f"{_int(n_fields)} שדות.")
    lede = (f"ספריית המילונים של מערך הדיגיטל הלאומי מגדירה שפה אחידה לתיאור אדם במערכות ממשלתיות: "
            f"רשומה מרכזית של {_int(n_fields)} שדות ב-{_int(len(cat_rows))} קטגוריות, ולצדה {_int(n_dicts)} "
            f"מילוני קוד עם {_int(n_values)} ערכים. הגדול הוא מילון ה{biggest[0]} ({_int(biggest[1])} ערכים).")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מילוני נתונים", "טבלאות קוד", "קודי יישובים", "קודי ארצות",
                               "טרמינולוגיה", "תקינה"],
            "related_ids": [
                "e9b65317-9e73-4189-b30f-004759afd070",
                "83bd6cfa-cab5-4645-92a1-1a757524ce70",
                "069357eb-bcc9-466c-a515-ce6d0a81462f",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "fields": {"value": n_fields, "display": _int(n_fields), "tone": "brand"},
            "linked": {"value": round(linked / n_fields, 4) if n_fields else 0,
                       "display": _pct(linked / n_fields) if n_fields else "0.0%",
                       "tone": "ok" if n_fields and linked / n_fields >= 0.5 else "info"},
            "dicts": {"value": n_dicts, "display": _int(n_dicts), "tone": "brand"},
            "entries": {"value": n_values, "display": _int(n_values), "tone": "brand"},
            "countries": {"value": n_countries, "display": _int(n_countries), "tone": "brand"},
            "localities": {"value": n_loc, "display": _int(n_loc), "tone": "brand"},
        },
        "charts": {
            "dicts": {"names": [t[0] for t in sizes], "values": [t[1] for t in sizes]},
            "categories": {"names": [r["name"] for r in cat_rows],
                           "linked": [r["linked"] for r in cat_rows],
                           "free": [r["free"] for r in cat_rows]},
            "kinds": [{"name": r["name"], "value": r["value"]} for r in kind_rows],
            "reuse": {"names": [r["name"] for r in reuse_rows], "values": [r["value"] for r in reuse_rows]},
            "continents": {"names": [r["name"] for r in cont_rows],
                           "admin": [r["admin"] for r in cont_rows],
                           "geo": [r["geo"] for r in cont_rows]},
            "systems": {"names": [r["name"] for r in sys_rows], "values": [r["value"] for r in sys_rows]},
            "splits": {"names": [r["name"] for r in split_rows], "values": [r["value"] for r in split_rows]},
            "loc": {"districts": districts, "series": loc_series},
            "authorities": [{"name": r["name"], "value": r["value"]} for r in auth_rows],
            "councils": {"names": [r["name"] for r in council_rows], "values": [r["value"] for r in council_rows]},
            "neigh": {"names": [r["name"] for r in nb_rows], "values": [r["value"] for r in nb_rows]},
            "stypes": {"names": [r["name"] for r in stype_rows], "values": [r["value"] for r in stype_rows]},
            "snames": {"names": [r["name"] for r in sname_rows], "values": [r["value"] for r in sname_rows]},
            "prof": {"names": [r["name"] for r in prof_rows], "values": [r["value"] for r in prof_rows]},
            "inst": {"names": [r["name"] for r in inst_rows], "values": [r["value"] for r in inst_rows]},
        },
        "tables": {
            "dicts": [{"name": t[0], "value": t[1]} for t in sizes],
            "categories": cat_rows,
            "kinds": kind_rows,
            "reuse": reuse_rows,
            "continents": cont_rows,
            "systems": sys_rows,
            "splits": split_rows,
            "loc_groups": groups,
            "loc": loc_rows,
            "authorities": auth_rows,
            "councils": council_rows,
            "neigh": nb_rows,
            "stypes": stype_rows,
            "snames": sname_rows,
            "prof": prof_rows,
            "inst": inst_rows,
        },
        "insights": insights,
        "labels": {
            "lede": lede,
            "fields_kpi": "שדות ברשומת האדם המרכזית",
            "linked_kpi": "מהשדות מקושרים למילון קוד",
            "dicts_kpi": "מילוני קוד בספרייה",
            "values_kpi": "ערכים בכל המילונים יחד",
            "countries_kpi": "ארצות וטריטוריות במילון הארצות",
            "localities_kpi": "יישובים במילון היישובים",
            "dicts_lede": (f"{_int(n_dicts)} מילונים עם {_int(n_values)} ערכים. רוב המילונים קצרים "
                           f"(חציון {_int(sorted(t[1] for t in sizes)[len(sizes) // 2]) if sizes else '0'} ערכים), "
                           f"ומעטים ענקיים: {sizes[0][0] if sizes else ''} לבדו מחזיק "
                           f"{_pct(sizes[0][1] / n_values) if n_values else '0.0%'} מכלל הערכים. הציר לוגריתמי."),
            "dicts_aria": (f"גרף עמודות אופקי בציר לוגריתמי: מספר הערכים בכל אחד מ-{_int(n_dicts)} המילונים. "
                           f"הגדול: {sizes[0][0] if sizes else ''} עם {_int(sizes[0][1]) if sizes else '0'}."),
            "cat_lede": (f"{_int(n_fields)} השדות מחולקים ל-{_int(len(cat_rows))} קטגוריות. הגדולה היא "
                         f"{cat_rows[0]['name'] if cat_rows else ''} ({_int(cat_rows[0]['total']) if cat_rows else '0'} שדות). "
                         f"בכחול: שדות המקושרים למילון; באפור: שדות חופשיים."),
            "cat_aria": (f"גרף עמודות מוערמות: שדות רשומת האדם לפי קטגוריה, מקושרים למילון מול חופשיים. "
                         f"{_int(linked)} מתוך {_int(n_fields)} מקושרים."),
            "kinds_lede": (f"סוג השדה נגזר מסיומת שמו באנגלית (code, flag, id, date, number). "
                           f"הנפוץ: {kind_rows[0]['name'] if kind_rows else ''} ({kind_rows[0]['share'] if kind_rows else ''})."),
            "kinds_aria": (f"גרף טבעת: התפלגות {_int(n_fields)} שדות הרשומה לפי סוג. "
                           f"הנפוץ: {kind_rows[0]['name'] if kind_rows else ''}."),
            "reuse_lede": (f"הרשומה מפנה ל-{_int(n_codelists)} מילוני קוד. אלה המילונים שמשמשים "
                           f"הכי הרבה שדות"
                           + (f"; המוביל, {reuse_rows[0]['name']}, משמש {_int(reuse_rows[0]['value'])} שדות: "
                              f"{reuse_rows[0]['fields']}." if reuse_rows else ".")),
            "reuse_aria": (f"גרף עמודות אופקי: מספר השדות ברשומה שמשתמשים בכל מילון קוד. "
                           f"המוביל: {reuse_rows[0]['name'] if reuse_rows else ''} עם {_int(reuse_rows[0]['value']) if reuse_rows else '0'} שדות."),
            "cont_lede": (f"לכל אחת מ-{_int(n_countries)} הארצות יש שתי יבשות: ה\"יבשת\" שבה משתמשת רשות "
                          f"האוכלוסין, והיבשת הגיאוגרפית. {_int(len(mism))} ארצות מסווגות אחרת בשתיהן. "
                          + (f"השכיח: {_int(pair.iloc[0].n)} ארצות שגיאוגרפית ב{pair.iloc[0].geo} מסווגות כ{pair.iloc[0].cont}."
                             if not pair.empty else "")),
            "cont_aria": (f"גרף עמודות כפולות: מספר הארצות בכל יבשת לפי רשות האוכלוסין ולפי הגיאוגרפיה. "
                          f"{_int(len(mism))} ארצות שונות בין השתיים."),
            "sys_lede": (f"כל ארץ נושאת קוד לפי התקן הישראלי; לא לכולן יש גם קוד של רשות האוכלוסין "
                         f"או סמל או״ם, ולכן חשוב לבחור את מערכת הקוד הנכונה בעת חיבור מערכות."),
            "sys_aria": (f"גרף עמודות: {_int(n_countries)} הארצות לפי מערכות הקוד שבהן הן מופיעות. "
                         f"{_int(sys_rows[0]['value']) if sys_rows else '0'} {sys_rows[0]['name'] if sys_rows else ''}."),
            "splits_lede": (f"{_int(len(splits))} ארצות מסומנות כנגזרות מישות קודמת ברשות האוכלוסין, "
                            f"ונרשמה להן שנת שינוי. כך אפשר לקשר רישום ישן (למשל ארץ לידה בריה\"מ) לארץ של היום."),
            "splits_aria": (f"גרף עמודות אופקי: מספר הארצות שנגזרו מכל ישות קודמת. "
                            f"המובילה: {split_rows[0]['name'] if split_rows else ''} עם {_int(split_rows[0]['value']) if split_rows else '0'}."),
            "loc_lede": (f"{_int(n_loc)} יישובים ב-{_int(len(districts))} מחוזות, לפי צורת היישוב "
                         f"(קובצה לקבוצות; היישובים העירוניים הם יישובים של אלפיים תושבים ומעלה)."),
            "loc_aria": (f"גרף עמודות מוערמות: יישובים בכל מחוז לפי צורת יישוב. "
                         f"המחוז המוביל: {districts[0] if districts else ''} עם {_int(dist_tot.iloc[0]) if len(dist_tot) else '0'}."),
            "auth_lede": (f"{_int(n_auth)} רשויות מקומיות לפי סוג. מעמדו המוניציפלי של כל יישוב במילון היישובים "
                          f"מצביע על עירייה, מועצה מקומית או שם המועצה האזורית שאליה הוא שייך."),
            "auth_aria": (f"גרף טבעת: {_int(n_auth)} רשויות מקומיות לפי סוג. "
                          f"הנפוץ: {auth_rows[0]['name'] if auth_rows else ''} ({_int(auth_rows[0]['value']) if auth_rows else '0'})."),
            "councils_lede": (f"{_int(len(in_rc))} יישובים שייכים למועצות אזוריות. אלה {_int(len(council_rows))} "
                              f"המועצות עם מספר היישובים הגדול ביותר."),
            "councils_aria": (f"גרף עמודות אופקי: מספר היישובים בכל מועצה אזורית, {_int(len(council_rows))} המובילות. "
                              f"הגדולה: {council_rows[0]['name'] if council_rows else ''} עם {_int(council_rows[0]['value']) if council_rows else '0'}."),
            "neigh_lede": (f"מילון השכונות מונה {_int(n_nb)} שכונות ב-{_int(n_nb_cities)} ערים. "
                           f"אלה {_int(len(nb_rows))} הערים עם הכי הרבה שכונות מוגדרות."),
            "neigh_aria": (f"גרף עמודות אופקי: מספר השכונות בכל עיר, {_int(len(nb_rows))} המובילות. "
                           f"המובילה: {nb_rows[0]['name'] if nb_rows else ''} עם {_int(nb_rows[0]['value']) if nb_rows else '0'}."),
            "stypes_lede": (f"{_int(n_streets)} שמות רחובות (בלי {_int(n_locality_rows)} רשומות קוד "
                            f"{LOCALITY_ROW_CODE} שמייצגות את היישוב עצמו), לפי הקידומת המקוצרת שבשם כפי שהיא "
                            f"נרשמת במרשם: רח, שכ, שד, סמ ועוד."),
            "stypes_aria": (f"גרף עמודות אופקי: שמות הרחובות לפי סוג הדרך שמופיע בשם. "
                            f"הנפוץ: {stype_rows[0]['name'] if stype_rows else ''} ({stype_rows[0]['share'] if stype_rows else ''})."),
            "snames_lede": (f"השמות שחוזרים הכי הרבה פעמים במילון (שמות ללא קידומת סוג). כל יישוב רושם את רחובותיו "
                            f"בנפרד, ולכן שם נפוץ מופיע פעם אחת בכל יישוב שבו הוא קיים."),
            "snames_aria": (f"גרף עמודות אופקי: {_int(len(sname_rows))} שמות הרחובות הנפוצים. "
                            f"המוביל: {sname_rows[0]['name'] if sname_rows else ''} עם {_int(sname_rows[0]['value']) if sname_rows else '0'} הופעות."),
            "prof_lede": (f"{_int(n_prof)} מקצועות לימוד מקובצים לפי תחומי לימודים. "
                          f"התחום עם הכי הרבה מקצועות: {prof_rows[0]['name'] if prof_rows else ''} ({_int(prof_rows[0]['value']) if prof_rows else '0'})."),
            "prof_aria": (f"גרף עמודות אופקי: מספר מקצועות הלימוד בכל תחום לימודים. "
                          f"המוביל: {prof_rows[0]['name'] if prof_rows else ''}."),
            "inst_lede": (f"{_int(n_inst)} מוסדות להשכלה גבוהה לפי סוג, כפי שמסווג במילון "
                          f"(כולל ערכי מערכת כלליים)."),
            "inst_aria": (f"גרף עמודות: {_int(n_inst)} מוסדות להשכלה גבוהה לפי סוג. "
                          f"הנפוץ: {inst_rows[0]['name'] if inst_rows else ''} ({_int(inst_rows[0]['value']) if inst_rows else '0'})."),
        },
    }
