"""עיצובים (מדגמים) — Israeli industrial-design applications, Patent Office.

One row per application (a handful of application numbers appear twice
with a case-only difference in the applicant name; one row per number is
kept, picked after a total sort so the choice is order-free).

Time axis: the application date (תאריך בקשה). Yearly views start at the
first year with at least MIN_YEAR_ROWS filings (the register's earliest
years hold a few stray rows; they are disclosed). Five-year periods are
used for mix views; the latest period and the latest year are partial while
they fill up — partiality is read from the data (the last filing month of
the latest year), never from the clock, and trend rules use complete years
only.

Locarno class: the leading number of `סוג` ("25 ( 01 )" → class 25; a
handful carry the class number alone). Class names are the Locarno
classification's headings (definitions, not data); an unknown code is
shown as its number.

Applicant identity: `קוד מבקש 1` (the register's applicant code), shown by
its most common English name. Different codes stay separate even when they
are affiliates. Rows without an applicant code are excluded from applicant
views and the exclusion is disclosed. "Foreign priority" = the filing
claims priority (`1 דין קדימה` == -1) from an office other than Israel.

Status: the 17 register statuses fold into five groups by their wording
(registered / registered with an unpaid renewal / under examination /
expired / closed or cancelled); an unknown status falls in "אחר".
"""
import re

import pandas as pd

MIN_YEAR_ROWS = 20
PERIOD = 5
MIN_PERIOD_ROWS = 500     # earlier periods merge into the first one that reaches this
TOP_CLASSES = 15
HEAT_CLASSES = 12
TOP_OFFICES = 12
TREND_OFFICES = 4
TOP_APPLICANTS = 15
TOP_WORDS = 15
LAG_MAX_MONTHS = 120      # filing→publication lags outside 0..this are treated as data errors
PRIO_MAX_MONTHS = 24

LOCARNO = {
    1: "מוצרי מזון", 2: "ביגוד והלבשה", 3: "מוצרי מסע, תיקים ופריטים אישיים",
    4: "מברשות", 5: "טקסטיל ויריעות", 6: "ריהוט", 7: "כלי בית",
    8: "כלי עבודה ופרזול", 9: "אריזות ומכלים", 10: "שעונים ומכשירי מדידה",
    11: "תכשיטים וחפצי נוי", 12: "כלי תחבורה ורכיביהם", 13: "ציוד חשמל",
    14: "ציוד תקשורת ומחשוב", 15: "מכונות", 16: "צילום ואופטיקה",
    17: "כלי נגינה", 18: "מכונות דפוס ומשרד", 19: "צורכי כתיבה ומשרד",
    20: "ציוד מכירה ושילוט", 21: "משחקים, צעצועים וספורט",
    22: "נשק, ציד, דיג והדברה", 23: "אינסטלציה, תברואה, חימום ומיזוג",
    24: "ציוד רפואי ומעבדה", 25: "רכיבי בנייה", 26: "תאורה",
    27: "טבק וצורכי עישון", 28: "תרופות, קוסמטיקה וטואלטיקה",
    29: "ציוד בטיחות והצלה", 30: "ציוד לבעלי חיים",
    31: "מכונות להכנת מזון ומשקאות", 32: "סמלים גרפיים, לוגואים וממשקי משתמש",
    99: "שונות",
}

OFFICE_HE = {
    "United States": "ארה״ב", "OHIM": "האיחוד האירופי", "China": "סין",
    "WIPO": "הגשה בינלאומית", "Switzerland": "שווייץ", "Japan": "יפן",
    "Italy": "איטליה", "Germany": "גרמניה", "Sweden": "שוודיה", "France": "צרפת",
    "South Korea": "דרום קוריאה", "United Kingdom - England": "בריטניה",
    "Turkey": "טורקיה", "Australia": "אוסטרליה", "Finland": "פינלנד",
    "Spain": "ספרד", "Denmark": "דנמרק", "Canada": "קנדה", "Benelux": "בנלוקס",
    "Norway": "נורווגיה", "Russian Federation": "רוסיה", "Singapore": "סינגפור",
    "India": "הודו", "Liechtenstein": "ליכטנשטיין", "Austria": "אוסטריה",
    "New Zealand": "ניו זילנד", "Brazil": "ברזיל", "Czech Republic": "צ׳כיה",
    "Ukraine": "אוקראינה", "Croatia": "קרואטיה", "Hong Kong": "הונג קונג",
    "Belgium": "בלגיה", "Portugal": "פורטוגל", "Rumania": "רומניה",
    "Taiwan": "טייוואן", "South Africa": "דרום אפריקה", "Poland": "פולין",
    "Greece": "יוון", "Ireland": "אירלנד", "Hungary": "הונגריה",
    "Luxembourg": "לוקסמבורג", "Netherlands": "הולנד", "Israel": "ישראל",
}
ISRAEL_OFFICE = "Israel"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
OTHER = "אחר"
UNSTATED_OFFICE = "לא צוין"

