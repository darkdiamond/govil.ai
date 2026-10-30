"""מאגר הכונס הרשמי (Ministry of Justice, Official Receiver) — recipe compute.

Three tables from the Official Receiver's case systems:

- `debtors`: one row per individual bankruptcy case (no debtor names): city,
  court/district, status, the procedure's dates (opening, receivership order,
  bankruptcy order, order cancellation, case closing, summary-report
  approval), the cancellation reason, order amount, bank balance, whether the
  receivership order included section 42, and the special manager's report /
  repayment-plan dates (filed as yyyymmdd ints, 0 = none; planned as dd/mm/yyyy).
- `companies`: one row per company liquidation case under the old (pre-2019)
  companies ordinance: city, status, petition / order / cancellation / closing
  dates, closing reason, court, company name and number.
- `claims`: one row per proof of debt (2.7M rows) filed in either kind of
  case: claimant type, claim status, system (bankruptcy / liquidation),
  creation date, claimed and approved amounts (approved in priority split out).

What the data is (2026-10): almost every debtor case in the file has already
ended (status closed / cancelled / discharged), including cases opened this
year. Counts by OPENING year therefore undercount recent years (cases still
running are absent); the page says so whenever the ended share is
overwhelming. Company liquidation petitions stop in 2019 (the insolvency law
moved new cases elsewhere) while closings of the old docket continue.

"~" in the source stands for gershayim (ת~א = ת״א); labels are normalised.
Dates outside 1948..as_of are typos (years 2100, 2206, ...) and are ignored;
as_of is the latest day with at least two case openings (one typo can't move
it). Dates are parsed per distinct value, never per row.

Every number and sentence on the page comes from here. Insight rules return
a sentence or None when their premise does not hold.
"""
import numpy as np
import pandas as pd

# debtors
B_CITY = "עיר בה מתגורר החייב"
B_COURT = "שם בית משפט"
B_STATUS = "סטטוס תיק"
B_OPEN = "תאריך פתיחת תיק"
B_REC = "תאריך צו כינוס"
B_BK = "תאריך צו פשיטת רגל"
B_CAN = "תאריך ביטול צו"
B_REASON = "סיבת ביטול צו"
B_CUT = "תאריך גזירת תיק"
B_AMT = "סכום הצו"
B_BANK = "יתרה בבנק"
B_S42 = "האם בצו הכינוס נכלל סעיף 42"
B_REP = "תאריך הגשת דוח על ידי מנהל מיוחד"
B_PLAN = "תאריך הגשה של תכנית פרעון"
B_REP_DUE = "תאריך מתוכנן להגשת דוח"
B_PLAN_DUE = "תאריך מתוכנן להגשת תכנית פרעון"
B_SUMMARY = "תאריך אישור דוח מסכם"

# companies
C_CITY = "עיר פעילות חברה"
C_STATUS = "סטטוס תיק"
C_FILE = "תאריך הגשת הבקשה"
C_ORDER = "תאריך קבלת צו פירוק"
C_CAN = "תאריך ביטול / הקפאת צו פירוק"
C_CLOSE = "תאריך סגירת תיק"
C_REASON = "סיבת סגירה"
C_COURT = "בית משפט מחוזי בו מתנהל התיק"

# claims
D_TYPE = "סוג תובע החוב"
D_STATUS = "סטטוס תביעת חוב"
D_SYS = "סוג מערכת"
D_DATE = "תאריך יצירת החוב"
D_AMT = "סכום תביעת החוב"
D_APP = "סכום שאושר"
D_PRI = "סכום שאושר בדין קדימה"

DMY = "%d/%m/%Y"
MIN_YEAR = 1948
START_SHARE = 0.02      # a yearly chart starts at the first year with 2% of the peak year's count
WINDOW_YEARS = 15       # stacked by-year charts show the last 15 years
HEAT_YEARS = 12
COHORT_MIN = 500
TOP_REASONS = 12
TOP_CITIES = 15
TOP_C_REASONS = 10
TOP_C_CITIES = 10
PARTIAL_BEFORE = (12, 15)  # the as_of year is partial if as_of falls before 15 December
ENDED_NOTE_SHARE = 0.9
CLAIMS_DAY_MIN = 10     # claims as_of: latest day with 10+ claims (hundreds a day are normal)
LAG_QUANTILE = 0.8      # cohort lag = years within which 80% of discharges end
LAG_RANGE = (3, 10)

MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני",
                "יולי", "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]

DISCHARGE = "הפטר"
ABUSE = "ניצול לרעה או מחדלים"
DROPPED = "מחיקה, דחייה או ביטול"
SETTLED = "הסדר, פשרה או פירעון"
OTHER = "אחר"
OUTCOMES = [DISCHARGE, SETTLED, ABUSE, DROPPED, OTHER]

DUR_BUCKETS = [(1, "עד שנה"), (2, "שנה עד שנתיים"), (3, "שנתיים עד שלוש"),
               (4, "שלוש עד ארבע"), (5, "ארבע עד חמש"), (7, "חמש עד שבע"),
               (10, "שבע עד עשר"), (None, "מעל עשר שנים")]
BANK_BUCKETS = [(1000, "עד 1,000"), (5000, "1,000 עד 5,000"), (20000, "5,000 עד 20,000"),
                (50000, "20,000 עד 50,000"), (200000, "50,000 עד 200,000"),
                (None, "מעל 200,000")]
ORDER_BUCKETS = [(500, "עד 500"), (1000, "500 עד 1,000"), (2000, "1,000 עד 2,000"),
                 (5000, "2,000 עד 5,000"), (None, "מעל 5,000")]
CLAIM_BUCKETS = [(1000, "עד 1,000"), (5000, "1,000 עד 5,000"), (20000, "5,000 עד 20,000"),
                 (100000, "20,000 עד 100,000"), (1000000, "100,000 עד מיליון"),
                 (None, "מעל מיליון")]

# Spelling variants of the biggest cities; anything else keeps its cleaned name.
CITY_ALIASES = {
    "תל אביב": "תל אביב יפו",
    "ת״א": "תל אביב יפו",
    "תל אביב יפו": "תל אביב יפו",
    "פתח תקוה": "פתח תקווה",
    "קרית אתא": "קריית אתא",
    "קרית גת": "קריית גת",
    "קרית שמונה": "קריית שמונה",
    "קרית ביאליק": "קריית ביאליק",
    "קרית מוצקין": "קריית מוצקין",
    "קרית ים": "קריית ים",
    "קרית אונו": "קריית אונו",
    "קרית מלאכי": "קריית מלאכי",
    "קרית ארבע": "קריית ארבע",
    "י-ם": "ירושלים",
    "ב״ש": "באר שבע",
}


# ── formatting ──────────────────────────────────────────────────────────

def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _num(x, digits=1):
    return f"{x:,.{digits}f}"


