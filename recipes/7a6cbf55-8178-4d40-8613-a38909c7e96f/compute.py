"""מאגר חומרי הדברה — the Ministry of Agriculture's registry of approved
plant-protection products.

Two resources carry the same table (Hebrew vs English column headers,
cell-identical); this recipe reads the Hebrew-header one. A row is one
fan-out of product (licence) × activity type × active ingredient ×
environmental-toxicity flag × crop × pest × dose, so raw row counts are
meaningless. Every count here is DISTINCT products (licence numbers) or
distinct approved uses (licence × crop × pest).

"Now" is never the wall clock: the reference year is the latest year in
which the committee met on several distinct dates; approvals dated later
than that year (data-entry slips) are kept out of the timeline and the
page says how many.
"""
import re

import pandas as pd

LIC = "מספר רשיון"
TYPE = "סוג תכשיר"
NAME = "שם תכשיר"
ACT = "סוג פעילות"
UN = "מספר או'ם"
AI = "חומר פעיל"
MOA = "קבוצת עמידות"
CODE = "טרגט קוד"
FORM = "פורמולציה"
HOLDER = "בעל רשיון"
MAKER = "יצרן פורמולציה"
ENVTOX = "רעילות"
TOXCLS = "דרגת רעילות"
CROPGRP = "קבוצת גידולים"
CROP = "גידול"
DATE = "תאריך אישור וועדה"
PESTGRP = "קבוצת נגעים"
PEST = "נגע"
PHI = "תקופת המתנה"
REENTRY = "כניסה מחדש"

UNSPEC = "לא צוין"
OTHER = "אחר"
MIN_REF_DATES = 3          # distinct committee dates a year needs to count as "current"
TREND_WINDOW = 5           # years per side in the approvals-trend insight
TREND_THRESH = 0.15
TOP_ACT = 10
TOP_AI = 15
TOP_CROPS = 15
TOP_PESTS = 15
TOP_HOLDERS = 12
TOP_MAKERS = 12
TOP_FORMS = 10
TOP_MOA = 12
TOP_PRODUCTS = 10
HEAT_ACTS = 6
HEAT_GROUPS = 12
MIN_PHI_USES = 100         # numeric PHI uses a crop group needs for the boxplot
FEW_PRODUCTS = 3           # "minor crop": approved for at most this many products
NO_MOA = {"", "ללא", "0"}

BEE_ORDER = ["רעיל מאוד לדבורים", "רעילות בינונית לדבורים", "רעילות קלה לדבורים",
             "רעיל לדבורים, ללא דרגה", "לא רעיל לדבורים", "ללא סימון לדבורים"]
ENV_KEYS = [("דבורים", "דבורים"), ("ימיים", "יצורים ימיים"), ("דגים", "דגים"),
            ("צפורים", "ציפורים"), ("אצות", "אצות")]
PHI_BUCKETS = [(0, 0), (1, 3), (4, 7), (8, 14), (15, 21), (22, 30), (31, 60), (61, None)]
REENTRY_ORDER = ["מיד / ללא מגבלה", "עם התייבשות התרסיס", "עד 4 שעות", "5–12 שעות",
                 "13–24 שעות", "מעל 24 שעות", OTHER, UNSPEC]
