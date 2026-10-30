"""ספריית מילוני נתונים: טרמינולוגיית נתוני נכס (מערך הדיגיטל הלאומי).

A data dictionary, not an event table.  Seventeen resources:

* ``record``: the central asset record, one row per field (category, Hebrew
  name, English name, linked code list, note).  The English name's suffix
  (``_flag``, ``_code``, ``_id``, ``_date`` ...) tells the field's kind.
* twelve small code lists (``Code`` + Hebrew name + optional description):
  asset types, housing types, usages, ownership types/nature, operators,
  ownership-change types, registration status, legal restrictions, plan
  types, air directions, infrastructure types and sub-types (sub-type code
  // 100 = its type code).
* three large reference lists: localities (district, sub-district, form,
  municipal status, natural region, cluster), CBS statistical areas per
  locality, and street names (code + name, no locality column).

The page profiles the structure of the dictionary itself: which field kinds
the record is made of, how big each list is, how the locality list splits by
district/municipal status/form/size, where statistical areas are dense, and
how Israeli streets are named.  Every sort is total (value, then label), so
row order never matters.
"""
import re

import pandas as pd

TOP_N = 15
MAX_INSIGHTS = 9

SMALL_LISTS = [
    ("asset_types", "סוגי נכסים"),
    ("housing", "סוגי דיור"),
    ("usage", "שימושים בנכס"),
    ("ownership", "סוגי בעלות בנכס"),
    ("ownership_nature", "אופי בעלות בנכס"),
    ("operators", "גופים מפעילים"),
    ("ownership_change", "סוגי שינוי בעלות"),
    ("reg_status", "סטטוס רישום"),
    ("legal", "הגבלות משפטיות"),
    ("plans", "סוגי תכניות"),
    ("directions", "כיווני אוויר"),
    ("infra_types", "סוגי תשתיות"),
    ("infra_subtypes", "תת סוגי תשתיות"),
]
NAME_COLS = ["Name_Hebrew", "Name_Hbrew", "Column1"]

KIND_RULES = [
    ("_flag", "שדה כן/לא"),
    ("_code", "קוד מסווג"),
    ("_id", "מזהה"),
    ("_date", "תאריך"),
    ("_year", "שנה"),
    ("_amount", "סכום או כמות"),
    ("_number", "סכום או כמות"),
    ("_count", "סכום או כמות"),
    ("_name", "שם"),
]
KIND_ORDER = ["שדה כן/לא", "קוד מסווג", "מזהה", "סכום או כמות", "תאריך", "שנה", "שם", "אחר"]

MUNI_ORDER = ["עירייה", "מועצה מקומית", "מועצה אזורית", "ללא שיוך"]

STREET_TOKEN = {
    "שכ": "שכונה", "שכונת": "שכונה", "שכונה": "שכונה",
    "ש": "שיכון",
    "דרך": "דרך",
    "משעול": "משעול",
    "סמ": "סמטה", "סמטת": "סמטה", "סמטה": "סמטה",
    "ככר": "כיכר", "כיכר": "כיכר",
    "שד": "שדרה", "שדרות": "שדרה", "שד'": "שדרה",
    "שביל": "שביל",
    "מבוא": "מבוא",
    "הרב": "על שם רב", "רבי": "על שם רב", "הרבי": "על שם רב",
    "קרית": "קריה", "קריית": "קריה",
    "אזור": "אזור",
    "רחבת": "רחבה",
    "מעלה": "מעלה", "מעלות": "מעלה",
}
PLAIN_STREET = "שם ללא תחילית"


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def clean(s):
    return s.astype(str).str.replace(" ", " ", regex=False).str.strip()


def name_col(df):
    for c in NAME_COLS:
        if c in df.columns:
            return c
    return None


def code_list(df):
    """Return a clean frame (code:int, name:str, desc:bool) without blank rows."""
    nc = name_col(df)
    code = pd.to_numeric(clean(df["Code"]), errors="coerce")
    name = clean(df[nc]) if nc else pd.Series([""] * len(df), index=df.index)
    desc = clean(df["Description_Hebrew"]) if "Description_Hebrew" in df.columns else pd.Series([""] * len(df), index=df.index)
    out = pd.DataFrame({"code": code, "name": name, "has_desc": desc != ""})
    out = out[out["code"].notna() & (out["name"] != "")].copy()
    out["code"] = out["code"].astype(int)
    out = out.sort_values(["code", "name"], kind="mergesort").drop_duplicates(["code", "name"])
    return out.reset_index(drop=True)


def field_kind(en):
    e = en.lower().strip()
    for suf, lab in KIND_RULES:
        if e.endswith(suf):
            return lab
    return "אחר"


def ranked(counts, n=None):
    """counts: dict label->int → list of (label, n) sorted desc then label."""
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:n] if n else items


