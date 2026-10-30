"""דיווח על תקלה לידיעת הציבור: public fault reports from factories whose
chimneys are under continuous emission monitoring (Ministry of Environmental
Protection). One row per report: site, region, chimney, monitored pollutant,
fault start/end dates, fault type, a short description and free-text remarks.

The log is small (tens of rows) and dominated by a handful of sites, so the
page is about who reports, what fails, how long it lasts and how fast it is
reported. Rows from the ministry's test district ("מחוז לבדיקות") are portal
test entries; they are excluded and the exclusion is disclosed.

Remarks are free text written by the factories. The page never quotes them;
it only (a) tags each report with cause themes found by keyword and (b) reads
the stated oxidizer/treatment downtime ("סה"כ X שעות") where the factory gave
one.
"""
import re

import pandas as pd

TEST_REGION = "מחוז לבדיקות"  # the ministry's test district
TEST_SITE = "בדיקות פורטל"    # test sites ("תת בדיקות פורטל תעשיה")
MIN_FAULT_YEAR = 2000         # fault dates before this, or after the last report year + 1, are typos
OTHER = "אחר"
UNSET = "לא צוין"
TOP_SITES = 8
TOP_POLLUTANTS = 8
TOP_CHIMNEYS = 10
RECENT_ROWS = 10
DOWNTIME_ROWS = 20
MONTHLY_MAX_MONTHS = 48       # longer spans switch the timeline to quarters
CONCENTRATION_SHARE = 0.3     # one site this share of reports is a finding
LEADER_SHARE = 0.3            # leading fault type / pollutant / theme
TREND_MIN = 3                 # min reports in the comparison window
TREND_CHANGE = 0.2            # ±20% counts as a real change
FAST_DAYS = 2                 # "reported within N days"
MULTI_DAY = 2                 # events lasting this many days or more

# Cause themes, matched (as regexes) in the fault description + remarks. A
# report can carry several themes; one with none is "ללא נושא מזוהה".
THEMES = [
    ("הפסקת חשמל", ["חשמל"]),
    ("מדי LEL וכיול", ["LEL", "כיול"]),
    ("קירור וצ'ילר", ["קירור", "צ'ילר", "צילר", "מעבים"]),
    ("ברזים ומגופים", ["ברז(?!ל)", "מגוף"]),  # not "ברזל" (iron)
    ("אספקת מים", ["אספקת מים", "מי רשת", "מי תהליך", "מים ממקורות"]),
    ("הדממה או אחזקה מתוכננת", ["הדממ", "מתוכננ", "אחזקתי", "עבודות אחזקה"]),
    ("לפיד", ["לפיד"]),
    ("מעקף במתקן הטיפול", ["מעקף"]),
    ("מדחסים ועליית לחץ", ["מדחס", "עליית לחץ"]),
]
NO_THEME = "ללא נושא מזוהה"

LAG_BUCKETS = [(0, 1, "עד יום"), (2, 3, "2-3 ימים"), (4, 7, "4-7 ימים"),
               (8, 14, "8-14 ימים"), (15, None, "15 ימים ומעלה")]
DUR_BUCKETS = [(1, 1, "יום אחד"), (2, 3, "2-3 ימים"), (4, 7, "4-7 ימים"),
               (8, None, "8 ימים ומעלה")]

HE_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

HOURS_RE = re.compile(r"סה[\"״'’]{1,2}כ\s*([0-9]+(?:\.[0-9]+)?)\s*שעות")
ABBR_RE = re.compile(r"\(([A-Za-z0-9]{2,10})\)")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _fmt_hours(h):
    return f"{h:,.1f}".rstrip("0").rstrip(".")


def _b(name):
    """Hebrew prefix "ב": glued before a Hebrew word, hyphenated before digits/Latin."""
    return f"ב{name}" if re.match(r"[\u0590-\u05FF]", str(name)) else f"ב-{name}"


def _days(v):
    return "יום אחד" if v == 1 else f"{v:g} ימים" if isinstance(v, float) else f"{_int(v)} ימים"


