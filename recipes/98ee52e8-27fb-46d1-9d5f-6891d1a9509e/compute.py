"""כלי רכב שמותקנים בהם מסננים לצמצום פליטת מזהמים.

One row per vehicle fitted with an emissions-reduction (particulate) filter:
licence plate, EU vehicle category (M1/M2/M3 passenger, N1/N2/N3 goods),
manufacture year, first-registration date and filter-installation date.
The register is a retrofit programme's record: an older diesel fleet, most
of it fitted in one burst. The page tells that story — when (monthly,
yearly, per-category waves, bulk-recorded days, weekdays), what (category
mix) and how old (manufacture vintage, age at installation, registration
lag).

- The plate is a lookup identifier and never reaches the page; everything
  is aggregated.
- "Latest" is the latest installation date in the data, never the clock;
  a last calendar year that ends before December is labelled partial.
- Unknown EU codes flow through after the known ones; categories smaller
  than MIN_CAT stay in counts but are left out of per-category
  distribution views (disclosed).
"""
import pandas as pd

MIN_CAT = 30                # vehicles, for per-category boxplot / wave / timing views
PEAK_SHARE = 0.4            # a single year holding >= 40% of installs is "a burst"
TAIL_SHARE = 0.1            # years after peak+1 holding < 10% = "petered out"
LEADER_SHARE = 0.4
WAVE_GAP_DAYS = 180         # median install dates this far apart = distinct waves
VINTAGE_MIN_SHARE = 0.01    # last manufacture year with >= 1% of the fleet
VINTAGE_SHARE = 0.95
AGE_MIN_MEDIAN = 10
OLD_AGE = 10
TOP_DAYS = 10
BULK_SHARE = 0.2
LAG_SHARE = 0.03
YEAR_FROM = 1990
MONTHLY_MAX = 180           # months; longer spans switch the timeline to quarters

CAT_ORDER = ["N3", "N2", "N1", "M3", "M2", "M1", "O1", "O2", "O3", "O4"]
CAT_DESC = {
    "M1": "רכב נוסעים",
    "M2": "מיניבוס עד 5 טון",
    "M3": "אוטובוס מעל 5 טון",
    "N1": "רכב משא עד 3.5 טון",
    "N2": "משאית 3.5 עד 12 טון",
    "N3": "משאית מעל 12 טון",
    "O1": "גרור קל",
    "O2": "גרור עד 3.5 טון",
    "O3": "גרור 3.5 עד 10 טון",
    "O4": "גרור מעל 10 טון",
}
UNKNOWN = "לא צוין"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
WEEKDAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
LAG_BUCKETS = [(None, -1, "שנה לפני שנת הייצור"), (0, 0, "באותה שנה"),
               (1, 1, "שנה אחרי"), (2, 5, "2 עד 5 שנים אחרי"),
               (6, 10, "6 עד 10 שנים אחרי"), (11, None, "מעל 10 שנים אחרי")]
AGE_BUCKETS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, None)]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    """v is a fraction; bidi-isolated percent that never rounds a partial share to 0/100."""
    x = v * 100
    step = 10 ** -digits
    if 0 < x < step:
        return f"פחות מ-{LRI}{step:.{digits}f}%{PDI}"
    if 100 - step < x < 100:
        x = 100 - step
    return f"{LRI}{x:.{digits}f}%{PDI}"


def pct_plain(v):
    x = v * 100
    if 0 < x < 0.1:
        x = 0.1
    elif 99.9 < x < 100:
        x = 99.9
    return f"{x:.1f}%"


def month_he(ts):
    return f"{MONTHS_HE[ts.month - 1]} {ts.year}"