def top_with_other(counts, n):
    items = ranked(counts)
    head = items[:n]
    rest = sum(v for _, v in items[n:])
    if rest:
        head.append(("אחר", rest))
    return head


def table(headers, rows):
    return {"headers": headers, "rows": rows}


def muni_kind(v):
    v = v.strip()
    if v == "עירייה":
        return "עירייה"
    if v == "מועצה מקומית":
        return "מועצה מקומית"
    if v == "":
        return "ללא שיוך"
    return "מועצה אזורית"


BAND_RE = re.compile(r"(\d+)\s*-\s*(\d+)\s*תושבים")
BAND_UP_RE = re.compile(r"(\d+)\s*תושבים ומעלה")


def form_family(v):
    v = BAND_RE.sub("", v)
    v = BAND_UP_RE.sub("", v)
    return re.sub(r"\s+", " ", v).strip(" -")


def form_band(v):
    m = BAND_RE.search(v)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    m = BAND_UP_RE.search(v)
    if m:
        return (int(m.group(1)), None)
    return None


def band_label(b):
    lo, hi = b
    if hi is None:
        return f"{fmt(lo)} ומעלה"
    return f"{fmt(lo)}-{fmt(hi + 1)}"


def street_type(name):
    n = re.sub(r"\s+", " ", name).strip()
    if re.match(r"^רח\s", n):
        return "רחוב ממוספר או באות"
    if re.search(r"סמ\s*\d+$", n):
        return "סמטה ממוספרת"
    tok = n.split(" ")[0] if n else ""
    return STREET_TOKEN.get(tok, PLAIN_STREET)


