"""ספר סיווג טובין ביצוא — the Israeli export goods-classification book.

Two inputs, the same book in two languages (CustomsBookTypeID 2):

- ``he`` — the Hebrew book. Page text comes from here (chapter and heading
  names, the hierarchy labels, the "אחרים" catch-all lines). Its datastore
  table was loaded from a CSV with unquoted commas and line breaks, so most
  of its rows are fragments of broken lines; only rows whose leading code
  columns parse as a full classification line are read, and the trailing
  columns (measurement unit) are unreliable even on those.
- ``en`` — the English book, cleanly quoted: the source of each line's
  measurement-unit code and item end date, joined on the full code.

The book is a snapshot with no time axis and no tariff rates (export lines
carry none); the page is about its structure — where the HS classification
is subdivided, how far Israel splits it nationally, and in what unit each
declarable line is reported.
"""
import re

import pandas as pd

TOP_CHAPTERS = 12
TOP_HEADINGS = 10
TOP_UNITS_SEC = 4
TOP_UNITS = 8
ISR_MIN_LINES = 20
LRI, PDI = "⁦", "⁩"

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
# The export book has no section rows, so the (fixed, HS-standard) section
# names are mapped here; an unknown section falls back to "חלק <n>".
SECTION_NAMES = {
    "I": "בעלי חיים ומוצרים מן החי",
    "II": "מוצרים מן הצומח",
    "III": "שומנים ושמנים",
    "IV": "מזון מעובד, משקאות וטבק",
    "V": "מוצרים מינרליים",
    "VI": "מוצרי התעשייה הכימית",
    "VII": "פלסטיק וגומי",
    "VIII": "עורות, פרוות ומוצריהם",
    "IX": "עץ, שעם ומוצרי קליעה",
    "X": "עיסת עץ, נייר וקרטון",
    "XI": "טקסטיל ומוצריו",
    "XII": "הנעלה, כיסויי ראש ומטריות",
    "XIII": "אבן, קרמיקה וזכוכית",
    "XIV": "פנינים, אבנים ומתכות יקרות",
    "XV": "מתכות פשוטות ומוצריהן",
    "XVI": "מכונות וציוד חשמלי",
    "XVII": "כלי רכב, טיס ושיט",
    "XVIII": "מכשירים אופטיים, רפואיים ושעונים",
    "XIX": "נשק ותחמושת",
    "XX": "מוצרים מיוצרים שונים",
    "XXI": "יצירות אמנות ועתיקות",
    "XXII": "פרקים ישראליים מיוחדים",
}

# Hebrew names for known measurement-unit codes — used only when the Hebrew
# file carries no clean name for the code; unknown codes get a generic label.
UNIT_FALLBACK = {
    1: "כל אחד", 2: "זוג", 5: "אלף יחידות", 6: "קילוגרם", 8: "טון",
    10: "קרט", 11: "מטר מעוקב / 1000 ליטר", 12: "ליטר", 19: "מטר",
    28: "מטר רבוע", 49: "אריזה", 51: "אלף סיגריות",
}
NO_UNIT = "יחידה לא מזוהה"
OTHER_UNITS = "יחידות אחרות"

LEVEL_ORDER = ["פרק", "פרט", "פרט משנה אב", "פרט משנה פיצול",
               "סעיף ישראלי א אב", "סעיף ישראלי א פיצול"]
LEVEL_LABELS = {
    "פרק": "פרק",
    "פרט": "פרט (ארבע ספרות)",
    "פרט משנה אב": "פרט משנה (שש ספרות)",
    "פרט משנה פיצול": "פיצול של פרט משנה",
    "סעיף ישראלי א אב": "סעיף ישראלי",
    "סעיף ישראלי א פיצול": "פיצול של סעיף ישראלי",
}

DECL_ORDER = ["heading", "hs6", "national"]
DECL_LABELS = {
    "heading": "ברמת הפרט (ארבע ספרות)",
    "hs6": "ברמת פרט משנה בין־לאומי (שש ספרות)",
    "national": "סעיף ישראלי (חלוקה לאומית)",
}

FANOUT_BINS = [(1, 1, "שורה אחת"), (2, 2, "שתי שורות"), (3, 5, "3-5"),
               (6, 10, "6-10"), (11, 20, "11-20"), (21, None, "יותר מ־20")]

