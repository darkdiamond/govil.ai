"""דרושים — Be'er Sheva municipality job ads.

One row per job advertisement (title, tender number, update date, last date
to apply, link). "Now" is the latest update date in the data, never the
wall clock; the latest calendar year is partial unless December is present.
Departments and role families are classified from the free-text title by an
ordered keyword table; anything unmatched is shown honestly as "לא מסווג".
"""
import html
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
LRI, PDI = "⁦", "⁩"
HEAT_YEARS = 12
MIX_TOP = 5
TOP_TITLES = 10
LATEST_ROWS = 12

UNIT_RULES = [
    ("רווחה וחברה", r'רווחה|עו"ס|סוציאל|שכונתי|נוער|מפ"ה|מוגנות'),
    ("איכות הסביבה", r'איכות הסביבה|סיירת הירוקה|וטרינר|בעלי חיים|השקיה|גינון'),
    ("חינוך", r'החינוך|קונסרבטוריון|ספרי|ספרן|גנ[יו]|בית.ספר|פסיכולוג|סייע|מצוינות|הטכנולוגי|ניצנים|תומכ|מרכז'),
    ("פיקוח, אכיפה וביטחון", r'פיקוח|פקח|אכיפה|סיירת|מוקד|ביטחון|מאבטח|קב"ט|סייר|מטווח|חירום|בטיחות'),
    ("הנדסה ותכנון", r'הנדסה|מהנדס|תנועה|רישוי|נגישות|מבנים|תכנון|אדריכל|בניה|בנייה|פרויקטים'),
    ("כספים, שכר ורכש", r'כספים|חשבות|חשבונות|גבייה|גביה|שכר|תקציב|הכנסות|ארנונה|כלכלה|רכש|התקשרויות|מכרזים|ביטוח|נכסים|כ"א|משאבי אנוש|הון האנושי|הוראה|גזבר'),
    ("מינהל כללי ושירות", r'מערכות מידע|חדשנות|לשכ|ראש העיר|מנכ"ל|דוברות|דובר|הסברה|קשרי חוץ|שיווק|שרות|שירות|משפטית|עורך/ת דין|אחזקה|תחזוקה|מזרקות|לוגיסטיקה|רכב|פניות הציבור|מבקר'),
]
UNCLASSIFIED = "לא מסווג"
ROLE_RULES = [
    ("ניהול ובכירים", r'^(מנהל|מנהלת|ראש|סגן|סגנית|סגן-ית|גזבר)(?!/ת חשבונות)'),
    ("רכזים", r'^רכז'),
    ("עובדים סוציאליים", r'^(עו"ס|עובד/ת סוציאלי|תומך/ת עו"ס)'),
    ("פיקוח, סיור וביטחון", r'^(מפקח|פקח|סייר|מאבטח|קב"ט|קבט|קצין)'),
    ("סיוע וליווי בחינוך", r'^(סייע|תומכ|מזכיר/ת בית|אחראי/ת תחזוקה)'),
    ("מדריכים", r'^מדריך'),
    ("שירות ומוקד", r'^(נציג|מוקדן|טלפן)'),
    ("הנדסה ומקצועות חופשיים", r'^(מהנדס|אדריכל|עורך/ת דין|עו"ד|רופא|חשב|כלכלן|פסיכולוג|מתכנן)'),
    ("פקידות, בדיקה ותפעול", r'^(פקיד|בודק|בוחן|מזכיר|מתאם|עובד|טכנאי|אחראי|תחשיבן|רפרנט|ממצה|ספרן|מרכז/ת)'),
]
OTHER_ROLE = "תפקידים אחרים"
SUBSTITUTE_RE = re.compile(r'מ"מ|מילוי מקום|מילויי מקום|על פי קריאה|על-פי קריאה|עפ"י קריאה')


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def norm_title(s):
    s = html.unescape(s).replace("״", '"').replace("‏", "").replace("‎", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s*[-–]\s*", " - ", s)
    return s


def core_title(s):
    s = re.sub(r'^(דרושים|לשנה"ל [^ ]+ דרושים|וועדת קבלה[ \d/\-–]*)\s*[-:]?\s*', "", s).strip()
    s = re.sub(r'^(מ"מ)\s+', "", s)
    s = re.sub(r"\s*-\s*(וועדת קבלה|הארכת משרה|תיקון)\s*$", "", s)
    return s


def classify(rules, text, default):
    for name, pat in rules:
        if re.search(pat, text):
            return name
    return default


def parse_dt(series):
    a = pd.to_datetime(series, errors="coerce", format="%d/%m/%Y %H:%M:%S")
    b = pd.to_datetime(series, errors="coerce", format="%Y-%m-%d %H:%M:%S")
    return a.fillna(b)


def _prepare(df):
    out = pd.DataFrame({
        "raw": df["שם מכרז"].map(norm_title),
        "num": df["מספר מכרז"].str.strip(),
        "upd": parse_dt(df["תאריך עדכון"]),
        "due": parse_dt(df["תאריך אחרון להגשה"]),
        "url": df["URL"].str.strip(),
    })
    out = out.dropna(subset=["upd"])
    out = out[out["raw"] != ""].copy()
    out["core"] = out["raw"].map(core_title)
    out["unit"] = out["core"].map(lambda t: classify(UNIT_RULES, t, UNCLASSIFIED))
    out["role"] = out["core"].map(lambda t: classify(ROLE_RULES, t, OTHER_ROLE))
    out["year"] = out["upd"].dt.year
    out["month"] = out["upd"].dt.month
    out["window"] = (out["due"].dt.normalize() - out["upd"].dt.normalize()).dt.days
    out.loc[out["window"] < 0, "window"] = float("nan")
    out["committee"] = out["raw"].str.contains("וועדת קבלה") | (out["num"] == "וועדת קבלה")
    out["substitute"] = out["raw"].map(lambda t: bool(SUBSTITUTE_RE.search(t)))
    return out.sort_values(["upd", "num", "raw", "url"], kind="mergesort").reset_index(drop=True)


def _table_rows(pairs):
    return [[a, n(b)] for a, b in pairs]


def compute(frames):
    d = _prepare(frames["main"])
    total = len(d)
    last = d["upd"].max()
    first = d["upd"].min()
    ly = int(last.year)
    months_in_last = int(d.loc[d["year"] == ly, "month"].max())
    partial = months_in_last < 12
    years = sorted(int(y) for y in d["year"].unique())
    full_years = [y for y in years if not (y == ly and partial)]
    ycount = d.groupby("year").size()

    def ylabel(y):
        return f"{y} (עד {MONTHS_HE[months_in_last - 1]})" if (y == ly and partial) else str(y)

    # ---- charts
    by_year = {"x": [ylabel(y) for y in years], "y": [int(ycount[y]) for y in years]}

    heat_years = years[-HEAT_YEARS:]
    cell = d.groupby(["year", "month"]).size()
    heat_cells = []
    for yi, y in enumerate(heat_years):
        for m in range(12):
            heat_cells.append([m, yi, int(cell.get((y, m + 1), 0))])
    heat = {"x": MONTHS_HE, "y": [str(y) for y in heat_years], "cells": heat_cells,
            "max": max([c[2] for c in heat_cells] + [1])}

    ucount = d["unit"].value_counts()
    unit_pairs = sorted(((k, int(v)) for k, v in ucount.items()),
                        key=lambda kv: (kv[0] == UNCLASSIFIED, -kv[1], kv[0]))
    units = {"names": [k for k, _ in unit_pairs], "values": [v for _, v in unit_pairs]}

    top_units = [k for k, _ in unit_pairs if k != UNCLASSIFIED][:MIX_TOP]
    mix_names = top_units + ["אחר"]
    d["unit_mix"] = d["unit"].where(d["unit"].isin(top_units), "אחר")
    mix = d.groupby(["year", "unit_mix"]).size()
    mix_series = [{"name": u, "data": [int(mix.get((y, u), 0)) for y in years]} for u in mix_names]
    mix_chart = {"x": [ylabel(y) for y in years], "series": mix_series}
    mix_rows = [[ylabel(y)] + [n(s["data"][i]) for s in mix_series] for i, y in enumerate(years)]

    w = d["window"].dropna().astype(int)
    buckets = [("עד שבוע", 0, 7), ("8 עד 14 ימים", 8, 14), ("15 עד 21 ימים", 15, 21),
               ("22 עד 28 ימים", 22, 28), ("29 ימים ומעלה", 29, None)]
    wb_names, wb_vals = [], []
    for name, lo, hi in buckets:
        m = w >= lo
        if hi is not None:
            m &= w <= hi
        wb_names.append(name)
        wb_vals.append(int(m.sum()))
    wmed = {"x": [], "med": [], "p75": []}
    wrows = []
    for y in years:
        s = d.loc[d["year"] == y, "window"].dropna()
        if s.empty:
            continue
        p50, p75 = float(s.quantile(0.5)), float(s.quantile(0.75))
        wmed["x"].append(ylabel(y))
        wmed["med"].append(round(p50, 1))
        wmed["p75"].append(round(p75, 1))
        wrows.append([ylabel(y), f"{p50:g}", f"{p75:g}"])
    wbuckets = {"names": wb_names, "values": wb_vals}

    rcount = d["role"].value_counts()
    role_pairs = sorted(((k, int(v)) for k, v in rcount.items()),
                        key=lambda kv: (kv[0] == OTHER_ROLE, -kv[1], kv[0]))
    roles = {"names": [k for k, _ in role_pairs], "values": [v for _, v in role_pairs]}

    tcount = d.groupby("core").agg(cnt=("core", "size"), y0=("year", "min"), y1=("year", "max")).reset_index()
    tcount = tcount.sort_values(["cnt", "core"], ascending=[False, True], kind="mergesort")
    top_t = tcount.head(TOP_TITLES)
    titles = {"names": top_t["core"].tolist(), "values": [int(v) for v in top_t["cnt"]]}
    title_rows = [[r.core, n(r.cnt), f"{int(r.y0)} עד {int(r.y1)}"] for r in top_t.itertuples()]

    wd_u = d["upd"].dt.weekday.map(lambda x: (x + 1) % 7)
    dd = d["due"].dropna()
    wd_d = dd.dt.weekday.map(lambda x: (x + 1) % 7)
    wd = {"x": DAYS_HE,
          "upd": [int((wd_u == i).sum()) for i in range(7)],
          "due": [int((wd_d == i).sum()) for i in range(7)]}
    wd_rows = [[DAYS_HE[i], n(wd["upd"][i]), n(wd["due"][i])] for i in range(7)]

    # ---- latest ads (link goes to the municipality's own ad page)
    lat = d.sort_values(["upd", "num", "raw", "url"], ascending=[False, True, True, True],
                        kind="mergesort").head(LATEST_ROWS)
    latest = []
    for r in lat.itertuples():
        url = r.url if re.match(r"^https?://", r.url) else ""
        latest.append({"title": r.raw, "upd": r.upd.strftime("%d.%m.%Y"),
                       "due": "" if pd.isna(r.due) else r.due.strftime("%d.%m.%Y"), "url": url})

    open_now = int((d["due"].dt.normalize() >= last.normalize()).sum())

    # ---- insights
    insights = []

    if len(full_years) >= 3:
        py = max(full_years, key=lambda y: (int(ycount[y]), -y))
        low = min(full_years, key=lambda y: (int(ycount[y]), y))
        insights.append({"id": "peak", "text_he": (
            f"השנה העמוסה ביותר במאגר היא {py} עם {n(ycount[py])} מודעות "
            f"({pct(ycount[py] / total * 100)} מכלל המודעות); השנה השקטה ביותר מבין השנים המלאות היא "
            f"{low} עם {n(ycount[low])}.")})

    if partial and months_in_last >= 3 and len(full_years) >= 1:
        prev = max(full_years)
        pace = ycount[ly] / months_in_last
        prev_pace = ycount[prev] / 12
        ch = (pace / prev_pace - 1) * 100
        if abs(ch) < 15:
            verdict = "בקצב דומה"
        elif ch > 0:
            verdict = f"בקצב גבוה ב-{pct(abs(ch), 0)}"
        else:
            verdict = f"בקצב נמוך ב-{pct(abs(ch), 0)}"
        insights.append({"id": "pace", "text_he": (
            f"ב-{ly} (עד {MONTHS_HE[months_in_last - 1]}) פורסמו {n(ycount[ly])} מודעות, "
            f"כ-{pace:.1f} בחודש — {verdict} ביחס ל-{prev} המלאה ({prev_pace:.1f} בחודש).")})

    known = [(k, v) for k, v in unit_pairs if k != UNCLASSIFIED]
    if len(known) >= 2 and known[0][1] / total >= 0.15:
        unc = int(ucount.get(UNCLASSIFIED, 0))
        tail = (f" {pct(unc / total * 100)} מהמודעות לא שויכו לתחום כי שם התפקיד אינו מציין יחידה."
                if unc / total >= 0.01 else "")
        insights.append({"id": "unit", "text_he": (
            f"התחום המוביל בגיוס הוא {known[0][0]} עם {n(known[0][1])} מודעות ({pct(known[0][1] / total * 100)}), "
            f"אחריו {known[1][0]} ({n(known[1][1])}). שיוך התחום נגזר מנוסח שם התפקיד.{tail}")})

    if len(w) >= 30:
        med = float(w.median())
        txt = f"חציון חלון ההגשה (הימים מתאריך העדכון עד המועד האחרון להגשה) הוא {med:g} ימים"
        if len(full_years) >= 4:
            fy0, fy1 = full_years[0], full_years[-1]
            m0 = float(d.loc[d["year"] == fy0, "window"].dropna().median())
            m1 = float(d.loc[d["year"] == fy1, "window"].dropna().median())
            if abs(m1 - m0) >= 2:
                txt += f"; ב-{fy0} היה {m0:g} ימים וב-{fy1} {m1:g} ימים, כלומר החלון {'התארך' if m1 > m0 else 'התקצר'}"
            else:
                txt += f", ויציב לאורך השנים ({m0:g} ב-{fy0} ו-{m1:g} ב-{fy1})"
        short = int((w <= 7).sum())
        if short / len(w) >= 0.02:
            txt += f". {n(short)} מודעות ({pct(short / len(w) * 100)}) נתנו שבוע או פחות להגשה"
        insights.append({"id": "window", "text_he": txt + "."})

    fd = d[d["year"].isin(full_years)]
    if len(full_years) >= 3 and len(fd) >= 120:
        mc = fd.groupby("month").size()
        avg = len(fd) / 12
        top_m = max(range(1, 13), key=lambda m: (int(mc.get(m, 0)), -m))
        low_m = min(range(1, 13), key=lambda m: (int(mc.get(m, 0)), m))
        if mc.get(top_m, 0) / avg >= 1.2:
            insights.append({"id": "season", "text_he": (
                f"בשנים המלאות ({full_years[0]} עד {full_years[-1]}) {MONTHS_HE[top_m - 1]} הוא חודש הפרסום העמוס ביותר: "
                f"{n(mc[top_m])} מודעות, {pct((mc[top_m] / avg - 1) * 100, 0)} מעל הממוצע החודשי, "
                f"ו{MONTHS_HE[low_m - 1]} השקט ביותר עם {n(mc.get(low_m, 0))}.")})

    if len(tcount) and int(tcount.iloc[0]["cnt"]) >= 5:
        r0 = tcount.iloc[0]
        span = f"בין {int(r0.y0)} ל-{int(r0.y1)}" if r0.y0 != r0.y1 else f"ב-{int(r0.y0)}"
        insights.append({"id": "repeat", "text_he": (
            f"התפקיד «{r0.core}» פורסם {n(r0.cnt)} פעמים {span}; "
            f"{n((tcount['cnt'] > 1).sum())} כותרות תפקיד חוזרות יותר מפעם אחת במאגר, מתוך {n(len(tcount))} כותרות שונות.")})

    mg = int((d["role"] == "ניהול ובכירים").sum())
    if mg / total >= 0.2:
        insights.append({"id": "mgmt", "text_he": (
            f"{pct(mg / total * 100)} מהמודעות ({n(mg)}) הן לתפקידי ניהול ובכירים: מנהלים, ראשי צוותים וסגנים.")})

    cm = int(d["committee"].sum())
    sb = int(d["substitute"].sum())
    parts = []
    if cm / total >= 0.03:
        parts.append(f"{n(cm)} מודעות ({pct(cm / total * 100)}) מציינות ועדת קבלה")
    if sb / total >= 0.03:
        parts.append(f"{n(sb)} מודעות ({pct(sb / total * 100)}) הן מילוי מקום או גיוס לפי קריאה")
    if parts:
        insights.append({"id": "special", "text_he": "; ".join(parts) + "."})

    if open_now > 0:
        insights.append({"id": "open", "text_he": (
            f"במועד העדכון האחרון במאגר ({d_he(last)}) {n(open_now)} מודעות עדיין פתוחות להגשה, "
            "כלומר המועד האחרון שלהן אינו לפני תאריך זה.")})

    # ---- KPIs
    distinct_titles = int(len(tcount))
    med_w = float(w.median()) if len(w) else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "span": {"value": f"{years[0]}–{years[-1]}", "display": f"{years[0]}–{years[-1]}", "tone": "brand"},
        "window": {"value": med_w, "display": f"{med_w:g}", "tone": "info"},
        "titles": {"value": distinct_titles, "display": n(distinct_titles), "tone": "brand"},
    }

    labels = {
        "lede": (f"{n(total)} מודעות דרושים של עיריית באר שבע שפורסמו בין {d_he(first)} ל-{d_he(last)}: "
                 f"היקף הגיוס לפי שנה ועונה, התחומים והתפקידים המבוקשים, וכמה זמן ניתן להגיש מועמדות."),
        "year_aria": f"מספר מודעות הדרושים בכל שנה, {years[0]} עד {years[-1]}",
        "heat_aria": "מפת חום של מספר המודעות לפי חודש ושנה",
        "units_aria": "מספר מודעות לפי תחום",
        "mix_aria": "תמהיל התחומים בכל שנה",
        "wb_aria": "התפלגות חלון ההגשה בימים",
        "wmed_aria": "חציון חלון ההגשה בכל שנה",
        "roles_aria": "מספר מודעות לפי סוג תפקיד",
        "titles_aria": "התפקידים שפורסמו הכי הרבה פעמים",
        "wd_aria": "מודעות לפי יום בשבוע של העדכון ושל המועד האחרון",
        "year_note": (f"{ylabel(ly)}: שנה חלקית, המאגר כולל מודעות עד {d_he(last)}." if partial
                      else "כל חודשי השנה האחרונה מיוצגים."),
        "heat_note": f"{n(len(heat_years))} השנים האחרונות; הצבע מבטא את מספר המודעות שעודכנו בכל חודש.",
    }

    agent_data = {
        "summary_he": (f"{n(total)} מודעות דרושים של עיריית באר שבע בין {years[0]} ל-{years[-1]}, "
                       f"לפי תחום, סוג תפקיד, עונתיות וחלון הגשה (חציון {med_w:g} ימים)."),
        "dataset_kind": "timeseries",
        "suggested_tags": ["דרושים", "משרות", "גיוס עובדים", "עיריית באר שבע", "שוק העבודה"],
        "related_ids": ["f4a5cdab-82b2-48ad-9d95-424a035cfed8", "54b65747-904e-42e1-9316-0575ebbc1216"],
        "temporal_coverage": f"{first.year}/{last.year}",
        "spatial_coverage": "באר שבע",
    }
    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"by_year": by_year, "heat": heat, "units": units, "mix": mix_chart,
                   "wbuckets": wbuckets, "wmed": wmed, "roles": roles, "titles": titles, "wd": wd},
        "insights": insights,
        "labels": labels,
        "tables": {"year": [[ylabel(y), n(ycount[y])] for y in years], "units": _table_rows(unit_pairs),
                   "mix_heads": mix_names, "mix": mix_rows,
                   "wb": [[a, n(b)] for a, b in zip(wb_names, wb_vals)], "wmed": wrows,
                   "roles": _table_rows(role_pairs), "titles": title_rows, "wd": wd_rows},
        "latest": latest,
        "has_window": bool(len(w)),
        "has_repeat": bool(len(tcount) and int(tcount.iloc[0]["cnt"]) >= 3),
    }