UN_NAMES = {"3082": "חומר מסוכן לסביבה, נוזלי", "3077": "חומר מסוכן לסביבה, מוצק"}
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
PHI_RE = re.compile(r"^(?:ימים\s*)?(\d+)\s*(?:ימים|יום)?\s*(?:לפני.*)?$")
LEGAL_RE = re.compile(r"\s*(?:בע\"מ|בע״מ|בעיימ)\s*")
HOURS_RE = re.compile(r"(\d+)\s*שעות|שעות\s*(\d+)")
DAYS_RE = re.compile(r"(\d+)\s*(?:ימים|יום)")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def ranked(counts):
    """Descending by value, ties by label — a total, shuffle-proof order."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def short_co(name):
    """Chart label without the legal suffix (tables keep the full name)."""
    return LEGAL_RE.sub(" ", name).strip() or name


def top_other(counts, k):
    counts = ranked(counts)
    top = counts.head(k)
    rest = int(counts.iloc[k:].sum())
    names = list(top.index) + ([OTHER] if rest else [])
    vals = [int(v) for v in top.values] + ([rest] if rest else [])
    return names, vals


def bee_class(label):
    if label == "רעיל מאד לדבורים":
        return 0
    if label == "רעילות בינונית לדבורים":
        return 1
    if label == "רעילות קלה לדבורים":
        return 2
    if "לא רעיל" in label:
        return 4
    if "דבורים" in label:
        return 3
    return 5


def env_tags(label):
    if not label or "לא רעיל" in label:
        return []
    tags = [t for key, t in ENV_KEYS if key in label]
    return tags or [OTHER]


def phi_days(s):
    m = PHI_RE.match(s.strip())
    return int(m.group(1)) if m else None


def phi_bucket(v):
    for lo, hi in PHI_BUCKETS:
        if v >= lo and (hi is None or v <= hi):
            if lo == hi:
                return "ללא המתנה"
            return f"{lo}+ ימים" if hi is None else f"{lo}–{hi} ימים"
    return OTHER


def reentry_class(s):
    s = s.strip()
    if not s:
        return UNSPEC
    if "התייבש" in s or "היתייבש" in s:
        return "עם התייבשות התרסיס"
    if "אין מגבלה" in s or s.startswith("מיד") or s.startswith("בסיום"):
        return "מיד / ללא מגבלה"
    m = HOURS_RE.search(s)
    if m:
        h = int(m.group(1) or m.group(2))
        if h <= 4:
            return "עד 4 שעות"
        if h <= 12:
            return "5–12 שעות"
        if h <= 24:
            return "13–24 שעות"
        return "מעל 24 שעות"
    m = DAYS_RE.search(s)
    if m:
        return "13–24 שעות" if int(m.group(1)) <= 1 else "מעל 24 שעות"
    return OTHER


def _prepare(df):
    cols = [LIC, TYPE, NAME, ACT, UN, AI, MOA, CODE, FORM, HOLDER, MAKER, ENVTOX, TOXCLS,
            CROPGRP, CROP, DATE, PESTGRP, PEST, PHI, REENTRY]
    out = pd.DataFrame({c: df[c].astype(str).str.strip() for c in cols})
    out = out[out[LIC] != ""]
    for c in [TYPE, ACT, TOXCLS, CROPGRP, CROP, PEST, PESTGRP, HOLDER, FORM]:
        out[c] = out[c].replace("", UNSPEC)
    out["dt"] = pd.to_datetime(out[DATE], errors="coerce", format="%d/%m/%Y")
    return out


def products_by(df, col):
    return df[df[col] != ""].groupby(col)[LIC].nunique()


# ── insight rules ─────────────────────────────────────────────────────────

def insight_activity(act_counts, total):
    c = ranked(act_counts)
    if len(c) < 2:
        return None
    (a1, v1), (a2, v2) = (c.index[0], c.iloc[0]), (c.index[1], c.iloc[1])
    if v1 == v2:
        return (f"{a1} ו{a2} הם סוגי הפעילות הנפוצים ביותר, עם {n(v1)} תכשירים כל אחד "
                f"(תכשיר יכול להשתייך ליותר מסוג פעילות אחד).")
    return (f"סוג הפעילות הנפוץ ביותר הוא {a1}: {n(v1)} תכשירים ({pct(v1 / total * 100)} "
            f"מהתכשירים), ואחריו {a2} עם {n(v2)}.")


def insight_bees(bee, prod_act, total):
    worst = bee == 0
    overall = worst.mean()
    ins = prod_act[prod_act[ACT] == "קוטלי חרקים ואקריות"][LIC].unique()
    if len(ins) < 20 or overall == 0:
        return None
    ins_share = worst.reindex(ins).fillna(False).mean()
    if ins_share < overall * 1.5:
        return None
    return (f"{n(worst.sum())} תכשירים ({pct(overall * 100)}) מסומנים כרעילים מאוד לדבורים; "
            f"בקרב קוטלי החרקים והאקריות השיעור עולה ל-{pct(ins_share * 100)} — "
            f"שיקול חשוב בריסוס בזמן פריחה.")


def insight_organic(prod, total):
    org = prod[prod[TYPE].str.contains("אורגני")]
    if org.empty:
        return None
    nop = int(prod[TYPE].str.contains("NOP").sum())
    s = f"{n(len(org))} תכשירים ({pct(len(org) / total * 100)}) רשומים כאורגניים"
    if nop:
        s += f", מתוכם {n(nop)} בתקן האמריקאי NOP"
    return s + "."


def insight_holders(holders, total):
    c = ranked(holders)
    if len(c) < 5:
        return None
    top5 = c.head(5).sum() / total
    if top5 < 0.3:
        return None
    return (f"בעל הרישיון הגדול הוא {c.index[0]} עם {n(c.iloc[0])} תכשירים; חמשת בעלי "
            f"הרישיון הגדולים מחזיקים יחד {pct(top5 * 100)} מהתכשירים, מתוך {n(len(c))} "
            f"בעלי רישיון במאגר.")


def insight_ai(ai_counts, ai_per_product):
    c = ranked(ai_counts)
    if c.empty:
        return None
    multi = (ai_per_product > 1).mean()
    s = (f"החומר הפעיל המשותף למספר הרב ביותר של תכשירים הוא {c.index[0]} "
         f"({n(c.iloc[0])} תכשירים)")
    if multi >= 0.05:
        s += f"; {pct(multi * 100)} מהתכשירים משלבים שני חומרים פעילים או יותר"
    return s + "."


def insight_crops(crop_counts):
    c = ranked(crop_counts)
    if len(c) < 10:
        return None
    few = int((c <= FEW_PRODUCTS).sum())
    s = f"{c.index[0]} הוא הגידול עם מגוון התכשירים הרחב ביותר — {n(c.iloc[0])} תכשירים מאושרים"
    if few >= 10:
        s += (f"; מנגד, ל-{n(few)} מתוך {n(len(c))} הגידולים במאגר מאושרים {FEW_PRODUCTS} "
              f"תכשירים לכל היותר")
    return s + "."


def insight_trend(per_year, last_full):
    w = TREND_WINDOW
    recent = [per_year.get(y, 0) for y in range(last_full - w + 1, last_full + 1)]
    before = [per_year.get(y, 0) for y in range(last_full - 2 * w + 1, last_full - w + 1)]
    if per_year.index.min() > last_full - 2 * w + 1:
        return None
    r, b = sum(recent) / w, sum(before) / w
    if b == 0:
        return None
    chg = r / b - 1
    span_r = f"{last_full - w + 1}–{last_full}"
    span_b = f"{last_full - 2 * w + 1}–{last_full - w}"
    if abs(chg) < TREND_THRESH:
        return (f"קצב אישור השימושים החדשים יציב: כ-{n(round(r))} בשנה ב-{span_r}, "
                f"בדומה ל-{n(round(b))} ב-{span_b} (לפי תאריך האישור של שימושים שבתוקף).")
    word = "ירידה" if chg < 0 else "עלייה"
    return (f"{word} בקצב אישור שימושים חדשים: בממוצע {n(round(r))} שימושים בשנה ב-{span_r}, "
            f"לעומת {n(round(b))} ב-{span_b} ({pct(abs(chg) * 100, 0)} "
            f"{'פחות' if chg < 0 else 'יותר'}; לפי תאריך האישור של שימושים שבתוקף).")


def insight_phi(stats):
    if len(stats) < 3:
        return None
    meds = sorted(s["med"] for s in stats)
    # A clear longest and shortest group only — ties make "longest" meaningless.
    if meds[-1] == meds[-2] or meds[0] == meds[1] or meds[-1] - meds[0] < 3:
        return None
    hi = max(stats, key=lambda s: s["med"])
    lo = min(stats, key=lambda s: s["med"])
    return (f"תקופת ההמתנה החציונית מהריסוס האחרון ועד הקטיף ארוכה ביותר ב{hi['group']} "
            f"({n(hi['med'])} ימים) וקצרה ביותר ב{lo['group']} ({n(lo['med'])} ימים).")


def insight_un(prod, total):
    has = prod[prod[UN] != ""]
    if len(has) / total < 0.2:
        return None
    c = ranked(has[UN].value_counts())
    code = c.index[0]
    desc = f" ({UN_NAMES[code]})" if code in UN_NAMES else ""
    return (f"{pct(len(has) / total * 100)} מהתכשירים מסווגים כחומר מסוכן בהובלה ונושאים "
            f"מספר או״ם; הנפוץ הוא {code}{desc}, ב-{n(c.iloc[0])} תכשירים.")


def insight_tox(prod, total):
    severe = prod[TOXCLS].isin(["רעיל", "רעיל ביותר", "משחרר גזים רעילים"])
    common = ranked(prod[TOXCLS].value_counts())
    if common.empty:
        return None
    s = (f"דרגת הרעילות הנפוצה היא \"{common.index[0]}\" ({pct(common.iloc[0] / total * 100)} "
         f"מהתכשירים)")
    if severe.sum():
        s += (f"; {n(severe.sum())} תכשירים ({pct(severe.mean() * 100)}) מסווגים "
              f"ברעיל, רעיל ביותר או משחרר גזים רעילים")
    return s + "."


# ── compute ───────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    prod = (df.sort_values([LIC, NAME, HOLDER, TYPE], kind="stable")
              .drop_duplicates(LIC).set_index(LIC, drop=False))
    total = len(prod)
    uses = (df.dropna(subset=["dt"]).groupby([LIC, CROP, PEST])["dt"].min().reset_index())
    uses_all = df.drop_duplicates([LIC, CROP, PEST])
    n_uses = len(uses_all)

    # Reference year: latest year with several distinct committee dates.
    dates = df["dt"].dropna().drop_duplicates()
    per_year_dates = dates.groupby(dates.dt.year).size()
    good_years = per_year_dates[per_year_dates >= MIN_REF_DATES]
    ref_year = int(good_years.index.max()) if len(good_years) else int(dates.dt.year.max())
    in_ref = uses[uses["dt"].dt.year <= ref_year]
    future = uses[uses["dt"].dt.year > ref_year]
    ref = in_ref["dt"].max()
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year

    # Timeline: new uses and new products by first approval year.
    uy = in_ref.groupby(in_ref["dt"].dt.year).size()
    first = in_ref.groupby(LIC)["dt"].min()
    py = first.groupby(first.dt.year).size()
    y0 = int(min(uy.index.min(), py.index.min()))
    years = list(range(y0, ref_year + 1))
    timeline = {"x": [str(y) for y in years],
                "uses": [int(uy.get(y, 0)) for y in years],
                "products": [int(py.get(y, 0)) for y in years],
                "partial": partial}

    # Activity × product type (products may carry several activity types).
    prod_act = df[[LIC, ACT]].drop_duplicates()
    prod_act = prod_act.merge(prod[[TYPE]].reset_index(), on=LIC)
    act_counts = prod_act.groupby(ACT)[LIC].nunique()
    act_names, act_vals = top_other(act_counts, TOP_ACT)
    act_key = prod_act[ACT].where(prod_act[ACT].isin(act_names), OTHER)
    types = list(ranked(prod[TYPE].value_counts()).index)
    act_ct = prod_act.assign(k=act_key).groupby(["k", TYPE])[LIC].nunique().unstack(fill_value=0)
    act_ct = act_ct.reindex(index=act_names, columns=types, fill_value=0)
    activity = {"names": act_names, "totals": act_vals,
                "series": [{"name": t, "data": [int(v) for v in act_ct[t]]} for t in types]}

    # Toxicity class × product type.
    tox_order = list(ranked(prod[TOXCLS].value_counts()).index)
    tox_ct = prod.groupby([TOXCLS, TYPE]).size().unstack(fill_value=0)
    tox_ct = tox_ct.reindex(index=tox_order, columns=types, fill_value=0)
    tox = {"names": tox_order, "totals": [int(v) for v in tox_ct.sum(axis=1)],
           "series": [{"name": t, "data": [int(v) for v in tox_ct[t]]} for t in types]}

    # Bees: worst rating per product, split by the main activity types.
    bee_rows = df[[LIC, ENVTOX]].drop_duplicates()
    bee_rows = bee_rows.assign(cls=bee_rows[ENVTOX].map(bee_class))
    bee = bee_rows.groupby(LIC)["cls"].min().reindex(prod.index).fillna(5).astype(int)
    bee_acts = list(ranked(act_counts).head(4).index)
    bee_tab = []
    for a in bee_acts:
        ids = prod_act.loc[prod_act[ACT] == a, LIC].unique()
        vc = bee.reindex(ids).value_counts()
        bee_tab.append([int(vc.get(i, 0)) for i in range(len(BEE_ORDER))])
    vc_all = bee.value_counts()
    bee_tab.append([int(vc_all.get(i, 0)) for i in range(len(BEE_ORDER))])
    bee_rows_names = bee_acts + ["כל התכשירים"]
    bees = {"rows": bee_rows_names, "cats": BEE_ORDER,
            "series": [{"name": c, "data": [round(r[i] / max(sum(r), 1) * 100, 1) for r in bee_tab]}
                       for i, c in enumerate(BEE_ORDER)],
            "counts": bee_tab}

    # Environmental hazard flags (products).
    env_pairs = [(lic, t) for lic, lab in zip(bee_rows[LIC], bee_rows[ENVTOX]) for t in env_tags(lab)]
    env = pd.DataFrame(env_pairs, columns=[LIC, "t"]).drop_duplicates() if env_pairs \
        else pd.DataFrame(columns=[LIC, "t"])
    env_c = env.groupby("t")[LIC].nunique()
    env_names = [t for _, t in ENV_KEYS if t in env_c.index] + ([OTHER] if OTHER in env_c.index else [])
    env_chart = {"names": env_names, "values": [int(env_c[t]) for t in env_names]}

    # Active ingredients.
    ai_counts = products_by(df, AI)
    ai_names, ai_vals = top_other(ai_counts, TOP_AI)
    ai_names, ai_vals = ai_names[:TOP_AI], ai_vals[:TOP_AI]
    ai_per_product = df[df[AI] != ""].groupby(LIC)[AI].nunique()

    # Mode of action (resistance groups) within the three main activity classes.
    main_acts = [a for a in ranked(act_counts).index
                 if a in {"קוטלי חרקים ואקריות", "קוטלי פטריות וחיידקים", "קוטלי עשבים ומשלכים"}]
    moa_df = df[df[ACT].isin(main_acts) & ~df[CODE].isin(NO_MOA)][[LIC, ACT, CODE, MOA]].drop_duplicates()
    moa_c = moa_df.groupby([ACT, CODE])[LIC].nunique().reset_index(name="k")
    moa_desc = (moa_df.groupby([ACT, CODE, MOA])[LIC].nunique().reset_index(name="k")
                      .sort_values([ACT, CODE, "k", MOA], ascending=[True, True, False, True])
                      .drop_duplicates([ACT, CODE]).set_index([ACT, CODE])[MOA])
    moa_c = moa_c.sort_values(["k", ACT, CODE], ascending=[False, True, True]).head(TOP_MOA)
    short = {"קוטלי חרקים ואקריות": "חרקים", "קוטלי פטריות וחיידקים": "פטריות",
             "קוטלי עשבים ומשלכים": "עשבים"}
    moa_rows = [{"act": r[ACT], "short": short.get(r[ACT], r[ACT]), "code": r[CODE],
                 "desc": moa_desc.get((r[ACT], r[CODE]), ""), "count": int(r["k"])}
                for _, r in moa_c.iterrows()]
    moa_chart = {"names": [f"{r['short']} · {r['code']}" for r in moa_rows],
                 "values": [r["count"] for r in moa_rows],
                 "desc": [r["desc"] for r in moa_rows]}
    no_moa_share = 1 - (df[df[ACT].isin(main_acts) & ~df[CODE].isin(NO_MOA)][LIC].nunique()
                        / max(df[df[ACT].isin(main_acts)][LIC].nunique(), 1))

    def moa_top(act):
        allr = (moa_df[moa_df[ACT] == act].groupby(CODE)[LIC].nunique())
        allr = ranked(allr)
        return (allr.index[0], int(allr.iloc[0])) if len(allr) else None

    # Crops, crop groups, pests.
    crop_counts = df.groupby(CROP)[LIC].nunique()
    crop_names, crop_vals = top_other(crop_counts, TOP_CROPS)
    crop_names, crop_vals = crop_names[:TOP_CROPS], crop_vals[:TOP_CROPS]
    crop_uses = uses_all.groupby(CROP).size()

    grp_counts = ranked(df.groupby(CROPGRP)[LIC].nunique())
    heat_groups = list(grp_counts.head(HEAT_GROUPS).index)
    heat_acts = list(ranked(act_counts).head(HEAT_ACTS).index)
    hd = df[[LIC, CROPGRP, ACT]].drop_duplicates()
    hd = hd.assign(g=hd[CROPGRP].where(hd[CROPGRP].isin(heat_groups), OTHER),
                   a=hd[ACT].where(hd[ACT].isin(heat_acts), OTHER))
    hx = heat_acts + ([OTHER] if (hd["a"] == OTHER).any() else [])
    hy = heat_groups + ([OTHER] if (hd["g"] == OTHER).any() else [])
    hct = hd.groupby(["g", "a"])[LIC].nunique()
    cells, heat_tab = [], []
    for yi, g in enumerate(hy):
        row = []
        for xi, a in enumerate(hx):
            v = int(hct.get((g, a), 0))
            cells.append([xi, yi, v])
            row.append(n(v))
        heat_tab.append({"group": g, "cells": row})
    heat = {"x": hx, "y": hy, "cells": cells, "max": max([c[2] for c in cells] or [1])}

    pest_counts = df.groupby(PEST)[LIC].nunique()
    pest_names, pest_vals = top_other(pest_counts, TOP_PESTS)
    pest_names, pest_vals = pest_names[:TOP_PESTS], pest_vals[:TOP_PESTS]
    pest_grp = (df.groupby([PEST, PESTGRP])[LIC].nunique().reset_index(name="k")
                  .sort_values([PEST, "k", PESTGRP], ascending=[True, False, True])
                  .drop_duplicates(PEST).set_index(PEST)[PESTGRP])
    pestgrp_counts = ranked(df.groupby(PESTGRP)[LIC].nunique())

    # Pre-harvest interval (per use; the longest stated value when a use has several).
    ph = df[[LIC, CROP, PEST, CROPGRP, PHI]].drop_duplicates()
    ph = ph.assign(d=ph[PHI].map(phi_days))
    stated = ph.groupby([LIC, CROP, PEST])[PHI].apply(lambda s: (s != "").any())
    phn = ph.dropna(subset=["d"]).groupby([LIC, CROP, PEST, CROPGRP])["d"].max().reset_index()
    phi_hist_c = phn["d"].map(phi_bucket).value_counts()
    phi_labels = [phi_bucket(lo) for lo, _ in PHI_BUCKETS]
    n_phi_num = int(len(phn.drop_duplicates([LIC, CROP, PEST])))
    n_phi_none = int((~stated).sum())
    n_phi_text = max(int(len(stated)) - n_phi_num - n_phi_none, 0)
    phi_hist = {"names": phi_labels, "values": [int(phi_hist_c.get(b, 0)) for b in phi_labels]}
    stats = []
    for g, sub in phn.groupby(CROPGRP):
        if len(sub) < MIN_PHI_USES:
            continue
        q = sub["d"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).tolist()
        stats.append({"group": g, "q": [round(float(v), 1) for v in q], "med": float(q[2]),
                      "count": int(len(sub))})
    stats.sort(key=lambda s: (-s["med"], -s["count"], s["group"]))
    phi_box = {"names": [s["group"] for s in stats], "box": [s["q"] for s in stats]}

    # Re-entry interval (one value per product).
    re_c = prod[REENTRY].map(reentry_class).value_counts()
    re_names = [c for c in REENTRY_ORDER if re_c.get(c, 0)]
    reentry = {"names": re_names, "values": [int(re_c[c]) for c in re_names]}

    # Registrants, formulation makers, formulation types.
    holder_counts = prod.groupby(HOLDER).size()
    h_names, h_vals = top_other(holder_counts, TOP_HOLDERS)
    maker_counts = products_by(df, MAKER)
    m_names, m_vals = top_other(maker_counts, TOP_MAKERS)
    m_names, m_vals = m_names[:TOP_MAKERS], m_vals[:TOP_MAKERS]
    form_counts = prod.groupby(FORM).size()
    f_names, f_vals = top_other(form_counts, TOP_FORMS)

    # Broadest labels: products with the most approved uses.
    pu = uses_all.groupby(LIC).size().rename("u").reset_index()
    pu = pu.merge(prod[[NAME, HOLDER]].reset_index(), on=LIC)
    pu = pu.sort_values(["u", NAME, LIC], ascending=[False, True, True]).head(TOP_PRODUCTS)
    acts_of = prod_act.sort_values([LIC, ACT]).groupby(LIC)[ACT].apply(lambda s: "، ".join(s))
    crops_of = uses_all.groupby(LIC)[CROP].nunique()
    top_products = [{"name": r[NAME], "holder": r[HOLDER], "act": acts_of.get(r[LIC], ""),
                     "crops": n(crops_of.get(r[LIC], 0)), "uses": n(r["u"])}
                    for _, r in pu.iterrows()]

    # ── insights ──
    rules = [
        ("activity", insight_activity(act_counts, total)),
        ("bees", insight_bees(bee, prod_act, total)),
        ("organic", insight_organic(prod, total)),
        ("holders", insight_holders(holder_counts, total)),
        ("ai", insight_ai(ai_counts, ai_per_product)),
        ("crops", insight_crops(crop_counts)),
        ("trend", insight_trend(uy, last_full)),
        ("phi", insight_phi(stats)),
        ("tox", insight_tox(prod, total)),
        ("un", insight_un(prod, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    highly = int((bee == 0).sum())
    hshare = highly / total * 100
    bee_tone = "danger" if hshare >= 15 else ("warn" if hshare >= 5 else "ok")
    organic = int(prod[TYPE].str.contains("אורגני").sum())
    kpis = {
        "products": {"value": total, "display": n(total), "tone": "brand"},
        "uses": {"value": n_uses, "display": n(n_uses), "tone": "brand"},
        "ai": {"value": int(ai_counts.size), "display": n(ai_counts.size), "tone": "brand"},
        "holders": {"value": int(holder_counts.size), "display": n(holder_counts.size), "tone": "brand"},
        "organic": {"value": organic, "display": f"{organic / total * 100:.1f}%", "tone": "info"},
        "bees": {"value": highly, "display": f"{hshare:.1f}%", "tone": bee_tone},
    }

    top_act = ranked(act_counts)
    ins_moa = moa_top("קוטלי חרקים ואקריות")
    partial_note = (f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else "")
    future_note = (f" {n(len(future))} שימושים שתאריך אישורם רשום אחרי {ref_year} "
                   f"(ככל הנראה שגיאת הקלדה) אינם מוצגים." if len(future) else "")
    phi_hi = stats[0] if stats else None
    labels = {
        "lede": (f"מרשם תכשירי ההדברה המורשים לשימוש בחקלאות בישראל: {n(total)} תכשירים "
                 f"של {n(holder_counts.size)} בעלי רישיון, המבוססים על {n(ai_counts.size)} "
                 f"חומרים פעילים ומאושרים ל-{n(n_uses)} שימושים — צירופים של גידול ונגע — "
                 f"ב-{n(crop_counts.size)} גידולים. לכל שימוש רשומים מינון, תקופת המתנה "
                 f"עד הקטיף ומועד כניסה מחדש לשטח."),
        "uses_kpi": "שימושים מאושרים (תכשיר × גידול × נגע)",
        "bees_kpi": f"מהתכשירים רעילים מאוד לדבורים ({n(highly)} תכשירים)",
        "organic_kpi": f"מהתכשירים אורגניים ({n(organic)} תכשירים)",
        "activity_note": (f"מספר תכשירים לפי סוג פעילות, בחלוקה לסוג התכשיר. תכשיר יכול "
                          f"להשתייך ליותר מסוג פעילות אחד. הנפוץ: {top_act.index[0]} "
                          f"({n(top_act.iloc[0])} תכשירים)."),
        "activity_aria": (f"תרשים עמודות מוערמות: מספר תכשירים לפי סוג פעילות ({TOP_ACT} "
                          f"הנפוצים) וסוג תכשיר. המוביל: {top_act.index[0]}."),
        "activity_caption": "מספר תכשירים לפי סוג פעילות וסוג תכשיר.",
        "timeline_note": (f"שימושים מאושרים (תכשיר × גידול × נגע) לפי שנת אישור הוועדה, ומספר "
                          f"התכשירים לפי השנה של השימוש המוקדם ביותר שלהם שעדיין בתוקף. "
                          f"שימושים ותכשירים שבוטלו אינם במאגר, ולכן שנים מוקדמות מוצגות "
                          f"חסר.{partial_note}{future_note}"),
        "timeline_aria": (f"גרף עמודות וקו: שימושים חדשים ותכשירים חדשים לפי שנת אישור, "
                          f"{y0} עד {ref_year}."),
        "tox_note": "דרגת הרעילות הרשומה של כל תכשיר, בחלוקה לסוג התכשיר.",
        "tox_aria": (f"תרשים עמודות מוערמות: מספר תכשירים לפי דרגת רעילות וסוג תכשיר. "
                     f"הנפוצה: {tox_order[0]}."),
        "tox_caption": "מספר תכשירים לפי דרגת רעילות וסוג תכשיר.",
        "bees_note": ("הסימון החמור ביותר לדבורים של כל תכשיר, כאחוז מהתכשירים בכל סוג "
                      "פעילות. \"ללא סימון לדבורים\" — תכשירים שסימוני הרעילות שלהם נוגעים "
                      "לבעלי חיים אחרים בלבד, או ללא סימון."),
        "bees_aria": (f"תרשים עמודות מוערמות באחוזים: סימון הרעילות לדבורים לפי סוג פעילות. "
                      f"{pct(hshare)} מכלל התכשירים רעילים מאוד לדבורים."),
        "bees_caption": "מספר תכשירים לפי סוג פעילות וסימון רעילות לדבורים.",
        "env_note": "מספר התכשירים המסומנים כרעילים לכל קבוצת בעלי חיים (תכשיר יכול לשאת כמה סימונים).",
        "env_aria": (f"תרשים עמודות: מספר תכשירים לפי סימון רעילות סביבתי. "
                     f"{env_names[0] if env_names else ''}."),
        "env_caption": "מספר תכשירים לפי סימון רעילות לבעלי חיים.",
        "ai_note": (f"{TOP_AI} החומרים הפעילים המשותפים למספר הרב ביותר של תכשירים; מתוך "
                    f"{n(ai_counts.size)} חומרים פעילים במאגר."),
        "ai_aria": f"תרשים עמודות: {TOP_AI} החומרים הפעילים הנפוצים לפי מספר תכשירים.",
        "ai_caption": "מספר תכשירים לפי חומר פעיל.",
        "moa_note": (f"קבוצות מנגנון הפעולה (קוד יעד לניהול עמידות) הנפוצות בקוטלי חרקים, "
                     f"פטריות ועשבים, לפי מספר תכשירים. {pct(no_moa_share * 100)} מהתכשירים "
                     f"בשלושת הסוגים רשומים ללא קוד ואינם נכללים."
                     + (f" בקוטלי החרקים מוביל קוד {ins_moa[0]} ({n(ins_moa[1])} תכשירים)."
                        if ins_moa else "")),
        "moa_aria": f"תרשים עמודות: {TOP_MOA} קבוצות מנגנון הפעולה הנפוצות לפי מספר תכשירים.",
        "moa_caption": "מספר תכשירים לפי סוג פעילות וקוד מנגנון פעולה.",
        "heat_note": "מספר התכשירים המאושרים לכל צירוף של קבוצת גידולים וסוג פעילות.",
        "heat_aria": (f"מפת חום: מספר תכשירים לפי קבוצת גידולים ({len(hy)}) וסוג פעילות "
                      f"({len(hx)})."),
        "heat_caption": "מספר תכשירים לפי קבוצת גידולים וסוג פעילות.",
        "crops_note": (f"{TOP_CROPS} הגידולים עם מספר התכשירים המאושרים הגדול ביותר, מתוך "
                       f"{n(crop_counts.size)} גידולים."),
        "crops_aria": (f"תרשים עמודות: {TOP_CROPS} הגידולים לפי מספר תכשירים מאושרים. "
                       f"המוביל: {crop_names[0] if crop_names else ''}."),
        "crops_caption": "מספר תכשירים ושימושים לפי גידול.",
        "pests_note": (f"{TOP_PESTS} הנגעים שלהדברתם מאושרים הכי הרבה תכשירים, מתוך "
                       f"{n(pest_counts.size)} נגעים."),
        "pests_aria": (f"תרשים עמודות: {TOP_PESTS} הנגעים לפי מספר תכשירים מאושרים. "
                       f"המוביל: {pest_names[0] if pest_names else ''}."),
        "pests_caption": "מספר תכשירים לפי נגע וקבוצת נגעים.",
        "phi_note": (f"מספר הימים שיש להמתין מהיישום האחרון ועד הקטיף, לכל שימוש מאושר "
                     f"(הערך הארוך כשרשומים כמה). {n(n_phi_num)} שימושים עם ערך מספרי; "
                     f"{n(n_phi_none)} ללא ערך ו-{n(n_phi_text)} עם הנחיה מילולית אינם נכללים."),
        "phi_aria": "תרשים עמודות: שימושים מאושרים לפי תקופת המתנה עד הקטיף, בימים.",
        "phi_caption": "מספר שימושים לפי תקופת המתנה.",
        "box_note": (f"פיזור תקופת ההמתנה בכל קבוצת גידולים: הקופסה בין הרבעון התחתון לעליון, "
                     f"הקו — החציון, והשפמים — העשירון התחתון והעליון. קבוצות עם "
                     f"{MIN_PHI_USES} שימושים לפחות."
                     + (f" הארוכה ביותר: {phi_hi['group']} (חציון {n(phi_hi['med'])} ימים)."
                        if phi_hi else "")),
        "box_aria": "תרשים קופסה: תקופת ההמתנה עד הקטיף לפי קבוצת גידולים, בימים.",
        "box_caption": "תקופת המתנה בימים לפי קבוצת גידולים: עשירונים, רבעונים וחציון.",
        "reentry_note": ("הזמן שיש להמתין אחרי היישום לפני כניסת עובדים לשטח, לפי תכשיר. "
                         "ניסוחים חופשיים מקובצים לפי מספר השעות."),
        "reentry_aria": "תרשים עמודות: מספר תכשירים לפי זמן הכניסה מחדש לשטח המטופל.",
        "reentry_caption": "מספר תכשירים לפי זמן כניסה מחדש.",
        "holders_note": (f"{TOP_HOLDERS} בעלי הרישיון עם מספר התכשירים הגדול ביותר, מתוך "
                         f"{n(holder_counts.size)}."),
        "holders_aria": (f"תרשים עמודות: {TOP_HOLDERS} בעלי הרישיון לפי מספר תכשירים. "
                         f"המוביל: {h_names[0] if h_names else ''}."),
        "holders_caption": "מספר תכשירים ושימושים לפי בעל רישיון.",
        "makers_note": (f"{TOP_MAKERS} יצרני הפורמולציה עם מספר התכשירים הגדול ביותר, מתוך "
                        f"{n(maker_counts.size)}."),
        "makers_aria": f"תרשים עמודות: {TOP_MAKERS} יצרני הפורמולציה לפי מספר תכשירים.",
        "makers_caption": "מספר תכשירים לפי יצרן פורמולציה.",
        "form_note": f"סוג התכשיר הפיזי (פורמולציה), {TOP_FORMS} הנפוצים.",
        "form_aria": f"תרשים עמודות: מספר תכשירים לפי סוג פורמולציה, {TOP_FORMS} הנפוצים.",
        "form_caption": "מספר תכשירים לפי פורמולציה.",
        "products_caption": f"{TOP_PRODUCTS} התכשירים עם מספר השימושים המאושרים הגדול ביותר.",
    }

    hu = uses_all.groupby(HOLDER).size()
    tables = {
        "activity": [{"name": nm, "cells": [n(v) for v in act_ct.loc[nm]], "total": n(t)}
                     for nm, t in zip(act_names, act_vals)],
        "types": types,
        "tox": [{"name": nm, "cells": [n(v) for v in tox_ct.loc[nm]], "total": n(tox_ct.loc[nm].sum())}
                for nm in tox_order],
        "bees": [{"name": r, "cells": [n(v) for v in c]} for r, c in zip(bee_rows_names, bee_tab)],
        "env": [{"name": a, "count": n(b)} for a, b in zip(env_chart["names"], env_chart["values"])],
        "ai": [{"name": a, "count": n(b)} for a, b in zip(ai_names, ai_vals)],
        "moa": [{"act": r["act"], "code": r["code"], "desc": r["desc"], "count": n(r["count"])}
                for r in moa_rows],
        "heat_x": hx,
        "heat": heat_tab,
        "crops": [{"name": a, "count": n(b), "uses": n(crop_uses.get(a, 0))}
                  for a, b in zip(crop_names, crop_vals)],
        "pests": [{"name": a, "group": pest_grp.get(a, ""), "count": n(b)}
                  for a, b in zip(pest_names, pest_vals)],
        "phi": [{"name": a, "count": n(b)} for a, b in zip(phi_hist["names"], phi_hist["values"])],
        "box": [{"group": s["group"], "q": [f"{v:g}" for v in s["q"]], "count": n(s["count"])}
                for s in stats],
        "reentry": [{"name": a, "count": n(b)} for a, b in zip(reentry["names"], reentry["values"])],
        "holders": [{"name": a, "count": n(b),
                     "uses": n(hu.get(a, 0)) if a != OTHER else
                     n(int(hu.sum()) - int(sum(hu.get(x, 0) for x in h_names if x != OTHER)))}
                    for a, b in zip(h_names, h_vals)],
        "makers": [{"name": a, "count": n(b)} for a, b in zip(m_names, m_vals)],
        "forms": [{"name": a, "count": n(b)} for a, b in zip(f_names, f_vals)],
        "products": top_products,
        "pestgroups": [{"name": a, "count": n(b)} for a, b in pestgrp_counts.head(8).items()],
    }

    charts = {
        "timeline": timeline,
        "activity": activity,
        "tox": tox,
        "bees": bees,
        "env": env_chart,
        "ai": {"names": ai_names, "values": ai_vals},
        "moa": moa_chart,
        "heat": heat,
        "crops": {"names": crop_names, "values": crop_vals},
        "pests": {"names": pest_names, "values": pest_vals},
        "phi": phi_hist,
        "box": phi_box,
        "reentry": reentry,
        "holders": {"names": [short_co(x) for x in h_names], "values": h_vals},
        "makers": {"names": [short_co(x) for x in m_names], "values": m_vals},
        "forms": {"names": f_names, "values": f_vals},
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם תכשירי ההדברה המורשים בחקלאות בישראל: {n(total)} תכשירים, "
                           f"{n(ai_counts.size)} חומרים פעילים ו-{n(n_uses)} שימושים מאושרים "
                           f"לפי גידול ונגע, עם דרגות רעילות, סימוני סיכון לדבורים ותקופות המתנה."),
            "dataset_kind": "registry",
            "related_ids": ["a11eddd8-8288-4a10-a991-76d65df3e6eb",
                            "fdf06a98-0fe3-47df-8c3e-18ee582d1445",
                            "bff9b8b5-0e09-47f5-8b84-c1a853a7ebc5"],
            "suggested_tags": ["חומרי הדברה", "חקלאות", "הדברה אורגנית", "רעילות",
                               "דבורים", "גידולים"],
            "temporal_coverage": f"{y0}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