def _ils(v):
    """A shekel amount in words-friendly form: 1,234 / 12.3 אלף / 1.2 מיליון."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:,.1f} מיליון"
    return _int(v)


def _delay(days):
    if days > 0:
        return f"בחציון {_int(days)} ימים אחרי המועד"
    if days < 0:
        return f"בחציון {_int(-days)} ימים לפני המועד"
    return "בחציון ביום המועד"


def _dmy(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _clean(s):
    """Source '~' is gershayim; collapse whitespace."""
    return " ".join(str(s).replace("~", "״").split())


def _city(raw):
    s = _clean(raw).strip(" .,")
    s = s.replace(" -", "-").replace("- ", "-").replace("-", " ")
    s = " ".join(s.split())
    return CITY_ALIASES.get(s, s)


# ── parsing ─────────────────────────────────────────────────────────────

def _dates(col, fmt=DMY):
    """Parse a date column per distinct value; returns datetime64 array (NaT = missing)."""
    codes, uniq = pd.factorize(col, sort=True)
    parsed = pd.to_datetime(pd.Series(uniq, dtype=object), format=fmt, errors="coerce").to_numpy()
    out = np.full(len(col), np.datetime64("NaT"), dtype="datetime64[ns]")
    ok = codes >= 0
    out[ok] = parsed[codes[ok]]
    return out


def _num_col(col):
    v = pd.to_numeric(col.str.replace(",", "", regex=False), errors="coerce")
    return v.to_numpy(dtype=float)


def _labels(col, fn=_clean):
    """Map a string column through fn per distinct value."""
    codes, uniq = pd.factorize(col, sort=True)
    mapped = np.array([fn(u) for u in uniq] + [""], dtype=object)
    return mapped[np.where(codes >= 0, codes, len(uniq))]


def _valid(d, as_of):
    lo = np.datetime64(f"{MIN_YEAR}-01-01")
    return (~np.isnat(d)) & (d >= lo) & (d <= np.datetime64(as_of))


def _years(d):
    return d.astype("datetime64[Y]").astype(int) + 1970


def _as_of(d, min_count=2):
    """Latest day with at least min_count records (a lone typo can't move it)."""
    s = pd.Series(d[~np.isnat(d)])
    s = s[s.dt.year >= MIN_YEAR]
    if s.empty:
        return None
    vc = s.value_counts()
    multi = vc[vc >= min_count]
    return (multi.index.max() if len(multi) else vc.index.max())


def _top(values, n=None, exclude_empty=True):
    """[(name, count)] sorted by count desc, then name — a total order."""
    vc = pd.Series(values).value_counts()
    items = [(k, int(v)) for k, v in vc.items() if not (exclude_empty and k == "")]
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    if n is None or len(items) <= n:
        return items, 0
    rest = sum(v for _, v in items[n:])
    return items[:n], rest


def _year_counts(years, mask, y0, y1):
    ys = years[mask]
    ys = ys[(ys >= y0) & (ys <= y1)]
    bc = np.bincount(ys - y0, minlength=y1 - y0 + 1) if len(ys) else np.zeros(y1 - y0 + 1, int)
    return [int(x) for x in bc]


def _start_year(years, mask, y1):
    ys = years[mask]
    ys = ys[ys <= y1]
    if not len(ys):
        return y1
    vc = pd.Series(ys).value_counts()
    peak = vc.max()
    ok = sorted(int(y) for y, c in vc.items() if c >= peak * START_SHARE)
    return ok[0]


def _bucket(values, buckets):
    out = []
    lo = None
    for ub, name in buckets:
        m = np.ones(len(values), bool)
        if lo is not None:
            m &= values >= lo
        if ub is not None:
            m &= values < ub
        out.append((name, int(m.sum())))
        lo = ub
    return out


def _outcome(reason):
    r = reason
    if r == "":
        return OTHER
    if "לא עמד" in r or "ניצול לרעה" in r or "מחדלים" in r or "אי עמידה" in r:
        return ABUSE
    if "הפטר" in r:
        return DISCHARGE
    if "לא אושר" in r:
        return DROPPED
    if "הסדר" in r or "פשרה" in r or "תשלום מלא" in r:
        return SETTLED
    if ("מחיק" in r or "דחי" in r or "נדחת" in r or "מעש" in r or "משיכת" in r
            or "ביטול יזום" in r or "העדר תועלת" in r):
        return DROPPED
    return OTHER


def _partial(as_of):
    return (as_of.month, as_of.day) < PARTIAL_BEFORE


# ── debtors ─────────────────────────────────────────────────────────────

def _debtors(df):
    n = len(df)
    opened = _dates(df[B_OPEN])
    as_of = _as_of(opened)
    if as_of is None:
        raise ValueError("no valid opening dates")
    ay = as_of.year
    partial = _partial(as_of)
    full_y = ay - 1 if partial else ay

    o_ok = _valid(opened, as_of)
    oy = _years(opened)
    rec = _dates(df[B_REC]); rec_ok = _valid(rec, as_of); ry = _years(rec)
    bk = _dates(df[B_BK]); bk_ok = _valid(bk, as_of); by = _years(bk)
    can = _dates(df[B_CAN]); can_ok = _valid(can, as_of); cy = _years(can)
    summ = _dates(df[B_SUMMARY]); summ_ok = _valid(summ, as_of)
    rep = _dates(df[B_REP], "%Y%m%d"); rep_ok = _valid(rep, as_of)
    plan = _dates(df[B_PLAN], "%Y%m%d"); plan_ok = _valid(plan, as_of)
    rep_due = _dates(df[B_REP_DUE]); plan_due = _dates(df[B_PLAN_DUE])

    status = _labels(df[B_STATUS])
    reason = _labels(df[B_REASON])
    court = _labels(df[B_COURT])
    city = _labels(df[B_CITY], _city)
    s42 = df[B_S42].to_numpy()
    amt = _num_col(df[B_AMT])
    bank = _num_col(df[B_BANK])

    ended = np.array([s.startswith("סגור") or "ביטול" in s or "הפטר" in s or "נמחקה" in s
                      for s in status]) | can_ok
    ended_share = float(ended.mean()) if n else 0.0

    # yearly flows
    y0 = _start_year(oy, o_ok, ay)
    years = list(range(y0, ay + 1))
    yearly = {
        "x": [str(y) for y in years],
        "series": [
            {"name": "תיקים שנפתחו", "data": _year_counts(oy, o_ok, y0, ay)},
            {"name": "צווי כינוס", "data": _year_counts(ry, rec_ok, y0, ay)},
            {"name": "צווי פשיטת רגל", "data": _year_counts(by, bk_ok, y0, ay)},
            {"name": "ביטולי צו", "data": _year_counts(cy, can_ok, y0, ay)},
        ],
        "partial": partial,
    }
    opens = yearly["series"][0]["data"]
    before = int((o_ok & (oy < y0)).sum())

    # month x year heat of openings
    hy0 = max(y0, ay - HEAT_YEARS + 1)
    hm = o_ok & (oy >= hy0)
    om = opened[hm].astype("datetime64[M]").astype(int) % 12
    hyy = oy[hm] - hy0
    grid = np.zeros((ay - hy0 + 1, 12), int)
    np.add.at(grid, (hyy, om), 1)
    cells = []
    for yi in range(ay - hy0 + 1):
        for mi in range(12):
            if hy0 + yi == ay and mi + 1 > as_of.month:
                continue
            cells.append([mi, yi, int(grid[yi, mi])])
    heat = {"months": MONTHS_SHORT, "years": [str(y) for y in range(hy0, ay + 1)],
            "cells": cells, "max": int(grid.max()) if grid.size else 0}
    month_tot = grid[: (ay - hy0) if partial else (ay - hy0 + 1)].sum(axis=0)

    # cancellation reasons
    has_reason = reason != ""
    top_r, rest_r = _top(reason[has_reason], TOP_REASONS)
    n_reason = int(has_reason.sum())
    reasons = {"names": [k for k, _ in top_r] + ([OTHER + " (סיבות נוספות)"] if rest_r else []),
               "values": [v for _, v in top_r] + ([rest_r] if rest_r else [])}
    reasons_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n_reason)}
                   for k, v in zip(reasons["names"], reasons["values"])]

    outcome = np.array([_outcome(r) for r in reason], dtype=object)

    # duration open -> cancellation
    dm = o_ok & can_ok & (can >= opened)
    dur = (can[dm] - opened[dm]).astype("timedelta64[D]").astype(float) / 365.25
    dur_out = outcome[dm]

    # outcome mix by opening cohort; cohorts stop `lag` years before as_of, where
    # lag covers most discharges, so the archive's ended-cases-only selection
    # doesn't strip discharges out of the recent cohorts
    dd = dur[dur_out == DISCHARGE]
    lag = int(np.ceil(np.quantile(dd, LAG_QUANTILE))) if len(dd) >= 30 else LAG_RANGE[1]
    lag = min(max(lag, LAG_RANGE[0]), LAG_RANGE[1])
    c1 = ay - lag
    cohorts = []
    for y in range(max(y0, c1 - WINDOW_YEARS + 1), c1 + 1):
        m = o_ok & (oy == y) & has_reason
        tot = int(m.sum())
        if tot >= COHORT_MIN:
            cnt = pd.Series(outcome[m]).value_counts()
            cohorts.append((y, tot, [float(cnt.get(g, 0)) / tot for g in OUTCOMES]))
    mix = {"x": [str(y) for y, _, _ in cohorts],
           "series": [{"name": g, "data": [round(s[i] * 100, 1) for _, _, s in cohorts]}
                      for i, g in enumerate(OUTCOMES)]}
    mix_tbl = [{"year": str(y), "total": _int(t), "shares": [_pct(v) for v in s]}
               for y, t, s in cohorts]

    dur_b = _bucket(dur, DUR_BUCKETS)
    n_dur = len(dur)
    duration = {"names": [k for k, _ in dur_b], "values": [v for _, v in dur_b]}
    dur_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n_dur) if n_dur else "0.0%"}
               for k, v in dur_b]
    med_by = {}
    for g in OUTCOMES:
        sel = dur[dur_out == g]
        if len(sel) >= 30:
            med_by[g] = (float(np.median(sel)), len(sel))
    dur_groups = [{"name": g, "n": _int(med_by[g][1]), "median": _num(med_by[g][0])}
                  for g in OUTCOMES if g in med_by]
    med_all = float(np.median(dur)) if n_dur else None

    # courts by opening year
    wy0 = max(y0, ay - WINDOW_YEARS + 1)
    wm = o_ok & (oy >= wy0)
    court_names = [k for k, _ in _top(court[wm])[0]]
    courts = {"x": [str(y) for y in range(wy0, ay + 1)], "series": []}
    for cname in court_names:
        courts["series"].append({"name": cname,
                                 "data": _year_counts(oy, wm & (court == cname), wy0, ay)})
    court_all, _ = _top(court)
    court_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n)} for k, v in court_all]

    # cities
    has_city = city != ""
    top_c, _ = _top(city[has_city], TOP_CITIES)
    n_city = int(has_city.sum())
    cities = {"names": [k for k, _ in top_c], "values": [v for _, v in top_c]}
    city_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n_city)} for k, v in top_c]

    # section 42 by opening year
    s42_rows = []
    for y in range(wy0, ay + 1):
        m = o_ok & (oy == y)
        tot = int(m.sum())
        if tot:
            yes = int((m & (s42 == "כן")).sum())
            s42_rows.append((y, tot, yes / tot))
    s42c = {"x": [str(y) for y, _, _ in s42_rows],
            "y": [round(s * 100, 1) for _, _, s in s42_rows]}
    s42_tbl = [{"year": str(y), "total": _int(t), "share": _pct(s)} for y, t, s in s42_rows]
    s42_all = float((s42 == "כן").mean()) if n else 0.0

    # procedure funnel
    funnel_items = [
        ("תיקים במאגר", n),
        ("ניתן צו כינוס", int(rec_ok.sum())),
        ("ניתן צו פשיטת רגל", int(bk_ok.sum())),
        ("הוגש דוח מנהל מיוחד", int(rep_ok.sum())),
        ("הוגשה תכנית פירעון", int(plan_ok.sum())),
        ("אושר דוח מסכם", int(summ_ok.sum())),
        ("הסתיים בהפטר", int((outcome == DISCHARGE).sum())),
    ]
    funnel = {"names": [k for k, _ in funnel_items], "values": [v for _, v in funnel_items]}
    funnel_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n)} for k, v in funnel_items]

    def _ontime(done, done_ok, due):
        due_ok = (~np.isnat(due)) & (due >= np.datetime64(f"{MIN_YEAR}-01-01"))
        m = done_ok & due_ok
        if m.sum() < 100:
            return None
        late = (done[m] - due[m]).astype("timedelta64[D]").astype(float)
        return float((late <= 0).mean()), float(np.median(late)), int(m.sum())
    rep_time = _ontime(rep, rep_ok, rep_due)
    plan_time = _ontime(plan, plan_ok, plan_due)

    # amounts
    bank_pos = bank[np.isfinite(bank) & (bank > 0)]
    amt_pos = amt[np.isfinite(amt) & (amt > 0)]
    bank_b = _bucket(bank_pos, BANK_BUCKETS)
    amt_b = _bucket(amt_pos, ORDER_BUCKETS)
    money = {
        "bank": {"names": [k for k, _ in bank_b], "values": [v for _, v in bank_b]},
        "amt": {"names": [k for k, _ in amt_b], "values": [v for _, v in amt_b]},
    }
    bank_tbl = [{"name": k, "n": _int(v), "share": _pct(v / len(bank_pos)) if len(bank_pos) else "0.0%"}
                for k, v in bank_b]
    amt_tbl = [{"name": k, "n": _int(v), "share": _pct(v / len(amt_pos)) if len(amt_pos) else "0.0%"}
               for k, v in amt_b]

    disc = outcome == DISCHARGE

    return {
        "n": n, "as_of": as_of, "partial": partial, "full_y": full_y, "y0": y0, "before": before,
        "years": years, "opens": opens, "yearly": yearly, "heat": heat, "month_tot": month_tot,
        "reasons": reasons, "reasons_tbl": reasons_tbl, "n_reason": n_reason,
        "mix": mix, "mix_tbl": mix_tbl, "cohorts": cohorts, "lag": lag, "c1": c1,
        "duration": duration, "dur_tbl": dur_tbl, "dur_groups": dur_groups, "med_by": med_by,
        "med_all": med_all, "n_dur": n_dur,
        "courts": courts, "court_tbl": court_tbl, "wy0": wy0, "court_all": court_all,
        "cities": cities, "city_tbl": city_tbl, "n_city": n_city, "no_city": n - n_city,
        "s42": s42c, "s42_tbl": s42_tbl, "s42_rows": s42_rows, "s42_all": s42_all,
        "funnel": funnel, "funnel_tbl": funnel_tbl, "rep_time": rep_time, "plan_time": plan_time,
        "money": money, "bank_tbl": bank_tbl, "amt_tbl": amt_tbl,
        "bank_n": len(bank_pos), "bank_med": float(np.median(bank_pos)) if len(bank_pos) else None,
        "amt_n": len(amt_pos), "amt_med": float(np.median(amt_pos)) if len(amt_pos) else None,
        "ended_share": ended_share, "disc_share": float(disc.sum()) / n if n else 0.0,
        "opened_dates": opened, "o_ok": o_ok, "oy": oy,
    }


