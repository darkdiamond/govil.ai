"""ספר סיווג טובין ביבוא — the Israeli import customs tariff book.

Two inputs (both Hebrew; the English twins carry the same codes and are not
read — their English tariff column is also less complete):

- ``tariff``   — the general customs book (CustomsBookTypeID 1): one row per
  classification line, from HS sections (חלק) and chapters (פרק) down to
  Israeli national sub-items, with the customs duty and purchase-tax strings.
  Rows with a negative code (category 2) are the special-provision
  supplements (פרטי התוספות), analysed apart from the HS chapters.
- ``autonomy`` — the autonomy book (CustomsBookTypeID 3), a smaller book of
  lines with their own customs rates; compared line by line with the general
  book on the full classification code.

The book is a snapshot (republished daily with small edits), so there is no
time axis; the "end date" columns are validity dates of the rates, shown as a
calendar of expiries — never compared with the wall clock.
"""
import re

import pandas as pd

TOP_CHAPTERS = 12
TOP_UNITS = 8
TOP_RATES_TABLE = 10
AUTO_RATE_CATS = 8
END_DATE_MAX_BUCKETS = 12
LRI, PDI = "⁦", "⁩"
MINUS = "−"

# HS sections → chapter ranges (the fixed international Harmonized System
# layout; chapters 98–99 are the Israeli national annex, section XXII).
SECTION_RANGES = [
    ("I", 1, 5), ("II", 6, 14), ("III", 15, 15), ("IV", 16, 24),
    ("V", 25, 27), ("VI", 28, 38), ("VII", 39, 40), ("VIII", 41, 43),
    ("IX", 44, 46), ("X", 47, 49), ("XI", 50, 63), ("XII", 64, 67),
    ("XIII", 68, 70), ("XIV", 71, 71), ("XV", 72, 83), ("XVI", 84, 85),
    ("XVII", 86, 89), ("XVIII", 90, 92), ("XIX", 93, 93), ("XX", 94, 96),
    ("XXI", 97, 97), ("XXII", 98, 99),
]
SECTION_ORDER = [s for s, _, _ in SECTION_RANGES]
FOOD_SECTIONS = {"I", "II", "III", "IV"}   # animals, plants, fats, prepared food

FORM_LABELS = {
    "exempt": "פטור",
    "adval": "שיעור באחוזים",
    "mixed": "משולב (אחוז וסכום, תקרה או רצפה)",
    "specific": "סכום קצוב ליחידה",
    "relative": "שיעור יחסי מהמס החל",
    "rules": "לפי כללים",
    "other": "צורה אחרת",
    "none": "ללא שיעור",
}
FORM_ORDER = ["exempt", "adval", "mixed", "specific", "relative", "rules", "other", "none"]
DUTIABLE = {"adval", "mixed", "specific", "relative", "other"}
PTAX_LIABLE = {"adval", "mixed", "specific", "relative", "rules", "other"}

LEVELS = [
    ("חלק", "חלק"),
    ("פרק", "פרק (שתי ספרות)"),
    ("פרט", "פרט (ארבע ספרות)"),
    ("פרט משנה", "פרט משנה (שש ספרות)"),
    ("סעיף ישראלי", "סעיף ישראלי (תת־חלוקה לאומית)"),
]

RATE_BINS = [(0, 5, "עד 5%"), (5, 10, "5%–10%"), (10, 20, "10%–20%"),
             (20, 50, "20%–50%"), (50, 100, "50%–100%"), (100, None, "מעל 100%")]

