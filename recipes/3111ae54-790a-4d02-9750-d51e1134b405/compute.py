"""רשם המשכונות (Ministry of Justice pledges registry) — recipe compute.

One row per (pledge, asset): a pledge (משכון) with several pledged assets
appears once per asset. The pledge-level fields (registration date, status,
status reason, status date) are constant across a pledge's rows, so the page
works on two levels: rows (asset links) and unique pledges.

The column named "תאריך סיבת סטטוס" holds the status REASON (ביוזמת צד,
תום תוקף, ...), not a date; the CKAN header is mislabelled.

What the data is (2026-10): despite the CKAN notes, practically every pledge
in the file is no longer active (a few thousand "פעיל" out of ~5.7M), with
cancellations going back to the 1990s. Pledges still in force are not
published. So counts by REGISTRATION year undercount recent years (most
recent pledges are still active, hence absent); the page leads with
cancellations (status date), which the file does cover, and states the
selection on the page whenever the non-active share is overwhelming.

The table is ~8.5M rows, so everything is vectorised over numpy arrays:
strings are factorised once (few distinct values per column) and dates are
parsed per distinct value, never per row. String columns are popped off the
input frame as soon as they are converted, to keep the heap small.

Every number and sentence on the page comes from here. Insight rules return
a sentence or None when their premise does not hold.
"""
import numpy as np
import pandas as pd

C_ID = "מזהה משכון"
C_REG = "תאריך רישום"
C_STATUS = "סטטוס רישום"
C_REASON = "תאריך סיבת סטטוס"  # holds the status reason (mislabelled header)
C_SDATE = "תאריך סטטוס"
C_REM = "תאריך הסרת הנכס"

ACTIVE = "פעיל"
INACTIVE = "לא פעיל"
EXPIRED = "תום תוקף"
BY_PARTY = "ביוזמת צד"

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני",
                "יולי", "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
WEEKDAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]

# Lifetime buckets, in days: (upper bound exclusive, label).
LIFE_BUCKETS = [
    (31, "עד חודש"),
    (183, "חודש עד חצי שנה"),
    (366, "חצי שנה עד שנה"),
    (731, "שנה עד שנתיים"),
    (1096, "שנתיים עד שלוש"),
    (1827, "שלוש עד חמש שנים"),
    (3653, "חמש עד עשר שנים"),
    (None, "מעל עשר שנים"),
]
ASSET_BUCKETS = [(1, 1, "נכס אחד"), (2, 2, "שני נכסים"), (3, 3, "שלושה נכסים"),
                 (4, 5, "ארבעה עד חמישה"), (6, 10, "שישה עד עשרה"),
                 (11, 50, "11 עד 50"), (51, None, "מעל 50")]
TOP_REASONS = 4          # reasons shown by name; the rest fold into "אחר"
MIX_MIN_CANCELLED = 1000  # a cancellation year enters the reason-mix chart from this count
YTD_MIN_DAYS = 45  # year-to-date comparison only once the new year has this many days
MIN_YEAR_REGISTRATIONS = 100  # first charted year: the first with this many registrations
TERM_TOLERANCE_DAYS = 3  # an expiry this close to a whole-year anniversary had a fixed term
TERM_MAX_SHOWN = 15      # terms above this many years fold into one bar
AGE_MIN_CANCELLED = 1000  # a cancellation year enters the age-at-cancellation chart from this count
AGE_WARMUP_YEARS = 10     # ages are capped by the file's start; skip the first decade of cancellations


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _ddmmyyyy(day):
    d = pd.Timestamp(int(day), unit="D")
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


# ── vectorised conversions ──────────────────────────────────────────────


def _date_days(s):
    """dd/mm/yyyy strings → float days since epoch (NaN when empty/garbage).
    Parsed once per distinct value."""
    codes, uniq = pd.factorize(s, sort=True)
    parsed = pd.to_datetime(pd.Index(uniq).str.strip(), format="%d/%m/%Y", errors="coerce")
    days = np.full(len(uniq) + 1, np.nan)
    ok = ~pd.isna(parsed)
    days[:-1][ok] = parsed[ok].values.astype("datetime64[D]").astype("int64")
    # Implausible years are garbage, not data.
    yr = np.floor(days / 365.2425) + 1970
    days[(yr < 1980) | (yr > 2100)] = np.nan
    return days[codes]  # code -1 → last slot (NaN)


def _labels(s):
    """Strings → (int codes, stripped labels). Codes are value-sorted, so they
    do not depend on row order."""
    codes, uniq = pd.factorize(s, sort=True)
    return codes, [str(u).strip() for u in uniq]


def _year(days):
    return days.astype("int64").astype("datetime64[D]").astype("datetime64[Y]").astype("int64") + 1970