# ── companies ───────────────────────────────────────────────────────────

def _companies(df, as_of):
    n = len(df)
    ay = as_of.year
    filed = _dates(df[C_FILE]); f_ok = _valid(filed, as_of); fy = _years(filed)
    order = _dates(df[C_ORDER]); or_ok = _valid(order, as_of); ory = _years(order)
    can = _dates(df[C_CAN]); can_ok = _valid(can, as_of)
    close = _dates(df[C_CLOSE]); cl_ok = _valid(close, as_of); cly = _years(close)
    status = _labels(df[C_STATUS])
    reason = _labels(df[C_REASON])
    court = _labels(df[C_COURT])
    city = _labels(df[C_CITY], _city)

    y0 = min(_start_year(fy, f_ok, ay), _start_year(cly, cl_ok, ay))
    yearly = {
        "x": [str(y) for y in range(y0, ay + 1)],
        "series": [
            {"name": "בקשות פירוק שהוגשו", "data": _year_counts(fy, f_ok, y0, ay)},
            {"name": "צווי פירוק", "data": _year_counts(ory, or_ok, y0, ay)},
            {"name": "תיקים שנסגרו", "data": _year_counts(cly, cl_ok, y0, ay)},
        ],
    }
    filings = yearly["series"][0]["data"]
    closes = yearly["series"][2]["data"]

    is_closed = np.array(["סגור" in s for s in status])
    not_closed = int((~is_closed).sum())

    has_r = reason != ""
    top_r, rest = _top(reason[has_r], TOP_C_REASONS)
    nr = int(has_r.sum())
    reasons = {"names": [k for k, _ in top_r] + ([OTHER + " (סיבות נוספות)"] if rest else []),
               "values": [v for _, v in top_r] + ([rest] if rest else [])}
    reasons_tbl = [{"name": k, "n": _int(v), "share": _pct(v / nr)}
                   for k, v in zip(reasons["names"], reasons["values"])]

    court_all, _ = _top(court)
    courts = {"names": [k for k, _ in court_all], "values": [v for _, v in court_all]}
    court_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n)} for k, v in court_all]

    has_c = city != ""
    top_c, _ = _top(city[has_c], TOP_C_CITIES)
    cities = {"names": [k for k, _ in top_c], "values": [v for _, v in top_c]}
    city_tbl = [{"name": k, "n": _int(v), "share": _pct(v / int(has_c.sum()))} for k, v in top_c]

    dm = or_ok & cl_ok & (close >= order)
    dur = (close[dm] - order[dm]).astype("timedelta64[D]").astype(float) / 365.25
    dm2 = f_ok & or_ok & (order >= filed)
    to_order = (order[dm2] - filed[dm2]).astype("timedelta64[D]").astype(float)
    dur_b = _bucket(dur, DUR_BUCKETS)
    duration = {"names": [k for k, _ in dur_b], "values": [v for _, v in dur_b]}
    dur_tbl = [{"name": k, "n": _int(v), "share": _pct(v / len(dur)) if len(dur) else "0.0%"}
               for k, v in dur_b]
    frozen = int(can_ok.sum())

    return {
        "n": n, "y0": y0, "yearly": yearly, "filings": filings, "closes": closes,
        "not_closed": not_closed, "reasons": reasons, "reasons_tbl": reasons_tbl, "n_reason": nr,
        "courts": courts, "court_tbl": court_tbl, "cities": cities, "city_tbl": city_tbl,
        "no_city": int((~has_c).sum()), "duration": duration, "dur_tbl": dur_tbl,
        "med_dur": float(np.median(dur)) if len(dur) else None, "n_dur": len(dur),
        "med_to_order": float(np.median(to_order)) if len(to_order) else None,
        "frozen": frozen,
    }