def _date(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _pollutant(name):
    """'כלל פחמן אורגני (TOC)' and 'TOC' are the same pollutant."""
    m = ABBR_RE.search(name)
    return m.group(1) if m else name


def _themes(text):
    out = []
    for label, keys in THEMES:
        if any(re.search(k, text) for k in keys):
            out.append(label)
    return out or [NO_THEME]


def _bucket(v, buckets):
    for lo, hi, label in buckets:
        if v >= lo and (hi is None or v <= hi):
            return label
    return None


def _prepare(df):
    out = df.copy()
    for c in out.columns:
        out[c] = out[c].astype(str).str.strip()
    test = ((out["SiteRegion"] == TEST_REGION)
            | out["SiteName"].str.contains(TEST_SITE, regex=False))
    n_test = int(test.sum())
    out = out[~test].copy()
    out["site"] = out["SiteName"].replace("", UNSET)
    out["region"] = out["SiteRegion"].replace("", UNSET)
    out["chimney"] = out["ChimneyName"].replace("", UNSET)
    out["pollutant"] = out["PollutingName"].replace("", UNSET).map(_pollutant)
    out["fault"] = out["FaultType"].replace("", UNSET)
    out["reported"] = pd.to_datetime(out["ReportActualDate"], format="%d/%m/%Y %I:%M:%S %p",
                                     errors="coerce")
    out["start"] = pd.to_datetime(out["StartDate"], format="%d/%m/%Y", errors="coerce")
    out["end"] = pd.to_datetime(out["EndDate"], format="%d/%m/%Y", errors="coerce")
    max_year = out["reported"].dt.year.max()
    hi_year = (int(max_year) + 1) if pd.notna(max_year) else None
    bad_any = pd.Series(False, index=out.index)
    for c in ("start", "end"):
        y = out[c].dt.year
        bad = out[c].notna() & ((y < MIN_FAULT_YEAR) | ((y > hi_year) if hi_year else False))
        out.loc[bad, c] = pd.NaT
        bad_any |= bad
    n_bad_dates = int(bad_any.sum())
    out["event"] = out["start"].fillna(out["reported"].dt.normalize())
    lag = (out["reported"].dt.normalize() - out["start"]).dt.days
    out["lag"] = lag.where(lag >= 0)
    dur = (out["end"] - out["start"]).dt.days + 1
    out["dur"] = dur.where(dur >= 1)
    text = out["FaultTypeDesc"] + " " + out["Remarks"]
    out["themes"] = text.map(_themes)
    hours = out["Remarks"].map(lambda s: [float(h) for h in HOURS_RE.findall(s)])
    out["hours"] = hours.map(lambda hs: round(sum(hs), 2) if hs else None)
    out["desc"] = out["FaultTypeDesc"].where(out["FaultTypeDesc"] != "", out["fault"])
    out = out.sort_values(["event", "reported", "site", "chimney", "pollutant", "desc"],
                          kind="stable", na_position="first").reset_index(drop=True)
    return out, n_test, n_bad_dates, hi_year


def _timeline(d):
    dated = d[d["event"].notna()]
    if dated.empty:
        return {"x": [], "y": [], "unit": "חודש"}, []
    first, last = dated["event"].min(), dated["event"].max()
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    if months <= MONTHLY_MAX_MONTHS:
        per = dated["event"].dt.to_period("M")
        rng = pd.period_range(first.to_period("M"), last.to_period("M"), freq="M")
        lab = lambda p: f"{HE_MONTHS[p.month - 1]} {p.year}"
        unit = "חודש"
    else:
        per = dated["event"].dt.to_period("Q")
        rng = pd.period_range(first.to_period("Q"), last.to_period("Q"), freq="Q")
        lab = lambda p: f"רבעון {p.quarter} {p.year}"
        unit = "רבעון"
    counts = per.value_counts()
    x = [lab(p) for p in rng]
    y = [int(counts.get(p, 0)) for p in rng]
    table = [{"name": x[i], "count": _int(y[i])} for i in range(len(x)) if y[i] > 0]
    return {"x": x, "y": y, "unit": unit}, table


def _top(series, n):
    vc = _ranked(series)
    names = list(vc.index[:n])
    vals = [int(v) for v in vc.values[:n]]
    rest = int(vc.values[n:].sum())
    if rest:
        names.append(OTHER)
        vals.append(rest)
    return names, vals


def compute(frames):
    raw = frames["reports"]
    d, n_test, n_bad_dates, hi_fault_year = _prepare(raw)
    n = len(d)
    if n == 0:
        raise ValueError("no non-test reports")
    labels, tables, charts, kpis = {}, {}, {}, {}

    # ---- timeline
    tl, tl_table = _timeline(d)
    charts["timeline"] = tl
    tables["timeline"] = tl_table
    dated = d[d["event"].notna()]
    first, last = dated["event"].min(), dated["event"].max()
    years = f"{first.year}–{last.year}" if first.year != last.year else f"{first.year}"
    labels["years_text"] = (f"{first.year}-{last.year}" if first.year != last.year
                            else f"{first.year}")
    peak_i = max(range(len(tl["y"])), key=lambda i: (tl["y"][i], -i))
    labels["timeline_lede"] = (
        f"מספר הדיווחים לפי {tl['unit']} תחילת התקלה, {HE_MONTHS[first.month - 1]} {first.year} "
        f"עד {HE_MONTHS[last.month - 1]} {last.year}. השיא: {tl['x'][peak_i]}, "
        f"עם {_int(tl['y'][peak_i])} דיווחים."
    )
    labels["timeline_aria"] = f"תרשים עמודות: דיווחי תקלות לפי {tl['unit']}"

    # ---- sites (stacked by fault type)
    site_names, site_vals = _top(d["site"], TOP_SITES)
    faults_rank = list(_ranked(d["fault"]).index)
    site_key = d["site"].where(d["site"].isin(site_names[:TOP_SITES]), OTHER)
    ct = pd.crosstab(site_key, d["fault"])
    charts["sites"] = {
        "names": site_names,
        "series": [{"name": f, "data": [int(ct.at[s, f]) if s in ct.index else 0
                                        for s in site_names]} for f in faults_rank],
    }
    site_rows = []
    for name, cnt in zip(site_names, site_vals):
        g = d[site_key == name]
        site_rows.append({
            "name": name, "count": _int(cnt), "share": _pct(cnt / n),
            "chimneys": _int(g["chimney"].nunique()),
            "last": _date(g["event"].max()) if g["event"].notna().any() else UNSET,
        })
    tables["sites"] = site_rows
    top_site, top_cnt = site_names[0], site_vals[0]
    top_share = top_cnt / n
    labels["sites_lede"] = (
        f"{top_site} הגיש {_int(top_cnt)} מתוך {_int(n)} הדיווחים ({_pct(top_share)}). "
        f"הצבעים מראים את סוג התקלה שדווח."
    )
    labels["sites_aria"] = "תרשים עמודות מוערמות: דיווחים לפי מפעל וסוג תקלה"

    # ---- fault types
    fvc = _ranked(d["fault"])
    charts["faults"] = {"names": list(fvc.index), "values": [int(v) for v in fvc.values]}
    tables["faults"] = [{"name": k, "count": _int(v), "share": _pct(v / n)}
                        for k, v in fvc.items()]
    other_desc = d.loc[(d["fault"] == OTHER) & (d["FaultTypeDesc"] != ""), "FaultTypeDesc"]
    labels["faults_lede"] = (
        f"{fvc.index[0]} הוא סוג התקלה הנפוץ ({_int(fvc.iloc[0])} דיווחים, {_pct(fvc.iloc[0] / n)})."
        + (f" ב-{_int(len(other_desc))} דיווחים מסוג \"{OTHER}\" המפעל פירט את הסיבה, "
           f"והיא נכללת בנושאי התקלה שבהמשך." if len(other_desc) and OTHER in fvc.index else "")
    )
    labels["faults_aria"] = "תרשים טבעת: דיווחים לפי סוג תקלה"

    # ---- pollutants
    p_names, p_vals = _top(d["pollutant"], TOP_POLLUTANTS)
    charts["pollutants"] = {"names": p_names, "values": p_vals}
    tables["pollutants"] = [{"name": k, "count": _int(v), "share": _pct(v / n)}
                            for k, v in zip(p_names, p_vals)]
    # renamed rows whose pollutant really has more than one spelling in the data
    raw = d["PollutingName"]
    spellings = raw[raw != ""].groupby(d["pollutant"]).nunique()
    merged = int(((raw != "") & (raw != d["pollutant"])
                  & d["pollutant"].map(spellings).gt(1)).sum())
    labels["pollutants_lede"] = (
        f"המזהם שהניטור הרציף שלו הושפע מהתקלה. {p_names[0]} מוביל עם {_int(p_vals[0])} דיווחים."
        + (f" שמות שונים של אותו מזהם אוחדו לפי הקיצור שבסוגריים ({_int(merged)} דיווחים)."
           if merged else "")
    )
    labels["pollutants_aria"] = "תרשים עמודות: דיווחים לפי מזהם"

    # ---- cause themes
    th = d["themes"].explode()
    tvc = _ranked(th)
    order = [t for t, _ in THEMES if t in tvc.index] + ([NO_THEME] if NO_THEME in tvc.index else [])
    order = sorted(order, key=lambda t: (t == NO_THEME, -int(tvc[t]), order.index(t)))
    charts["themes"] = {"names": order, "values": [int(tvc[t]) for t in order]}
    tables["themes"] = [{"name": t, "count": _int(tvc[t]), "share": _pct(tvc[t] / n)}
                        for t in order]
    labels["themes_lede"] = (
        "נושאים שזוהו לפי מילות מפתח בתיאור התקלה ובהערות המפעל. "
        "דיווח אחד יכול להופיע ביותר מנושא אחד, ולכן סכום העמודות גדול ממספר הדיווחים."
    )
    labels["themes_aria"] = "תרשים עמודות: דיווחים לפי נושא התקלה"

    # ---- reporting lag
    lag = d["lag"].dropna()
    lag_b = lag.map(lambda v: _bucket(v, LAG_BUCKETS))
    lvc = lag_b.value_counts()
    charts["lag"] = {"names": [b[2] for b in LAG_BUCKETS],
                     "values": [int(lvc.get(b[2], 0)) for b in LAG_BUCKETS]}
    tables["lag"] = [{"name": b[2], "count": _int(lvc.get(b[2], 0))} for b in LAG_BUCKETS]
    no_lag = n - len(lag)
    med_lag = float(lag.median()) if len(lag) else None
    labels["lag_lede"] = (
        f"כמה ימים עברו מתחילת התקלה ועד שהדיווח הוגש. החציון: {_days(med_lag)}."
        if med_lag is not None else "אין דיווחים עם תאריכים תקינים."
    ) + (f" {_int(no_lag)} דיווחים ללא תאריך תקין אינם נכללים." if no_lag else "")
    labels["lag_aria"] = "תרשים עמודות: הזמן מתחילת התקלה עד הדיווח"

    # ---- duration
    dur = d["dur"].dropna()
    dur_b = dur.map(lambda v: _bucket(v, DUR_BUCKETS))
    dvc = dur_b.value_counts()
    no_end = n - len(dur)
    dur_names = [b[2] for b in DUR_BUCKETS] + ([UNSET] if no_end else [])
    dur_vals = [int(dvc.get(b[2], 0)) for b in DUR_BUCKETS] + ([no_end] if no_end else [])
    charts["duration"] = {"names": dur_names, "values": dur_vals}
    tables["duration"] = [{"name": a, "count": _int(b)} for a, b in zip(dur_names, dur_vals)]
    labels["duration_lede"] = (
        "משך התקלה בימים, מתאריך ההתחלה עד תאריך הסיום שדווח (כולל שניהם)."
        + (f" ב-{_int(no_end)} דיווחים לא צוין תאריך סיום תקין." if no_end else "")
    )
    labels["duration_aria"] = "תרשים עמודות: משך התקלה בימים"

    # ---- stated downtime hours
    hd = d[d["hours"].notna()].copy()
    hd = hd.sort_values(["event", "reported", "site", "chimney"], kind="stable")
    hd_tail = hd.tail(DOWNTIME_ROWS)
    charts["downtime"] = {
        "x": [_date(t) for t in hd_tail["event"]],
        "y": [float(h) for h in hd_tail["hours"]],
        "site": list(hd_tail["site"]),
    }
    tables["downtime"] = [{"date": _date(r.event), "site": r.site, "hours": _fmt_hours(r.hours)}
                          for r in hd_tail.itertuples()]
    charts["has_downtime"] = len(hd) > 0
    if len(hd):
        labels["downtime_lede"] = (
            f"ב-{_int(len(hd))} דיווחים המפעל ציין את משך ההשבתה בשעות (סה\"כ "
            f"{_fmt_hours(hd['hours'].sum())} שעות). "
            + (f"מוצגים {_int(len(hd_tail))} הדיווחים האחרונים."
               if len(hd) > len(hd_tail) else "מוצגים כל הדיווחים האלה.")
        )
    else:
        labels["downtime_lede"] = ""
    labels["downtime_aria"] = "תרשים עמודות: שעות השבתה שדווחו בכל דיווח"

    # ---- region
    rvc = _ranked(d["region"])
    charts["regions"] = {"names": list(rvc.index), "values": [int(v) for v in rvc.values],
                         "sites": [int(d.loc[d["region"] == r, "site"].nunique()) for r in rvc.index]}
    tables["regions"] = [{"name": r, "count": _int(v), "sites": _int(s), "share": _pct(v / n)}
                         for r, v, s in zip(rvc.index, rvc.values, charts["regions"]["sites"])]
    labels["regions_lede"] = (
        f"אזור המפעל כפי שנרשם בדיווח. {rvc.index[0]}: {_int(rvc.iloc[0])} דיווחים "
        f"מ-{_int(charts['regions']['sites'][0])} מפעלים."
    )
    labels["regions_aria"] = "תרשים עמודות: דיווחים לפי אזור"

    # ---- chimneys
    ck = (d["site"] + "|" + d["chimney"])
    cvc = _ranked(ck)
    c_rows = [{"chimney": k.split("|", 1)[1], "site": k.split("|", 1)[0], "count": _int(v)}
              for k, v in cvc.iloc[:TOP_CHIMNEYS].items()]
    tables["chimneys"] = c_rows
    n_chim = len(cvc)
    labels["chimneys_lede"] = (
        f"{_int(n_chim)} ארובות ומוקדי פליטה שונים הופיעו בדיווחים."
        + (f" מוצגים {_int(TOP_CHIMNEYS)} עם הכי הרבה דיווחים." if n_chim > TOP_CHIMNEYS else "")
    )
    charts["chimneys"] = {"names": [f"{r['chimney']} ({r['site']})" for r in c_rows][::-1],
                          "values": [int(v) for v in cvc.iloc[:TOP_CHIMNEYS].values][::-1]}
    labels["chimneys_aria"] = "תרשים עמודות: ארובות עם הכי הרבה דיווחים"

    # ---- recent reports
    rec = d.sort_values(["reported", "event", "site", "chimney"], kind="stable",
                        na_position="first").tail(RECENT_ROWS).iloc[::-1]
    tables["recent"] = [{
        "date": _date(r.event) if pd.notna(r.event) else UNSET,
        "site": r.site, "chimney": r.chimney, "pollutant": r.pollutant, "desc": r.desc,
    } for r in rec.itertuples()]
    labels["recent_lede"] = f"{_int(len(rec))} הדיווחים האחרונים שהוגשו, מהחדש לישן."

    # ---- KPIs
    n_sites = d["site"].nunique()
    kpis["reports"] = {"value": n, "display": _int(n), "tone": "brand"}
    kpis["sites"] = {"value": int(n_sites), "display": _int(n_sites), "tone": "brand"}
    kpis["top_share"] = {"value": round(top_share, 4), "display": _pct(top_share),
                         "tone": "warn" if top_share >= 0.5 else "info"}
    if med_lag is not None:
        kpis["lag"] = {"value": med_lag, "display": f"{med_lag:g}",
                       "tone": "ok" if med_lag <= FAST_DAYS else ("warn" if med_lag <= 7 else "danger")}
    kpis["span"] = {"value": years, "display": years, "tone": "brand"}
    labels["kpi_reports"] = "דיווחי תקלות במאגר"
    labels["kpi_sites"] = "מפעלים שדיווחו"
    labels["kpi_top_share"] = f"מהדיווחים הגיעו מהמפעל המוביל"
    labels["kpi_lag"] = "ימים (חציון) מתחילת התקלה ועד הדיווח"
    labels["kpi_span"] = "שנות הדיווח"

    labels["test_note"] = (
        (f"{_int(n_test)} רשומות בדיקה של מערכת הדיווח (מחוז לבדיקות) אינן נכללות בניתוח."
         if n_test else "")
        + (" " if n_test and n_bad_dates else "")
        + ((f"ב-{_int(n_bad_dates)} דיווחים תאריך התקלה אינו סביר (לפני {MIN_FAULT_YEAR} "
            f"או אחרי {hi_fault_year}) ולא נכלל בחישובי התאריכים." if n_bad_dates > 1 else
            f"בדיווח אחד תאריך התקלה אינו סביר (לפני {MIN_FAULT_YEAR} או אחרי {hi_fault_year}) "
            "ולא נכלל בחישובי התאריכים.") if n_bad_dates else "")
    )

    # ---- insights
    ins = []

    def add(iid, text):
        if text:
            ins.append({"id": iid, "text_he": text})

    site_rank = _ranked(d["site"])
    second_cnt = int(site_rank.iloc[1]) if len(site_rank) > 1 else 0
    others = ("מהמפעל האחר" if n_sites == 2
              else f"מכל {_int(n_sites - 1)} המפעלים האחרים יחד")
    if top_share >= CONCENTRATION_SHARE and len(site_names) > 1:
        if top_cnt > n - top_cnt:
            add("concentration",
                f"הדיווחים מרוכזים: {top_site} הגיש {_int(top_cnt)} מתוך {_int(n)} הדיווחים "
                f"({_pct(top_share)}), יותר {others}.")
        elif top_cnt > second_cnt:
            add("concentration",
                f"{top_site} הגיש {_int(top_cnt)} מתוך {_int(n)} הדיווחים ({_pct(top_share)}), "
                f"יותר מכל מפעל אחר.")

    if (fvc.index[0] != OTHER and fvc.iloc[0] / n >= LEADER_SHARE
            and (len(fvc) == 1 or fvc.iloc[0] > fvc.iloc[1])):
        add("fault_leader",
            f"\"{fvc.index[0]}\" הוא סוג התקלה הנפוץ: {_int(fvc.iloc[0])} דיווחים "
            f"({_pct(fvc.iloc[0] / n)}).")

    # year-over-year on the same calendar window (Jan..last month in the data)
    ly, lm, ld = last.year, last.month, last.day
    md = dated["event"].dt.month * 100 + dated["event"].dt.day
    in_win = md <= lm * 100 + ld
    cur = int(((dated["event"].dt.year == ly) & in_win).sum())
    prev = int(((dated["event"].dt.year == ly - 1) & in_win).sum())
    if prev >= TREND_MIN and cur >= 1:
        ch = (cur - prev) / prev
        window = f"מתחילת {ly} ועד {ld}.{lm}.{ly} (תאריך התקלה האחרונה במאגר)"
        same = f"באותה תקופה ב-{ly - 1}"
        if ch <= -TREND_CHANGE:
            add("trend", f"ירידה במספר הדיווחים: {_int(cur)} תקלות {window}, "
                         f"לעומת {_int(prev)} {same} ({_pct(-ch)} פחות).")
        elif ch >= TREND_CHANGE:
            add("trend", f"עלייה במספר הדיווחים: {_int(cur)} תקלות {window}, "
                         f"לעומת {_int(prev)} {same} ({_pct(ch)} יותר).")
        else:
            add("trend", f"מספר הדיווחים יציב: {_int(cur)} תקלות {window}, "
                         f"לעומת {_int(prev)} {same}.")

    if len(lag) >= 3:
        fast = int((lag <= FAST_DAYS).sum())
        add("lag", f"{_int(fast)} מתוך {_int(len(lag))} הדיווחים ({_pct(fast / len(lag))}) "
                   f"הוגשו עד {FAST_DAYS} ימים מתחילת התקלה. הדיווח האיטי ביותר הוגש "
                   f"{_days(int(lag.max()))} אחריה.")

    if len(hd) >= 3:
        mx = hd.sort_values(["hours", "event"], ascending=[False, True], kind="stable").iloc[0]
        add("downtime", f"ב-{_int(len(hd))} דיווחים צוין משך ההשבתה, ובסך הכול "
                        f"{_fmt_hours(hd['hours'].sum())} שעות. הסך הגבוה ביותר בדיווח אחד: "
                        f"{_fmt_hours(mx['hours'])} שעות, {_b(mx['site'])} (תקלה מ-{_date(mx['event'])}).")

    real_themes = [t for t in order if t != NO_THEME]
    clear = len(real_themes) == 1 or (len(real_themes) > 1
                                      and tvc[real_themes[0]] > tvc[real_themes[1]])
    if real_themes and clear and tvc[real_themes[0]] / n >= LEADER_SHARE / 2:
        t0 = real_themes[0]
        add("theme", f"הנושא החוזר ביותר בתיאורי התקלות הוא {t0}: "
                     f"{_int(tvc[t0])} דיווחים ({_pct(tvc[t0] / n)}).")

    multi = d[d["dur"] >= MULTI_DAY]
    if len(multi):
        lg = multi.sort_values(["dur", "event"], ascending=[False, True], kind="stable").iloc[0]
        if len(multi) == 1:
            add("duration", f"תקלה אחת התפרשה על פני יומיים קלנדריים או יותר: "
                            f"{_days(int(lg['dur']))} {_b(lg['site'])}, מ-{_date(lg['start'])} "
                            f"עד {_date(lg['end'])} (כולל).")
        else:
            add("duration", f"{_int(len(multi))} תקלות התפרשו על פני יומיים קלנדריים או יותר. "
                            f"הארוכה ביותר: {_days(int(lg['dur']))} {_b(lg['site'])}, "
                            f"מ-{_date(lg['start'])} עד {_date(lg['end'])} (כולל).")

    # ---- summary (meta description, ≤155 chars)
    summary = (f"דיווחי מפעלים על תקלות בארובות בניטור רציף של פליטות: {_int(n)} דיווחים "
               f"מ-{_int(n_sites)} מפעלים, {labels['years_text']}.")
    tail = f" המוביל: {top_site}."
    if len(summary + tail) <= 155:
        summary += tail
    labels["lede"] = (
        f"מפעלים שארובותיהם מחוברות לניטור רציף של פליטות מדווחים למשרד להגנת הסביבה "
        f"על תקלה שעלולה להשפיע על הפליטה או על המדידה, והדיווח מתפרסם לציבור. "
        f"במאגר {_int(n)} דיווחים מ-{_int(n_sites)} מפעלים, {labels['years_text']}."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["זיהום אוויר", "ניטור רציף", "ארובות", "תעשייה", "דיווחי תקלות"],
            "related_ids": [
                "5bf900d4-819a-4991-8c5a-4566e1a4af24",
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
                "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                "780f8522-db2b-4147-b2ac-554aafaf1c1a",
                "2a4a9360-ebb1-470a-bb88-d2ba942bf561",
            ],
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": ins,
    }
