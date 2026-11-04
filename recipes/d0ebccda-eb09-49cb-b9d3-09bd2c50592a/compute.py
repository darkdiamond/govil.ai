"""רשימת מבקרים ותחזוקאי מטפים מורשים (כבאות והצלה): registry of extinguisher
auditors and maintainers authorised under Israeli Standard 129.

One table, one row per authorisation: type (auditor / maintainer), the
maintainer's company and business contacts, first/last name, authorisation
date (dd/mm/yyyy, a few malformed), status (authorised / not authorised).
Every number on the page is computed here.
"""
import re

import pandas as pd
from govlib import fmt, frame

AUDITOR = "מבקר מטפים"
MAINTAINER = "תחזוקאי מטפים"
OK_STATUS = "מורשה"
NOT_OK = "לא מורשה"
NO_ADDR = "ללא כתובת"
UNKNOWN_CITY = "יישוב לא זוהה"

# Localities searched for in the free-text company address (word-bounded,
# longest first). A generic national list, not the data's values: a new
# address in an unlisted locality falls into UNKNOWN_CITY, disclosed.
CITIES = [
    "תל אביב", "ירושלים", "חיפה", "ראשון לציון", "פתח תקווה", "אשדוד", "נתניה",
    "באר שבע", "בני ברק", "חולון", "רמת גן", "אשקלון", "רחובות", "בת ים",
    "בית שמש", "כפר סבא", "הרצליה", "חדרה", "מודיעין", "נצרת", "לוד", "רמלה",
    "רעננה", "הוד השרון", "רהט", "גבעתיים", "קרית אתא", "נהריה", "קרית גת",
    "אום אל-פחם", "אילת", "ראש העין", "עפולה", "נס ציונה", "עכו", "אלעד",
    "רמת השרון", "כרמיאל", "יבנה", "טבריה", "קרית מוצקין", "קרית ביאליק",
    "קרית ים", "קרית אונו", "קרית שמונה", "נוף הגליל", "נשר", "דימונה",
    "אור יהודה", "צפת", "שפרעם", "טייבה", "סחנין", "יהוד", "אופקים", "שדרות",
    "נתיבות", "מעלות", "ערד", "אור עקיבא", "זכרון יעקב", "בנימינה", "גן יבנה",
    "קצרין", "מגדל העמק", "יקנעם", "טירת כרמל", "קרית מלאכי", "באר יעקב",
    "גדרה", "מזכרת בתיה", "כפר יונה", "אריאל", "מעלה אדומים", "ביתר עילית",
    "מודיעין עילית", "קרית ענבים", "להבות הבשן", "גן נר", "שמעה", "אליקים",
    "דגניה", "קדמת גליל", "דייר אל-אסד", "עתלית", "כפר קאסם", "באקה אל-גרביה",
]
CITY_ALIASES = {"פתח תקוה": "פתח תקווה", "פ\"ת": "פתח תקווה", "ת\"א": "תל אביב",
                "יהוד-מונוסון": "יהוד", "ב\"ש": "באר שבע", "ראשל\"צ": "ראשון לציון"}

NOTES = [
    "רשימת המבקרים ותחזוקאי המטפים המורשים המפורסמת בזאת מפרטת את פרטי התחזוקאים ומבקרי המטפים העומדים בתקן ישראלי 129 חלק 1 ותקן ישראלי 129 חלק 2 (להלן, יחד: \"ת\"י 129\"), ממועד פרסום נוהל הגשה וטיפול בבקשה להרשאה של מבקר שנתי / תחזוקאי מטפים מאושר (12.4.2021).",
    "מבקר או תחזוקאי מטפים שניתנה לו הרשאה במועד שלאחר פרסום הנוהל (13.4.2021 ואילך) ושמו אינו נכלל ברשימה, רשאי לפנות לרשות הארצית לכבאות והצלה בדוא\"ל, בצירוף ההרשאה שניתנה בעניינו.",
    "מבקר או תחזוקאי מטפים שניתנה לו הרשאה עד ליום פרסום הנוהל (עד ליום 12.4.2021) ושמו אינו נכלל ברשימה, רשאי להגיש בקשת הרשאה למבקר שנתי / תחזוקאי מטפים, בהתאם להוראות הנוהל.",
    "מבקר או תחזוקאי המעוניין ששמו יוסר מהרשימה המפורסמת באתר רשאי לפנות לרשות הארצית לכבאות והצלה בדוא\"ל.",
    "יש להקפיד להתעדכן בכלל הוראות ת\"י 129, לרבות לעניין תנאי ההסמכה.",
]