# ── claims ──────────────────────────────────────────────────────────────

def _claims(df):
    n = len(df)
    d = _dates(df.pop(D_DATE))
    as_of = _as_of(d, CLAIMS_DAY_MIN)
    ay = as_of.year
    ok = _valid(d, as_of)
    yy = _years(d)
    typ = _labels(df.pop(D_TYPE))
    st = _labels(df.pop(D_STATUS))
    sys_ = _labels(df.pop(D_SYS))
    amt = _num_col(df.pop(D_AMT))
    app = _num_col(df.pop(D_APP))
    pri = _num_col(df.pop(D_PRI))
    amt = np.where(np.isfinite(amt), amt, 0.0)
    app = np.where(np.isfinite(app), app, 0.0)
    pri = np.where(np.isfinite(pri), pri, 0.0)

    systems = [k for k, _ in _top(sys_)[0]]
    y0 = _start_year(yy, ok, ay)
    yearly = {"x": [str(y) for y in range(y0, ay + 1)],
              "series": [{"name": s, "data": _year_counts(yy, ok & (sys_ == s), y0, ay)}
                         for s in systems]}
    totals = [sum(v) for v in zip(*[s["data"] for s in yearly["series"]])] if systems else []
    yearly_tbl = [{"year": x, "vals": [_int(s["data"][i]) for s in yearly["series"]],
                   "total": _int(totals[i])} for i, x in enumerate(yearly["x"])]

    pos = amt > 0
    types = [k for k, _ in _top(typ)[0] if k != ""]
    decided = (st == "אושר") | (st == "לא אושר")
    type_rows = []
    for t in types:
        m = typ == t
        cnt = int(m.sum())
        mp = m & pos
        med = float(np.median(amt[mp])) if mp.any() else 0.0
        dm = m & decided
        rate = float((m & (st == "אושר")).sum()) / int(dm.sum()) if dm.sum() >= 30 else None
        apm = m & (st == "אושר")
        ap_sum = float(app[apm].sum())
        pri_share = float(pri[apm].sum()) / ap_sum if ap_sum > 0 else None
        type_rows.append({"name": t, "n": cnt, "med": med, "rate": rate, "pri": pri_share})
    by_type = {"names": [r["name"] for r in type_rows], "values": [r["n"] for r in type_rows],
               "med": [round(r["med"]) for r in type_rows]}
    type_tbl = [{"name": r["name"], "n": _int(r["n"]), "share": _pct(r["n"] / n),
                 "med": _int(r["med"]),
                 "rate": _pct(r["rate"]) if r["rate"] is not None else "אין מספיק החלטות",
                 "pri": _pct(r["pri"]) if r["pri"] is not None else "אין"}
                for r in type_rows]
    pri_chart = {"names": [r["name"] for r in type_rows if r["pri"] is not None],
                 "values": [round(r["pri"] * 100, 1) for r in type_rows if r["pri"] is not None]}

    # claimant mix per system (share of the system's claims)
    sys_mix = {"names": types, "series": []}
    sys_tbl = []
    for s in systems:
        ms = sys_ == s
        tot = int(ms.sum())
        shares = [float((ms & (typ == t)).sum()) / tot if tot else 0.0 for t in types]
        sys_mix["series"].append({"name": s, "data": [round(v * 100, 1) for v in shares]})
        med = float(np.median(amt[ms & pos])) if (ms & pos).any() else 0.0
        sys_tbl.append({"name": s, "n": tot, "med": med, "shares": shares})
    sys_mix_tbl = [{"name": t, "vals": [_pct(r["shares"][i]) for r in sys_tbl]}
                   for i, t in enumerate(types)]

    # claimant mix by year
    wy0 = max(y0, ay - WINDOW_YEARS + 1)
    wm = ok & (yy >= wy0)
    ymix = {"x": [str(y) for y in range(wy0, ay + 1)], "series": []}
    ytot = _year_counts(yy, wm, wy0, ay)
    for t in types:
        cnts = _year_counts(yy, wm & (typ == t), wy0, ay)
        ymix["series"].append({"name": t, "data": [round(c / tt * 100, 1) if tt else 0
                                                   for c, tt in zip(cnts, ytot)]})

    st_top, _ = _top(st)
    status = {"names": [k for k, _ in st_top], "values": [v for _, v in st_top]}
    status_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n)} for k, v in st_top]

    size_b = _bucket(amt[pos], CLAIM_BUCKETS)
    n_pos = int(pos.sum())
    size = {"names": [k for k, _ in size_b], "values": [v for _, v in size_b]}
    size_tbl = [{"name": k, "n": _int(v), "share": _pct(v / n_pos)} for k, v in size_b]

    n_dec = int(decided.sum())
    return {
        "n": n, "as_of": as_of, "ay": ay, "partial": _partial(as_of), "y0": y0,
        "before": int((ok & (yy < y0)).sum()), "no_date": int((~ok).sum()),
        "yearly": yearly, "yearly_tbl": yearly_tbl, "totals": totals, "systems": systems,
        "by_type": by_type, "type_tbl": type_tbl, "type_rows": type_rows,
        "pri": pri_chart, "sys_mix": sys_mix, "sys_mix_tbl": sys_mix_tbl, "sys_tbl": sys_tbl,
        "ymix": ymix, "wy0": wy0, "status": status, "status_tbl": status_tbl,
        "size": size, "size_tbl": size_tbl, "n_pos": n_pos, "non_pos": n - n_pos,
        "median": float(np.median(amt[pos])) if n_pos else 0.0,
        "approve_rate": float((st == "אושר").sum()) / n_dec if n_dec else None,
        "approved_share_all": float((st == "אושר").sum()) / n if n else 0.0,
        "pending_share": float((st == "טרם").sum()) / n if n else 0.0,
    }


