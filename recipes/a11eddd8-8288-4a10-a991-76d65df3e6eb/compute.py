"""מאגר שאריות חומרי הדברה — Israel's maximum residue limits (MRL, mg/kg)
per active ingredient × crop (or animal product), from the Ministry of
Agriculture's plant-protection services.

One row = one limit: active ingredient, crop (Hebrew + English twin), the
MRL in mg/kg, the date the limit was last updated, and a truncated status
marker ("(בהמתנה" = pending, "(יתבטל ע" = slated for cancellation, empty =
no marker).

Crop groups follow the labels of the sibling registry recipe (7a6cbf55,
"קבוצת גידולים"); the residue table itself carries no group column, so a
fixed crop→group map is kept here, with keyword rules and an "אחר" bucket
for crops added later.

"Now" is never the wall clock: the latest year is the latest update date in
the data, and that year is labelled partial unless the data reaches
December.
"""
import math

import numpy as np
import pandas as pd

AI = "חומר_פעיל"
CROP = "גידול"
CROP_EN = "גידול_אנגלי"
MRL = "MRL"
DATE = "תאריך_עדכון"
FLAG = "MRL_בהמתנה"

ST_NONE = "ללא סימון"
ST_PEND = "בהמתנה"
ST_CANCEL = "מיועד לביטול"
ST_OTHER = "סימון אחר"
STATUS_ORDER = [ST_NONE, ST_PEND, ST_CANCEL, ST_OTHER]

OTHER = "אחר"
ANIMAL = "מוצרים מן החי"
GROUP_ORDER = ["ירקות", "נשירים", "הדרים", "סובטרופים", "צמחי תבלין", "גידולי שדה",
               "גידולי תעשיה", "מספוא", ANIMAL, "שונים", OTHER]

CROP_GROUP = {}
for _g, _crops in {
    "ירקות": ["סלק אדום (שורש ועלים)", "אבטיח", "קישוא", "כרובית", "תפוח אדמה", "חסה",
              "עגבניה", "שום", "דלורית", "שעועית ירוקה", "כרוביים", "תירס", "תות שדה לפרי",
              "מלון", "פלפל", "גזר", "חציל", "כרוב", "קינרס (ארטישוק)", "תירס מתוק",
              "כרפס/סלרי (שורש ועלים)", "בטטה", "בצל", "ברוקולי", "צנונית", "צנון", "אפון",
              "מלפפון", "לפת", "דלעת", "ירקות", "אפונת שלג", "כרוב סיני", "בצל ירוק",
              "לוף (כרתי/כרש/כרשה)", "סלק עלים", "קולרבי", "דלועיים", "תרד", "פול",
              "כרוב ניצנים", "ירקות שורש", "ירקות עלים", "קייל"],
    "נשירים": ["זית אירופאי", "אגס", "תפוח עץ", "משמש", "שזיף", "אפרסק", "שקד", "רימון",
               "פקאן תרבותי", "דובדבן", "תאנה", "נקטרינה", "חבוש", "חרוב מצוי", "ענבים",
               "פירות גלעיניים", "פירות גרעיניים"],
    "הדרים": ["פרי הדר", "קומקואט (תפוזון)"],
    "סובטרופים": ["מנגו", "אפרסמון", "אבוקדו", "גויאבה", "קיווי", "אנונה", "בננה", "תמר",
                  "שסק", "פיג'ואה", "ליצי", "פסיפלורה (שעונית)", "פירות סובטרופיים"],
    "צמחי תבלין": ["עירית בצלית", "רוקט (בן חרדל)", "כוסברה (גד השדה)", "מנטה",
                   "פטרוסלינון (שורש ועלים)", "שמיר (שבת)", "ריחן מצוי / בזיל", "פפריקה",
                   "מרווה", "אורגנו", "רוזמרין", "קורנית", "רוקולה", "טרגון", "חומעת הגינה",
                   "מיורם", "מיזונה (כרוב רפה)", "עלי טטסוי", "זעתר (אזוב מצוי)",
                   "לואיזה (ליפיה לימונית)", "לובאג'", "מליסה", "עשב לימון", "שומר",
                   "צמחי תבלין", "סטיביה", "עלי בוק צ'וי", "סייגית (צ'רביל)",
                   "אזוב מצוי (ראה גם זעתר)"],
    "גידולי שדה": ["חימצה (חומוס)", "חיטה", "שעורה תרבותית", "שבולת שועל", "דורה-סורגום",
                   "בקיה", "צבר", "קטניות", "דגניים"],
    "גידולי תעשיה": ["אגוז אדמה", "כותנה", "חמנית מצויה", "חוחובה", "חריע", "סלק סוכר"],
    "מספוא": ["אספסת", "סלק מספוא", "תלתן", "תירס מספוא", "עשב רודס", "קש חיטה"],
    ANIMAL: ["בשר", "חלב", "ביצים", "בשר עוף", "בשר, חלקי פנים", "בשר עוף, חלקי פנים",
             "בשר, שומן", "בקר", "כבשים", "דבש"],
    "שונים": ["שונות", "פירות", "אסתר", "וידן"],
}.items():
    for _c in _crops:
        CROP_GROUP[_c] = _g