def _month(days):
    return days.astype("int64").astype("datetime64[D]").astype("datetime64[M]").astype("int64") % 12 + 1


def _prepare(df):
    n_raw = len(df)
    pid = pd.to_numeric(df.pop(C_ID), errors="coerce").to_numpy(dtype="float64")
    reg = _date_days(df.pop(C_REG))
    sdate = _date_days(df.pop(C_SDATE))
    rem = _date_days(df.pop(C_REM))
    st_codes, st_labels = _labels(df.pop(C_STATUS))
    rs_codes, rs_labels = _labels(df.pop(C_REASON))

    keep = ~np.isnan(pid) & ~np.isnan(reg)
    pid, reg, sdate, rem = pid[keep], reg[keep], sdate[keep], rem[keep]
    st_codes, rs_codes = st_codes[keep], rs_codes[keep]

    # One record per pledge: sort by id (+ every pledge-level field as a total
    # tie-break, so the pick never depends on row order), keep the first row.
    sd_key = np.nan_to_num(sdate, nan=-1.0)
    order = np.lexsort((rs_codes, st_codes, sd_key, reg, pid))
    pid_s = pid[order]
    first = np.empty(len(pid_s), dtype=bool)
    if len(pid_s):
        first[0] = True
        first[1:] = pid_s[1:] != pid_s[:-1]
    starts = np.flatnonzero(first)
    n_assets = np.diff(np.append(starts, len(pid_s)))
    removed_sorted = (~np.isnan(rem[order])).astype("int64")
    n_removed = np.add.reduceat(removed_sorted, starts) if len(starts) else np.array([], dtype="int64")
    idx = order[starts]

    st_lab = np.array(st_labels + [""], dtype=object)
    rs_lab = np.array(rs_labels + [""], dtype=object)
    p = {
        "reg": reg[idx],
        "sdate": sdate[idx],
        "status": st_lab[st_codes[idx]],
        "reason": rs_lab[rs_codes[idx]],
        "n_assets": n_assets,
        "n_removed": n_removed,
    }
    rows = {"n": int(keep.sum()), "n_raw": n_raw, "rem": rem}
    return p, rows


# ── insight rules ───────────────────────────────────────────────────────


def insight_ytd(ytd):
    """Cancellations so far this year vs the same window a year earlier."""
    # A few days into a new year is too short a window to compare.
    if not ytd or ytd["prev"] <= 0 or ytd["days"] < YTD_MIN_DAYS:
        return None
    y1, v1, y0, v0, end = ytd["year"], ytd["now"], ytd["prev_year"], ytd["prev"], ytd["end_label"]
    ch = (v1 - v0) / v0
    if abs(ch) < 0.03:
        return (f"מתחילת {y1} ועד {end} נמחקו {_int(v1)} משכונות, כמעט ללא שינוי "
                f"לעומת התקופה המקבילה ב-{y0} ({_int(v0)}).")
    word = "יותר" if ch > 0 else "פחות"
    return (f"מתחילת {y1} ועד {end} נמחקו {_int(v1)} משכונות, {_pct(abs(ch))} {word} "
            f"מאשר בתקופה המקבילה ב-{y0} ({_int(v0)}).")


def insight_trend(full_years):
    """Cancellations: last full year vs the one before."""
    if len(full_years) < 2:
        return None
    (y0, v0), (y1, v1) = full_years[-2], full_years[-1]
    if v0 <= 0:
        return None
    ch = (v1 - v0) / v0
    if abs(ch) < 0.03:
        return f"בשנת {y1} נמחקו {_int(v1)} משכונות, כמעט ללא שינוי לעומת {y0} ({_int(v0)})."
    word = "עלייה" if ch > 0 else "ירידה"
    return f"בשנת {y1} נמחקו {_int(v1)} משכונות, {word} של {_pct(abs(ch))} לעומת {y0} ({_int(v0)})."


def insight_spike(monthly):
    """A month of mass cancellation: the busiest month vs the median month."""
    vals = [v for _, v in monthly if v > 0]
    if len(vals) < 24:
        return None
    med = float(np.median(vals))
    (y, m), v = sorted(monthly, key=lambda t: (-t[1], t[0]))[0]
    if med <= 0 or v < 3 * med:
        return None
    return (f"החודש עם הכי הרבה מחיקות הוא {MONTHS_HE[m - 1]} {y}: {_int(v)} משכונות נמחקו בו, "
            f"פי {v / med:.1f} מחודש חציוני ({_int(round(med))}).")