def compute(frames):
    labels, charts, tables, kpis = {}, {}, {}, {}
    ins = {}

    # ── central record ────────────────────────────────────────────────
    rec = frames["record"].copy()
    rec["cat"] = clean(rec["Category"])
    rec["he"] = clean(rec["Name_Hebrew"])
    rec["en"] = clean(rec["Name_English"])
    rec["cl"] = clean(rec["Codelist_Name_Hebrew"])
    rec["desc"] = clean(rec["Description_Hebrew"])
    rec = rec[(rec["he"] != "") | (rec["en"] != "")].copy()
    rec.loc[rec["cat"] == "", "cat"] = "ללא קטגוריה"
    rec["kind"] = rec["en"].map(field_kind)
    n_fields = len(rec)

    cat_counts = rec.groupby("cat").size().to_dict()
    cats = [c for c, _ in ranked(cat_counts)]
    kinds = [k for k in KIND_ORDER if (rec["kind"] == k).any()]
    ct = rec.groupby(["cat", "kind"]).size()
    charts["fields"] = {
        "cats": cats,
        "kinds": kinds,
        "series": [[int(ct.get((c, k), 0)) for c in cats] for k in kinds],
        "linked": [int(((rec["cat"] == c) & (rec["cl"] != "")).sum()) for c in cats],
    }
    tables["fields"] = table(
        ["קטגוריה", "שדות"] + kinds + ["מקושרים למילון"],
        [[c, fmt(cat_counts[c])] + [fmt(ct.get((c, k), 0)) for k in kinds] + [fmt(charts["fields"]["linked"][i])] for i, c in enumerate(cats)],
    )
    kind_counts = rec.groupby("kind").size().to_dict()
    n_linked = int((rec["cl"] != "").sum())
    n_lists_ref = int(rec.loc[rec["cl"] != "", "cl"].nunique())
    n_desc = int((rec["desc"] != "").sum())
    n_flag = int(kind_counts.get("שדה כן/לא", 0))

    kpis["fields"] = {"value": n_fields, "display": fmt(n_fields), "tone": "brand"}
    desc_share = n_desc / n_fields if n_fields else 0
    kpis["documented"] = {
        "value": round(desc_share * 100, 1),
        "display": pct(desc_share),
        "tone": "warn" if desc_share < 0.5 else "ok",
    }
    labels["fields_note"] = (
        f"הרשומה המרכזית מונה {fmt(n_fields)} שדות ב-{fmt(len(cats))} קטגוריות. "
        f"{fmt(n_linked)} מהם מקושרים למילון קוד ({fmt(n_lists_ref)} מילונים שונים)."
    )
    labels["fields_aria"] = (
        f"גרף עמודות מוערמות: שדות הרשומה המרכזית לפי קטגוריה וסוג שדה. "
        f"הקטגוריה הגדולה: {cats[0]} עם {fmt(cat_counts[cats[0]])} שדות." if cats else "גרף עמודות: שדות הרשומה המרכזית"
    )
    if cats and n_fields:
        top_c = cats[0]
        second = cat_counts[cats[1]] if len(cats) > 1 else 0
        if cat_counts[top_c] > second:
            ins["record_cat"] = (
                f"הקטגוריה הגדולה ברשומה המרכזית היא \"{top_c}\" עם {fmt(cat_counts[top_c])} שדות "
                f"({pct(cat_counts[top_c] / n_fields)} מ-{fmt(n_fields)} השדות)."
            )
    flag_names = rec[rec["kind"] == "שדה כן/לא"]["he"].str.replace(r"^האם\s+", "", regex=True)
    flag_ex = ", ".join(sorted(flag_names[flag_names != ""].unique().tolist())[:3])
    if n_fields and n_flag / n_fields >= 0.2 and flag_ex:
        ins["flags"] = (
            f"{fmt(n_flag)} שדות ({pct(n_flag / n_fields)}) הם שדות כן/לא, למשל: {flag_ex}; "
            f"רק {fmt(n_linked)} שדות מפנים למילון קוד."
        )
    if n_fields:
        ins["docs"] = (
            f"רק ל-{fmt(n_desc)} מתוך {fmt(n_fields)} השדות ({pct(desc_share)}) יש הערת הסבר ברשומה המרכזית."
            if desc_share < 0.5 else
            f"ל-{fmt(n_desc)} מתוך {fmt(n_fields)} השדות ({pct(desc_share)}) יש הערת הסבר ברשומה המרכזית."
        )

    # ── small code lists ──────────────────────────────────────────────
    lists = {}
    for key, title in SMALL_LISTS:
        lists[key] = code_list(frames[key])
    sizes = [(title, len(lists[key]), key) for key, title in SMALL_LISTS if len(lists[key])]
    sizes.sort(key=lambda t: (-t[1], t[0]))
    charts["lists"] = {"names": [t[0] for t in sizes], "values": [t[1] for t in sizes]}
    lrows = []
    for title, n, key in sizes:
        df = lists[key]
        ex = ", ".join(df["name"].head(3).tolist())
        lrows.append([title, fmt(n), pct(df["has_desc"].mean()), ex])
    tables["lists"] = table(["מילון", "ערכים", "עם תיאור", "ערכים ראשונים"], lrows)
    n_small_values = sum(t[1] for t in sizes)
    n_unknown_lists = sum(1 for _, _, k in sizes if (lists[k]["code"] == 99).any())
    labels["lists_note"] = (
        f"{fmt(len(sizes))} מילוני קוד קטנים עם {fmt(n_small_values)} ערכים בסך הכול. "
        f"{fmt(n_unknown_lists)} מהם שומרים את הקוד 99 לערך ברירת מחדל כמו \"לא ידוע\"."
    )
    if sizes:
        labels["lists_aria"] = f"גרף עמודות אופקי: מספר הערכים בכל מילון קוד. הגדול ביותר: {sizes[0][0]} עם {fmt(sizes[0][1])} ערכים."
        ins["lists"] = (
            f"המילון המפורט ביותר בין המילונים הקטנים הוא \"{sizes[0][0]}\" עם {fmt(sizes[0][1])} ערכים, "
            f"והקטן ביותר \"{sizes[-1][0]}\" עם {fmt(sizes[-1][1])} ערכים."
        ) if len(sizes) > 1 and sizes[0][1] > sizes[-1][1] else None
    else:
        labels["lists_aria"] = "גרף עמודות אופקי: מספר הערכים בכל מילון קוד."

    # usage families (codes grouped by tens)
    us = lists["usage"].copy()
    fam_rows = []
    if len(us):
        us["fam"] = us["code"] // 10
        for fam, g in us.groupby("fam", sort=True):
            g = g.sort_values(["code", "name"], kind="mergesort")
            lo, hi = int(fam) * 10, int(fam) * 10 + 9
            fam_rows.append({
                "label": f"{g['name'].iloc[0]} ועוד",
                "range": f"{lo}-{hi}",
                "n": len(g),
                "names": g["name"].tolist()[:8],
            })
    charts["usage"] = {
        "names": [f["label"] for f in fam_rows],
        "values": [f["n"] for f in fam_rows],
        "ranges": [f["range"] for f in fam_rows],
        "members": [f["names"] for f in fam_rows],
    }
    tables["usage"] = table(["קבוצת קודים", "טווח", "ערכים", "דוגמאות"],
                            [[f["label"], f["range"], fmt(f["n"]), ", ".join(f["names"][:4])] for f in fam_rows])
    if fam_rows:
        big = sorted(fam_rows, key=lambda f: (-f["n"], f["range"]))[0]
        labels["usage_note"] = (
            f"מילון השימושים בנוי בקבוצות של עשרות קודים: {fmt(len(us))} שימושים ב-{fmt(len(fam_rows))} קבוצות. "
            f"הקבוצה הגדולה ({big['range']}) מתחילה ב\"{big['names'][0]}\" ומונה {fmt(big['n'])} שימושים."
        )
        labels["usage_aria"] = f"גרף עמודות אופקי: מספר השימושים בכל קבוצת קודים. הגדולה: {big['label']} עם {fmt(big['n'])}."
    else:
        labels["usage_note"] = "מילון השימושים ריק."
        labels["usage_aria"] = "גרף עמודות אופקי: שימושים לפי קבוצת קודים."

    # infrastructure tree
    it, isub = lists["infra_types"], lists["infra_subtypes"]
    tname = dict(zip(it["code"], it["name"]))
    tree = []
    for code in sorted(set(it["code"]) | set(isub["code"] // 100)):
        subs = isub[isub["code"] // 100 == code].sort_values(["code", "name"], kind="mergesort")
        nm = tname.get(code, f"קוד {code}")
        tree.append({"name": nm, "value": int(len(subs)), "children": [{"name": s, "value": 1} for s in subs["name"]]})
    tree = [t for t in tree if t["value"] > 0]
    tree.sort(key=lambda t: (-t["value"], t["name"]))
    charts["infra"] = tree
    tables["infra"] = table(["סוג תשתית", "תת סוגים", "דוגמאות"],
                            [[t["name"], fmt(t["value"]), ", ".join(c["name"] for c in t["children"][:4])] for t in tree])
    n_sub = sum(t["value"] for t in tree)
    if tree:
        labels["infra_note"] = (
            f"{fmt(n_sub)} תת סוגי תשתית ממוינים תחת {fmt(len(tree))} סוגים (הספרה הראשונה בקוד תת הסוג היא קוד הסוג). "
            f"הענף המפורט ביותר: {tree[0]['name']} עם {fmt(tree[0]['value'])} תת סוגים."
        )
        labels["infra_aria"] = f"מפת ריבועים: תת סוגי תשתית לפי סוג. הגדול: {tree[0]['name']} עם {fmt(tree[0]['value'])}."
        if len(tree) > 1 and tree[0]["value"] > tree[1]["value"]:
            ins["infra"] = (
                f"במילון התשתיות {fmt(n_sub)} תת סוגים; \"{tree[0]['name']}\" מפורט ביותר עם {fmt(tree[0]['value'])} "
                f"(למשל {', '.join(c['name'] for c in tree[0]['children'][:3])})."
            )
    else:
        labels["infra_note"] = "אין תת סוגי תשתית במילון."
        labels["infra_aria"] = "מפת ריבועים: תת סוגי תשתית לפי סוג."

    # ── localities ────────────────────────────────────────────────────
    loc = frames["localities"].copy()
    for c in ["Code", "Name_Hebrew", "District", "נפה", "צורת יישוב", "מעמד מוניציפלי", "Natural_Region", "אשכול רשויות מקומיות"]:
        loc[c] = clean(loc[c])
    loc = loc[loc["Name_Hebrew"] != ""].copy()
    loc = loc.sort_values(["Code", "Name_Hebrew"], kind="mergesort").drop_duplicates(["Code", "Name_Hebrew"])
    n_loc = len(loc)
    loc["District"] = loc["District"].replace("", "ללא מחוז")
    loc["muni"] = loc["מעמד מוניציפלי"].map(muni_kind)
    kpis["localities"] = {"value": n_loc, "display": fmt(n_loc), "tone": "brand"}

    dcount = loc.groupby("District").size().to_dict()
    dists = [d for d, _ in ranked(dcount)]
    munis = [m for m in MUNI_ORDER if (loc["muni"] == m).any()]
    dm = loc.groupby(["District", "muni"]).size()
    charts["districts"] = {"names": dists, "munis": munis,
                           "series": [[int(dm.get((d, m), 0)) for d in dists] for m in munis]}
    tables["districts"] = table(["מחוז", "יישובים"] + munis,
                                [[d, fmt(dcount[d])] + [fmt(dm.get((d, m), 0)) for m in munis] for d in dists])
    mcount = loc.groupby("muni").size().to_dict()
    reg_share = mcount.get("מועצה אזורית", 0) / n_loc if n_loc else 0
    if dists:
        labels["districts_note"] = (
            f"{fmt(n_loc)} יישובים ב-{fmt(len(dists))} מחוזות. {pct(reg_share)} מהיישובים שייכים למועצה אזורית, "
            f"{fmt(mcount.get('עירייה', 0))} הם עיריות ו-{fmt(mcount.get('מועצה מקומית', 0))} מועצות מקומיות."
        )
        labels["districts_aria"] = f"גרף עמודות מוערמות: יישובים לפי מחוז ומעמד מוניציפלי. המחוז עם הכי הרבה יישובים: {dists[0]} עם {fmt(dcount[dists[0]])}."
        if len(dists) > 1 and dcount[dists[0]] > dcount[dists[1]]:
            ins["district"] = (
                f"מחוז {dists[0]} מוביל במספר היישובים במילון: {fmt(dcount[dists[0]])} מתוך {fmt(n_loc)} ({pct(dcount[dists[0]] / n_loc)}), "
                f"ומחוז {dists[-1]} מונה רק {fmt(dcount[dists[-1]])}."
            )
        if reg_share >= 0.5:
            ins["regional"] = (
                f"רוב היישובים ({pct(reg_share)}) שייכים למועצה אזורית; עיריות הן רק {fmt(mcount.get('עירייה', 0))} יישובים "
                f"({pct(mcount.get('עירייה', 0) / n_loc)})."
            )
    else:
        labels["districts_note"] = "אין יישובים במילון."
        labels["districts_aria"] = "גרף עמודות: יישובים לפי מחוז."

    # sub-districts
    nafa = loc["נפה"].replace("", "ללא נפה")
    ncount = nafa.value_counts().to_dict()
    nitems = top_with_other(ncount, TOP_N)
    charts["nafa"] = {"names": [k for k, _ in nitems], "values": [int(v) for _, v in nitems]}
    tables["nafa"] = table(["נפה", "יישובים"], [[k, fmt(v)] for k, v in nitems])
    real_n = {k: v for k, v in ncount.items() if k != "ללא נפה"}
    rn = ranked(real_n)
    no_nafa = ncount.get("ללא נפה", 0)
    if rn:
        labels["nafa_note"] = (
            f"{fmt(len(rn))} נפות. הגדולה: {rn[0][0]} עם {fmt(rn[0][1])} יישובים."
            + (f" ל-{fmt(no_nafa)} יישובים לא רשומה נפה." if no_nafa else "")
        )
        labels["nafa_aria"] = f"גרף עמודות אופקי: יישובים לפי נפה. הגדולה: {rn[0][0]} עם {fmt(rn[0][1])} יישובים."
    else:
        labels["nafa_note"] = "לא רשומות נפות במילון."
        labels["nafa_aria"] = "גרף עמודות אופקי: יישובים לפי נפה."
    if no_nafa and n_loc:
        nn = loc[loc["נפה"] == ""]["District"].value_counts()
        nn = ranked(nn.to_dict())
        if nn and nn[0][1] / no_nafa >= 0.5:
            ins["nafa_gap"] = (
                f"ל-{fmt(no_nafa)} יישובים ({pct(no_nafa / n_loc)}) אין נפה במילון, {fmt(nn[0][1])} מהם במחוז {nn[0][0]}."
            )

    # settlement form
    loc["family"] = loc["צורת יישוב"].map(form_family).replace("", "לא צוין")
    fcount = loc.groupby("family").size().to_dict()
    fitems = top_with_other(fcount, 12)
    charts["forms"] = {"names": [k for k, _ in fitems], "values": [int(v) for _, v in fitems]}
    tables["forms"] = table(["צורת יישוב", "יישובים"], [[k, fmt(v)] for k, v in fitems])
    fr = ranked(fcount)
    if fr:
        labels["forms_note"] = (
            f"צורות היישוב כפי שהן במילון, כשטווח האוכלוסייה מקובץ לצורה אחת. "
            f"הנפוצה: {fr[0][0]} ({fmt(fr[0][1])} יישובים)."
        )
        labels["forms_aria"] = f"גרף עמודות אופקי: יישובים לפי צורת יישוב. הנפוצה: {fr[0][0]} עם {fmt(fr[0][1])}."
        kib = fcount.get("קיבוצים", 0)
        mosh = sum(v for k, v in fcount.items() if k.startswith("מושבים"))
        if n_loc and (kib + mosh) / n_loc >= 0.3:
            ins["rural"] = (
                f"מושבים ({fmt(mosh)}) וקיבוצים ({fmt(kib)}) הם {pct((kib + mosh) / n_loc)} מרשימת היישובים"
                + (", " if (kib + mosh) / n_loc >= 0.5 else ": ")
                + ("ולכן רוב הערכים במילון הם יישובים כפריים." if (kib + mosh) / n_loc >= 0.5 else "חלק ניכר מהרשימה.")
            )
    else:
        labels["forms_note"] = "לא צוינו צורות יישוב."
        labels["forms_aria"] = "גרף עמודות אופקי: יישובים לפי צורת יישוב."

    # population bands (families that carry a band)
    loc["band"] = loc["צורת יישוב"].map(form_band)
    banded = loc[loc["band"].notna()].copy()
    fam_bands = banded.groupby("family")["band"].nunique()
    sfam = [f for f, _ in ranked(banded.groupby("family").size().to_dict()) if fam_bands.get(f, 0) >= 3][:4]
    bands = sorted(set(banded.loc[banded["family"].isin(sfam), "band"]), key=lambda b: (b[0], b[1] if b[1] is not None else 10**12))
    bc = banded.groupby(["family", "band"]).size()
    charts["sizes"] = {
        "bands": [band_label(b) for b in bands],
        "fams": sfam,
        "series": [[int(bc.get((f, b), 0)) for b in bands] for f in sfam],
    }
    tables["sizes"] = table(["תושבים"] + sfam, [[band_label(b)] + [fmt(bc.get((f, b), 0)) for f in sfam] for b in bands])
    charts["has_sizes"] = bool(sfam and bands)
    if charts["has_sizes"]:
        tot_b = int(banded["family"].isin(sfam).sum())
        labels["sizes_note"] = (
            f"{fmt(tot_b)} יישובים שהמילון מסווג לפי טווח אוכלוסייה ({', '.join(sfam)}). "
            f"ישובים כפריים ללא טווח אינם בתרשים."
        )
        big = max(((band_label(b), int(bc.get((f, b), 0)), f) for f in sfam for b in bands), key=lambda t: (t[1], t[0]))
        labels["sizes_aria"] = f"גרף עמודות מקובצות: יישובים לפי טווח אוכלוסייה. השכיח: {big[2]} בטווח {big[0]} תושבים עם {fmt(big[1])} יישובים."
        top_band = bands[-1]
        tb = sum(int(bc.get((f, top_band), 0)) for f in sfam)
        if tb:
            ins["big_cities"] = (
                f"בטווח האוכלוסייה הגבוה במילון ({band_label(top_band)} תושבים) "
                + ("יש יישוב אחד" if tb == 1 else f"יש {fmt(tb)} יישובים")
                + f", ואילו הטווח השכיח הוא {big[0]} תושבים ({fmt(big[1])} {big[2]})."
            )
    else:
        labels["sizes_note"] = ""
        labels["sizes_aria"] = ""

    # regional councils
    rc = loc[loc["muni"] == "מועצה אזורית"]["מעמד מוניציפלי"].value_counts().to_dict()
    rci = ranked(rc, TOP_N)
    charts["councils"] = {"names": [k for k, _ in rci], "values": [int(v) for _, v in rci]}
    tables["councils"] = table(["מועצה אזורית", "יישובים"], [[k, fmt(v)] for k, v in rci])
    kpis["councils"] = {"value": len(rc), "display": fmt(len(rc)), "tone": "brand"}
    if rci:
        labels["councils_note"] = (
            f"{fmt(len(rc))} מועצות אזוריות מופיעות במילון; מוצגות {fmt(len(rci))} עם הכי הרבה יישובים. "
            f"בראש: {rci[0][0]} עם {fmt(rci[0][1])} יישובים."
        )
        labels["councils_aria"] = f"גרף עמודות אופקי: מועצות אזוריות לפי מספר יישובים. בראש: {rci[0][0]} עם {fmt(rci[0][1])}."
        if len(rci) > 1 and rci[0][1] > rci[1][1]:
            ins["council"] = (
                f"המועצה האזורית עם הכי הרבה יישובים היא {rci[0][0]} ({fmt(rci[0][1])}), לפני {rci[1][0]} ({fmt(rci[1][1])}); "
                f"במילון {fmt(len(rc))} מועצות אזוריות."
            )
    else:
        labels["councils_note"] = "אין מועצות אזוריות במילון."
        labels["councils_aria"] = "גרף עמודות אופקי: מועצות אזוריות."

    # clusters
    cl = loc["אשכול רשויות מקומיות"].replace("", "ללא שיוך לאשכול")
    clc = cl.value_counts().to_dict()
    cli = ranked(clc, TOP_N)
    charts["clusters"] = {"names": [k for k, _ in cli], "values": [int(v) for _, v in cli]}
    tables["clusters"] = table(["אשכול", "יישובים"], [[k, fmt(v)] for k, v in cli])
    no_cl = clc.get("ללא שיוך לאשכול", 0)
    real_cl = ranked({k: v for k, v in clc.items() if k != "ללא שיוך לאשכול"})
    labels["clusters_note"] = (
        f"{fmt(len(real_cl))} אשכולות רשויות. {fmt(no_cl)} יישובים ({pct(no_cl / n_loc if n_loc else 0)}) אינם משויכים לאשכול."
        + (f" האשכול הגדול: {real_cl[0][0]} ({fmt(real_cl[0][1])})." if real_cl else "")
    )
    labels["clusters_aria"] = (
        f"גרף עמודות אופקי: יישובים לפי אשכול רשויות מקומיות. האשכול הגדול: {real_cl[0][0]} עם {fmt(real_cl[0][1])}."
        if real_cl else "גרף עמודות אופקי: יישובים לפי אשכול רשויות."
    )
    if real_cl and n_loc and no_cl / n_loc >= 0.2:
        ins["clusters"] = (
            f"{fmt(no_cl)} יישובים ({pct(no_cl / n_loc)}) אינם משויכים לאף אשכול רשויות; "
            f"הגדול באשכולות הוא {real_cl[0][0]} עם {fmt(real_cl[0][1])} יישובים."
        )

    # natural regions
    nr = loc["Natural_Region"]
    nrc = ranked(nr[nr != ""].value_counts().to_dict())
    kpis["regions"] = {"value": len(nrc), "display": fmt(len(nrc)), "tone": "brand"}
    nri = nrc[:TOP_N]
    charts["regions"] = {"names": [k for k, _ in nri], "values": [int(v) for _, v in nri]}
    tables["regions"] = table(["אזור טבעי", "יישובים"], [[k, fmt(v)] for k, v in nri])
    no_nr = int((nr == "").sum())
    labels["regions_note"] = (
        f"{fmt(len(nrc))} אזורים טבעיים; מוצגים {fmt(len(nri))} הגדולים."
        + (f" ל-{fmt(no_nr)} יישובים לא רשום אזור טבעי." if no_nr else "")
    )
    labels["regions_aria"] = (
        f"גרף עמודות אופקי: יישובים לפי אזור טבעי. הגדול: {nri[0][0]} עם {fmt(nri[0][1])}." if nri else "גרף עמודות אופקי: יישובים לפי אזור טבעי."
    )

    # ── statistical areas ─────────────────────────────────────────────
    sa = frames["stat_areas"].copy()
    for c in ["Name_Hebrew", "Full_Statistic_Area_Code", "סמל יישוב", "אזורים סטטיסטיים", "רחובות עיקריים", "שכונות"]:
        sa[c] = clean(sa[c])
    sa = sa[(sa["Full_Statistic_Area_Code"] != "") | (sa["Name_Hebrew"] != "")]
    sa = sa.sort_values(["Full_Statistic_Area_Code", "Name_Hebrew", "אזורים סטטיסטיים"], kind="mergesort").drop_duplicates()
    n_sa = len(sa)
    kpis["stat_areas"] = {"value": n_sa, "display": fmt(n_sa), "tone": "brand"}
    sac = sa.groupby("Name_Hebrew").size().to_dict()
    n_sa_loc = len(sac)
    sai = ranked(sac, TOP_N)
    charts["statareas"] = {"names": [k for k, _ in sai], "values": [int(v) for _, v in sai]}
    tables["statareas"] = table(["יישוב", "אזורים סטטיסטיים"], [[k, fmt(v)] for k, v in sai])
    has_nb = float((sa["שכונות"] != "").mean()) if n_sa else 0.0
    has_st = float((sa["רחובות עיקריים"] != "").mean()) if n_sa else 0.0
    if sai:
        top5 = sum(v for _, v in sai[:5])
        labels["statareas_note"] = (
            f"{fmt(n_sa)} אזורים סטטיסטיים ב-{fmt(n_sa_loc)} יישובים בלבד (מתוך {fmt(n_loc)} במילון היישובים). "
            f"לכל אזור רשומים רחובות עיקריים ב-{pct(has_st)} מהמקרים ושכונות ב-{pct(has_nb)}."
        )
        labels["statareas_aria"] = f"גרף עמודות אופקי: היישובים עם הכי הרבה אזורים סטטיסטיים. בראש: {sai[0][0]} עם {fmt(sai[0][1])}."
        if n_sa and len(sai) >= 5:
            ins["statareas"] = (
                f"חמשת היישובים המפורטים ביותר ({', '.join(k for k, _ in sai[:5])}) מחזיקים {fmt(top5)} מתוך {fmt(n_sa)} "
                f"האזורים הסטטיסטיים ({pct(top5 / n_sa)}); {sai[0][0]} לבדה מחולקת ל-{fmt(sai[0][1])} אזורים."
            )
        if has_nb < 0.75:
            ins["neighborhoods"] = (
                f"רק ל-{pct(has_nb)} מהאזורים הסטטיסטיים רשומות שכונות, ולעומת זאת ל-{pct(has_st)} רשומים רחובות עיקריים."
            )
    else:
        labels["statareas_note"] = "אין אזורים סטטיסטיים במילון."
        labels["statareas_aria"] = "גרף עמודות אופקי: אזורים סטטיסטיים לפי יישוב."

    # ── streets ───────────────────────────────────────────────────────
    st = frames["streets"].copy()
    st["name"] = clean(st["Name_Hebrew"]).str.replace(r"\s+", " ", regex=True)
    st["code"] = pd.to_numeric(clean(st["Code"]), errors="coerce")
    st = st[st["name"] != ""]
    n_st = len(st)
    kpis["streets"] = {"value": n_st, "display": fmt(n_st), "tone": "brand"}
    st["type"] = st["name"].map(street_type)
    tc = st["type"].value_counts().to_dict()
    tci = ranked(tc)
    tcp = [(k, v) for k, v in tci if k != PLAIN_STREET]
    charts["street_types"] = {"names": [k for k, _ in tcp], "values": [int(v) for _, v in tcp]}
    tables["street_types"] = table(["סוג השם", "רשומות", "שיעור"], [[k, fmt(v), pct(v / n_st if n_st else 0)] for k, v in tci])
    plain = tc.get(PLAIN_STREET, 0)
    pref = ranked({k: v for k, v in tc.items() if k != PLAIN_STREET})
    if n_st:
        labels["street_types_note"] = (
            f"סיווג {fmt(n_st)} רשומות הרחובות לפי המילה הפותחת את השם (רח, שכ, דרך, סמ וכדומה). "
            f"{fmt(plain)} השמות ללא תחילית ({pct(plain / n_st)}) אינם בתרשים ומופיעים בטבלה."
        )
        labels["street_types_aria"] = (f"גרף עמודות אופקי: רשומות רחובות לפי תחילית השם. הנפוצה: {pref[0][0]} עם {fmt(pref[0][1])}." if pref else "גרף עמודות אופקי: רשומות רחובות לפי תחילית השם.")
        if pref:
            ins["street_types"] = (
                f"התחילית הנפוצה במילון הרחובות היא \"{pref[0][0]}\" ({fmt(pref[0][1])} רשומות)"
                + (f", לפני \"{pref[1][0]}\" ({fmt(pref[1][1])})" if len(pref) > 1 else "")
                + f"; {pct(plain / n_st)} מהשמות הם שם בלבד ללא תחילית."
            )
    else:
        labels["street_types_note"] = "מילון הרחובות ריק."
        labels["street_types_aria"] = "גרף עמודות אופקי: רחובות לפי סוג השם."

    named = st[st["type"] == PLAIN_STREET]
    nc = named["name"].value_counts().to_dict()
    nci = ranked(nc, TOP_N)
    charts["street_names"] = {"names": [k for k, _ in nci], "values": [int(v) for _, v in nci]}
    tables["street_names"] = table(["שם הרחוב", "מופעים"], [[k, fmt(v)] for k, v in nci])
    n_unique = int(st["name"].nunique())
    kpis["street_names"] = {"value": n_unique, "display": fmt(n_unique), "tone": "brand"}
    if nci:
        labels["street_names_note"] = (
            f"{fmt(n_unique)} שמות שונים ב-{fmt(n_st)} רשומות; אותו שם חוזר ביישובים רבים. "
            f"מוצגים {fmt(len(nci))} השמות הנפוצים מבין השמות ללא תחילית."
        )
        labels["street_names_aria"] = f"גרף עמודות אופקי: שמות הרחובות הנפוצים. בראש: {nci[0][0]} עם {fmt(nci[0][1])} מופעים."
        if len(nci) >= 3 and nci[0][1] > nci[1][1]:
            ins["street_names"] = (
                f"שם הרחוב הנפוץ במילון הוא \"{nci[0][0]}\" ({fmt(nci[0][1])} מופעים), ואחריו \"{nci[1][0]}\" ({fmt(nci[1][1])}) "
                f"ו\"{nci[2][0]}\" ({fmt(nci[2][1])})."
            )
    else:
        labels["street_names_note"] = "אין שמות רחובות במילון."
        labels["street_names_aria"] = "גרף עמודות אופקי: שמות רחובות נפוצים."

    kpis["lists"] = {"value": len(sizes) + 3, "display": fmt(len(sizes) + 3), "tone": "brand"}

    # ── insights, summary ─────────────────────────────────────────────
    order = ["flags", "record_cat", "docs", "regional", "district", "statareas", "neighborhoods", "street_names",
             "street_types", "council", "infra", "rural", "clusters", "nafa_gap", "big_cities", "lists"]
    insights = [{"id": k, "text_he": ins[k]} for k in order if ins.get(k)][:MAX_INSIGHTS]

    n_dicts = len(sizes) + 3
    summary = (
        f"מילוני קוד אחידים לנתוני נכס: איתור קוד לסוג נכס, שימוש, בעלות, יישוב או רחוב. "
        f"{fmt(n_fields)} שדות ברשומה המרכזית ו-{fmt(n_dicts)} מילונים."
    )
    labels["lede"] = (
        f"ספריית המילונים של מערך הדיגיטל הלאומי מגדירה שפה אחידה לתיאור נכסי מקרקעין ותשתיות: "
        f"רשומה מרכזית של {fmt(n_fields)} שדות ו-{fmt(n_dicts)} מילוני קוד (code lists), "
        f"מסוגי נכסים ושימושים ועד {fmt(n_loc)} יישובים, {fmt(n_sa)} אזורים סטטיסטיים ו-{fmt(n_st)} רשומות רחובות."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מילון נתונים", "נכסי מקרקעין", "קודים", "יישובים", "רחובות", "תשתיות"],
            "related_ids": [
                "d4a897f6-84bf-4560-9f28-7757bf8a0619",
                "83bd6cfa-cab5-4645-92a1-1a757524ce70",
                "009348a4-40d5-4bbe-92ab-ac19e4460fce",
                "7a6d0673-920c-470a-ad90-600d4ce3adcb",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
    }