ANIMAL_KEYS = ["בשר", "חלב", "ביצ", "דבש", "בקר", "כבש", "עוף"]

MRL_BINS = [(0.01, "עד 0.01"), (0.05, "עד 0.05"), (0.1, "עד 0.1"), (0.5, "עד 0.5"),
            (1.0, "עד 1"), (5.0, "עד 5"), (math.inf, "מעל 5")]   # each bin: above the previous edge
STRICT_AT = 0.05
TOP_CROPS = 15
TOP_AI = 15
HEAT_AI = 12
MIN_GROUP = 30          # limits a group needs to enter the boxplot / median comparison
MIN_RANGE_CROPS = 10    # crops an ingredient needs for the widest-range insight
RECENT_YEARS = 8        # window (years up to the latest) for the pending-share insight
HIGH_ROWS = 10
RECENT_ROWS = 12
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def mg(v):
    """An MRL value as written in the table: 0.01, 0.5, 15."""
    return f"{round(float(v), 4):g}"


def iso(name):
    return f"{LRI}{name}{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_dot(ts):
    return ts.strftime("%d.%m.%Y")


def ranked(counts):
    """Descending by value, ties by label — a total, shuffle-proof order."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def crop_group(c):
    g = CROP_GROUP.get(c)
    if g:
        return g
    if any(k in c for k in ANIMAL_KEYS):
        return ANIMAL
    if "ירקות" in c:
        return "ירקות"
    if "תבלין" in c:
        return "צמחי תבלין"
    return OTHER


def status_of(s):
    s = s.strip().lstrip("(").strip()
    if not s:
        return ST_NONE
    if s.startswith("בהמתנה"):
        return ST_PEND
    if s.startswith("יתבטל"):
        return ST_CANCEL
    return ST_OTHER


def mrl_bin(v):
    for hi, label in MRL_BINS:
        if v <= hi + 1e-12:
            return label
    return MRL_BINS[-1][1]


def quant(vals, q):
    return float(np.percentile(np.sort(np.asarray(vals, dtype=float)), q))


def _prepare(df):
    out = pd.DataFrame({c: df[c].astype(str).str.strip() for c in [AI, CROP, CROP_EN, MRL, DATE, FLAG]})
    out["mrl"] = pd.to_numeric(out[MRL].str.replace(",", "", regex=False), errors="coerce")
    raw = len(out)
    bad = out[AI].eq("") | out[CROP].eq("") | out["mrl"].isna() | (out["mrl"] <= 0)
    out = out[~bad].copy()
    out["dt"] = pd.to_datetime(out[DATE], errors="coerce", format="%d/%m/%Y")
    out["status"] = out[FLAG].map(status_of)
    out["group"] = out[CROP].map(crop_group)
    out = out.sort_values([AI, CROP, "mrl", DATE, FLAG], kind="stable").reset_index(drop=True)
    return out, raw - len(out)


# ── insight rules ──────────────────────────────────────────────────────────

def insight_crop_leader(crop_ai):
    if len(crop_ai) < 3:
        return None
    (c1, v1), (c2, v2), (c3, v3) = list(crop_ai.items())[:3]
    if v1 <= v2:
        return None
    return (f"{c1} הוא הגידול שנקבעו לו גבולות שארית למספר החומרים הפעילים הרב ביותר "
            f"({n(v1)}), ואחריו {c2} ({n(v2)}) ו{c3} ({n(v3)}).")


def insight_strict(df, top_row):
    total = len(df)
    if total == 0:
        return None
    k = int((df["mrl"] <= STRICT_AT + 1e-12).sum())
    share = k / total
    if share < 0.25:
        return None
    med = quant(df["mrl"], 50)
    return (f"{pct(share)} מהגבולות ({n(k)}) הם {mg(STRICT_AT)} מ״ג/ק״ג או פחות, וחציון "
            f"כל הגבולות הוא {mg(med)} מ״ג/ק״ג. הגבול הגבוה ביותר, {mg(top_row['mrl'])} "
            f"מ״ג/ק״ג, נקבע ל-{iso(top_row[AI])} ב{top_row[CROP]}.")


def insight_groups(box_rows):
    rows = [r for r in box_rows if r["n"] >= MIN_GROUP]
    if len(rows) < 3:
        return None
    hi = max(rows, key=lambda r: (r["med"], r["name"]))
    lo = min(rows, key=lambda r: (r["med"], r["name"]))
    if lo["med"] <= 0 or hi["med"] / lo["med"] < 2:
        return None
    ratio = hi["med"] / lo["med"]
    return (f"רמת הגבול תלויה בסוג הגידול: החציון ב{hi['name']} הוא {mg(hi['med'])} מ״ג/ק״ג, "
            f"פי {ratio:.0f} מהחציון ב{lo['name']} ({mg(lo['med'])} מ״ג/ק״ג) "
            f"(קבוצות עם {n(MIN_GROUP)} גבולות לפחות).")


def insight_pending_shift(dated, last_year):
    if dated.empty:
        return None
    start = last_year - RECENT_YEARS + 1
    recent = dated[dated["dt"].dt.year >= start]
    early = dated[dated["dt"].dt.year < start]
    if len(recent) < 30 or len(early) < 30:
        return None
    r = float((recent["status"] == ST_PEND).mean())
    e = float((early["status"] == ST_PEND).mean())
    if r < 0.5 or r - e < 0.2:
        return None
    return (f"רוב העדכונים האחרונים עדיין ממתינים: מבין {n(len(recent))} הגבולות שעודכנו "
            f"בשנים {start}–{last_year}, {pct(r)} מסומנים „{ST_PEND}”, לעומת {pct(e)} "
            f"מהגבולות שעודכנו לפני {start}.")


def insight_old_vs_new(df):
    first = df.dropna(subset=["dt"]).groupby(AI)["dt"].min().dt.year
    canc = df[df["status"] == ST_CANCEL]
    pend = df[df["status"] == ST_PEND]
    ca = sorted(set(canc[AI]) & set(first.index))
    pa = sorted(set(pend[AI]) & set(first.index))
    if len(ca) < 5 or len(pa) < 5:
        return None
    yc = int(round(quant(first.loc[ca], 50)))
    yp = int(round(quant(first.loc[pa], 50)))
    if yp - yc < 5:
        return None
    lead = ranked(canc.groupby(AI).size())
    return (f"הסימון „{ST_CANCEL}” חל על {n(len(canc))} גבולות של {n(len(ca))} חומרים פעילים "
            f"ותיקים יחסית (חציון שנת העדכון המוקדם ביותר שלהם: {yc}), ובראשם "
            f"{iso(lead.index[0])} ({n(lead.iloc[0])}); הסימון „{ST_PEND}” חל בעיקר על חומרים "
            f"חדשים יותר ({n(len(pa))} חומרים, חציון {yp}).")


def insight_breadth(ai_crops):
    if len(ai_crops) < 2:
        return None
    (a1, v1), (a2, v2) = list(ai_crops.items())[:2]
    single = int((ai_crops == 1).sum())
    if v1 <= v2:
        return None
    tail = (f" מנגד, ל-{n(single)} חומרים ({pct(single / len(ai_crops))}) נקבע גבול בגידול "
            f"אחד בלבד.") if single else ""
    return (f"{iso(a1)} הוא החומר הפעיל עם הכיסוי הרחב ביותר — גבולות ב-{n(v1)} גידולים, "
            f"לעומת {n(v2)} ל-{iso(a2)} שבמקום השני.{tail}")


def insight_range(ai_stats):
    s = ai_stats[ai_stats["crops"] >= MIN_RANGE_CROPS].copy()
    if s.empty:
        return None
    s["ratio"] = s["max"] / s["min"]
    s = s.reset_index().sort_values(["ratio", AI], ascending=[False, True], kind="stable")
    top = s.iloc[0]
    if top["ratio"] < 100:
        return None
    ties = [a for a in s.loc[s["ratio"] == top["ratio"], AI] if a != top[AI]]
    tie_txt = f" (יחד עם {', '.join(iso(a) for a in ties[:2])})" if ties else ""
    return (f"לאותו חומר יכולים להיות גבולות שונים מאוד בין גידולים: ל-{iso(top[AI])} "
            f"נקבעו גבולות מ-{mg(top['min'])} ועד {mg(top['max'])} מ״ג/ק״ג "
            f"(פי {n(round(top['ratio']))}) ב-{n(top['crops'])} גידולים — הפער הגדול ביותר "
            f"בין החומרים עם {n(MIN_RANGE_CROPS)} גידולים לפחות{tie_txt}.")


def insight_latest(dated, last_date, partial):
    if dated.empty:
        return None
    y = last_date.year
    cur = dated[dated["dt"].dt.year == y]
    prev = int((dated["dt"].dt.year == y - 1).sum())
    k, ais = len(cur), cur[AI].nunique()
    if k == 0:
        return None
    when = f"ב-{y} (עד {d_he(last_date)})" if partial else f"ב-{y}"
    s = f"{when} עודכנו {n(k)} גבולות של {n(ais)} חומרים פעילים"
    if prev:
        if partial and k > prev:
            s += f" — כבר יותר מבכל {y - 1} ({n(prev)})"
        elif not partial and k != prev:
            word = "יותר" if k > prev else "פחות"
            s += f" — {word} מב-{y - 1} ({n(prev)})"
        elif not partial:
            s += f" — כמו ב-{y - 1}"
    last = cur[cur["dt"] == last_date]
    la = last[AI].nunique()
    who = "חומר אחד" if la == 1 else f"{n(la)} חומרים"
    lim = "גבול אחד" if len(last) == 1 else f"{n(len(last))} גבולות"
    s += (f". העדכון האחרון כלל {lim} של {who}." if partial
          else f". העדכון האחרון, ב-{d_he(last_date)}, כלל {lim} של {who}.")
    return s


def insight_animal(df):
    a = df[df["group"] == ANIMAL]
    if len(a) < 5:
        return None
    prods = ranked(a.groupby(CROP).size())
    head = ", ".join(f"{k} ({n(v)})" for k, v in list(prods.items())[:3])
    return (f"המאגר כולל גם {n(len(a))} גבולות שארית במוצרים מן החי, ל-{n(a[AI].nunique())} "
            f"חומרים פעילים; המוצרים עם הכי הרבה גבולות: {head}.")


# ── compute ────────────────────────────────────────────────────────────────

def compute(frames):
    df, dropped = _prepare(frames["main"])
    total = len(df)
    n_ai = df[AI].nunique()
    n_crop = df[CROP].nunique()
    dated = df.dropna(subset=["dt"])
    undated = total - len(dated)
    last_date = dated["dt"].max()
    first_date = dated["dt"].min()
    last_year, first_year = int(last_date.year), int(first_date.year)
    partial = int(last_date.month) < 12

    st_counts = df["status"].value_counts()
    statuses = [s for s in STATUS_ORDER if st_counts.get(s, 0)]
    n_pend = int(st_counts.get(ST_PEND, 0))
    n_canc = int(st_counts.get(ST_CANCEL, 0))
    med_all = quant(df["mrl"], 50)

    # KPIs
    pend_share = n_pend / total if total else 0.0
    canc_share = n_canc / total if total else 0.0
    kpis = {
        "limits": {"value": total, "display": n(total), "tone": "brand"},
        "ai": {"value": n_ai, "display": n(n_ai), "tone": "brand"},
        "crops": {"value": n_crop, "display": n(n_crop), "tone": "brand"},
        "median": {"value": med_all, "display": mg(med_all), "tone": "info"},
        "pending": {"value": n_pend, "display": f"{pend_share * 100:.1f}%",
                    "tone": "warn" if pend_share >= 0.2 else "info"},
        "cancel": {"value": n_canc, "display": n(n_canc),
                   "tone": "warn" if canc_share >= 0.05 else ("info" if n_canc else "ok")},
    }

    # chart: limits by year of last update × status
    years = list(range(first_year, last_year + 1))
    yc = dated.groupby([dated["dt"].dt.year, "status"]).size()
    year_series = [{"name": s, "data": [int(yc.get((y, s), 0)) for y in years]} for s in statuses]
    by_year_chart = {"x": [str(y) for y in years], "series": year_series, "partial": partial}

    # chart: MRL distribution
    bins = df["mrl"].map(mrl_bin).value_counts()
    mrl_chart = {"names": [b for _, b in MRL_BINS], "values": [int(bins.get(b, 0)) for _, b in MRL_BINS]}
    mrl_table = [{"name": b, "count": n(bins.get(b, 0)),
                  "share": f"{bins.get(b, 0) / total * 100:.1f}%"} for _, b in MRL_BINS]

    # groups
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    g_lim = df.groupby("group").size()
    g_ai = df.groupby("group")[AI].nunique()
    g_crop = df.groupby("group")[CROP].nunique()
    groups = sorted(g_lim.index, key=lambda g: (-int(g_lim[g]), order.get(g, 99), g))
    group_chart = {"names": groups, "limits": [int(g_lim[g]) for g in groups],
                   "ai": [int(g_ai[g]) for g in groups]}
    group_table = [{"name": g, "limits": n(g_lim[g]), "ai": n(g_ai[g]), "crops": n(g_crop[g])}
                   for g in groups]

    # boxplot by group (groups with enough limits)
    box_rows = []
    for g in groups:
        v = df.loc[df["group"] == g, "mrl"]
        box_rows.append({"name": g, "n": len(v), "p10": quant(v, 10), "q1": quant(v, 25),
                         "med": quant(v, 50), "q3": quant(v, 75), "p90": quant(v, 90)})
    box_used = sorted([r for r in box_rows if r["n"] >= MIN_GROUP],
                      key=lambda r: (-r["med"], -r["n"], r["name"]))
    box_chart = {"names": [r["name"] for r in box_used],
                 "box": [[round(r[k], 4) for k in ("p10", "q1", "med", "q3", "p90")] for r in box_used]}
    box_table = [{"name": r["name"], "n": n(r["n"]), "p10": mg(r["p10"]), "q1": mg(r["q1"]),
                  "med": mg(r["med"]), "q3": mg(r["q3"]), "p90": mg(r["p90"])} for r in box_used]
    box_excluded = len(groups) - len(box_used)

    # status by group (100%)
    sg = df.groupby(["group", "status"]).size()
    status_rows = groups
    status_chart = {"rows": status_rows, "series": [], "counts": []}
    for s in statuses:
        status_chart["series"].append({"name": s, "data": [
            round(float(sg.get((g, s), 0)) / float(g_lim[g]) * 100, 1) for g in status_rows]})
    status_chart["counts"] = [[int(sg.get((g, s), 0)) for s in statuses] for g in status_rows]
    status_table = [{"name": g, "cells": [n(sg.get((g, s), 0)) for s in statuses], "total": n(g_lim[g])}
                    for g in status_rows]

    # crops ranked by distinct active ingredients
    crop_ai = ranked(df.groupby(CROP)[AI].nunique())
    crop_med = df.groupby(CROP)["mrl"].median()
    crop_grp = df.groupby(CROP)["group"].first()
    top_c = list(crop_ai.index[:TOP_CROPS])
    crops_chart = {"names": top_c, "values": [int(crop_ai[c]) for c in top_c]}
    crops_table = [{"name": c, "group": crop_grp[c], "ai": n(crop_ai[c]), "med": mg(crop_med[c])}
                   for c in top_c]

    # active ingredients ranked by distinct crops
    ai_crops = ranked(df.groupby(AI)[CROP].nunique())
    ai_stats = df.groupby(AI)["mrl"].agg(["min", "max", "median"])
    ai_stats["crops"] = ai_crops
    top_a = list(ai_crops.index[:TOP_AI])
    ai_chart = {"names": top_a, "values": [int(ai_crops[a]) for a in top_a]}
    ai_table = [{"name": a, "crops": n(ai_crops[a]), "min": mg(ai_stats.at[a, "min"]),
                 "med": mg(ai_stats.at[a, "median"]), "max": mg(ai_stats.at[a, "max"])} for a in top_a]

    # heatmap: top ingredients × crop groups (distinct crops with a limit)
    heat_ai = list(ai_crops.index[:HEAT_AI])
    hc = df[df[AI].isin(heat_ai)].groupby([AI, "group"])[CROP].nunique()
    heat_groups = [g for g in groups if g in set(hc.index.get_level_values(1))]
    cells = []
    for yi, a in enumerate(heat_ai):
        for xi, g in enumerate(heat_groups):
            v = int(hc.get((a, g), 0))
            if v:
                cells.append([xi, yi, v])
    heat_chart = {"x": heat_groups, "y": heat_ai, "cells": cells,
                  "max": max([c[2] for c in cells] or [1])}

    # scatter: breadth vs median limit per ingredient
    sc = ai_stats.reset_index().sort_values(AI, kind="stable")
    scatter = {"points": [[int(r["crops"]), round(float(r["median"]), 4), r[AI]] for _, r in sc.iterrows()]}

    # tables: highest limits, latest updates
    hi = df.sort_values(["mrl", AI, CROP], ascending=[False, True, True], kind="stable").head(HIGH_ROWS)
    high_table = [{"ai": r[AI], "crop": r[CROP], "mrl": mg(r["mrl"]),
                   "date": d_dot(r["dt"]) if pd.notna(r["dt"]) else "", "status": r["status"]}
                  for _, r in hi.iterrows()]
    rc = dated.sort_values(["dt", AI, CROP], ascending=[False, True, True], kind="stable").head(RECENT_ROWS)
    recent_table = [{"ai": r[AI], "crop": r[CROP], "mrl": mg(r["mrl"]), "date": d_dot(r["dt"]),
                     "status": r["status"]} for _, r in rc.iterrows()]
    top_row = hi.iloc[0]

    # insights
    rules = [
        ("crop-leader", insight_crop_leader(crop_ai)),
        ("strict", insight_strict(df, top_row)),
        ("groups", insight_groups(box_rows)),
        ("pending-shift", insight_pending_shift(dated, last_year)),
        ("old-vs-new", insight_old_vs_new(df)),
        ("breadth", insight_breadth(ai_crops)),
        ("range", insight_range(ai_stats)),
        ("latest", insight_latest(dated, last_date, partial)),
        ("animal", insight_animal(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    excl = []
    if dropped:
        excl.append(f"{n(dropped)} רשומות ללא חומר, גידול או ערך MRL חיובי לא נכללו")
    excl_txt = (" " + "; ".join(excl) + ".") if excl else ""
    undated_txt = f" {n(undated)} גבולות ללא תאריך תקין אינם מוצגים בתרשים זה." if undated else ""
    partial_txt = f" שנת {last_year} חלקית — הנתונים עד {d_he(last_date)}." if partial else ""

    labels = {
        "lede": (f"גבולות השארית המרביים (MRL) של חומרי הדברה במזון בישראל: {n(total)} גבולות "
                 f"ל-{n(n_ai)} חומרים פעילים ב-{n(n_crop)} גידולים ומוצרים מן החי, במיליגרם לקילוגרם "
                 f"תוצרת. הגבולות עודכנו בין {first_year} ל-{d_he(last_date)}; {n(n_pend)} מהם "
                 f"מסומנים „{ST_PEND}” ו-{n(n_canc)} „{ST_CANCEL}”.{excl_txt}"),
        "median_kpi": "חציון הגבול (מ״ג/ק״ג)",
        "pending_kpi": f"גבולות בסימון „{ST_PEND}” ({n(n_pend)})",
        "cancel_kpi": f"גבולות בסימון „{ST_CANCEL}”",
        "years_note": (f"מספר הגבולות לפי שנת העדכון האחרון שלהם ולפי הסימון בטבלה. גבול שעודכן "
                       f"נספר רק בשנת העדכון האחרונה.{partial_txt}{undated_txt}"),
        "years_aria": (f"תרשים עמודות מוערמות: גבולות שארית לפי שנת עדכון, {first_year}–{last_year}, "
                       f"לפי סימון."),
        "mrl_note": (f"התפלגות ערכי הגבול במ״ג/ק״ג; כל עמודה — מעל העמודה שלפניה ועד הערך שבה. {pct(mrl_chart['values'][0] / total)} מהגבולות "
                     f"הם {mg(MRL_BINS[0][0])} או פחות."),
        "mrl_aria": "תרשים עמודות: מספר גבולות השארית לפי טווח ערך הגבול במ״ג/ק״ג.",
        "mrl_caption": "מספר הגבולות ושיעורם לפי טווח ערך הגבול (כל טווח — מעל הגבול העליון של הטווח הקודם).",
        "groups_note": (f"מספר הגבולות ומספר החומרים הפעילים בכל קבוצת גידולים "
                        f"({n(len(groups))} קבוצות). השיוך לקבוצות לפי שם הגידול."),
        "groups_aria": "תרשים עמודות: גבולות וחומרים פעילים לפי קבוצת גידולים.",
        "groups_caption": "גבולות, חומרים פעילים וגידולים לפי קבוצת גידולים.",
        "box_note": (f"פיזור ערכי הגבול בכל קבוצה, בציר לוגריתמי: הקופסה בין הרבעון התחתון לעליון, "
                     f"הקו — החציון, והשפמים — העשירון התחתון והעליון. קבוצות עם {n(MIN_GROUP)} "
                     f"גבולות לפחות" + (f" ({n(box_excluded)} קבוצות קטנות לא הוצגו)." if box_excluded else ".")),
        "box_aria": "תרשים קופסה: פיזור ערכי הגבול במ״ג/ק״ג לפי קבוצת גידולים, בציר לוגריתמי.",
        "box_caption": "עשירונים, רבעונים וחציון של ערך הגבול (מ״ג/ק״ג) לפי קבוצת גידולים.",
        "status_note": "שיעור הגבולות בכל סימון, בכל קבוצת גידולים.",
        "status_aria": "תרשים עמודות מוערמות באחוזים: סימון הגבולות לפי קבוצת גידולים.",
        "status_caption": "מספר הגבולות לפי סימון וקבוצת גידולים.",
        "crops_note": (f"{n(len(top_c))} הגידולים שנקבעו להם גבולות למספר החומרים הפעילים "
                       f"הרב ביותר, מתוך {n(n_crop)}."),
        "crops_aria": f"תרשים עמודות: {n(len(top_c))} הגידולים עם מספר החומרים הפעילים הרב ביותר.",
        "crops_caption": "מספר החומרים הפעילים וחציון הגבול לפי גידול.",
        "ai_note": (f"{n(len(top_a))} החומרים הפעילים שנקבעו להם גבולות במספר הגידולים הרב ביותר, "
                    f"מתוך {n(n_ai)}. בטבלה — טווח הגבולות של כל חומר."),
        "ai_aria": f"תרשים עמודות: {n(len(top_a))} החומרים הפעילים עם מספר הגידולים הרב ביותר.",
        "ai_caption": "מספר הגידולים וטווח הגבול (מ״ג/ק״ג) לפי חומר פעיל.",
        "heat_note": (f"מספר הגידולים שבהם נקבע גבול לכל אחד מ-{n(len(heat_ai))} החומרים הנפוצים, "
                      f"לפי קבוצת גידולים."),
        "heat_aria": (f"מפת חום: מספר גידולים עם גבול לפי חומר פעיל ({n(len(heat_ai))}) "
                      f"וקבוצת גידולים ({n(len(heat_groups))})."),
        "scatter_note": (f"כל נקודה היא חומר פעיל ({n(n_ai)}): מספר הגידולים שנקבע לו בהם גבול, "
                         f"מול חציון הגבולות שלו (ציר לוגריתמי)."),
        "scatter_aria": "תרשים פיזור: מספר הגידולים מול חציון הגבול לכל חומר פעיל.",
        "high_note": f"{n(len(high_table))} הגבולות הגבוהים ביותר במאגר.",
        "high_caption": "הגבולות הגבוהים ביותר: חומר פעיל, גידול, גבול, תאריך עדכון וסימון.",
        "recent_note": f"{n(len(recent_table))} הגבולות שעודכנו לאחרונה, עד {d_he(last_date)}.",
        "recent_caption": "הגבולות שעודכנו לאחרונה: חומר פעיל, גידול, גבול, תאריך עדכון וסימון.",
    }

    return {
        "agent_data": {
            "summary_he": (f"גבולות השארית המרביים (MRL) של חומרי הדברה במזון בישראל: {n(total)} "
                           f"גבולות ל-{n(n_ai)} חומרים פעילים ב-{n(n_crop)} גידולים ומוצרים מן החי, "
                           f"בחציון {mg(med_all)} מ״ג/ק״ג, עם {n(n_pend)} גבולות בהמתנה ו-{n(n_canc)} "
                           f"המיועדים לביטול."),
            "dataset_kind": "registry",
            "related_ids": ["7a6cbf55-8178-4d40-8613-a38909c7e96f",
                            "bff9b8b5-0e09-47f5-8b84-c1a853a7ebc5",
                            "fdf06a98-0fe3-47df-8c3e-18ee582d1445"],
            "suggested_tags": ["חומרי הדברה", "שאריות", "בטיחות מזון", "חקלאות", "גידולים",
                               "רגולציה"],
            "temporal_coverage": f"{first_year}/{last_date.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "years": by_year_chart,
            "mrl": mrl_chart,
            "groups": group_chart,
            "box": box_chart,
            "status": status_chart,
            "crops": crops_chart,
            "ai": ai_chart,
            "heat": heat_chart,
            "scatter": scatter,
        },
        "tables": {
            "statuses": statuses,
            "mrl": mrl_table,
            "groups": group_table,
            "box": box_table,
            "status": status_table,
            "crops": crops_table,
            "ai": ai_table,
            "high": high_table,
            "recent": recent_table,
        },
        "insights": insights,
        "labels": labels,
    }
