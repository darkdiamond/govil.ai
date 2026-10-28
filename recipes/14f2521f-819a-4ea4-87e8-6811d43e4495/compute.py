"""רשימת נציגויות ישראל בעולם — Israel's diplomatic missions abroad (MFA).

The data is published twice: a Hebrew file and an English translation with
the same rows. The recipe reads the Hebrew file only (the page is Hebrew; the
two files also disagree on the region of two Central-Asian countries — the
Hebrew `ybsht` is used as published).

Grain: one row per (country, mission) pair. `k_ntz` is the mission code; a
mission accredited to several countries (e.g. one embassy covering a group of
Pacific states) appears once per country it serves, with identical mission
fields. So:
- missions = distinct `k_ntz`; mission attributes (type, city, hours,
  contacts) are taken per mission (most common value, alphabetical tie-break);
- countries = distinct `shem_mdn`; visa flags and region are per country.

The data does not say which country of a shared mission hosts it, so the
page never names a host; it reports a lower bound for countries served from
abroad (countries in shared missions minus the number of shared missions).
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_SHARED = 12
TOP_MULTI = 10
NA = "לא צוין"
YES, NO = "כן", "לא"
VISA_COMBOS = [
    ("free_both", "ללא אשרה בשני הכיוונים"),
    ("israelis_only", "נדרשת אשרה לישראלים בלבד"),
    ("foreign_only", "נדרשת אשרה לאזרחי המדינה בלבד"),
    ("both", "נדרשת אשרה בשני הכיוונים"),
    ("na", "לא צוין"),
]
HOUR_BINS = [(0, 10, "פחות מ־10"), (10, 15, "10 עד 15"), (15, 20, "15 עד 20"),
             (20, 30, "20 עד 30"), (30, None, "30 ומעלה")]
DAYS = "אבגדהוז"
SEG_RE = re.compile(r"([א-ז])'\s*(?:-\s*([א-ז])')?\s*(\d{1,2}):?(\d{2})\s*-\s*(\d{1,2}):?(\d{2})")
CONTACT_FIELDS = [("Address", "כתובת"), ("Kabala", "שעות קבלת קהל"), ("email", "דואר אלקטרוני"),
                  ("tel", "טלפון"), ("fax", "פקס"), ("Atar", "אתר אינטרנט")]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pct_disp(v, digits=0):
    return f"{v:.{digits}f}%"


def _mode(s):
    vc = s.value_counts()
    vc = vc.sort_index().sort_values(ascending=False, kind="stable")
    return vc.index[0] if len(vc) else ""


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def weekly_hours(text):
    """Weekly public-reception hours from strings like "ב'-ה' 09:00-13:00  ו' 09:00-12:00"."""
    segs = SEG_RE.findall(text)
    if not segs:
        return None
    parts = []
    for d1, d2, h1, m1, h2, m2 in segs:
        a = DAYS.index(d1)
        b = DAYS.index(d2) if d2 else a
        days = b - a + 1
        dur = (int(h2) * 60 + int(m2) - int(h1) * 60 - int(m1)) / 60
        if days <= 0 or dur <= 0 or dur > 14:
            return None
        parts.append(days * dur)
    return math.fsum(parts)


def _days_pattern(text):
    segs = SEG_RE.findall(text)
    if not segs:
        return None
    covered = set()
    for d1, d2, *_ in segs:
        a = DAYS.index(d1)
        b = DAYS.index(d2) if d2 else a
        covered.update(range(a, b + 1))
    return "".join(DAYS[i] for i in sorted(covered))


def compute(frames):
    df = frames["he"]
    rows = pd.DataFrame({
        "country": df["shem_mdn"].str.strip(),
        "region": df["ybsht"].str.strip().replace("", NA),
        "code": df["k_ntz"].str.strip(),
        "city": df["shem_ntz"].str.strip(),
        "type": df["maamad"].str.strip().str.replace(r"^שגר'\s", "שגרירות ", regex=True).replace("", NA),
        "visa_out": df["visa_to_mdn"].str.strip(),
        "visa_in": df["visa_to_Israel"].str.strip(),
    })
    for col, _ in CONTACT_FIELDS:
        rows[col] = df[col].str.strip()
    rows = rows[rows["country"] != ""].copy()
    # A mission without a code is keyed by its city + type.
    rows["mission"] = rows["code"].where(rows["code"] != "", "~" + rows["city"] + "|" + rows["type"])
    rows = rows.sort_values(["mission", "country", "city", "type"], kind="stable")

    # ---- mission level -------------------------------------------------
    g = rows.groupby("mission", sort=True)
    missions = pd.DataFrame({
        "city": g["city"].agg(_mode),
        "type": g["type"].agg(_mode),
        "n_countries": g["country"].nunique(),
        "countries": g["country"].agg(lambda s: sorted(set(s))),
    })
    for col, _ in CONTACT_FIELDS:
        missions[col] = g[col].agg(_mode)
    n_missions = len(missions)

    # ---- country level -------------------------------------------------
    gc = rows.groupby("country", sort=True)
    countries = pd.DataFrame({
        "region": gc["region"].agg(_mode),
        "visa_out": gc["visa_out"].agg(_mode),
        "visa_in": gc["visa_in"].agg(_mode),
        "n_missions": gc["mission"].nunique(),
    })
    shared_missions = missions[missions["n_countries"] > 1]
    shared_set = set(c for lst in shared_missions["countries"] for c in lst)
    countries["shared"] = countries.index.isin(shared_set)
    n_countries = len(countries)
    n_shared_c = int(countries["shared"].sum())
    n_shared_m = len(shared_missions)
    abroad_lb = max(n_shared_c - n_shared_m, 0)

    # ---- KPIs ------------------------------------------------------------
    types = _sorted_counts(missions["type"])
    top_type = types.index[0]
    n_top_type = int(types.iloc[0])
    shared_share = n_shared_c / n_countries * 100 if n_countries else 0
    kpis = {
        "missions": {"value": n_missions, "display": n(n_missions), "tone": "brand"},
        "countries": {"value": n_countries, "display": n(n_countries), "tone": "brand"},
        "top_type": {"value": n_top_type, "display": n(n_top_type), "tone": "brand"},
        "shared": {"value": n_shared_c, "display": n(n_shared_c),
                   "tone": "info" if shared_share >= 25 else "brand"},
    }

    # ---- chart: regions ------------------------------------------------------
    reg_tot = _sorted_counts(countries["region"])
    reg_names = list(reg_tot.index)
    reg_ded = [int(((countries["region"] == r) & ~countries["shared"]).sum()) for r in reg_names]
    reg_sh = [int(((countries["region"] == r) & countries["shared"]).sum()) for r in reg_names]
    # Missions per region: a mission counts in every region of the countries it serves.
    mreg = rows.drop_duplicates(["mission", "region"])
    reg_m = [int((mreg["region"] == r).sum()) for r in reg_names]
    regions_chart = {"x": reg_names, "dedicated": reg_ded, "shared": reg_sh}
    regions_table = [{"region": r, "countries": n(reg_tot[r]), "dedicated": n(d), "shared": n(s), "missions": n(m)}
                     for r, d, s, m in zip(reg_names, reg_ded, reg_sh, reg_m)]

    # ---- chart: mission types ------------------------------------------------
    types_chart = {"names": list(types.index), "values": [int(v) for v in types.values]}
    types_table = [{"type": k, "count": n(v), "share": pct_disp(v / n_missions * 100, 1)} for k, v in types.items()]

    # ---- chart: shared missions ----------------------------------------------
    sm = shared_missions.reset_index().sort_values(["n_countries", "city", "mission"],
                                                   ascending=[False, True, True], kind="stable")
    sm_top = sm.head(TOP_SHARED)
    shared_chart = {"names": list(sm_top["city"]), "values": [int(v) for v in sm_top["n_countries"]],
                    "lists": [" · ".join(c) for c in sm_top["countries"]]}
    shared_table = [{"city": r.city, "type": r.type, "count": n(r.n_countries), "countries": ", ".join(r.countries)}
                    for r in sm.itertuples()]
    size_dist = _sorted_counts(missions["n_countries"]).sort_index()

    # ---- chart: countries with several missions ----------------------------------
    multi = countries[countries["n_missions"] > 1].reset_index()
    multi = multi.sort_values(["n_missions", "country"], ascending=[False, True], kind="stable").head(TOP_MULTI)
    multi_names = list(multi["country"])
    pair = rows.drop_duplicates(["country", "mission"])[["country", "mission"]].merge(
        missions[["type"]], left_on="mission", right_index=True)
    pair = pair[pair["country"].isin(multi_names)]
    multi_types = list(_sorted_counts(pair["type"]).index)
    ct = pair.groupby(["country", "type"]).size()
    multi_chart = {"names": multi_names, "series": [
        {"name": t, "data": [int(ct.get((c, t), 0)) for c in multi_names]} for t in multi_types]}
    multi_table = [{"country": c, "total": n(multi.set_index("country").loc[c, "n_missions"]),
                    "cells": [n(ct.get((c, t), 0)) for t in multi_types]} for c in multi_names]

    # ---- chart: visa ----------------------------------------------------------
    def combo(o, i):
        if o not in (YES, NO) or i not in (YES, NO):
            return "na"
        if o == NO and i == NO:
            return "free_both"
        if o == YES and i == NO:
            return "israelis_only"
        if o == NO and i == YES:
            return "foreign_only"
        return "both"
    countries["visa"] = [combo(o, i) for o, i in zip(countries["visa_out"], countries["visa_in"])]
    vc_all = countries["visa"].value_counts()
    used = [(k, lbl) for k, lbl in VISA_COMBOS if vc_all.get(k, 0) > 0]
    vtab = countries.groupby(["region", "visa"]).size()
    visa_series = []
    for k, lbl in used:
        counts = [int(vtab.get((r, k), 0)) for r in reg_names]
        shares = [round(c / reg_tot[r] * 100, 1) if reg_tot[r] else 0 for c, r in zip(counts, reg_names)]
        visa_series.append({"key": k, "name": lbl, "data": shares, "counts": counts})
    visa_chart = {"x": reg_names, "series": visa_series}
    visa_table = [{"region": r, "cells": [n(vtab.get((r, k), 0)) for k, _ in used]} for r in reg_names]
    visa_table.append({"region": "סה״כ", "cells": [n(vc_all.get(k, 0)) for k, _ in used]})
    visa_heads = [lbl for _, lbl in used]
    known = countries[countries["visa"] != "na"]
    n_known = len(known)
    isr_free = int((known["visa_out"] == NO).sum())
    isr_req = int((known["visa_out"] == YES).sum())

    # ---- chart: reception hours ------------------------------------------------
    missions["hours"] = missions["Kabala"].map(lambda t: weekly_hours(t) if t else None)
    missions["pattern"] = missions["Kabala"].map(lambda t: _days_pattern(t) if t else None)
    listed = missions[missions["Kabala"] != ""]
    parsed = listed[listed["hours"].notna()]
    n_unlisted = n_missions - len(listed)
    n_unparsed = len(listed) - len(parsed)
    hb_labels, hb_values = [], []
    for lo, hi, lbl in HOUR_BINS:
        m = (parsed["hours"] >= lo) & ((parsed["hours"] < hi) if hi is not None else True)
        hb_labels.append(lbl)
        hb_values.append(int(m.sum()))
    hours_chart = {"x": hb_labels, "y": hb_values, "unlisted": n_unlisted, "unparsed": n_unparsed}
    hours_table = [{"bin": l, "count": n(v)} for l, v in zip(hb_labels, hb_values)]
    hours_table.append({"bin": "שעות קבלה לא צוינו", "count": n(n_unlisted)})
    if n_unparsed:
        hours_table.append({"bin": "פורמט שלא פוענח", "count": n(n_unparsed)})
    med_hours = float(parsed["hours"].median()) if len(parsed) else None
    pat = _sorted_counts(parsed["pattern"]) if len(parsed) else pd.Series(dtype=int)
    friday_share = (parsed["pattern"].str.contains("ו").sum() / len(parsed) * 100) if len(parsed) else 0

    # ---- chart: contact completeness ------------------------------------------
    contact_names, contact_vals, contact_counts = [], [], []
    for col, lbl in CONTACT_FIELDS:
        c = int((missions[col] != "").sum())
        contact_names.append(lbl)
        contact_counts.append(c)
        contact_vals.append(round(c / n_missions * 100, 1) if n_missions else 0)
    contacts_chart = {"names": contact_names, "values": contact_vals, "counts": contact_counts}
    contacts_table = [{"field": a, "count": n(c), "share": pct_disp(v, 1)}
                      for a, c, v in zip(contact_names, contact_counts, contact_vals)]
    all_fields = int((missions[[c for c, _ in CONTACT_FIELDS]] != "").all(axis=1).sum())

    # ---- insights ---------------------------------------------------------------
    insights = []

    if len(reg_names) >= 2 and reg_tot.iloc[0] > reg_tot.iloc[1]:
        r0, r1 = reg_names[0], reg_names[1]
        insights.append({"id": "regions", "text_he": (
            f"{r0} מובילה במספר המדינות שבהן יש לישראל נציגות: {n(reg_tot[r0])} מתוך {n(n_countries)} "
            f"({pct(reg_tot[r0] / n_countries * 100)}), ואחריה {r1} עם {n(reg_tot[r1])}.")})

    if n_shared_m and int(sm.iloc[0]["n_countries"]) >= 3:
        top = sm.iloc[0]
        insights.append({"id": "shared", "text_he": (
            f"{n(n_shared_c)} מדינות ({pct(shared_share)}) מכוסות בידי {n(n_shared_m)} נציגויות שמשרתות יותר ממדינה אחת. "
            f"הרחבה שבהן — {top['type']} ב{top['city']} — משרתת {n(top['n_countries'])} מדינות. "
            f"לפחות {n(abroad_lb)} מדינות משורתות אפוא מנציגות שאינה יושבת בשטחן.")})

    if len(multi_names) and int(multi.iloc[0]["n_missions"]) >= 3:
        c0 = multi_names[0]
        cnt0 = int(multi.iloc[0]["n_missions"])
        sub = pair[pair["country"] == c0]["type"].value_counts()
        cons = int(sub.get("קונסוליה כללית", 0))
        extra = f", מהן {n(cons)} קונסוליות כלליות" if cons else ""
        second = ""
        if len(multi_names) > 1:
            second = f" שנייה לה {multi_names[1]} עם {n(multi.iloc[1]['n_missions'])}."
        else:
            second = "."
        insights.append({"id": "multi", "text_he": (
            f"ב{c0} פועלות {n(cnt0)} נציגויות ישראליות{extra} — הפריסה הצפופה ביותר במאגר;{second}")})

    if n_known >= 10:
        reg_req = []
        for r in reg_names:
            k = known[known["region"] == r]
            if len(k) >= 5:
                reg_req.append(((k["visa_out"] == YES).mean() * 100, r, len(k)))
        reg_req.sort(key=lambda t: (-t[0], t[1]))
        txt = (f"ישראלים נכנסים ללא אשרה ל-{n(isr_free)} מתוך {n(n_known)} המדינות שבמאגר "
               f"({pct(isr_free / n_known * 100)}).")
        if len(reg_req) >= 2 and reg_req[0][0] - reg_req[-1][0] >= 20:
            txt += (f" הדרישה לאשרה מרוכזת ב{reg_req[0][1]} ({pct(reg_req[0][0])} מהמדינות בה), "
                    f"לעומת {pct(reg_req[-1][0])} ב{reg_req[-1][1]}.")
        insights.append({"id": "visa", "text_he": txt})

    recip = int(((known["visa_out"] == known["visa_in"])).sum()) if n_known else 0
    asym_isr = int(vc_all.get("israelis_only", 0))
    asym_for = int(vc_all.get("foreign_only", 0))
    if n_known >= 10 and (asym_isr + asym_for) > 0:
        def in_countries(k):
            return "במדינה אחת" if k == 1 else f"ב-{n(k)} מדינות"
        parts = []
        if asym_for:
            parts.append(f"{in_countries(asym_for)} ישראל דורשת אשרה מאזרחי המדינה בעוד שישראלים פטורים")
        if asym_isr:
            parts.append(f"{in_countries(asym_isr)} המצב הפוך" if asym_for else
                         f"{in_countries(asym_isr)} ישראלים זקוקים לאשרה בעוד שאזרחי המדינה פטורים בישראל")
        insights.append({"id": "reciprocity", "text_he": (
            f"משטר האשרות הדדי ב-{n(recip)} מדינות ({pct(recip / n_known * 100)}); " + ", ו".join(parts) + ".")})

    if med_hours is not None and len(parsed) >= 10:
        hrs = f"{med_hours:.1f}".rstrip("0").rstrip(".")
        txt = (f"חציון שעות קבלת הקהל של נציגות הוא {LRI}{hrs}{PDI} שעות בשבוע "
               f"(מבין {n(len(parsed))} נציגויות שפרסמו שעות); {pct(friday_share)} מהן פתוחות לקהל גם ביום ו׳.")
        if n_unlisted:
            txt += f" {n(n_unlisted)} נציגויות לא פרסמו שעות קבלה."
        insights.append({"id": "hours", "text_he": txt})

    fax_i = [c for c, _ in CONTACT_FIELDS].index("fax")
    site_i = [c for c, _ in CONTACT_FIELDS].index("Atar")
    if n_missions >= 10:
        txt = (f"{n(all_fields)} מתוך {n(n_missions)} הנציגויות ({pct(all_fields / n_missions * 100)}) מפרסמות את כל "
               f"פרטי הקשר — כתובת, שעות, דוא״ל, טלפון, פקס ואתר.")
        if contact_vals[fax_i] >= 50:
            txt += f" מספר פקס עדיין מופיע אצל {pct(contact_vals[fax_i])} מהנציגויות."
        missing_site = n_missions - contact_counts[site_i]
        if missing_site:
            txt += f" ל-{n(missing_site)} נציגויות אין קישור לאתר."
        insights.append({"id": "contacts", "text_he": txt})

    # ---- labels ---------------------------------------------------------------
    non_emb = [f"{k} ({n(v)})" for k, v in types.items() if k != top_type]
    singles = int(size_dist.get(1, 0))
    labels = {
        "lede": (f"מאגר משרד החוץ מונה {n(n_missions)} נציגויות ישראליות בעולם — שגרירויות, קונסוליות כלליות, "
                 f"משלחות ונציגויות מיוחדות — המשרתות {n(n_countries)} מדינות. לכל נציגות מופיעים מעמדה, העיר, "
                 f"הכתובת, שעות קבלת הקהל ודרכי ההתקשרות, ולכל מדינה גם האם נדרשת אשרת כניסה בכל כיוון."),
        "missions_kpi": "נציגויות",
        "countries_kpi": "מדינות שבהן יש לישראל נציגות או כיסוי",
        "top_type_kpi": f"{top_type} — המעמד הנפוץ",
        "shared_kpi": "מדינות המשורתות בנציגות משותפת",
        "regions_note": (f"מספר המדינות בכל אזור, לפי שיוך האזורים של משרד החוץ. {n(n_countries - n_shared_c)} מדינות "
                         f"מקבלות שירות מנציגות ייעודית בלבד, ו-{n(n_shared_c)} חולקות נציגות עם מדינות אחרות."),
        "regions_aria": "גרף עמודות מוערמות: מדינות לפי אזור, נציגות ייעודית מול נציגות משותפת.",
        "regions_caption": "מדינות ונציגויות לפי אזור.",
        "types_note": (f"מעמדן של {n(n_top_type)} מתוך {n(n_missions)} הנציגויות ({pct(n_top_type / n_missions * 100)}) "
                       f"הוא {top_type}. שאר המעמדות: " + ", ".join(non_emb) + "."),
        "types_aria": "גרף עמודות: נציגויות לפי מעמד.",
        "types_caption": "נציגויות לפי מעמד.",
        "shared_note": (f"{n(singles)} נציגויות משרתות מדינה אחת בלבד; {n(n_shared_m)} משרתות כמה מדינות. "
                        f"מוצגות {n(min(TOP_SHARED, n_shared_m))} הנציגויות המשרתות את מספר המדינות הגדול ביותר — "
                        f"הרשימה המלאה בטבלה."),
        "shared_aria": "גרף עמודות אופקי: נציגויות לפי מספר המדינות שהן משרתות.",
        "shared_caption": "נציגויות המשרתות יותר ממדינה אחת.",
        "multi_note": (f"מדינות שבהן פועלת יותר מנציגות אחת — לרוב שגרירות בבירה ולצידה קונסוליות כלליות או משלחת "
                       f"לארגון בינלאומי. מוצגות עד {n(TOP_MULTI)} מדינות."),
        "multi_aria": "גרף עמודות אופקי מוערם: מדינות עם כמה נציגויות, לפי מעמד הנציגות.",
        "multi_caption": "מדינות עם יותר מנציגות אחת, לפי מעמד.",
        "visa_note": ("לכל מדינה שני דגלים: האם ישראלים צריכים אשרה כדי להיכנס אליה, והאם אזרחיה צריכים אשרה "
                      "כדי להיכנס לישראל. העמודות מציגות את חלק המדינות בכל שילוב בכל אזור."),
        "visa_aria": "גרף עמודות מוערמות מנורמל: שילובי דרישת אשרה לפי אזור.",
        "visa_caption": "מדינות לפי אזור ושילוב דרישות האשרה.",
        "hours_note": (f"שעות קבלת קהל שבועיות לנציגות, מחושבות מהטווחים שפורסמו (ימים × שעות). "
                       f"{n(n_unlisted)} נציגויות לא פרסמו שעות" +
                       (f", ו-{n(n_unparsed)} פורסמו בפורמט שלא פוענח" if n_unparsed else "") + "."),
        "hours_aria": "גרף עמודות: נציגויות לפי שעות קבלת קהל שבועיות.",
        "hours_caption": "נציגויות לפי שעות קבלת קהל שבועיות.",
        "contacts_note": (f"חלק הנציגויות שמפרסמות כל פרט קשר במאגר. {n(all_fields)} נציגויות מפרסמות את כולם."),
        "contacts_aria": "גרף עמודות אופקי: שיעור הנציגויות המפרסמות כל פרט קשר.",
        "contacts_caption": "פרטי קשר שמפורסמים לנציגויות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{n(n_missions)} נציגויות דיפלומטיות של ישראל המשרתות {n(n_countries)} מדינות ב-{n(len(reg_names))} "
                           f"אזורים: מעמד הנציגות, נציגויות משותפות לכמה מדינות, דרישות אשרה בשני הכיוונים, "
                           f"שעות קבלת קהל ופרטי קשר."),
            "dataset_kind": "registry",
            "suggested_tags": ["נציגויות", "משרד החוץ", "שגרירויות", "קונסוליות", "דיפלומטיה", "אשרות"],
            "related_ids": ["bae5a627-f1bd-4da7-8b08-664cf626df47", "505aa85e-a49f-4a49-aea2-4cc7b6e44e92",
                            "4eaa3676-34ea-4c88-8980-dd64cba86411", "0093a1b8-918b-42b7-b268-e35e22616de1",
                            "46577c12-8675-4464-a5ca-473ae20e3dd9"],
            "spatial_coverage": "עולם",
        },
        "kpis": kpis,
        "charts": {"regions": regions_chart, "types": types_chart, "shared": shared_chart,
                   "multi": multi_chart, "visa": visa_chart, "hours": hours_chart, "contacts": contacts_chart},
        "tables": {"regions": regions_table, "types": types_table, "shared": shared_table,
                   "multi": multi_table, "multi_types": multi_types, "visa": visa_table,
                   "visa_heads": visa_heads, "hours": hours_table, "contacts": contacts_table},
        "insights": insights,
        "labels": labels,
    }