# ── insights ────────────────────────────────────────────────────────────

def _ins_peak(b):
    o = b["opens"]
    ys = b["years"]
    last = ys.index(b["full_y"]) if b["full_y"] in ys else None
    if last is None or len(o) < 5:
        return None
    pk = int(np.argmax(o))
    if pk == last or o[pk] == 0:
        return None
    drop = 1 - o[last] / o[pk]
    if drop < 0.15:
        return None
    txt = (f"שיא תיקי פשיטת הרגל במאגר הוא בשנת {ys[pk]}, עם {_int(o[pk])} תיקים שנפתחו; "
           f"בשנת {ys[last]} נפתחו {_int(o[last])}, ירידה של {_pct(drop, 0)} מהשיא.")
    if b["ended_share"] >= ENDED_NOTE_SHARE:
        txt += " המאגר כולל כמעט רק תיקים שכבר הסתיימו, ולכן השנים האחרונות חסרות תיקים שעדיין מתנהלים."
    return txt


def _ins_ytd(b):
    # a same-period comparison is only fair when running cases are in the file
    if not b["partial"] or b["ended_share"] >= ENDED_NOTE_SHARE:
        return None
    as_of = b["as_of"]
    y = as_of.year
    opened, ok, oy = b["opened_dates"], b["o_ok"], b["oy"]
    cur = int((ok & (oy == y)).sum())
    prev_cut = np.datetime64(f"{y - 1}-{as_of.month:02d}-{as_of.day:02d}") if not (
        as_of.month == 2 and as_of.day == 29) else np.datetime64(f"{y - 1}-02-28")
    prev = int((ok & (oy == y - 1) & (opened <= prev_cut)).sum())
    if prev < 50:
        return None
    ch = cur / prev - 1
    if abs(ch) < 0.05:
        word = "דומה למספר"
        return (f"בשנת {y} (עד {_dmy(as_of)}) נרשמו במאגר {_int(cur)} תיקים חדשים, "
                f"{word} בתקופה המקבילה בשנת {y - 1} ({_int(prev)}).")
    word = "ירידה" if ch < 0 else "עלייה"
    return (f"בשנת {y} (עד {_dmy(as_of)}) נרשמו במאגר {_int(cur)} תיקים חדשים, לעומת {_int(prev)} "
            f"בתקופה המקבילה בשנת {y - 1}: {word} של {_pct(abs(ch), 0)}.")


def _ins_outcome(b):
    if b["n_reason"] < 100:
        return None
    top = b["reasons"]["names"][0]
    share = b["reasons"]["values"][0] / b["n_reason"]
    return (f"הסיבה השכיחה לביטול צו היא \"{top}\" ({_pct(share)} מהתיקים עם סיבה רשומה); "
            f"בסך הכול {_pct(b['disc_share'])} מתיקי החייבים במאגר הסתיימו בהפטר מחובות.")


def _ins_duration(b):
    mb = b["med_by"]
    if DISCHARGE not in mb or ABUSE not in mb:
        return None
    d, a = mb[DISCHARGE][0], mb[ABUSE][0]
    if d <= a * 1.2:
        return None
    return (f"הדרך להפטר ארוכה: מפתיחת התיק ועד ביטול הצו עוברות בחציון {_num(d)} שנים בתיקים "
            f"שהסתיימו בהפטר, לעומת {_num(a)} שנים בתיקים שבוטלו בשל ניצול לרעה או מחדלים.")


def _ins_mix(b):
    co = b["cohorts"]
    if len(co) < 4:
        return None
    i = OUTCOMES.index(DISCHARGE)
    first, last = co[0], co[-1]
    diff = last[2][i] - first[2][i]
    if abs(diff) < 0.05:
        return None
    word = "עלה" if diff > 0 else "ירד"
    return (f"שיעור התיקים שהסתיימו בהפטר {word} מ-{_pct(first[2][i], 0)} בתיקים שנפתחו ב-{first[0]} "
            f"ל-{_pct(last[2][i], 0)} בתיקים שנפתחו ב-{last[0]}.")


def _ins_s42(b):
    rows = [r for r in b["s42_rows"] if r[1] >= 200]
    if len(rows) < 4:
        return None
    pk = max(rows, key=lambda r: (r[2], r[0]))
    last = rows[-1]
    if pk[0] == last[0] or pk[2] - last[2] < 0.15:
        return None
    return (f"שיעור צווי הכינוס שכללו את סעיף 42 הגיע לשיא של {_pct(pk[2], 0)} בתיקים שנפתחו ב-{pk[0]}, "
            f"וירד ל-{_pct(last[2], 0)} בתיקים שנפתחו ב-{last[0]}.")


def _ins_report(b):
    rt = b["rep_time"]
    if rt is None:
        return None
    share, med, cnt = rt
    if share >= 0.5:
        return (f"{_pct(share, 0)} מדוחות המנהל המיוחד הוגשו עד המועד המתוכנן "
                f"(מתוך {_int(cnt)} תיקים עם דוח ומועד).")
    return (f"רק {_pct(share, 0)} מדוחות המנהל המיוחד הוגשו עד המועד המתוכנן; בחציון הדוח הוגש "
            f"{_int(med)} ימים אחרי המועד (מתוך {_int(cnt)} תיקים עם דוח ומועד).")


def _ins_city(b):
    c = b["cities"]
    if len(c["names"]) < 3 or b["n_city"] < 1000:
        return None
    top3 = sum(c["values"][:3]) / b["n_city"]
    return (f"שלוש הערים עם הכי הרבה חייבים הן {c['names'][0]} ({_int(c['values'][0])}), "
            f"{c['names'][1]} ({_int(c['values'][1])}) ו{c['names'][2]} ({_int(c['values'][2])}): "
            f"{_pct(top3)} מהתיקים שבהם רשומה עיר.")


def _ins_companies(c, as_of):
    f = c["filings"]
    ys = list(range(c["y0"], as_of.year + 1))
    if not f or max(f) == 0:
        return None
    pk = max(f)
    active = [y for y, v in zip(ys, f) if v >= pk * 0.1]
    last_y = active[-1]
    after = sum(v for y, v in zip(ys, f) if y > last_y)
    cl_recent = sum(c["closes"][-3:])
    if last_y >= as_of.year - 1:
        return None
    return (f"קובץ החברות בפירוק הוא תיק היסטורי: בקשות פירוק חדשות נרשמו בו עד {last_y} "
            f"(ומאז רק {_int(after)}), אבל סגירת התיקים הישנים נמשכת, "
            f"עם {_int(cl_recent)} תיקים שנסגרו בשלוש השנים האחרונות במאגר.")


def _ins_claims_type(cl):
    rows = cl["type_rows"]
    if len(rows) < 2:
        return None
    top = rows[0]
    big = max(rows, key=lambda r: (r["med"], r["name"]))
    if big["name"] == top["name"]:
        return (f"\"{top['name']}\" הגישו את מספר תביעות החוב הגדול ביותר ({_int(top['n'])}, "
                f"{_pct(top['n'] / cl['n'])}), וגם התביעה החציונית שלהם היא הגבוהה ביותר: "
                f"{_int(top['med'])} ₪, לעומת {_int(cl['median'])} ₪ בכלל התביעות.")
    return (f"\"{top['name']}\" הגישו את מספר תביעות החוב הגדול ביותר ({_int(top['n'])}, "
            f"{_pct(top['n'] / cl['n'])}), אך התביעה החציונית הגבוהה ביותר היא של "
            f"\"{big['name']}\": {_int(big['med'])} ₪, לעומת {_int(cl['median'])} ₪ בכלל התביעות.")


