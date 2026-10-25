"""נחליאלי — Ministry of Health vaccine catalogue + batch list for the national
digital vaccination record.

Four related tables:
  * batches       — one row per registered batch (lot) number, carrying the
                    vaccine-type, manufacturer and trade-name codes + labels.
                    Grows as new batches are released (the fact table).
  * tradenames    — the product catalogue: every trade name (תרכיב) with its
                    vaccine type and manufacturer. Many entries have no batch
                    (legacy products, vaccines given abroad).
  * manufacturers — code table of manufacturers.
  * vaccines      — code table of vaccine types that must be reported.

Batch aggregates use the batch file's own labels (authoritative for that file);
catalogue aggregates use the catalogue and code tables. Links between them are
by code and checked (integrity insight). No dates exist anywhere — the data is
a snapshot, so there are no trends; ordering by trade-name code is shown as
"catalogue order" only.

Manufacturers and product names are commercial and are named freely; there
are no people in the data.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_TYPES = 15
TOP_PRODUCTS = 15
TOP_MANU = 12
HEAT_TYPES = 12
HEAT_MANU = 10
TOP_CAT_TYPES = 12
EVO_MAX = 20
LEN_MANU = 10
NEWEST = 10
OTHER = "אחר"

# Hebrew glosses for known vaccine-type codes (by their label). Unknown labels
# fall back to the raw label, so new codes flow through untouched.
GLOSS = {
    "DTP": "דיפתריה, טטנוס ושעלת",
    "DT": "דיפתריה וטטנוס",
    "IPV": "פוליו מומת",
    "tOPV": "פוליו חי פומי, תלת-ערכי",
    "bOPV": "פוליו חי פומי, דו-ערכי",
    "MMR": "חצבת, חזרת ואדמת",
    "Measles": "חצבת",
    "Mumps": "חזרת",
    "Rubella": "אדמת",
    "Measles-Mumps": "חצבת וחזרת",
    "MMRV": "חצבת, חזרת, אדמת ואבעבועות רוח",
    "BCG": "שחפת",
    "HBV": "דלקת כבד נגיפית B",
    "HAV": "דלקת כבד נגיפית A",
    "HAHB": "דלקת כבד נגיפית A ו-B",
    "HA-Typh-I": "דלקת כבד נגיפית A וטיפוס",
    "Hib": "המופילוס אינפלואנזה b",
    "Rab": "כלבת",
    "infl.TIV/QIV": "שפעת (תרכיב מומת)",
    "Infl. LAIV": "שפעת, תרכיב חי מוחלש",
    "Pneu-P-23": "פנאומוקוק פוליסכרידי",
    "PCV7": "פנאומוקוק מצומד",
    "PCV10": "פנאומוקוק מצומד",
    "PCV13": "פנאומוקוק מצומד",
    "PCV20": "פנאומוקוק מצומד",
    "Men-P-ACWY": "מנינגוקוק ACWY פוליסכרידי",
    "MCV4": "מנינגוקוק ACWY מצומד",
    "4CMenB": "מנינגוקוק B",
    "DTaP": "דיפתריה, טטנוס ושעלת (אצלולרי)",
    "DTaP-Hib": "דיפתריה, טטנוס, שעלת ו-Hib",
    "DTaP-IPV": "דיפתריה, טטנוס, שעלת ופוליו",
    "DTaP-IPV-Hib": "דיפתריה, טטנוס, שעלת, פוליו ו-Hib",
    "DTaP-IPV-HB-Hib": "דיפתריה, טטנוס, שעלת, פוליו, דלקת כבד B ו-Hib",
    "DT-IPV": "דיפתריה, טטנוס ופוליו",
    "DTP-HIB": "דיפתריה, טטנוס, שעלת ו-Hib",
    "DTP-IPV": "דיפתריה, טטנוס, שעלת ופוליו",
    "TT": "טטנוס",
    "Td": "טטנוס ודיפתריה",
    "Td-IPV": "טטנוס, דיפתריה ופוליו",
    "Tdap": "טטנוס, דיפתריה ושעלת",
    "Tdap-IPV": "טטנוס, דיפתריה, שעלת ופוליו",
    "VAR": "אבעבועות רוח",
    "VZV": "שלבקת חוגרת",
    "Rota": "נגיף רוטה",
    "HPV": "נגיף הפפילומה",
    "JE": "דלקת מוח יפנית",
    "TBE": "דלקת מוח מקרדית",
    "Typh-I": "טיפוס, בהזרקה",
    "Typh-O": "טיפוס, פומי",
    "YF": "קדחת צהובה",
    "COVID-19": "קורונה",
    "MVA": "אבעבועות הקופים",
    "RSV": "נגיף RSV",
    "Dengue": "דנגי",
    "RSV-IG": "נוגדנים נגד נגיף RSV",
    "HBIG": "נוגדנים נגד דלקת כבד B",
    "VZ-IG": "נוגדנים נגד אבעבועות רוח",
    "R-IG": "נוגדנים נגד כלבת",
    "T-IG": "נוגדנים נגד טטנוס",
    "COVID-19 IG": "נוגדנים נגד קורונה",
    "Measles (IG)": "נוגדנים נגד חצבת",
}
PASSIVE_RE = re.compile(r"IG\)?$")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def iso(s):
    return f"{LRI}{s}{PDI}"


def gloss(desc):
    return GLOSS.get(desc, desc)


def is_passive(desc):
    return bool(PASSIVE_RE.search(desc.strip().upper()))


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _code(s):
    return pd.to_numeric(s.str.strip(), errors="coerce")


def _clean(df, cols):
    out = pd.DataFrame({c: df[c].str.strip() for c in cols})
    return out


def _top(counts, k):
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + ([OTHER] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def _join_names(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו" if "\u05d0" <= last[:1] <= "\u05ea" else " ו-"
    return ", ".join(items[:-1]) + conj + last


# ── insight rules ───────────────────────────────────────────────────────
def insight_top_product(prod, prod_info, total):
    if prod.empty or total == 0:
        return None
    lead, v = prod.index[0], int(prod.iloc[0])
    share = v / total
    if share < 0.10:
        return None
    vt, mf = prod_info[lead]
    second = int(prod.iloc[1]) if len(prod) > 1 else 0
    tail = ""
    if second and v >= 2 * second:
        tail = f" — פי {v / second:.1f} מהתרכיב השני בגודלו, {prod.index[1]} ({n(second)})"
    return (f"תרכיב אחד מחזיק נתח חריג מהקטלוג: {lead} של {mf} ({vt} — {gloss(vt)}) רשום עם "
            f"{n(v)} אצוות, {pct(share * 100)} מכלל {n(total)} האצוות{tail}.")


def insight_passive(b, total):
    if total == 0:
        return None
    pas = b[b["passive"]]
    share = len(pas) / total
    if share < 0.10:
        return None
    vt = _sorted_counts(pas["vt"])
    parts = [f"{k} ({n(c)})" for k, c in vt.head(3).items()]
    return (f"{pct(share * 100)} מהאצוות ({n(len(pas))}) אינן תרכיבים אלא תכשירי נוגדנים לחיסון סביל, "
            f"שהמובילים בהם {_join_names(parts)}.")


def insight_diverse(cat, batch_tn):
    if cat.empty:
        return None
    per = _sorted_counts(cat["vt"])
    if len(per) < 2:
        return None
    lead, v = per.index[0], int(per.iloc[0])
    v2 = int(per.iloc[1])
    if v < 1.5 * v2 or v < 5:
        return None
    sub = cat[cat["vt"] == lead]
    with_b = int(sub["tn_code"].isin(batch_tn).sum())
    n_m = sub["mf"].nunique()
    return (f"לסוג החיסון {lead} ({gloss(lead)}) יש בקטלוג {n(v)} שמות מסחריים של {n(n_m)} יצרנים — "
            f"יותר מכל סוג אחר (השני: {per.index[1]}, עם {n(v2)}). רק {n(with_b)} מהם מופיעים "
            f"ברשימת האצוות, והשאר רשומים בקטלוג בלי אצוות.")


def insight_dormant(cat, manu, batch_tn, batch_mf):
    if cat.empty:
        return None
    no_b = cat[~cat["tn_code"].isin(batch_tn)]
    s = (f"{n(len(no_b))} מתוך {n(len(cat))} השמות המסחריים בקטלוג ({pct(len(no_b) / len(cat) * 100)}) "
         f"אינם מופיעים באף אצווה ברשימה.")
    if not manu.empty:
        idle = manu[~manu["mf_code"].isin(batch_mf)]
        if len(idle):
            cnt = cat[cat["mf_code"].isin(idle["mf_code"])].groupby("mf").size()
            idle_names = idle[["mf"]].copy()
            idle_names["k"] = idle_names["mf"].map(cnt).fillna(0)
            idle_names = idle_names.sort_values(["k", "mf"], ascending=[False, True], kind="stable")
            ex = list(idle_names["mf"].head(4))
            s += (f" {n(len(idle))} מתוך {n(len(manu))} היצרנים ברשימת היצרנים אינם מופיעים באף אצווה, "
                  f"ביניהם {_join_names(ex)}.")
    if len(no_b) / len(cat) < 0.15:
        return None
    return s


def insight_mandatory(vac, batch_vt, cat_vt):
    if vac.empty:
        return None
    tot = len(vac)
    with_b = vac[vac["vt_code"].isin(batch_vt)]
    no_cat = vac[~vac["vt_code"].isin(cat_vt)]
    if len(with_b) == tot:
        return f"לכל {n(tot)} סוגי החיסון ברשימת הדיווח לנחליאלי רשומה לפחות אצווה אחת."
    s = (f"ברשימת סוגי החיסון המחייבים דיווח לנחליאלי {n(tot)} סוגים; ל-{n(len(with_b))} מהם "
         f"({pct(len(with_b) / tot * 100)}) רשומות אצוות")
    if len(no_cat):
        ex = list(no_cat.sort_values(["vt_code", "vt"], kind="stable")["vt"].head(5))
        s += f", ול-{n(len(no_cat))} אין אף שם מסחרי בקטלוג (למשל {', '.join(ex)})"
    return s + "."


def insight_manu(manu_b, total):
    if len(manu_b) < 4 or total == 0:
        return None
    top4 = manu_b.head(4)
    share = top4.sum() / total
    if share < 0.5:
        return None
    parts = [f"{k} ({n(c)})" for k, c in top4.items()]
    return (f"ארבעה יצרנים מחזיקים {pct(share * 100)} מהאצוות: {_join_names(parts)}. "
            f"בסך הכול רשומות אצוות של {n(len(manu_b))} יצרנים.")


def insight_competition(b):
    per = b.groupby("vt")["mf"].nunique()
    multi = per[per >= 2]
    if multi.empty:
        return None
    m_sorted = multi.sort_index().sort_values(ascending=False, kind="stable")
    lead = m_sorted.index[0]
    mfs = sorted(b.loc[b["vt"] == lead, "mf"].unique())
    return (f"ל-{n(len(multi))} מתוך {n(len(per))} סוגי החיסון ברשימת האצוות יש אצוות מיותר מיצרן אחד. "
            f"המגוון ביותר: {lead} ({gloss(lead)}), עם אצוות של {n(len(mfs))} יצרנים — {_join_names(mfs)}.")


def insight_integrity(b, cat):
    if b.empty or cat.empty:
        return None
    m = b.merge(cat[["tn_code", "vt_code", "mf_code"]], on="tn_code", how="left",
                suffixes=("", "_c"), indicator=True)
    orphan = int((m["_merge"] == "left_only").sum())
    both = m[m["_merge"] == "both"]
    mism = int(((both["vt_code"] != both["vt_code_c"]) | (both["mf_code"] != both["mf_code_c"])).sum())
    dup = int(b["batch"].duplicated().sum())
    if orphan == 0 and mism == 0 and dup == 0:
        return (f"הרשימה עקבית: כל {n(len(b))} מספרי האצווה ייחודיים, וכל אחד מהם מקושר לשם מסחרי קיים "
                f"בקטלוג עם אותו קוד סוג חיסון ואותו קוד יצרן.")
    bits = []
    if orphan:
        bits.append(f"{n(orphan)} אצוות מפנות לקוד שם מסחרי שאינו מופיע בקטלוג")
    if mism:
        bits.append(f"ב-{n(mism)} אצוות קוד סוג החיסון או היצרן שונה מזה שבקטלוג")
    if dup:
        bits.append(f"{n(dup)} מספרי אצווה חוזרים יותר מפעם אחת")
    return "בדיקת עקביות בין הקבצים: " + "; ".join(bits) + "."


# ── compute ─────────────────────────────────────────────────────────────
def compute(frames):
    rb = frames["batches"]
    rt = frames["tradenames"]
    rm = frames["manufacturers"]
    rv = frames["vaccines"]

    b = pd.DataFrame({
        "vt_code": _code(rb["vaccinationCode"]),
        "vt": rb["vaccinationDesc"].str.strip(),
        "mf_code": _code(rb["manufacturerCode"]),
        "mf": rb["manufacturerDesc"].str.strip(),
        "tn_code": _code(rb["tradeNameCode"]),
        "tn": rb["tradeNameDesc"].str.strip(),
        "batch": rb["batchNumber"].str.strip(),
    })
    b = b[(b["batch"] != "") & b["tn_code"].notna()].copy()
    b["vt"] = b["vt"].replace("", "לא צוין")
    b["mf"] = b["mf"].replace("", "לא צוין")
    b["tn"] = b["tn"].replace("", "לא צוין")
    b["passive"] = b["vt"].map(is_passive)
    total = len(b)

    cat = pd.DataFrame({
        "vt_code": _code(rt["vaccinationCode"]),
        "vt": rt["vaccinationDesc"].str.strip(),
        "mf_code": _code(rt["manufacturerCode"]),
        "mf": rt["manufacturerDesc"].str.strip(),
        "tn_code": _code(rt["tradeNameCode"]),
        "tn": rt["tradeNameDesc"].str.strip(),
    })
    cat = cat[cat["tn_code"].notna()].drop_duplicates("tn_code").copy()
    manu = pd.DataFrame({"mf_code": _code(rm["manufacturerCode"]), "mf": rm["manufacturerDesc"].str.strip()})
    manu = manu[manu["mf_code"].notna()].drop_duplicates("mf_code").copy()
    vac = pd.DataFrame({"vt_code": _code(rv["vaccinationCode"]), "vt": rv["vaccinationDesc"].str.strip()})
    vac = vac[vac["vt_code"].notna()].drop_duplicates("vt_code").copy()

    batch_tn = set(b["tn_code"])
    batch_mf = set(b["mf_code"].dropna())
    batch_vt = set(b["vt_code"].dropna())
    cat_vt = set(cat["vt_code"].dropna())

    types = _sorted_counts(b["vt"])
    prod = _sorted_counts(b["tn"])
    manu_b = _sorted_counts(b["mf"])
    passive_of = {t: is_passive(t) for t in types.index}
    first = b.sort_values(["tn", "vt", "mf", "batch"], kind="stable").drop_duplicates("tn")
    prod_info = {r.tn: (r.vt, r.mf) for r in first.itertuples()}
    n_pas = int(b["passive"].sum())

    # 1. vaccine types by batches, split active / passive
    t_names, t_vals = _top(types, TOP_TYPES)
    types_chart = {"names": t_names, "gloss": [gloss(t) if t != OTHER else "סוגים נוספים" for t in t_names],
                   "active": [v if (t != OTHER and not passive_of[t]) else None for t, v in zip(t_names, t_vals)],
                   "passive": [v if (t != OTHER and passive_of[t]) else None for t, v in zip(t_names, t_vals)],
                   "other": [v if t == OTHER else None for t, v in zip(t_names, t_vals)]}
    types_table = [{"name": t, "gloss": (gloss(t) if t != OTHER else "סוגים נוספים"),
                    "kind": ("" if t == OTHER else ("נוגדנים (חיסון סביל)" if passive_of[t] else "תרכיב")),
                    "count": n(v), "share": pct(v / total * 100) if total else "—"}
                   for t, v in zip(t_names, t_vals)]

    # 2. treemap type -> trade name
    tt = b.groupby(["vt", "tn"]).size()
    tree = []
    for t in types.index:
        kids = tt.loc[t].sort_index().sort_values(ascending=False, kind="stable")
        tree.append({"name": t, "value": int(types[t]), "gloss": gloss(t),
                     "children": [{"name": k, "value": int(v)} for k, v in kids.items()]})

    # 3. top products
    p_names = list(prod.head(TOP_PRODUCTS).index)
    products_chart = {"names": p_names, "values": [int(prod[p]) for p in p_names]}
    products_table = [{"name": p, "vt": prod_info[p][0], "mf": prod_info[p][1], "count": n(prod[p])}
                      for p in p_names]

    # 4. concentration (Pareto)
    cum = prod.cumsum() / total if total else prod * 0
    pareto_chart = {"x": list(range(1, len(prod) + 1)), "values": [int(v) for v in prod.values],
                    "names": list(prod.index), "cum": [round(float(v) * 100, 1) for v in cum.values]}
    milestones = []
    for k in (1, 3, 5, 10, 20):
        if k <= len(prod):
            milestones.append({"label": f"{n(k)} המובילים", "share": pct(float(cum.iloc[k - 1]) * 100)})
    n50 = int((cum < 0.5).sum()) + 1 if total else 0
    n80 = int((cum < 0.8).sum()) + 1 if total else 0
    single = int((prod == 1).sum())
    pareto_table = milestones

    # 5. manufacturers by batches
    m_names, m_vals = _top(manu_b, TOP_MANU)
    manu_chart = {"names": m_names, "values": m_vals}
    manu_prod = b.groupby("mf")["tn"].nunique()
    manu_types = b.groupby("mf")["vt"].nunique()
    manu_table = [{"name": m, "count": n(manu_b[m]), "products": n(manu_prod[m]), "types": n(manu_types[m])}
                  for m in list(manu_b.head(TOP_MANU).index)]

    # 6. catalogue per manufacturer: with / without batches
    cat["has_b"] = cat["tn_code"].isin(batch_tn)
    mc = cat.groupby("mf").agg(total=("tn_code", "size"), with_b=("has_b", "sum"))
    mc = mc.sort_index().sort_values("total", ascending=False, kind="stable")
    mc_top = mc.head(TOP_MANU)
    mc_rest = mc.iloc[TOP_MANU:]
    mc_names = list(mc_top.index) + ([OTHER] if len(mc_rest) else [])
    mc_with = [int(v) for v in mc_top["with_b"]] + ([int(mc_rest["with_b"].sum())] if len(mc_rest) else [])
    mc_tot = [int(v) for v in mc_top["total"]] + ([int(mc_rest["total"].sum())] if len(mc_rest) else [])
    manucat_chart = {"names": mc_names, "with_b": mc_with, "without_b": [t - w for t, w in zip(mc_tot, mc_with)]}
    manucat_table = [{"name": nm, "total": n(t), "with_b": n(w), "without_b": n(t - w)}
                     for nm, t, w in zip(mc_names, mc_tot, mc_with)]

    # 7. heatmap manufacturer x vaccine type
    hx = list(types.head(HEAT_TYPES).index)
    hy = list(manu_b.head(HEAT_MANU).index)
    hm = b[b["vt"].isin(hx) & b["mf"].isin(hy)].groupby(["mf", "vt"]).size()
    cells = [[xi, yi, int(hm.get((m, t), 0))] for yi, m in enumerate(hy) for xi, t in enumerate(hx)]
    heat_covered = int(sum(c[2] for c in cells))
    hv = sorted((c[2] for c in cells), reverse=True)
    heat_cap = len(hv) > 1 and hv[1] > 0 and hv[0] > 2 * hv[1]
    heat_chart = {"x": hx, "y": hy, "cells": [c for c in cells if c[2] > 0],
                  "max": (hv[1] if heat_cap else (hv[0] if hv and hv[0] else 1))}

    # 8. mandatory-reporting list status
    in_cat = vac["vt_code"].isin(cat_vt)
    has_b = vac["vt_code"].isin(batch_vt)
    st_with = vac[has_b]
    st_cat = vac[in_cat & ~has_b]
    st_none = vac[~in_cat & ~has_b]

    def _ex(df_):
        return ", ".join(df_.sort_values(["vt_code", "vt"], kind="stable")["vt"].head(8))
    status_rows = [
        ("רשומות אצוות", st_with),
        ("בקטלוג, ללא אצוות", st_cat),
        ("ללא שם מסחרי בקטלוג", st_none),
    ]
    status_chart = [{"name": nm, "value": int(len(d))} for nm, d in status_rows]
    status_table = [{"name": nm, "count": n(len(d)), "examples": _ex(d) or "—"} for nm, d in status_rows]

    # 9. catalogue per vaccine type: with / without batches
    vc = cat.groupby("vt").agg(total=("tn_code", "size"), with_b=("has_b", "sum"), mfs=("mf", "nunique"))
    vc = vc.sort_index().sort_values("total", ascending=False, kind="stable").head(TOP_CAT_TYPES)
    typecat_chart = {"names": list(vc.index), "with_b": [int(v) for v in vc["with_b"]],
                     "without_b": [int(t - w) for t, w in zip(vc["total"], vc["with_b"])]}
    typecat_table = [{"name": t, "gloss": gloss(t), "total": n(r.total), "with_b": n(r.with_b), "mfs": n(r.mfs)}
                     for t, r in vc.iterrows()]

    # 10. product line of the most diverse type, in catalogue-code order
    evo = None
    if len(vc):
        evo_t = vc.index[0]
        sub = cat[cat["vt"] == evo_t].sort_values("tn_code", kind="stable")
        cut = len(sub) > EVO_MAX
        sub = sub.tail(EVO_MAX)
        bcount = b[b["vt"] == evo_t].groupby("tn_code").size()
        vals = [int(bcount.get(c, 0)) for c in sub["tn_code"]]
        evo = {"type": evo_t, "gloss": gloss(evo_t), "names": list(sub["tn"]), "mf": list(sub["mf"]),
               "codes": [int(c) for c in sub["tn_code"]], "values": vals, "cut": cut,
               "n": int(len(sub)), "with_b": int(sum(1 for v in vals if v > 0))}
        evo["table"] = [{"code": n(c), "name": nm, "mf": mf, "count": n(v)}
                        for c, nm, mf, v in zip(evo["codes"], evo["names"], evo["mf"], vals)]

    # 11. batch-number length by manufacturer
    b["blen"] = b["batch"].str.len()
    b["alpha0"] = b["batch"].str.match(r"[A-Za-z]")
    lens = sorted(int(x) for x in b["blen"].unique())
    ly = list(manu_b.head(LEN_MANU).index)
    lm = b[b["mf"].isin(ly)].groupby(["mf", "blen"]).size()
    lcells = [[xi, yi, int(lm.get((m, L), 0))] for yi, m in enumerate(ly) for xi, L in enumerate(lens)]
    blen_chart = {"x": [str(L) for L in lens], "y": ly, "cells": [c for c in lcells if c[2] > 0],
                  "max": max([c[2] for c in lcells] or [1])}
    blen_table = []
    for m in ly:
        sm = b[b["mf"] == m]
        mode = _sorted_counts(sm["blen"]).index[0]
        lo, hi = int(sm["blen"].min()), int(sm["blen"].max())
        blen_table.append({"name": m, "count": n(len(sm)), "mode": n(mode),
                           "range": f"{lo}–{hi}" if lo != hi else f"{lo}",
                           "alpha": pct(sm["alpha0"].mean() * 100, 0)})
    med_len = int(b["blen"].median()) if total else 0
    alpha_share = float(b["alpha0"].mean()) if total else 0.0

    # 12. newest catalogue entries (highest trade-name codes)
    bc_all = b.groupby("tn_code").size()
    newest = cat.sort_values("tn_code", ascending=False, kind="stable").head(NEWEST)
    newest_table = [{"code": n(r.tn_code), "name": r.tn, "vt": r.vt, "mf": r.mf,
                     "count": n(bc_all.get(r.tn_code, 0))} for r in newest.itertuples()]

    # ── KPIs ────────────────────────────────────────────────────────────
    n_tn_b = int(b["tn"].nunique())
    share_top = float(prod.iloc[0]) / total if total else 0.0
    pas_share = n_pas / total if total else 0.0
    cov = len(st_with) / len(vac) if len(vac) else 0.0
    kpis = {
        "batches": {"value": total, "display": n(total), "tone": "brand"},
        "types_b": {"value": int(types.size), "display": n(types.size), "tone": "brand"},
        "manu_b": {"value": int(manu_b.size), "display": n(manu_b.size), "tone": "brand"},
        "tn_b": {"value": n_tn_b, "display": n(n_tn_b), "tone": "brand"},
        "catalog": {"value": int(len(cat)), "display": n(len(cat)), "tone": "brand"},
        "coverage": {"value": round(cov * 100, 1), "display": f"{cov * 100:.1f}%",
                     "tone": "ok" if cov >= 0.9 else "info"},
        "passive": {"value": round(pas_share * 100, 1), "display": f"{pas_share * 100:.1f}%", "tone": "info"},
        "top_share": {"value": round(share_top * 100, 1), "display": f"{share_top * 100:.1f}%",
                      "tone": "brand"},
    }

    # ── insights ────────────────────────────────────────────────────────
    rules = [
        ("top_product", lambda: insight_top_product(prod, prod_info, total)),
        ("passive", lambda: insight_passive(b, total)),
        ("manu", lambda: insight_manu(manu_b, total)),
        ("diverse", lambda: insight_diverse(cat, batch_tn)),
        ("competition", lambda: insight_competition(b)),
        ("dormant", lambda: insight_dormant(cat, manu, batch_tn, batch_mf)),
        ("mandatory", lambda: insight_mandatory(vac, batch_vt, cat_vt)),
        ("integrity", lambda: insight_integrity(b, cat)),
    ]
    insights = []
    for rid, fn in rules:
        t = fn()
        if t:
            insights.append({"id": rid, "text_he": t})

    # ── labels ──────────────────────────────────────────────────────────
    lead_t = types.index[0]
    lead_m = manu_b.index[0]
    lead_p = prod.index[0]
    labels = {
        "lede": (f"הקטלוג הרשמי של משרד הבריאות לדיווח חיסונים למערכת נחליאלי — פנקס החיסונים הדיגיטלי. "
                 f"הוא כולל {n(total)} מספרי אצווה של {n(n_tn_b)} שמות מסחריים, {n(types.size)} סוגי חיסון "
                 f"ו-{n(manu_b.size)} יצרנים, לצד קטלוג של {n(len(cat))} שמות מסחריים ורשימה של {n(len(vac))} "
                 f"סוגי חיסון המחייבים דיווח. כל אצווה מקושרת לסוג החיסון, ליצרן ולשם המסחרי, כך שמערכות "
                 f"המידע הרפואיות מדווחות על כל מנה באופן אחיד."),
        "batches_kpi": "מספרי אצווה רשומים",
        "types_kpi": "סוגי חיסון עם אצוות",
        "manu_kpi": "יצרנים עם אצוות",
        "tn_kpi": "שמות מסחריים עם אצוות",
        "catalog_kpi": f"שמות מסחריים בקטלוג (מתוכם {n(n_tn_b)} עם אצוות)",
        "coverage_kpi": f"מסוגי החיסון ברשימת הדיווח עם אצוות ({n(len(st_with))} מתוך {n(len(vac))})",
        "passive_kpi": "מהאצוות הן תכשירי נוגדנים (חיסון סביל)",
        "top_share_kpi": f"מהאצוות שייכות לתרכיב המוביל, {lead_p}",
        # chart ledes / aria
        "types_note": (f"כל עמודה היא סוג חיסון לפי קוד נחליאלי. {lead_t} ({gloss(lead_t)}) מוביל עם "
                       f"{n(types.iloc[0])} אצוות. תכשירי נוגדנים (חיסון סביל, קודים המסתיימים ב-IG) "
                       f"מסומנים בנפרד, והם {pct(pas_share * 100)} מכלל האצוות. "
                       f"מוצגים {n(min(TOP_TYPES, types.size))} הסוגים המובילים"
                       + (f"; {n(types.size - TOP_TYPES)} הנותרים מקובצים תחת „אחר”." if types.size > TOP_TYPES else ".")),
        "types_aria": (f"גרף עמודות אופקי: אצוות לפי סוג חיסון. המוביל {lead_t} עם {n(types.iloc[0])} אצוות."),
        "tree_note": (f"מפת שטח של כל {n(total)} האצוות: מלבן לכל סוג חיסון, ובתוכו מלבן לכל שם מסחרי. "
                      f"השטח יחסי למספר האצוות. לחיצה על סוג מתמקדת בו."),
        "tree_aria": (f"מפת שטח היררכית: {n(types.size)} סוגי חיסון ו-{n(n_tn_b)} שמות מסחריים לפי מספר אצוות."),
        "products_note": (f"{n(min(TOP_PRODUCTS, prod.size))} השמות המסחריים עם מספר האצוות הגדול ביותר. "
                          f"{lead_p} לבדו מחזיק {pct(share_top * 100)} מהאצוות."),
        "products_aria": f"גרף עמודות אופקי: שמות מסחריים לפי מספר אצוות. המוביל {lead_p} עם {n(prod.iloc[0])} אצוות.",
        "pareto_note": (f"השמות המסחריים מדורגים לפי מספר אצוות, והקו מראה את חלקם המצטבר. "
                        f"{n(n50)} שמות מסחריים מכסים מחצית מהאצוות ו-{n(n80)} מכסים {pct(80, 0)}; "
                        f"ל-{n(single)} שמות מסחריים רשומה אצווה אחת בלבד."),
        "pareto_aria": (f"גרף פארטו: ריכוזיות האצוות בין {n(prod.size)} שמות מסחריים. "
                        f"{n(n50)} שמות מסחריים מכסים מחצית מהאצוות."),
        "manu_note": (f"{lead_m} מוביל עם {n(manu_b.iloc[0])} אצוות. הטבלה מוסיפה לכל יצרן את מספר השמות "
                      f"המסחריים ומספר סוגי החיסון שלו ברשימת האצוות."
                      + (f" {n(manu_b.size - TOP_MANU)} יצרנים קטנים מקובצים תחת „אחר”." if manu_b.size > TOP_MANU else "")),
        "manu_aria": f"גרף עמודות אופקי: אצוות לפי יצרן. המוביל {lead_m} עם {n(manu_b.iloc[0])} אצוות.",
        "manucat_note": (f"כמה שמות מסחריים יש לכל יצרן בקטלוג, וכמה מהם מופיעים באצווה אחת לפחות. "
                         f"מתוך {n(len(cat))} השמות המסחריים בקטלוג, {n(int(cat['has_b'].sum()))} מופיעים ברשימת "
                         f"האצוות."),
        "manucat_aria": (f"גרף עמודות מוערמות: שמות מסחריים בקטלוג לפי יצרן, עם אצוות ובלי אצוות. "
                         f"המוביל {mc_names[0] if mc_names else ''} עם {n(mc_tot[0]) if mc_tot else 0} שמות."),
        "heat_note": (f"אילו יצרנים מספקים כל סוג חיסון: {n(len(hy))} היצרנים המובילים מול {n(len(hx))} "
                      f"סוגי החיסון המובילים, לפי מספר אצוות. התאים מכסים {n(heat_covered)} מתוך {n(total)} "
                      f"האצוות; תא ריק פירושו שאין אצוות לצירוף."
                      + (f" סולם הצבע נעצר ב-{n(heat_chart['max'])} כדי שהתא הגדול ביותר ({n(hv[0])} אצוות) "
                         f"לא יטשטש את השאר; הערך המלא מופיע בריחוף." if heat_cap else "")),
        "heat_aria": (f"מפת חום: אצוות לפי יצרן וסוג חיסון, {n(len(hy))} יצרנים על {n(len(hx))} סוגים."),
        "status_note": (f"רשימת סוגי החיסון המחייבים דיווח מול הקטלוג ומול רשימת האצוות: "
                        f"ל-{n(len(st_with))} סוגים יש אצוות, {n(len(st_cat))} מופיעים בקטלוג בלי אצוות, "
                        f"ול-{n(len(st_none))} אין שם מסחרי כלל."),
        "status_aria": (f"תרשים טבעת: {n(len(vac))} סוגי החיסון ברשימת הדיווח — {n(len(st_with))} עם אצוות, "
                        f"{n(len(st_cat))} בקטלוג בלבד, {n(len(st_none))} ללא שם מסחרי."),
        "typecat_note": (f"{n(len(vc))} סוגי החיסון עם מספר השמות המסחריים הגדול ביותר בקטלוג, ומתוכם "
                         f"כמה מופיעים ברשימת האצוות."),
        "typecat_aria": (f"גרף עמודות מוערמות: שמות מסחריים בקטלוג לפי סוג חיסון. "
                         f"המוביל {vc.index[0] if len(vc) else ''} עם {n(vc['total'].iloc[0]) if len(vc) else 0} שמות."),
        "blen_note": (f"אורך מספר האצווה (בתווים) לפי יצרן, עבור {n(len(ly))} היצרנים המובילים. לכל יצרן "
                      f"תבנית משלו: האורך החציוני הוא {n(med_len)} תווים, ו-{pct(alpha_share * 100, 0)} "
                      f"ממספרי האצווה מתחילים באות לועזית. התבנית עוזרת לזהות טעויות הקלדה בדיווח."),
        "blen_aria": f"מפת חום: אורך מספר האצווה לפי יצרן, {n(len(ly))} יצרנים.",
        "newest_note": (f"{n(len(newest))} השמות המסחריים בעלי קוד התרכיב הגבוה ביותר בקטלוג, "
                        f"ומספר האצוות הרשומות לכל אחד."),
    }
    if evo:
        labels["evo_title"] = f"השמות המסחריים של {evo['type']} לפי קוד בקטלוג"
        labels["evo_note"] = (f"כל השמות המסחריים של {evo['type']} ({evo['gloss']})"
                              + (f" — {n(EVO_MAX)} בעלי הקוד הגבוה ביותר" if evo["cut"] else "")
                              + f", מסודרים לפי קוד התרכיב. לכל אחד מספר האצוות הרשומות לו; "
                              f"{n(evo['with_b'])} מתוך {n(evo['n'])} מופיעים באצווה אחת לפחות.")
        labels["evo_aria"] = (f"גרף עמודות: אצוות לכל שם מסחרי של {evo['type']} לפי קוד בקטלוג, "
                              f"{n(evo['with_b'])} מתוך {n(evo['n'])} עם אצוות.")

    # ── agent_data ──────────────────────────────────────────────────────
    summary = (f"קטלוג נחליאלי של משרד הבריאות: {n(total)} מספרי אצווה של חיסונים, מקושרים ל-{n(n_tn_b)} "
               f"שמות מסחריים, {n(types.size)} סוגי חיסון ו-{n(manu_b.size)} יצרנים. "
               f"המוביל הוא {lead_p} של {prod_info[lead_p][1]} עם {pct(share_top * 100)} מהאצוות.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["חיסונים", "אצוות", "תרכיבים", "נחליאלי", "יצרני תרופות", "רפואה מונעת"],
        "related_ids": [
            "7a973115-c27c-40f4-8072-07bbe3aef3d2",
            "a8b76aca-af26-4984-ad6e-134921a02031",
            "a25e63f2-4f22-4eff-a696-e7c6d20c9e27",
        ],
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "types": types_chart,
            "tree": tree,
            "products": products_chart,
            "pareto": pareto_chart,
            "manu": manu_chart,
            "manucat": manucat_chart,
            "heat": heat_chart,
            "status": status_chart,
            "typecat": typecat_chart,
            "evo": evo,
            "blen": blen_chart,
        },
        "tables": {
            "types": types_table,
            "products": products_table,
            "pareto": pareto_table,
            "manu": manu_table,
            "manucat": manucat_table,
            "status": status_table,
            "typecat": typecat_table,
            "blen": blen_table,
            "newest": newest_table,
        },
        "insights": insights,
        "labels": labels,
    }