def insight_reasons(reason_counts, n_cancelled):
    if n_cancelled < 100 or not reason_counts:
        return None
    lead, v = reason_counts[0]
    share = v / n_cancelled
    if share < 0.4:
        return None
    exp = dict(reason_counts).get(EXPIRED, 0)
    tail = ""
    if lead != EXPIRED and exp > 0:
        tail = f"; {_pct(exp / n_cancelled)} פקעו בתום תוקף הרישום"
    return (f"{_pct(share)} מהמשכונות שאינם פעילים נמחקו מסיבה \"{lead}\" "
            f"({_int(v)} מתוך {_int(n_cancelled)}){tail}.")


def insight_mix_shift(mix_years, exp_series, partial):
    """How the expiry share moved between its peak year and the latest full year."""
    if partial:
        mix_years, exp_series = mix_years[:-1], exp_series[:-1]
    if len(exp_series) < 5:
        return None
    i = max(range(len(exp_series)), key=lambda k: (exp_series[k], -k))
    peak, last = exp_series[i], exp_series[-1]
    if i == len(exp_series) - 1 or peak - last < 5:
        return None
    return (f"חלקן של מחיקות בתום תוקף ירד: משיא של {peak:.1f}% מהמחיקות בשנת {mix_years[i]} "
            f"ל-{last:.1f}% בשנת {mix_years[-1]}.")


def insight_lifetime(life_days, within_year_share):
    if len(life_days) < 100:
        return None
    med = float(np.median(life_days)) / 365.2425
    return (f"משך החיים החציוני של משכון עד למחיקתו הוא {med:.1f} שנים; "
            f"{_pct(within_year_share)} מהמשכונות שנמחקו הוסרו בתוך שנה מיום הרישום.")


def insight_terms(n_exp, n_on_term, top_terms):
    if n_exp < 200 or not top_terms:
        return None
    share = n_on_term / n_exp
    if share < 0.5:
        return None
    top = top_terms[:3]
    named = ", ".join(("שנה" if t == 1 else f"{t} שנים") for t, _ in top)
    lead = "התקופות הנפוצות" if len(top) > 1 else "התקופה הנפוצה"
    return (f"{_pct(share)} מהמשכונות שפקעו בתום תוקף פקעו בדיוק ביום השנה לרישומם "
            f"(בטווח של {TERM_TOLERANCE_DAYS} ימים), כלומר נרשמו לתקופה קצובה; "
            f"{lead}: {named}.")


def insight_age_shift(age, partial):
    xs, med = age["x"], age["median"]
    if partial:
        xs, med = xs[:-1], med[:-1]
    if len(xs) < 6:
        return None
    a, b = med[0], med[-1]
    if abs(b - a) < 0.5:
        return None
    word = "עלה" if b > a else "ירד"
    return (f"הגיל החציוני של משכון ביום מחיקתו {word} מ-{a:.1f} שנים במחיקות של {xs[0]} "
            f"ל-{b:.1f} שנים במחיקות של {xs[-1]}.")


def insight_assets(n_assets):
    n = len(n_assets)
    if n == 0:
        return None
    multi = int((n_assets > 1).sum())
    share = multi / n
    if share < 0.02:
        return None
    return (f"{_pct(share)} מהמשכונות ({_int(multi)}) משעבדים יותר מנכס אחד; "
            f"המשכון הגדול ביותר כולל {_int(n_assets.max())} נכסים, ולכן במאגר יותר "
            "שורות מאשר משכונות.")


def insight_active(n_active, n_pledges, oldest_active_year):
    if n_pledges == 0:
        return None
    if n_active == 0:
        return "אין במאגר משכונות בסטטוס פעיל: כל המשכונות בו נמחקו או פקעו."
    share = n_active / n_pledges
    if n_active == 1:
        return (f"רק משכון אחד מתוך {_int(n_pledges)} המשכונות במאגר רשום כפעיל"
                + (f"; הוא נרשם בשנת {oldest_active_year}." if oldest_active_year else "."))
    tail = f"; הוותיק שבהם נרשם בשנת {oldest_active_year}" if oldest_active_year else ""
    if share < 0.05:
        return (f"המאגר הוא בעיקרו היסטוריה של משכונות שנמחקו: רק {_int(n_active)} מתוך "
                f"{_int(n_pledges)} המשכונות ({_pct(share, 2)}) רשומים כפעילים{tail}.")
    return f"{_int(n_active)} מהמשכונות במאגר ({_pct(share)}) רשומים כפעילים{tail}."


def insight_weekday(wd_counts):
    tot = sum(wd_counts)
    if tot < 1000:
        return None
    work = sum(wd_counts[0:5])
    i = max(range(7), key=lambda k: (wd_counts[k], -k))
    return (f"{_pct(work / tot)} מהמחיקות נרשמו בימים ראשון עד חמישי; "
            f"היום העמוס ביותר הוא יום {WEEKDAYS_HE[i]} ({_pct(wd_counts[i] / tot)}).")


# ── compute ─────────────────────────────────────────────────────────────