def _ins_claims_sys(cl):
    rows = cl["sys_tbl"]
    names = cl["sys_mix"]["names"]
    if len(rows) < 2 or "עובדים" not in names:
        return None
    i = names.index("עובדים")
    hi = max(rows, key=lambda r: (r["shares"][i], r["name"]))
    lo = min(rows, key=lambda r: (r["shares"][i], r["name"]))
    if hi["shares"][i] - lo["shares"][i] < 0.1:
        return None
    return (f"עובדים מגישים {_pct(hi['shares'][i])} מתביעות החוב בתיקי {hi['name']}, "
            f"לעומת {_pct(lo['shares'][i])} בתיקי {lo['name']}.")


def _ins_priority(cl):
    rows = [r for r in cl["type_rows"] if r["pri"] is not None and r["n"] >= 1000]
    if len(rows) < 3:
        return None
    hi = max(rows, key=lambda r: (r["pri"], r["name"]))
    if hi["pri"] < 0.1:
        return None
    return (f"מהסכומים שאושרו ל\"{hi['name']}\", {_pct(hi['pri'])} אושרו בדין קדימה, "
            f"כלומר ייפרעו לפני הנושים הרגילים.")


def _ins_pending(cl):
    if cl["pending_share"] < 0.2:
        return None
    return (f"{_pct(cl['pending_share'])} מתביעות החוב במאגר עדיין בסטטוס \"טרם\", "
            f"ו-{_pct(cl['approved_share_all'])} אושרו.")


# ── main ────────────────────────────────────────────────────────────────