def date_he(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def cat_label(c):
    d = CAT_DESC.get(c)
    return f"{c} — {d}" if d else c


def cat_short(c):
    d = CAT_DESC.get(c)
    return f"{d} ({c})" if d else c


def _ranked(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _cat_order(cats):
    present = set(cats)
    counts = _ranked(cats)
    known = [c for c in CAT_ORDER if c in present]
    return known + [c for c in counts.index if c not in CAT_ORDER]


def _prepare(df):
    cat = df["sug_rechev_EU_cd"].str.strip().str.upper().replace("", UNKNOWN)
    out = pd.DataFrame({
        "cat": cat,
        "year": pd.to_numeric(df["shnat_yitzur"].str.strip(), errors="coerce"),
        "reg": pd.to_datetime(df["rishum_rishon_dt"].str.strip().str[:10],
                              errors="coerce", format="%Y-%m-%d"),
        "inst": pd.to_datetime(df["taarich_hatkana"].str.strip().str[:10],
                               errors="coerce", format="%Y-%m-%d"),
    })
    out.loc[~out["year"].between(1900, 2100), "year"] = float("nan")
    return out


# ── insight rules ──────────────────────────────────────────────────────────


def insight_peak(by_year, total_dated):
    if by_year.empty or total_dated == 0:
        return None
    peak = int(by_year.sort_index().sort_values(ascending=False, kind="stable").index[0])
    share = by_year[peak] / total_dated
    if share < PEAK_SHARE:
        return None
    upto = by_year[by_year.index <= peak].sum() / total_dated
    return (f"עיקר ההתקנות בוצעו בגל אחד: {n(by_year[peak])} מסננים ({pct(share)}) הותקנו ב-{peak}, "
            f"ועד סוף {peak} הותקנו {pct(upto)} מכלל המסננים במאגר.")


def insight_tail(by_year, total_dated, last_date):
    if by_year.empty:
        return None
    peak = int(by_year.sort_index().sort_values(ascending=False, kind="stable").index[0])
    after = by_year[by_year.index >= peak + 2]
    if after.empty:
        return None
    k = int(after.sum())
    if k / total_dated >= TAIL_SHARE:
        return None
    first = int(after.index.min())
    years = int(last_date.year) - first + 1
    return (f"מאז {first} נרשמו {n(k)} התקנות בלבד ({pct(k / total_dated)}) — "
            f"בממוצע {k / years:,.0f} בשנה, לעומת {n(by_year[peak])} ב-{peak} "
            f"(הנתונים עד {date_he(last_date)}).")


def insight_leader(cats, total):
    c = cats.index[0]
    share = cats.iloc[0] / total
    if share < LEADER_SHARE:
        return None
    s = f"{pct(share)} מכלי הרכב ({n(cats.iloc[0])}) הם בקטגוריית {cat_short(c)}"
    if len(cats) > 1:
        s += f"; אחריה {cat_short(cats.index[1])} — {pct(cats.iloc[1] / total)}"
    return s + "."


def insight_wave(med_dates):
    if len(med_dates) < 2:
        return None
    first, last = med_dates.index[0], med_dates.index[-1]
    gap = (med_dates.iloc[-1] - med_dates.iloc[0]).days
    if gap < WAVE_GAP_DAYS:
        return None
    return (f"הקטגוריות צוידו בגלים נפרדים: חציון מועד ההתקנה בקטגוריית {cat_short(first)} הוא "
            f"{month_he(med_dates.iloc[0])}, ובקטגוריית {cat_short(last)} — {month_he(med_dates.iloc[-1])}, "
            f"כ-{gap / 30.44:,.0f} חודשים מאוחר יותר.")


def insight_vintage(years, total_years):
    if years.empty:
        return None
    counts = years.value_counts().sort_index()
    big = counts[counts / total_years >= VINTAGE_MIN_SHARE]
    if big.empty:
        return None
    cut = int(big.index.max())
    share = counts[counts.index <= cut].sum() / total_years
    if share < VINTAGE_SHARE:
        return None
    later = int(counts[counts.index > cut].sum())
    lo = int(big.index.min())
    core = counts[(counts.index >= lo) & (counts.index <= cut)].sum() / total_years
    s = f"{pct(share)} מכלי הרכב יוצרו עד {cut} — {pct(core)} בשנים {lo} עד {cut}"
    if later:
        s += f"; רק {n(later)} יוצרו אחרי {cut}"
    return s + "."


def insight_age(age_years):
    a = age_years.dropna()
    if a.empty:
        return None
    med = float(a.median())
    if med < AGE_MIN_MEDIAN:
        return None
    old = (a >= OLD_AGE).mean()
    return (f"המסננים הותקנו בצי ותיק: הגיל החציוני בעת ההתקנה הוא {med:.1f} שנים מהרישום הראשון, "
            f"ו-{pct(old)} מכלי הרכב היו בני {OLD_AGE} שנים ומעלה.")


def insight_bulk(day_counts, total_dated):
    if day_counts.empty:
        return None
    top = day_counts.iloc[:TOP_DAYS]
    share = top.sum() / total_dated
    if share < BULK_SHARE or len(day_counts) <= TOP_DAYS:
        return None
    d0 = top.index[0]
    return (f"ההתקנות רשומות בריכוזים: ב-{TOP_DAYS} התאריכים העמוסים ביותר נרשמו {pct(share)} "
            f"מכלל ההתקנות, וביום העמוס ביותר ({date_he(d0)}) — {n(top.iloc[0])} התקנות, "
            f"מתוך {n(len(day_counts))} תאריכים שונים במאגר.")


def insight_lag(lag, total_lag):
    if total_lag == 0:
        return None
    k = int((lag >= 2).sum())
    if k / total_lag < LAG_SHARE:
        return None
    k10 = int((lag > 10).sum())
    s = (f"{n(k)} כלי רכב ({pct(k / total_lag)}) נרשמו לראשונה שנתיים ומעלה אחרי שנת הייצור שלהם")
    if k10:
        s += f", ומהם {n(k10)} יותר מ-{LRI}10{PDI} שנים אחריה"
    return s + "."


# ── compute ────────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    order = _cat_order(df["cat"])
    cats = _ranked(df["cat"])
    cats = cats.reindex(order)
    cats_ranked = _ranked(df["cat"])

    dated = df.dropna(subset=["inst"])
    total_dated = len(dated)
    first_date, last_date = dated["inst"].min(), dated["inst"].max()
    by_year = dated["inst"].dt.year.value_counts().sort_index()
    last_year = int(last_date.year)
    partial = last_date.month < 12 or last_date.day < 31
    year_lab = {y: (f"{y} (עד {MONTHS_HE[last_date.month - 1]})" if y == last_year and partial
                    else str(y)) for y in range(int(first_date.year), last_year + 1)}
    years_all = list(range(int(first_date.year), last_year + 1))

    # 1. category mix
    cat_rows = [{"name": cat_label(c), "count": n(cats[c]), "share": pct_plain(cats[c] / total)}
                for c in order]

    # 2. timeline (monthly, or quarterly once the span grows long)
    span_months = (last_date.year - first_date.year) * 12 + last_date.month - first_date.month + 1
    freq = "M" if span_months <= MONTHLY_MAX else "Q"
    per = dated["inst"].dt.to_period(freq)
    rng = pd.period_range(first_date.to_period(freq), last_date.to_period(freq), freq=freq)
    tl = per.value_counts().reindex(rng, fill_value=0)
    cum = tl.cumsum()
    if freq == "M":
        tl_x = [f"{p.month:02d}/{p.year}" for p in rng]
    else:
        tl_x = [f"Q{p.quarter}/{p.year}" for p in rng]
    peak_p = tl.sort_index().sort_values(ascending=False, kind="stable").index[0]
    timeline = {"x": tl_x, "y": [int(v) for v in tl],
                "cum": [round(float(v) / total_dated * 100, 1) for v in cum]}

    # 3. year × category
    yc = pd.crosstab(dated["inst"].dt.year, dated["cat"]).reindex(index=years_all, columns=order,
                                                                  fill_value=0)
    year_cat = {"x": [str(y) for y in years_all],
                "series": [{"name": c, "data": [int(v) for v in yc[c]]} for c in order]}
    year_rows = [{"name": year_lab[y], "total": n(yc.loc[y].sum()),
                  "cols": [n(yc.loc[y, c]) for c in order]} for y in years_all]

    # 4. per-category cumulative wave (categories with >= MIN_CAT vehicles)
    wave_cats = [c for c in order if cats[c] >= MIN_CAT]
    wave_series = []
    for c in wave_cats:
        s = per[dated["cat"] == c].value_counts().reindex(rng, fill_value=0).cumsum()
        wave_series.append({"name": c, "data": [round(float(v) / s.iloc[-1] * 100, 1) for v in s]})
    wave = {"x": tl_x, "series": wave_series}
    med = dated[dated["cat"].isin(wave_cats)].groupby("cat")["inst"].median()
    med = med.reindex(wave_cats).sort_index().sort_values(kind="stable")
    med = med.dt.normalize()
    small_cats = [c for c in order if cats[c] < MIN_CAT]

    # 5. manufacture year × category
    yr = df.dropna(subset=["year"]).copy()
    yr["year"] = yr["year"].astype(int)
    min_y, max_y = int(yr["year"].min()), int(yr["year"].max())
    yc_counts = yr["year"].value_counts()
    dense = yc_counts[yc_counts / len(yr) >= VINTAGE_MIN_SHARE]
    top_y = min(max_y, int(dense.index.max()) + 1) if len(dense) else max_y
    after_lab = f"אחרי {top_y}"

    def ylab(y):
        if y < YEAR_FROM:
            return f"לפני {YEAR_FROM}"
        return after_lab if y > top_y else str(y)
    yr["ylab"] = yr["year"].map(ylab)
    year_keys = ([f"לפני {YEAR_FROM}"] if min_y < YEAR_FROM else []) + \
        [str(y) for y in range(max(YEAR_FROM, min_y), top_y + 1)] + \
        ([after_lab] if max_y > top_y else [])
    my = pd.crosstab(yr["ylab"], yr["cat"]).reindex(index=year_keys, columns=order, fill_value=0)
    make_year = {"x": year_keys,
                 "series": [{"name": c, "data": [int(v) for v in my[c]]} for c in order]}
    med_year = int(yr["year"].median())

    # 6. age at installation (years since first registration)
    age = (df["inst"] - df["reg"]).dt.days / 365.25
    age = age.where(age >= 0)
    box_cats = [c for c in order if age[df["cat"] == c].notna().sum() >= MIN_CAT]
    box, box_rows = [], []
    for c in box_cats:
        a = age[df["cat"] == c].dropna()
        q = [round(float(a.quantile(p)), 1) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box.append(q)
        box_rows.append({"name": cat_label(c), "n": n(len(a)), "q5": f"{q[0]:.1f}",
                         "q1": f"{q[1]:.1f}", "med": f"{q[2]:.1f}", "q3": f"{q[3]:.1f}",
                         "q95": f"{q[4]:.1f}"})
    a_all = age.dropna()
    med_age = float(a_all.median()) if len(a_all) else None
    bucket_labels, bucket_vals = [], []
    for lo, hi in AGE_BUCKETS:
        m = a_all >= lo
        if hi is not None:
            m &= a_all < hi
        bucket_labels.append(f"{lo} ומעלה" if hi is None else f"{lo} עד {hi}")
        bucket_vals.append(int(m.sum()))

    # 7. registration lag vs manufacture year
    lag = (df["reg"].dt.year - df["year"]).dropna().astype(int)
    lag_rows, lag_vals, lag_names = [], [], []
    for lo, hi, lab in LAG_BUCKETS:
        m = pd.Series(True, index=lag.index)
        if lo is not None:
            m &= lag >= lo
        if hi is not None:
            m &= lag <= hi
        k = int(m.sum())
        lag_names.append(lab)
        lag_vals.append(k)
        lag_rows.append({"name": lab, "count": n(k),
                         "share": pct_plain(k / len(lag)) if len(lag) else "0.0%"})

    # 8. weekday (Sunday first)
    wd = ((dated["inst"].dt.dayofweek + 1) % 7).value_counts().reindex(range(7), fill_value=0)
    weekday = {"names": WEEKDAYS_HE, "values": [int(v) for v in wd]}
    wd_rows = [{"name": WEEKDAYS_HE[i], "count": n(wd[i]),
                "share": pct_plain(wd[i] / total_dated)} for i in range(7)]
    wd_top = int(wd.sort_index().sort_values(ascending=False, kind="stable").index[0])

    # 9. busiest days
    days = dated["inst"].dt.normalize().value_counts()
    days = days.sort_index().sort_values(ascending=False, kind="stable")
    top_days = days.iloc[:TOP_DAYS]
    day_cat = pd.crosstab(dated["inst"].dt.normalize(), dated["cat"])
    days_rows = []
    for d, k in top_days.items():
        row = day_cat.loc[d]
        main = row.sort_index().sort_values(ascending=False, kind="stable").index[0]
        days_rows.append({"name": date_he(d), "count": n(k), "share": pct_plain(k / total_dated),
                          "cat": cat_label(main), "cat_share": pct_plain(row[main] / k)})
    days_chart = {"names": [date_he(d) for d in top_days.index],
                  "values": [int(v) for v in top_days]}

    rules = [
        ("peak", insight_peak(by_year, total_dated)),
        ("tail", insight_tail(by_year, total_dated, last_date)),
        ("leader", insight_leader(cats_ranked, total)),
        ("wave", insight_wave(med)),
        ("vintage", insight_vintage(yr["year"], len(yr))),
        ("age", insight_age(age)),
        ("bulk", insight_bulk(days, total_dated)),
        ("lag", insight_lag(lag, len(lag))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    peak_year = int(by_year.sort_index().sort_values(ascending=False, kind="stable").index[0])
    peak_share = by_year[peak_year] / total_dated
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "peak": {"value": round(peak_share * 100, 1), "display": f"{peak_share * 100:.1f}%",
                 "tone": "info" if peak_share >= PEAK_SHARE else "brand"},
        "age": {"value": round(med_age, 1) if med_age is not None else None,
                "display": f"{med_age:.1f}" if med_age is not None else "—",
                "tone": ("warn" if med_age is not None and med_age >= 15 else "brand")},
        "vintage": {"value": med_year, "display": str(med_year), "tone": "brand"},
    }

    gran = "חודש" if freq == "M" else "רבעון"
    small_note = (f" קטגוריות עם פחות מ-{MIN_CAT} כלי רכב ({', '.join(small_cats)}) אינן מוצגות."
                  if small_cats else "")
    peak_p_lab = (month_he(peak_p.to_timestamp()) if freq == "M"
                  else f"רבעון {peak_p.quarter} של {peak_p.year}")
    top_wd_share = wd[wd_top] / total_dated if total_dated else 0
    labels = {
        "lede": (f"{n(total)} כלי רכב שבהם הותקן מסנן לצמצום פליטת מזהמים, לפי קטגוריית הרכב "
                 f"האירופית, שנת הייצור, מועד הרישום הראשון ומועד התקנת המסנן. ההתקנות במאגר "
                 f"נפרשות מ-{date_he(first_date)} עד {date_he(last_date)}; "
                 f"{pct(peak_share)} מהן בוצעו ב-{peak_year}. הקטגוריה הגדולה היא "
                 f"{cat_short(cats_ranked.index[0])}, ושנת הייצור החציונית היא {med_year}."),
        "total_kpi": "כלי רכב עם מסנן מותקן",
        "q5_head": "אחוזון 5",
        "q95_head": "אחוזון 95",
        "peak_kpi": f"מההתקנות בוצעו ב-{peak_year}",
        "age_kpi": "גיל חציוני בהתקנה (שנים מהרישום הראשון)",
        "vintage_kpi": "שנת ייצור חציונית",
        "cats_note": (f"מספר כלי הרכב בכל קטגוריה אירופית (M — נוסעים, N — משא). "
                      f"הקטגוריה {cat_short(cats_ranked.index[0])} מהווה {pct(cats_ranked.iloc[0] / total)} "
                      f"מהמאגר."),
        "cats_aria": f"תרשים עמודות: {n(total)} כלי רכב לפי קטגוריה אירופית.",
        "tl_note": (f"מספר ההתקנות בכל {gran}, והקו — השיעור המצטבר מכלל ההתקנות. "
                    f"ה{gran} העמוס ביותר: {peak_p_lab}, עם {n(tl[peak_p])} התקנות. "
                    f"אפשר לגרור את הסרגל שבתחתית כדי להתמקד בטווח."),
        "tl_aria": f"תרשים עמודות וקו: התקנות מסננים לפי {gran}, {date_he(first_date)} עד "
                   f"{date_he(last_date)}.",
        "yc_note": (f"התקנות בכל שנה לפי קטגוריית רכב." +
                    (f" השנה {last_year} חלקית — הנתונים עד {date_he(last_date)}." if partial else "")),
        "yc_aria": "תרשים עמודות מוערמות: התקנות לפי שנה וקטגוריית רכב.",
        "yc_caption": "מספר התקנות לפי שנה וקטגוריית רכב.",
        "wave_note": (f"לכל קטגוריה — איזה חלק מכלי הרכב שלה כבר צויד במסנן בכל {gran}. "
                      f"קו שמטפס מוקדם מסמן קטגוריה שצוידה ראשונה.{small_note}"),
        "wave_aria": "תרשים קווים: שיעור מצטבר של כלי רכב שצוידו במסנן, לפי קטגוריה.",
        "my_note": (f"כלי הרכב לפי שנת הייצור וקטגוריה (כלי רכב שיוצרו לפני {YEAR_FROM} מקובצים "
                    f"יחד" + (f", וכך גם כלי הרכב שיוצרו אחרי {top_y} ({n((yr['year'] > top_y).sum())})"
                              if max_y > top_y else "") + f"). שנת הייצור החציונית: {med_year}."),
        "my_aria": "תרשים עמודות מוערמות: כלי רכב לפי שנת ייצור וקטגוריה.",
        "age_note": (f"הזמן שעבר מהרישום הראשון ועד התקנת המסנן, בשנים: הקופסה — הרבעון התחתון "
                     f"עד העליון, הקו — החציון, והשפמים — אחוזון 5 עד 95.{small_note}"),
        "age_aria": "תרשים קופסה: גיל כלי הרכב בעת התקנת המסנן לפי קטגוריה.",
        "agehist_note": ("התפלגות גיל כלי הרכב בעת ההתקנה (שנים מהרישום הראשון) בכלל המאגר."
                         + (f" חציון: {med_age:.1f} שנים." if med_age is not None else "")),
        "agehist_aria": "תרשים עמודות: כלי רכב לפי גיל בעת התקנת המסנן.",
        "agehist_caption": "מספר כלי רכב לפי טווח גיל בעת ההתקנה.",
        "lag_note": ("ההפרש בין שנת הרישום הראשון לשנת הייצור. רישום בשנה שלפני שנת הייצור "
                     "נפוץ כששנת הדגם מוקדמת לשנה הקלנדרית; פער גדול מסמן כלי רכב שעלו לכביש "
                     "שנים אחרי ייצורם."),
        "lag_aria": "תרשים עמודות: כלי רכב לפי הפער בין שנת הייצור לרישום הראשון.",
        "wd_note": (f"התקנות לפי יום בשבוע. יום {WEEKDAYS_HE[wd_top]} הוא העמוס ביותר, עם "
                    f"{pct(top_wd_share)} מההתקנות."),
        "wd_aria": "תרשים עמודות: התקנות לפי יום בשבוע.",
        "days_note": (f"{TOP_DAYS} התאריכים שבהם נרשמו הכי הרבה התקנות. ריכוז גדול ביום אחד "
                      f"מרמז על רישום מרוכז של התקנות ולא בהכרח על התקנה באותו יום."),
        "days_aria": f"תרשים עמודות: {TOP_DAYS} התאריכים עם מספר ההתקנות הגבוה ביותר.",
    }

    tables = {
        "cats": cat_rows,
        "year_cat": year_rows,
        "cat_cols": order,
        "box": box_rows,
        "agehist": [{"name": lab, "count": n(v),
                     "share": pct_plain(v / len(a_all)) if len(a_all) else "0.0%"}
                    for lab, v in zip(bucket_labels, bucket_vals)],
        "lag": lag_rows,
        "weekday": wd_rows,
        "days": days_rows,
    }

    charts = {
        "cats": {"names": [cat_label(c) for c in order], "values": [int(cats[c]) for c in order]},
        "timeline": timeline,
        "year_cat": year_cat,
        "wave": wave,
        "make_year": make_year,
        "box": {"names": box_cats, "data": box},
        "agehist": {"names": [f"{LRI}{lo}+{PDI}" if hi is None else f"{LRI}{lo}–{hi}{PDI}"
                              for lo, hi in AGE_BUCKETS], "values": bucket_vals},
        "lag": {"names": lag_names, "values": lag_vals},
        "weekday": weekday,
        "days": days_chart,
    }

    return {
        "agent_data": {
            "summary_he": (f"{n(total)} כלי רכב שבהם הותקן מסנן לצמצום פליטת מזהמים: "
                           f"{pct(cats_ranked.iloc[0] / total)} מהם בקטגוריית {cat_short(cats_ranked.index[0])}, "
                           f"שנת ייצור חציונית {med_year}, ו-{pct(peak_share)} מההתקנות בוצעו "
                           f"ב-{peak_year}."),
            "dataset_kind": "timeseries",
            "related_ids": ["6b991a56-c209-4b02-a52e-ba1c69091a4c",
                            "5877dcf0-1895-4f35-b87b-c85a0b286318",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4"],
            "suggested_tags": ["כלי רכב", "זיהום אוויר", "מסנני חלקיקים", "פליטות",
                               "משאיות", "אוטובוסים", "תחבורה"],
            "temporal_coverage": f"{first_date.year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