CODE_RE = r"\d{10}(/\d)?"
OTHER_RE = re.compile(r'^[\s"\-–:]*(אחרים|אחרות|אחר)(?=$|[\s:\-–,.;()])')


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def short(s, k=30):
    s = s.strip()
    return s if len(s) <= k else s[:k].rstrip(" ,;-:") + "…"


def clean_desc(s):
    """Strip quoting and trailing hierarchy dashes. A value that opens a quote
    it never closes was cut at an embedded comma by the broken export — it is
    marked with an ellipsis so a fragment never reads as the full name."""
    raw = s.strip()
    cut = raw.startswith('"') and not raw.endswith('"')
    s = raw.strip('"').strip()
    s = re.sub(r"[\s:\-–,;]+$", "", s).strip()
    return s + "…" if cut and s else s


def section_of(ch):
    for s, lo, hi in SECTION_RANGES:
        if lo <= ch <= hi:
            return s
    return ""


def unit_code(s):
    m = re.fullmatch(r"\s*(\d+)(\.0+)?\s*", s)
    return int(m.group(1)) if m else None


def valid_lines(df):
    """Rows that parse as a complete classification line of the export book."""
    ok = (
        df["CustomsBookTypeID"].str.strip().str.fullmatch(r"\d+")
        & df["CustomsItem_2_Digits"].str.strip().str.fullmatch(r"\d{2}")
        & df["CustomsItem_4_Digits"].str.strip().str.fullmatch(r"\d{4}")
        & df["CustomsItem_6_Digits"].str.strip().str.fullmatch(r"\d{6}")
        & df["CustomsItemFullClassification"].str.strip().str.fullmatch(CODE_RE)
    )
    out = df[ok].copy()
    out["code"] = out["CustomsItemFullClassification"].str.strip()
    out = out[out["code"].str[:2] == out["CustomsItem_2_Digits"].str.strip()]
    # Full-row tie-break so which duplicate survives never depends on row order.
    keys = ["code"] + [c for c in out.columns if c != "code"]
    return out.sort_values(keys, kind="mergesort").drop_duplicates("code")