def compute(frames):
    b = _debtors(frames["debtors"])
    as_of = b["as_of"]
    c = _companies(frames["companies"], as_of)
    cl = _claims(frames["claims"])

    ay = as_of.year
    nb, nc, ncl = b["n"], c["n"], cl["n"]

    insights = []
    for iid, fn in [
        ("peak", lambda: _ins_peak(b)),
        ("ytd", lambda: _ins_ytd(b)),
        ("outcome", lambda: _ins_outcome(b)),
        ("duration", lambda: _ins_duration(b)),
        ("mix", lambda: _ins_mix(b)),
        ("report", lambda: _ins_report(b)),
        ("s42", lambda: _ins_s42(b)),
        ("city", lambda: _ins_city(b)),
        ("companies", lambda: _ins_companies(c, as_of)),
        ("claims_type", lambda: _ins_claims_type(cl)),
        ("claims_sys", lambda: _ins_claims_sys(cl)),
        ("priority", lambda: _ins_priority(cl)),
        ("pending", lambda: _ins_pending(cl)),
    ]:
        t = fn()
        if t:
            insights.append({"id": iid, "text_he": t})

    pk_i = int(np.argmax(b["opens"]))
    peak_year, peak_n = b["years"][pk_i], b["opens"][pk_i]
    disc_med = b["med_by"].get(DISCHARGE)

    kpis = {
        "cases": {"value": nb, "display": _int(nb), "tone": "brand"},
        "peak_year": {"value": peak_year, "display": str(peak_year), "tone": "brand"},
        "discharge": {"value": round(b["disc_share"], 4), "display": _pct(b["disc_share"]),
                      "tone": "brand"},
        "disc_years": ({"value": round(disc_med[0], 1), "display": _num(disc_med[0]), "tone": "brand"}
                       if disc_med else {"value": None, "display": "אין", "tone": "brand"}),
        "companies": {"value": nc, "display": _int(nc), "tone": "brand"},
        "not_closed": {"value": c["not_closed"], "display": _int(c["not_closed"]),
                       "tone": "warn" if c["not_closed"] > 0 else "ok"},
        "claims": {"value": ncl, "display": _int(ncl), "tone": "brand"},
        "claim_median": {"value": round(cl["median"]), "display": _int(cl["median"]), "tone": "brand"},
        "approve_rate": ({"value": round(cl["approve_rate"], 4), "display": _pct(cl["approve_rate"]),
                          "tone": "ok" if cl["approve_rate"] >= 0.5 else "warn"}
                         if cl["approve_rate"] is not None
                         else {"value": None, "display": "אין", "tone": "brand"}),
    }

    span = f"{b['y0']}-{ay}"
    partial_txt = f" (שנת {ay} חלקית, עד {_dmy(as_of)})" if b["partial"] else ""
    ended_note = (f"{_pct(b['ended_share'])} מתיקי החייבים במאגר כבר הסתיימו (סגורים, בוטלו או הסתיימו בהפטר), "
                  f"כולל תיקים שנפתחו בשנים האחרונות. נראה שהמאגר מפרסם בעיקר תיקים שהסתיימו, ולכן מספר "
                  f"התיקים לפי שנת פתיחה בשנים האחרונות נמוך מהמספר שנפתח בפועל."
                  if b["ended_share"] >= ENDED_NOTE_SHARE else "")

    labels = {
        "lede": (f"המאגר של הכונס הרשמי במשרד המשפטים מרכז שלושה קבצים: {_int(nb)} תיקי חייבים בהליך פשיטת רגל, "
                 f"{_int(nc)} תיקי פירוק חברות ו-{_int(ncl)} תביעות חוב שהגישו נושים בהליכים האלה. "
                 f"הנתונים מעודכנים עד {_dmy(as_of)}. העמוד מנתח את מהלך התיקים, איך הם מסתיימים, "
                 f"כמה זמן הם נמשכים ומי הנושים."),
        "ended_note": ended_note,
        "cases_kpi": "תיקי חייבים בהליך פשיטת רגל",
        "peak_year_kpi": f"שנת השיא בפתיחת תיקי חייבים ({_int(peak_n)} תיקים)",
        "discharge_kpi": "מתיקי החייבים במאגר הסתיימו בהפטר",
        "disc_years_kpi": "שנים בחציון מפתיחת התיק ועד הפטר",
        "companies_kpi": "תיקי פירוק חברות",
        "not_closed_kpi": "תיקי פירוק חברות שטרם נסגרו",
        "claims_kpi": "תביעות חוב",
        "claim_median_kpi": "תביעת חוב חציונית (₪)",
        "approve_rate_kpi": "מתביעות החוב שנבדקו אושרו",
        # debtors
        "yearly_note": (f"מספר האירועים בכל שנה לפי התאריך שלהם: פתיחת תיק, צו כינוס, צו פשיטת רגל וביטול צו. "
                        f"מוצגות השנים {span}{partial_txt}; "
                        f"{_int(b['before'])} תיקים שנפתחו לפני {b['y0']} נכללים בסיכומים אך לא בגרף."),
        "yearly_aria": (f"גרף קווים: תיקי פשיטת רגל שנפתחו, צווים וביטולים לפי שנה, {span}. "
                        f"שיא הפתיחות בשנת {b['years'][int(np.argmax(b['opens']))]} עם {_int(max(b['opens']))} תיקים."),
        "heat_note": (f"תיקים שנפתחו בכל חודש, {b['heat']['years'][0]}-{b['heat']['years'][-1]}. "
                      f"גוון כהה יותר הוא יותר תיקים."),
        "heat_aria": (f"מפת חום: תיקי פשיטת רגל שנפתחו לפי חודש ושנה, {b['heat']['years'][0]}-{b['heat']['years'][-1]}. "
                      f"המספר החודשי הגבוה ביותר: {_int(b['heat']['max'])} תיקים."),
        "reasons_note": (f"הסיבה שנרשמה לביטול הצו, ב-{_int(b['n_reason'])} תיקים. "
                         f"{TOP_REASONS} הסיבות השכיחות מוצגות בשמן, השאר מקובצות תחת אחר."),
        "reasons_aria": (f"גרף עמודות: סיבות לביטול צו בתיקי פשיטת רגל. השכיחה: {b['reasons']['names'][0]} "
                         f"עם {_int(b['reasons']['values'][0])} תיקים."),
        "mix_note": (f"התפלגות התוצאות לפי שנת פתיחת התיק, בקבוצות סיבות: הפטר (כל סוגי ההפטר), "
                     f"הסדר, פשרה או פירעון, ניצול לרעה או מחדלים בהליך, ומחיקה, דחייה או ביטול של הבקשה. "
                     f"מוצגות שנות פתיחה עד {b['c1']} שבהן לפחות {_int(COHORT_MIN)} תיקים עם סיבה רשומה: "
                     f"{_pct(LAG_QUANTILE, 0)} מההפטרים מגיעים בתוך {b['lag']} שנים מפתיחת התיק, "
                     f"ולכן בשנים מאוחרות יותר חסרים עדיין תיקים שיסתיימו בהפטר.") if b["cohorts"] else "",
        "mix_aria": (f"גרף עמודות מוערמות: תוצאות תיקי פשיטת רגל באחוזים לפי שנת פתיחה, "
                     f"{b['mix']['x'][0]}-{b['mix']['x'][-1]}.") if b["cohorts"] else "",
        "duration_note": (f"הזמן מפתיחת התיק ועד ביטול הצו, ב-{_int(b['n_dur'])} תיקים עם שני התאריכים. "
                          + (f"החציון: {_num(b['med_all'])} שנים. " if b["med_all"] is not None else "")
                          + "בטבלה השנייה: משך חציוני לפי סוג התוצאה."),
        "duration_aria": (f"גרף עמודות: משך תיקי פשיטת רגל מפתיחה ועד ביטול הצו. "
                          + (f"החציון {_num(b['med_all'])} שנים." if b["med_all"] is not None else "")),
        "courts_note": (f"תיקים שנפתחו בכל שנה לפי בית המשפט שנרשם בתיק, {b['wy0']}-{ay}{partial_txt}."),
        "courts_aria": (f"גרף עמודות מוערמות: תיקי פשיטת רגל לפי בית משפט ושנת פתיחה, {b['wy0']}-{ay}. "
                        f"הגדול בכלל המאגר: {b['court_all'][0][0]} עם {_int(b['court_all'][0][1])} תיקים."),
        "cities_note": (f"{TOP_CITIES} הערים שבהן מתגוררים הכי הרבה חייבים, מתוך {_int(b['n_city'])} תיקים "
                        f"שבהם רשומה עיר ({_int(b['no_city'])} תיקים בלי עיר). איות שונה של אותה עיר אוחד."),
        "cities_aria": (f"גרף עמודות: {TOP_CITIES} הערים עם הכי הרבה תיקי פשיטת רגל. "
                        f"בראש: {b['cities']['names'][0]} עם {_int(b['cities']['values'][0])} תיקים.")
                       if b["cities"]["names"] else "",
        "s42_note": (f"שיעור התיקים שבהם צו הכינוס כלל את סעיף 42, לפי שנת פתיחת התיק, {b['wy0']}-{ay}. "
                     f"בכלל המאגר: {_pct(b['s42_all'])}."),
        "s42_aria": (f"גרף קו: שיעור צווי כינוס הכוללים את סעיף 42 לפי שנת פתיחה, {b['wy0']}-{ay}."),
        "funnel_note": ("כמה מהתיקים הגיעו לכל שלב בהליך. "
                        + (f"דוח המנהל המיוחד הוגש עד המועד המתוכנן ב-{_pct(b['rep_time'][0], 0)} מהתיקים "
                           f"שבהם הוגש דוח ({_delay(b['rep_time'][1])}). " if b["rep_time"] else "")
                        + (f"תכנית הפירעון הוגשה עד המועד המתוכנן ב-{_pct(b['plan_time'][0], 0)} מהתיקים "
                           f"שבהם הוגשה תכנית ({_delay(b['plan_time'][1])})." if b["plan_time"] else "")),
        "funnel_aria": (f"גרף עמודות: שלבי ההליך בתיקי פשיטת רגל. מתוך {_int(nb)} תיקים, "
                        f"{_int(b['funnel']['values'][-1])} הסתיימו בהפטר."),
        "bank_note": (f"יתרת הבנק שנרשמה בתיק, ב-{_int(b['bank_n'])} תיקים עם יתרה חיובית "
                      f"({_int(nb - b['bank_n'])} תיקים עם אפס או בלי יתרה)."
                      + (f" החציון: {_int(b['bank_med'])} ₪." if b["bank_med"] is not None else "")),
        "bank_aria": (f"גרף עמודות: התפלגות יתרת הבנק בתיקי פשיטת רגל, בשקלים."
                      + (f" החציון {_int(b['bank_med'])} ₪." if b["bank_med"] is not None else "")),
        "amt_note": (f"סכום הצו שנקבע בתיק, ב-{_int(b['amt_n'])} תיקים שבהם נרשם סכום "
                     f"({_int(nb - b['amt_n'])} תיקים בלי סכום)."
                     + (f" החציון: {_int(b['amt_med'])} ₪." if b["amt_med"] is not None else "")),
        "amt_aria": (f"גרף עמודות: התפלגות סכום הצו בתיקי פשיטת רגל, בשקלים."
                     + (f" החציון {_int(b['amt_med'])} ₪." if b["amt_med"] is not None else "")),
        # companies
        "c_yearly_note": (f"בקשות פירוק, צווי פירוק ותיקים שנסגרו בכל שנה, {c['y0']}-{ay}{partial_txt}."),
        "c_yearly_aria": (f"גרף קווים: בקשות פירוק חברות, צווי פירוק ותיקים שנסגרו לפי שנה, {c['y0']}-{ay}. "
                          f"שיא הבקשות: {_int(max(c['filings']) if c['filings'] else 0)} בשנה."),
        "c_reasons_note": (f"סיבת הסגירה שנרשמה ב-{_int(c['n_reason'])} תיקים."
                           + (f" בחציון עברו {_num(c['med_dur'])} שנים מצו הפירוק ועד סגירת התיק "
                              f"({_int(c['n_dur'])} תיקים עם שני התאריכים)." if c["med_dur"] is not None else "")),
        "c_reasons_aria": (f"גרף עמודות: סיבות סגירה של תיקי פירוק חברות. השכיחה: {c['reasons']['names'][0]} "
                           f"עם {_int(c['reasons']['values'][0])} תיקים.") if c["reasons"]["names"] else "",
        "c_courts_aria": (f"גרף עמודות: תיקי פירוק חברות לפי בית משפט. הגדול: {c['courts']['names'][0]} "
                          f"עם {_int(c['courts']['values'][0])} תיקים.") if c["courts"]["names"] else "",
        "c_cities_note": (f"{TOP_C_CITIES} הערים שבהן פעלו הכי הרבה חברות בפירוק "
                          f"({_int(c['no_city'])} תיקים בלי עיר)."),
        "c_cities_aria": (f"גרף עמודות: {TOP_C_CITIES} הערים עם הכי הרבה חברות בפירוק. בראש: "
                          f"{c['cities']['names'][0]} עם {_int(c['cities']['values'][0])} תיקים.")
                         if c["cities"]["names"] else "",
        "c_duration_aria": ("גרף עמודות: משך תיקי פירוק חברות מצו הפירוק ועד סגירה."
                            + (f" החציון {_num(c['med_dur'])} שנים." if c["med_dur"] is not None else "")),
        "c_duration_note": ((f"הזמן מצו הפירוק ועד סגירת התיק, ב-{_int(c['n_dur'])} תיקים."
                             f" החציון: {_num(c['med_dur'])} שנים.") if c["med_dur"] is not None else "")
                           + (f" מהגשת הבקשה ועד צו הפירוק עוברים בחציון {_int(c['med_to_order'])} ימים."
                              if c["med_to_order"] is not None else "")
                           + f" ב-{_int(c['frozen'])} תיקים נרשם תאריך ביטול או הקפאה של צו הפירוק.",
        # claims
        "d_yearly_note": (f"תביעות חוב לפי שנת יצירת החוב ולפי סוג ההליך, {cl['y0']}-{cl['ay']}"
                          + (f" (שנת {cl['ay']} חלקית, עד {_dmy(cl['as_of'])})" if cl["partial"] else "")
                          + f". {_int(cl['no_date'])} תביעות בלי תאריך תקין ו-{_int(cl['before'])} תביעות "
                          f"מלפני {cl['y0']} אינן בגרף."),
        "d_yearly_aria": (f"גרף עמודות מוערמות: תביעות חוב לפי שנה וסוג הליך, {cl['y0']}-{cl['ay']}. "
                          f"השנה עם הכי הרבה תביעות: {cl['yearly']['x'][int(np.argmax(cl['totals']))]} "
                          f"עם {_int(max(cl['totals']))}.") if cl["totals"] else "",
        "d_type_note": (f"מספר התביעות לפי סוג התובע. בטבלה גם התביעה החציונית, שיעור האישור מתוך התביעות "
                        f"שהוכרעו (אושר או לא אושר), והחלק מהסכום שאושר בדין קדימה."),
        "d_type_aria": (f"גרף עמודות: תביעות חוב לפי סוג תובע. הגדול: {cl['by_type']['names'][0]} עם "
                        f"{_int(cl['by_type']['values'][0])} תביעות.") if cl["by_type"]["names"] else "",
        "d_sys_note": ("איזה חלק מהתביעות בכל סוג הליך הגיע מכל סוג תובע (באחוזים מתביעות ההליך). "
                       + " ".join(f"תביעה חציונית ב{r['name']}: {_int(r['med'])} ₪." for r in cl["sys_tbl"])),
        "d_sys_aria": ("גרף עמודות: שיעור סוגי התובעים בתביעות חוב, לפי סוג הליך."),
        "d_ymix_note": (f"התפלגות סוגי התובעים בתביעות שנוצרו בכל שנה, {cl['wy0']}-{cl['ay']}."),
        "d_ymix_aria": (f"גרף שטח מוערם: שיעור כל סוג תובע מתביעות החוב לפי שנה, {cl['wy0']}-{cl['ay']}."),
        "d_pri_note": ("החלק מהסכום שאושר שאושר בדין קדימה, כלומר ייפרע לפני הנושים הרגילים, לפי סוג התובע "
                       "(מתוך התביעות שאושרו)."),
        "d_pri_aria": ("גרף עמודות: שיעור הסכום שאושר בדין קדימה לפי סוג תובע."
                       + (f" הגבוה: {cl['pri']['names'][int(np.argmax(cl['pri']['values']))]}."
                          if cl["pri"]["names"] else "")),
        "d_status_note": (f"מצב הטיפול בתביעות החוב. {_pct(cl['pending_share'])} עדיין בסטטוס \"טרם\"."),
        "d_status_aria": (f"גרף עמודות: תביעות חוב לפי סטטוס. השכיח: {cl['status']['names'][0]} עם "
                          f"{_int(cl['status']['values'][0])} תביעות.") if cl["status"]["names"] else "",
        "d_size_note": (f"גודל הסכום שנתבע, ב-{_int(cl['n_pos'])} תביעות עם סכום חיובי "
                        f"({_int(cl['non_pos'])} תביעות עם סכום אפס או שלילי אינן בגרף). "
                        f"התביעה החציונית: {_int(cl['median'])} ₪."),
        "d_size_aria": (f"גרף עמודות: התפלגות סכומי תביעות החוב בשקלים. החציון {_int(cl['median'])} ₪."),
    }

    charts = {
        "yearly": b["yearly"], "heat": b["heat"], "reasons": b["reasons"], "mix": b["mix"],
        "duration": b["duration"], "courts": b["courts"], "cities": b["cities"], "s42": b["s42"],
        "funnel": b["funnel"], "bank": b["money"]["bank"], "amt": b["money"]["amt"],
        "c_yearly": c["yearly"], "c_reasons": c["reasons"], "c_courts": c["courts"],
        "c_cities": c["cities"], "c_duration": c["duration"],
        "d_yearly": cl["yearly"], "d_type": cl["by_type"], "d_sys": cl["sys_mix"],
        "d_ymix": cl["ymix"], "d_pri": cl["pri"], "d_status": cl["status"], "d_size": cl["size"],
    }

    yearly_tbl = [{"year": x, "vals": [_int(s["data"][i]) for s in b["yearly"]["series"]]}
                  for i, x in enumerate(b["yearly"]["x"])]
    c_yearly_tbl = [{"year": x, "vals": [_int(s["data"][i]) for s in c["yearly"]["series"]]}
                    for i, x in enumerate(c["yearly"]["x"])]
    courts_tbl = [{"year": x, "vals": [_int(s["data"][i]) for s in b["courts"]["series"]]}
                  for i, x in enumerate(b["courts"]["x"])]
    ymix_tbl = [{"year": x, "vals": [f"{s['data'][i]:.1f}%" for s in cl["ymix"]["series"]]}
                for i, x in enumerate(cl["ymix"]["x"])]

    tables = {
        "yearly": yearly_tbl, "reasons": b["reasons_tbl"], "mix": b["mix_tbl"],
        "duration": b["dur_tbl"], "dur_groups": b["dur_groups"], "courts": courts_tbl,
        "court_all": b["court_tbl"], "cities": b["city_tbl"], "s42": b["s42_tbl"],
        "funnel": b["funnel_tbl"], "bank": b["bank_tbl"], "amt": b["amt_tbl"],
        "c_yearly": c_yearly_tbl, "c_reasons": c["reasons_tbl"], "c_courts": c["court_tbl"],
        "c_cities": c["city_tbl"], "c_duration": c["dur_tbl"],
        "d_yearly": cl["yearly_tbl"], "d_type": cl["type_tbl"], "d_sys": cl["sys_mix_tbl"],
        "d_ymix": ymix_tbl, "d_status": cl["status_tbl"], "d_size": cl["size_tbl"],
    }

    flags = {
        "mix": len(b["cohorts"]) >= 2,
        "cities": len(b["cities"]["names"]) >= 3,
        "c_cities": len(c["cities"]["names"]) >= 3,
        "c_duration": c["n_dur"] >= 30,
        "pri": len(cl["pri"]["names"]) >= 2,
        "ended_note": bool(ended_note),
    }

    summary = (f"איתור תיקי פשיטת רגל, חברות בפירוק ותביעות חוב במאגר הכונס הרשמי: "
               f"{_int(nb)} תיקי חייבים, {_int(nc)} חברות ו-{_int(ncl)} תביעות חוב.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["פשיטת רגל", "פירוק חברות", "חדלות פירעון", "תביעות חוב",
                               "הכונס הרשמי", "הפטר"],
            "related_ids": ["01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                            "246d949c-a253-4811-8a11-41a137d3d613",
                            "6397d78e-f00f-4657-a03a-3868f845d3c0",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "temporal_coverage": f"{b['y0']}/{ay}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "columns": {
            "yearly": [s["name"] for s in b["yearly"]["series"]],
            "courts": [s["name"] for s in b["courts"]["series"]],
            "mix": OUTCOMES,
            "c_yearly": [s["name"] for s in c["yearly"]["series"]],
            "d_yearly": cl["systems"],
            "d_sys": cl["systems"],
            "d_ymix": [s["name"] for s in cl["ymix"]["series"]],
        },
    }