MIN_YEAR_ROWS = 3
MAX_YEAR_GAP = 2  # a sparse year 3+ years from the core span = 2+ empty years between

_HEB = "א-ת"
_CITY_RES = None


def _city_res():
    global _CITY_RES
    if _CITY_RES is None:
        names = {c: c for c in CITIES}
        names.update(CITY_ALIASES)
        keys = sorted(names, key=lambda k: (-len(k), k))
        _CITY_RES = [(re.compile(rf"(?<![{_HEB}]){re.escape(k)}(?![{_HEB}])"), names[k]) for k in keys]
    return _CITY_RES


def city_of(addr: str) -> str:
    a = frame.clean(addr).replace("״", "\"").replace("''", "\"")
    if not a:
        return NO_ADDR
    for rx, name in _city_res():
        if rx.search(a):
            return name
    return UNKNOWN_CITY


_CO_JUNK = re.compile(r"בע[\"'״]*מ|\bחברת\s+|[^\wא-ת]")


def company_key(name: str) -> str:
    n = frame.clean(name).replace("''", "\"")
    return _CO_JUNK.sub("", n)


def outlier_years(d: pd.Series) -> set:
    """Years that are typos, not history: a year with fewer than
    MIN_YEAR_ROWS dated rows that sits more than MAX_YEAR_GAP years from
    every well-populated year (e.g. 20/01/2062 in a 2021-2026 registry).
    Data-relative only; with no well-populated year nothing is dropped."""
    counts = d.dropna().dt.year.value_counts()
    core = [int(y) for y, c in counts.items() if c >= MIN_YEAR_ROWS]
    if not core:
        return set()
    return {int(y) for y, c in counts.items()
            if c < MIN_YEAR_ROWS and min(abs(int(y) - k) for k in core) > MAX_YEAR_GAP}