STATUS_HE = {
    "Design Registered": "רשום",
    "Design Registered First Renewal": "רשום, חידוש ראשון",
    "Design Registered Second Renewal": "רשום, חידוש שני",
    "Design Registered Third Renewal": "רשום, חידוש שלישי",
    "Design Registered Full Period Renewal": "רשום, חודש לתקופה המלאה",
    "Design Registered Not Paid First Renewal": "רשום, חידוש ראשון לא שולם",
    "Design Registered Not Paid Second Renewal": "רשום, חידוש שני לא שולם",
    "Design Registered Not Paid Third Renewal": "רשום, חידוש שלישי לא שולם",
    "Waiting For Fundamental Exam": "ממתין לבחינה",
    "Subsantitive Examination": "בבחינה מהותית",
    "Repeat Subsantitive Examination": "בבחינה מהותית חוזרת",
    "Expired Not Paid Renewal": "פג, החידוש לא שולם",
    "Expired": "פג בתום תקופת ההגנה",
    "Expired Refundable": "פג, ניתן להשבה",
    "Request For Close Design": "הבקשה נסגרה",
    "Cancel Design": "בוטל",
    "Deleted Design": "נמחק",
}
GROUPS = [("reg", "רשום ובתוקף"), ("unpaid", "רשום, חידוש לא שולם"),
          ("exam", "בבחינה"), ("expired", "פג תוקף"), ("closed", "נסגר או בוטל"),
          ("other", "אחר")]
GROUP_HE = dict(GROUPS)

PROLIFIC = [(1, 1, "1"), (2, 2, "2"), (3, 5, "3 עד 5"), (6, 10, "6 עד 10"),
            (11, 50, "11 עד 50"), (51, 200, "51 עד 200"), (201, 10**9, "מעל 200")]