def compute(frames):
    he_raw = frames["he"]
    en_raw = frames["en"]
    he = valid_lines(he_raw)
    en = valid_lines(en_raw)
    total = len(he)
    he_frag = len(he_raw) - total
    en_frag = len(en_raw) - len(en)

    t = pd.DataFrame({
        "code": he["code"],
        "ch": he["code"].str[:2],
        "h4": he["code"].str[:4],
        "h6": he["code"].str[:6],
        "hier": he["HierarchicLocation"].str.strip(),
        "desc": he["GoodsDescription"].map(clean_desc),
        "he_unit": he["MeasurementUnitID"].map(unit_code),
        "he_unit_name": he["MeasurementUnitDescription"].str.strip(),
        "he_maslul": he["MaslulMeasurementUnit"].map(unit_code),
    }).reset_index(drop=True)
    t["section"] = t["ch"].map(lambda c: section_of(int(c)))
    t["leaf"] = t["code"].str.contains("/", regex=False)
    t["national"] = t["code"].str[6:10] != "0000"
    t["decl"] = "hs6"
    t.loc[(t["code"].str[4:6] == "00") & ~t["national"], "decl"] = "heading"
    t.loc[t["national"], "decl"] = "national"

    # --- unit: English file first (clean), then a clean Hebrew value -------
    en_unit = en.set_index("code")["MeasurementUnitID"].map(unit_code)
    en_end = en.set_index("code")["CustomsItemEndDate"].str.strip()
    t["unit"] = t["code"].map(en_unit)
    he_ok = t["he_unit"].notna() & t["he_maslul"].notna()
    t["unit"] = t["unit"].where(t["unit"].notna(), t["he_unit"].where(he_ok))

    # Hebrew unit names, from Hebrew rows whose unit columns are unshifted.
    nm = t[he_ok & (t["he_unit_name"] != "") & ~t["he_unit_name"].str.contains(r"\d", regex=True)]
    he_names = {}
    for code_, g in sorted(nm.groupby("he_unit"), key=lambda kv: kv[0]):
        vc = sorted(g["he_unit_name"].value_counts().items(), key=lambda kv: (-kv[1], kv[0]))
        he_names[int(code_)] = vc[0][0]

    def unit_name(u):
        if u is None or pd.isna(u):
            return NO_UNIT
        u = int(u)
        return he_names.get(u) or UNIT_FALLBACK.get(u) or "יחידה אחרת"

    t["unit_name"] = t["unit"].map(unit_name)

    # --- names ---------------------------------------------------------------
    ch_rows = t[t["code"].str[2:10] == "00000000"]
    ch_names = {}
    for _, r in ch_rows.iterrows():
        nm_ = re.sub(r"^\s*פרק\s*-?\s*\d+\s*-?\s*", "", r["desc"]).strip()
        nm_ = re.split(r"[;]", nm_)[0].strip()
        if nm_:
            ch_names[r["ch"]] = nm_
    head_rows = t[(t["code"].str[4:10] == "000000") & (t["code"].str[2:4] != "00")]
    head_desc = head_rows.drop_duplicates("h4").set_index("h4")["desc"]

    def ch_label(c):
        nm_ = ch_names.get(c)
        return f"{int(c)} · {short(nm_, 22)}" if nm_ else f"פרק {int(c)}"

    def brief(c):
        nm_ = ch_names.get(c, "")
        nm_ = re.split(r"[;(]", nm_)[0].strip()
        return short(nm_, 34) if nm_ else ""

    def ch_ref(c):
        b = brief(c)
        return f"פרק {int(c)} ({b})" if b else f"פרק {int(c)}"

    def sec_label(s):
        return f"{SECTION_NAMES.get(s, 'חלק ' + s)} ({s})"

    n_chapters = int(t["ch"].nunique())
    n_headings = int(t.loc[t["code"].str[2:4] != "00", "h4"].nunique())
    n_h6 = int(t.loc[(t["code"].str[4:6] != "00"), "h6"].nunique())

    leaves = t[t["leaf"]].copy()
    n_leaf = len(leaves)
    leaves["other"] = leaves["desc"].map(lambda s: bool(OTHER_RE.match(s)))
    n_nat = int((leaves["decl"] == "national").sum())
    nat_share = n_nat / n_leaf * 100 if n_leaf else 0.0
    n_other = int(leaves["other"].sum())
    other_share = n_other / n_leaf * 100 if n_leaf else 0.0
    n_nat_all = int(t["national"].sum())

    present_secs = [s for s in SECTION_ORDER if (t["section"] == s).any()]

    # ---- treemap: section → chapter by declarable lines ----------------------
    tree, sec_rows = [], []
    for s in present_secs:
        sub = t[t["section"] == s]
        sl = leaves[leaves["section"] == s]
        kids = []
        for c, g in sorted(sl.groupby("ch"), key=lambda kv: kv[0]):
            kids.append({"name": ch_label(c), "value": int(len(g))})
        if kids:
            tree.append({"name": sec_label(s), "value": int(len(sl)), "children": kids})
        nl = len(sl)
        sec_rows.append({
            "sec": s, "name": sec_label(s), "lines": int(len(sub)),
            "chapters": int(sub["ch"].nunique()), "leaves": int(nl),
            "decl": {k: int((sl["decl"] == k).sum()) for k in DECL_ORDER},
            "other": int(sl["other"].sum()),
            "other_share": (sl["other"].sum() / nl * 100) if nl else 0.0,
            "nat_share": ((sl["decl"] == "national").sum() / nl * 100) if nl else 0.0,
        })

    # ---- hierarchy levels (all lines) ----------------------------------------
    lv = t["hier"].replace("", "ללא רמה").value_counts()
    lv_rows = [(LEVEL_LABELS[k], int(lv[k])) for k in LEVEL_ORDER if k in lv.index]
    for k in sorted(set(lv.index) - set(LEVEL_ORDER)):
        lv_rows.append((k, int(lv[k])))

    # ---- declaration level of declarable lines, per section (100%) -----------
    decl_present = [k for k in DECL_ORDER if (leaves["decl"] == k).any()]
    sec_decl = {
        "names": [r["name"] for r in sec_rows if r["leaves"]],
        "series": [{"name": DECL_LABELS[k],
                    "data": [round(r["decl"][k] / r["leaves"] * 100, 1)
                             for r in sec_rows if r["leaves"]],
                    "counts": [r["decl"][k] for r in sec_rows if r["leaves"]]}
                   for k in decl_present],
    }
    decl_totals = [(DECL_LABELS[k], int((leaves["decl"] == k).sum())) for k in decl_present]

    # ---- chapters with the most declarable lines -----------------------------
    lch = sorted(leaves.groupby("ch").size().items(), key=lambda kv: (-kv[1], kv[0]))
    top_ch = [c for c, _ in lch[:TOP_CHAPTERS]]
    chap_series = [{"name": DECL_LABELS[k],
                    "data": [int(((leaves["ch"] == c) & (leaves["decl"] == k)).sum()) for c in top_ch]}
                   for k in decl_present]
    chap_table = [{"name": ch_label(c), "leaves": n(v),
                   "nat": n(((leaves["ch"] == c) & (leaves["decl"] == "national")).sum()),
                   "share": f"{v / n_leaf * 100:.1f}%"} for c, v in lch[:TOP_CHAPTERS]]
    others_leaf = sum(v for _, v in lch[TOP_CHAPTERS:])
    top5_share = sum(v for _, v in lch[:5]) / n_leaf * 100 if n_leaf else 0.0

    # ---- chapters with the highest national-subdivision share ----------------
    ng = leaves.groupby("ch").agg(cnt=("decl", "size"),
                                  nat=("decl", lambda s: int((s == "national").sum())))
    ng = ng[(ng["cnt"] >= ISR_MIN_LINES) & (ng["nat"] > 0)].copy()
    ng["share"] = ng["nat"] / ng["cnt"] * 100
    ng = ng.reset_index().sort_values(["share", "nat", "ch"], ascending=[False, False, True])
    isr = ng.head(TOP_CHAPTERS)
    isr_chart = {"names": [ch_label(c) for c in isr["ch"]],
                 "share": [round(float(v), 1) for v in isr["share"]],
                 "nat": [int(v) for v in isr["nat"]], "cnt": [int(v) for v in isr["cnt"]]}
    isr_table = [{"name": ch_label(r.ch), "nat": n(r.nat), "cnt": n(r.cnt),
                  "share": f"{r.share:.0f}%"} for r in isr.itertuples()]
    nat_by_ch = sorted(leaves[leaves["decl"] == "national"].groupby("ch").size().items(),
                       key=lambda kv: (-kv[1], kv[0]))

    # ---- fan-out: declarable lines per heading -------------------------------
    per_h = leaves.groupby("h4").size()
    fan = []
    for lo, hi, lab in FANOUT_BINS:
        m = per_h >= lo
        if hi is not None:
            m &= per_h <= hi
        fan.append((lab, int(m.sum())))
    med_h = float(per_h.median()) if len(per_h) else 0.0
    hs = sorted(per_h.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_HEADINGS]
    top_heads = [{"code": f"{h[:2]}.{h[2:]}",
                  "desc": short(head_desc.get(h, "") or ch_names.get(h[:2], ""), 60) or "ללא תיאור",
                  "cnt": n(v)} for h, v in hs]
    single_h = int((per_h == 1).sum())

    # ---- measurement units -----------------------------------------------------
    uv = sorted(leaves["unit_name"].value_counts().items(),
                key=lambda kv: (kv[0] == NO_UNIT, -kv[1], kv[0]))
    named = [(k, v) for k, v in uv if k != NO_UNIT]
    no_unit = int((leaves["unit_name"] == NO_UNIT).sum())
    units = named[:TOP_UNITS]
    rest = sum(v for _, v in named[TOP_UNITS:])
    if rest:
        units.append((OTHER_UNITS, rest))
    if no_unit:
        units.append((NO_UNIT, no_unit))
    n_unit_kinds = len(named)

    # units per section (100% stacked)
    top_u = [k for k, _ in named[:TOP_UNITS_SEC]]
    ucats = top_u + ([OTHER_UNITS] if len(named) > TOP_UNITS_SEC else []) + ([NO_UNIT] if no_unit else [])

    def ucat(u):
        if u in top_u or u == NO_UNIT:
            return u
        return OTHER_UNITS
    leaves["ucat"] = leaves["unit_name"].map(ucat)
    us_rows = [r for r in sec_rows if r["leaves"]]
    usec_series, usec_table = [], []
    for k in ucats:
        cnts = [int(((leaves["section"] == r["sec"]) & (leaves["ucat"] == k)).sum()) for r in us_rows]
        usec_series.append({"name": k, "counts": cnts,
                            "data": [round(c / r["leaves"] * 100, 1) for c, r in zip(cnts, us_rows)]})
    for i, r in enumerate(us_rows):
        usec_table.append({"name": r["name"], "cells": [n(s["counts"][i]) for s in usec_series]})
    kg_name = named[0][0] if named else ""
    kg_n = named[0][1] if named else 0
    kg_share = kg_n / n_leaf * 100 if n_leaf else 0.0
    # section where the leading unit is least dominant
    lead_series = usec_series[0] if usec_series else None
    low_lead = None
    if lead_series and us_rows:
        cand = [(lead_series["data"][i], r["sec"], i) for i, r in enumerate(us_rows) if r["leaves"] >= ISR_MIN_LINES]
        if cand:
            low_lead = sorted(cand)[0]

    # ---- catch-all "אחרים" lines by section ---------------------------------
    oth_rows = [r for r in sec_rows if r["leaves"]]
    other_chart = {"names": [r["name"] for r in oth_rows],
                   "share": [round(r["other_share"], 1) for r in oth_rows],
                   "cnt": [r["other"] for r in oth_rows]}
    oth_big = [r for r in oth_rows if r["leaves"] >= ISR_MIN_LINES]
    top_oth = sorted(oth_big, key=lambda r: (-r["other_share"], r["sec"]))[0] if oth_big else None

    # ---- item end dates ---------------------------------------------------------
    ends = t["code"].map(en_end).fillna("")
    ends = ends[ends.str.fullmatch(r"\d{4}-\d{2}-\d{2}")]
    n_end = len(ends)

    # ---- English/Hebrew alignment -------------------------------------------
    he_codes, en_codes = set(t["code"]), set(en["code"])
    only_he = len(he_codes - en_codes)
    only_en = len(en_codes - he_codes)

    # ---------------------------------------------------------------- insights
    def ins_leader():
        if len(lch) < 2 or not n_leaf:
            return None
        (c1, v1), (c2, v2) = lch[0], lch[1]
        share = v1 / n_leaf * 100
        if share < 5 or v1 < v2 * 1.2:
            return None
        return (f"{ch_ref(c1)} הוא הפרק המפורט ביותר בספר: {n(v1)} שורות סיווג שאפשר להצהיר "
                f"עליהן, {pct(share)} מכלל {n(n_leaf)} השורות, לפני {ch_ref(c2)} עם {n(v2)}.")

    def ins_concentration():
        if len(lch) < 10 or top5_share < 25:
            return None
        codes = ", ".join(str(int(c)) for c, _ in lch[:5])
        return (f"חמשת הפרקים המפורטים ביותר (פרקים {codes}) מחזיקים {pct(top5_share)} משורות "
                f"הסיווג שאפשר להצהיר עליהן, מתוך {n(n_chapters)} פרקים בספר.")

    def ins_national():
        if not n_leaf or nat_share < 5 or not nat_by_ch:
            return None
        c1, v1 = nat_by_ch[0]
        return (f"{pct(nat_share)} משורות הסיווג שאפשר להצהיר עליהן ({n(n_nat)} מתוך {n(n_leaf)}) "
                f"הן סעיפים ישראליים: חלוקה לאומית מעבר לשש הספרות של השיטה הבין־לאומית. "
                f"הכי הרבה מהן ב{ch_ref(c1)}: {n(v1)}.")

    def ins_national_hot():
        if isr.empty:
            return None
        r = isr.iloc[0]
        if r["share"] < 50:
            return None
        return (f"ב{ch_ref(r['ch'])} החלוקה הלאומית היא הכלל: {pct(float(r['share']), 0)} משורות "
                f"הפרק ({n(r['nat'])} מתוך {n(r['cnt'])}) הן סעיפים ישראליים "
                f"(בין הפרקים עם {n(ISR_MIN_LINES)} שורות לפחות).")

    def ins_fanout():
        if not hs or hs[0][1] < 10:
            return None
        h, v = hs[0]
        d = short(re.split(r"[(;]", head_desc.get(h, ""))[0].strip(" ,"), 40)
        what = f" ({d})" if d else ""
        return (f"בפרט טיפוסי יש {med_h:g} שורות להצהרה (חציון), ו-{n(single_h)} מתוך {n(len(per_h))} "
                f"הפרטים אינם מחולקים כלל; הפרט המפוצל ביותר הוא {h[:2]}.{h[2:]}{what} "
                f"עם {n(v)} שורות.")

    def ins_units():
        if not named or kg_share < 30 or len(named) < 2:
            return None
        u2, v2 = named[1]
        txt = (f"יחידת הדיווח הנפוצה היא ״{kg_name}״: {n(kg_n)} שורות ({pct(kg_share)}), ואחריה "
               f"״{u2}״ עם {n(v2)}; בסך הכול {n(n_unit_kinds)} יחידות מידה שונות.")
        if low_lead and low_lead[0] < kg_share / 2:
            sec = SECTION_NAMES.get(low_lead[1], "")
            where = f"בחלק {low_lead[1]}" + (f" ({sec})" if sec else "")
            if low_lead[0] == 0:
                txt += f" {where} אף שורה אינה נמדדת ב״{kg_name}״."
            else:
                txt += f" {where} רק {pct(low_lead[0])} מהשורות נמדדות ב״{kg_name}״."
        return txt

    def ins_other():
        if not n_leaf or other_share < 10:
            return None
        txt = (f"{pct(other_share)} משורות הסיווג שאפשר להצהיר עליהן ({n(n_other)}) הן שורות "
               f"\"אחרים\": סל לכל מה שלא סווג בשורה מפורשת לפניהן.")
        if top_oth and top_oth["other_share"] >= other_share * 1.3:
            txt += (f" השיעור הגבוה ביותר בחלק {top_oth['sec']} "
                    f"({SECTION_NAMES.get(top_oth['sec'], '')}): {pct(top_oth['other_share'])}.")
        return txt

    def ins_quality():
        if he_frag <= 0:
            return None
        share = he_frag / len(he_raw) * 100
        txt = (f"בקובץ העברי {n(he_frag)} מתוך {n(len(he_raw))} השורות בטבלה ({pct(share)}) הן "
               f"שברים של שורות שנשברו בייצוא (פסיקים וירידות שורה בתוך התיאור); העמוד נשען על "
               f"{n(total)} שורות הסיווג השלמות, ויחידות המידה נלקחות מהקובץ האנגלי")
        if en_frag > 0:
            txt += f", שבו {n(en_frag)} שורות שבורות בלבד"
        txt += "."
        if only_he or only_en:
            txt += (f" {n(only_he + only_en)} קודי סיווג מופיעים רק באחד משני הקבצים.")
        return txt

    def ins_enddate():
        if not n_end:
            return None
        lo, hi = min(ends), max(ends)

        def dh(s):
            y, m, d = s.split("-")
            return f"{int(d)}.{int(m)}.{y}"
        rng = dh(lo) if lo == hi else f"{dh(lo)} עד {dh(hi)}"
        return (f"רק ל-{n(n_end)} שורות סיווג נקבע מועד סיום תוקף ({rng}); "
                f"שאר {n(total - n_end)} השורות בספר אינן מוגבלות בזמן.")

    rules = [
        ("leader", ins_leader()), ("concentration", ins_concentration()),
        ("national", ins_national()), ("national_hot", ins_national_hot()),
        ("fanout", ins_fanout()), ("units", ins_units()), ("other", ins_other()),
        ("enddate", ins_enddate()), ("quality", ins_quality()),
    ]
    insights = [{"id": i, "text_he": x} for i, x in rules if x]

    # ---------------------------------------------------------------- kpis
    kpis = {
        "lines": {"value": total, "display": n(total), "tone": "brand"},
        "chapters": {"value": n_chapters, "display": n(n_chapters), "tone": "brand"},
        "headings": {"value": n_headings, "display": n(n_headings), "tone": "brand"},
        "leaves": {"value": n_leaf, "display": n(n_leaf), "tone": "brand"},
        "national": {"value": round(nat_share, 1), "display": f"{nat_share:.1f}%", "tone": "info"},
        "other": {"value": round(other_share, 1), "display": f"{other_share:.1f}%", "tone": "brand"},
        "kg": {"value": round(kg_share, 1), "display": f"{kg_share:.1f}%", "tone": "brand"},
        "fragments": {"value": he_frag, "display": n(max(he_frag, 0)),
                      "tone": "warn" if he_frag > 0 else "ok"},
    }

    # ---------------------------------------------------------------- labels
    labels = {
        "lede": (f"ספר המכס ליצוא (ספר סיווג הטובין ביצוא) של רשות המסים: {n(total)} שורות סיווג ב-{n(n_chapters)} "
                 f"פרקים ו-{n(n_headings)} פרטים, לפי מערכת ההרמוניזציה הבין־לאומית ועם חלוקה "
                 f"ישראלית משלימה. {n(n_leaf)} מהשורות הן שורות שאפשר להצהיר עליהן ביצוא, ולכל "
                 f"אחת יחידת מידה לדיווח; {pct(nat_share)} מהן סעיפים ישראליים. הסיווג קובע אילו "
                 f"אישורים, רישיונות ותנאי יצוא חלים על הטובין. בספר עצמו אין שיעורי מס."),
        "national_kpi": "משורות ההצהרה הן סעיפים ישראליים",
        "other_kpi": "משורות ההצהרה הן שורות ״אחרים״",
        "kg_kpi": f"משורות ההצהרה נמדדות ב{kg_name}" if kg_name else "משורות ההצהרה ביחידה הנפוצה",
        "tree_note": (f"מספר שורות ההצהרה בכל פרק, מקובצות לפי {n(len(tree))} חלקי מערכת "
                      f"ההרמוניזציה. שטח כל ריבוע יחסי למספר השורות; לחיצה על חלק מתמקדת בפרקיו."),
        "tree_aria": f"מפת עץ: {n(n_leaf)} שורות ההצהרה לפי חלק ופרק.",
        "tree_caption": "שורות הסיווג לפי חלק: שורות, פרקים ושורות שאפשר להצהיר עליהן.",
        "levels_note": (f"כל רמה מפצלת את הקודמת: {n(n_headings)} פרטים, {n(n_h6)} פרטי משנה בני "
                        f"שש ספרות ו-{n(n_nat_all)} שורות ברמה הישראלית. שורה שאינה מפוצלת הלאה "
                        f"היא שורת הצהרה."),
        "levels_aria": "תרשים עמודות: מספר שורות הסיווג בכל רמה בהיררכיה.",
        "levels_caption": "מספר שורות הסיווג לפי רמה בהיררכיה.",
        "decl_note": ("באיזו רמה נקבעת שורת ההצהרה בכל חלק: בפרט עצמו, בפרט משנה בין־לאומי, או "
                      "בסעיף ישראלי. "
                      + ", ".join(f"{k}: {n(v)}" for k, v in decl_totals) + "."),
        "decl_aria": "תרשים עמודות מוערמות: שיעור שורות ההצהרה בכל חלק לפי רמת הסיווג.",
        "decl_caption": "שורות ההצהרה בכל חלק לפי רמת הסיווג.",
        "chapters_note": (f"{len(top_ch)} הפרקים עם מספר שורות ההצהרה הגבוה ביותר, לפי רמת הסיווג."
                          + (f" בשאר הפרקים יחד {n(others_leaf)} שורות." if others_leaf else "")),
        "chapters_aria": f"תרשים עמודות מוערמות: שורות ההצהרה ב-{len(top_ch)} הפרקים המפורטים ביותר.",
        "chapters_caption": "שורות ההצהרה לפי פרק, מתוכן סעיפים ישראליים, ושיעורן מכלל הספר.",
        "isr_note": (f"הפרקים שבהם שיעור הסעיפים הישראליים מבין שורות ההצהרה הוא הגבוה ביותר. "
                     f"נכללים רק פרקים עם {n(ISR_MIN_LINES)} שורות הצהרה לפחות ועם סעיף ישראלי "
                     f"אחד לפחות ({n(len(ng))} פרקים)."),
        "isr_aria": "תרשים עמודות: שיעור הסעיפים הישראליים בפרקים עם החלוקה הלאומית הגבוהה ביותר.",
        "isr_caption": "פרקים לפי שיעור הסעיפים הישראליים משורות ההצהרה.",
        "fan_note": (f"כמה שורות הצהרה יש בכל אחד מ-{n(len(per_h))} הפרטים (ארבע ספרות). "
                     f"החציון: {med_h:g} שורות לפרט."),
        "fan_aria": "תרשים עמודות: מספר הפרטים לפי מספר שורות ההצהרה בפרט.",
        "fan_caption": "מספר הפרטים לפי מספר שורות ההצהרה.",
        "top_heads_caption": f"{len(top_heads)} הפרטים עם מספר שורות ההצהרה הגבוה ביותר.",
        "units_note": (f"יחידת המידה לדיווח על הכמות בשורות ההצהרה, {n(n_unit_kinds)} יחידות שונות."
                       + (f" ב-{n(no_unit)} שורות קוד היחידה לא זוהה בקבצים." if no_unit else "")),
        "units_aria": "תרשים עמודות: שורות ההצהרה לפי יחידת מידה, בציר לוגריתמי.",
        "units_caption": "מספר שורות ההצהרה לפי יחידת מידה.",
        "usec_note": (f"תמהיל יחידות המידה בשורות ההצהרה של כל חלק: {n(len(top_u))} היחידות "
                      f"הנפוצות"
                      + (" ושאר היחידות יחד." if OTHER_UNITS in ucats else ".")),
        "usec_aria": "תרשים עמודות מוערמות: שיעור כל יחידת מידה בשורות ההצהרה של כל חלק.",
        "usec_caption": "מספר שורות ההצהרה בכל חלק לפי יחידת מידה.",
        "other_note": (f"שיעור שורות ה״אחרים״ (שורת סל לכל מה שלא סווג בשורה מפורשת) מבין שורות "
                       f"ההצהרה בכל חלק. בכל הספר: {pct(other_share)}."),
        "other_aria": "תרשים עמודות: שיעור שורות האחרים משורות ההצהרה בכל חלק.",
        "other_caption": "שורות האחרים ושיעורן משורות ההצהרה, לפי חלק.",
        "fragments_kpi": "שורות שבורות בקובץ העברי",
    }

    charts = {
        "tree": tree,
        "levels": {"names": [k for k, _ in lv_rows], "values": [v for _, v in lv_rows]},
        "decl": sec_decl,
        "chapters": {"names": [ch_label(c) for c in top_ch], "series": chap_series},
        "isr": isr_chart,
        "fan": {"names": [b for b, _ in fan], "values": [v for _, v in fan]},
        "units": {"names": [k for k, _ in units], "values": [v for _, v in units]},
        "usec": {"names": [r["name"] for r in us_rows],
                 "series": [{"name": s["name"], "data": s["data"], "counts": s["counts"]}
                            for s in usec_series]},
        "other": other_chart,
    }
    tables = {
        "sections": [{"name": r["name"], "lines": n(r["lines"]), "chapters": n(r["chapters"]),
                      "leaves": n(r["leaves"])} for r in sec_rows],
        "levels": [{"name": k, "count": n(v)} for k, v in lv_rows],
        "decl_cols": [DECL_LABELS[k] for k in decl_present],
        "decl": [{"name": r["name"], "cells": [n(r["decl"][k]) for k in decl_present]}
                 for r in sec_rows if r["leaves"]],
        "chapters": chap_table,
        "isr": isr_table,
        "fan": [{"name": b, "count": n(v)} for b, v in fan],
        "top_heads": top_heads,
        "units": [{"name": k, "count": n(v)} for k, v in units],
        "usec_cols": ucats,
        "usec": usec_table,
        "other": [{"name": r["name"], "cnt": n(r["other"]), "share": f"{r['other_share']:.1f}%"}
                  for r in oth_rows],
    }

    return {
        "agent_data": {
            "summary_he": (f"ספר המכס ליצוא: איתור פרט מכס וסיווג טובין לפי קוד או תיאור. "
                           f"{n(total)} שורות סיווג ב-{n(n_chapters)} פרקים, מהן {n(n_leaf)} "
                           f"שורות הצהרה עם יחידת מידה."),
            "dataset_kind": "registry",
            "suggested_tags": ["מכס", "יצוא", "סיווג טובין", "ספר המכס", "תעריף המכס", "יחידות מידה"],
            "related_ids": ["3de0e7f0-03e1-4665-b078-da6e87543ed7",
                            "15fd7d7f-da3a-461e-94dd-1dfbbec52a22",
                            "965b52b6-7267-45d9-bccd-020416fbcfb5"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"isr": bool(len(isr)), "fragments": he_frag > 0},
    }
