"""החלטות ועדת כופר — משרד הכלכלה והתעשייה.

One row per published decision of the Ministry of Economy's ransom
(settlement-fine) committee: a title that carries the case number
(`tviaa_number`), the decision date (`decision_date`, dd/mm/yyyy), the case
file id (`tik`, the case number plus a trailing letter; it is also the PDF
file name) and an HTML anchor to the decision document (`pub_link`).

The page is a lookup first (people search a case number), then the honest
aggregates the four columns carry: decisions per month/year, a month x year
heatmap, the weekday they are signed on, the case-opening year read from the
case number (two numbering schemes: an older 11-digit id whose 5th-6th
digits are the year, and a newer "NNN-YYYY"), the approximate years from case
opening to decision, and the switch between the numbering schemes.

Growth: rows are appended as decisions are published. The monthly series is
zero-filled and coarsens to quarters past MONTHLY_MAX months; the heatmap and
the yearly tables grow by one row a year; case-year axes are capped to the
last CASE_YEARS_MAX years plus an "earlier" bucket. A case id that fits
neither scheme (or decodes to a year after its decision) counts as
"unidentified" and the page says so.
"""
import re

import pandas as pd

MONTHLY_MAX = 84          # months on the monthly chart before coarsening to quarters
CASE_YEARS_MAX = 6        # case-opening years shown before an "earlier" bucket
LATEST_N = 12             # latest decisions listed with a document link
TREND_THRESHOLD = 0.15    # ±15% for a 12-month change to count as a change
GAP_MIN_DAYS = 45         # longest pause worth an insight
WEEKDAY_LEAD_MIN = 0.25   # leading weekday holds at least this share

HE_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
HE_MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                   "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
# Ordered Sunday..Saturday; keys are pandas dayofweek (Mon=0).
WEEKDAYS = [(6, "ראשון"), (0, "שני"), (1, "שלישי"), (2, "רביעי"),
            (3, "חמישי"), (4, "שישי"), (5, "שבת")]
FMT_OLD = "מספור ישן (11 ספרות)"
FMT_NEW = "מספור חדש (מספר-שנה)"
FMT_OTHER = "מבנה אחר"

NEW_RE = re.compile(r"^(\d{1,5})-(\d{4})$")
OLD_RE = re.compile(r"^\d{11}$")
TITLE_NUM_RE = re.compile(r"(\d[\d-]*\d)\s*$")
HREF_RE = re.compile(r'href="(https://www\.gov\.il/[A-Za-z0-9/._-]+\.pdf)"')


def n(v):
    return f"{int(v):,}"


def in_decisions(k):
    return "בהחלטה אחת" if k == 1 else f"ב-{n(k)} החלטות"


def pct(x):
    return f"{x * 100:.0f}%"