def _days_of(ts):
    return (ts - pd.Timestamp(0)).days


def compute(frames):
    p, rows = _prepare(frames["main"])
    n_rows = rows["n"]
    n_p = len(p["reg"])
    reg, sdate, status, reason = p["reg"], p["sdate"], p["status"], p["reason"]
    n_assets, n_removed = p["n_assets"], p["n_removed"]

    reg_max = float(np.max(reg))
    reg_y = _year(reg)
    y_last_reg = int(reg_y.max())
    # The page starts at the first registration year with a real volume; a
    # stray earlier date (a typo, typically) is counted but not charted.
    ry_vals, ry_cnt = np.unique(reg_y, return_counts=True)
    big = ry_vals[ry_cnt >= MIN_YEAR_REGISTRATIONS]
    y_first = int(big.min()) if len(big) else int(ry_vals.min())
    n_early = int((reg_y < y_first).sum())

    is_active = status == ACTIVE
    is_inactive = status == INACTIVE
    n_active = int(is_active.sum())
    n_cancelled = int(is_inactive.sum())
    inactive_share = n_cancelled / n_p if n_p else 0.0
    # A status date past the last registration by over a year is garbage.
    sd_ok = ~np.isnan(sdate) & (sdate <= reg_max + 366) & (sdate >= reg)
    data_end = max(reg_max, float(np.max(sdate[sd_ok])) if sd_ok.any() else reg_max)
    end_ts = pd.Timestamp(int(data_end), unit="D")
    y_last = max(y_last_reg, end_ts.year)
    last_partial = not (end_ts.month == 12 and end_ts.day >= 25)
    years = list(range(y_first, y_last + 1))
    year_labels = [f"{y} (חלקית)" if (y == y_last and last_partial) else str(y) for y in years]

    # ── cancellations (non-active pledges, by status date) ──
    canc = is_inactive & sd_ok
    c_day = sdate[canc]
    c_y = _year(c_day)
    c_m = _month(c_day)
    c_reason = np.where(reason[canc] == "", "לא צוין", reason[canc])
    c_life = (sdate - reg)[canc]
    c_in = c_y >= y_first
    canc_by_year = np.bincount(c_y[c_in] - y_first, minlength=len(years))
    reg_by_year = np.bincount(reg_y[reg_y >= y_first] - y_first, minlength=len(years))
    full_canc = [(y, int(v)) for y, v in zip(years, canc_by_year)
                 if not (y == y_last and last_partial) and v > 0]

    ytd = None
    if last_partial and y_last - 1 >= y_first:
        prev_start = pd.Timestamp(year=y_last - 1, month=1, day=1)
        prev_cut = prev_start + pd.Timedelta(days=end_ts.dayofyear - 1)
        prev_n = int(((c_day >= _days_of(prev_start)) & (c_day <= _days_of(prev_cut))).sum())
        ytd = {"year": y_last, "now": int((c_y == y_last).sum()), "prev_year": y_last - 1,
               "prev": prev_n, "days": int(end_ts.dayofyear), "end_label": f"{end_ts.day} ב{MONTHS_HE[end_ts.month - 1]}"}

    # month × year heatmap of cancellations
    hy0 = int(c_y.min()) if len(c_y) else y_last
    heat_years = list(range(hy0, y_last + 1))
    heat = np.zeros((len(heat_years), 12), dtype="int64")
    if len(c_y):
        np.add.at(heat, (c_y - hy0, c_m - 1), 1)
    heat_cells = [[m, yi, int(heat[yi, m])] for yi in range(len(heat_years)) for m in range(12)
                  if not (heat_years[yi] == y_last and m + 1 > end_ts.month)]
    monthly = [((heat_years[yi], m + 1), int(heat[yi, m])) for yi in range(len(heat_years))
               for m in range(12) if not (heat_years[yi] == y_last and m + 1 >= end_ts.month)]
    full_rows = np.array([not (y == y_last and last_partial) for y in heat_years])
    by_month = heat[full_rows].sum(axis=0) if full_rows.any() else heat.sum(axis=0)
    peak_m = int(np.argmax(by_month)) if by_month.sum() else 0
    avg_m = by_month.sum() / 12 if by_month.sum() else 0

    wd_counts = [int(v) for v in np.bincount((c_day.astype("int64") + 4) % 7, minlength=7)]

    # ── reasons ──
    rs_inactive = np.where(reason[is_inactive] == "", "לא צוין", reason[is_inactive])
    r_vals, r_cnt = np.unique(rs_inactive, return_counts=True)
    reason_counts = sorted(zip([str(v) for v in r_vals], [int(c) for c in r_cnt]),
                           key=lambda t: (-t[1], t[0]))
    rc = dict(reason_counts)
    named = [r for r, _ in reason_counts[:TOP_REASONS]]
    other_cnt = sum(c for _, c in reason_counts[TOP_REASONS:])
    reason_names = named + (["אחר"] if other_cnt else [])

    def _bucket_reason(arr):
        out = np.full(len(arr), len(named), dtype="int64")
        for i, r in enumerate(named):
            out[arr == r] = i
        return out

    c_rb = _bucket_reason(c_reason)

    # lifetime histogram, stacked by reason
    bounds = np.array([b for b, _ in LIFE_BUCKETS if b is not None], dtype="float64")
    life_b = np.searchsorted(bounds, c_life, side="right")
    life_hist = np.zeros((len(reason_names), len(LIFE_BUCKETS)), dtype="int64")
    np.add.at(life_hist, (c_rb, life_b), 1)
    life_tot = life_hist.sum(axis=0)
    within_year_share = float((c_life < 366).sum() / len(c_life)) if len(c_life) else 0.0
    med_life = float(np.median(c_life)) / 365.2425 if len(c_life) else 0.0

    reason_table = []
    for i, r in enumerate(reason_names):
        cnt = other_cnt if (r == "אחר" and i == len(named)) else rc[r]
        lr = c_life[c_rb == i]
        reason_table.append({
            "name": r, "n": _int(cnt), "value": int(cnt),
            "share": _pct(cnt / n_cancelled) if n_cancelled else "0.0%",
            "median": f"{np.median(lr) / 365.2425:.1f}" if len(lr) else "",
        })

    # reason mix by cancellation year
    mix_years, mix_rows = [], []
    mix = {r: [] for r in reason_names}
    for y in years:
        sel = c_y == y
        tot = int(sel.sum())
        if tot < MIX_MIN_CANCELLED:
            continue
        cnts = np.bincount(c_rb[sel], minlength=len(reason_names))
        lab = year_labels[y - y_first]
        mix_years.append(lab)
        row = {"year": lab, "total": _int(tot), "shares": []}
        for i, r in enumerate(reason_names):
            mix[r].append(round(float(cnts[i]) / tot * 100, 2))
            row["shares"].append(f"{cnts[i] / tot * 100:.1f}%")
        mix_rows.append(row)

    # fixed terms of expired pledges: expiry on a whole-year anniversary
    exp_life = c_life[c_reason == EXPIRED]
    t_years = np.round(exp_life / 365.2425)
    on_term = (t_years >= 1) & (np.abs(exp_life - t_years * 365.2425) <= TERM_TOLERANCE_DAYS)
    terms = t_years[on_term].astype("int64")
    n_on_term = int(on_term.sum())
    term_counts = np.bincount(np.minimum(terms, TERM_MAX_SHOWN + 1), minlength=TERM_MAX_SHOWN + 2)[1:]
    term_x = [("שנה" if t == 1 else f"{t} שנים") for t in range(1, TERM_MAX_SHOWN + 1)] + [f"מעל {TERM_MAX_SHOWN}"]
    term_pairs = [(t + 1, int(v)) for t, v in enumerate(term_counts[:TERM_MAX_SHOWN])]
    top_terms = sorted([tp for tp in term_pairs if tp[1] > 0], key=lambda tp: (-tp[1], tp[0]))
    while len(term_x) > 1 and term_counts[len(term_x) - 1] == 0 and len(term_x) - 1 >= TERM_MAX_SHOWN:
        term_x.pop()  # drop an empty "above N" bar
    term_counts = [int(v) for v in term_counts[:len(term_x)]]

    # age at cancellation, per cancellation year (unaffected by which pledges are published)
    age = {"x": [], "p25": [], "median": [], "p75": [], "n": []}
    for y in years:
        sel = c_y == y
        n = int(sel.sum())
        if n < AGE_MIN_CANCELLED or y < y_first + AGE_WARMUP_YEARS:
            continue
        q = np.percentile(c_life[sel], [25, 50, 75]) / 365.2425
        age["x"].append(year_labels[y - y_first])
        age["p25"].append(round(float(q[0]), 2))
        age["median"].append(round(float(q[1]), 2))
        age["p75"].append(round(float(q[2]), 2))
        age["n"].append(n)

    # ── assets per pledge ──
    a_counts = []
    for lo, hi, label in ASSET_BUCKETS:
        m = (n_assets >= lo) if hi is None else ((n_assets >= lo) & (n_assets <= hi))
        a_counts.append({"name": label, "n": int(m.sum()), "rows": int(n_assets[m].sum())})
    multi_share = float((n_assets > 1).sum() / n_p) if n_p else 0.0

    # asset removals (an asset released from a pledge)
    rem = rows["rem"]
    rem_ok = rem[~np.isnan(rem) & (rem <= reg_max + 366)]
    n_rem_rows = int(len(rem_ok))
    rem_y = _year(rem_ok) if n_rem_rows else np.array([], dtype="int64")
    rem_y = rem_y[(rem_y >= y_first) & (rem_y <= y_last)]
    rem_by_year = (np.bincount(rem_y - y_first, minlength=len(years)) if len(rem_y)
                   else np.zeros(len(years), dtype="int64"))
    n_p_removed = int((n_removed > 0).sum())
    rem_first = next((i for i, v in enumerate(rem_by_year) if v > 0), 0)

    act_y = reg_y[is_active]
    oldest_active = int(act_y.min()) if len(act_y) else None

    # ── insights ──
    rules = [
        ("active", insight_active(n_active, n_p, oldest_active)),
        ("ytd", insight_ytd(ytd)),
        ("trend", insight_trend(full_canc)),
        ("spike", insight_spike(monthly)),
        ("reasons", insight_reasons(reason_counts, n_cancelled)),
        ("mix", insight_mix_shift(mix_years, mix.get(EXPIRED, []),
                                   bool(mix_years) and mix_years[-1] == year_labels[-1] and last_partial)),
        ("terms", insight_terms(len(exp_life), n_on_term, top_terms)),
        ("lifetime", insight_lifetime(c_life, within_year_share)),
        ("age", insight_age_shift(age, bool(age["x"]) and age["x"][-1] == year_labels[-1] and last_partial)),
        ("assets", insight_assets(n_assets)),
        ("weekday", insight_weekday(wd_counts)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    last_full = full_canc[-1] if full_canc else None
    exp_share = rc.get(EXPIRED, 0) / n_cancelled if n_cancelled else 0.0
    kpis = {
        "pledges": {"value": n_p, "display": _int(n_p), "tone": "brand"},
        "rows": {"value": n_rows, "display": _int(n_rows), "tone": "brand"},
        "active": {"value": n_active, "display": _int(n_active),
                   "tone": "warn" if inactive_share >= 0.95 else "info"},
        "last_year": {"value": last_full[1] if last_full else 0,
                      "display": _int(last_full[1]) if last_full else "0", "tone": "brand"},
        "median_life": {"value": round(med_life, 1), "display": f"{med_life:.1f}", "tone": "brand"},
        "expired": {"value": round(exp_share * 100, 1), "display": _pct(exp_share), "tone": "info"},
        "span": {"value": y_last - y_first, "display": f"{y_first}–{y_last}", "tone": "brand"},
    }

    # ── labels ──
    peak_c = sorted(full_canc, key=lambda t: (-t[1], t[0]))[0] if full_canc else None
    selection = inactive_share >= 0.95
    sel_note = (f"שימו לב: {_pct(inactive_share, 2)} מהמשכונות במאגר אינם פעילים, ומשכונות פעילים "
                "כמעט אינם מופיעים בו. לכן מספר המשכונות לפי שנת רישום נמוך בשנים האחרונות: "
                "משכונות שנרשמו בהן ולא נמחקו אינם בקובץ. מספר המחיקות בכל שנה אינו מושפע מכך."
                if selection else "")
    labels = {
        "lede": (f"רשם המשכונות במשרד המשפטים מנהל את פנקס המשכונות, שבו נרשמים שעבודים על מטלטלין "
                 f"וזכויות. המאגר כולל {_int(n_p)} משכונות שנרשמו {'ברובם המכריע ' if n_early else ''}בשנים {y_first} עד {y_last_reg}, "
                 f"ב-{_int(n_rows)} שורות (שורה לכל נכס משועבד). {_int(n_cancelled)} מהם נמחקו או פקעו, "
                 f"ו-{_int(n_active)} רשומים כפעילים. הנתונים עדכניים עד {_ddmmyyyy(data_end)}."),
        "selection_note": sel_note,
        "pledges_kpi": "משכונות במאגר",
        "rows_kpi": "שורות במאגר (נכסים משועבדים)",
        "active_kpi": "משכונות בסטטוס פעיל",
        "last_year_kpi": (f"משכונות שנמחקו בשנת {last_full[0]}" if last_full else "משכונות שנמחקו"),
        "median_life_kpi": "משך חיים חציוני של משכון שנמחק (שנים)",
        "expired_kpi": "מהמחיקות: בתום תוקף הרישום",
        "span_kpi": "שנות רישום במאגר",
        "years_note": ("עמודות: משכונות שנמחקו או פקעו בכל שנה (לפי תאריך הסטטוס). קו: המשכונות שבמאגר לפי שנת רישומן. "
                       + ((f"משכון אחד עם תאריך רישום לפני {y_first} אינו מוצג בגרף. " if n_early == 1 else
                          f"{_int(n_early)} משכונות עם תאריך רישום לפני {y_first} אינם מוצגים בגרף. ") if n_early else "")
                       + (f"שנת השיא במחיקות: {peak_c[0]} עם {_int(peak_c[1])}. " if peak_c else "")
                       + (f"שנת {y_last} חלקית: הנתונים עד {_ddmmyyyy(data_end)}." if last_partial else "")),
        "years_aria": (f"גרף עמודות וקו: מחיקות משכונות לפי שנה ומשכונות במאגר לפי שנת רישום, {y_first} עד {y_last}."
                       + (f" שיא המחיקות ב-{peak_c[0]} עם {_int(peak_c[1])}." if peak_c else "")),
        "heat_note": (f"כל תא הוא מספר המשכונות שנמחקו בחודש מסוים, {heat_years[0]} עד {y_last}. "
                      "תאים כהים חריגים מסמנים גלי מחיקה מרוכזים."),
        "heat_aria": (f"מפת חום: מחיקות משכונות לפי חודש ושנה, {heat_years[0]} עד {y_last}."),
        "month_note": (f"סך המחיקות בכל חודש בשנים המלאות. העמוס ביותר: {MONTHS_HE[peak_m]} "
                       f"({_int(by_month[peak_m])}, לעומת ממוצע של {_int(round(avg_m))} לחודש)."),
        "month_aria": f"גרף עמודות: מחיקות משכונות לפי חודש בשנה. העמוס ביותר: {MONTHS_HE[peak_m]}.",
        "weekday_note": "היום בשבוע שבו נרשמה המחיקה, בכל שנות המאגר.",
        "weekday_aria": (f"גרף עמודות: מחיקות משכונות לפי יום בשבוע. "
                         f"{_pct(sum(wd_counts[:5]) / max(1, sum(wd_counts)))} בימים ראשון עד חמישי."),
        "reasons_note": (f"מתוך {_int(n_cancelled)} המשכונות שאינם פעילים: הסיבה הרשומה למחיקה, "
                         "ומשך החיים החציוני של משכון מכל סוג (מיום הרישום עד תאריך הסטטוס)."),
        "reasons_aria": (f"גרף טבעת: סיבות מחיקת משכונות. המובילה: {reason_counts[0][0]} עם "
                         f"{_pct(reason_counts[0][1] / n_cancelled)} מהמשכונות שאינם פעילים."
                         if reason_counts and n_cancelled else "גרף טבעת: סיבות מחיקת משכונות."),
        "mix_note": (f"התפלגות סיבות המחיקה בכל שנה, לפי שנת המחיקה (שנים עם {_int(MIX_MIN_CANCELLED)} "
                     "מחיקות לפחות)."),
        "mix_aria": (f"גרף עמודות מוערמות באחוזים: סיבות מחיקה לפי שנה, {mix_years[0]} עד {mix_years[-1]}."
                     if mix_years else "גרף עמודות מוערמות: סיבות מחיקה לפי שנה."),
        "life_note": (f"כמה זמן עבר מרישום המשכון ועד מחיקתו, לפי סיבת המחיקה. החציון: {med_life:.1f} שנים; "
                      f"{_pct(within_year_share)} נמחקו בתוך שנה."),
        "life_aria": (f"גרף עמודות מוערמות: משך החיים של {_int(len(c_life))} משכונות שנמחקו, לפי טווח זמן "
                      f"וסיבת מחיקה. חציון {med_life:.1f} שנים."),
        "terms_note": (f"משכונות שפקעו בתום תוקף ביום השנה לרישומם (בטווח של {TERM_TOLERANCE_DAYS} ימים): "
                       f"{_int(n_on_term)} מתוך {_int(len(exp_life))} המשכונות שפקעו. "
                       "כל עמודה היא תקופת הרישום שנקבעה למשכון."),
        "terms_aria": (f"גרף עמודות: משכונות שפקעו לפי תקופת הרישום בשנים. הנפוצה: "
                       f"{('שנה' if top_terms[0][0] == 1 else str(top_terms[0][0]) + ' שנים')} "
                       f"עם {_int(top_terms[0][1])} משכונות." if top_terms else
                       "גרף עמודות: משכונות שפקעו לפי תקופת הרישום."),
        "age_note": (f"לכל שנת מחיקה: הגיל החציוני של המשכונות שנמחקו בה (מיום הרישום), והטווח שבין הרבעון "
                     f"התחתון לעליון. מוצגות שנים עם {_int(AGE_MIN_CANCELLED)} מחיקות לפחות, החל מ-{y_first + AGE_WARMUP_YEARS}: "
                     "בשנים הראשונות של המאגר עוד לא היו בו משכונות ותיקים."),
        "age_aria": (f"גרף קווים: גיל חציוני של משכון ביום מחיקתו, לפי שנת מחיקה {age['x'][0]} עד {age['x'][-1]}."
                     if age["x"] else "גרף קווים: גיל משכון ביום מחיקתו."),
        "assets_note": (f"משכון אחד יכול לשעבד כמה נכסים, וכל נכס הוא שורה במאגר. "
                        f"{_pct(multi_share)} מהמשכונות כוללים יותר מנכס אחד. ציר אנכי לוגריתמי."),
        "assets_aria": (f"גרף עמודות: התפלגות מספר הנכסים במשכון. {_pct(1 - multi_share)} מהמשכונות "
                        "כוללים נכס אחד."),
        "removed_note": (f"נכס שהוסר ממשכון: {_int(n_rem_rows)} הסרות במאגר, "
                         f"ב-{_int(n_p_removed)} משכונות שונים."),
        "removed_aria": f"גרף עמודות: נכסים שהוסרו ממשכונות לפי שנת ההסרה. סך הכול {_int(n_rem_rows)} הסרות.",
    }

    charts = {
        "years": {"x": year_labels, "canc": [int(v) for v in canc_by_year],
                  "reg": [int(v) for v in reg_by_year], "partial": bool(last_partial)},
        "heat": {"months": MONTHS_SHORT, "years": [str(y) for y in heat_years], "cells": heat_cells,
                 "max": int(heat.max()) if heat.size else 0},
        "month": {"x": MONTHS_HE, "y": [int(v) for v in by_month]},
        "weekday": {"x": WEEKDAYS_HE, "y": wd_counts},
        "reasons": {"data": [{"name": r["name"], "value": r["value"]} for r in reason_table]},
        "mix": {"x": mix_years, "series": [{"name": r, "data": mix[r]} for r in reason_names]},
        "life": {"x": [b[1] for b in LIFE_BUCKETS],
                 "series": [{"name": r, "data": [int(v) for v in life_hist[i]]}
                            for i, r in enumerate(reason_names)]},
        "terms": {"x": term_x, "y": term_counts},
        "age": age,
        "assets": {"x": [a["name"] for a in a_counts], "y": [a["n"] if a["n"] > 0 else None for a in a_counts]},
        "removed": {"x": [str(y) for y in years[rem_first:]], "y": [int(v) for v in rem_by_year[rem_first:]]},
    }
    tables = {
        "years": [{"year": year_labels[i], "canc": _int(canc_by_year[i]), "reg": _int(reg_by_year[i])}
                  for i in range(len(years))][::-1],
        "month": [{"name": MONTHS_HE[i], "n": _int(by_month[i])} for i in range(12)],
        "weekday": [{"name": WEEKDAYS_HE[i], "n": _int(wd_counts[i]),
                     "share": _pct(wd_counts[i] / max(1, sum(wd_counts)))} for i in range(7)],
        "reasons": reason_table,
        "mix": mix_rows[::-1],
        "life": [{"name": LIFE_BUCKETS[j][1], "total": _int(life_tot[j]),
                  "share": _pct(life_tot[j] / max(1, len(c_life)))} for j in range(len(LIFE_BUCKETS))],
        "terms": [{"name": term_x[i], "n": _int(term_counts[i]),
                   "share": _pct(term_counts[i] / max(1, n_on_term))} for i in range(len(term_x))],
        "age": [{"year": age["x"][i], "n": _int(age["n"][i]), "median": f"{age['median'][i]:.1f}",
                 "p25": f"{age['p25'][i]:.1f}", "p75": f"{age['p75'][i]:.1f}"}
                for i in range(len(age["x"]))][::-1],
        "assets": [{"name": a["name"], "n": _int(a["n"]), "share": _pct(a["n"] / max(1, n_p)),
                    "rows": _int(a["rows"])} for a in a_counts],
        "removed": [{"year": str(y), "n": _int(v)} for y, v in zip(years, rem_by_year) if v > 0][::-1],
    }

    summary = (f"בדיקת משכון ברשם המשכונות לפי מספר משכון ותאריך רישום: {_int(n_p)} משכונות "
               f"מאז {y_first}, {_int(n_cancelled)} מהם נמחקו. סיבות מחיקה, תוקף ומגמות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["משכונות", "שעבוד", "רשם המשכונות", "אשראי", "משרד המשפטים"],
            "related_ids": [
                "246d949c-a253-4811-8a11-41a137d3d613",
                "382c098b-a687-478a-9965-06977d7c9501",
                "6397d78e-f00f-4657-a03a-3868f845d3c0",
                "01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
            ],
            "temporal_coverage": f"{y_first}/{y_last}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"removed": n_rem_rows > 0, "mix": len(mix_years) >= 2,
                  "terms": n_on_term > 0, "age": len(age["x"]) >= 2, "selection": selection},
    }
