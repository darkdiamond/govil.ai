"""השתלמויות למורי דרך: the Ministry of Tourism's catalog of refresher courses.

Licensed tour guides must complete two refresher courses every two years to
renew their licence. Since July 2020 the courses are run by external
organizers (museums, colleges, NGOs) under a ministry call; each training
year (July to June) the ministry publishes the full catalog as a new file:
one row per course with organizer, title, catalog number, date, instructor,
region, course type, language and price.

Input "courses" concatenates every catalog file (by_schema). The file named
"2020 - 2021" was overwritten upstream with an early copy of the 2025-2026
catalog, so each file is assigned to the training year its DATES fall in
(modal year), not to its name. When two files land on the same year, the one
whose name matches that year is kept (else the larger file) and the other is
dropped, disclosed on the page. A new yearly file flows in automatically.

Formats drift per file: dates come as ISO, dd/mm/yyyy or d.m.yy; regions are
the four macro regions in recent files but fine-grained places in older ones
(mapped to macro regions, unknown -> "אחר"); the 2021-2022 file has no course
type column (Place instead). Price bands (Price_Range) changed every year, so
the page bins Price itself.

Input "institutions" is the small list of colleges that run the licensing
course itself; it is shown as a table.
"""
import re

import pandas as pd

SUMMARY_MAX = 155
TOP_ORGS = 15
TOP_INSTR = 15
TOP_TYPES = 6
FULL_YEAR_MONTHS = 10   # a catalog spanning fewer months is treated as partial
TREND_PCT = 5.0         # +-% for "growth"/"decline" wording

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTH_ORDER = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]   # training year runs July-June
DOW_HE = {6: "ראשון", 0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת"}
DOW_ORDER = [6, 0, 1, 2, 3, 4, 5]

REGION_ORDER = ["ירושלים", "מרכז", "חיפה והצפון", "דרום", "יהודה ושומרון", "מקוון", "אחר"]
REGION_MAP = {
    "ירושלים": "ירושלים",
    "מרכז": "מרכז", "תל אביב": "מרכז", "תל אביב וגוש דן": "מרכז", "שפלה": "מרכז",
    "השרון": "מרכז", "נתניה": "מרכז", "לוד": "מרכז", "יפו העתיקה": "מרכז", "הרצליה": "מרכז",
    "עמק חפר": "מרכז", "מישור החוף": "מרכז",
    "חיפה והצפון": "חיפה והצפון", "צפון": "חיפה והצפון", "חיפה והכרמל": "חיפה והצפון",
    "חיפה": "חיפה והצפון", "גליל תחתון": "חיפה והצפון", "גליל מערבי": "חיפה והצפון",
    "גליל עליון": "חיפה והצפון", "עכו": "חיפה והצפון", "צפת": "חיפה והצפון",
    "עמק יזרעאל": "חיפה והצפון", "עמק חרוד": "חיפה והצפון", "עמק הירדן": "חיפה והצפון",
    "קיסריה": "חיפה והצפון", "מגידו": "חיפה והצפון", "אום אל פחם": "חיפה והצפון",
    "טבריה": "חיפה והצפון", "נצרת": "חיפה והצפון", "גולן": "חיפה והצפון",
    "דרום": "דרום", "אשקלון": "דרום", "אילת": "דרום", "ים המלח": "דרום", "נגב": "דרום",
    "באר שבע": "דרום", "מדבר יהודה": "דרום", "ים המלח והבקעה": "דרום",
    "שומרון": "יהודה ושומרון", "יהודה": "יהודה ושומרון", "בנימין": "יהודה ושומרון",
    "בקעת הירדן": "יהודה ושומרון", "בקעת הירדן סובב יריחו": "יהודה ושומרון",
    "מקוון": "מקוון",
}

LANG_ORDER = ["עברית", "אנגלית", "ערבית", "רוסית"]
PRICE_BANDS = [(0, 100, "עד 99 ₪"), (100, 150, "100 עד 149 ₪"), (150, 200, "150 עד 199 ₪"),
               (200, None, "200 ₪ ומעלה")]
LEGAL = re.compile(r'\b(בע"מ|בע״מ|ע"ר|ע״ר|חל"צ|חל״צ)')
TITLES = re.compile(r'^(ד"ר|ד״ר|דר\'|פרופ\'|פרופ׳|פרופסור|פרופ)\s+')


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _i(v):
    return f"{int(round(v)):,}"


def _pct(v, d=1):
    return f"{v:.{d}f}%"


def _signed(v, d=1):
    s = f"{abs(v):.{d}f}%"
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def _dates(s):
    s = s.map(_clean)
    out = pd.to_datetime(s.str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    for f in ("%d/%m/%Y", "%d.%m.%y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d"):
        out = out.fillna(pd.to_datetime(s, format=f, errors="coerce"))
    # Excel serial day numbers (an XLSX date column exported as a number)
    serial = pd.to_numeric(s.where(s.str.fullmatch(r"\d{5}(\.0+)?")), errors="coerce")
    serial = serial.where((serial >= 36526) & (serial <= 73051))   # 2000-01-01 .. 2099-12-31
    out = out.fillna(pd.to_datetime(serial, unit="D", origin="1899-12-30", errors="coerce"))
    return out


def _region(v):
    v = _clean(v)
    if v in REGION_MAP:
        return REGION_MAP[v]
    for k in sorted(REGION_MAP, key=lambda k: (-len(k), k)):
        if v.startswith(k):
            return REGION_MAP[k]
    if v.startswith("הר חברון"):
        return "יהודה ושומרון"
    return "אחר" if v else "לא צוין"


def _ctype(v):
    v = _clean(v)
    if not v:
        return "לא צוין"
    if "לכת" in v:
        return "סיור רגלי למיטיבי לכת"
    if v.startswith("יום עיון"):
        return "יום עיון"
    return v


def _org_key(v):
    v = LEGAL.sub(" ", _clean(v))
    v = re.sub(r"[\-–()\"'״׳,]", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def _org_disp(v):
    v = re.sub(r"\(\s*\)", "", LEGAL.sub("", v))
    return _clean(v).strip(" -,")


def _year_label(y):
    return f"{y}-{y + 1}"


def _choose_files(df):
    """Assign each file to its modal training year; one file per year."""
    info, undated = [], []
    for name, g in df.groupby("_resource_name", sort=True):
        ys = g["ty"].dropna()
        if ys.empty:
            undated.append({"name": name, "n": len(g)})
            continue
        vc = ys.value_counts()
        modal = int(min(vc[vc == vc.max()].index))
        m = re.search(r"(20\d\d)", name)
        named = int(m.group(1)) if m else None
        info.append({"name": name, "year": modal, "named": named, "n": len(g)})
    keep, dropped = {}, []
    for y in sorted({r["year"] for r in info}):
        cands = [r for r in info if r["year"] == y]
        cands.sort(key=lambda r: (r["named"] != y, -r["n"], r["name"]))
        keep[cands[0]["name"]] = y
        dropped += cands[1:]
    return keep, dropped, undated


def compute(frames):
    raw = frames["courses"].copy()
    for c in ("character", "Place"):
        if c not in raw.columns:
            raw[c] = ""
    raw = raw.fillna("")
    raw["_resource_name"] = raw["_resource_name"].map(_clean)
    raw["dt"] = _dates(raw["Date"])
    raw["ty"] = raw["dt"].dt.year - (raw["dt"].dt.month < 7).astype("float")

    keep, dropped, undated = _choose_files(raw)
    df = raw[raw["_resource_name"].isin(keep)].copy()
    df["year"] = df["_resource_name"].map(keep).astype(int)
    n_dropped = sum(r["n"] for r in dropped)

    df["org_raw"] = df["School"].map(_clean)
    df["org_key"] = df["org_raw"].map(_org_key)
    disp = (df.groupby(["org_key", "org_raw"]).size().reset_index(name="n")
            .sort_values(["org_key", "n", "org_raw"], ascending=[True, False, True], kind="stable")
            .drop_duplicates("org_key"))
    org_name = dict(zip(disp["org_key"], disp["org_raw"].map(_org_disp)))
    df["org"] = df["org_key"].map(org_name)
    df["region"] = df["Region"].map(_region)
    df["ctype"] = df["character"].map(_ctype)
    df["lang"] = df["Language"].map(_clean).replace("", "לא צוין")
    df["price"] = pd.to_numeric(df["Price"].map(_clean).str.replace(",", "", regex=False), errors="coerce")
    df["title"] = df["Name"].map(_clean)
    df = df.sort_values(["year", "Number", "title", "dt", "org"], kind="stable").reset_index(drop=True)

    years = sorted(df["year"].unique().tolist())
    ylabels = [_year_label(y) for y in years]
    by_year = df.groupby("year")
    n_courses = by_year.size().reindex(years).astype(int).tolist()
    n_orgs = by_year["org_key"].nunique().reindex(years).astype(int).tolist()
    months_cov = df.dropna(subset=["dt"]).groupby("year")["dt"].apply(lambda s: s.dt.month.nunique()).reindex(years).fillna(0).astype(int).tolist()
    full = [m >= FULL_YEAR_MONTHS for m in months_cov]
    latest = years[-1]
    L = _year_label(latest)
    li = len(years) - 1
    cur = df[df["year"] == latest]
    full_years = [y for y, f in zip(years, full) if f]

    labels, charts, tables, flags, insights = {}, {}, {}, {}, []

    # ---------- per year
    charts["years"] = {"x": ylabels, "n": n_courses, "orgs": n_orgs, "partial": [not f for f in full]}
    tables["years"] = [{"year": ylabels[i] + ("" if full[i] else " (חלקי)"), "n": _i(n_courses[i]), "orgs": _i(n_orgs[i])}
                       for i in range(len(years))]
    labels["years_aria"] = f"מספר ההשתלמויות ומספר המארגנים בכל שנת השתלמויות, {ylabels[0]} עד {L}"
    peak_i = max(range(len(years)), key=lambda i: (n_courses[i], years[i]))
    peak_txt = ("זו השנה עם ההיצע הגדול ביותר במאגר. " if peak_i == li else
                f"השנה עם ההיצע הגדול ביותר: {ylabels[peak_i]}, עם {n_courses[peak_i]:,} השתלמויות. ")
    labels["years_lede"] = (f"בקטלוג {L} {n_courses[li]:,} השתלמויות של {n_orgs[li]:,} מארגנים. " + peak_txt +
                            "כל שנת השתלמויות נמשכת מיולי עד יוני.")
    if dropped:
        names = ", ".join(f"\"{r['name']}\"" for r in dropped)
        labels["dup_note"] = (f"הקובץ {names} מכיל עותק נוסף של קטלוג {', '.join(_year_label(r['year']) for r in dropped)} "
                              f"({n_dropped:,} שורות) ולכן לא נספר; השנה נקבעת לפי תאריכי ההשתלמויות.")
    else:
        labels["dup_note"] = ""
    if undated:
        names = ", ".join(f"\"{r['name']}\" ({r['n']:,} שורות)" for r in undated)
        labels["dup_note"] = (labels["dup_note"] + " " if labels["dup_note"] else "") + (
            f"לא ניתן לפענח את התאריכים בקובץ {names}, ולכן ההשתלמויות שבו אינן נספרות בעמוד.")

    if len(years) >= 2:
        prev = n_courses[li - 1]
        ch = (n_courses[li] - prev) / prev * 100 if prev else 0.0
        if not full[li]:
            insights.append({"id": "trend", "text_he": (
                f"קטלוג {L} עדיין חלקי: {n_courses[li]:,} השתלמויות ב-{months_cov[li]:,} חודשים בלבד, "
                f"לעומת {prev:,} בכל {ylabels[li - 1]}.")})
        else:
            word = "עלייה" if ch >= TREND_PCT else "ירידה" if ch <= -TREND_PCT else "יציבות"
            insights.append({"id": "trend", "text_he": (
                f"{word} בהיצע: בקטלוג {L} {n_courses[li]:,} השתלמויות לעומת {prev:,} ב-{ylabels[li - 1]} "
                f"({_signed(ch)}).")})
        if peak_i != li and n_courses[peak_i] > n_courses[li]:
            insights.append({"id": "peak", "text_he": (
                f"השנה עם ההיצע הגדול ביותר היא {ylabels[peak_i]}: {n_courses[peak_i]:,} השתלמויות "
                f"מ-{n_orgs[peak_i]:,} מארגנים.")})

    # ---------- month x year heatmap
    dd = df.dropna(subset=["dt"])
    mcounts = dd.groupby(["year", dd["dt"].dt.month]).size()
    heat = []
    for yi, y in enumerate(years):
        for mi, m in enumerate(MONTH_ORDER):
            heat.append([mi, yi, int(mcounts.get((y, m), 0))])
    charts["months"] = {"months": [MONTHS_HE[m - 1] for m in MONTH_ORDER], "years": ylabels, "cells": heat,
                        "max": max([c[2] for c in heat] + [1])}
    tables["months"] = [{"m": MONTHS_HE[m - 1], "v": [_i(mcounts.get((y, m), 0)) for y in years]} for m in MONTH_ORDER]
    labels["months_aria"] = f"מפת חום: מספר ההשתלמויות לפי חודש ושנת השתלמויות, {ylabels[0]} עד {L}"
    fdd = dd[dd["year"].isin(full_years)]
    if len(full_years) >= 2 and len(fdd):
        mtot = fdd.groupby(fdd["dt"].dt.month).size().reindex(range(1, 13), fill_value=0)
        avg = mtot / len(full_years)
        top_m = int(sorted(range(1, 13), key=lambda m: (-mtot[m], m))[0])
        low_m = int(sorted(range(1, 13), key=lambda m: (mtot[m], m))[0])
        share_top = mtot[top_m] / mtot.sum() * 100
        labels["months_lede"] = (f"בממוצע על {len(full_years):,} שנים מלאות, {MONTHS_HE[top_m - 1]} הוא החודש העמוס ביותר "
                                 f"({avg[top_m]:.1f} השתלמויות בשנה) ו{MONTHS_HE[low_m - 1]} השקט ביותר ({avg[low_m]:.1f}).")
        if share_top >= 100 / 12 * 1.3:
            insights.append({"id": "season", "text_he": (
                f"עונתיות: {_pct(share_top)} מההשתלמויות בשנים המלאות נערכות ב{MONTHS_HE[top_m - 1]}, "
                f"לעומת {_pct(mtot[low_m] / mtot.sum() * 100)} ב{MONTHS_HE[low_m - 1]}.")})
    else:
        labels["months_lede"] = "כל תא הוא מספר ההשתלמויות שנקבעו לאותו חודש."

    # ---------- weekday (latest year vs all)
    dow_all = dd["dt"].dt.dayofweek.value_counts()
    dow_cur = dd[dd["year"] == latest]["dt"].dt.dayofweek.value_counts()
    tot_all = max(int(dow_all.sum()), 1)
    tot_cur = max(int(dow_cur.sum()), 1)
    charts["dow"] = {"x": [DOW_HE[d] for d in DOW_ORDER],
                     "all": [round(int(dow_all.get(d, 0)) / tot_all * 100, 1) for d in DOW_ORDER],
                     "cur": [round(int(dow_cur.get(d, 0)) / tot_cur * 100, 1) for d in DOW_ORDER],
                     "cur_name": L}
    tables["dow"] = [{"d": DOW_HE[d], "all": _i(dow_all.get(d, 0)), "cur": _i(dow_cur.get(d, 0))} for d in DOW_ORDER]
    labels["dow_aria"] = f"התפלגות ההשתלמויות לפי יום בשבוע, בכל המאגר ובקטלוג {L}"
    top_d = sorted(DOW_ORDER, key=lambda d: (-int(dow_all.get(d, 0)), DOW_ORDER.index(d)))[0]
    fri = int(dow_all.get(4, 0))
    sat = int(dow_all.get(5, 0))
    labels["dow_lede"] = (f"יום {DOW_HE[top_d]} מוביל עם {_pct(int(dow_all.get(top_d, 0)) / tot_all * 100)} מההשתלמויות במאגר; "
                          f"ביום שישי {_pct(fri / tot_all * 100)}.")
    if sat == 0 and tot_all >= 50:
        insights.append({"id": "weekday", "text_he": (
            f"אף אחת מ-{tot_all:,} ההשתלמויות במאגר לא נקבעה ליום שבת, ורק {_pct(fri / tot_all * 100)} ליום שישי; "
            f"היום העמוס ביותר הוא יום {DOW_HE[top_d]}.")})

    # ---------- region mix per year
    regs = [r for r in REGION_ORDER + ["לא צוין"] if (df["region"] == r).any()]
    rc = df.groupby(["year", "region"]).size()
    charts["region"] = {"years": ylabels, "regions": regs,
                        "share": {r: [round(int(rc.get((y, r), 0)) / n_courses[i] * 100, 1) for i, y in enumerate(years)] for r in regs},
                        "n": {r: [int(rc.get((y, r), 0)) for y in years] for r in regs}}
    tables["region"] = [{"r": r, "v": [_i(rc.get((y, r), 0)) for y in years]} for r in regs]
    labels["region_aria"] = f"חלוקת ההשתלמויות לפי אזור בכל שנת השתלמויות, {ylabels[0]} עד {L}"
    lead_r = sorted(regs, key=lambda r: (-int(rc.get((latest, r), 0)), regs.index(r)))[0]
    lead_share = int(rc.get((latest, lead_r), 0)) / n_courses[li] * 100
    labels["region_lede"] = (f"האזור המוביל ב-{L}: {lead_r}, עם {_pct(lead_share)} מההשתלמויות. "
                             "אזורים מפורטים בקבצים הישנים (יישוב או חבל ארץ) קובצו לאזורים הראשיים.")
    if lead_share >= 30:
        first_share = int(rc.get((years[0], lead_r), 0)) / n_courses[0] * 100
        tail = (f", לעומת {_pct(first_share)} ב-{ylabels[0]}" if len(years) >= 2 else "")
        insights.append({"id": "region", "text_he": (
            f"מוקד ההשתלמויות הוא {lead_r}: {_pct(lead_share)} מהקטלוג של {L} "
            f"({int(rc.get((latest, lead_r), 0)):,} השתלמויות){tail}.")})

    # ---------- course type per year
    tdf = df[df["ctype"] != "לא צוין"]
    type_years = [y for y in years if (tdf["year"] == y).any()]
    if type_years and tdf["ctype"].nunique() >= 2:
        flags["types"] = True
        tc_all = tdf["ctype"].value_counts()
        ranked = sorted(tc_all.index, key=lambda t: (-int(tc_all[t]), t))
        top_t = ranked[:TOP_TYPES]
        tdf = tdf.assign(t=tdf["ctype"].where(tdf["ctype"].isin(top_t), "אחר"))
        tlist = top_t + (["אחר"] if (tdf["t"] == "אחר").any() else [])
        tc = tdf.groupby(["year", "t"]).size()
        ty_tot = tdf.groupby("year").size()
        charts["types"] = {"years": [_year_label(y) for y in type_years], "types": tlist,
                           "share": {t: [round(int(tc.get((y, t), 0)) / int(ty_tot[y]) * 100, 1) for y in type_years] for t in tlist},
                           "n": {t: [int(tc.get((y, t), 0)) for y in type_years] for t in tlist}}
        tables["types"] = [{"t": t, "v": [_i(tc.get((y, t), 0)) for y in type_years]} for t in tlist]
        labels["types_years"] = [_year_label(y) for y in type_years]
        labels["types_aria"] = f"חלוקת ההשתלמויות לפי אופי ההשתלמות בכל שנה, {_year_label(type_years[0])} עד {_year_label(type_years[-1])}"
        missing = [ylabels[i] for i, y in enumerate(years) if y not in type_years]
        lt = type_years[-1]
        lead_t = sorted(tlist, key=lambda t: (-int(tc.get((lt, t), 0)), tlist.index(t)))[0]
        lead_t_share = int(tc.get((lt, lead_t), 0)) / int(ty_tot[lt]) * 100
        walk = sum(int(tc.get((lt, t), 0)) for t in tlist if t.startswith("סיור")) / int(ty_tot[lt]) * 100
        labels["types_lede"] = (f"ב-{_year_label(lt)} הסוג הנפוץ הוא {lead_t} ({_pct(lead_t_share)}); "
                                f"סיורים מכל הסוגים הם {_pct(walk)} מהקטלוג."
                                + (f" בקובץ {', '.join(missing)} אין שדה אופי ההשתלמות, ולכן הוא לא מוצג." if missing else ""))
        lecture = int(tc.get((lt, "יום עיון"), 0)) / int(ty_tot[lt]) * 100
        if walk >= 50:
            insights.append({"id": "types", "text_he": (
                f"רוב ההשתלמויות הן סיורי שטח: {_pct(walk)} מהקטלוג של {_year_label(lt)} הם סיורים "
                f"(עירוני, רגלי או רכוב), ו-{_pct(lecture)} ימי עיון.")})
    else:
        flags["types"] = False

    # ---------- price distribution per year
    pr = df.dropna(subset=["price"])
    pr = pr[pr["price"] > 0]
    box, ptab, med, mean = [], [], [], []
    for y in years:
        s = pr[pr["year"] == y]["price"]
        if len(s) == 0:
            box.append([0, 0, 0, 0, 0]); med.append(0); mean.append(0)
            ptab.append({"year": _year_label(y), "min": "", "q1": "", "med": "", "q3": "", "max": "", "mean": ""})
            continue
        q = [float(s.min()), float(s.quantile(0.25)), float(s.median()), float(s.quantile(0.75)), float(s.max())]
        box.append([round(v, 1) for v in q]); med.append(round(q[2], 1)); mean.append(round(float(s.mean()), 1))
        ptab.append({"year": _year_label(y), "min": _i(q[0]), "q1": _i(q[1]), "med": _i(q[2]),
                     "q3": _i(q[3]), "max": _i(q[4]), "mean": f"{s.mean():,.1f}"})
    charts["price"] = {"years": ylabels, "box": box, "mean": mean}
    tables["price"] = ptab
    labels["price_aria"] = f"התפלגות מחיר ההשתלמות בכל שנה (מינימום, רבעונים, חציון ומקסימום), {ylabels[0]} עד {L}"
    labels["price_lede"] = (f"המחיר החציוני ב-{L}: {_i(med[li])} ₪, הממוצע {mean[li]:,.1f} ₪, "
                            f"והטווח {_i(box[li][0])} עד {_i(box[li][4])} ₪ להשתלמות.")
    if len(years) >= 2 and mean[0] > 0:
        chm = (mean[li] - mean[0]) / mean[0] * 100
        if abs(chm) >= TREND_PCT:
            insights.append({"id": "price", "text_he": (
                f"מחיר ההשתלמות הממוצע {'עלה' if chm > 0 else 'ירד'} מ-{mean[0]:,.1f} ₪ ב-{ylabels[0]} "
                f"ל-{mean[li]:,.1f} ₪ ב-{L} ({_signed(chm)}); החציון: {_i(med[0])} ₪ לעומת {_i(med[li])} ₪.")})

    # price bands latest year + by type (latest)
    pc = pr[pr["year"] == latest]
    bands = []
    for lo, hi, name in PRICE_BANDS:
        m = (pc["price"] >= lo) & (pc["price"] < hi) if hi is not None else (pc["price"] >= lo)
        bands.append({"name": name, "n": int(m.sum())})
    while bands and bands[-1]["n"] == 0:
        bands.pop()
    tables["bands"] = [{"name": b["name"], "n": _i(b["n"]), "share": _pct(b["n"] / max(len(pc), 1) * 100)} for b in bands]
    charts["bands"] = {"x": [b["name"] for b in bands], "n": [b["n"] for b in bands]}
    labels["bands_aria"] = f"מספר ההשתלמויות לפי טווח מחיר בקטלוג {L}"
    tp = pc[pc["ctype"] != "לא צוין"].groupby("ctype")["price"].agg(["mean", "median", "size"])
    tp = tp[tp["size"] >= 5]
    flags["ptype"] = len(tp) >= 2
    if flags["ptype"]:
        order = sorted(tp.index, key=lambda t: (-float(tp.loc[t, "mean"]), t))
        charts["ptype"] = {"x": order, "mean": [round(float(tp.loc[t, "mean"]), 1) for t in order],
                           "n": [int(tp.loc[t, "size"]) for t in order]}
        tables["ptype"] = [{"t": t, "mean": f"{tp.loc[t, 'mean']:,.1f}", "med": _i(tp.loc[t, "median"]), "n": _i(tp.loc[t, "size"])} for t in order]
        labels["ptype_aria"] = f"מחיר ממוצע להשתלמות לפי אופי ההשתלמות, קטלוג {L}"
        hi_t, lo_t = order[0], order[-1]
        labels["ptype_lede"] = (f"{hi_t} הוא הסוג היקר ביותר ({tp.loc[hi_t, 'mean']:,.1f} ₪ בממוצע) "
                                f"ו{lo_t} הזול ביותר ({tp.loc[lo_t, 'mean']:,.1f} ₪). סוגים עם חמש השתלמויות לפחות.")
        if tp.loc[lo_t, "mean"] > 0 and tp.loc[hi_t, "mean"] / tp.loc[lo_t, "mean"] >= 1.15:
            insights.append({"id": "ptype", "text_he": (
                f"ב-{L} {hi_t} עולה בממוצע {tp.loc[hi_t, 'mean']:,.1f} ₪, "
                f"{_pct((tp.loc[hi_t, 'mean'] / tp.loc[lo_t, 'mean'] - 1) * 100, 0)} יותר מ{lo_t} ({tp.loc[lo_t, 'mean']:,.1f} ₪).")})

    # ---------- organizers (latest)
    oc = cur.groupby("org").size()
    oyears = df.groupby("org")["year"].nunique()
    orank = sorted(oc.index, key=lambda o: (-int(oc[o]), o))
    top_o = orank[:TOP_ORGS]
    charts["orgs"] = {"names": top_o, "n": [int(oc[o]) for o in top_o], "years": [int(oyears[o]) for o in top_o]}
    tables["orgs"] = [{"name": o, "n": _i(oc[o]), "years": _i(oyears[o])} for o in top_o]
    labels["orgs_aria"] = f"המארגנים עם מספר ההשתלמויות הגבוה ביותר בקטלוג {L}"
    top3 = sum(int(oc[o]) for o in orank[:3]) / n_courses[li] * 100
    labels["orgs_lede"] = (f"{len(orank):,} מארגנים בקטלוג {L}; " +
                           (f"{len(top_o):,} המובילים מוצגים. " if len(orank) > len(top_o) else "") +
                           f"שלושת הגדולים מחזיקים {_pct(top3)} מההשתלמויות. "
                           "שמות מארגנים שנכתבו באיות שונה אוחדו.")
    mx = int(oc[orank[0]])
    at_max = [o for o in orank if int(oc[o]) == mx]
    if len(orank) >= 10 and top3 < 25:
        if len(at_max) == 1:
            lead = f"המארגן הגדול ב-{L}, {at_max[0]}, מציע {mx:,} השתלמויות בלבד"
        elif len(at_max) == 2:
            lead = f"הגדולים ב-{L}, {at_max[0]} ו{at_max[1]}, מציעים {mx:,} השתלמויות כל אחד"
        else:
            lead = f"{len(at_max):,} המארגנים הגדולים ב-{L} מציעים {mx:,} השתלמויות כל אחד"
        insights.append({"id": "orgs", "text_he": (
            f"ההיצע מפוזר בין {len(orank):,} מארגנים: {lead}, ושלושת הגדולים יחד מחזיקים {_pct(top3)} מהקטלוג.")})
    steady = sorted([o for o in oyears.index if int(oyears[o]) == len(years)])
    labels["orgs_steady"] = (f"{len(steady):,} מארגנים הציעו השתלמויות בכל {len(years):,} השנים במאגר." if len(years) >= 3 and steady else "")

    # ---------- languages per year
    langs = [l for l in LANG_ORDER if l != "עברית" and (df["lang"] == l).any()]
    langs += sorted(l for l in df["lang"].unique() if l not in LANG_ORDER)
    lc = df.groupby(["year", "lang"]).size()
    flags["langs"] = bool(langs)
    charts["langs"] = {"years": ylabels, "langs": langs, "n": {l: [int(lc.get((y, l), 0)) for y in years] for l in langs},
                       "share": [round((n_courses[i] - int(lc.get((y, "עברית"), 0))) / n_courses[i] * 100, 1) for i, y in enumerate(years)]}
    tables["langs"] = [{"year": ylabels[i], "v": [_i(lc.get((y, l), 0)) for l in langs],
                        "share": _pct((n_courses[i] - int(lc.get((y, "עברית"), 0))) / n_courses[i] * 100)} for i, y in enumerate(years)]
    labels["langs_aria"] = f"מספר ההשתלמויות בשפות שאינן עברית בכל שנה, {ylabels[0]} עד {L}"
    non_he = n_courses[li] - int(lc.get((latest, "עברית"), 0))
    non_he_share = non_he / n_courses[li] * 100
    eng = int(lc.get((latest, "אנגלית"), 0))
    labels["langs_lede"] = (f"ב-{L} {non_he:,} השתלמויות ({_pct(non_he_share)}) בשפה שאינה עברית, "
                            f"מהן {eng:,} באנגלית.")
    if non_he and non_he_share < 15:
        insights.append({"id": "langs", "text_he": (
            f"השתלמויות בשפות זרות נדירות: רק {non_he:,} מתוך {n_courses[li]:,} השתלמויות ב-{L} "
            f"({_pct(non_he_share)}) אינן בעברית, {eng:,} מהן באנגלית.")})

    # ---------- instructors (all years)
    ins = df[["year", "Instructor"]].copy()
    ins["p"] = ins["Instructor"].map(lambda v: [TITLES.sub("", _clean(x)).strip() for x in re.split(r"[,;/]", str(v))])
    ins = ins.explode("p")
    ins = ins[ins["p"].str.len() >= 3]
    ic = ins.groupby("p").size()
    iy = ins.groupby("p")["year"].nunique()
    irank = sorted(ic.index, key=lambda p: (-int(ic[p]), p))[:TOP_INSTR]
    flags["instr"] = len(irank) >= 5
    charts["instr"] = {"names": irank, "n": [int(ic[p]) for p in irank], "years": [int(iy[p]) for p in irank]}
    tables["instr"] = [{"name": p, "n": _i(ic[p]), "years": _i(iy[p])} for p in irank]
    labels["instr_aria"] = f"המרצים והמדריכים שהעבירו הכי הרבה השתלמויות, {ylabels[0]} עד {L}"
    n_instr = int(ic.size)
    if irank:
        labels["instr_lede"] = (f"{n_instr:,} מרצים ומדריכים שונים מופיעים במאגר. {irank[0]} מוביל עם {int(ic[irank[0]]):,} השתלמויות "
                                f"ב-{int(iy[irank[0]]):,} שנים. השתלמות עם כמה מרצים נספרת לכל אחד מהם; תארים אקדמיים הוסרו לצורך האיחוד.")
    else:
        labels["instr_lede"] = ""

    # ---------- institutions (licensing course)
    inst = frames["institutions"].fillna("").copy()
    inst_rows = []
    for r in inst.itertuples(index=False):
        name = _clean(getattr(r, "institution"))
        if not name:
            continue
        inst_rows.append({"name": name, "city": _clean(getattr(r, "city")), "addr": _clean(getattr(r, "address")),
                          "remarks": _clean(getattr(r, "remarks"))})
    inst_rows.sort(key=lambda r: (r["city"], r["name"], r["addr"], r["remarks"]))
    tables["inst"] = inst_rows
    flags["inst"] = bool(inst_rows)
    labels["inst_lede"] = (f"{len(inst_rows):,} מוסדות מופיעים ברשימת מוסדות הלימוד במאגר, "
                           f"{sum(1 for r in inst_rows if 'אנגלית' in r['remarks']):,} מהם מציינים קורס גם באנגלית."
                           if inst_rows else "")

    # ---------- KPIs
    total = int(len(df))
    kpis, order = {}, []
    tone = "brand"
    if len(years) >= 2 and full[li]:
        ch = (n_courses[li] - n_courses[li - 1]) / max(n_courses[li - 1], 1) * 100
        tone = "ok" if ch >= TREND_PCT else "warn" if ch <= -TREND_PCT else "brand"
    elif not full[li]:
        tone = "warn"
    kpis["latest"] = {"value": n_courses[li], "display": f"{n_courses[li]:,}", "tone": tone}
    labels["kpi_latest"] = f"השתלמויות בקטלוג {L}" + ("" if full[li] else " (חלקי)")
    kpis["total"] = {"value": total, "display": f"{total:,}", "tone": "brand"}
    labels["kpi_total"] = f"השתלמויות במאגר, {len(years):,} שנים"
    kpis["orgs"] = {"value": n_orgs[li], "display": f"{n_orgs[li]:,}", "tone": "brand"}
    labels["kpi_orgs"] = f"מארגנים ב-{L}"
    kpis["price"] = {"value": med[li], "display": _i(med[li]), "tone": "info"}
    labels["kpi_price"] = f"מחיר חציוני להשתלמות ב-{L} (₪)"
    kpis["region"] = {"value": lead_share, "display": _pct(lead_share), "tone": "brand"}
    labels["kpi_region"] = f"שיעור ההשתלמויות ב{'אזור ' if lead_r not in ('ירושלים',) else ''}{lead_r}, {L}"
    kpis["span"] = {"value": len(years), "display": f"{years[0]}–{latest + 1}", "tone": "brand"}
    labels["kpi_span"] = "שנות ההשתלמויות במאגר"
    order = ["latest", "total", "orgs", "price", "region", "span"]

    # ---------- summary + lede
    summary = (f"קטלוג השתלמויות למורי דרך לחידוש רישיון: איתור השתלמות לפי נושא, מארגן, אזור ומחיר. "
               f"{n_courses[li]:,} השתלמויות ב-{L}.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור השתלמויות למורי דרך לפי נושא, מארגן ואזור. {n_courses[li]:,} השתלמויות ב-{L}."
    labels["lede"] = (f"מורי דרך מורשים חייבים לעבור שתי השתלמויות בכל שנתיים כדי לחדש את רישיון מורה הדרך. "
                      f"המאגר של משרד התיירות מרכז את קטלוג ההשתלמויות של {len(years):,} שנים, {ylabels[0]} עד {L}: "
                      f"{total:,} השתלמויות מ-{df['org_key'].nunique():,} מארגנים, עם תאריך, מרצה, אזור, שפה ומחיר.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["מורי דרך", "השתלמויות", "רישיון מורה דרך", "תיירות", "סיורים", "משרד התיירות"],
            "related_ids": ["aa55c19d-afdd-4ff4-8b1e-1cb0d59d2b26", "a416609e-f68a-4fea-b278-657f92bfbe73",
                            "c5b1b556-09c4-4d10-8efb-ba1bc0cafe0d"],
            "temporal_coverage": f"{years[0]}/{latest + 1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": order,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
        "years": ylabels,
        "latest": L,
    }