def ddate(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def month_label(p):
    return f"{HE_MONTHS[p.month - 1]} {p.year}"


def case_id(tik):
    s = tik.strip()
    s = re.sub(r"[A-Za-zא-ת]+$", "", s)
    return s


def parse_case(cid, dec_year):
    """-> (format, case_year or None)."""
    m = NEW_RE.match(cid)
    if m:
        fmt, year = FMT_NEW, int(m.group(2))
    elif OLD_RE.match(cid):
        fmt, year = FMT_OLD, 2000 + int(cid[4:6])
    else:
        return FMT_OTHER, None
    if year < 2000 or year > dec_year:
        return fmt, None
    return fmt, year


def compute(frames):
    df = frames["main"].copy()
    total_rows = len(df)
    df["dt"] = pd.to_datetime(df["decision_date"].str.strip(), format="%d/%m/%Y", errors="coerce")
    bad_dates = int(df["dt"].isna().sum())
    df = df[df["dt"].notna()].copy()
    df["cid"] = df["tik"].map(case_id)
    df["title_num"] = df["tviaa_number"].map(
        lambda t: (TITLE_NUM_RE.search(t.strip()).group(1) if TITLE_NUM_RE.search(t.strip()) else ""))
    df["year"] = df["dt"].dt.year
    parsed = [parse_case(c, y) for c, y in zip(df["cid"], df["year"])]
    df["fmt"] = [p[0] for p in parsed]
    df["case_year"] = [p[1] for p in parsed]
    df["url"] = df["pub_link"].map(lambda s: (HREF_RE.search(s).group(1) if HREF_RE.search(s) else ""))
    df = df.sort_values(["dt", "cid", "tviaa_number", "pub_link"], ascending=[False, False, False, False],
                        kind="mergesort").reset_index(drop=True)

    total = len(df)
    first, last = df["dt"].min(), df["dt"].max()
    first_y, last_y = int(first.year), int(last.year)
    last_p = last.to_period("M")
    first_p = first.to_period("M")

    # ---- monthly series (zero-filled) ----
    per = df["dt"].dt.to_period("M")
    months = pd.period_range(first_p, last_p, freq="M")
    mcount = per.value_counts()
    mvals = [int(mcount.get(p, 0)) for p in months]
    cum, run = [], 0
    for v in mvals:
        run += v
        cum.append(run)
    if len(months) > MONTHLY_MAX:
        q = df["dt"].dt.to_period("Q")
        quarters = pd.period_range(first.to_period("Q"), last.to_period("Q"), freq="Q")
        qc = q.value_counts()
        mx = [f"{p.year} Q{p.quarter}" for p in quarters]
        my = [int(qc.get(p, 0)) for p in quarters]
        gran = "רבעון"
    else:
        mx = [f"{p.year}-{p.month:02d}" for p in months]
        my = mvals
        gran = "חודש"
    cum_x, cum_y, run = [], [], 0
    for x, v in zip(mx, my):
        run += v
        cum_x.append(x)
        cum_y.append(run)

    # ---- yearly ----
    years = list(range(first_y, last_y + 1))
    ycount = df["year"].value_counts()
    yrows = []
    for y in years:
        m_from = first.month if y == first_y else 1
        m_to = last.month if y == last_y else 12
        active = len({p for p in per[df["year"] == y]})
        span_m = m_to - m_from + 1
        c = int(ycount.get(y, 0))
        yrows.append({
            "year": str(y), "count": c, "months": span_m, "active": active,
            "avg": f"{c / span_m:.1f}", "partial": span_m < 12,
        })
    yearly = {"x": [r["year"] for r in yrows], "y": [r["count"] for r in yrows],
              "partial": [r["partial"] for r in yrows], "avg": [float(r["avg"]) for r in yrows]}

    # ---- heatmap month x year ----
    heat_cells, heat_rows = [], []
    hm = df.groupby([df["year"], df["dt"].dt.month]).size()
    heat_max = 0
    for yi, y in enumerate(years):
        row = []
        for m in range(1, 13):
            in_range = not ((y == first_y and m < first.month) or (y == last_y and m > last.month))
            v = int(hm.get((y, m), 0))
            if in_range:
                heat_cells.append([m - 1, yi, v])
                heat_max = max(heat_max, v)
                row.append(n(v))
            else:
                row.append("")
        heat_rows.append({"year": str(y), "cells": row})

    # ---- weekday ----
    wd = df["dt"].dt.dayofweek.value_counts()
    wd_names = [name for _, name in WEEKDAYS]
    wd_vals = [int(wd.get(k, 0)) for k, _ in WEEKDAYS]
    wd_rows = [{"name": nm, "count": v, "share": pct(v / total)} for nm, v in zip(wd_names, wd_vals)]

    # ---- case year x decision year ----
    known = df[df["case_year"].notna()].copy()
    known["case_year"] = known["case_year"].astype(int)
    unknown_cases = total - len(known)
    cy_all = sorted(known["case_year"].unique().tolist())
    if len(cy_all) > CASE_YEARS_MAX:
        cut = cy_all[-CASE_YEARS_MAX]
        cy_keep = [y for y in cy_all if y >= cut]
        known["cy_lab"] = known["case_year"].map(lambda y: str(y) if y >= cut else f"לפני {cut}")
        cy_labels = [f"לפני {cut}"] + [str(y) for y in cy_keep]
    else:
        known["cy_lab"] = known["case_year"].astype(str)
        cy_labels = [str(y) for y in cy_all]
    ct = known.groupby(["cy_lab", "year"]).size()
    cross_series = []
    for lab in cy_labels:
        cross_series.append({"name": lab, "data": [int(ct.get((lab, y), 0)) for y in years]})
    cross_rows = []
    for y in years:
        cells = [n(ct.get((lab, y), 0)) for lab in cy_labels]
        unk = int(((df["year"] == y) & df["case_year"].isna()).sum())
        cross_rows.append({"year": str(y), "cells": cells, "unknown": n(unk)})
    case_year_counts = known["cy_lab"].value_counts()
    case_bar = {"x": cy_labels, "y": [int(case_year_counts.get(l, 0)) for l in cy_labels]}

    # ---- lag (decision year - case year) ----
    known["lag"] = known["year"] - known["case_year"]
    lag_labels = ["באותה שנה", "שנה אחת", "שנתיים", "שלוש שנים ומעלה"]
    lag_bins = [int((known["lag"] == 0).sum()), int((known["lag"] == 1).sum()),
                int((known["lag"] == 2).sum()), int((known["lag"] >= 3).sum())]
    lag_rows = [{"name": l, "count": v, "share": pct(v / len(known)) if len(known) else "0%"}
                for l, v in zip(lag_labels, lag_bins)]
    lag_median = float(known["lag"].median()) if len(known) else None

    # ---- numbering format by decision year ----
    fmts = [f for f in [FMT_OLD, FMT_NEW, FMT_OTHER] if (df["fmt"] == f).any()]
    fc = df.groupby(["fmt", "year"]).size()
    fmt_series = [{"name": f, "data": [int(fc.get((f, y), 0)) for y in years]} for f in fmts]
    fmt_rows = [{"year": str(y), "cells": [n(fc.get((f, y), 0)) for f in fmts]} for y in years]

    # ---- latest decisions ----
    latest = []
    for r in df.head(LATEST_N).itertuples():
        latest.append({"date": ddate(r.dt), "case": r.cid, "url": r.url})

    # ---- mismatches between title number and file id ----
    mism = df[(df["title_num"] != "") & (df["title_num"] != df["cid"])]
    n_mism = len(mism)

    # ---- 12-month windows ----
    win_cur = [p for p in months if p > last_p - 12]
    win_prev = [p for p in months if last_p - 24 < p <= last_p - 12]
    cur12 = sum(int(mcount.get(p, 0)) for p in win_cur)
    prev12 = sum(int(mcount.get(p, 0)) for p in win_prev)
    have_24 = len(months) >= 24

    # ---- gaps ----
    dates = sorted(df["dt"].unique())
    gap_days, gap_from, gap_to = 0, None, None
    for a, b in zip(dates[:-1], dates[1:]):
        g = int((pd.Timestamp(b) - pd.Timestamp(a)).days)
        if g > gap_days:
            gap_days, gap_from, gap_to = g, pd.Timestamp(a), pd.Timestamp(b)

    # ================= insights =================
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    # trend over the last 12 months
    t = None
    if have_24 and prev12 > 0:
        ch = (cur12 - prev12) / prev12
        span = f"{month_label(last_p - 11)} עד {month_label(last_p)}"
        if ch >= TREND_THRESHOLD:
            t = (f"קצב ההחלטות עלה: {n(cur12)} החלטות ב-12 החודשים {span}, לעומת {n(prev12)} "
                 f"ב-12 החודשים שקדמו להם (עלייה של {pct(ch)}).")
        elif ch <= -TREND_THRESHOLD:
            t = (f"קצב ההחלטות ירד: {n(cur12)} החלטות ב-12 החודשים {span}, לעומת {n(prev12)} "
                 f"ב-12 החודשים שקדמו להם (ירידה של {pct(-ch)}).")
        else:
            t = (f"קצב ההחלטות יציב: {n(cur12)} החלטות ב-12 החודשים {span}, לעומת {n(prev12)} "
                 f"ב-12 החודשים שקדמו להם.")
    add("trend", t)

    # partial latest year vs the same months last year
    t = None
    if yrows[-1]["partial"] and len(yrows) >= 2:
        m_to = last.month
        cur_ytd = int(((df["year"] == last_y) & (df["dt"].dt.month <= m_to)).sum())
        prev_ytd = int(((df["year"] == last_y - 1) & (df["dt"].dt.month <= m_to)).sum())
        prev_starts_jan = not (first_y == last_y - 1 and first.month > 1)
        if prev_ytd > 0 and prev_starts_jan:
            t = (f"שנת {last_y} חלקית במאגר (עד {month_label(last_p)}): פורסמו בה {n(cur_ytd)} החלטות, "
                 f"לעומת {n(prev_ytd)} בחודשים המקבילים של {last_y - 1}.")
    add("ytd", t)

    # busiest month
    if mvals:
        mxv = max(mvals)
        tops = [p for p, v in zip(months, mvals) if v == mxv]
        if len(tops) == 1 and mxv >= 3:
            add("peak", f"החודש העמוס ביותר היה {month_label(tops[0])}, עם {n(mxv)} החלטות "
                        f"(ממוצע של {total / len(months):.1f} החלטות בחודש לאורך כל התקופה).")

    # pause
    if gap_days >= GAP_MIN_DAYS:
        add("gap", f"ההפסקה הארוכה ביותר בין שתי החלטות נמשכה {n(gap_days)} ימים, "
                   f"מ-{ddate(gap_from)} ועד {ddate(gap_to)}.")

    # backlog / lag
    if len(known) >= 10 and lag_median is not None:
        later = sum(lag_bins[1:])
        old_y = int(known.loc[known["year"] == last_y, "case_year"].min()) if (known["year"] == last_y).any() else None
        t = (f"{pct(later / len(known))} מההחלטות שמספר התיק שלהן מזוהה ניתנו בשנה שאחרי פתיחת התיק "
             f"או מאוחר יותר (לפי שנת התיק שבמספר).")
        if old_y is not None and old_y < last_y:
            t += f" התיק הוותיק ביותר שהוכרע ב-{last_y} נפתח ב-{old_y}."
        add("lag", t)

    # numbering switch
    if FMT_NEW in fmts and FMT_OLD in fmts:
        first_new = df.loc[df["fmt"] == FMT_NEW, "dt"].min()
        last_old = df.loc[df["fmt"] == FMT_OLD, "dt"].max()
        share_new_last = float(((df["year"] == last_y) & (df["fmt"] == FMT_NEW)).sum()) / max(1, int(ycount.get(last_y, 0)))
        add("format", f"מספרי התיקים עברו לשיטת מספור חדשה (מספר-שנה): ההחלטה הראשונה במספור החדש פורסמה ב-{ddate(first_new)}, "
                      f"והאחרונה במספור הישן ב-{ddate(last_old)}. ב-{last_y} {pct(share_new_last)} מההחלטות במספור החדש.")

    # weekday
    lead_i = max(range(len(wd_vals)), key=lambda i: (wd_vals[i], -i))
    if wd_vals[lead_i] / total >= WEEKDAY_LEAD_MIN and sorted(wd_vals)[-2] < wd_vals[lead_i]:
        weekend = wd_vals[5] + wd_vals[6]
        t = f"יום {wd_names[lead_i]} הוא היום הנפוץ ביותר לחתימת החלטות: {pct(wd_vals[lead_i] / total)} מההחלטות."
        if weekend:
            t += f" {n(weekend)} החלטות נושאות תאריך של שישי או שבת."
        add("weekday", t)

    # data quality
    if n_mism or unknown_cases:
        parts = []
        if n_mism:
            parts.append(f"{in_decisions(n_mism)} מספר התיק בכותרת שונה מהמספר בשם הקובץ")
        if unknown_cases:
            parts.append(f"{in_decisions(unknown_cases)} לא ניתן לזהות את שנת פתיחת התיק מתוך המספר, ו{'היא אינה נכללת' if unknown_cases == 1 else 'הן אינן נכללות'} בניתוח לפי שנת תיק")
        add("quality", "הערת איכות נתונים: " + "; ".join(parts) + ".")

    # ================= kpis =================
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "span": {"value": last_y - first_y + 1,
                 "display": f"{first_y}–{last_y}" if first_y != last_y else str(first_y), "tone": "brand"},
        "last": {"value": ddate(last), "display": f"{last.day:02d}.{last.month:02d}.{last.year}", "tone": "info"},
    }
    if have_24 and prev12 > 0:
        ch = (cur12 - prev12) / prev12
        tone = "ok" if ch >= TREND_THRESHOLD else ("warn" if ch <= -TREND_THRESHOLD else "brand")
    else:
        tone = "brand"
    kpis["last12"] = {"value": cur12, "display": n(cur12), "tone": tone}

    years_lbl = f"{first_y} עד {last_y}" if first_y != last_y else str(first_y)
    summary = (f"איתור החלטות ועדת הכופר של משרד הכלכלה והתעשייה לפי מספר תיק, עם קישור למסמך ההחלטה. "
               f"{n(total)} החלטות מ-{years_lbl}.")

    labels = {
        "lede": (f"המאגר מרכז {n(total)} החלטות של ועדת הכופר במשרד הכלכלה והתעשייה, שניתנו בין "
                 f"{ddate(first)} ל-{ddate(last)}. לכל החלטה רשומים מספר התיק, תאריך ההחלטה וקישור למסמך "
                 f"ההחלטה המלא. העמוד מציג את קצב ההחלטות לאורך זמן, את שנת פתיחת התיקים שהוכרעו ואת "
                 f"המעבר בין שיטות מספור התיקים."),
        "total_kpi": "החלטות במאגר",
        "span_kpi": "שנות ההחלטות במאגר",
        "last_kpi": "תאריך ההחלטה האחרונה",
        "last12_kpi": f"החלטות ב-12 החודשים האחרונים במאגר (עד {month_label(last_p)})",
        "latest_note": f"{n(len(latest))} ההחלטות האחרונות לפי תאריך ההחלטה. את כל ההחלטות אפשר לחפש לפי מספר תיק בטבלה שבתחתית העמוד.",
        "latest_caption": "ההחלטות האחרונות ומסמכיהן",
        "monthly_note": (f"מספר ההחלטות בכל {gran}, והמצטבר לאורך זמן. "
                         f"בממוצע {total / len(months):.1f} החלטות בחודש."),
        "monthly_aria": (f"תרשים עמודות של מספר ההחלטות בכל {gran} מ-{month_label(first_p)} עד "
                         f"{month_label(last_p)}, עם קו מצטבר שמגיע ל-{n(total)} החלטות"),
        "yearly_note": ("מספר ההחלטות בכל שנה. שנה חלקית (שבה המאגר מכסה פחות מ-12 חודשים) מסומנת בצבע אחר; "
                        "להשוואה הוגנת מוצג גם הממוצע החודשי."),
        "yearly_aria": (f"תרשים עמודות של מספר ההחלטות לפי שנה, {years_lbl}; השנה העמוסה ביותר "
                        f"{yrows[max(range(len(yrows)), key=lambda i: (yrows[i]['count'], -i))]['year']}"),
        "yearly_caption": "החלטות לפי שנה",
        "heat_note": "כל משבצת היא חודש: ככל שהצבע כהה יותר, פורסמו בו יותר החלטות. משבצות ריקות הן חודשים שמחוץ לתקופת המאגר.",
        "heat_aria": f"מפת חום של מספר ההחלטות לפי חודש ושנה, {years_lbl}, עד {n(heat_max)} החלטות בחודש",
        "heat_caption": "החלטות לפי חודש ושנה",
        "weekday_note": "יום השבוע של תאריך ההחלטה.",
        "weekday_aria": (f"תרשים עמודות של ההחלטות לפי יום בשבוע; היום הנפוץ ביותר הוא יום "
                         f"{wd_names[lead_i]} עם {n(wd_vals[lead_i])} החלטות"),
        "weekday_caption": "החלטות לפי יום בשבוע",
        "cross_note": (f"לכל שנת החלטה: באיזו שנה נפתחו התיקים שהוכרעו בה (שנת התיק נקראת מתוך מספר התיק). "
                       f"{n(len(known))} מתוך {n(total)} ההחלטות כוללות שנת תיק מזוהה."),
        "cross_aria": (f"תרשים עמודות מוערמות של ההחלטות בכל שנה לפי שנת פתיחת התיק, "
                       f"עבור {n(len(known))} החלטות עם שנת תיק מזוהה"),
        "cross_caption": "החלטות לפי שנת החלטה ושנת פתיחת התיק",
        "lag_note": ("ההפרש בין שנת ההחלטה לשנת פתיחת התיק, לפי שנים קלנדריות בלבד (המאגר אינו כולל את תאריך "
                     "פתיחת התיק, ולכן זהו קירוב)."),
        "lag_aria": (f"תרשים עמודות של מספר השנים מפתיחת התיק ועד ההחלטה; "
                     f"{pct(lag_bins[0] / len(known)) if len(known) else '0%'} הוכרעו באותה שנה"),
        "lag_caption": "שנים מפתיחת התיק ועד ההחלטה",
        "format_note": "מספרי התיקים במאגר בשתי שיטות: מספר ישן בן 11 ספרות, ומספר חדש בתבנית מספר-שנה.",
        "format_aria": f"תרשים עמודות מוערמות של ההחלטות בכל שנה לפי שיטת מספור התיק, {years_lbl}",
        "format_caption": "החלטות לפי שנה ושיטת מספור",
        "unknown_col": "לא מזוהה",
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "suggested_tags": ["ועדת כופר", "אכיפה", "משרד הכלכלה", "החלטות ועדה", "רגולציה"],
        "related_ids": ["ed8ce28e-ae7f-4588-b3f9-59485960d521", "89fbf87e-6bc0-4e26-acc7-a288c31b12a1",
                        "12c7457c-a9f0-40f8-9ed6-b4689d3d3fa4", "dda8f0aa-8901-473d-a4d6-8b361aa51417"],
        "temporal_coverage": f"{first_y}/{last_y}",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "monthly": {"x": cum_x, "y": my, "cum": cum_y},
            "yearly": yearly,
            "heat": {"months": HE_MONTHS_SHORT, "years": [str(y) for y in years],
                     "cells": heat_cells, "max": heat_max},
            "weekday": {"x": wd_names, "y": wd_vals},
            "cross": {"years": [str(y) for y in years], "series": cross_series},
            "lag": {"x": lag_labels, "y": lag_bins},
            "format": {"years": [str(y) for y in years], "series": fmt_series},
        },
        "tables": {
            "yearly": yrows,
            "heat": {"months": HE_MONTHS, "rows": heat_rows},
            "weekday": wd_rows,
            "cross": {"cols": cy_labels, "rows": cross_rows, "has_unknown": unknown_cases > 0},
            "lag": lag_rows,
            "format": {"cols": fmts, "rows": fmt_rows},
        },
        "latest": latest,
        "flags": {"cross": len(known) >= 10, "format": len(fmts) >= 2, "bad_dates": bad_dates > 0},
        "labels": labels,
        "insights": insights,
        "meta": {"rows": total_rows, "bad_dates": bad_dates},
    }