def plural(n, one, many):
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def compute(frames):
    df = frames["registry"].copy()
    df["t"] = frame.clean_series(df["type"])
    df["st"] = frame.clean_series(df["status"])
    df["co_raw"] = frame.clean_series(df["company"]).str.replace("''", "\"", regex=False)
    df["fn"] = frame.clean_series(df["first_name"])
    df["ln"] = frame.clean_series(df["last_name"])
    df["name"] = (df["fn"] + " " + df["ln"]).str.strip()
    df["d"] = pd.to_datetime(frame.clean_series(df["date"]), format="%d/%m/%Y", errors="coerce")
    n_malformed = int(df["d"].isna().sum())
    df["d"] = df["d"].where(~df["d"].dt.year.isin(outlier_years(df["d"])))
    n_far_date = int(df["d"].isna().sum()) - n_malformed
    df["city"] = df["adress"].map(city_of)

    n = len(df)
    is_aud = df["t"] == AUDITOR
    is_mnt = df["t"] == MAINTAINER
    n_aud, n_mnt = int(is_aud.sum()), int(is_mnt.sum())
    n_other_type = n - n_aud - n_mnt
    n_not = int((df["st"] == NOT_OK).sum())
    n_ok = int((df["st"] == OK_STATUS).sum())

    types = frame.ranked(df["t"].replace("", "לא צוין"))
    type_order = [AUDITOR, MAINTAINER] + [t for t in types.index if t not in (AUDITOR, MAINTAINER)]
    type_order = [t for t in type_order if t in types.index]

    # ---- companies (normalised key, displayed by the most common spelling) ----
    co = df[df["co_raw"] != ""].copy()
    co["key"] = co["co_raw"].map(company_key)
    co = co[co["key"] != ""]
    spell = (co.groupby(["key", "co_raw"]).size().reset_index(name="c")
             .sort_values(["key", "c", "co_raw"], ascending=[True, False, True], kind="stable")
             .drop_duplicates("key"))
    disp = dict(zip(spell["key"], spell["co_raw"]))
    co["company_name"] = co["key"].map(disp)
    n_spellings = int(co["co_raw"].nunique())
    co_counts = frame.ranked(co["company_name"])
    n_companies = len(co_counts)
    mnt_with_co = int((is_mnt & (df["co_raw"] != "")).sum())

    # ---- dates ----
    dated = df[df["d"].notna()].copy()
    n_bad_date = int(n - len(dated))
    dated["y"] = dated["d"].dt.year.astype(int)
    dated["m"] = dated["d"].dt.month.astype(int)
    last_d = dated["d"].max() if len(dated) else None
    first_d = dated["d"].min() if len(dated) else None
    years = sorted(dated["y"].unique().tolist())
    last_y = years[-1] if years else None
    partial = bool(last_d is not None and last_d.month < 12)
    full_years = [y for y in years if not (partial and y == last_y)]
    # the first year started mid-year (the procedure was published in April 2021):
    # treat a first year whose earliest record is after January as partial too
    first_partial = bool(first_d is not None and first_d.month > 1 and len(years) > 1)
    whole_years = [y for y in full_years if not (first_partial and y == years[0])]

    def ylabel(y):
        if partial and y == last_y:
            return f"{y} (עד {fmt.MONTHS_HE[last_d.month - 1]})"
        return str(y)

    by_year = {t: [int(((dated["y"] == y) & (dated["t"] == t)).sum()) for y in years] for t in type_order}
    year_tot = [int((dated["y"] == y).sum()) for y in years]

    # YTD: each year up to the same month/day as the latest record
    ytd = []
    if last_d is not None:
        md = (last_d.month, last_d.day)
        cut = (dated["m"] * 100 + dated["d"].dt.day) <= md[0] * 100 + md[1]
        ytd = [int(((dated["y"] == y) & cut).sum()) for y in years]

    # cumulative monthly
    dated["ym"] = dated["d"].dt.to_period("M")
    months = pd.period_range(dated["ym"].min(), dated["ym"].max(), freq="M") if len(dated) else []
    cum = {}
    for t in [AUDITOR, MAINTAINER]:
        s = dated[dated["t"] == t].groupby("ym").size().reindex(months, fill_value=0).cumsum()
        cum[t] = [int(v) for v in s]
    cum_x = [f"{p.year}-{p.month:02d}" for p in months]

    # month x year heatmap
    heat = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if partial and y == last_y and m > last_d.month:
                continue
            heat.append([m - 1, yi, int(((dated["y"] == y) & (dated["m"] == m)).sum())])
    heat_max = max([c[2] for c in heat] or [0])
    # calendar-month totals over whole years only
    wy = dated[dated["y"].isin(whole_years)]
    cal = [int((wy["m"] == m).sum()) for m in range(1, 13)]

    # ---- maintainers by year x status ----
    md_ = dated[dated["t"] == MAINTAINER]
    statuses = [s for s in [OK_STATUS, NOT_OK] if (md_["st"] == s).any()] + \
        sorted(s for s in md_["st"].unique() if s not in (OK_STATUS, NOT_OK))
    m_years = sorted(md_["y"].unique().tolist())
    mstat = {s: [int(((md_["y"] == y) & (md_["st"] == s)).sum()) for y in m_years] for s in statuses}

    # ---- companies chart: top 12 ----
    TOPN = 12
    top_names = list(co_counts.index[:TOPN])
    co_ok = [int(((co["company_name"] == c) & (co["st"] != NOT_OK)).sum()) for c in top_names]
    co_not = [int(((co["company_name"] == c) & (co["st"] == NOT_OK)).sum()) for c in top_names]
    co_rest = int(co_counts.iloc[TOPN:].sum()) if n_companies > TOPN else 0
    top3_share = (co_counts.iloc[:3].sum() / len(co)) if len(co) else 0.0

    # company size buckets
    buckets = [("תחזוקאי אחד", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10-19", 10, 19), ("20 ומעלה", 20, 10**9)]
    size_rows = []
    for lab, lo, hi in buckets:
        sel = co_counts[(co_counts >= lo) & (co_counts <= hi)]
        size_rows.append((lab, len(sel), int(sel.sum())))

    # ---- cities (maintainers, company address) ----
    mnt = df[is_mnt]
    city_counts = frame.ranked(mnt["city"][~mnt["city"].isin([NO_ADDR, UNKNOWN_CITY])])
    c_labels, c_vals = frame.top_other(city_counts, 10, other="יישובים אחרים")
    n_unknown_city = int((mnt["city"] == UNKNOWN_CITY).sum())
    n_no_addr = int((mnt["city"] == NO_ADDR).sum())
    if n_unknown_city:
        c_labels.append(UNKNOWN_CITY)
        c_vals.append(n_unknown_city)
    mco = co[co["t"] == MAINTAINER]
    c_cos = []
    for lab in c_labels:
        if lab == "יישובים אחרים":
            sel = mco[~mco["city"].isin(c_labels) & ~mco["city"].isin([NO_ADDR])]
        else:
            sel = mco[mco["city"] == lab]
        c_cos.append(int(sel["company_name"].nunique()))
    n_cities = len(city_counts)

    # ---- batches: approvals per authorisation day ----
    per_day = dated.groupby("d").size()
    b_buckets = [("יום עם הרשאה אחת", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10-19", 10, 19), ("20 ומעלה", 20, 10**9)]
    batch_rows = []
    for lab, lo, hi in b_buckets:
        sel = per_day[(per_day >= lo) & (per_day <= hi)]
        batch_rows.append((lab, len(sel), int(sel.sum())))
    big_share = (per_day[per_day >= 10].sum() / len(dated)) if len(dated) else 0.0
    n_days = len(per_day)
    busiest = per_day.sort_index().sort_values(ascending=False, kind="stable")
    top_day, top_day_n = (busiest.index[0], int(busiest.iloc[0])) if len(busiest) else (None, 0)

    # ---- completeness by type ----
    comp_fields = [("company", "שם חברה"), ("phone", "טלפון"), ("adress", "כתובת"), ("email", "דוא\"ל")]
    comp_rows = []
    for t in type_order:
        sub = df[df["t"] == t]
        row = [t, fmt.int_he(len(sub))]
        for col, _ in comp_fields:
            filled = (frame.clean_series(sub[col]) != "").sum()
            row.append(fmt.pct(filled / len(sub), 0) if len(sub) else "0%")
        comp_rows.append(row)

    # ---- names: both roles / re-authorised ----
    named = df[df["name"] != ""]
    aud_names = set(named.loc[named["t"] == AUDITOR, "name"])
    mnt_names = set(named.loc[named["t"] == MAINTAINER, "name"])
    both = len(aud_names & mnt_names)
    not_rows = dated[(dated["st"] == NOT_OK) & (dated["name"] != "")]
    ok_rows = dated[(dated["st"] == OK_STATUS) & (dated["name"] != "")]
    last_ok = ok_rows.groupby("name")["d"].max()
    not_names = sorted(set(not_rows["name"]))
    reauth = sum(1 for nm in not_names
                 if nm in last_ok.index and last_ok[nm] > not_rows.loc[not_rows["name"] == nm, "d"].max())

    # ================= insights =================
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # registry mix
    if n_aud and n_mnt:
        add("mix", f"ברשימה {fmt.int_he(n)} רשומות: {fmt.int_he(n_aud)} מבקרי מטפים ({fmt.pct(n_aud / n)}) "
                   f"ו-{fmt.int_he(n_mnt)} תחזוקאי מטפים ({fmt.pct(n_mnt / n)}). "
                   f"מבקרים רשומים כאנשים פרטיים, ואילו {fmt.pct(mnt_with_co / n_mnt, 0)} מהתחזוקאים רשומים תחת חברת שירות.")

    # YTD comparison
    if partial and len(years) >= 2 and ytd[-2] > 0:
        cur, prev = ytd[-1], ytd[-2]
        ch = cur / prev - 1
        period = f"ינואר-{fmt.MONTHS_HE[last_d.month - 1]}" if last_d.month > 1 else "ינואר"
        if ch >= 0.1:
            word = "עלייה"
        elif ch <= -0.1:
            word = "ירידה"
        else:
            word = None
        if word:
            add("ytd", f"ב{period} {last_y} נרשמו {fmt.int_he(cur)} הרשאות חדשות, לעומת {fmt.int_he(prev)} "
                       f"באותה תקופה ב-{last_y - 1}: {word} של {fmt.pct(abs(ch), 0)}.")
        else:
            add("ytd", f"ב{period} {last_y} נרשמו {fmt.int_he(cur)} הרשאות חדשות, בדומה ל-{fmt.int_he(prev)} "
                       f"באותה תקופה ב-{last_y - 1}.")

    # peak whole year
    if len(whole_years) >= 2:
        wt = {y: year_tot[years.index(y)] for y in whole_years}
        peak = max(whole_years, key=lambda y: (wt[y], y))
        low = min(whole_years, key=lambda y: (wt[y], y))
        if wt[peak] > wt[low]:
            add("peak", f"השנה המלאה העמוסה ביותר הייתה {peak}, עם {fmt.int_he(wt[peak])} הרשאות; "
                        f"השקטה ביותר {low}, עם {fmt.int_he(wt[low])} "
                        f"(בין השנים המלאות {whole_years[0]}-{whole_years[-1]}).")

    # maintainers surge
    if n_mnt and len(m_years) >= 2:
        mt = {y: sum(mstat[s][m_years.index(y)] for s in statuses) for y in m_years}
        my = max(m_years, key=lambda y: (mt[y], y))
        if mt[my] / n_mnt >= 0.25:
            add("mpeak", f"תחזוקאי המטפים נרשמו בגלים: {fmt.int_he(mt[my])} מתוך {fmt.int_he(n_mnt)} "
                         f"({fmt.pct(mt[my] / n_mnt, 0)}) קיבלו הרשאה ב-{my}"
                         f"{' (שנה חלקית)' if (partial and my == last_y) or (first_partial and my == years[0]) else ''}.")

    # not authorised
    if n_not:
        nd = dated[dated["st"] == NOT_OK]
        nt = frame.ranked(df.loc[df["st"] == NOT_OK, "t"])
        only_mnt = len(nt) == 1 and nt.index[0] == MAINTAINER
        span = ""
        if len(nd):
            y0, y1 = int(nd["y"].min()), int(nd["y"].max())
            span = f", כולן מתאריכים בשנים {y0}-{y1}" if y1 > y0 else f", כולן מ-{y0}"
        who = "כולן של תחזוקאי מטפים" if only_mnt else "בעיקר של " + str(nt.index[0])
        txt = f"{plural(n_not, 'רשומה אחת', 'רשומות')} מסומנות \"לא מורשה\" ({who}{span})."
        if n_not == 1:
            txt = f"רשומה אחת מסומנת \"לא מורשה\" ({who}{span})."
        if reauth:
            txt += (" אחד מהשמות האלה מופיע" if reauth == 1 else f" {fmt.int_he(reauth)} מהשמות האלה מופיעים") + \
                " שוב ברשימה עם הרשאה מאוחרת יותר (התאמה לפי שם מלא)."
        add("not_ok", txt)

    # company concentration
    if n_companies >= 5 and top3_share >= 0.25:
        add("conc", f"שלוש חברות השירות הגדולות ({fmt.join_he(co_counts.index[:3])}) מעסיקות "
                    f"{fmt.pct(top3_share, 0)} מהתחזוקאים הרשומים תחת חברה; "
                    f"בסך הכול ברשימה {fmt.int_he(n_companies)} חברות.")

    # city
    if len(city_counts) >= 3:
        lead, lead_n = city_counts.index[0], int(city_counts.iloc[0])
        located = len(mnt) - n_no_addr
        if located and lead_n / located >= 0.15:
            ncos = int(mco.loc[mco["city"] == lead, "company_name"].nunique())
            add("city", f"{lead} מובילה בכתובות חברות השירות: {fmt.int_he(lead_n)} תחזוקאים "
                        f"({fmt.pct(lead_n / located, 0)} מהתחזוקאים עם כתובת) רשומים בחברות שכתובתן ב{lead}, "
                        f"ב-{plural(ncos, 'חברה אחת', 'חברות')}.")

    # batches
    if big_share >= 0.2 and top_day is not None:
        add("batch", f"ההרשאות ניתנות במקבצים: {fmt.pct(big_share, 0)} מהן נרשמו בימים שבהם ניתנו 10 הרשאות ומעלה. "
                     f"היום העמוס ביותר היה {fmt.d_he(top_day)}, עם {fmt.int_he(top_day_n)} הרשאות.")

    # seasonality
    if len(whole_years) >= 2 and sum(cal) >= 120:
        avg = sum(cal) / 12
        mi = max(range(12), key=lambda i: (cal[i], -i))
        if cal[mi] >= 1.4 * avg:
            add("season", f"{fmt.MONTHS_HE[mi]} הוא החודש העמוס ביותר בשנים המלאות {whole_years[0]}-{whole_years[-1]}: "
                          f"{fmt.int_he(cal[mi])} הרשאות, פי {fmt.num_he(cal[mi] / avg)} מהממוצע החודשי.")

    # both roles
    if both >= 2:
        add("both", f"{fmt.int_he(both)} שמות מופיעים ברשימה הן כמבקר מטפים והן כתחזוקאי מטפים (התאמה לפי שם מלא).")

    # data quality
    if n_bad_date:
        def rows(k):
            return "ברשומה אחת" if k == 1 else f"ב-{fmt.int_he(k)} רשומות"
        parts = []
        if n_malformed:
            parts.append(f"{rows(n_malformed)} תאריך ההרשאה אינו תקין")
        if n_far_date:
            parts.append(f"{rows(n_far_date)} התאריך חריג, רחוק בשנים משאר הרשומות (ככל הנראה טעות הקלדה)")
        verb = "היא אינה נכללת" if n_bad_date == 1 else "הן אינן נכללות"
        add("dates", "; ".join(parts) + f". לכן {verb} בגרפים לפי זמן.")

    # ================= KPIs =================
    kpis = {
        "total": kpi(n, fmt.int_he(n)),
        "auditors": kpi(n_aud, fmt.int_he(n_aud)),
        "maintainers": kpi(n_mnt, fmt.int_he(n_mnt)),
        "not_ok": kpi(n_not, fmt.int_he(n_not), "warn" if n_not else "ok"),
        "companies": kpi(n_companies, fmt.int_he(n_companies)),
        "last": kpi(last_d.strftime("%Y-%m-%d") if last_d is not None else "",
                    last_d.strftime("%d.%m.%Y") if last_d is not None else "אין",
                    "info"),
    }

    # ================= labels / ledes =================
    span_txt = f"{first_d.year}-{last_d.year}" if last_d is not None else ""
    summary = (f"איתור מבקר מטפים או תחזוקאי מטפים מורשה לפי שם או חברה: {fmt.int_he(n_aud)} מבקרים "
               f"ו-{fmt.int_he(n_mnt)} תחזוקאים ברשימת כבאות והצלה לפי ת\"י 129.")
    if len(summary) > 155:
        summary = f"איתור מבקר או תחזוקאי מטפים מורשה: {fmt.int_he(n)} רשומות לפי ת\"י 129."

    lede = (f"הרשימה הרשמית של הרשות הארצית לכבאות והצלה של מבקרי מטפים (בודקי מטפי כיבוי אש) ותחזוקאי מטפים "
            f"שקיבלו הרשאה לפי ת\"י 129. היא כוללת {fmt.int_he(n)} רשומות: {fmt.int_he(n_aud)} מבקרים, "
            f"{fmt.int_he(n_mnt)} תחזוקאים ב-{fmt.int_he(n_companies)} חברות שירות, "
            f"עם תאריכי הרשאה {('מ-' + fmt.d_he(first_d) + ' עד ' + fmt.d_he(last_d)) if last_d is not None else 'שלא צוינו'}. "
            f"{n_ok:,} מהרשומות בסטטוס \"מורשה\".")

    yr_lede = ""
    if years:
        yr_lede = ("מספר ההרשאות לפי שנת ההרשאה, בחלוקה לסוג."
                   + (f" {last_y} חלקית: הנתונים מגיעים עד {fmt.d_he(last_d)}." if partial else "")
                   + (f" {years[0]} חלקית גם היא: ההרשאה הראשונה ברשימה מ-{fmt.d_he(first_d)}." if first_partial else ""))
    ytd_lede = ""
    if ytd and last_d is not None:
        ytd_lede = (f"השוואה הוגנת בין השנים: בכל שנה נספרו רק הרשאות עד {last_d.day} ב{fmt.MONTHS_HE[last_d.month - 1]}, "
                    f"התאריך האחרון בנתונים. השנה הנוכחית: {fmt.int_he(ytd[-1])}.")
    cum_lede = (f"גודל הרשימה המצטבר לפי חודש ההרשאה: {fmt.int_he(cum[AUDITOR][-1] if cum_x else 0)} מבקרים "
                f"ו-{fmt.int_he(cum[MAINTAINER][-1] if cum_x else 0)} תחזוקאים עם תאריך תקין. "
                f"אפשר לגלול ולהתמקד בטווח זמן בעזרת המחוון שמתחת לגרף.")
    heat_lede = ""
    if heat:
        hc = max(heat, key=lambda c: (c[2], -c[1], -c[0]))
        heat_lede = (f"כל משבצת היא חודש: ככל שהצבע כהה יותר, ניתנו בו יותר הרשאות. "
                     f"השיא: {fmt.MONTHS_HE[hc[0]]} {years[hc[1]]}, עם {fmt.int_he(hc[2])} הרשאות.")
    # not-authorised rows per type: the donut splits each type that has any
    not_by_type = {t: int(((df["t"].replace("", "לא צוין") == t) & (df["st"] == NOT_OK)).sum())
                   for t in type_order}
    type_names, type_values = [], []
    for t in type_order:
        k = not_by_type[t]
        type_names.append(f"{t}: {OK_STATUS}" if k else t)
        type_values.append(int(types[t]) - k)
    for t in type_order:
        if not_by_type[t]:
            type_names.append(f"{t}: {NOT_OK}")
            type_values.append(not_by_type[t])
    not_parts = [f"{plural(k, 'רשומה אחת', 'רשומות')} של {t}" for t, k in not_by_type.items() if k]
    type_lede = ""
    if n:
        type_lede = f"{fmt.pct(n_aud / n, 0)} מהרשומות הן של מבקרי מטפים."
        if not_parts:
            type_lede += f" בסטטוס \"לא מורשה\": {fmt.join_he(not_parts)}."
    if n_other_type:
        type_lede += f" {plural(n_other_type, 'רשומה אחת', 'רשומות')} בסוג אחר."
    mstat_lede = ""
    if m_years:
        mstat_lede = "תחזוקאי המטפים לפי שנת ההרשאה וסטטוס."
        not_years = sorted(md_.loc[md_["st"] == NOT_OK, "y"].unique().tolist())
        if not_years and not_years[-1] < m_years[-1]:
            rng = f"בשנים {not_years[0]}-{not_years[-1]}" if len(not_years) > 1 else f"ב-{not_years[0]}"
            mstat_lede += (f" רשומות \"לא מורשה\" מופיעות רק {rng}; "
                           f"מאז {not_years[-1] + 1} כל רשומות התחזוקאים מורשות.")
    co_lede = (f"החברות עם הכי הרבה תחזוקאים רשומים. {fmt.int_he(len(co))} תחזוקאים רשומים תחת "
               f"{plural(n_companies, 'חברה אחת', 'חברות')}"
               + (f"; {fmt.int_he(co_rest)} תחזוקאים בחברות שמחוץ לרשימה." if co_rest else ".")
               + (f" שמות חברה שנכתבו בכמה אופנים ({n_spellings} כתיבים) אוחדו." if n_spellings > n_companies else ""))
    single = size_rows[0][1]
    size_lede = (f"רוב החברות קטנות: {plural(single, 'חברה אחת', 'חברות')} עם תחזוקאי אחד בלבד, "
                 f"מול {plural(size_rows[-1][1] + size_rows[-2][1], 'חברה אחת', 'חברות')} עם 10 ומעלה, שבהן "
                 f"{fmt.int_he(size_rows[-1][2] + size_rows[-2][2])} תחזוקאים.")
    city_lede = (f"היישוב שבו נמצאת חברת השירות, כפי שחולץ מכתובת החברה ({plural(n_cities, 'יישוב אחד זוהה', 'יישובים זוהו')}). "
                 + (f"{'בכתובת אחת' if n_unknown_city == 1 else 'ב-' + fmt.int_he(n_unknown_city) + ' כתובות'} לא זוהה יישוב. " if n_unknown_city else "")
                 + (f"ל-{plural(n_no_addr, 'תחזוקאי אחד', 'תחזוקאים')} אין כתובת, והם אינם בגרף." if n_no_addr else ""))
    batch_lede = (f"ההרשאות ניתנו ב-{fmt.int_he(n_days)} ימים שונים. הגרף מחלק את הימים לפי מספר ההרשאות שניתנו בהם, "
                  f"וכמה הרשאות נרשמו בכל קבוצה.")
    comp_lede = ("איזה שיעור מהרשומות כולל כל פרט, לפי סוג ההרשאה. "
                 "פרטי הקשר עצמם מופיעים בעיון בנתונים שמתחת לעמוד.")

    def aria_bar(prefix, labels, vals):
        if not vals:
            return prefix
        i = max(range(len(vals)), key=lambda k: (vals[k], -k))
        return f"{prefix} הגבוה ביותר: {labels[i]}, {fmt.int_he(vals[i])}."

    ylabels = [ylabel(y) for y in years]

    def yshort(y):
        # chart axis: a short second line so 375px never skips the label
        if partial and y == last_y:
            return f"{y}\n(עד {fmt.MONTHS_SHORT_HE[last_d.month - 1]})"
        return str(y)
    labels = {
        "lede": lede,
        "year_lede": yr_lede,
        "year_aria": aria_bar("גרף עמודות מוערמות: הרשאות לפי שנה וסוג.", ylabels, year_tot),
        "ytd_lede": ytd_lede,
        "ytd_aria": aria_bar("גרף עמודות: הרשאות מתחילת כל שנה עד אותו תאריך.", [str(y) for y in years], ytd),
        "cum_lede": cum_lede,
        "cum_aria": f"גרף קווים: גודל הרשימה המצטבר לפי חודש, {fmt.int_he(len(dated))} הרשאות עם תאריך תקין.",
        "heat_lede": heat_lede,
        "heat_aria": "מפת חום: הרשאות לפי חודש ושנה. " + heat_lede,
        "type_lede": type_lede,
        "type_aria": f"תרשים טבעת: {fmt.int_he(n_aud)} מבקרי מטפים, {fmt.int_he(n_mnt)} תחזוקאי מטפים.",
        "mstat_lede": mstat_lede,
        "mstat_aria": f"גרף עמודות מוערמות: תחזוקאי מטפים לפי שנה וסטטוס, {fmt.int_he(n_not)} לא מורשים.",
        "co_lede": co_lede,
        "co_aria": aria_bar("גרף עמודות אופקי: תחזוקאים לפי חברת שירות.", top_names, [a + b for a, b in zip(co_ok, co_not)]),
        "size_lede": size_lede,
        "size_aria": f"גרף עמודות: חברות שירות לפי מספר התחזוקאים הרשומים בהן, {fmt.int_he(n_companies)} חברות.",
        "city_lede": city_lede,
        "city_aria": aria_bar("גרף עמודות אופקי: תחזוקאים לפי יישוב חברת השירות.", c_labels, c_vals),
        "batch_lede": batch_lede,
        "batch_aria": f"גרף עמודות: ימי הרשאה לפי מספר ההרשאות ביום, {fmt.int_he(n_days)} ימים.",
        "comp_lede": comp_lede,
        "comp_cap": "שיעור הרשומות הכוללות כל פרט, לפי סוג ההרשאה",
    }

    pct_aud = n_aud / n if n else 0
    tables = {
        "year": [[ylabels[i]] + [fmt.int_he(by_year[t][i]) for t in type_order] + [fmt.int_he(year_tot[i])]
                 for i in range(len(years))],
        "ytd": [[str(y), fmt.int_he(ytd[i])] for i, y in enumerate(years)] if ytd else [],
        "type": [[t, fmt.int_he(int(types[t])), fmt.pct(int(types[t]) / n)] for t in type_order],
        "mstat": [[ylabel(y)] + [fmt.int_he(mstat[s][i]) for s in statuses] for i, y in enumerate(m_years)],
        "co": [[top_names[i], fmt.int_he(co_ok[i]), fmt.int_he(co_not[i]), fmt.int_he(co_ok[i] + co_not[i])]
               for i in range(len(top_names))],
        "size": [[lab, fmt.int_he(c), fmt.int_he(m)] for lab, c, m in size_rows],
        "city": [[c_labels[i], fmt.int_he(c_vals[i]), fmt.int_he(c_cos[i])] for i in range(len(c_labels))],
        "batch": [[lab, fmt.int_he(d), fmt.int_he(a)] for lab, d, a in batch_rows],
        "comp": comp_rows,
    }
    cols = {
        "year": ["שנה"] + type_order + ["סך הכול"],
        "mstat": ["שנה"] + statuses,
        "comp": ["סוג", "רשומות"] + [lab for _, lab in comp_fields],
    }

    charts = {
        "year": {"x": [yshort(y) for y in years], "series": [{"name": t, "values": by_year[t]} for t in type_order]},
        "ytd": {"x": [str(y) for y in years], "y": ytd, "last": len(years) - 1 if partial else -1},
        "cum": {"x": cum_x, "series": [{"name": t, "values": cum[t]} for t in [AUDITOR, MAINTAINER]]},
        "heat": {"months": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in years], "cells": heat, "max": heat_max},
        "type": {"names": type_names, "values": type_values},
        "mstat": {"x": [yshort(y) for y in m_years], "series": [{"name": s, "values": mstat[s]} for s in statuses]},
        "co": {"names": top_names, "ok": co_ok, "not": co_not},
        "size": {"x": [r[0] for r in size_rows], "companies": [r[1] for r in size_rows], "people": [r[2] for r in size_rows]},
        "city": {"names": c_labels, "values": c_vals, "cos": c_cos},
        "batch": {"x": [r[0] for r in batch_rows], "days": [r[1] for r in batch_rows], "approvals": [r[2] for r in batch_rows]},
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
    }
    if span_txt:
        agent_data["temporal_coverage"] = f"{first_d.year}/{last_d.year}"

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "cols": cols,
        "notes": NOTES,
        "flags": {"has_not": bool(n_not), "has_co": bool(n_companies), "has_city": bool(c_vals),
                  "has_time": bool(years), "pct_aud": pct_aud},
    }