CMP_ORDER = ["higher", "same", "lower", "noncomp", "missing"]
CMP_LABELS = {
    "higher": "גבוה יותר בספר האוטונומיה",
    "same": "זהה לספר המכס",
    "lower": "נמוך יותר בספר האוטונומיה",
    "noncomp": "לא ניתן להשוואה ישירה",
    "missing": "הסיווג אינו בספר המכס",
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def rate_str(v):
    return f"{v:g}%"


def _clean(s):
    s = s.strip()
    return "" if s.upper() == "NULL" else s


def tariff_form(s):
    s = _clean(s)
    if not s:
        return "none"
    if s == "פטור":
        return "exempt"
    if "מהמס החל" in s:
        return "relative"
    if "כללים" in s:
        return "rules"
    if re.fullmatch(r"שיעור\s*[\d.]+\s*%", s):
        return "adval"
    has_sh = "₪" in s
    has_pct = "%" in s
    if has_sh and has_pct:
        return "mixed"
    if has_sh:
        return "specific"
    return "other"


def adval_rate(s):
    m = re.fullmatch(r"שיעור\s*([\d.]+)\s*%", _clean(s))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def ceiling_pct(s):
    """The ad-valorem ceiling of a compound duty ('… אל"י מ-X%')."""
    vals = [float(x) for x in re.findall(r'אל"י\s*מ-\s*([\d.]+)\s*%', _clean(s))
            if re.fullmatch(r"\d+(\.\d+)?", x)]
    return max(vals) if vals else None


def section_of(ch):
    for s, lo, hi in SECTION_RANGES:
        if lo <= ch <= hi:
            return s
    return None


def short(s, k=30):
    s = s.strip()
    return s if len(s) <= k else s[:k].rstrip(" ,;-") + "…"


def chapter_name_map(df):
    out = {}
    rows = df[df["level"] == "פרק"].sort_values("code")
    for _, r in rows.iterrows():
        nm = re.sub(r"^\s*פרק\s*-?\s*\d+\s*-?\s*", "", r["desc"]).strip()
        nm = re.split(r"[;]", nm)[0].strip()
        if r["chapter"] not in out:
            out[r["chapter"]] = nm or f"פרק {r['chapter']}"
    return out


def section_name_map(raw):
    out = {}
    for desc in sorted(raw["GoodsDescription"].tolist()):
        m = re.match(r"^\s*חלק\s*-?\s*([IVXL]+)\b\s*-?\s*(.*)$", desc.strip())
        if m and m.group(1) in SECTION_ORDER and m.group(1) not in out:
            nm = re.split(r"[;,]", m.group(2).strip())[0].strip()
            out[m.group(1)] = nm or f"חלק {m.group(1)}"
    return out


def level_of(h):
    h = h.strip()
    for key, _ in sorted(LEVELS, key=lambda kv: -len(kv[0])):
        if h == key or h.startswith(key + " "):
            return key
    return h or "ללא רמה"


def _prepare_tariff(df):
    out = pd.DataFrame({
        "ch_raw": df["CustomsItem_2_Digits"].str.strip(),
        "h4": df["CustomsItem_4_Digits"].str.strip(),
        "h6": df["CustomsItem_6_Digits"].str.strip(),
        "code": df["CustomsItemFullClassification"].str.strip(),
        "hier": df["HierarchicLocation"].str.strip(),
        "desc": df["GoodsDescription"].str.strip(),
        "unit": df["MeasurementUnitDescription"].map(_clean),
        "item_end": df["CustomsItemEndDate"].map(_clean),
        "duty": df["CustomsTariff"].map(_clean),
        "duty_end": df["CustomsTariffEndDate"].map(_clean),
        "ptax": df["PurchaseTaxTariff"].map(_clean),
        "ptax_end": df["PurchaseTaxTariffEndDate"].map(_clean),
        "cat": df["CustomsItemCategoryID"].str.strip(),
    })
    out["level"] = out["hier"].map(level_of)
    is_hs = out["ch_raw"].str.fullmatch(r"\d{1,2}") & (out["level"] != "חלק")
    out["chapter"] = ""
    out.loc[is_hs, "chapter"] = out.loc[is_hs, "ch_raw"].str.zfill(2)
    out["is_hs"] = is_hs
    out["is_special"] = out["ch_raw"].str.startswith("-")
    out["cf"] = out["duty"].map(tariff_form)
    out["pf"] = out["ptax"].map(tariff_form)
    out["rate"] = out["duty"].map(adval_rate)
    return out


def _date_he(s):
    try:
        y, m, d = s.split("-")
        return f"{int(d)}.{int(m)}.{y}"
    except ValueError:
        return s


def compute(frames):
    raw = frames["tariff"]
    t = _prepare_tariff(raw)
    total = len(t)
    hs = t[t["is_hs"]].copy()
    special = t[t["is_special"]]
    ch_names = chapter_name_map(t)
    sec_names = section_name_map(raw)
    n_chapters = int((hs["level"] == "פרק").sum())

    def brief(c):
        return short(re.split(r"[,(]", ch_names.get(c, "")) [0].strip() or f"פרק {int(c)}", 40)

    def ch_label(c):
        return f"{int(c)} · {short(ch_names.get(c, 'פרק ' + c), 22)}"

    def sec_label(s):
        return f"{short(sec_names.get(s, 'חלק ' + s), 24)} ({s})"

    hs["section"] = hs["chapter"].map(lambda c: section_of(int(c)) or "")
    rated = hs[hs["cf"] != "none"]
    n_rated = len(rated)
    n_exempt = int((rated["cf"] == "exempt").sum())
    dut = rated[rated["cf"].isin(DUTIABLE)]
    n_dut = len(dut)
    exempt_share = n_exempt / n_rated * 100 if n_rated else 0.0

    # ---- treemap: section → chapter by number of lines ----------------
    tree = []
    sec_rows = []
    for s in SECTION_ORDER:
        sub = hs[hs["section"] == s]
        if sub.empty:
            continue
        kids = []
        for c, g in sorted(sub.groupby("chapter"), key=lambda kv: kv[0]):
            kids.append({"name": ch_label(c), "value": int(len(g))})
        tree.append({"name": sec_label(s), "value": int(len(sub)), "children": kids})
        sr = sub[sub["cf"] != "none"]
        sd = int(sr["cf"].isin(DUTIABLE).sum())
        sec_rows.append({
            "sec": s, "name": sec_label(s), "lines": int(len(sub)),
            "chapters": int(sub["chapter"].nunique()), "rated": int(len(sr)),
            "dut": sd, "share": (sd / len(sr) * 100) if len(sr) else 0.0,
        })

    # ---- hierarchy levels ---------------------------------------------
    lv_counts = t[~t["is_special"]]["level"].value_counts()
    lv_rows = [(lab, int(lv_counts.get(k, 0))) for k, lab in LEVELS if lv_counts.get(k, 0)]
    known = {k for k, _ in LEVELS}
    for k in sorted(set(lv_counts.index) - known):
        lv_rows.append((k, int(lv_counts[k])))

    # ---- duty form split ----------------------------------------------
    cf_counts = rated["cf"].value_counts()
    regime = [(FORM_LABELS[f], int(cf_counts.get(f, 0))) for f in FORM_ORDER
              if f != "none" and cf_counts.get(f, 0)]

    # ---- dutiable lines by chapter, stacked by form --------------------
    dut_forms = [f for f in ["adval", "mixed", "specific", "relative", "other"]
                 if (dut["cf"] == f).any()]
    dch = dut.groupby("chapter").size()
    dch = sorted(dch.items(), key=lambda kv: (-kv[1], kv[0]))
    top_ch = [c for c, _ in dch[:TOP_CHAPTERS]]
    chap_series = []
    for f in dut_forms:
        vals = [int(((dut["chapter"] == c) & (dut["cf"] == f)).sum()) for c in top_ch]
        chap_series.append({"name": FORM_LABELS[f], "data": vals})
    rated_by_ch = rated.groupby("chapter").size()
    chap_table = [{
        "name": ch_label(c), "dut": n(v), "rated": n(rated_by_ch.get(c, 0)),
        "share": f"{v / rated_by_ch.get(c, 1) * 100:.0f}%"} for c, v in dch[:TOP_CHAPTERS]]
    others_dut = sum(v for _, v in dch[TOP_CHAPTERS:])

    # ---- ad valorem rate distribution ----------------------------------
    rates = rated["rate"].dropna()
    rates = rates[rates > 0]
    bins = []
    for lo, hi, lab in RATE_BINS:
        m = rates > lo
        if hi is not None:
            m &= rates <= hi
        bins.append((lab, int(m.sum())))
    rate_vc = rates.value_counts()
    rate_vc = sorted(rate_vc.items(), key=lambda kv: (-kv[1], kv[0]))
    mode_rate, mode_n = (rate_vc[0] if rate_vc else (None, 0))
    max_rate = float(rates.max()) if len(rates) else None
    median_rate = float(rates.median()) if len(rates) else None

    # ---- top headings by highest ad valorem rate ------------------------
    head_desc = (t[t["level"] == "פרט"].sort_values("code")
                 .drop_duplicates("h4").set_index("h4")["desc"])
    hr = rated[rated["rate"].notna() & (rated["rate"] > 0)]
    hg = hr.groupby("h4").agg(mx=("rate", "max"), cnt=("rate", "size"),
                              ch=("chapter", "first")).reset_index()
    hg = hg.sort_values(["mx", "cnt", "h4"], ascending=[False, False, True]).head(TOP_RATES_TABLE)
    top_rates = [{
        "code": f"{r.h4[:2]}.{r.h4[2:]}" if len(r.h4) == 4 else r.h4,
        "desc": short(re.sub(r"\s*[-:]+\s*$", "", head_desc.get(r.h4, "")) or ch_names.get(r.ch, ""), 60),
        "max": rate_str(r.mx), "cnt": n(r.cnt)} for r in hg.itertuples()]

    # ---- customs × purchase tax cross-tab -------------------------------
    any_rate = hs[(hs["cf"] != "none") | (hs["pf"] != "none")]
    xf = [f for f in FORM_ORDER if (any_rate["cf"] == f).any()]
    yf = [f for f in FORM_ORDER if (any_rate["pf"] == f).any()]
    ct = any_rate.groupby(["cf", "pf"]).size()
    cells = []
    cross_table = []
    for yi, pf_ in enumerate(yf):
        row = []
        for xi, cf_ in enumerate(xf):
            v = int(ct.get((cf_, pf_), 0))
            row.append(n(v))
            if v:
                cells.append([xi, yi, v])
        cross_table.append({"name": FORM_LABELS[pf_], "cells": row})
    exempt_cust_ptax = int(((any_rate["cf"] == "exempt") & any_rate["pf"].isin(PTAX_LIABLE)).sum())

    # ---- purchase tax by chapter -----------------------------------------
    pl = hs[hs["pf"].isin(PTAX_LIABLE)]
    n_ptax = len(pl)
    p_forms = [f for f in ["adval", "specific", "mixed", "rules", "relative", "other"]
               if (pl["pf"] == f).any()]
    pch = sorted(pl.groupby("chapter").size().items(), key=lambda kv: (-kv[1], kv[0]))
    ptop = [c for c, _ in pch[:TOP_CHAPTERS]]
    ptax_series = [{"name": FORM_LABELS[f],
                    "data": [int(((pl["chapter"] == c) & (pl["pf"] == f)).sum()) for c in ptop]}
                   for f in p_forms]
    ptax_table = [{"name": ch_label(c), "count": n(v)} for c, v in pch[:TOP_CHAPTERS]]
    p_rates = pl["ptax"].map(adval_rate).dropna()
    p_rate_vc = sorted(p_rates.value_counts().items(), key=lambda kv: (-kv[1], kv[0]))

    # ---- measurement units of rated lines ---------------------------------
    uv = rated["unit"].replace("", "ללא יחידה").value_counts()
    uv = sorted(uv.items(), key=lambda kv: (-kv[1], kv[0]))
    units = uv[:TOP_UNITS]
    rest = sum(v for _, v in uv[TOP_UNITS:])
    if rest:
        units.append(("יחידות אחרות", rest))
    spec_units = dut[dut["cf"].isin(["specific", "mixed"])]["unit"].replace("", "ללא יחידה").value_counts()
    spec_units = sorted(spec_units.items(), key=lambda kv: (-kv[1], kv[0]))

    # ---- validity end dates ------------------------------------------------
    def date_counts(col, frame):
        s = frame[col]
        s = s[s.str.fullmatch(r"\d{4}-\d{2}-\d{2}")]
        return s.value_counts()

    dc_duty = date_counts("duty_end", hs)
    dc_ptax = date_counts("ptax_end", hs)
    dc_item = date_counts("item_end", hs)
    all_dates = sorted(set(dc_duty.index) | set(dc_ptax.index) | set(dc_item.index))
    by_year = len(all_dates) > END_DATE_MAX_BUCKETS
    if by_year:
        def agg(vc):
            out = {}
            for k, v in vc.items():
                out[k[:4]] = out.get(k[:4], 0) + int(v)
            return out
        a_d, a_p, a_i = agg(dc_duty), agg(dc_ptax), agg(dc_item)
        keys = sorted(set(a_d) | set(a_p) | set(a_i))
        x_lab = keys
    else:
        a_d, a_p, a_i = ({k: int(v) for k, v in vc.items()} for vc in (dc_duty, dc_ptax, dc_item))
        keys = all_dates
        x_lab = [_date_he(k) for k in keys]
    end_chart = {"x": x_lab, "duty": [a_d.get(k, 0) for k in keys],
                 "ptax": [a_p.get(k, 0) for k in keys], "item": [a_i.get(k, 0) for k in keys]}
    end_table = [{"date": x_lab[i], "duty": n(end_chart["duty"][i]),
                  "ptax": n(end_chart["ptax"][i]), "item": n(end_chart["item"][i])}
                 for i in range(len(keys))]
    duty_dated = int(hs["duty_end"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").sum())
    rated_with_date = int(rated["duty_end"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").sum())
    top_end = sorted(dc_duty.items(), key=lambda kv: (-kv[1], kv[0]))[0] if len(dc_duty) else None

    # ---- autonomy book -----------------------------------------------------
    a = frames["autonomy"]
    au = pd.DataFrame({
        "ch": pd.to_numeric(a["CustomsItem_2_Digits"].str.strip(), errors="coerce"),
        "code": a["CustomsItemFullClassification"].str.strip(),
        "duty": a["CustomsTariff"].map(_clean),
    })
    au = au[au["ch"].notna()].copy()
    au["chapter"] = au["ch"].astype(int).map(lambda v: f"{v:02d}")
    au["cf"] = au["duty"].map(tariff_form)
    au_total = len(au)
    au_chapters = int(au["chapter"].nunique())
    au_rated = au[au["cf"] != "none"].copy()
    main_by_code = t.drop_duplicates("code").set_index("code")["duty"]

    def comp_val(s):
        f = tariff_form(s)
        if f == "exempt":
            return 0.0
        if f == "adval":
            return adval_rate(s)
        return None

    def cmp_cat(row):
        if row["code"] not in main_by_code.index:
            return "missing"
        mv = comp_val(main_by_code[row["code"]])
        av = comp_val(row["duty"])
        if mv is None or av is None:
            if _clean(row["duty"]) == _clean(main_by_code[row["code"]]):
                return "same"
            return "noncomp"
        if abs(av - mv) < 1e-9:
            return "same"
        return "higher" if av > mv else "lower"

    au_rated["cmp"] = au_rated.apply(cmp_cat, axis=1) if len(au_rated) else []
    au_rated["main_duty"] = au_rated["code"].map(lambda c: main_by_code.get(c, ""))
    cmp_counts = au_rated["cmp"].value_counts()
    cmp_present = [k for k in CMP_ORDER if cmp_counts.get(k, 0)]
    ach = sorted(au_rated.groupby("chapter").size().items(), key=lambda kv: (-kv[1], kv[0]))
    atop = [c for c, _ in ach[:TOP_CHAPTERS]]
    auto_series = [{"name": CMP_LABELS[k],
                    "data": [int(((au_rated["chapter"] == c) & (au_rated["cmp"] == k)).sum())
                             for c in atop]} for k in cmp_present]
    auto_ch_table = [{"name": ch_label(c), "count": n(v),
                      "higher": n(((au_rated["chapter"] == c) & (au_rated["cmp"] == "higher")).sum())}
                     for c, v in ach[:TOP_CHAPTERS]]

    def rate_cat(s):
        f = tariff_form(s)
        if f == "exempt":
            return "פטור"
        if f == "adval":
            return rate_str(adval_rate(s))
        if f == "none":
            return "ללא שיעור"
        return "שיעור מורכב"

    matched = au_rated[au_rated["cmp"] != "missing"]
    a_cat = matched["duty"].map(rate_cat).value_counts()
    m_cat = matched["main_duty"].map(rate_cat).value_counts()
    cats = sorted(set(a_cat.index) | set(m_cat.index),
                  key=lambda c: (-(a_cat.get(c, 0) + m_cat.get(c, 0)), c))
    keep = cats[:AUTO_RATE_CATS]
    drop = cats[AUTO_RATE_CATS:]

    def cat_key(c):
        if c == "פטור":
            return (0, 0.0, c)
        m = re.fullmatch(r"([\d.]+)%", c)
        if m:
            return (1, float(m.group(1)), c)
        return (2, 0.0, c)
    keep = sorted(keep, key=cat_key)
    auto_rates = {"x": keep + (["אחר"] if drop else []),
                  "auto": [int(a_cat.get(c, 0)) for c in keep] + ([int(sum(a_cat.get(c, 0) for c in drop))] if drop else []),
                  "main": [int(m_cat.get(c, 0)) for c in keep] + ([int(sum(m_cat.get(c, 0) for c in drop))] if drop else [])}
    auto_rates_table = [{"name": auto_rates["x"][i], "auto": n(auto_rates["auto"][i]),
                         "main": n(auto_rates["main"][i])} for i in range(len(auto_rates["x"]))]
    n_higher = int(cmp_counts.get("higher", 0))
    n_lower = int(cmp_counts.get("lower", 0))
    n_missing = int(cmp_counts.get("missing", 0))
    n_comparable = int(sum(cmp_counts.get(k, 0) for k in ["higher", "same", "lower"]))
    au_a_rates = au_rated[au_rated["cf"] == "adval"]["duty"].map(adval_rate).dropna()
    au_mode = sorted(au_a_rates.value_counts().items(), key=lambda kv: (-kv[1], kv[0]))

    # ---- conditional and special-provision lines ---------------------------
    cond = hs[hs["cat"] == "3"]
    n_cond = len(cond)
    cond_ch = sorted(cond.groupby("chapter").size().items(), key=lambda kv: (-kv[1], kv[0]))
    n_special = len(special)
    sp_rated = special[special["cf"] != "none"]
    sp_exempt = int((sp_rated["cf"] == "exempt").sum())

    # ---- Israeli national subdivisions --------------------------------------
    n_il = int((hs["level"] == "סעיף ישראלי").sum())
    n_h6 = int(hs.loc[hs["level"] == "פרט משנה", "h6"].nunique())
    n_h4 = int((hs["level"] == "פרט").sum())

    # ---------------------------------------------------------------- insights
    def ins_exempt():
        if not n_rated:
            return None
        lead = "הרוב המכריע" if exempt_share >= 80 else ("רוב" if exempt_share > 50 else "מיעוט")
        return (f"{lead} של שורות התעריף בפרקי הסיווג פטורות ממכס: {n(n_exempt)} מתוך "
                f"{n(n_rated)} ({pct(exempt_share)}). רק {n(n_dut)} שורות נושאות מכס — "
                f"בשיעור באחוזים, בסכום קצוב ליחידה או בשילוב של השניים.")

    def ins_food():
        if not n_dut or not n_rated:
            return None
        f_rated = int(rated["section"].isin(FOOD_SECTIONS).sum())
        f_dut = int(dut["section"].isin(FOOD_SECTIONS).sum())
        s_all = f_rated / n_rated * 100
        s_dut = f_dut / n_dut * 100
        if s_all <= 0 or s_dut / s_all < 1.5:
            return None
        return (f"המכס מרוכז במזון ובחקלאות: חלקים I עד IV (בעלי חיים, צמחים, שומנים ומזון "
                f"מעובד) מחזיקים {pct(s_all)} משורות התעריף, אך {pct(s_dut)} מהשורות החייבות "
                f"במכס ({n(f_dut)} מתוך {n(n_dut)}).")

    def ins_leader():
        if len(dch) < 2 or not n_dut:
            return None
        (c1, v1), (c2, v2) = dch[0], dch[1]
        share = v1 / n_dut * 100
        if share < 10 or v1 < v2 * 1.2:
            return None
        return (f"פרק {int(c1)} ({brief(c1)}) מוביל במספר השורות החייבות "
                f"במכס: {n(v1)} שורות, {pct(share)} מכלל השורות החייבות — לפני פרק {int(c2)} "
                f"עם {n(v2)}.")

    def ins_rates():
        if max_rate is None or mode_rate is None or not len(rates):
            return None
        top = hg.iloc[0] if len(hg) else None
        where = ""
        if top is not None:
            where = f" (פרט {top_rates[0]['code']}, {short(re.split(r'[,;(]', top_rates[0]['desc'])[0].strip(), 40)})"
        return (f"השיעור הנפוץ ביותר במכס באחוזים הוא {rate_str(mode_rate)} — ב-{n(mode_n)} מתוך "
                f"{n(len(rates))} שורות; החציון {rate_str(median_rate)}, והשיעור הגבוה ביותר "
                f"{rate_str(max_rate)}{where}.")

    def ins_ceiling():
        ce = dut[dut["cf"] == "mixed"]["duty"].map(ceiling_pct).dropna()
        if ce.empty:
            return None
        hi = ce[ce > 100]
        if hi.empty:
            return None
        return (f"במכס המשולב (סכום קצוב ליחידה עם תקרה באחוזים) התקרה מגיעה עד "
                f"{rate_str(float(ce.max()))}; ב-{n(len(hi))} מתוך {n(len(ce))} שורות כאלה התקרה "
                f"עולה על 100% מערך הטובין.")

    def ins_ptax():
        if not n_ptax or not pch:
            return None
        c1, v1 = pch[0]
        return (f"{n(n_ptax)} שורות חייבות במס קנייה, ופרק {int(c1)} "
                f"({brief(c1)}) מוביל עם {n(v1)} מהן. "
                f"ב-{n(exempt_cust_ptax)} שורות הטובין פטורים ממכס אך חייבים במס קנייה.")

    def ins_enddate():
        if not top_end or not rated_with_date or not n_rated:
            return None
        d, v = top_end
        share = v / n_rated * 100
        if share < 50:
            return None
        return (f"ל-{pct(share)} משורות התעריף ({n(v)}) נקבע אותו מועד סיום תוקף לשיעור "
                f"המכס: {_date_he(d)}.")

    def ins_israeli():
        if not n_il or not len(hs):
            return None
        share = n_il / len(hs) * 100
        if share < 20:
            return None
        return (f"{pct(share)} משורות הספר ({n(n_il)}) הן סעיפים ישראליים — חלוקה לאומית מעבר "
                f"לרמת שש הספרות הבין־לאומית, המפצלת {n(n_h6)} פרטי משנה ו-{n(n_h4)} פרטים.")

    def ins_auto():
        if not len(au_rated) or not n_comparable:
            return None
        hs_ = n_higher / n_comparable * 100
        if n_higher == 0:
            return None
        txt = (f"בספר האוטונומיה {n(n_higher)} מתוך {n(n_comparable)} השורות הניתנות להשוואה "
               f"({pct(hs_)}) נושאות שיעור מכס גבוה מזה שבספר המכס הכללי לאותו סיווג")
        if n_lower:
            txt += f", ו-{n(n_lower)} נמוך ממנו"
        txt += "."
        if n_missing:
            txt += f" {n(n_missing)} סיווגים בספר האוטונומיה אינם מופיעים בספר המכס הנוכחי."
        return txt

    def ins_cond():
        if not n_cond or not cond_ch:
            return None
        c1, v1 = cond_ch[0]
        if v1 / n_cond < 0.25:
            return (f"{n(n_cond)} שורות הן סיווגים מותנים — השיעור חל רק באישור גורם מוסמך "
                    f"לייעוד הטובין.")
        return (f"{n(n_cond)} שורות הן סיווגים מותנים — השיעור חל רק באישור גורם מוסמך לייעוד "
                f"הטובין; {n(v1)} מהן בפרק {int(c1)} ({brief(c1)}).")

    rules = [
        ("exempt", ins_exempt()), ("food", ins_food()), ("leader", ins_leader()),
        ("rates", ins_rates()), ("ceiling", ins_ceiling()), ("ptax", ins_ptax()),
        ("enddate", ins_enddate()), ("israeli", ins_israeli()), ("auto", ins_auto()),
        ("cond", ins_cond()),
    ]
    insights = [{"id": i, "text_he": x} for i, x in rules if x]

    # ---------------------------------------------------------------- kpis
    kpis = {
        "lines": {"value": total, "display": n(total), "tone": "brand"},
        "chapters": {"value": n_chapters, "display": n(n_chapters), "tone": "brand"},
        "exempt": {"value": round(exempt_share, 1), "display": f"{exempt_share:.1f}%",
                   "tone": "ok" if exempt_share >= 80 else "info"},
        "dutiable": {"value": n_dut, "display": n(n_dut), "tone": "info"},
        "max_rate": {"value": max_rate or 0, "display": rate_str(max_rate) if max_rate else "0%",
                     "tone": "danger" if (max_rate or 0) >= 100 else "warn"},
        "ptax": {"value": n_ptax, "display": n(n_ptax), "tone": "brand"},
        "cond": {"value": n_cond, "display": n(n_cond), "tone": "brand"},
        "auto": {"value": au_total, "display": n(au_total), "tone": "brand"},
    }

    # ---------------------------------------------------------------- labels
    top_sec = max(sec_rows, key=lambda r: (r["share"], r["sec"])) if sec_rows else None
    labels = {
        "lede": (f"ספר סיווג הטובין ביבוא של רשות המסים: {n(total)} שורות סיווג ב-{n(n_chapters)} "
                 f"פרקים, מחלקי מערכת ההרמוניזציה הבין־לאומית ועד סעיפים ישראליים, ולכל שורה "
                 f"שיעור המכס ומס הקנייה החלים עליה. {n(n_rated)} שורות בפרקי הסיווג נושאות "
                 f"שיעור מכס, ומהן {pct(exempt_share)} פטורות. לצד הספר הכללי מופיעים "
                 f"{n(n_special)} שורות של פרטי התוספות (הסדרי פטור והקלה מיוחדים) וספר "
                 f"האוטונומיה, עם {n(au_total)} שורות ב-{n(au_chapters)} פרקים."),
        "dut_kpi": "שורות חייבות במכס",
        "max_kpi": "שיעור המכס הגבוה ביותר באחוזים",
        "ptax_kpi": "שורות חייבות במס קנייה",
        "tree_note": (f"מספר שורות הסיווג בכל פרק, מקובצות לפי {n(len(tree))} חלקי מערכת "
                      f"ההרמוניזציה. השטח של כל ריבוע יחסי למספר השורות; פרטי התוספות אינם "
                      f"נכללים."),
        "tree_aria": f"מפת עץ: שורות הסיווג לפי חלק ופרק, {n(len(hs))} שורות.",
        "tree_caption": "שורות הסיווג לפי חלק: מספר שורות, פרקים, שורות עם שיעור ושורות חייבות במכס.",
        "levels_note": (f"כל רמה בהיררכיה מפצלת את הקודמת: {n(n_h4)} פרטים, {n(n_h6)} פרטי משנה "
                        f"ו-{n(n_il)} סעיפים ישראליים."),
        "levels_aria": "תרשים עמודות: מספר שורות הסיווג בכל רמה בהיררכיה.",
        "levels_caption": "מספר שורות הסיווג לפי רמה בהיררכיה (ללא פרטי התוספות).",
        "regime_note": (f"צורת שיעור המכס ב-{n(n_rated)} שורות התעריף בפרקי הסיווג. שורות כותרת "
                        f"ללא שיעור אינן נכללות."),
        "regime_aria": "תרשים טבעת: שורות התעריף לפי צורת שיעור המכס.",
        "regime_caption": "שורות התעריף לפי צורת שיעור המכס.",
        "sections_note": ("שיעור השורות החייבות במכס מבין שורות התעריף בכל חלק. "
                          + (f"השיעור הגבוה ביותר בחלק {top_sec['sec']}: {pct(top_sec['share'])}."
                             if top_sec else "")),
        "sections_aria": "תרשים עמודות: אחוז השורות החייבות במכס בכל חלק.",
        "sections_caption": "שורות חייבות במכס ושיעורן מבין שורות התעריף, לפי חלק.",
        "chapters_note": (f"{len(top_ch)} הפרקים עם מספר השורות החייבות במכס הגבוה ביותר, לפי צורת "
                          f"השיעור."
                          + (f" בשאר הפרקים יחד {n(others_dut)} שורות חייבות." if others_dut else "")),
        "chapters_aria": f"תרשים עמודות מוערמות: שורות חייבות במכס ב-{len(top_ch)} הפרקים המובילים.",
        "chapters_caption": "שורות חייבות במכס לפי פרק, ושיעורן מבין שורות התעריף בפרק.",
        "rates_note": (f"התפלגות {n(len(rates))} השורות שבהן המכס הוא שיעור באחוזים בלבד. "
                       f"שורות במכס משולב או בסכום קצוב אינן נכללות."),
        "rates_aria": "תרשים עמודות: שורות במכס באחוזים לפי טווח השיעור.",
        "rates_caption": "מספר שורות לפי טווח שיעור המכס באחוזים.",
        "top_rates_caption": f"{len(top_rates)} הפרטים עם שיעור המכס באחוזים הגבוה ביותר.",
        "cross_note": (f"כל שורה בפרקי הסיווג שיש לה שיעור מכס או מס קנייה, לפי צירוף שתי צורות "
                       f"המס. ב-{n(exempt_cust_ptax)} שורות הטובין פטורים ממכס אך חייבים במס קנייה."),
        "cross_aria": "מפת חום: שורות לפי צורת שיעור המכס וצורת מס הקנייה.",
        "cross_caption": "מספר שורות לפי צורת מס הקנייה (שורות) וצורת המכס (עמודות).",
        "ptax_note": (f"{len(ptop)} הפרקים עם מספר השורות החייבות במס קנייה הגבוה ביותר, לפי צורת "
                      f"המס."
                      + (f" השיעור הנפוץ באחוזים: {rate_str(p_rate_vc[0][0])} ({n(p_rate_vc[0][1])} שורות)."
                         if p_rate_vc else "")),
        "ptax_aria": f"תרשים עמודות מוערמות: שורות חייבות במס קנייה ב-{len(ptop)} הפרקים המובילים.",
        "ptax_caption": "שורות חייבות במס קנייה לפי פרק.",
        "units_note": (f"יחידת המידה הרשומה לשורות התעריף."
                       + (f" במכס בסכום קצוב או משולב היחידה הנפוצה היא {spec_units[0][0]} "
                          f"({n(spec_units[0][1])} שורות)." if spec_units else "")),
        "units_aria": "תרשים עמודות: שורות התעריף לפי יחידת מידה.",
        "units_caption": "מספר שורות התעריף לפי יחידת מידה.",
        "end_note": (("מועדי סיום התוקף הרשומים לשיעורי המכס, למס הקנייה ולסיווג עצמו"
                      + (", מקובצים לפי שנה" if by_year else "")
                      + f". {n(duty_dated)} שורות בפרקי הסיווג נושאות מועד סיום לשיעור המכס; "
                        f"שורות ללא מועד אינן מוצגות.")),
        "end_aria": "תרשים עמודות: מספר שורות לפי מועד סיום תוקף, למכס, למס קנייה ולסיווג.",
        "end_caption": "מספר שורות לפי מועד סיום תוקף.",
        "auto_ch_note": (f"שורות ספר האוטונומיה שיש להן שיעור מכס, ב-{len(atop)} הפרקים המובילים, "
                         f"לפי השוואה לשיעור בספר המכס הכללי לאותו קוד סיווג."),
        "auto_ch_aria": "תרשים עמודות מוערמות: שורות ספר האוטונומיה לפי פרק והשוואה לספר המכס.",
        "auto_ch_caption": "שורות ספר האוטונומיה עם שיעור, ומתוכן בשיעור גבוה מספר המכס, לפי פרק.",
        "auto_rates_note": (f"אותם {n(len(matched))} קודי סיווג, בשני הספרים: כמה שורות בכל שיעור."
                            + (f" בספר האוטונומיה השיעור הנפוץ באחוזים הוא {rate_str(au_mode[0][0])}."
                               if au_mode else "")),
        "auto_rates_aria": "תרשים עמודות: שיעורי המכס בספר האוטונומיה מול ספר המכס לאותם סיווגים.",
        "auto_rates_caption": "מספר שורות לפי שיעור מכס, בספר האוטונומיה ובספר המכס הכללי.",
    }

    charts = {
        "tree": tree,
        "levels": {"names": [k for k, _ in lv_rows], "values": [v for _, v in lv_rows]},
        "regime": [{"name": k, "value": v} for k, v in regime],
        "sections": {"names": [r["name"] for r in sec_rows],
                     "share": [round(r["share"], 1) for r in sec_rows],
                     "dut": [r["dut"] for r in sec_rows]},
        "chapters": {"names": [ch_label(c) for c in top_ch], "series": chap_series},
        "rates": {"names": [b for b, _ in bins], "values": [v for _, v in bins]},
        "cross": {"x": [FORM_LABELS[f] for f in xf], "y": [FORM_LABELS[f] for f in yf],
                  "cells": cells},
        "ptax": {"names": [ch_label(c) for c in ptop], "series": ptax_series},
        "units": {"names": [k for k, _ in units], "values": [v for _, v in units]},
        "end": end_chart,
        "auto_ch": {"names": [ch_label(c) for c in atop], "series": auto_series},
        "auto_rates": auto_rates,
    }
    tables = {
        "sections": [{"name": r["name"], "lines": n(r["lines"]), "chapters": n(r["chapters"]),
                      "rated": n(r["rated"]), "dut": n(r["dut"]),
                      "share": f"{r['share']:.1f}%"} for r in sec_rows],
        "levels": [{"name": k, "count": n(v)} for k, v in lv_rows],
        "regime": [{"name": k, "count": n(v), "share": f"{v / n_rated * 100:.1f}%"}
                   for k, v in regime] if n_rated else [],
        "chapters": chap_table,
        "rates": [{"name": b, "count": n(v)} for b, v in bins],
        "top_rates": top_rates,
        "cross_x": [FORM_LABELS[f] for f in xf],
        "cross": cross_table,
        "ptax": ptax_table,
        "units": [{"name": k, "count": n(v)} for k, v in units],
        "end": end_table,
        "auto_ch": auto_ch_table,
        "auto_rates": auto_rates_table,
    }

    return {
        "agent_data": {
            "summary_he": (f"ספר המכס — סיווג טובין ביבוא: {n(total)} שורות סיווג ב-{n(n_chapters)} פרקים, עם שיעור המכס "
                           f"ומס הקנייה לכל פרט; {pct(exempt_share)} פטורות ממכס. חיפוש לפי פרט מכס או תיאור."),
            "dataset_kind": "registry",
            "suggested_tags": ["מכס", "יבוא", "תעריף המכס", "מס קנייה", "סיווג טובין", "ספר המכס"],
            "related_ids": ["3e4e79f7-643b-4be6-94c2-e47667d42916",
                            "15fd7d7f-da3a-461e-94dd-1dfbbec52a22",
                            "965b52b6-7267-45d9-bccd-020416fbcfb5"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"auto": bool(len(au_rated)), "end": bool(keys), "cross": bool(cells)},
    }