PRIO_BINS = [(0, 1, "עד חודש", "0-1"), (1, 2, "1 עד 2", "1-2"), (2, 3, "2 עד 3", "2-3"),
             (3, 4, "3 עד 4", "3-4"), (4, 5, "4 עד 5", "4-5"), (5, 6, "5 עד 6", "5-6"),
             (6, 6.5, "6 עד 6.5", "6-6.5"), (6.5, PRIO_MAX_MONTHS + 0.001, "מעל 6.5", "מעל 6.5")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _group(s):
    if s.startswith("Design Registered"):
        return "unpaid" if "Not Paid" in s else "reg"
    if "Expired" in s:
        return "expired"
    if "Exam" in s:
        return "exam"
    if "Close" in s or "Cancel" in s or "Delete" in s:
        return "closed"
    return "other"


def _class_name(c):
    return LOCARNO.get(c, f"סוג {c:02d}")


def _clean_name(s):
    s = re.sub(r"\s+", " ", s).strip()
    t = re.sub(r"^[^\wא-ת]+", "", s)
    t = re.sub(r"[^\wא-ת)]+$", "", t).strip()
    return t or s


def _first_word(he):
    he = re.sub(r"[^\sא-ת״׳\"'-]", " ", he).strip()
    if he:
        w = he.split()[0].strip("\"'-")
        if len(w) >= 2:
            return w
    return ""


def _prepare(raw):
    df = raw.apply(lambda c: c.str.strip())
    n_raw = len(df)
    df = df.sort_values(list(df.columns), kind="stable")
    df = df.drop_duplicates("מספר בקשה").reset_index(drop=True)
    dups = n_raw - len(df)
    fmt = "%d/%m/%Y"
    df["fd"] = pd.to_datetime(df["תאריך בקשה"], format=fmt, errors="coerce")
    df["pd"] = pd.to_datetime(df["תאריך פרסום"], format=fmt, errors="coerce")
    df["prd"] = pd.to_datetime(df["תאריך דין קדימה 1"], format=fmt, errors="coerce")
    df["year"] = df["fd"].dt.year
    cls = pd.to_numeric(df["סוג"].str.extract(r"^\s*(\d+)")[0], errors="coerce")
    df["cls"] = cls.where(cls > 0)
    df["grp"] = df["סטטוס נוכחי באנגלית"].map(_group)
    df["prio"] = df["1 דין קדימה"] == "-1"
    off = df["מדינת איגוד דין קדימה 1"]
    df["office"] = off.where(off != "", UNSTATED_OFFICE).where(df["prio"], "")
    df["foreign"] = df["prio"] & (df["office"] != ISRAEL_OFFICE)
    df["code"] = df["קוד מבקש 1"].str.replace(",", "", regex=False)
    df["n_appl"] = sum((df[c] != "").astype(int) for c in
                       ["קוד מבקש 1", "קוד מבקש 2", "קוד מבקש 3", "קוד מבקש 4"])
    df["word"] = df["שם מדגם עיצוב בעברית"].map(_first_word)
    return df, dups


def compute(frames):
    df, dups = _prepare(frames["designs"])
    n = len(df)
    dated = df[df["year"].notna()].copy()
    dated["year"] = dated["year"].astype(int)
    ycount = dated.groupby("year").size()
    first_year = int(next((y for y, c in ycount.items() if c >= MIN_YEAR_ROWS), ycount.index[0]))
    last_year = int(ycount.index[-1])
    pre_rows = int(ycount[ycount.index < first_year].sum())
    last_month = int(dated.loc[dated["year"] == last_year, "fd"].dt.month.max())
    year_partial = last_month < 12
    full_last = last_year - 1 if year_partial else last_year
    years = list(range(first_year, last_year + 1))
    yc = [int(ycount.get(y, 0)) for y in years]
    yf = dated[dated["foreign"]].groupby("year").size()
    yshare = [round(float(yf.get(y, 0)) / c * 100, 1) if c else None for y, c in zip(years, yc)]

    # ---------------- periods ----------------
    dated["p0"] = (dated["year"] // PERIOD) * PERIOD
    pc = dated.groupby("p0").size()
    p_first = int(next((p for p, c in pc.items() if c >= MIN_PERIOD_ROWS), pc.index[0]))
    dated["per"] = dated["p0"].clip(lower=p_first)
    pkeys = sorted(int(p) for p in dated["per"].unique())
    pmin_year = int(dated["year"].min())

    def plabel(p):
        lo = pmin_year if p == p_first else p
        hi = min(p + PERIOD - 1, last_year)
        return f"{lo}–{hi}" if hi > lo else f"{lo}"

    def pprose(p):
        lo = pmin_year if p == p_first else p
        hi = min(p + PERIOD - 1, last_year)
        return f"{lo} עד {hi}" if hi > lo else f"{lo}"

    plabels = [plabel(p) for p in pkeys]
    # chart axes: ASCII hyphen keeps "1974-1989" in LTR order inside RTL canvas text
    paxis = [lab.replace("–", "-") for lab in plabels]
    p_last_partial = pkeys[-1] + PERIOD - 1 > full_last
    full_pkeys = [p for p in pkeys if not (p == pkeys[-1] and p_last_partial)]
    ptot = dated.groupby("per").size()

    # ---------------- status ----------------
    gcount = df["grp"].value_counts()
    groups = [(k, h) for k, h in GROUPS if gcount.get(k, 0)]
    status_chart = {"names": [h for _, h in groups], "values": [int(gcount[k]) for k, _ in groups],
                    "keys": [k for k, _ in groups]}
    sc = df.groupby(["grp", "סטטוס נוכחי באנגלית"]).size().rename("n").reset_index()
    sc["gi"] = sc["grp"].map({k: i for i, (k, _) in enumerate(GROUPS)})
    sc = sc.sort_values(["gi", "n", "סטטוס נוכחי באנגלית"], ascending=[True, False, True], kind="stable")
    status_rows = [{"group": GROUP_HE[r.grp], "name": STATUS_HE.get(r[2], r[2]), "n": _int(r.n),
                    "share": f"{r.n / n * 100:.1f}"} for r in sc.itertuples(index=False)]
    in_force = int(gcount.get("reg", 0) + gcount.get("unpaid", 0))

    cg = dated.groupby(["per", "grp"]).size().unstack(fill_value=0)
    cohort = {"x": paxis, "series": []}
    cohort_rows = []
    for k, h in groups:
        col = cg[k] if k in cg.columns else pd.Series(0, index=cg.index)
        cohort["series"].append({"name": h, "key": k,
                                 "data": [round(float(col.get(p, 0)) / ptot[p] * 100, 1) for p in pkeys]})
    for i, p in enumerate(pkeys):
        cohort_rows.append({"per": plabels[i], "vals": [f"{s['data'][i]:.1f}" for s in cohort["series"]],
                            "n": _int(ptot[p])})

    # ---------------- Locarno classes ----------------
    cl = df[df["cls"].notna()].copy()
    cl["cls"] = cl["cls"].astype(int)
    ccount = cl.groupby("cls").size().rename("n").reset_index().sort_values(
        ["n", "cls"], ascending=[False, True], kind="stable")
    n_cls = len(cl)
    top_c = ccount.head(TOP_CLASSES)
    rest_c = int(ccount["n"].iloc[TOP_CLASSES:].sum())
    classes = {"names": [f"{c:02d} {_class_name(c)}" for c in top_c["cls"]],
               "values": [int(v) for v in top_c["n"]]}
    if rest_c:
        classes["names"].append(f"{OTHER} ({len(ccount) - TOP_CLASSES} סוגים)")
        classes["values"].append(rest_c)
    class_rows = [{"code": f"{c:02d}", "name": _class_name(c), "n": _int(v), "share": f"{v / n_cls * 100:.1f}"}
                  for c, v in zip(top_c["cls"], top_c["n"])]
    if rest_c:
        class_rows.append({"code": "", "name": classes["names"][-1], "n": _int(rest_c),
                           "share": f"{rest_c / n_cls * 100:.1f}"})

    heat_cls = list(ccount["cls"].head(HEAT_CLASSES))
    cld = dated[dated["cls"].notna()].copy()
    cld["cls"] = cld["cls"].astype(int)
    pcl = cld.groupby("per").size()
    hc = cld[cld["cls"].isin(heat_cls)].groupby(["cls", "per"]).size()
    heat = {"x": paxis, "y": [f"{c:02d} {_class_name(c)}" for c in heat_cls], "cells": []}
    heat_rows = []
    hshare = {}
    for yi, c in enumerate(heat_cls):
        vals = []
        for xi, p in enumerate(pkeys):
            v = round(float(hc.get((c, p), 0)) / pcl[p] * 100, 1) if pcl.get(p, 0) else 0.0
            hshare[(c, p)] = v
            heat["cells"].append([xi, yi, v])
            vals.append(f"{v:.1f}")
        heat_rows.append({"name": heat["y"][yi], "vals": vals})
    heat["max"] = max((v for _, _, v in heat["cells"]), default=0)

    # ---------------- priority offices ----------------
    pr = df[df["prio"]]
    n_prio = len(pr)
    n_foreign = int(df["foreign"].sum())
    ocount = pr.groupby("office").size().rename("n").reset_index().sort_values(
        ["n", "office"], ascending=[False, True], kind="stable")
    top_o = ocount.head(TOP_OFFICES)
    rest_o = int(ocount["n"].iloc[TOP_OFFICES:].sum())
    offices = {"names": [OFFICE_HE.get(o, o) for o in top_o["office"]],
               "values": [int(v) for v in top_o["n"]]}
    if rest_o:
        offices["names"].append(f"{OTHER} ({len(ocount) - TOP_OFFICES})")
        offices["values"].append(rest_o)
    office_rows = [{"name": nm, "n": _int(v), "share": f"{v / n_prio * 100:.1f}"}
                   for nm, v in zip(offices["names"], offices["values"])]

    trend_off = [o for o in ocount["office"] if o not in (ISRAEL_OFFICE, UNSTATED_OFFICE)][:TREND_OFFICES]
    fo = dated[dated["foreign"]]
    oc = fo.groupby(["per", "office"]).size()
    otrend = {"x": paxis, "series": []}
    for o in trend_off:
        otrend["series"].append({"name": OFFICE_HE.get(o, o),
                                 "data": [round(float(oc.get((p, o), 0)) / ptot[p] * 100, 1) for p in pkeys]})
    rest_f = fo[~fo["office"].isin(trend_off)].groupby("per").size()
    otrend["series"].append({"name": "מדינות ומשרדים אחרים",
                             "data": [round(float(rest_f.get(p, 0)) / ptot[p] * 100, 1) for p in pkeys]})
    otrend_rows = [{"per": plabels[i], "vals": [f"{s['data'][i]:.1f}" for s in otrend["series"]],
                    "tot": f"{sum(s['data'][i] for s in otrend['series']):.1f}"} for i in range(len(pkeys))]

    # ---------------- applicants ----------------
    ap = df[df["code"] != ""]
    n_noappl = n - len(ap)
    acount = ap.groupby("code").size()
    n_applicants = len(acount)
    nm = ap[ap["שם מבקש אנגלית 1"] != ""].groupby(["code", "שם מבקש אנגלית 1"]).size().rename("k").reset_index()
    nm = nm.sort_values(["code", "k", "שם מבקש אנגלית 1"], ascending=[True, False, True], kind="stable")
    names = nm.drop_duplicates("code").set_index("code")["שם מבקש אנגלית 1"].map(_clean_name)
    af = ap.groupby("code")["foreign"].mean()
    ay = ap[ap["year"].notna()].groupby("code")["year"].agg(["min", "max"])
    rank = acount.rename("n").reset_index().sort_values(["n", "code"], ascending=[False, True], kind="stable")
    rank = rank[rank["code"].isin(names.index)]
    top_a = rank.head(TOP_APPLICANTS)
    top = {"names": [names[c] for c in top_a["code"]], "values": [int(v) for v in top_a["n"]],
           "foreign": [bool(af[c] >= 0.5) for c in top_a["code"]]}
    top_rows = []
    for c, v in zip(top_a["code"], top_a["n"]):
        lo, hi = (int(ay.at[c, "min"]), int(ay.at[c, "max"])) if c in ay.index else (None, None)
        top_rows.append({"name": names[c], "n": _int(v),
                         "years": (f"{lo}–{hi}" if hi != lo else f"{lo}") if lo else "",
                         "foreign": f"{af[c] * 100:.0f}"})
    top10_share = float(rank["n"].head(10).sum()) / len(ap) if len(ap) else 0.0

    pb = []
    for lo, hi, lab in PROLIFIC:
        sel = acount[(acount >= lo) & (acount <= hi)]
        pb.append((lab, int(len(sel)), int(sel.sum())))
    pb = [r for r in pb if r[1]]
    prolific = {"names": [r[0] for r in pb], "values": [r[1] for r in pb]}
    prolific_rows = [{"bucket": r[0], "appl": _int(r[1]), "apps": _int(r[2]),
                      "share": f"{r[2] / len(ap) * 100:.1f}"} for r in pb]
    single = int(acount[acount == 1].count())
    multi_n = int((df["n_appl"] >= 2).sum())

    # ---------------- lags ----------------
    lagd = dated[dated["pd"].notna()].copy()
    lagd["lag"] = (lagd["pd"] - lagd["fd"]).dt.days / 30.4375
    ok = (lagd["lag"] >= 0) & (lagd["lag"] <= LAG_MAX_MONTHS)
    lag_bad = int((~ok).sum())
    lagd = lagd[ok]
    lq = lagd[lagd["year"] >= first_year].groupby("year")["lag"].quantile([0.25, 0.5, 0.75]).unstack()
    lag_chart = {"x": [str(y) for y in years],
                 "p25": [round(float(lq.at[y, 0.25]), 1) if y in lq.index else None for y in years],
                 "p50": [round(float(lq.at[y, 0.5]), 1) if y in lq.index else None for y in years],
                 "p75": [round(float(lq.at[y, 0.75]), 1) if y in lq.index else None for y in years]}
    lmed = lq[0.5] if len(lq) else pd.Series(dtype=float)

    pl = df[df["prio"] & df["prd"].notna() & df["fd"].notna()]
    plag = (pl["fd"] - pl["prd"]).dt.days / 30.4375
    plag_ok = plag[(plag >= 0) & (plag <= PRIO_MAX_MONTHS)]
    prio_bins = []
    for lo, hi, lab, short in PRIO_BINS:
        prio_bins.append((lab, int(((plag_ok >= lo) & (plag_ok < hi)).sum()), short))
    prio_lag = {"names": [b[2] for b in prio_bins], "values": [b[1] for b in prio_bins]}
    n_plag = len(plag_ok)
    prio_rows = [{"bucket": b[0], "n": _int(b[1]), "share": f"{b[1] / n_plag * 100:.1f}" if n_plag else "0.0"}
                 for b in prio_bins]
    near_deadline = int(((plag_ok >= 5) & (plag_ok < 6.5)).sum())

    # ---------------- design-name words ----------------
    wd = df[df["word"] != ""]
    wcount = wd.groupby("word").size().rename("n").reset_index().sort_values(
        ["n", "word"], ascending=[False, True], kind="stable")
    top_w = wcount.head(TOP_WORDS)
    words = {"names": list(top_w["word"]), "values": [int(v) for v in top_w["n"]]}
    wcls = wd[wd["cls"].notna()].groupby(["word", "cls"]).size().rename("k").reset_index()
    wcls = wcls.sort_values(["word", "k", "cls"], ascending=[True, False, True], kind="stable").drop_duplicates("word")
    wcls = wcls.set_index("word")["cls"]
    word_rows = [{"word": w, "n": _int(v), "cls": _class_name(int(wcls[w])) if w in wcls.index else ""}
                 for w, v in zip(top_w["word"], top_w["n"])]

    # ---------------- insights ----------------
    full_years = [y for y in years if y <= full_last]

    def ins_trend():
        if len(full_years) < 10:
            return None
        z = full_years[-1]
        a = z - 10
        vz, va = int(ycount.get(z, 0)), int(ycount.get(a, 0))
        peak_y = max(full_years, key=lambda y: (int(ycount.get(y, 0)), y))
        vp = int(ycount.get(peak_y, 0))
        if not va:
            return None
        ch = (vz - va) / va
        if abs(ch) < 0.1:
            head = f"מספר הבקשות יציב יחסית: {_int(vz)} ב-{z} לעומת {_int(va)} ב-{a}"
        else:
            word = "עלייה" if ch > 0 else "ירידה"
            head = f"ב-{z} הוגשו {_int(vz)} בקשות לרישום עיצוב — {word} של {_pct(abs(ch), 0)} לעומת {a} ({_int(va)})"
        if peak_y == z:
            return head + "; זו השנה השיאית במאגר."
        return head + f"; השיא נרשם ב-{peak_y} עם {_int(vp)} בקשות."

    def ins_status():
        exp = int(gcount.get("expired", 0))
        unpaid_exp = int((df["סטטוס נוכחי באנגלית"] == "Expired Not Paid Renewal").sum())
        if not exp or not n:
            return None
        txt = f"{_pct(in_force / n, 0)} מהעיצובים במאגר רשומים כיום, ו-{_pct(exp / n, 0)} פגו"
        if unpaid_exp / exp >= 0.5:
            txt += f"; ברוב המקרים ({_pct(unpaid_exp / exp, 0)} מהפגים) העיצוב פקע משום שאגרת החידוש לא שולמה, ולא בתום תקופת ההגנה"
        return txt + "."

    def ins_class():
        if len(ccount) < 2:
            return None
        c1, v1 = int(ccount["cls"].iloc[0]), int(ccount["n"].iloc[0])
        c2, v2 = int(ccount["cls"].iloc[1]), int(ccount["n"].iloc[1])
        if v1 < 1.3 * v2:
            return None
        w1 = wd[wd["cls"] == c1].groupby("word").size().rename("k").reset_index().sort_values(
            ["k", "word"], ascending=[False, True], kind="stable")
        txt = (f"סוג {c1:02d} בסיווג לוקרנו ({_class_name(c1)}) מוביל עם {_int(v1)} בקשות — "
               f"{_pct(v1 / n_cls, 0)} מהמאגר, פי {v1 / v2:.1f} מהסוג הבא ({_class_name(c2)})")
        if len(w1) and w1["k"].iloc[0] / v1 >= 0.3:
            txt += f"; {_pct(w1['k'].iloc[0] / v1, 0)} מהן נקראות ״{w1['word'].iloc[0]}״"
        return txt + "."

    def ins_class_shift():
        if len(full_pkeys) < 3:
            return None
        a, z = full_pkeys[0], full_pkeys[-1]
        best = None
        for c in heat_cls:
            d = hshare[(c, z)] - hshare[(c, a)]
            if best is None or abs(d) > abs(best[1]) or (abs(d) == abs(best[1]) and c < best[0]):
                best = (c, d)
        if best is None or abs(best[1]) < 3:
            return None
        c, d = best
        word = "עלה" if d > 0 else "ירד"
        return (f"השינוי הגדול בתמהיל: שיעורו של סוג {c:02d} ({_class_name(c)}) {word} מ-{hshare[(c, a)]:.1f}% "
                f"מהבקשות בשנים {pprose(a)} ל-{hshare[(c, z)]:.1f}% בשנים {pprose(z)}.")

    def ins_prio():
        if not n_prio or not len(ocount):
            return None
        o1 = ocount["office"].iloc[0]
        txt = (f"{_pct(n_foreign / n, 0)} מהבקשות נשענות על דין קדימה מבקשה קודמת בחו״ל; "
               f"המקור הנפוץ הוא {OFFICE_HE.get(o1, o1)} ({_int(ocount['n'].iloc[0])} בקשות)")
        if len(ocount) > 1:
            o2 = ocount["office"].iloc[1]
            txt += f", ואחריו {OFFICE_HE.get(o2, o2)} ({_int(ocount['n'].iloc[1])})"
        return txt + "."

    def ins_foreign_trend():
        if len(full_pkeys) < 3:
            return None
        a, z = full_pkeys[0], full_pkeys[-1]
        fa = float((dated["foreign"] & (dated["per"] == a)).sum()) / ptot[a]
        fz = float((dated["foreign"] & (dated["per"] == z)).sum()) / ptot[z]
        if abs(fz - fa) < 0.05:
            return None
        word = "עלה" if fz > fa else "ירד"
        return (f"שיעור הבקשות עם דין קדימה מחו״ל {word} מ-{_pct(fa, 0)} בשנים {pprose(a)} "
                f"ל-{_pct(fz, 0)} בשנים {pprose(z)}.")

    def ins_deadline():
        if n_plag < 100 or near_deadline / n_plag < 0.5:
            return None
        return (f"{_pct(near_deadline / n_plag, 0)} מהבקשות עם דין קדימה הוגשו בישראל בין החודש החמישי "
                f"לחצי החודש השביעי מהבקשה המקורית — סמוך לסוף חלון דין הקדימה של שישה חודשים.")

    def ins_lag():
        ys = [y for y in full_years if y in lmed.index]
        if len(ys) < 10:
            return None
        recent, prior = ys[-5:], ys[-10:-5]
        mr = float(pd.Series([lmed[y] for y in recent]).median())
        mp = float(pd.Series([lmed[y] for y in prior]).median())
        if abs(mr - mp) < 2 or abs(mr - mp) / max(mp, 0.1) < 0.3:
            return None
        word = "התקצר" if mr < mp else "התארך"
        return (f"הזמן מהגשת הבקשה ועד פרסומה {word}: חציון של {mr:.1f} חודשים בבקשות מ-{recent[0]} עד {recent[-1]}, "
                f"לעומת {mp:.1f} חודשים בבקשות מ-{prior[0]} עד {prior[-1]}.")

    def ins_leader():
        if len(rank) < 10:
            return None
        c = top_a["code"].iloc[0]
        txt = (f"המגיש הגדול הוא {names[c]} עם {_int(top_a['n'].iloc[0])} בקשות"
               + (f" בין {int(ay.at[c, 'min'])} ל-{int(ay.at[c, 'max'])}" if c in ay.index else ""))
        txt += (f"; עשרת המגישים הגדולים מחזיקים {_pct(top10_share, 1)} מהבקשות, ו-{_pct(single / n_applicants, 0)} "
                f"מ-{_int(n_applicants)} המגישים הגישו בקשה אחת בלבד.")
        return txt

    def ins_pending():
        pend = int(gcount.get("exam", 0))
        if pend < 20:
            return None
        pe = dated[dated["grp"] == "exam"]
        txt = f"{_int(pend)} בקשות ממתינות כעת לבחינה או נמצאות בה"
        if len(pe):
            y0 = int(pe["year"].min())
            share_new = float((pe["year"] >= full_last).mean())
            txt += f"; {_pct(share_new, 0)} מהן הוגשו מ-{full_last} ואילך, והוותיקה שבהן מ-{y0}"
        return txt + "."

    def ins_co():
        if multi_n < 50:
            return None
        return f"{_int(multi_n)} בקשות ({_pct(multi_n / n, 1)}) הוגשו בידי שני מגישים או יותר."

    def ins_partial():
        if not year_partial:
            return None
        return (f"נתוני {last_year} חלקיים: הבקשה האחרונה במאגר הוגשה ב{MONTHS_HE[last_month - 1]}, "
                f"ועד כה נרשמו {_int(ycount.get(last_year, 0))} בקשות בשנה זו.")

    rules = [("trend", ins_trend()), ("status", ins_status()), ("class", ins_class()),
             ("class_shift", ins_class_shift()), ("prio", ins_prio()),
             ("foreign_trend", ins_foreign_trend()), ("deadline", ins_deadline()),
             ("lag", ins_lag()), ("leader", ins_leader()), ("pending", ins_pending()),
             ("co", ins_co()), ("partial", ins_partial())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- KPIs ----------------
    vz = int(ycount.get(full_last, 0))
    vprev = int(ycount.get(full_last - 1, 0))
    ch = (vz - vprev) / vprev if vprev else 0.0
    last_tone = "ok" if ch >= 0.05 else "danger" if ch <= -0.15 else "warn" if ch <= -0.05 else "brand"
    force_share = in_force / n if n else 0.0
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "in_force": {"value": in_force, "display": _int(in_force), "tone": "brand"},
        "last_year": {"value": vz, "display": _int(vz), "tone": last_tone},
        "foreign": {"value": n_foreign / n if n else 0.0, "display": _pct(n_foreign / n if n else 0.0, 0),
                    "tone": "info"},
    }
    if abs(ch) < 0.005:
        ch_txt = "ללא שינוי לעומת השנה הקודמת"
    else:
        ch_txt = f"{'+' if ch > 0 else '−'}{abs(ch) * 100:.0f}% לעומת {full_last - 1}"

    lo_d, hi_d = dated["fd"].min(), dated["fd"].max()
    lede = (f"{_int(n)} בקשות לרישום עיצוב (מדגם) ברשות הפטנטים, שהוגשו מ-{lo_d.year} ועד {hi_d.strftime('%d.%m.%Y')} — "
            f"מגיש הבקשה, שם המוצר, סוגו בסיווג לוקרנו הבין־לאומי, דין קדימה מבקשה קודמת בחו״ל, ומצבה כיום. "
            f"{_int(in_force)} עיצובים ({_pct(force_share, 0)}) רשומים כיום.")
    if dups:
        lede += f" {_int(dups)} שורות כפולות של אותו מספר בקשה אוחדו."
    summary = (f"{_int(n)} בקשות לרישום עיצוב בישראל מ-{lo_d.year} עד {hi_d.year}: מגמה שנתית, מצב הרישום, "
               f"סוגי מוצרים לפי סיווג לוקרנו, דין קדימה מחו״ל ({_pct(n_foreign / n, 0)} מהבקשות) "
               f"והמגישים הגדולים.")

    partial_note = f" נתוני {last_year} חלקיים (עד {MONTHS_HE[last_month - 1]})." if year_partial else ""
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["עיצובים", "מדגמים", "קניין רוחני", "רשות הפטנטים", "סיווג לוקרנו"],
            "related_ids": ["029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                            "ebf84395-4784-4438-b9ca-08caf263beaf",
                            "556634fd-fcec-4bbd-8bd5-ba1390bc1c14",
                            "5a2d2f62-781a-4994-bf6d-2c2585f83d36"],
            "temporal_coverage": f"{lo_d.year}/{hi_d.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"years": {"x": [str(y) for y in years], "y": yc, "share": yshare,
                             "partial": year_partial},
                   "status": status_chart, "cohort": cohort, "classes": classes, "heat": heat,
                   "offices": offices, "otrend": otrend, "top": top, "prolific": prolific,
                   "lag": lag_chart, "prio_lag": prio_lag, "words": words},
        "tables": {"status": status_rows, "cohort": cohort_rows, "classes": class_rows,
                   "heat": heat_rows, "offices": office_rows, "otrend": otrend_rows, "top": top_rows,
                   "prolific": prolific_rows, "prio_lag": prio_rows, "words": word_rows},
        "flags": {"year_partial": year_partial},
        "insights": insights,
        "labels": {
            "lede": lede,
            "in_force_kpi": f"עיצובים רשומים כיום ({_pct(force_share, 0)} מהבקשות)",
            "last_year_kpi": f"בקשות שהוגשו ב-{full_last} ({ch_txt})",
            "foreign_kpi": "מהבקשות עם דין קדימה מחו״ל",
            "years_note": (f"מספר הבקשות לפי שנת ההגשה, ושיעור הבקשות עם דין קדימה מחו״ל (קו, ציר ימני)."
                           + partial_note
                           + (f" {_int(pre_rows)} בקשות מלפני {first_year} אינן מוצגות בגרף." if pre_rows else "")),
            "status_note": (f"מצב {_int(n)} הבקשות כיום, בחמש קבוצות. ״רשום, חידוש לא שולם״ — עיצוב שמועד "
                            f"החידוש שלו הגיע והאגרה טרם שולמה."),
            "cohort_note": (f"מצב הבקשות כיום לפי תקופת ההגשה (באחוזים מהבקשות בכל תקופה). בקשות ותיקות "
                            f"פגו ברובן; בקשות חדשות עדיין רשומות או בבחינה."
                            + (" התקופה האחרונה חלקית." if p_last_partial else "")),
            "classes_note": (f"{_int(n_cls)} בקשות לפי סוג המוצר בסיווג לוקרנו — {TOP_CLASSES} הסוגים הגדולים."
                             + (f" {_int(n - n_cls)} בקשות ללא סיווג תקין אינן נכללות." if n - n_cls else "")),
            "heat_note": (f"שיעור כל אחד מ-{HEAT_CLASSES} הסוגים הגדולים מבין הבקשות בכל תקופת הגשה; "
                          f"גוון כהה = שיעור גבוה." + (" התקופה האחרונה חלקית." if p_last_partial else "")),
            "offices_note": (f"{_int(n_prio)} בקשות שבהן נדרש דין קדימה, לפי המדינה או המשרד של הבקשה "
                             f"המקורית. ״האיחוד האירופי״ — משרד הקניין הרוחני של האיחוד (EUIPO); ״הגשה בינלאומית״ — בקשה לפי הסדר האג באמצעות WIPO."),
            "otrend_note": ("שיעור הבקשות עם דין קדימה מחו״ל מכלל הבקשות בכל תקופה, לפי מקור דין הקדימה."
                            + (" התקופה האחרונה חלקית." if p_last_partial else "")),
            "top_note": (f"{TOP_APPLICANTS} המגישים עם מספר הבקשות הגדול ביותר, לפי קוד המבקש במאגר — "
                         f"חברות קשורות בקודים שונים נספרות בנפרד. בגוון כהה: מגישים שרוב בקשותיהם נשענות "
                         f"על דין קדימה מחו״ל."
                         + (f" {_int(n_noappl)} בקשות ללא קוד מבקש אינן נכללות." if n_noappl else "")),
            "prolific_note": (f"{_int(n_applicants)} המגישים לפי מספר הבקשות שכל אחד מהם הגיש "
                              f"(סקלה לוגריתמית)."),
            "lag_note": (f"חציון החודשים מהגשת הבקשה ועד פרסומה, לפי שנת ההגשה; הרצועה מציגה את הרבעון "
                         f"התחתון והעליון."
                         + (f" {_int(lag_bad)} בקשות עם פער שלילי או חריג אינן נכללות." if lag_bad else "")),
            "prio_note": (f"{_int(n_plag)} בקשות עם דין קדימה, לפי מספר החודשים בין הבקשה המקורית להגשה "
                          f"בישראל."),
            "words_note": (f"המילה הראשונה בשם העברי של העיצוב, ב-{TOP_WORDS} השכיחות; בטבלה — סוג הלוקרנו "
                           f"הנפוץ של כל מילה."),
            "years_aria": f"עמודות וקו: בקשות לרישום עיצוב לפי שנת הגשה, מ-{first_year} עד {last_year}.",
            "status_aria": "עמודות אופקיות: בקשות לפי מצב הרישום כיום.",
            "cohort_aria": "עמודות מוערמות באחוזים: מצב הבקשות כיום לפי תקופת ההגשה.",
            "classes_aria": f"עמודות אופקיות: {TOP_CLASSES} סוגי לוקרנו הגדולים.",
            "heat_aria": f"מפת חום: שיעור {HEAT_CLASSES} סוגי לוקרנו הגדולים לפי תקופת הגשה.",
            "offices_aria": "עמודות אופקיות: בקשות עם דין קדימה לפי מקור.",
            "otrend_aria": "עמודות מוערמות: שיעור הבקשות עם דין קדימה מחו״ל לפי מקור ותקופה.",
            "top_aria": f"עמודות אופקיות: {TOP_APPLICANTS} המגישים הגדולים.",
            "prolific_aria": "עמודות: מגישים לפי מספר הבקשות שהגישו.",
            "lag_aria": "קו ורצועה: חציון החודשים מהגשה לפרסום לפי שנת הגשה.",
            "prio_aria": "עמודות: בקשות עם דין קדימה לפי חודשים מהבקשה המקורית.",
            "words_aria": f"עמודות אופקיות: {TOP_WORDS} המילים השכיחות בשמות העיצובים.",
        },
    }
